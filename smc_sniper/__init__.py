"""
SMC Sniper — modular Smart Money Concepts trading system (spec architecture §26).

This package layers configuration, scoring, risk, correlation, news,
daily-guardrail, journaling, and validation modules on top of the
already-validated core sniper entry engine in sniper_smc.py /
sniper_backtest.py (see those files' docstrings for the honest-fill
backtest results this system is built to protect, not curve-fit past).

See smc_sniper/README.md for the module map and phased development status.
"""
from .config import CONFIG, SniperConfig
from .scoring import score_setup, rank_setups, ScoreBreakdown
from .risk import position_size, RiskViolation, PositionSize
from .correlation import check_correlation, CorrelationResult
from .news_filter import is_blackout_active, FileNewsCalendar, EmptyNewsCalendar, NewsEvent
from .daily_guardrails import load_state as load_daily_state, can_trade, record_trade_opened, record_trade_closed
from .scanner import run_pipeline, ExecutionPlan, RejectedSetup
from .explain import explain_setup, format_explanation
from . import journal
from . import backtest_report
from . import walk_forward
from . import monte_carlo

# NOTE: live_runner is intentionally NOT imported here. It pulls in
# trading_agent.py, which requires TL_EMAIL/TL_PASSWORD to be set just to
# import — every other module in this package works standalone (backtests,
# scoring, sizing, journaling) without live credentials. Import it
# explicitly when you actually want live execution:
#   from smc_sniper import live_runner

__all__ = [
    "CONFIG", "SniperConfig",
    "score_setup", "rank_setups", "ScoreBreakdown",
    "position_size", "RiskViolation", "PositionSize",
    "check_correlation", "CorrelationResult",
    "is_blackout_active", "FileNewsCalendar", "EmptyNewsCalendar", "NewsEvent",
    "load_daily_state", "can_trade", "record_trade_opened", "record_trade_closed",
    "run_pipeline", "ExecutionPlan", "RejectedSetup",
    "explain_setup", "format_explanation",
    "journal", "backtest_report", "walk_forward", "monte_carlo",
]
