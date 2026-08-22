"""
Smart Money Concepts engine — H4 bias -> H1 point of interest -> M15 shift ->
M1 sniper entry, with a fixed-pip trailing stop.

TIMEFRAME ROLES
    H4   market structure and directional bias (BOS / CHoCH, swing structure)
    H1   the point of interest: an unmitigated order block or fair-value gap
         sitting in the correct premium/discount half of the dealing range
    M15  confirmation that the POI is reacting — a change of character
    M1   the sniper trigger: micro-CHoCH plus entry at the micro order block /
         FVG, which is what makes the stop small enough to matter

NO LOOK-AHEAD
    Every structure read is built from bars that had already CLOSED at the
    decision instant. Swing points carry an explicit right-hand confirmation
    lag, and higher-timeframe frames are gated by `visible_upto`.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from strategy import PIP, CONTRACT, QUOTE, BASE, SPREAD_PIPS, atr, ema


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
@dataclass
class SMCParams:
    # --- structure ---
    swing_left: int = 2
    swing_right: int = 2
    h4_lookback: int = 60            # H4 bars used for the dealing range

    # --- point of interest (H1) ---
    poi_max_age: int = 60            # H1 bars an unmitigated POI stays valid
    use_order_blocks: bool = True
    use_fvg: bool = True
    premium_discount: float = 0.5    # buy below this fraction of the range

    # --- confirmation (M15) ---
    m15_confirm_bars: int = 12       # bars after the POI touch to find a CHoCH
    require_m15_choch: bool = True
    require_sweep: bool = True       # a liquidity raid must precede the reversal
    sweep_lookback_m15: int = 30     # bars defining the liquidity pool
    sweep_window_m15: int = 12       # how recently the raid must have happened

    # --- sniper entry (M1) ---
    use_m1: bool = True
    m1_window_bars: int = 90         # M1 bars searched after the M15 CHoCH
    m1_swing_left: int = 2
    m1_swing_right: int = 2
    m1_entry_mode: str = "ob"        # "ob" = micro order block, "fvg", "market"
    m1_ob_lookback: int = 30         # M1 bars searched back for the micro block
    # Where the stop is anchored when a sniper entry is used:
    #   "m1"  - the micro structure that produced the entry (very tight)
    #   "m15" - the M15 swing behind the setup (sniper entry, survivable stop)
    m1_stop_source: str = "m1"
    entry_expiry_m1: int = 120       # M1 bars the sniper limit stays live
    m1_fill_bars: int = 8            # M15 bars the sniper limit stays live

    # --- risk / exits ---
    sl_buffer_atr: float = 0.35      # beyond the entry structure, in M15 ATR
    sl_min_pips: float = 4.0
    tp_r: float = 3.0                # sniper entries make a wide target reachable
    trail_mode: str = "gap"          # "gap" | "step" | "off" | "r"
    trail_step_pips: float = 20.0    # move the stop every 20 pips of progress
    trail_start_pips: float = 20.0   # arm the trail after this much profit
    trail_gap_pips: float = 20.0     # distance the stop keeps behind price
    trail_r: float = 1.0             # trail_mode "r": step size in R instead
    time_stop_bars_m15: int = 96     # 24 hours on M15

    # --- filters ---
    atr_period: int = 14
    min_atr_pct: float = 0.00020
    max_atr_pct: float = 0.01500
    max_spread_atr: float = 0.45
    sessions: tuple = ((6, 18),)     # UTC; London + New York
    min_rr: float = 1.5
    min_score: int = 60


def default_smc():
    return SMCParams()


# ---------------------------------------------------------------------------
# Structure primitives
# ---------------------------------------------------------------------------
def swings(high, low, left=2, right=2):
    """Fractal swing highs/lows. Index i is only CONFIRMED at i+right."""
    n = len(high)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        wh = high[i - left:i + right + 1]
        wl = low[i - left:i + right + 1]
        if high[i] == wh.max() and wh.argmax() == left:
            sh[i] = True
        if low[i] == wl.min() and wl.argmin() == left:
            sl[i] = True
    return sh, sl


def structure_state(high, low, close, sh, sl, upto):
    """Bias from break of structure / change of character, using only bars
    confirmed at or before `upto`.

    Returns (bias, last_swing_high_idx, last_swing_low_idx).
    bias: +1 bullish, -1 bearish, 0 undefined.
    """
    lim = upto - 2                                  # fractal confirmation lag
    if lim < 5:
        return 0, None, None
    hi_idx = np.flatnonzero(sh[:lim + 1])
    lo_idx = np.flatnonzero(sl[:lim + 1])
    if len(hi_idx) < 2 or len(lo_idx) < 2:
        return 0, None, None

    last_h, prev_h = hi_idx[-1], hi_idx[-2]
    last_l, prev_l = lo_idx[-1], lo_idx[-2]

    hh = high[last_h] > high[prev_h]
    hl = low[last_l] > low[prev_l]
    lh = high[last_h] < high[prev_h]
    ll = low[last_l] < low[prev_l]

    bias = 0
    if hh and hl:
        bias = 1
    elif lh and ll:
        bias = -1
    else:
        # No clean swing pattern: fall back to the most recent displacement
        # through a confirmed swing (a break of structure).
        c = close[upto]
        if c > high[last_h]:
            bias = 1
        elif c < low[last_l]:
            bias = -1
    return bias, last_h, last_l


def order_blocks(o, h, l, c, atr_v, direction, upto, lookback=40, min_disp=0.6):
    """Unmitigated order blocks visible at `upto`.

    Bullish OB: the last down-close candle before an up-move that displaces
    and breaks the preceding high. Returns [(idx, top, bottom)], newest first.
    """
    out = []
    start = max(1, upto - lookback)
    for i in range(upto - 1, start, -1):
        a = atr_v[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if direction > 0:
            if c[i] >= o[i]:                       # need a down candle
                continue
            j = i + 1
            if j > upto:
                continue
            # displacement away from the block
            move = c[min(j + 2, upto)] - o[j]
            if move < min_disp * a:
                continue
            if h[min(j + 2, upto)] <= h[i]:        # must break the block's high
                continue
            top, bot = max(o[i], c[i]), l[i]
            # unmitigated: price has not traded back below the block's low
            if l[j:upto + 1].min() < bot:
                continue
            out.append((i, top, bot))
        else:
            if c[i] <= o[i]:
                continue
            j = i + 1
            if j > upto:
                continue
            move = o[j] - c[min(j + 2, upto)]
            if move < min_disp * a:
                continue
            if l[min(j + 2, upto)] >= l[i]:
                continue
            top, bot = h[i], min(o[i], c[i])
            if h[j:upto + 1].max() > top:
                continue
            out.append((i, top, bot))
        if len(out) >= 3:
            break
    return out


def fair_value_gaps(h, l, direction, upto, lookback=40):
    """Unfilled 3-candle imbalances visible at `upto`. Newest first."""
    out = []
    start = max(2, upto - lookback)
    for i in range(upto - 1, start, -1):
        if direction > 0:
            gap_lo, gap_hi = h[i - 1], l[i + 1] if i + 1 <= upto else np.nan
            if not np.isfinite(gap_hi) or gap_hi <= gap_lo:
                continue
            if l[i + 1:upto + 1].min() < gap_lo:   # already filled
                continue
            out.append((i, gap_hi, gap_lo))
        else:
            gap_hi, gap_lo = l[i - 1], h[i + 1] if i + 1 <= upto else np.nan
            if not np.isfinite(gap_lo) or gap_lo >= gap_hi:
                continue
            if h[i + 1:upto + 1].max() > gap_hi:
                continue
            out.append((i, gap_hi, gap_lo))
        if len(out) >= 3:
            break
    return out


def choch(high, low, close, sh, sl, upto, direction, window=12):
    """Change of character: within `window` bars up to `upto`, did price close
    through the most recent opposing confirmed swing?"""
    lim = upto - 2
    if lim < 3:
        return None
    if direction > 0:
        idx = np.flatnonzero(sh[:lim + 1])
        if not len(idx):
            return None
        lvl = high[idx[-1]]
        for k in range(max(0, upto - window), upto + 1):
            if close[k] > lvl:
                return k
    else:
        idx = np.flatnonzero(sl[:lim + 1])
        if not len(idx):
            return None
        lvl = low[idx[-1]]
        for k in range(max(0, upto - window), upto + 1):
            if close[k] < lvl:
                return k
    return None


# ---------------------------------------------------------------------------
# Multi-timeframe context
# ---------------------------------------------------------------------------
def resample(df, rule):
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    return out.dropna()


class SMCContext:
    """Holds H4 / H1 / M15 (and optionally M1) views of one instrument.

    `m15` is the raw 15-minute feed; higher frames are derived from it so all
    timeframes share a single source of truth.
    """

    def __init__(self, symbol, m15, p: SMCParams, m1=None):
        self.symbol = symbol
        self.p = p
        self.pip = PIP[symbol]
        self.spread = SPREAD_PIPS[symbol] * self.pip

        self.m15 = m15
        self.h1 = resample(m15, "1h")
        self.h4 = resample(m15, "4h")
        self.m1 = m1

        for name, f in (("m15", self.m15), ("h1", self.h1), ("h4", self.h4)):
            o, h, l, c = (f[k].values for k in ("open", "high", "low", "close"))
            setattr(self, f"{name}_o", o); setattr(self, f"{name}_h", h)
            setattr(self, f"{name}_l", l); setattr(self, f"{name}_c", c)
            sh, sl = swings(h, l, p.swing_left, p.swing_right)
            setattr(self, f"{name}_sh", sh); setattr(self, f"{name}_sl", sl)
            setattr(self, f"{name}_atr", atr(f, p.atr_period).values)

        # index maps: for each M15 bar, the last CLOSED H1 / H4 bar
        self.h1_pos = self._visible(self.m15.index, self.h1.index, 60)
        self.h4_pos = self._visible(self.m15.index, self.h4.index, 240)

        if m1 is not None and len(m1):
            self.m1_o = m1["open"].values.astype(float)
            self.m1_h = m1["high"].values.astype(float)
            self.m1_l = m1["low"].values.astype(float)
            self.m1_c = m1["close"].values.astype(float)
            self.m1_sh, self.m1_sl = swings(self.m1_h, self.m1_l,
                                            p.m1_swing_left, p.m1_swing_right)
            self.m1_idx = m1.index
            self.m1_ts = m1.index.values.astype("datetime64[ns]")
        else:
            self.m1_idx = None

    @staticmethod
    def _visible(base_index, htf_index_, htf_minutes, base_minutes=15):
        """Positional index of the last HTF bar CLOSED by each base bar's close."""
        base_close = base_index + pd.Timedelta(minutes=base_minutes)
        htf_close = htf_index_ + pd.Timedelta(minutes=htf_minutes)
        return np.searchsorted(htf_close.values, base_close.values, side="right") - 1

    def m1_slice(self, start_ts, end_ts):
        """Positional [lo, hi) range of M1 bars in [start_ts, end_ts]."""
        if self.m1_idx is None:
            return None
        lo = int(np.searchsorted(self.m1_ts, np.datetime64(start_ts.tz_localize(None)
                                                           if start_ts.tzinfo else start_ts), "left"))
        hi = int(np.searchsorted(self.m1_ts, np.datetime64(end_ts.tz_localize(None)
                                                           if end_ts.tzinfo else end_ts), "right"))
        return lo, hi

    def session_ok(self, ts):
        return any(a <= ts.hour < b for a, b in self.p.sessions)


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------
@dataclass
class SMCSignal:
    symbol: str
    direction: int
    m15_bar: int
    entry: float
    stop: float
    target: float
    score: int
    rr: float
    entry_tf: str                 # "M1" or "M15"
    entry_deadline: pd.Timestamp
    poi: tuple = None
    parts: dict = field(default_factory=dict)


