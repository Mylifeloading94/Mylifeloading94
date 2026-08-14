"""Phase 2 -- Liquidity.

Where the stops are, and whether price has just run them.

Pool types tracked:

* **equal highs / equal lows** -- clusters of swing extremes within an
  ATR-scaled tolerance (never a flat pip figure: median 15m ATR is ~80 pips on
  XAUUSD versus ~2.5 on a quiet cross, so flat thresholds are broken by
  construction).
* **PDH / PDL** -- previous day's high / low.
* **PWH / PWL** -- previous week's high / low.
* **session highs / lows** -- Asian, London, NY.
* **major swing points** -- the raw structural extremes.

A **sweep** is a wick that pierces a pool and then *closes back* on the origin
side. That failed-breakout shape is the confirmation; a mere touch is not, and
a close beyond the pool is a break, not a sweep. Per the spec a sweep is a
major confirmation but never an automatic entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .sessions import session_of

PoolKind = Literal["equal_highs", "equal_lows", "PDH", "PDL", "PWH", "PWL",
                   "session_high", "session_low", "swing_high", "swing_low"]

# Pools worth the spec's "+5 previous day / previous week liquidity" bonus.
MAJOR_POOLS = {"PDH", "PDL", "PWH", "PWL"}
# Pools that count as "major sweep" targets (the +15).
STRONG_POOLS = {"equal_highs", "equal_lows", "PDH", "PDL", "PWH", "PWL",
                "session_high", "session_low"}


@dataclass
class LiquidityPool:
    index: int          # bar at which the pool became knowable
    price: float
    side: Literal["buy_side", "sell_side"]   # buy_side sits ABOVE price
    kind: PoolKind
    touches: int = 1
    label: str = ""


@dataclass
class Sweep:
    index: int
    pool: LiquidityPool
    direction: Literal["bullish", "bearish"]  # the direction the sweep implies
    extreme: float       # the wick extreme that took the liquidity
    pierce_atr: float


def _tolerance(bar_atr: float, cfg: dict) -> float:
    return float(cfg.get("equal_level_tolerance_atr", 0.12)) * bar_atr


def find_equal_levels(frame: pd.DataFrame, swings, cfg: dict) -> list[LiquidityPool]:
    """Cluster swing highs (and lows) that sit within an ATR-scaled band."""
    min_touches = int(cfg.get("equal_level_min_touches", 2))
    lookback = int(cfg.get("pool_lookback_bars", 120))
    pools: list[LiquidityPool] = []
    atr_vals = frame["atr"].values

    for kind, side, pool_kind in (("high", "buy_side", "equal_highs"),
                                  ("low", "sell_side", "equal_lows")):
        pts = [s for s in swings if s.kind == kind]
        used = set()
        for i, anchor in enumerate(pts):
            if i in used:
                continue
            bar_atr = atr_vals[min(anchor.index, len(atr_vals) - 1)]
            if not np.isfinite(bar_atr) or bar_atr <= 0:
                continue
            tol = _tolerance(bar_atr, cfg)
            cluster = [anchor]
            for j in range(i + 1, len(pts)):
                other = pts[j]
                if other.index - anchor.index > lookback:
                    break
                if abs(other.price - anchor.price) <= tol:
                    cluster.append(other)
                    used.add(j)
            if len(cluster) >= min_touches:
                # The pool is knowable only once its LAST touch is confirmed.
                confirmed = max(s.confirmed_at for s in cluster)
                price = float(np.mean([s.price for s in cluster]))
                pools.append(LiquidityPool(confirmed, price, side, pool_kind,
                                           len(cluster), f"{pool_kind}x{len(cluster)}"))
    return pools


def _period_levels(frame: pd.DataFrame, rule: str,
                   hi_kind: PoolKind, lo_kind: PoolKind) -> list[LiquidityPool]:
    """Previous-period high/low pools (PDH/PDL, PWH/PWL).

    The level for period N is knowable from the first bar of period N+1, which
    is exactly how it is indexed here -- no lookahead.
    """
    kwargs = {"origin": "epoch"} if rule.endswith(("h", "min", "s")) else {}
    grouped = frame.resample(rule, **kwargs)
    highs = grouped["high"].max().dropna()
    lows = grouped["low"].min().dropna()
    starts = grouped["open"].first().dropna()
    pools: list[LiquidityPool] = []
    positions = frame.index
    keys = list(starts.index)
    for k in range(1, len(keys)):
        # first bar index at/after the start of period k
        idx = int(positions.searchsorted(keys[k], side="left"))
        if idx >= len(frame):
            continue
        prev = keys[k - 1]
        if prev in highs.index:
            pools.append(LiquidityPool(idx, float(highs[prev]), "buy_side", hi_kind,
                                       1, hi_kind))
        if prev in lows.index:
            pools.append(LiquidityPool(idx, float(lows[prev]), "sell_side", lo_kind,
                                       1, lo_kind))
    return pools


def find_session_levels(frame: pd.DataFrame, cfg: dict) -> list[LiquidityPool]:
    """Prior-session highs and lows, knowable from the session's last bar on."""
    sess = np.array([session_of(ts, cfg) for ts in frame.index])
    day = frame.index.floor("D")
    key = pd.Series([f"{d.date()}|{s}" for d, s in zip(day, sess)], index=frame.index)
    pools: list[LiquidityPool] = []
    positions = frame.index
    for label, block in frame.groupby(key.values, sort=False):
        name = str(label).split("|")[1]
        if name in ("dead", "unknown"):
            continue
        end_time = block.index[-1]
        idx = int(positions.searchsorted(end_time, side="right"))
        if idx >= len(frame):
            continue
        pools.append(LiquidityPool(idx, float(block["high"].max()), "buy_side",
                                   "session_high", 1, f"{name}_high"))
        pools.append(LiquidityPool(idx, float(block["low"].min()), "sell_side",
                                   "session_low", 1, f"{name}_low"))
    return pools


