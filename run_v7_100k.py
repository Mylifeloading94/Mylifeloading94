#!/usr/bin/env python3
"""The v7 deliverable: $100,000 at a chosen flat reward-to-risk, with the
minimum-target-distance gate live.

Identical machinery to ``run_v6_100k.py`` -- same fill model, same compounding,
same cluster bootstrap, same continuous period tables -- with two knobs exposed
so the WR/RR frontier's chosen point can be produced as a deliverable without
editing a profile:

    --rr    the flat reward-to-risk target (``targets.fixed_rr``)
    --gate  the minimum target distance in pips (``targets.min_target_pips``)

Both windows the owner asked for:

    python3 run_v7_100k.py --full --rr 2.0 --gate 20 --tag full_2r
    python3 run_v7_100k.py --days 90 --rr 2.0 --gate 20 --tag 90d_2r

Writes ``reports/v7_100k/<tag>/``. Nothing here places an order; cached broker
bars are read and nothing else.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper import walkforward
from smc_sniper.backtest import Backtester
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine

from run_v6_100k import ruin_table, run_one, trade_rows

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v7_100k")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--balance", type=float, default=100000.0)
    ap.add_argument("--profile", default="v6")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--gate", type=float, default=20.0)
    ap.add_argument("--source", default="tradelocker")
    ap.add_argument("--risks", default="1.0")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    cfg = load_config()
    if args.profile and args.profile.lower() not in ("", "none"):
        cfg = cfg.apply_profile(args.profile)
    cfg.set("targets.fixed_rr", args.rr)
    cfg.set("targets.min_target_pips", args.gate)
    # `min_rr_on_liquidity` keeps the reward-to-risk filter reading the
    # liquidity that is actually there rather than the flat multiple the config
    # just asserted (v5 audit defect 7), so a change of `fixed_rr` changes the
    # EXIT and not the entry population.
    cfg.set("targets.min_rr_on_liquidity", True)

    engine = DataEngine(cfg, source=args.source)
    contexts = Backtester(cfg, engine).build_contexts()
    dstart, dend = walkforward.data_window(contexts)
    if args.full:
        start, end, label = dstart, dend, "full"
    else:
        end = dend
        start = end - pd.Timedelta(days=args.days)
        label = f"{args.days}d"
    tag_dir = os.path.join(OUT, args.tag or label)
    os.makedirs(tag_dir, exist_ok=True)

    print("=" * 78)
    print(f"v7 DELIVERABLE -- ${args.balance:,.0f}, {label} window, compounding")
    print(f"  profile '{args.profile}'  flat {args.rr}R  min target "
          f"{args.gate:.0f} pips  {len(contexts)} pairs  gate {cfg.score_threshold:.0f}")
    print(f"  window {str(start)[:10]} -> {str(end)[:10]}  "
          f"({(end - start).days} days)")
    print("=" * 78)

    all_trades, summaries = [], []
    for risk_pct in [float(x) for x in args.risks.split(",")]:
        ledger, per, summary = run_one(cfg, engine, contexts, start, end,
                                       args.balance, risk_pct)
        summary["fixed_rr"] = args.rr
        summary["min_target_pips"] = args.gate
        rtag = f"{risk_pct:g}pct".replace(".", "_")
        for name in ("daily", "weekly", "monthly", "yearly"):
            per[name].insert(0, "risk_pct", risk_pct)
            per[name].to_csv(os.path.join(tag_dir, f"{name}_{rtag}.csv"), index=False)
        ledger.to_csv(os.path.join(tag_dir, f"ledger_{rtag}.csv"), index=False)
        all_trades.append(trade_rows(ledger, args.balance, risk_pct))
        summaries.append(summary)
        print(f"\n--- RISK {risk_pct}% ---")
        for k, v in summary.items():
            print(f"  {k:26s} {v}")

    pd.concat(all_trades, ignore_index=True).to_csv(
        os.path.join(tag_dir, "trades.csv"), index=False)
    pd.DataFrame(summaries).to_csv(os.path.join(tag_dir, "summary.csv"), index=False)

    streak = int(max(s["max_consecutive_losses"] for s in summaries)) or 1
    ruin_table(streak).to_csv(os.path.join(tag_dir, "risk_of_ruin.csv"), index=False)
    print(f"\nWrote {tag_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
