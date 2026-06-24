"""
AI Forex Trading Agent — Improved SMC Strategy
===============================================
Improvements over v1:
  - Session filter       : London 07-12 UTC + New York 13-17 UTC only
  - Swing-point structure: Real HH/HL/LH/LL tracking (not simple half-period)
  - Premium/Discount     : Only buy in discount (<50% of range), sell in premium (>50%)
  - CHoCH detection      : Change of Character confirms reversal
  - VWAP bias            : Only trade in direction of VWAP
  - PDH/PDL levels       : Previous Day High/Low as key confluence
  - Equal H/L (BSL/SSL)  : Detects stop-hunt liquidity pools
  - Correlation filter   : Max 1 open trade per currency group
  - Breakeven management : SL → entry once TP1 is hit (checked every scan)
  - Scoring rebalance    : OB rejection + liq sweep worth more; FVG alone = minor point
  - Min score raised to 7 (harder filter, higher quality)

Environment variables:
  TL_EMAIL       — TradeLocker account email
  TL_PASSWORD    — TradeLocker account password
  TL_SERVER      — Broker server  (default: GenFX)
  TL_ACCOUNT_ID  — Account ID     (default: 2265464)
  TG_BOT_TOKEN   — Telegram bot token
  TG_CHAT_ID     — Telegram channel/group ID  (default: TRADING ROOM)
"""

import os, time, json, datetime, traceback
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
BASE_URL   = "https://demo.tradelocker.com/backend-api"
EMAIL      = os.environ["TL_EMAIL"]
PASSWORD   = os.environ["TL_PASSWORD"]
SERVER     = os.environ.get("TL_SERVER", "GenFX")
TARGET_ACC = os.environ.get("TL_ACCOUNT_ID", "2265464")
TG_TOKEN   = os.environ["TG_BOT_TOKEN"]
TG_CHAT    = os.environ.get("TG_CHAT_ID", "-1001190707115")  # TRADING ROOM channel

INFO_ROUTE  = 452
TRADE_ROUTE = 9912

RISK_PCT      = 0.02    # 2% risk per trade
MAX_TRADES    = 3       # max new trades per day
MIN_SCORE     = 7       # raised from 5 — only high-confluence setups
MIN_RISK_PIPS = 8
MAX_LOTS      = 5.0
SCAN_EVERY    = 900     # 15 min
UPDATE_EVERY  = 14400   # 4 hours pip update
TG_ALERTS     = True

STATE_FILE  = "agent_state.json"
TRADES_FILE = "active_trades.json"  # tracks open trades for breakeven mgmt

# ──────────────────────────────────────────────────────────────────────────────
# MARKETS  (instrument IDs verified on GenFX)
# ──────────────────────────────────────────────────────────────────────────────
MARKETS = {
    "EURUSD": {"id": 278, "pip": 0.0001, "pip_val": 10.00},
    "GBPUSD": {"id": 279, "pip": 0.0001, "pip_val": 10.00},
    "USDJPY": {"id": 283, "pip": 0.01,   "pip_val":  6.70},
    "USDCHF": {"id": 280, "pip": 0.0001, "pip_val": 10.00},
    "USDCAD": {"id": 281, "pip": 0.0001, "pip_val":  7.30},
    "AUDUSD": {"id": 277, "pip": 0.0001, "pip_val": 10.00},
    "NZDUSD": {"id": 284, "pip": 0.0001, "pip_val": 10.00},
    "GBPJPY": {"id": 243, "pip": 0.01,   "pip_val":  6.70},
    "EURJPY": {"id": 238, "pip": 0.01,   "pip_val":  6.70},
    "AUDJPY": {"id": 229, "pip": 0.01,   "pip_val":  6.70},
    "EURGBP": {"id": 235, "pip": 0.0001, "pip_val": 12.50},
    "GBPCAD": {"id": 241, "pip": 0.0001, "pip_val":  7.30},
    "XAUUSD": {"id": 314, "pip": 0.1,    "pip_val":  1.00},
    "NAS100": {"id": 306, "pip": 1.0,    "pip_val":  1.00},
    "SPX500": {"id": 307, "pip": 1.0,    "pip_val":  1.00},
}

ID_TO_NAME = {v["id"]: k for k, v in MARKETS.items()}

# Currency correlation groups — no 2 trades from same group simultaneously
CORR_GROUPS = [
    {"EURUSD", "EURJPY", "EURGBP"},          # EUR exposure
    {"GBPUSD", "GBPJPY", "GBPCAD", "EURGBP"},# GBP exposure
    {"USDJPY", "GBPJPY", "EURJPY", "AUDJPY"},# JPY exposure
    {"AUDUSD", "AUDJPY"},                      # AUD exposure
    {"USDCHF", "USDCAD"},                      # USD-base pairs
]

# ──────────────────────────────────────────────────────────────────────────────
# STATE
# ──────────────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"trades_today": 0, "trade_date": "", "last_update": 0, "last_engage": 0}

