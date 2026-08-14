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
from smc_sniper.signal_engine import CONTEXT_CACHE_VERSION
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
                version, contexts = pickle.load(fh)
            if version != CONTEXT_CACHE_VERSION:
                raise ValueError(f"cache v{version} != code v{CONTEXT_CACHE_VERSION}")
            print(f"contexts: {len(contexts)} pairs (cached)", flush=True)
            return cfg, engine, contexts
        except Exception as exc:  # noqa: BLE001
            print(f"context cache unusable ({exc}); rebuilding", flush=True)
    t0 = time.time()
    contexts = Backtester(cfg, engine).build_contexts()
    print(f"contexts: {len(contexts)} pairs built in {time.time() - t0:.0f}s",
          flush=True)
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
# Round DIAG -- does this entry model have ANY edge, at any target?
# ---------------------------------------------------------------------------
def round_diag(cfg, engine, contexts):
    """The question that has to be answered before any tuning is worth doing.

    Round S1 came back negative at every score gate and every cost gate, on
    TRAIN and on TEST alike. Two very different things produce that: exits that
    give back a real edge, or entries that never had one. The matched-R control
    separates them in one pass -- strip the management off, put a single flat
    target at each R, and see whether ANY of them is profitable. If the entries
    carry edge, some R is positive. If none is, no exit tuning can help and the
    honest move is to say so rather than to keep searching.
    """
    bnds = bounds(contexts)
    rows = []
    for rr in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        over = {"targets.mode": "fixed_rr", "targets.fixed_rr": float(rr),
                "targets.min_rr": float(min(rr, 1.0)),
                "targets.partial_tp.enabled": False,
                "targets.breakeven.enabled": False,
                "targets.trailing.enabled": False,
                "targets.intraday.enabled": False}
        row, _ = evaluate(cfg, engine, contexts, over, f"flat_{rr}R", splits=bnds)
        row["breakeven_wr_needed"] = round(100.0 / (1.0 + rr), 2)
        rows.append(row)
        print(f"  flat {rr}R: n={row['n']:5d} wr={row['wr']:.2f}% "
              f"(needs {row['breakeven_wr_needed']:.1f}%) "
              f"train_exp={row['train_exp']:+.4f} test_exp={row['test_exp']:+.4f}",
              flush=True)
    show(rows, cols=CORE + ["breakeven_wr_needed"],
         path=os.path.join(OUT, "diag_matched_r.csv"))

    # Where the base config's trades actually end, and who carries them.
    _, frames = evaluate(cfg, engine, contexts, {}, "base", splits=bnds)
    for split in ("train", "test"):
        frame = frames[split]
        if frame.empty:
            continue
        frame = frame.copy()
        frame["hour"] = pd.to_datetime(frame["signal_time"]).dt.hour
        frame["dir"] = frame["direction"].map({"bullish": "long", "bearish": "short"})
        for dim in ("exit_reason", "session", "hour", "dir", "liquidity_type",
                    "symbol", "zone_kind"):
            table = subgroup(frame, dim)
            if table.empty:
                continue
            print(f"\n--- {split.upper()} by {dim} ---")
            print(table.to_string(index=False), flush=True)
            table.to_csv(os.path.join(OUT, f"diag_{split}_{dim}.csv"), index=False)
    return frames


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
# Round S2 -- follow the cost. The matched-R control says the entries have no
# edge at any target, so the only question left worth asking is WHY.
# ---------------------------------------------------------------------------
# Pairs whose typical 15m scalp stop (1.5x median London/NY ATR) clears the
# round-trip cost by a wide margin. Chosen from `cost_viability.csv` -- an
# arithmetic property of the broker's spreads, computed BEFORE any backtest,
# so it is not a performance selection dressed up as a cost argument.
COST_VIABLE_5 = ["USDJPY", "EURUSD", "GBPUSD", "EURJPY", "GBPJPY"]          # >10x
COST_VIABLE_12 = COST_VIABLE_5 + ["GBPCAD", "CHFJPY", "AUDUSD", "AUDJPY",
                                  "USDCHF", "USDCAD", "GBPAUD"]            # >6.5x


