"""
Strategy selector: runs all enabled strategies, then lets the REGIME decide
which one may act on each bar. Exactly one strategy controls any given
decision (spec section 9) - conflicts are resolved by regime priority, and if
two enabled strategies disagree on direction the bar becomes NO_TRADE.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.config import Config
from xauusd_bot.strategy import breakout, liquidity_reversal, trend_continuation
from xauusd_bot.strategy.base import empty_signals

PERMITTED = {
    "TREND_CONTINUATION": {"STRONG_BULL", "STRONG_BEAR", "BULL", "BEAR", "EXPANSION"},
    "LIQUIDITY_REVERSAL": {"LIQUIDITY_REVERSAL", "CHOPPY", "HIGH_VOLATILITY", "NEUTRAL",
                           "BULL", "BEAR"},
    "BREAKOUT": {"EXPANSION", "COMPRESSION", "BULL", "BEAR", "STRONG_BULL", "STRONG_BEAR"},
}
# Regime -> the ONE strategy that owns the decision when several could fire.
PRIORITY = {
    "STRONG_BULL": ["TREND_CONTINUATION", "BREAKOUT"],
    "STRONG_BEAR": ["TREND_CONTINUATION", "BREAKOUT"],
    "BULL": ["TREND_CONTINUATION", "BREAKOUT", "LIQUIDITY_REVERSAL"],
    "BEAR": ["TREND_CONTINUATION", "BREAKOUT", "LIQUIDITY_REVERSAL"],
    "EXPANSION": ["BREAKOUT", "TREND_CONTINUATION"],
    "COMPRESSION": ["BREAKOUT"],
    "LIQUIDITY_REVERSAL": ["LIQUIDITY_REVERSAL"],
    "CHOPPY": ["LIQUIDITY_REVERSAL"],
    "HIGH_VOLATILITY": ["LIQUIDITY_REVERSAL"],
    "NEUTRAL": ["LIQUIDITY_REVERSAL"],
    "LOW_VOLATILITY": [],
    "NO_TRADE": [],
}


def select(F: pd.DataFrame, R: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, dict]:
    parts = {
        "TREND_CONTINUATION": trend_continuation.signals(F, R, cfg),
        "LIQUIDITY_REVERSAL": liquidity_reversal.signals(F, R, cfg),
        "BREAKOUT": breakout.signals(F, R, cfg),
    }
    out = empty_signals(F.index, "")
    regime = R["regime"].values
    conf = R["regime_conf"].values
    min_conf = cfg.regime.min_confidence

    chosen = np.full(len(F), "", dtype=object)
    taken = np.zeros(len(F), dtype=bool)
    counts = {k: 0 for k in parts}
    counts["conflict_no_trade"] = 0
    counts["regime_blocked"] = 0

    # detect disagreement between strategies that are BOTH permitted here
    dirs = np.stack([p["dir"].values for p in parts.values()])
    active = dirs != 0
    n_active = active.sum(axis=0)
    pos_any = (dirs > 0).any(axis=0)
    neg_any = (dirs < 0).any(axis=0)
    disagree = (n_active > 1) & pos_any & neg_any

    names = ["TREND_CONTINUATION", "BREAKOUT", "LIQUIDITY_REVERSAL"]
    # rank[k, i] = priority of strategy k in the regime at bar i (lower wins);
    # a big number means "not permitted in this regime".
    BIG = 99
    prio_lookup = {r: {n: i for i, n in enumerate(v)} for r, v in PRIORITY.items()}
    rank = np.full((len(names), len(F)), BIG, dtype=int)
    for k, name in enumerate(names):
        per_regime = np.array([prio_lookup.get(r, {}).get(name, BIG) for r in regime])
        rank[k] = per_regime
    d_all = np.stack([parts[n]["dir"].values for n in names])
    rank_eff = np.where(d_all != 0, rank, BIG)          # only firing strategies compete
    best = rank_eff.argmin(axis=0)
    has_winner = rank_eff.min(axis=0) < BIG

    take_all = has_winner & (conf >= min_conf) & (~disagree)
    for k, name in enumerate(names):
        take = take_all & (best == k)
        p = parts[name]
        for col in out.columns:
            out.loc[take, col] = p.loc[take, col]
        chosen[take] = name
        taken |= take
        counts[name] = int(take.sum())

    counts["conflict_no_trade"] = int((disagree & (dirs != 0).any(axis=0)).sum())
    counts["regime_blocked"] = int(((dirs != 0).any(axis=0) & ~taken & ~disagree).sum())
    out["strategy"] = chosen
    out.loc[~taken, "dir"] = 0
    return out, counts
