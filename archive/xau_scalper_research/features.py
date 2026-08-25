"""Feature construction for the XAUUSD scalper, computed on a chosen timeframe.

Every feature at bar i uses bars <= i only. The barrier scan then measures what
happened AFTER bar i, so nothing here can see its own outcome.
"""
import numpy as np
import pandas as pd


def resample(m1, rule):
    out = m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    return out.dropna()


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50)


def session_vwap(df):
    """VWAP anchored to each UTC day. No volume in the feed, so this is a
    typical-price mean — a session fair-value proxy, which is what the fade
    setups actually need."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    return tp.groupby(day).expanding().mean().reset_index(level=0, drop=True)


def build(df):
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    f["atr"] = atr(df, 14)
    f["atr_pct"] = f["atr"] / c
    f["ema20"] = c.ewm(span=20, adjust=False).mean()
    f["ema50"] = c.ewm(span=50, adjust=False).mean()
    f["ema200"] = c.ewm(span=200, adjust=False).mean()
    f["rsi"] = rsi(c, 14)
    f["vwap"] = session_vwap(df)

    # distance from fair value, in ATR — the fade signal
    f["vwap_dist"] = (c - f["vwap"]) / f["atr"]
    f["ema_dist"] = (c - f["ema20"]) / f["atr"]

    # trend context
    f["trend"] = np.where(c > f["ema200"], 1, -1)
    f["slope"] = (f["ema20"] - f["ema20"].shift(10)) / f["atr"]

    # recent thrust / exhaustion
    f["ret5"] = (c - c.shift(5)) / f["atr"]
    f["ret20"] = (c - c.shift(20)) / f["atr"]

    # position inside the recent range
    hh = df["high"].rolling(40).max()
    ll = df["low"].rolling(40).min()
    f["range_pos"] = (c - ll) / (hh - ll).replace(0, np.nan)

    # liquidity sweep: wick beyond the prior 20-bar extreme, closing back inside
    ph = df["high"].rolling(20).max().shift(1)
    pl = df["low"].rolling(20).min().shift(1)
    f["swept_low"] = ((df["low"] < pl) & (c > pl)).astype(int)
    f["swept_high"] = ((df["high"] > ph) & (c < ph)).astype(int)

    # volatility regime relative to its own recent norm
    f["atr_rel"] = f["atr"] / f["atr"].rolling(96).median()

    # bar body strength
    f["body"] = (c - df["open"]) / f["atr"]

    f["hour"] = df.index.hour
    return f