def save_state(s):
    json.dump(s, open(STATE_FILE, "w"))

def reset_daily(state):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if state["trade_date"] != today:
        state["trades_today"] = 0
        state["trade_date"]   = today
    return state

def load_active_trades():
    if os.path.exists(TRADES_FILE):
        return json.load(open(TRADES_FILE))
    return {}

def save_active_trades(t):
    json.dump(t, open(TRADES_FILE, "w"))

# ──────────────────────────────────────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────────────────────────────────────
def auth():
    r = requests.post(f"{BASE_URL}/auth/jwt/token",
                      json={"email": EMAIL, "password": PASSWORD, "server": SERVER},
                      timeout=15)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Auth failed {r.status_code}: {r.text[:200]}")
    token = r.json()["accessToken"]
    h = {"Authorization": f"Bearer {token}"}
    accs = requests.get(f"{BASE_URL}/auth/jwt/all-accounts", headers=h, timeout=15).json()
    acc = next((a for a in accs["accounts"] if a["id"] == TARGET_ACC), accs["accounts"][0])
    h["accNum"] = str(acc["accNum"])
    return h, acc["id"], float(acc["accountBalance"])

# ──────────────────────────────────────────────────────────────────────────────
# BARS
# ──────────────────────────────────────────────────────────────────────────────
def fetch_bars(headers, iid, resolution, days=30):
    now_ms = int(time.time() * 1000)
    frm_ms = now_ms - int(days * 86400 * 1000)
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE_URL}/trade/history", headers=headers, params={
                "tradableInstrumentId": iid, "routeId": INFO_ROUTE,
                "resolution": resolution, "from": frm_ms, "to": now_ms,
            }, timeout=20)
            if r.status_code == 429:
                time.sleep(2 ** attempt); continue
            bars = r.json().get("d", {}).get("barDetails", [])
            if bars:
                return bars
        except Exception:
            pass
        time.sleep(2 ** attempt)
    return []

# ──────────────────────────────────────────────────────────────────────────────
# SESSION FILTER  (improvement #1)
# ──────────────────────────────────────────────────────────────────────────────
def in_session():
    """True during London (07-12 UTC) or New York (13-17 UTC) kill zones."""
    now  = datetime.datetime.utcnow()
    hour = now.hour + now.minute / 60.0
    return (7.0 <= hour < 12.0) or (13.0 <= hour < 17.0)

def session_name():
    now  = datetime.datetime.utcnow()
    hour = now.hour + now.minute / 60.0
    if 7.0 <= hour < 12.0:  return "London"
    if 13.0 <= hour < 17.0: return "New York"
    return "Closed"

# ──────────────────────────────────────────────────────────────────────────────
# SWING POINTS  (improvement #2 — replaces half-period comparison)
# ──────────────────────────────────────────────────────────────────────────────
def find_swings(bars, strength=3):
    """
    Find fractal swing highs and lows.
    strength: number of bars on each side that must be lower/higher.
    """
    swings = []
    n = len(bars)
    for i in range(strength, n - strength):
        hi = bars[i]["h"]
        lo = bars[i]["l"]
        is_sh = all(bars[j]["h"] < hi for j in range(i - strength, i)) and \
                all(bars[j]["h"] < hi for j in range(i + 1, i + strength + 1))
        is_sl = all(bars[j]["l"] > lo for j in range(i - strength, i)) and \
                all(bars[j]["l"] > lo for j in range(i + 1, i + strength + 1))
        if is_sh:
            swings.append({"type": "high", "price": hi, "idx": i})
        if is_sl:
            swings.append({"type": "low",  "price": lo, "idx": i})
    return sorted(swings, key=lambda x: x["idx"])

def market_structure(bars, lookback=80, strength=3):
    """
    Determine trend from real swing points (HH/HL or LH/LL).
    Returns: 'bullish' | 'bearish' | 'ranging'
    """
    r = bars[-lookback:] if len(bars) >= lookback else bars
    swings = find_swings(r, strength)
    highs = [s for s in swings if s["type"] == "high"]
    lows  = [s for s in swings if s["type"] == "low"]

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1]["price"] > highs[-2]["price"]
        hl = lows[-1]["price"]  > lows[-2]["price"]
        lh = highs[-1]["price"] < highs[-2]["price"]
        ll = lows[-1]["price"]  < lows[-2]["price"]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
        if hh or hl:  return "bullish"
        if lh or ll:  return "bearish"
    return "ranging"

# ──────────────────────────────────────────────────────────────────────────────
# PREMIUM / DISCOUNT  (improvement #3)
# ──────────────────────────────────────────────────────────────────────────────
def in_premium_discount(bars, direction, lookback=50):
    """
    Buy in discount (price below 50% of range) — bullish.
    Sell in premium (price above 50% of range) — bearish.
    Returns True if price is in the correct zone.
    """
    r = bars[-lookback:] if len(bars) >= lookback else bars
    hi  = max(b["h"] for b in r)
    lo  = min(b["l"] for b in r)
    mid = (hi + lo) / 2
    price = bars[-1]["c"]
    if direction == "bullish": return price <= mid
    return price >= mid

