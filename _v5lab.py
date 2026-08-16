"""v5 audit lab -- shared harness. Loads cached contexts, evaluates variants
on TRAIN/TEST independently. Nothing here selects on the full window."""
from __future__ import annotations
import os, pickle, sys, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.metrics import compute_metrics, expectancy_ci, win_rate_ci
from smc_sniper import walkforward
from smc_sniper.signal_engine import CONTEXT_CACHE_VERSION

REPO = os.path.dirname(os.path.abspath(__file__))
FRACTIONS = (0.50, 0.20, 0.30)


def load_env(stack="swing", source="tradelocker", rebuild=False, ctx_over=None, tag=""):
    """ctx_over: dotted config overrides that SHAPE the context (zones, structure,
    liquidity). They must be applied before the context is built and get their
    own cache slot, keyed by `tag`."""
    cfg = load_config(); cfg.set("active_stack", stack)
    for k, v in (ctx_over or {}).items():
        cfg.set(k, v)
    engine = DataEngine(cfg, source=source)
    cache = os.path.join(REPO, "smc_data", f"_ctx_{stack}_{source}{tag}.pkl")
    if os.path.exists(cache) and not rebuild:
        try:
            with open(cache, "rb") as fh:
                version, contexts = pickle.load(fh)
            if version != CONTEXT_CACHE_VERSION:
                raise ValueError(f"cache v{version} != code v{CONTEXT_CACHE_VERSION}")
            print(f"contexts: {len(contexts)} pairs (cached {stack})", flush=True)
            return cfg, engine, contexts
        except Exception as exc:
            print(f"context cache unusable ({exc}); rebuilding", flush=True)
    t0 = time.time()
    contexts = Backtester(cfg, engine).build_contexts()
    print(f"contexts: {len(contexts)} pairs built in {time.time()-t0:.0f}s", flush=True)
    try:
        with open(cache, "wb") as fh:
            pickle.dump((CONTEXT_CACHE_VERSION, contexts), fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        print(f"  (cache not written: {exc})")
    return cfg, engine, contexts


def bounds(contexts):
    start, end = walkforward.data_window(contexts)
    return walkforward.split_window(start, end, FRACTIONS)


def apply(cfg, overrides):
    v = cfg.copy()
    for k, val in (overrides or {}).items():
        v.set(k, val)
    return v


def evaluate(cfg, engine, contexts, overrides, name, balance=10000.0,
             splits=None, ci=False, allowed=None, want_frames=False):
    variant = apply(cfg, overrides)
    bt = Backtester(variant, engine); bt.bind(contexts)
    t0 = time.time()
    trades, _, _ = bt.run(contexts=contexts, collect_rejections=False, allowed_symbols=allowed)
    full = trades_to_frame(trades)
    row = {"variant": name, "seconds": round(time.time()-t0, 1)}
    frames = {"full": full}
    for split, (a, b) in (splits or bounds(contexts)).items():
        tr, _, _ = bt.run(contexts=contexts, start=a, end=b, collect_rejections=False,
                          allowed_symbols=allowed)
        frames[split] = trades_to_frame(tr)
    # trades/day on the full window
    if not full.empty:
        span = (pd.to_datetime(full.exit_time).max() - pd.to_datetime(full.signal_time).min()).days or 1
        row["per_day"] = round(len(full) / span, 3)
    else:
        row["per_day"] = 0.0
    for tag, frame in frames.items():
        m = compute_metrics(frame, balance)
        p = "" if tag == "full" else f"{tag}_"
        row[f"{p}n"] = m["trades"]; row[f"{p}wr"] = round(m["win_rate"], 2)
        row[f"{p}pf"] = round(m["profit_factor"], 3); row[f"{p}exp"] = round(m["expectancy_r"], 4)
        if tag == "full":
            row["max_dd"] = round(m["max_drawdown_pct"], 2)
            row["total_r"] = round(m.get("total_r", 0.0), 2)
            row["max_loss_streak"] = m.get("max_consecutive_losses", 0)
            row["scratches"] = m.get("scratches", 0)
            row["wr_ex_scratch"] = round(m.get("win_rate_ex_scratch", 0.0), 2)
    if ci and not full.empty:
        lo, hi = expectancy_ci(full, 5000); row["ci_lo"], row["ci_hi"] = round(lo, 4), round(hi, 4)
        wlo, whi = win_rate_ci(full, 5000); row["wr_lo"], row["wr_hi"] = round(wlo, 2), round(whi, 2)
    return (row, frames) if want_frames else (row, frames)


COLS = ["variant", "n", "per_day", "wr", "pf", "exp", "train_n", "train_exp",
        "test_n", "test_exp", "max_dd"]


def show(rows, cols=None):
    f = pd.DataFrame(rows)
    cols = [c for c in (cols or COLS) if c in f.columns]
    print(f[cols].to_string(index=False), flush=True)
    return f
