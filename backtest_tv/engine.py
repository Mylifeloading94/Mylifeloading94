"""SMC + TDI + divergence sniper backtest on TradingView OHLCV (OANDA feed).

Rules are fixed up-front (see RULES in report). Everything is causal:
pivots are only known L bars after they print, HTF bias only uses HTF bars
that have fully closed, indicators at bar j use data <= j, entries are limit
orders filled only by trade-through on later bars.
"""
import json, math, os, datetime as dt
from collections import defaultdict

DATA = os.path.join(os.path.dirname(__file__), "data")

# Estimated typical OANDA spreads (pips / index points). Not from the data feed.
SPREAD = {"EURUSD": 1.4, "GBPUSD": 2.0, "USDJPY": 1.6, "USDCHF": 1.8, "USDCAD": 2.2, "AUDUSD": 1.6,
          "NZDUSD": 2.0, "EURJPY": 2.0, "GBPJPY": 3.0, "CHFJPY": 3.0, "AUDJPY": 2.0, "NZDJPY": 2.5,
          "CADJPY": 2.5, "EURGBP": 1.6, "EURCHF": 2.0, "EURCAD": 2.8, "EURAUD": 2.8, "EURNZD": 4.0,
          "GBPCHF": 3.5, "GBPCAD": 4.0, "GBPAUD": 3.5, "GBPNZD": 5.0, "AUDCHF": 2.5, "AUDCAD": 2.5,
          "AUDNZD": 3.0, "NZDCHF": 3.0, "NZDCAD": 3.0, "CADCHF": 2.5, "XAUUSD": 3.5, "SPX500USD": 0.6}
SYMBOLS = sorted(SPREAD)
TF_SEC = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400}


def pip(sym):
    return 0.01 if "JPY" in sym else 0.1 if sym == "XAUUSD" else 1.0 if sym == "SPX500USD" else 0.0001


def load(sym, tf):
    if tf in ("4h", "1D"):
        return resample(load(sym, "1h"), TF_SEC[tf])
    bars = json.load(open(os.path.join(DATA, f"{sym}_{tf}.json")))
    return [(b["t"], b["o"], b["h"], b["l"], b["c"]) for b in bars]


def resample(bars, sec):
    out, cur = [], None
    for t, o, h, l, c in bars:
        k = t - t % sec
        if cur and cur[0] == k:
            cur = [k, cur[1], max(cur[2], h), min(cur[3], l), c]
        else:
            if cur: out.append(tuple(cur))
            cur = [k, o, h, l, c]
    if cur: out.append(tuple(cur))
    return out


# ---------------- indicators (causal) ----------------
def atr(bars, n=14):
    out, prev, a = [], None, None
    for t, o, h, l, c in bars:
        tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        a = tr if a is None else (a * (n - 1) + tr) / n
        out.append(a); prev = c
    return out


def rsi(bars, n=13):
    out, ag, al, prev = [], None, None, None
    for i, (t, o, h, l, c) in enumerate(bars):
        if prev is None:
            out.append(50.0); prev = c; continue
        g, d = max(c - prev, 0), max(prev - c, 0)
        if ag is None: ag, al = g, d
        else: ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + d) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al)); prev = c
    return out


def sma(x, n):
    out, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n: s -= x[i - n]
        out.append(s / min(i + 1, n))
    return out


def tdi(bars):
    r = rsi(bars, 13)
    price, signal, mid = sma(r, 2), sma(r, 7), sma(r, 34)
    return r, price, signal, mid


# ---------------- structure ----------------
def pivots(bars, L):
    """Return list per bar index j of pivots *confirmed* at j: (kind, idx, price)."""
    conf = defaultdict(list)
    n = len(bars)
    for i in range(L, n - L):
        h, l = bars[i][2], bars[i][3]
        if all(h >= bars[k][2] for k in range(i - L, i + L + 1)) and any(h > bars[k][2] for k in range(i - L, i + L + 1) if k != i):
            conf[i + L].append(("H", i, h))
        if all(l <= bars[k][3] for k in range(i - L, i + L + 1)) and any(l < bars[k][3] for k in range(i - L, i + L + 1) if k != i):
            conf[i + L].append(("L", i, l))
    return conf


