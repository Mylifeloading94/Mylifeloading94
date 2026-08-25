#!/usr/bin/env python3
"""SMC Sniper v9 -- three new angles at the win rate, tested honestly.

The owner's request: *"Let's improve it, go over the bot, find any solution to
make it better. Then give a stats update. Let's push for a higher win rate."*

Three angles, none of them previously measured on this engine:

1. **15-minute entry timing.** The adopted config qualifies a setup on 1H and
   fills a resting limit on the 1H bar. This round asks whether waiting for a
   15m confirmation candle inside the already-qualified 1H zone raises the win
   rate. Setup qualification (sweep -> MSS -> OB/FVG) is untouched: only the
   fill changes. Three variants of increasing strictness:
     a. `swing15`  -- same 1H setup, 15m fill resolution. This alone makes
        `_ltf_confirmation` a REAL 15m check instead of the degenerate
        "the setup bar confirmed itself".
     b. `swing15` + `filters.require_ltf_confirmation` -- promote that 15m
        displacement check from a +5 score component to a hard gate.
     c. `entry.confirm_mode: close_back` -- the owner's actual description:
        price taps the zone on a 15m bar, and the entry is only taken once a
        15m bar CLOSES back in the trade direction. Entry is then the NEXT 15m
        bar's OPEN with cost against us -- the first price actually reachable.

2. **Triple-timeframe alignment.** 1D bias is already a HARD gate (it IS the
   trade direction) and a 1H structure event in the trade direction is already
   a HARD gate (`no_structure_event_after_sweep`). The 4H structure layer is
   NOT: it is worth +15 in the score card as `htf_aligned` and nothing more.
   `filters.require_structure_alignment` promotes it to a hard gate.

3. **Scoring-weight re-derivation.** The card's weights came verbatim from the
   owner's original spec and have never been checked against outcome. Round
   `score` measures each component's marginal contribution on TRAIN ONLY, then
   tests whether a re-weighted card holds on the untouched TEST.

    python3 tune_v9.py --round ledger    # reproduce the live config + component ledger
    python3 tune_v9.py --round align     # angle 2
    python3 tune_v9.py --round score     # angle 3
    python3 tune_v9.py --round entry15   # angle 1
    python3 tune_v9.py --round final --extra '{...}'   # walk-forward on a survivor

Results land in ``reports/v9/``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tune_v5 import (apply, bounds, cluster_bootstrap, cluster_ids, evaluate,
                     load_env)
from tune_v6 import CTX
from tune_v7 import V6, geometry, pip_table, spread_table
from smc_sniper import walkforward
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.metrics import compute_metrics

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v9")
os.makedirs(OUT, exist_ok=True)

# The LIVE configuration, exactly as `scan_live.ADOPTED` builds it: the
# `profiles.v6` block (v5 + break-even at +3R) with a flat 1:2 target and the
# 20-pip minimum-target gate. `execute_live.py` runs this and nothing else.
LIVE = dict(V6)
LIVE.update({"targets.fixed_rr": 2.0, "targets.min_target_pips": 20.0})

# The published reference the whole session is checked against.
LIVE_EXPECT = "196 / 47.45% / PF 1.478 / +0.2660R / CI [+0.0245, +0.5151]"

PCOLS = ["variant", "n", "per_day", "wr", "pf", "exp", "train_n", "train_wr",
         "train_exp", "test_n", "test_wr", "test_exp", "max_dd",
         "max_loss_streak"]


def env(stack="swing", tag="_causal"):
    return load_env(stack, "tradelocker", CTX, tag)


def show(rows, cols=None, name=None):
    frame = pd.DataFrame(rows)
    use = [c for c in (cols or PCOLS) if c in frame.columns]
    print(frame[use].to_string(index=False), flush=True)
    if name:
        frame.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    return frame


def label_splits(frame, sp):
    f = frame.copy()
    f["signal_time"] = pd.to_datetime(f["signal_time"], utc=True)
    (_, tr_b), (te_a, _) = sp["train"], sp["test"]
    f["split"] = np.where(f.signal_time < tr_b, "train",
                          np.where(f.signal_time >= te_a, "test", "val"))
    return f


def stats(frame, label=""):
    if frame is None or not len(frame):
        return {"cut": label, "n": 0, "wr": np.nan, "pf": np.nan, "exp": np.nan}
    r = frame["r_multiple"].astype(float)
    wins, losses = r[r > 0], r[r <= 0]
    gw, gl = float(wins.sum()), float(-losses.sum())
    return {"cut": label, "n": int(len(r)), "wins": int((r > 0).sum()),
            "wr": round(float((r > 0).mean()) * 100, 2),
            "pf": round(gw / gl, 3) if gl > 0 else np.nan,
            "exp": round(float(r.mean()), 4),
            "total_r": round(float(r.sum()), 2)}


def priced(cfg, engine, contexts, over, name, splits=None, allowed=None):
    """One variant, split-scored, with a cluster interval on the full window."""
    row, frames = evaluate(cfg, engine, contexts, over, name, splits=splits,
                           allowed=allowed)
    full = frames["full"]
    if len(full) >= 25:
        lo, hi, nc = cluster_bootstrap(full, 5000)
        row.update({"clusters": nc, "ccl_lo": round(lo, 4),
                    "ccl_hi": round(hi, 4),
                    "clears": "YES" if not (lo < 0 < hi) else "no"})
    return row, frames


# ---------------------------------------------------------------------------
# Scorecard components -- reconstructed WITHOUT touching the shared engine
# ---------------------------------------------------------------------------
def component_map(cfg, engine, contexts, over):
    """signal_id -> {component: points} for every signal a config produces.

    `Signal` already carries its `ScoreCard`; the trade frame drops it. Rather
    than change `trades_to_frame` (which `execute_live.py` imports), the
    signals are regenerated here and joined onto the ledger by `signal_id`.
    """
    variant = apply(cfg, over)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    signals, _ = bt.collect_signals(contexts)
    out = {}
    for _sym, sig in signals:
        out[sig.signal_id] = dict(sig.scorecard.components)
    return out


COMPONENTS = ["htf_aligned", "mss_choch", "bos", "major_sweep",
              "pd_pw_liquidity", "valid_ob", "valid_fvg", "premium_discount",
              "displacement", "ltf_confirmation", "favorable_spread"]


def annotate(ledger, cmap):
    f = ledger.copy()
    for comp in COMPONENTS:
        f[f"c_{comp}"] = [1 if comp in cmap.get(sid, {}) else 0
                          for sid in f.signal_id]
    return f


# ---------------------------------------------------------------------------
# Round: ledger -- the live config must reproduce, and gets a component ledger
# ---------------------------------------------------------------------------
def round_ledger():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    pips, spreads = pip_table(cfg), spread_table(cfg)

    print("\n=== V9 SANITY CHECK: the LIVE config must reproduce exactly ===")
    variant = apply(cfg, LIVE)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
    f = trades_to_frame(trades)
    m = compute_metrics(f, 10000.0)
    lo, hi, nc = cluster_bootstrap(f, 5000)
    got = (f"{m['trades']} / {m['win_rate']:.2f}% / PF {m['profit_factor']:.3f}"
           f" / {m['expectancy_r']:+.4f}R / CI [{lo:+.4f}, {hi:+.4f}]")
    print(f"  got      {got}")
    print(f"  expected {LIVE_EXPECT}")
    print(f"  MATCH    {'YES' if got == LIVE_EXPECT else '*** NO ***'}")

    led = label_splits(geometry(f, pips, spreads), sp)
    cmap = component_map(cfg, engine, contexts, LIVE)
    led = annotate(led, cmap)
    led["win"] = led.r_multiple > 0
    led["hour"] = led.signal_time.dt.hour
    led.to_csv(os.path.join(OUT, "v9_live_ledger.csv"), index=False)
    print(f"\nledger -> {OUT}/v9_live_ledger.csv "
          f"({len(led)} trades, {int(led.win.sum())} wins)")
    for s in ("train", "val", "test"):
        print(f"  {s:6s} {stats(led[led.split == s])}")

    print("\n--- score-card component presence over the traded population ---")
    rows = []
    for comp in COMPONENTS:
        col = f"c_{comp}"
        rows.append({"component": comp, "weight": cfg.get(f"scoring.weights.{comp}"),
                     "present": int(led[col].sum()),
                     "absent": int((1 - led[col]).sum()),
                     "pct": round(float(led[col].mean()) * 100, 1)})
    print(pd.DataFrame(rows).to_string(index=False))
    return led


def load_ledger():
    path = os.path.join(OUT, "v9_live_ledger.csv")
    if not os.path.exists(path):
        return round_ledger()
    f = pd.read_csv(path)
    f["signal_time"] = pd.to_datetime(f["signal_time"], utc=True)
    f["exit_time"] = pd.to_datetime(f["exit_time"], utc=True)
    return f


# ---------------------------------------------------------------------------
# Round: align -- angle 2, the 4H structure layer as a hard gate
# ---------------------------------------------------------------------------
def round_align():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    led = load_ledger()

    print("\n=== ANGLE 2: what is ALREADY enforced ===")
    print("  1D bias        HARD  -- `direction = ctx.htf_bias(i)`; a neutral")
    print("                        1D bias skips the bar entirely.")
    print("  1H structure   HARD  -- a MSS/CHoCH/BOS in the trade direction")
    print("                        between the sweep bar and the setup bar is")
    print("                        required (`no_structure_event_after_sweep`).")
    print("  4H structure   SOFT  -- worth +15 as `htf_aligned`, no gate.")
    n_al = int(led.c_htf_aligned.sum())
    print(f"\n  4H agrees on {n_al}/{len(led)} traded setups "
          f"({n_al / len(led) * 100:.1f}%). {len(led) - n_al} trades would go.")
    print("\n--- the 4H-aligned cut, scored on TRAIN and TEST independently ---")
    rows = []
    for value, g in led.groupby("c_htf_aligned"):
        gt, ge, gv = (g[g.split == "train"], g[g.split == "test"],
                      g[g.split == "val"])
        rows.append({"4H aligned": bool(value),
                     "n": len(g), "wr": stats(g)["wr"], "exp": stats(g)["exp"],
                     "train_n": len(gt), "train_wr": stats(gt)["wr"],
                     "train_exp": stats(gt)["exp"],
                     "test_n": len(ge), "test_wr": stats(ge)["wr"],
                     "test_exp": stats(ge)["exp"],
                     "val_n": len(gv), "val_exp": stats(gv)["exp"]})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n--- through the engine (caps re-bind on the smaller population) ---")
    variants = {
        "LIVE (baseline)": {},
        "+require 4H alignment": {"filters.require_structure_alignment": True},
        "+require LTF confirm (1H, degenerate)": {"filters.require_ltf_confirmation": True},
        "+require major sweep": {"filters.require_major_sweep": True},
        "+require OB and FVG": {"filters.require_ob_and_fvg": True},
        "+4H align +OB&FVG": {"filters.require_structure_alignment": True,
                              "filters.require_ob_and_fvg": True},
    }
    rows = []
    for label, over in variants.items():
        merged = dict(LIVE)
        merged.update(over)
        row, _ = priced(cfg, engine, contexts, merged, label, splits=sp)
        rows.append(row)
        show([row])
    print("\n=== ANGLE 2 SUMMARY ===")
    return show(rows, name="v9_align",
                cols=PCOLS + ["clusters", "ccl_lo", "ccl_hi", "clears"])


# ---------------------------------------------------------------------------
# Round: score -- angle 3, do the weights predict anything?
# ---------------------------------------------------------------------------
def round_score():
    cfg, engine, contexts = env()
    sp = bounds(contexts)
    led = load_ledger()
    train = led[led.split == "train"]
    test = led[led.split == "test"]

    print(f"\n=== ANGLE 3: component -> outcome, TRAIN ONLY (n={len(train)}) ===")
    print("Selection happens here and nowhere else. TEST is printed beside it")
    print("only so the reader can see whether the TRAIN ranking survived.\n")
    rows = []
    for comp in COMPONENTS:
        col = f"c_{comp}"
        tp, ta = train[train[col] == 1], train[train[col] == 0]
        ep, ea = test[test[col] == 1], test[test[col] == 0]
        rows.append({
            "component": comp,
            "weight": cfg.get(f"scoring.weights.{comp}"),
            "train_n_present": len(tp), "train_n_absent": len(ta),
            "train_E_present": stats(tp)["exp"], "train_E_absent": stats(ta)["exp"],
            "train_delta": (round(stats(tp)["exp"] - stats(ta)["exp"], 4)
                            if len(tp) and len(ta) else np.nan),
            "train_WR_present": stats(tp)["wr"], "train_WR_absent": stats(ta)["wr"],
            "test_delta": (round(stats(ep)["exp"] - stats(ea)["exp"], 4)
                           if len(ep) and len(ea) else np.nan),
        })
    frame = pd.DataFrame(rows)
    print(frame.to_string(index=False))
    frame.to_csv(os.path.join(OUT, "v9_component_marginal.csv"), index=False)

    print("\nA component that is present on EVERY trade carries no information")
    print("at the gate the system runs at -- its column is constant, so it")
    print("cannot discriminate and its weight is unfalsifiable on this data.")
    const = [r["component"] for r in rows
             if r["train_n_present"] == 0 or r["train_n_absent"] == 0]
    print(f"  constant on the traded population: {const or 'none'}")

    # --- re-weighted cards -------------------------------------------------
    print("\n--- re-weighted score cards, selected on TRAIN, judged on TEST ---")
    print("Each card keeps the same 95-point ceiling and the same gate, so the")
    print("only thing that changes is how the 95 points are distributed.\n")
    base_w = dict(cfg.get("scoring.weights"))

    # Variable components, ranked by TRAIN marginal contribution.
    var = frame[(frame.train_n_present > 0) & (frame.train_n_absent > 0)]
    var = var.sort_values("train_delta", ascending=False)
    print("TRAIN ranking of the components that actually vary:")
    print(var[["component", "weight", "train_n_present", "train_delta",
               "test_delta"]].to_string(index=False))

    def reweight(boost, cut, amount):
        w = dict(base_w)
        w[boost] = w[boost] + amount
        w[cut] = max(0, w[cut] - amount)
        return {f"scoring.weights.{k}": v for k, v in w.items()}

    cards = {"LIVE weights": {}}
    if len(var) >= 2:
        best, worst = var.iloc[0]["component"], var.iloc[-1]["component"]
        for amt in (5, 10):
            cards[f"+{amt} {best} / -{amt} {worst}"] = reweight(best, worst, amt)
    # A pure "does the gate discriminate at all" probe.
    for gate in (75, 78, 82, 85):
        cards[f"gate {gate}"] = {"scoring.threshold": float(gate)}

    rows2 = []
    for label, over in cards.items():
        merged = dict(LIVE)
        merged.update(over)
        row, _ = priced(cfg, engine, contexts, merged, label, splits=sp)
        rows2.append(row)
        show([row])
    print("\n=== ANGLE 3 SUMMARY ===")
    return show(rows2, name="v9_score",
                cols=PCOLS + ["clusters", "ccl_lo", "ccl_hi", "clears"])


# ---------------------------------------------------------------------------
# Round: entry15 -- angle 1, the 15m entry refinement
# ---------------------------------------------------------------------------
def round_entry15():
    cfg, engine, contexts = env("swing15", "_causal15")
    # `data_window` reads the SETUP frame, which is 1H in both `swing` and
    # `swing15` -- so these are the same TRAIN/TEST boundaries the repo has
    # used since v5, not a new split invented for this round.
    sp = bounds(contexts)
    print(f"\n=== ANGLE 1: 15m ENTRY REFINEMENT (setup stays 1H) ===")
    w0, w1 = walkforward.data_window(contexts)
    print(f"  setup (1H) window: {w0} .. {w1}")
    print(f"  split boundaries (unchanged): train<{sp['train'][1]}  "
          f"test>={sp['test'][0]}")

    # `targets.max_hold_bars` counts ENTRY bars, so the live 96 means 96 hours
    # on a 1H entry frame and 24 hours on a 15m one. Every row here holds the
    # wall-clock budget at 96 hours (384 15m bars) so that a time-stop change
    # cannot be mistaken for an entry-timing effect. Round `entry15b` prints
    # the unmatched 24h version beside it.
    hold = {"targets.max_hold_bars": 384}
    variants = {
        "swing15 (15m fills)": {},
        "  +hard 15m LTF confirm": {"filters.require_ltf_confirmation": True},
        "  +15m close-back confirm (1 bar)": {"entry.confirm_mode": "close_back",
                                              "entry.confirm_bars": 1},
        "  +15m close-back confirm (2 bars)": {"entry.confirm_mode": "close_back",
                                               "entry.confirm_bars": 2},
        "  +15m close-back confirm (4 bars)": {"entry.confirm_mode": "close_back",
                                               "entry.confirm_bars": 4},
        "  +15m close-back (2) +hard LTF": {"entry.confirm_mode": "close_back",
                                            "entry.confirm_bars": 2,
                                            "filters.require_ltf_confirmation": True},
    }
    rows = []
    for label, over in variants.items():
        merged = dict(LIVE)
        merged.update({"active_stack": "swing15"})
        merged.update(hold)
        merged.update(over)
        row, _ = priced(cfg, engine, contexts, merged, label, splits=sp)
        rows.append(row)
        show([row])
    print("\n=== ANGLE 1 SUMMARY ===")
    return show(rows, name="v9_entry15",
                cols=PCOLS + ["clusters", "ccl_lo", "ccl_hi", "clears"])


# The entry-matched control for angle 1.
#
# Moving `entry_tf` from 1H to 15m does TWO things at once, and only one of
# them is the thing being asked about:
#
#   1. the fill is simulated on 15m bars instead of 1H bars -- the entry
#      refinement itself;
#   2. `_ltf_confirmation` stops being degenerate. With `entry_tf == setup_tf`
#      it collapses to "the setup bar confirmed itself", and since displacement
#      is ALREADY a hard gate that is automatically true -- so +5 of the live
#      card's 95 points is a free constant on every setup. On a real 15m frame
#      it becomes a genuine test that only some setups pass, and setups that
#      were clearing the gate of 80 on that free 5 stop clearing it.
#
# (2) is a SETUP-POPULATION change wearing an entry-refinement costume, and it
# is what takes the ledger from 196 trades to 100. To measure (1) on its own,
# the control sets `ltf_confirmation` to zero weight and drops the gate by the
# same 5 points: same card, same bar, minus the constant. The population then
# matches the 1H baseline and the ONLY difference left is the fill.
#
# It also has to fix a SECOND confound, and this one is an exit change wearing
# an entry-refinement costume. `targets.max_hold_bars: 96` is counted in ENTRY
# bars. On the 1H entry frame that is a 96-HOUR time budget; on a 15m frame the
# identical number is 24 hours. v5's Round H measured that time stop as doing
# real work at 96 1H-bars, so quartering it silently is not a neutral act. The
# control therefore runs 384 15m bars = the same 96 hours of wall clock.
CONTROL = {"scoring.weights.ltf_confirmation": 0, "scoring.threshold": 75.0,
           "targets.max_hold_bars": 384}


def round_entry15b():
    cfg, engine, contexts = env("swing15", "_causal15")
    sp = bounds(contexts)
    print("\n=== ANGLE 1, ENTRY-MATCHED: the fill change on its own ===")
    print("Every row below neutralises the `ltf_confirmation` constant and")
    print("restores the 96-HOUR hold budget, so the setup population is the 1H")
    print("baseline's and the only thing that moves is when and at what price")
    print("the entry is taken.\n")

    variants = {
        "control: 15m fills (96h hold)": {},
        "  +close_back confirm (1 bar)": {"entry.confirm_mode": "close_back",
                                          "entry.confirm_bars": 1},
        "  +close_back confirm (2 bars)": {"entry.confirm_mode": "close_back",
                                           "entry.confirm_bars": 2},
        "  +close_back confirm (4 bars)": {"entry.confirm_mode": "close_back",
                                           "entry.confirm_bars": 4},
        "  +close_back confirm (8 bars)": {"entry.confirm_mode": "close_back",
                                           "entry.confirm_bars": 8},
        "  +close_dir confirm (1 bar)": {"entry.confirm_mode": "close_dir",
                                         "entry.confirm_bars": 1},
        "  +close_dir confirm (2 bars)": {"entry.confirm_mode": "close_dir",
                                          "entry.confirm_bars": 2},
        "UNMATCHED: 24h hold (96 15m bars)": {"targets.max_hold_bars": 96},
    }
    rows = []
    for label, over in variants.items():
        merged = dict(LIVE)
        merged.update({"active_stack": "swing15"})
        merged.update(CONTROL)
        merged.update(over)
        row, _ = priced(cfg, engine, contexts, merged, label, splits=sp)
        rows.append(row)
        show([row])
    print("\n=== ANGLE 1 ENTRY-MATCHED SUMMARY ===")
    return show(rows, name="v9_entry15_matched",
                cols=PCOLS + ["clusters", "ccl_lo", "ccl_hi", "clears"])


# ---------------------------------------------------------------------------
# Round: final -- walk-forward + cluster CI on a candidate
# ---------------------------------------------------------------------------
def round_final(extra=None, stack="swing", tag="_causal", name="candidate"):
    cfg, engine, contexts = env(stack, tag)
    # `data_window` reads the SETUP frame, which is 1H on both `swing` and
    # `swing15`, so the split boundaries are identical either way.
    sp = bounds(contexts)
    over = dict(LIVE)
    if stack != "swing":
        over["active_stack"] = stack
    over.update(extra or {})
    print(f"\n=== V9 FINAL: {name} ===")
    print(json.dumps(over, indent=2, default=str))

    row, frames = priced(cfg, engine, contexts, over, name, splits=sp)
    show([row], cols=PCOLS + ["clusters", "ccl_lo", "ccl_hi", "clears"])

    variant = apply(cfg, over)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    wf = walkforward.walk_forward(bt, contexts, folds=5, train_frac=0.5,
                                  anchored=False)
    oos = wf["oos_trades"]
    print("\n" + wf["folds"][["fold", "oos_trades", "oos_wr", "oos_pf",
                              "oos_exp_r"]].to_string(index=False))
    if oos is not None and len(oos):
        m = compute_metrics(oos, 10000.0)
        lo, hi, nc = cluster_bootstrap(oos, 5000)
        print(f"\nWALK-FORWARD OOS: n={m['trades']}  WR {m['win_rate']:.2f}%  "
              f"PF {m['profit_factor']:.3f}  E {m['expectancy_r']:+.4f}R")
        print(f"  clusters {nc}  cluster CI [{lo:+.4f}, {hi:+.4f}]  "
              f"{'CLEARS' if not (lo < 0 < hi) else 'SPANS ZERO'}")
    return row, frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True,
                    choices=["ledger", "align", "score", "entry15", "entry15b",
                             "final"])
    ap.add_argument("--extra", default="")
    ap.add_argument("--stack", default="swing")
    ap.add_argument("--tag", default="_causal")
    ap.add_argument("--name", default="candidate")
    args = ap.parse_args()
    extra = json.loads(args.extra) if args.extra else None
    fn = {"ledger": round_ledger, "align": round_align, "score": round_score,
          "entry15": round_entry15, "entry15b": round_entry15b}.get(args.round)
    if fn:
        fn()
    else:
        round_final(extra, args.stack, args.tag, args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
