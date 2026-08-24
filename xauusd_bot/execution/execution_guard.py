"""
Execution safety layer (spec sections 20, 22, 23, 24).

The central rule: an order whose outcome is UNKNOWN halts new trading until the
account state has been re-verified against the broker. Never retry blindly -
first find out whether the broker accepted the original order.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from xauusd_bot.config import Config
from xauusd_bot.execution.tradelocker_client import (TradeLockerClient, TradeLockerError,
                                                     TransportError)
from xauusd_bot.risk.kill_switch import KillSwitch


class OrderState(str, Enum):
    SIGNAL = "SIGNAL"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    VERIFIED = "VERIFIED"


@dataclass
class OrderTicket:
    client_ref: str
    side: str
    qty: float
    intended_entry: float
    intended_sl: float
    intended_tp: float
    state: OrderState = OrderState.SIGNAL
    order_id: object = None
    position_id: object = None
    fill_price: float | None = None
    actual_sl: float | None = None
    actual_tp: float | None = None
    slippage_points: float = 0.0
    slippage_money: float = 0.0
    history: list = field(default_factory=list)

    def to(self, state: OrderState, note: str = "") -> None:
        self.state = state
        self.history.append((time.time(), state.value, note))


class ExecutionGuard:
    """Wraps the client with lifecycle verification and staleness checks."""

    def __init__(self, client: TradeLockerClient, cfg: Config, kill: KillSwitch):
        self.c = client
        self.cfg = cfg
        self.kill = kill
        self.last_quote_ts: float = 0.0
        self.unknown_tickets: list[OrderTicket] = []

    # ------------------------------------------------------- data freshness
    def data_is_fresh(self, quote_epoch_s: float | None = None) -> bool:
        ts = quote_epoch_s if quote_epoch_s is not None else self.last_quote_ts
        if not ts:
            return False
        age = time.time() - ts
        if age > self.cfg.execution.max_data_age_seconds:
            self.kill.trip(f"stale market data ({age:.0f}s old)")
            return False
        return True

    # ------------------------------------------------------- order placing
    def submit(self, ins, ticket: OrderTicket) -> OrderTicket:
        if not self.kill.allow_new_trades():
            ticket.to(OrderState.REJECTED, "kill switch active")
            return ticket
        ticket.to(OrderState.SUBMITTED)
        try:
            resp = self.c.place_market(ins, ticket.side, ticket.qty,
                                       ticket.intended_sl, ticket.intended_tp)
        except TransportError as e:
            # We do NOT know whether the broker got this. Halt and reconcile.
            ticket.to(OrderState.UNKNOWN, str(e))
            self.unknown_tickets.append(ticket)
            self.kill.trip(f"order outcome UNKNOWN: {e}")
            return ticket
        except TradeLockerError as e:
            ticket.to(OrderState.REJECTED, str(e))
            return ticket

        oid = (resp.get("d") or {}).get("orderId") or resp.get("orderId")
        if oid is None:
            ticket.to(OrderState.UNKNOWN, "no orderId in response")
            self.unknown_tickets.append(ticket)
            self.kill.trip("order response missing orderId")
            return ticket
        ticket.order_id = oid
        ticket.to(OrderState.CONFIRMED, f"orderId={oid}")
        return ticket

    # --------------------------------------------------------- verification
    def verify_fill(self, ticket: OrderTicket, wait_s: float | None = None) -> OrderTicket:
        """Poll ordersHistory + positions until the order resolves. Never
        assume a fill - if it cannot be resolved, the state is UNKNOWN."""
        deadline = time.time() + (wait_s or self.cfg.execution.order_timeout_seconds)
        while time.time() < deadline:
            try:
                hist = self.c.orders_history()
                rec = next((h for h in hist if str(h.get("orderId")) == str(ticket.order_id)), None)
                if rec:
                    status = str(rec.get("status", "")).upper()
                    if "FILL" in status:
                        ticket.position_id = rec.get("positionId")
                        ticket.fill_price = float(rec.get("avgPrice") or rec.get("price") or 0) or None
                        ticket.to(OrderState.FILLED, f"positionId={ticket.position_id}")
                        return self._verify_protection(ticket)
                    if any(k in status for k in ("REJECT", "CANCEL", "EXPIRE")):
                        ticket.to(OrderState.REJECTED, status)
                        return ticket
            except TradeLockerError:
                pass
            time.sleep(0.5)
        ticket.to(OrderState.UNKNOWN, "fill not resolved before timeout")
        self.unknown_tickets.append(ticket)
        if self.cfg.execution.halt_on_unknown:
            self.kill.trip("fill state UNKNOWN after timeout")
        return ticket

    def _verify_protection(self, ticket: OrderTicket) -> OrderTicket:
        """A filled position without a live stop is the single most dangerous
        state this system can be in. Verify, and repair once if missing."""
        if not self.cfg.execution.verify_sl_tp:
            return ticket
        try:
            pos = next((p for p in self.c.positions()
                        if str(p.get("id")) == str(ticket.position_id)), None)
        except TradeLockerError as e:
            self.kill.trip(f"cannot verify position protection: {e}")
            return ticket
        if pos is None:
            ticket.to(OrderState.UNKNOWN, "filled but position not found")
            self.kill.trip("filled order has no matching position")
            return ticket
        sl = pos.get("stopLoss")
        tp = pos.get("takeProfit")
        ticket.actual_sl = float(sl) if sl else None
        ticket.actual_tp = float(tp) if tp else None
        if not ticket.actual_sl:
            try:
                self.c.modify_position(ticket.position_id, stop_loss=ticket.intended_sl)
                ticket.actual_sl = ticket.intended_sl
                ticket.history.append((time.time(), "SL_REPAIRED", ""))
            except TradeLockerError as e:
                self.kill.trip(f"position has NO STOP and repair failed: {e}")
                return ticket
        if ticket.fill_price:
            ticket.slippage_points = abs(ticket.fill_price - ticket.intended_entry)
            ticket.slippage_money = ticket.slippage_points * ticket.qty * \
                self.cfg.instrument.contract_size
            if ticket.slippage_points > self.cfg.costs.max_slippage:
                ticket.history.append((time.time(), "SLIPPAGE_EXCEEDED",
                                       f"{ticket.slippage_points:.3f}"))
        ticket.to(OrderState.VERIFIED)
        return ticket

    # ------------------------------------------------------- reconciliation
    def reconcile(self) -> dict:
        """After any UNKNOWN or reconnect: rebuild truth from the broker.
        Only a clean reconcile may clear the halt."""
        try:
            state = self.c.account_state()
            positions = self.c.positions()
            orders = self.c.orders()
        except TradeLockerError as e:
            return {"ok": False, "error": str(e)}
        for t in list(self.unknown_tickets):
            match = next((p for p in positions
                          if str(p.get("id")) == str(t.position_id)), None)
            if match is None and t.order_id is not None:
                hist_match = None
                try:
                    hist_match = next((h for h in self.c.orders_history()
                                       if str(h.get("orderId")) == str(t.order_id)), None)
                except TradeLockerError:
                    pass
                if hist_match and "FILL" in str(hist_match.get("status", "")).upper():
                    t.position_id = hist_match.get("positionId")
                    t.to(OrderState.FILLED, "resolved during reconcile")
                else:
                    t.to(OrderState.REJECTED, "no position/fill found during reconcile")
            else:
                t.to(OrderState.FILLED, "resolved during reconcile")
            self.unknown_tickets.remove(t)
        return {"ok": True, "positions": len(positions), "orders": len(orders),
                "equity": (state.get("d") or state).get("equity")}
