"""
XAUUSD SNIPER 87 — implementation of the supplied rule set.

Timeframe architecture (§1):
    H4  macro bias        H1  primary trend      M15 liquidity map
    M5  setup confirmation                       M1  precision entry

Every rule below is numbered against the source document. Where the document
leaves a value to be "calibrated in backtesting" the choice is marked CALIBRATED
and the value used is stated.

NO LOOK-AHEAD
    A signal computed from a bar's CLOSE is only actionable at/after that close.
    This is enforced by `visible()` for higher timeframes and by resolving all
    entries and exits on M1 bars stamped at or after the signal bar's close.
    (An earlier build in this repo lost this and manufactured a fake edge; see
    archive/xau_scalper_research/README.md.)

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


# ---------------------------------------------------------------------------
# Execution model
# ---------------------------------------------------------------------------
@dataclass
class Costs:
    spread_pips: float = 3.0        # $0.30 typical retail gold spread
    max_spread_pips: float = 5.0    # §22 spread filter
    slip_entry_pips: float = 0.5    # §23
    slip_stop_pips: float = 1.0     # extra adverse when a stop triggers
    commission_per_lot: float = 7.0 # USD round turn


@dataclass
class Params:
    # §7 displacement
    disp_ratio_min: float = 1.5
    disp_body_median_n: int = 20
    # §14 stop loss
    sl_atr_mult: float = 0.20
    sl_min_pips: float = 15.0       # CALIBRATED — floor, else spread dominates
    sl_max_pips: float = 120.0      # CALIBRATED — ceiling, else sizing collapses
    # §15 take profit
    tp_r: float = 2.0               # "Preferred = 2R"
    # §16 management
    be_at_r: float = 1.0
    partial_at_r: float = 1.5
    partial_frac: float = 0.5
    # §11 score
    min_score: int = 90
    # §13 ATR regime (percentile of M5 ATR14)
    atr_pct_lo: float = 30.0
    atr_pct_hi: float = 85.0
    atr_pct_window: int = 2000
    # §6 sweep
    sweep_lookback_m5: int = 12     # bars allowed between sweep and entry
    liq_tolerance_atr: float = 0.25 # how close counts as "at" a level
    # §10 M1 entry
    m1_window_bars: int = 60
    m1_fill_bars: int = 90          # how long the FVG limit rests
    # §19 / §21
    max_trades_per_day: int = 2
    max_losses_per_day: int = 2
    daily_loss_stop: float = 0.01   # §21 -- scaled with risk by the caller
    max_hold_bars_m1: int = 480     # 8h safety valve
    # §18 sessions (local exchange times)
    london_window: tuple = (7, 10)
    ny_window: tuple = (8, 11)


def default_params():
    return Params()


# ---------------------------------------------------------------------------
# Helpers
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
    """Fractal swings. A swing at i is only CONFIRMED at i+right."""
    n = len(high)
    sh = np.zeros(n, bool)
    sl = np.zeros(n, bool)
    for i in range(left, n - right):
        wh = high[i - left:i + right + 1]
        wl = low[i - left:i + right + 1]
        if high[i] == wh.max() and wh.argmax() == left:
            sh[i] = True
        if low[i] == wl.min() and wl.argmin() == left:
            sl[i] = True
    return sh, sl


def visible(base_index, htf_index, htf_minutes, base_minutes):
    """Positional index of the last HTF bar CLOSED by each base bar's close."""
    bc = base_index + pd.Timedelta(minutes=base_minutes)
    hc = htf_index + pd.Timedelta(minutes=htf_minutes)
    return np.searchsorted(hc.values, bc.values, "right") - 1


def structure(high, low, sh, sl, upto):
    """+1 HH+HL, -1 LH+LL, 0 otherwise, using swings confirmed by `upto`."""
    lim = upto - 2
    if lim < 4:
        return 0
    hi = np.flatnonzero(sh[:lim + 1])
    lo = np.flatnonzero(sl[:lim + 1])
    if len(hi) < 2 or len(lo) < 2:
        return 0
    hh = high[hi[-1]] > high[hi[-2]]
    hl = low[lo[-1]] > low[lo[-2]]
    lh = high[hi[-1]] < high[hi[-2]]
    ll = low[lo[-1]] < low[lo[-2]]
    if hh and hl:
        return 1
    if lh and ll:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Context: all timeframes, precomputed
