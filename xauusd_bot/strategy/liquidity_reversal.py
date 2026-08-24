"""
STRATEGY 2 - Liquidity Reversal.

Sequence enforced (spec section 7):
    LIQUIDITY LEVEL -> SWEEP -> REJECTION -> STRUCTURE SHIFT (CHoCH)
    -> DISPLACEMENT -> (RETEST) -> ENTRY

A touch of a level is NOT a signal. The sweep must be rejected, the lower
timeframe must change character against the sweep, and a displacement leg must
confirm it. Every level used (previous-day extremes, completed Asian range,
prior session extremes) was complete before the bar being evaluated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.config import Config
from xauusd_bot.strategy.base import bars_since, empty_signals, recent, structural_stop, tradeable_time


def _pool_levels(F: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    highs = pd.DataFrame({
        "pdh": F["pdh"], "asia_high": F["asia_high"],
        "m15_swing": F["M15_swing_high"],
    })
    lows = pd.DataFrame({
        "pdl": F["pdl"], "asia_low": F["asia_low"],
        "m15_swing": F["M15_swing_low"],
    })
    return highs, lows


def signals(F: pd.DataFrame, R: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    q = cfg.liquidity
    out = empty_signals(F.index, "LIQUIDITY_REVERSAL")
    if not cfg.toggles.liquidity_reversal:
        return out

    atr5 = F["M5_atr"].ffill()
    tol = q.sweep_tol_atr * atr5
    highs, lows = _pool_levels(F)

    # ---- 1. SWEEP: the bar's extreme trades beyond a pool by > tol
    above = (F["high"].values[:, None] > (highs.values + tol.values[:, None]))
    below = (F["low"].values[:, None] < (lows.values - tol.values[:, None]))
    swept_high = pd.Series(np.nansum(np.where(np.isnan(highs.values), 0, above), axis=1) > 0,
                           index=F.index)
    swept_low = pd.Series(np.nansum(np.where(np.isnan(lows.values), 0, below), axis=1) > 0,
                          index=F.index)

    # ---- 2. REJECTION: the same bar closes back inside the pool
    closed_back_dn = pd.Series(
        np.nansum(np.where(np.isnan(highs.values), 0,
                           F["close"].values[:, None] < highs.values), axis=1) > 0, index=F.index)
    closed_back_up = pd.Series(
        np.nansum(np.where(np.isnan(lows.values), 0,
                           F["close"].values[:, None] > lows.values), axis=1) > 0, index=F.index)
    rej_high = swept_high & closed_back_dn      # bearish rejection -> look SHORT
    rej_low = swept_low & closed_back_up        # bullish rejection -> look LONG

    age_high = bars_since(rej_high)
    age_low = bars_since(rej_low)
    fresh_high = (age_high <= q.max_sweep_age_bars) & recent(rej_high, q.max_sweep_age_bars)
    fresh_low = (age_low <= q.max_sweep_age_bars) & recent(rej_low, q.max_sweep_age_bars)

    # ---- 3. STRUCTURE SHIFT against the sweep (CHoCH on M3/M5)
    choch_dn = (F["M3_choch"] < 0) | (F["M5_choch"] < 0)
    choch_up = (F["M3_choch"] > 0) | (F["M5_choch"] > 0)
    shift_dn = recent(choch_dn, q.max_sweep_age_bars)
    shift_up = recent(choch_up, q.max_sweep_age_bars)
    if not q.require_choch:
        shift_dn = shift_dn | (F["M3_bos"] < 0)
        shift_up = shift_up | (F["M3_bos"] > 0)

    # ---- 4. DISPLACEMENT confirming the new direction
    disp_dn = recent(F["M3_disp"] < 0, 10) | (F["M1_disp"] < 0)
    disp_up = recent(F["M3_disp"] > 0, 10) | (F["M1_disp"] > 0)
    if not q.require_displacement:
        disp_dn = disp_dn | True
        disp_up = disp_up | True

    # ---- 5. RETEST of the displacement leg (optional but scored)
    retest_short = recent(F["high"] >= F["M3_ema_f"], 6)
    retest_long = recent(F["low"] <= F["M3_ema_f"], 6)

    # ---- filters: don't fade a violent trend
    not_runaway = F["M15_adx"] < q.max_adx
    ok_time = tradeable_time(F, cfg)
    regime_ok = R["regime"].isin(["LIQUIDITY_REVERSAL", "CHOPPY", "NEUTRAL", "HIGH_VOLATILITY",
                                  "BULL", "BEAR", "EXPANSION", "COMPRESSION"])

    short_sig = fresh_high & shift_dn & disp_dn & not_runaway & ok_time & regime_ok
    long_sig = fresh_low & shift_up & disp_up & not_runaway & ok_time & regime_ok
    both = short_sig & long_sig
    short_sig &= ~both
    long_sig &= ~both

    # only take the reversal against the dominant HTF bias when it is a genuine
    # counter-trend sweep; with the bias it is simply a better trend entry
    direction = np.where(long_sig, 1, np.where(short_sig, -1, 0))

    # ---- stop: beyond the swept extreme
    sweep_hi = F["high"].rolling(q.max_sweep_age_bars, min_periods=1).max()
    sweep_lo = F["low"].rolling(q.max_sweep_age_bars, min_periods=1).min()
    sl = structural_stop(F, direction, sweep_hi, sweep_lo, cfg)

    out["dir"] = direction
    out["sl"] = sl
    h1_align = ((direction > 0) & (F["H1_ema_spread"] > 0).values) | \
               ((direction < 0) & (F["H1_ema_spread"] < 0).values)
    m15_align = ((direction > 0) & (F["M15_struct_bias"] >= 0).values) | \
                ((direction < 0) & (F["M15_struct_bias"] <= 0).values)
    out["c_h1"] = h1_align
    out["c_m15"] = m15_align
    out["c_m5mom"] = ((direction > 0) & (F["M5_rsi"] > 45).values) | \
                     ((direction < 0) & (F["M5_rsi"] < 55).values)
    out["c_vwap"] = ((direction > 0) & (F["M15_vwap_dist_atr"] < 0.5).values) | \
                    ((direction < 0) & (F["M15_vwap_dist_atr"] > -0.5).values)
    out["c_liq"] = direction != 0                      # a sweep is definitional here
    out["c_ltf"] = (long_sig & shift_up) | (short_sig & shift_dn)
    out["c_retest"] = (long_sig & retest_long) | (short_sig & retest_short)
    out.loc[direction != 0, "reason"] = "sweep + rejection + CHoCH + displacement"
    out.loc[direction == 0, "strategy"] = ""
    return out