# ──────────────────────────────────────────────────────────────────────────────
# CHoCH — Change of Character  (improvement #4)
# ──────────────────────────────────────────────────────────────────────────────
def choch(bars, direction, lookback=40):
    """
    Bullish CHoCH: in a downtrend, price breaks ABOVE a previous lower high → trend flip signal.
    Bearish CHoCH: in an uptrend, price breaks BELOW a previous higher low → trend flip signal.
    """
    r = bars[-lookback:] if len(bars) >= lookback else bars
    swings = find_swings(r, 2)
    price  = r[-1]["c"]

    if direction == "bullish":
        highs = [s for s in swings if s["type"] == "high"]
        if len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"]:
            return price > highs[-2]["price"]
    else:
        lows = [s for s in swings if s["type"] == "low"]
        if len(lows) >= 2 and lows[-1]["price"] < lows[-2]["price"]:
            return price < lows[-2]["price"]
    return False

# ──────────────────────────────────────────────────────────────────────────────
# VWAP BIAS  (improvement #5)
# ──────────────────────────────────────────────────────────────────────────────
def vwap_bias(bars, direction):
    """
    Use today's bars to compute VWAP.
    Returns True if price is on the correct side of VWAP for the trade direction.
    Buy below VWAP (bullish), sell above VWAP (bearish).
    """
    today = datetime.datetime.utcnow().date()
    day_bars = [b for b in bars
                if datetime.datetime.utcfromtimestamp(b["t"] / 1000).date() == today]
    if len(day_bars) < 2:
        return True  # Not enough data — don't block the trade
    total_tpv = sum(((b["h"] + b["l"] + b["c"]) / 3) * abs(b["c"] - b["o"] or 0.0001)
                    for b in day_bars)
    total_v   = sum(abs(b["c"] - b["o"]) or 0.0001 for b in day_bars)
    vwap_val  = total_tpv / total_v
    price     = bars[-1]["c"]
    if direction == "bullish": return price < vwap_val
    return price > vwap_val

# ──────────────────────────────────────────────────────────────────────────────
# PREVIOUS DAY HIGH / LOW  (improvement #6)
# ──────────────────────────────────────────────────────────────────────────────
def prev_day_levels(bars):
    """Return (PDH, PDL) from yesterday's bars."""
    today = datetime.datetime.utcnow().date()
    yesterday = today - datetime.timedelta(days=1)
    yday = [b for b in bars
            if datetime.datetime.utcfromtimestamp(b["t"] / 1000).date() == yesterday]
    if not yday:
        return None, None
    return max(b["h"] for b in yday), min(b["l"] for b in yday)

def near_pdh_pdl(bars, direction, pdh, pdl, threshold_pips, pip):
    """True if price is within threshold_pips of PDH (sell) or PDL (buy)."""
    if pdh is None or pdl is None:
        return False
    price = bars[-1]["c"]
    if direction == "bullish":
        return abs(price - pdl) <= threshold_pips * pip
    return abs(price - pdh) <= threshold_pips * pip

# ──────────────────────────────────────────────────────────────────────────────
# EQUAL HIGHS / LOWS  (BSL/SSL liquidity)  (improvement #7)
# ──────────────────────────────────────────────────────────────────────────────
def equal_highs_lows(bars, direction, tolerance=0.0003, lookback=40):
    """
    Detect equal highs (sell-side liquidity) or equal lows (buy-side liquidity).
    Equal = within tolerance of each other.
    """
    r = bars[-lookback:] if len(bars) >= lookback else bars
    price = r[-1]["c"]
    if direction == "bullish":
        # Look for 2+ lows within tolerance → BSL pool → sweep candidate
        lows = [b["l"] for b in r[:-3]]
        for i in range(len(lows)):
            for j in range(i + 1, len(lows)):
                if abs(lows[i] - lows[j]) <= tolerance * lows[i]:
                    if price < min(lows[i], lows[j]) * 1.002:
                        return True
    else:
        highs = [b["h"] for b in r[:-3]]
        for i in range(len(highs)):
            for j in range(i + 1, len(highs)):
                if abs(highs[i] - highs[j]) <= tolerance * highs[i]:
                    if price > max(highs[i], highs[j]) * 0.998:
                        return True
    return False

# ──────────────────────────────────────────────────────────────────────────────
# EXISTING SMC INDICATORS (refined)
# ──────────────────────────────────────────────────────────────────────────────
def atr(bars, period=14):
    if len(bars) < 2: return 0
    trs = [max(bars[i]["h"] - bars[i]["l"],
               abs(bars[i]["h"] - bars[i-1]["c"]),
               abs(bars[i]["l"] - bars[i-1]["c"]))
           for i in range(1, len(bars))]
    return sum(trs[-period:]) / min(len(trs), period)

