"""
Smart Money Concepts primitives.

Every function here is PURE: it takes closed bars and returns structure. No
network, no clock, no state. That is what makes the live engine and the
backtest run identical logic — the property the win-rate numbers depend on.

Vocabulary used consistently across the codebase:
  swing        fractal high/low confirmed `strength` bars later
  BOS          break of structure — continuation break in the prevailing trend
  CHoCH / MSS  change of character — the FIRST break against the prevailing
               trend; "MSS" is used when it happens on an execution timeframe
  sweep        price takes a liquidity pool and CLOSES back inside (stop hunt)
  displacement an impulsive leg whose body dwarfs ATR — the institutional print
  FVG          3-bar imbalance left behind by displacement
  OB           the last opposing candle before the displacement leg
  premium/     upper / lower half of the dealing range; equilibrium is the mid;
  discount     OTE is the 0.618-0.79 retracement "golden pocket"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .candles import Bar, atr, atr_series

# --------------------------------------------------------------------------
# Swings
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Swing:
    idx: int
    ts: int
    price: float
    kind: str            # "high" | "low"

    @property
    def confirmed_idx(self) -> int:
        return self.idx


def swings(bars: Sequence[Bar], strength: int = 2) -> list[Swing]:
    """Fractal swing points. A swing at i is only knowable at i+strength."""
    out: list[Swing] = []
    n = len(bars)
    for i in range(strength, n - strength):
        win = bars[i - strength:i + strength + 1]
        if bars[i].h == max(b.h for b in win) and bars[i].h > max(
                [b.h for b in win[:strength]] + [b.h for b in win[strength + 1:]] or [-1e18]):
            out.append(Swing(i, bars[i].ts, bars[i].h, "high"))
        if bars[i].l == min(b.l for b in win) and bars[i].l < min(
                [b.l for b in win[:strength]] + [b.l for b in win[strength + 1:]] or [1e18]):
            out.append(Swing(i, bars[i].ts, bars[i].l, "low"))
    out.sort(key=lambda s: (s.idx, s.kind))
    return out


# --------------------------------------------------------------------------
# Market structure: BOS / CHoCH
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class StructureEvent:
    kind: str            # "BOS" | "CHOCH"
    direction: str       # "bullish" | "bearish"
    level: float         # the swing level that was broken
    idx: int             # bar index whose CLOSE broke it
    ts: int
    displacement: float  # break-bar body in ATR units


@dataclass
class Structure:
    trend: str = "ranging"                 # bullish | bearish | ranging
    events: list[StructureEvent] = field(default_factory=list)
    swing_highs: list[Swing] = field(default_factory=list)
    swing_lows: list[Swing] = field(default_factory=list)
    ref_high: float | None = None          # live structural high to break for a bull BOS
    ref_low: float | None = None
    range_high: float = 0.0                # dealing range used for premium/discount
    range_low: float = 0.0
    range_high_ts: int = 0
    range_low_ts: int = 0

    @property
    def last_bos(self) -> StructureEvent | None:
        return next((e for e in reversed(self.events) if e.kind == "BOS"), None)

    @property
    def last_choch(self) -> StructureEvent | None:
        return next((e for e in reversed(self.events) if e.kind == "CHOCH"), None)

    @property
    def last_event(self) -> StructureEvent | None:
        return self.events[-1] if self.events else None

    def equilibrium(self) -> float:
        return (self.range_high + self.range_low) / 2.0


def analyze_structure(bars: Sequence[Bar], strength: int = 2) -> Structure:
    """
    Walk the bars forward, maintaining the live structural reference levels and
    emitting BOS / CHoCH as closes break them. Swings only become references
    once fractally confirmed, so this never peeks into the future.
    """
    st = Structure()
    n = len(bars)
    if n < strength * 2 + 3:
        return st
    a_series = atr_series(bars, 14)
    sw = swings(bars, strength)
    by_conf: dict[int, list[Swing]] = {}
    for s in sw:
        by_conf.setdefault(s.idx + strength, []).append(s)

    trend = "ranging"
    ref_high: Swing | None = None
    ref_low: Swing | None = None
    for i in range(n):
        for s in by_conf.get(i, []):               # newly confirmed swings
            if s.kind == "high":
                st.swing_highs.append(s)
                if ref_high is None or s.idx > ref_high.idx:
                    ref_high = s
            else:
                st.swing_lows.append(s)
                if ref_low is None or s.idx > ref_low.idx:
                    ref_low = s

        c = bars[i].c
        a = a_series[i] or 1e-9
        if ref_high is not None and c > ref_high.price and i > ref_high.idx:
            kind = "BOS" if trend == "bullish" else "CHOCH"
            st.events.append(StructureEvent(kind, "bullish", ref_high.price, i, bars[i].ts,
                                            bars[i].body / a))
            trend = "bullish"
            # the broken high stops being a reference; the low that produced the
            # leg becomes the level that would invalidate the new trend
            ref_low = max((s for s in st.swing_lows if s.idx <= i), key=lambda s: s.idx, default=ref_low)
            ref_high = None
        elif ref_low is not None and c < ref_low.price and i > ref_low.idx:
            kind = "BOS" if trend == "bearish" else "CHOCH"
            st.events.append(StructureEvent(kind, "bearish", ref_low.price, i, bars[i].ts,
                                            bars[i].body / a))
            trend = "bearish"
            ref_high = max((s for s in st.swing_highs if s.idx <= i), key=lambda s: s.idx, default=ref_high)
            ref_low = None

    st.trend = trend
    st.ref_high = ref_high.price if ref_high else (
        max((s.price for s in st.swing_highs), default=None))
    st.ref_low = ref_low.price if ref_low else (
        min((s.price for s in st.swing_lows), default=None))

    # Dealing range = the most recent opposing swing extremes (fallback: window).
    look = bars[-min(n, 120):]
    hi_sw = [s for s in st.swing_highs if s.idx >= n - 120]
    lo_sw = [s for s in st.swing_lows if s.idx >= n - 120]
    st.range_high = max((s.price for s in hi_sw), default=max(b.h for b in look))
    st.range_low = min((s.price for s in lo_sw), default=min(b.l for b in look))
    st.range_high_ts = next((s.ts for s in hi_sw if s.price == st.range_high), look[-1].ts)
    st.range_low_ts = next((s.ts for s in lo_sw if s.price == st.range_low), look[-1].ts)
    return st


# --------------------------------------------------------------------------
# Liquidity
# --------------------------------------------------------------------------
@dataclass
class LiquidityPool:
    price: float
    side: str            # "high" (buy-side liquidity) | "low" (sell-side liquidity)
    kind: str            # equal_highs | equal_lows | swing_high | swing_low | pdh | pdl | asia_high | asia_low
    strength: int        # 1 = single swing, 2+ = equal-level cluster / session level
    ts: int
    swept: bool = False
    swept_ts: int | None = None

    @property
    def label(self) -> str:
        return self.kind.upper()


def liquidity_pools(bars: Sequence[Bar], strength: int = 2, tolerance_atr: float = 0.10,
                    lookback: int = 150) -> list[LiquidityPool]:
    """Swing-derived pools, with equal highs/lows clustered into stronger pools."""
    win = list(bars[-lookback:])
    if len(win) < 20:
        return []
    a = atr(win, 14) or (win[-1].c * 0.001)
    tol = a * tolerance_atr
    sw = swings(win, strength)
    pools: list[LiquidityPool] = []

    for side, kind_single, kind_equal in (("high", "swing_high", "equal_highs"),
                                          ("low", "swing_low", "equal_lows")):
        pts = [s for s in sw if s.kind == side]
        used = [False] * len(pts)
        for i, s in enumerate(pts):
            if used[i]:
                continue
            cluster = [s]
            used[i] = True
            for j in range(i + 1, len(pts)):
                if not used[j] and abs(pts[j].price - s.price) <= tol:
                    cluster.append(pts[j])
                    used[j] = True
            price = (max(c.price for c in cluster) if side == "high"
                     else min(c.price for c in cluster))
            pools.append(LiquidityPool(
                price=price, side=side,
                kind=kind_equal if len(cluster) > 1 else kind_single,
                strength=len(cluster), ts=max(c.ts for c in cluster)))

    # Session / daily levels are the liquidity institutions actually target.
    for p in _session_levels(win):
        pools.append(p)

    # Mark pools already taken out (a pool traded through is spent liquidity).
    for p in pools:
        after = [b for b in win if b.ts > p.ts]
        for b in after:
            if (p.side == "high" and b.h > p.price) or (p.side == "low" and b.l < p.price):
                p.swept, p.swept_ts = True, b.ts
                break
    pools.sort(key=lambda p: (-p.strength, -p.ts))
    return pools


def _session_levels(bars: Sequence[Bar]) -> list[LiquidityPool]:
    """Prior-day high/low and the Asia-session range of the current day (UTC)."""
    from datetime import datetime, timezone
    out: list[LiquidityPool] = []
    by_day: dict[str, list[Bar]] = {}
    for b in bars:
        d = datetime.fromtimestamp(b.ts, tz=timezone.utc)
        by_day.setdefault(d.strftime("%Y-%m-%d"), []).append(b)
    days = sorted(by_day)
    span = (bars[1].ts - bars[0].ts) if len(bars) > 1 else 0
    full_day = (86400 // span) if span else 0
    if len(days) >= 2:
        prev = by_day[days[-2]]
        # A window holding only a slice of yesterday does not know yesterday's
        # high or low, and publishing that slice as PDH/PDL would be a lie.
        if full_day and len(prev) >= full_day * 0.5:
            out.append(LiquidityPool(max(b.h for b in prev), "high", "pdh", 3, prev[-1].ts))
            out.append(LiquidityPool(min(b.l for b in prev), "low", "pdl", 3, prev[-1].ts))
    today = by_day[days[-1]] if days else []
    asia = [b for b in today if 0 <= datetime.fromtimestamp(b.ts, tz=timezone.utc).hour < 7]
    if len(asia) >= 4:
        out.append(LiquidityPool(max(b.h for b in asia), "high", "asia_high", 2, asia[-1].ts))
        out.append(LiquidityPool(min(b.l for b in asia), "low", "asia_low", 2, asia[-1].ts))
    return out


@dataclass
class Sweep:
    idx: int
    ts: int
    direction: str        # "bullish" = sell-side swept -> expect up; "bearish" = buy-side swept
    extreme: float        # the wick extreme of the sweep bar (SL reference)
    pool: LiquidityPool | None
    displacement_back: float   # how far the bar closed back inside, in ATR


def detect_sweep(bars: Sequence[Bar], pools: Sequence[LiquidityPool], idx: int,
                 a: float, min_reject: float = 0.20) -> Sweep | None:
    """
    Bar `idx` sweeps a pool when its WICK trades through the level and its BODY
    closes back on the origin side — the signature of a stop hunt rather than a
    genuine break. Falls back to an N-bar extreme when no named pool is nearby.
    """
    b = bars[idx]
    if a <= 0:
        return None
    best: Sweep | None = None
    for p in pools:
        if p.ts >= b.ts:
            continue
        if p.side == "low" and b.l < p.price and b.c > p.price:
            back = (b.c - p.price) / a
            if back >= min_reject and (best is None or p.strength > (best.pool.strength if best.pool else 0)):
                best = Sweep(idx, b.ts, "bullish", b.l, p, back)
        elif p.side == "high" and b.h > p.price and b.c < p.price:
            back = (p.price - b.c) / a
            if back >= min_reject and (best is None or p.strength > (best.pool.strength if best.pool else 0)):
                best = Sweep(idx, b.ts, "bearish", b.h, p, back)
    if best is not None:
        return best

    lb = 20
    if idx < lb + 1:
        return None
    prior = bars[idx - lb:idx]
    lo, hi = min(x.l for x in prior), max(x.h for x in prior)
    if b.l < lo and b.c > lo and (b.c - lo) / a >= min_reject:
        return Sweep(idx, b.ts, "bullish", b.l, None, (b.c - lo) / a)
    if b.h > hi and b.c < hi and (hi - b.c) / a >= min_reject:
        return Sweep(idx, b.ts, "bearish", b.h, None, (hi - b.c) / a)
    return None


# --------------------------------------------------------------------------
# Imbalance: FVG + order blocks + displacement
# --------------------------------------------------------------------------
@dataclass
class FVG:
    top: float
    bottom: float
    idx: int             # index of the 3rd bar
    ts: int
    direction: str       # "bullish" | "bearish"
    filled_pct: float = 0.0

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def size(self) -> float:
        return self.top - self.bottom

    @property
    def mitigated(self) -> bool:
        return self.filled_pct >= 0.999

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


def fair_value_gaps(bars: Sequence[Bar], lookback: int = 80, min_size_atr: float = 0.15) -> list[FVG]:
    """3-bar imbalances, each annotated with how much has since been filled."""
    n = len(bars)
    if n < 5:
        return []
    a = atr(bars[-60:] if n >= 60 else bars, 14) or 1e-9
    out: list[FVG] = []
    start = max(2, n - lookback)
    for i in range(start, n):
        b0, b2 = bars[i - 2], bars[i]
        if b2.l > b0.h:                                  # bullish imbalance
            g = FVG(b2.l, b0.h, i, b2.ts, "bullish")
        elif b2.h < b0.l:                                # bearish imbalance
            g = FVG(b0.l, b2.h, i, b2.ts, "bearish")
        else:
            continue
        if g.size < min_size_atr * a:
            continue
        # fill accounting from subsequent bars
        for b in bars[i + 1:]:
            if g.direction == "bullish":
                pen = max(0.0, g.top - b.l)
            else:
                pen = max(0.0, b.h - g.bottom)
            g.filled_pct = max(g.filled_pct, min(1.0, pen / g.size if g.size else 1.0))
            if g.filled_pct >= 0.999:
                break
        out.append(g)
    return out


@dataclass
class OrderBlock:
    top: float
    bottom: float
    idx: int
    ts: int
    direction: str       # "bullish" (demand) | "bearish" (supply)
    impulse_atr: float
    mitigated: bool = False

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


def order_blocks(bars: Sequence[Bar], lookback: int = 80, disp_mult: float = 1.0) -> list[OrderBlock]:
    """
    The last opposing candle before a displacement leg. Only displacement legs
    (body >= disp_mult x ATR) qualify — a random red candle is not an order block.
    """
    n = len(bars)
    if n < 10:
        return []
    a_s = atr_series(bars, 14)
    out: list[OrderBlock] = []
    for i in range(max(3, n - lookback), n):
        a = a_s[i]
        if a <= 0:
            continue
        b = bars[i]
        if b.body < disp_mult * a:
            continue
        if b.bullish:
            j = next((k for k in range(i - 1, max(-1, i - 6), -1) if bars[k].bearish), None)
            if j is None:
                continue
            ob = OrderBlock(max(bars[j].o, bars[j].c), bars[j].l, j, bars[j].ts, "bullish", b.body / a)
        else:
            j = next((k for k in range(i - 1, max(-1, i - 6), -1) if bars[k].bullish), None)
            if j is None:
                continue
            ob = OrderBlock(bars[j].h, min(bars[j].o, bars[j].c), j, bars[j].ts, "bearish", b.body / a)
        for nb in bars[i + 1:]:
            if ob.direction == "bullish" and nb.l <= ob.top:
                ob.mitigated = True
                break
            if ob.direction == "bearish" and nb.h >= ob.bottom:
                ob.mitigated = True
                break
        out.append(ob)
    return out


@dataclass
class Displacement:
    idx: int
    ts: int
    direction: str
    size_atr: float
    body_ratio: float
    leg_low: float
    leg_high: float


def find_displacement(bars: Sequence[Bar], start: int, end: int, direction: str,
                      a: float, mult: float = 1.0, min_body_ratio: float = 0.5) -> Displacement | None:
    """The strongest qualifying impulse bar in [start, end) moving `direction`."""
    best: Displacement | None = None
    for i in range(max(1, start), min(end, len(bars))):
        b = bars[i]
        if a <= 0 or b.range <= 0:
            continue
        if direction == "bullish" and not b.bullish:
            continue
        if direction == "bearish" and not b.bearish:
            continue
        size = b.body / a
        if size < mult or b.body_ratio < min_body_ratio:
            continue
        if best is None or size > best.size_atr:
            best = Displacement(i, b.ts, direction, size, b.body_ratio, b.l, b.h)
    return best


# --------------------------------------------------------------------------
# Premium / discount / OTE
# --------------------------------------------------------------------------
@dataclass
class PremiumDiscount:
    high: float
    low: float
    price: float

    @property
    def equilibrium(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def span(self) -> float:
        return max(1e-9, self.high - self.low)

    @property
    def position(self) -> float:
        """0.0 at range low, 1.0 at range high."""
        return max(0.0, min(1.0, (self.price - self.low) / self.span))

    @property
    def zone(self) -> str:
        p = self.position
        if p >= 0.62:
            return "PREMIUM"
        if p <= 0.38:
            return "DISCOUNT"
        return "EQUILIBRIUM"

    def ote(self, direction: str) -> tuple[float, float]:
        """Optimal-trade-entry band (0.618-0.79 retrace) for the given direction."""
        if direction == "bullish":                    # retracing down into discount
            return (self.high - 0.79 * self.span, self.high - 0.618 * self.span)
        return (self.low + 0.618 * self.span, self.low + 0.79 * self.span)

    def in_ote(self, direction: str, price: float | None = None) -> bool:
        lo, hi = self.ote(direction)
        p = self.price if price is None else price
        return lo <= p <= hi

    def favourable(self, direction: str) -> bool:
        """Buys want discount, sells want premium."""
        return (direction == "bullish" and self.position <= 0.5) or \
               (direction == "bearish" and self.position >= 0.5)


def premium_discount(structure: Structure, price: float) -> PremiumDiscount:
    return PremiumDiscount(structure.range_high, structure.range_low, price)