def evaluate_smc(ctx: SMCContext, i: int):
    """Evaluate M15 bar `i` (already closed). Returns SMCSignal or None.

    Chain: H4 bias -> H1 POI touched and in discount/premium -> M15 CHoCH ->
    M1 micro-CHoCH + micro order block for the sniper entry.
    """
    p = ctx.p
    if i < 60:
        return None
    ts = ctx.m15.index[i]
    if not ctx.session_ok(ts):
        return None

    a15 = ctx.m15_atr[i]
    price = ctx.m15_c[i]
    if not np.isfinite(a15) or a15 <= 0 or price <= 0:
        return None
    atr_pct = a15 / price
    if atr_pct < p.min_atr_pct or atr_pct > p.max_atr_pct:
        return None
    if ctx.spread > p.max_spread_atr * a15:
        return None

    # ---- 1. H4 bias -----------------------------------------------------
    k4 = ctx.h4_pos[i]
    if k4 < 30:
        return None
    bias, h4_sh_i, h4_sl_i = structure_state(
        ctx.h4_h, ctx.h4_l, ctx.h4_c, ctx.h4_sh, ctx.h4_sl, k4)
    if bias == 0:
        return None
    direction = bias

    # ---- 2. H4 dealing range: premium / discount ------------------------
    lo4 = max(0, k4 - p.h4_lookback)
    rng_hi = ctx.h4_h[lo4:k4 + 1].max()
    rng_lo = ctx.h4_l[lo4:k4 + 1].min()
    if rng_hi <= rng_lo:
        return None
    pos_in_range = (price - rng_lo) / (rng_hi - rng_lo)
    if direction > 0 and pos_in_range > p.premium_discount:
        return None                       # only buy in discount
    if direction < 0 and pos_in_range < (1 - p.premium_discount):
        return None                       # only sell in premium

    # ---- 3. H1 point of interest ----------------------------------------
    k1 = ctx.h1_pos[i]
    if k1 < 40:
        return None
    pois = []
    if p.use_order_blocks:
        for idx, top, bot in order_blocks(ctx.h1_o, ctx.h1_h, ctx.h1_l, ctx.h1_c,
                                          ctx.h1_atr, direction, k1,
                                          lookback=p.poi_max_age):
            pois.append(("OB", idx, top, bot))
    if p.use_fvg:
        for idx, top, bot in fair_value_gaps(ctx.h1_h, ctx.h1_l, direction, k1,
                                             lookback=p.poi_max_age):
            pois.append(("FVG", idx, top, bot))
    if not pois:
        return None

    # price must be trading INTO the POI right now
    touched = None
    for kind, idx, top, bot in pois:
        if direction > 0 and ctx.m15_l[i] <= top and ctx.m15_c[i] >= bot:
            touched = (kind, idx, top, bot); break
        if direction < 0 and ctx.m15_h[i] >= bot and ctx.m15_c[i] <= top:
            touched = (kind, idx, top, bot); break
    if touched is None:
        return None
    poi_kind, poi_idx, poi_top, poi_bot = touched

    # ---- 3b. liquidity must be taken BEFORE the reversal ----------------
    # Core SMC: price raids a prior swing (stop-loss pool) and only then
    # reverses from the POI. Without this the chain fires on every ordinary
    # pullback into a zone, which is why the first build over-traded ~25x.
    if p.require_sweep:
        swept = _liquidity_swept(ctx, i, direction, p.sweep_lookback_m15,
                                 p.sweep_window_m15)
        if not swept:
            return None

    # ---- 4. M15 change of character, AFTER the POI touch ----------------
    # The confirmation has to be part of the reaction to the POI. Searching a
    # backward window could match a CHoCH that printed BEFORE price reached
    # the zone, which is not confirmation of anything.
    if p.require_m15_choch:
        touch_bar = _poi_touch_bar(ctx, i, direction, poi_top, poi_bot,
                                   p.m15_confirm_bars)
        if touch_bar is None:
            return None
        cc = choch(ctx.m15_h, ctx.m15_l, ctx.m15_c, ctx.m15_sh, ctx.m15_sl,
                   i, direction, window=max(1, i - touch_bar))
        if cc is None or cc < touch_bar:
            return None

    # ---- 5. M1 sniper entry ---------------------------------------------
    entry_tf = "M15"
    entry_px = price
    struct_low = ctx.m15_l[max(0, i - 6):i + 1].min()
    struct_high = ctx.m15_h[max(0, i - 6):i + 1].max()

    if p.use_m1 and ctx.m1_idx is not None:
        got = _m1_sniper(ctx, i, direction, p)
        if got is not None:
            entry_px, m1_low, m1_high, entry_tf = got
            if p.m1_stop_source == "m1":
                struct_low, struct_high = m1_low, m1_high
            # else: keep the M15 structural levels computed above, so the
            # precision of the entry is gained without a noise-width stop
        elif p.m1_entry_mode != "market":
            return None                    # sniper required but unavailable

    # ---- 6. stop / target ------------------------------------------------
    buf = max(p.sl_buffer_atr * a15, p.sl_min_pips * ctx.pip)
    if direction > 0:
        stop = struct_low - buf
        risk = entry_px - stop
    else:
        stop = struct_high + buf
        risk = stop - entry_px
    if risk <= 0:
        return None
    if risk < 1.5 * ctx.spread:
        return None
    target = entry_px + direction * p.tp_r * risk

    cost = ctx.spread + 0.3 * ctx.pip
    rr_net = (p.tp_r * risk - cost) / (risk + cost)
    if rr_net < p.min_rr:
        return None

    # ---- 7. score --------------------------------------------------------
    parts = {}
    parts["h4_bias"] = 20
    loc = (p.premium_discount - pos_in_range) if direction > 0 \
        else (pos_in_range - (1 - p.premium_discount))
    parts["location"] = round(18 * float(np.clip(loc / p.premium_discount, 0, 1)), 1)
    parts["poi"] = 14 if poi_kind == "OB" else 10
    parts["m15_choch"] = 12 if p.require_m15_choch else 6
    parts["sniper"] = 14 if entry_tf == "M1" else 5
    parts["rr"] = round(12 * float(np.clip((rr_net - p.min_rr) / 2.0, 0, 1)), 1)
    vol_n = float(np.clip((atr_pct - p.min_atr_pct) / (0.003 - p.min_atr_pct), 0, 1))
    parts["volatility"] = round(6 * vol_n, 1)
    parts["liquidity"] = round(4 * float(np.clip(1 - ctx.spread / (p.max_spread_atr * a15), 0, 1)), 1)
    score = int(round(sum(parts.values())))
    if score < p.min_score:
        return None

    deadline = ts + pd.Timedelta(minutes=15 * 8)
    return SMCSignal(symbol=ctx.symbol, direction=direction, m15_bar=i,
                     entry=float(entry_px), stop=float(stop), target=float(target),
                     score=score, rr=float(rr_net), entry_tf=entry_tf,
                     entry_deadline=deadline, poi=(poi_kind, poi_top, poi_bot),
                     parts=parts)


