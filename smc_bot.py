"""
XAUUSD SMC ULTIMATE SNIPER BOT — implementation of the supplied rule set.

Timeframes (§CORE): H4 macro bias · H1 premium/discount · M15 liquidity map ·
M5 setup · M1 precision entry.
Method: Liquidity Sweep + MSS + FVG + Order Block.

Every gate is numbered against the source document. Values the document leaves
open ("optimize only through walk-forward testing") are marked CALIBRATED with
the value used and where it was chosen.

NO LOOK-AHEAD
    A signal computed from a bar's CLOSE is only actionable at/after that close.
    Higher timeframes are gated by `visible()`; entries and exits resolve on M1
    bars stamped at or after the signal bar's close. An earlier build in this
    repo lost that property and manufactured a fake edge — see
    archive/xau_scalper_research/README.md.

Conventions: 1 pip = $0.10; contract 100 oz, so $1.00 = $100 per standard lot.
"""
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PIP = 0.10
CONTRACT = 100.0
LONDON = ZoneInfo("Europe/London")
NEWYORK = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")


@dataclass
class Costs:
    spread_pips: float = 3.0          # $0.30
    max_spread_pips: float = 5.0      # §20
    slip_entry_pips: float = 0.5      # §20
    slip_stop_pips: float = 1.0
    commission_per_lot: float = 7.0


@dataclass
class Params:
    # §6 displacement
    disp_ratio_min: float = 1.5
    disp_pref: float = 1.8
    disp_median_n: int = 20
    # §16 stop
    sl_atr_mult: float = 0.20
    sl_min_pips: float = 15.0         # CALIBRATED (dev 2024) — floor vs spread
    sl_max_pips: float = 250.0        # CALIBRATED (dev 2024) — sizing floor
    # §17 targets / §18 management
    tp_r_1: float = 1.5               # close 30%
    tp_r_2: float = 2.0               # close another 30%
    runner_max_r: float = 3.0         # remainder -> external liquidity, capped
    be_at_r: float = 1.0
    part1_frac: float = 0.30
    part2_frac: float = 0.30
    # §11 score
    min_score: int = 90
    # §2 H1 dealing range
    h1_range_bars: int = 60
    require_pd: bool = True           # §2 premium/discount gate
    # §5 sweep
    sweep_lookback_m5: int = 12
    # §10 M1
    m1_window_bars: int = 60
    m1_fill_bars: int = 90
    # §13 regime / volatility
    atr_pct_lo: float = 20.0
    atr_pct_hi: float = 95.0
    atr_pct_window: int = 2000
    # §CORE / §19
    max_trades_per_day: int = 3
    max_consec_losses: int = 3
    daily_loss_stop: float = 0.01
    max_hold_bars_m1: int = 480
    # §14 sessions (local exchange time)
    london_window: tuple = (7, 10)
    ny_window: tuple = (8, 11)
    # §12/§13 engines
    engines_enabled: tuple = ("A", "B", "C")


def default_params():
    return Params()


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def resample(m1, rule):
    o = m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    return o.dropna()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def swings(high, low, left=2, right=2):
    """Fractal swings; a swing at i is only CONFIRMED at i+right."""
    n = len(high)
    sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    for i in range(left, n - right):
        wh = high[i - left:i + right + 1]; wl = low[i - left:i + right + 1]
        if high[i] == wh.max() and wh.argmax() == left:
            sh[i] = True
        if low[i] == wl.min() and wl.argmin() == left:
            sl[i] = True
    return sh, sl


