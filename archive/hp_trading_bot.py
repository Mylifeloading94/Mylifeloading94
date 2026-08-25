"""
HIGH-PROBABILITY FOREX + XAUUSD TRADING BOT
Implements the full specification: multi-timeframe bias (D1/H4) -> H1 setup
zone -> M15 liquidity sweep + market-structure shift + confirmation candle ->
10-point trade-quality score -> strict risk management -> execution.

IMPORTANT (from the spec): the 75-90% win-rate is a TARGET to be validated
through backtesting / out-of-sample / forward / live testing. It is NOT a
guarantee. This module contains the strategy + risk logic ONLY; run
hp_bot_backtest.py to validate it on real historical data before any live use.

Data/exec integration reuses trading_agent.py (TradeLocker) when run live.
The strategy math here is self-contained (pandas/numpy) so it can be
backtested deterministically without a broker connection.
"""
from dataclasses import dataclass, field, asdict
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# 1. MARKETS
# ----------------------------------------------------------------------------
FOREX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
METAL = ["XAUUSD"]
MARKETS = FOREX + METAL

PIP = {  # pip size per market
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "USDJPY": 0.01, "XAUUSD": 0.1,
}

# Currency legs for the correlation guard
LEGS = {
    "EURUSD": ("EUR", "USD"), "GBPUSD": ("GBP", "USD"), "AUDUSD": ("AUD", "USD"),
    "USDCAD": ("USD", "CAD"), "USDCHF": ("USD", "CHF"), "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("XAU", "USD"),
}


# ----------------------------------------------------------------------------
# 14. OPERATING MODES  +  7/10 RISK CONFIG
# ----------------------------------------------------------------------------
@dataclass
class BotConfig:
    mode: str = "high_probability"          # "high_probability" | "balanced"
    risk_pct: float = 0.005                  # default 0.5%
    risk_pct_xau: float = 0.0025             # gold 0.25%
    risk_min: float = 0.0025
    risk_max: float = 0.02
    max_daily_loss: float = 0.02             # 2% equity
    max_weekly_loss: float = 0.05            # 5% equity
    max_open_trades: int = 3
    max_xau_trades: int = 1
    max_correlated: int = 2
    min_rr: float = 1.5
    preferred_rr: float = 2.0
    # scoring thresholds by mode
    spread_limit_pips: dict = field(default_factory=lambda: {
        "EURUSD": 1.5, "GBPUSD": 2.0, "USDJPY": 1.5, "AUDUSD": 2.0,
        "USDCAD": 2.0, "USDCHF": 2.0, "XAUUSD": 40.0})
    # sessions (UTC): London 7-16, NY 12-21, overlap 12-16
    session_hours: tuple = (7, 21)
    news_blackouts: list = field(default_factory=list)  # list of (start_iso, end_iso)
    ema_fast: int = 50
    ema_slow: int = 200
    atr_period: int = 14
    sl_atr_buffer: float = 0.5
    swing_strength: int = 3

    def min_score(self):
        return 9 if self.mode == "high_probability" else 8

    def max_trades_per_day(self):
        return 3 if self.mode == "high_probability" else 5

    def risk_for(self, symbol):
        return self.risk_pct_xau if symbol == "XAUUSD" else self.risk_pct


# ----------------------------------------------------------------------------
# Indicator helpers (self-contained)
# ----------------------------------------------------------------------------
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def swings(df, strength=3):
    """Return boolean Series marking confirmed swing highs / lows (fractals)."""
    h, l = df["high"].values, df["low"].values
    n = len(df)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(strength, n - strength):
        if h[i] == max(h[i - strength:i + strength + 1]):
            sh[i] = True
        if l[i] == min(l[i - strength:i + strength + 1]):
            sl[i] = True
    return pd.Series(sh, index=df.index), pd.Series(sl, index=df.index)


