"""
AI Forex Trading Agent
======================
Multi-timeframe SMC scanner + auto-execution on TradeLocker + Telegram alerts.

Markets  : Major/Minor Forex, Gold (XAUUSD), SPX500, NAS100
Strategy : Smart Money Concepts — Order Blocks, FVG, Liquidity Sweeps, BOS
Timeframes: 4H trend → 1H structure → 15M entry trigger
Risk     : 2% per trade, max 3 trades/day, 8-pip minimum SL

Environment variables required:
  TL_EMAIL      — TradeLocker account email
  TL_PASSWORD   — TradeLocker account password
  TL_SERVER     — TradeLocker broker server (default: PLEXY)
  TG_BOT_TOKEN  — Telegram bot token
  TG_CHAT_ID    — Telegram group/channel chat ID

Usage:
  python trading_agent.py
"""

import os
import time
import json
import datetime
import io
import requests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

BASE_URL     = "https://demo.tradelocker.com/backend-api"
EMAIL        = os.environ["TL_EMAIL"]
PASSWORD     = os.environ["TL_PASSWORD"]
SERVER       = os.environ.get("TL_SERVER", "PLEXY")
TG_TOKEN     = os.environ["TG_BOT_TOKEN"]
TG_CHAT      = os.environ["TG_CHAT_ID"]

RISK_PCT     = 0.02       # 2% risk per trade
MAX_TRADES   = 3          # max trades per day
MIN_SCORE    = 6          # minimum signal score out of 12
MIN_RISK_PIPS = 8         # minimum SL distance — prevents tight stops
MAX_LOTS     = 10.0       # position size cap
SCAN_EVERY   = 900        # seconds between scans (15 min)
UPDATE_EVERY = 14400      # seconds between pip updates (4 hours)
TG_ALERTS    = True       # set False to pause Telegram, keep TL execution

STATE_FILE   = "agent_state.json"

# ──────────────────────────────────────────────────────────────────────────────
# MARKETS
# ──────────────────────────────────────────────────────────────────────────────

MARKETS = {
    # name       : {id, pip size, pip value per 1 lot in USD}
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
    "SPX500": {"id": 307, "pip": 1.0,    "pip_val":  1.00},
    "NAS100": {"id": 306, "pip": 1.0,    "pip_val":  1.00},
}

# Map instrument IDs back to names for position tracking
ID_TO_NAME = {v["id"]: k for k, v in MARKETS.items()}

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

# ──────────────────────────────────────────────────────────────────────────────
# TRADELOCKER AUTH
# ──────────────────────────────────────────────────────────────────────────────

def auth():
    """Authenticate and return (headers, account_id, balance)."""
    r = requests.post(f"{BASE_URL}/auth/jwt/token",
                      json={"email": EMAIL, "password": PASSWORD, "server": SERVER},
                      timeout=15)
    token = r.json()["accessToken"]
    h = {"Authorization": f"Bearer {token}"}
    accs = requests.get(f"{BASE_URL}/auth/jwt/all-accounts", headers=h, timeout=15).json()
    acc  = accs["accounts"][0]
    h["accNum"] = str(acc["accNum"])
    return h, acc["id"], float(acc["accountBalance"])

# ──────────────────────────────────────────────────────────────────────────────
# DATA FETCHING
# ──────────────────────────────────────────────────────────────────────────────

def fetch_bars(headers, instrument_id, resolution, days):
    """
    Fetch OHLCV bars from TradeLocker.

    resolution : "15m" | "1H" | "4H" | "1D"
    days       : how many days of history to fetch
    """
    now_ms = int(time.time() * 1000)
    frm_ms = now_ms - int(days * 86400 * 1000)
    for attempt in range(4):
        try:
            r = requests.get(f"{BASE_URL}/trade/history", headers=headers, params={
                "tradableInstrumentId": instrument_id,
                "routeId":              452,
                "resolution":           resolution,
                "from":                 frm_ms,
                "to":                   now_ms,
            }, timeout=15)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                bars = r.json().get("d", {}).get("barDetails", [])
                if bars:
                    return bars
        except Exception:
            pass
        time.sleep(2 ** attempt)
    return []

