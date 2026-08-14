"""Phase 7 -- Risk management.

Per the spec this layer outranks the win rate. It is also the layer with the
hardest guarantees:

* **No martingale.** Size is a function of balance and stop distance only --
  never of the previous result. Asserted in the test suite.
* **No grid, no revenge trading.** A loss can only ever *reduce* activity
  (consecutive-loss cooldown), never increase size or frequency.
* Daily loss, weekly loss, max open positions, trades/day, consecutive losses
  and per-currency exposure are all hard gates.

Position sizing is fixed-fractional on the *starting* balance by default
(``risk.compounding: false``) so that backtest R-multiples are not flattered by
a rising equity curve.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


def contract_value(symbol: str, icfg) -> float:
    """Approximate value of a 1.00 lot move of 1.0 price unit, in USD.

    FX standard lot = 100,000 units of base. For USD-quoted pairs one pip on
    1 lot is $10. JPY-quoted and cross pairs are approximated; gold is 100 oz.
    This is deliberately simple -- position sizing feeds R-multiples, and R is
    normalised by the stop distance, so modest contract-value error does not
    distort the R-based statistics that the report leads with.
    """
    kind = icfg.instrument_type
    if kind == "metal":
        return 100.0
    return 100_000.0


@dataclass
class RiskState:
    balance: float
    day_pnl: float = 0.0
    week_pnl: float = 0.0
    open_positions: int = 0
    consecutive_losses: int = 0
    trades_today: int = 0
    current_day: object = None
    current_week: object = None
    cooldown_until: object = None
    currency_exposure: dict = field(default_factory=dict)


class RiskEngine:
    """Enforces every hard limit and sizes positions."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.rcfg = cfg.get("risk")
        self.start_balance = float(self.rcfg.get("starting_balance", 10000.0))
        self.balance = self.start_balance
        self.state = RiskState(balance=self.start_balance)
        self.blocked: dict[str, int] = {}

    # -- sizing -----------------------------------------------------------
    def size(self, symbol: str, risk_price: float) -> tuple[float, float]:
        """Return ``(lots, risk_amount)``.

        Depends on balance and stop distance ONLY. There is no term for the
        previous trade's outcome -- that is what makes martingale structurally
        impossible rather than merely discouraged.
        """
        icfg = self.cfg.for_instrument(symbol)
        pct = icfg.risk_per_trade_pct / 100.0
        base = self.balance if self.rcfg.get("compounding", False) else self.start_balance
        risk_amount = base * pct
        value = contract_value(symbol, icfg)
        if risk_price <= 0 or value <= 0:
            return 0.0, risk_amount
        lots = risk_amount / (risk_price * value)
        return round(lots, 4), risk_amount

    # -- gates -------------------------------------------------------------
    def _roll_periods(self, ts: pd.Timestamp) -> None:
        day = ts.date()
        week = ts.isocalendar()[:2]
        if self.state.current_day != day:
            self.state.current_day = day
            self.state.day_pnl = 0.0
            self.state.trades_today = 0
        if self.state.current_week != week:
            self.state.current_week = week
            self.state.week_pnl = 0.0

    def can_trade(self, symbol: str, sig) -> tuple[bool, str]:
        ts = sig.time
        self._roll_periods(ts)
        st = self.state
        base = self.start_balance

        if st.cooldown_until is not None and ts < st.cooldown_until:
            return False, "consecutive_loss_cooldown"
        if st.trades_today >= int(self.rcfg.get("max_trades_per_day", 3)):
            return False, "max_trades_per_day"
        if st.day_pnl <= -abs(float(self.rcfg.get("max_daily_loss_pct", 2.0))) / 100 * base:
            return False, "max_daily_loss"
        if st.week_pnl <= -abs(float(self.rcfg.get("max_weekly_loss_pct", 5.0))) / 100 * base:
            return False, "max_weekly_loss"
        if st.open_positions >= int(self.rcfg.get("max_open_positions", 3)):
            return False, "max_open_positions"

        max_ccy = int(self.rcfg.get("max_exposure_per_currency", 2))
        for ccy in (symbol[:3], symbol[3:6]):
            if st.currency_exposure.get(ccy, 0) >= max_ccy:
                return False, f"max_exposure_{ccy}"
        return True, ""

    # -- bookkeeping --------------------------------------------------------
    def register(self, trade) -> None:
        """Record a completed trade. Losses tighten, never loosen."""
        st = self.state
        self._roll_periods(trade.signal_time)
        st.trades_today += 1
        st.day_pnl += trade.pnl
        st.week_pnl += trade.pnl
        self.balance += trade.pnl
        st.balance = self.balance

        if trade.r_multiple < 0:
            st.consecutive_losses += 1
            limit = int(self.rcfg.get("max_consecutive_losses", 4))
            if st.consecutive_losses >= limit:
                hours = float(self.rcfg.get("consecutive_loss_cooldown_hours", 24))
                st.cooldown_until = trade.exit_time + pd.Timedelta(hours=hours)
                st.consecutive_losses = 0
        else:
            st.consecutive_losses = 0
