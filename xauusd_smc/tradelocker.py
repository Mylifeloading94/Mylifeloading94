"""
Minimal, dependency-light TradeLocker Public API client.

Docs: https://public-api.tradelocker.com/docs/getting-started
Credentials come from Config (env / .env) — never hardcoded.
"""
from __future__ import annotations

import time
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("xauusd_smc.tradelocker")

# Resolution strings differ slightly between TradeLocker deployments; try the
# repo-proven ones first, then the documented numeric fallbacks.
RESOLUTIONS = {
    "H4":  ["4H", "240"],
    "H1":  ["1H", "60"],
    "M15": ["15m", "15"],
    "M5":  ["5m", "5"],
    "D1":  ["1D", "D"],
}


class TradeLockerError(RuntimeError):
    pass


class TradeLocker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.base_url
        self.session = requests.Session()
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expire_ms: int = 0
        self.account_id: Optional[str] = None
        self.acc_num: Optional[str] = None
        self.balance: float = 0.0
        self._instrument: Optional[Dict[str, Any]] = None
        self._resolution_cache: Dict[str, str] = {}

    # -- auth --------------------------------------------------------------
    @property
    def headers(self) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self.access_token}"}
        if self.acc_num:
            h["accNum"] = str(self.acc_num)
        return h

    def login(self) -> None:
        r = self.session.post(
            f"{self.base}/auth/jwt/token",
            json={"email": self.cfg.tl_email, "password": self.cfg.tl_password,
                  "server": self.cfg.tl_server},
            timeout=20)
        if r.status_code not in (200, 201):
            raise TradeLockerError(f"auth failed {r.status_code}: {r.text[:200]}")
        d = r.json()
        self.access_token = d["accessToken"]
        self.refresh_token = d.get("refreshToken")
        self.expire_ms = int(d.get("expireDate") or 0)
        self._load_account()

    def ensure_token(self) -> None:
        """Refresh a few minutes before expiry; fall back to a full login."""
        if self.access_token is None:
            self.login()
            return
        if self.expire_ms and time.time() * 1000 < self.expire_ms - 300_000:
            return
        try:
            r = self.session.post(f"{self.base}/auth/jwt/refresh",
                                  json={"refreshToken": self.refresh_token}, timeout=20)
            if r.status_code in (200, 201):
                d = r.json()
                self.access_token = d["accessToken"]
                self.expire_ms = int(d.get("expireDate") or 0)
                if d.get("refreshToken"):
                    self.refresh_token = d["refreshToken"]
                return
        except requests.RequestException as e:
            log.warning("token refresh failed: %s", e)
        self.login()

    def _load_account(self) -> None:
        r = self.session.get(f"{self.base}/auth/jwt/all-accounts",
                             headers={"Authorization": f"Bearer {self.access_token}"},
                             timeout=20)
        if r.status_code != 200:
            raise TradeLockerError(f"all-accounts failed {r.status_code}: {r.text[:200]}")
        accounts = r.json().get("accounts", [])
        if not accounts:
            raise TradeLockerError("no trading accounts on this login")
        acc = accounts[0]
        if self.cfg.tl_account_id:
            acc = next((a for a in accounts
                        if str(a.get("id")) == str(self.cfg.tl_account_id)), acc)
        self.account_id = str(acc["id"])
        self.acc_num = str(acc["accNum"])
        self.balance = float(acc.get("accountBalance") or 0.0)
        log.info("account %s (accNum %s) balance $%.2f",
                 self.account_id, self.acc_num, self.balance)

    # -- low level ---------------------------------------------------------
    def _req(self, method: str, path: str, **kw) -> Any:
        self.ensure_token()
        url = f"{self.base}{path}"
        for attempt in range(4):
            try:
                r = self.session.request(method, url, headers=self.headers,
                                         timeout=kw.pop("timeout", 25), **kw)
            except requests.RequestException as e:
                log.warning("%s %s network error: %s", method, path, e)
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401:
                self.login()
                continue
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 2 ** attempt))
                log.warning("rate limited on %s, sleeping %.1fs", path, wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            try:
                return r.json()
            except ValueError:
                raise TradeLockerError(f"{method} {path} -> {r.status_code} {r.text[:200]}")
        raise TradeLockerError(f"{method} {path} failed after retries")

    # -- account state -----------------------------------------------------
    def account_state(self) -> Dict[str, float]:
        try:
            d = self._req("GET", f"/trade/accounts/{self.account_id}/state")
        except TradeLockerError:
            d = self._req("GET", f"/trade/accounts/{self.account_id}")
        vals = (d.get("d") or {}).get("accountDetailsData") or []
        keys = ["balance", "projectedBalance", "availableFunds", "blockedBalance",
                "cashBalance", "unsettledCash", "withdrawalAvailable", "stocksValue",
                "optionValue", "initialMarginReq", "maintMarginReq", "marginWarning",
                "blockedForStocks", "stockOrdersReq", "positionsMargin",
                "ordersMargin", "openNetPnL", "openGrossPnL", "positionsCount",
                "ordersCount"]
        state = {}
        for k, v in zip(keys, vals):
            try:
                state[k] = float(v)
            except (TypeError, ValueError):
                state[k] = 0.0
        if state.get("balance"):
            self.balance = state["balance"]
        return state

    def equity(self) -> float:
        """Balance + open P/L, falling back to the login balance."""
        try:
            st = self.account_state()
            bal = st.get("balance") or self.balance
            return float(bal) + float(st.get("openNetPnL") or 0.0)
        except (TradeLockerError, KeyError, ValueError) as e:
            log.warning("equity lookup failed: %s", e)
            return self.balance

    # -- instruments -------------------------------------------------------
    def instrument(self, symbol: str) -> Dict[str, Any]:
        if self._instrument and self._instrument.get("name") == symbol:
            return self._instrument
        d = self._req("GET", f"/trade/accounts/{self.account_id}/instruments")
        items = (d.get("d") or {}).get("instruments") or []
        match = None
        for i in items:
            name = (i.get("name") or "").upper()
            if name == symbol or name.replace(".", "").replace("_", "") == symbol:
                match = i
                break
        if match is None:                      # tolerate broker suffixes (XAUUSD.r)
            match = next((i for i in items
                          if (i.get("name") or "").upper().startswith(symbol)), None)
        if match is None:
            raise TradeLockerError(f"instrument {symbol} not available on this account")
        routes = match.get("routes") or []
        match["_trade_route"] = next((r.get("id") for r in routes
                                      if r.get("type") == "TRADE"), None)
        match["_info_route"] = next((r.get("id") for r in routes
                                     if r.get("type") == "INFO"), None)
        self._instrument = match
        log.info("instrument %s id=%s trade_route=%s info_route=%s",
                 match.get("name"), match.get("tradableInstrumentId"),
                 match["_trade_route"], match["_info_route"])
        return match

    # -- market data -------------------------------------------------------
    def bars(self, symbol: str, timeframe: str, lookback_days: float) -> List[Any]:
        ins = self.instrument(symbol)
        iid = ins["tradableInstrumentId"]
        now_ms = int(time.time() * 1000)
        frm_ms = now_ms - int(lookback_days * 86_400_000)
        candidates = ([self._resolution_cache[timeframe]]
                      if timeframe in self._resolution_cache
                      else RESOLUTIONS.get(timeframe, [timeframe]))
        for res in candidates:
            d = self._req("GET", "/trade/history", params={
                "tradableInstrumentId": iid, "routeId": ins["_info_route"],
                "resolution": res, "from": frm_ms, "to": now_ms})
            rows = (d.get("d") or {}).get("barDetails") or []
            if rows:
                self._resolution_cache[timeframe] = res
                return rows
        return []

    def quote(self, symbol: str) -> Dict[str, float]:
        ins = self.instrument(symbol)
        d = self._req("GET", "/trade/quotes", params={
            "tradableInstrumentId": ins["tradableInstrumentId"],
            "routeId": ins["_info_route"]})
        q = (d.get("d") or {})
        try:
            bid, ask = float(q.get("bp")), float(q.get("ap"))
        except (TypeError, ValueError):
            return {}
        return {"bid": bid, "ask": ask, "spread": ask - bid, "mid": (ask + bid) / 2}

    # -- orders / positions ------------------------------------------------
    def place_market_order(self, symbol: str, side: str, qty: float,
                           stop_loss: float, take_profit: float) -> Dict[str, Any]:
        ins = self.instrument(symbol)
        body = {
            "tradableInstrumentId": ins["tradableInstrumentId"],
            "routeId": ins["_trade_route"],
            "type": "market",
            "side": side,
            "qty": qty,
            "validity": "IOC",
            "stopLoss": round(stop_loss, 2),
            "stopLossType": "absolute",
            "takeProfit": round(take_profit, 2),
            "takeProfitType": "absolute",
        }
        d = self._req("POST", f"/trade/accounts/{self.account_id}/orders", json=body)
        ok = d.get("s") == "ok"
        return {"ok": ok, "order_id": (d.get("d") or {}).get("orderId"), "raw": d}

    def positions(self) -> List[List[Any]]:
        d = self._req("GET", f"/trade/accounts/{self.account_id}/positions")
        return (d.get("d") or {}).get("positions") or []

    def orders_history(self) -> List[List[Any]]:
        d = self._req("GET", f"/trade/accounts/{self.account_id}/ordersHistory")
        return (d.get("d") or {}).get("ordersHistory") or []

    def new_position_for(self, symbol: str, known_ids: set,
                         tries: int = 8, delay: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        A filled order becomes a NEW position with a different id. Rather than
        guessing which history column holds it, diff the open positions against
        the snapshot taken before the order was sent.
        """
        iid = str(self.instrument(symbol)["tradableInstrumentId"])
        for _ in range(tries):
            for row in self.positions():
                pos = parse_position(row)
                if pos and pos["id"] not in known_ids and str(pos["instrument_id"]) == iid:
                    return pos
            time.sleep(delay)
        return None

    def open_position_ids(self) -> set:
        return {parse_position(r)["id"] for r in self.positions() if parse_position(r)}

    def modify_position(self, position_id: str, stop_loss: Optional[float] = None,
                        take_profit: Optional[float] = None) -> bool:
        body: Dict[str, Any] = {}
        if stop_loss is not None:
            body.update({"stopLoss": round(stop_loss, 2), "stopLossType": "absolute"})
        if take_profit is not None:
            body.update({"takeProfit": round(take_profit, 2),
                         "takeProfitType": "absolute"})
        if not body:
            return False
        d = self._req("PATCH",
                      f"/trade/accounts/{self.account_id}/positions/{position_id}",
                      json=body)
        return d.get("s") == "ok"

    def close_position(self, position_id: str, qty: Optional[float] = None) -> bool:
        kw = {"json": {"qty": qty}} if qty else {}
        d = self._req("DELETE",
                      f"/trade/accounts/{self.account_id}/positions/{position_id}",
                      **kw)
        return d.get("s") == "ok"


# ---------------------------------------------------------------------------
# Position rows come back as arrays; column order is stable on TradeLocker but
# parsed defensively here so a layout change degrades instead of crashing.
# ---------------------------------------------------------------------------
POSITION_COLUMNS = ["id", "tradableInstrumentId", "routeId", "side", "qty",
                    "avgPrice", "stopLossId", "takeProfitId", "openDate",
                    "unrealizedPl"]


def parse_position(row: Any) -> Optional[Dict[str, Any]]:
    if isinstance(row, dict):
        row_d = row
    elif isinstance(row, (list, tuple)) and len(row) >= 6:
        row_d = dict(zip(POSITION_COLUMNS, list(row) + [None] * 10))
    else:
        return None

    def _num(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    try:
        return {
            "id": str(row_d.get("id")),
            "instrument_id": row_d.get("tradableInstrumentId"),
            "side": str(row_d.get("side") or "").lower(),
            "qty": _num(row_d.get("qty")),
            "entry": _num(row_d.get("avgPrice")),
            "pnl": _num(row_d.get("unrealizedPl")),
            "open_date": row_d.get("openDate"),
        }
    except (TypeError, ValueError):
        return None