def structure(bars, L=3):
    """Per-bar trend after close (+1/-1/0) and the dealing range (last confirmed swing H/L)."""
    conf = pivots(bars, L)
    trend, rng = [], []
    lh = ll = None; lh_broken = ll_broken = True; tr = 0
    for j, (t, o, h, l, c) in enumerate(bars):
        for kind, i, p in conf.get(j, []):
            if kind == "H": lh, lh_broken = p, False
            else: ll, ll_broken = p, False
        if lh is not None and not lh_broken and c > lh: tr, lh_broken = 1, True
        if ll is not None and not ll_broken and c < ll: tr, ll_broken = -1, True
        trend.append(tr); rng.append((lh, ll))
    return trend, rng


class HTF:
    """Causal HTF lookup: state as of the last HTF bar closed at or before time T."""
    def __init__(self, bars, sec, L=3):
        self.bars, self.sec = bars, sec
        self.trend, self.rng = structure(bars, L)
        self.close_times = [b[0] + sec for b in bars]

    def at(self, T):
        lo, hi = 0, len(self.close_times) - 1; k = -1
        while lo <= hi:
            m = (lo + hi) // 2
            if self.close_times[m] <= T: k, lo = m, m + 1
            else: hi = m - 1
        if k < 0: return 0, None
        lh, ll = self.rng[k]
        return self.trend[k], (lh, ll)


def session(ts):
    h = dt.datetime.fromtimestamp(ts, dt.UTC); m = h.hour * 60 + h.minute
    if 7 * 60 <= m < 10 * 60 + 30: return "London KZ"
    if 12 * 60 <= m < 15 * 60 + 30: return "NY KZ"
    if 0 <= m < 6 * 60: return "Asia"
    return "Off-KZ"


# ---------------- setup detection + simulation ----------------
CFG = dict(L_entry=3, L_int=2, sweep_lookback=60, mss_window=12, disp_atr=1.0, fvg_atr=0.15,
           fill_window=16, stop_atr=0.3, dol_min=1.6, room_min=1.2, tp1=1.0, tp2=2.5, pd_max=0.5)


