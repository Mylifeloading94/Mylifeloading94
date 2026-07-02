"""
Honest-Edge SMC strategy — v4, backtest-validated.
=================================================
Built after a 3-month backtest (867+ trades, GenFX data) proved the old
trend-continuation logic won only 29% (PF 0.82 — a losing system).

Two independent backtests (this repo + a separate engine) agree:
  • A profitable 70%+ win rate does NOT exist on this data at honest targets.
  • The one pair with a real, parameter-robust edge is USDCHF
    (76.7% WR, PF 1.54 over 3 months; holds PF 1.28-1.54 across param variants).
  • The biggest fixable leak was the STOP: tight swing stops got wicked;
    a 1.0-1.2x ATR buffer beyond the sweep roughly DOUBLED win rate.

Validated rule set (measured, not guessed):
  ENTRY (all must hold):
    1. Session: UTC 07:00-10:45 or 12:30-15:45 only (London / NY overlap).
    2. Setup = sweep-and-reclaim: a 15M wick trades beyond the prior 20-bar
       extreme and CLOSES back inside, within the last 4 bars.
    3. Displacement: entry candle body >= 0.5*ATR(15M) and closes beyond the
       3-bar pre-sweep extreme (micro-CHoCH), in trade direction.
    4. Location: <=45% of 40-bar 15M range for buys, >=55% for sells.
    5. Not extended: within 1.5*ATR(15M) of the 15M EMA20.
    6. Risk floor: structural risk >= 8 pips (cost gate).
  EXIT:
    7. SL = sweep extreme +/- 1.0*ATR(15M)  (beyond the liquidity pool).
    8. TP1 = +0.5R, close 80%, move SL to breakeven. TP2 = +1.5R on runner.
    9. Time stop: close at market after 40 bars (10h) if neither hit.
  PAIRS:  USDCHF (primary) + USDCAD, AUDJPY, EURUSD (secondary watch).
          DROP XAUUSD / USDJPY / EURJPY — strategy has no edge on them.
  RISK:   0.5-1.0% per trade until live PF > 1.2 over 40+ trades.

This is an honest ~60-65% portfolio edge with USDCHF the standout — NOT a
guaranteed 70%. Validate live on demo; re-run the backtest monthly, because
the regime that favours these entries will eventually flip.
"""
import time
import trading_agent as ta

# Pair tiers from the 3-month backtest
PRIMARY   = ["USDCHF"]
SECONDARY = ["USDCAD", "AUDJPY", "EURUSD"]
TRADE_PAIRS = PRIMARY + SECONDARY
BANNED    = ["XAUUSD", "USDJPY", "EURJPY"]   # no edge — do not trade

# Exit geometry (validated robust)
TP1_R      = 0.5
TP1_CLOSE  = 0.80
TP2_R      = 1.5
SL_ATR     = 1.0
MAX_HOLD   = 40


def in_edge_session(now=None):
    """UTC 07:00-10:45 or 12:30-15:45 only."""
    import datetime
    n = now or datetime.datetime.utcnow()
    h, m = n.hour, n.minute
    if 7 <= h <= 9: return True
    if h == 10 and m <= 45: return True
    if h == 12 and m >= 30: return True
    if 13 <= h <= 14: return True
    if h == 15 and m <= 45: return True
    return False


def _sweep_reclaim(w, bias):
    if len(w) < 25: return False
    for k in range(len(w) - 4, len(w)):
        if k < 21: continue
        prior = w[k-21:k-1]; c = w[k]
        if bias == "bullish":
            lo = min(b["l"] for b in prior)
            if c["l"] < lo and c["c"] > lo: return True
        else:
            hi = max(b["h"] for b in prior)
            if c["h"] > hi and c["c"] < hi: return True
    return False


def _displacement(w, bias, a15):
    last = w[-1]; body = abs(last["c"] - last["o"])
    if body < 0.5 * a15: return False
    pre = w[-4:-1]
    if bias == "bullish":
        return last["c"] > last["o"] and last["c"] > max(b["h"] for b in pre)
    return last["c"] < last["o"] and last["c"] < min(b["l"] for b in pre)


def analyze_edge(name, cfg, headers):
    """Return a trade setup dict if the honest-edge rules fire, else None."""
    if name in BANNED:
        return None
    if not in_edge_session():
        return None
    pip = cfg["pip"]
    b15 = ta.fetch_bars(headers, cfg["id"], "15m", 6)
    if len(b15) < 60:
        return None
    w = b15[-50:]
    price = w[-1]["c"]
    a15 = ta.atr(w[-30:], 14)
    if a15 <= 0:
        return None
    r40 = w[-40:]
    hi = max(b["h"] for b in r40); lo = min(b["l"] for b in r40)
    if hi <= lo:
        return None

    bias = None
    for cand in ("bullish", "bearish"):
        if _sweep_reclaim(w, cand):
            bias = cand; break
    if bias is None:
        return None

    pos = (price - lo) / (hi - lo)
    if bias == "bullish" and pos > 0.45: return None
    if bias == "bearish" and pos < 0.55: return None

    e20 = ta.ema([b["c"] for b in w], 20)
    if abs(price - e20) > 1.5 * a15: return None

    if not _displacement(w, bias, a15): return None

    entry = price
    if bias == "bullish":
        swext = min(b["l"] for b in w[-5:]); sl = round(swext - SL_ATR * a15, 5); sign = 1
    else:
        swext = max(b["h"] for b in w[-5:]); sl = round(swext + SL_ATR * a15, 5); sign = -1
    risk = abs(entry - sl)
    if risk < 8 * pip: return None

    tp1 = round(entry + risk * TP1_R * sign, 5)
    tp2 = round(entry + risk * TP2_R * sign, 5)
    return {
        "name": name, "direction": bias, "entry": round(entry, 5),
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "risk_pips": round(risk / pip, 1),
        "tp1_close": TP1_CLOSE, "tier": "PRIMARY" if name in PRIMARY else "SECONDARY",
        "cfg": cfg, "bars_15m": b15,
        "setup": "sweep-reclaim + displacement",
    }


def scan_edge(headers):
    """Scan the tradeable pairs and return firing setups (primary first)."""
    setups = []
    for name in TRADE_PAIRS:
        cfg = ta.MARKETS[name]
        try:
            s = analyze_edge(name, cfg, headers)
            if s: setups.append(s)
        except Exception as e:
            print(f"  {name} err {e}")
        time.sleep(0.3)
    setups.sort(key=lambda x: (0 if x["tier"] == "PRIMARY" else 1, x["risk_pips"]))
    return setups


if __name__ == "__main__":
    import os, datetime
    headers, account_id, balance = ta.auth()
    print(f"Honest-Edge scan {datetime.datetime.utcnow().strftime('%H:%M UTC')} | "
          f"session_ok={in_edge_session()} | bal ${balance:,.2f}")
    for s in scan_edge(headers):
        print(f"  ⭐ {s['tier']} {s['name']} {s['direction'].upper()} "
              f"entry {s['entry']} SL {s['sl']} TP1 {s['tp1']} TP2 {s['tp2']} ({s['risk_pips']}p)")
