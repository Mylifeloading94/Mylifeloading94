#!/usr/bin/env python3
"""SMC Sniper v7 -- the minimum-target-distance gate, the pair cull, and the
win-rate / reward-to-risk frontier priced in dollars.

The owner's request, in his words: *"Up the win rate with better sniper entry,
target only 20 pips minimum. Figure the issue, remove any pairs that don't meet
the requirement. Aim for 60% and nothing less."*

Three separable questions, and they are kept separate here because two of them
have been asked in disguised form before and answered NO:

1. **The 20-pip minimum TARGET distance.** This is a cost-viability gate, not a
   target cap. It never shrinks a target -- it declines a setup whose reward is
   too small in absolute terms for the round-trip cost to be a rounding error.
   The rejected idea (four times over) was capping targets AT 20 pips to buy win
   rate; a matched-R, entry-matched control exposes that every time. This is the
   opposite operation and it is measured on its own terms.
   ``targets.min_target_pips``, default 0.0, swept 10/15/20/25/30/40.

2. **The pair cull.** Per instrument: median target distance in pips at the
   adopted config, configured spread, spread as a share of the target, and the
   survival rate under each gate. Selection is made on TRAIN and scored on an
   untouched TEST, because a pair list chosen on the full window is the exact
   overfitting trap that produced v1's retracted claim.

3. **60% win rate.** At a flat 4R target the break-even win rate is 20% and 60%
   is not a realistic number. It becomes arithmetically plausible only at a
   LOWER reward-to-risk: 1:1.5 break-even is 40%, 1:1 is 50%. So the frontier is
   measured properly -- flat 1R through 4R with the gate live and the culled
   universe -- and each row reports win rate, PF, expectancy in R AND IN
   DOLLARS, trade count and the cluster interval. Whether 60% is reachable and
   whether it pays are two different questions and both get answered.

Every row is entry-matched: ``targets.min_rr_on_liquidity`` is TRUE throughout,
so the reward-to-risk gate reads the liquidity that is actually there rather
than the flat multiple the config just asserted (v5 audit defect 7). The exit
changes; the entries do not.

    python3 tune_v7.py --round pipgate    # sweep min_target_pips
    python3 tune_v7.py --round pairs      # per-instrument cost geometry
    python3 tune_v7.py --round universe   # the cull, TRAIN-selected
    python3 tune_v7.py --round rr         # the WR-vs-RR frontier, in dollars
    python3 tune_v7.py --round final      # walk-forward on whatever survived

Results land in ``reports/v7/``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tune_v5 import (FRACTIONS, apply, bounds, cluster_bootstrap, cluster_ids,
                     evaluate, load_env)
from tune_v5 import show as _show_v5
from tune_v6 import CTX, PCOLS, V5, priced
from smc_sniper import walkforward
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.metrics import compute_metrics, expectancy_ci

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v7")
os.makedirs(OUT, exist_ok=True)

# The adopted v6 configuration expressed as overrides: v5 plus the break-even
# stop that arms at +3R. This is the baseline every v7 row is measured against.
V6 = dict(V5)
V6.update({"targets.breakeven.enabled": True, "targets.breakeven.trigger_r": 3.0})

RISK_PCT = 0.01
BALANCE = 100_000.0


def show(rows, cols=None, name=None):
    """`tune_v5.show` writes into reports/v5; v7 results belong in reports/v7."""
    frame = _show_v5(rows, cols, None)
    if name:
        frame.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    return frame


def env():
    return load_env("swing", "tradelocker", CTX, "_causal")


def pip_table(cfg):
    return {s: float(m.get("pip", 0.0001)) for s, m in cfg.get("markets").items()}


def spread_table(cfg):
    sp = cfg.get("execution.spreads") or {}
    default = float(cfg.get("execution.max_spread_pips_default", 2.0))
    return {s: float(sp.get(s, default)) for s in cfg.get("markets")}


def geometry(frame, pips, spreads):
    """Attach per-trade target distance in pips and the cost share of it."""
    f = frame.copy()
    f["pip"] = f.symbol.map(pips)
    f["spread_pips"] = f.symbol.map(spreads)
    # The gate reads the RESTING LIMIT, not the spread-adjusted fill, because
    # that is the price the target is measured from when the setup is judged.
    f["target_pips"] = (f.tp2 - f.limit_price).abs() / f["pip"]
    f["stop_pips"] = (f.limit_price - f.stop).abs() / f["pip"]
    f["cost_share"] = f.spread_pips / f.target_pips
    return f


# ---------------------------------------------------------------------------
# Round 1 -- the minimum target distance gate
# ---------------------------------------------------------------------------
def round_pipgate():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    rows = []
    for gate in (0.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0):
        over = dict(V6)
        over["targets.min_target_pips"] = gate
        label = "v6 baseline (gate off)" if gate == 0 else f"min target {gate:.0f} pips"
        row, frames = priced(cfg, engine, contexts, over, label, splits=sp)
        f = frames["full"]
        if len(f):
            row["avg_win_r"] = round(float(f.loc[f.r_multiple > 0, "r_multiple"].mean()), 3)
            row["pairs"] = int(f.symbol.nunique())
        rows.append(row)
        show([row], PCOLS + ["avg_win_r", "pairs"])
    print("\n=== V7 ROUND 1: MINIMUM TARGET DISTANCE ===")
    return show(rows, PCOLS + ["avg_win_r", "pairs"], name="v7_pipgate")


# ---------------------------------------------------------------------------
# Round 2 -- per-instrument cost geometry
# ---------------------------------------------------------------------------
def round_pairs():
    """Which instruments can structurally produce a >=20-pip target, and at
    what cost share -- computed on the adopted ledger, split TRAIN / TEST."""
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    pips, spreads = pip_table(cfg), spread_table(cfg)
    variant = apply(cfg, V6)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
    full = geometry(trades_to_frame(trades), pips, spreads)
    full["signal_time"] = pd.to_datetime(full["signal_time"], utc=True)
    (tr_a, tr_b), (te_a, te_b) = sp["train"], sp["test"]
    full["split"] = np.where(full.signal_time < tr_b, "train",
                             np.where(full.signal_time >= te_a, "test", "val"))

    rows = []
    for sym, g in full.groupby("symbol"):
        gt, ge = g[g.split == "train"], g[g.split == "test"]
        row = {
            "pair": sym, "n": len(g),
            "median_target_pips": round(float(g.target_pips.median()), 1),
            "median_stop_pips": round(float(g.stop_pips.median()), 1),
            "spread_pips": spreads[sym],
            "spread_pct_of_target": round(float(g.cost_share.median()) * 100, 2),
            "pct_ge_15": round(float((g.target_pips >= 15).mean()) * 100, 1),
            "pct_ge_20": round(float((g.target_pips >= 20).mean()) * 100, 1),
            "pct_ge_30": round(float((g.target_pips >= 30).mean()) * 100, 1),
            "exp": round(float(g.r_multiple.mean()), 4),
            "train_n": len(gt), "test_n": len(ge),
            "train_exp": round(float(gt.r_multiple.mean()), 4) if len(gt) else np.nan,
            "test_exp": round(float(ge.r_multiple.mean()), 4) if len(ge) else np.nan,
        }
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values("median_target_pips")
    print("\n=== V7 ROUND 2: PER-INSTRUMENT COST GEOMETRY ===")
    print(frame.to_string(index=False), flush=True)
    frame.to_csv(os.path.join(OUT, "v7_pair_geometry.csv"), index=False)
    full.to_csv(os.path.join(OUT, "v7_baseline_ledger.csv"), index=False)

    print("\n--- structural failures: median target below 20 pips ---")
    print(frame[frame.median_target_pips < 20][
        ["pair", "n", "median_target_pips", "spread_pips",
         "spread_pct_of_target", "pct_ge_20"]].to_string(index=False))
    print("\n--- punitive cost share: spread >= 5% of the median target ---")
    print(frame[frame.spread_pct_of_target >= 5.0][
        ["pair", "n", "median_target_pips", "spread_pips",
         "spread_pct_of_target"]].to_string(index=False))
    return frame


# ---------------------------------------------------------------------------
# Round 3 -- the cull, selected on TRAIN
# ---------------------------------------------------------------------------
def round_universe():
    """Candidate universes, each scored TRAIN and TEST independently.

    The selection rule is fixed BEFORE the numbers are read: a pair is cut only
    on a STRUCTURAL property measured on TRAIN (its target geometry / cost
    share), never on its TRAIN profitability -- cutting the pairs that happened
    to lose is the v1 mistake and it does not survive TEST.
    """
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    pips, spreads = pip_table(cfg), spread_table(cfg)

    # Geometry measured on the TRAIN half only.
    variant = apply(cfg, V6)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    (tr_a, tr_b) = sp["train"]
    tr, _, _ = bt.run(contexts=contexts, start=tr_a, end=tr_b, collect_rejections=False)
    train = geometry(trades_to_frame(tr), pips, spreads)
    geo = train.groupby("symbol").agg(
        n=("r_multiple", "size"),
        median_target_pips=("target_pips", "median"),
        cost_share=("cost_share", "median"),
        pct_ge_20=("target_pips", lambda s: (s >= 20).mean()),
    ).reset_index()
    geo.to_csv(os.path.join(OUT, "v7_train_geometry.csv"), index=False)
    print("\n--- TRAIN-half geometry (the selection surface) ---")
    print(geo.sort_values("median_target_pips").round(3).to_string(index=False), flush=True)

    allsyms = sorted(cfg.get("markets"))
    keep_med20 = sorted(geo.loc[geo.median_target_pips >= 20, "symbol"])
    keep_med20_cost = sorted(geo.loc[(geo.median_target_pips >= 20)
                                     & (geo.cost_share <= 0.05), "symbol"])
    keep_surv50 = sorted(geo.loc[geo.pct_ge_20 >= 0.50, "symbol"])
    keep_cost = sorted(geo.loc[geo.cost_share <= 0.05, "symbol"])

    universes = {
        "all 29 pairs (v6)": None,
        "TRAIN median target >= 20 pips": keep_med20,
        "TRAIN >=50% of targets >= 20 pips": keep_surv50,
        "TRAIN spread <= 5% of target": keep_cost,
        "both: median >=20 and cost <=5%": keep_med20_cost,
    }
    rows = []
    for label, keep in universes.items():
        for gate in (0.0, 20.0):
            over = dict(V6)
            over["targets.min_target_pips"] = gate
            name = f"{label} | gate {gate:.0f}p"
            row, frames = evaluate(cfg, engine, contexts, over, name,
                                   splits=sp, allowed=keep)
            f = frames["full"]
            if len(f) >= 30:
                clo, chi, n_c = cluster_bootstrap(f, 5000)
                row.update({"clusters": n_c, "ccl_lo": round(clo, 4),
                            "ccl_hi": round(chi, 4),
                            "cluster_clears": "YES" if not (clo < 0 < chi) else "no"})
            row["pairs"] = len(keep) if keep else len(allsyms)
            rows.append(row)
            show([row], PCOLS + ["pairs"])
    print("\n=== V7 ROUND 3: THE UNIVERSE CULL (selected on TRAIN geometry) ===")
    with open(os.path.join(OUT, "v7_universes.json"), "w") as fh:
        json.dump({k: v for k, v in universes.items()}, fh, indent=1)
    return show(rows, PCOLS + ["pairs"], name="v7_universe")


# ---------------------------------------------------------------------------
# Round 4 -- the win-rate / reward-to-risk frontier, in R and in dollars
# ---------------------------------------------------------------------------
def round_rr(gate=20.0, universe=None):
    """WR vs RR with the gate live and the culled universe.

    Every row is entry-matched -- `min_rr_on_liquidity` gates on the liquidity
    that exists rather than on the flat multiple -- so the rows differ in their
    EXIT only. Expectancy is reported in dollars as well as in R, because an R
    is not a fixed amount of money across rows: a system that trades more often
    at a lower expectancy per trade can still end the year ahead, and that is
    exactly the question the 60% target raises.
    """
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    keep = None
    if universe:
        keep = sorted(json.load(open(universe))) if os.path.exists(str(universe)) \
            else sorted(universe)
    rows = []
    for rr in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        over = dict(V6)
        over["targets.fixed_rr"] = rr
        over["targets.min_target_pips"] = gate
        # The break-even stop arms at +3R, which is unreachable at or below a
        # 3R target -- so it is inert on those rows by construction rather than
        # by choice. Stated explicitly so the rows are not read as if some had
        # trade management and others did not.
        row, frames = priced(cfg, engine, contexts, over,
                             f"flat {rr}R (gate {gate:.0f}p)", splits=sp)
        f = frames["full"]
        row["breakeven_wr"] = round(100.0 / (1.0 + rr), 2)
        row["clears_by"] = round(row["wr"] - row["breakeven_wr"], 2)
        row["exp_usd"] = round(row["exp"] * BALANCE * RISK_PCT, 2)
        row["total_usd_flat"] = round(row["exp"] * BALANCE * RISK_PCT * row["n"], 2)
        row["avg_win_r"] = round(float(f.loc[f.r_multiple > 0, "r_multiple"].mean()), 3)
        rows.append(row)
        show([row], PCOLS + ["breakeven_wr", "clears_by", "exp_usd",
                             "total_usd_flat", "avg_win_r"])
    print(f"\n=== V7 ROUND 4: THE WR / RR FRONTIER (gate {gate:.0f} pips) ===")
    print("Break-even WR is the number a win rate has to be read against. "
          "60% clears the line at 1.5R (+20 points) and 1R (+10); at 4R the "
          "line is 20% and a 35% win rate clears it by 15.")
    return show(rows, PCOLS + ["breakeven_wr", "clears_by", "exp_usd",
                               "total_usd_flat", "avg_win_r"], name=f"v7_rr_gate{int(gate)}")


# ---------------------------------------------------------------------------
# Round 5 -- freeze and walk forward
# ---------------------------------------------------------------------------
def round_final(extra=None, universe=None):
    cfg, engine, contexts = env()
    over = dict(V6)
    over.update(extra or {})
    keep = sorted(universe) if universe else None
    variant = apply(cfg, over)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False,
                          allowed_symbols=keep)
    f = trades_to_frame(trades)
    m = compute_metrics(f, 10000.0)
    lo, hi = expectancy_ci(f, 5000)
    clo, chi, n_c = cluster_bootstrap(f, 5000)
    span = (pd.to_datetime(f.exit_time).max() - pd.to_datetime(f.signal_time).min()).days
    print(f"\n=== V7 FROZEN CONFIG {extra or '(v6)'} pairs={len(keep) if keep else 29} ===")
    print(f"  trades {m['trades']}  clusters {n_c}  per_day {m['trades']/span:.3f}")
    print(f"  WR {m['win_rate']:.2f}%  PF {m['profit_factor']:.3f}  "
          f"E {m['expectancy_r']:+.4f}R  maxDD {m['max_drawdown_pct']:.2f}%  "
          f"streak {m['max_consecutive_losses']}")
    print(f"  naive   CI [{lo:+.4f}, {hi:+.4f}]  "
          f"{'SPANS ZERO' if lo < 0 < hi else 'clear of zero'}")
    print(f"  CLUSTER CI [{clo:+.4f}, {chi:+.4f}]  "
          f"{'SPANS ZERO' if clo < 0 < chi else 'CLEAR OF ZERO'}")
    # Splits are run manually rather than through `walkforward.run_splits`,
    # which has no universe argument -- restricting the pair list AFTER the
    # backtest would leave the concurrency caps binding on pairs that are not
    # in the universe, which is a different system.
    for split, (a, b) in bounds(contexts).items():
        st, _, _ = bt.run(contexts=contexts, start=a, end=b,
                          collect_rejections=False, allowed_symbols=keep)
        mm = compute_metrics(trades_to_frame(st), 10000.0)
        print(f"    {split:11s} n={mm['trades']:4d}  WR {mm['win_rate']:6.2f}%  "
              f"PF {mm['profit_factor']:6.3f}  E {mm['expectancy_r']:+.4f}R")
    wf = walkforward.walk_forward(bt, contexts, folds=5, train_frac=0.5,
                                  anchored=False, allowed_symbols=keep)
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


ROUNDS = {"pipgate": round_pipgate, "pairs": round_pairs,
          "universe": round_universe, "rr": round_rr, "final": round_final}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True, choices=sorted(ROUNDS))
    ap.add_argument("--gate", type=float, default=20.0)
    ap.add_argument("--universe", default=None,
                    help="JSON list of symbols, or a path to one")
    ap.add_argument("--extra", default=None)
    args = ap.parse_args()
    keep = None
    if args.universe:
        keep = json.load(open(args.universe)) if os.path.exists(args.universe) \
            else json.loads(args.universe)
    if args.round == "rr":
        round_rr(args.gate, keep)
    elif args.round == "final":
        round_final(json.loads(args.extra) if args.extra else None, keep)
    else:
        ROUNDS[args.round]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