# ---------------------------------------------------------------------------
class Context:
    def __init__(self, m1, p: Params):
        self.p = p
        self.m1 = m1
        self.m5 = resample(m1, "5min")
        self.m15 = resample(m1, "15min")
        self.h1 = resample(m1, "1h")
        self.h4 = resample(m1, "4h")

        for nm, f in (("m5", self.m5), ("m15", self.m15),
                      ("h1", self.h1), ("h4", self.h4)):
            for c in ("open", "high", "low", "close"):
                setattr(self, f"{nm}_{c[0] if c != 'close' else 'c'}",
                        f[c].values.astype(float))
            sh, sl = swings(f["high"].values, f["low"].values, 2, 2)
            setattr(self, f"{nm}_sh", sh)
            setattr(self, f"{nm}_sl", sl)
            setattr(self, f"{nm}_atr", atr(f, 14).values)

        self.m1_o = m1["open"].values.astype(float)
        self.m1_h = m1["high"].values.astype(float)
        self.m1_l = m1["low"].values.astype(float)
        self.m1_c = m1["close"].values.astype(float)
        self.m1_ts = m1.index.values
        self.m1_sh, self.m1_sl = swings(self.m1_h, self.m1_l, 2, 2)

        # §2/§3 moving averages
        self.h4_ema50 = ema(self.h4["close"], 50).values
        self.h4_ema200 = ema(self.h4["close"], 200).values
        self.h1_ema50 = ema(self.h1["close"], 50).values

        # visibility maps (M5 is the decision clock)
        self.m5_idx = self.m5.index
        self.h4_pos = visible(self.m5_idx, self.h4.index, 240, 5)
        self.h1_pos = visible(self.m5_idx, self.h1.index, 60, 5)
        self.m15_pos = visible(self.m5_idx, self.m15.index, 15, 5)
        self.m5_close_pos = np.searchsorted(
            self.m1_ts, (self.m5_idx + pd.Timedelta(minutes=5)).values, "left")

        # §7 displacement denominator
        body = np.abs(self.m5_c - self.m5_o)
        self.m5_body = body
        self.m5_body_med = pd.Series(body).rolling(
            p.disp_body_median_n).median().values

        # §13 ATR percentile
        s = pd.Series(self.m5_atr)
        self.m5_atr_pct = s.rolling(p.atr_pct_window, min_periods=200).rank(pct=True).values * 100

        # §12 VWAP (session-anchored typical price; no volume in feed)
        tp = (self.m5["high"] + self.m5["low"] + self.m5["close"]) / 3
        self.m5_vwap = tp.groupby(self.m5_idx.normalize()).expanding().mean() \
                         .reset_index(level=0, drop=True).values

        self._build_liquidity()

    # -- §4 liquidity map --------------------------------------------------
    def _build_liquidity(self):
        """Previous day / previous week / Asian / London extremes, per M5 bar.

        Each level is shifted so a bar only ever sees COMPLETED sessions.
        """
        idx = self.m5_idx
        day = idx.normalize()
        d = pd.DataFrame({"h": self.m5_h, "l": self.m5_l}, index=idx)

        dh = d["h"].groupby(day).max()
        dl = d["l"].groupby(day).min()
        self.pdh = dh.shift(1).reindex(day).values
        self.pdl = dl.shift(1).reindex(day).values

        wk = idx.to_period("W")
        wh = d["h"].groupby(wk).max()
        wl = d["l"].groupby(wk).min()
        self.pwh = wh.shift(1).reindex(wk).values
        self.pwl = wl.shift(1).reindex(wk).values
        self.pw_mid = (self.pwh + self.pwl) / 2.0        # §2 weekly midpoint

        hour = idx.hour
        # Asian 00:00-07:00 UTC, London 07:00-12:00 UTC — running extremes of
        # the CURRENT day's completed portion of each session
        asia = (hour >= 0) & (hour < 7)
        lon = (hour >= 7) & (hour < 12)
        self.asian_h = self._session_extreme(d["h"], day, asia, "max")
        self.asian_l = self._session_extreme(d["l"], day, asia, "min")
        self.london_h = self._session_extreme(d["h"], day, lon, "max")
        self.london_l = self._session_extreme(d["l"], day, lon, "min")

    @staticmethod
    def _session_extreme(series, day, mask, how):
        s = series.where(mask)
        g = s.groupby(day)
        run = g.cummax() if how == "max" else g.cummin()
        return run.ffill().shift(1).values      # shift: never see the live bar

    # -- §18 session filter -------------------------------------------------
    def in_session(self, ts):
        lo_h = ts.astimezone(LONDON).hour
        ny_h = ts.astimezone(NEWYORK).hour
        a, b = self.p.london_window
        c, d_ = self.p.ny_window
        return (a <= lo_h < b) or (c <= ny_h < d_)

    # -- §2 H4 macro filter (3 of 4) ---------------------------------------
    def h4_bias(self, i):
        k = self.h4_pos[i]
        if k < 200:
            return 0, 0
        c = self.h4_c[k]
        bull = [c > self.h4_ema50[k],
                self.h4_ema50[k] > self.h4_ema200[k],
                structure(self.h4_h, self.h4_l, self.h4_sh, self.h4_sl, k) == 1,
                (not np.isnan(self.pw_mid[i])) and c > self.pw_mid[i]]
        bear = [c < self.h4_ema50[k],
                self.h4_ema50[k] < self.h4_ema200[k],
                structure(self.h4_h, self.h4_l, self.h4_sh, self.h4_sl, k) == -1,
                (not np.isnan(self.pw_mid[i])) and c < self.pw_mid[i]]
        nb, ns = sum(bull), sum(bear)
        if nb >= 3:
            return 1, nb
        if ns >= 3:
            return -1, ns
        return 0, max(nb, ns)

    # -- §3 H1 directional filter ------------------------------------------
    def h1_ok(self, i, direction):
        k = self.h1_pos[i]
        if k < 60:
            return False
        c = self.h1_c[k]
        st = structure(self.h1_h, self.h1_l, self.h1_sh, self.h1_sl, k)
        if st != direction:
            return False
        if direction > 0 and not c > self.h1_ema50[k]:
            return False
        if direction < 0 and not c < self.h1_ema50[k]:
            return False
        # last confirmed swing low/high still intact
        lim = k - 2
        if direction > 0:
            lows = np.flatnonzero(self.h1_sl[:lim + 1])
            if not len(lows):
                return False
            if self.h1_c[lows[-1]:k + 1].min() < self.h1_l[lows[-1]]:
                return False
        else:
            highs = np.flatnonzero(self.h1_sh[:lim + 1])
            if not len(highs):
                return False
            if self.h1_c[highs[-1]:k + 1].max() > self.h1_h[highs[-1]]:
                return False
        # recent bullish/bearish displacement on H1
        b = np.abs(self.h1_c - self.h1_o)
        med = np.median(b[max(0, k - 20):k + 1]) if k >= 20 else np.nan
        if not np.isfinite(med) or med <= 0:
            return False
        win = slice(max(0, k - 5), k + 1)
        disp = ((self.h1_c[win] - self.h1_o[win]) * direction > 1.2 * med).any()
        return bool(disp)

    # -- §4 nearest major liquidity level -----------------------------------
    def liquidity_levels(self, i, direction):
        """Sell-side pools for a LONG, buy-side for a SHORT, newest first.
        Returns [(name, level, weight)] where weight feeds the §11 score."""
        out = []
        def add(name, lvl, w):
            if lvl is not None and np.isfinite(lvl):
                out.append((name, float(lvl), w))
        if direction > 0:
            add("PDL", self.pdl[i], 15); add("PWL", self.pwl[i], 15)
            add("AsianL", self.asian_l[i], 12); add("LondonL", self.london_l[i], 12)
        else:
            add("PDH", self.pdh[i], 15); add("PWH", self.pwh[i], 15)
            add("AsianH", self.asian_h[i], 12); add("LondonH", self.london_h[i], 12)

        # major M15 swing extremes
        k = self.m15_pos[i]
        if k > 10:
            lim = k - 2
            if direction > 0:
                idx = np.flatnonzero(self.m15_sl[:lim + 1])
                for j in idx[-3:]:
                    add("M15swingL", self.m15_l[j], 10)
            else:
                idx = np.flatnonzero(self.m15_sh[:lim + 1])
                for j in idx[-3:]:
                    add("M15swingH", self.m15_h[j], 10)

        # §4 optional psychological levels xx00 / xx50
        px = self.m5_c[i]
        for step in (100.0, 50.0):
            lvl = np.floor(px / step) * step if direction > 0 else np.ceil(px / step) * step
            add(f"psych{int(step)}", lvl, 8)
        return out

    # -- §6 sweep + reclaim --------------------------------------------------
    def find_sweep(self, i, direction):
        """A bar within the lookback that traded THROUGH a liquidity level and
        whose M5 close reclaimed it. Returns (bar, extreme, name, weight)."""
        p = self.p
        a = self.m5_atr[i]
        if not np.isfinite(a) or a <= 0:
            return None
        tol = p.liq_tolerance_atr * a
        best = None
        for j in range(max(0, i - p.sweep_lookback_m5), i + 1):
            for name, lvl, w in self.liquidity_levels(j, direction):
                if direction > 0:
                    if self.m5_l[j] < lvl and self.m5_c[j] > lvl and (lvl - self.m5_l[j]) <= 3 * a:
                        ext = self.m5_l[j:i + 1].min()
                        if best is None or w > best[3]:
                            best = (j, float(ext), name, w)
                else:
                    if self.m5_h[j] > lvl and self.m5_c[j] < lvl and (self.m5_h[j] - lvl) <= 3 * a:
                        ext = self.m5_h[j:i + 1].max()
                        if best is None or w > best[3]:
                            best = (j, float(ext), name, w)
        return best

    # -- §8 market structure shift ------------------------------------------
    def mss(self, i, sweep_bar, direction):
        """LONG: close through the most recent M5 lower-high after the sweep."""
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

    # -- §9 fair value gap ---------------------------------------------------
    @staticmethod
    def find_fvg(h, l, upto, direction, lookback=6):
        """Newest unfilled 3-candle imbalance ending at/near `upto`.
        Bullish: candle1.high < candle3.low. Returns (top, bottom)."""
        for c3 in range(upto, max(1, upto - lookback), -1):
            c1 = c3 - 2
            if c1 < 0:
                continue
            if direction > 0 and h[c1] < l[c3]:
                return float(l[c3]), float(h[c1])
            if direction < 0 and l[c1] > h[c3]:
                return float(l[c1]), float(h[c3])
        return None


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    ts: pd.Timestamp
    direction: int
    entry: float
    stop: float
    target: float
    score: int
    grade: str
    sweep_level: str
    sl_pips: float
    parts: dict = field(default_factory=dict)
    fill_deadline_m1: int = 0