# ──────────────────────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS
# ──────────────────────────────────────────────────────────────────────────────

def atr(bars, period=14):
    """Average True Range."""
    if len(bars) < 2:
        return 0
    trs = [
        max(bars[i]["h"] - bars[i]["l"],
            abs(bars[i]["h"] - bars[i-1]["c"]),
            abs(bars[i]["l"] - bars[i-1]["c"]))
        for i in range(1, len(bars))
    ]
    return sum(trs[-period:]) / min(len(trs), period)


def market_structure(bars, lookback=24):
    """
    Determine trend direction by comparing first vs second half of lookback.
    Returns: "bullish" | "bearish" | "ranging"
    """
    if len(bars) < lookback:
        return "ranging"
    r = bars[-lookback:]
    m = lookback // 2
    early, late = r[:m], r[m:]
    hh = max(b["h"] for b in late)  > max(b["h"] for b in early)
    hl = min(b["l"] for b in late)  > min(b["l"] for b in early)
    lh = max(b["h"] for b in late)  < max(b["h"] for b in early)
    ll = min(b["l"] for b in late)  < min(b["l"] for b in early)
    if hh and hl: return "bullish"
    if lh and ll: return "bearish"
    return "ranging"


def find_order_block(bars, direction, lookback=60):
    """
    Find the most recent UNMITIGATED order block.

    For bullish  : last bearish candle before a 2-of-3 bullish impulse,
                   where no later candle has CLOSED below the OB body.
    For bearish  : last bullish candle before a 2-of-3 bearish impulse,
                   where no later candle has CLOSED above the OB body.

    Returns dict {"h", "l", "mid"} or None.
    """
    r = bars[-lookback:] if len(bars) >= lookback else bars
    n = len(r)
    for i in range(n - 5, 1, -1):
        if direction == "bullish" and r[i]["c"] < r[i]["o"]:
            impulse = sum(1 for j in range(1, 4) if i+j < n and r[i+j]["c"] > r[i+j]["o"])
            if impulse >= 2:
                ob = {"h": r[i]["o"], "l": r[i]["c"]}  # use candle body
                # Mitigation: any close below OB low = zone consumed
                if any(r[j]["c"] < ob["l"] for j in range(i + 1, n)):
                    continue
                ob["mid"] = (ob["h"] + ob["l"]) / 2
                return ob

        if direction == "bearish" and r[i]["c"] > r[i]["o"]:
            impulse = sum(1 for j in range(1, 4) if i+j < n and r[i+j]["c"] < r[i+j]["o"])
            if impulse >= 2:
                ob = {"h": r[i]["c"], "l": r[i]["o"]}
                if any(r[j]["c"] > ob["h"] for j in range(i + 1, n)):
                    continue
                ob["mid"] = (ob["h"] + ob["l"]) / 2
                return ob
    return None


def ob_rejection(bars, ob, direction):
    """
    Check if the last candle shows a genuine rejection from the OB.
    Requires: directional close + rejection wick >= 40% of body.
    """
    if not ob or len(bars) < 2:
        return False
    last = bars[-1]
    body = abs(last["c"] - last["o"])
    if body == 0:
        return False
    if direction == "bullish":
        wick    = min(last["o"], last["c"]) - last["l"]
        in_zone = last["l"] <= ob["h"] and last["c"] >= ob["l"]
        return last["c"] > last["o"] and wick >= body * 0.4 and in_zone
    else:
        wick    = last["h"] - max(last["o"], last["c"])
        in_zone = last["h"] >= ob["l"] and last["c"] <= ob["h"]
        return last["c"] < last["o"] and wick >= body * 0.4 and in_zone


