"""
Candle series primitives — pure stdlib, no pandas/numpy dependency.

Everything downstream (SMC detection, grading, backtest) operates on a
`Series`: an immutable-ish, time-ascending list of `Bar`s for one timeframe.
Bars are UTC-epoch-seconds keyed and always represent CLOSED candles unless
the series is explicitly marked `has_forming_bar`.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable, Sequence

# Timeframe registry -------------------------------------------------------
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
TF_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

# XAUUSD conventions. A "pip" on gold is a 0.10 USD move; a "point" is 1.00 USD.
PIP = 0.10
POINT = 1.0


def tf_seconds(tf: str) -> int:
    return TF_MINUTES[tf] * 60


def to_pips(price_delta: float) -> float:
    return abs(price_delta) / PIP


def utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


@dataclass(frozen=True)
class Bar:
    ts: int          # epoch seconds, bar OPEN time, UTC
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.c - self.o)

    @property
    def range(self) -> float:
        return self.h - self.l

    @property
    def bullish(self) -> bool:
        return self.c > self.o

    @property
    def bearish(self) -> bool:
        return self.c < self.o

    @property
    def body_ratio(self) -> float:
        return self.body / self.range if self.range > 0 else 0.0

    @property
    def upper_wick(self) -> float:
        return self.h - max(self.o, self.c)

    @property
    def lower_wick(self) -> float:
        return min(self.o, self.c) - self.l

    def as_dict(self) -> dict:
        return {"ts": self.ts, "o": self.o, "h": self.h, "l": self.l, "c": self.c, "v": self.v}


class Series:
    """Time-ascending bars for a single timeframe."""

    __slots__ = ("tf", "bars", "source", "symbol", "has_forming_bar", "_ts")

    def __init__(self, tf: str, bars: Sequence[Bar], source: str = "", symbol: str = "",
                 has_forming_bar: bool = False):
        self.tf = tf
        self.bars = list(bars)
        self.source = source
        self.symbol = symbol
        self.has_forming_bar = has_forming_bar
        self._ts: list[int] | None = None

    @property
    def ts_index(self) -> list[int]:
        """Cached ascending bar-open timestamps — the backtest bisects this hard."""
        if self._ts is None or len(self._ts) != len(self.bars):
            self._ts = [b.ts for b in self.bars]
        return self._ts

    # -- container protocol ------------------------------------------------
    def __len__(self) -> int:
        return len(self.bars)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return Series(self.tf, self.bars[i], self.source, self.symbol)
        return self.bars[i]

    def __iter__(self):
        return iter(self.bars)

    def __repr__(self) -> str:
        return f"<Series {self.symbol} {self.tf} n={len(self.bars)} src={self.source}>"

    # -- accessors ---------------------------------------------------------
    @property
    def closed(self) -> "Series":
        """Drop the still-forming bar so structure logic never reads a partial candle."""
        if self.has_forming_bar and self.bars:
            return Series(self.tf, self.bars[:-1], self.source, self.symbol, False)
        return self

    @property
    def last(self) -> Bar | None:
        return self.bars[-1] if self.bars else None

    @property
    def closes(self) -> list[float]:
        return [b.c for b in self.bars]

    @property
    def highs(self) -> list[float]:
        return [b.h for b in self.bars]

    @property
    def lows(self) -> list[float]:
        return [b.l for b in self.bars]

    def tail(self, n: int) -> "Series":
        return Series(self.tf, self.bars[-n:], self.source, self.symbol, self.has_forming_bar)

    def before(self, ts: int) -> "Series":
        """All bars that had CLOSED strictly before `ts` — the backtest's anti-lookahead gate."""
        span = tf_seconds(self.tf)
        idx = bisect.bisect_left(self.ts_index, ts - span + 1)
        return Series(self.tf, self.bars[:idx], self.source, self.symbol, False)

    def age_seconds(self, now: float | None = None) -> float:
        """Seconds since the last bar's period should have ended."""
        if not self.bars:
            return float("inf")
        now = now if now is not None else datetime.now(tz=timezone.utc).timestamp()
        return now - (self.bars[-1].ts + tf_seconds(self.tf))

    def merge(self, other: "Series") -> "Series":
        """Merge newer bars in, de-duplicating by timestamp (newer wins)."""
        idx = {b.ts: b for b in self.bars}
        idx.update({b.ts: b for b in other.bars})
        bars = [idx[k] for k in sorted(idx)]
        return Series(self.tf, bars, other.source or self.source, self.symbol, other.has_forming_bar)


