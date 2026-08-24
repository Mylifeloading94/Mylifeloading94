"""
Central configuration. Every number a strategy or risk rule depends on lives
here so that sensitivity testing can sweep it without touching logic.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, replace


# ---------------------------------------------------------------- instrument
@dataclass
class Instrument:
    symbol: str = "XAUUSD"
    contract_size: float = 100.0     # troy oz per 1.00 lot
    tick_size: float = 0.01          # price increment
    min_lot: float = 0.001           # micro. A 0.01 standard lot cannot be
    #                                  risked correctly on a small account: see
    #                                  README "Account size".
    max_lot: float = 50.0
    lot_step: float = 0.001
    digits: int = 2

    def money_per_price_unit(self, lots: float) -> float:
        """$ P&L for a 1.00 move in price at this position size."""
        return lots * self.contract_size


# ---------------------------------------------------------------- costs
@dataclass
class CostModel:
    """Retail XAUUSD costs. Spread is in PRICE units ($ per oz)."""
    base_spread: float = 0.25            # typical broker spread on gold
    spread_by_session: dict = field(default_factory=lambda: {
        "ASIA": 0.40, "LONDON": 0.22, "OVERLAP": 0.20,
        "NEWYORK": 0.25, "CLOSED": 1.20,
    })
    spread_vol_coef: float = 0.6         # spread widens with realised volatility
    max_spread: float = 0.60             # above this: no new trades
    commission_per_lot_round_turn: float = 0.0   # spread-only account by default
    entry_slippage: float = 0.05         # market-order slippage, price units
    stop_slippage: float = 0.12          # stops fill worse than they trigger
    stop_slippage_news: float = 0.50
    max_slippage: float = 0.60
    # Refuse a setup when the round trip (spread + both slippages) is a large
    # fraction of the target. This is the filter that makes the system
    # volatility-aware: gold at $1300 with a $0.29 spread is not scalpable,
    # gold at $4600 with the same spread is. 1.0 disables it.
    max_cost_to_target_ratio: float = 0.03


# ---------------------------------------------------------------- risk
@dataclass
class RiskConfig:
    risk_percent: float = 0.50
    max_open_positions: int = 1
    max_consecutive_losses: int = 3
    max_daily_loss_percent: float = 1.50
    max_weekly_loss_percent: float = 4.00
    max_daily_trades: int = 6
    min_rr: float = 0.9
    allow_min_lot_override: bool = False  # if True, take min lot even if it
    #                                       exceeds risk_percent (NOT default)
    max_risk_percent_hard_cap: float = 1.00  # never risk more than this


# ---------------------------------------------------------------- stops/targets
@dataclass
class ExitConfig:
    stop_scale: float = 3.0           # multiplies the structural stop distance.
    #                                   Validated on 2024-25: wider stops with
    #                                   proportionally larger targets beat tight
    #                                   stops, because the round-trip cost then
    #                                   becomes a small fraction of the target.
    atr_mult_sl: float = 1.1          # ATR floor for the stop
    structure_buffer_atr: float = 0.25  # buffer beyond the invalidation swing
    min_sl_price: float = 1.20        # never place a stop tighter than this ($)
    max_sl_atr: float = 4.0           # reject setups needing an absurd stop
    tp_model: str = "full"            # full | partial | trail | structure
    tp1_r: float = 1.0                # validated geometry: wide stop, 1R target
    tp2_r: float = 1.0
    partial_frac: float = 0.5
    breakeven_at_r: float = 99.0      # OFF: never validated, and each such
    #                                   knob is a free parameter that flatters
    #                                   the backtest without earning its keep
    be_buffer_atr: float = 0.05
    trail_start_r: float = 99.0       # OFF, same reason
    trail_atr_mult: float = 1.5
    max_hold_minutes: int = 480
    time_stop_min_r: float = 0.0      # exit at max_hold regardless


# ---------------------------------------------------------------- session/hours
@dataclass
class SessionConfig:
    enabled_sessions: tuple = ("ASIA", "LONDON", "OVERLAP", "NEWYORK")
    trade_start_utc: int = 0
    trade_end_utc: int = 20           # last minute a trade may be OPENED
    friday_cutoff_utc: int = 16
    flat_by_utc: int = 21             # force-close everything (no overnight)
    trade_days: tuple = (0, 1, 2, 3, 4)


# ---------------------------------------------------------------- regime
@dataclass
class RegimeConfig:
    adx_trend: float = 22.0
    adx_strong: float = 30.0
    adx_chop: float = 18.0
    atr_rank_low: float = 0.20
    atr_rank_high: float = 0.85
    bbw_rank_compression: float = 0.20
    min_confidence: float = 0.55
    vol_floor_atr_pct: float = 0.0004   # M5 ATR / price below this = dead market
    vol_ceiling_atr_pct: float = 0.0055


# ---------------------------------------------------------------- scoring
@dataclass
class EntryGate:
    """Hard component requirements, on top of the numeric setup score."""
    require_retest: bool = True
    require_m15_alignment: bool = True
    require_h1_alignment: bool = False
    require_ltf_structure: bool = False


@dataclass
class ScoreConfig:
    w_h1_regime: float = 15
    w_m15_structure: float = 15
    w_m5_momentum: float = 10
    w_vwap: float = 10
    w_liquidity: float = 15
    w_ltf_structure: float = 15
    w_retest: float = 10
    w_atr: float = 5
    w_spread: float = 5
    threshold: float = 0.0            # superseded by the hard EntryGate
    grade_a_plus: float = 90.0
    grade_a: float = 85.0
    grade_b: float = 75.0


# ---------------------------------------------------------------- strategies
@dataclass
class StrategyToggles:
    trend_continuation: bool = True
    liquidity_reversal: bool = True
    breakout: bool = True


@dataclass
class TrendConfig:
    max_extension_atr: float = 2.2     # don't buy > this many ATR above EMA20
    min_pullback_atr: float = 0.25     # require an actual pullback
    require_ltf_bos: bool = True
    require_retest: bool = False
    min_adx: float = 20.0
    entry_window_bars: int = 12        # M1 bars a trigger stays valid
    pullback_window: int = 20          # M1 bars a completed pullback stays valid


@dataclass
class LiquidityConfig:
    sweep_tol_atr: float = 0.10        # how far beyond the level counts as a sweep
    max_sweep_age_bars: int = 30       # M1 bars from sweep to entry
    require_displacement: bool = True
    require_choch: bool = True
    min_level_age_min: int = 30
    max_adx: float = 40.0


@dataclass
class BreakoutConfig:
    compression_bbw_rank: float = 0.25
    min_compression_bars: int = 8      # M15 bars in compression
    breakout_buffer_atr: float = 0.10
    max_chase_atr: float = 1.0         # don't enter > this far past the level
    require_momentum: bool = True
    retest_optional: bool = True


# ---------------------------------------------------------------- news
@dataclass
class NewsConfig:
    enabled: bool = True
    minutes_before: int = 30
    minutes_after: int = 30
    calendar_path: str = "xauusd_bot/config/news_calendar.csv"
    block_high_only: bool = True


# ---------------------------------------------------------------- execution
@dataclass
class ExecutionConfig:
    max_data_age_seconds: int = 90
    order_timeout_seconds: int = 10
    max_retries: int = 2
    verify_sl_tp: bool = True
    halt_on_unknown: bool = True


# ---------------------------------------------------------------- root
@dataclass
class Config:
    instrument: Instrument = field(default_factory=Instrument)
    costs: CostModel = field(default_factory=CostModel)
    risk: RiskConfig = field(default_factory=RiskConfig)
    exits: ExitConfig = field(default_factory=ExitConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    gate: EntryGate = field(default_factory=EntryGate)
    toggles: StrategyToggles = field(default_factory=StrategyToggles)
    trend: TrendConfig = field(default_factory=TrendConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    breakout: BreakoutConfig = field(default_factory=BreakoutConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    initial_equity: float = 500.0
    live_trading: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def with_overrides(self, **kw) -> "Config":
        """Dotted overrides, e.g. cfg.with_overrides(**{'trend.min_adx': 25})."""
        import copy
        c = copy.deepcopy(self)
        for key, val in kw.items():
            obj = c
            parts = key.split(".")
            for p in parts[:-1]:
                obj = getattr(obj, p)
            if not hasattr(obj, parts[-1]):
                raise KeyError(f"unknown config key: {key}")
            setattr(obj, parts[-1], val)
        return c


def from_env() -> Config:
    c = Config()
    g = os.environ.get
    c.live_trading = g("LIVE_TRADING", "false").lower() == "true"
    c.risk.risk_percent = float(g("RISK_PERCENT", c.risk.risk_percent))
    c.risk.max_daily_loss_percent = float(g("MAX_DAILY_LOSS_PERCENT", c.risk.max_daily_loss_percent))
    c.risk.max_weekly_loss_percent = float(g("MAX_WEEKLY_LOSS_PERCENT", c.risk.max_weekly_loss_percent))
    c.risk.max_consecutive_losses = int(g("MAX_CONSECUTIVE_LOSSES", c.risk.max_consecutive_losses))
    c.risk.max_daily_trades = int(g("MAX_DAILY_TRADES", c.risk.max_daily_trades))
    if g("MAX_SPREAD"):
        c.costs.max_spread = float(g("MAX_SPREAD"))
    if g("MAX_SLIPPAGE"):
        c.costs.max_slippage = float(g("MAX_SLIPPAGE"))
    if g("MIN_LOT"):
        c.instrument.min_lot = float(g("MIN_LOT"))
        c.instrument.lot_step = float(g("LOT_STEP", g("MIN_LOT")))
    c.toggles.trend_continuation = g("TREND_CONTINUATION", "true").lower() == "true"
    c.toggles.liquidity_reversal = g("LIQUIDITY_REVERSAL", "true").lower() == "true"
    c.toggles.breakout = g("BREAKOUT", "true").lower() == "true"
    return c
