"""
Full Market Watch Scanner — TradeLocker
Scans EVERY instrument in the watch list (crypto, FX, indices, commodities,
metals) and ranks high-probability SMC setups.

Instrument-agnostic: scores use price structure + ATR/percentage terms so the
same logic works for BTCUSD, EURUSD, US30, XAUUSD, etc. No fixed pip sizing.

Usage:  python3 market_watch_scan.py
"""

import requests
import time
import datetime
import os

BASE = "https://demo.tradelocker.com/backend-api"
EMAIL = os.environ.get("TRADELOCKER_EMAIL", "carlinpool94@gmail.com")
PASSWORD = os.environ.get("TRADELOCKER_PASSWORD", "Tinapool321!?")
SERVER = os.environ.get("TRADELOCKER_SERVER", "GenFX")

MIN_SCORE_REPORT = 5      # only surface setups scoring >= this
MAX_SCORE = 10
REQUEST_PAUSE = 0.35      # gentle pacing between history calls

# ─── AUTH ─────────────────────────────────────────────────────────────────────

def auth():
    r = requests.post(f"{BASE}/auth/jwt/token",
                      json={"email": EMAIL, "password": PASSWORD, "server": SERVER}, timeout=20)
    tokens = r.json()
    headers = {"Authorization": f"Bearer {tokens['accessToken']}"}
    accounts = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=headers, timeout=20).json()
    account = accounts["accounts"][0]
    return {**headers, "accNum": str(account["accNum"])}, account


def get_instruments(headers, account_id):
    r = requests.get(f"{BASE}/trade/accounts/{account_id}/instruments", headers=headers, timeout=30)
    return r.json().get("d", {}).get("instruments", [])


def fetch_bars(headers, instr_id, route_id, resolution, days=40, retries=5):
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    backoff = 1.0
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/trade/history", headers=headers, params={
                "tradableInstrumentId": instr_id,
                "routeId": route_id,
                "resolution": resolution,
                "from": from_ms,
                "to": now_ms,
            }, timeout=30)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", backoff))
                time.sleep(wait); backoff *= 2; continue
            bars = r.json().get("d", {}).get("barDetails", [])
            if bars:
                return bars
            # empty but 200 -> brief retry in case of transient throttle
            time.sleep(backoff); backoff *= 2
        except Exception:
            time.sleep(backoff); backoff *= 2
    return []

# ─── INDICATORS / SMC ─────────────────────────────────────────────────────────

def atr(bars, period=14):
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0
    return sum(trs[-period:]) / min(len(trs), period)


def swing_highs_lows(bars, lookback=3):
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


def market_structure(bars_htf):
    if len(bars_htf) < 20:
        return "neutral", 0
    highs, lows = swing_highs_lows(bars_htf[-60:], lookback=3)
    if len(highs) < 2 or len(lows) < 2:
        return "neutral", 0
    last_hh = highs[-1][1] > highs[-2][1]
    last_hl = lows[-1][1] > lows[-2][1]
    last_lh = highs[-1][1] < highs[-2][1]
    last_ll = lows[-1][1] < lows[-2][1]
    score = 0
    if last_hh: score += 1
    if last_hl: score += 1
    if last_lh: score -= 1
    if last_ll: score -= 1
    if score >= 2:   return "bullish", score
    if score <= -2:  return "bearish", -score
    if score == 1:   return "bullish", 1
    if score == -1:  return "bearish", 1
    return "neutral", 0


def find_ob(bars, direction, lookback=40):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    n = len(recent)
    for i in range(n - 4, 1, -1):
        if direction == "bullish":
            is_bearish = recent[i]["c"] < recent[i]["o"]
            bull_run = sum(1 for j in range(1, 4) if i+j < n and recent[i+j]["c"] > recent[i+j]["o"])
            if is_bearish and bull_run >= 2:
                body = abs(recent[i]["o"] - recent[i]["c"]); total = recent[i]["h"] - recent[i]["l"]
                return {"high": recent[i]["h"], "low": recent[i]["l"], "mid": (recent[i]["h"]+recent[i]["l"])/2,
                        "quality": round(body/total if total else 0, 2), "age": n-1-i}
        else:
            is_bullish = recent[i]["c"] > recent[i]["o"]
            bear_run = sum(1 for j in range(1, 4) if i+j < n and recent[i+j]["c"] < recent[i+j]["o"])
            if is_bullish and bear_run >= 2:
                body = abs(recent[i]["o"] - recent[i]["c"]); total = recent[i]["h"] - recent[i]["l"]
                return {"high": recent[i]["h"], "low": recent[i]["l"], "mid": (recent[i]["h"]+recent[i]["l"])/2,
                        "quality": round(body/total if total else 0, 2), "age": n-1-i}
    return None


