"""
Configuration for the XAUUSD SMC bot.

Every secret is read from the environment (or a gitignored .env file).
Nothing sensitive is ever written to disk or to source control.

PRICE UNITS — read this before touching sizing
----------------------------------------------
The strategy document defines gold in "pips" where **1 pip = $1.00 of gold
price = $10 P/L per 1.0 lot** ("SL 30 pips -> Lot = 1500/(30*10) = 5.0").
That is the convention used everywhere in this package:

    PIP_USD                   = 1.00   # price move that equals one "pip"
    USD_PER_PIP_PER_LOT       = 10.00  # P/L per pip per 1.0 lot

It is also consistent with the rest of this repo (trading_agent.py uses
pip=0.1 / pip_val=$1.00, i.e. the same $10 per $1.00 move per lot).
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# .env loading (no third-party dependency)
# ---------------------------------------------------------------------------
def load_dotenv(path: str = ".env") -> None:
    """Populate os.environ from a simple KEY=VALUE file. Existing env wins."""
    p = pathlib.Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _b(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


# ---------------------------------------------------------------------------
# Instrument constants (gold)
# ---------------------------------------------------------------------------
PIP_USD = 1.00              # 1 "pip" of gold = $1.00 of price (strategy doc)
USD_PER_PIP_PER_LOT = 10.0  # $ P/L per pip per 1.0 lot

# Grade -> risk fraction of equity (section 5 of the strategy)
GRADE_RISK = {"A+": 0.030, "A": 0.025, "B": 0.015}
GRADE_ORDER = ["C", "B", "A", "A+"]     # ascending quality


@dataclass
class Config:
    # --- TradeLocker ------------------------------------------------------
    tl_env: str = "demo"                 # "demo" | "live"
    tl_email: str = ""
    tl_password: str = ""
    tl_server: str = ""
    tl_account_id: str = ""              # optional; first account if blank
    confirm_live: str = ""               # must equal "I_UNDERSTAND" for live

    # --- Telegram ---------------------------------------------------------
    tg_token: str = ""
    tg_chat: str = ""
    tg_enabled: bool = True

    # --- Loop -------------------------------------------------------------
    symbol: str = "XAUUSD"
    scan_seconds: int = 60
    dry_run: bool = False

    # --- Risk (section 4) -------------------------------------------------
    min_grade: str = "A"                 # skip anything below this grade
    max_open_positions: int = 1
    max_trades_per_day: int = 3
    max_consecutive_losses: int = 2      # stop for the day after N in a row
    daily_loss_pct: float = 0.06         # 2 x 3% = $3,000 on $50k
    weekly_loss_pct: float = 0.10        # -10% weekly kill switch
    max_lots: float = 10.0
    min_lots: float = 0.01
    lot_step: float = 0.01
    risk_overrun_tolerance: float = 1.10 # computed risk may exceed target by 10%

    # --- Filters ----------------------------------------------------------
    max_spread_usd: float = 0.50         # skip if spread > $0.50
    news_buffer_min: int = 15            # no trades +/- 15 min around news
    news_fallback_blackout: bool = True  # block classic US release times
    min_atr_pips: float = 1.5            # "avoid tight ranges" (M15 ATR, $)
    session_only: bool = True            # London + NY only
    session_windows: tuple = ((7, 0, 16, 0), (12, 0, 21, 0))  # UTC h,m,h,m

    # --- Setup geometry ---------------------------------------------------
    sl_buffer_pips: float = 2.5          # doc: 2-3 pips beyond the OB
    sl_atr_mult: float = 0.25            # extra ATR cushion (see README)
    min_sl_pips: float = 3.0
    max_sl_pips: float = 60.0
    tp1_r: float = 2.0                   # doc: TP1 = 2R
    tp2_r: float = 3.0                   # doc: TP2 = 3R..4R
    tp2_r_max: float = 4.0
    tp1_close_fraction: float = 0.50     # close 50% at TP1, SL -> breakeven
    min_rr: float = 2.0                  # reject anything under 1:2
    max_chase_r: float = 0.50            # never chase >0.5R past the zone
    require_dol_room: bool = True        # need clear room to TP1 liquidity

    # --- Structure detection ---------------------------------------------
    swing_strength_htf: int = 2
    swing_strength_ltf: int = 2
    sweep_lookback: int = 20             # bars defining the liquidity pool
    sweep_recent_bars: int = 3           # "within last 2-3 M15 candles"
    zone_max_age_bars: int = 12          # OB/FVG must still be fresh
    discount_max: float = 0.50           # longs only below 50% of the range
    ote_aplus: float = 0.705             # A+ needs retrace beyond 0.705

    # --- Files ------------------------------------------------------------
    state_file: str = "xauusd_smc_state.json"
    journal_file: str = "xauusd_smc_journal.jsonl"
    news_file: str = "news_calendar.json"
    log_file: str = "xauusd_smc_bot.log"
    chart_dir: str = "charts"

    @property
    def base_url(self) -> str:
        host = "live" if self.tl_env == "live" else "demo"
        return f"https://{host}.tradelocker.com/backend-api"

    @property
    def is_live(self) -> bool:
        return self.tl_env == "live"

    def risk_pct(self, grade: str) -> float:
        return GRADE_RISK.get(grade, 0.0)

    def grade_allowed(self, grade: str) -> bool:
        if grade not in GRADE_ORDER:
            return False
        return GRADE_ORDER.index(grade) >= GRADE_ORDER.index(self.min_grade)

    # -- validation --------------------------------------------------------
    def missing_credentials(self) -> list:
        missing = []
        if not self.tl_email:
            missing.append("TL_EMAIL")
        if not self.tl_password:
            missing.append("TL_PASSWORD")
        if not self.tl_server:
            missing.append("TL_SERVER")
        if self.tg_enabled and not self.tg_token:
            missing.append("TG_BOT_TOKEN")
        if self.tg_enabled and not self.tg_chat:
            missing.append("TG_CHAT_ID")
        return missing

    @classmethod
    def from_env(cls, dotenv: str = ".env") -> "Config":
        load_dotenv(dotenv)
        c = cls(
            tl_env=os.environ.get("TL_ENV", "demo").strip().lower(),
            tl_email=os.environ.get("TL_EMAIL", "").strip(),
            tl_password=os.environ.get("TL_PASSWORD", ""),
            tl_server=os.environ.get("TL_SERVER", "").strip(),
            tl_account_id=os.environ.get("TL_ACCOUNT_ID", "").strip(),
            confirm_live=os.environ.get("TL_CONFIRM_LIVE", "").strip(),
            tg_token=os.environ.get("TG_BOT_TOKEN", "").strip(),
            tg_chat=os.environ.get("TG_CHAT_ID", "").strip(),
            tg_enabled=_b("TG_ALERTS", True),
            symbol=os.environ.get("SYMBOL", "XAUUSD").strip().upper(),
            scan_seconds=_i("SCAN_SECONDS", 60),
            dry_run=_b("DRY_RUN", False),
            min_grade=os.environ.get("MIN_GRADE", "A").strip().upper(),
            max_open_positions=_i("MAX_OPEN_POSITIONS", 1),
            max_trades_per_day=_i("MAX_TRADES_PER_DAY", 3),
            max_consecutive_losses=_i("MAX_CONSECUTIVE_LOSSES", 2),
            daily_loss_pct=_f("DAILY_LOSS_PCT", 0.06),
            weekly_loss_pct=_f("WEEKLY_LOSS_PCT", 0.10),
            max_lots=_f("MAX_LOTS", 10.0),
            max_spread_usd=_f("MAX_SPREAD_USD", 0.50),
            news_buffer_min=_i("NEWS_BUFFER_MIN", 15),
            news_fallback_blackout=_b("NEWS_FALLBACK_BLACKOUT", True),
            min_atr_pips=_f("MIN_ATR_PIPS", 1.5),
            session_only=_b("SESSION_ONLY", True),
            sl_buffer_pips=_f("SL_BUFFER_PIPS", 2.5),
            sl_atr_mult=_f("SL_ATR_MULT", 0.25),
            tp1_r=_f("TP1_R", 2.0),
            tp2_r=_f("TP2_R", 3.0),
            min_rr=_f("MIN_RR", 2.0),
            require_dol_room=_b("REQUIRE_DOL_ROOM", True),
            max_chase_r=_f("MAX_CHASE_R", 0.50),
        )
        if c.min_grade not in GRADE_ORDER:
            c.min_grade = "A"
        return c
