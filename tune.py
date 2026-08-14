#!/usr/bin/env python3
"""SMC Sniper v2 -- the improvement loop.

This is the harness the v2 tuning was actually done with. It exists so the
tuning log in ``reports/tuning/`` is reproducible rather than asserted.

The protocol every round follows, without exception:

* A change is proposed as a **hypothesis** and written down BEFORE it is run.
* It is measured on TRAIN (first 50% of the window) and on TEST (last 30%)
  **independently**. The two never get pooled to make a decision.
* A change is adopted only if it helps TRAIN *and* survives TEST. "Survives"
  means it does not make TEST materially worse; a change that only works on
  one side is rejected and the rejection is logged with its numbers.
* Nothing selects on the full window. Nothing selects on TEST.

Usage::

    python3 tune.py --round diagnostics
    python3 tune.py --round a      # loss minimisation
    python3 tune.py --round b      # win rate / quality
    python3 tune.py --round c      # opportunity / volume
    python3 tune.py --round final  # the adopted config, full validation
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.metrics import breakdown, compute_metrics, expectancy_ci, win_rate_ci
from smc_sniper import walkforward

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "tuning")
os.makedirs(OUT, exist_ok=True)

FRACTIONS = (0.50, 0.20, 0.30)


# ---------------------------------------------------------------------------
# Context cache -- building 13 pairs of context takes ~60s, so it is done once
# and reused across every variant in a round.
# ---------------------------------------------------------------------------
def load_env(stack: str = "swing", source: str = "tradelocker"):
    cfg = load_config()
    cfg.set("active_stack", stack)
    engine = DataEngine(cfg, source=source)
    cache = os.path.join(REPO, "smc_data", f"_ctx_{stack}_{source}.pkl")
    if os.path.exists(cache):
        try:
            with open(cache, "rb") as fh:
                contexts = pickle.load(fh)
            print(f"contexts: {len(contexts)} pairs (cached)")
            return cfg, engine, contexts
        except Exception as exc:  # noqa: BLE001
            print(f"context cache unusable ({exc}); rebuilding")
    t0 = time.time()
    contexts = Backtester(cfg, engine).build_contexts()
    print(f"contexts: {len(contexts)} pairs built in {time.time() - t0:.0f}s")
    try:
        with open(cache, "wb") as fh:
            pickle.dump(contexts, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:  # noqa: BLE001
        print(f"  (context cache not written: {exc})")
    return cfg, engine, contexts


def bounds(contexts):
    start, end = walkforward.data_window(contexts)
    return walkforward.split_window(start, end, FRACTIONS)


# ---------------------------------------------------------------------------
# Variant evaluation
# ---------------------------------------------------------------------------
def apply(cfg, overrides: dict):
    variant = cfg.copy()
    for dotted, value in (overrides or {}).items():
        variant.set(dotted, value)
    return variant


def evaluate(cfg, engine, contexts, overrides: dict, name: str,
             balance: float = 10000.0, splits=None, ci: bool = False) -> dict:
    """Run one variant and return full / train / test metrics.

    Signal generation happens once per variant and is reused across the
    splits, so a split result is exactly the subset of the full run that falls
    in that window -- with the risk engine reset per window, which is the
    honest way to score a period in isolation.
    """
    variant = apply(cfg, overrides)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    t0 = time.time()
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
    full = trades_to_frame(trades)
    row = {"variant": name, "seconds": round(time.time() - t0, 1)}
    frames = {"full": full}
    for split, (a, b) in (splits or bounds(contexts)).items():
        tr, _, _ = bt.run(contexts=contexts, start=a, end=b, collect_rejections=False)
        frames[split] = trades_to_frame(tr)
    for tag, frame in frames.items():
        m = compute_metrics(frame, balance)
        prefix = "" if tag == "full" else f"{tag}_"
        row[f"{prefix}n"] = m["trades"]
        row[f"{prefix}wr"] = round(m["win_rate"], 2)
        row[f"{prefix}pf"] = round(m["profit_factor"], 3)
        row[f"{prefix}exp"] = round(m["expectancy_r"], 4)
        if tag == "full":
            row["max_dd"] = round(m["max_drawdown_pct"], 2)
            row["total_r"] = round(m["total_r"], 2)
            row["max_loss_streak"] = m.get("max_consecutive_losses", 0)
    if ci and not full.empty:
        lo, hi = expectancy_ci(full, 5000)
        row["exp_ci_low"], row["exp_ci_high"] = round(lo, 4), round(hi, 4)
        wlo, whi = win_rate_ci(full, 5000)
        row["wr_ci_low"], row["wr_ci_high"] = round(wlo, 2), round(whi, 2)
    return row, frames


def show(rows, cols=None):
    frame = pd.DataFrame(rows)
    cols = cols or [c for c in frame.columns if c != "seconds"]
    print(frame[cols].to_string(index=False))
    return frame


def subgroup(frame: pd.DataFrame, by: str, min_n: int = 0) -> pd.DataFrame:
    """Per-group metrics with a bootstrap CI on expectancy."""
    if frame is None or frame.empty or by not in frame:
        return pd.DataFrame()
    rows = []
    for key, group in frame.groupby(by):
        m = compute_metrics(group, 10000.0)
        lo, hi = expectancy_ci(group, 2000)
        rows.append({by: key, "n": m["trades"], "wr": round(m["win_rate"], 2),
                     "pf": round(m["profit_factor"], 3),
                     "exp": round(m["expectancy_r"], 4),
                     "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                     "total_r": round(m["total_r"], 2)})
    out = pd.DataFrame(rows)
    if min_n:
        out = out[out["n"] >= min_n]
    return out.sort_values("exp", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------
def round_diagnostics(cfg, engine, contexts):
    """Where do the losses live? Measured on TRAIN, reported for TEST."""
    bnds = bounds(contexts)
    row, frames = evaluate(cfg, engine, contexts, {}, "baseline",
                           splits=bnds, ci=True)
    print("\nBASELINE")
    print(pd.DataFrame([row]).to_string(index=False))

    train, test = frames["train"], frames["test"]
    for frame, label in ((train, "TRAIN"), (test, "TEST")):
        frame = frame.copy()
        if frame.empty:
            continue
        frame["hour"] = pd.to_datetime(frame["signal_time"]).dt.hour
        frame["dow"] = pd.to_datetime(frame["signal_time"]).dt.dayofweek
        frame["dir"] = frame["direction"].map({"bullish": "long", "bearish": "short"})
        frame["score_bucket"] = pd.cut(frame["score"], [-1, 79.9, 84.9, 200],
                                       labels=["<80", "80-84", "85+"]).astype(str)
        for dim in ("liquidity_type", "dir", "session", "hour", "dow",
                    "score_bucket", "exit_reason", "symbol", "zone_kind"):
            table = subgroup(frame, dim)
            if table.empty:
                continue
            print(f"\n--- {label} by {dim} ---")
            print(table.to_string(index=False))
            table.to_csv(os.path.join(OUT, f"diag_{label.lower()}_{dim}.csv"), index=False)

    # Where do the biggest losses come from?
    for frame, label in ((train, "TRAIN"), (test, "TEST")):
        if frame.empty:
            continue
        worst = frame.nsmallest(12, "r_multiple")[
            ["symbol", "signal_time", "direction", "liquidity_type", "session",
             "score", "r_multiple", "exit_reason", "mae_r", "mfe_r"]]
        print(f"\n--- {label}: 12 worst trades ---")
        print(worst.to_string(index=False))
    return frames


def round_a(cfg, engine, contexts):
    """A -- minimise losses. Pre-registered from the v1 adaptive layer."""
    bnds = bounds(contexts)
    variants = {
        "baseline": {},
        "A1_no_session_high_sweeps": {"filters.liquidity_exclude": ["session_high"]},
        "A2_no_session_extremes": {"filters.liquidity_exclude":
                                   ["session_high", "session_low"]},
        "A3_struct_invalidation": {"filters.structural_invalidation.enabled": True},
        "A3b_struct_inval_mss_only": {"filters.structural_invalidation.enabled": True,
                                      "filters.structural_invalidation.kinds": ["MSS"]},
        "A4_loss_streak_3": {"risk.max_consecutive_losses": 3},
        "A5_loss_streak_2": {"risk.max_consecutive_losses": 2},
        "A6_no_swing_pools": {"filters.liquidity_exclude": ["swing_high", "swing_low"]},
    }
    rows = []
    for name, over in variants.items():
        row, _ = evaluate(cfg, engine, contexts, over, name, splits=bnds)
        rows.append(row)
        print(f"  {name:30s} done")
    frame = show(rows, ["variant", "n", "wr", "pf", "exp", "max_dd",
                        "train_n", "train_wr", "train_pf", "train_exp",
                        "test_n", "test_wr", "test_pf", "test_exp"])
    frame.to_csv(os.path.join(OUT, "round_a.csv"), index=False)
    return frame


def round_b(cfg, engine, contexts, base: dict):
    """B -- more winners. Score gate frontier + the equal-lows hypothesis.

    ``B8`` is the literal v1 post-hoc claim ("sweeps of equal lows carry the
    edge") tested on splits it was not derived from. It is included precisely
    because it is expected to shrink -- a post-hoc subgroup found by scanning
    seven liquidity types should shrink, and reporting that is the point.
    """
    bnds = bounds(contexts)
    variants = {
        "B0_carry_forward": {},
        "B1_equal_levels_only": {"filters.liquidity_include":
                                 ["equal_highs", "equal_lows"]},
        "B2_equal_plus_pdpw": {"filters.liquidity_include":
                               ["equal_highs", "equal_lows",
                                "PDH", "PDL", "PWH", "PWL"]},
        "B3_gate_75": {"scoring.threshold": 75},
        "B4_gate_85": {"scoring.threshold": 85},
        "B5_longs_only": {"filters.directions": ["bullish"]},
        "B6_london_only": {"sessions.allowed": ["london"]},
        "B7_min_rr_25": {"targets.min_rr": 2.5},
        "B8_equal_lows_only_v1_claim": {"filters.liquidity_include": ["equal_lows"]},
        "B9_no_pdl": {"filters.liquidity_exclude":
                      ["session_high", "session_low", "PDL"]},
    }
    rows = []
    for name, over in variants.items():
        merged = dict(base)
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, name, splits=bnds,
                          ci=name in ("B0_carry_forward",))
        rows.append(row)
        print(f"  {name:30s} done")
    frame = show(rows, ["variant", "n", "wr", "pf", "exp", "max_dd",
                        "train_n", "train_wr", "train_pf", "train_exp",
                        "test_n", "test_wr", "test_pf", "test_exp"])
    frame.to_csv(os.path.join(OUT, "round_b.csv"), index=False)
    return frame


def round_c(cfg, engine, contexts, base: dict):
    """C -- more opportunities, without giving the expectancy back."""
    bnds = bounds(contexts)
    variants = {
        "C0_carry_forward": {},
        "C1_gate_75": {"scoring.threshold": 75},
        "C2_gate_70": {"scoring.threshold": 70},
        "C3_more_concurrent": {"risk.max_open_positions": 5,
                               "risk.max_trades_per_day": 5},
        "C4_more_ccy_exposure": {"risk.max_exposure_per_currency": 3},
        "C5_asian_session": {"sessions.allowed": ["asian", "london", "ny"]},
        "C6_late_ny": {"sessions.allowed": ["london", "ny", "late_ny"]},
        "C7_dedupe_4": {"dedupe.cooldown_bars": 4},
        "C8_all_volume": {"scoring.threshold": 75, "risk.max_open_positions": 5,
                          "risk.max_trades_per_day": 5,
                          "risk.max_exposure_per_currency": 3,
                          "dedupe.cooldown_bars": 4},
    }
    rows = []
    for name, over in variants.items():
        merged = dict(base)
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, name, splits=bnds)
        rows.append(row)
        print(f"  {name:30s} done")
    frame = show(rows, ["variant", "n", "wr", "pf", "exp", "max_dd",
                        "train_n", "train_wr", "train_pf", "train_exp",
                        "test_n", "test_wr", "test_pf", "test_exp"])
    frame.to_csv(os.path.join(OUT, "round_c.csv"), index=False)
    return frame


# Adopted after round A: session-extreme sweeps are removed. Pre-registered
# from the v1 adaptive layer (session highs, n=34, PF 0.46) and confirmed on
# TRAIN as a CLASS (session highs + lows, n=33 train trades, expectancy
# -0.271R) rather than cherry-picking the one negative side. It improves TRAIN
# and TEST independently, which is the bar every filter in this repo has to
# clear.
ADOPTED: dict = {"filters.liquidity_exclude": ["session_high", "session_low"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="diagnostics")
    ap.add_argument("--stack", default="swing")
    args = ap.parse_args()
    cfg, engine, contexts = load_env(args.stack)
    name = args.round.lower()
    if name == "diagnostics":
        round_diagnostics(cfg, engine, contexts)
    elif name == "a":
        round_a(cfg, engine, contexts)
    elif name == "b":
        round_b(cfg, engine, contexts, ADOPTED)
    elif name == "c":
        round_c(cfg, engine, contexts, ADOPTED)
    else:
        raise SystemExit(f"unknown round {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
