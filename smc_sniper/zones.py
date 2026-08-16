"""Phase 3 -- Order blocks and fair value gaps.

**Order block.** The last opposing candle before a displacement leg. A bullish
OB is the last down-candle before an up-displacement; a bearish OB is the last
up-candle before a down-displacement. Per the spec an OB is only valid with an
associated structure event *and* displacement -- not every down candle is an
order block. Blocks are quality-ranked 0-4 and low-ranked ones are ignored.

Variants: **breaker** (an OB that failed and was flipped by an opposing break)
and **mitigation** (an OB revisited but not fully consumed).

**Fair value gap.** A three-candle imbalance: for a bullish FVG,
``low[i] > high[i-2]``. Size is measured in ATR (never flat pips -- flat pip
thresholds are broken by construction across this watchlist). A gap is
consumed once ``fill_pct_invalidate`` of it has been traded back through.

Everything here is computed causally: a zone created at bar ``i`` is only
usable from bar ``i`` onward, and mitigation is evaluated bar by bar.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from .structure import StructureState, _is_displacement_at, bar_arrays

ZoneKind = Literal["order_block", "breaker", "mitigation", "fvg"]


@dataclass
class Zone:
    index: int                  # bar at which the zone was created/knowable
    top: float
    bottom: float
    direction: Literal["bullish", "bearish"]
    kind: ZoneKind
    quality: int = 0            # 0-4
    displacement: bool = False
    structure_event: str = ""   # BOS / CHoCH / MSS that validates it
    invalidated_at: int | None = None
    label: str = ""

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def height(self) -> float:
        return max(self.top - self.bottom, 0.0)

    def entry_price(self, fill_pct: float) -> float:
        """Limit price at ``fill_pct`` depth into the zone.

        For a bullish zone, 0.0 = top edge (shallow) and 1.0 = bottom (deep).
        """
        if self.direction == "bullish":
            return self.top - fill_pct * self.height
        return self.bottom + fill_pct * self.height

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    def active_at(self, index: int, max_age: int) -> bool:
        if index < self.index or index - self.index > max_age:
            return False
        return self.invalidated_at is None or index < self.invalidated_at


# ---------------------------------------------------------------------------
# Fair value gaps
# ---------------------------------------------------------------------------
def find_fvgs(frame: pd.DataFrame, cfg: dict) -> list[Zone]:
    """Three-candle imbalances, ATR-scaled, with causal invalidation."""
    min_size_atr = float(cfg.get("min_size_atr", 0.18))
    fill_invalidate = float(cfg.get("fill_pct_invalidate", 0.85))
    max_age = int(cfg.get("max_age_bars", 40))

    highs, lows = frame["high"].values, frame["low"].values
    atr_vals = frame["atr"].values
    n = len(frame)
    zones: list[Zone] = []

    for i in range(2, n):
        bar_atr = atr_vals[i]
        if not np.isfinite(bar_atr) or bar_atr <= 0:
            continue
        # Bullish FVG: gap between high[i-2] and low[i]
        if lows[i] > highs[i - 2]:
            size = lows[i] - highs[i - 2]
            if size >= min_size_atr * bar_atr:
                zones.append(Zone(i, float(lows[i]), float(highs[i - 2]),
                                  "bullish", "fvg", label="bullish_fvg"))
        # Bearish FVG: gap between low[i-2] and high[i]
        if highs[i] < lows[i - 2]:
            size = lows[i - 2] - highs[i]
            if size >= min_size_atr * bar_atr:
                zones.append(Zone(i, float(lows[i - 2]), float(highs[i]),
                                  "bearish", "fvg", label="bearish_fvg"))

    _mark_fill_invalidation(frame, zones, fill_invalidate, max_age)
    return zones


def _mark_fill_invalidation(frame: pd.DataFrame, zones: list[Zone],
                            fill_pct: float, max_age: int) -> None:
    """Set ``invalidated_at`` once a zone has been filled past ``fill_pct``."""
    highs, lows = frame["high"].values, frame["low"].values
    n = len(frame)
    for zone in zones:
        height = zone.height
        if height <= 0:
            zone.invalidated_at = zone.index
            continue
        limit = min(n, zone.index + max_age + 1)
        for j in range(zone.index + 1, limit):
            if zone.direction == "bullish":
                # filled from the top downward
                filled = (zone.top - max(lows[j], zone.bottom)) / height
            else:
                filled = (min(highs[j], zone.top) - zone.bottom) / height
            if filled >= fill_pct:
                zone.invalidated_at = j
                break


# ---------------------------------------------------------------------------
# Order blocks
# ---------------------------------------------------------------------------
def find_order_blocks(frame: pd.DataFrame, state: StructureState,
                      cfg: dict, disp_cfg: dict) -> list[Zone]:
    """Last opposing candle before a displacement leg, validated by structure."""
    lookback = int(cfg.get("lookback_bars", 40))
    max_age = int(cfg.get("max_age_bars", 60))
    require_disp = bool(cfg.get("require_displacement", True))
    opens, closes = frame["open"].values, frame["close"].values
    highs, lows = frame["high"].values, frame["low"].values
    n = len(frame)

    # Map bar -> structural event, so an OB can be tied to BOS/CHoCH/MSS.
    event_at: dict[int, str] = {}
    event_dir: dict[int, str] = {}
    for event in state.events:
        event_at[event.index] = event.kind
        event_dir[event.index] = event.direction

    zones: list[Zone] = []
    cols = bar_arrays(frame)
    for i in range(1, n):
        has_disp, disp_dir = _is_displacement_at(cols, n, i, disp_cfg)
        if require_disp and not has_disp:
            continue
        if not has_disp:
            continue
        # Walk back for the last candle of the opposite colour.
        origin = None
        for j in range(i - 1, max(0, i - lookback) - 1, -1):
            if disp_dir == "bullish" and closes[j] < opens[j]:
                origin = j
                break
            if disp_dir == "bearish" and closes[j] > opens[j]:
                origin = j
                break
        if origin is None:
            continue

        # Structure association: an event on/near the displacement bar.
        #
        # v5 AUDIT FIX. The original window ran to `i + 3`, i.e. it read
        # structure events up to TWO BARS AFTER the bar at which the zone
        # becomes knowable, and fed them into `_rank_ob`, whose output gates
        # admission through `order_blocks.min_quality`. Measured across 88,299
        # order blocks on the 1H swing stack, 11.16% of them have their quality
        # rank decided by an event the market had not yet printed. That is a
        # genuine lookahead: a zone created at bar i can only be scored on
        # information available at bar i's close.
        #
        # Kept behind a flag that defaults to the OLD behaviour purely so
        # `run_backtest.py --stack swing` keeps reproducing v2's published
        # 153 / 54.90% / 1.260. The v5 profile turns it on.
        hi_k = i + 1 if cfg.get("causal_structure_association", False) else i + 3
        struct_kind = ""
        for k in range(origin, min(n, hi_k)):
            if k in event_at and event_dir.get(k) == disp_dir:
                struct_kind = event_at[k]
                break

        quality = _rank_ob(frame, origin, i, has_disp, struct_kind)
        zone = Zone(i, float(highs[origin]), float(lows[origin]), disp_dir,
                    "order_block", quality, has_disp, struct_kind,
                    label=f"{disp_dir}_ob")
        zones.append(zone)

    _mark_ob_mitigation(frame, zones, cfg, max_age)
    _derive_breakers(frame, zones, state, cfg)
    return zones


def _rank_ob(frame: pd.DataFrame, origin: int, disp_i: int,
             has_disp: bool, struct_kind: str) -> int:
    """Quality 0-4: displacement, structure event, leg strength, tight body."""
    score = 0
    if has_disp:
        score += 1
    if struct_kind in ("MSS", "CHoCH"):
        score += 2
    elif struct_kind == "BOS":
        score += 1
    row = frame.iloc[disp_i]
    bar_atr = row.get("atr", np.nan)
    if np.isfinite(bar_atr) and bar_atr > 0:
        leg = abs(row["close"] - row["open"])
        if leg >= 1.5 * bar_atr:
            score += 1
    return min(score, 4)


def _mark_ob_mitigation(frame: pd.DataFrame, zones: list[Zone],
                        cfg: dict, max_age: int) -> None:
    """An OB fully traded through is dead."""
    if not cfg.get("mitigation_invalidates", True):
        return
    highs, lows = frame["high"].values, frame["low"].values
    n = len(frame)
    for zone in zones:
        limit = min(n, zone.index + max_age + 1)
        for j in range(zone.index + 1, limit):
            if zone.direction == "bullish" and lows[j] < zone.bottom:
                zone.invalidated_at = j
                break
            if zone.direction == "bearish" and highs[j] > zone.top:
                zone.invalidated_at = j
                break


def _derive_breakers(frame: pd.DataFrame, zones: list[Zone],
                     state: StructureState, cfg: dict) -> None:
    """A failed OB that price broke through becomes a breaker block the other way."""
    if not cfg.get("use_breaker_blocks", True):
        return
    max_age = int(cfg.get("max_age_bars", 60))
    breakers: list[Zone] = []
    for zone in zones:
        if zone.kind != "order_block" or zone.invalidated_at is None:
            continue
        flip = "bearish" if zone.direction == "bullish" else "bullish"
        age = zone.invalidated_at - zone.index
        if age > max_age:
            continue
        breakers.append(Zone(zone.invalidated_at, zone.top, zone.bottom, flip,
                             "breaker", max(zone.quality - 1, 0), zone.displacement,
                             zone.structure_event, label=f"{flip}_breaker"))
    zones.extend(breakers)


# ---------------------------------------------------------------------------
# Zone map
# ---------------------------------------------------------------------------
class ZoneMap:
    """Causal access to order blocks, breakers and FVGs."""

    def __init__(self, frame: pd.DataFrame, state: StructureState,
                 ob_cfg: dict, fvg_cfg: dict, disp_cfg: dict):
        self.frame = frame
        self.ob_cfg = ob_cfg
        self.fvg_cfg = fvg_cfg
        self.order_blocks = find_order_blocks(frame, state, ob_cfg, disp_cfg)
        self.fvgs = find_fvgs(frame, fvg_cfg)
        self.min_quality = int(ob_cfg.get("min_quality", 2))
        self.ob_max_age = int(ob_cfg.get("max_age_bars", 60))
        self.fvg_max_age = int(fvg_cfg.get("max_age_bars", 40))
        # A zone can only be active in the bar window [z.index, z.index+max_age],
        # so ordering by formation bar lets a lookup scan that window instead of
        # every zone in the series. On a 143k-bar 5m frame the unsorted scan was
        # 127M `active_at` calls and ~93s of a 178s signal pass.
        #
        # The returned slice is re-sorted back into ORIGINAL list order before
        # it leaves this class. That is not cosmetic: `best_zone` breaks exact
        # ties with a strict `>`, so whichever equal-keyed zone is seen first
        # wins, and `order_blocks` is not stored in index order (breakers are
        # appended last, indexed by their invalidation bar). Sorting the window
        # and forgetting to restore the order silently moved the swing stack
        # from 153 trades to 155 -- a real behaviour change wearing the costume
        # of a speedup.
        self._obs_win = sorted(enumerate(self.order_blocks), key=lambda t: t[1].index)
        self._fvgs_win = sorted(enumerate(self.fvgs), key=lambda t: t[1].index)
        self._ob_idx = [z.index for _, z in self._obs_win]
        self._fvg_idx = [z.index for _, z in self._fvgs_win]

    @staticmethod
    def _window(pairs: list, idx: list, index: int, max_age: int) -> list:
        lo = bisect.bisect_left(idx, index - max_age)
        hi = bisect.bisect_right(idx, index)
        return [z for _, z in sorted(pairs[lo:hi], key=lambda t: t[0])]

    def active_obs(self, index: int, direction: str) -> list[Zone]:
        return [z for z in self._window(self._obs_win, self._ob_idx,
                                        index, self.ob_max_age)
                if z.direction == direction
                and z.quality >= self.min_quality
                and z.active_at(index, self.ob_max_age)]

    def active_fvgs(self, index: int, direction: str) -> list[Zone]:
        return [z for z in self._window(self._fvgs_win, self._fvg_idx,
                                        index, self.fvg_max_age)
                if z.direction == direction and z.active_at(index, self.fvg_max_age)]

    def best_zone(self, index: int, direction: str, price: float,
                  atr_value: float, min_index: int | None = None
                  ) -> tuple[Zone | None, Zone | None]:
        """Pick the OB and FVG the entry will be built on.

        Preference: closest to price, within ``max_distance_atr``, highest
        quality first. Returns ``(order_block, fvg)`` -- either may be None.

        ``min_index`` restricts zones to those formed at or after a given bar,
        normally the sweep. The spec's sequence is sweep -> displacement ->
        MSS -> *then* the OB/FVG forms, so the entry zone must belong to the
        reversal leg. Without this, a stale order block from 60 bars ago could
        satisfy step 7 while having nothing to do with the setup.
        """
        max_dist = float(self.fvg_cfg.get("max_distance_atr", 2.5)) * atr_value

        def _pick(zones: list[Zone]):
            best, best_key = None, None
            for zone in zones:
                if min_index is not None and zone.index < min_index:
                    continue
                dist = abs(zone.mid - price)
                if dist > max_dist:
                    continue
                # zone must not already be behind price in the trade's favour
                if direction == "bullish" and zone.bottom > price:
                    continue
                if direction == "bearish" and zone.top < price:
                    continue
                key = (zone.quality, -dist)
                if best_key is None or key > best_key:
                    best, best_key = zone, key
            return best

        return _pick(self.active_obs(index, direction)), _pick(self.active_fvgs(index, direction))
