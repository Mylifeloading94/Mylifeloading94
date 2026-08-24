"""Live position management: breakeven, trailing, partials, session flat."""
from __future__ import annotations

from dataclasses import dataclass

from xauusd_bot.config import Config
from xauusd_bot.execution.tradelocker_client import TradeLockerClient, TradeLockerError


@dataclass
class LivePosition:
    position_id: object
    direction: int
    entry: float
    stop: float
    tp1: float
    tp2: float
    qty: float
    qty_open: float
    r_distance: float
    atr: float
    partial_done: bool = False
    be_moved: bool = False


class PositionManager:
    def __init__(self, client: TradeLockerClient, cfg: Config, instrument):
        self.c = client
        self.cfg = cfg
        self.ins = instrument

    def manage(self, p: LivePosition, price: float) -> list[str]:
        """Returns the list of actions taken. A stop is NEVER widened."""
        e = self.cfg.exits
        acts: list[str] = []
        r_now = (price - p.entry) * p.direction / p.r_distance

        if not p.partial_done and e.tp_model == "partial" and r_now >= e.tp1_r:
            part = round(p.qty * e.partial_frac, 8)
            if part >= self.cfg.instrument.min_lot:
                try:
                    self.c.close_position(p.position_id, qty=part)
                    p.qty_open = round(p.qty - part, 8)
                    p.partial_done = True
                    acts.append(f"partial {part} at {r_now:.2f}R")
                except TradeLockerError as ex:
                    acts.append(f"partial FAILED: {ex}")

        if not p.be_moved and r_now >= e.breakeven_at_r:
            new_stop = p.entry + p.direction * e.be_buffer_atr * p.atr
            if self._improves(p, new_stop):
                try:
                    self.c.modify_position(p.position_id, stop_loss=new_stop)
                    p.stop, p.be_moved = new_stop, True
                    acts.append(f"stop -> breakeven {new_stop:.2f}")
                except TradeLockerError as ex:
                    acts.append(f"BE move FAILED: {ex}")

        if r_now >= e.trail_start_r:
            trail = price - p.direction * e.trail_atr_mult * p.atr
            if self._improves(p, trail):
                try:
                    self.c.modify_position(p.position_id, stop_loss=trail)
                    p.stop = trail
                    acts.append(f"trail -> {trail:.2f}")
                except TradeLockerError as ex:
                    acts.append(f"trail FAILED: {ex}")
        return acts

    @staticmethod
    def _improves(p: LivePosition, new_stop: float) -> bool:
        """Only ever move a stop closer to profit - the anti-martingale rule."""
        return (p.direction > 0 and new_stop > p.stop) or \
               (p.direction < 0 and new_stop < p.stop)

    def flatten_all(self) -> str:
        try:
            self.c.close_all()
            return "all positions closed"
        except TradeLockerError as e:
            return f"flatten FAILED: {e}"