def find_fvg(bars, direction, lookback=40):
    """Fair Value Gap — gap between candle[i-2].high and candle[i].low (bullish) or inverse."""
    r = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(2, len(r)):
        if direction == "bullish" and r[i]["l"] > r[i-2]["h"]:
            return {"h": r[i]["l"], "l": r[i-2]["h"]}
        if direction == "bearish" and r[i]["h"] < r[i-2]["l"]:
            return {"h": r[i-2]["l"], "l": r[i]["h"]}
    return None


def liquidity_sweep(bars, direction, lookback=30):
    """Price swept below (bullish) or above (bearish) a prior swing and closed back."""
    r = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(5, len(r)):
        window = r[max(0, i-8):i]
        if direction == "bullish":
            low = min(b["l"] for b in window)
            if r[i]["l"] < low and r[i]["c"] > low:
                return True
        else:
            high = max(b["h"] for b in window)
            if r[i]["h"] > high and r[i]["c"] < high:
                return True
    return False


def break_of_structure(bars, direction, lookback=30):
    """Price closed above (bullish) or below (bearish) the earlier half's extreme."""
    r = bars[-lookback:] if len(bars) >= lookback else bars
    if len(r) < 8:
        return False
    m = len(r) // 2
    early, late = r[:m], r[m:]
    if direction == "bullish":
        return any(b["c"] > max(x["h"] for x in early) for b in late)
    return any(b["c"] < min(x["l"] for x in early) for b in late)

# ──────────────────────────────────────────────────────────────────────────────
# SIGNAL ANALYSIS  (4H trend + 1H structure + 15M entry)
# ──────────────────────────────────────────────────────────────────────────────

def analyze(name, cfg, headers):
    """
    Score a market across three timeframes.
    Returns a setup dict or None if score < MIN_SCORE or SL < MIN_RISK_PIPS.
    """
    time.sleep(1)
    bars_4h  = fetch_bars(headers, cfg["id"], "4H",  20)
    time.sleep(0.4)
    bars_1h  = fetch_bars(headers, cfg["id"], "1H",  10)
    time.sleep(0.4)
    bars_15m = fetch_bars(headers, cfg["id"], "15m",  3)
    time.sleep(0.6)

    if len(bars_4h) < 20 or len(bars_1h) < 40 or len(bars_15m) < 30:
        return None

    trend_4h = market_structure(bars_4h)
    trend_1h = market_structure(bars_1h)

    # Both ranging → no trade
    if trend_4h == "ranging" and trend_1h == "ranging":
        return None
    # Conflicting direction → no trade
    if trend_4h != "ranging" and trend_1h != "ranging" and trend_4h != trend_1h:
        return None

    direction = trend_4h if trend_4h != "ranging" else trend_1h
    price     = bars_1h[-1]["c"]
    pip       = cfg["pip"]

    # ── 1H confluences ────────────────────────────────────────────
    ob_1h    = find_order_block(bars_1h, direction)
    fvg_1h   = find_fvg(bars_1h, direction)
    liq_1h   = liquidity_sweep(bars_1h, direction)
    bos_1h   = break_of_structure(bars_1h, direction)
    rej_1h   = ob_rejection(bars_1h, ob_1h, direction)
    in_ob_1h = ob_1h and ob_1h["l"] <= price <= ob_1h["h"]

    # ── 15M entry confluences ─────────────────────────────────────
    ob_15m   = find_order_block(bars_15m, direction)
    fvg_15m  = find_fvg(bars_15m, direction)
    liq_15m  = liquidity_sweep(bars_15m, direction)
    rej_15m  = ob_rejection(bars_15m, ob_15m, direction)
    in_ob_15 = ob_15m and ob_15m["l"] <= price <= ob_15m["h"]

    # ── SCORING ───────────────────────────────────────────────────
    score = 0
    tags  = []

    # Trend alignment (max 2)
    if trend_4h == direction and trend_1h == direction:
        score += 2; tags.append("4H+1H aligned")
    elif trend_4h == direction:
        score += 1; tags.append("4H trend")
    else:
        score += 1; tags.append("1H trend")

    # 1H Order Block (max 3)
    if in_ob_1h and rej_1h:
        score += 3; tags.append("1H OB rejection ✅")
    elif in_ob_1h:
        score += 2; tags.append("inside 1H OB")
    elif ob_1h:
        score += 1; tags.append("1H OB nearby")

    # 15M OB (max 2)
    if in_ob_15 and rej_15m:
        score += 2; tags.append("15M OB rejection ✅")
    elif in_ob_15:
        score += 1; tags.append("inside 15M OB")

    # Liquidity (max 2)
    if liq_1h:
        score += 2; tags.append("1H liq sweep")
    elif liq_15m:
        score += 1; tags.append("15M liq sweep")

    # BOS (max 1)
    if bos_1h:
        score += 1; tags.append("1H BOS")

    # FVG (max 1)
    if fvg_1h or fvg_15m:
        score += 1; tags.append("FVG present")

    if score < MIN_SCORE:
        return None

    # ── LEVELS ────────────────────────────────────────────────────
    entry = price

    # SL anchored to recent structure — not OB boundary
    if direction == "bullish":
        struct = min(b["l"] for b in bars_1h[-20:])
        sl     = round(struct - 2 * pip, 5)
    else:
        struct = max(b["h"] for b in bars_1h[-20:])
        sl     = round(struct + 2 * pip, 5)

    risk      = abs(entry - sl)
    risk_pips = round(risk / pip, 1)

    # Hard floor: reject if SL too tight to survive spread/noise
    if risk_pips < MIN_RISK_PIPS:
        return None

    # Wide-SL filter for standard forex pairs
    if pip == 0.0001 and risk_pips > 40:
        return None

    sign = 1 if direction == "bullish" else -1
    tp1  = round(entry + risk * 1.5 * sign, 5)
    tp2  = round(entry + risk * 2.5 * sign, 5)

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
        "trend_4h":  trend_4h,
        "trend_1h":  trend_1h,
        "ob_1h":     ob_1h,
        "ob_15m":    ob_15m,
        "cfg":       cfg,
        "bars_1h":   bars_1h,
    }