def visible(base_index, htf_index, htf_minutes, base_minutes):
    bc = base_index + pd.Timedelta(minutes=base_minutes)
    hc = htf_index + pd.Timedelta(minutes=htf_minutes)
    return np.searchsorted(hc.values, bc.values, "right") - 1


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class Context:
    def __init__(self, m1, p: Params):
        self.p = p
        self.m1 = m1
        self.m5 = resample(m1, "5min")
        self.m15 = resample(m1, "15min")
        self.h1 = resample(m1, "1h")
        self.h4 = resample(m1, "4h")

        for nm, f in (("m5", self.m5), ("m15", self.m15), ("h1", self.h1), ("h4", self.h4)):
            setattr(self, f"{nm}_o", f["open"].values.astype(float))
            setattr(self, f"{nm}_h", f["high"].values.astype(float))
            setattr(self, f"{nm}_l", f["low"].values.astype(float))
            setattr(self, f"{nm}_c", f["close"].values.astype(float))
            sh, sl = swings(f["high"].values, f["low"].values, 2, 2)
            setattr(self, f"{nm}_sh", sh); setattr(self, f"{nm}_sl", sl)
            setattr(self, f"{nm}_atr", atr(f, 14).values)

        self.m1_o = m1["open"].values.astype(float)
        self.m1_h = m1["high"].values.astype(float)
        self.m1_l = m1["low"].values.astype(float)
        self.m1_c = m1["close"].values.astype(float)
        self.m1_ts = m1.index.values
        self.m1_sh, self.m1_sl = swings(self.m1_h, self.m1_l, 2, 2)

        self.m5_idx = self.m5.index
        self.h4_pos = visible(self.m5_idx, self.h4.index, 240, 5)
        self.h1_pos = visible(self.m5_idx, self.h1.index, 60, 5)
        self.m15_pos = visible(self.m5_idx, self.m15.index, 15, 5)
        self.m5_close_pos = np.searchsorted(
            self.m1_ts, (self.m5_idx + pd.Timedelta(minutes=5)).values, "left")

        body = np.abs(self.m5_c - self.m5_o)
        self.m5_body = body
        self.m5_body_med = pd.Series(body).rolling(p.disp_median_n).median().values

        s = pd.Series(self.m5_atr)
        self.m5_atr_pct = s.rolling(p.atr_pct_window, min_periods=200).rank(pct=True).values * 100

        # §13 regime, measured on H1: trending / ranging / compression
        h1c = pd.Series(self.h1_c)
        e20 = h1c.ewm(span=20, adjust=False).mean()
        e50 = h1c.ewm(span=50, adjust=False).mean()
        slope = (e20 - e20.shift(10)).abs() / pd.Series(self.h1_atr).replace(0, np.nan)
        rng = (pd.Series(self.h1_h).rolling(24).max()
               - pd.Series(self.h1_l).rolling(24).min())
        rng_atr = rng / pd.Series(self.h1_atr).replace(0, np.nan)
        self.h1_trending = ((slope > 1.0) & ((e20 > e50) | (e20 < e50))).values
        self.h1_compressed = (rng_atr < 6.0).values
        self.h1_slope = slope.values

        self._liquidity()

    # -- §3 liquidity map ---------------------------------------------------
    def _liquidity(self):
        idx = self.m5_idx
        day = idx.normalize()
        d = pd.DataFrame({"h": self.m5_h, "l": self.m5_l}, index=idx)
        dh = d["h"].groupby(day).max(); dl = d["l"].groupby(day).min()
        self.pdh = dh.shift(1).reindex(day).values
        self.pdl = dl.shift(1).reindex(day).values
        wk = pd.PeriodIndex(idx.tz_convert(None), freq="W")
        wh = d["h"].groupby(wk).max(); wl = d["l"].groupby(wk).min()
        self.pwh = wh.shift(1).reindex(wk).values
        self.pwl = wl.shift(1).reindex(wk).values

        hour = idx.hour
        asia = (hour >= 0) & (hour < 7)
        lon = (hour >= 7) & (hour < 12)
        self.asian_h = self._sess(d["h"], day, asia, "max")
        self.asian_l = self._sess(d["l"], day, asia, "min")
        self.london_h = self._sess(d["h"], day, lon, "max")
        self.london_l = self._sess(d["l"], day, lon, "min")

    @staticmethod
    def _sess(series, day, mask, how):
        s = series.where(mask); g = s.groupby(day)
        run = g.cummax() if how == "max" else g.cummin()
        return run.ffill().shift(1).values

    # -- §14 -----------------------------------------------------------------
    def in_session(self, ts):
        lh = ts.astimezone(LONDON).hour
        nh = ts.astimezone(NEWYORK).hour
        a, b = self.p.london_window; c, d_ = self.p.ny_window
        return (a <= lh < b) or (c <= nh < d_)

    # -- §1 H4 macro bias: at least 3 of 5 ----------------------------------
    def h4_bias(self, i):
        k = self.h4_pos[i]
        if k < 60:
            return 0, 0
        lim = k - 2
        hi = np.flatnonzero(self.h4_sh[:lim + 1])
        lo = np.flatnonzero(self.h4_sl[:lim + 1])
        if len(hi) < 2 or len(lo) < 2:
            return 0, 0
        c = self.h4_c[k]
        w = slice(max(0, k - 40), k + 1)
        eq = (self.h4_h[w].max() + self.h4_l[w].min()) / 2.0     # equilibrium
        a = self.h4_atr[k]
        body = self.h4_c - self.h4_o
        med = np.median(np.abs(body[max(0, k - 20):k + 1])) or np.nan
        disp_up = bool((body[max(0, k - 6):k + 1] > 1.5 * med).any()) if np.isfinite(med) else False
        disp_dn = bool((body[max(0, k - 6):k + 1] < -1.5 * med).any()) if np.isfinite(med) else False
        e20 = pd.Series(self.h4_c[:k + 1]).ewm(span=20, adjust=False).mean().iloc[-1]
        e50 = pd.Series(self.h4_c[:k + 1]).ewm(span=50, adjust=False).mean().iloc[-1]

        bull = [self.h4_h[hi[-1]] > self.h4_h[hi[-2]],          # higher highs
                self.h4_l[lo[-1]] > self.h4_l[lo[-2]],          # higher lows
                c > eq,                                          # above equilibrium
                disp_up,                                         # bullish displacement
                e20 > e50]                                       # bullish order flow
        bear = [self.h4_h[hi[-1]] < self.h4_h[hi[-2]],
                self.h4_l[lo[-1]] < self.h4_l[lo[-2]],
                c < eq,
                disp_dn,
                e20 < e50]
        nb, ns = sum(bull), sum(bear)
        if nb >= 3 and nb > ns:
            return 1, nb
        if ns >= 3 and ns > nb:
            return -1, ns
        return 0, max(nb, ns)

    # -- §2 H1 dealing range, premium / discount ----------------------------
    def h1_pd(self, i, direction):
        """Returns (ok, position_in_range 0..1) for the latest H1 range."""
        k = self.h1_pos[i]
        if k < self.p.h1_range_bars:
            return False, np.nan
        w = slice(k - self.p.h1_range_bars + 1, k + 1)
        hi = self.h1_h[w].max(); lo = self.h1_l[w].min()
        if hi <= lo:
            return False, np.nan
        pos = (self.m5_c[i] - lo) / (hi - lo)
        if not self.p.require_pd:
            return True, pos
        return ((pos < 0.5) if direction > 0 else (pos > 0.5)), pos

    def h1_bias(self, i):
        k = self.h1_pos[i]
        if k < 60:
            return 0
        lim = k - 2
        hi = np.flatnonzero(self.h1_sh[:lim + 1]); lo = np.flatnonzero(self.h1_sl[:lim + 1])
        if len(hi) < 2 or len(lo) < 2:
            return 0
        hh = self.h1_h[hi[-1]] > self.h1_h[hi[-2]]
        hl = self.h1_l[lo[-1]] > self.h1_l[lo[-2]]
        lh = self.h1_h[hi[-1]] < self.h1_h[hi[-2]]
        ll = self.h1_l[lo[-1]] < self.h1_l[lo[-2]]
        if hh and hl:
            return 1
        if lh and ll:
            return -1
        return 0

    # -- §13 regime engine ---------------------------------------------------
    def regime(self, i):
        k = self.h1_pos[i]
        if k < 30:
            return None
        ap = self.m5_atr_pct[i]
        if not np.isfinite(ap) or ap < self.p.atr_pct_lo or ap > self.p.atr_pct_hi:
            return None                      # chop / abnormal volatility -> NO TRADE
        if self.h1_compressed[k]:
            return "C"                       # compression -> breakout
        if self.h1_trending[k] and self.h1_slope[k] > 1.5:
            return "B"                       # trending -> continuation
        return "A"                           # ranging -> liquidity reversal

    # -- §3 liquidity pools --------------------------------------------------
    def pools(self, i, direction):
        """Sell-side pools for LONG, buy-side for SHORT. (name, level, weight)."""
        out = []
        def add(n, v, w):
            if v is not None and np.isfinite(v):
                out.append((n, float(v), w))
        if direction > 0:
            add("PDL", self.pdl[i], 15); add("PWL", self.pwl[i], 15)
            add("AsianLow", self.asian_l[i], 12); add("LondonLow", self.london_l[i], 12)
        else:
            add("PDH", self.pdh[i], 15); add("PWH", self.pwh[i], 15)
            add("AsianHigh", self.asian_h[i], 12); add("LondonHigh", self.london_h[i], 12)
        k = self.m15_pos[i]
        if k > 10:
            lim = k - 2
            if direction > 0:
                for j in np.flatnonzero(self.m15_sl[:lim + 1])[-4:]:
                    add("M15 swing low", self.m15_l[j], 10)
            else:
                for j in np.flatnonzero(self.m15_sh[:lim + 1])[-4:]:
                    add("M15 swing high", self.m15_h[j], 10)
        return out

    # -- §5 sweep + reclaim ---------------------------------------------------
    def sweep(self, i, direction):
        p = self.p
        a = self.m5_atr[i]
        if not np.isfinite(a) or a <= 0:
            return None
        best = None
        for j in range(max(0, i - p.sweep_lookback_m5), i + 1):
            for name, lvl, w in self.pools(j, direction):
                if direction > 0:
                    pierced = self.m5_l[j] < lvl
                    reclaimed = self.m5_c[j] > lvl
                    depth = lvl - self.m5_l[j]
                else:
                    pierced = self.m5_h[j] > lvl
                    reclaimed = self.m5_c[j] < lvl
                    depth = self.m5_h[j] - lvl
                # §5: a clean raid, not a run-through
                if pierced and reclaimed and 0 < depth <= 3 * a:
                    ext = (self.m5_l[j:i + 1].min() if direction > 0
                           else self.m5_h[j:i + 1].max())
                    if best is None or w > best[3]:
                        best = (j, float(ext), name, w, float(depth / a))
        return best

    # -- §7 MSS ---------------------------------------------------------------
    def mss(self, i, sweep_bar, direction):
        lim = i - 2
        if direction > 0:
            idx = [j for j in np.flatnonzero(self.m5_sh[:lim + 1]) if j >= sweep_bar - 6]
            if not idx:
                return None
            lvl = self.m5_h[idx[-1]]
            return lvl if self.m5_c[i] > lvl else None
        idx = [j for j in np.flatnonzero(self.m5_sl[:lim + 1]) if j >= sweep_bar - 6]
        if not idx:
            return None
        lvl = self.m5_l[idx[-1]]
        return lvl if self.m5_c[i] < lvl else None

    # -- §8 FVG ---------------------------------------------------------------
    @staticmethod
    def fvg(h, l, upto, direction, lookback=6):
        for c3 in range(upto, max(1, upto - lookback), -1):
            c1 = c3 - 2
            if c1 < 0:
                continue
            if direction > 0 and h[c1] < l[c3]:
                return float(l[c3]), float(h[c1])
            if direction < 0 and l[c1] > h[c3]:
                return float(l[c1]), float(h[c3])
        return None

    # -- §9 order block -------------------------------------------------------
    @staticmethod
    def order_block(o, h, l, c, upto, direction, lookback=12):
        """Last opposing candle before the impulse. (top, bottom) or None."""
        for j in range(upto, max(1, upto - lookback), -1):
            if direction > 0 and c[j] < o[j]:
                return float(max(o[j], c[j])), float(l[j])
            if direction < 0 and c[j] > o[j]:
                return float(h[j]), float(min(o[j], c[j]))
        return None