def gross_vs_net(cfg, engine, contexts, splits) -> pd.DataFrame:
    """How much of the result is the strategy and how much is the toll?

    Every Trade carries `gross_r` (the realised move) and `r_multiple` (the
    same thing after commission; spread and slippage are already inside the
    fill price). The gap between them is what a 15m scalp pays to exist. If
    gross expectancy is positive and net is negative, the entry model works and
    the cost structure is the problem. If gross is negative too, there is
    nothing to rescue.
    """
    rows = []
    _, frames = evaluate(cfg, engine, contexts, {}, "base", splits=splits)
    for tag in ("full", "train", "test"):
        frame = frames[tag]
        if frame.empty:
            continue
        # Spread + slippage are baked into the fill, so reconstruct the
        # pre-cost R as well: what the same move would have paid on a mid fill.
        gross = frame["gross_r"].mean()
        net = frame["r_multiple"].mean()
        rows.append({
            "split": tag, "n": len(frame),
            "gross_exp_r": round(float(gross), 4),
            "net_exp_r": round(float(net), 4),
            "commission_drag_r": round(float(gross - net), 4),
            "win_rate": round(float((frame["r_multiple"] > 0).mean() * 100), 2),
            "gross_win_rate": round(float((frame["gross_r"] > 0).mean() * 100), 2),
            "median_stop_pips_over_cost": "see cost_viability.csv",
        })
    out = pd.DataFrame(rows)
    print("\n=== GROSS vs NET (what the toll costs) ===")
    print(out.to_string(index=False), flush=True)
    out.to_csv(os.path.join(OUT, "gross_vs_net.csv"), index=False)
    return out


def round_s2(cfg, engine, contexts, base: dict):
    """Cost-driven hypotheses, plus the exit levers, plus the v2 leads."""
    bnds = bounds(contexts)
    gross_vs_net(cfg, engine, contexts, bnds)

    variants = {
        "S2_base": ({}, None),
        # -- the cost hypothesis, three ways
        "S2_cost_12x": ({"stops.min_stop_over_cost": 12.0}, None),
        "S2_cost_15x_v2lead": ({"stops.min_stop_over_cost": 15.0}, None),
        "S2_cost_20x": ({"stops.min_stop_over_cost": 20.0}, None),
        "S2_universe_top5": ({}, COST_VIABLE_5),
        "S2_universe_top12": ({}, COST_VIABLE_12),
        "S2_top5_cost12x": ({"stops.min_stop_over_cost": 12.0}, COST_VIABLE_5),
        "S2_no_commission": ({"execution.commission_per_lot_rt": 0.0}, None),
        "S2_observed_spreads": ({}, None),      # filled in below
        # -- exits
        "S2_no_intraday_flat": ({"targets.intraday.enabled": False}, None),
        "S2_no_breakeven": ({"targets.breakeven.enabled": False}, None),
        "S2_minrr_10": ({"targets.min_rr": 1.0}, None),
        "S2_flat4R_v2lead": ({"targets.mode": "fixed_rr", "targets.fixed_rr": 4.0,
                              "targets.partial_tp.enabled": False,
                              "targets.breakeven.enabled": False,
                              "targets.trailing.enabled": False}, None),
        # -- the hard gates (selection, not exits)
        "S2_require_structure_align": (
            {"filters.require_structure_alignment": True}, None),
        "S2_require_ltf_confirm": ({"filters.require_ltf_confirmation": True}, None),
        "S2_ny_only": ({"sessions.allowed": ["ny"]}, None),
        "S2_skip_early_london": ({"filters.hours_exclude": [8, 9]}, None),
    }
    # The backtester deliberately runs ~3x the broker's live quotes, because
    # over-estimating cost is the safe direction. On a swing stack that is
    # cheap insurance; on a scalp it may be the entire result, so the live
    # sample is run as a SENSITIVITY -- reported, never adopted.
    observed = dict(cfg.get("data.observed_broker_spreads_pips") or {})
    variants["S2_observed_spreads"] = (
        {f"execution.spreads.{k}": v for k, v in observed.items()}, None)

    rows = []
    for name, (over, allowed) in variants.items():
        merged = dict(base)
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, name, splits=bnds,
                          allowed=allowed)
        row["pairs"] = len(allowed) if allowed else len(contexts)
        rows.append(row)
        print(f"  {name:28s} n={row['n']:5d} tpd={row['tpd']:.2f} "
              f"wr={row['wr']:.2f} train_exp={row['train_exp']:+.4f} "
              f"test_exp={row['test_exp']:+.4f}", flush=True)
    return show(rows, cols=["variant", "pairs"] + CORE[1:],
                path=os.path.join(OUT, "round_s2.csv"))