def evaluate(ctx: Context, i: int, costs: Costs):
    """Evaluate M5 bar i (closed). Returns Signal or None. §25 algorithm."""
    p = ctx.p
    ts = ctx.m5_idx[i]
    if i < 300:
        return None
    if not ctx.in_session(ts):                                   # §18
        return None

    a = ctx.m5_atr[i]
    if not np.isfinite(a) or a <= 0:
        return None
    apct = ctx.m5_atr_pct[i]                                     # §13
    if not np.isfinite(apct) or not (p.atr_pct_lo <= apct <= p.atr_pct_hi):
        return None
    if costs.spread_pips > costs.max_spread_pips:                # §22
        return None

    bias, nb = ctx.h4_bias(i)                                    # §2
    if bias == 0:
        return None
    direction = bias
    if not ctx.h1_ok(i, direction):                              # §3
        return None

    sw = ctx.find_sweep(i, direction)                            # §6
    if sw is None:
        return None
    sweep_bar, sweep_ext, liq_name, liq_w = sw

    med = ctx.m5_body_med[i]                                     # §7
    if not np.isfinite(med) or med <= 0:
        return None
    disp_ratio = ctx.m5_body[i] / med
    if disp_ratio < p.disp_ratio_min:
        return None
    if (ctx.m5_c[i] - ctx.m5_o[i]) * direction <= 0:
        return None
    rng = ctx.m5_h[i] - ctx.m5_l[i]
    close_pos = ((ctx.m5_c[i] - ctx.m5_l[i]) / rng if rng > 0 else 0.5)
    if direction < 0:
        close_pos = 1 - close_pos
    if close_pos < 0.6:                       # "close near candle extreme"
        return None

    if ctx.mss(i, sweep_bar, direction) is None:                 # §8
        return None

    fvg5 = ctx.find_fvg(ctx.m5_h, ctx.m5_l, i, direction)        # §9

    # ---- §10 M1 precision entry -----------------------------------------
    end_m1 = ctx.m5_close_pos[i]
    beg_m1 = max(0, end_m1 - p.m1_window_bars)
    if end_m1 >= len(ctx.m1_c) - 5:
        return None
    m1_shift = _m1_mss(ctx, beg_m1, end_m1, direction)
    if m1_shift is None:
        return None
    fvg1 = ctx.find_fvg(ctx.m1_h, ctx.m1_l, end_m1 - 1, direction, lookback=12)
    if fvg1 is None:
        return None
    top1, bot1 = fvg1
    entry_px = (top1 + bot1) / 2.0                               # §9 50% retrace

    # ---- §14 stop ---------------------------------------------------------
    buf = p.sl_atr_mult * a
    stop = sweep_ext - direction * buf
    sl_dist = abs(entry_px - stop)
    sl_pips = sl_dist / PIP
    if sl_pips < p.sl_min_pips or sl_pips > p.sl_max_pips:
        return None
    if sl_dist <= 0:
        return None

    target = entry_px + direction * p.tp_r * sl_dist             # §15

    # ---- §11 score --------------------------------------------------------
    parts = {}
    parts["h4_bias"] = 15 if nb >= 4 else 13
    parts["h1_bias"] = 15
    parts["major_liquidity"] = min(15, liq_w)
    reclaim = abs(ctx.m5_c[sweep_bar] - sweep_ext) / a
    parts["clean_sweep"] = round(min(15.0, 9 + 6 * min(1.0, reclaim / 1.2)), 1)
    parts["m5_displacement"] = 10 if disp_ratio >= 1.8 else 8
    parts["m5_mss"] = 10
    parts["fvg"] = 5 if fvg5 is not None else 3
    parts["m1_confirmation"] = 10
    vw = ctx.m5_vwap[i]                                          # §12
    if np.isfinite(vw):
        aligned = (ctx.m5_c[i] > vw) if direction > 0 else (ctx.m5_c[i] < vw)
        parts["vwap"] = 3 if aligned else 0
    else:
        parts["vwap"] = 0
    parts["atr_regime"] = 2 if 40 <= apct <= 75 else 1           # §13

    score = int(round(sum(parts.values())))
    grade = ("A+" if score >= 90 else "A" if score >= 85
             else "B" if score >= 80 else "C")
    if score < p.min_score:                                      # §11
        return None

    return Signal(ts=ts, direction=direction, entry=float(entry_px),
                  stop=float(stop), target=float(target), score=score,
                  grade=grade, sweep_level=liq_name, sl_pips=float(sl_pips),
                  parts=parts, fill_deadline_m1=end_m1 + p.m1_fill_bars)