def find_fvg(bars, direction, lookback=30):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    fvgs = []
    for i in range(2, len(recent)):
        if direction == "bullish" and recent[i]["l"] > recent[i-2]["h"]:
            fvgs.append({"high": recent[i]["l"], "low": recent[i-2]["h"]})
        elif direction == "bearish" and recent[i]["h"] < recent[i-2]["l"]:
            fvgs.append({"high": recent[i-2]["l"], "low": recent[i]["h"]})
    return fvgs[-1] if fvgs else None


def liq_sweep_detected(bars, direction, lookback=25):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(5, len(recent)):
        window = recent[max(0, i-8):i]
        if not window: continue
        if direction == "bullish":
            swing_low = min(b["l"] for b in window)
            if recent[i]["l"] < swing_low and recent[i]["c"] > swing_low:
                return True, f"swept low {swing_low:.5g}"
        else:
            swing_high = max(b["h"] for b in window)
            if recent[i]["h"] > swing_high and recent[i]["c"] < swing_high:
                return True, f"swept high {swing_high:.5g}"
    return False, None


def bos_detected(bars, direction, lookback=30):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if len(recent) < 8:
        return False, 0
    mid = len(recent) // 2
    early, late = recent[:mid], recent[mid:]
    if direction == "bullish":
        swing = max(b["h"] for b in early)
        return any(b["c"] > swing for b in late), swing
    else:
        swing = min(b["l"] for b in early)
        return any(b["c"] < swing for b in late), swing


def premium_discount(bars, direction):
    if len(bars) < 20:
        return "neutral"
    recent = bars[-50:]
    high = max(b["h"] for b in recent); low = min(b["l"] for b in recent)
    mid = (high + low) / 2; price = bars[-1]["c"]
    if direction == "bullish":
        return "discount" if price < mid else "premium"
    return "premium" if price > mid else "discount"

# ─── ANALYSIS ─────────────────────────────────────────────────────────────────

def analyze(name, bars_1h, bars_4h, price):
    if len(bars_1h) < 50 or len(bars_4h) < 20:
        return None
    curr_atr = atr(bars_1h[-20:])
    if curr_atr <= 0:
        return None

    direction, ms_strength = market_structure(bars_4h)
    if direction == "neutral":
        return None

    crit = {}
    score = 0

    # 1. 4H structure (w2)
    crit["4H Trend"] = f"{'OK ' if ms_strength>=2 else '~  '}{direction.upper()} (str {ms_strength}/2)"
    score += 2 if ms_strength >= 2 else 1

    # 2. Order block (w2)
    ob = find_ob(bars_1h, direction)
    if ob:
        in_zone = ob["low"] <= price <= ob["high"]
        approaching = (direction=="bullish" and ob["low"]-curr_atr*0.5 <= price <= ob["high"]+curr_atr*0.3) or \
                      (direction=="bearish" and ob["low"]-curr_atr*0.3 <= price <= ob["high"]+curr_atr*0.5)
        if in_zone:
            crit["Order Block"] = f"OK  INSIDE OB [{ob['low']:.5g}-{ob['high']:.5g}] q={ob['quality']:.0%} age={ob['age']}"
            score += 2
        elif approaching:
            crit["Order Block"] = f"~   APPROACHING OB [{ob['low']:.5g}-{ob['high']:.5g}] q={ob['quality']:.0%}"
            score += 1
        else:
            crit["Order Block"] = f"x   OB exists, price away [{ob['low']:.5g}-{ob['high']:.5g}]"
    else:
        crit["Order Block"] = "x   no OB"

    # 3. FVG (w1)
    fvg = find_fvg(bars_1h, direction)
    if fvg:
        crit["FVG"] = f"OK  FVG [{fvg['low']:.5g}-{fvg['high']:.5g}]"; score += 1
    else:
        crit["FVG"] = "x   no FVG"

    # 4. Liquidity sweep (w2)
    swept, detail = liq_sweep_detected(bars_1h, direction)
    if swept:
        crit["Liquidity"] = f"OK  {detail}"; score += 2
    else:
        crit["Liquidity"] = "x   no sweep"

    # 5. BOS (w1)
    bos_ok, bos_level = bos_detected(bars_1h, direction)
    if bos_ok:
        crit["BOS"] = f"OK  BOS @ {bos_level:.5g}"; score += 1
    else:
        crit["BOS"] = f"x   no BOS (need {bos_level:.5g})"

    # 6. Premium/discount (w1)
    zone = premium_discount(bars_1h, direction)
    if (zone=="discount" and direction=="bullish") or (zone=="premium" and direction=="bearish"):
        crit["Zone"] = f"OK  {zone} zone ideal"; score += 1
    else:
        crit["Zone"] = f"~   {zone} zone"

    # Trade levels
    if ob:
        entry = ob["mid"]
        if direction == "bullish":
            sl = ob["low"] - curr_atr * 0.1; risk = entry - sl
        else:
            sl = ob["high"] + curr_atr * 0.1; risk = sl - entry
    else:
        entry = price; risk = curr_atr * 0.8
        sl = entry - risk if direction == "bullish" else entry + risk

    if risk <= 0:
        return None
    risk_pct = risk / price * 100
    tp1 = entry + risk     if direction=="bullish" else entry - risk
    tp2 = entry + risk*2   if direction=="bullish" else entry - risk*2
    tp3 = entry + risk*3   if direction=="bullish" else entry - risk*3
    dist_to_entry_pct = abs(price - entry) / price * 100

    return {
        "name": name, "direction": direction, "score": score, "criteria": crit,
        "price": price, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "risk_pct": round(risk_pct, 2), "atr": curr_atr,
        "dist_pct": round(dist_to_entry_pct, 2),
    }