def build_liquidity(frame: pd.DataFrame, swings, cfg: dict) -> list[LiquidityPool]:
    """All liquidity pools for a frame, sorted by the bar they become knowable."""
    pools: list[LiquidityPool] = []
    pools += find_equal_levels(frame, swings, cfg)
    if cfg.get("daily_levels", True):
        pools += _period_levels(frame, "1D", "PDH", "PDL")
    if cfg.get("weekly_levels", True):
        pools += _period_levels(frame, "1W", "PWH", "PWL")
    if cfg.get("session_levels", True):
        pools += find_session_levels(frame, cfg)
    for swing in swings:
        if swing.kind == "high":
            pools.append(LiquidityPool(swing.confirmed_at, swing.price, "buy_side",
                                       "swing_high", 1, swing.label or "swing_high"))
        else:
            pools.append(LiquidityPool(swing.confirmed_at, swing.price, "sell_side",
                                       "swing_low", 1, swing.label or "swing_low"))
    pools.sort(key=lambda p: p.index)
    return pools


def detect_sweeps(frame: pd.DataFrame, pools: list[LiquidityPool],
                  cfg: dict) -> list[Sweep]:
    """Find bars that pierced a pool and closed back inside.

    A bullish sweep runs *sell-side* liquidity (below) and closes back up: it
    implies upside. A bearish sweep runs buy-side liquidity and closes back
    down.
    """
    sweep_cfg = cfg.get("sweep", {})
    min_pierce = float(sweep_cfg.get("min_pierce_atr", 0.05))
    require_close_back = bool(sweep_cfg.get("require_close_back", True))
    lookback = int(cfg.get("pool_lookback_bars", 120))

    highs, lows = frame["high"].values, frame["low"].values
    closes, opens = frame["close"].values, frame["open"].values
    atr_vals = frame["atr"].values
    n = len(frame)

    # Bucket pools by the bar they become active.
    active: list[LiquidityPool] = []
    by_index: dict[int, list[LiquidityPool]] = {}
    for pool in pools:
        by_index.setdefault(pool.index, []).append(pool)

    sweeps: list[Sweep] = []
    for i in range(n):
        active.extend(by_index.get(i, []))
        if len(active) > 4000:
            active = [p for p in active if i - p.index <= lookback]
        bar_atr = atr_vals[i]
        if not np.isfinite(bar_atr) or bar_atr <= 0:
            continue
        need = min_pierce * bar_atr
        for pool in active:
            if pool.index >= i or i - pool.index > lookback:
                continue
            if pool.side == "buy_side":
                # wick above the pool, close back below it
                if highs[i] >= pool.price + need and (
                        not require_close_back or closes[i] < pool.price):
                    if closes[i] < opens[i] or highs[i] - max(closes[i], opens[i]) > need:
                        sweeps.append(Sweep(i, pool, "bearish", float(highs[i]),
                                            float((highs[i] - pool.price) / bar_atr)))
            else:
                if lows[i] <= pool.price - need and (
                        not require_close_back or closes[i] > pool.price):
                    if closes[i] > opens[i] or min(closes[i], opens[i]) - lows[i] > need:
                        sweeps.append(Sweep(i, pool, "bullish", float(lows[i]),
                                            float((pool.price - lows[i]) / bar_atr)))
    return sweeps


class LiquidityMap:
    """Indexed access to pools and sweeps for a frame."""

    def __init__(self, frame: pd.DataFrame, swings, cfg: dict):
        self.cfg = cfg
        self.pools = build_liquidity(frame, swings, cfg)
        self.sweeps = detect_sweeps(frame, self.pools, cfg)
        self._sweeps_by_index: dict[int, list[Sweep]] = {}
        for sweep in self.sweeps:
            self._sweeps_by_index.setdefault(sweep.index, []).append(sweep)

    def recent_sweep(self, index: int, direction: str,
                     max_bars: int) -> Sweep | None:
        """The most recent qualifying sweep at or before ``index``.

        Prefers strong pools (equal highs/lows, PD/PW, session extremes) over a
        plain swing point, and among those the deepest pierce.
        """
        best: Sweep | None = None
        best_key = None
        for j in range(index, max(-1, index - max_bars), -1):
            for sweep in self._sweeps_by_index.get(j, []):
                if sweep.direction != direction:
                    continue
                key = (sweep.pool.kind in STRONG_POOLS, sweep.pool.touches,
                       sweep.pierce_atr)
                if best_key is None or key > best_key:
                    best, best_key = sweep, key
        return best

    def pools_at(self, index: int, side: str, lookback: int = 300) -> list[LiquidityPool]:
        return [p for p in self.pools
                if p.side == side and p.index <= index and index - p.index <= lookback]

    def next_pool_above(self, index: int, price: float,
                        kinds: set | None = None) -> LiquidityPool | None:
        """Nearest untapped buy-side pool above ``price`` -- a TP candidate."""
        best = None
        for pool in self.pools_at(index, "buy_side"):
            if kinds and pool.kind not in kinds:
                continue
            if pool.price > price and (best is None or pool.price < best.price):
                best = pool
        return best

    def next_pool_below(self, index: int, price: float,
                        kinds: set | None = None) -> LiquidityPool | None:
        best = None
        for pool in self.pools_at(index, "sell_side"):
            if kinds and pool.kind not in kinds:
                continue
            if pool.price < price and (best is None or pool.price > best.price):
                best = pool
        return best
