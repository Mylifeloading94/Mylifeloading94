"""BB SNIPER default inputs. Every rule threshold lives here so it can be changed in one place."""

DEFAULTS = dict(
    # --- indicators ---
    bb_len=20, bb_dev=2.0, ema_fast=20, ema_slow=200, rsi_len=14, adx_len=14, atr_len=14,
    bw_lookback=100,             # BandWidth percentile lookback (candles)
    # --- regime ---
    adx_weak=20, adx_trend=25,   # <weak = no trend, weak..trend = transitional, >trend = trending
    squeeze_pct=20,              # BandWidth percentile below this = squeeze
    expand_pct=80,               # BandWidth percentile above this (and rising) = expansion
    # --- structure / liquidity ---
    piv_liq=3,                   # pivot strength (bars each side) for liquidity levels
    piv_micro=2,                 # pivot strength for micro structure (MSS)
    liq_lookback=60,             # bars to look back for unswept liquidity
    arm_window=12,               # bars a sweep/pullback/retest stays armed waiting for MSS
    # --- confirmations ---
    rsi_os=40, rsi_ob=60,        # mean-reversion RSI zones
    rsi_trend_floor=40,          # trend long: RSI must stay above this in the pullback
    bb_approach=0.10,            # "approaches" band = within 10% of band width
    # --- setups enabled ---
    setups=("MR", "TC", "SB"),   # mean reversion, trend continuation, squeeze breakout
    sb_range=20, sb_retest_window=15, sb_confirm_window=5,
    # --- score filter ---
    min_score=8,                 # Conservative 9 / Standard 8 / Aggressive 7
    neutral_needs_full=True,     # neutral HTF bias: trade only if every non-bias point is scored
    # --- risk / filters ---
    sl_buf_atr=0.20, max_sl_atr=3.0, min_sl_spreads=1.0,
    min_rr=1.5,                  # nearest opposing structure must allow at least this many R
    max_spread_pct_atr=50.0,     # spread filter: max spread as % of ATR(exec) (stops average ~3 ATR -> <=~0.17R cost)
    sessions=("London", "NY"),   # enabled: Asian, London, NY (Overlap is inside London+NY)
    news_filter=False,           # no historical calendar feed -> disabled in backtests (see report)
    news_before_min=15, news_after_min=30,
    # --- trade management ---
    tp_r=(1.0, 2.0, 3.0), tp_frac=(0.30, 0.35, 0.35),
    be_after_tp1=True, be_buffer_r=0.05,
    trail="atr", trail_after_r=2.0, trail_atr=1.5,
    tp_through_pips=0.2,         # a target needs price to trade 0.2 pip through it
    spread_mult=1.0,             # cost diagnostic: 0 = frictionless test
    max_hold_bars=120,
    # --- account rules ---
    max_trades_day=3, max_losses_day=3, daily_loss_pct=3.0,
    risk_pct=1.0, fixed_lot=None, min_lot=0.01, lot_step=0.01,
)

SCORE_MODES = {"Conservative": 9, "Standard": 8, "Aggressive": 7}

INSTRUMENTS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "EURJPY", "GBPJPY",
               "EURGBP", "EURAUD", "EURCAD", "GBPCAD", "GBPAUD", "AUDJPY", "CADJPY", "XAUUSD"]

# Typical OANDA spreads in pips (static estimates; the feed has no historical spread data).
SPREAD_PIPS = {"EURUSD": 1.4, "GBPUSD": 2.0, "USDJPY": 1.6, "USDCHF": 1.8, "USDCAD": 2.2, "AUDUSD": 1.6,
               "NZDUSD": 2.0, "EURJPY": 2.0, "GBPJPY": 3.0, "AUDJPY": 2.0, "CADJPY": 2.5, "EURGBP": 1.6,
               "EURCAD": 2.8, "EURAUD": 2.8, "GBPCAD": 4.0, "GBPAUD": 3.5, "XAUUSD": 3.5}

# Execution TF -> (setup TF, bias TF). Higher timeframes stay configurable.
TF_MAP = {"1m": ("5m", "15m"), "3m": ("5m", "15m"), "5m": ("5m", "15m"), "15m": ("15m", "1h")}
TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def pip(sym):
    return 0.01 if "JPY" in sym else 0.1 if sym == "XAUUSD" else 0.0001


def cfg(**over):
    c = dict(DEFAULTS); c.update(over); return c
