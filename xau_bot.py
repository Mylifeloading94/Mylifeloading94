"""
XAUUSD daily trend-pullback bot + honest backtest.

Data: real Yahoo Finance GC=F (COMEX gold futures, tracks spot XAUUSD) daily bars,
cached to data/GC_D1.csv. Nothing is simulated or fabricated.

Rules (all decided on the CLOSE of day t, executed from day t+1 -> no lookahead):
  LONG  : close > EMA(trend) and RSI(2) < rsi_buy
  SHORT : (optional) close < EMA(trend) and RSI(2) > rsi_sell
  Entry : next open, pay spread/slippage
  Stop  : sl_atr * ATR(14);  Target: tp_atr * ATR(14);  time stop: max_hold days
  Fills : stop checked first when a bar touches both (pessimistic); gaps fill at the open
  Size  : risk_pct of equity per trade at the stop distance
"""
import sys, os, itertools, json
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "data", "GC_D1.csv")
SPREAD = 0.50          # $/oz round-trip cost (spread + slippage), conservative for gold
START_EQ = 100_000.0


def load():
    return pd.read_csv(DATA, parse_dates=["time"], index_col="time")[["open", "high", "low", "close"]]


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def atr(df, n=14):
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def backtest(df, trend=200, rsi_n=2, rsi_buy=10, rsi_sell=90, shorts=False,
             sl_atr=3.0, tp_atr=1.0, max_hold=10, risk_pct=0.01, start=None, end=None):
    d = df.copy()
    d["ema"] = d.close.ewm(span=trend, adjust=False).mean()
    d["rsi"] = rsi(d.close, rsi_n)
    d["atr"] = atr(d)
    o, h, l, c = (d[x].values for x in ("open", "high", "low", "close"))
    idx = d.index
    eq = START_EQ
    trades, curve = [], []
    i, n = trend, len(d)
    pos = None
    while i < n - 1:
        if pos is None:
            side = 0
            if c[i] > d.ema.iat[i] and d.rsi.iat[i] < rsi_buy: side = 1
            elif shorts and c[i] < d.ema.iat[i] and d.rsi.iat[i] > rsi_sell: side = -1
            if side and (start is None or idx[i] >= pd.Timestamp(start, tz="UTC")):
                a = d.atr.iat[i]
                entry = o[i + 1] + side * SPREAD / 2
                sl = entry - side * sl_atr * a
                tp = entry + side * tp_atr * a
                units = eq * risk_pct / abs(entry - sl)
                pos = dict(side=side, entry=entry, sl=sl, tp=tp, units=units, t0=idx[i + 1], k=i + 1)
            i += 1
            curve.append((idx[i], eq))
            continue
        # manage open position on bar i (entry bar handled with k==i)
        s = pos["side"]; exit_p = None; why = None
        j = i
        if s == 1:
            if o[j] <= pos["sl"]: exit_p, why = o[j], "gapSL"
            elif l[j] <= pos["sl"]: exit_p, why = pos["sl"], "SL"
            elif h[j] >= pos["tp"]: exit_p, why = pos["tp"], "TP"
        else:
            if o[j] >= pos["sl"]: exit_p, why = o[j], "gapSL"
            elif h[j] >= pos["sl"]: exit_p, why = pos["sl"], "SL"
            elif l[j] <= pos["tp"]: exit_p, why = pos["tp"], "TP"
        if exit_p is None and j - pos["k"] + 1 >= max_hold:
            exit_p, why = c[j], "time"
        if exit_p is not None:
            exit_p -= s * SPREAD / 2
            pnl = s * (exit_p - pos["entry"]) * pos["units"]
            eq += pnl
            trades.append(dict(entry_t=pos["t0"], exit_t=idx[j], side=s, entry=pos["entry"],
                               exit=exit_p, pnl=pnl, ret=pnl / (eq - pnl), why=why))
            pos = None
        curve.append((idx[j], eq))
        i += 1
    cv = pd.Series(dict(curve))
    cv = cv[~cv.index.duplicated(keep="last")]
    return pd.DataFrame(trades), cv


def stats(tr, cv, label=""):
    if len(tr) == 0:
        return dict(label=label, n=0)
    w = tr[tr.pnl > 0].pnl.sum(); lo = -tr[tr.pnl < 0].pnl.sum()
    peak = cv.cummax(); dd = ((cv - peak) / peak).min()
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    return dict(label=label, n=len(tr), win=round((tr.pnl > 0).mean() * 100, 1),
                pf=round(w / lo, 2) if lo else float("inf"),
                avg_win=round(tr[tr.pnl > 0].pnl.mean(), 0), avg_loss=round(tr[tr.pnl < 0].pnl.mean(), 0) if lo else 0,
                net_pct=round((cv.iloc[-1] / START_EQ - 1) * 100, 1),
                cagr=round(((cv.iloc[-1] / START_EQ) ** (1 / yrs) - 1) * 100, 1),
                maxdd=round(dd * 100, 1))


def window(tr, cv, a, b):
    a, b = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
    t = tr[(tr.entry_t >= a) & (tr.entry_t <= b)].reset_index(drop=True)
    return t, cv[(cv.index >= a) & (cv.index <= b)]


if __name__ == "__main__":
    df = load()
    tr, cv = backtest(df)
    print(stats(tr, cv, "default"))
