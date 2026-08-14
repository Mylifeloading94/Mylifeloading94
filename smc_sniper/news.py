"""News blackout filter.

The engine is complete and config-driven, but there is an honest caveat that is
repeated in every report: **no historical economic calendar is available in
this environment**, so the backtests reported here run *without* news
filtering. That makes results slightly pessimistic in one sense (some losing
news-spike trades would have been skipped) and unvalidated in another (the
filter's real effect is unmeasured).

To activate it, supply ``news.calendar_file`` as a CSV with columns
``utc_timestamp,impact,event`` and re-run. The filter then blocks any signal
within the configured window of a high-impact event.
"""
from __future__ import annotations

import os

import pandas as pd


class NewsFilter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ncfg = cfg.get("news", {}) or {}
        self.enabled = bool(self.ncfg.get("enabled", True))
        self.events: pd.DataFrame | None = None
        self.active = False
        self.status = "disabled"
        if self.enabled:
            self._load()

    def _load(self) -> None:
        path = self.cfg.resolve_path(self.ncfg.get("calendar_file"))
        if not path or not os.path.exists(path):
            self.status = "no_calendar_file"
            behaviour = self.ncfg.get("on_missing_calendar", "warn")
            msg = ("news filter ENABLED but no calendar file supplied -- "
                   "backtests run WITHOUT news filtering (documented caveat)")
            if behaviour == "fail":
                raise RuntimeError(msg)
            self.warning = msg
            return
        frame = pd.read_csv(path)
        frame["utc_timestamp"] = pd.to_datetime(frame["utc_timestamp"], utc=True)
        high = set(self.ncfg.get("high_impact_events", []))
        if high and "event" in frame:
            frame = frame[frame["event"].str.upper().isin({e.upper() for e in high})
                          | frame.get("impact", "").astype(str).str.lower().eq("high")]
        self.events = frame.sort_values("utc_timestamp").reset_index(drop=True)
        self.active = True
        self.status = f"loaded {len(self.events)} events"

    def blocked(self, ts: pd.Timestamp) -> tuple[bool, str]:
        """Is ``ts`` inside a blackout window?"""
        if not self.active or self.events is None or self.events.empty:
            return False, ""
        before = pd.Timedelta(minutes=float(self.ncfg.get("blackout_minutes_before", 30)))
        after = pd.Timedelta(minutes=float(self.ncfg.get("blackout_minutes_after", 30)))
        times = self.events["utc_timestamp"]
        hit = self.events[(times - before <= ts) & (ts <= times + after)]
        if hit.empty:
            return False, ""
        return True, f"news_blackout_{hit.iloc[0].get('event', 'high_impact')}"