def fmt(v):
    return f"{v:.5g}"

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    now = datetime.datetime.utcnow()
    print("=" * 70)
    print(f"  FULL MARKET WATCH SCAN — {now.strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 70)
    headers, account = auth()
    try:
        _bal = float(account.get('accountBalance') or 0)
    except (TypeError, ValueError):
        _bal = 0.0
    print(f"  Account #{account['accNum']}  balance ${_bal:,.2f} {account.get('currency')}")
    instruments = get_instruments(headers, account["id"])
    print(f"  Instruments in watch list: {len(instruments)}")
    print("  Scanning (1H + 4H each)...\n")

    results = []
    skipped = []
    for idx, instr in enumerate(instruments, 1):
        name = instr["name"]
        info_route = next((r["id"] for r in instr.get("routes", []) if r.get("type") == "INFO"), None)
        if info_route is None:
            skipped.append((name, "no INFO route"))
            print(f"  [{idx:>2}/{len(instruments)}] {name:<12} skip (no route)"); continue
        iid = instr["tradableInstrumentId"]
        bars_4h = fetch_bars(headers, iid, info_route, "4H", 60); time.sleep(REQUEST_PAUSE)
        bars_1h = fetch_bars(headers, iid, info_route, "1H", 30); time.sleep(REQUEST_PAUSE)
        if not bars_1h or not bars_4h:
            skipped.append((name, "no data"))
            print(f"  [{idx:>2}/{len(instruments)}] {name:<12} skip (no data)"); continue
        res = analyze(name, bars_1h, bars_4h, bars_1h[-1]["c"])
        if res:
            res["type"] = instr.get("type", "")
            results.append(res)
        print(f"  [{idx:>2}/{len(instruments)}] {name:<12} "
              f"{(res['direction'].upper()+' '+str(res['score'])+'/10') if res else 'neutral'}")

    results.sort(key=lambda r: (r["score"], -r["dist_pct"]), reverse=True)
    high = [r for r in results if r["score"] >= MIN_SCORE_REPORT]

    print("\n" + "=" * 70)
    print(f"  HIGH-PROBABILITY SETUPS  (score >= {MIN_SCORE_REPORT}/10)")
    print("=" * 70)
    if not high:
        print("  None today. Top candidates below threshold:")
        high = results[:5]

    for rank, r in enumerate(high, 1):
        conv = "HIGH CONVICTION" if r["score"] >= 7 else ("VALID" if r["score"] >= 5 else "WATCH")
        bar = "#" * int(r["score"]/MAX_SCORE*20) + "." * (20-int(r["score"]/MAX_SCORE*20))
        arrow = "LONG" if r["direction"]=="bullish" else "SHORT"
        print(f"\n  #{rank}  {r['name']} ({r['type']}) — {arrow} — {conv}")
        print(f"      Score {r['score']}/10 [{bar}]")
        for k, v in r["criteria"].items():
            print(f"        {k:<13} {v}")
        print(f"      ---- TRADE PLAN ----")
        print(f"        Current:  {fmt(r['price'])}  (entry {r['dist_pct']}% away)")
        print(f"        Entry:    {fmt(r['entry'])}  (OB mid)")
        print(f"        Stop:     {fmt(r['sl'])}  (risk {r['risk_pct']}%)")
        print(f"        TP1 1R:   {fmt(r['tp1'])}")
        print(f"        TP2 2R:   {fmt(r['tp2'])}  <- main target")
        print(f"        TP3 3R:   {fmt(r['tp3'])}")

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  Analyzed: {len(results)} | High-prob (>={MIN_SCORE_REPORT}): "
          f"{len([r for r in results if r['score']>=MIN_SCORE_REPORT])} | Skipped: {len(skipped)}")
    longs = [r['name'] for r in results if r['direction']=='bullish' and r['score']>=MIN_SCORE_REPORT]
    shorts = [r['name'] for r in results if r['direction']=='bearish' and r['score']>=MIN_SCORE_REPORT]
    print(f"  Longs:  {', '.join(longs) or '-'}")
    print(f"  Shorts: {', '.join(shorts) or '-'}")
    print("\n  Reminder: confirm on lower TF (rejection wick/engulfing into OB),")
    print("  check news, and respect risk limits before executing. Demo by default.")


if __name__ == "__main__":
    run()
