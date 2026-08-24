"""
Risk Engine. Every trade must be approved here. It is also the component that
makes doing nothing possible - most calls return a rejection.

Hard prohibitions (spec section 13): no martingale, no grid, no averaging down,
no size increase after a loss, no stop removal. These are enforced structurally
(size only ever derives from equity * risk_percent, and the engine refuses a
second position in the symbol) and asserted in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from xauusd_bot.config import Config
from xauusd_bot.risk.position_sizer import SizingResult, size_position


@dataclass
class RiskDecision:
    approved: bool
    reason: str = ""
    sizing: SizingResult | None = None


@dataclass
class RiskState:
    equity: float
    start_equity: float
    day_start_equity: float
    week_start_equity: float
    tday: object = None
    week_key: object = None
    trades_today: int = 0
    consecutive_losses: int = 0
    daily_locked: bool = False
    weekly_locked: bool = False
    open_positions: int = 0
    peak_equity: float = 0.0
    max_dd: float = 0.0
    lock_events: list = field(default_factory=list)


class RiskManager:
    def __init__(self, cfg: Config, equity: float):
        self.cfg = cfg
        self.s = RiskState(equity=equity, start_equity=equity,
                           day_start_equity=equity, week_start_equity=equity,
                           peak_equity=equity)
        self.rejections: dict[str, int] = {}

    # ------------------------------------------------ day / week rollover
    def on_bar(self, ts: pd.Timestamp, tday, equity: float) -> None:
        self.s.equity = equity
        if equity > self.s.peak_equity:
            self.s.peak_equity = equity
        dd = (self.s.peak_equity - equity) / self.s.peak_equity if self.s.peak_equity else 0.0
        self.s.max_dd = max(self.s.max_dd, dd)

        if self.s.tday is None:
            self.s.tday = tday
        elif tday != self.s.tday:
            self.s.tday = tday
            self.s.day_start_equity = equity
            self.s.trades_today = 0
            self.s.daily_locked = False
            # The consecutive-loss lock is a DAILY circuit breaker. Without a
            # reset it latches forever after the first three losses and the
            # system never trades again - which silently flatters a backtest
            # by hiding every subsequent trade.
            self.s.consecutive_losses = 0

        wk = (ts.isocalendar().year, ts.isocalendar().week)
        if self.s.week_key is None:
            self.s.week_key = wk
        elif wk != self.s.week_key:
            self.s.week_key = wk
            self.s.week_start_equity = equity
            self.s.weekly_locked = False

    # ------------------------------------------------ live loss locks
    def _daily_pl_pct(self) -> float:
        return 100.0 * (self.s.equity - self.s.day_start_equity) / self.s.day_start_equity

    def _weekly_pl_pct(self) -> float:
        return 100.0 * (self.s.equity - self.s.week_start_equity) / self.s.week_start_equity

    def check_locks(self, ts) -> None:
        r = self.cfg.risk
        if not self.s.daily_locked and self._daily_pl_pct() <= -r.max_daily_loss_percent:
            self.s.daily_locked = True
            self.s.lock_events.append((ts, "DAILY_LOSS_LOCK", self._daily_pl_pct()))
        if not self.s.weekly_locked and self._weekly_pl_pct() <= -r.max_weekly_loss_percent:
            self.s.weekly_locked = True
            self.s.lock_events.append((ts, "WEEKLY_LOSS_LOCK", self._weekly_pl_pct()))

    # ------------------------------------------------ approval
    def _reject(self, reason: str) -> RiskDecision:
        self.rejections[reason] = self.rejections.get(reason, 0) + 1
        return RiskDecision(False, reason)

    def approve(self, entry: float, stop: float, tp: float, direction: int) -> RiskDecision:
        r = self.cfg.risk
        if self.s.weekly_locked:
            return self._reject("weekly_loss_lock")
        if self.s.daily_locked:
            return self._reject("daily_loss_lock")
        if self.s.open_positions >= r.max_open_positions:
            return self._reject("max_open_positions")
        if self.s.trades_today >= r.max_daily_trades:
            return self._reject("max_daily_trades")
        if self.s.consecutive_losses >= r.max_consecutive_losses:
            return self._reject("consecutive_loss_lock")
        if stop is None or not (stop == stop):
            return self._reject("no_valid_stop")
        if direction > 0 and not (stop < entry):
            return self._reject("stop_on_wrong_side")
        if direction < 0 and not (stop > entry):
            return self._reject("stop_on_wrong_side")

        risk_dist = abs(entry - stop)
        reward_dist = abs(tp - entry)
        if risk_dist <= 0:
            return self._reject("zero_risk_distance")
        if reward_dist / risk_dist < r.min_rr:
            return self._reject("insufficient_rr")

        sz = size_position(self.s.equity, entry, stop, self.cfg)
        if not sz.ok:
            return self._reject("position_size_" +
                                ("below_min_lot" if "min lot" in sz.reason else "invalid"))
        return RiskDecision(True, "approved", sz)

    # ------------------------------------------------ outcome bookkeeping
    def on_open(self) -> None:
        self.s.open_positions += 1
        self.s.trades_today += 1

    def on_close(self, pnl: float, equity: float, ts) -> None:
        self.s.open_positions = max(0, self.s.open_positions - 1)
        self.s.equity = equity
        if pnl < 0:
            self.s.consecutive_losses += 1
        elif pnl > 0:
            self.s.consecutive_losses = 0
        self.check_locks(ts)
