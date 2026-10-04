"""
Execution of liq_scalp signals on real M1 bid/ask. Same pessimistic rules as smc_exec:
  market entries fill at the ASK (long) / BID (short) of the first candle after the signal bar closes;
  limit entries fill only when ask/bid TRADES THROUGH the level (fill bar: only the stop is honoured);
  a candle that touches both stop and target counts as a stop; stops gap-fill at the open;
  target is a resting order (bid/ask touch); time exit at the close after hold_min; flat before closures.
R is measured against the actual risk at the fill. Risk rules from the spec: max trades/day, daily stop.
"""
import numpy as np, pandas as pd
from numba import njit
import xau_engine as E


@njit(cache=True)
def _sim_trade(act, direction, is_limit, limit, stop, target, expire_min, hold_min, tmin,
               bo, bh, bl, bc, ao, ah, al, ac, o_status, o_r, o_fill, o_end, o_why, o_fpx, o_xpx):
    n = len(tmin)
    for k in range(len(act)):
        j0 = act[k]; d = direction[k]; stp = stop[k]; tgt = target[k]
        o_status[k] = 0; o_end[k] = j0; o_fill[k] = -1; o_why[k] = 0
        jf = -1; fill = 0.0; risk = 0.0
        if is_limit[k] == 0:
            fill = ao[j0] if d == 1 else bo[j0]
            risk = d * (fill - stp)
            if risk <= 0 or d * (tgt - fill) <= 0:
                continue
            jf = j0
        else:
            lim = limit[k]; expire = tmin[j0] + expire_min
            for j in range(j0, n):
                o_end[k] = j
                if tmin[j] >= expire:
                    break
                if d == 1:
                    if al[j] <= lim:
                        fill = min(lim, ao[j]); jf = j; break
                else:
                    if bh[j] >= lim:
                        fill = max(lim, bo[j]); jf = j; break
            if jf < 0:
                continue
            risk = d * (lim - stp)
            if risk <= 0 or d * (tgt - lim) <= 0:
                continue
        o_status[k] = 1; o_fill[k] = jf; o_fpx[k] = fill
        ex = np.nan; why = 0; jx = jf
        start = jf
        if is_limit[k] == 1:                       # fill bar: stop only
            if d == 1 and bl[jf] <= stp:
                ex, why = stp, 1
            elif d == -1 and ah[jf] >= stp:
                ex, why = stp, 1
            start = jf + 1
        if why == 0:
            deadline = tmin[jf] + hold_min
            for j in range(start, n):
                jx = j
                if d == 1:
                    if bo[j] <= stp: ex, why = bo[j], 1; break
                    if bl[j] <= stp: ex, why = stp, 1; break
                    if bh[j] >= tgt: ex, why = tgt, 2; break
                else:
                    if ao[j] >= stp: ex, why = ao[j], 1; break
                    if ah[j] >= stp: ex, why = stp, 1; break
                    if al[j] <= tgt: ex, why = tgt, 2; break
                if tmin[j] + 1 >= deadline:
                    ex = bc[j] if d == 1 else ac[j]; why = 3; break
                if j + 1 < n and tmin[j + 1] - tmin[j] > 30:
                    ex = bc[j] if d == 1 else ac[j]; why = 4; break
        else:
            jx = jf
        if np.isnan(ex):
            ex = bc[jx] if d == 1 else ac[jx]; why = 4
        o_r[k] = d * (ex - fill) / risk; o_xpx[k] = ex
        o_end[k] = jx; o_why[k] = why


def run(m1, b15, sig, hold_min=360, expiry_bars=8, cooldown=1, max_per_day=3, daily_stop_r=-2.0, risk_rules=True):
    cols = ["entry_time", "exit_time", "dir", "r", "reason", "model", "rr_plan", "h1_aligned", "poi", "risk"]
    if len(sig) == 0:
        return pd.DataFrame(columns=cols)
    tmin = E._min(m1.index)
    close_min = E._min(b15.index)[sig.t.to_numpy()] + 15
    act = np.searchsorted(tmin, close_min, side="left")
    ok = act < len(tmin)
    ok[ok] = (tmin[act[ok]] - close_min[ok]) <= 15
    s = sig[ok].reset_index(drop=True); act = act[ok].astype(np.int64)
    arr = [np.ascontiguousarray(m1[c].to_numpy("float64")) for c in ("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac")]
    n = len(s)
    st = np.empty(n, np.int64); r = np.empty(n); fi = np.empty(n, np.int64); en = np.empty(n, np.int64); wy = np.empty(n, np.int64)
    fpx = np.zeros(n); xpx = np.zeros(n)
    _sim_trade(act, s.dir.to_numpy().astype(np.int64), (s.model.to_numpy() == "E3").astype(np.int64), s.entry.to_numpy("float64"),
               s.stop.to_numpy("float64"), s.target.to_numpy("float64"), int(expiry_bars * 15), int(hold_min), tmin, *arr, st, r, fi, en, wy, fpx, xpx)
    et_day = (m1.index.tz_convert("America/New_York") + pd.Timedelta(hours=7)).floor("D")
    keep, busy = [], -1
    day_n, day_r = {}, {}
    for i in range(n):
        if act[i] <= busy:
            continue
        if st[i] != 1:
            busy = en[i] + cooldown; continue
        dkey = et_day[fi[i]]
        if risk_rules and (day_n.get(dkey, 0) >= max_per_day or day_r.get(dkey, 0.0) <= daily_stop_r):
            continue
        keep.append(i); busy = en[i] + cooldown
        day_n[dkey] = day_n.get(dkey, 0) + 1; day_r[dkey] = day_r.get(dkey, 0.0) + r[i]
    k = np.array(keep, dtype=int)
    if len(k) == 0:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({"entry_time": m1.index[fi[k]], "exit_time": m1.index[en[k]], "dir": s.dir.to_numpy()[k], "r": r[k],
                         "reason": wy[k], "model": s.model.to_numpy()[k], "rr_plan": s.rr.to_numpy()[k],
                         "h1_aligned": s.h1_aligned.to_numpy()[k], "poi": s.poi.to_numpy()[k], "risk": s.risk.to_numpy()[k],
                         "fill_i": fi[k], "exit_i": en[k], "entry_px": fpx[k], "exit_px": xpx[k], "stop": s.stop.to_numpy()[k]})