def structure_dir(df, strength=3, lookback=60):
    """+1 bullish (HH+HL), -1 bearish (LH+LL), 0 unclear — from last 2 swings."""
    sh, sl = swings(df, strength)
    hi = df["high"][sh].tail(3).values
    lo = df["low"][sl].tail(3).values
    if len(hi) >= 2 and len(lo) >= 2:
        if hi[-1] > hi[-2] and lo[-1] > lo[-2]:
            return 1
        if hi[-1] < hi[-2] and lo[-1] < lo[-2]:
            return -1
    return 0


# ----------------------------------------------------------------------------
# 3. HIGHER-TIMEFRAME BIAS (D1 + H4)
# ----------------------------------------------------------------------------
def htf_bias(df, cfg):
    """Return +1 / -1 / 0 for one higher timeframe."""
    if len(df) < cfg.ema_slow + 5:
        return 0
    ef = ema(df["close"], cfg.ema_fast)
    es = ema(df["close"], cfg.ema_slow)
    price = df["close"].iloc[-1]
    st = structure_dir(df, cfg.swing_strength)
    if price > es.iloc[-1] and ef.iloc[-1] > es.iloc[-1] and st == 1:
        return 1
    if price < es.iloc[-1] and ef.iloc[-1] < es.iloc[-1] and st == -1:
        return -1
    return 0


def combined_bias(d1, h4, cfg):
    """Clear bias only when D1 and H4 agree; else 0 (NO TRADE)."""
    b1, b4 = htf_bias(d1, cfg), htf_bias(h4, cfg)
    return b1 if (b1 != 0 and b1 == b4) else 0


# ----------------------------------------------------------------------------
# 4. H1 SETUP CONFIRMATION — price in a high-probability zone
# ----------------------------------------------------------------------------
def h1_in_zone(h1, direction, cfg):
    """True if H1 price has pulled back into a valid area aligned with bias:
    near 50/200 EMA, into an FVG, or into a prior swing level."""
    if len(h1) < cfg.ema_slow + 5:
        return False, None
    a = atr(h1, cfg.atr_period).iloc[-1]
    price = h1["close"].iloc[-1]
    ef = ema(h1["close"], cfg.ema_fast).iloc[-1]
    es = ema(h1["close"], cfg.ema_slow).iloc[-1]
    near_ema = min(abs(price - ef), abs(price - es)) <= 0.75 * a
    # FVG on H1 in bias direction (3-bar imbalance) within last 20 bars
    fvg = _recent_fvg(h1, direction, lookback=20)
    in_fvg = fvg is not None and fvg[1] <= price <= fvg[0]
    # prior swing level proximity
    sh, sl = swings(h1, cfg.swing_strength)
    lvls = (h1["low"][sl].tail(4).tolist() if direction == 1 else h1["high"][sh].tail(4).tolist())
    near_swing = any(abs(price - lv) <= 0.75 * a for lv in lvls)
    zone = near_ema or in_fvg or near_swing
    kind = "EMA" if near_ema else "FVG" if in_fvg else "SWING" if near_swing else None
    return zone, kind


def _recent_fvg(df, direction, lookback=20):
    h, l = df["high"].values, df["low"].values
    n = len(df)
    for k in range(n - 1, max(1, n - lookback), -1):
        if k - 2 < 0:
            continue
        if direction == 1 and h[k - 2] < l[k]:
            return (l[k], h[k - 2])            # (top, bottom)
        if direction == -1 and l[k - 2] > h[k]:
            return (l[k - 2], h[k])
    return None


# ----------------------------------------------------------------------------
# 5. M15 ENTRY: liquidity sweep -> market-structure shift -> confirmation
# ----------------------------------------------------------------------------
def liquidity_sweep(m15, direction, lookback=20):
    """Buy: wick sweeps below a recent swing low then closes back above.
    Sell: wick sweeps above a recent swing high then closes back below.
    Returns swept level or None."""
    sh, sl = swings(m15, 2)
    last = m15.iloc[-1]
    if direction == 1:
        lows = m15["low"][sl].iloc[:-1].tail(lookback)
        for lv in lows.values[::-1]:
            if last["low"] < lv and last["close"] > lv:
                return lv
    else:
        highs = m15["high"][sh].iloc[:-1].tail(lookback)
        for lv in highs.values[::-1]:
            if last["high"] > lv and last["close"] < lv:
                return lv
    return None


