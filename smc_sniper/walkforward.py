"""Phase 11 -- Walk-forward, splits, and anti-overfitting checks.

The protocol, and why each piece is here:

* **Chronological split** into TRAIN / VALIDATION / TEST. Results are always
  reported separately. A strategy that only works in-sample is not a strategy.
* **Pair selection on TRAIN only.** Choosing pairs on the full window is
  overfitting -- it has happened in this repo. The selection made on TRAIN is
  frozen and applied unchanged to TEST.
* **Rolling walk-forward folds**: fit window -> immediately following
  out-of-sample window, repeated across the series.
* **Perturbation checks**: nudge each key parameter and confirm the result does
  not collapse. A result that only survives at one exact threshold is a fit.
* **Matched-R control**: the same entries evaluated at a range of fixed R:R
  targets. If a headline win rate comes from shrinking the target rather than
  from real edge, the R-sweep exposes it -- win rate must fall as R rises and
  expectancy must not depend on one convenient target.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import trades_to_frame
from .metrics import breakdown, compute_metrics


def split_window(start: pd.Timestamp, end: pd.Timestamp,
                 fractions=(0.5, 0.2, 0.3)) -> dict:
    """Chronological TRAIN / VALIDATION / TEST boundaries."""
    total = (end - start).total_seconds()
    t1 = start + pd.Timedelta(seconds=total * fractions[0])
    t2 = t1 + pd.Timedelta(seconds=total * fractions[1])
    return {"train": (start, t1), "validation": (t1, t2), "test": (t2, end)}


def data_window(contexts) -> tuple[pd.Timestamp, pd.Timestamp]:
    starts, ends = [], []
    for ctx in contexts.values():
        starts.append(ctx.setup.index[0])
        ends.append(ctx.setup.index[-1])
    return min(starts), max(ends)


def run_splits(bt, contexts, fractions=(0.5, 0.2, 0.3),
               starting_balance: float = 10000.0) -> dict:
    """Backtest each chronological split independently."""
    start, end = data_window(contexts)
    bounds = split_window(start, end, fractions)
    out = {"bounds": {k: (str(v[0]), str(v[1])) for k, v in bounds.items()}}
    for name, (a, b) in bounds.items():
        trades, _, _ = bt.run(contexts=contexts, start=a, end=b,
                              collect_rejections=False)
        frame = trades_to_frame(trades)
        out[name] = {"metrics": compute_metrics(frame, starting_balance),
                     "trades": frame}
    return out


def select_pairs_on_train(train_trades: pd.DataFrame, cfg) -> list[str]:
    """Pick pairs using TRAIN ONLY. The choice is then frozen for TEST."""
    pcfg = cfg.get("backtest.pair_selection", {}) or {}
    if not pcfg.get("enabled", True) or train_trades is None or train_trades.empty:
        return list(cfg.symbols)
    min_trades = int(pcfg.get("min_trades", 12))
    metric = pcfg.get("metric", "expectancy_r")
    floor = float(pcfg.get("min_metric", 0.0))
    table = breakdown(train_trades, "symbol")
    if table.empty:
        return list(cfg.symbols)
    keep = table[(table["trades"] >= min_trades) & (table[metric] > floor)]
    return keep["symbol"].tolist()


def walk_forward(bt, contexts, folds: int = 5, train_frac: float = 0.5,
                 anchored: bool = False, starting_balance: float = 10000.0) -> dict:
    """Rolling fit -> out-of-sample evaluation.

    Each fold selects pairs on its own fit window and scores those pairs on the
    immediately following, never-seen window. Only the out-of-sample slices are
    concatenated into the headline walk-forward result.
    """
    start, end = data_window(contexts)
    total = (end - start).total_seconds()
    step = total / (folds + 1)
    rows = []
    oos_frames = []

    for k in range(folds):
        if anchored:
            fit_a = start
        else:
            fit_a = start + pd.Timedelta(seconds=step * k)
        fit_b = start + pd.Timedelta(seconds=step * (k + 1))
        oos_b = start + pd.Timedelta(seconds=step * (k + 2))

        fit_trades, _, _ = bt.run(contexts=contexts, start=fit_a, end=fit_b,
                                  collect_rejections=False)
        fit_frame = trades_to_frame(fit_trades)
        chosen = select_pairs_on_train(fit_frame, bt.cfg)

        oos_trades, _, _ = bt.run(contexts=contexts, start=fit_b, end=oos_b,
                                  collect_rejections=False, allowed_symbols=chosen)
        oos_frame = trades_to_frame(oos_trades)
        if not oos_frame.empty:
            oos_frame = oos_frame.copy()
            oos_frame["fold"] = k + 1
            oos_frames.append(oos_frame)

        fm = compute_metrics(fit_frame, starting_balance)
        om = compute_metrics(oos_frame, starting_balance)
        rows.append({
            "fold": k + 1,
            "fit_start": str(fit_a)[:10], "fit_end": str(fit_b)[:10],
            "oos_end": str(oos_b)[:10],
            "pairs_selected": ",".join(chosen) if chosen else "(none)",
            "fit_trades": fm["trades"], "fit_wr": round(fm["win_rate"], 2),
            "fit_pf": round(fm["profit_factor"], 3),
            "fit_exp_r": round(fm["expectancy_r"], 4),
            "oos_trades": om["trades"], "oos_wr": round(om["win_rate"], 2),
            "oos_pf": round(om["profit_factor"], 3),
            "oos_exp_r": round(om["expectancy_r"], 4),
        })

    combined = pd.concat(oos_frames, ignore_index=True) if oos_frames else pd.DataFrame()
    return {"folds": pd.DataFrame(rows), "oos_trades": combined,
            "oos_metrics": compute_metrics(combined, starting_balance)}


def perturbation_check(make_bt, contexts, cfg, params: dict,
                       starting_balance: float = 10000.0) -> pd.DataFrame:
    """Re-run with each parameter nudged. Robust edges survive small changes."""
    rows = []
    for dotted, values in params.items():
        for value in values:
            variant = cfg.with_override(dotted, value)
            bt = make_bt(variant)
            trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
            m = compute_metrics(trades_to_frame(trades), starting_balance)
            rows.append({"param": dotted, "value": value, "trades": m["trades"],
                         "win_rate": round(m["win_rate"], 2),
                         "profit_factor": round(m["profit_factor"], 3),
                         "expectancy_r": round(m["expectancy_r"], 4),
                         "total_r": round(m["total_r"], 2)})
    return pd.DataFrame(rows)


def matched_r_control(make_bt, contexts, cfg, r_values=(1.0, 1.5, 2.0, 2.5, 3.0, 4.0),
                      starting_balance: float = 10000.0) -> pd.DataFrame:
    """The anti-TP-shrinking control.

    Same entry logic, management stripped off, one flat target at each R. If a
    strategy's win rate comes from a small target rather than from edge, this
    table shows it immediately: win rate falls steeply with R while expectancy
    stays flat or negative at every R.
    """
    rows = []
    for rr in r_values:
        variant = cfg.copy()
        variant.set("targets.mode", "fixed_rr")
        variant.set("targets.fixed_rr", float(rr))
        variant.set("targets.min_rr", float(min(rr, 2.0)))
        variant.set("targets.partial_tp.enabled", False)
        variant.set("targets.breakeven.enabled", False)
        variant.set("targets.trailing.enabled", False)
        bt = make_bt(variant)
        trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
        m = compute_metrics(trades_to_frame(trades), starting_balance)
        rows.append({"fixed_rr": rr, "trades": m["trades"],
                     "win_rate": round(m["win_rate"], 2),
                     "profit_factor": round(m["profit_factor"], 3),
                     "expectancy_r": round(m["expectancy_r"], 4),
                     "total_r": round(m["total_r"], 2),
                     "breakeven_wr_needed": round(100.0 / (1.0 + rr), 2)})
    return pd.DataFrame(rows)
