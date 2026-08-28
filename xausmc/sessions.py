"""Trading sessions and ICT killzones, all in UTC."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# (name, start_hour, end_hour) — half-open [start, end) in UTC
SESSIONS = [
    ("ASIA", 0, 7),
    ("LONDON", 7, 12),
    ("LONDON_NY_OVERLAP", 12, 16),
    ("NEW_YORK", 16, 21),
    ("ROLLOVER", 21, 24),
]

# Killzones — the windows where SMC setups historically resolve fastest.
KILLZONES = [
    ("LONDON_KZ", 7.0, 10.0),
    ("NY_AM_KZ", 12.0, 15.0),
    ("NY_PM_KZ", 17.5, 19.0),
    ("ASIA_KZ", 0.0, 3.0),
]

PRIME_KILLZONES = {"LONDON_KZ", "NY_AM_KZ"}


@dataclass(frozen=True)
class SessionInfo:
    name: str
    killzone: str | None
    hour: float
    is_prime: bool
    weekday: int

    @property
    def label(self) -> str:
        return f"{self.name}{' / ' + self.killzone if self.killzone else ''}"


def session_at(ts: float | int | None = None) -> SessionInfo:
    t = datetime.fromtimestamp(ts, tz=timezone.utc) if ts is not None else datetime.now(tz=timezone.utc)
    hour = t.hour + t.minute / 60.0
    name = next((n for n, s, e in SESSIONS if s <= hour < e), "ROLLOVER")
    kz = next((n for n, s, e in KILLZONES if s <= hour < e), None)
    return SessionInfo(name, kz, hour, kz in PRIME_KILLZONES, t.weekday())


def session_name(ts: float | int | None = None) -> str:
    return session_at(ts).name
