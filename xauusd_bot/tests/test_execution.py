"""Execution safety tests with a fake broker - no network, no credentials."""
import pytest

from xauusd_bot.config import Config
from xauusd_bot.execution.execution_guard import ExecutionGuard, OrderState, OrderTicket
from xauusd_bot.execution.position_manager import LivePosition, PositionManager
from xauusd_bot.execution.tradelocker_client import (Instrument, TradeLockerError,
                                                     TransportError)
from xauusd_bot.risk.kill_switch import KillSwitch


class FakeClient:
    def __init__(self, behaviour="ok"):
        self.behaviour = behaviour
        self.orders_placed = []
        self._positions = []
        self._history = []
        self.modifies = []
        self.closes = []

    def place_market(self, ins, side, qty, stop_loss=None, take_profit=None):
        self.orders_placed.append((side, qty, stop_loss, take_profit))
        if self.behaviour == "transport":
            # the broker MAY have received this - outcome unknown
            self._history.append({"orderId": "o1", "status": "FILLED",
                                  "positionId": "p1", "avgPrice": 4600.0})
            self._positions.append({"id": "p1", "stopLoss": stop_loss,
                                    "takeProfit": take_profit, "qty": qty})
            raise TransportError("connection reset")
        if self.behaviour == "reject":
            raise TradeLockerError("HTTP 400 insufficient margin")
        if self.behaviour == "no_id":
            return {"d": {}}
        oid = f"o{len(self.orders_placed)}"
        self._history.append({"orderId": oid, "status": "FILLED",
                              "positionId": f"p{len(self.orders_placed)}",
                              "avgPrice": 4600.10})
        sl = None if self.behaviour == "no_sl" else stop_loss
        self._positions.append({"id": f"p{len(self.orders_placed)}", "stopLoss": sl,
                                "takeProfit": take_profit, "qty": qty})
        return {"d": {"orderId": oid}}

    def orders_history(self): return list(self._history)
    def orders(self): return []
    def positions(self): return list(self._positions)
    def account_state(self): return {"equity": 500.0}

    def modify_position(self, pid, stop_loss=None, take_profit=None):
        self.modifies.append((pid, stop_loss, take_profit))
        for p in self._positions:
            if p["id"] == pid:
                if stop_loss is not None:
                    p["stopLoss"] = stop_loss
        return {"ok": True}

    def close_position(self, pid, qty=None):
        self.closes.append((pid, qty)); return {"ok": True}

    def close_all(self):
        self.closes.append(("ALL", None)); self._positions.clear(); return {"ok": True}


INS = Instrument("XAUUSD", 1, 10, 20, {})


def _guard(behaviour="ok"):
    c = FakeClient(behaviour)
    k = KillSwitch()
    return c, k, ExecutionGuard(c, Config(), k)


def _ticket():
    return OrderTicket("ref", "buy", 0.01, 4600.0, 4595.0, 4610.0)


def test_happy_path_reaches_verified():
    c, k, g = _guard()
    t = g.verify_fill(g.submit(INS, _ticket()))
    assert t.state == OrderState.VERIFIED
    assert t.position_id == "p1" and t.actual_sl == 4595.0
    assert k.allow_new_trades()


def test_transport_error_marks_unknown_and_halts():
    """The single most dangerous case: we don't know if the order landed."""
    c, k, g = _guard("transport")
    t = g.submit(INS, _ticket())
    assert t.state == OrderState.UNKNOWN
    assert not k.allow_new_trades(), "unknown order state must halt new trading"
    assert len(c.orders_placed) == 1


def test_no_blind_retry_after_unknown():
    c, k, g = _guard("transport")
    g.submit(INS, _ticket())
    t2 = g.submit(INS, _ticket())     # a second attempt must be refused
    assert t2.state == OrderState.REJECTED
    assert len(c.orders_placed) == 1, "duplicate order sent after an UNKNOWN outcome"


def test_reconcile_resolves_unknown_from_broker_truth():
    c, k, g = _guard("transport")
    t = g.submit(INS, _ticket())
    assert t.state == OrderState.UNKNOWN
    out = g.reconcile()
    assert out["ok"] and out["positions"] == 1
    assert t.state == OrderState.FILLED
    assert not g.unknown_tickets


def test_broker_rejection_is_not_unknown():
    c, k, g = _guard("reject")
    t = g.submit(INS, _ticket())
    assert t.state == OrderState.REJECTED
    assert k.allow_new_trades(), "a clean rejection must not halt the system"


def test_missing_order_id_halts():
    c, k, g = _guard("no_id")
    t = g.submit(INS, _ticket())
    assert t.state == OrderState.UNKNOWN and not k.allow_new_trades()


def test_position_without_stop_is_repaired():
    c, k, g = _guard("no_sl")
    t = g.verify_fill(g.submit(INS, _ticket()))
    assert c.modifies, "a filled position with no stop must be repaired immediately"
    assert t.actual_sl == 4595.0
    assert any(h[1] == "SL_REPAIRED" for h in t.history)


def test_slippage_is_measured():
    c, k, g = _guard()
    t = g.verify_fill(g.submit(INS, _ticket()))
    assert t.slippage_points == pytest.approx(0.10, abs=1e-6)
    assert t.slippage_money == pytest.approx(0.10 * 0.01 * 100, abs=1e-6)


def test_stale_data_trips_kill_switch():
    c, k, g = _guard()
    import time
    assert not g.data_is_fresh(time.time() - 600)
    assert not k.allow_new_trades()
    assert g.data_is_fresh(time.time())  # fresh check itself does not clear the trip


def test_stop_is_never_widened():
    c = FakeClient()
    pm = PositionManager(c, Config(), INS)
    p = LivePosition("p1", 1, 4600.0, 4595.0, 4607.5, 4612.5, 0.01, 0.01, 5.0, 2.0)
    pm.manage(p, 4606.0)                 # >1R -> breakeven
    assert p.be_moved and p.stop > 4595.0
    stop_after_be = p.stop
    pm.manage(p, 4601.0)                 # price falls back
    assert p.stop >= stop_after_be, "stop was moved backwards"


def test_partial_and_trail_sequence():
    c = FakeClient()
    pm = PositionManager(c, Config().with_overrides(**{"instrument.min_lot": 0.001}), INS)
    p = LivePosition("p1", 1, 4600.0, 4595.0, 4607.5, 4612.5, 0.02, 0.02, 5.0, 2.0)
    acts = pm.manage(p, 4608.0)          # past TP1 (1.5R) and trail start
    assert p.partial_done and c.closes
    assert any("trail" in a or "breakeven" in a for a in acts)


def test_flatten_all():
    c = FakeClient()
    c._positions.append({"id": "p1"})
    pm = PositionManager(c, Config(), INS)
    assert "closed" in pm.flatten_all()
    assert c._positions == []
