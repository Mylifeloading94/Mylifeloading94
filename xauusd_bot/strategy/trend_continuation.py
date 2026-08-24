"""
STRATEGY 1 - Trend Continuation.

Trades pullbacks inside an established, multi-timeframe-confirmed trend.
Entry requires the pullback to have actually happened (price retraced toward
the M15 EMA20) AND a lower-timeframe break of structure back in the trend
direction. It refuses entries when price is already extended.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.config import Config
from xauusd_bot.strategy.base import empty_signals, recent, structural_stop, tradeable_time


def signals(F: pd.DataFrame, R: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    t = cfg.trend
    out = empty_signals(F.index, "TREND_CONTINUATION")
    if not cfg.toggles.trend_continuation:
        return out

    atr15 = F["M15_atr"].ffill()
    atr5 = F["M5_atr"].ffill()

    # ---- context: higher timeframes must agree
    h1_up = (F["H1_ema_spread"] > 0) & (F["H1_struct_bias"] >= 0)
    h1_dn = (F["H1_ema_spread"] < 0) & (F["H1_struct_bias"] <= 0)
    m15_up = (F["M15_ema_spread"] > 0) & (F["M15_struct_bias"] > 0)
    m15_dn = (F["M15_ema_spread"] < 0) & (F["M15_struct_bias"] < 0)
    adx_ok = F["M15_adx"] >= t.min_adx

    regime_up = R["regime"].isin(["BULL", "STRONG_BULL"]) & (R["dir_score"] > 0)
    regime_dn = R["regime"].isin(["BEAR", "STRONG_BEAR"]) & (R["dir_score"] < 0)

    long_ctx = h1_up & m15_up & adx_ok & regime_up
    short_ctx = h1_dn & m15_dn & adx_ok & regime_dn

    # ---- location: pulled back but not broken, and not overextended
    ext = (F["close"] - F["M15_ema_f"]) / atr15
    over_long = ext > t.max_extension_atr
    over_short = ext < -t.max_extension_atr
    # a real pullback: within the last 30 M1 bars price was >= min_pullback_atr
    # further from the EMA than it is now, in the trend direction
    ext_max = ext.rolling(30, min_periods=5).max()
    ext_min = ext.rolling(30, min_periods=5).min()
    # A pullback must have happened RECENTLY, not necessarily on the trigger
    # bar itself - by the time the break-of-structure fires, price has already
    # started moving back with the trend.
    pulled_long = recent((ext_max - ext) >= t.min_pullback_atr, t.pullback_window)
    pulled_short = recent((ext - ext_min) >= t.min_pullback_atr, t.pullback_window)

    # ---- trigger: lower-timeframe break of structure back with the trend
    m3_bos_up = F["M3_bos"] > 0
    m3_bos_dn = F["M3_bos"] < 0
    m1_disp_up = F["M1_disp"] > 0
    m1_disp_dn = F["M1_disp"] < 0
    # Fire on the break-of-structure bar itself, or on an M1 displacement that
    # occurs inside the entry window opened by that break (a continuation push
    # after a shallow retest).
    trig_long = m3_bos_up | (recent(m3_bos_up, t.entry_window_bars) & m1_disp_up)
    trig_short = m3_bos_dn | (recent(m3_bos_dn, t.entry_window_bars) & m1_disp_dn)
    if not t.require_ltf_bos:
        trig_long = trig_long | m1_disp_up
        trig_short = trig_short | m1_disp_dn

    # ---- momentum + location quality (also feed the setup score)
    m5_mom_up = (F["M5_plus_di"] > F["M5_minus_di"]) & (F["M5_ema_slope"] > 0)
    m5_mom_dn = (F["M5_plus_di"] < F["M5_minus_di"]) & (F["M5_ema_slope"] < 0)
    vwap_up = F["M15_vwap_dist_atr"] > -0.25
    vwap_dn = F["M15_vwap_dist_atr"] < 0.25
    # "liquidity" leg for a trend pullback = the pullback swept a minor low/high
    liq_long = recent(F["low"] <= F["M5_swing_low"], 20)
    liq_short = recent(F["high"] >= F["M5_swing_high"], 20)
    retest_long = recent(F["low"] <= F["M3_ema_f"], 5)
    retest_short = recent(F["high"] >= F["M3_ema_f"], 5)

    ok_time = tradeable_time(F, cfg)

    long_sig = (long_ctx & pulled_long & ~over_long & trig_long & m5_mom_up & ok_time)
    short_sig = (short_ctx & pulled_short & ~over_short & trig_short & m5_mom_dn & ok_time)
    # never both
    both = long_sig & short_sig
    long_sig &= ~both
    short_sig &= ~both

    direction = np.where(long_sig, 1, np.where(short_sig, -1, 0))

    # ---- stop: below the pullback swing low (longs) with an ATR floor
    anchor_low = pd.concat([F["M5_swing_low"], F["low"].rolling(20, min_periods=1).min()],
                           axis=1).min(axis=1)
    anchor_high = pd.concat([F["M5_swing_high"], F["high"].rolling(20, min_periods=1).max()],
                            axis=1).max(axis=1)
    sl = structural_stop(F, direction, anchor_high, anchor_low, cfg)

    out["dir"] = direction
    out["sl"] = sl
    out["c_h1"] = (long_sig & h1_up) | (short_sig & h1_dn)
    out["c_m15"] = (long_sig & m15_up) | (short_sig & m15_dn)
    out["c_m5mom"] = (long_sig & m5_mom_up) | (short_sig & m5_mom_dn)
    out["c_vwap"] = (long_sig & vwap_up) | (short_sig & vwap_dn)
    out["c_liq"] = (long_sig & liq_long) | (short_sig & liq_short)
    out["c_ltf"] = (long_sig & trig_long) | (short_sig & trig_short)
    out["c_retest"] = (long_sig & retest_long) | (short_sig & retest_short)
    out.loc[direction != 0, "reason"] = "trend pullback + LTF BOS"
    out.loc[direction == 0, "strategy"] = ""
    return out
