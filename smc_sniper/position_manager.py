"""Position manager -- live-side trade management.

The backtester simulates management inline (vectorised over bars) for speed.
This module is the equivalent logic for a *live* or paper session, driven bar
by bar, and it shares the same rules so behaviour cannot silently diverge:

* partial take-profits at TP1 / TP2
* break-even move once ``trigger_r`` is reached
* trailing stop (structure or ATR) once ``start_after_r`` is reached
* a stop is **never widened** -- :meth:`_tighten` only ever moves it toward
  price, and rejects any modification that would increase risk
* time stop at ``max_hold_bars``
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ManagedPosition:
    symbol: str
    direction: str
    entry: float
    stop: float
    original_stop: float
    tp1: float
    tp2: float
    tp3: float
    risk_price: float
    size_lots: float
    remaining: float = 1.0
    stage: int = 0
    opened_index: int = 0
    client_id: str = ""
    realised_r: float = 0.0
    events: list = field(default_factory=list)

    @property
    def sign(self) -> float:
        return 1.0 if self.direction == "bullish" else -1.0

    def r_of(self, price: float) -> float:
        return self.sign * (price - self.entry) / self.risk_price


class PositionManager:
    def __init__(self, cfg, execution=None, telegram=None):
        self.cfg = cfg
        self.execution = execution
        self.telegram = telegram
        self.positions: dict[str, ManagedPosition] = {}

    def open(self, pos: ManagedPosition) -> None:
        self.positions[pos.client_id] = pos

    def _tighten(self, pos: ManagedPosition, new_stop: float) -> bool:
        """Move a stop toward price only. Never widens risk."""
        if pos.direction == "bullish" and new_stop > pos.stop:
            pos.stop = new_stop
            return True
        if pos.direction == "bearish" and new_stop < pos.stop:
            pos.stop = new_stop
            return True
        return False

    def on_bar(self, pos: ManagedPosition, bar: pd.Series, index: int) -> str | None:
        """Process one bar. Returns an exit reason when the position closes."""
        icfg = self.cfg.for_instrument(pos.symbol)
        high, low = float(bar["high"]), float(bar["low"])
        long = pos.direction == "bullish"

        # Ambiguity resolves against us -- stop is checked first.
        if (low <= pos.stop) if long else (high >= pos.stop):
            pos.realised_r += pos.remaining * pos.r_of(pos.stop)
            pos.remaining = 0.0
            reason = "stop_loss" if pos.stop == pos.original_stop else "breakeven_or_trail"
            pos.events.append({"event": reason, "price": pos.stop, "index": index})
            if self.telegram and reason == "stop_loss":
                self.telegram.sl_hit(pos)
            return reason

        tps = [pos.tp1, pos.tp2, pos.tp3]
        # Must mirror backtest.simulate_trade exactly: with scale-outs off, the
        # first target closes the entire position rather than banking nothing.
        pcfg = icfg.get("targets.partial_tp")
        if pcfg.get("enabled", True):
            portions = [float(pcfg.get("tp1_close_pct", 0.5)),
                        float(pcfg.get("tp2_close_pct", 0.3))]
            portions.append(max(0.0, 1.0 - portions[0] - portions[1]))
        else:
            portions = [1.0, 0.0, 0.0]

        if pos.stage < 3:
            target = tps[pos.stage]
            if (high >= target) if long else (low <= target):
                part = portions[pos.stage]
                if part >= pos.remaining or sum(portions[pos.stage + 1:]) <= 0:
                    part = pos.remaining
                pos.realised_r += part * pos.r_of(target)
                pos.remaining -= part
                pos.events.append({"event": f"TP{pos.stage + 1}", "price": target,
                                   "portion": part, "index": index})
                if self.telegram:
                    self.telegram.tp_hit(pos, f"TP{pos.stage + 1}", target, part)
                if self.execution:
                    self.execution.close_position(pos.client_id, part)
                pos.stage += 1
                if pos.remaining <= 1e-9:
                    return f"TP{pos.stage}"

        cur_r = pos.r_of(high if long else low)
        be = icfg.get("targets.breakeven")
        if be.get("enabled", True) and cur_r >= float(be.get("trigger_r", 1.0)):
            level = pos.entry + pos.sign * float(be.get("offset_r", 0.05)) * pos.risk_price
            if self._tighten(pos, level):
                pos.events.append({"event": "breakeven", "price": level, "index": index})
                if self.telegram:
                    self.telegram.breakeven_moved(pos, level)

        tr = icfg.get("targets.trailing")
        if tr.get("enabled", True) and cur_r >= float(tr.get("start_after_r", 2.0)):
            atr_val = float(bar.get("atr", 0) or 0)
            if atr_val > 0:
                mult = float(tr.get("atr_mult", 1.5))
                level = (high - mult * atr_val) if long else (low + mult * atr_val)
                if self._tighten(pos, level):
                    pos.events.append({"event": "trail", "price": level, "index": index})

        if index - pos.opened_index >= int(icfg.get("targets.max_hold_bars", 96)):
            pos.realised_r += pos.remaining * pos.r_of(float(bar["close"]))
            pos.remaining = 0.0
            return "time_stop"
        return None
