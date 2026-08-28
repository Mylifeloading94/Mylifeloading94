"""
Risk management and persistent state (section 4 of the strategy).

  * 3% / 2.5% / 1.5% risk by grade
  * lot sizing from the real stop distance
  * stop for the day after 2 consecutive losses  (max daily risk $3,000)
  * stop for the week at -10%
  * max open positions / trades per day
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from .config import PIP_USD, USD_PER_PIP_PER_LOT

log = logging.getLogger("xauusd_smc.risk")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def day_key(now: Optional[dt.datetime] = None) -> str:
    return (now or utcnow()).strftime("%Y-%m-%d")


def week_key(now: Optional[dt.datetime] = None) -> str:
    n = now or utcnow()
    iso = n.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------
def position_size(risk_usd: float, sl_distance: float, cfg) -> float:
    """
    Lot = risk$ / (SL pips x $/pip/lot).

    `sl_distance` is in price units; for gold 1 pip = $1.00 of price and one
    lot earns $10 per pip, exactly as the strategy document specifies
    (SL 30 pips, $1,500 risk -> 5.00 lots).
    """
    sl_pips = sl_distance / PIP_USD
    if sl_pips <= 0:
        return 0.0
    raw = risk_usd / (sl_pips * USD_PER_PIP_PER_LOT)
    stepped = math.floor(raw / cfg.lot_step) * cfg.lot_step
    lots = round(min(max(stepped, 0.0), cfg.max_lots), 2)
    if lots < cfg.min_lots:
        return 0.0
    # Never let rounding push real risk past the tolerance.
    while lots > cfg.min_lots and \
            lots * sl_pips * USD_PER_PIP_PER_LOT > risk_usd * cfg.risk_overrun_tolerance:
        lots = round(lots - cfg.lot_step, 2)
    return lots


def money_risk(lots: float, sl_distance: float) -> float:
    return lots * (sl_distance / PIP_USD) * USD_PER_PIP_PER_LOT


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------
@dataclass
class RiskState:
    day: str = field(default_factory=day_key)
    week: str = field(default_factory=week_key)
    day_start_equity: float = 0.0
    week_start_equity: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    realized_today: float = 0.0
    realized_week: float = 0.0
    halted_reason: str = ""
    open_trades: Dict[str, Any] = field(default_factory=dict)
    last_setup_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RiskManager:
    def __init__(self, cfg, equity: float):
        self.cfg = cfg
        self.state = self._load(equity)

    # -- persistence -------------------------------------------------------
    def _load(self, equity: float) -> RiskState:
        path = self.cfg.state_file
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                st = RiskState(**{k: v for k, v in data.items()
                                  if k in RiskState.__dataclass_fields__})
            except (OSError, ValueError, TypeError) as e:
                log.warning("state file unreadable (%s), starting fresh", e)
                st = RiskState()
        else:
            st = RiskState()
        if not st.day_start_equity:
            st.day_start_equity = equity
        if not st.week_start_equity:
            st.week_start_equity = equity
        return st

    def save(self) -> None:
        try:
            tmp = self.cfg.state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
            os.replace(tmp, self.cfg.state_file)
        except OSError as e:
            log.error("could not save state: %s", e)

    def journal(self, record: Dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("ts", utcnow().isoformat())
        try:
            with open(self.cfg.journal_file, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            log.error("could not write journal: %s", e)

    # -- rollovers ---------------------------------------------------------
    def roll_periods(self, equity: float) -> List[str]:
        """Reset daily/weekly counters when the clock rolls over."""
        msgs = []
        today, thisweek = day_key(), week_key()
        if self.state.day != today:
            self.state.day = today
            self.state.day_start_equity = equity
            self.state.trades_today = 0
            self.state.consecutive_losses = 0
            self.state.realized_today = 0.0
            if self.state.halted_reason.startswith("daily"):
                self.state.halted_reason = ""
            msgs.append("new trading day — daily limits reset")
        if self.state.week != thisweek:
            self.state.week = thisweek
            self.state.week_start_equity = equity
            self.state.realized_week = 0.0
            if self.state.halted_reason.startswith("weekly"):
                self.state.halted_reason = ""
            msgs.append("new trading week — weekly limits reset")
        if msgs:
            self.save()
        return msgs

    # -- gates -------------------------------------------------------------
    def blocked_reason(self, equity: float, open_positions: int) -> Optional[str]:
        s, c = self.state, self.cfg
        if s.halted_reason:
            return s.halted_reason
        if s.consecutive_losses >= c.max_consecutive_losses:
            return (f"daily stop — {s.consecutive_losses} consecutive losses "
                    f"(limit {c.max_consecutive_losses})")
        day_dd = s.day_start_equity - equity
        if s.day_start_equity and day_dd >= s.day_start_equity * c.daily_loss_pct:
            return (f"daily stop — drawdown ${day_dd:,.0f} "
                    f"({c.daily_loss_pct*100:.0f}% of day-start equity)")
        week_dd = s.week_start_equity - equity
        if s.week_start_equity and week_dd >= s.week_start_equity * c.weekly_loss_pct:
            return (f"weekly stop — drawdown ${week_dd:,.0f} "
                    f"({c.weekly_loss_pct*100:.0f}% of week-start equity)")
        if s.trades_today >= c.max_trades_per_day:
            return f"max trades per day reached ({c.max_trades_per_day})"
        if open_positions >= c.max_open_positions:
            return f"already {open_positions} position(s) open"
        return None

    def latch_halt(self, reason: str) -> None:
        self.state.halted_reason = reason
        self.save()

    # -- bookkeeping -------------------------------------------------------
    def register_trade(self, record: Dict[str, Any]) -> None:
        self.state.trades_today += 1
        if record.get("position_id"):
            self.state.open_trades[str(record["position_id"])] = record
        self.save()
        self.journal({"event": "open", **record})

    def register_close(self, position_id: str, pnl: float, reason: str) -> None:
        rec = self.state.open_trades.pop(str(position_id), {})
        self.state.realized_today += pnl
        self.state.realized_week += pnl
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        self.save()
        self.journal({"event": "close", "position_id": position_id, "pnl": pnl,
                      "reason": reason, "consecutive_losses": self.state.consecutive_losses,
                      **{k: rec.get(k) for k in ("symbol", "side", "grade", "entry",
                                                 "sl", "tp1", "tp2", "lots")}})