def find_ob(bars, direction, lookback=60):
    """Most recent unmitigated Order Block."""
    r = bars[-lookback:] if len(bars) >= lookback else bars
    n = len(r)
    for i in range(n - 5, 1, -1):
        if direction == "bullish" and r[i]["c"] < r[i]["o"]:
            if sum(1 for j in range(1, 4) if i+j < n and r[i+j]["c"] > r[i+j]["o"]) >= 2:
                ob = {"h": r[i]["o"], "l": r[i]["c"]}
                if any(r[j]["c"] < ob["l"] for j in range(i+1, n)): continue
                ob["mid"] = (ob["h"] + ob["l"]) / 2
                return ob
        if direction == "bearish" and r[i]["c"] > r[i]["o"]:
            if sum(1 for j in range(1, 4) if i+j < n and r[i+j]["c"] < r[i+j]["o"]) >= 2:
                ob = {"h": r[i]["c"], "l": r[i]["o"]}
                if any(r[j]["c"] > ob["h"] for j in range(i+1, n)): continue
                ob["mid"] = (ob["h"] + ob["l"]) / 2
                return ob
    return None

def ob_rejection(bars, ob, direction):
    if not ob or len(bars) < 1: return False
    last = bars[-1]
    body = abs(last["c"] - last["o"])
    if body == 0: return False
    if direction == "bullish":
        wick = min(last["o"], last["c"]) - last["l"]
        in_z = last["l"] <= ob["h"] and last["c"] >= ob["l"]
        return last["c"] > last["o"] and wick >= body * 0.4 and in_z
    else:
        wick = last["h"] - max(last["o"], last["c"])
        in_z = last["h"] >= ob["l"] and last["c"] <= ob["h"]
        return last["c"] < last["o"] and wick >= body * 0.4 and in_z

def liq_sweep(bars, direction, lookback=30):
    r = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(5, len(r)):
        w = r[max(0, i-8):i]
        if direction == "bullish":
            lo = min(b["l"] for b in w)
            if r[i]["l"] < lo and r[i]["c"] > lo: return True
        else:
            hi = max(b["h"] for b in w)
            if r[i]["h"] > hi and r[i]["c"] < hi: return True
    return False

def bos_check(bars, direction, lookback=30):
    r = bars[-lookback:] if len(bars) >= lookback else bars
    if len(r) < 8: return False
    m = len(r) // 2; e, l = r[:m], r[m:]
    if direction == "bullish":
        return any(b["c"] > max(x["h"] for x in e) for b in l)
    return any(b["c"] < min(x["l"] for x in e) for b in l)

def find_fvg(bars, direction, lookback=40):
    r = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(2, len(r)):
        if direction == "bullish" and r[i]["l"] > r[i-2]["h"]: return True
        if direction == "bearish" and r[i]["h"] < r[i-2]["l"]: return True
    return False

def momentum_check(bars, direction):
    if len(bars) < 3: return False
    last2 = bars[-2:]
    if direction == "bullish": return all(b["c"] > b["o"] for b in last2)
    return all(b["c"] < b["o"] for b in last2)

# ──────────────────────────────────────────────────────────────────────────────
# CORRELATION FILTER  (improvement #8)
# ──────────────────────────────────────────────────────────────────────────────
def passes_correlation(name, open_positions):
    """Return True if taking this trade doesn't double up on a currency."""
    open_names = set(open_positions)
    for group in CORR_GROUPS:
        if name in group:
            if open_names & (group - {name}):
                return False
    return True

