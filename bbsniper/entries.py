"""Module 8 - entry engine: the three BB SNIPER setups as bar-by-bar state machines.

Bars are processed strictly in order; everything a bar uses is closed at that bar's close.
Shorts are produced by running the long logic on a mirrored "view" of the market
(prices negated, %B -> 1-%B, RSI -> 100-RSI, bias/regime/trend sign-flipped), so both sides
follow identical rules.

Every candidate is emitted with its score components and filter flags; thresholds that are
optimised later (min score, min RR, sessions) are applied by the backtester, not here."""
import datetime as dt
import numpy as np
from . import indicators as I, regime as RG, bias as B, liquidity as LQ, structure as ST, divergence as DV, bands as BD
from .config import TF_MAP, TF_SEC, SPREAD_PIPS, pip
from .data import load, HTF


def session_of(T):
    h = dt.datetime.fromtimestamp(T, dt.UTC).hour
    if 12 <= h < 16: return "Overlap"
    if 7 <= h < 12: return "London"
    if 16 <= h < 21: return "NY"
    return "Asian"


def session_enabled(label, sessions):
    if label == "Overlap": return "London" in sessions or "NY" in sessions or "Overlap" in sessions
    return label in sessions


class Context:
    """Exec / setup / bias series + indicators for one symbol and execution timeframe."""
    def __init__(self, sym, tf, cfg):
        stf, btf = TF_MAP[tf]
        self.sym, self.tf, self.cfg = sym, tf, cfg
        self.x = load(sym, tf); self.s = load(sym, stf); self.b = load(sym, btf)
        if self.x is None or self.s is None or self.b is None: raise FileNotFoundError(f"missing data {sym} {tf}")
        self.xi = I.compute(self.x, cfg); self.si = I.compute(self.s, cfg); self.bi = I.compute(self.b, cfg)
        self.reg = RG.classify(self.s, self.si, cfg); self.strend = B.trend(self.s, self.si)
        self.bias, self.brise, self.bfall = B.bias(self.b, self.bi)
        self.sh, self.bh = HTF(self.s, stf), HTF(self.b, btf)
        self.sec = TF_SEC[tf]; self.pip = pip(sym); self.spread = SPREAD_PIPS[sym] * self.pip * cfg.get("spread_mult", 1.0)
        n = len(self.x["t"]); T = self.x["t"] + self.sec
        self.ks = np.array([self.sh.idx(v) for v in T]); self.kb = np.array([self.bh.idx(v) for v in T])


def _view(ctx, side):
    x, xi = ctx.x, ctx.xi
    if side == 1:
        v = dict(o=x["o"], h=x["h"], l=x["l"], c=x["c"], up=xi["up"], lo=xi["lo"], mid=xi["mid"], ef=xi["ema_f"],
                 pctb=xi["pctb"], rsi=xi["rsi"], reg=ctx.reg, strend=ctx.strend, bias=ctx.bias, brise=ctx.brise)
    else:
        v = dict(o=-x["o"], h=-x["l"], l=-x["h"], c=-x["c"], up=-xi["lo"], lo=-xi["up"], mid=-xi["mid"], ef=-xi["ema_f"],
                 pctb=1 - xi["pctb"], rsi=100 - xi["rsi"], reg=np.where(np.abs(ctx.reg) == 2, -ctx.reg, ctx.reg),
                 strend=-ctx.strend, bias=-ctx.bias, brise=ctx.bfall)
    v.update(atr=xi["atr"], adx=xi["adx"], bwp=xi["bw_pct"], sadx=ctx.si["adx"])
    return v


