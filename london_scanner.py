"""
London Open Scanner — Prop Firm Edition
Run this at 07:00 UTC each day before London open.
Finds the top 1-2 SMC setups for manual confirmation.
Manual confirm adds the 60%+ win rate needed to pass FTMO.
"""

import requests
import time
import datetime

BASE = "https://demo.tradelocker.com/backend-api"
EMAIL = "carlinpool94@gmail.com"
PASSWORD = "Tinapool321!?"
SERVER = "GenFX"

ACCOUNT_BALANCE = 10_000   # update daily
RISK_PCT = 0.02            # 2% risk per trade
MAX_SL_PIPS = 15           # tight SL only

# Prop firm targets
DAILY_LOSS_LIMIT = 500
MAX_DRAWDOWN_LIMIT = 1_000
PROFIT_TARGET = 1_000

PAIRS = {
    "EURUSD": {"id": 278, "routeId": 452, "is_jpy": False, "spread": 0.5,  "pip_val_lot": 10.00, "emoji": "🇪🇺"},
    "GBPUSD": {"id": 279, "routeId": 452, "is_jpy": False, "spread": 1.0,  "pip_val_lot": 10.00, "emoji": "🇬🇧"},
    "USDJPY": {"id": 283, "routeId": 452, "is_jpy": True,  "spread": 1.0,  "pip_val_lot": 6.70,  "emoji": "🇯🇵"},
    "USDCAD": {"id": 281, "routeId": 452, "is_jpy": False, "spread": 1.0,  "pip_val_lot": 7.30,  "emoji": "🇨🇦"},
    "GBPJPY": {"id": 243, "routeId": 452, "is_jpy": True,  "spread": 2.0,  "pip_val_lot": 6.70,  "emoji": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
}

# ─── AUTH ─────────────────────────────────────────────────────────────────────

def auth():
    r = requests.post(f"{BASE}/auth/jwt/token",
                      json={"email": EMAIL, "password": PASSWORD, "server": SERVER})
    tokens = r.json()
    headers = {"Authorization": f"Bearer {tokens['accessToken']}"}
    accounts = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=headers).json()
    account = accounts["accounts"][0]
    return {**headers, "accNum": str(account["accNum"])}, account["id"]

def fetch_bars(headers, instr_id, route_id, resolution, days=30):
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    r = requests.get(f"{BASE}/trade/history", headers=headers, params={
        "tradableInstrumentId": instr_id,
        "routeId": route_id,
        "resolution": resolution,
        "from": from_ms,
        "to": now_ms,
    })
    return r.json().get("d", {}).get("barDetails", [])

# ─── INDICATORS ───────────────────────────────────────────────────────────────

def atr(bars, period=14):
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0
    return sum(trs[-period:]) / min(len(trs), period)

def swing_highs_lows(bars, lookback=5):
    """Identify swing H and L using local extremes"""
    highs, lows = [], []
    n = len(bars)
    for i in range(lookback, n - lookback):
        local_high = all(bars[i]["h"] >= bars[j]["h"] for j in range(i - lookback, i + lookback + 1) if j != i)
        local_low  = all(bars[i]["l"] <= bars[j]["l"] for j in range(i - lookback, i + lookback + 1) if j != i)
        if local_high:
            highs.append((i, bars[i]["h"]))
        if local_low:
            lows.append((i, bars[i]["l"]))
    return highs, lows

def market_structure(bars_4h):
    """Determine bias using swing structure on 4H"""
    if len(bars_4h) < 20:
        return "neutral", 0

    highs, lows = swing_highs_lows(bars_4h[-60:], lookback=3)
    if len(highs) < 2 or len(lows) < 2:
        return "neutral", 0

    last_hh = highs[-1][1] > highs[-2][1]  # Higher High
    last_hl = lows[-1][1] > lows[-2][1]    # Higher Low
    last_lh = highs[-1][1] < highs[-2][1]  # Lower High
    last_ll = lows[-1][1] < lows[-2][1]    # Lower Low

    score = 0
    if last_hh:
        score += 1
    if last_hl:
        score += 1
    if last_lh:
        score -= 1
    if last_ll:
        score -= 1

    if score >= 2:
        return "bullish", score
    elif score <= -2:
        return "bearish", -score
    elif score == 1:
        return "bullish", 1
    elif score == -1:
        return "bearish", 1
    return "neutral", 0