# ──────────────────────────────────────────────────────────────────────────────
# SIGNAL ANALYSIS  (multi-TF + all new confluences)
# ──────────────────────────────────────────────────────────────────────────────
def analyze(name, cfg, headers):
    """
    Full SMC analysis with improved scoring.
    Max possible score: 18  |  Min required: 7
    """
    time.sleep(0.8)
    b4  = fetch_bars(headers, cfg["id"], "4H", 30)
    time.sleep(0.4)
    b1  = fetch_bars(headers, cfg["id"], "1H", 20)
    time.sleep(0.4)
    b15 = fetch_bars(headers, cfg["id"], "15m", 5)

    if len(b4) < 20 or len(b1) < 40:
        return None

    pip = cfg["pip"]

    # ── Multi-TF structure using real swing points ─────────────────────────
    dir_4h = market_structure(b4, 80, 3)
    dir_1h = market_structure(b1, 60, 2)

    if dir_4h == "ranging" and dir_1h == "ranging":
        return None
    if dir_4h != "ranging" and dir_1h != "ranging" and dir_4h != dir_1h:
        return None

    direction = dir_4h if dir_4h != "ranging" else dir_1h
    price     = b1[-1]["c"]

    score = 0
    tags  = []

    # 1. Trend alignment (max 2)
    if dir_4h != "ranging" and dir_1h != "ranging":
        score += 2; tags.append("4H+1H aligned ✅")
    else:
        score += 1; tags.append("single-TF trend")

    # 2. Session bonus (max 1)
    if in_session():
        score += 1; tags.append(f"{session_name()} session ✅")

    # 3. Premium/Discount zone (max 2) — key filter
    if in_premium_discount(b1, direction):
        score += 2; tags.append("P&D zone ✅")
    else:
        # Outside zone — significantly lower quality, can still trade but rare
        tags.append("outside P&D zone ⚠")

    # 4. VWAP bias (max 1)
    if vwap_bias(b1, direction):
        score += 1; tags.append("VWAP aligned ✅")

    # 5. Order Block 1H (max 3)
    ob_1h = find_ob(b1, direction)
    in_ob = ob_1h and ob_1h["l"] <= price <= ob_1h["h"]
    rej   = ob_rejection(b1, ob_1h, direction)
    if in_ob and rej:
        score += 3; tags.append("1H OB rejection ✅")
    elif in_ob:
        score += 2; tags.append("inside 1H OB")
    elif ob_1h:
        near = (direction == "bullish" and price <= ob_1h["h"] * 1.001) or \
               (direction == "bearish" and price >= ob_1h["l"] * 0.999)
        if near:
            score += 1; tags.append("approaching 1H OB")

    # 6. Liquidity sweep 1H (max 2)
    if liq_sweep(b1, direction):
        score += 2; tags.append("liq sweep ✅")

    # 7. CHoCH (max 2)
    if choch(b1, direction):
        score += 2; tags.append("CHoCH ✅")

    # 8. BOS (max 1)
    if bos_check(b1, direction):
        score += 1; tags.append("BOS ✅")

    # 9. Equal H/L liquidity (max 1)
    if equal_highs_lows(b1, direction):
        score += 1; tags.append("equal H/L BSL ✅")

    # 10. FVG (max 1)
    if find_fvg(b1, direction):
        score += 1; tags.append("FVG")

    # 11. PDH/PDL confluence (max 1)
    pdh, pdl = prev_day_levels(b1)
    if near_pdh_pdl(b1, direction, pdh, pdl, 10, pip):
        score += 1; tags.append("PDH/PDL confluence")

    # 12. 15M OB confirmation (max 1)
    if len(b15) >= 20:
        ob15 = find_ob(b15, direction, 30)
        if ob15 and ob_rejection(b15, ob15, direction):
            score += 1; tags.append("15M OB ✅")

    # 13. Momentum (max 1)
    if momentum_check(b1, direction):
        score += 1; tags.append("momentum")

    if score < MIN_SCORE:
        return None

    # ── Levels ────────────────────────────────────────────────────────────
    entry = price

    # SL: just beyond the OB if available, else recent structure
    if ob_1h and in_ob:
        if direction == "bullish":
            sl = round(ob_1h["l"] - 3 * pip, 5)
        else:
            sl = round(ob_1h["h"] + 3 * pip, 5)
    else:
        if direction == "bullish":
            sl = round(min(b["l"] for b in b1[-15:]) - 3 * pip, 5)
        else:
            sl = round(max(b["h"] for b in b1[-15:]) + 3 * pip, 5)

    risk      = abs(entry - sl)
    risk_pips = round(risk / pip, 1)

    if risk_pips < MIN_RISK_PIPS: return None
    if pip <= 0.0001 and risk_pips > 60: return None

    sign = 1 if direction == "bullish" else -1
    tp1  = round(entry + risk * 1.5 * sign, 5)   # 1:1.5 partial close
    tp2  = round(entry + risk * 2.5 * sign, 5)   # 1:2.5 full target

    return {
        "name":      name,
        "direction": direction,
        "score":     score,
        "entry":     round(entry, 5),
        "sl":        round(sl, 5),
        "tp1":       tp1,
        "tp2":       tp2,
        "rr":        "1:2.5",
        "risk_pips": risk_pips,
        "tags":      tags,
        "cfg":       cfg,
        "bars_1h":   b1,
    }

# ──────────────────────────────────────────────────────────────────────────────
# POSITION SIZING
# ──────────────────────────────────────────────────────────────────────────────
def calc_lots(risk_pips, pip_val, balance):
    risk_usd = balance * RISK_PCT
    raw = risk_usd / (risk_pips * pip_val) if risk_pips * pip_val > 0 else 0.01
    return round(max(0.01, min(raw, MAX_LOTS)), 2)

# ──────────────────────────────────────────────────────────────────────────────
# PLACE TRADE
# ──────────────────────────────────────────────────────────────────────────────
def place_trade(headers, account_id, setup, balance):
    cfg  = setup["cfg"]
    side = "buy" if setup["direction"] == "bullish" else "sell"
    lots = calc_lots(setup["risk_pips"], cfg["pip_val"], balance)
    body = {
        "tradableInstrumentId": cfg["id"],
        "routeId":              TRADE_ROUTE,
        "type":                 "market",
        "side":                 side,
        "qty":                  lots,
        "validity":             "IOC",
        "stopLoss":             setup["sl"],
        "takeProfit":           setup["tp2"],
        "stopLossType":         "absolute",
        "takeProfitType":       "absolute",
    }
    r = requests.post(f"{BASE_URL}/trade/accounts/{account_id}/orders",
                      headers=headers, json=body, timeout=15)
    d = r.json()
    return d.get("s") == "ok", d.get("d", {}).get("orderId"), lots

