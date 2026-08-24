"""
High-impact news blackout.

Reads a CSV calendar (UTC timestamps) and blocks a configurable window either
side of each event. If no calendar file is present the filter reports that it
is INACTIVE rather than silently passing everything - a silent no-op news
filter is how backtests get flattered.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from xauusd_bot.config import NewsConfig

HIGH_IMPACT_KEYWORDS = [
    "FOMC", "Fed Interest Rate", "Federal Funds", "CPI", "Core CPI", "PCE",
    "Non-Farm", "NFP", "Unemployment Rate", "Powell", "PPI", "GDP",
    "Retail Sales", "ISM", "Jobless",
]


@dataclass
class NewsFilter:
    cfg: NewsConfig
    events: pd.DataFrame | None = None
    active: bool = False

    @classmethod
    def load(cls, cfg: NewsConfig) -> "NewsFilter":
        f = cls(cfg=cfg)
        p = Path(cfg.calendar_path)
        if not cfg.enabled or not p.exists():
            print(f"[news] calendar not found at {p} -> news filter INACTIVE")
            return f
        df = pd.read_csv(p)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        if cfg.block_high_only and "impact" in df.columns:
            df = df[df["impact"].str.upper() == "HIGH"]
        f.events = df.sort_values("time").reset_index(drop=True)
        f.active = len(df) > 0
        print(f"[news] loaded {len(df)} high-impact events -> filter ACTIVE")
        return f

    def blackout_mask(self, index: pd.DatetimeIndex) -> pd.Series:
        """True where trading is blocked."""
        if not self.active or self.events is None or self.events.empty:
            return pd.Series(False, index=index)
        mask = np.zeros(len(index), dtype=bool)
        before = pd.Timedelta(minutes=self.cfg.minutes_before)
        after = pd.Timedelta(minutes=self.cfg.minutes_after)
        idx = index.values
        for t in self.events["time"]:
            lo = np.datetime64((t - before).tz_convert("UTC").tz_localize(None))
            hi = np.datetime64((t + after).tz_convert("UTC").tz_localize(None))
            naive = index.tz_convert("UTC").tz_localize(None).values
            mask |= (naive >= lo) & (naive <= hi)
        return pd.Series(mask, index=index)
