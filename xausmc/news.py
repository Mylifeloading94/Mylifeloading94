"""
High-impact news filter (spec §17: "news filter where reliable data is available").

There is no free, reliable, redistributable economic calendar this bot can
depend on, so it does not pretend to have one. The filter reads a calendar file
you supply and reports honestly when none is configured — it never invents
event times, and it never silently reports "no news" when what it means is
"no calendar".

Calendar format — state/news.json:
  [{"time": "2026-08-28T12:30:00Z", "impact": "high", "title": "US CPI"}, ...]
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class NewsVerdict:
    configured: bool
    blocked: bool
    reason: str
    next_event: str = ""

    @property
    def label(self) -> str:
        if not self.configured:
            return "NEWS FILTER: no calendar configured — filter NOT applied"
        return f"NEWS FILTER: {'BLOCKED — ' + self.reason if self.blocked else 'clear'}"


def _parse(t: str) -> float | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(t, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def check(path: str, blackout_minutes: int = 30, now: float | None = None) -> NewsVerdict:
    if not path or not os.path.exists(path):
        return NewsVerdict(False, False, f"no calendar file at {path}")
    try:
        with open(path) as fh:
            events = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return NewsVerdict(False, False, f"calendar unreadable: {exc}")

    t = now if now is not None else datetime.now(tz=timezone.utc).timestamp()
    win = blackout_minutes * 60
    upcoming: list[tuple[float, str]] = []
    for e in events:
        if str(e.get("impact", "")).lower() not in ("high", "3", "red"):
            continue
        ets = _parse(str(e.get("time", "")))
        if ets is None:
            continue
        title = str(e.get("title", "high-impact event"))
        if abs(ets - t) <= win:
            mins = int((ets - t) / 60)
            when = f"in {mins} min" if mins > 0 else f"{abs(mins)} min ago"
            return NewsVerdict(True, True, f"{title} {when} (+/-{blackout_minutes} min blackout)")
        if ets > t:
            upcoming.append((ets, title))
    upcoming.sort()
    nxt = ""
    if upcoming:
        ets, title = upcoming[0]
        nxt = f"{title} at {datetime.fromtimestamp(ets, tz=timezone.utc):%H:%M UTC}"
    return NewsVerdict(True, False, "no high-impact event inside the blackout window", nxt)
