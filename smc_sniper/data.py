"""Market-data engine: fetch, cache, resample, and lookahead-safe MTF alignment.

Primary source is **TradeLocker** (the real execution venue, BID bars, ~400d of
15m and ~1200d of 1H). **Yahoo** is retained as a fallback so the package still
runs without broker credentials.

Honest limitations, restated in every report:

* TradeLocker bars are BID-only, so the backtester applies spread explicitly.
* ``XAUUSD`` is the broker's own gold contract on TradeLocker; on the Yahoo
  fallback it is proxied by the COMEX future ``GC=F``, which is close but not
  identical to spot (session gaps, settlement).
* 4H and 1D frames are **resampled from 1H**, anchored to the epoch, so a 4H
  bar covers [00,04) UTC etc. This matches the UTC session grid used elsewhere.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .providers import FetchResult, make_provider

# Timeframes fetched natively from the provider.
NATIVE = {"5m": "5m", "15m": "15m", "1H": "1H", "1D": "1D"}

# tf -> (native interval it is built from, pandas resample rule or None)
DERIVED = {
    "5m": ("5m", None),
    "15m": ("15m", None),
    # v5: 30m is resampled from the native 15m cache. It exists to test the rung
    # BETWEEN the working 1H setup model and the 15m one v3 measured as broken.
    "30m": ("15m", "30min"),
    "1H": ("1H", None),
    "4H": ("1H", "4h"),
    "1D": ("1H", "1D"),
}

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1H": 60,
               "4H": 240, "1D": 1440}


def tf_minutes(tf: str) -> int:
    return _TF_MINUTES[tf]


class DataEngine:
    """Fetches, caches and serves OHLC frames.

    Frames are indexed by **bar open time** (tz-aware UTC) and carry a
    ``close_time`` column. Anything asking "what was knowable at time t" must
    filter on ``close_time <= t``; :class:`MTFView` enforces that.
    """

    def __init__(self, cfg: Config, source: str | None = None):
        self.cfg = cfg
        self.source = source or cfg.get("data.provider", "tradelocker")
        root = cfg.resolve_path(cfg.get("data.cache_dir", "smc_data"))
        self.cache_dir = os.path.join(root, self.source)
        os.makedirs(self.cache_dir, exist_ok=True)
        self._provider = None
        self._mem: dict[tuple, pd.DataFrame] = {}

    @property
    def provider(self):
        if self._provider is None:
            self._provider = make_provider(self.cfg, self.source)
        return self._provider

    def _path(self, symbol: str, interval: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol}_{interval}.csv")

    # -- download -------------------------------------------------------
    def download(self, symbol: str, interval: str, days: int | None = None,
                 force: bool = False) -> FetchResult:
        path = self._path(symbol, interval)
        if os.path.exists(path) and not force:
            try:
                frame = pd.read_csv(path)
                return FetchResult(symbol, interval, len(frame), True, self.source)
            except OSError:
                pass
        if days is None:
            days = int(self.cfg.get(f"data.request_days.{interval}", 400))
        try:
            frame = self.provider.fetch(symbol, interval, days)
            if frame.empty:
                return FetchResult(symbol, interval, 0, False, self.source, "empty payload")
            frame.to_csv(path, index=False)
            times = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
            return FetchResult(symbol, interval, len(frame), True, self.source, "",
                               str(times.min()), str(times.max()))
        except Exception as exc:  # noqa: BLE001 -- reported, never silently dropped
            return FetchResult(symbol, interval, 0, False, self.source, str(exc)[:200])

    def download_deep(self, symbol: str, interval: str, days: int,
                      verbose: bool = False) -> FetchResult:
        """Chunked deep download, merged with whatever is already cached.

        The cache is a superset union keyed on timestamp, so re-running this
        can only ever *add* history. Only TradeLocker supports it; Yahoo's
        intraday windows are hard server-side caps.
        """
        if self.source != "tradelocker":
            return self.download(symbol, interval, days)
        path = self._path(symbol, interval)
        try:
            fresh = self.provider.fetch_deep(symbol, interval, days, verbose=verbose)
        except Exception as exc:  # noqa: BLE001 -- reported, never silently dropped
            return FetchResult(symbol, interval, 0, False, self.source, str(exc)[:200])
        if fresh.empty:
            return FetchResult(symbol, interval, 0, False, self.source, "empty payload")
        if os.path.exists(path):
            try:
                fresh = pd.concat([pd.read_csv(path), fresh], ignore_index=True)
            except OSError:
                pass
        fresh = (fresh.drop_duplicates(subset="timestamp")
                      .sort_values("timestamp").reset_index(drop=True))
        fresh.to_csv(path, index=False)
        times = pd.to_datetime(fresh["timestamp"], unit="s", utc=True)
        self._mem.pop((symbol, "native", interval), None)
        for tf, (native, _) in DERIVED.items():
            if native == interval:
                self._mem.pop((symbol, "tf", tf), None)
        return FetchResult(symbol, interval, len(fresh), True, self.source, "",
                           str(times.min()), str(times.max()))

    def download_all(self, intervals=("1H", "15m", "5m", "1D"),
                     force: bool = False, verbose: bool = True):
        """Download the whole watchlist. Failures are reported, never dropped."""
        sleep_s = float(self.cfg.get("data.request_sleep_s", 1.0))
        results: list[FetchResult] = []
        for interval in intervals:
            for symbol in self.cfg.symbols:
                res = self.download(symbol, interval, force=force)
                results.append(res)
                if verbose:
                    tag = "ok  " if res.ok else "FAIL"
                    span = f"{res.first[:10]}..{res.last[:10]}" if res.first else ""
                    print(f"  [{tag}] {self.source:12s} {symbol:8s} {interval:4s} "
                          f"{res.bars:6d} {span} {res.error}")
                time.sleep(sleep_s)
        return results

    # -- frames ---------------------------------------------------------
    def _load_native(self, symbol: str, interval: str) -> pd.DataFrame:
        key = (symbol, "native", interval)
        if key in self._mem:
            return self._mem[key]
        path = self._path(symbol, interval)
        if not os.path.exists(path):
            self._mem[key] = pd.DataFrame()
            return self._mem[key]
        raw = pd.read_csv(path)
        if raw.empty:
            self._mem[key] = pd.DataFrame()
            return self._mem[key]
        idx = pd.to_datetime(raw["timestamp"], unit="s", utc=True)
        frame = raw[["open", "high", "low", "close", "volume"]].copy()
        frame.index = idx
        frame = frame[~frame.index.duplicated(keep="first")].sort_index()
        frame.index.name = "time"
        self._mem[key] = frame
        return frame

    def get(self, symbol: str, tf: str) -> pd.DataFrame:
        """OHLC frame for ``tf`` with ``close_time`` and ``atr`` columns."""
        key = (symbol, "tf", tf)
        if key in self._mem:
            return self._mem[key]
        native, rule = DERIVED[tf]
        base = self._load_native(symbol, native)
        if base.empty:
            self._mem[key] = pd.DataFrame()
            return self._mem[key]
        if rule is None:
            frame = base.copy()
        else:
            # 'origin' only applies to tick-like frequencies; passing it for
            # daily/weekly rules emits a warning and has no effect.
            kwargs = {"origin": "epoch"} if rule.endswith(("h", "min", "s")) else {}
            frame = base.resample(rule, label="left", closed="left", **kwargs).agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}
            ).dropna(subset=["open", "high", "low", "close"])
        frame["close_time"] = frame.index + pd.Timedelta(minutes=tf_minutes(tf))
        frame["atr"] = atr(frame, int(self.cfg.get("stops.atr_period", 14)))
        self._mem[key] = frame
        return frame

    def available(self, symbol: str, tf: str) -> bool:
        return not self.get(symbol, tf).empty

    def coverage(self, tf: str) -> pd.DataFrame:
        """Per-symbol bar counts and date spans -- used for honest reporting."""
        rows = []
        for symbol in self.cfg.symbols:
            frame = self.get(symbol, tf)
            if frame.empty:
                rows.append({"symbol": symbol, "tf": tf, "bars": 0,
                             "first": "", "last": "", "days": 0})
                continue
            rows.append({
                "symbol": symbol, "tf": tf, "bars": len(frame),
                "first": str(frame.index[0])[:16], "last": str(frame.index[-1])[:16],
                "days": int((frame.index[-1] - frame.index[0]).days),
            })
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (rolling mean of true range)."""
    high, low, close = frame["high"], frame["low"], frame["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(period, min_periods=max(2, period // 2)).mean().bfill()


class MTFView:
    """Lookahead-safe multi-timeframe alignment.

    For every bar of the *setup* timeframe this precomputes the index of the
    last **completed** bar on each other timeframe. A higher-timeframe bar is
    knowable only once ``close_time <= setup_bar.close_time``. All strategy
    code reads higher timeframes exclusively through this class, which is what
    makes the no-lookahead claim mechanical rather than aspirational.
    """

    def __init__(self, engine: DataEngine, symbol: str, stack: dict):
        self.symbol = symbol
        self.stack = stack
        self.setup_tf = stack["setup_tf"]
        self.entry_tf = stack.get("entry_tf", stack["setup_tf"])
        self.frames: dict[str, pd.DataFrame] = {}
        for role in ("bias_tf", "structure_tf", "setup_tf", "entry_tf"):
            tf = stack.get(role)
            if tf and tf not in self.frames:
                self.frames[tf] = engine.get(symbol, tf)
        self.setup = self.frames[self.setup_tf]
        self.ok = not self.setup.empty and all(not f.empty for f in self.frames.values())
        self._maps: dict[str, np.ndarray] = {}
        if self.ok:
            setup_close = self.setup["close_time"].values
            for tf, frame in self.frames.items():
                if tf == self.setup_tf:
                    self._maps[tf] = np.arange(len(self.setup))
                else:
                    self._maps[tf] = np.searchsorted(
                        frame["close_time"].values, setup_close, side="right") - 1

    def index_at(self, tf: str, setup_i: int) -> int:
        return int(self._maps[tf][setup_i])

    def slice(self, tf: str, setup_i: int) -> pd.DataFrame:
        j = self.index_at(tf, setup_i)
        if j < 0:
            return self.frames[tf].iloc[:0]
        return self.frames[tf].iloc[: j + 1]