def overlap(a, b):
    """Overlap of two (top, bottom) zones, or None."""
    if a is None or b is None:
        return None
    top = min(a[0], b[0]); bot = max(a[1], b[1])
    return (top, bot) if top > bot else None


# ---------------------------------------------------------------------------
@dataclass
class Signal:
    ts: pd.Timestamp
    direction: int
    engine: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    runner: float
    score: int
    grade: str
    liquidity: str
    sl_pips: float
    ob_fvg: bool
    parts: dict = field(default_factory=dict)
    deadline_m1: int = 0


def evaluate(ctx: Context, i: int, costs: Costs):
    """§21 long / §22 short. Returns Signal or None."""
    p = ctx.p
    if i < 300:
        return None
    ts = ctx.m5_idx[i]
    if not ctx.in_session(ts):                                    # §14
        return None
    if costs.spread_pips > costs.max_spread_pips:                 # §20
        return None

    engine = ctx.regime(i)                                        # §13
    if engine is None or engine not in p.engines_enabled:
        return None

    a = ctx.m5_atr[i]
    if not np.isfinite(a) or a <= 0:
        return None

    bias, nb = ctx.h4_bias(i)                                     # §1
    if bias == 0:
        return None
    direction = bias
    h1b = ctx.h1_bias(i)
    if h1b != 0 and h1b != direction:                             # §4 H4/H1 agree
        return None
    pd_ok, pd_pos = ctx.h1_pd(i, direction)                       # §2
    if not pd_ok:
        return None

    sw = ctx.sweep(i, direction)                                  # §5
    if sw is None:
        return None
    sweep_bar, sweep_ext, liq_name, liq_w, depth_atr = sw

    med = ctx.m5_body_med[i]                                      # §6
    if not np.isfinite(med) or med <= 0:
        return None
    ratio = ctx.m5_body[i] / med
    if ratio < p.disp_ratio_min:
        return None
    if (ctx.m5_c[i] - ctx.m5_o[i]) * direction <= 0:
        return None
    rng = ctx.m5_h[i] - ctx.m5_l[i]
    cpos = (ctx.m5_c[i] - ctx.m5_l[i]) / rng if rng > 0 else 0.5
    if direction < 0:
        cpos = 1 - cpos
    if cpos < 0.6:                                                # "strong close"
        return None

    if ctx.mss(i, sweep_bar, direction) is None:                  # §7
        return None

    fvg5 = ctx.fvg(ctx.m5_h, ctx.m5_l, i, direction)              # §8
    ob5 = ctx.order_block(ctx.m5_o, ctx.m5_h, ctx.m5_l, ctx.m5_c, # §9
                          i, direction, lookback=12)
    ob_fvg = overlap(ob5, fvg5) is not None

    # ---- §10 M1 precision -------------------------------------------------
    end_m1 = ctx.m5_close_pos[i]
    beg_m1 = max(0, end_m1 - p.m1_window_bars)
    if end_m1 >= len(ctx.m1_c) - 5:
        return None
    if _m1_mss(ctx, beg_m1, end_m1, direction) is None:
        return None
    fvg1 = ctx.fvg(ctx.m1_h, ctx.m1_l, end_m1 - 1, direction, lookback=12)
    ob1 = ctx.order_block(ctx.m1_o, ctx.m1_h, ctx.m1_l, ctx.m1_c,
                          end_m1 - 1, direction, lookback=15)
    zone = overlap(ob1, fvg1) or fvg1 or ob1                      # §10 preference
    if zone is None:
        return None
    entry_px = (zone[0] + zone[1]) / 2.0                          # 50% retracement

    # ---- §16 stop -----------------------------------------------------------
    stop = sweep_ext - direction * p.sl_atr_mult * a
    risk = abs(entry_px - stop)
    sl_pips = risk / PIP
    if risk <= 0 or sl_pips < p.sl_min_pips or sl_pips > p.sl_max_pips:
        return None

    # ---- §17 targets --------------------------------------------------------
    tp1 = entry_px + direction * p.tp_r_1 * risk
    tp2 = entry_px + direction * p.tp_r_2 * risk
    runner = _external_target(ctx, i, direction, entry_px, risk, p)

    # ---- §11 score ----------------------------------------------------------
    # §11 lists points PER CATEGORY. Each category is already a mandatory gate
    # in the §21 sequence, so a setup that reaches here has met all of them and
    # earns close to full marks; the remaining spread grades quality WITHIN each
    # category (e.g. 5-of-5 H4 conditions vs 3, a PDL sweep vs an M15 swing,
    # displacement 1.8+ vs 1.5). A setup scoring 90+ is therefore one where
    # nearly every category is at its best, which is the intended A+ bar.
    parts = {}
    parts["h4_bias"] = {5: 15.0, 4: 14.0, 3: 13.0}.get(nb, 13.0)
    parts["h1_bias"] = 10.0 if h1b == direction else 8.0
    edge = abs(pd_pos - 0.5) * 2 if np.isfinite(pd_pos) else 0.0
    parts["premium_discount"] = round(8.0 + 2.0 * min(1.0, edge / 0.6), 1)
    parts["major_liquidity"] = {15: 15.0, 12: 13.0, 10: 11.0}.get(liq_w, 11.0)
    parts["clean_sweep"] = round(12.0 + 3.0 * min(1.0, depth_atr / 1.0), 1)
    parts["m5_displacement"] = 10.0 if ratio >= p.disp_pref else 8.0
    parts["m5_mss"] = 10.0
    parts["fvg"] = 5.0 if fvg5 is not None else 3.0
    parts["ob_fvg_overlap"] = 5.0 if ob_fvg else (3.0 if ob5 is not None else 2.0)
    parts["m1_confirmation"] = 5.0
    score = int(round(sum(parts.values())))
    grade = "A+" if score >= 90 else "A" if score >= 85 else "B" if score >= 80 else "C"
    if score < p.min_score:                                       # §11
        return None

    return Signal(ts=ts, direction=direction, engine=engine, entry=float(entry_px),
                  stop=float(stop), tp1=float(tp1), tp2=float(tp2),
                  runner=float(runner), score=score, grade=grade,
                  liquidity=liq_name, sl_pips=float(sl_pips), ob_fvg=ob_fvg,
                  parts=parts, deadline_m1=end_m1 + p.m1_fill_bars)


