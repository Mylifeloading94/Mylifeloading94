"""Rolling walk-forward: optimise on train, record the UNSEEN test block."""
from __future__ import annotations

import pandas as pd

from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.config import Config
from xauusd_bot.optimization.objective import score as obj_score
from xauusd_bot.optimization.splits import walk_forward_windows
from xauusd_bot.pipeline import run


class _Prep:
    def __init__(self, F): self.F = F; self.m1 = None


def run_walk_forward(F: pd.DataFrame, base: Config, grid: list[dict], news=None,
                     train_days=75, test_days=25, equity0=500.0, verbose=True):
    windows = walk_forward_windows(F.index, train_days, test_days)
    rows = []
    for wi, ((a, b), (c, d)) in enumerate(windows, 1):
        tr = F.loc[(F.index >= a) & (F.index < b)]
        te = F.loc[(F.index >= c) & (F.index < d)]
        if len(tr) < 5000 or len(te) < 2000:
            continue
        best, best_s, best_m = None, -1e9, None
        for params in grid:
            cfg = base.with_overrides(**params); cfg.initial_equity = equity0
            res, _ = run(_Prep(tr), cfg, news, equity0)
            m = compute(res.trades, res.equity, equity0)
            s = obj_score(m, min_trades=15)
            if s > best_s:
                best, best_s, best_m = params, s, m
        cfg = base.with_overrides(**best); cfg.initial_equity = equity0
        res, _ = run(_Prep(te), cfg, news, equity0)
        mt = compute(res.trades, res.equity, equity0)
        rows.append({
            "window": wi, "train": f"{a.date()}->{b.date()}", "test": f"{c.date()}->{d.date()}",
            "params": best,
            "is_trades": best_m["trades"], "is_pf": round(min(best_m["profit_factor"], 99.0), 2),
            "is_wr": round(best_m["win_rate"], 1),
            "oos_trades": mt["trades"], "oos_pf": round(min(mt["profit_factor"], 99.0), 2),
            "oos_wr": round(mt["win_rate"], 1), "oos_ret": round(mt["net_return_pct"], 2),
            "oos_dd": round(mt["max_dd_pct"], 2), "oos_exp_r": round(mt["expectancy_r"], 3),
        })
        if verbose:
            r = rows[-1]
            print(f"  WF{wi}: train {r['train']} (n={r['is_trades']}, PF {r['is_pf']}) "
                  f"-> test {r['test']} n={r['oos_trades']} PF {r['oos_pf']} "
                  f"ret {r['oos_ret']:+.2f}% expR {r['oos_exp_r']:+.3f}")
    return pd.DataFrame(rows)


def stability(wf: pd.DataFrame) -> dict:
    if wf.empty:
        return {"windows": 0}
    prof = (wf["oos_pf"] > 1.0)
    return {
        "windows": len(wf),
        "profitable_windows": int(prof.sum()),
        "pct_profitable": round(100 * prof.mean(), 1),
        # a no-loss window is capped at 5 so one lucky window cannot
        # dominate the mean; the median is the honest summary either way
        "mean_oos_pf": round(wf["oos_pf"].clip(upper=5.0).mean(), 2),
        "median_oos_pf": round(wf["oos_pf"].clip(upper=5.0).median(), 2),
        "mean_oos_expR": round(wf["oos_exp_r"].mean(), 3),
        "worst_oos_ret": round(wf["oos_ret"].min(), 2),
        "total_oos_trades": int(wf["oos_trades"].sum()),
        "param_stability": _param_stability(wf),
    }


def _param_stability(wf: pd.DataFrame) -> dict:
    keys = set().union(*[set(p) for p in wf["params"]]) if len(wf) else set()
    out = {}
    for k in keys:
        vals = [p.get(k) for p in wf["params"]]
        uniq = len(set(map(str, vals)))
        out[k] = {"values": vals, "distinct": uniq,
                  "stable": uniq <= max(1, len(vals) // 2)}
    return out
