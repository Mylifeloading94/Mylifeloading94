"""
TradeLocker execution client.

This is the only module in the package that can move money. Everything else
analyses; this places, modifies and closes orders.

Safety properties that are structural rather than advisory:

  * Every position is sent to the broker WITH its stop loss and take profit
    attached in the same request. If this process is killed, the container is
    reclaimed, or the network drops, the broker still holds the protective
    orders. An unmanaged position is never left naked.
  * Credentials come from the environment only. Nothing in this file writes a
    password to disk, logs one, or accepts one as an argument.
  * `TL_ENV` selects demo or live and defaults to demo. Trading real money
    requires the operator to set that variable deliberately.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

# The analysis engine is stdlib-only on purpose. This module is the one
# exception: TradeLocker sits behind Cloudflare, which rejects urllib's TLS
# fingerprint outright (HTTP 403, error 1010) while allowing requests. Trading
# is opt-in, so the dependency is too.
try:
    import requests
except ImportError:                                   # pragma: no cover
    requests = None

BASE_URLS = {
    "demo": "https://demo.tradelocker.com/backend-api",
    "live": "https://live.tradelocker.com/backend-api",
}

# Fallback column order for the array-shaped /positions payload, used only when
# /trade/config cannot be read. The live layout is resolved dynamically.
FALLBACK_POSITION_COLUMNS = [
    "id", "tradableInstrumentId", "routeId", "side", "qty", "avgPrice",
    "stopLossId", "takeProfitId", "openDate", "unrealizedPl", "stopLoss", "takeProfit",
]


class BrokerError(RuntimeError):
    pass


@dataclass
class Account:
    id: str
    acc_num: str
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    env: str = "demo"

    @property
    def is_live(self) -> bool:
        return self.env == "live"


@dataclass
class Position:
    id: str
    instrument_id: int
    side: str            # buy | sell
    qty: float
    open_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    unrealized: float = 0.0
    raw: dict = field(default_factory=dict)

    @property
    def is_buy(self) -> bool:
        return self.side.lower() == "buy"


class TradeLockerBroker:
    """Thin, defensive client over the TradeLocker public API."""

    def __init__(self, env: str | None = None, timeout: int = 20):
        self.env = (env or os.environ.get("TL_ENV", "demo")).lower()
        if self.env not in BASE_URLS:
            raise BrokerError(f"TL_ENV must be 'demo' or 'live', got {self.env!r}")
        self.base = os.environ.get("TL_BASE_URL") or BASE_URLS[self.env]
        self.timeout = timeout
        self._token: str | None = None
        self._refresh: str | None = None
        self._token_ts = 0.0
        self.account: Account | None = None
        self._instruments: dict[str, dict] = {}
        self._pos_columns: list[str] | None = None

    # -- transport ---------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None,
                 params: dict | None = None, auth: bool = True) -> dict:
        if requests is None:
            raise BrokerError("the execution layer needs the 'requests' package "
                              "(pip install requests)")
        headers = {"Accept": "application/json",
                   "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 "
                                  "Safari/537.36")}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            self._ensure_token()
            headers["Authorization"] = f"Bearer {self._token}"
            if self.account is not None:
                headers["accNum"] = str(self.account.acc_num)
        try:
            r = requests.request(method, f"{self.base}{path}", json=body, params=params,
                                 headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise BrokerError(f"{method} {path} -> network error: {exc}") from None
        if r.status_code >= 400:
            raise BrokerError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
        if not r.text.strip():
            return {}
        try:
            return r.json()
        except ValueError:
            raise BrokerError(f"{method} {path} -> non-JSON response: {r.text[:200]}") from None

    # -- auth --------------------------------------------------------------
    def _ensure_token(self):
        if self._token and (time.time() - self._token_ts) < 1500:
            return
        if self._refresh and self._token:
            try:
                d = self._request("POST", "/auth/jwt/refresh",
                                  {"refreshToken": self._refresh}, auth=False)
                if d.get("accessToken"):
                    self._token = d["accessToken"]
                    self._token_ts = time.time()
                    return
            except BrokerError:
                pass                                  # fall through to a full login
        email = os.environ.get("TL_EMAIL")
        password = os.environ.get("TL_PASSWORD")
        server = os.environ.get("TL_SERVER")
        missing = [n for n, v in (("TL_EMAIL", email), ("TL_PASSWORD", password),
                                  ("TL_SERVER", server)) if not v]
        if missing:
            raise BrokerError(f"missing credentials in the environment: {', '.join(missing)}")
        d = self._request("POST", "/auth/jwt/token",
                          {"email": email, "password": password, "server": server}, auth=False)
        if not d.get("accessToken"):
            raise BrokerError("authentication failed: no accessToken returned")
        self._token = d["accessToken"]
        self._refresh = d.get("refreshToken")
        self._token_ts = time.time()

    def connect(self, account_id: str | None = None) -> Account:
        """Authenticate and select the account. Returns what was actually selected."""
        self._ensure_token()
        d = self._request("GET", "/auth/jwt/all-accounts")
        accounts = d.get("accounts") or []
        if not accounts:
            raise BrokerError("no accounts on this login")
        want = account_id or os.environ.get("TL_ACCOUNT_ID")
        acc = next((a for a in accounts if str(a.get("id")) == str(want)), None) if want else None
        if acc is None:
            if want:
                raise BrokerError(f"account {want} not found. Available: "
                                  f"{', '.join(str(a.get('id')) for a in accounts)}")
            acc = accounts[0]
        self.account = Account(id=str(acc["id"]), acc_num=str(acc.get("accNum")),
                               currency=acc.get("currency", "USD"),
                               balance=float(acc.get("accountBalance") or 0.0),
                               env=self.env)
        self.refresh_account()
        return self.account

    def refresh_account(self) -> Account:
        if self.account is None:
            raise BrokerError("connect() first")
        try:
            d = self._request("GET", f"/trade/accounts/{self.account.id}/state")
            state = (d.get("d") or {}).get("accountDetailsData") or []
            if isinstance(state, list) and len(state) >= 2:
                self.account.balance = float(state[0])
                self.account.equity = float(state[1])
        except (BrokerError, TypeError, ValueError, IndexError):
            self.account.equity = self.account.equity or self.account.balance
        return self.account

    # -- instruments -------------------------------------------------------
    def instrument(self, symbol: str = "XAUUSD") -> dict:
        """Resolve a symbol to its tradableInstrumentId and TRADE/INFO routes."""
        if symbol in self._instruments:
            return self._instruments[symbol]
        if self.account is None:
            raise BrokerError("connect() first")
        d = self._request("GET", f"/trade/accounts/{self.account.id}/instruments")
        items = (d.get("d") or {}).get("instruments") or []
        match = next((i for i in items if str(i.get("name", "")).upper() == symbol.upper()), None)
        if match is None:
            match = next((i for i in items
                          if str(i.get("name", "")).upper().startswith(symbol.upper())), None)
        if match is None:
            raise BrokerError(f"{symbol} is not tradable on this account")
        routes = match.get("routes") or []
        info = {
            "id": match.get("tradableInstrumentId"),
            "name": match.get("name"),
            "trade_route": next((r.get("id") for r in routes if r.get("type") == "TRADE"), None),
            "info_route": next((r.get("id") for r in routes if r.get("type") == "INFO"), None),
            "lot_min": float(match.get("minLotSize") or 0.01),
            "lot_max": float(match.get("maxLotSize") or 100.0),
            "lot_step": float(match.get("lotStep") or 0.01),
            "raw": match,
        }
        if info["trade_route"] is None:
            raise BrokerError(f"no TRADE route for {symbol}")
        self._instruments[symbol] = info
        return info

    def quote(self, symbol: str = "XAUUSD") -> tuple[float | None, float | None]:
        """(bid, ask) straight from the broker — the prices an order will meet."""
        ins = self.instrument(symbol)
        d = self._request("GET", "/trade/quotes",
                          params={"tradableInstrumentId": ins["id"],
                                  "routeId": ins["info_route"]})
        q = d.get("d") or {}
        bid, ask = q.get("bp"), q.get("ap")
        return (float(bid) if bid else None), (float(ask) if ask else None)

    # -- positions ---------------------------------------------------------
    def _position_columns(self) -> list[str]:
        if self._pos_columns:
            return self._pos_columns
        try:
            d = self._request("GET", "/trade/config")
            cols = ((d.get("d") or {}).get("positionsConfig") or {}).get("columns") or []
            names = [c.get("id") for c in cols if c.get("id")]
            self._pos_columns = names or FALLBACK_POSITION_COLUMNS
        except BrokerError:
            self._pos_columns = FALLBACK_POSITION_COLUMNS
        return self._pos_columns

    def positions(self, symbol: str | None = None) -> list[Position]:
        if self.account is None:
            raise BrokerError("connect() first")
        d = self._request("GET", f"/trade/accounts/{self.account.id}/positions")
        rows = (d.get("d") or {}).get("positions") or []
        cols = self._position_columns()
        want_id = self.instrument(symbol)["id"] if symbol else None
        out: list[Position] = []
        for row in rows:
            rec = dict(zip(cols, row)) if isinstance(row, list) else dict(row)
            try:
                iid = int(rec.get("tradableInstrumentId"))
            except (TypeError, ValueError):
                continue
            if want_id is not None and iid != want_id:
                continue

            def num(key):
                v = rec.get(key)
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            out.append(Position(
                id=str(rec.get("id")), instrument_id=iid,
                side=str(rec.get("side", "")).lower(), qty=num("qty") or 0.0,
                open_price=num("avgPrice") or num("openPrice") or 0.0,
                stop_loss=num("stopLoss"), take_profit=num("takeProfit"),
                unrealized=num("unrealizedPl") or 0.0, raw=rec))
        return out

    # -- order placement ---------------------------------------------------
    def place(self, symbol: str, side: str, qty: float, stop_loss: float,
              take_profit: float, order_type: str = "market",
              price: float | None = None, validity: str = "IOC") -> dict:
        """
        Send an order with its protection attached in the same request.

        stop_loss and take_profit are mandatory here by design: this client has
        no code path that opens an unprotected position, because a process that
        can die must not be the only thing standing between a position and the
        market.
        """
        if side not in ("buy", "sell"):
            raise BrokerError(f"side must be buy or sell, got {side!r}")
        if not stop_loss or not take_profit:
            raise BrokerError("refusing to send an order without both a stop loss "
                              "and a take profit attached")
        if qty <= 0:
            raise BrokerError(f"refusing to send a non-positive quantity ({qty})")
        ins = self.instrument(symbol)
        body = {
            "tradableInstrumentId": ins["id"],
            "routeId": ins["trade_route"],
            "type": order_type,
            "side": side,
            "qty": round(qty, 2),
            "validity": validity,
            "stopLoss": round(float(stop_loss), 2),
            "stopLossType": "absolute",
            "takeProfit": round(float(take_profit), 2),
            "takeProfitType": "absolute",
        }
        if order_type in ("limit", "stop", "stopLimit"):
            if price is None:
                raise BrokerError(f"{order_type} order needs a price")
            body["price"] = round(float(price), 2)
            body["validity"] = "GTC"
        d = self._request("POST", f"/trade/accounts/{self.account.id}/orders", body)
        if d.get("s") != "ok":
            raise BrokerError(f"order rejected: {json.dumps(d)[:300]}")
        return {"order_id": (d.get("d") or {}).get("orderId"), "request": body, "response": d}

    def modify_position(self, position_id: str, stop_loss: float | None = None,
                        take_profit: float | None = None) -> bool:
        body: dict = {}
        if stop_loss is not None:
            body["stopLoss"] = round(float(stop_loss), 2)
            body["stopLossType"] = "absolute"
        if take_profit is not None:
            body["takeProfit"] = round(float(take_profit), 2)
            body["takeProfitType"] = "absolute"
        if not body:
            return False
        d = self._request("PATCH", f"/trade/accounts/{self.account.id}/positions/{position_id}",
                          body)
        return d.get("s", "ok") == "ok"

    def close_position(self, position_id: str, qty: float | None = None) -> bool:
        body = {"qty": round(float(qty), 2)} if qty else None
        d = self._request("DELETE",
                          f"/trade/accounts/{self.account.id}/positions/{position_id}", body)
        return d.get("s", "ok") == "ok"

    def close_all(self, symbol: str | None = None) -> int:
        n = 0
        for p in self.positions(symbol):
            if self.close_position(p.id):
                n += 1
        return n
