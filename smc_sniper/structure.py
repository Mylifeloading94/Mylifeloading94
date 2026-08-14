"""Phase 1 -- Market structure.

Swing detection (fractals), HH/HL/LH/LL labelling, and the three structural
events the strategy cares about:

* **BOS**  (Break Of Structure)   -- continuation: price closes beyond the last
  swing *in the direction of the existing trend*.
* **CHoCH** (Change of Character) -- the first break against the prevailing
  trend. A warning, not yet a trend.
* **MSS**  (Market Structure Shift) -- a CHoCH that is *backed by displacement*.
  This is the only structural event allowed to flip the directional bias.

Nothing here looks forward: a swing at index ``i`` is only *confirmed* at
``i + lookback`` and every function takes that confirmation lag into account.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

Direction = Literal["bullish", "bearish", "neutral"]


@dataclass
class Swing:
    index: int          # bar index where the extreme printed
    confirmed_at: int   # bar index at which it became knowable
    price: float
    kind: Literal["high", "low"]
    label: str = ""     # HH / HL / LH / LL


@dataclass
class StructureEvent:
    index: int
    kind: Literal["BOS", "CHoCH", "MSS"]
    direction: Direction
    broken_swing: Swing
    displacement: bool = False


@dataclass
class StructureState:
    swings: list[Swing] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    bias: Direction = "neutral"
    last_event: StructureEvent | None = None
    leg_high: float | None = None   # current structural leg, for premium/discount
    leg_low: float | None = None

    def recent_events(self, index: int, within: int) -> list[StructureEvent]:
        return [e for e in self.events if 0 <= index - e.index <= within]

    def last_swing(self, kind: str) -> Swing | None:
        for swing in reversed(self.swings):
            if swing.kind == kind:
                return swing
        return None

    def swings_before(self, index: int, kind: str | None = None) -> list[Swing]:
        return [s for s in self.swings
                if s.confirmed_at <= index and (kind is None or s.kind == kind)]


# ---------------------------------------------------------------------------
# Swings
# ---------------------------------------------------------------------------
def find_swings(frame: pd.DataFrame, lookback: int = 2) -> list[Swing]:
    """Fractal swing highs/lows with ``lookback`` bars of confirmation each side.

    A bar is a swing high if its high is >= the highs of the ``lookback`` bars
    on both sides (strictly greater on at least one side to avoid flat runs
    producing a swing at every bar).
    """
    highs = frame["high"].values
    lows = frame["low"].values
    n = len(frame)
    swings: list[Swing] = []
    for i in range(lookback, n - lookback):
        left_h = highs[i - lookback:i]
        right_h = highs[i + 1:i + 1 + lookback]
        if highs[i] >= left_h.max() and highs[i] >= right_h.max() \
                and (highs[i] > left_h.max() or highs[i] > right_h.max()):
            swings.append(Swing(i, i + lookback, float(highs[i]), "high"))
        left_l = lows[i - lookback:i]
        right_l = lows[i + 1:i + 1 + lookback]
        if lows[i] <= left_l.min() and lows[i] <= right_l.min() \
                and (lows[i] < left_l.min() or lows[i] < right_l.min()):
            swings.append(Swing(i, i + lookback, float(lows[i]), "low"))
    swings.sort(key=lambda s: (s.index, s.kind))
    _label_swings(swings)
    return swings


def _label_swings(swings: list[Swing]) -> None:
    """Attach HH/HL/LH/LL labels by comparing to the previous same-kind swing."""
    last_high: Swing | None = None
    last_low: Swing | None = None
    for swing in swings:
        if swing.kind == "high":
            if last_high is not None:
                swing.label = "HH" if swing.price > last_high.price else "LH"
            last_high = swing
        else:
            if last_low is not None:
                swing.label = "HL" if swing.price > last_low.price else "LL"
            last_low = swing


# ---------------------------------------------------------------------------
# Displacement
# ---------------------------------------------------------------------------
def bar_arrays(frame: pd.DataFrame) -> dict:
    """Cached raw numpy columns for a frame.

    ``frame.iloc[i]`` costs a pandas row construction, which is invisible on a
    20k-bar 1H frame and dominates the profile on a 143k-bar 5m one (it was
    ~34s of a 178s signal pass). The values are identical; only the access path
    changes. Cached on ``frame.attrs`` so it follows the frame around.
    """
    # `.attrs` is inherited by copies and slices, so the guard fingerprints the
    # frame rather than trusting the tag: a stale cache here would feed the
    # wrong bars into every displacement test.
    n = len(frame)
    stamp = (n, float(frame["close"].iloc[0]), float(frame["close"].iloc[-1])) if n else (0,)
    cache = frame.attrs.get("_bar_arrays")
    if cache is None or cache.get("_stamp") != stamp:
        cache = {
            "_stamp": stamp,
            "open": frame["open"].values, "high": frame["high"].values,
            "low": frame["low"].values, "close": frame["close"].values,
            "atr": (frame["atr"].values if "atr" in frame
                    else np.full(n, np.nan)),
        }
        frame.attrs["_bar_arrays"] = cache
    return cache


def is_displacement(frame: pd.DataFrame, i: int, cfg: dict) -> tuple[bool, Direction]:
    """Was bar ``i`` a displacement candle (big directional body vs ATR)?"""
    if i < 1 or i >= len(frame):
        return False, "neutral"
    cols = bar_arrays(frame)
    open_, close = cols["open"][i], cols["close"][i]
    body = abs(close - open_)
    rng = max(cols["high"][i] - cols["low"][i], 1e-12)
    bar_atr = cols["atr"][i]
    if not np.isfinite(bar_atr) or bar_atr <= 0:
        return False, "neutral"
    ok = (body >= cfg["min_body_atr"] * bar_atr) and (body / rng >= cfg["min_body_ratio"])
    if not ok:
        return False, "neutral"
    return True, ("bullish" if close > open_ else "bearish")


def displacement_near(frame: pd.DataFrame, i: int, cfg: dict,
                      direction: Direction | None = None) -> bool:
    """Displacement within ``lookback_bars`` ending at bar ``i`` (inclusive)."""
    start = max(1, i - int(cfg.get("lookback_bars", 5)) + 1)
    for j in range(start, i + 1):
        ok, d = is_displacement(frame, j, cfg)
        if ok and (direction is None or d == direction):
            return True
    return False


# ---------------------------------------------------------------------------
# Structure events
# ---------------------------------------------------------------------------
def build_structure(frame: pd.DataFrame, cfg: dict) -> StructureState:
    """Walk the frame forward and emit BOS / CHoCH / MSS events.

    ``cfg`` is the ``structure`` config block.
    """
    lookback = int(cfg.get("swing_lookback", 2))
    disp_cfg = cfg.get("displacement", {})
    require_close = bool(cfg.get("bos_confirm_close", True))
    mss_needs_disp = bool(cfg.get("mss_requires_displacement", True))

    swings = find_swings(frame, lookback)
    state = StructureState(swings=swings)

    # Bucket swings by the bar at which they become knowable.
    by_confirm: dict[int, list[Swing]] = {}
    for swing in swings:
        by_confirm.setdefault(swing.confirmed_at, []).append(swing)

    active_high: Swing | None = None   # most recent confirmed swing high
    active_low: Swing | None = None
    bias: Direction = "neutral"
    n = len(frame)
    closes = frame["close"].values
    highs = frame["high"].values
    lows = frame["low"].values

    for i in range(n):
        for swing in by_confirm.get(i, []):
            if swing.kind == "high":
                active_high = swing
            else:
                active_low = swing

        up_break = False
        down_break = False
        if active_high is not None and active_high.index < i:
            level = active_high.price
            up_break = closes[i] > level if require_close else highs[i] > level
        if active_low is not None and active_low.index < i:
            level = active_low.price
            down_break = closes[i] < level if require_close else lows[i] < level

        # A bar that breaks both ways is noise -- ignore it.
        if up_break and down_break:
            continue

        if up_break:
            has_disp = displacement_near(frame, i, disp_cfg, "bullish")
            if bias == "bullish":
                kind = "BOS"
            else:
                kind = "MSS" if (has_disp or not mss_needs_disp) else "CHoCH"
            event = StructureEvent(i, kind, "bullish", active_high, has_disp)
            state.events.append(event)
            state.last_event = event
            if kind in ("BOS", "MSS"):
                bias = "bullish"
            active_high = None   # consumed
        elif down_break:
            has_disp = displacement_near(frame, i, disp_cfg, "bearish")
            if bias == "bearish":
                kind = "BOS"
            else:
                kind = "MSS" if (has_disp or not mss_needs_disp) else "CHoCH"
            event = StructureEvent(i, kind, "bearish", active_low, has_disp)
            state.events.append(event)
            state.last_event = event
            if kind in ("BOS", "MSS"):
                bias = "bearish"
            active_low = None

    state.bias = bias
    _set_leg(state, frame)
    return state


def _set_leg(state: StructureState, frame: pd.DataFrame) -> None:
    """Define the current structural leg (for premium/discount) from the last
    confirmed opposing swing pair."""
    high = state.last_swing("high")
    low = state.last_swing("low")
    if high is None or low is None:
        return
    state.leg_high = high.price
    state.leg_low = low.price


def bias_at(state: StructureState, index: int, min_swings: int = 4) -> Direction:
    """Directional bias using only information available at ``index``.

    Requires ``min_swings`` confirmed swings before it will commit -- the spec's
    "never enter on a single structure signal alone".
    """
    if len([s for s in state.swings if s.confirmed_at <= index]) < min_swings:
        return "neutral"
    bias: Direction = "neutral"
    for event in state.events:
        if event.index > index:
            break
        if event.kind in ("BOS", "MSS"):
            bias = event.direction
    return bias


def leg_at(state: StructureState, index: int) -> tuple[float | None, float | None]:
    """The most recent confirmed swing-high / swing-low pair as of ``index``."""
    high = low = None
    for swing in state.swings:
        if swing.confirmed_at > index:
            break
        if swing.kind == "high":
            high = swing.price
        else:
            low = swing.price
    return high, low