# ──────────────────────────────────────────────────────────────────────────────
# BREAKEVEN MANAGEMENT  (improvement #9)
# ──────────────────────────────────────────────────────────────────────────────
def get_positions(headers, account_id):
    r = requests.get(f"{BASE_URL}/trade/accounts/{account_id}/positions",
                     headers=headers, timeout=15)
    return r.json().get("d", {}).get("positions", [])

def modify_position_sl(headers, account_id, position_id, new_sl):
    """Modify SL on an open position."""
    r = requests.patch(
        f"{BASE_URL}/trade/accounts/{account_id}/positions/{position_id}",
        headers=headers,
        json={"stopLoss": new_sl, "stopLossType": "absolute"},
        timeout=15,
    )
    return r.status_code == 200

def manage_breakeven(headers, account_id, active_trades):
    """
    For each tracked trade: if price has reached TP1, move SL to entry (breakeven).
    Updates the active_trades dict in place.
    """
    if not active_trades:
        return

    positions = {str(p[0]): p for p in get_positions(headers, account_id)}

    for pos_id, trade in list(active_trades.items()):
        pos = positions.get(pos_id)
        if pos is None:
            # Position closed — remove from tracking
            del active_trades[pos_id]
            continue

        entry     = trade["entry"]
        tp1       = trade["tp1"]
        sl        = trade["sl"]
        direction = trade["direction"]
        be_moved  = trade.get("be_moved", False)

        if be_moved:
            continue

        current_price = float(pos[5])  # entry price from position; use pnl to infer current
        pnl = float(pos[9])
        pip_val = MARKETS.get(trade["name"], {}).get("pip_val", 10.0)
        qty = float(pos[4])
        # Estimate current price from pnl
        pips_in_profit = pnl / (qty * pip_val) if qty * pip_val else 0
        pip = MARKETS.get(trade["name"], {}).get("pip", 0.0001)
        est_price = entry + pips_in_profit * pip * (1 if direction == "bullish" else -1)

        tp1_hit = (direction == "bullish" and est_price >= tp1) or \
                  (direction == "bearish" and est_price <= tp1)

        if tp1_hit:
            # Move SL to entry + 1 pip buffer
            buffer = 1 * pip
            be_sl = round(entry + buffer if direction == "bullish" else entry - buffer, 5)
            ok = modify_position_sl(headers, account_id, pos_id, be_sl)
            if ok:
                active_trades[pos_id]["sl"] = be_sl
                active_trades[pos_id]["be_moved"] = True
                name = trade["name"]
                print(f"  🔒 Breakeven set: {name} SL→{be_sl}")
                tg_send(
                    f"🔒 BREAKEVEN SET\n\n"
                    f"{name} — TP1 reached ✅\n"
                    f"SL moved to entry {be_sl}\n"
                    f"Trade now risk-free 🛡"
                )

