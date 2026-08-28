"""
High-impact news blackout (section 4: no trades 15 min before/after NFP,
CPI, FOMC).

Sources, in order of preference:
  1. `news_calendar.json` in the working directory — a list of
     {"time": "2026-09-05T12:30:00Z", "title": "NFP", "impact": "high"}
     entries. Edit it, no restart required (re-read every 5 minutes).
  2. Optional NEWS_JSON_URL env var pointing at the same shape.
  3. A conservative fallback that blocks the classic US high-impact release
     slots (12:30 and 14:00 UTC on weekdays, plus 18:00 UTC FOMC) when no
     calendar is configured. Disable with NEWS_FALLBACK_BLACKOUT=false.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import List, Optional, Tuple

import requests

log = logging.getLogger("xauusd_smc.news")

FALLBACK_SLOTS = [(12, 30), (14, 0), (18, 0)]   # UTC hh:mm, weekdays only


def _parse_iso(value: str) -> Optional[dt.datetime]:
    try:
        v = value.strip().replace("Z", "+00:00")
        d = dt.datetime.fromisoformat(v)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (AttributeError, ValueError):
        return None


class NewsFilter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.url = os.environ.get("NEWS_JSON_URL", "").strip()
        self._events: List[Tuple[dt.datetime, str]] = []
        self._loaded_at: float = 0.0
        self._have_calendar = False

    def _refresh(self, now: dt.datetime) -> None:
        if self._loaded_at and (now.timestamp() - self._loaded_at) < 300:
            return
        self._loaded_at = now.timestamp()
        events: List[Tuple[dt.datetime, str]] = []
        raw = None
        if os.path.exists(self.cfg.news_file):
            try:
                with open(self.cfg.news_file) as f:
                    raw = json.load(f)
            except (OSError, ValueError) as e:
                log.warning("news calendar unreadable: %s", e)
        if raw is None and self.url:
            try:
                r = requests.get(self.url, timeout=15)
                if r.status_code == 200:
                    raw = r.json()
            except (requests.RequestException, ValueError) as e:
                log.warning("news url fetch failed: %s", e)
        if isinstance(raw, dict):
            raw = raw.get("events") or raw.get("data") or []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("impact", "high")).lower() not in ("high", "3", "red"):
                continue
            when = _parse_iso(str(item.get("time") or item.get("date") or ""))
            if when:
                events.append((when, str(item.get("title") or "high-impact news")))
        self._events = events
        self._have_calendar = bool(events)

    def blackout(self, now: Optional[dt.datetime] = None) -> Optional[str]:
        """Return the reason string when trading is blocked, else None."""
        now = now or dt.datetime.now(dt.timezone.utc)
        self._refresh(now)
        buf = dt.timedelta(minutes=self.cfg.news_buffer_min)
        for when, title in self._events:
            if abs((now - when).total_seconds()) <= buf.total_seconds():
                return f"news blackout: {title} at {when.strftime('%H:%M UTC')}"
        if self._have_calendar or not self.cfg.news_fallback_blackout:
            return None
        if now.weekday() >= 5:
            return None
        for hh, mm in FALLBACK_SLOTS:
            slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if abs((now - slot).total_seconds()) <= buf.total_seconds():
                return (f"news blackout: default US release window "
                        f"{hh:02d}:{mm:02d} UTC (add {self.cfg.news_file} to refine)")
        return None