def find_ob(bars, direction, lookback=40):
    """Find most recent valid Order Block"""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    n = len(recent)
    for i in range(n - 4, 1, -1):
        if direction == "bullish":
            # Bearish OB candle before bullish run
            is_bearish = recent[i]["c"] < recent[i]["o"]
            bull_run = sum(1 for j in range(1, 4) if i+j < n and recent[i+j]["c"] > recent[i+j]["o"])
            if is_bearish and bull_run >= 2:
                # Calculate OB size quality
                body = abs(recent[i]["o"] - recent[i]["c"])
                total = recent[i]["h"] - recent[i]["l"]
                quality = body / total if total else 0
                return {
                    "high": recent[i]["h"],
                    "low":  recent[i]["l"],
                    "mid":  (recent[i]["h"] + recent[i]["l"]) / 2,
                    "quality": round(quality, 2),
                    "age": n - 1 - i   # bars ago
                }
        else:
            is_bullish = recent[i]["c"] > recent[i]["o"]
            bear_run = sum(1 for j in range(1, 4) if i+j < n and recent[i+j]["c"] < recent[i+j]["o"])
            if is_bullish and bear_run >= 2:
                body = abs(recent[i]["o"] - recent[i]["c"])
                total = recent[i]["h"] - recent[i]["l"]
                quality = body / total if total else 0
                return {
                    "high": recent[i]["h"],
                    "low":  recent[i]["l"],
                    "mid":  (recent[i]["h"] + recent[i]["l"]) / 2,
                    "quality": round(quality, 2),
                    "age": n - 1 - i
                }
    return None

def find_fvg(bars, direction, lookback=30):
    """Find Fair Value Gap"""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    fvgs = []
    for i in range(2, len(recent)):
        if direction == "bullish" and recent[i]["l"] > recent[i-2]["h"]:
            size = recent[i]["l"] - recent[i-2]["h"]
            fvgs.append({"high": recent[i]["l"], "low": recent[i-2]["h"], "size": size})
        elif direction == "bearish" and recent[i]["h"] < recent[i-2]["l"]:
            size = recent[i-2]["l"] - recent[i]["h"]
            fvgs.append({"high": recent[i-2]["l"], "low": recent[i]["h"], "size": size})
    return fvgs[-1] if fvgs else None

def liq_sweep_detected(bars, direction, lookback=25):
    """Return True + details if liquidity was swept recently"""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(5, len(recent)):
        window = recent[max(0, i-8):i]
        if direction == "bullish":
            swing_low = min(b["l"] for b in window)
            wick_down = recent[i]["l"] < swing_low
            closed_above = recent[i]["c"] > swing_low
            if wick_down and closed_above:
                swept = round((swing_low - recent[i]["l"]) * (100 if "JPY" in str(direction) else 10000), 1)
                return True, f"Swept {swing_low:.5f}"
        else:
            swing_high = max(b["h"] for b in window)
            wick_up = recent[i]["h"] > swing_high
            closed_below = recent[i]["c"] < swing_high
            if wick_up and closed_below:
                return True, f"Swept {swing_high:.5f}"
    return False, None

def bos_detected(bars, direction, lookback=30):
    """Break of Structure confirmation"""
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if len(recent) < 8:
        return False
    mid = len(recent) // 2
    early, late = recent[:mid], recent[mid:]
    if direction == "bullish":
        swing = max(b["h"] for b in early)
        return any(b["c"] > swing for b in late), round(swing, 5)
    else:
        swing = min(b["l"] for b in early)
        return any(b["c"] < swing for b in late), round(swing, 5)

def premium_discount(bars, direction):
    """Is price in premium (sell) or discount (buy) zone?"""
    if len(bars) < 20:
        return "neutral"
    recent = bars[-50:]
    high = max(b["h"] for b in recent)
    low = min(b["l"] for b in recent)
    mid = (high + low) / 2
    price = bars[-1]["c"]
    if direction == "bullish":
        return "discount" if price < mid else "premium"
    else:
        return "premium" if price > mid else "discount"

def calc_lots(balance, sl_pips, pip_val_lot, risk_pct=RISK_PCT):
    """Risk-based lot sizing"""
    dollar_risk = balance * risk_pct
    lots = dollar_risk / (sl_pips * pip_val_lot)
    return round(min(lots, 3.0), 2)

# ─── SCORE SETUP ──────────────────────────────────────────────────────────────