def _m1_mss(ctx, beg, end, direction):
    lim = end - 2
    if lim <= beg + 3:
        return None
    if direction > 0:
        idx = [j for j in np.flatnonzero(ctx.m1_sh[:lim + 1]) if j >= beg]
        if not idx:
            return None
        lvl = ctx.m1_h[idx[-1]]
        return lvl if ctx.m1_c[beg:end].max() > lvl else None
    idx = [j for j in np.flatnonzero(ctx.m1_sl[:lim + 1]) if j >= beg]
    if not idx:
        return None
    lvl = ctx.m1_l[idx[-1]]
    return lvl if ctx.m1_c[beg:end].min() < lvl else None


def _external_target(ctx, i, direction, entry, risk, p):
    """§17 TP3/TP4 — nearest external liquidity beyond 2R, capped at runner_max_r."""
    lo = entry + direction * p.tp_r_2 * risk
    hi = entry + direction * p.runner_max_r * risk
    cands = []
    for lvl in ((ctx.pdh[i], ctx.pwh[i]) if direction > 0 else (ctx.pdl[i], ctx.pwl[i])):
        if lvl is None or not np.isfinite(lvl):
            continue
        if (direction > 0 and lo < lvl <= hi) or (direction < 0 and hi <= lvl < lo):
            cands.append(float(lvl))
    if cands:
        return min(cands) if direction > 0 else max(cands)
    return float(hi)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def backtest(ctx: Context, start, end, balance=10_000.0, risk_pct=0.0025,
             costs: Costs = None, daily_loss_stop=None):
    """§21 execution, §18 management, §19 daily protection.

    Entry is a LIMIT at the 50% of the M1 OB/FVG zone. It fills only if price
    trades back into the zone before the order expires, and is abandoned if the
    stop level trades first. Exits resolve on M1 bars; a bar spanning both the
    stop and a target resolves as the STOP.
    """
    costs = costs or Costs()
    p = ctx.p
    dstop = daily_loss_stop if daily_loss_stop is not None else p.daily_loss_stop

    lo = int(np.searchsorted(ctx.m5_idx.values,
             np.datetime64(pd.Timestamp(start).tz_convert("UTC").tz_localize(None)), "left"))
    hi = int(np.searchsorted(ctx.m5_idx.values,
             np.datetime64(pd.Timestamp(end).tz_convert("UTC").tz_localize(None)), "right"))

    ecost = (costs.spread_pips / 2 + costs.slip_entry_pips) * PIP
    trades, equity = [], [(ctx.m5_idx[lo], balance)]
    day = None; day_pnl = 0.0; day_trades = 0; consec = 0; day_start = balance
    busy = -1

    for i in range(lo, min(hi, len(ctx.m5_idx) - 1)):
        ts = ctx.m5_idx[i]
        d = ts.date()
        if d != day:
            day, day_pnl, day_trades, consec, day_start = d, 0.0, 0, 0, balance

        if day_trades >= p.max_trades_per_day:                     # §19
            continue
        if consec >= p.max_consec_losses:                          # §19
            continue
        if day_start > 0 and (day_pnl / day_start) <= -dstop:      # §19
            continue
        if ctx.m5_close_pos[i] < busy:
            continue

        sig = evaluate(ctx, i, costs)
        if sig is None:
            continue

        f0 = ctx.m5_close_pos[i]
        f1 = min(len(ctx.m1_c), sig.deadline_m1)
        fill = None
        for k in range(f0, f1):
            h_, l_ = ctx.m1_h[k], ctx.m1_l[k]
            if (sig.direction > 0 and l_ <= sig.stop) or (sig.direction < 0 and h_ >= sig.stop):
                break
            if (sig.direction > 0 and l_ <= sig.entry) or (sig.direction < 0 and h_ >= sig.entry):
                fill = k; break
        if fill is None:
            continue

        entry = sig.entry + sig.direction * ecost
        stop = sig.stop
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        tp1 = entry + sig.direction * p.tp_r_1 * risk
        tp2 = entry + sig.direction * p.tp_r_2 * risk
        runner = sig.runner
        be_lvl = entry + sig.direction * p.be_at_r * risk

        risk_usd = balance * risk_pct
        lots = max(0.01, np.floor(risk_usd / (risk * CONTRACT) * 100) / 100)

        cur_stop = stop
        remaining = 1.0
        realized = 0.0                      # in price units, weighted by fraction
        moved_be = False
        hit1 = hit2 = False
        reason = "time"
        end_k = min(len(ctx.m1_c), fill + p.max_hold_bars_m1)
        exit_k = end_k - 1
        exit_px = None

        for k in range(fill, end_k):
            h_, l_ = ctx.m1_h[k], ctx.m1_l[k]
            hit_sl = (l_ <= cur_stop) if sig.direction > 0 else (h_ >= cur_stop)
            hit_run = (h_ >= runner) if sig.direction > 0 else (l_ <= runner)

            if hit_sl:                       # ambiguity resolves against us
                px = cur_stop - sig.direction * costs.slip_stop_pips * PIP
                realized += remaining * (px - entry) * sig.direction
                reason = ("runner_stop" if hit2 else "partial_stop" if hit1
                          else ("breakeven" if moved_be else "stop"))
                exit_px, exit_k = px, k
                remaining = 0.0
                break
            if hit_run:
                realized += remaining * (runner - entry) * sig.direction
                reason, exit_px, exit_k = "target_runner", runner, k
                remaining = 0.0
                break

            reach = h_ if sig.direction > 0 else l_
            prog = (reach - entry) * sig.direction
            if not hit1 and prog >= p.tp_r_1 * risk:               # §18 close 30%
                realized += p.part1_frac * (tp1 - entry) * sig.direction
                remaining -= p.part1_frac; hit1 = True
            if not hit2 and prog >= p.tp_r_2 * risk:               # §18 close 30%
                realized += p.part2_frac * (tp2 - entry) * sig.direction
                remaining -= p.part2_frac; hit2 = True
            if not moved_be and prog >= p.be_at_r * risk:          # §18 BE+spread
                cur_stop = entry + sig.direction * costs.spread_pips * PIP
                moved_be = True
        else:
            exit_k = end_k - 1
            exit_px = ctx.m1_c[exit_k] - sig.direction * costs.slip_entry_pips * PIP
            realized += remaining * (exit_px - entry) * sig.direction
            remaining = 0.0

        gross = realized * CONTRACT * lots
        pnl = gross - costs.commission_per_lot * lots
        balance += pnl
        day_pnl += pnl
        day_trades += 1
        consec = consec + 1 if pnl < 0 else 0
        busy = exit_k + 1

        eff_pips = realized / PIP            # position-weighted pips captured
        trades.append(dict(
            signal_time=ts, entry_time=ctx.m1.index[fill], exit_time=ctx.m1.index[exit_k],
            side="BUY" if sig.direction > 0 else "SELL", engine=sig.engine,
            entry=entry, stop=stop, tp1=tp1, tp2=tp2, runner=runner,
            exit=exit_px, lots=round(lots, 2), pips=eff_pips, pnl=pnl,
            reason=reason, score=sig.score, grade=sig.grade,
            liquidity=sig.liquidity, ob_fvg=sig.ob_fvg, sl_pips=sig.sl_pips,
            risk_usd=risk_usd, r=pnl / risk_usd if risk_usd else 0.0,
            hold_min=int(exit_k - fill), balance=balance))
        equity.append((ctx.m1.index[exit_k], balance))

    return pd.DataFrame(trades), pd.DataFrame(equity, columns=["time", "equity"]).set_index("time")