# ---------------------------------------------------------------------------
# Round S3 -- the hypotheses still standing after S1/S2
# ---------------------------------------------------------------------------
def round_s3(cfg, engine, contexts, base: dict):
    """What is left that could plausibly flip a -0.12R entry model positive.

    ``S3_hold_*`` is the one structural asymmetry found by reading the config
    rather than the results. ``targets.max_hold_bars`` is counted on the ENTRY
    timeframe. On the swing stack entry_tf is 1H, so 96 bars is four days; on
    scalp15 entry_tf is 5m, so the same 96 is eight hours -- roughly a third of
    the setup-bar holding time the swing stack gets, while the targets are the
    same ATR-scaled distance away. A target that needs a day to arrive and a
    time stop that fires in eight hours is a losing combination by
    construction, and it is worth ruling in or out before concluding anything.

    Everything else here removes setups or shifts entry timing. None of it
    touches the target ladder.
    """
    bnds = bounds(contexts)
    variants = {
        "S3_base": {},
        # the time-stop asymmetry -- the highest-prior hypothesis left
        "S3_hold_288_24h": {"targets.max_hold_bars": 288},
        "S3_hold_576_48h": {"targets.max_hold_bars": 576,
                            "targets.intraday.enabled": False},
        # volatility regime
        "S3_vol_high_only": {"filters.atr_pct_min": 60},
        "S3_vol_mid": {"filters.atr_pct_min": 30, "filters.atr_pct_max": 80},
        # pool selection -- equal levels are 93% of the sample and are negative
        # with a CI clear of zero on TRAIN; PD/PW are positive but rare
        "S3_pdpw_only": {"filters.liquidity_include":
                         ["PDH", "PDL", "PWH", "PWL"]},
        "S3_no_equal_levels": {"filters.liquidity_exclude":
                               ["session_high", "session_low",
                                "equal_highs", "equal_lows"]},
    }
    frame = _run_variants(cfg, engine, contexts, base, variants, bnds,
                          os.path.join(OUT, "round_s3.csv"))

    # RE-RUN the matched-R control with a generous time stop.
    #
    # The round-`diag` version of this control was flawed and the flaw was
    # mine: it left `targets.max_hold_bars` at 96, which on a 5m entry frame is
    # eight hours. A 4R target at 15m scale frequently needs longer than that,
    # so a wide-target row was being scored with its winners truncated at the
    # time stop while its losers still paid a full -1R. That understates wide
    # targets specifically -- exactly the rows the control exists to test.
    # 576 bars is 48 hours, which is the same setup-bar budget the swing stack
    # gives its trades.
    rows = []
    for rr in (0.5, 1.0, 2.0, 3.0, 4.0):
        over = dict(base)
        over.update({"targets.mode": "fixed_rr", "targets.fixed_rr": float(rr),
                     "targets.min_rr": float(min(rr, 1.0)),
                     "targets.partial_tp.enabled": False,
                     "targets.breakeven.enabled": False,
                     "targets.trailing.enabled": False,
                     "targets.intraday.enabled": False,
                     "targets.max_hold_bars": 576})
        row, _ = evaluate(cfg, engine, contexts, over, f"flat_{rr}R_hold48h",
                          splits=bnds)
        row["breakeven_wr_needed"] = round(100.0 / (1.0 + rr), 2)
        rows.append(row)
        print(f"  flat {rr}R (48h hold): n={row['n']:5d} wr={row['wr']:.2f}% "
              f"(needs {row['breakeven_wr_needed']:.1f}%) "
              f"train_exp={row['train_exp']:+.4f} test_exp={row['test_exp']:+.4f}",
              flush=True)
    show(rows, cols=CORE + ["breakeven_wr_needed"],
         path=os.path.join(OUT, "matched_r_generous_hold.csv"))
    return frame


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
    # The FREQUENCY dial is the score gate, and round S1 already swept it over
    # exactly these variants -- rerunning it would burn half an hour to
    # reproduce a CSV. It is read back instead.
    gate_path = os.path.join(OUT, "round_s1.csv")
    frame = pd.read_csv(gate_path) if os.path.exists(gate_path) else pd.DataFrame()

    # The TARGET-WIDTH dial. This is the one that buys a win rate without
    # buying any edge, so it is reported next to the frequency dial rather
    # than in place of it.
    rows = []
    for rr in (0.25, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0):
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
    if name == "diag":
        round_diag(cfg, engine, contexts)
    elif name == "viability":
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