# ──────────────────────────────────────────────────────────────────────────────
# POSITION SIZING
# ──────────────────────────────────────────────────────────────────────────────

def calc_lots(risk_pips, pip_val, balance):
    """2% risk position sizing, capped at MAX_LOTS."""
    risk_usd = balance * RISK_PCT
    raw      = risk_usd / (risk_pips * pip_val) if risk_pips * pip_val > 0 else 0.01
    return round(max(0.01, min(raw, MAX_LOTS)), 2)

# ──────────────────────────────────────────────────────────────────────────────
# TRADE EXECUTION
# ──────────────────────────────────────────────────────────────────────────────

def place_trade(headers, account_id, setup, balance):
    """Place a market order on TradeLocker. Returns (success, order_id)."""
    cfg  = setup["cfg"]
    side = "buy" if setup["direction"] == "bullish" else "sell"
    lots = calc_lots(setup["risk_pips"], cfg["pip_val"], balance)
    body = {
        "tradableInstrumentId": cfg["id"],
        "routeId":              9912,
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
# CHART GENERATION
# ──────────────────────────────────────────────────────────────────────────────

def generate_chart(bars, pair_label, entry, sl, tp1, tp2, save_path):
    """
    Generate a dark-theme H1 chart with Entry / SL / TP1 / TP2 lines.
    Approved format: 100 candles, price axis right, no zones/legend.
    """
    BG        = "#131722"
    BULL_COL  = "#26a69a"
    BEAR_COL  = "#ef5350"
    COL_ENTRY = "#FFD700"
    COL_SL    = "#ef5350"
    COL_TP1   = "#66BB6A"
    COL_TP2   = "#00E676"

    bars = bars[-100:] if len(bars) >= 100 else bars
    n    = len(bars)

    fig, ax = plt.subplots(figsize=(16, 9), facecolor=BG)
    ax.set_facecolor(BG)

    # Draw candles
    for i, b in enumerate(bars):
        o, c, hi, lo = b["o"], b["c"], b["h"], b["l"]
        col = BULL_COL if c >= o else BEAR_COL
        ax.plot([i, i], [lo, hi], color=col, linewidth=0.8, zorder=2)
        body_h = max(abs(c - o), (hi - lo) * 0.015)
        ax.add_patch(plt.Rectangle((i - 0.35, min(o, c)), 0.7, body_h,
                                   color=col, zorder=3))

    # Price lines
    all_prices  = [entry, sl, tp1, tp2]
    price_range = max(b["h"] for b in bars) - min(b["l"] for b in bars)
    pad         = price_range * 0.10
    label_x     = n + n * 0.015

    for level, col, ls, lw, lbl in [
        (entry, COL_ENTRY, "-",  1.8, f"Entry  {entry}"),
        (sl,    COL_SL,    "--", 1.6, f"SL      {sl}"),
        (tp1,   COL_TP1,   "--", 1.4, f"TP1    {tp1}"),
        (tp2,   COL_TP2,   "--", 1.6, f"TP2    {tp2}"),
    ]:
        ax.axhline(level, color=col, linestyle=ls, linewidth=lw, alpha=0.92)
        ax.text(label_x, level, str(lbl), color=col, fontsize=7.5,
                va="center", ha="left", fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.18", facecolor=BG,
                          edgecolor="none", alpha=0.75))

    # Pair label
    ax.text(0.01, 0.97, pair_label, transform=ax.transAxes,
            color="white", fontsize=13, fontweight="bold", va="top", ha="left")

    # Axes — price on right only
    ax.yaxis.set_label_position("right")
    ax.yaxis.tick_right()
    ax.tick_params(colors="gray", labelsize=8)
    for sp in ax.spines.values():
        sp.set_edgecolor("#2a2e39")

    lo_all = min(min(b["l"] for b in bars), sl)
    hi_all = max(max(b["h"] for b in bars), tp2)
    ax.set_xlim(-1, n + n * 0.22)
    ax.set_ylim(lo_all - pad, hi_all + pad)
    ax.set_xticks([])
    ax.grid(False)

    plt.tight_layout(pad=0.3)
    plt.savefig(save_path, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close()

# ──────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────────────────────────────────────

def tg_send(text):
    if not TG_ALERTS:
        return
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text},
        timeout=15,
    )