def analyze_pair(pair_name, bars_1h, bars_4h, current_price):
    """Full SMC analysis. Returns score 0-10 and setup details."""
    if len(bars_1h) < 50 or len(bars_4h) < 20:
        return None

    pip_size = 0.01 if PAIRS[pair_name]["is_jpy"] else 0.0001
    pip_val_lot = PAIRS[pair_name]["pip_val_lot"]
    curr_atr = atr(bars_1h[-20:])
    curr_atr_pips = round(curr_atr / pip_size, 1)

    # 4H Market Structure (most important)
    direction, ms_strength = market_structure(bars_4h)
    if direction == "neutral":
        return None

    criteria = {}
    score = 0

    # 1. 4H Market Structure (weight: 2)
    criteria["4H Trend"] = f"{'✅' if ms_strength >= 2 else '⚠️'} {direction.upper()} (strength {ms_strength}/2)"
    if ms_strength >= 2:
        score += 2
    elif ms_strength == 1:
        score += 1

    # 2. Order Block quality (weight: 2)
    ob = find_ob(bars_1h, direction)
    if ob:
        in_zone = ob["low"] <= current_price <= ob["high"]
        approaching = False
        if direction == "bullish" and ob["low"] - curr_atr * 0.5 <= current_price <= ob["high"] + curr_atr * 0.3:
            approaching = True
        elif direction == "bearish" and ob["low"] - curr_atr * 0.3 <= current_price <= ob["high"] + curr_atr * 0.5:
            approaching = True

        if in_zone:
            criteria["Order Block"] = f"✅ INSIDE OB [{ob['low']:.5f} – {ob['high']:.5f}] quality={ob['quality']:.0%} age={ob['age']}bars"
            score += 2
        elif approaching:
            criteria["Order Block"] = f"⚠️ APPROACHING OB [{ob['low']:.5f} – {ob['high']:.5f}] quality={ob['quality']:.0%}"
            score += 1
        else:
            criteria["Order Block"] = f"❌ OB exists but price not near [{ob['low']:.5f} – {ob['high']:.5f}]"
    else:
        criteria["Order Block"] = "❌ No valid Order Block found"

    # 3. Fair Value Gap (weight: 1)
    fvg = find_fvg(bars_1h, direction)
    if fvg:
        criteria["FVG"] = f"✅ FVG [{fvg['low']:.5f} – {fvg['high']:.5f}]"
        score += 1
    else:
        criteria["FVG"] = "❌ No FVG detected"

    # 4. Liquidity Sweep (weight: 2)
    swept, sweep_detail = liq_sweep_detected(bars_1h, direction)
    if swept:
        criteria["Liquidity"] = f"✅ Sweep confirmed — {sweep_detail}"
        score += 2
    else:
        criteria["Liquidity"] = "❌ No liquidity sweep yet"

    # 5. Break of Structure (weight: 1)
    bos_result = bos_detected(bars_1h, direction)
    bos_ok, bos_level = bos_result
    if bos_ok:
        criteria["BOS"] = f"✅ BOS confirmed at {bos_level}"
        score += 1
    else:
        criteria["BOS"] = f"❌ No BOS — level to break: {bos_level}"

    # 6. Premium/Discount zone alignment (weight: 1)
    zone = premium_discount(bars_1h, direction)
    if zone == "discount" and direction == "bullish":
        criteria["Zone"] = "✅ Price in DISCOUNT zone — ideal for buys"
        score += 1
    elif zone == "premium" and direction == "bearish":
        criteria["Zone"] = "✅ Price in PREMIUM zone — ideal for sells"
        score += 1
    else:
        criteria["Zone"] = f"⚠️ Price in {zone.upper()} zone ({direction})"

    # Trade levels
    if ob:
        if direction == "bullish":
            entry = ob["mid"]   # enter at OB midpoint
            sl = ob["low"] - curr_atr * 0.1
            risk = entry - sl
            risk_pips = risk / pip_size
        else:
            entry = ob["mid"]
            sl = ob["high"] + curr_atr * 0.1
            risk = sl - entry
            risk_pips = risk / pip_size
    else:
        entry = current_price
        risk_pips = curr_atr_pips * 0.8
        sl = (entry - risk_pips * pip_size) if direction == "bullish" else (entry + risk_pips * pip_size)
        risk = risk_pips * pip_size

    risk_pips = round(risk_pips, 1)

    if risk_pips > MAX_SL_PIPS:
        criteria["SL Check"] = f"⚠️ SL {risk_pips}p exceeds {MAX_SL_PIPS}p max — tighten entry"
        score -= 1
    else:
        criteria["SL Check"] = f"✅ SL {risk_pips}p — within {MAX_SL_PIPS}p limit"

    tp1 = (entry + risk) if direction == "bullish" else (entry - risk)
    tp2 = (entry + risk * 2) if direction == "bullish" else (entry - risk * 2)
    tp3 = (entry + risk * 3) if direction == "bullish" else (entry - risk * 3)

    lots = calc_lots(ACCOUNT_BALANCE, risk_pips, pip_val_lot)
    dollar_risk = round(risk_pips * pip_val_lot * lots, 2)
    dollar_tp2 = round(risk_pips * 2 * pip_val_lot * lots, 2)

    return {
        "pair": pair_name,
        "direction": direction,
        "score": score,
        "max_score": 9,
        "criteria": criteria,
        "current_price": current_price,
        "entry": round(entry, 5),
        "sl": round(sl, 5),
        "tp1": round(tp1, 5),
        "tp2": round(tp2, 5),
        "tp3": round(tp3, 5),
        "risk_pips": risk_pips,
        "atr_pips": curr_atr_pips,
        "lots": lots,
        "dollar_risk": dollar_risk,
        "dollar_tp2": dollar_tp2,
        "rr": "2:1",
    }