def mss(m15, direction, lookback=12):
    """Market-structure shift on M15: close breaks the most recent opposite
    swing in the trade direction."""
    sh, sl = swings(m15, 2)
    c = m15["close"].iloc[-1]
    if direction == 1:
        highs = m15["high"][sh].iloc[:-1].tail(lookback)
        return len(highs) > 0 and c > highs.max()
    else:
        lows = m15["low"][sl].iloc[:-1].tail(lookback)
        return len(lows) > 0 and c < lows.min()


def confirmation_candle(m15, direction, min_body=0.5):
    last = m15.iloc[-1]
    rng = last["high"] - last["low"]
    if rng <= 0:
        return False
    body = abs(last["close"] - last["open"]) / rng
    if direction == 1:
        return last["close"] > last["open"] and body >= min_body
    return last["close"] < last["open"] and body >= min_body


# ----------------------------------------------------------------------------
# 6. TRADE QUALITY SCORING (10 points)
# ----------------------------------------------------------------------------
def score_setup(bias_ok, h1_ok, sweep, ob_or_fvg, mss_ok, strong_candle, rr_ok):
    s = 0
    s += 2 if bias_ok else 0            # H4/D1 trend alignment
    s += 2 if h1_ok else 0             # H1 market structure alignment
    s += 2 if sweep else 0            # liquidity sweep
    s += 1 if ob_or_fvg else 0        # valid OB / FVG
    s += 1 if mss_ok else 0           # M15 market-structure shift
    s += 1 if strong_candle else 0    # strong confirmation candle
    s += 1 if rr_ok else 0            # min 1:1.5 RR
    return s


# ----------------------------------------------------------------------------
# 8/9. STOP-LOSS + TAKE-PROFIT
# ----------------------------------------------------------------------------
def build_trade(symbol, direction, m15, swept_level, cfg):
    """Compute entry/stop/targets. Returns dict or None if RR/structure fails."""
    pip = PIP[symbol]
    a = atr(m15, cfg.atr_period).iloc[-1]
    entry = m15["close"].iloc[-1]
    sh, sl = swings(m15, 2)
    if direction == 1:
        base = swept_level if swept_level is not None else m15["low"].tail(10).min()
        struct_low = m15["low"][sl].tail(6).min()
        stop = min(base, struct_low) - cfg.sl_atr_buffer * a
        risk = entry - stop
    else:
        base = swept_level if swept_level is not None else m15["high"].tail(10).max()
        struct_high = m15["high"][sh].tail(6).max()
        stop = max(base, struct_high) + cfg.sl_atr_buffer * a
        risk = stop - entry
    if risk <= 0:
        return None
    tp1 = entry + direction * 1.0 * risk
    tp2 = entry + direction * cfg.preferred_rr * risk
    rr = cfg.preferred_rr
    return {"symbol": symbol, "direction": direction, "entry": entry, "stop": stop,
            "risk": risk, "risk_pips": risk / pip, "tp1": tp1, "tp2": tp2,
            "rr": rr, "atr": a}


# ----------------------------------------------------------------------------
# 11/13. FILTERS: session + news + spread
# ----------------------------------------------------------------------------
def in_session(ts, cfg):
    return cfg.session_hours[0] <= ts.hour < cfg.session_hours[1]


def in_news_blackout(ts, cfg):
    for start, end in cfg.news_blackouts:
        if pd.Timestamp(start) <= ts <= pd.Timestamp(end):
            return True
    return False


def spread_ok(symbol, spread_pips, cfg):
    return spread_pips <= cfg.spread_limit_pips.get(symbol, 999)


