"""
Scale-free feature construction for the learned entry model.

CRITICAL: every feature must be invariant to gold's price level. Gold went from
$1,180 to $4,600 across this dataset; any feature carrying the price level lets
the model learn "gold above $3,000 => buy", which is era-fitting, not an edge.
So: no raw prices, no raw ATR, no absolute levels. Everything is a ratio, a
rank, a z-score, or a distance measured in ATR units.

All inputs come from the causal feature matrix (see data/data_engine.py), which
is covered by the anti-lookahead tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-9


def build(F: pd.DataFrame) -> pd.DataFrame:
    close = F["close"].astype(np.float64)
    atr5 = F["M5_atr"].ffill().astype(np.float64).clip(lower=EPS)
    atr15 = F["M15_atr"].ffill().astype(np.float64).clip(lower=EPS)
    X = pd.DataFrame(index=F.index)

    # ---- multi-horizon momentum, normalised by volatility
    for n in (1, 3, 5, 15, 30, 60, 120, 240):
        X[f"ret_{n}"] = (close - close.shift(n)) / (atr5 * np.sqrt(max(n / 5.0, 1.0)))
    # ---- momentum agreement / persistence
    up = (close.diff() > 0).astype(np.float64)
    X["up_frac_15"] = up.rolling(15, min_periods=5).mean()
    X["up_frac_60"] = up.rolling(60, min_periods=20).mean()
    X["streak"] = _streak(close.diff().values)

    # ---- volatility structure (ratios only)
    X["atr_ratio_5_15"] = atr5 / atr15
    X["atr_pct"] = atr5 / close                     # scale-free by construction
    X["atr_expand_30"] = atr5 / atr5.shift(30).clip(lower=EPS)
    X["atr_expand_120"] = atr5 / atr5.shift(120).clip(lower=EPS)
    for c in ("M15_atr_rank", "M15_bbw_rank", "H1_atr_rank", "M5_atr_rank"):
        if c in F: X[c] = F[c]
    X["realised_vol_ratio"] = (close.diff().abs().rolling(30, min_periods=10).mean()
                               / atr5)

    # ---- trend / oscillator state (already scale-free)
    for c in ("M5_adx", "M15_adx", "H1_adx", "M5_rsi", "M15_rsi", "H1_rsi",
              "M3_adx", "M3_rsi"):
        if c in F: X[c] = F[c]
    for tf in ("M3", "M5", "M15", "H1"):
        if f"{tf}_plus_di" in F:
            X[f"{tf}_di_diff"] = (F[f"{tf}_plus_di"] - F[f"{tf}_minus_di"])
        if f"{tf}_ema_spread" in F:
            X[f"{tf}_ema_spread_atr"] = F[f"{tf}_ema_spread"] / atr5
        if f"{tf}_ema_slope" in F:
            X[f"{tf}_ema_slope_atr"] = F[f"{tf}_ema_slope"] / atr5
        if f"{tf}_ema_f" in F:
            X[f"{tf}_ext_atr"] = (close - F[f"{tf}_ema_f"]) / atr5
        for c in (f"{tf}_struct_bias", f"{tf}_bos", f"{tf}_choch", f"{tf}_disp",
                  f"{tf}_range_pos", f"{tf}_vwap_dist_atr",
                  f"{tf}_bars_since_disp", f"{tf}_bars_since_bos"):
            if c in F: X[c] = F[c]
        for c in (f"{tf}_eqh", f"{tf}_eql"):
            if c in F: X[c] = F[c].astype(np.float32)

    # ---- distance to liquidity levels, in ATR units
    for lvl in ("pdh", "pdl", "day_high", "day_low", "sess_high", "sess_low",
                "asia_high", "asia_low"):
        if lvl in F:
            X[f"d_{lvl}"] = (close - F[lvl].astype(np.float64)) / atr5
    for tf in ("M5", "M15"):
        for lvl in ("swing_high", "swing_low"):
            c = f"{tf}_{lvl}"
            if c in F: X[f"d_{c}"] = (close - F[c].astype(np.float64)) / atr5

    # ---- position within the day's range
    dh, dl = F["day_high"].astype(np.float64), F["day_low"].astype(np.float64)
    X["day_range_pos"] = (close - dl) / (dh - dl).clip(lower=EPS)
    X["day_range_atr"] = (dh - dl) / atr5

    # ---- clock (cyclical, no level information)
    h = F["hour"].astype(np.float64)
    minute = pd.Series(F.index.minute, index=F.index).astype(np.float64)
    tod = h + minute / 60.0
    X["tod_sin"] = np.sin(2 * np.pi * tod / 24.0)
    X["tod_cos"] = np.cos(2 * np.pi * tod / 24.0)
    X["dow"] = F["dow"].astype(np.float64)
    for s in ("ASIA", "LONDON", "OVERLAP", "NEWYORK"):
        X[f"sess_{s}"] = (F["session"] == s).astype(np.float32)

    # ---- the cost regime: how expensive is this market relative to its own
    # volatility? This is the variable that decided everything in the V3 work.
    from xauusd_bot.backtesting.simulator import spread_series
    from xauusd_bot.config import Config
    sp = spread_series(F, Config()).astype(np.float64)
    X["cost_over_atr"] = (sp + 0.10) / atr5

    return X.replace([np.inf, -np.inf], np.nan).astype(np.float32)


def _streak(d: np.ndarray) -> np.ndarray:
    """Signed count of consecutive same-direction bars, clipped."""
    out = np.zeros(len(d), dtype=np.float64)
    run = 0
    for i in range(1, len(d)):
        if d[i] > 0:
            run = run + 1 if run > 0 else 1
        elif d[i] < 0:
            run = run - 1 if run < 0 else -1
        else:
            run = 0
        out[i] = run
    return np.clip(out, -10, 10)


def triple_barrier(F: pd.DataFrame, target_atr: float, stop_atr: float,
                   horizon: int) -> pd.DataFrame:
    """
    Outcome of a long and of a short opened at this bar's close.

    Pessimistic tie-break: if target and stop are both reached within the same
    minute, the STOP is taken - identical to the backtester's rule.
    Returns y_long / y_short in {1 win, 0 loss, -1 timeout}.
    """
    close = F["close"].values.astype(np.float64)
    high = F["high"].values.astype(np.float64)
    low = F["low"].values.astype(np.float64)
    atr = F["M5_atr"].ffill().values.astype(np.float64)
    n = len(F)
    T, S = target_atr * atr, stop_atr * atr

    l_tp, l_sl = close + T, close - S
    s_tp, s_sl = close - T, close + S
    f_ltp = np.full(n, horizon + 1, np.int32); f_lsl = np.full(n, horizon + 1, np.int32)
    f_stp = np.full(n, horizon + 1, np.int32); f_ssl = np.full(n, horizon + 1, np.int32)
    for k in range(1, horizon + 1):
        m = n - k
        a, b, c, d = f_ltp[:m], f_lsl[:m], f_stp[:m], f_ssl[:m]
        hk, lk = high[k:], low[k:]
        a[(hk >= l_tp[:m]) & (a > horizon)] = k
        b[(lk <= l_sl[:m]) & (b > horizon)] = k
        c[(lk <= s_tp[:m]) & (c > horizon)] = k
        d[(hk >= s_sl[:m]) & (d > horizon)] = k

    y_long = np.where(f_ltp < f_lsl, 1, np.where(f_lsl <= horizon, 0, -1))
    y_short = np.where(f_stp < f_ssl, 1, np.where(f_ssl <= horizon, 0, -1))
    out = pd.DataFrame({"y_long": y_long, "y_short": y_short,
                        "t_long": np.minimum(f_ltp, f_lsl),
                        "t_short": np.minimum(f_stp, f_ssl),
                        "atr": atr, "target_px": T, "stop_px": S}, index=F.index)
    out.iloc[-(horizon + 2):, out.columns.get_indexer(["y_long", "y_short"])] = -1
    return out
