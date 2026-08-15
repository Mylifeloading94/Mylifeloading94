"""
SMC Sniper — central configuration (spec §28).

Nothing that changes trading behaviour should be hard-coded anywhere else in
the smc_sniper package. Every module reads its thresholds from `CONFIG`
(a `SniperConfig` instance) so a single file governs the bot's behaviour.

IMPORTANT: the defaults below are the VALIDATED config from the 90-day
honest-fill backtest (see sniper_smc.py / sniper_backtest.py docstrings —
70.0% WR, PF 2.17, holds out-of-sample). Changing MIN_SETUP_SCORE, OTE band,
displacement multiplier, or TP/SL logic invalidates that result until
re-backtested. Treat any edit here as "needs a fresh backtest", not a free
tuning knob.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# §1 Watchlist — forex + gold only, no crypto.
# ---------------------------------------------------------------------------
FOREX_WATCHLIST: List[str] = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD",
    "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "CADJPY",
]
GOLD_WATCHLIST: List[str] = ["XAUUSD"]

# Broker instrument specs (id / pip size / pip value per 1.0 lot).
# Pulled from trading_agent.MARKETS where available; CADJPY is not yet
# configured on the connected broker account, so it is listed but flagged
# `configured=False` — the scanner refuses to size/trade any symbol that
# is not fully specified (safety §27: "never trade outside watchlist").
INSTRUMENTS: Dict[str, Dict] = {
    "EURUSD": {"pip": 0.0001, "pip_val": 10.00, "configured": True},
    "GBPUSD": {"pip": 0.0001, "pip_val": 10.00, "configured": True},
    "USDJPY": {"pip": 0.01,   "pip_val": 6.70,  "configured": True},
    "USDCHF": {"pip": 0.0001, "pip_val": 10.00, "configured": True},
    "USDCAD": {"pip": 0.0001, "pip_val": 7.30,  "configured": True},
    "AUDUSD": {"pip": 0.0001, "pip_val": 10.00, "configured": True},
    "NZDUSD": {"pip": 0.0001, "pip_val": 10.00, "configured": True},
    "EURJPY": {"pip": 0.01,   "pip_val": 6.70,  "configured": True},
    "GBPJPY": {"pip": 0.01,   "pip_val": 6.70,  "configured": True},
    "EURGBP": {"pip": 0.0001, "pip_val": 12.50, "configured": True},
    "AUDJPY": {"pip": 0.01,   "pip_val": 6.70,  "configured": True},
    "CADJPY": {"pip": 0.01,   "pip_val": 6.70,  "configured": False},
    "XAUUSD": {"pip": 0.1,    "pip_val": 1.00,  "configured": True},
}

# Currency correlation groups (§14) — no two simultaneous trades whose
# combined directional exposure to one currency exceeds MAX_CORRELATED_RISK.
CURRENCY_GROUPS: Dict[str, List[str]] = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "XAUUSD"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CADJPY"],
    "EUR": ["EURUSD", "EURJPY", "EURGBP"],
    "GBP": ["GBPUSD", "GBPJPY", "EURGBP"],
    "CAD": ["USDCAD", "CADJPY"],
    "AUD": ["AUDUSD", "AUDJPY"],
    "GOLD": ["XAUUSD"],
}


@dataclass(frozen=True)
class SniperConfig:
    # --- watchlist -----------------------------------------------------
    watchlist: Tuple[str, ...] = tuple(FOREX_WATCHLIST + GOLD_WATCHLIST)

    # --- §6 setup scoring -----------------------------------------------
    MIN_SETUP_SCORE: int = 85          # 0-100, configurable trade gate
    SCORE_WEIGHTS: Dict[str, int] = field(default_factory=lambda: {
        "htf_alignment": 20,
        "liquidity_sweep": 20,
        "structure_shift": 15,   # BOS / CHoCH / MSS
        "displacement": 10,
        "order_block": 10,
        "fvg": 10,
        "premium_discount": 5,
        "session": 5,
        "risk_reward": 5,
    })

    # --- §7 trade frequency ----------------------------------------------
    TARGET_SETUP_COUNT: Tuple[int, int] = (2, 3)   # target only, never forced
    MAX_DAILY_TRADES: int = 3

    # --- §8 risk management ----------------------------------------------
    RISK_PER_TRADE: float = 0.02        # 2% of equity per trade
    MAX_RISK_PER_TRADE: float = 0.02    # hard ceiling — never exceeded

    # --- §10 reward ----------------------------------------------------
    MIN_RR: float = 1.5
    PREFERRED_RR: Tuple[float, float] = (2.0, 3.0)

    # --- §11 trade management -------------------------------------------
    BREAK_EVEN_R: float = 1.0
    PARTIAL_TP_ENABLED: bool = True
    PARTIAL_TARGETS: Tuple[Tuple[float, float], ...] = ((1.0, 0.5), (2.5, 0.5))
    # (R multiple, % of position closed) — TP1 1R/50%, TP2(runner) 2.5R/50%.
    TRAILING_STOP_ENABLED: bool = False   # only enable if backtest proves it helps

    # --- §12/13 session + news --------------------------------------------
    SESSIONS_UTC: Dict[str, Tuple[int, int]] = field(default_factory=lambda: {
        # (start_hour*60+min, end_hour*60+min) prime killzones, validated.
        "london_open":   (7 * 60, 9 * 60),
        "ny_overlap":     (12 * 60 + 30, 14 * 60 + 30),
    })
    NEWS_BLACKOUT_BEFORE_MIN: int = 30
    NEWS_BLACKOUT_AFTER_MIN: int = 15
    NEWS_HIGH_IMPACT_ONLY: bool = True

    # --- §14 correlation ---------------------------------------------------
    MAX_CORRELATED_RISK: float = 0.02   # max combined directional risk (as
                                          # fraction of equity) per currency
    MAX_OPEN_PER_CURRENCY: int = 1

    # --- §15 daily protection ------------------------------------------
    MAX_DAILY_LOSS_PCT: float = 0.04
    MAX_CONSECUTIVE_LOSSES: int = 2
    CONSEC_LOSS_COOLDOWN_MIN: int = 120

    # --- §9 stop loss ------------------------------------------------
    SPREAD_BUFFER_MULT: float = 3.0     # SL buffer >= N * spread
    VOLATILITY_BUFFER_ATR: float = 0.5  # SL buffer >= N * ATR
    MAX_SPREAD_PIPS: Dict[str, float] = field(default_factory=lambda: {
        "EURUSD": 1.5, "GBPUSD": 2.0, "USDJPY": 1.8, "USDCHF": 2.2,
        "USDCAD": 2.5, "AUDUSD": 1.8, "NZDUSD": 2.5, "EURJPY": 2.5,
        "GBPJPY": 3.5, "EURGBP": 2.2, "AUDJPY": 3.0, "CADJPY": 3.0,
        "XAUUSD": 5.0,
    })

    # --- entry model (validated core engine — see sniper_smc.py) --------
    DISPLACEMENT_ATR_MULT: float = 1.1
    OTE_BAND: Tuple[float, float] = (0.62, 0.90)
    RETRACE_WINDOW_BARS: int = 8

    def with_overrides(self, **kwargs) -> "SniperConfig":
        """Return a copy with fields overridden — use for backtests / A-B runs,
        never mutate CONFIG in place."""
        return replace(self, **kwargs)


CONFIG = SniperConfig()
