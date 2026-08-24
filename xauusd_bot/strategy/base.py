"""Shared signal representation + stop-loss engine used by all strategies."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from xauusd_bot.config import Config

SIGNAL_COLS = ["dir", "sl", "reason", "strategy",
               "c_h1", "c_m15", "c_m5mom", "c_vwap", "c_liq", "c_ltf", "c_retest"]


def empty_signals(index: pd.DatetimeIndex, strategy: str) -> pd.DataFrame:
    n = len(index)
    return pd.DataFrame({
        "dir": np.zeros(n, dtype=int),
        "sl": np.full(n, np.nan),
        "reason": np.full(n, "", dtype=object),
        "strategy": np.full(n, strategy, dtype=object),
        "c_h1": np.zeros(n, dtype=bool),
        "c_m15": np.zeros(n, dtype=bool),
        "c_m5mom": np.zeros(n, dtype=bool),
        "c_vwap": np.zeros(n, dtype=bool),
        "c_liq": np.zeros(n, dtype=bool),
        "c_ltf": np.zeros(n, dtype=bool),
        "c_retest": np.zeros(n, dtype=bool),
    }, index=index)


def structural_stop(F: pd.DataFrame, direction: np.ndarray, anchor_high: pd.Series,
                    anchor_low: pd.Series, cfg: Config) -> np.ndarray:
    """
    SL = max(structural invalidation distance, ATR * multiplier) + buffer.

    `anchor_*` are the invalidation levels (a swing, or the extreme of a sweep).
    The result is a PRICE, not a distance, and is always on the losing side of
    the reference close.
    """
    close = F["close"].values
    atr = F["M5_atr"].ffill().values
    buf = cfg.exits.structure_buffer_atr * atr
    atr_dist = cfg.exits.atr_mult_sl * atr

    struct_dist_long = close - anchor_low.values
    struct_dist_short = anchor_high.values - close
    struct_dist = np.where(direction > 0, struct_dist_long, struct_dist_short)
    struct_dist = np.where(np.isfinite(struct_dist), struct_dist, np.nan)

    dist = np.fmax(np.nan_to_num(struct_dist, nan=0.0), atr_dist) + buf
    dist = dist * cfg.exits.stop_scale
    dist = np.maximum(dist, cfg.exits.min_sl_price)
    sl = np.where(direction > 0, close - dist, close + dist)
    # reject absurd stops (the ceiling scales with the deliberate widening)
    too_wide = dist > (cfg.exits.max_sl_atr * cfg.exits.stop_scale * atr)
    sl = np.where(too_wide | (direction == 0), np.nan, sl)
    return sl


def tradeable_time(F: pd.DataFrame, cfg: Config) -> np.ndarray:
    """Session / hour / weekday gate for OPENING a position."""
    s = cfg.sessions
    hour = F["hour"].values
    dow = F["dow"].values
    ok = np.isin(F["session"].values, list(s.enabled_sessions))
    ok &= (hour >= s.trade_start_utc) & (hour <= s.trade_end_utc)
    ok &= np.isin(dow, list(s.trade_days))
    ok &= ~((dow == 4) & (hour >= s.friday_cutoff_utc))
    return ok


def recent(flag: pd.Series, bars: int) -> pd.Series:
    """True if `flag` was True on any of the last `bars` bars (inclusive)."""
    return flag.astype(float).rolling(bars, min_periods=1).max().astype(bool)


def bars_since(flag: pd.Series) -> pd.Series:
    f = flag.astype(bool)
    grp = (~f).cumsum()
    return (grp - grp.where(f).ffill().fillna(grp.iloc[0])).astype(float)