def _liquidity_swept(ctx, i, direction, lookback, window):
    """Did price raid the prior swing pool and close back inside, recently?"""
    for j in range(max(0, i - window), i + 1):
        a = max(0, j - lookback)
        if a >= j:
            continue
        if direction > 0:
            pool = ctx.m15_l[a:j].min()
            if ctx.m15_l[j] < pool and ctx.m15_c[j] > pool:
                return True
        else:
            pool = ctx.m15_h[a:j].max()
            if ctx.m15_h[j] > pool and ctx.m15_c[j] < pool:
                return True
    return False


def _poi_touch_bar(ctx, i, direction, top, bot, window):
    """Index of the most recent bar that traded into the POI."""
    for j in range(i, max(-1, i - window), -1):
        if direction > 0 and ctx.m15_l[j] <= top:
            return j
        if direction < 0 and ctx.m15_h[j] >= bot:
            return j
    return None


def _m1_sniper(ctx, i, direction, p):
    """Drill into M1 for the precision entry.

    Looks for a micro change of character inside the M15 bar's window, then
    places the entry at the micro order block (or FVG) that produced it. This
    is what shrinks the stop from ~M15 scale to ~M1 scale.

    Returns (entry_px, struct_low, struct_high, "M1") or None.
    """
    ts = ctx.m15.index[i]
    win = ctx.m1_slice(ts - pd.Timedelta(minutes=p.m1_window_bars), ts + pd.Timedelta(minutes=15))
    if win is None:
        return None
    lo, hi = win
    if hi - lo < 30:
        return None
    hi = min(hi, len(ctx.m1_c))
    upto = hi - 1

    cc = choch(ctx.m1_h, ctx.m1_l, ctx.m1_c, ctx.m1_sh, ctx.m1_sl,
               upto, direction, window=min(40, hi - lo))
    if cc is None or cc < lo:
        return None

    # The micro order block that CAUSED the change of character is the sniper
    # entry: the last opposing candle before the impulse that broke micro
    # structure. Entering at its edge -- rather than at the M1 close -- is what
    # makes the stop small enough for a wide target to be reachable.
    seg_start = max(lo, cc - p.m1_ob_lookback)
    ob_idx = None
    if direction > 0:
        for m in range(cc, seg_start, -1):
            if ctx.m1_c[m] < ctx.m1_o[m]:            # last down candle
                ob_idx = m
                break
    else:
        for m in range(cc, seg_start, -1):
            if ctx.m1_c[m] > ctx.m1_o[m]:            # last up candle
                ob_idx = m
                break
    if ob_idx is None:
        return None

    if direction > 0:
        entry_px = max(ctx.m1_o[ob_idx], ctx.m1_c[ob_idx])   # block top
        struct_low = ctx.m1_l[max(lo, ob_idx - 3):cc + 1].min()
        if entry_px <= struct_low:
            return None
        return float(entry_px), float(struct_low), float(ctx.m1_h[upto]), "M1"

    entry_px = min(ctx.m1_o[ob_idx], ctx.m1_c[ob_idx])       # block bottom
    struct_high = ctx.m1_h[max(lo, ob_idx - 3):cc + 1].max()
    if entry_px >= struct_high:
        return None
    return float(entry_px), float(ctx.m1_l[upto]), float(struct_high), "M1"
