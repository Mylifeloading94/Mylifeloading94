"""Market-data providers.

Two sources are supported behind one interface:

**TradeLocker (primary).** The actual execution venue. Credentials come from
``.env`` (gitignored, never committed) and only *read-only* endpoints are ever
touched: ``/trade/accounts/{id}/instruments``, ``/trade/quotes`` and
``/trade/history``. No order endpoint is called anywhere in this package.
History depth measured against this account (GENFX demo):

    ==========  ===========  ==================
    resolution  bars (1 req) span
    ==========  ===========  ==================
    1D          1641         ~2000 days
    1H          20480        ~1200 days
    15m         27283        ~400 days
    5m          24792        ~120 days
    ==========  ===========  ==================

Bars are **BID** (``barSource: "BID"`` on every instrument), so the backtester
adds the spread explicitly rather than reading a bid/ask series.

**Yahoo Finance (fallback/secondary).** Public chart API. Mid-price bars, and
much shorter intraday history (60m -> 730d, 15m/5m -> 60d, 1m -> 7d). Kept so
the package still runs if broker credentials go missing again -- which has
already happened twice in this repo's history.

Timestamps from both sources are epoch seconds/ms in genuine **UTC** (verified
by cross-correlating TradeLocker against Yahoo bar-for-bar, and by confirming
the weekly gap falls Fri 21:00 -> Sun 21:00 UTC). No timezone correction is
applied, so the UTC session windows in ``config.yaml`` are valid as written.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import pandas as pd
import requests

CA_BUNDLE = "/root/.ccr/ca-bundle.crt"


def _verify():
    return CA_BUNDLE if os.path.exists(CA_BUNDLE) else True


def load_dotenv(path: str) -> dict:
    """Minimal .env reader. The file is gitignored and never logged."""
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            out[key.strip()] = val.strip().strip('"').strip("'")
    return out


@dataclass
class FetchResult:
    symbol: str
    interval: str
    bars: int
    ok: bool
    source: str = ""
    error: str = ""
    first: str = ""
    last: str = ""


class BaseProvider:
    name = "base"

    def fetch(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# TradeLocker
# ---------------------------------------------------------------------------
class TradeLockerProvider(BaseProvider):
    """Read-only TradeLocker market-data client.

    This class deliberately exposes **no** order-placing methods. Historical
    bars, instrument metadata and quotes only.
    """

    name = "tradelocker"

    def __init__(self, cfg, env_path: str | None = None):
        self.cfg = cfg
        self.base = cfg.get("data.tradelocker.base_url",
                            "https://demo.tradelocker.com/backend-api")
        env_path = env_path or cfg.resolve_path(cfg.get("data.tradelocker.env_file", ".env"))
        self.env = load_dotenv(env_path)
        self._token: str | None = None
        self._instruments: dict[str, dict] | None = None

    # -- auth -----------------------------------------------------------
    @property
    def configured(self) -> bool:
        return all(self.env.get(k) for k in ("TL_EMAIL", "TL_PASSWORD", "TL_SERVER",
                                             "TL_ACCOUNT_ID", "TL_ACC_NUM"))

    def _auth(self, force: bool = False) -> str:
        if self._token and not force:
            return self._token
        if not self.configured:
            raise RuntimeError("TradeLocker credentials missing from .env")
        resp = requests.post(
            f"{self.base}/auth/jwt/token",
            json={"email": self.env["TL_EMAIL"], "password": self.env["TL_PASSWORD"],
                  "server": self.env["TL_SERVER"]},
            verify=_verify(), timeout=30,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"TradeLocker auth failed: {resp.status_code}")
        self._token = resp.json()["accessToken"]
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._auth()}",
                "accNum": self.env["TL_ACC_NUM"], "Accept": "application/json"}

    def _get(self, path: str, params: dict, timeout: int = 90):
        for attempt in range(4):
            resp = requests.get(f"{self.base}{path}", headers=self._headers(),
                                params=params, verify=_verify(), timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                self._auth(force=True)
                continue
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(3 + attempt * 4)
                continue
            raise RuntimeError(f"TradeLocker {path} -> {resp.status_code}")
        raise RuntimeError(f"TradeLocker {path} failed after retries")

    # -- instruments ----------------------------------------------------
    def instruments(self) -> dict[str, dict]:
        if self._instruments is not None:
            return self._instruments
        acct = self.env["TL_ACCOUNT_ID"]
        payload = self._get(f"/trade/accounts/{acct}/instruments", {})
        node = payload.get("d", payload)
        items = node.get("instruments", node) if isinstance(node, dict) else node
        out: dict[str, dict] = {}
        for item in items:
            name = item.get("name") or item.get("symbol")
            if not name:
                continue
            info = next((r["id"] for r in item.get("routes", []) if r["type"] == "INFO"), None)
            trade = next((r["id"] for r in item.get("routes", []) if r["type"] == "TRADE"), None)
            out[name] = {
                "tradableInstrumentId": item.get("tradableInstrumentId"),
                "info_route": info, "trade_route": trade,
                "bar_source": item.get("barSource"), "type": item.get("type"),
            }
        self._instruments = out
        return out

    def quote(self, symbol: str) -> dict:
        """Current bid/ask. Used to sanity-check configured spreads, not to trade."""
        meta = self.instruments().get(symbol)
        if not meta:
            return {}
        payload = self._get("/trade/quotes", {
            "tradableInstrumentId": meta["tradableInstrumentId"],
            "routeId": meta["info_route"]})
        return payload.get("d", {})

    # -- history --------------------------------------------------------
    RESOLUTIONS = {"1m": "1m", "5m": "5m", "15m": "15m", "60m": "1H",
                   "1H": "1H", "4H": "4H", "1D": "1D"}

    # Measured against this account: a single /trade/history call returns at
    # most ~20-27k bars and answers an over-long range with an EMPTY payload
    # rather than a truncated one. That silent-empty behaviour is what made
    # earlier versions of this repo believe 5m history only went back ~120
    # days. It does not -- see :meth:`fetch_deep`. Chunk sizes below are
    # calendar days chosen to stay under ~15k bars per request.
    CHUNK_DAYS = {"1m": 8, "5m": 70, "15m": 180, "1H": 600, "1D": 2000}

    def _history(self, meta: dict, resolution: str, from_ms: int, to_ms: int) -> list:
        payload = self._get("/trade/history", {
            "tradableInstrumentId": meta["tradableInstrumentId"],
            "routeId": meta["info_route"], "resolution": resolution,
            "from": from_ms, "to": to_ms})
        return payload.get("d", {}).get("barDetails", []) or []

    @staticmethod
    def _to_frame(bars: list) -> pd.DataFrame:
        if not bars:
            return pd.DataFrame()
        frame = pd.DataFrame(bars)
        frame = frame.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                                      "l": "low", "c": "close", "v": "volume"})
        frame["timestamp"] = (frame["timestamp"] // 1000).astype("int64")
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        frame = frame[[c for c in cols if c in frame.columns]]
        if "volume" not in frame:
            frame["volume"] = 0.0
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        return (frame.drop_duplicates(subset="timestamp")
                     .sort_values("timestamp").reset_index(drop=True))

    def fetch(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        meta = self.instruments().get(symbol)
        if not meta:
            raise RuntimeError(f"{symbol} not tradable on this account")
        resolution = self.RESOLUTIONS[interval]
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - days * 86400 * 1000
        return self._to_frame(self._history(meta, resolution, start_ms, now_ms))

    def fetch_deep(self, symbol: str, interval: str, days: int,
                   sleep_s: float = 0.4, verbose: bool = False) -> pd.DataFrame:
        """Walk ``days`` of history backwards in chunks and stitch the result.

        The per-request bar cap is the *only* thing that limits intraday depth
        on this broker -- 5m bars are served at least 700 days back and 1m at
        least 200, both of which a single request reports as "empty". Chunking
        is therefore a genuine capability gain, not a workaround: it is what
        makes a validated 5m scalping stack possible at all.

        Stops early after two consecutive empty chunks, which is how the true
        end of history announces itself.
        """
        meta = self.instruments().get(symbol)
        if not meta:
            raise RuntimeError(f"{symbol} not tradable on this account")
        resolution = self.RESOLUTIONS[interval]
        chunk = int(self.CHUNK_DAYS.get(interval, 70))
        now_ms = int(time.time() * 1000)
        day_ms = 86400 * 1000
        collected: list = []
        empties = 0
        offset = 0
        while offset < days:
            hi = now_ms - offset * day_ms
            lo = now_ms - min(offset + chunk, days) * day_ms
            try:
                bars = self._history(meta, resolution, lo, hi)
            except RuntimeError:
                bars = []
            if bars:
                collected.extend(bars)
                empties = 0
            else:
                empties += 1
                if empties >= 2:
                    break
            if verbose:
                print(f"    {symbol} {interval} -{offset}d..-{offset + chunk}d: "
                      f"{len(bars)} bars")
            offset += chunk
            time.sleep(sleep_s)
        return self._to_frame(collected)


# ---------------------------------------------------------------------------
# Yahoo
# ---------------------------------------------------------------------------
class YahooProvider(BaseProvider):
    name = "yahoo"

    WINDOWS = {"60m": "730d", "1H": "730d", "15m": "60d", "5m": "60d", "1m": "7d"}

    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg.get("data.yahoo.base_url",
                            "https://query2.finance.yahoo.com/v8/finance/chart/")
        self.headers = {"User-Agent": cfg.get(
            "data.yahoo.user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")}

    def fetch(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        icfg = self.cfg.for_instrument(symbol)
        native = "60m" if interval in ("60m", "1H") else interval
        range_ = self.WINDOWS.get(native, "60d")
        url = f"{self.base}{icfg.yahoo_symbol}"
        last = None
        for attempt in range(6):
            resp = requests.get(url, params={"range": range_, "interval": native},
                                headers=self.headers, verify=_verify(), timeout=30)
            if resp.status_code == 200:
                return self._to_frame(resp.json())
            last = resp
            if resp.status_code in (429, 502, 503):
                time.sleep(3 + attempt * 4)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Yahoo fetch failed {symbol} {interval}: "
                           f"{last.status_code if last is not None else '?'}")

    @staticmethod
    def _to_frame(payload: dict) -> pd.DataFrame:
        result = payload.get("chart", {}).get("result")
        if not result:
            return pd.DataFrame()
        node = result[0]
        quote = node["indicators"]["quote"][0]
        frame = pd.DataFrame({
            "timestamp": node.get("timestamp") or [],
            "open": quote.get("open"), "high": quote.get("high"),
            "low": quote.get("low"), "close": quote.get("close"),
            "volume": quote.get("volume"),
        }).dropna(subset=["open", "high", "low", "close"])
        frame["volume"] = frame["volume"].fillna(0)
        return frame


def make_provider(cfg, source: str) -> BaseProvider:
    if source == "tradelocker":
        return TradeLockerProvider(cfg)
    if source == "yahoo":
        return YahooProvider(cfg)
    raise ValueError(f"unknown data source: {source}")
