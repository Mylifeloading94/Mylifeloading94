"""Turns an approved signal into a verified live position."""
from __future__ import annotations

import uuid

from xauusd_bot.config import Config
from xauusd_bot.execution.execution_guard import ExecutionGuard, OrderState, OrderTicket
from xauusd_bot.execution.position_manager import LivePosition
from xauusd_bot.risk.risk_manager import RiskManager


class OrderManager:
    def __init__(self, guard: ExecutionGuard, risk: RiskManager, cfg: Config, instrument):
        self.g = guard
        self.risk = risk
        self.cfg = cfg
        self.ins = instrument

    def open_trade(self, direction: int, entry_ref: float, stop: float, tp1: float,
                   tp2: float, atr: float):
        dec = self.risk.approve(entry_ref, stop, tp2, direction)
        if not dec.approved:
            return None, dec.reason
        t = OrderTicket(client_ref=str(uuid.uuid4())[:8],
                        side="buy" if direction > 0 else "sell",
                        qty=dec.sizing.lots, intended_entry=entry_ref,
                        intended_sl=stop, intended_tp=tp2)
        t.to(OrderState.RISK_APPROVED)
        t = self.g.submit(self.ins, t)
        if t.state in (OrderState.REJECTED, OrderState.UNKNOWN):
            return t, t.state.value
        t = self.g.verify_fill(t)
        if t.state != OrderState.VERIFIED:
            return t, t.state.value
        self.risk.on_open()
        fill = t.fill_price or entry_ref
        lp = LivePosition(position_id=t.position_id, direction=direction, entry=fill,
                          stop=t.actual_sl or stop, tp1=tp1, tp2=tp2,
                          qty=t.qty, qty_open=t.qty,
                          r_distance=abs(fill - (t.actual_sl or stop)), atr=atr)
        return (t, lp), "opened"
