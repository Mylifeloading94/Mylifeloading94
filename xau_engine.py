"""
XAUUSD backtest engine on bid/ask M1 bars (Dukascopy, 2019 -> today).

Fill model (deliberately pessimistic):
  * Signals use only CLOSED signal-timeframe bars. Entry is the first M1 bar
    that opens at/after the signal bar's close.
  * Longs enter at the ASK and exit at the BID; shorts the reverse, so the real
    time-varying spread is paid on every trade. No fixed-spread assumption.
  * If one M1 bar touches both the stop and the target, the STOP is assumed to
    have hit first. (Ticks would sometimes say otherwise; this never flatters.)
  * A bar that gaps through the stop fills at its open, not at the stop.
  * Positions are flattened at the last bar before any market closure
    (gap > 30 min), so nothing is held through a weekend.
"""
import glob, os
import numpy as np
import pandas as pd
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
M1_DIR = os.path.join(HERE, "data", "m1")
CACHE = os.path.join(HERE, "data", "XAUUSD_M1_bidask.parquet")


def _min(idx):
    """Epoch MINUTES as int64, whatever resolution pandas stored the index in.

    pandas 3 no longer defaults to nanoseconds, so idx.view("int64") silently
    changes meaning; as_unit("ns") pins it."""
    return (idx.as_unit("ns").asi8 // 60_000_000_000).astype(np.int64)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load_m1(refresh=False):
    """All M1 bid/ask bars, UTC index. Rebuilt from per-day files if stale."""
    files = sorted(glob.glob(os.path.join(M1_DIR, "*.parquet")))
    if (not refresh and os.path.exists(CACHE)
            and os.path.getmtime(CACHE) >= os.path.getmtime(files[-1])):
        return pd.read_parquet(CACHE)
    parts = [pd.read_parquet(f) for f in files]
    parts = [p for p in parts if len(p)]
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.to_parquet(CACHE)
    return df


def to_tf(m1, rule):
    """Signal-timeframe MID bars (open/high/low/close) from M1 bid/ask.

    Bars are labelled by their START time. A bar labelled T is only knowable
    at T + rule; callers must enter after that moment, never at T.
    """
    mo = (m1.bo + m1.ao) / 2
    mh = (m1.bh + m1.ah) / 2
    ml = (m1.bl + m1.al) / 2
    mc = (m1.bc + m1.ac) / 2
    if rule in ("1min", "1T"):
        out = pd.DataFrame({"open": mo, "high": mh, "low": ml, "close": mc})
    else:
        r = lambda s, f: s.resample(rule, label="left", closed="left").agg(f)
        out = pd.DataFrame({"open": r(mo, "first"), "high": r(mh, "max"),
                            "low": r(ml, "min"), "close": r(mc, "last")}).dropna()
    return out.astype("float64")


def tf_minutes(rule):
    return int(pd.Timedelta(rule).total_seconds() // 60)


# --------------------------------------------------------------------------
# Simulation (numba)
# --------------------------------------------------------------------------
@njit(cache=True)
def _sim(entry_i, direction, risk, tp_mult, hold_min, be_r,
         tmin, bo, bh, bl, bc, ao, ah, al, ac, out_exit, out_i, out_reason, bar_min, gap_min):
    n = len(tmin)
    for k in range(len(entry_i)):
        j0 = entry_i[k]
        d = direction[k]
        r = risk[k]
        if d == 1:
            entry = ao[j0]
            stop = entry - r
            target = entry + tp_mult * r if tp_mult > 0 else 1e18
        else:
            entry = bo[j0]
            stop = entry + r
            target = entry - tp_mult * r if tp_mult > 0 else -1e18
        deadline = tmin[j0] + hold_min
        cur = stop
        be_armed = False
        ex = np.nan
        why = 0                       # 1 stop 2 target 3 time 4 closure 5 breakeven
        jx = j0
        for j in range(j0, n):
            jx = j
            if d == 1:
                if j > j0 and bo[j] <= cur:                 # gapped through stop
                    ex = bo[j]; why = 5 if be_armed else 1; break
                if bl[j] <= cur:                            # stop checked FIRST
                    ex = cur; why = 5 if be_armed else 1; break
                if bh[j] >= target:
                    ex = target; why = 2; break
            else:
                if j > j0 and ao[j] >= cur:
                    ex = ao[j]; why = 5 if be_armed else 1; break
                if ah[j] >= cur:
                    ex = cur; why = 5 if be_armed else 1; break
                if al[j] <= target:
                    ex = target; why = 2; break
            if tmin[j] + bar_min >= deadline:               # bar j closes at deadline
                ex = bc[j] if d == 1 else ac[j]; why = 3; break
            if j + 1 < n and tmin[j + 1] - tmin[j] > gap_min:  # market about to close
                ex = bc[j] if d == 1 else ac[j]; why = 4; break
            if be_r > 0 and not be_armed:                   # arms for NEXT bar only
                fav = (bh[j] - entry) if d == 1 else (entry - al[j])
                if fav >= be_r * r:
                    be_armed = True
                    cur = entry
        if np.isnan(ex):
            ex = bc[jx] if d == 1 else ac[jx]; why = 4
        out_exit[k] = (ex - entry) / r if d == 1 else (entry - ex) / r
        out_i[k] = jx
        out_reason[k] = why


def run(m1, tf_bars, tf_rule, long_sig, short_sig, risk_dist, hold_min,
        tp_mult=0.0, be_r=0.0, cooldown_bars=1, bar_min=1, gap_min=30, max_delay=15):
    """Turn TF-bar signals into a trade table.

    long_sig/short_sig: boolean arrays aligned to tf_bars (signal known at close).
    risk_dist: stop distance in PRICE per TF bar (e.g. k * ATR).
    One position at a time; the next signal must come after the previous exit.
    """
    m = tf_minutes(tf_rule)
    tmin_all = _min(m1.index)
    sig = np.where(long_sig, 1, np.where(short_sig, -1, 0))
    cand = np.flatnonzero(sig != 0)
    if len(cand) == 0:
        return pd.DataFrame(columns=["entry_time", "dir", "r", "reason"])
    close_min = _min(tf_bars.index)[cand] + m
    ent = np.searchsorted(tmin_all, close_min, side="left")
    ok = (ent < len(tmin_all))
    ok[ok] = (tmin_all[ent[ok]] - close_min[ok]) <= max_delay   # market was open
    ok &= np.isfinite(risk_dist[cand]) & (risk_dist[cand] > 0)
    cand, ent = cand[ok], ent[ok]

    f = lambda c: np.ascontiguousarray(m1[c].to_numpy(dtype="float64"))
    arr = [f(c) for c in ("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac")]
    # Resolve overlap: simulate sequentially, skipping signals inside an open trade.
    keep_entry, keep_dir, keep_risk, keep_sig = [], [], [], []
    last_exit = -1
    r_arr, i_arr, w_arr = np.empty(1), np.empty(1, np.int64), np.empty(1, np.int64)
    order = np.arange(len(cand))
    # one-at-a-time needs the exit of each trade before choosing the next, so run
    # in chunks: simulate every candidate, then drop the overlapped ones.
    n = len(cand)
    r_all = np.empty(n); i_all = np.empty(n, np.int64); w_all = np.empty(n, np.int64)
    _sim(ent.astype(np.int64), sig[cand].astype(np.int64),
         risk_dist[cand].astype("float64"), float(tp_mult), int(hold_min), float(be_r),
         tmin_all, *arr, r_all, i_all, w_all, int(bar_min), int(gap_min))
    sel = []
    busy_until = -1
    for q in range(n):
        if ent[q] <= busy_until:
            continue
        sel.append(q)
        busy_until = i_all[q] + cooldown_bars
    sel = np.array(sel, dtype=int)
    t = pd.DataFrame({
        "entry_time": m1.index[ent[sel]], "dir": sig[cand][sel],
        "r": r_all[sel], "exit_time": m1.index[i_all[sel]],
        "reason": w_all[sel], "risk": risk_dist[cand][sel]})
    return t


REASONS = {1: "stop", 2: "target", 3: "time", 4: "closure", 5: "breakeven"}


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def stats(t, risk_pct=0.5):
    """Trade stats in R, plus compounded equity drawdown at risk_pct % per trade."""
    if t is None or len(t) == 0:
        return dict(n=0, wr=0, pf=0, exp_r=0, tot_r=0, dd_r=0, dd_pct=0, t=0,
                    avg_win=0, avg_loss=0, ret_pct=0)
    r = t.r.to_numpy()
    w, l = r[r > 0], r[r <= 0]
    gl = -l.sum()
    eq = np.cumprod(1 + risk_pct / 100 * r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    cum = np.cumsum(r)
    sd = r.std(ddof=1) if len(r) > 1 else 0
    return dict(
        n=len(r), wr=100 * len(w) / len(r),
        pf=(w.sum() / gl) if gl > 0 else float("inf"),
        exp_r=r.mean(), tot_r=r.sum(),
        dd_r=float((np.maximum.accumulate(cum) - cum).max()),
        dd_pct=float(100 * ((peak - eq) / peak).max()),
        t=(r.mean() / (sd / np.sqrt(len(r)))) if sd > 0 else 0,
        avg_win=w.mean() if len(w) else 0, avg_loss=l.mean() if len(l) else 0,
        ret_pct=float(100 * (eq[-1] - 1)))


def by_year(t, risk_pct=0.5):
    if t is None or len(t) == 0:
        return {}
    yrs = t.entry_time.dt.year
    return {int(y): stats(g, risk_pct) for y, g in t.groupby(yrs)}
