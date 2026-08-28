"""
Live XAUUSD market data feed.

Hard rule (spec §18): this module NEVER invents a price. Every quote and every
bar comes from a named upstream. When no upstream answers with fresh data the
feed reports `LIVE DATA UNAVAILABLE` and the engine refuses to publish a setup.

Providers, in priority order:
  1. tradelocker  — the broker's own XAUUSD spot stream. True XAUUSD. Needs
                    TL_EMAIL / TL_PASSWORD / TL_SERVER in the environment.
  2. binance      — PAX Gold (PAXGUSDT), a spot-gold-redeemable token. A PROXY,
                    but real-time and it tracks spot closely.
  3. yahoo        — COMEX front-month gold futures (GC=F). A PROXY *and* a
                    DELAYED feed (exchange rules: ~10 min for futures), plus it
                    carries a basis over spot. Last resort only.

Anything that is not provider #1 is flagged `is_true_xauusd = False`, and any
feed with a known lag is flagged `delayed`. Both facts are printed on every
dashboard and stamped onto every setup. Neither is ever hidden.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .candles import Series, make_series, resample, tf_seconds

UA = "Mozilla/5.0 (compatible; xausmc-bot/1.0)"

# How old the newest bar of a timeframe may be before we call the feed stale.
MAX_AGE_SEC = {"M1": 300, "M5": 720, "M15": 1800, "H1": 6000, "H4": 21600, "D1": 108000}
# How long a cached fetch may be reused before we go back to the upstream.
CACHE_TTL_SEC = {"M1": 45, "M5": 120, "M15": 300, "H1": 900, "H4": 1800, "D1": 3600}


def now_utc() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def _http_json(url: str, headers: dict | None = None, timeout: int = 25,
               data: bytes | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json, text/plain, */*")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# A spot-price-only reference used to calibrate a proxy feed back onto true
# XAUUSD. It publishes no candles, so it cannot drive the analysis — but it can
# say how far the proxy currently sits from spot, which turns proxy-derived
# levels into levels you can actually put in a broker terminal.
SPOT_REFERENCE_URL = "https://api.gold-api.com/price/XAU"


def spot_reference(timeout: int = 10) -> tuple[float | None, str]:
    """Live XAUUSD spot from an independent reference. (price, note)."""
    try:
        d = _http_json(SPOT_REFERENCE_URL, timeout=timeout)
        px = float(d.get("price"))
        if px <= 0:
            return None, "spot reference returned a non-positive price"
        return px, f"XAU spot {px:,.2f} at {d.get('updatedAt', '?')}"
    except Exception as exc:                        # noqa: BLE001 - absence is reportable
        return None, f"spot reference unavailable: {type(exc).__name__}: {exc}"


def gold_market_open(ts: float | None = None) -> bool:
    """
    Spot gold trades ~22:00 UTC Sunday to ~21:00 UTC Friday, with a daily
    settlement break around 21:00-22:00 UTC. Outside that, flat/absent bars are
    expected and are NOT a feed failure.
    """
    t = datetime.fromtimestamp(ts if ts is not None else now_utc(), tz=timezone.utc)
    wd, hour = t.weekday(), t.hour            # Mon=0 .. Sun=6
    if wd == 5:                                # Saturday
        return False
    if wd == 6:                                # Sunday: opens 22:00 UTC
        return hour >= 22
    if wd == 4 and hour >= 21:                 # Friday close
        return False
    return not (21 <= hour < 22)               # daily break


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
class Provider:
    name = "base"
    symbol = ""
    kind = ""
    kind_label = ""
    is_true_xauusd = False
    expected_delay_sec = 0        # publisher-imposed lag (exchange delay rules)
    priority = 99

    def available(self) -> bool:
        return True

    def fetch(self, tf: str, bars: int) -> Series:
        raise NotImplementedError


class YahooProvider(Provider):
    """COMEX front-month gold futures via Yahoo's public chart endpoint."""
    name = "yahoo"
    symbol = "GC=F"
    kind = "gold_futures_proxy"
    kind_label = "COMEX gold futures (proxy for XAUUSD spot — carries basis)"
    is_true_xauusd = False
    expected_delay_sec = 900      # Yahoo publishes futures on ~10-15 min delay
    priority = 3

    # tf -> (yahoo interval, range) ; H4 is resampled from 60m
    PLAN = {"M1": ("1m", "5d"), "M5": ("5m", "1mo"), "M15": ("15m", "1mo"),
            "M30": ("30m", "1mo"), "H1": ("60m", "3mo"), "D1": ("1d", "2y")}

    def _raw(self, interval: str, rng: str) -> tuple[list, dict]:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(self.symbol)}?interval={interval}&range={rng}"
               f"&includePrePost=false")
        d = _http_json(url)
        res = (d.get("chart") or {}).get("result") or []
        if not res:
            raise RuntimeError((d.get("chart") or {}).get("error") or "empty yahoo result")
        r = res[0]
        ts = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        rows = []
        for i, t in enumerate(ts):
            o, h, l, c = q.get("open", [])[i], q.get("high", [])[i], q.get("low", [])[i], q.get("close", [])[i]
            v = (q.get("volume") or [None] * len(ts))[i]
            if None in (o, h, l, c):
                continue
            rows.append((t, o, h, l, c, v or 0.0))
        return rows, r.get("meta") or {}

    def fetch(self, tf: str, bars: int) -> Series:
        if tf == "H4":
            return resample(self.fetch("H1", bars * 4 + 8), "H4")
        interval, rng = self.PLAN[tf]
        rows, meta = self._raw(interval, rng)
        s = make_series(tf, rows, self.name, self.symbol)
        # Yahoo's final bucket is the live, still-forming candle.
        if s.bars and meta.get("regularMarketTime", 0) < s.bars[-1].ts + tf_seconds(tf):
            s.has_forming_bar = True
        return s.tail(bars)


