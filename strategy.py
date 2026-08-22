"""
High-probability multi-timeframe strategy: liquidity sweep -> market-structure
shift -> confirmation, gated by a 0-100 trade-quality score.

Everything here is pure pandas/numpy over OHLC frames so the identical code
path drives both the backtest and the live bot. There is no broker dependency.

NO LOOK-AHEAD CONTRACT
----------------------
A signal for M15 bar `i` may read bars 0..i only, and only higher-timeframe
bars that had already CLOSED by the close of bar i. `htf_index()` enforces the
second half of that; the backtester fills the resulting order at the OPEN of
bar i+1. Nothing in this module ever indexes past `i`.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Market metadata
# ---------------------------------------------------------------------------
PIP = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "USDSGD": 0.0001, "EURGBP": 0.0001,
    "EURAUD": 0.0001, "GBPAUD": 0.0001, "EURCAD": 0.0001, "EURCHF": 0.0001,
    "GBPCAD": 0.0001, "GBPCHF": 0.0001, "AUDCAD": 0.0001, "AUDNZD": 0.0001,
    "USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01, "AUDJPY": 0.01,
    "CHFJPY": 0.01, "CADJPY": 0.01, "NZDJPY": 0.01,
    "XAUUSD": 0.1,
}

CONTRACT = {s: 100_000.0 for s in PIP}
CONTRACT["XAUUSD"] = 100.0          # 100 oz per standard lot

# Quote currency drives the USD conversion of P&L.
QUOTE = {
    "EURUSD": "USD", "GBPUSD": "USD", "AUDUSD": "USD", "NZDUSD": "USD",
    "XAUUSD": "USD", "USDJPY": "JPY", "USDCAD": "CAD", "USDCHF": "CHF",
    "USDSGD": "SGD", "EURGBP": "GBP", "EURAUD": "AUD", "GBPAUD": "AUD",
    "AUDNZD": "NZD", "EURCAD": "CAD", "GBPCAD": "CAD", "AUDCAD": "CAD",
    "EURCHF": "CHF", "GBPCHF": "CHF", "EURJPY": "JPY", "GBPJPY": "JPY",
    "AUDJPY": "JPY", "CHFJPY": "JPY", "CADJPY": "JPY", "NZDJPY": "JPY",
}

BASE = {s: s[:3] for s in PIP}
BASE["XAUUSD"] = "XAU"

# Conservative retail spreads in PIPS for the PULSE-style feed. Deliberately
# set at or above typical quoted spreads so the backtest is not flattered.
SPREAD_PIPS = {
    "EURUSD": 0.9, "GBPUSD": 1.1, "USDJPY": 1.0, "AUDUSD": 1.1,
    "USDCAD": 1.3, "USDCHF": 1.3, "NZDUSD": 1.6, "EURGBP": 1.3,
    "EURJPY": 1.5, "GBPJPY": 2.2, "AUDJPY": 1.8, "CHFJPY": 2.4,
    "CADJPY": 2.0, "NZDJPY": 2.2, "EURAUD": 2.0, "GBPAUD": 2.8,
    "EURCAD": 2.0, "EURCHF": 1.8, "GBPCAD": 2.8, "GBPCHF": 2.8,
    "AUDCAD": 2.0, "AUDNZD": 2.4, "USDSGD": 2.2, "XAUUSD": 3.0,
}

COMMISSION_PER_LOT = 7.0        # USD, round turn, per standard lot
SLIPPAGE_PIPS = 0.3             # entry slippage, always adverse
STOP_SLIPPAGE_PIPS = 0.6        # extra adverse slippage when a stop triggers


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Signal timeframe -> (resample rule, context rules, minutes).
# Higher signal timeframes carry much lower cost drag: the round-trip cost is
# ~14% of the stop at M15, ~4% at H1, ~2% at H4.
TF_PRESETS = {
    15:  dict(rule="15min", mid="1h",  high="4h", bias="1D",
              mid_m=60,   high_m=240,  bias_m=1440),
    60:  dict(rule="1h",    mid="4h",  high="1D", bias="1W",
              mid_m=240,  high_m=1440, bias_m=10080),
    240: dict(rule="4h",    mid="1D",  high="1W", bias="1W",
              mid_m=1440, high_m=10080, bias_m=10080),
}


@dataclass
class Params:
    # --- signal timeframe ---
    tf_minutes: int = 15

    # --- structure / trigger ---
    sweep_lookback: int = 20        # bars defining the liquidity pool
    confirm_bars: int = 6           # bars allowed for the reclaim + MSS
    mss_ref: int = 3                # pre-sweep bars whose extreme MSS must break
    disp_body_atr: float = 0.45     # displacement body as multiple of ATR
    atr_period: int = 14

    # --- entry ---
    # "market"  : fill at the open after the confirmation bar
    # "retrace" : rest a limit order back inside the displacement leg. Costs
    #             some fills, but puts entry far closer to the stop, which is
    #             what actually decides whether a target is reachable.
    entry_mode: str = "retrace"
    retr_frac: float = 0.5          # fraction of the displacement leg retraced
    entry_expiry: int = 8           # bars the limit order stays live

    # --- stop / target ---
    sl_atr_buffer: float = 1.0      # stop sits this far beyond the sweep wick
    tp_r: float = 2.0               # final target in R
    tp1_r: float = 1.0              # partial target in R
    tp1_frac: float = 0.5           # fraction closed at TP1
    breakeven_after_tp1: bool = True
    time_stop_bars: int = 64        # 16 hours on M15

    # --- location / regime gates ---
    range_lookback: int = 40
    max_entry_zone: float = 0.45    # buys must sit in the lower 45% of range
    max_extension_atr: float = 1.6  # distance from EMA20 in ATR
    min_atr_pct: float = 0.00025    # dead-market floor (ATR / price)
    max_atr_pct: float = 0.0125     # blow-off ceiling
    min_rr_after_costs: float = 1.5
    max_spread_atr: float = 0.45    # skip when the spread eats the stop

    # A liquidity sweep is a counter-trend event at the local scale, so
    # forcing agreement with the daily trend may be filtering out the very
    # reversals the logic exists to catch. Made optional so it can be tested.
    require_bias: bool = True

    # Cost-efficiency gate: the score component most correlated with outcome
    # was "spread small relative to ATR". Tightening it is a real lever.
    max_spread_atr_hard: float = 0.45

    # --- exits ---
    # After `trail_start_r` of profit, trail the stop by `trail_atr` * ATR.
    # 0 disables trailing (fixed target only).
    trail_atr: float = 0.0
    trail_start_r: float = 0.0

    # --- score ---
    min_score: int = 70

    # --- sessions (UTC hours, entry bar open) ---
    sessions: tuple = ((7, 11), (12, 16))


def default_params():
    return Params()


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def ema(s, period):
    return s.ewm(span=period, adjust=False).mean()


def rsi(s, period=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def swing_points(df, left=2, right=2):
    """Fractal swing highs/lows. `right` bars of lag are inherent — a swing is
    only confirmed `right` bars after it prints, which the callers respect."""
    h, l = df["high"].values, df["low"].values
    n = len(h)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        w_h = h[i - left:i + right + 1]
        w_l = l[i - left:i + right + 1]
        if h[i] == w_h.max() and (w_h.argmax() == left):
            sh[i] = True
        if l[i] == w_l.min() and (w_l.argmin() == left):
            sl[i] = True
    return sh, sl


# ---------------------------------------------------------------------------
# Higher-timeframe alignment without look-ahead
# ---------------------------------------------------------------------------
def resample(df, rule):
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    return out.dropna()


def htf_index(m15_index, htf_frame, rule_minutes, sig_minutes=15):
    """For every M15 bar, the positional index of the last HTF bar that had
    already closed by the time that M15 bar closed. -1 where none exists.

    This is the single mechanism preventing higher-timeframe look-ahead: an
    H4 bar stamped 08:00 does not become visible until 12:00.
    """
    m15_close = m15_index + pd.Timedelta(minutes=sig_minutes)
    htf_close = htf_frame.index + pd.Timedelta(minutes=rule_minutes)
    # searchsorted 'right' => count of HTF bars whose close <= this M15 close
    pos = np.searchsorted(htf_close.values, m15_close.values, side="right") - 1
    return pos


class Context:
    """Pre-computes every series the signal function needs for one symbol."""

    def __init__(self, symbol, m15, p: Params):
        self.symbol = symbol
        self.p = p
        preset = TF_PRESETS[p.tf_minutes]
        self.preset = preset
        # `m15` is always the raw M15 feed; the signal frame is derived from it
        # so that every timeframe shares one source of truth.
        m15 = m15 if p.tf_minutes == 15 else resample(m15, preset["rule"])
        self.m15 = m15
        self.idx = m15.index
        self.tf_minutes = p.tf_minutes

        self.o = m15["open"].values
        self.h = m15["high"].values
        self.l = m15["low"].values
        self.c = m15["close"].values

        self.atr15 = atr(m15, p.atr_period).values
        self.ema20 = ema(m15["close"], 20).values
        self.rsi15 = rsi(m15["close"], 14).values

        # rolling pools/ranges, shifted so bar i never sees itself
        self.pool_hi = m15["high"].rolling(p.sweep_lookback).max().shift(1).values
        self.pool_lo = m15["low"].rolling(p.sweep_lookback).min().shift(1).values
        self.rng_hi = m15["high"].rolling(p.range_lookback).max().shift(1).values
        self.rng_lo = m15["low"].rolling(p.range_lookback).min().shift(1).values

        # ---- context timeframes (relative to the signal timeframe) ----
        h1 = resample(m15, preset["mid"])
        h4 = resample(m15, preset["high"])
        d1 = resample(m15, preset["bias"])

        self.h1 = h1
        self.h4 = h4
        self.d1 = d1

        self.h1_pos = htf_index(self.idx, h1, preset["mid_m"], p.tf_minutes)
        self.h4_pos = htf_index(self.idx, h4, preset["high_m"], p.tf_minutes)
        self.d1_pos = htf_index(self.idx, d1, preset["bias_m"], p.tf_minutes)

        self.d1_ema50 = ema(d1["close"], 50).values
        self.d1_ema200 = ema(d1["close"], 200).values
        self.d1_close = d1["close"].values

        self.h4_ema20 = ema(h4["close"], 20).values
        self.h4_ema50 = ema(h4["close"], 50).values
        self.h4_close = h4["close"].values
        self.h4_sh, self.h4_sl = swing_points(h4, 2, 2)
        self.h4_high = h4["high"].values
        self.h4_low = h4["low"].values

        self.h1_high = h1["high"].values
        self.h1_low = h1["low"].values
        self.h1_close = h1["close"].values
        self.h1_ema50 = ema(h1["close"], 50).values

        # A weekly bias frame will never accumulate 200 bars, so the warmup
        # requirement is capped at what the frame can actually supply.
        self.bias_warmup = min(200, max(50, len(d1) // 3))

        self.pip = PIP[symbol]
        self.spread = SPREAD_PIPS[symbol] * self.pip

    # -- higher-timeframe reads (all guarded by the *_pos mapping) ----------
    def d1_bias(self, i):
        k = self.d1_pos[i]
        if k < self.bias_warmup:
            return 0
        c, e50, e200 = self.d1_close[k], self.d1_ema50[k], self.d1_ema200[k]
        if c > e50 > e200:
            return 1
        if c < e50 < e200:
            return -1
        if c > e200 and c > e50:
            return 1
        if c < e200 and c < e50:
            return -1
        return 0

    def h4_bias(self, i):
        k = self.h4_pos[i]
        if k < 50:
            return 0
        c, e20, e50 = self.h4_close[k], self.h4_ema20[k], self.h4_ema50[k]
        if c > e20 and e20 > e50:
            return 1
        if c < e20 and e20 < e50:
            return -1
        return 0

    def h4_structure(self, i):
        """+1 higher-high & higher-low, -1 lower-high & lower-low, else 0.
        Uses only swings confirmed at or before the visible H4 bar."""
        k = self.h4_pos[i]
        if k < 12:
            return 0
        lim = k - 2                      # fractal confirmation lag
        highs = np.flatnonzero(self.h4_sh[:lim + 1])
        lows = np.flatnonzero(self.h4_sl[:lim + 1])
        if len(highs) < 2 or len(lows) < 2:
            return 0
        hh = self.h4_high[highs[-1]] > self.h4_high[highs[-2]]
        hl = self.h4_low[lows[-1]] > self.h4_low[lows[-2]]
        lh = self.h4_high[highs[-1]] < self.h4_high[highs[-2]]
        ll = self.h4_low[lows[-1]] < self.h4_low[lows[-2]]
        if hh and hl:
            return 1
        if lh and ll:
            return -1
        return 0

    def h1_zone(self, i, direction):
        """Where price sits inside the visible H1 range: 0 = low, 1 = high."""
        k = self.h1_pos[i]
        if k < 24:
            return None
        w = slice(max(0, k - 23), k + 1)
        hi = self.h1_high[w].max()
        lo = self.h1_low[w].min()
        if hi <= lo:
            return None
        return float((self.c[i] - lo) / (hi - lo))

    def session_ok(self, i):
        hour = self.idx[i].hour
        return any(a <= hour < b for a, b in self.p.sessions)

    def session_quality(self, i):
        """London/NY overlap is the deepest book; score it highest."""
        hour = self.idx[i].hour
        if 12 <= hour < 16:
            return 1.0
        if 7 <= hour < 11:
            return 0.85
        return 0.0


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    symbol: str
    direction: int                  # +1 long, -1 short
    bar: int                        # index of the CONFIRMATION bar
    entry_ref: float                # close of confirmation bar (fill is next open)
    stop: float
    target: float
    tp1: float
    score: int
    rr: float
    parts: dict = field(default_factory=dict)


def _find_sweep(ctx, i, direction):
    """Was there a liquidity sweep in the last `confirm_bars` bars that price
    has since reclaimed? Returns (sweep_bar, sweep_extreme) or None."""
    p = ctx.p
    for back in range(p.confirm_bars, -1, -1):
        j = i - back
        if j < p.sweep_lookback + p.mss_ref:
            continue
        if direction > 0:
            pool = ctx.pool_lo[j]
            if np.isnan(pool):
                continue
            # wick below the pool, body closing back above it
            if ctx.l[j] < pool and ctx.c[j] > pool:
                lo = ctx.l[j:i + 1].min()
                return j, float(lo)
        else:
            pool = ctx.pool_hi[j]
            if np.isnan(pool):
                continue
            if ctx.h[j] > pool and ctx.c[j] < pool:
                hi = ctx.h[j:i + 1].max()
                return j, float(hi)
    return None


def evaluate(ctx: Context, i: int):
    """Evaluate M15 bar `i` (already closed). Returns a Signal or None."""
    p = ctx.p
    if i < max(p.range_lookback, p.sweep_lookback) + p.atr_period + 5:
        return None
    if not ctx.session_ok(i):
        return None

    a = ctx.atr15[i]
    price = ctx.c[i]
    if not np.isfinite(a) or a <= 0 or price <= 0:
        return None

    # --- volatility regime gate -------------------------------------------
    atr_pct = a / price
    if atr_pct < p.min_atr_pct or atr_pct > p.max_atr_pct:
        return None

    # --- spread sanity: never trade when the stop is small vs the spread ---
    if ctx.spread > min(p.max_spread_atr, p.max_spread_atr_hard) * a:
        return None

    d1b = ctx.d1_bias(i)
    h4b = ctx.h4_bias(i)
    h4s = ctx.h4_structure(i)

    if p.require_bias:
        if d1b == 0:
            return None
        direction = d1b
        if h4b != 0 and h4b != direction:
            return None
        found = _find_sweep(ctx, i, direction)
        if not found:
            return None
        sweep_bar, sweep_ext = found
    else:
        # No trend filter: take whichever side actually swept and reclaimed.
        found = None
        for cand in (1, -1):
            found = _find_sweep(ctx, i, cand)
            if found:
                direction = cand
                break
        if not found:
            return None
        sweep_bar, sweep_ext = found

    # --- market-structure shift: bar i closes past the pre-sweep extreme ---
    ref_a = max(0, sweep_bar - p.mss_ref)
    if direction > 0:
        mss_level = ctx.h[ref_a:sweep_bar].max() if sweep_bar > ref_a else ctx.h[sweep_bar]
        if not (ctx.c[i] > mss_level):
            return None
    else:
        mss_level = ctx.l[ref_a:sweep_bar].min() if sweep_bar > ref_a else ctx.l[sweep_bar]
        if not (ctx.c[i] < mss_level):
            return None

    # --- displacement: the confirming bar must actually move -------------
    body = abs(ctx.c[i] - ctx.o[i])
    if body < p.disp_body_atr * a:
        return None
    if direction > 0 and ctx.c[i] <= ctx.o[i]:
        return None
    if direction < 0 and ctx.c[i] >= ctx.o[i]:
        return None

    # --- location inside the M15 range ------------------------------------
    # Measured at the SWEEP extreme, not at the confirmation bar. The sweep is
    # where liquidity was taken; the confirmation bar has by construction
    # already displaced away from it, so scoring location there would reject
    # exactly the setups the logic is built to find.
    rhi, rlo = ctx.rng_hi[sweep_bar], ctx.rng_lo[sweep_bar]
    if not np.isfinite(rhi) or not np.isfinite(rlo) or rhi <= rlo:
        return None
    zone = (sweep_ext - rlo) / (rhi - rlo)
    if direction > 0 and zone > p.max_entry_zone:
        return None
    if direction < 0 and zone < (1.0 - p.max_entry_zone):
        return None

    # --- not over-extended from the mean ----------------------------------
    ext = abs(price - ctx.ema20[i]) / a
    if ext > p.max_extension_atr:
        return None

    # --- entry level ------------------------------------------------------
    # The displacement leg runs from the sweep extreme to the extreme of the
    # confirmation bar. A retrace entry rests a limit inside that leg, which
    # puts the fill far closer to the stop than the displacement close does.
    if direction > 0:
        leg_end = ctx.h[sweep_bar:i + 1].max()
        leg = leg_end - sweep_ext
        entry_px = (leg_end - p.retr_frac * leg) if p.entry_mode == "retrace" else price
    else:
        leg_end = ctx.l[sweep_bar:i + 1].min()
        leg = sweep_ext - leg_end
        entry_px = (leg_end + p.retr_frac * leg) if p.entry_mode == "retrace" else price
    if leg <= 0:
        return None

    # --- stop / target ----------------------------------------------------
    if direction > 0:
        stop = sweep_ext - p.sl_atr_buffer * a
        risk = entry_px - stop
    else:
        stop = sweep_ext + p.sl_atr_buffer * a
        risk = stop - entry_px
    if risk <= 0:
        return None
    # a stop tighter than ~1.2x spread is noise, not a stop
    if risk < 1.2 * ctx.spread + 2 * ctx.pip:
        return None

    target = entry_px + direction * p.tp_r * risk
    tp1 = entry_px + direction * p.tp1_r * risk

    # R:R measured AFTER costs, using the same numbers the fill will use
    cost = ctx.spread + SLIPPAGE_PIPS * ctx.pip
    rr_net = (p.tp_r * risk - cost) / (risk + cost)
    if rr_net < p.min_rr_after_costs:
        return None

    # ---------------------------------------------------------------------
    # Trade-quality score, 0-100
    # ---------------------------------------------------------------------
    parts = {}

    # 1. higher-timeframe trend (15)
    parts["d1_trend"] = 15 if d1b == direction else (7 if d1b == 0 else 0)

    # 2. H4 momentum + structure agreement (12)
    s = 0
    if h4b == direction:
        s += 7
    if h4s == direction:
        s += 5
    elif h4s == 0:
        s += 2
    parts["h4"] = s

    # 3. entry location, M15 + H1 (14)
    loc = (p.max_entry_zone - zone) if direction > 0 else (zone - (1 - p.max_entry_zone))
    loc_n = float(np.clip(loc / p.max_entry_zone, 0, 1))
    s = 6 * loc_n
    hz = ctx.h1_zone(i, direction)
    if hz is not None:
        good = (1 - hz) if direction > 0 else hz
        s += 8 * float(np.clip((good - 0.4) / 0.5, 0, 1))
    parts["location"] = round(s, 1)

    # 4. sweep quality (13) - depth of the raid and cleanliness of the reclaim
    pool = ctx.pool_lo[sweep_bar] if direction > 0 else ctx.pool_hi[sweep_bar]
    depth = abs(pool - sweep_ext) / a
    depth_n = float(np.clip(depth / 0.8, 0, 1))
    sb_rng = ctx.h[sweep_bar] - ctx.l[sweep_bar]
    if sb_rng > 0:
        wick = ((ctx.c[sweep_bar] - ctx.l[sweep_bar]) / sb_rng if direction > 0
                else (ctx.h[sweep_bar] - ctx.c[sweep_bar]) / sb_rng)
    else:
        wick = 0.5
    parts["sweep"] = round(7 * depth_n + 6 * float(np.clip((wick - 0.5) / 0.4, 0, 1)), 1)

    # 5. displacement / momentum (13)
    disp_n = float(np.clip((body / a - p.disp_body_atr) / 0.9, 0, 1))
    r = ctx.rsi15[i]
    mom = (r - 50) / 25 if direction > 0 else (50 - r) / 25
    parts["momentum"] = round(8 * disp_n + 5 * float(np.clip(mom, 0, 1)), 1)

    # 6. volatility regime (8) - reward the middle of the band
    lo_b, hi_b = 0.0006, 0.0045
    if atr_pct <= lo_b:
        vol_n = atr_pct / lo_b
    elif atr_pct <= hi_b:
        vol_n = 1.0
    else:
        vol_n = float(np.clip(1 - (atr_pct - hi_b) / hi_b, 0, 1))
    parts["volatility"] = round(8 * vol_n, 1)

    # 7. risk-to-reward headroom (12) - is the target reachable inside the range?
    room = ((rhi - entry_px) / (p.tp_r * risk) if direction > 0
            else (entry_px - rlo) / (p.tp_r * risk))
    parts["rr"] = round(6 * float(np.clip((rr_net - p.min_rr_after_costs) / 0.8, 0, 1))
                        + 6 * float(np.clip(room, 0, 1)), 1)

    # 8. liquidity / spread conditions (10)
    parts["liquidity"] = round(10 * float(np.clip(1 - (ctx.spread / (p.max_spread_atr * a)), 0, 1)), 1)

    # 9. session quality (13)
    parts["session"] = round(13 * ctx.session_quality(i), 1)

    score = int(round(sum(parts.values())))
    if score < p.min_score:
        return None

    return Signal(symbol=ctx.symbol, direction=direction, bar=i,
                  entry_ref=float(entry_px), stop=float(stop), target=float(target),
                  tp1=float(tp1), score=score, rr=float(rr_net), parts=parts)