def find_trades(sym, entry_tf, bias_tf, cfg=CFG, start_ts=0, end_ts=1e18):
    bars = load(sym, entry_tf); sec = TF_SEC[entry_tf]
    hb = load(sym, bias_tf); htf = HTF(hb, TF_SEC[bias_tf])
    A = atr(bars); R, P, S, M = tdi(bars); etr, _ = structure(bars, cfg["L_entry"])
    P_ = pip(sym); spread = SPREAD[sym] * P_
    conf_e = pivots(bars, cfg["L_entry"]); conf_i = pivots(bars, cfg["L_int"])
    n = len(bars)
    piv_lo, piv_hi = [], []        # confirmed entry-TF pivots (idx, price, swept?)
    int_hi, int_lo = [], []        # internal pivots for MSS
    trades = []
    sweeps = {1: None, -1: None}   # active sweep per direction
    day_hl = {}                    # UTC date -> (high, low)
    for j in range(n):
        t, o, h, l, c = bars[j]
        d = dt.datetime.fromtimestamp(t, dt.UTC).date()
        dh, dl = day_hl.get(d, (h, l)); day_hl[d] = (max(dh, h), min(dl, l))
        for kind, i, p in conf_e.get(j, []):
            (piv_hi if kind == "H" else piv_lo).append([i, p, False])
        for kind, i, p in conf_i.get(j, []):
            (int_hi if kind == "H" else int_lo).append((i, p))
        if j < 50: continue
        a = A[j - 1]
        prevd = d - dt.timedelta(days=1)
        while prevd not in day_hl and (d - prevd).days < 5: prevd -= dt.timedelta(days=1)
        pdh, pdl = day_hl.get(prevd, (None, None))
        # --- liquidity sweeps (wick through named liquidity, close back inside) ---
        for side in (1, -1):
            pools = piv_lo if side == 1 else piv_hi
            cand = []
            for pv in pools:
                if pv[2] or j - pv[0] > cfg["sweep_lookback"]: continue
                cand.append(("swing", pv))
            if pdl is not None:
                cand.append(("PDL" if side == 1 else "PDH", [None, pdl if side == 1 else pdh, False]))
            for name, pv in cand:
                lvl = pv[1]
                if name == "swing" and ((side == 1 and c < lvl) or (side == -1 and c > lvl)):
                    pv[2] = True; continue  # closed through = broken, no longer resting liquidity
                if side == 1 and l < lvl and c > lvl and lvl - l <= 1.5 * a:
                    pv[2] = True
                    sw = sweeps[1]
                    if sw is None or l < sw["ext"]:
                        sweeps[1] = dict(idx=j, ext=l, lvl=lvl, pool=name, piv=pv[0])
                elif side == -1 and h > lvl and c < lvl and h - lvl <= 1.5 * a:
                    pv[2] = True
                    sw = sweeps[-1]
                    if sw is None or h > sw["ext"]:
                        sweeps[-1] = dict(idx=j, ext=h, lvl=lvl, pool=name, piv=pv[0])
        # --- MSS with displacement after a sweep ---
        for side in (1, -1):
            sw = sweeps[side]
            if sw is None: continue
            if j - sw["idx"] > cfg["mss_window"]: sweeps[side] = None; continue
            if j == sw["idx"]: continue
            if side == 1 and l < sw["ext"]: sw["ext"], sw["idx"] = l, j; continue
            if side == -1 and h > sw["ext"]: sw["ext"], sw["idx"] = h, j; continue
            ref = [p for (i, p) in (int_hi if side == 1 else int_lo) if i < j and i >= sw["idx"] - 10]
            if not ref: continue
            lvl = ref[-1]
            body = abs(c - o)
            broke = (c > lvl and c > o) if side == 1 else (c < lvl and c < o)
            if not (broke and body >= cfg["disp_atr"] * a): continue
            # FVG inside the displacement leg (sweep -> MSS)
            fvg = None
            for k in range(j, sw["idx"] + 1, -1):
                if side == 1 and bars[k][3] > bars[k - 2][2] and bars[k][3] - bars[k - 2][2] >= cfg["fvg_atr"] * a:
                    fvg = (bars[k - 2][2], bars[k][3]); break
                if side == -1 and bars[k][2] < bars[k - 2][3] and bars[k - 2][3] - bars[k][2] >= cfg["fvg_atr"] * a:
                    fvg = (bars[k][2], bars[k - 2][3]); break
            sweeps[side] = None
            if fvg is None: continue
            T_close = t + sec
            if T_close < start_ts or T_close > end_ts: continue
            # --- HTF bias + premium/discount (causal) ---
            btr, brng = htf.at(T_close)
            if btr != side or brng is None or None in brng: continue
            bh, bl = brng
            if bh <= bl: continue
            entry = (fvg[0] + fvg[1]) / 2
            pd = (entry - bl) / (bh - bl)
            in_pd = (pd <= cfg["pd_max"]) if side == 1 else (pd >= 1 - cfg["pd_max"])
            if (side == 1 and pd >= 1.0) or (side == -1 and pd <= 0.0): continue  # beyond HTF range: no DOL left
            buf = max(cfg["stop_atr"] * a, 1.5 * spread)
            stop = sw["ext"] - buf if side == 1 else sw["ext"] + buf
            risk = abs(entry - stop)
            if risk < 3 * spread: continue
            # draw on liquidity = opposing extreme of the HTF dealing range (unmitigated HTF swing)
            dol = bh if side == 1 else bl
            room = abs(dol - entry) / risk
            if room < cfg["room_min"]: continue
            tp2_r = min(cfg["tp2"], room - 0.1 * a / risk)
            tp1 = entry + side * cfg["tp1"] * risk
            tp2 = entry + side * tp2_r * risk
            # --- confluence tags at decision time (bar j) ---
            tdi_ok = (P[j] > S[j] and P[j] > P[j - 1]) if side == 1 else (P[j] < S[j] and P[j] < P[j - 1])
            tdi_strong = tdi_ok and ((P[j] > 50 and min(P[j - 3:j]) <= 50) or P[j] > M[j]) if side == 1 else \
                tdi_ok and ((P[j] < 50 and max(P[j - 3:j]) >= 50) or P[j] < M[j])
            tdi_os = (min(P[sw["idx"] - 1:sw["idx"] + 1]) < 32) if side == 1 else (max(P[sw["idx"] - 1:sw["idx"] + 1]) > 68)
            div = "none"
            if sw["piv"] is not None:
                pi = sw["piv"]
                if side == 1 and R[sw["idx"]] > R[pi]: div = "regular"
                if side == -1 and R[sw["idx"]] < R[pi]: div = "regular"
            if div == "none":
                pp = [pv for pv in (piv_lo if side == 1 else piv_hi) if pv[0] < sw["idx"]][-2:]
                if len(pp) == 2:
                    (i1, p1, _), (i2, p2, _) = pp
                    if side == 1 and p2 > p1 and R[i2] < R[i1]: div = "hidden"
                    if side == -1 and p2 < p1 and R[i2] > R[i1]: div = "hidden"
            sess = session(t)
            kz = sess in ("London KZ", "NY KZ")
            deep = (pd <= 0.4) if side == 1 else (pd >= 0.6)
            score = 40 + 10 * in_pd + 5 * deep + 10 * kz + 10 * tdi_ok + 5 * tdi_strong + \
                (10 if div == "regular" else 7 if div == "hidden" else 0) + 10 * (room >= cfg["dol_min"])
            # --- order lifecycle: limit at FVG CE, trade-through fill, honest exits ---
            res = simulate(bars, j, side, entry, stop, tp1, tp2, spread, P_, cfg["fill_window"])
            if res is None: continue
            trades.append(dict(sym=sym, entry_tf=entry_tf, bias_tf=bias_tf, side="BUY" if side == 1 else "SELL",
                               signal_t=T_close, session=sess, entry=entry, stop=stop, tp1=tp1, tp2=tp2,
                               rr=round(tp2_r, 2), risk_pips=round(risk / P_, 1), pool=sw["pool"],
                               mss="BOS" if etr[j - 1] == side else "CHoCH",
                               setup="trend continuation" if etr[j - 1] == side else "liquidity reversal",
                               tdi=("strong" if tdi_strong else "confirm" if tdi_ok else "against"), tdi_os=tdi_os,
                               div=div, in_pd=in_pd, kz=kz, pd=round(pd, 2), dol_room=round(room, 2), score=score, **res))
    return trades


