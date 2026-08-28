"""
Performance engine (spec §15) over LIVE-TRACKED journal results.

Everything here describes signals this bot actually published and then tracked
to a result. It is never mixed with backtest numbers: the backtest answers
"what did this strategy do on history", this answers "what has it done since it
was switched on".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .journal import Journal, Record
from .stats import Bucket, compute_bucket


def _window(records: list[Record], days: int) -> list[Record]:
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp()
    return [r for r in records if (r.created_at or r.signal_ts) >= cutoff]


def _period_start(kind: str) -> float:
    now = datetime.now(tz=timezone.utc)
    if kind == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif kind == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0,
                                                              microsecond=0)
    else:                                          # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp()


@dataclass
class Period:
    name: str
    setups: int = 0
    open: int = 0
    invalidated: int = 0
    stats: Bucket = field(default_factory=Bucket)

    @property
    def wins(self) -> int:
        return self.stats.wins

    @property
    def losses(self) -> int:
        return self.stats.losses

    @property
    def win_rate(self) -> float:
        return self.stats.win_rate

    def as_dict(self) -> dict:
        return {"period": self.name, "setups": self.setups, "open": self.open,
                "invalidated": self.invalidated, **self.stats.as_dict()}


@dataclass
class Report:
    periods: dict[str, Period] = field(default_factory=dict)
    breakdowns: dict[str, dict[str, Bucket]] = field(default_factory=dict)
    total_records: int = 0
    resolved: int = 0
    source: str = "LIVE-TRACKED (journal)"

    def as_dict(self) -> dict:
        return {"source": self.source, "total_records": self.total_records,
                "resolved": self.resolved,
                "periods": {k: v.as_dict() for k, v in self.periods.items()},
                "breakdowns": {n: {k: v.as_dict() for k, v in b.items()}
                               for n, b in self.breakdowns.items()}}


BREAKDOWN_KEYS = {
    "by_mode": lambda r: r.mode,
    "by_pattern": lambda r: r.pattern,
    "by_direction": lambda r: r.direction,
    "by_grade": lambda r: r.grade,
    "by_session": lambda r: r.session or "UNKNOWN",
    "by_timeframe": lambda r: r.exec_tf or "?",
}


def build(journal: Journal) -> Report:
    all_recs = list(journal.records.values())
    rep = Report(total_records=len(all_recs))
    rep.resolved = sum(1 for r in all_recs if r.state == "CLOSED")

    for name in ("today", "week", "month"):
        start = _period_start(name)
        recs = [r for r in all_recs if (r.created_at or r.signal_ts) >= start]
        closed = [r.as_stat_trade() for r in recs
                  if r.state == "CLOSED" and r.outcome in ("WIN", "LOSS", "BREAKEVEN")]
        rep.periods[name] = Period(
            name=name, setups=len(recs),
            open=sum(1 for r in recs if r.state in ("PENDING", "ACTIVE")),
            invalidated=sum(1 for r in recs if r.state == "INVALIDATED"),
            stats=compute_bucket(name, closed))

    for name, keyfn in BREAKDOWN_KEYS.items():
        groups: dict[str, list[dict]] = {}
        for r in all_recs:
            if r.state == "CLOSED" and r.outcome in ("WIN", "LOSS", "BREAKEVEN"):
                groups.setdefault(keyfn(r), []).append(r.as_stat_trade())
        rep.breakdowns[name] = {k: compute_bucket(k, v) for k, v in sorted(groups.items())}
    return rep
