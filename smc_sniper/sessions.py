"""Trading sessions (UTC).

The repo's history contains session filters that looked excellent in TRAIN and
then *inverted* on TEST. So sessions here are treated as a hypothesis to be
validated in walk-forward, never as a free win: the filter is config-driven,
defaults to London+NY per the spec, and the walk-forward report scores every
session separately so an inversion is visible rather than hidden.
"""
from __future__ import annotations

import pandas as pd

DEFAULT_DEFS = {
    "asian":   {"start": 0,  "end": 7},
    "london":  {"start": 7,  "end": 12},
    "ny":      {"start": 12, "end": 17},
    "late_ny": {"start": 17, "end": 21},
    "dead":    {"start": 21, "end": 24},
}


def session_of(ts: pd.Timestamp, cfg: dict | None = None) -> str:
    """Name of the session containing ``ts`` (UTC)."""
    defs = (cfg or {}).get("definitions", DEFAULT_DEFS) if cfg else DEFAULT_DEFS
    hour = ts.hour
    for name, window in defs.items():
        if window["start"] <= hour < window["end"]:
            return name
    return "unknown"


def is_tradeable(ts: pd.Timestamp, cfg: dict, allowed: list[str] | None = None) -> tuple[bool, str]:
    """Session gate. Returns ``(ok, reason_if_blocked)``."""
    if not cfg.get("enabled", True):
        return True, ""
    name = session_of(ts, cfg)
    allowed = allowed if allowed is not None else cfg.get("allowed", [])

    # Weekend / illiquid edges
    if cfg.get("skip_sunday_open", True) and ts.dayofweek == 6:
        return False, "sunday_open"
    friday_cut = cfg.get("skip_friday_after_utc")
    if friday_cut is not None and ts.dayofweek == 4 and ts.hour >= int(friday_cut):
        return False, "friday_late"
    if ts.dayofweek == 5:
        return False, "saturday"

    if cfg.get("avoid_low_liquidity", True) and name in ("dead", "unknown"):
        return False, f"low_liquidity_{name}"
    if allowed and name not in allowed:
        return False, f"session_{name}_not_allowed"
    return True, ""


def session_series(index: pd.DatetimeIndex, cfg: dict | None = None) -> pd.Series:
    return pd.Series([session_of(ts, cfg) for ts in index], index=index)
