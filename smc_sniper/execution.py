"""Phase 8 -- Execution.

A broker-agnostic interface with two implementations:

* :class:`PaperExecution` -- fully offline, works without credentials, used by
  the backtester and by paper/demo runs.
* :class:`TradeLockerExecution` -- the real venue. **It cannot place orders.**

On that last point, deliberately and permanently: this package is a research
and backtesting system. The TradeLocker class implements account/instrument/
quote reads and contains the order-submission shape for review, but every
order path passes through :meth:`_guard`, which raises unless an explicit
config flag *and* an environment variable are both set. Neither is set, the
flag is documented as never-to-be-enabled here, and no code path in this
repository turns them on. Read-only endpoints are the only ones exercised.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Order:
    symbol: str
    side: str                 # buy | sell
    order_type: str           # limit | market
    qty: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    client_id: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Position:
    symbol: str
    side: str
    qty: float
    entry: float
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: Any = None
    client_id: str = ""


@dataclass
class ExecutionResult:
    ok: bool
    order_id: str = ""
    message: str = ""
    detail: dict = field(default_factory=dict)


class ExecutionEngine(ABC):
    """The interface every broker adapter implements."""

    name = "abstract"

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def account(self) -> dict: ...

    @abstractmethod
    def quote(self, symbol: str) -> dict: ...

    @abstractmethod
    def place_order(self, order: Order) -> ExecutionResult: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> ExecutionResult: ...

    @abstractmethod
    def modify_position(self, client_id: str, stop_loss: float | None = None,
                        take_profit: float | None = None) -> ExecutionResult: ...

    @abstractmethod
    def close_position(self, client_id: str, portion: float = 1.0) -> ExecutionResult: ...

    @abstractmethod
    def positions(self) -> list[Position]: ...


class PaperExecution(ExecutionEngine):
    """In-memory broker. No network, no credentials, safe to run anywhere."""

    name = "paper"

    def __init__(self, cfg, starting_balance: float | None = None):
        self.cfg = cfg
        self.balance = float(
            starting_balance if starting_balance is not None
            else cfg.get("risk.starting_balance", 10000.0))
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._seq = 0
        self.log: list[dict] = []

    def connect(self) -> bool:
        return True

    def account(self) -> dict:
        return {"balance": self.balance, "equity": self.balance,
                "open_positions": len(self._positions), "mode": "paper"}

    def quote(self, symbol: str) -> dict:
        icfg = self.cfg.for_instrument(symbol)
        return {"symbol": symbol, "spread_pips": icfg.spread_pips, "source": "paper"}

    def place_order(self, order: Order) -> ExecutionResult:
        self._seq += 1
        oid = f"paper-{self._seq}"
        self._orders[oid] = order
        cid = order.client_id or oid
        self._positions[cid] = Position(
            order.symbol, order.side, order.qty, order.price or 0.0,
            order.stop_loss, order.take_profit, pd.Timestamp.now("UTC"), cid)
        self.log.append({"event": "order", "id": oid, "symbol": order.symbol,
                         "side": order.side, "qty": order.qty, "price": order.price})
        return ExecutionResult(True, oid, "accepted (paper)")

    def cancel_order(self, order_id: str) -> ExecutionResult:
        self._orders.pop(order_id, None)
        return ExecutionResult(True, order_id, "cancelled (paper)")

    def modify_position(self, client_id, stop_loss=None, take_profit=None) -> ExecutionResult:
        pos = self._positions.get(client_id)
        if not pos:
            return ExecutionResult(False, client_id, "no such position")
        if stop_loss is not None:
            pos.stop_loss = stop_loss
        if take_profit is not None:
            pos.take_profit = take_profit
        return ExecutionResult(True, client_id, "modified (paper)")

    def close_position(self, client_id: str, portion: float = 1.0) -> ExecutionResult:
        pos = self._positions.get(client_id)
        if not pos:
            return ExecutionResult(False, client_id, "no such position")
        if portion >= 1.0:
            self._positions.pop(client_id)
        else:
            pos.qty *= (1.0 - portion)
        return ExecutionResult(True, client_id, f"closed {portion:.0%} (paper)")

    def positions(self) -> list[Position]:
        return list(self._positions.values())


class TradeLockerExecution(ExecutionEngine):
    """TradeLocker adapter. Reads are live; **writes are structurally blocked.**

    Enabling orders would require setting both
    ``execution.tradelocker.allow_live_orders: true`` in config *and* the
    ``SMC_SNIPER_ALLOW_LIVE_ORDERS=1`` environment variable. Nothing in this
    repository sets either, and this system has never placed an order.
    """

    name = "tradelocker"
    ENV_GUARD = "SMC_SNIPER_ALLOW_LIVE_ORDERS"

    def __init__(self, cfg):
        from .providers import TradeLockerProvider
        self.cfg = cfg
        self.provider = TradeLockerProvider(cfg)
        self._connected = False

    # -- reads (safe, exercised) -----------------------------------------
    def connect(self) -> bool:
        if not self.provider.configured:
            raise RuntimeError(
                "TradeLocker credentials not present. Populate .env with "
                "TL_EMAIL/TL_PASSWORD/TL_SERVER/TL_ACCOUNT_ID/TL_ACC_NUM. "
                "The .env file is gitignored and must never be committed.")
        self.provider.instruments()
        self._connected = True
        return True

    def account(self) -> dict:
        acct = self.provider.env.get("TL_ACCOUNT_ID")
        payload = self.provider._get(f"/trade/accounts/{acct}/state", {})
        return payload.get("d", {})

    def quote(self, symbol: str) -> dict:
        return self.provider.quote(symbol)

    def instruments(self) -> dict:
        return self.provider.instruments()

    def positions(self) -> list[Position]:
        acct = self.provider.env.get("TL_ACCOUNT_ID")
        payload = self.provider._get(f"/trade/accounts/{acct}/positions", {})
        out = []
        for row in payload.get("d", {}).get("positions", []) or []:
            try:
                out.append(Position(str(row[1]), "buy" if float(row[4]) > 0 else "sell",
                                    abs(float(row[4])), float(row[5])))
            except (IndexError, TypeError, ValueError):
                continue
        return out

    # -- writes (blocked) --------------------------------------------------
    def _guard(self) -> None:
        import os
        allowed = bool(self.cfg.get("execution.tradelocker.allow_live_orders", False))
        env_ok = os.environ.get(self.ENV_GUARD) == "1"
        if not (allowed and env_ok):
            raise PermissionError(
                "Order placement is disabled. This package is a research and "
                "backtesting system and has never placed a live order. Enabling "
                "would require BOTH execution.tradelocker.allow_live_orders=true "
                f"and {self.ENV_GUARD}=1, neither of which is set anywhere in "
                "this repository. Validate on a demo account manually first.")

    def place_order(self, order: Order) -> ExecutionResult:
        self._guard()
        raise NotImplementedError("intentionally not implemented -- see _guard()")

    def cancel_order(self, order_id: str) -> ExecutionResult:
        self._guard()
        raise NotImplementedError("intentionally not implemented -- see _guard()")

    def modify_position(self, client_id, stop_loss=None, take_profit=None) -> ExecutionResult:
        self._guard()
        raise NotImplementedError("intentionally not implemented -- see _guard()")

    def close_position(self, client_id: str, portion: float = 1.0) -> ExecutionResult:
        self._guard()
        raise NotImplementedError("intentionally not implemented -- see _guard()")


def make_execution(cfg) -> ExecutionEngine:
    broker = cfg.get("execution.broker", "paper")
    if broker == "paper":
        return PaperExecution(cfg)
    if broker == "tradelocker":
        return TradeLockerExecution(cfg)
    raise ValueError(f"unknown broker: {broker}")
