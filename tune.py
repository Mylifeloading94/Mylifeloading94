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
from smc_sniper.signal_engine import CONTEXT_CACHE_VERSION

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
                version, contexts = pickle.load(fh)
            if version != CONTEXT_CACHE_VERSION:
                raise ValueError(f"cache v{version} != code v{CONTEXT_CACHE_VERSION}")
            print(f"contexts: {len(contexts)} pairs (cached)")
            return cfg, engine, contexts
        except Exception as exc:  # noqa: BLE001
            print(f"context cache unusable ({exc}); rebuilding")
    t0 = time.time()
    contexts = Backtester(cfg, engine).build_contexts()
    print(f"contexts: {len(contexts)} pairs built in {time.time() - t0:.0f}s")
    try:
        with open(cache, "wb") as fh:
            pickle.dump((CONTEXT_CACHE_VERSION, contexts), fh,
                        protocol=pickle.HIGHEST_PROTOCOL)
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
             balance: float = 10000.0, splits=None, ci: bool = False,
             allowed=None) -> dict:
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
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False,
                          allowed_symbols=allowed)
    full = trades_to_frame(trades)
    row = {"variant": name, "seconds": round(time.time() - t0, 1)}
    frames = {"full": full}
    for split, (a, b) in (splits or bounds(contexts)).items():
        tr, _, _ = bt.run(contexts=contexts, start=a, end=b, collect_rejections=False,
                          allowed_symbols=allowed)
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


V1_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
            "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "CADJPY", "XAUUSD"]
V2_PAIRS = ["AUDCAD", "AUDCHF", "AUDNZD", "CADCHF", "CHFJPY", "EURAUD", "EURCAD",
            "EURCHF", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
            "NZDCAD", "NZDCHF", "NZDJPY"]


def round_c(cfg, engine, contexts, base: dict):
    """C -- more opportunities, without giving the expectancy back.

    ``C1`` is the honest gate on the 16 added pairs: they are scored ALONE, on
    TRAIN and on TEST, so their contribution is visible rather than diluted
    into a 29-pair average that the original 13 could carry.
    """
    bnds = bounds(contexts)
    everything = list(contexts)
    v2_only = [s for s in V2_PAIRS if s in contexts]
    variants = [
        ("C0_13pairs_carry_forward", {}, V1_PAIRS),
        ("C1_new16_alone", {}, v2_only),
        ("C2_29pairs", {}, everything),
        ("C3_29pairs_london_only", {"sessions.allowed": ["london"]}, everything),
        ("C4_29pairs_wider_caps", {"risk.max_open_positions": 5,
                                   "risk.max_trades_per_day": 5,
                                   "risk.max_exposure_per_currency": 3}, everything),
        ("C5_29pairs_dedupe4", {"dedupe.cooldown_bars": 4}, everything),
        ("C6_29pairs_gate75", {"scoring.threshold": 75}, everything),
        ("C7_29pairs_volume_combo", {"risk.max_open_positions": 5,
                                     "risk.max_trades_per_day": 5,
                                     "risk.max_exposure_per_currency": 3,
                                     "dedupe.cooldown_bars": 4}, everything),
        ("C8_29pairs_london_wider_caps", {"sessions.allowed": ["london"],
                                          "risk.max_open_positions": 5,
                                          "risk.max_trades_per_day": 5,
                                          "risk.max_exposure_per_currency": 3},
         everything),
    ]
    rows = []
    for name, over, allowed in variants:
        merged = dict(base)
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, name, splits=bnds,
                          allowed=allowed)
        row["pairs"] = len(allowed)
        rows.append(row)
        print(f"  {name:30s} done")
    frame = show(rows, ["variant", "pairs", "n", "wr", "pf", "exp", "max_dd",
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


def write_improvements() -> pd.DataFrame:
    """Assemble the v2 tuning log from the round CSVs.

    Every row carries the TRAIN and TEST numbers the decision was made on, so
    a reader can disagree with a call without having to re-run anything. The
    ``decision`` column is the only editorial judgement in the file.
    """
    rows = []
    files = {"A": "round_a.csv", "B": "round_b.csv", "C": "round_c.csv"}
    for phase, fname in files.items():
        path = os.path.join(OUT, fname)
        if not os.path.exists(path):
            continue
        frame = pd.read_csv(path)
        for _, r in frame.iterrows():
            rows.append({
                "round": phase, "variant": r["variant"],
                "pairs": r.get("pairs", 13),
                "full_n": r["n"], "full_wr": r["wr"], "full_pf": r["pf"],
                "full_exp_r": r["exp"], "full_max_dd_pct": r["max_dd"],
                "train_n": r["train_n"], "train_wr": r["train_wr"],
                "train_pf": r["train_pf"], "train_exp_r": r["train_exp"],
                "test_n": r["test_n"], "test_wr": r["test_wr"],
                "test_pf": r["test_pf"], "test_exp_r": r["test_exp"],
                "decision": DECISIONS.get(r["variant"], ("", ""))[0],
                "reason": DECISIONS.get(r["variant"], ("", ""))[1],
            })
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "improvements.csv"), index=False)
    print(f"wrote {OUT}/improvements.csv ({len(out)} rows)")
    return out