def scan(ctx, side, start=250):
    cfg = ctx.cfg; v = _view(ctx, side)
    o, h, l, c, up, lo, mid, ef = v["o"], v["h"], v["l"], v["c"], v["up"], v["lo"], v["mid"], v["ef"]
    rsi, pctb, atr, adx, bwp = v["rsi"], v["pctb"], v["atr"], v["adx"], v["bwp"]
    n = len(c); t = ctx.x["t"]; spr = ctx.spread
    Lq, Lm = cfg["piv_liq"], cfg["piv_micro"]
    pool_lo = LQ.Pool(LQ.pivot_lows(l, Lq, Lq), cfg["liq_lookback"])
    pool_mlo = LQ.Pool(LQ.pivot_lows(l, Lm, Lm), cfg["liq_lookback"])
    pool_hi = LQ.Pool(LQ.pivot_lows(-h, 2 * Lq, 2 * Lq), 4 * cfg["liq_lookback"])  # opposing major swing highs (negated)
    ph_px, ph_ix = ST.last_pivot_high(n, LQ.pivot_highs(h, Lm, Lm))
    mr = tc = sb = None; out = []
    for i in range(1, n):
        swept = pool_lo.update(i, l[i]); swept_m = pool_mlo.update(i, l[i]); pool_hi.update(i, -h[i])
        if i < start: continue
        ks, kb = ctx.ks[i], ctx.kb[i]
        ok = ks >= 3 and kb >= 0 and not np.isnan(atr[i]) and not np.isnan(bwp[i]) and not np.isnan(v["sadx"][ks])
        reg = v["reg"][ks] if ok else None
        cands = []
        # ---------- A. mean reversion (ranging / transitional regimes) ----------
        if "MR" in cfg["setups"]:
            if ok and swept and reg in (0, 1) and BD.at_lower_extreme(i, l, lo, up, cfg["bb_approach"]):
                pj, lvl = min(swept, key=lambda p: p[1])
                mr = dict(i0=i, lvl=lvl, pj=pj, low=l[i], low_i=i, rec=c[i] > lvl, exp=i + cfg["arm_window"],
                          bbx=BD.pierced_lower(i, l, lo), rsi_min=min(rsi[i - 1], rsi[i]), pb_min=min(pctb[i - 1], pctb[i]))
            elif mr:
                if l[i] < mr["low"]: mr["low"], mr["low_i"] = l[i], i
                mr["bbx"] |= BD.pierced_lower(i, l, lo); mr["rsi_min"] = min(mr["rsi_min"], rsi[i]); mr["pb_min"] = min(mr["pb_min"], pctb[i])
                if c[i] > mr["lvl"]: mr["rec"] = True
                if i > mr["exp"]: mr = None
            if mr and ok and mr["rec"] and c[i] > mr["lvl"]:
                ref = ph_px[i] if ph_ix[i] > mr["pj"] else (h[mr["i0"]] if i > mr["i0"] else np.nan)
                if ST.bullish_mss(c, i, ref) and reg in (0, 1):
                    pj, li = mr["pj"], mr["low_i"]
                    comp = dict(sweep=True, bbx=mr["bbx"], mss=True,
                                rsi=mr["rsi_min"] < cfg["rsi_os"] or DV.bullish(mr["low"], l[pj], rsi[li], rsi[pj]),
                                pctb=(mr["pb_min"] < 0 and pctb[i] > 0) or DV.bullish(mr["low"], l[pj], pctb[li], pctb[pj]),
                                adx=v["sadx"][ks] < cfg["adx_weak"],
                                rsi_div=DV.bullish(mr["low"], l[pj], rsi[li], rsi[pj]),
                                pctb_div=DV.bullish(mr["low"], l[pj], pctb[li], pctb[pj]))
                    cands.append(("MR", mr["low"], comp)); mr = None
        # ---------- B. trend continuation (trending regime, with-trend pullback) ----------
        if "TC" in cfg["setups"]:
            ctx_ok = ok and reg == 2 and v["bias"][kb] == 1
            if tc is None and ctx_ok and BD.touched_mean(i, l, ef, mid) and c[i] > lo[i] and np.nanmax(pctb[i - 20:i]) > 0.8:
                tc = dict(i0=i, low=l[i], exp=i + cfg["arm_window"], rsi_min=rsi[i], pb_min=pctb[i],
                          swept=bool(swept_m) and c[i] > min(p for _, p in swept_m))
            elif tc:
                tc["low"] = min(tc["low"], l[i]); tc["rsi_min"] = min(tc["rsi_min"], rsi[i]); tc["pb_min"] = min(tc["pb_min"], pctb[i])
                if swept_m and c[i] > min(p for _, p in swept_m): tc["swept"] = True
                if c[i] < lo[i] or i > tc["exp"]: tc = None
            if tc and ctx_ok and i > tc["i0"] and ph_ix[i] >= tc["i0"] - 8 and ST.bullish_mss(c, i, ph_px[i]):
                comp = dict(sweep=tc["swept"], bbx=True, mss=True,
                            rsi=tc["rsi_min"] >= cfg["rsi_trend_floor"] and rsi[i] > 50,
                            pctb=pctb[i] > pctb[i - 1] and tc["pb_min"] <= 0.6,
                            adx=v["sadx"][ks] > cfg["adx_trend"] and v["sadx"][ks] > v["sadx"][ks - 3],
                            rsi_div=False, pctb_div=False)
                cands.append(("TC", tc["low"], comp)); tc = None
        # ---------- C. squeeze breakout -> retest -> confirmation ----------
        if "SB" in cfg["setups"]:
            if sb is None:
                lvl = BD.band_breakout_up(i, c, up, h, cfg["sb_range"]) if ok else None
                if lvl is not None and reg != -2 and BD.squeezed_recently(i, bwp, cfg["squeeze_pct"]) and adx[i] > adx[i - 3]:
                    sb = dict(b=i, lvl=lvl, st=0, exp=i + cfg["sb_retest_window"], rsi_b=rsi[i], pb_b=pctb[i])
            else:
                if c[i] < sb["lvl"] - 0.2 * atr[i] or (sb["st"] == 0 and i > sb["exp"]): sb = None
                elif sb["st"] == 0:
                    if i > sb["b"] and l[i] <= sb["lvl"] + 0.1 * atr[i] and c[i] >= sb["lvl"]:
                        sb.update(st=1, r_low=l[i], r_high=h[i], cexp=i + cfg["sb_confirm_window"], pb_r=pctb[i])
                else:
                    sb["r_low"] = min(sb["r_low"], l[i])
                    if ok and c[i] > sb["r_high"] and c[i] > o[i]:
                        comp = dict(sweep=True, bbx=True, mss=True, rsi=sb["rsi_b"] > 55 and rsi[i] >= 50,
                                    pctb=sb["pb_b"] > 1 and sb["pb_r"] >= 0.5, adx=adx[i] > adx[i - 3] and adx[i] > cfg["adx_weak"],
                                    rsi_div=False, pctb_div=False)
                        cands.append(("SB", sb["r_low"], comp)); sb = None
                    elif i > sb["cexp"]: sb = None
        if not cands: continue
        # ---------- score + filters ----------
        bias = v["bias"][kb]
        if bias == -1: continue                                  # never trade against the 15M bias
        best = None
        for setup, swing, comp in cands:
            pts = 2 * (bias == 1) + (v["strend"][ks] == 1) + 2 * comp["sweep"] + comp["bbx"] + comp["mss"] + comp["rsi"] + comp["pctb"] + comp["adx"]
            if bias == 0 and cfg["neutral_needs_full"] and pts < 8: continue
            if best is None or pts > best[0]: best = (pts, setup, swing, comp)
        if best is None: continue
        pts, setup, swing, comp = best
        entry_v = c[i] + (spr if side == 1 else 0.0)              # longs pay the ask; shorts sell the bid
        stop_v = swing - cfg["sl_buf_atr"] * atr[i]
        risk = entry_v - stop_v
        opp = pool_hi.nearest_below(-entry_v)
        room = (-opp - entry_v) / risk if (opp is not None and risk > 0) else 99.0
        T = int(t[i] + ctx.sec)
        out.append(dict(sym=ctx.sym, tf=ctx.tf, side=side, setup=setup, i=i, t=T, session=session_of(T),
                        entry=entry_v * side, stop=stop_v * side, risk=risk, atr=atr[i], score=int(pts),
                        bias=int(bias * side), setup_trend=int(v["strend"][ks] == 1), regime=RG.NAMES[int(ctx.reg[ks])],
                        room_r=round(float(room), 2), spread=spr,
                        bias_slope=bool(v["brise"][kb]), **{k: bool(x) for k, x in comp.items()}))
        mr = tc = sb = None                                       # one signal consumes all armed setups
    return out


def signals(sym, tf, cfg):
    ctx = Context(sym, tf, cfg)
    return ctx, sorted(scan(ctx, 1) + scan(ctx, -1), key=lambda s: s["i"])
