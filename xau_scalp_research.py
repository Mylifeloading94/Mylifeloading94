"""
High-frequency XAUUSD scalp research (target: 4-10 trades/day, SL <= 50 pips so a
0.01 lot fits 1% risk on a $500 account).

Every family is filtered by the daily trend (D1 EMA20/50), the ingredient that gave
v2 its edge. Fills, spread and stop-first rules come from xau_research.sim_trade.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xau_research as xr  # noqa: E402


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50)


def prep(tf, d1_bias, h1_bias=None):
    df = tf.copy()
    df["atr"] = xr.atr(df)
    df["e21"] = xr.ema(df["close"], 21)
    df["e50"] = xr.ema(df["close"], 50)
    df["rsi"] = rsi(df["close"])
    step = df.index[1] - df.index[0]
    df["trend"] = [d1_bias(t + step) for t in df.index]
    if h1_bias is not None:
        df["h1"] = [h1_bias(t + step) for t in df.index]
    df["hour"] = df.index.hour
    return df, step


def sig_frame(df, step, mask_long, mask_short, sl_atr, hours):
    out = []
    a = df["atr"].values
    c = df["close"].values
    hr = df["hour"].values
    for d, mask in ((1, mask_long), (-1, mask_short)):
        idx = np.where(mask & (hr >= hours[0]) & (hr < hours[1]) & np.isfinite(a))[0]
        for i in idx:
            out.append(dict(time=df.index[i] + step, dir=d, entry=None, sl=c[i] - d * sl_atr * a[i]))
    out.sort(key=lambda s: s["time"])
    return out


# --------------------------------------------------------------- families
def fam_pullback(df, step, sl_atr=1.0, hours=(6, 17), pb=6, use_h1=False):
    """Trend pullback to EMA21 + momentum break candle (v1 scalp logic) with D1 trend."""
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    rng = (h - l).replace(0, np.nan)
    strong = (c - o).abs() / rng >= 0.5
    pbl = l.rolling(pb).min()
    pbh = h.rolling(pb).max()
    a = df["atr"]
    tl, ts = df["trend"] == 1, df["trend"] == -1
    if use_h1:
        tl &= df["h1"] == 1
        ts &= df["h1"] == -1
    longm = (tl & (df.e21 > df.e50) & (pbl <= df.e21 + 0.25 * a) & (pbl >= df.e50 - 0.5 * a) & (c > o) & strong
             & (c > h.shift(1)) & (c > df.e21) & (df.rsi > 50) & (df.rsi < 75))
    shortm = (ts & (df.e21 < df.e50) & (pbh >= df.e21 - 0.25 * a) & (pbh <= df.e50 + 0.5 * a) & (c < o) & strong
              & (c < l.shift(1)) & (c < df.e21) & (df.rsi < 50) & (df.rsi > 25))
    return sig_frame(df, step, longm.values, shortm.values, sl_atr, hours)


def fam_hour_break(df, step, sl_atr=1.0, hours=(6, 17)):
    """Break of the previous H1 candle's high/low (first cross) with D1 trend."""
    h1 = df.resample("1h").agg({"high": "max", "low": "min"})
    prev = h1.shift(1).reindex(df.index, method="ffill")
    c = df["close"]
    cross_up = (c > prev["high"]) & (c.shift(1) <= prev["high"])
    cross_dn = (c < prev["low"]) & (c.shift(1) >= prev["low"])
    return sig_frame(df, step, (cross_up & (df.trend == 1)).values, (cross_dn & (df.trend == -1)).values, sl_atr, hours)


def fam_donchian(df, step, n=12, sl_atr=1.0, hours=(6, 17), squeeze=None):
    """Break of the last n-bar high/low with D1 trend (optional tight-range squeeze)."""
    c = df["close"]
    hh = df["high"].rolling(n).max().shift(1)
    ll = df["low"].rolling(n).min().shift(1)
    up = (c > hh) & (c.shift(1) <= hh.shift(1))
    dn = (c < ll) & (c.shift(1) >= ll.shift(1))
    if squeeze:
        tight = (hh - ll) <= squeeze * df["atr"]
        up &= tight
        dn &= tight
    return sig_frame(df, step, (up & (df.trend == 1)).values, (dn & (df.trend == -1)).values, sl_atr, hours)


def fam_ema_bounce(df, step, sl_atr=1.0, hours=(6, 17)):
    """Price dips to EMA50 in a D1 + local uptrend and closes back above EMA21."""
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    longm = (df.trend == 1) & (df.e21 > df.e50) & (l <= df.e50) & (c > df.e21) & (c > o)
    shortm = (df.trend == -1) & (df.e21 < df.e50) & (h >= df.e50) & (c < df.e21) & (c < o)
    return sig_frame(df, step, longm.values, shortm.values, sl_atr, hours)


# ------------------------------------------------------------------ runner
def evaluate(m, sigs, label, tp1_r, tp2_r, frac, tstop, sl_min=20, sl_max=50, split=None, days=None):
    df = xr.run_signals(m, sigs, tp1_r=tp1_r, tp2_r=tp2_r, tp1_frac=frac, tstop_min=tstop,
                        limit=False, sl_min=sl_min * xr.PIP, sl_max=sl_max * xr.PIP)
    if len(df) == 0:
        print(f"{label:58s} no trades")
        return df
    r = df["R"].values
    gw, gl = r[r > 0].sum(), -r[r <= 0].sum()
    per_day = len(r) / days if days else 0
    line = (f"{label:58s} n={len(r):4d} /day={per_day:4.1f} win%={100 * (r > 0).mean():5.1f} "
            f"PF={gw / gl if gl else 0:4.2f} avgR={r.mean():+.3f} totR={r.sum():+6.1f}")
    if split is not None:
        line += f" | <{split.date()} {df[df.time < split].R.sum():+5.1f}R  >= {df[df.time >= split].R.sum():+5.1f}R"
    print(line, flush=True)
    return df


def fam_dip(df, step, n=12, sl_atr=1.0, hours=(6, 17), rsi_lo=None):
    """Mean reversion inside the daily trend: in a D1 uptrend buy the first close below
    the last n-bar low (sell the first close above the n-bar high in a downtrend)."""
    c = df["close"]
    hh = df["high"].rolling(n).max().shift(1)
    ll = df["low"].rolling(n).min().shift(1)
    dip = (c < ll) & (c.shift(1) >= ll.shift(1))
    pop = (c > hh) & (c.shift(1) <= hh.shift(1))
    if rsi_lo:
        dip &= df.rsi < rsi_lo
        pop &= df.rsi > 100 - rsi_lo
    return sig_frame(df, step, (dip & (df.trend == 1)).values, (pop & (df.trend == -1)).values, sl_atr, hours)