# ─── PLACE TRADE ──────────────────────────────────────────────────────────────

def place_trade(headers, account_id, acc_num, setup):
    """Place the trade on TradeLocker with SL and TP."""
    pair = setup["pair"]
    direction = setup["direction"]

    # Find tradable instrument
    instr_resp = requests.get(f"{BASE}/trade/accounts/{account_id}/instruments", headers=headers)
    instruments = instr_resp.json().get("d", {}).get("instruments", [])
    instr = next((i for i in instruments if i["name"] == pair), None)
    if not instr:
        return None, f"Instrument {pair} not found"

    instr_id = instr["tradableInstrumentId"]
    trade_route = next((r["id"] for r in instr.get("routes", []) if r.get("type") == "TRADE"), None)

    order_body = {
        "tradableInstrumentId": instr_id,
        "routeId": trade_route,
        "type": "market",
        "side": "buy" if direction == "bullish" else "sell",
        "qty": setup["lots"],
        "validity": "IOC",
        "stopLoss": setup["sl"],
        "takeProfit": setup["tp2"],
        "stopLossType": "absolute",
        "takeProfitType": "absolute",
    }

    resp = requests.post(
        f"{BASE}/trade/accounts/{account_id}/orders",
        headers=headers,
        json=order_body
    )
    data = resp.json()
    if data.get("s") == "ok":
        return data.get("d", {}).get("orderId"), None
    return None, str(data)

# ─── MAIN SCANNER ─────────────────────────────────────────────────────────────