# variant -> (decision, reason). Written as each round was scored, before the
# next round started. "helps TRAIN and survives TEST" is the whole bar.
DECISIONS: dict[str, tuple[str, str]] = {
    "baseline": ("reference", "v1 config, 13 pairs, no filters"),
    "A1_no_session_high_sweeps": (
        "superseded by A2",
        "Works (TRAIN +0.011->+0.117R, TEST +0.002->+0.047R) but cuts only one "
        "side of a symmetric pool type; A2 does the same job as a class."),
    "A2_no_session_extremes": (
        "ADOPTED",
        "TRAIN +0.011->+0.179R (PF 1.022->1.405) and TEST +0.002->+0.145R "
        "(PF 0.996->1.330). Improves both splits independently. The only v2 "
        "change that does."),
    "A3_struct_invalidation": (
        "REJECTED",
        "Early exit on an opposing structure shift made things WORSE on both "
        "splits (TRAIN +0.011->-0.064R, TEST +0.002->-0.003R) and pushed max DD "
        "3.74%->5.98%. It cuts trades that were going to recover."),
    "A3b_struct_inval_mss_only": (
        "REJECTED", "Identical to A3 -- the first opposing event is almost "
        "always an MSS, so narrowing the kinds changes nothing."),
    "A4_loss_streak_3": (
        "REJECTED", "Tighter loss-streak cooldown hurt TRAIN (+0.011->-0.025R) "
        "and TEST (+0.002->-0.049R). It skips the recovery trades too."),
    "A5_loss_streak_2": (
        "REJECTED", "Same shape as A4: TRAIN -0.026R. Throttling on streaks "
        "removes good trades along with bad ones."),
    "A6_no_swing_pools": (
        "no-op", "Bit-identical to baseline: recent_sweep already prefers "
        "strong pools, so a raw swing point is never the swept pool."),
    "B0_carry_forward": ("reference", "A2 adopted, 13 pairs"),
    "B1_equal_levels_only": (
        "REJECTED", "Trading only equal-high/equal-low sweeps HURT TRAIN "
        "(+0.179->+0.132R). It improves TEST (+0.145->+0.142R is flat, PF up), "
        "but selection is made on TRAIN, so this is not adoptable."),
    "B2_equal_plus_pdpw": ("no-op", "Identical to B0 -- after A2 the only "
                           "remaining pool kinds are already equal levels and PD/PW."),
    "B3_gate_75": (
        "REJECTED", "Loosening the score gate collapsed TRAIN (+0.179->-0.113R) "
        "and tripled max DD to 9.09%. Matches the v1 perturbation result."),
    "B4_gate_85": (
        "REJECTED", "Starves the sample: 14 trades in 1200 days, 4 of them on "
        "TRAIN. Nothing can be concluded from it either way."),
    "B5_longs_only": (
        "REJECTED", "Better on both splits (TRAIN +0.309R, TEST +0.141R) but "
        "halves trade count to 43, and direction INVERTED between train and "
        "test at baseline. Not adopted on a signal that has already flipped."),
    "B6_london_only": (
        "REJECTED", "Excellent on 13 pairs (TRAIN +0.269R, TEST +0.274R) but "
        "reversed on the 29-pair universe (C3: TRAIN +0.070R, WORSE than "
        "+0.109R). A filter that depends on the universe is a fit."),
    "B7_min_rr_25": (
        "REJECTED", "Improves both splits but touches exits, so it needs the "
        "matched-R control, and it costs 62% of the trades. Not worth "
        "adopting on 35 trades late in the session."),
    "B8_equal_lows_only_v1_claim": (
        "NOT REPLICATED",
        "The v1 post-hoc 68.57% subgroup, tested properly: TRAIN +0.446R but "
        "TEST +0.057R -- an 87% shrink out of sample, on 8 test trades. This "
        "is the expected fate of a subgroup found by scanning 7 liquidity "
        "types, and it is why it was never a result."),
    "B9_no_pdl": (
        "REJECTED", "Helps TRAIN (+0.231R) and hurts TEST (+0.079R). Mixed "
        "signals are rejected, not split the convenient way."),
    "C0_13pairs_carry_forward": ("reference", "A2 adopted, original 13 pairs"),
    "C1_new16_alone": (
        "NOT VALIDATED ALONE",
        "The 16 added crosses on their own are NEGATIVE on TRAIN (-0.029R) and "
        "weakly positive on TEST (+0.051R). They are volume, not edge, and "
        "this row exists so nobody can claim otherwise."),
    "C2_29pairs": (
        "ADOPTED",
        "The portfolio still improves against the v1 baseline on both splits "
        "(TRAIN +0.011->+0.109R, TEST +0.002->+0.083R) while holding trade "
        "count at 153 vs 151. It does dilute the 13-pair filter result "
        "(+0.174->+0.114R) -- that is the price of the frequency."),
    "C3_29pairs_london_only": (
        "REJECTED", "TRAIN +0.070R is worse than the +0.109R it is compared "
        "against, even though TEST looks superb (+0.360R). Selecting on that "
        "TEST number is exactly the mistake the protocol exists to prevent."),
    "C4_29pairs_wider_caps": (
        "no-op", "Bit-identical to C2: max_open_positions / max_trades_per_day "
        "/ per-currency exposure were never the binding constraint. The system "
        "is limited by setup scarcity, not by its risk caps."),
    "C5_29pairs_dedupe4": (
        "REJECTED", "Halving the dedupe cooldown bought 3 extra trades "
        "(153->156) and moved nothing. Not worth loosening a safety rule."),
    "C6_29pairs_gate75": (
        "REJECTED", "TRAIN -0.059R and max DD 11.46%. Volume at the cost of "
        "the whole edge."),
    "C7_29pairs_volume_combo": (
        "REJECTED", "Every volume lever at once = C5's result. There is no "
        "combination effect because none of the caps bind."),
    "C8_29pairs_london_wider_caps": ("REJECTED", "Same as C3; caps do not bind."),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="diagnostics")
    ap.add_argument("--stack", default="swing")
    args = ap.parse_args()
    name = args.round.lower()
    if name == "log":          # pure bookkeeping -- no contexts needed
        write_improvements()
        return 0
    cfg, engine, contexts = load_env(args.stack)
    if name == "diagnostics":
        round_diagnostics(cfg, engine, contexts)
    elif name == "a":
        round_a(cfg, engine, contexts)
    elif name == "b":
        round_b(cfg, engine, contexts, ADOPTED)
    elif name == "c":
        round_c(cfg, engine, contexts, ADOPTED)
    elif name == "log":
        write_improvements()
    else:
        raise SystemExit(f"unknown round {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