def _m1_mss(ctx, beg, end, direction):
    """§10 — did M1 shift structure inside the window?"""
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


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def backtest(ctx: Context, start, end, balance=10_000.0, risk_pct=0.005,
             costs: Costs = None, daily_loss_stop=None):
    """§25 execution with §16 management and §19/§21 kill switches.

    Entry is a LIMIT at the 50% M1 FVG retracement (§9). It fills only if price
    actually trades back into the gap before the order expires, and is
    abandoned if the stop level is hit first. Every exit is resolved on M1
    bars; a bar spanning both stop and target resolves as a STOP.
    """
    costs = costs or Costs()
    p = ctx.p
    daily_loss_stop = daily_loss_stop if daily_loss_stop is not None else p.daily_loss_stop

    lo = int(np.searchsorted(ctx.m5_idx.values,
                             np.datetime64(pd.Timestamp(start).tz_convert("UTC").tz_localize(None)), "left"))
    hi = int(np.searchsorted(ctx.m5_idx.values,
                             np.datetime64(pd.Timestamp(end).tz_convert("UTC").tz_localize(None)), "right"))

    entry_cost = (costs.spread_pips / 2 + costs.slip_entry_pips) * PIP
    trades = []
    equity = [(ctx.m5_idx[lo], balance)]

    day = None
    day_pnl = 0.0
    day_trades = 0
    day_losses = 0
    day_start_bal = balance
    busy_until = -1

    for i in range(lo, min(hi, len(ctx.m5_idx) - 1)):
        ts = ctx.m5_idx[i]
        d = ts.date()
        if d != day:
            day, day_pnl, day_trades, day_losses, day_start_bal = d, 0.0, 0, 0, balance

        if day_trades >= p.max_trades_per_day:                    # §19
            continue
        if day_losses >= p.max_losses_per_day:                    # §19/§21
            continue
        if day_start_bal > 0 and (day_pnl / day_start_bal) <= -daily_loss_stop:
            continue                                              # §21
        if ctx.m5_close_pos[i] < busy_until:
            continue

        sig = evaluate(ctx, i, costs)
        if sig is None:
            continue

        # ---- limit fill at the M1 FVG 50% ------------------------------
        f0 = ctx.m5_close_pos[i]
        f1 = min(len(ctx.m1_c), sig.fill_deadline_m1)
        fill = None
        for k in range(f0, f1):
            h_, l_ = ctx.m1_h[k], ctx.m1_l[k]
            if (sig.direction > 0 and l_ <= sig.stop) or \
               (sig.direction < 0 and h_ >= sig.stop):
                break                                    # invalidated pre-fill
            if (sig.direction > 0 and l_ <= sig.entry) or \
               (sig.direction < 0 and h_ >= sig.entry):
                fill = k
                break
        if fill is None:
            continue

        entry = sig.entry + sig.direction * entry_cost
        stop = sig.stop
        risk_px = abs(entry - stop)
        if risk_px <= 0:
            continue
        target = entry + sig.direction * p.tp_r * risk_px
        be_lvl = entry + sig.direction * p.be_at_r * risk_px
        part_lvl = entry + sig.direction * p.partial_at_r * risk_px

        risk_usd = balance * risk_pct
        lots = max(0.01, np.floor(risk_usd / (risk_px * CONTRACT) * 100) / 100)

        # ---- resolve on M1 ---------------------------------------------
        cur_stop = stop
        remaining = 1.0
        realized = 0.0
        moved_be = False
        took_partial = False
        reason = "time"
        exit_px = None
        end_k = min(len(ctx.m1_c), fill + p.max_hold_bars_m1)

        for k in range(fill, end_k):
            h_, l_ = ctx.m1_h[k], ctx.m1_l[k]
            hit_sl = (l_ <= cur_stop) if sig.direction > 0 else (h_ >= cur_stop)
            hit_tp = (h_ >= target) if sig.direction > 0 else (l_ <= target)

            if hit_sl:                       # ambiguity resolves against us
                px = cur_stop - sig.direction * costs.slip_stop_pips * PIP
                realized += remaining * (px - entry) * sig.direction
                reason = "breakeven" if (moved_be and cur_stop != stop) else "stop"
                exit_px = px
                exit_k = k
                break
            if hit_tp:
                realized += remaining * (target - entry) * sig.direction
                reason, exit_px, exit_k = "target", target, k
                break

            # §16 management, checked after barriers so it cannot rescue a bar
            reached = (h_ if sig.direction > 0 else l_)
            prog = (reached - entry) * sig.direction
            if not took_partial and prog >= p.partial_at_r * risk_px:
                realized += p.partial_frac * (part_lvl - entry) * sig.direction
                remaining -= p.partial_frac
                took_partial = True
            if not moved_be and prog >= p.be_at_r * risk_px:
                cur_stop = entry + sig.direction * costs.spread_pips * PIP
                moved_be = True
        else:
            exit_k = end_k - 1
            exit_px = ctx.m1_c[exit_k] - sig.direction * costs.slip_entry_pips * PIP
            realized += remaining * (exit_px - entry) * sig.direction

        gross = realized * CONTRACT * lots
        comm = costs.commission_per_lot * lots
        pnl = gross - comm
        balance += pnl
        day_pnl += pnl
        day_trades += 1
        if pnl < 0:
            day_losses += 1
        busy_until = exit_k + 1

        pips = (exit_px - entry) * sig.direction / PIP
        trades.append(dict(
            signal_time=ts,
            entry_time=ctx.m1.index[fill], exit_time=ctx.m1.index[exit_k],
            side="BUY" if sig.direction > 0 else "SELL",
            entry=entry, stop=stop, target=target, exit=exit_px,
            lots=round(lots, 2), pips=pips, pnl=pnl, reason=reason,
            score=sig.score, grade=sig.grade, liquidity=sig.sweep_level,
            sl_pips=sig.sl_pips, risk_usd=risk_usd,
            r=pnl / risk_usd if risk_usd else 0.0,
            hold_min=int(exit_k - fill), balance=balance))
        equity.append((ctx.m1.index[exit_k], balance))

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame(equity, columns=["time", "equity"]).set_index("time")
    return tr, eq
