"""
TradeLocker REST client.

Covers auth + refresh, account discovery, instrument discovery, quotes,
history, orders, positions, SL/TP modification and closing. Every call is
wrapped so that a network failure surfaces as an explicit error rather than a
silent None - the order manager treats "I don't know" as a halt condition.

Credentials come from the environment only; nothing here logs a secret.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

DEMO = "https://demo.tradelocker.com/backend-api"
LIVE = "https://live.tradelocker.com/backend-api"


class TradeLockerError(RuntimeError):
    pass


class TransportError(TradeLockerError):
    """Network / timeout / 5xx - the request outcome is UNKNOWN."""


@dataclass
class Account:
    id: int
    acc_num: int
    currency: str
    balance: float


@dataclass
class Instrument:
    name: str
    tradable_instrument_id: int
    trade_route_id: int
    info_route_id: int
    raw: dict = field(default_factory=dict)

    @property
    def min_lot(self) -> float:
        for k in ("minLotSize", "lotSizeMin", "minQty"):
            if k in self.raw:
                return float(self.raw[k])
        return 0.01

    @property
    def lot_step(self) -> float:
        for k in ("lotSizeStep", "qtyStep", "lotStep"):
            if k in self.raw:
                return float(self.raw[k])
        return self.min_lot


class TradeLockerClient:
    def __init__(self, env: str = "demo", timeout: int = 15):
        self.base = LIVE if env.lower() == "live" else DEMO
        self.env = env.lower()
        self.timeout = timeout
        self.s = requests.Session()
        self._access: str | None = None
        self._refresh: str | None = None
        self._expire_ms: int = 0
        self.account: Account | None = None
        self._instruments: dict[str, Instrument] = {}

    # ------------------------------------------------------------- plumbing
    def _headers(self, with_acc: bool = True) -> dict:
        if not self._access:
            raise TradeLockerError("not authenticated")
        h = {"Authorization": f"Bearer {self._access}"}
        if with_acc and self.account:
            h["accNum"] = str(self.account.acc_num)
        return h

    def _req(self, method: str, path: str, *, auth: bool = True, with_acc: bool = True,
             **kw) -> Any:
        if auth:
            self._ensure_token()
            kw.setdefault("headers", {}).update(self._headers(with_acc))
        url = self.base + path
        try:
            r = self.s.request(method, url, timeout=self.timeout, **kw)
        except requests.RequestException as e:
            raise TransportError(f"{method} {path}: {type(e).__name__}") from e
        if r.status_code >= 500:
            raise TransportError(f"{method} {path}: HTTP {r.status_code}")
        if r.status_code >= 400:
            raise TradeLockerError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            raise TradeLockerError(f"{method} {path}: non-JSON response")

    # --------------------------------------------------------------- auth
    def login(self, email: str | None = None, password: str | None = None,
              server: str | None = None) -> None:
        email = email or os.environ.get("TRADELOCKER_USERNAME") or os.environ.get("TL_EMAIL")
        password = password or os.environ.get("TRADELOCKER_PASSWORD") or os.environ.get("TL_PASSWORD")
        server = server or os.environ.get("TRADELOCKER_SERVER") or os.environ.get("TL_SERVER")
        if not (email and password and server):
            raise TradeLockerError(
                "missing credentials: set TRADELOCKER_USERNAME / _PASSWORD / _SERVER")
        d = self._req("POST", "/auth/jwt/token", auth=False,
                      json={"email": email, "password": password, "server": server})
        self._access = d["accessToken"]
        self._refresh = d.get("refreshToken")
        self._expire_ms = int(d.get("expireDate", 0))

    def _ensure_token(self) -> None:
        if not self._access:
            raise TradeLockerError("not authenticated - call login() first")
        if self._expire_ms and time.time() * 1000 > self._expire_ms - 60_000:
            self.refresh()

    def refresh(self) -> None:
        if not self._refresh:
            raise TradeLockerError("no refresh token")
        d = self._req("POST", "/auth/jwt/refresh", auth=False,
                      json={"refreshToken": self._refresh})
        self._access = d["accessToken"]
        self._expire_ms = int(d.get("expireDate", 0))

    # ----------------------------------------------------------- accounts
    def accounts(self) -> list[Account]:
        d = self._req("GET", "/auth/jwt/all-accounts", with_acc=False)
        return [Account(int(a["id"]), int(a["accNum"]), a.get("currency", "USD"),
                        float(a.get("accountBalance", 0)))
                for a in d.get("accounts", [])]

    def select_account(self, account_id: int | None = None) -> Account:
        accs = self.accounts()
        if not accs:
            raise TradeLockerError("no accounts on this login")
        want = account_id or os.environ.get("TRADELOCKER_ACCOUNT_ID")
        if want:
            for a in accs:
                if a.id == int(want):
                    self.account = a
                    return a
            raise TradeLockerError(f"account {want} not found")
        self.account = accs[0]
        return self.account

    def account_state(self) -> dict:
        if not self.account:
            raise TradeLockerError("no account selected")
        return self._req("GET", f"/trade/accounts/{self.account.id}")

    # -------------------------------------------------------- instruments
    def instruments(self, refresh: bool = False) -> dict[str, Instrument]:
        if self._instruments and not refresh:
            return self._instruments
        d = self._req("GET", f"/trade/accounts/{self.account.id}/instruments")
        items = d.get("d", {}).get("instruments", d.get("instruments", []))
        out = {}
        for it in items:
            routes = it.get("routes", [])
            trade = next((r["id"] for r in routes if r.get("type") == "TRADE"), None)
            info = next((r["id"] for r in routes if r.get("type") == "INFO"), None)
            out[it["name"]] = Instrument(it["name"], int(it["tradableInstrumentId"]),
                                         trade, info, it)
        self._instruments = out
        return out

    def find_gold(self) -> Instrument:
        """Brokers name gold XAUUSD / XAU/USD / GOLD - resolve it explicitly."""
        ins = self.instruments()
        for name in ("XAUUSD", "XAU/USD", "GOLD", "XAUUSD.", "XAUUSD_"):
            if name in ins:
                return ins[name]
        for k, v in ins.items():
            if k.upper().replace("/", "").startswith("XAUUSD"):
                return v
        raise TradeLockerError(f"no gold instrument found among {len(ins)} instruments")

    # -------------------------------------------------------- market data
    def quote(self, ins: Instrument) -> dict:
        return self._req("GET", "/trade/quotes",
                         params={"tradableInstrumentId": ins.tradable_instrument_id,
                                 "routeId": ins.info_route_id})

    def history(self, ins: Instrument, resolution: str, start_ms: int, end_ms: int) -> dict:
        return self._req("GET", "/trade/history",
                         params={"tradableInstrumentId": ins.tradable_instrument_id,
                                 "routeId": ins.info_route_id, "resolution": resolution,
                                 "from": start_ms, "to": end_ms})

    # -------------------------------------------------------------- trade
    def place_market(self, ins: Instrument, side: str, qty: float,
                     stop_loss: float | None = None, take_profit: float | None = None) -> dict:
        body = {"tradableInstrumentId": ins.tradable_instrument_id,
                "routeId": ins.trade_route_id, "type": "market",
                "side": side, "qty": qty, "validity": "IOC"}
        if stop_loss is not None:
            body["stopLoss"] = round(stop_loss, 2)
        if take_profit is not None:
            body["takeProfit"] = round(take_profit, 2)
        return self._req("POST", f"/trade/accounts/{self.account.id}/orders", json=body)

    def orders(self) -> list[dict]:
        d = self._req("GET", f"/trade/accounts/{self.account.id}/orders")
        return d.get("d", {}).get("orders", d.get("orders", []))

    def orders_history(self) -> list[dict]:
        d = self._req("GET", f"/trade/accounts/{self.account.id}/ordersHistory")
        return d.get("d", {}).get("ordersHistory", d.get("ordersHistory", []))

    def cancel_order(self, order_id) -> dict:
        return self._req("DELETE", f"/trade/accounts/{self.account.id}/orders/{order_id}")

    def positions(self) -> list[dict]:
        d = self._req("GET", f"/trade/accounts/{self.account.id}/positions")
        return d.get("d", {}).get("positions", d.get("positions", []))

    def modify_position(self, position_id, stop_loss=None, take_profit=None) -> dict:
        body = {}
        if stop_loss is not None:
            body["stopLoss"] = round(stop_loss, 2)
        if take_profit is not None:
            body["takeProfit"] = round(take_profit, 2)
        if not body:
            raise TradeLockerError("modify_position called with nothing to modify")
        return self._req("PATCH", f"/trade/accounts/{self.account.id}/positions/{position_id}",
                         json=body)

    def close_position(self, position_id, qty: float | None = None) -> dict:
        body = {"qty": qty} if qty else {}
        return self._req("DELETE", f"/trade/accounts/{self.account.id}/positions/{position_id}",
                         json=body)

    def close_all(self) -> dict:
        return self._req("DELETE", f"/trade/accounts/{self.account.id}/positions")
