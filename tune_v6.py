#!/usr/bin/env python3
"""SMC Sniper v6 -- resolving the cooldown lead, and the loss-side audit.

v5 left one open finding worth chasing: removing the duplicate-setup cooldown
improved TRAIN, VALIDATION and TEST, added 60% more trades and LOWERED drawdown
-- the only change to do all four -- but 87 of its 231 trades are same-pair,
same-direction re-entries inside 24 hours, and once the cluster bootstrap prices
that correlation the interval falls back across zero.

v6 tests the middle ground. Rather than "all re-entries" or "no re-entries",
allow a re-entry only when it represents something genuinely new:

  * ``dedupe.max_signals_per_sweep`` -- re-enter only once a NEW liquidity
    sweep has formed. The sweep's bar index is its identity, so this is a
    structural rule, not a clock. This is the hypothesis with a mechanism
    behind it: a second entry off the SAME sweep is the same bet; a second
    entry off a new sweep is a new one.
  * ``dedupe.cooldown_hours`` -- a wall-clock cooldown, the blunter version.

The bar to clear is the honest one, stated in advance: better on TRAIN **and**
TEST independently, and priced with the CLUSTER bootstrap with the spec's
concurrency caps ENFORCED. Anything scored any other way is not adopted.

    python3 tune_v6.py --round dedupe    # the middle ground
    python3 tune_v6.py --round rr        # 5R / 6R on the v5 config
    python3 tune_v6.py --round loss      # where the losses actually are
    python3 tune_v6.py --round final     # splits + walk-forward + perturbation

Results land in ``reports/v6/``.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tune_v5 import (FRACTIONS, apply, bounds, cluster_bootstrap, cluster_ids,
                     evaluate, load_env, show)
from smc_sniper import walkforward
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.metrics import compute_metrics, expectancy_ci

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v6")
os.makedirs(OUT, exist_ok=True)

# The v5 adopted configuration, expressed as overrides on a context already
# built with the causal (lookahead-free) order-block association.
V5 = {
    "risk.quote_ccy_conversion": True,
    "risk.book_on_exit": True,
    "execution.tp_trade_through": True,
    "entry.exact_expiry": True,
    "targets.mode": "fixed_rr",
    "targets.fixed_rr": 4.0,
    "targets.min_rr": 2.0,
    "targets.min_rr_on_liquidity": True,
    "targets.partial_tp.enabled": False,
    "targets.breakeven.enabled": False,
    "targets.trailing.enabled": False,
    "dedupe.enabled": False,
    "risk.enforce_concurrency": True,
}
CTX = {"order_blocks.causal_structure_association": True}


def env():
    return load_env("swing", "tradelocker", CTX, "_causal")


def priced(cfg, engine, contexts, over, name, splits=None):
    """One variant scored on TRAIN/TEST *and* priced with the cluster bootstrap.

    The cluster interval is computed here rather than reported separately
    because the whole point of v6 is that a variant which improves both splits
    but does so by taking more bets on the same event has not improved anything.
    """
    row, frames = evaluate(cfg, engine, contexts, over, name, splits=splits)
    full = frames["full"]
    if len(full) >= 30:
        lo, hi = expectancy_ci(full, 5000)
        clo, chi, n_c = cluster_bootstrap(full, 5000)
        row.update({"ci_lo": round(lo, 4), "ci_hi": round(hi, 4),
                    "clusters": n_c,
                    "ccl_lo": round(clo, 4), "ccl_hi": round(chi, 4),
                    "cluster_clears": "YES" if not (clo < 0 < chi) else "no"})
        f = cluster_ids(full)
        sizes = f.groupby("cluster").size()
        row["clustered_trades"] = int((sizes[sizes > 1]).sum())
    return row, frames


PCOLS = ["variant", "n", "per_day", "wr", "pf", "exp", "train_n", "train_exp",
         "test_n", "test_exp", "max_dd", "max_loss_streak", "clusters",
         "clustered_trades", "ci_lo", "ci_hi", "ccl_lo", "ccl_hi",
         "cluster_clears"]


# ---------------------------------------------------------------------------
# Round 1 -- partial deduplication
# ---------------------------------------------------------------------------
def round_dedupe():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    variants = {
        "v5 shipped (dedupe OFF)": {},
        "cooldown 8 bars (v2 default)": {"dedupe.enabled": True},
        "cooldown 2 bars": {"dedupe.enabled": True, "dedupe.cooldown_bars": 2},
        "1 signal per sweep": {"dedupe.max_signals_per_sweep": 1},
        "2 signals per sweep": {"dedupe.max_signals_per_sweep": 2},
        "3 signals per sweep": {"dedupe.max_signals_per_sweep": 3},
        "cooldown 6h": {"dedupe.cooldown_hours": 6},
        "cooldown 12h": {"dedupe.cooldown_hours": 12},
        "cooldown 24h": {"dedupe.cooldown_hours": 24},
        "cooldown 48h": {"dedupe.cooldown_hours": 48},
        "1/sweep + 12h": {"dedupe.max_signals_per_sweep": 1,
                          "dedupe.cooldown_hours": 12},
        "2/sweep + 6h": {"dedupe.max_signals_per_sweep": 2,
                         "dedupe.cooldown_hours": 6},
    }
    rows = []
    for label, over in variants.items():
        merged = dict(V5)
        merged.update(over)
        row, _ = priced(cfg, engine, contexts, merged, label, splits=sp)
        rows.append(row)
        show([row], PCOLS)
    print("\n=== V6 ROUND 1: PARTIAL DEDUPLICATION ===")
    return show(rows, PCOLS, name="v6_dedupe")


# ---------------------------------------------------------------------------
# Round 2 -- target geometry beyond 4R, on the v5 config
# ---------------------------------------------------------------------------
def round_rr():
    """5R and 6R on the ADOPTED config, entry-matched.

    v5's reward-to-risk frontier was measured on the dedupe-ON ladder baseline.
    The adopted configuration has the cooldown off and the concurrency caps on,
    which is a different trade population, so the frontier has to be re-measured
    on it rather than carried over. `min_rr_on_liquidity` stays TRUE in every
    row -- that is audit defect 7, and it is what makes the rows entry-matched.
    """
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    rows = []
    for rr in (2.0, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 8.0):
        over = dict(V5)
        over["targets.fixed_rr"] = rr
        row, frames = priced(cfg, engine, contexts, over, f"flat {rr}R", splits=sp)
        row["breakeven_wr"] = round(100.0 / (1.0 + rr), 2)
        row["clears_by"] = round(row["wr"] - row["breakeven_wr"], 2)
        f = frames["full"]
        row["avg_win_r"] = round(float(f.loc[f.r_multiple > 0, "r_multiple"].mean()), 3)
        rows.append(row)
        show([row], PCOLS + ["breakeven_wr", "clears_by", "avg_win_r"])
    print("\n=== V6 ROUND 2: TARGET GEOMETRY ON THE ADOPTED CONFIG ===")
    return show(rows, PCOLS + ["breakeven_wr", "clears_by", "avg_win_r"],
                name="v6_rr")


# ---------------------------------------------------------------------------
# Round 3 -- where the losses actually are
# ---------------------------------------------------------------------------
def round_loss():
    """Diagnose the losing side on the ADOPTED ledger, split TRAIN vs TEST.

    v2's session-extreme filter is the only filter in this repo's history that
    held on both splits, and it came out of exactly this kind of cut. The rule
    here: a property is only worth a filter if it points the SAME way on TRAIN
    and on TEST. Anything visible on the full window alone is a story.
    """
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    variant = apply(cfg, V5)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
    full = trades_to_frame(trades)
    full["signal_time"] = pd.to_datetime(full["signal_time"], utc=True)
    full["hour"] = full["signal_time"].dt.hour
    full["dow"] = full["signal_time"].dt.day_name()
    (tr_a, tr_b), (te_a, te_b) = sp["train"], sp["test"]
    full["split"] = np.where(full.signal_time < tr_b, "train",
                             np.where(full.signal_time >= te_a, "test", "val"))
    full.to_csv(os.path.join(OUT, "v6_adopted_ledger.csv"), index=False)

    def cut(col, min_n=12):
        rows = []
        for key, g in full.groupby(col):
            if len(g) < min_n:
                continue
            gt, ge = g[g.split == "train"], g[g.split == "test"]
            rows.append({
                col: key, "n": len(g),
                "wr": round((g.r_multiple > 0).mean() * 100, 2),
                "exp": round(g.r_multiple.mean(), 4),
                "train_n": len(gt),
                "train_exp": round(gt.r_multiple.mean(), 4) if len(gt) else np.nan,
                "test_n": len(ge),
                "test_exp": round(ge.r_multiple.mean(), 4) if len(ge) else np.nan,
            })
        frame = pd.DataFrame(rows).sort_values("exp")
        # A cut is only actionable if TRAIN and TEST agree on its sign.
        frame["both_splits_agree"] = np.where(
            frame.train_exp.notna() & frame.test_exp.notna()
            & (np.sign(frame.train_exp) == np.sign(frame.test_exp)),
            np.where(frame.train_exp < 0, "BOTH NEGATIVE", "both positive"), "")
        print(f"\n--- by {col} (n>={min_n}) ---")
        print(frame.to_string(index=False), flush=True)
        frame.to_csv(os.path.join(OUT, f"v6_loss_by_{col}.csv"), index=False)
        return frame

    for col in ("symbol", "session", "hour", "direction", "liquidity_type",
                "zone_kind", "setup_type", "dow", "exit_reason"):
        cut(col)

    # Continuous properties: does the loser look different from the winner?
    print("\n--- continuous properties, winners vs losers ---")
    full["won"] = full.r_multiple > 0
    cont = [c for c in ("score", "mae_r", "mfe_r", "bars_held", "rr_tp2")
            if c in full.columns]
    print(full.groupby("won")[cont].mean().round(3).to_string())

    # Distance of entry into the move, and stop size in ATR -- the two
    # properties a "chasing" failure mode would show up in.
    full["stop_atr"] = (full["entry"] - full["stop"]).abs()
    print("\n--- MFE distribution of losers (how close did they get?) ---")
    losers = full[~full.won]
    print(losers["mfe_r"].describe().round(3).to_string())
    print(f"  losers that never got beyond +0.5R: "
          f"{(losers.mfe_r < 0.5).mean() * 100:.1f}%")
    print(f"  losers that got past +2R and still lost: "
          f"{(losers.mfe_r > 2.0).mean() * 100:.1f}%  "
          f"({int((losers.mfe_r > 2.0).sum())} trades)")
    return full


# ---------------------------------------------------------------------------
# Round 4 -- freeze whatever survived, and walk it forward
# ---------------------------------------------------------------------------
def round_final(extra=None):
    cfg, engine, contexts = env()
    over = dict(V5)
    over.update(extra or {})
    variant = apply(cfg, over)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
    f = trades_to_frame(trades)
    m = compute_metrics(f, 10000.0)
    lo, hi = expectancy_ci(f, 5000)
    clo, chi, n_c = cluster_bootstrap(f, 5000)
    span = (pd.to_datetime(f.exit_time).max() - pd.to_datetime(f.signal_time).min()).days
    print(f"\n=== FROZEN CONFIG {extra or '(v5 shipped)'} ===")
    print(f"  trades {m['trades']}  clusters {n_c}  per_day {m['trades']/span:.3f}")
    print(f"  WR {m['win_rate']:.2f}%  PF {m['profit_factor']:.3f}  "
          f"E {m['expectancy_r']:+.4f}R  maxDD {m['max_drawdown_pct']:.2f}%  "
          f"streak {m['max_consecutive_losses']}")
    print(f"  naive   CI [{lo:+.4f}, {hi:+.4f}]  "
          f"{'SPANS ZERO' if lo < 0 < hi else 'clear of zero'}")
    print(f"  CLUSTER CI [{clo:+.4f}, {chi:+.4f}]  "
          f"{'SPANS ZERO' if clo < 0 < chi else 'CLEAR OF ZERO'}")
    res = walkforward.run_splits(bt, contexts, FRACTIONS, 10000.0)
    for split in ("train", "validation", "test"):
        mm = res[split]["metrics"]
        print(f"    {split:11s} n={mm['trades']:4d}  WR {mm['win_rate']:6.2f}%  "
              f"PF {mm['profit_factor']:6.3f}  E {mm['expectancy_r']:+.4f}R")
    wf = walkforward.walk_forward(bt, contexts, folds=5, train_frac=0.5, anchored=False)
    oos, om = wf["oos_trades"], wf["oos_metrics"]
    olo, ohi = expectancy_ci(oos, 5000)
    oclo, ochi, onc = cluster_bootstrap(oos, 5000)
    print(f"  WALK-FORWARD OOS n={om['trades']} ({onc} clusters)  "
          f"WR {om['win_rate']:.2f}%  PF {om['profit_factor']:.3f}  "
          f"E {om['expectancy_r']:+.4f}R")
    print(f"    naive   CI [{olo:+.4f}, {ohi:+.4f}]")
    print(f"    CLUSTER CI [{oclo:+.4f}, {ochi:+.4f}]  "
          f"{'SPANS ZERO' if oclo < 0 < ochi else 'CLEAR OF ZERO'}")
    return f


def round_perturb(extra=None):
    """Robustness: nudge the parameters that were not selected and re-score."""
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    base = dict(V5)
    base.update(extra or {})
    tweaks = {
        "baseline": {},
        "score gate 78": {"scoring.profiles.standard": 78},
        "score gate 82": {"scoring.profiles.standard": 82},
        "stop buffer 0.20": {"stops.buffer_atr": 0.20},
        "stop buffer 0.30": {"stops.buffer_atr": 0.30},
        "fill depth 0.45": {"fvg.entry_fill_pct": 0.45},
        "fill depth 0.55": {"fvg.entry_fill_pct": 0.55},
        "valid bars 7": {"entry.valid_bars": 7},
        "valid bars 9": {"entry.valid_bars": 9},
        "max hold 84": {"targets.max_hold_bars": 84},
        "max hold 108": {"targets.max_hold_bars": 108},
        "sweep recency 5": {"liquidity.sweep.max_bars_since_sweep": 5},
        "sweep recency 7": {"liquidity.sweep.max_bars_since_sweep": 7},
    }
    rows = []
    for label, over in tweaks.items():
        merged = dict(base)
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, label, splits=sp)
        rows.append(row)
        show([row])
    print("\n=== V6 PERTURBATION ===")
    return show(rows, name="v6_perturb")


def round_runner():
    """The runner exit, on the adopted config -- entry-matched by construction.

    The loss-side audit found the one mechanically actionable thing in the
    ledger: **11.0% of losing trades (14 of 127) reached beyond +2R before
    reversing all the way through the stop.** Recovering even part of that is
    worth ~0.18R per trade if it were free. It is not free -- any stop that
    protects a runner also clips the 45 trades that reach the full +4R at an
    average of +3.68R -- so the arithmetic has to be measured rather than
    assumed. v5 measured break-even and trailing on the LADDER; neither has
    ever been measured on the flat-4R configuration that is actually shipped.

    Every row selects the identical entries (`min_rr_on_liquidity` gates on the
    liquidity that is there, not on the target), so this is a clean
    entry-matched control: only the exit changes.
    """
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    variants = {
        "adopted (no management)": {},
        "trail from +1R": {"targets.trailing.enabled": True,
                           "targets.trailing.start_after_r": 1.0},
        "trail from +2R": {"targets.trailing.enabled": True,
                           "targets.trailing.start_after_r": 2.0},
        "trail from +3R": {"targets.trailing.enabled": True,
                           "targets.trailing.start_after_r": 3.0},
        "trail ATR from +2R": {"targets.trailing.enabled": True,
                               "targets.trailing.mode": "atr",
                               "targets.trailing.start_after_r": 2.0},
        "BE at +2R": {"targets.breakeven.enabled": True,
                      "targets.breakeven.trigger_r": 2.0},
        "BE at +3R": {"targets.breakeven.enabled": True,
                      "targets.breakeven.trigger_r": 3.0},
        "BE +2R & trail +3R": {"targets.breakeven.enabled": True,
                               "targets.breakeven.trigger_r": 2.0,
                               "targets.trailing.enabled": True,
                               "targets.trailing.start_after_r": 3.0},
        "partial 50% at +2R": {"targets.partial_tp.enabled": True},
    }
    rows = []
    for label, over in variants.items():
        merged = dict(V5)
        merged.update(over)
        row, frames = priced(cfg, engine, contexts, merged, label, splits=sp)
        f = frames["full"]
        row["avg_win_r"] = round(float(f.loc[f.r_multiple > 0, "r_multiple"].mean()), 3)
        row["scratch"] = int((f.r_multiple.abs() < 0.10).sum())
        rows.append(row)
        show([row], PCOLS + ["avg_win_r", "scratch"])
    print("\n=== V6 ROUND 3: THE RUNNER EXIT (entry-matched) ===")
    return show(rows, PCOLS + ["avg_win_r", "scratch"], name="v6_runner")


ROUNDS = {"dedupe": round_dedupe, "rr": round_rr, "loss": round_loss,
          "runner": round_runner, "final": round_final, "perturb": round_perturb}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True, choices=sorted(ROUNDS))
    ap.add_argument("--extra", default=None,
                    help="JSON dict of extra overrides for final/perturb")
    args = ap.parse_args()
    extra = None
    if args.extra:
        import json
        extra = json.loads(args.extra)
    fn = ROUNDS[args.round]
    if args.round in ("final", "perturb"):
        fn(extra)
    else:
        fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
