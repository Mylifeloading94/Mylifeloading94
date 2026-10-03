"""
Gold (XAUUSD) signal definitions, shared by the backtest AND the live bot so the
two can never silently diverge.

Every function takes a DataFrame of CLOSED signal-timeframe MID bars
(open/high/low/close, UTC index labelled by bar START) and returns
    (long_signal, short_signal, risk_distance)
as numpy arrays aligned to the bars. A True at index i means: "bar i has just
closed and the setup is complete". Nothing here reads bar i+1.
Rolling extremes are always .shift(1), so a level can never be redrawn by the
bar being judged.
"""
import numpy as np
import pandas as pd


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rma(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def atr(b, n=14):
    pc = b.close.shift(1)
    tr = pd.concat([b.high - b.low, (b.high - pc).abs(), (b.low - pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)


def rsi(s, n=14):
    d = s.diff()
    return 100 - 100 / (1 + rma(d.clip(lower=0), n) / rma(-d.clip(upper=0), n))


def adx(b, n=14):
    up, dn = b.high.diff(), -b.low.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(b, n)
    pdi = 100 * rma(pd.Series(pdm, index=b.index), n) / a
    mdi = 100 * rma(pd.Series(mdm, index=b.index), n) / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return rma(dx.fillna(0), n)


def _gate(b, a, vol_lo, vol_hi, hours):
    """Volatility-regime + session gate. ATR must sit inside a band of its own
    500-bar median, so dead tape and news spikes are skipped."""
    med = a.rolling(500).median()
    ok = (a >= vol_lo * med) & (a <= vol_hi * med) & med.notna()
    if hours is not None:
        h = b.index.hour
        s, e = hours
        ok &= (h >= s) & (h < e) if s < e else ((h >= s) | (h < e))
    return ok.to_numpy()


def _side(long_, short_, side):
    if side == "long":
        short_ = np.zeros_like(short_)
    elif side == "short":
        long_ = np.zeros_like(long_)
    return long_, short_


# --------------------------------------------------------------------------
# 1. Momentum continuation: buy strength / sell weakness after a range break
# --------------------------------------------------------------------------
def momentum(b, bo_len=20, rsi_thr=75.0, trend_ema=200, fast_ema=50, stack=True,
             sl_atr=3.0, side="both", vol_lo=0.5, vol_hi=2.2, hours=None):
    a = atr(b)
    r = rsi(b.close)
    es, ef = ema(b.close, trend_ema), ema(b.close, fast_ema)
    hi = b.high.rolling(bo_len).max().shift(1)
    lo = b.low.rolling(bo_len).min().shift(1)
    up = (b.close > es) & ((ef > es) if stack else True)
    dn = (b.close < es) & ((ef < es) if stack else True)
    ok = _gate(b, a, vol_lo, vol_hi, hours)
    long_ = ok & (up & (b.close > hi) & (r > rsi_thr)).to_numpy()
    short_ = ok & (dn & (b.close < lo) & (r < 100 - rsi_thr)).to_numpy()
    long_, short_ = _side(long_, short_, side)
    return long_, short_, (sl_atr * a).to_numpy()


# --------------------------------------------------------------------------
# 2. Trend pullback: short-RSI washout inside an established trend
# --------------------------------------------------------------------------
def pullback(b, trend_ema=200, rsi_len=3, dip=15.0, sl_atr=2.0, side="both",
             vol_lo=0.5, vol_hi=2.2, hours=None):
    a = atr(b)
    r = rsi(b.close, rsi_len)
    es = ema(b.close, trend_ema)
    ok = _gate(b, a, vol_lo, vol_hi, hours)
    long_ = ok & ((b.close > es) & (r < dip)).to_numpy()
    short_ = ok & ((b.close < es) & (r > 100 - dip)).to_numpy()
    long_, short_ = _side(long_, short_, side)
    return long_, short_, (sl_atr * a).to_numpy()


# --------------------------------------------------------------------------
# 3. Range fade: stretched move away from the mean in a NON-trending market
# --------------------------------------------------------------------------
def fade(b, bb_len=20, bb_k=2.5, rsi_len=7, rsi_thr=20.0, adx_max=25.0, sl_atr=2.5,
         side="both", vol_lo=0.5, vol_hi=2.2, hours=None,
         trend_ema=0, confirm=False, min_ratio=0.0):
    """Buy a statistical washout (short: sell a spike).

    trend_ema > 0   longs only when close is ABOVE that EMA, shorts only BELOW it
                    (buy dips in an uptrend / sell rips in a downtrend).
    confirm         wait one bar: the washout must have happened on the PREVIOUS
                    bar and the current bar must close back in the trade direction.
    min_ratio       require ATR >= min_ratio x its 500-bar median (panic volatility).
    All defaults reproduce the original behaviour exactly.
    """
    a = atr(b)
    m = b.close.rolling(bb_len).mean()
    sd = b.close.rolling(bb_len).std()
    r = rsi(b.close, rsi_len)
    x = adx(b)
    ok = _gate(b, a, vol_lo, vol_hi, hours) & (x < adx_max).to_numpy()
    if min_ratio > 0:
        ok = ok & (a >= min_ratio * a.rolling(500).median()).to_numpy()
    lraw = (b.close < m - bb_k * sd) & (r < rsi_thr)
    sraw = (b.close > m + bb_k * sd) & (r > 100 - rsi_thr)
    if confirm:
        lraw = lraw.shift(1, fill_value=False) & (b.close > b.open) & (b.close > b.close.shift(1))
        sraw = sraw.shift(1, fill_value=False) & (b.close < b.open) & (b.close < b.close.shift(1))
    if trend_ema:
        es = ema(b.close, trend_ema)
        lraw &= (b.close > es)
        sraw &= (b.close < es)
    long_ = ok & lraw.to_numpy()
    short_ = ok & sraw.to_numpy()
    long_, short_ = _side(long_, short_, side)
    return long_, short_, (sl_atr * a).to_numpy()


# --------------------------------------------------------------------------
# 4. Session range breakout: Asian range broken during London (intraday)
# --------------------------------------------------------------------------
def session_breakout(b, asia=(0, 7), window=(7, 12), sl_atr=2.0, side="both",
                     trend_ema=0, min_range_atr=0.5, max_range_atr=4.0):
    a = atr(b)
    day = b.index.normalize()
    h = b.index.hour
    in_asia = (h >= asia[0]) & (h < asia[1])
    ah = b.high.where(in_asia).groupby(day).transform("max")
    al = b.low.where(in_asia).groupby(day).transform("min")
    # the range is only COMPLETE once the Asian session is over
    done = h >= asia[1]
    rng = (ah - al)
    sane = (rng >= min_range_atr * a) & (rng <= max_range_atr * a)
    win = (h >= window[0]) & (h < window[1])
    trend_up = trend_dn = True
    if trend_ema:
        es = ema(b.close, trend_ema)
        trend_up, trend_dn = b.close > es, b.close < es
    lc = (b.close > ah) & done & win & sane & trend_up
    sc = (b.close < al) & done & win & sane & trend_dn
    # only the FIRST breakout of each day
    lfirst = lc & (lc.groupby(day).cumsum() == 1)
    sfirst = sc & (sc.groupby(day).cumsum() == 1)
    long_, short_ = lfirst.to_numpy(), sfirst.to_numpy()
    long_, short_ = _side(long_, short_, side)
    return long_, short_, (sl_atr * a).to_numpy()


STRATEGIES = {"momentum": momentum, "pullback": pullback, "fade": fade,
              "session_breakout": session_breakout}