# ──────────────────────────────────────────────────────────────────────────────
# CHART
# ──────────────────────────────────────────────────────────────────────────────
def generate_chart(bars, pair_label, entry, sl, tp1, tp2, direction, save_path):
    BG = "#131722"; BULL = "#26a69a"; BEAR = "#ef5350"
    disp = bars[-100:] if len(bars) >= 100 else bars
    n    = len(disp)
    fig, ax = plt.subplots(figsize=(16, 9), facecolor=BG)
    ax.set_facecolor(BG)
    for i, b in enumerate(disp):
        o, c, hi, lo = b["o"], b["c"], b["h"], b["l"]
        col = BULL if c >= o else BEAR
        ax.plot([i, i], [lo, hi], color=col, linewidth=0.8)
        ax.add_patch(plt.Rectangle((i-0.35, min(o, c)), 0.7,
                                   max(abs(c-o), (hi-lo)*0.01), color=col, zorder=3))
    lo_all = min(b["l"] for b in disp)
    hi_all = max(b["h"] for b in disp)
    pad    = (hi_all - lo_all) * 0.08
    lx     = n + n * 0.02
    for lv, col, ls, lbl in [
        (entry, "#FFD700", "-",  f"ENTRY  {entry:.5f}"),
        (sl,    "#ef5350", "--", f"SL      {sl:.5f}"),
        (tp1,   "#66BB6A", "--", f"TP1    {tp1:.5f}"),
        (tp2,   "#00E676", "--", f"TP2    {tp2:.5f}"),
    ]:
        ax.axhline(lv, color=col, linestyle=ls, linewidth=1.6, alpha=0.9)
        ax.text(lx, lv, lbl, color=col, fontsize=8, va="center", ha="left",
                fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.2", facecolor=BG, edgecolor="none", alpha=0.8))
    # Risk zone shading
    lo_z = min(entry, sl); hi_z = max(entry, sl)
    ax.axhspan(lo_z, hi_z, alpha=0.07, color="#ef5350")
    ax.text(0.01, 0.97, pair_label, transform=ax.transAxes, color="white",
            fontsize=13, fontweight="bold", va="top")
    dlbl = "▲ BUY" if direction == "bullish" else "▼ SELL"
    ax.text(0.99, 0.97, dlbl, transform=ax.transAxes,
            color=BULL if direction == "bullish" else BEAR,
            fontsize=11, fontweight="bold", va="top", ha="right")
    ax.yaxis.tick_right(); ax.tick_params(colors="gray", labelsize=8)
    for sp in ax.spines.values(): sp.set_edgecolor("#2a2e39")
    ax.set_xlim(-1, n + n * 0.22)
    ax.set_ylim(min(lo_all, sl) - pad, max(hi_all, tp2) + pad)
    ax.set_xticks([]); ax.grid(False)
    plt.tight_layout(pad=0.3)
    plt.savefig(save_path, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close()

# ──────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────────────────────────────────────
def tg_send(text):
    if not TG_ALERTS or not TG_CHAT:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": text}, timeout=15)
    except Exception:
        pass

def tg_photo(image_path, caption=""):
    if not TG_ALERTS or not TG_CHAT:
        return
    try:
        with open(image_path, "rb") as f:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                          data={"chat_id": TG_CHAT, "caption": caption},
                          files={"photo": f}, timeout=30)
    except Exception:
        pass

def send_trade_alert(setup, chart_path):
    pip   = setup["cfg"]["pip"]
    arrow = "📈" if setup["direction"] == "bullish" else "📉"
    side  = "BUY" if setup["direction"] == "bullish" else "SELL"
    tp1p  = round(abs(setup["tp1"] - setup["entry"]) / pip, 1)
    tp2p  = round(abs(setup["tp2"] - setup["entry"]) / pip, 1)
    caption = (
        f"🔥 TRADE ALERT 🔥\n\n"
        f"{arrow} {setup['name']} {side}\n"
        f"💰 Entry: {setup['entry']}\n"
        f"🛑 Stop Loss: {setup['sl']}\n"
        f"🎯 TP1: {setup['tp1']} (+{tp1p}p)\n"
        f"🎯 TP2: {setup['tp2']} (+{tp2p}p)\n"
        f"📊 RR: {setup['rr']}  |  Score: {setup['score']}/18\n"
        f"🧠 {' | '.join(setup['tags'][:4])}"
    )
    tg_photo(chart_path, caption=caption)

# ──────────────────────────────────────────────────────────────────────────────
# PIP UPDATE
# ──────────────────────────────────────────────────────────────────────────────
def send_pip_update(headers, account_id):
    positions = get_positions(headers, account_id)
    now = datetime.datetime.utcnow().strftime("%H:%M UTC")
    if not positions:
        tg_send(f"📊 PIP UPDATE — {now}\n\nNo open positions. Watching markets 👀")
        return
    lines = [f"📊 PIP UPDATE — {now}\n"]
    total_pips = 0.0
    for p in positions:
        iid  = int(p[1])
        name = ID_TO_NAME.get(iid, f"ID:{iid}")
        side = p[3].upper()
        qty  = float(p[4])
        pnl  = float(p[9])
        cfg  = MARKETS.get(name, {})
        pv   = cfg.get("pip_val", 10.0)
        pips = round(pnl / (qty * pv), 1) if qty * pv else 0
        total_pips += pips
        icon = "🟢" if pips >= 0 else "🔴"
        lines.append(f"{icon} {name} {side}  {pips:+.1f} pips")
    lines.append(f"\n{'─'*20}")
    t_icon = "🟢" if total_pips >= 0 else "🔴"
    lines.append(f"{t_icon} Total  {total_pips:+.1f} pips")
    tg_send("\n".join(lines))

# ──────────────────────────────────────────────────────────────────────────────
# ENGAGEMENT
# ──────────────────────────────────────────────────────────────────────────────
ENGAGE_MSGS = [
    "💬 How is everyone doing this session? Drop your thoughts below!",
    "👀 What setups are you watching right now? Share with the group!",
    "❓ Any questions about today's signals? Ask away.",
    "🔥 Stay disciplined. Quality over quantity — always.",
    "💡 Reminder: Let the trade come to you. Never chase entries.",
    "🧠 Risk management first. Profits follow discipline.",
    "📈 Patience is an edge. The best setups are worth waiting for.",
    "🛡 Remember: once TP1 hits, we move SL to breakeven. Risk-free from there.",
]
_engage_idx = 0

def send_engagement():
    global _engage_idx
    tg_send(ENGAGE_MSGS[_engage_idx % len(ENGAGE_MSGS)])
    _engage_idx += 1

# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────
def run():
    print("=" * 60)
    print(" AI Trading Agent — Improved SMC Strategy")
    print(f" Server  : {SERVER}  |  Account: {TARGET_ACC}")
    print(f" Risk    : {RISK_PCT*100:.0f}%  |  Min score: {MIN_SCORE}/18")
    print(f" Session : London 07-12 UTC + New York 13-17 UTC")
    print("=" * 60)

    headers, account_id, balance = auth()
    token_time   = time.time()
    state        = load_state()
    active_trades = load_active_trades()

    print(f"  Balance: ${balance:,.2f}")
    print(f"  Active tracked trades: {len(active_trades)}")
    print()

    while True:
        now_ts = time.time()

        # Refresh token every 20 min
        if now_ts - token_time > 1200:
            try:
                headers, account_id, balance = auth()
                token_time = now_ts
            except Exception as e:
                print(f"  Token refresh failed: {e}")

        state = reset_daily(state)
        ts    = datetime.datetime.utcnow().strftime("%H:%M UTC")

        # ── BREAKEVEN CHECK (every scan) ──────────────────────────────────
        try:
            manage_breakeven(headers, account_id, active_trades)
            save_active_trades(active_trades)
        except Exception as e:
            print(f"  Breakeven check error: {e}")

        # ── SCAN (session-gated) ──────────────────────────────────────────
        if state["trades_today"] < MAX_TRADES:
            sess = session_name()
            if not in_session():
                print(f"[{ts}] Outside session ({sess}) — scan skipped. "
                      f"Next: London 07:00 UTC or NY 13:00 UTC")
            else:
                print(f"[{ts}] {sess} session — scanning {len(MARKETS)} markets...")

                # Get open position names for correlation check
                open_positions = get_positions(headers, account_id)
                open_names = set()
                for p in open_positions:
                    nm = ID_TO_NAME.get(int(p[1]))
                    if nm:
                        open_names.add(nm)

                setups = []
                for name, cfg in MARKETS.items():
                    # Correlation filter — skip if correlated pair already open
                    if not passes_correlation(name, open_names):
                        print(f"  ⊘  {name} — correlated position open")
                        continue
                    try:
                        result = analyze(name, cfg, headers)
                        if result:
                            setups.append(result)
                            print(f"  ✅ {name} {result['direction'].upper()} "
                                  f"score={result['score']}/18  risk={result['risk_pips']}p  "
                                  f"{result['tags'][:3]}")
                        else:
                            print(f"  —  {name}")
                    except Exception as ex:
                        traceback.print_exc()
                        print(f"  ⚠  {name}: {ex}")

                setups.sort(key=lambda x: x["score"], reverse=True)

                if setups:
                    top = setups[0]
                    print(f"\n  Best: {top['name']} {top['direction'].upper()} "
                          f"[{top['score']}/18]  risk={top['risk_pips']}p")

                    # Refresh balance
                    try:
                        accs    = requests.get(f"{BASE_URL}/auth/jwt/all-accounts",
                                               headers=headers, timeout=10).json()
                        balance = float(accs["accounts"][0]["accountBalance"])
                    except Exception:
                        pass

                    ok, order_id, lots = place_trade(headers, account_id, top, balance)
                    if ok:
                        state["trades_today"] += 1
                        save_state(state)
                        print(f"  ✅ Order {order_id} — {lots} lots")

                        # Track for breakeven management
                        active_trades[str(order_id)] = {
                            "name":      top["name"],
                            "direction": top["direction"],
                            "entry":     top["entry"],
                            "tp1":       top["tp1"],
                            "tp2":       top["tp2"],
                            "sl":        top["sl"],
                            "be_moved":  False,
                        }
                        save_active_trades(active_trades)

                        # Chart + alert
                        chart = f"/tmp/chart_{top['name'].lower()}.png"
                        try:
                            generate_chart(top["bars_1h"], f"{top['name']} • H1",
                                           top["entry"], top["sl"],
                                           top["tp1"], top["tp2"],
                                           top["direction"], chart)
                            send_trade_alert(top, chart)
                        except Exception as e:
                            print(f"  Chart error: {e}")
                    else:
                        print("  ❌ Order failed")
                else:
                    print("  No qualifying setups this scan.")
        else:
            print(f"[{ts}] Daily limit reached ({MAX_TRADES} trades). Monitoring only.")

        # ── 4H PIP UPDATE ─────────────────────────────────────────────────
        if now_ts - state["last_update"] >= UPDATE_EVERY:
            send_pip_update(headers, account_id)
            state["last_update"] = now_ts
            save_state(state)

        # ── ENGAGEMENT ────────────────────────────────────────────────────
        if now_ts - state.get("last_engage", 0) >= UPDATE_EVERY:
            send_engagement()
            state["last_engage"] = now_ts
            save_state(state)

        print(f"  Trades today: {state['trades_today']}/{MAX_TRADES}. "
              f"Next scan in {SCAN_EVERY//60} min.\n")
        time.sleep(SCAN_EVERY)


if __name__ == "__main__":
    run()
