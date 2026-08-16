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


# Quote-currency -> USD conversion, used to express a contract's value in the
# account currency. Window medians of the broker's own 1H closes over the
# ~1200-day backtest window (USDJPY 150.256, USDCHF 0.86251, USDCAD 1.3724,
# AUDUSD 0.65828, NZDUSD 0.59461, GBPUSD 1.29417). A static median is used
# rather than a time-varying rate because the only quantity it touches is the
# commission drag, which is 2-4% of R; a +/-20% rate error moves that by well
# under a hundredth of an R. Documented rather than hidden.
_QUOTE_USD = {
    "USD": 1.0,
    "JPY": 1.0 / 150.256,
    "CHF": 1.0 / 0.86251,
    "CAD": 1.0 / 1.3724,
    "AUD": 0.65828,
    "NZD": 0.59461,
    "GBP": 1.29417,
    "EUR": 1.09751,
}


def contract_value(symbol: str, icfg, quote_conversion: bool = False) -> float:
    """Value in USD of a 1.00-lot position moving 1.0 price unit.

    FX standard lot = 100,000 units of base; gold is 100 oz.

    v5 AUDIT FIX (``risk.quote_ccy_conversion``). The original returned a flat
    100,000 for every non-metal pair, which is only correct when the QUOTE
    currency is USD. A 1.0-price-unit move on 1 lot of USDJPY is 100,000 *JPY*,
    about $666 -- not $100,000. The consequence was not in the R statistics
    (``pnl`` is ``R x risk_amount`` and R is normalised by the stop) but in
    ``size_lots``, and therefore in the commission, which is charged per lot:

        measured commission drag, v2 swing ledger, by quote currency
          USD-quoted  0.0359 R      JPY-quoted  0.00019 R  (~190x too small)
          CHF-quoted  0.0320 R      CAD-quoted  0.0259 R
          NZD-quoted  0.0130 R      AUD-quoted  0.0150 R

    36% of v2's trades are on JPY crosses and were effectively trading
    commission-free, and every lot figure the system would have placed on a
    non-USD-quoted pair was wrong by the quote rate.

    Defaults to the old behaviour so v2 stays reproducible; on in the v5
    profile.
    """
    if icfg.instrument_type == "metal":
        return 100.0                      # 100 oz, quoted in USD -- already right
    if not quote_conversion:
        return 100_000.0
    return 100_000.0 * _QUOTE_USD.get(symbol[3:6].upper(), 1.0)


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
        self.quote_conversion = bool(self.rcfg.get("quote_ccy_conversion", False))
        # v5: book realised P/L at EXIT time rather than at signal time.
        self.book_on_exit = bool(self.rcfg.get("book_on_exit", False))
        self._clock = None

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
        value = contract_value(symbol, icfg, self.quote_conversion)
        if risk_price <= 0 or value <= 0:
            return 0.0, risk_amount
        lots = risk_amount / (risk_price * value)
        return round(lots, 4), risk_amount

    # -- gates -------------------------------------------------------------
    def _roll_periods(self, ts: pd.Timestamp) -> None:
        # Monotonic clock. With book-on-exit the engine sees two interleaved
        # time streams (signal times and exit times); a timestamp that runs
        # backwards must not reset the day counters.
        if self._clock is not None and ts < self._clock:
            ts = self._clock
        self._clock = ts
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

    # -- concurrency --------------------------------------------------------
    def set_open_positions(self, open_trades) -> None:
        """Tell the engine what is currently open, so the caps can bind.

        ``max_open_positions`` and ``max_exposure_per_currency`` were read by
        :meth:`can_trade` and never written by anything in the backtest path,
        which made both of them **inert**. That is the real explanation for
        v2's "raising the caps changed the result by exactly zero trades" --
        it was not setup scarcity, it was a cap that could never bind.

        It matters far more to a scalper than to a swing system: at 2% risk,
        six concurrent positions is 12% of the account live at once, and three
        of them sharing USD is one correlated bet wearing three hats.

        Enforcement is opt-in (``risk.enforce_concurrency``) purely so v2's
        published numbers stay reproducible bit-for-bit. It is ON in the scalp
        profile.
        """
        self.state.open_positions = len(open_trades)
        exposure: dict[str, int] = {}
        for trade in open_trades:
            for ccy in (trade.symbol[:3], trade.symbol[3:6]):
                exposure[ccy] = exposure.get(ccy, 0) + 1
        self.state.currency_exposure = exposure

    # -- bookkeeping --------------------------------------------------------
    def note_entry(self, ts: pd.Timestamp) -> None:
        """Count an order placed at ``ts`` against the per-day activity cap.

        v5 AUDIT FIX. ``register`` used to do everything at ``signal_time``,
        including adding the trade's realised P/L to ``day_pnl`` / ``week_pnl``
        and stepping the consecutive-loss counter. For a stack whose trades are
        held for days that books an OUTCOME before it is knowable: the
        ``max_daily_loss`` / ``max_weekly_loss`` gates and the consecutive-loss
        cooldown were being evaluated against results from positions that were
        still open. It is a lookahead in the risk layer, and it decides which
        later setups get taken. With ``risk.book_on_exit`` the entry counter
        stays on the signal clock (an order placed is an order placed) and the
        money lands on the exit clock.
        """
        self._roll_periods(ts)
        self.state.trades_today += 1

    def register(self, trade, count_entry: bool = True) -> None:
        """Record a completed trade. Losses tighten, never loosen."""
        st = self.state
        self._roll_periods(trade.exit_time if self.book_on_exit else trade.signal_time)
        if count_entry:
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
