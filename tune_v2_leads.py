#!/usr/bin/env python3
"""The two v2 leads, finally put through a TRAIN/TEST cycle.

v2's perturbation sweep and matched-R control each turned up something that
looked better than the adopted config and neither was adoptable as it stood,
because **both were scored on the full window** -- exactly the selection this
repo forbids. They were recorded as candidates for the next round:

  (a) ``stops.min_stop_over_cost = 15``  -> PF 1.644, +0.245R on 94 trades
  (b) a flat 4R target                   -> +0.263R vs the ladder's +0.114R

Both were measured on the SWING stack (1D/4H/1H, ~1200 days), so that is where
they get tested. Selection is made on TRAIN; TEST is reported but is not what
the decision is made on. A lead that only survives by being scored on the same
window that suggested it is not a lead, it is a fit.

    python3 tune_v2_leads.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tune import bounds, evaluate, load_env

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "reports", "tuning")

VARIANTS = {
    "V2_baseline": {},
    # lead (a): the cost gate, either side of the flagged value
    "V2a_cost_12x": {"stops.min_stop_over_cost": 12.0},
    "V2a_cost_15x": {"stops.min_stop_over_cost": 15.0},
    "V2a_cost_20x": {"stops.min_stop_over_cost": 20.0},
    # lead (b): the flat target. Management is stripped so this is the same
    # shape the matched-R control measured -- otherwise it is a different
    # change wearing the lead's name.
    "V2b_flat_4R": {"targets.mode": "fixed_rr", "targets.fixed_rr": 4.0,
                    "targets.min_rr": 2.0,
                    "targets.partial_tp.enabled": False,
                    "targets.breakeven.enabled": False,
                    "targets.trailing.enabled": False},
    "V2b_flat_3R": {"targets.mode": "fixed_rr", "targets.fixed_rr": 3.0,
                    "targets.min_rr": 2.0,
                    "targets.partial_tp.enabled": False,
                    "targets.breakeven.enabled": False,
                    "targets.trailing.enabled": False},
    # both together, since each was flagged in isolation
    "V2ab_cost15_flat4R": {"stops.min_stop_over_cost": 15.0,
                           "targets.mode": "fixed_rr", "targets.fixed_rr": 4.0,
                           "targets.min_rr": 2.0,
                           "targets.partial_tp.enabled": False,
                           "targets.breakeven.enabled": False,
                           "targets.trailing.enabled": False},
}


def main() -> int:
    cfg, engine, contexts = load_env("swing")
    bnds = bounds(contexts)
    rows = []
    for name, over in VARIANTS.items():
        row, _ = evaluate(cfg, engine, contexts, over, name, splits=bnds,
                          ci=name in ("V2_baseline", "V2a_cost_15x", "V2b_flat_4R"))
        rows.append(row)
        print(f"  {name:22s} n={row['n']:4d} wr={row['wr']:.2f} pf={row['pf']:.3f} "
              f"train_exp={row['train_exp']:+.4f} test_exp={row['test_exp']:+.4f}",
              flush=True)
    frame = pd.DataFrame(rows)
    cols = ["variant", "n", "wr", "pf", "exp", "max_dd",
            "train_n", "train_wr", "train_pf", "train_exp",
            "test_n", "test_wr", "test_pf", "test_exp"]
    cols += [c for c in ("exp_ci_low", "exp_ci_high") if c in frame.columns]
    print("\n" + frame[cols].to_string(index=False))
    os.makedirs(OUT, exist_ok=True)
    frame.to_csv(os.path.join(OUT, "v2_leads.csv"), index=False)
    print(f"\nwrote {OUT}/v2_leads.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
