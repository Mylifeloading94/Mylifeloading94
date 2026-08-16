"""
SMC Sniper — Daily Risk Protection (spec §15, §27).

Tracks per-UTC-day state (starting equity, trade count, consecutive
losses) in a small JSON file so guardrails survive process restarts —
the same pattern already used by autopilot.py's agent_state.json, kept
separate here (smc_sniper_daily_state.json) so this package doesn't share
mutable state with the older scripts.

Enforces, in order:
  - MAX_DAILY_LOSS_PCT: equity drawdown from day-start halts new entries
    for the rest of the day.
  - MAX_CONSECUTIVE_LOSSES: N losses in a row triggers a cooldown before
    new entries resume.
  - MAX_DAILY_TRADES: hard cap on entries per day.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .config import SniperConfig, CONFIG

DEFAULT_STATE_PATH = Path("smc_sniper_daily_state.json")


@dataclass
class DailyState:
    trade_date: str
    day_start_equity: float
    trades_today: int = 0
    consecutive_losses: int = 0
    cooldown_until: Optional[str] = None   # ISO timestamp
    results_today: List[float] = None      # R multiples, in order

    def __post_init__(self):
        if self.results_today is None:
            self.results_today = []


def load_state(equity: float, path: Path = DEFAULT_STATE_PATH, now: Optional[datetime] = None) -> DailyState:
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            if raw.get("trade_date") == today:
                return DailyState(**raw)
        except (json.JSONDecodeError, TypeError):
            pass
    state = DailyState(trade_date=today, day_start_equity=equity)
    save_state(state, path)
    return state


def save_state(state: DailyState, path: Path = DEFAULT_STATE_PATH) -> None:
    path.write_text(json.dumps(asdict(state), indent=2))


def record_trade_opened(state: DailyState, path: Path = DEFAULT_STATE_PATH) -> DailyState:
    state.trades_today += 1
    save_state(state, path)
    return state


def record_trade_closed(
    state: DailyState,
    r_multiple: float,
    cfg: SniperConfig = CONFIG,
    path: Path = DEFAULT_STATE_PATH,
    now: Optional[datetime] = None,
) -> DailyState:
    now = now or datetime.now(timezone.utc)
    state.results_today.append(r_multiple)
    if r_multiple < -0.05:
        state.consecutive_losses += 1
        if state.consecutive_losses >= cfg.MAX_CONSECUTIVE_LOSSES:
            cooldown_end = now + timedelta(minutes=cfg.CONSEC_LOSS_COOLDOWN_MIN)
            state.cooldown_until = cooldown_end.isoformat()
    else:
        state.consecutive_losses = 0
        state.cooldown_until = None
    save_state(state, path)
    return state


def can_trade(
    state: DailyState,
    current_equity: float,
    cfg: SniperConfig = CONFIG,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)

    if state.trades_today >= cfg.MAX_DAILY_TRADES:
        return False, f"max daily trades reached ({state.trades_today}/{cfg.MAX_DAILY_TRADES})"

    loss_floor = state.day_start_equity * (1 - cfg.MAX_DAILY_LOSS_PCT)
    if current_equity <= loss_floor:
        dd = (state.day_start_equity - current_equity) / state.day_start_equity
        return False, (f"max daily loss hit: equity ${current_equity:,.2f} <= floor "
                        f"${loss_floor:,.2f} (-{dd:.2%} of day-start equity)")

    if state.cooldown_until:
        cooldown_end = datetime.fromisoformat(state.cooldown_until)
        if now < cooldown_end:
            mins_left = int((cooldown_end - now).total_seconds() / 60)
            return False, (f"consecutive-loss cooldown active ({state.consecutive_losses} losses in a row), "
                            f"{mins_left} min remaining")

    return True, "ok"
