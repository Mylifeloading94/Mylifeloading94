"""
STRATEGY 3 - Breakout / Volatility Expansion.

Requires a measurable compression phase first, then a CLOSE beyond the range
boundary (not a wick), momentum expansion confirming it, and a cap on how far
price may already have travelled (anti-chase). Failed-breakout protection: the
breakout close must be beyond the boundary by a buffer, and the bar must not
have already covered more than max_chase_atr of ATR beyond it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.config import Config
from xauusd_bot.strategy.base import empty_signals, recent, structural_stop, tradeable_time


def signals(F: pd.DataFrame, R: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    b = cfg.breakout
    out = empty_signals(F.index, "BREAKOUT")
    if not cfg.toggles.breakout:
        return out

    atr15 = F["M15_atr"].ffill()
    atr5 = F["M5_atr"].ffill()

    # ---- 1. COMPRESSION: M15 Bollinger width in its lowest quantile, sustained
    compressed = (F["M15_bbw_rank"] <= b.compression_bbw_rank) & (F["M15_atr_rank"] <= 0.40)
    # sustained for at least min_compression_bars M15 bars == 15*n M1 bars
    sustained = compressed.rolling(b.min_compression_bars * 15, min_periods=1).mean() >= 0.6
    was_compressed = recent(compressed & sustained, 240)   # within the last 4h

    # ---- 2. RANGE BOUNDARIES from the compression window (previous bars only)
    hi = F["M15_dc_high"]
    lo = F["M15_dc_low"]
    buf = b.breakout_buffer_atr * atr15

    # ---- 3. BREAKOUT: an M5 close beyond the boundary + buffer
    brk_up = (F["M5_close"] > (hi + buf)) & (F["M5_close"].shift(1) <= (hi + buf))
    brk_dn = (F["M5_close"] < (lo - buf)) & (F["M5_close"].shift(1) >= (lo - buf))
    brk_up_recent = recent(brk_up, 15)
    brk_dn_recent = recent(brk_dn, 15)

    # ---- 4. MOMENTUM EXPANSION
    mom_up = (F["M5_disp"] > 0) | ((F["M5_adx"] > F["M5_adx"].shift(5)) & (F["M5_plus_di"] > F["M5_minus_di"]))
    mom_dn = (F["M5_disp"] < 0) | ((F["M5_adx"] > F["M5_adx"].shift(5)) & (F["M5_minus_di"] > F["M5_plus_di"]))
    if not b.require_momentum:
        mom_up = mom_dn = pd.Series(True, index=F.index)

    # ---- 5. ANTI-CHASE: price must still be near the broken boundary
    near_up = (F["close"] - hi) <= (b.max_chase_atr * atr15)
    near_dn = (lo - F["close"]) <= (b.max_chase_atr * atr15)

    # ---- 6. FALSE-BREAK GUARD: price must still be on the breakout side
    holding_up = F["close"] > hi
    holding_dn = F["close"] < lo

    # ---- 7. retest of the broken boundary (scored, optional)
    retest_up = recent((F["low"] <= (hi + buf)) & (F["close"] > hi), 10)
    retest_dn = recent((F["high"] >= (lo - buf)) & (F["close"] < lo), 10)

    ok_time = tradeable_time(F, cfg)
    regime_ok = R["regime"].isin(["EXPANSION", "COMPRESSION", "BULL", "BEAR",
                                  "STRONG_BULL", "STRONG_BEAR", "NEUTRAL"])

    long_sig = was_compressed & brk_up_recent & mom_up & near_up & holding_up & ok_time & regime_ok
    short_sig = was_compressed & brk_dn_recent & mom_dn & near_dn & holding_dn & ok_time & regime_ok
    both = long_sig & short_sig
    long_sig &= ~both
    short_sig &= ~both
    direction = np.where(long_sig, 1, np.where(short_sig, -1, 0))

    # ---- stop: a breakout is invalidated by trading back INSIDE the range, so
    # the invalidation level is the broken boundary itself (plus the buffer),
    # not the far side of the range - which would be an absurdly wide stop.
    anchor_low = pd.concat([hi - buf, F["low"].rolling(10, min_periods=1).min()],
                           axis=1).min(axis=1)
    anchor_high = pd.concat([lo + buf, F["high"].rolling(10, min_periods=1).max()],
                            axis=1).max(axis=1)
    sl = structural_stop(F, direction, anchor_high, anchor_low, cfg)

    out["dir"] = direction
    out["sl"] = sl
    out["c_h1"] = ((direction > 0) & (F["H1_ema_spread"] > 0).values) | \
                  ((direction < 0) & (F["H1_ema_spread"] < 0).values)
    out["c_m15"] = ((direction > 0) & (F["M15_struct_bias"] >= 0).values) | \
                   ((direction < 0) & (F["M15_struct_bias"] <= 0).values)
    out["c_m5mom"] = (long_sig & mom_up) | (short_sig & mom_dn)
    out["c_vwap"] = ((direction > 0) & (F["M15_vwap_dist_atr"] > -0.5).values) | \
                    ((direction < 0) & (F["M15_vwap_dist_atr"] < 0.5).values)
    out["c_liq"] = (long_sig & (F["M15_eqh"].astype(bool))) | (short_sig & (F["M15_eql"].astype(bool)))
    out["c_ltf"] = (long_sig & (F["M3_bos"] > 0)) | (short_sig & (F["M3_bos"] < 0)) | \
                   (long_sig & brk_up) | (short_sig & brk_dn)
    out["c_retest"] = (long_sig & retest_up) | (short_sig & retest_dn)
    out.loc[direction != 0, "reason"] = "compression -> confirmed range break + momentum"
    out.loc[direction == 0, "strategy"] = ""
    return out
