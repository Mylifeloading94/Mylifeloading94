#!/usr/bin/env python3
"""SMC Sniper v3 -- the SCALPING improvement loop.

Same protocol as ``tune.py``, applied to a different animal:

* every change is written down as a hypothesis BEFORE it is run;
* it is measured on TRAIN (first 50% of the window) and TEST (last 30%)
  **independently**, never pooled to make a decision;
* it is adopted only if it helps TRAIN *and* survives TEST;
* nothing selects on the full window, nothing selects on TEST;
* anything that touches exits is re-checked against the matched-R control,
  which is the only thing standing between "we raised the win rate" and "we
  shrank the target". That mistake has been caught three times in this repo.

Rounds::

    python3 tune_scalp.py --round viability   # 5m vs 15m, and cost per pair
    python3 tune_scalp.py --round s1          # score gate + cost gate frontier
    python3 tune_scalp.py --round s2          # target/stop geometry (matched-R)
    python3 tune_scalp.py --round s3          # win-rate levers
    python3 tune_scalp.py --round s4          # frequency levers
    python3 tune_scalp.py --round frontier    # the WR-vs-frequency frontier
    python3 tune_scalp.py --round final       # full validation of the adopted config
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

from smc_sniper import walkforward
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.metrics import (breakdown, compute_metrics, expectancy_ci,
                                win_rate_ci)

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "scalp")
os.makedirs(OUT, exist_ok=True)

FRACTIONS = (0.50, 0.20, 0.30)
BALANCE = 100_000.0


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def load_env(stack: str = "scalp15", profile: str = "scalp"):
    """Config + data engine + per-pair contexts (disk-cached).

    Contexts are expensive on a 47k-bar 15m frame with a 143k-bar 5m entry
    frame underneath it, and every variant in a round reuses them, so they are
    built once and pickled.
    """
    cfg = load_config().apply_profile(profile)
    cfg.set("active_stack", stack)
    cfg.set("risk.starting_balance", BALANCE)
    engine = DataEngine(cfg, source="tradelocker")
    cache = os.path.join(REPO, "smc_data", f"_ctx_{stack}_v3.pkl")
    if os.path.exists(cache):
        try:
            with open(cache, "rb") as fh:
                contexts = pickle.load(fh)
            print(f"contexts: {len(contexts)} pairs (cached)", flush=True)
            return cfg, engine, contexts
        except Exception as exc:  # noqa: BLE001
            print(f"context cache unusable ({exc}); rebuilding")
    t0 = time.time()
    contexts = Backtester(cfg, engine).build_contexts()
    print(f"contexts: {len(contexts)} pairs built in {time.time() - t0:.0f}s",
          flush=True)
    try:
        with open(cache, "wb") as fh:
            pickle.dump(contexts, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:  # noqa: BLE001
        print(f"  (context cache not written: {exc})")
    return cfg, engine, contexts


def bounds(contexts):
    start, end = walkforward.data_window(contexts)
    return walkforward.split_window(start, end, FRACTIONS)


def window_days(contexts) -> float:
    start, end = walkforward.data_window(contexts)
    return max((end - start).total_seconds() / 86400.0, 1.0)


def trading_days(frame: pd.DataFrame, span_days: float) -> float:
    """Weekday count in the span -- the honest denominator for trades/day.

    The owner asked for "3 trades a day". FX is shut at the weekend, so
    dividing by calendar days would understate the achieved rate by ~30% and
    dividing by *active* days only would overstate it by pretending the flat
    days did not happen. Weekdays is the denominator that means what the
    owner meant.
    """
    return max(span_days * 5.0 / 7.0, 1.0)


# ---------------------------------------------------------------------------
# Variant evaluation
# ---------------------------------------------------------------------------
def apply(cfg, overrides: dict):
    variant = cfg.copy()
    for dotted, value in (overrides or {}).items():
        variant.set(dotted, value)
    return variant


def evaluate(cfg, engine, contexts, overrides: dict, name: str,
             splits=None, ci: bool = False, allowed=None) -> tuple[dict, dict]:
    """Run one variant; return full / train / validation / test metrics."""
    variant = apply(cfg, overrides)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    t0 = time.time()
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False,
                          allowed_symbols=allowed)
    full = trades_to_frame(trades)
    splits = splits or bounds(contexts)
    row = {"variant": name, "seconds": round(time.time() - t0, 1)}
    frames = {"full": full}
    for split, (a, b) in splits.items():
        tr, _, _ = bt.run(contexts=contexts, start=a, end=b,
                          collect_rejections=False, allowed_symbols=allowed)
        frames[split] = trades_to_frame(tr)

    span = {"full": window_days(contexts)}
    for split, (a, b) in splits.items():
        span[split] = max((b - a).total_seconds() / 86400.0, 1.0)

    for tag, frame in frames.items():
        m = compute_metrics(frame, BALANCE)
        prefix = "" if tag == "full" else f"{tag}_"
        row[f"{prefix}n"] = m["trades"]
        row[f"{prefix}wr"] = round(m["win_rate"], 2)
        row[f"{prefix}pf"] = round(m["profit_factor"], 3)
        row[f"{prefix}exp"] = round(m["expectancy_r"], 4)
        row[f"{prefix}tpd"] = round(m["trades"] / trading_days(frame, span[tag]), 2)
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


CORE = ["variant", "n", "tpd", "wr", "pf", "exp", "max_dd",
        "train_n", "train_tpd", "train_wr", "train_pf", "train_exp",
        "test_n", "test_tpd", "test_wr", "test_pf", "test_exp"]


def show(rows, cols=None, path: str | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    cols = [c for c in (cols or CORE) if c in frame.columns]
    print(frame[cols].to_string(index=False), flush=True)
    if path:
        frame.to_csv(path, index=False)
    return frame


def subgroup(frame: pd.DataFrame, by: str, min_n: int = 0) -> pd.DataFrame:
    if frame is None or frame.empty or by not in frame:
        return pd.DataFrame()
    rows = []
    for key, group in frame.groupby(by):
        m = compute_metrics(group, BALANCE)
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
# Round: VIABILITY -- is a scalp on this broker payable at all, and where?
# ---------------------------------------------------------------------------
def round_viability(cfg, engine, contexts):
    """Cost realism first. On a scalp the spread is a large fraction of R.

    For each pair and each candidate setup timeframe this reports the median
    London/NY ATR against the round-trip cost. A pair whose typical scalp stop
    cannot clear the cost gate is not a pair with poor performance -- it is a
    pair that cannot be scalped on this broker's spreads at all, and it is
    excluded on that ground rather than on a backtested number.
    """
    rows = []
    for tf in ("5m", "15m"):
        for symbol in cfg.symbols:
            frame = engine.get(symbol, tf)
            if frame.empty:
                continue
            icfg = cfg.for_instrument(symbol)
            pip = icfg.pip
            hours = frame.index.hour
            live = frame[(hours >= 7) & (hours < 17)]      # London + NY
            atr_pips = float(np.nanmedian(live["atr"].values)) / pip
            cost = icfg.spread_pips + float(cfg.get("execution.slippage_pips", 0.2))
            rows.append({
                "tf": tf, "symbol": symbol,
                "atr_pips": round(atr_pips, 2),
                "spread_pips": icfg.spread_pips,
                "cost_pips": round(cost, 2),
                # A typical structural scalp stop is ~1.5 ATR.
                "typical_stop_pips": round(1.5 * atr_pips, 2),
                "stop_over_cost": round(1.5 * atr_pips / cost, 1),
                "cost_pct_of_R": round(100 * cost / (1.5 * atr_pips), 1),
            })
    table = pd.DataFrame(rows)
    for tf in ("5m", "15m"):
        sub = table[table.tf == tf].sort_values("stop_over_cost", ascending=False)
        print(f"\n=== cost viability on a {tf} setup "
              f"(median London/NY ATR, 1.5-ATR stop) ===")
        print(sub.drop(columns=["tf"]).to_string(index=False))
    table.to_csv(os.path.join(OUT, "cost_viability.csv"), index=False)
    return table


# ---------------------------------------------------------------------------
# Round S1 -- the two gates. Score threshold and cost threshold.
# ---------------------------------------------------------------------------
def round_s1(cfg, engine, contexts):
    """The 80/95 gate is a v2 number and cannot simply be carried over.

    On a 15m setup fewer scoring components co-occur, so the same gate means
    something different. Both gates are swept on TRAIN; TEST is reported
    alongside but is NOT what the choice is made on.
    """
    bnds = bounds(contexts)
    rows = []
    for gate in (55, 60, 65, 70, 75, 80):
        row, _ = evaluate(cfg, engine, contexts, {"scoring.threshold": gate},
                          f"S1_gate_{gate}", splits=bnds)
        rows.append(row)
        print(f"  gate {gate} done", flush=True)
    for over_cost in (0.0, 3.0, 5.0, 6.0, 8.0, 10.0):
        row, _ = evaluate(cfg, engine, contexts,
                          {"stops.min_stop_over_cost": over_cost},
                          f"S1_cost_{over_cost:g}x", splits=bnds)
        rows.append(row)
        print(f"  cost {over_cost} done", flush=True)
    return show(rows, path=os.path.join(OUT, "round_s1.csv"))


# ---------------------------------------------------------------------------
# Round S2 -- exit geometry. Every row here needs the matched-R control.
# ---------------------------------------------------------------------------
def round_s2(cfg, engine, contexts, base: dict):
    """Target and stop geometry, plus the two leads v2 flagged and never tested.

    ``S2_cost15`` and ``S2_flat4R`` are the v2 perturbation leads
    (``min_stop_over_cost`` = 15 and a flat 4R target) getting the TRAIN/TEST
    cycle they never had. A perturbation sweep is scored on the full window,
    which is exactly the selection this repo forbids, so neither was adoptable
    as it stood.
    """
    bnds = bounds(contexts)
    variants = {
        "S2_base": {},
        "S2_no_intraday_flat": {"targets.intraday.enabled": False},
        "S2_flat_17utc": {"targets.intraday.flat_by_utc_hour": 17},
        "S2_hold_48": {"targets.max_hold_bars": 48},
        "S2_hold_36": {"targets.max_hold_bars": 36},
        "S2_minrr_15": {"targets.min_rr": 1.5},
        "S2_minrr_25": {"targets.min_rr": 2.5},
        "S2_be_at_05R": {"targets.breakeven.trigger_r": 0.5},
        "S2_no_breakeven": {"targets.breakeven.enabled": False},
        "S2_tp1_70pct": {"targets.partial_tp.tp1_close_pct": 0.7,
                         "targets.partial_tp.tp2_close_pct": 0.2},
        "S2_buffer_015": {"stops.buffer_atr": 0.15},
        "S2_buffer_040": {"stops.buffer_atr": 0.40},
        # v2 leads, finally on a TRAIN/TEST cycle
        "S2_lead_cost15x": {"stops.min_stop_over_cost": 15.0},
        "S2_lead_flat4R": {"targets.mode": "fixed_rr", "targets.fixed_rr": 4.0,
                           "targets.partial_tp.enabled": False,
                           "targets.breakeven.enabled": False,
                           "targets.trailing.enabled": False},
        "S2_lead_flat2R": {"targets.mode": "fixed_rr", "targets.fixed_rr": 2.0,
                           "targets.partial_tp.enabled": False,
                           "targets.breakeven.enabled": False,
                           "targets.trailing.enabled": False},
    }
    rows = []
    for name, over in variants.items():
        merged = dict(base)
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, name, splits=bnds)
        rows.append(row)
        print(f"  {name:26s} done", flush=True)
    return show(rows, path=os.path.join(OUT, "round_s2.csv"))


# ---------------------------------------------------------------------------
# Round S3 -- the win-rate levers. This is where the real work is.
# ---------------------------------------------------------------------------
def round_s3(cfg, engine, contexts, base: dict):
    """Ways to raise win rate that are NOT "shrink the target".

    Every variant here either REMOVES setups (selection) or changes WHEN an
    entry is allowed (timing). None of them touches the target ladder, so a
    win-rate gain here is not automatically suspect. The matched-R control
    still runs on whatever is adopted -- the rule in this repo is that exits
    get re-checked, not that selection filters are trusted.
    """
    bnds = bounds(contexts)
    variants = {
        "S3_base": {},
        # -- hard gates: promote a scoring component into a requirement
        "S3_require_structure_align": {"filters.require_structure_alignment": True},
        "S3_require_ltf_confirm": {"filters.require_ltf_confirmation": True},
        "S3_require_major_sweep": {"filters.require_major_sweep": True},
        "S3_require_ob_and_fvg": {"filters.require_ob_and_fvg": True},
        "S3_align_plus_ltf": {"filters.require_structure_alignment": True,
                              "filters.require_ltf_confirmation": True},
        # -- session / hour selection (a hypothesis in this repo, never assumed)
        "S3_london_only": {"sessions.allowed": ["london"]},
        "S3_ny_only": {"sessions.allowed": ["ny"]},
        "S3_skip_lunch": {"filters.hours_exclude": [11, 12]},
        # -- pool selection
        "S3_equal_levels_only": {"filters.liquidity_include":
                                 ["equal_highs", "equal_lows"]},
        "S3_pdpw_only": {"filters.liquidity_include":
                         ["PDH", "PDL", "PWH", "PWL"]},
        "S3_keep_session_extremes": {"filters.liquidity_exclude": []},
        # -- zone quality / entry depth (context-shaping: rebuilt, not rebound)
        "S3_ob_quality_3": {"order_blocks.min_quality": 3},
        "S3_fvg_bigger": {"fvg.min_size_atr": 0.30},
        "S3_zone_close_to_price": {"fvg.max_distance_atr": 1.5},
        "S3_sweep_deeper": {"liquidity.sweep.min_pierce_atr": 0.15},
        "S3_sweep_fresher": {"liquidity.sweep.max_bars_since_sweep": 3},
        # -- entry depth into the zone: shallower fills more often but worse,
        #    deeper fills less often but better. Both directions tested.
        "S3_deeper_fill": {"fvg.entry_fill_pct": 0.75},
        "S3_shallower_fill": {"fvg.entry_fill_pct": 0.25},
    }
    return _run_variants(cfg, engine, contexts, base, variants, bnds,
                         os.path.join(OUT, "round_s3.csv"))


def _needs_rebuild(overrides: dict) -> bool:
    """Does this override reshape the PairContext itself?

    Rebinding config to a cached context only updates parameters consumed at
    signal time. Structure / liquidity / order-block / FVG parameters are baked
    into the context when it is built, so a variant touching them must rebuild
    or it silently re-measures the baseline and reports it as a result.
    """
    return any(k.startswith(("structure.", "liquidity.", "order_blocks.", "fvg."))
               for k in overrides)


def _run_variants(cfg, engine, contexts, base, variants, bnds, path):
    rows = []
    for name, over in variants.items():
        merged = dict(base)
        merged.update(over)
        ctxs = contexts
        if _needs_rebuild(merged):
            ctxs = Backtester(apply(cfg, merged), engine).build_contexts()
        row, _ = evaluate(cfg, engine, ctxs, merged, name, splits=bnds)
        row["context_rebuilt"] = "yes" if ctxs is not contexts else "no"
        rows.append(row)
        print(f"  {name:28s} n={row['n']:5d} tpd={row['tpd']:.2f} "
              f"train_exp={row['train_exp']:+.4f} test_exp={row['test_exp']:+.4f}",
              flush=True)
    return show(rows, path=path)


# ---------------------------------------------------------------------------
# Round S4 -- frequency. Volume that destroys expectancy is worthless.
# ---------------------------------------------------------------------------
def round_s4(cfg, engine, contexts, base: dict):
    bnds = bounds(contexts)
    variants = {
        "S4_base": {},
        "S4_dedupe_4": {"dedupe.cooldown_bars": 4},
        "S4_dedupe_2": {"dedupe.cooldown_bars": 2},
        "S4_dedupe_off": {"dedupe.enabled": False},
        "S4_entry_valid_16": {"entry.valid_bars": 16},
        "S4_add_late_ny": {"sessions.allowed": ["london", "ny", "late_ny"]},
        "S4_all_sessions": {"sessions.allowed":
                            ["asian", "london", "ny", "late_ny"]},
        "S4_caps_20_10": {"risk.max_trades_per_day": 20,
                          "risk.max_open_positions": 10,
                          "risk.max_exposure_per_currency": 5},
        "S4_no_streak_cooldown": {"risk.max_consecutive_losses": 999},
        "S4_zone_before_sweep_ok": {"entry.zone_must_form_after_sweep": False},
        "S4_swing_lookback_1": {"structure.swing_lookback": 1},
        "S4_pool_lookback_240": {"liquidity.pool_lookback_bars": 240},
    }
    return _run_variants(cfg, engine, contexts, base, variants, bnds,
                         os.path.join(OUT, "round_s4.csv"))


# ---------------------------------------------------------------------------
# The frontier -- the honest answer to "70% and 3 a day"
# ---------------------------------------------------------------------------
def round_frontier(cfg, engine, contexts, base: dict):
    """Win rate against frequency, both ends, on TRAIN and TEST separately.

    The owner asked for 70%+ win rate AND 3+ trades a day. Those pull in
    opposite directions, so the deliverable is not a single flattering number
    but the whole curve: what win rate survives at 3 a day, and what frequency
    survives at 70%.

    The score gate is the frequency dial. The matched-R sweep is run alongside
    it because target width is the *other* dial -- and the one that buys a win
    rate without buying any edge. Both are reported so the difference between
    them is visible rather than arguable.
    """
    bnds = bounds(contexts)
    rows = []
    for gate in (50, 55, 60, 65, 70, 75, 80):
        row, _ = evaluate(cfg, engine, contexts, {"scoring.threshold": gate},
                          f"gate_{gate}", splits=bnds, ci=True)
        row["dial"] = "score_gate"
        rows.append(row)
        print(f"  gate {gate:3d}: n={row['n']:5d} tpd={row['tpd']:.2f} "
              f"wr={row['wr']:.2f} exp={row['exp']:+.4f}", flush=True)
    frame = show(rows, cols=CORE + ["exp_ci_low", "exp_ci_high",
                                    "wr_ci_low", "wr_ci_high"],
                 path=os.path.join(OUT, "frontier_gate.csv"))

    # The target-width dial, at the adopted gate.
    rows = []
    for rr in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0):
        over = dict(base)
        over.update({"targets.mode": "fixed_rr", "targets.fixed_rr": float(rr),
                     "targets.min_rr": float(min(rr, 1.0)),
                     "targets.partial_tp.enabled": False,
                     "targets.breakeven.enabled": False,
                     "targets.trailing.enabled": False})
        row, _ = evaluate(cfg, engine, contexts, over, f"flat_{rr}R", splits=bnds)
        row["breakeven_wr_needed"] = round(100.0 / (1.0 + rr), 2)
        rows.append(row)
        print(f"  flat {rr}R: n={row['n']:5d} wr={row['wr']:.2f} "
              f"(needs {row['breakeven_wr_needed']:.1f}%) exp={row['exp']:+.4f}",
              flush=True)
    show(rows, cols=CORE + ["breakeven_wr_needed"],
         path=os.path.join(OUT, "frontier_target.csv"))
    return frame


# ---------------------------------------------------------------------------
# Adopted config -- filled in as each round is scored. See DECISIONS below.
# ---------------------------------------------------------------------------
ADOPTED: dict = {}


def round_final(cfg, engine, contexts):
    """Full validation of the adopted config: splits, walk-forward, controls."""
    from smc_sniper.walkforward import (matched_r_control, perturbation_check,
                                        walk_forward)

    variant = apply(cfg, ADOPTED)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    bnds = bounds(contexts)

    row, frames = evaluate(cfg, engine, contexts, ADOPTED, "FINAL",
                           splits=bnds, ci=True)
    print("\n=== FINAL CONFIG ===")
    print(pd.DataFrame([row]).to_string(index=False), flush=True)
    pd.DataFrame([row]).to_csv(os.path.join(OUT, "final_splits.csv"), index=False)
    frames["full"].to_csv(os.path.join(OUT, "final_trades.csv"), index=False)

    print("\n=== WALK-FORWARD (out-of-sample only) ===", flush=True)
    wf = walk_forward(bt, contexts, folds=int(cfg.get("backtest.walk_forward.folds", 5)),
                      train_frac=0.5, anchored=False, starting_balance=BALANCE)
    print(wf["folds"].to_string(index=False))
    wf["folds"].to_csv(os.path.join(OUT, "final_walkforward_folds.csv"), index=False)
    oos = wf["oos_trades"]
    om = compute_metrics(oos, BALANCE)
    span = window_days(contexts) * (int(cfg.get("backtest.walk_forward.folds", 5))
                                    / (int(cfg.get("backtest.walk_forward.folds", 5)) + 1))
    lo, hi = expectancy_ci(oos, 5000)
    wlo, whi = win_rate_ci(oos, 5000)
    print(f"\nOOS: {om['trades']} trades, {om['win_rate']:.2f}% WR "
          f"[{wlo:.2f}-{whi:.2f}], PF {om['profit_factor']:.3f}, "
          f"{om['expectancy_r']:+.4f}R [{lo:+.4f}, {hi:+.4f}], "
          f"{om['trades'] / trading_days(oos, span):.2f} trades/day", flush=True)
    pd.DataFrame([{**om, "exp_ci_low": lo, "exp_ci_high": hi,
                   "wr_ci_low": wlo, "wr_ci_high": whi,
                   "trades_per_day": om["trades"] / trading_days(oos, span)}]
                 ).to_csv(os.path.join(OUT, "final_walkforward.csv"), index=False)
    oos.to_csv(os.path.join(OUT, "final_walkforward_trades.csv"), index=False)

    print("\n=== MATCHED-R CONTROL (the anti-TP-shrinking check) ===", flush=True)
    ctrl = matched_r_control(lambda c: Backtester(c, engine), contexts, variant,
                             r_values=(0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0),
                             starting_balance=BALANCE)
    print(ctrl.to_string(index=False))
    ctrl.to_csv(os.path.join(OUT, "final_matched_r.csv"), index=False)

    print("\n=== PERTURBATION ===", flush=True)
    params = {
        "scoring.threshold": [60, 65, 70],
        "stops.min_stop_over_cost": [4.0, 6.0, 8.0],
        "stops.buffer_atr": [0.20, 0.25, 0.35],
        "targets.min_rr": [1.5, 2.0, 2.5],
        "fvg.min_size_atr": [0.14, 0.18, 0.25],
        "structure.swing_lookback": [2, 3],
    }
    pert = perturbation_check(
        lambda c: Backtester(c, engine), contexts, variant, params,
        starting_balance=BALANCE,
        rebuild_fn=lambda c: Backtester(c, engine).build_contexts())
    print(pert.to_string(index=False))
    pert.to_csv(os.path.join(OUT, "final_perturbation.csv"), index=False)

    print("\n=== PER-PAIR (cost viability shows up here) ===", flush=True)
    per_pair = breakdown(frames["full"], "symbol", BALANCE)
    print(per_pair.to_string(index=False))
    per_pair.to_csv(os.path.join(OUT, "final_per_pair.csv"), index=False)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="viability")
    ap.add_argument("--stack", default="scalp15")
    ap.add_argument("--profile", default="scalp")
    args = ap.parse_args()
    name = args.round.lower()
    cfg, engine, contexts = load_env(args.stack, args.profile)
    if name == "viability":
        round_viability(cfg, engine, contexts)
    elif name == "s1":
        round_s1(cfg, engine, contexts)
    elif name == "s2":
        round_s2(cfg, engine, contexts, ADOPTED)
    elif name == "s3":
        round_s3(cfg, engine, contexts, ADOPTED)
    elif name == "s4":
        round_s4(cfg, engine, contexts, ADOPTED)
    elif name == "frontier":
        round_frontier(cfg, engine, contexts, ADOPTED)
    elif name == "final":
        round_final(cfg, engine, contexts)
    else:
        raise SystemExit(f"unknown round {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
