"""
Market Regime Engine.

Classifies the market from several INDEPENDENT measurements (trend strength,
structure, volatility state, momentum, location) and returns a regime label
plus a confidence in [0, 1]. It is vectorised over the whole M1 feature matrix
but every input column is causal, so row i only reflects information available
at the close of M1 bar i.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.config import RegimeConfig

REGIMES = ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR",
           "LIQUIDITY_REVERSAL", "COMPRESSION", "EXPANSION", "CHOPPY",
           "HIGH_VOLATILITY", "LOW_VOLATILITY", "NO_TRADE"]

# Which strategy each regime routes to (section 9 of the spec).
REGIME_STRATEGY = {
    "STRONG_BULL": "TREND_CONTINUATION",
    "STRONG_BEAR": "TREND_CONTINUATION",
    "BULL": "TREND_CONTINUATION",
    "BEAR": "TREND_CONTINUATION",
    "LIQUIDITY_REVERSAL": "LIQUIDITY_REVERSAL",
    "EXPANSION": "BREAKOUT",
    "COMPRESSION": "WAIT",
    "CHOPPY": "NO_TRADE",
    "HIGH_VOLATILITY": "STRICT",       # trade, but with tightened filters
    "LOW_VOLATILITY": "NO_TRADE",
    "NEUTRAL": "NO_TRADE",
    "NO_TRADE": "NO_TRADE",
}


def classify(F: pd.DataFrame, cfg: RegimeConfig) -> pd.DataFrame:
    """Returns columns: regime, regime_conf, trend_score, vol_state, and the
    component sub-scores used for diagnostics."""
    h1_adx = F["H1_adx"]
    m15_adx = F["M15_adx"]
    h1_bias = F["H1_struct_bias"]
    m15_bias = F["M15_struct_bias"]
    h1_ema = np.sign(F["H1_ema_spread"]).fillna(0)
    m15_ema = np.sign(F["M15_ema_spread"]).fillna(0)
    m15_di = np.sign(F["M15_plus_di"] - F["M15_minus_di"]).fillna(0)
    vwap_side = np.sign(F["M15_vwap_dist_atr"]).fillna(0)

    # ---- directional agreement across five independent measures (-1..+1)
    votes = pd.concat([h1_bias.fillna(0), m15_bias.fillna(0), h1_ema,
                       m15_ema, m15_di, vwap_side], axis=1)
    dir_score = votes.mean(axis=1)
    agreement = votes.apply(lambda r: abs(r.sum()) / max(1, (r != 0).sum()), axis=1) \
        if False else (votes.sum(axis=1).abs() / votes.ne(0).sum(axis=1).replace(0, np.nan))

    # ---- trend strength (0..1)
    trend_strength = ((h1_adx.clip(0, 45) / 45.0) * 0.5 +
                      (m15_adx.clip(0, 45) / 45.0) * 0.5).fillna(0)

    # ---- volatility state
    atr_pct = F["M5_atr"] / F["close"]
    atr_rank = F["M15_atr_rank"]
    bbw_rank = F["M15_bbw_rank"]
    vol_state = pd.Series("NORMAL", index=F.index, dtype=object)
    vol_state[atr_rank <= cfg.atr_rank_low] = "LOW"
    vol_state[atr_rank >= cfg.atr_rank_high] = "HIGH"
    dead = atr_pct < cfg.vol_floor_atr_pct
    berserk = atr_pct > cfg.vol_ceiling_atr_pct

    compression = (bbw_rank <= cfg.bbw_rank_compression) & (atr_rank <= 0.35)
    expansion = (bbw_rank >= 0.75) & (F["M15_atr"] > F["M15_atr"].rolling(96, min_periods=20).mean())

    # ---- liquidity-reversal context: a recent sweep of a known pool + CHoCH
    swept = _sweep_flag(F)
    recent_choch = (F["M5_bars_since_bos"] <= 6) & (F["M5_choch"] != 0)
    liq_context = swept & (F["M15_adx"] < 40)

    # ---- chop: low adx, no structure, price oscillating around VWAP
    choppy = ((m15_adx < cfg.adx_chop) & (h1_adx < cfg.adx_trend) &
              (m15_bias.fillna(0) == 0) & (F["M15_vwap_dist_atr"].abs() < 0.8))

    n = len(F)
    regime = np.full(n, "NEUTRAL", dtype=object)
    conf = np.zeros(n)

    ts, ds, ag = trend_strength.values, dir_score.values, agreement.fillna(0).values
    m15a, h1a = m15_adx.fillna(0).values, h1_adx.fillna(0).values

    strong_trend = (m15a >= cfg.adx_strong) & (np.abs(ds) >= 0.6) & (ag >= 0.8)
    trend = (m15a >= cfg.adx_trend) & (np.abs(ds) >= 0.4) & (ag >= 0.6)

    # Priority order matters: the most specific, tradeable contexts win.
    regime = np.where(trend & (ds > 0), "BULL", regime)
    regime = np.where(trend & (ds < 0), "BEAR", regime)
    regime = np.where(strong_trend & (ds > 0), "STRONG_BULL", regime)
    regime = np.where(strong_trend & (ds < 0), "STRONG_BEAR", regime)
    regime = np.where(expansion.values & ~trend, "EXPANSION", regime)
    regime = np.where(compression.values, "COMPRESSION", regime)
    regime = np.where(liq_context.values, "LIQUIDITY_REVERSAL", regime)
    regime = np.where(choppy.values, "CHOPPY", regime)
    regime = np.where(berserk.values, "HIGH_VOLATILITY", regime)
    regime = np.where(dead.values, "LOW_VOLATILITY", regime)
    regime = np.where(np.isnan(h1a) | (h1a == 0), "NO_TRADE", regime)

    # ---- confidence: how strongly the evidence supports the label
    trend_conf = np.clip(0.35 + 0.4 * np.abs(ds) + 0.35 * ts, 0, 1) * np.clip(ag, 0, 1)
    liq_conf = np.clip(0.5 + 0.3 * recent_choch.fillna(False).values.astype(float) +
                       0.2 * (F["M5_disp"].abs().fillna(0).values > 0), 0, 1)
    comp_conf = np.clip(0.5 + 0.5 * (1 - bbw_rank.fillna(1).values), 0, 1)
    exp_conf = np.clip(0.45 + 0.5 * bbw_rank.fillna(0).values, 0, 1)
    chop_conf = np.clip(0.5 + (cfg.adx_chop - np.minimum(m15a, cfg.adx_chop)) / cfg.adx_chop * 0.5, 0, 1)

    conf = np.select(
        [np.isin(regime, ["STRONG_BULL", "STRONG_BEAR", "BULL", "BEAR"]),
         regime == "LIQUIDITY_REVERSAL",
         regime == "COMPRESSION",
         regime == "EXPANSION",
         regime == "CHOPPY"],
        [trend_conf, liq_conf, comp_conf, exp_conf, chop_conf],
        default=0.3)
    conf = np.where(np.isin(regime, ["NO_TRADE", "LOW_VOLATILITY", "HIGH_VOLATILITY"]), 0.9, conf)

    out = pd.DataFrame({
        "regime": regime,
        "regime_conf": np.round(conf, 3),
        "dir_score": np.round(ds, 3),
        "agreement": np.round(ag, 3),
        "trend_strength": np.round(ts, 3),
        "vol_state": vol_state.values,
        "atr_pct": atr_pct.values,
        "swept": swept.values,
    }, index=F.index)
    out["strategy"] = out["regime"].map(REGIME_STRATEGY)
    # confidence gate
    low = out["regime_conf"] < cfg.min_confidence
    out.loc[low & out["strategy"].isin(["TREND_CONTINUATION", "LIQUIDITY_REVERSAL", "BREAKOUT"]),
            "strategy"] = "NO_TRADE"
    return out


def _sweep_flag(F: pd.DataFrame, tol_atr: float = 0.10, lookback: int = 30) -> pd.Series:
    """True when price has, within `lookback` M1 bars, traded beyond a known
    liquidity pool (PDH/PDL, Asian high/low, session extreme) and closed back
    inside it. Uses only levels that were already complete at that time."""
    atr = F["M5_atr"].ffill()
    tol = tol_atr * atr
    highs = pd.concat([F["pdh"], F["asia_high"]], axis=1)
    lows = pd.concat([F["pdl"], F["asia_low"]], axis=1)
    above = (F["high"].values[:, None] > (highs.values + tol.values[:, None]))
    below = (F["low"].values[:, None] < (lows.values - tol.values[:, None]))
    poked_up = pd.Series(np.nansum(above, axis=1) > 0, index=F.index)
    poked_dn = pd.Series(np.nansum(below, axis=1) > 0, index=F.index)
    back_in_up = poked_up.rolling(lookback, min_periods=1).max().astype(bool) & \
        (F["close"].values[:, None] < highs.values).any(axis=1)
    back_in_dn = poked_dn.rolling(lookback, min_periods=1).max().astype(bool) & \
        (F["close"].values[:, None] > lows.values).any(axis=1)
    return (back_in_up | back_in_dn).fillna(False)