def run_scanner(auto_trade=False):
    now = datetime.datetime.utcnow()
    print("=" * 62)
    print(f"  LONDON OPEN SCANNER — {now.strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 62)
    print(f"  Account: ${ACCOUNT_BALANCE:,}  |  Risk/trade: {RISK_PCT*100:.0f}%  |  Max SL: {MAX_SL_PIPS}p")
    print(f"  Prop targets: +${PROFIT_TARGET} | Daily limit: -${DAILY_LOSS_LIMIT} | Max DD: -${MAX_DRAWDOWN_LIMIT}")
    print()

    print("Authenticating...")
    headers, account_id = auth()
    acc_num = headers["accNum"]

    results = []

    for pair_name, cfg in PAIRS.items():
        print(f"  Scanning {pair_name}...", end=" ", flush=True)
        bars_1h = fetch_bars(headers, cfg["id"], cfg["routeId"], "1H", 30)
        bars_4h = fetch_bars(headers, cfg["id"], cfg["routeId"], "4H", 30)

        if not bars_1h or not bars_4h:
            print("no data")
            continue

        current_price = bars_1h[-1]["c"]
        result = analyze_pair(pair_name, bars_1h, bars_4h, current_price)
        if result:
            results.append(result)
            print(f"score {result['score']}/{result['max_score']}")
        else:
            print("neutral — skip")

    if not results:
        print("\nNo setups found — market is ranging or no clear structure.")
        return

    # Sort by score
    results.sort(key=lambda r: r["score"], reverse=True)

    print("\n" + "=" * 62)
    print("  SETUP RANKING")
    print("=" * 62)

    for rank, r in enumerate(results, 1):
        emoji = PAIRS[r["pair"]]["emoji"]
        bar_len = int(r["score"] / r["max_score"] * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        quality = "🔥 HIGH CONVICTION" if r["score"] >= 7 else ("✅ VALID" if r["score"] >= 5 else "⚠️ WEAK")

        print(f"\n  #{rank} {emoji} {r['pair']} — {r['direction'].upper()} — {quality}")
        print(f"  Score: {r['score']}/{r['max_score']} [{bar}]")
        print()

        for criterion, detail in r["criteria"].items():
            print(f"    {criterion:<18} {detail}")

        print()
        arrow = "▲" if r["direction"] == "bullish" else "▼"
        print(f"  ┌─ TRADE PLAN ──────────────────────────────────────────┐")
        print(f"  │  Direction:  {r['direction'].upper()} {arrow}                                    │")
        print(f"  │  Entry:      {r['entry']:<12} (OB midpoint)               │")
        print(f"  │  Stop Loss:  {r['sl']:<12} ({r['risk_pips']}p from entry)         │")
        print(f"  │  TP1 (1:1):  {r['tp1']:<12}                               │")
        print(f"  │  TP2 (2:1):  {r['tp2']:<12} ← main target                │")
        print(f"  │  TP3 (3:1):  {r['tp3']:<12}                               │")
        print(f"  │  Lot size:   {r['lots']} lots ({RISK_PCT*100:.0f}% = ${r['dollar_risk']} risk)        │")
        print(f"  │  TP2 profit: +${r['dollar_tp2']}                              │")
        print(f"  │  RR:         {r['rr']}                                    │")
        print(f"  └───────────────────────────────────────────────────────┘")

    # Top pick
    top = results[0]
    print(f"\n{'='*62}")
    print(f"  RECOMMENDED TRADE TODAY")
    print(f"{'='*62}")
    if top["score"] >= 5:
        print(f"\n  {PAIRS[top['pair']]['emoji']} {top['pair']} {top['direction'].upper()}")
        print(f"  → {top['lots']} lots | SL: {top['sl']} | TP2: {top['tp2']}")
        print(f"  → Risk ${top['dollar_risk']} | Potential +${top['dollar_tp2']}")
        print()

        print("  MANUAL CONFIRM BEFORE TRADING:")
        print("  [ ] Open chart — confirm OB visually")
        print("  [ ] Check economic calendar (no red news next 2 hours)")
        print("  [ ] Confirm price is moving INTO OB (not away)")
        print("  [ ] See a rejection wick or engulfing candle on 15m/5m")
        print("  [ ] Session: best entries 08:00–10:30 UTC")
        print()

        if auto_trade:
            confirm = input(f"  Place {top['pair']} {top['direction'].upper()} {top['lots']} lots now? (yes/no): ").strip().lower()
            if confirm == "yes":
                order_id, err = place_trade(headers, account_id, acc_num, top)
                if order_id:
                    print(f"\n  ✅ ORDER PLACED — ID: {order_id}")
                    print(f"  SL: {top['sl']}  |  TP: {top['tp2']}")
                else:
                    print(f"\n  ❌ Order failed: {err}")
            else:
                print("  Trade skipped.")
        else:
            print("  Run with auto_trade=True to place via API")
    else:
        print(f"\n  No high-conviction setup today (top score {top['score']}/{top['max_score']}).")
        print("  Wait for tomorrow's London open — don't force trades.")
        print()
        print("  Prop firm rule: 0 trades is better than a bad trade.")

    print()
    print("=" * 62)
    print("  PROP FIRM PROGRESS TRACKER")
    print("=" * 62)
    print(f"  Balance:      ${ACCOUNT_BALANCE:,}")
    print(f"  Target:       ${ACCOUNT_BALANCE + PROFIT_TARGET:,}  (+${PROFIT_TARGET})")
    print(f"  Remaining:    Update ACCOUNT_BALANCE variable daily")
    print(f"  Daily limit:  Never lose more than ${DAILY_LOSS_LIMIT} in one day")
    print(f"  Max DD:       Never drop below ${ACCOUNT_BALANCE - MAX_DRAWDOWN_LIMIT:,}")
    print()

if __name__ == "__main__":
    import sys
    # auto_trade=True only when running interactively in a terminal
    interactive = sys.stdin.isatty()
    run_scanner(auto_trade=interactive)
