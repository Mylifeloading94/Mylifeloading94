"""Alternative strategy families, same honest execution as engine.py.

B  trend pullback + TDI cross : H4 EMA50 trend, M30 pullback into EMA20, TDI price line crosses its
   signal line, market entry at next bar open, stop beyond recent swing.
C  London Asian-range breakout-retest : H4 EMA50 trend, M30 close beyond the 00:00-06:00 UTC range
   during 07:00-10:30, limit at the broken range edge, stop at range midpoint.
"""
import datetime as dt, bisect
import engine as E


def ema(x, n):
    out, k, e = [], 2 / (n + 1), None
    for v in x:
        e = v if e is None else e + k * (v - e); out.append(e)
    return out


class HTFEma:
    def __init__(self, bars, sec, n=50, slope=3):
        c = [b[4] for b in bars]; self.e = ema(c, n); self.c = c; self.slope = slope
        self.close_t = [b[0] + sec for b in bars]

    def bias(self, T):
        k = bisect.bisect_right(self.close_t, T) - 1
        if k < self.slope + 50: return 0
        if self.c[k] > self.e[k] and self.e[k] > self.e[k - self.slope]: return 1
        if self.c[k] < self.e[k] and self.e[k] < self.e[k - self.slope]: return -1
        return 0


def _res(sym, side, entry, stop, tp2, r_tp2, res, T, sess, strat):
    return dict(sym=sym, side="BUY" if side == 1 else "SELL", signal_t=T, session=sess, entry=entry, stop=stop,
                tp2=tp2, rr=r_tp2, risk_pips=round(abs(entry - stop) / E.pip(sym), 1), strat=strat,
                score=100, tdi_os=False, div="n/a", **res)


def pullback(sym, cfg, start_ts, end_ts):
    bars = E.load(sym, "30m"); sec = 1800
    htf = HTFEma(E.load(sym, "4h"), 14400)
    c = [b[4] for b in bars]; e20, e50 = ema(c, 20), ema(c, 50); A = E.atr(bars)
    _, P, S, _ = E.tdi(bars); P_ = E.pip(sym); spread = E.SPREAD[sym] * P_
    out, busy_until = [], 0
    for j in range(60, len(bars) - 1):
        t, o, h, l, cl = bars[j]; T = t + sec
        if T < start_ts or T > end_ts or T < busy_until: continue
        side = htf.bias(T)
        if side == 0: continue
        sess = E.session(t)
        if cfg.get("kz_only") and sess not in ("London KZ", "NY KZ"): continue
        touched = any((bars[k][3] <= e20[k]) if side == 1 else (bars[k][2] >= e20[k]) for k in range(j - 3, j + 1))
        above = (cl > e50[j]) if side == 1 else (cl < e50[j])
        cross = (P[j] > S[j] and P[j - 1] <= S[j - 1] and P[j] < 60) if side == 1 else \
                (P[j] < S[j] and P[j - 1] >= S[j - 1] and P[j] > 40)
        if not (touched and above and cross and ((cl > o) if side == 1 else (cl < o))): continue
        a = A[j]
        entry = bars[j + 1][1] + (0 if side == 1 else 0)
        ext = min(b[3] for b in bars[j - 5:j + 1]) if side == 1 else max(b[2] for b in bars[j - 5:j + 1])
        stop = ext - side * cfg["stop_atr"] * a
        risk = abs(entry - stop)
        if risk < 0.5 * a or risk > 3 * a or risk < 3 * spread or (entry - stop) * side <= 0: continue
        tp2 = entry + side * cfg["tp"] * risk; tp1 = entry + side * 1.0 * risk
        res = E.manage(bars, j + 1, side, entry, stop, tp1, tp2, spread, cfg["partial"], fill_bar_open=True)
        if res is None: continue
        out.append(_res(sym, side, entry, stop, tp2, cfg["tp"], res, T, sess, "B pullback")); busy_until = res["exit_t"]
    return out


def asia_breakout(sym, cfg, start_ts, end_ts):
    bars = E.load(sym, "30m"); sec = 1800
    htf = HTFEma(E.load(sym, "4h"), 14400)
    P_ = E.pip(sym); spread = E.SPREAD[sym] * P_
    byday = {}
    for i, b in enumerate(bars):
        byday.setdefault(dt.datetime.fromtimestamp(b[0], dt.UTC).date(), []).append(i)
    out = []
    for d, idx in sorted(byday.items()):
        asia = [bars[i] for i in idx if dt.datetime.fromtimestamp(bars[i][0], dt.UTC).hour < 6]
        if len(asia) < 10: continue
        hi, lo = max(b[2] for b in asia), min(b[3] for b in asia)
        mid = (hi + lo) / 2
        for i in idx:
            t = bars[i][0]; hm = dt.datetime.fromtimestamp(t, dt.UTC); m = hm.hour * 60 + hm.minute
            if not (7 * 60 <= m < 10 * 60 + 30): continue
            T = t + sec
            if T < start_ts or T > end_ts: break
            cl = bars[i][4]; side = 1 if cl > hi else -1 if cl < lo else 0
            if side == 0: continue
            if htf.bias(T) != side: break       # first break against bias kills the day
            entry = hi if side == 1 else lo
            stop = mid - side * cfg["stop_pad"] * (hi - lo)
            risk = abs(entry - stop)
            if risk < 3 * spread: break
            tp2 = entry + side * cfg["tp"] * risk; tp1 = entry + side * risk
            res = E.simulate(bars, i, side, entry, stop, tp1, tp2, spread, P_, cfg["window"], cfg["partial"])
            if res is not None:
                out.append(_res(sym, side, entry, stop, tp2, cfg["tp"], res, T, "London KZ", "C asia-breakout"))
            break                                  # one attempt per day
    return out
