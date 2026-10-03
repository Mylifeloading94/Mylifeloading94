"""
Limit-order execution of SMC setups on real M1 bid/ask.

Pessimistic by construction:
  * a buy limit fills only when the ASK trades down to it (a sell limit: the BID trades up to it);
    if the bar GAPS through the limit the fill is at the (better) open, never worse than the limit
  * if the fill bar also reaches the stop, the trade is stopped out -- the fill bar's target is not credited
  * stops fill at the stop, or at the open if the bar gaps through it
  * target is a resting order that fills when bid (long) / ask (short) touches it
  * time exit at the bar close after `hold_min`; flat before any market closure (gap > 30 min)
  * an order that has not filled by its expiry is cancelled -- no trade
"""
import numpy as np
import pandas as pd
from numba import njit

import xau_engine as E


@njit(cache=True)
def _sim_limit(act, direction, limit, stop, risk, rr, expire_bars_min, hold_min, tmin,
               bo, bh, bl, bc, ao, ah, al, ac, o_status, o_r, o_fill, o_end, o_why):
    n = len(tmin)
    for k in range(len(act)):
        j0 = act[k]; d = direction[k]; lim = limit[k]; stp = stop[k]; rk = risk[k]
        expire = tmin[j0] + expire_bars_min
        o_status[k] = 0; o_end[k] = j0; o_fill[k] = -1; o_why[k] = 0
        jf = -1; fill = 0.0
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
        o_status[k] = 1; o_fill[k] = jf
        target = lim + d * rr * rk
        ex = np.nan; why = 0; jx = jf
        # fill bar: only the stop is honoured (pessimistic)
        if d == 1 and bl[jf] <= stp:
            ex, why = stp, 1
        elif d == -1 and ah[jf] >= stp:
            ex, why = stp, 1
        if why == 0:
            deadline = tmin[jf] + hold_min
            for j in range(jf + 1, n):
                jx = j
                if d == 1:
                    if bo[j] <= stp: ex, why = bo[j], 1; break
                    if bl[j] <= stp: ex, why = stp, 1; break
                    if bh[j] >= target: ex, why = target, 2; break
                else:
                    if ao[j] >= stp: ex, why = ao[j], 1; break
                    if ah[j] >= stp: ex, why = stp, 1; break
                    if al[j] <= target: ex, why = target, 2; break
                if tmin[j] + 1 >= deadline:
                    ex = bc[j] if d == 1 else ac[j]; why = 3; break
                if j + 1 < n and tmin[j + 1] - tmin[j] > 30:
                    ex = bc[j] if d == 1 else ac[j]; why = 4; break
        else:
            jx = jf
        if np.isnan(ex):
            ex = bc[jx] if d == 1 else ac[jx]; why = 4
        o_r[k] = (d * (ex - fill)) / rk
        o_end[k] = jx; o_why[k] = why


def run_orders(m1, b, tf_min, sig, rr, expiry_bars=8, hold_min=240, cooldown=1, market=False):
    """Turn signals (DataFrame from smc.generate) into a trade table, one position/order at a time."""
    if len(sig) == 0:
        return pd.DataFrame(columns=["entry_time", "exit_time", "dir", "r", "reason", "zone"])
    tmin = E._min(m1.index)
    close_min = E._min(b.index)[sig.t.to_numpy()] + tf_min
    act = np.searchsorted(tmin, close_min, side="left")
    ok = act < len(tmin)
    ok[ok] = (tmin[act[ok]] - close_min[ok]) <= 15
    s = sig[ok].reset_index(drop=True); act = act[ok].astype(np.int64)
    if market:
        # diagnostic: enter AT MARKET on the next candle's open (ask for longs, bid for shorts) instead of
        # resting a limit; same structural stop, planned risk recomputed from the real entry
        ask_o = m1.ao.to_numpy("float64")[act]; bid_o = m1.bo.to_numpy("float64")[act]
        s["limit"] = np.where(s.dir.to_numpy() == 1, ask_o, bid_o)
        s["risk"] = s.dir.to_numpy() * (s.limit.to_numpy() - s.stop.to_numpy())
        keepm = s.risk > 0
        s, act = s[keepm].reset_index(drop=True), act[keepm.to_numpy()]
    arr = [np.ascontiguousarray(m1[c].to_numpy("float64")) for c in ("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac")]
    n = len(s)
    st = np.empty(n, np.int64); r = np.empty(n); fi = np.empty(n, np.int64); en = np.empty(n, np.int64); wy = np.empty(n, np.int64)
    _sim_limit(act, s.dir.to_numpy().astype(np.int64), s.limit.to_numpy("float64"), s.stop.to_numpy("float64"),
               s.risk.to_numpy("float64"), float(rr), int(expiry_bars * tf_min), int(hold_min), tmin, *arr, st, r, fi, en, wy)
    keep, busy = [], -1
    for i in range(n):
        if act[i] <= busy:
            continue
        busy = en[i] + cooldown
        if st[i] == 1:
            keep.append(i)
    k = np.array(keep, dtype=int)
    if len(k) == 0:
        return pd.DataFrame(columns=["entry_time", "exit_time", "dir", "r", "reason", "zone"])
    return pd.DataFrame({"entry_time": m1.index[fi[k]], "exit_time": m1.index[en[k]], "dir": s.dir.to_numpy()[k],
                         "r": r[k], "reason": wy[k], "zone": s.zone.to_numpy()[k], "risk": s.risk.to_numpy()[k]})