def make_series(tf: str, rows: Iterable[Sequence[float]], source: str = "", symbol: str = "",
                has_forming_bar: bool = False) -> Series:
    """Build a Series from (ts, o, h, l, c, v) rows, dropping malformed/None entries."""
    bars: list[Bar] = []
    for r in rows:
        try:
            ts, o, h, l, c = int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])
            v = float(r[5]) if len(r) > 5 and r[5] is not None else 0.0
        except (TypeError, ValueError, IndexError):
            continue
        if not all(x > 0 for x in (o, h, l, c)):
            continue
        if h < max(o, c) or l > min(o, c):        # incoherent OHLC -> drop
            continue
        bars.append(Bar(ts, o, h, l, c, v))
    bars.sort(key=lambda b: b.ts)
    dedup: list[Bar] = []
    for b in bars:
        if dedup and dedup[-1].ts == b.ts:
            dedup[-1] = b
        else:
            dedup.append(b)
    return Series(tf, dedup, source, symbol, has_forming_bar)


def resample(src: Series, tf: str) -> Series:
    """Aggregate a lower timeframe into a higher one (e.g. H1 -> H4) on UTC boundaries."""
    span = tf_seconds(tf)
    if span <= tf_seconds(src.tf):
        return src
    buckets: dict[int, list[Bar]] = {}
    for b in src.bars:
        buckets.setdefault(b.ts - (b.ts % span), []).append(b)
    out: list[Bar] = []
    for key in sorted(buckets):
        grp = buckets[key]
        out.append(Bar(key, grp[0].o, max(x.h for x in grp), min(x.l for x in grp),
                       grp[-1].c, sum(x.v for x in grp)))
    forming = src.has_forming_bar or (
        bool(out) and bool(src.bars) and src.bars[-1].ts + tf_seconds(src.tf) < out[-1].ts + span)
    return Series(tf, out, src.source, src.symbol, forming)


# -- indicators ------------------------------------------------------------
def true_ranges(bars: Sequence[Bar]) -> list[float]:
    out = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b.range)
        else:
            pc = bars[i - 1].c
            out.append(max(b.h - b.l, abs(b.h - pc), abs(b.l - pc)))
    return out


def atr(bars: Sequence[Bar], period: int = 14) -> float:
    """Wilder-smoothed ATR of the last `period` bars. 0.0 when there isn't enough data."""
    if len(bars) < period + 1:
        return 0.0
    tr = true_ranges(bars)
    val = sum(tr[1:period + 1]) / period
    for x in tr[period + 1:]:
        val = (val * (period - 1) + x) / period
    return val


def atr_series(bars: Sequence[Bar], period: int = 14) -> list[float]:
    """ATR at every index (0.0 until warm) — used by the backtest to avoid re-computing."""
    tr = true_ranges(bars)
    out = [0.0] * len(bars)
    if len(bars) < period + 1:
        return out
    val = sum(tr[1:period + 1]) / period
    out[period] = val
    for i in range(period + 1, len(bars)):
        val = (val * (period - 1) + tr[i]) / period
        out[i] = val
    return out


def ema(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def stdev(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return (sum((v - m) ** 2 for v in values) / (n - 1)) ** 0.5


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * max(0.0, min(1.0, pct))
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
