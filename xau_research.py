"""
XAUUSD strategy research harness (honest fills on Dukascopy M1 BID data).

Candidate entries:
  sniper : liquidity sweep -> displacement (MSS) -> limit entry in the OTE pocket
           of the displacement leg  (port of sniper_smc.py logic to gold)
  asia   : London "Judas swing" - sweep of the Asian range that closes back
           inside, reversal toward the other side of the range

Execution model (per trade, on M1):
  - market entries at next M1 open (+spread for buys)
  - limit entries need a trade-through (buy: ask < limit, sell: bid > limit)
  - SL checked before TP inside a bar; same-bar TP+SL = SL
  - TP1 closes `tp1_frac`, then SL -> breakeven + lock; runner to TP2 or time stop
Results are in R (risk units) so they are independent of account size.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SPREAD = 0.30   # $0.30 = 3 pips
PIP = 0.10


# --------------------------------------------------------------------- data
def load(name):
    df = pd.read_csv(os.path.join(HERE, "data", name))
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.index = df.index.tz_localize(None)     # UTC, naive
    return df


def load_m1_all():
    """Merge cached Dukascopy daily M1 files into one frame."""
    import datetime as dt
    import fetch_dukascopy_xau as f
    rows = []
    d = os.path.join(HERE, "data", "duka_xau")
    for fn in sorted(os.listdir(d)):
        if not fn[:8].isdigit():
            continue
        day = dt.date(int(fn[:4]), int(fn[4:6]), int(fn[6:8]))
        rows += f.parse(day, open(os.path.join(d, fn), "rb").read())
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).set_index("time")
    df.index = df.index.tz_localize(None)
    df = df.sort_index()
    return df[~df.index.duplicated(keep="first")]


def resample(m1, rule):
    r = m1.resample(rule, label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


# ---------------------------------------------------------------- simulator
class M1:
    def __init__(self, m1):
        self.t = m1.index.values
        self.o, self.h, self.l, self.c = (m1[k].values for k in ("open", "high", "low", "close"))

    def idx(self, ts):
        return int(np.searchsorted(self.t, np.datetime64(ts), side="left"))


def sim_trade(m, i0, d, entry, sl, tp1, tp2, limit=False, expiry=None, tstop=None,
              tp1_frac=0.5, be_lock=3 * PIP, spread=SPREAD):
    """Return (R, fill_index, exit_index) or None if a limit never filled."""
    n = len(m.t)
    i = i0
    # ---- fill
    if limit:
        end = min(expiry if expiry is not None else n, n)
        filled = False
        while i < end:
            if d > 0:
                if m.l[i] + spread < entry:
                    filled = True
                    break
                if m.h[i] >= tp1:            # ran to target without us
                    return None
            else:
                if m.h[i] > entry:
                    filled = True
                    break
                if m.l[i] + spread <= tp1:
                    return None
            i += 1
        if not filled:
            return None
    else:
        if i >= n:
            return None
        entry = m.o[i] + (spread if d > 0 else 0.0)
    R = d * (entry - sl)
    if R <= 0:
        return None
    end = min(tstop if tstop is not None else n, n)
    stop = sl
    got = 0.0          # realised R so far
    rem = 1.0          # remaining fraction
    tp1_done = False
    j = i
    while j < end:
        lo, hi = (m.l[j], m.h[j]) if d > 0 else (m.l[j] + spread, m.h[j] + spread)
        # stop first (conservative)
        if (d > 0 and lo <= stop) or (d < 0 and hi >= stop):
            px = stop
            if j > i:  # gap through stop at bar open
                op = m.o[j] if d > 0 else m.o[j] + spread
                if (d > 0 and op < stop) or (d < 0 and op > stop):
                    px = op
            got += rem * d * (px - entry) / R
            return got, i, j
        if not tp1_done and ((d > 0 and hi >= tp1) or (d < 0 and lo <= tp1)):
            got += tp1_frac * d * (tp1 - entry) / R
            rem -= tp1_frac
            tp1_done = True
            stop = entry + d * be_lock
            if rem <= 1e-9:
                return got, i, j
        if tp1_done and ((d > 0 and hi >= tp2) or (d < 0 and lo <= tp2)):
            got += rem * d * (tp2 - entry) / R
            return got, i, j
        j += 1
    j = min(end, n) - 1
    px = m.c[j] if d > 0 else m.c[j] + spread
    got += rem * d * (px - entry) / R
    return got, i, j


# ------------------------------------------------------------------ signals
def sniper_signals(tf, bias=None, kz=((7, 11), (12, 16)), sweep_n=20, mss_bars=4, disp=1.1,
                   ote=0.705, sl_buf=0.5, retrace_bars=8):
    """Yield dicts: time (TF close of MSS bar), dir, entry(limit), sl, leg."""
    a = atr(tf).values
    o, h, l, c = (tf[k].values for k in ("open", "high", "low", "close"))
    T = tf.index
    step = T[1] - T[0] if len(T) > 1 else pd.Timedelta("5min")
    out = []
    for i in range(sweep_n + 15, len(tf) - mss_bars - 1):
        hr = T[i].hour
        if kz and not any(s <= hr < e for s, e in kz):
            continue
        if not np.isfinite(a[i]):
            continue
        prior_low = l[i - sweep_n:i].min()
        prior_high = h[i - sweep_n:i].max()
        for d in (1, -1):
            if d > 0 and not (l[i] < prior_low and c[i] > prior_low):
                continue
            if d < 0 and not (h[i] > prior_high and c[i] < prior_high):
                continue
            b = bias(T[i]) if bias else d
            if b != d:
                continue
            ext = l[i] if d > 0 else h[i]
            for k in range(i + 1, i + 1 + mss_bars):
                body = c[k] - o[k]
                if d > 0:
                    struct = h[max(i - 5, 0):k].max()
                    ok = body >= disp * a[i] and c[k] > struct
                else:
                    struct = l[max(i - 5, 0):k].min()
                    ok = -body >= disp * a[i] and c[k] < struct
                if ok:
                    leg_end = h[i:k + 1].max() if d > 0 else l[i:k + 1].min()
                    entry = leg_end - d * ote * abs(leg_end - ext)
                    sl = ext - d * sl_buf * a[i]
                    out.append(dict(time=T[k] + step, dir=d, entry=entry, sl=sl,
                                    expiry=T[k] + step * (retrace_bars + 1)))
                    break
    return out


def asia_signals(m5, asia=(0, 6), window=(6, 10), buf_atr=0.2):
    """London Judas swing: M5 close back inside after sweeping the Asian range."""
    a = atr(m5).values
    out = []
    days = m5.groupby(m5.index.date)
    for day, g in days:
        asia_g = g[(g.index.hour >= asia[0]) & (g.index.hour < asia[1])]
        if len(asia_g) < 40:
            continue
        ah, al = asia_g["high"].max(), asia_g["low"].min()
        lon = g[(g.index.hour >= window[0]) & (g.index.hour < window[1])]
        done = set()
        for ts, row in lon.iterrows():
            ii = m5.index.get_loc(ts)
            if not np.isfinite(a[ii]):
                continue
            if -1 not in done and row.high > ah and row.close < ah:
                out.append(dict(time=ts + pd.Timedelta("5min"), dir=-1, entry=None,
                                sl=row.high + buf_atr * a[ii], tgt=al, mid=(ah + al) / 2))
                done.add(-1)
            if 1 not in done and row.low < al and row.close > al:
                out.append(dict(time=ts + pd.Timedelta("5min"), dir=1, entry=None,
                                sl=row.low - buf_atr * a[ii], tgt=ah, mid=(ah + al) / 2))
                done.add(1)
    return out


def ema_bias(htf, fast=50, slow=200):
    f, s, c = ema(htf["close"], fast).values, ema(htf["close"], slow).values, htf["close"].values
    close_t = (htf.index + (htf.index[1] - htf.index[0])).values

    def fn(ts):
        k = int(np.searchsorted(close_t, np.datetime64(ts), side="right")) - 1
        if k < slow:
            return 0
        if c[k] > s[k] and f[k] > s[k]:
            return 1
        if c[k] < s[k] and f[k] < s[k]:
            return -1
        return 0
    return fn


# ------------------------------------------------------------------- runner
def run_signals(m, sigs, tp1_r=1.0, tp2_r=2.5, tp1_frac=0.5, tstop_min=48 * 5, limit=True,
                sl_min=None, sl_max=None, use_tgt=False):
    res = []
    busy_until = -1
    for s in sigs:
        i0 = m.idx(s["time"])
        if i0 <= busy_until or i0 >= len(m.t):
            continue
        d = s["dir"]
        if limit:
            entry = s["entry"]
        else:
            entry = m.o[i0] + (SPREAD if d > 0 else 0.0)
        R = d * (entry - s["sl"])
        if not np.isfinite(R) or R <= 0:
            continue
        if sl_min and R < sl_min:
            R = sl_min
        if sl_max and R > sl_max:
            continue
        sl = entry - d * R
        tp1 = entry + d * tp1_r * R
        tp2 = entry + d * tp2_r * R
        if use_tgt and s.get("tgt") is not None:
            if d * (s["tgt"] - entry) > 1.2 * R:
                tp2 = s["tgt"]
        expiry = m.idx(s["expiry"]) if limit else None
        r = sim_trade(m, i0, d, entry, sl, tp1, tp2, limit=limit, expiry=expiry,
                      tstop=None, tp1_frac=tp1_frac)
        if r is None:
            continue
        R_res, fi, xi = r
        ts = fi + tstop_min
        if xi > ts:   # apply time stop
            r = sim_trade(m, i0, d, entry, sl, tp1, tp2, limit=limit, expiry=expiry,
                          tstop=ts, tp1_frac=tp1_frac)
            R_res, fi, xi = r
        busy_until = xi
        res.append(dict(time=pd.Timestamp(m.t[fi]), dir=d, R=R_res, risk_pips=R / PIP))
    return pd.DataFrame(res)


def report(label, df, split=None):
    if df is None or len(df) == 0:
        print(f"{label:46s} no trades")
        return
    r = df["R"].values
    wins, losses = r[r > 0].sum(), -r[r <= 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    line = (f"{label:46s} n={len(r):4d} win%={100 * (r > 0).mean():5.1f} PF={pf:4.2f} "
            f"avgR={r.mean():+.3f} totR={r.sum():+6.1f}")
    if split is not None:
        a = df[df["time"] < split]["R"].sum()
        b = df[df["time"] >= split]["R"].sum()
        line += f" | before {a:+5.1f}R after {b:+5.1f}R"
    print(line, flush=True)


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    m1 = load_m1_all()
    print("M1", m1.index[0], "->", m1.index[-1], len(m1))