def tg_photo(image_path, caption=""):
    if not TG_ALERTS:
        return
    with open(image_path, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_CHAT, "caption": caption},
            files={"photo": f},
            timeout=30,
        )

# ──────────────────────────────────────────────────────────────────────────────
# TRADE ALERT
# ──────────────────────────────────────────────────────────────────────────────

def send_trade_alert(setup, chart_path):
    """Send chart + alert message to Telegram in approved format."""
    arrow = "📈" if setup["direction"] == "bullish" else "📉"
    side  = "BUY" if setup["direction"] == "bullish" else "SELL"

    caption = (
        f"🔥TRADE ALERT🔥\n\n"
        f"{arrow} {setup['name']} {side}\n"
        f"🎯 Target: {setup['tp2']}\n"
        f"🛑 Stop Loss: {setup['sl']}"
    )
    tg_photo(chart_path, caption=caption)

# ──────────────────────────────────────────────────────────────────────────────
# PIP UPDATE
# ──────────────────────────────────────────────────────────────────────────────

def send_pip_update(headers, account_id):
    """Fetch open positions and send pip-only update to Telegram."""
    raw       = requests.get(f"{BASE_URL}/trade/accounts/{account_id}/positions",
                             headers=headers, timeout=15).json()
    positions = raw.get("d", {}).get("positions", [])
    now       = datetime.datetime.utcnow().strftime("%H:%M UTC")

    if not positions:
        tg_send(f"📊 PIP UPDATE — {now}\n\nNo open positions. Watching the market... 👀")
        return

    lines     = [f"📊 PIP UPDATE — {now}\n"]
    total_pips = 0.0

    for p in positions:
        iid  = int(p[1])
        name = ID_TO_NAME.get(iid, f"ID:{iid}")
        side = p[3].upper()
        qty  = float(p[4])
        pnl  = float(p[9])
        cfg  = MARKETS.get(name)
        pv   = cfg["pip_val"] if cfg else 10.0
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
    "❓ Any questions about today's signals? Ask away — we're here to help.",
    "📊 What markets are showing the cleanest structure right now?",
    "🔥 Stay disciplined traders. Quality over quantity — always.",
    "💡 Reminder: Let the trade come to you. Never chase entries.",
    "🧠 Risk management first. Profits follow discipline.",
    "📈 Patience is a trading edge. The best setups are worth waiting for.",
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
    print("AI Trading Agent starting...")
    print(f"  Markets : {len(MARKETS)}")
    print(f"  Risk    : {RISK_PCT*100:.0f}% per trade")
    print(f"  Max/day : {MAX_TRADES} trades")
    print(f"  Min SL  : {MIN_RISK_PIPS} pips")
    print(f"  Alerts  : {'ON' if TG_ALERTS else 'PAUSED'}")
    print()

    headers, account_id, balance = auth()
    token_time = time.time()
    state      = load_state()

    while True:
        now_ts = time.time()

        # Refresh auth token every 20 minutes
        if now_ts - token_time > 1200:
            try:
                headers, account_id, balance = auth()
                token_time = now_ts
            except Exception as e:
                print(f"  Token refresh failed: {e}")

        state = reset_daily(state)

        # ── MARKET SCAN ───────────────────────────────────────────
        ts = datetime.datetime.utcnow().strftime("%H:%M UTC")

        if state["trades_today"] < MAX_TRADES:
            print(f"[{ts}] Scanning {len(MARKETS)} markets...")
            setups = []

            for name, cfg in MARKETS.items():
                try:
                    result = analyze(name, cfg, headers)
                    if result:
                        setups.append(result)
                        print(f"  ✅ {name} {result['direction'].upper()} "
                              f"score={result['score']}  risk={result['risk_pips']}p")
                    else:
                        print(f"  —  {name} no setup")
                except Exception as ex:
                    print(f"  ⚠  {name} error: {ex}")

            # Take only the highest-scoring setup per scan
            setups.sort(key=lambda x: x["score"], reverse=True)

            if setups:
                top = setups[0]
                print(f"\n  Best: {top['name']} {top['direction'].upper()} "
                      f"[{top['score']}/12]")

                # Refresh balance before sizing
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

                    # Generate chart
                    chart_path = f"/tmp/chart_{top['name'].lower()}.png"
                    generate_chart(
                        bars       = top["bars_1h"],
                        pair_label = f"{top['name']} • H1",
                        entry      = top["entry"],
                        sl         = top["sl"],
                        tp1        = top["tp1"],
                        tp2        = top["tp2"],
                        save_path  = chart_path,
                    )

                    # Send alert with chart
                    send_trade_alert(top, chart_path)
                else:
                    print("  ❌ Order failed")
            else:
                print("  No qualifying setups this scan.")
        else:
            print(f"[{ts}] Daily limit reached ({MAX_TRADES} trades). Monitoring only.")

        # ── 4H PIP UPDATE ─────────────────────────────────────────
        if now_ts - state["last_update"] >= UPDATE_EVERY:
            send_pip_update(headers, account_id)
            state["last_update"] = now_ts
            save_state(state)

        # ── ENGAGEMENT POST ───────────────────────────────────────
        if now_ts - state["last_engage"] >= UPDATE_EVERY:
            send_engagement()
            state["last_engage"] = now_ts
            save_state(state)

        print(f"  Trades today: {state['trades_today']}/{MAX_TRADES}. "
              f"Next scan in {SCAN_EVERY//60} min.\n")
        time.sleep(SCAN_EVERY)


if __name__ == "__main__":
    run()
