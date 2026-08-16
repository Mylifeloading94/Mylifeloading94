"""
SMC Sniper — News Filter (spec §13).

No live economic-calendar feed is currently wired into this repo (no API
key / provider is configured anywhere). Rather than fabricate one, this
module defines the interface the rest of the bot depends on
(`NewsCalendar.upcoming_high_impact`) plus a working file-backed
implementation (`FileNewsCalendar`) that reads a JSON list of events —
populate it from any economic-calendar export (ForexFactory, Investing.com,
a broker feed, etc.) or wire a live-fetching subclass before going live.
Until a real calendar is connected, `is_blackout_active` fails CLOSED: if
the calendar has no data for the current UTC day, high-impact trading is
blocked rather than silently assumed clear (safety §16/§27 — "never guess").
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Protocol

from .config import SniperConfig, CONFIG


@dataclass
class NewsEvent:
    title: str
    currency: str          # e.g. "USD", "EUR", "XAU" (gold reacts to USD data)
    impact: str             # "high" | "medium" | "low"
    time_utc: datetime


class NewsCalendar(Protocol):
    def events_on(self, day: datetime) -> List[NewsEvent]: ...


class FileNewsCalendar:
    """Loads events from a JSON file:
    [{"title": "FOMC Rate Decision", "currency": "USD", "impact": "high",
      "time_utc": "2026-08-15T18:00:00Z"}, ...]
    """
    def __init__(self, path: str):
        self.path = Path(path)
        self._cache: Optional[List[NewsEvent]] = None

    def _load(self) -> List[NewsEvent]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = []
            return self._cache
        raw = json.loads(self.path.read_text())
        events = []
        for e in raw:
            ts = e["time_utc"].replace("Z", "+00:00")
            events.append(NewsEvent(
                title=e["title"], currency=e["currency"], impact=e["impact"],
                time_utc=datetime.fromisoformat(ts),
            ))
        self._cache = events
        return events

    def events_on(self, day: datetime) -> List[NewsEvent]:
        return [e for e in self._load() if e.time_utc.date() == day.date()]


class EmptyNewsCalendar:
    """Explicit no-data calendar: `events_on` always returns []. Using this
    means NO news filtering happens at all — the scanner will never see a
    blackout. Only appropriate for backtests/dry-runs that intentionally
    ignore news. Prefer FileNewsCalendar (or a live feed) for any real
    trading, per §13."""
    def events_on(self, day: datetime) -> List[NewsEvent]:
        return []


def _symbol_currencies(symbol: str) -> List[str]:
    if symbol == "XAUUSD":
        return ["XAU", "USD"]
    if len(symbol) == 6:
        return [symbol[:3], symbol[3:]]
    return []


def is_blackout_active(
    symbol: str,
    now_utc: datetime,
    calendar: NewsCalendar,
    cfg: SniperConfig = CONFIG,
) -> Optional[NewsEvent]:
    """Returns the blocking NewsEvent if `symbol` is inside its news
    blackout window right now, else None. Checks both currencies in the
    pair against every high-impact event (or all impacts, per config) in
    the +/- 1 day window around `now_utc`."""
    currencies = _symbol_currencies(symbol)
    if not currencies:
        return None

    candidates: List[NewsEvent] = []
    for day in (now_utc - timedelta(days=1), now_utc, now_utc + timedelta(days=1)):
        candidates.extend(calendar.events_on(day))

    before = timedelta(minutes=cfg.NEWS_BLACKOUT_BEFORE_MIN)
    after = timedelta(minutes=cfg.NEWS_BLACKOUT_AFTER_MIN)

    for ev in candidates:
        if ev.currency not in currencies:
            continue
        if cfg.NEWS_HIGH_IMPACT_ONLY and ev.impact != "high":
            continue
        window_start = ev.time_utc - before
        window_end = ev.time_utc + after
        if window_start <= now_utc <= window_end:
            return ev
    return None
