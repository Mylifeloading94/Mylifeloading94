"""Module 1 - indicators. All series are causal: value[i] uses bars 0..i only."""
import numpy as np


def sma(x, n):
    out = np.full(len(x), np.nan); c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def ema(x, n):
    out = np.empty(len(x)); k = 2 / (n + 1); e = x[0]
    for i, v in enumerate(x):
        e = v if i == 0 else e + k * (v - e); out[i] = e
    return out


def rma(x, n):
    """Wilder smoothing, seeded with an SMA of the first n values."""
    out = np.full(len(x), np.nan)
    if len(x) < n: return out
    out[n - 1] = np.nanmean(x[:n])
    for i in range(n, len(x)): out[i] = out[i - 1] + (x[i] - out[i - 1]) / n
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = rma(np.maximum(d, 0), n); dn = rma(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn; r = 100 - 100 / (1 + rs)
    r[dn == 0] = 100.0
    return r


def true_range(h, l, c):
    pc = np.roll(c, 1); pc[0] = c[0]
    return np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))


def atr(h, l, c, n=14):
    return rma(true_range(h, l, c), n)


def adx(h, l, c, n=14):
    up = np.diff(h, prepend=h[0]); dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = rma(true_range(h, l, c), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * rma(pdm, n) / tr; ndi = 100 * rma(ndm, n) / tr
        dx = 100 * abs(pdi - ndi) / (pdi + ndi)
    dx = np.nan_to_num(dx)
    return rma(dx, n), pdi, ndi


def bollinger(c, n=20, dev=2.0):
    mid = sma(c, n); sd = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)): sd[i] = c[i - n + 1:i + 1].std()   # population stdev, like TradingView
    up, lo = mid + dev * sd, mid - dev * sd
    with np.errstate(divide="ignore", invalid="ignore"):
        pctb = (c - lo) / (up - lo); bw = (up - lo) / mid
    return up, mid, lo, pctb, bw


def rolling_pct_rank(x, n):
    """Percentile (0-100) of x[i] within x[i-n+1..i]."""
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if np.isnan(w).any(): continue
        out[i] = 100.0 * (w < x[i]).sum() / (n - 1)
    return out


def compute(bars, cfg):
    """bars: dict of numpy arrays t,o,h,l,c. Returns dict of indicator arrays aligned to bars."""
    o, h, l, c = bars["o"], bars["h"], bars["l"], bars["c"]
    up, mid, lo, pctb, bw = bollinger(c, cfg["bb_len"], cfg["bb_dev"])
    a, pdi, ndi = adx(h, l, c, cfg["adx_len"])
    return dict(up=up, mid=mid, lo=lo, pctb=pctb, bw=bw, bw_pct=rolling_pct_rank(bw, cfg["bw_lookback"]),
                ema_f=ema(c, cfg["ema_fast"]), ema_s=ema(c, cfg["ema_slow"]), rsi=rsi(c, cfg["rsi_len"]),
                adx=a, pdi=pdi, ndi=ndi, atr=atr(h, l, c, cfg["atr_len"]))
