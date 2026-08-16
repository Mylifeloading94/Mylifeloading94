#!/usr/bin/env python3
"""SMC Sniper v5 -- the audit and improvement loop.

This is the harness the v5 work was actually done with, so every table in the
skill doc is reproducible rather than asserted.

The protocol, unchanged from v2 and v3 and with no exceptions:

* a change is written down as a hypothesis BEFORE it is run;
* it is measured on TRAIN (first 50% of the window) and TEST (last 30%)
  **independently**, never pooled to make a decision;
* it is adopted only if it helps TRAIN *and* survives TEST;
* nothing selects on the full window, and nothing selects on TEST.

Two things are new in v5 and both are about honesty rather than performance:

* every audit fix ships behind a flag defaulting to the OLD behaviour, so
  ``run_backtest.py --stack swing`` keeps reproducing v2's published
  153 trades / 54.90% / PF 1.260 / +0.114R forever -- ``--round regress``
  checks exactly that;
* the headline configuration takes several positions on one liquidity event, so
  a **cluster bootstrap** is used alongside the ordinary one. Resampling trades
  as if they were independent when 44% of them are re-entries on the same setup
  reports an interval that is too narrow, and the difference decides whether
  this system's edge is established or merely encouraging.

Usage::

    python3 tune_v5.py --round regress    # v2 must still be bit-for-bit
    python3 tune_v5.py --round fixes      # what each audit fix costs
    python3 tune_v5.py --round entry      # entry mechanics / stops / sequencing
    python3 tune_v5.py --round rr         # the reward-to-risk frontier
    python3 tune_v5.py --round hold       # the time stop, matched-R
    python3 tune_v5.py --round qual       # setup-quality filters
    python3 tune_v5.py --round misc       # caps, universe, the off-by-one
    python3 tune_v5.py --round dedupe     # the one change that worked
    python3 tune_v5.py --round cluster    # and the interval that prices it
    python3 tune_v5.py --round freq       # 30m: is there a rung below 1H?
    python3 tune_v5.py --round final      # splits + walk-forward on the frozen config
    python3 tune_v5.py --round perturb    # robustness of the frozen config

Results land in ``reports/v5/``.
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
from smc_sniper.metrics import compute_metrics, expectancy_ci, win_rate_ci
from smc_sniper.signal_engine import CONTEXT_CACHE_VERSION

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v5")
os.makedirs(OUT, exist_ok=True)

FRACTIONS = (0.50, 0.20, 0.30)

# The context-shaping half of the audit. It changes what a PairContext IS, so it
# has to be applied before the context is built and gets its own cache slot.
CTX_FIX = {"order_blocks.causal_structure_association": True}
# The rest of the audit -- consumed at signal/fill time, so a cached context can
# simply be rebound.
RUN_FIX = {"risk.quote_ccy_conversion": True, "risk.book_on_exit": True,
           "execution.tp_trade_through": True, "entry.exact_expiry": True}


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def load_env(stack="swing", source="tradelocker", ctx_over=None, tag=""):
    cfg = load_config()
    cfg.set("active_stack", stack)
    for key, value in (ctx_over or {}).items():
        cfg.set(key, value)
    engine = DataEngine(cfg, source=source)
    cache = os.path.join(REPO, "smc_data", f"_ctx_{stack}_{source}{tag}.pkl")
    if os.path.exists(cache):
        try:
            with open(cache, "rb") as fh:
                version, contexts = pickle.load(fh)
            if version != CONTEXT_CACHE_VERSION:
                raise ValueError(f"cache v{version} != code v{CONTEXT_CACHE_VERSION}")
            print(f"contexts: {len(contexts)} pairs (cached {stack}{tag})", flush=True)
            return cfg, engine, contexts
        except Exception as exc:  # noqa: BLE001
            print(f"context cache unusable ({exc}); rebuilding", flush=True)
    t0 = time.time()
    contexts = Backtester(cfg, engine).build_contexts()
    print(f"contexts: {len(contexts)} pairs built in {time.time() - t0:.0f}s", flush=True)
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


def apply(cfg, overrides):
    variant = cfg.copy()
    for dotted, value in (overrides or {}).items():
        variant.set(dotted, value)
    return variant


def evaluate(cfg, engine, contexts, overrides, name, balance=10000.0,
             splits=None, ci=False, allowed=None):
    """One variant, scored on the full window and on each split independently."""
    variant = apply(cfg, overrides)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False,
                          allowed_symbols=allowed)
    full = trades_to_frame(trades)
    row = {"variant": name}
    frames = {"full": full}
    for split, (a, b) in (splits or bounds(contexts)).items():
        tr, _, _ = bt.run(contexts=contexts, start=a, end=b,
                          collect_rejections=False, allowed_symbols=allowed)
        frames[split] = trades_to_frame(tr)
    if not full.empty:
        span = (pd.to_datetime(full.exit_time).max()
                - pd.to_datetime(full.signal_time).min()).days or 1
        row["per_day"] = round(len(full) / span, 3)
    else:
        row["per_day"] = 0.0
    for tag, frame in frames.items():
        m = compute_metrics(frame, balance)
        prefix = "" if tag == "full" else f"{tag}_"
        row[f"{prefix}n"] = m["trades"]
        row[f"{prefix}wr"] = round(m["win_rate"], 2)
        row[f"{prefix}pf"] = round(m["profit_factor"], 3)
        row[f"{prefix}exp"] = round(m["expectancy_r"], 4)
        if tag == "full":
            row["max_dd"] = round(m["max_drawdown_pct"], 2)
            row["total_r"] = round(m.get("total_r", 0.0), 2)
            row["max_loss_streak"] = m.get("max_consecutive_losses", 0)
            row["scratches"] = m.get("scratches", 0)
    if ci and not full.empty:
        lo, hi = expectancy_ci(full, 5000)
        row["ci_lo"], row["ci_hi"] = round(lo, 4), round(hi, 4)
    return row, frames


COLS = ["variant", "n", "per_day", "wr", "pf", "exp", "train_n", "train_exp",
        "test_n", "test_exp", "max_dd"]


def show(rows, cols=None, name=None):
    frame = pd.DataFrame(rows)
    use = [c for c in (cols or COLS) if c in frame.columns]
    print(frame[use].to_string(index=False), flush=True)
    if name:
        frame.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    return frame


def sweep(cfg, engine, contexts, variants, name, base=None, ci=False, allowed_map=None):
    rows = []
    for label, over in variants.items():
        merged = dict(base or {})
        merged.update(over)
        row, _ = evaluate(cfg, engine, contexts, merged, label, ci=ci,
                          allowed=(allowed_map or {}).get(label))
        rows.append(row)
        show([row])
    print(f"\n=== {name.upper()} ===")
    return show(rows, name=name)


# ---------------------------------------------------------------------------
# Cluster bootstrap -- the interval that prices this system's own correlation
# ---------------------------------------------------------------------------
def cluster_ids(frame: pd.DataFrame, hours: float = 24.0) -> pd.DataFrame:
    """Label runs of same-symbol, same-direction trades signalled within ``hours``.

    Several entries off one liquidity sweep are one bet wearing several hats.
    Counting them as separate observations is how a bootstrap ends up claiming
    more evidence than the market supplied.
    """
    f = frame.sort_values("signal_time").reset_index(drop=True)
    ids = np.zeros(len(f), dtype=int)
    nxt = 0
    last: dict = {}
    for i, row in f.iterrows():
        key = (row.symbol, row.direction)
        prev = last.get(key)
        if prev is not None and (row.signal_time - prev[1]).total_seconds() <= hours * 3600:
            ids[i] = prev[0]
        else:
            ids[i] = nxt
            nxt += 1
        last[key] = (ids[i], row.signal_time)
    f["cluster"] = ids
    return f


def cluster_bootstrap(frame, iterations=5000, ci=0.95, seed=7, hours=24.0):
    """Percentile bootstrap that draws whole clusters rather than single trades."""
    f = cluster_ids(frame, hours)
    groups = [g["r_multiple"].values for _, g in f.groupby("cluster")]
    n_c = len(groups)
    rng = np.random.default_rng(seed)
    stats = np.empty(iterations)
    for it in range(iterations):
        pick = rng.integers(0, n_c, size=n_c)
        stats[it] = np.concatenate([groups[k] for k in pick]).mean()
    lo = (1 - ci) / 2 * 100
    return float(np.percentile(stats, lo)), float(np.percentile(stats, 100 - lo)), n_c


def full_report(name, cfg, engine, contexts, over):
    variant = apply(cfg, over)
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
    f = trades_to_frame(trades)
    m = compute_metrics(f, 10000.0)
    lo, hi = expectancy_ci(f, 5000)
    clo, chi, n_c = cluster_bootstrap(f, 5000)
    wlo, whi = win_rate_ci(f, 5000)
    span = (pd.to_datetime(f.exit_time).max() - pd.to_datetime(f.signal_time).min()).days
    print(f"\n=== {name} ===")
    print(f"  trades {m['trades']}  INDEPENDENT CLUSTERS {n_c}  per_day {m['trades']/span:.3f}")
    print(f"  WR {m['win_rate']:.2f}% [{wlo:.2f}, {whi:.2f}]  PF {m['profit_factor']:.3f}  "
          f"E {m['expectancy_r']:+.4f}R")
    print(f"  maxDD {m['max_drawdown_pct']:.2f}%  longest losing streak "
          f"{m['max_consecutive_losses']}  scratches {m['scratches']}")
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
    print(pd.DataFrame(wf["folds"])[
        ["fold", "fit_end", "oos_end", "fit_trades", "fit_exp_r",
         "oos_trades", "oos_wr", "oos_exp_r"]].to_string(index=False))
    oos, om = wf["oos_trades"], wf["oos_metrics"]
    olo, ohi = expectancy_ci(oos, 5000)
    oclo, ochi, onc = cluster_bootstrap(oos, 5000)
    print(f"  WALK-FORWARD OOS n={om['trades']} ({onc} clusters)  "
          f"WR {om['win_rate']:.2f}%  PF {om['profit_factor']:.3f}  "
          f"E {om['expectancy_r']:+.4f}R")
    print(f"    naive   CI [{olo:+.4f}, {ohi:+.4f}]")
    print(f"    CLUSTER CI [{oclo:+.4f}, {ochi:+.4f}]  "
          f"{'SPANS ZERO' if oclo < 0 < ochi else 'CLEAR OF ZERO'}")
    f.to_csv(os.path.join(OUT, f"ledger_{name.replace(' ', '_').replace('+', '')}.csv"),
             index=False)
    return f


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------
def round_regress():
    """v2 must still be bit-for-bit. Every audit flag defaults to OFF for this."""
    cfg, engine, contexts = load_env("swing")
    row, _ = evaluate(cfg, engine, contexts, {}, "v2 REGRESSION")
    print(pd.Series(row).to_string())
    ok = (row["n"] == 153 and abs(row["wr"] - 54.90) < 0.01
          and abs(row["pf"] - 1.260) < 0.001 and abs(row["exp"] - 0.1144) < 0.0001
          and abs(row["max_dd"] - 3.98) < 0.01)
    print("\nV2 REGRESSION:", "PASS" if ok else "*** FAIL ***")
    return 0 if ok else 1


def round_fixes():
    """What each audit fix costs, one at a time and together."""
    cfg, engine, contexts = load_env("swing")
    sweep(cfg, engine, contexts, {
        "v2 baseline": {},
        "+quote_ccy_conversion": {"risk.quote_ccy_conversion": True},
        "+book_on_exit": {"risk.book_on_exit": True},
        "+tp_trade_through": {"execution.tp_trade_through": True},
        "+exact_expiry": {"entry.exact_expiry": True},
        "+exact_expiry, valid_bars 9": {"entry.exact_expiry": True,
                                        "entry.valid_bars": 9},
        "all run-time fixes": dict(RUN_FIX),
    }, "fixes_runtime")
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    sweep(cfg, engine, contexts, {
        "+causal OB association": {},
        "ALL EIGHT AUDIT FIXES": dict(RUN_FIX),
    }, "fixes_all", ci=True)
    return 0


def round_entry():
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    variants = {"BASE (all fixes)": {}}
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        variants[f"fill_pct {v}"] = {"fvg.entry_fill_pct": v}
    for v in (4, 6, 12, 16):
        variants[f"valid_bars {v}"] = {"entry.valid_bars": v}
    variants["zone after sweep OFF"] = {"entry.zone_must_form_after_sweep": False}
    for v in (3, 4, 8, 10):
        variants[f"max_bars_since_sweep {v}"] = {"liquidity.sweep.max_bars_since_sweep": v}
    for v in (0.15, 0.35, 0.50):
        variants[f"buffer_atr {v}"] = {"stops.buffer_atr": v}
    for v in (0.50, 0.65, 1.00, 1.30):
        variants[f"min_stop_atr {v}"] = {"stops.min_stop_atr": v}
    for v in (0.65, 0.75, 0.95):
        variants[f"pd_hard_veto {v}"] = {"premium_discount.hard_veto_beyond": v}
    sweep(cfg, engine, contexts, variants, "round_entry", base=RUN_FIX)
    return 0


def round_rr():
    """The matched-R control, ENTRY-MATCHED (audit defect 7)."""
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    flat = {"targets.mode": "fixed_rr", "targets.partial_tp.enabled": False,
            "targets.breakeven.enabled": False, "targets.trailing.enabled": False,
            "targets.min_rr_on_liquidity": True}
    variants = {"ladder (base)": {},
                "ladder, min_rr on liquidity": {"targets.min_rr_on_liquidity": True}}
    for rr in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0):
        over = dict(flat)
        over["targets.fixed_rr"] = rr
        variants[f"flat {rr}R"] = over
    variants["ladder, no BE"] = {"targets.breakeven.enabled": False}
    variants["ladder, no trail"] = {"targets.trailing.enabled": False}
    variants["ladder, no partials"] = {"targets.partial_tp.enabled": False}
    for gate in (75, 70, 65):
        variants[f"ladder gate {gate}"] = {
            "scoring.threshold": gate, "risk.max_trades_per_day": 30,
            "risk.max_open_positions": 8, "risk.max_exposure_per_currency": 4,
            "risk.enforce_concurrency": True}
    sweep(cfg, engine, contexts, variants, "round_rr", base=RUN_FIX,
          ci=False)
    return 0


def round_hold():
    """The time stop against a wide target. Matched-R: 2R and 4R, same sweep."""
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    cfg = cfg.apply_profile("v5")
    cfg.set("active_stack", "swing")
    rows = []
    for rr in (2.0, 4.0):
        for hold in (48, 96, 192, 384, 720):
            row, frames = evaluate(cfg, engine, contexts,
                                   {"targets.max_hold_bars": hold,
                                    "targets.fixed_rr": rr}, f"{rr:g}R hold {hold}h")
            f = frames["full"]
            if not f.empty:
                row["pct_time_stop"] = round((f.exit_reason == "time_stop").mean() * 100, 1)
                row["avg_win_r"] = round(f[f.r_multiple > 0].r_multiple.mean(), 3)
            rows.append(row)
            show([row], COLS + ["pct_time_stop", "avg_win_r"])
    print("\n=== ROUND HOLD ===")
    show(rows, COLS + ["pct_time_stop", "avg_win_r"], name="round_hold")
    return 0


def round_qual():
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    sweep(cfg, engine, contexts, {
        "BASE": {},
        "require OB and FVG": {"filters.require_ob_and_fvg": True},
        "require structure align": {"filters.require_structure_alignment": True},
        "require LTF confirm": {"filters.require_ltf_confirmation": True},
        "require major sweep": {"filters.require_major_sweep": True},
        "gate 85": {"scoring.threshold": 85},
        "min_stop_over_cost 15": {"stops.min_stop_over_cost": 15.0},
        "min_stop_over_cost 6": {"stops.min_stop_over_cost": 6.0},
        "min_rr 2.5": {"targets.min_rr": 2.5},
        "dedupe cooldown 4": {"dedupe.cooldown_bars": 4},
        "dedupe cooldown 16": {"dedupe.cooldown_bars": 16},
        "no dedupe": {"dedupe.enabled": False},
        "sessions +late_ny": {"sessions.allowed": ["london", "ny", "late_ny"]},
        "sessions +asian": {"sessions.allowed": ["asian", "london", "ny", "late_ny"]},
    }, "round_qual", base=RUN_FIX)
    return 0


def round_misc():
    orig13 = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
              "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "CADJPY", "XAUUSD"]
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    sweep(cfg, engine, contexts, {
        "BASE": {},
        "enforce_concurrency ON": {"risk.enforce_concurrency": True},
        "max_trades_per_day 12": {"risk.max_trades_per_day": 12},
        "no consec-loss cooldown": {"risk.max_consecutive_losses": 999},
        "13-pair universe": {},
        "structural invalidation ON": {"filters.structural_invalidation.enabled": True},
    }, "round_misc", base=RUN_FIX, allowed_map={"13-pair universe": orig13})
    # context-shaping variants need their own build
    rows = []
    for label, over in {"OB min_quality 3": {"order_blocks.min_quality": 3},
                        "equal_level touches 3": {"liquidity.equal_level_min_touches": 3}}.items():
        shaped = dict(CTX_FIX)
        shaped.update(over)
        c2, e2, x2 = load_env("swing", ctx_over=shaped,
                              tag="_causal_" + label.split()[0] + str(list(over.values())[0]))
        row, _ = evaluate(c2, e2, x2, RUN_FIX, label)
        rows.append(row)
        show([row])
    show(rows, name="round_misc_ctx")
    return 0


def round_dedupe():
    """The one change that improved TRAIN, TEST, frequency and drawdown."""
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    cfg = cfg.apply_profile("v5")
    cfg.set("active_stack", "swing")
    rows = []
    for label, over in {
        "v5 SHIPPED": {},
        "dedupe ON (cooldown 8)": {"dedupe.enabled": True,
                                   "risk.enforce_concurrency": False},
        "dedupe cooldown 4": {"dedupe.enabled": True, "dedupe.cooldown_bars": 4,
                              "risk.enforce_concurrency": False},
        "dedupe cooldown 2": {"dedupe.enabled": True, "dedupe.cooldown_bars": 2,
                              "risk.enforce_concurrency": False},
        "dedupe OFF, no concurrency": {"risk.enforce_concurrency": False},
    }.items():
        row, frames = evaluate(cfg, engine, contexts, over, label, ci=True)
        f = frames["full"]
        if not f.empty:
            events = []
            for _, t in f.iterrows():
                events += [(t.signal_time, 1), (t.exit_time, -1)]
            events.sort()
            cur = peak = 0
            for _, step in events:
                cur += step
                peak = max(peak, cur)
            row["max_concurrent"] = peak
            row["clusters"] = int(cluster_ids(f)["cluster"].nunique())
        rows.append(row)
        show([row], COLS + ["ci_lo", "ci_hi", "max_concurrent", "clusters"])
    print("\n=== ROUND DEDUPE ===")
    show(rows, COLS + ["ci_lo", "ci_hi", "max_loss_streak", "max_concurrent", "clusters"],
         name="round_dedupe")
    return 0


def round_cluster():
    """Naive vs cluster bootstrap on the three configurations that matter."""
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    cfg = cfg.apply_profile("v5")
    cfg.set("active_stack", "swing")
    full_report("dedupe ON", cfg, engine, contexts,
                {"dedupe.enabled": True, "risk.enforce_concurrency": False})
    full_report("dedupe OFF", cfg, engine, contexts,
                {"risk.enforce_concurrency": False})
    full_report("dedupe OFF + concurrency (SHIPPED)", cfg, engine, contexts, {})
    return 0


def round_freq(stack="mid30_swing"):
    """Is there a rung between the 1H model that works and the 15m one that does not?"""
    cfg, engine, contexts = load_env(stack, ctx_over=CTX_FIX, tag="_causal")
    base = dict(RUN_FIX)
    base.update({"risk.max_trades_per_day": 30, "risk.max_open_positions": 8,
                 "risk.max_exposure_per_currency": 4, "risk.enforce_concurrency": True})
    sweep(cfg, engine, contexts,
          {f"{stack} gate {g}": {"scoring.threshold": g}
           for g in (80, 75, 70, 65, 60, 55)},
          f"round_freq_{stack}", base=base)
    return 0


def round_final():
    cfg, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    cfg = cfg.apply_profile("v5")
    cfg.set("active_stack", "swing")
    full_report("v5 FINAL", cfg, engine, contexts, {})
    return 0


def round_perturb():
    """Robustness of the FROZEN config. Nothing here selects."""
    base, engine, contexts = load_env("swing", ctx_over=CTX_FIX, tag="_causal")
    base = base.apply_profile("v5")
    base.set("active_stack", "swing")
    params = {
        "scoring.threshold": [75, 78, 80, 82, 85],
        "stops.buffer_atr": [0.20, 0.25, 0.30, 0.35],
        "stops.min_stop_atr": [0.65, 0.80, 1.00],
        "stops.min_stop_over_cost": [6.0, 10.0, 15.0],
        "targets.fixed_rr": [3.0, 3.5, 4.0, 4.5, 5.0],
        "targets.min_rr": [1.5, 2.0, 2.5],
        "fvg.entry_fill_pct": [0.4, 0.5, 0.6],
        "entry.valid_bars": [6, 8, 10],
        "dedupe.cooldown_bars": [2, 8],
        "fvg.min_size_atr": [0.14, 0.18, 0.25],
    }
    rows = []
    for dotted, values in params.items():
        rebuild = walkforward.needs_rebuild(dotted)
        for value in values:
            if rebuild:
                shaped = dict(CTX_FIX)
                shaped[dotted] = value
                cfgv, eng, ctxs = load_env(
                    "swing", ctx_over=shaped,
                    tag="_p_" + dotted.replace(".", "_") + f"_{value}")
                cfgv = cfgv.apply_profile("v5")
                cfgv.set("active_stack", "swing")
                cfgv.set(dotted, value)
                bt = Backtester(cfgv, eng)
                trades, _, _ = bt.run(contexts=ctxs, collect_rejections=False)
            else:
                cfgv = base.copy()
                cfgv.set(dotted, value)
                bt = Backtester(cfgv, engine)
                bt.bind(contexts)
                trades, _, _ = bt.run(contexts=contexts, collect_rejections=False)
            m = compute_metrics(trades_to_frame(trades), 10000.0)
            rows.append({"param": dotted, "value": value,
                         "context_rebuilt": "yes" if rebuild else "no",
                         "trades": m["trades"], "wr": round(m["win_rate"], 2),
                         "pf": round(m["profit_factor"], 3),
                         "exp_r": round(m["expectancy_r"], 4),
                         "max_dd": round(m["max_drawdown_pct"], 2)})
            print(rows[-1], flush=True)
            pd.DataFrame(rows).to_csv(os.path.join(OUT, "perturbation.csv"), index=False)
    print("\n=== PERTURBATION ===")
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


ROUNDS = {
    "regress": round_regress, "fixes": round_fixes, "entry": round_entry,
    "rr": round_rr, "hold": round_hold, "qual": round_qual, "misc": round_misc,
    "dedupe": round_dedupe, "cluster": round_cluster, "freq": round_freq,
    "final": round_final, "perturb": round_perturb,
}


def main():
    ap = argparse.ArgumentParser(description="SMC Sniper v5 audit + improvement loop")
    ap.add_argument("--round", required=True, choices=sorted(ROUNDS))
    ap.add_argument("--stack", default="mid30_swing",
                    help="only used by --round freq")
    args = ap.parse_args()
    if args.round == "freq":
        return round_freq(args.stack)
    return ROUNDS[args.round]()


if __name__ == "__main__":
    sys.exit(main())