def simulate(bars, j, side, entry, stop, tp1, tp2, spread, P_, window):
    n = len(bars); fill = None
    for k in range(j + 1, min(n, j + 1 + window)):
        t, o, h, l, c = bars[k]
        # rule A (same as live bot): pending order cancelled only if a candle CLOSES beyond the stop
        # before the fill; touching TP1 first does not cancel it. Unfilled after `window` bars -> expired.
        if (side == 1 and c < stop) or (side == -1 and c > stop):
            if not ((side == 1 and l <= entry - P_) or (side == -1 and h >= entry + P_)):
                return None
        if (side == 1 and l <= entry - P_) or (side == -1 and h >= entry + P_):
            fill = k; break
    if fill is None: return None
    risk = abs(entry - stop); cost = spread / risk
    half_done = False; mfe = mae = 0.0
    for k in range(fill, n):
        t, o, h, l, c = bars[k]
        fav = ((h - entry) if side == 1 else (entry - l)) / risk
        adv = ((entry - l) if side == 1 else (h - entry)) / risk
        mfe, mae = max(mfe, fav), max(mae, adv)
        cur_stop = entry if half_done else stop
        hit_stop = (l <= cur_stop) if side == 1 else (h >= cur_stop)
        hit_tp1 = (h >= tp1) if side == 1 else (l <= tp1)
        hit_tp2 = (h >= tp2) if side == 1 else (l <= tp2)
        if k == fill and ((side == 1 and l <= stop) or (side == -1 and h >= stop)):
            return out(bars, fill, k, -1.0 - cost, "SL (fill bar)", mfe, mae)
        if hit_stop:  # stop wins any tie with a target on the same bar
            r = (0.5 * abs(tp1 - entry) / risk + 0.0) - cost if half_done else -1.0 - cost
            return out(bars, fill, k, r, "BE after TP1" if half_done else "SL", mfe, mae)
        if not half_done and hit_tp1:
            half_done = True
            if hit_tp2:
                r = 0.5 * abs(tp1 - entry) / risk + 0.5 * abs(tp2 - entry) / risk - cost
                return out(bars, fill, k, r, "TP2", mfe, mae)
            continue
        if half_done and hit_tp2:
            r = 0.5 * abs(tp1 - entry) / risk + 0.5 * abs(tp2 - entry) / risk - cost
            return out(bars, fill, k, r, "TP2", mfe, mae)
    return None  # still open at end of data -> excluded


def out(bars, fill, k, r, why, mfe, mae):
    return dict(fill_t=bars[fill][0], exit_t=bars[k][0], r=round(r, 3), exit=why,
                mfe=round(mfe, 2), mae=round(min(mae, 1.0), 2))