# ----------------------------------------------------------------------------
# 17. CORE EVALUATION — one symbol, given multi-TF data as-of "now"
# ----------------------------------------------------------------------------
def evaluate(symbol, d1, h4, h1, m15, cfg, ts, spread_pips=0.0):
    """Return a scored trade dict (or None). Pure function of the data given."""
    if not in_session(ts, cfg):
        return None
    if in_news_blackout(ts, cfg):
        return None
    if not spread_ok(symbol, spread_pips, cfg):
        return None

    bias = combined_bias(d1, h4, cfg)
    if bias == 0:                                   # STEP 2: no clear bias -> reject
        return None

    h1_ok, zone_kind = h1_in_zone(h1, bias, cfg)    # STEP 3
    sweep = liquidity_sweep(m15, bias)              # STEP 5
    fvg = _recent_fvg(m15, bias, lookback=20)
    ob_or_fvg = (fvg is not None) or (zone_kind in ("FVG", "SWING"))
    mss_ok = mss(m15, bias)                         # STEP 6
    strong = confirmation_candle(m15, bias)         # STEP 7

    trade = build_trade(symbol, bias, m15, sweep, cfg)
    if trade is None:
        return None
    rr_ok = trade["rr"] >= cfg.min_rr

    # hard requirements from spec 12 (no-trade conditions)
    if sweep is None or not mss_ok or not h1_ok or not rr_ok:
        # these are core structural requirements, not just score points
        return None

    s = score_setup(bias != 0, h1_ok, sweep is not None, ob_or_fvg, mss_ok, strong, rr_ok)
    if s < cfg.min_score():                         # STEP 9
        return None

    trade.update({"score": s, "zone": zone_kind, "bias": bias, "time": ts,
                  "session": _session_name(ts), "spread": spread_pips,
                  "reason": f"{'BUY' if bias==1 else 'SELL'} {zone_kind} sweep+MSS conf score{s}/10"})
    return trade


def _session_name(ts):
    h = ts.hour
    if 12 <= h < 16:
        return "London/NY overlap"
    if 7 <= h < 12:
        return "London"
    if 16 <= h < 21:
        return "New York"
    return "Off"


# ----------------------------------------------------------------------------
# 7/16. PORTFOLIO RISK GATE — apply account-level limits before entering
# ----------------------------------------------------------------------------
def correlated_count(symbol, direction, open_trades):
    base, quote = LEGS[symbol]
    sign = {base: direction, quote: -direction}
    n = 0
    for ot in open_trades:
        ob, oq = LEGS[ot["symbol"]]
        osgn = {ob: ot["direction"], oq: -ot["direction"]}
        if any(k in osgn and osgn[k] == sign[k] for k in sign):
            n += 1
    return n


def risk_gate(trade, state, cfg):
    """Return (allowed: bool, reason: str). state carries live counters."""
    if state["daily_loss"] <= -cfg.max_daily_loss:
        return False, "daily loss limit reached"
    if state["weekly_loss"] <= -cfg.max_weekly_loss:
        return False, "weekly loss limit reached"
    if state["trades_today"] >= cfg.max_trades_per_day():
        return False, "max trades/day reached"
    if len(state["open"]) >= cfg.max_open_trades:
        return False, "max open trades reached"
    if trade["symbol"] == "XAUUSD" and sum(1 for o in state["open"] if o["symbol"] == "XAUUSD") >= cfg.max_xau_trades:
        return False, "max XAUUSD trades reached"
    if correlated_count(trade["symbol"], trade["direction"], state["open"]) >= cfg.max_correlated:
        return False, "too many correlated trades"
    return True, "ok"


def risk_multiplier(consecutive_losses):
    """16. Automatic risk reduction."""
    if consecutive_losses >= 3:
        return 0.5
    return 1.0


def position_size(symbol, trade, balance, cfg, consecutive_losses=0):
    risk_dollars = balance * cfg.risk_for(symbol) * risk_multiplier(consecutive_losses)
    # pip value approximations consistent with the repo's convention
    pip_val = {"EURUSD": 10.0, "GBPUSD": 10.0, "AUDUSD": 10.0, "USDCAD": 7.3,
               "USDCHF": 11.0, "USDJPY": 6.7, "XAUUSD": 1.0}[symbol]
    lots = risk_dollars / (trade["risk_pips"] * pip_val) if trade["risk_pips"] > 0 else 0.01
    return max(round(lots, 2), 0.01), round(risk_dollars, 2)


if __name__ == "__main__":
    print("hp_trading_bot: strategy/risk module. Run hp_bot_backtest.py to validate on data.")