class BinanceProvider(Provider):
    """PAX Gold (PAXGUSDT) — a spot-gold-redeemable token, closest free spot proxy."""
    name = "binance"
    symbol = "PAXGUSDT"
    kind = "gold_token_proxy"
    kind_label = "PAX Gold token (proxy for XAUUSD spot — trades 24/7)"
    is_true_xauusd = False
    expected_delay_sec = 0        # real-time
    priority = 2

    PLAN = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "D1": "1d"}

    def fetch(self, tf: str, bars: int) -> Series:
        url = (f"https://data-api.binance.vision/api/v3/klines?symbol={self.symbol}"
               f"&interval={self.PLAN[tf]}&limit={min(1000, max(bars, 10))}")
        k = _http_json(url)
        rows = [(int(x[0]) // 1000, x[1], x[2], x[3], x[4], x[5]) for x in k]
        s = make_series(tf, rows, self.name, self.symbol)
        if s.bars and s.bars[-1].ts + tf_seconds(tf) > now_utc():
            s.has_forming_bar = True
        return s


class TradeLockerProvider(Provider):
    """The broker's own XAUUSD feed — the only source that is true XAUUSD spot."""
    name = "tradelocker"
    symbol = "XAUUSD"
    kind = "xauusd_spot"
    kind_label = "Broker XAUUSD spot (TradeLocker)"
    is_true_xauusd = True
    expected_delay_sec = 0
    priority = 1

    BASE = os.environ.get("TL_BASE_URL", "https://demo.tradelocker.com/backend-api")
    INFO_ROUTE = int(os.environ.get("TL_INFO_ROUTE", "452"))
    RES = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1H", "H4": "4H", "D1": "1D"}

    def __init__(self):
        self._headers: dict | None = None
        self._instrument_id: int | None = None
        self._auth_ts = 0.0

    def available(self) -> bool:
        return bool(os.environ.get("TL_EMAIL") and os.environ.get("TL_PASSWORD"))

    def _auth(self):
        if self._headers and now_utc() - self._auth_ts < 1800:
            return
        body = json.dumps({"email": os.environ["TL_EMAIL"],
                           "password": os.environ["TL_PASSWORD"],
                           "server": os.environ.get("TL_SERVER", "GenFX")}).encode()
        tok = _http_json(f"{self.BASE}/auth/jwt/token", {"Content-Type": "application/json"},
                         data=body, method="POST")
        access = tok.get("accessToken")
        if not access:
            raise RuntimeError("tradelocker auth returned no accessToken")
        h = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
        accs = _http_json(f"{self.BASE}/auth/jwt/all-accounts", h).get("accounts", [])
        if not accs:
            raise RuntimeError("tradelocker returned no accounts")
        want = os.environ.get("TL_ACCOUNT_ID")
        acc = next((a for a in accs if str(a.get("id")) == str(want)), accs[0])
        h["accNum"] = str(acc.get("accNum"))
        self._headers = h
        self._auth_ts = now_utc()
        if self._instrument_id is None:
            instr = _http_json(f"{self.BASE}/trade/accounts/{acc['id']}/instruments", h)
            for it in (instr.get("d", {}) or {}).get("instruments", []):
                if it.get("name", "").upper().startswith("XAUUSD"):
                    self._instrument_id = it.get("tradableInstrumentId")
                    self.symbol = it.get("name")
                    break
        if self._instrument_id is None:
            raise RuntimeError("XAUUSD instrument not found on this TradeLocker account")

    def fetch(self, tf: str, bars: int) -> Series:
        self._auth()
        span = tf_seconds(tf)
        to_ms = int(now_utc() * 1000)
        frm_ms = to_ms - int((bars + 5) * span * 1000 * 1.6)   # slack for weekend gaps
        q = urllib.parse.urlencode({"tradableInstrumentId": self._instrument_id,
                                    "routeId": self.INFO_ROUTE, "resolution": self.RES[tf],
                                    "from": frm_ms, "to": to_ms})
        d = _http_json(f"{self.BASE}/trade/history?{q}", self._headers)
        raw = (d.get("d") or {}).get("barDetails") or []
        rows = [(int(b["t"]) // 1000, b["o"], b["h"], b["l"], b["c"], b.get("v", 0.0)) for b in raw]
        s = make_series(tf, rows, self.name, self.symbol)
        if s.bars and s.bars[-1].ts + span > now_utc():
            s.has_forming_bar = True
        return s.tail(bars)


ALL_PROVIDERS: list[type[Provider]] = [TradeLockerProvider, YahooProvider, BinanceProvider]


# --------------------------------------------------------------------------
# Feed status + market snapshot
# --------------------------------------------------------------------------
@dataclass
class FeedStatus:
    state: str = "UNAVAILABLE"        # LIVE | STALE | MARKET_CLOSED | UNAVAILABLE
    source: str = ""
    symbol: str = ""
    kind: str = ""
    kind_label: str = ""
    is_true_xauusd: bool = False
    delayed_by_sec: int = 0
    # Live true-XAUUSD spot and the proxy's offset from it. Both None on a true
    # XAUUSD feed (nothing to calibrate) or when the reference is unreachable.
    spot_price: float | None = None
    basis: float | None = None
    basis_note: str = ""
    price: float | None = None
    price_ts: int | None = None
    age_sec: float = float("inf")
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.state == "LIVE"

    @property
    def delayed(self) -> bool:
        return self.delayed_by_sec > 0

    def to_spot(self, level: float) -> float | None:
        """Convert a proxy-derived price level into true XAUUSD terms."""
        return None if self.basis is None else round(level + self.basis, 2)

    @property
    def quality(self) -> str:
        """One token describing exactly what this price is. Stamped onto every setup."""
        if self.state != "LIVE":
            return self.state
        if self.is_true_xauusd:
            return "LIVE_XAUUSD_SPOT"
        return "LIVE_PROXY_DELAYED" if self.delayed else "LIVE_PROXY_REALTIME"

    @property
    def banner(self) -> str:
        if self.state == "LIVE":
            tag = "LIVE MARKET DATA" if self.is_true_xauusd else "LIVE MARKET DATA (PROXY FEED)"
            if self.delayed:
                tag += f" [DELAYED ~{self.delayed_by_sec // 60} MIN]"
            line = f"{tag} — {self.source}:{self.symbol} — last tick {self.age_sec:.0f}s ago"
            if self.basis is not None:
                line += (f" — calibrated to XAUUSD spot {self.spot_price:,.2f} "
                         f"(basis {self.basis:+.2f})")
            return line
        if self.state == "STALE":
            return f"LIVE DATA UNAVAILABLE — {self.source}:{self.symbol} last tick {self.age_sec:.0f}s old (stale)"
        if self.state == "MARKET_CLOSED":
            return "MARKET CLOSED — gold is outside trading hours; no new setups will be generated"
        return "LIVE DATA UNAVAILABLE — no provider returned usable data"


@dataclass
class Snapshot:
    """One coherent multi-timeframe read of the market at `taken_at`."""
    status: FeedStatus
    series: dict[str, Series] = field(default_factory=dict)
    taken_at: float = 0.0

    def tf(self, name: str) -> Series:
        return self.series.get(name, Series(name, []))

    @property
    def price(self) -> float | None:
        return self.status.price


class DataFeed:
    """Provider-failover feed with per-timeframe caching and staleness enforcement."""

    def __init__(self, providers: list[Provider] | None = None, prefer: str | None = None):
        if providers is None:
            providers = [cls() for cls in ALL_PROVIDERS]
        providers = [p for p in providers if p.available()]
        if prefer:
            providers.sort(key=lambda p: (0 if p.name == prefer else 1, p.priority))
        else:
            providers.sort(key=lambda p: p.priority)
        self.providers = providers
        self.active: Provider | None = None
        self._cache: dict[tuple[str, str], tuple[float, Series]] = {}

    def provider_names(self) -> list[str]:
        return [p.name for p in self.providers]

    def _cached_fetch(self, prov: Provider, tf: str, bars: int, force: bool) -> Series:
        key = (prov.name, tf)
        hit = self._cache.get(key)
        if hit and not force:
            fetched_at, series = hit
            fresh_enough = (now_utc() - fetched_at) < CACHE_TTL_SEC.get(tf, 300)
            not_stale = series.age_seconds() <= MAX_AGE_SEC.get(tf, 1800)
            if fresh_enough and not_stale and len(series) >= bars * 0.8:
                return series
        series = prov.fetch(tf, bars)
        if hit:                                    # keep history depth across refreshes
            series = hit[1].merge(series).tail(max(bars * 4, 500))
        self._cache[key] = (now_utc(), series)
        return series

    def snapshot(self, timeframes: dict[str, int], force: bool = True) -> Snapshot:
        """
        Fetch every requested timeframe from the first provider that can serve
        ALL of them. `force=True` bypasses the cache for the fastest timeframe so
        a scan never grades a setup against a price it has already used.
        """
        errors: list[str] = []
        order = [p for p in self.providers]
        if self.active:                            # sticky: don't flip feeds mid-session
            order.sort(key=lambda p: (0 if p is self.active else 1, p.priority))
        for prov in order:
            series: dict[str, Series] = {}
            try:
                fastest = min(timeframes, key=lambda t: tf_seconds(t))
                for tf, n in sorted(timeframes.items(), key=lambda kv: tf_seconds(kv[0])):
                    s = self._cached_fetch(prov, tf, n, force and tf == fastest)
                    if len(s) < 20:
                        raise RuntimeError(f"{tf}: only {len(s)} bars")
                    series[tf] = s
            except Exception as exc:               # noqa: BLE001 - report, then fail over
                errors.append(f"{prov.name}: {type(exc).__name__}: {exc}")
                continue

            self.active = prov
            fastest_tf = min(series, key=lambda t: tf_seconds(t))
            fs = series[fastest_tf]
            last = fs.last
            age = fs.age_seconds()
            # A forming bar is current by definition — age it from its open, not its close.
            if fs.has_forming_bar and last:
                age = max(0.0, now_utc() - last.ts)
            budget = MAX_AGE_SEC.get(fastest_tf, 300) + prov.expected_delay_sec
            state = "LIVE"
            if age > budget:
                state = "MARKET_CLOSED" if not gold_market_open() else "STALE"
            spot_px, spot_note = (None, "")
            if state == "LIVE" and not prov.is_true_xauusd:
                spot_px, spot_note = spot_reference()
            basis = (round(spot_px - last.c, 2)
                     if (spot_px is not None and last is not None) else None)
            status = FeedStatus(spot_price=spot_px, basis=basis, basis_note=spot_note,
                                state=state, source=prov.name, symbol=prov.symbol,
                                kind=prov.kind, kind_label=prov.kind_label,
                                is_true_xauusd=prov.is_true_xauusd,
                                delayed_by_sec=prov.expected_delay_sec,
                                price=last.c if last else None,
                                price_ts=last.ts if last else None,
                                age_sec=age, errors=errors)
            return Snapshot(status=status, series=series, taken_at=now_utc())

        if not self.providers:
            errors.append("no providers configured/available")
        return Snapshot(status=FeedStatus(state="UNAVAILABLE", errors=errors),
                        series={}, taken_at=now_utc())


def historical(provider_name: str, tf: str, bars: int, cache_dir: str | None = None) -> Series:
    """
    Pull a long history for the backtest. Explicitly HISTORICAL data, not live.

    Deep pulls are paginated and slow, so completed pages are cached on disk and
    only the missing tail is re-fetched. The cache holds past bars only, which
    never change; nothing here is ever used to answer a live price.
    """
    prov = next((c() for c in ALL_PROVIDERS if c.name == provider_name), None)
    if prov is None:
        raise ValueError(f"unknown provider {provider_name!r}")

    cache_path = None
    cached = Series(tf, [])
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"hist_{provider_name}_{tf}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as fh:
                    cached = make_series(tf, json.load(fh), provider_name, prov.symbol)
            except (OSError, json.JSONDecodeError, TypeError):
                cached = Series(tf, [])

    if len(cached) >= bars and cached.age_seconds() <= tf_seconds(tf) * 3:
        return cached.tail(bars)

    fresh = _fetch_history(prov, tf, max(bars - len(cached), 1000) if cached else bars)
    out = cached.merge(fresh) if len(cached) else fresh
    if len(out) < bars and len(cached):          # cache too short: pull the whole span
        out = _fetch_history(prov, tf, bars).merge(out)
    if cache_path:
        with open(cache_path, "w") as fh:
            json.dump([[b.ts, b.o, b.h, b.l, b.c, b.v] for b in out.bars], fh)
    return out.tail(bars)


def _fetch_history(prov: Provider, tf: str, bars: int) -> Series:
    """Paginate an upstream backwards until `bars` bars are in hand."""
    if prov.name == "binance":                      # paginate 1000-bar pages backwards
        span, out, end = tf_seconds(tf), [], int(now_utc() * 1000)
        while len(out) < bars:
            url = (f"https://data-api.binance.vision/api/v3/klines?symbol={prov.symbol}"
                   f"&interval={prov.PLAN[tf]}&limit=1000&endTime={end}")
            k = _http_json(url)
            if not k:
                break
            out = [(int(x[0]) // 1000, x[1], x[2], x[3], x[4], x[5]) for x in k] + out
            end = int(k[0][0]) - span * 1000
            time.sleep(0.25)
        return make_series(tf, out, prov.name, prov.symbol)
    return prov.fetch(tf, bars)
