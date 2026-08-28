"""Configuration: modes, strategy parameters, grading weights, risk limits."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

SYMBOL = "XAUUSD"


# --------------------------------------------------------------------------
# Trading modes (spec §6) — each maps to its own timeframe stack (spec §4)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ModeSpec:
    name: str
    htf: str          # major bias / dealing range
    mtf: str          # secondary bias confirmation
    ltf: str          # execution structure: sweep, MSS/BOS, displacement
    ttf: str          # trigger timeframe: entry refinement (sniper fill)
    bars: dict[str, int]
    sl_buffer_atr: float      # stop beyond the sweep extreme, in LTF ATR
    min_sl_pips: float        # floor so spread/noise cannot take the stop
    max_sl_pips: float        # ceiling so a "setup" can't become an investment
    tp_r: tuple[float, ...]   # R-multiple floors for TP1/TP2/TP3
    min_rr: float             # measured to TP2
    max_age_bars: int         # how many LTF bars a sequence stays actionable
    entry_tolerance_atr: float  # how far outside the zone price may sit and still count
    typical_hold_bars: int    # LTF bars used as the backtest time-stop

    @property
    def timeframes(self) -> list[str]:
        return sorted(set([self.htf, self.mtf, self.ltf, self.ttf]))


MODES: dict[str, ModeSpec] = {
    "SCALP": ModeSpec(
        name="SCALP", htf="H1", mtf="M15", ltf="M5", ttf="M1",
        bars={"H1": 300, "M15": 400, "M5": 500, "M1": 400},
        sl_buffer_atr=0.35, min_sl_pips=25, max_sl_pips=150,
        tp_r=(1.0, 2.0, 3.0), min_rr=1.8, max_age_bars=10,
        entry_tolerance_atr=0.25, typical_hold_bars=48),
    "INTRADAY": ModeSpec(
        name="INTRADAY", htf="H4", mtf="H1", ltf="M15", ttf="M5",
        bars={"H4": 250, "H1": 300, "M15": 500, "M5": 400},
        sl_buffer_atr=0.45, min_sl_pips=45, max_sl_pips=350,
        tp_r=(1.0, 2.0, 3.5), min_rr=2.0, max_age_bars=8,
        entry_tolerance_atr=0.30, typical_hold_bars=48),
    "SWING": ModeSpec(
        name="SWING", htf="H4", mtf="H4", ltf="H1", ttf="M15",
        bars={"H4": 300, "H1": 400, "M15": 400},
        sl_buffer_atr=0.60, min_sl_pips=120, max_sl_pips=900,
        tp_r=(1.0, 2.5, 4.0), min_rr=2.2, max_age_bars=6,
        entry_tolerance_atr=0.35, typical_hold_bars=60),
}


# --------------------------------------------------------------------------
# Strategy detection parameters
# --------------------------------------------------------------------------
@dataclass
class StrategyConfig:
    swing_strength_htf: int = 2
    swing_strength_ltf: int = 2
    sweep_lookback_bars: int = 14        # window scanned for a completed sweep
    mss_within_bars: int = 5             # MSS must follow the sweep this quickly
    displacement_atr: float = 1.0        # impulse body >= this x ATR
    displacement_body_ratio: float = 0.50
    min_sweep_rejection_atr: float = 0.20
    fvg_min_size_atr: float = 0.15
    ob_disp_mult: float = 1.0
    consolidation_bars: int = 20         # breakout pattern: compression window
    consolidation_max_atr: float = 3.2   # range height <= this x ATR = coiled
    ote_band: tuple[float, float] = (0.618, 0.90)
    min_confluences: int = 5             # hard floor on confluence count


# --------------------------------------------------------------------------
# Grading weights (spec §8) — must total 100
# --------------------------------------------------------------------------
# These ten components are MARKET facts only, and they total 100.
#
# Historical performance is deliberately NOT one of them. If history fed the
# score, the score would set the grade, the grade would select the historical
# bucket, and that bucket would then feed the score — a loop that quietly
# invents an edge. Instead history is applied afterwards as a one-way VETO
# (see grading.apply_history_veto): a configuration measured to lose money is
# struck out, but no configuration is ever promoted by its own statistics.
# That keeps the backtest's grade buckets and the live grades directly
# comparable, which is the whole point of publishing a sample size.
GRADE_WEIGHTS: dict[str, float] = {
    "htf_bias": 15,          # 4H/1H (mode-relative) direction agreement
    "liquidity": 13,         # quality of the pool that was taken
    "structure": 10,         # clean, readable structure on the execution TF
    "mss_bos": 13,           # the confirming structure break
    "displacement": 10,      # institutional footprint of the impulse
    "fvg": 11,               # a real, unmitigated imbalance to enter from
    "order_block": 8,        # an aligned OB backing the zone
    "premium_discount": 11,  # entering from the right half of the range (+OTE)
    "session": 6,            # killzone conditions
    "volatility": 3,         # regime fit
}

GRADE_BANDS = [("A+", 90.0), ("A", 80.0), ("B", 70.0), ("C", 60.0)]

# The engine's own read on each band (spec §8). A C-grade setup is still
# published — hiding it would hide why the engine passed — but it is published
# with the advice to skip it, not as an invitation.
GRADE_ADVICE = {
    "A+": "SNIPER — full institutional alignment",
    "A": "STRONG — one minor confluence missing",
    "B": "TRADEABLE — second tier, size down",
    "C": "WEAK — the engine's own advice is to skip this",
    "INVALID": "DO NOT TRADE",
}


# --------------------------------------------------------------------------
# Risk management (spec §17)
# --------------------------------------------------------------------------
@dataclass
class RiskConfig:
    account_balance: float = 10_000.0
    risk_per_trade_pct: float = 0.005          # 0.5%
    max_daily_loss_pct: float = 0.02           # 2% of balance
    max_open_trades: int = 2
    max_consecutive_losses: int = 3            # then stand down for the day
    min_rr: float = 1.8
    max_setups_per_day: int = 3                # a CEILING, never a quota
    target_setups_per_day: int = 2
    allowed_sessions: tuple[str, ...] = ("LONDON", "LONDON_NY_OVERLAP", "NEW_YORK")
    require_killzone: bool = False
    news_filter: bool = True
    news_blackout_minutes: int = 30            # +/- around a high-impact event
    xau_pip_value_per_lot: float = 10.0        # USD per pip (0.10) per 1.00 lot

    def risk_dollars(self) -> float:
        return self.account_balance * self.risk_per_trade_pct


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
@dataclass
class EngineConfig:
    scan_interval_sec: int = 60                # spec §3 / §11
    modes: tuple[str, ...] = ("SCALP", "INTRADAY", "SWING")
    provider: str | None = None                # force a feed, else auto-failover
    allow_delayed_feed: bool = True            # delayed feeds are labelled, not hidden
    allow_proxy_feed: bool = True              # non-broker feeds are labelled, not hidden
    # B, not C. The shipped backtest measured C-grade setups at PF 0.58 and
    # -0.27R per trade on the held-out last 40% of history (n=71), while A and B
    # were both clearly positive there. Spec §8 already says a C is a "weak
    # setup, prefer no trade"; the measurement agrees, so the default declines
    # to publish that band. Set it to "C" to see them anyway — they are still
    # detected, graded and listed under the rejected setups with their reason.
    min_publish_grade: str = "B"               # grades below this are not published
    min_probability_sample: int = 30           # below this we print the sample, not a %
    history_veto_pf: float = 1.0               # measured PF under this -> setup vetoed
    state_dir: str = os.environ.get("XAUSMC_STATE_DIR", "state")
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    @property
    def timeframes(self) -> dict[str, int]:
        need: dict[str, int] = {}
        for m in self.modes:
            for tf, n in MODES[m].bars.items():
                need[tf] = max(need.get(tf, 0), n)
        return need

    def path(self, *parts: str) -> str:
        os.makedirs(self.state_dir, exist_ok=True)
        return os.path.join(self.state_dir, *parts)

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "EngineConfig":
        path = path or os.environ.get("XAUSMC_CONFIG", "xausmc.config.json")
        cfg = cls()
        if path and os.path.exists(path):
            with open(path) as fh:
                raw = json.load(fh)
            for k, v in raw.items():
                if k == "strategy":
                    cfg.strategy = StrategyConfig(**{**asdict(cfg.strategy), **v})
                elif k == "risk":
                    cfg.risk = RiskConfig(**{**asdict(cfg.risk), **v})
                elif hasattr(cfg, k):
                    setattr(cfg, k, tuple(v) if isinstance(getattr(cfg, k), tuple) else v)
        return cfg

    def save(self, path: str = "xausmc.config.json") -> str:
        with open(path, "w") as fh:
            json.dump(asdict(self), fh, indent=2)
        return path
