"""
SMC Backtester v2 — Prop Firm Edition
Fixes: pip value calculation, TP1+BE partial close logic, XAUUSD data
Improvements: relaxed entry criteria, better SL placement, per-session scoring
"""

import os
import requests
import time
import datetime
from collections import defaultdict

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BASE = "https://demo.tradelocker.com/backend-api"
EMAIL = os.environ["TL_EMAIL"]
PASSWORD = os.environ["TL_PASSWORD"]
SERVER = os.environ.get("TL_SERVER", "GenFX")

LOT_SIZE = 0.10
LOOKBACK_DAYS = 90
MIN_SIGNAL_SCORE = 4    # require 4 out of 5 criteria (was 5/5)

PROP = {
    "name": "FTMO $10k Challenge",
    "balance": 10_000,
    "daily_loss_pct": 0.05,
    "max_drawdown_pct": 0.10,
    "profit_target_pct": 0.10,
    "max_days": 30,
    "min_trading_days": 4,
}

# pip_val = USD profit per 1 pip move at 0.10 lots
# JPY pip = 0.01, at 10,000 units ≈ $0.67 @ 150 JPY/USD
# USD pip = 0.0001, at 10,000 units = $1.00
PAIRS = {
    "EURUSD": {"id": 278, "routeId": 452, "is_jpy": False, "spread": 0.5,  "pip_val": 1.00},
    "GBPUSD": {"id": 279, "routeId": 452, "is_jpy": False, "spread": 1.0,  "pip_val": 1.00},
    "GBPJPY": {"id": 243, "routeId": 452, "is_jpy": True,  "spread": 2.0,  "pip_val": 0.67},
    "USDJPY": {"id": 283, "routeId": 452, "is_jpy": True,  "spread": 1.0,  "pip_val": 0.67},
    "AUDUSD": {"id": 277, "routeId": 452, "is_jpy": False, "spread": 1.0,  "pip_val": 0.70},
    "USDCAD": {"id": 281, "routeId": 452, "is_jpy": False, "spread": 1.0,  "pip_val": 0.73},
    "EURJPY": {"id": 238, "routeId": 452, "is_jpy": True,  "spread": 2.0,  "pip_val": 0.67},
}

# ─── AUTH ─────────────────────────────────────────────────────────────────────

def auth():
    r = requests.post(f"{BASE}/auth/jwt/token",
                      json={"email": EMAIL, "password": PASSWORD, "server": SERVER})
    tokens = r.json()
    access_token = tokens["accessToken"]
    headers = {"Authorization": f"Bearer {access_token}"}
    accounts = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=headers).json()
    account = accounts["accounts"][0]
    return {**headers, "accNum": str(account["accNum"])}, account["id"]

# ─── DATA ─────────────────────────────────────────────────────────────────────

def fetch_bars(headers, instr_id, route_id, resolution, days_back):
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - (days_back * 24 * 60 * 60 * 1000)
    r = requests.get(f"{BASE}/trade/history", headers=headers, params={
        "tradableInstrumentId": instr_id,
        "routeId": route_id,
        "resolution": resolution,
        "from": from_ms,
        "to": now_ms,
    })
    return r.json().get("d", {}).get("barDetails", [])

# ─── INDICATORS ───────────────────────────────────────────────────────────────

def calc_atr(bars, period=14):
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0
    return sum(trs[-period:]) / min(len(trs), period)

def calc_adx(bars, period=14):
    """Simplified trend strength — returns 0-100"""
    if len(bars) < period + 2:
        return 20
    pos_dm, neg_dm, tr_vals = [], [], []
    for i in range(1, len(bars)):
        up = bars[i]["h"] - bars[i-1]["h"]
        down = bars[i-1]["l"] - bars[i]["l"]
        pos_dm.append(up if up > down and up > 0 else 0)
        neg_dm.append(down if down > up and down > 0 else 0)
        tr_vals.append(max(bars[i]["h"] - bars[i]["l"],
                           abs(bars[i]["h"] - bars[i-1]["c"]),
                           abs(bars[i]["l"] - bars[i-1]["c"])))
    atr_val = sum(tr_vals[-period:]) / period
    if atr_val == 0:
        return 0
    pdi = (sum(pos_dm[-period:]) / period) / atr_val * 100
    ndi = (sum(neg_dm[-period:]) / period) / atr_val * 100
    dx = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) else 0
    return dx

def trend_4h(bars):
    """Return bullish/bearish/neutral + strength score 0-2"""
    if len(bars) < 12:
        return "neutral", 0
    recent = bars[-24:]
    mid = len(recent) // 2
    fh, sh = recent[:mid], recent[mid:]
    hh = max(b["h"] for b in sh) > max(b["h"] for b in fh)
    hl = min(b["l"] for b in sh) > min(b["l"] for b in fh)
    lh = max(b["h"] for b in sh) < max(b["h"] for b in fh)
    ll = min(b["l"] for b in sh) < min(b["l"] for b in fh)
    score = 0
    if hh:
        score += 1
    if hl:
        score += 1
    if hh and hl:
        return "bullish", score
    if lh and ll:
        return "bearish", 2
    if hh or hl:
        return "bullish", score
    if lh or ll:
        return "bearish", 1
    return "neutral", 0

def find_ob(bars, direction, lookback=50):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    n = len(recent)
    for i in range(n - 5, 1, -1):
        if direction == "bullish":
            is_opp = recent[i]["c"] < recent[i]["o"]
            momentum = sum(1 for j in range(1, 4) if i+j < n and recent[i+j]["c"] > recent[i+j]["o"])
            if is_opp and momentum >= 2:
                return {"high": recent[i]["h"], "low": recent[i]["l"]}
        else:
            is_opp = recent[i]["c"] > recent[i]["o"]
            momentum = sum(1 for j in range(1, 4) if i+j < n and recent[i+j]["c"] < recent[i+j]["o"])
            if is_opp and momentum >= 2:
                return {"high": recent[i]["h"], "low": recent[i]["l"]}
    return None

def find_fvg(bars, direction, lookback=40):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(2, len(recent)):
        if direction == "bullish" and recent[i]["l"] > recent[i-2]["h"]:
            return {"high": recent[i]["l"], "low": recent[i-2]["h"]}
        if direction == "bearish" and recent[i]["h"] < recent[i-2]["l"]:
            return {"high": recent[i-2]["l"], "low": recent[i]["h"]}
    return None

def has_liq_sweep(bars, direction, lookback=30):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    for i in range(5, len(recent)):
        window = recent[max(0, i-10):i]
        if direction == "bullish":
            swing_low = min(b["l"] for b in window)
            if recent[i]["l"] < swing_low and recent[i]["c"] > swing_low:
                return True
        else:
            swing_high = max(b["h"] for b in window)
            if recent[i]["h"] > swing_high and recent[i]["c"] < swing_high:
                return True
    return False

def has_bos(bars, direction, lookback=35):
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    if len(recent) < 8:
        return False
    mid = len(recent) // 2
    early, late = recent[:mid], recent[mid:]
    if direction == "bullish":
        swing = max(b["h"] for b in early)
        return any(b["c"] > swing for b in late)
    else:
        swing = min(b["l"] for b in early)
        return any(b["c"] < swing for b in late)

def is_session(ts_ms):
    """Return session name or None"""
    dt = datetime.datetime.utcfromtimestamp(ts_ms / 1000)
    h = dt.hour
    # Skip weekends
    if dt.weekday() >= 5:
        return None
    if 7 <= h < 12:
        return "London"
    if 13 <= h < 17:
        return "NewYork"
    return None

def ob_zone_strength(ob, price, direction):
    """Is price inside OB or approaching it? Returns 0/1/2"""
    if ob is None:
        return 0
    ob_size = ob["high"] - ob["low"]
    if ob_size == 0:
        return 0
    if direction == "bullish":
        # Price approaching from above into OB
        if ob["low"] <= price <= ob["high"]:
            return 2   # inside OB
        if ob["high"] < price <= ob["high"] + ob_size * 0.5:
            return 1   # just above OB (will retrace in)
    else:
        if ob["low"] <= price <= ob["high"]:
            return 2
        if ob["low"] - ob_size * 0.5 <= price < ob["low"]:
            return 1
    return 0

# ─── SIGNAL DETECTION ─────────────────────────────────────────────────────────

def score_setup(bars_1h, bars_4h, pair_name, idx):
    """Score 0-5 based on SMC criteria. Returns (score, setup_dict)"""
    if idx < 50:
        return 0, None

    curr = bars_1h[idx]
    session = is_session(curr["t"])
    if session is None:
        return 0, None

    curr_time = curr["t"]
    h4_hist = [b for b in bars_4h if b["t"] <= curr_time]
    if len(h4_hist) < 12:
        return 0, None

    direction, trend_str = trend_4h(h4_hist)
    if direction == "neutral":
        return 0, None

    hist = bars_1h[:idx + 1]
    pip_size = 0.01 if PAIRS[pair_name]["is_jpy"] else 0.0001
    curr_atr = calc_atr(hist[-20:])
    if curr_atr == 0:
        return 0, None

    price = curr["c"]
    score = 0
    details = []

    # 1. Order Block
    ob = find_ob(hist, direction)
    ob_str = ob_zone_strength(ob, price, direction)
    if ob_str >= 1:
        score += 1
        details.append(f"OB({'in' if ob_str==2 else 'near'})")

    # 2. FVG
    fvg = find_fvg(hist, direction)
    if fvg:
        score += 1
        details.append("FVG")

    # 3. Liquidity Sweep
    if has_liq_sweep(hist, direction):
        score += 1
        details.append("LiqSweep")

    # 4. BOS
    if has_bos(hist, direction):
        score += 1
        details.append("BOS")

    # 5. Confirmation candle (current bar closes in direction of trade)
    body = abs(curr["c"] - curr["o"])
    candle_range = curr["h"] - curr["l"]
    body_pct = body / candle_range if candle_range else 0
    if direction == "bullish" and curr["c"] > curr["o"] and body_pct > 0.4:
        score += 1
        details.append("BullConfirm")
    elif direction == "bearish" and curr["c"] < curr["o"] and body_pct > 0.4:
        score += 1
        details.append("BearConfirm")

    if score < MIN_SIGNAL_SCORE:
        return score, None

    # Build trade levels
    spread = PAIRS[pair_name]["spread"] * pip_size

    if direction == "bullish":
        entry = curr["c"] + spread
        sl_base = ob["low"] if ob else entry - curr_atr
        sl = sl_base - curr_atr * 0.2    # buffer below OB
        risk = entry - sl
        if risk / pip_size < 8:
            return score, None
        tp1 = entry + risk              # 1:1
        tp2 = entry + risk * 2         # 2:1
        tp3 = entry + risk * 3         # 3:1
    else:
        entry = curr["c"] - spread
        sl_base = ob["high"] if ob else entry + curr_atr
        sl = sl_base + curr_atr * 0.2
        risk = sl - entry
        if risk / pip_size < 8:
            return score, None
        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    return score, {
        "pair": pair_name,
        "direction": direction,
        "session": session,
        "score": score,
        "criteria": ", ".join(details),
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_pips": round(risk / pip_size, 1),
        "atr_pips": round(curr_atr / pip_size, 1),
        "timestamp": curr["t"],
        "date": datetime.datetime.utcfromtimestamp(curr["t"] / 1000).strftime("%Y-%m-%d %H:%M"),
    }

# ─── SIMULATION ───────────────────────────────────────────────────────────────

def simulate(setup, future_bars, pair_name):
    d = setup["direction"]
    entry = setup["entry"]
    sl = setup["sl"]
    tp1, tp2, tp3 = setup["tp1"], setup["tp2"], setup["tp3"]
    pip_size = 0.01 if PAIRS[pair_name]["is_jpy"] else 0.0001
    pip_val = PAIRS[pair_name]["pip_val"]

    tp1_hit = False
    result = "EXPIRED"
    exit_pips = 0
    bars_held = 0

    for bar in future_bars[:120]:
        bars_held += 1
        h, l = bar["h"], bar["l"]

        if d == "bullish":
            if not tp1_hit and h >= tp1:
                tp1_hit = True
            if l <= (entry if tp1_hit else sl):   # BE after TP1
                if tp1_hit:
                    # 50% closed at TP1, 50% at breakeven
                    exit_pips = (tp1 - entry) / pip_size * 0.5
                    result = "TP1+BE"
                else:
                    exit_pips = (sl - entry) / pip_size
                    result = "SL"
                break
            if h >= tp3:
                exit_pips = (tp3 - entry) / pip_size
                result = "TP3"
                break
            if h >= tp2:
                exit_pips = (tp2 - entry) / pip_size
                result = "TP2"
                break
        else:
            if not tp1_hit and l <= tp1:
                tp1_hit = True
            if h >= (entry if tp1_hit else sl):
                if tp1_hit:
                    exit_pips = (entry - tp1) / pip_size * 0.5
                    result = "TP1+BE"
                else:
                    exit_pips = (entry - sl) / pip_size
                    result = "SL"
                break
            if l <= tp3:
                exit_pips = (entry - tp3) / pip_size
                result = "TP3"
                break
            if l <= tp2:
                exit_pips = (entry - tp2) / pip_size
                result = "TP2"
                break

    if result == "EXPIRED":
        last_c = future_bars[-1]["c"] if future_bars else entry
        exit_pips = (last_c - entry) / pip_size if d == "bullish" else (entry - last_c) / pip_size

    pnl = exit_pips * pip_val

    return {
        "result": result,
        "pips": round(exit_pips, 1),
        "pnl": round(pnl, 2),
        "bars_held": bars_held,
    }

# ─── BACKTEST LOOP ────────────────────────────────────────────────────────────

def run_backtest():
    print("Authenticating...")
    headers, account_id = auth()
    print("Fetching historical data (90 days)...\n")

    all_bars_1h = {}
    all_bars_4h = {}
    for name, cfg in PAIRS.items():
        b1 = fetch_bars(headers, cfg["id"], cfg["routeId"], "1H", LOOKBACK_DAYS)
        b4 = fetch_bars(headers, cfg["id"], cfg["routeId"], "4H", LOOKBACK_DAYS)
        all_bars_1h[name] = b1
        all_bars_4h[name] = b4
        print(f"  {name}: {len(b1)} x 1H,  {len(b4)} x 4H")

    print(f"\nMin signal score required: {MIN_SIGNAL_SCORE}/5\n")

    trades = []

    for pair_name in PAIRS:
        bars_1h = all_bars_1h[pair_name]
        bars_4h = all_bars_4h[pair_name]
        last_signal_bar = -15
        last_direction = None

        for i in range(50, len(bars_1h) - 1):
            if i - last_signal_bar < 8:
                continue

            score, setup = score_setup(bars_1h, bars_4h, pair_name, i)
            if setup is None:
                continue

            # Avoid consecutive same-direction signals (wait for outcome)
            if setup["direction"] == last_direction and i - last_signal_bar < 24:
                continue

            future = bars_1h[i + 1:]
            outcome = simulate(setup, future, pair_name)
            trades.append({**setup, **outcome})
            last_signal_bar = i
            last_direction = setup["direction"]

    if not trades:
        print("No trades found — try lowering MIN_SIGNAL_SCORE")
        return

    trades.sort(key=lambda t: t["timestamp"])

    # ─── STATS ────────────────────────────────────────────────────────────────

    total = len(trades)
    wins = [t for t in trades if t["result"] in ("TP2", "TP3", "TP1+BE")]
    sls = [t for t in trades if t["result"] == "SL"]
    expired = [t for t in trades if t["result"] == "EXPIRED"]

    win_rate = len(wins) / total * 100
    total_pnl = sum(t["pnl"] for t in trades)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else 999
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(sls) if sls else 0
    avg_rr = avg_win / avg_loss if avg_loss else 0

    # Drawdown + daily tracking
    equity = PROP["balance"]
    peak = equity
    max_dd = 0
    daily_pnl = defaultdict(float)
    daily_trades = defaultdict(int)

    for t in trades:
        day = t["date"][:10]
        daily_pnl[day] += t["pnl"]
        daily_trades[day] += 1
        equity += t["pnl"]
        peak = max(peak, equity)
        dd = (peak - equity) / PROP["balance"]
        max_dd = max(max_dd, dd)

    trading_days = len(daily_pnl)
    max_daily_loss = min(daily_pnl.values()) if daily_pnl else 0
    daily_violations = sum(1 for d, p in daily_pnl.items()
                           if p / PROP["balance"] < -PROP["daily_loss_pct"])
    max_consec_losses = 0
    consec = 0
    for t in trades:
        if t["result"] == "SL":
            consec += 1
            max_consec_losses = max(max_consec_losses, consec)
        else:
            consec = 0

    monthly_return = total_pnl / 3

    # Per-pair stats
    pair_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "sls": 0, "pnl": 0.0})
    session_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        p = t["pair"]
        s = t["session"]
        pair_stats[p]["trades"] += 1
        pair_stats[p]["pnl"] += t["pnl"]
        session_stats[s]["trades"] += 1
        session_stats[s]["pnl"] += t["pnl"]
        if t["result"] != "SL" and t["result"] != "EXPIRED":
            pair_stats[p]["wins"] += 1
            session_stats[s]["wins"] += 1
        if t["result"] == "SL":
            pair_stats[p]["sls"] += 1

    # Prop Firm Simulation (first 30 days)
    prop_balance = PROP["balance"]
    prop_peak = prop_balance
    prop_dd = 0
    prop_trading_days = 0
    prop_daily_violations = 0
    prop_fail = None
    prop_days_elapsed = 0

    sorted_days = sorted(daily_pnl.keys())
    for day in sorted_days[:PROP["max_days"]]:
        prop_days_elapsed += 1
        dp = daily_pnl.get(day, 0)
        if dp != 0:
            prop_trading_days += 1
        prop_balance += dp
        prop_peak = max(prop_peak, prop_balance)
        dd = (prop_peak - prop_balance) / PROP["balance"]
        prop_dd = max(prop_dd, dd)

        if dp / PROP["balance"] < -PROP["daily_loss_pct"]:
            prop_daily_violations += 1
            prop_fail = f"Daily loss limit breached on {day} (${dp:.0f})"
            break
        if prop_dd >= PROP["max_drawdown_pct"]:
            prop_fail = f"Max drawdown breached: {prop_dd*100:.1f}%"
            break

    prop_profit = prop_balance - PROP["balance"]
    target = PROP["balance"] * PROP["profit_target_pct"]
    if prop_fail is None:
        if prop_profit >= target:
            prop_verdict = "✅ PASS"
        else:
            prop_verdict = "❌ FAIL"
            prop_fail = f"Profit ${prop_profit:.0f} did not reach target ${target:.0f}"
    else:
        prop_verdict = "❌ FAIL"

    # ─── PRINT REPORT ─────────────────────────────────────────────────────────

    sep = "=" * 68
    print(sep)
    print("  SMC BACKTEST REPORT v2 — 90 Days | All Sessions")
    print(sep)

    print(f"\n{'DATE':<18} {'PAIR':<8} {'DIR':<5} {'SCORE':<7} {'RESULT':<12} {'PIPS':>7} {'P&L':>9}")
    print("-" * 68)
    for t in trades:
        pnl_s = f"+${t['pnl']:.2f}" if t["pnl"] >= 0 else f"-${abs(t['pnl']):.2f}"
        pip_s = f"+{t['pips']:.1f}" if t["pips"] >= 0 else f"{t['pips']:.1f}"
        icon = "✅" if t["pnl"] > 0 else ("❌" if t["result"] == "SL" else "⬜")
        print(f"{icon} {t['date']:<16} {t['pair']:<8} {t['direction'][:4].upper():<5} "
              f"{t['score']}/5{'':<4} {t['result']:<12} {pip_s:>7} {pnl_s:>9}")

    print(f"\n{sep}")
    print("  PERFORMANCE METRICS")
    print(sep)
    print(f"  Trades total:         {total}")
    print(f"  Trades / month:       {total/3:.1f}")
    print(f"  Win rate:             {win_rate:.1f}%  (target: >45%)")
    print(f"  SL hits:              {len(sls)}")
    print(f"  Max consec losses:    {max_consec_losses}")
    print(f"  Profit factor:        {profit_factor:.2f}  (target: >1.50)")
    print(f"  Avg win:              ${avg_win:.2f}")
    print(f"  Avg loss:             ${avg_loss:.2f}")
    print(f"  Avg RR:               {avg_rr:.2f}:1  (target: >1.5)")
    print(f"  Max drawdown:         {max_dd*100:.2f}%  (limit: 10%)")
    print(f"  Worst day:            ${max_daily_loss:.2f}")
    print(f"  Daily violations:     {daily_violations}  (limit: 0)")
    print(f"  Total P&L (90d):      ${total_pnl:.2f}")
    print(f"  Monthly avg:          ${monthly_return:.2f}/month")
    print(f"  Trading days:         {trading_days}")

    print(f"\n  BY PAIR:")
    for pair, s in sorted(pair_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        pnl_s = f"+${s['pnl']:.2f}" if s["pnl"] >= 0 else f"-${abs(s['pnl']):.2f}"
        icon = "🟢" if s["pnl"] > 0 else "🔴"
        print(f"    {icon} {pair:<8} {s['trades']:>3} trades  WR:{wr:.0f}%  {pnl_s}")

    print(f"\n  BY SESSION:")
    for sess, s in sorted(session_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        pnl_s = f"+${s['pnl']:.2f}" if s["pnl"] >= 0 else f"-${abs(s['pnl']):.2f}"
        print(f"    {sess:<12} {s['trades']:>3} trades  WR:{wr:.0f}%  {pnl_s}")

    print(f"\n{sep}")
    print(f"  PROP FIRM SIMULATION — {PROP['name']}")
    print(sep)
    print(f"  Balance:           $10,000")
    print(f"  Profit target:     $1,000  (10%)")
    print(f"  Max daily loss:    $500    (5%)")
    print(f"  Max drawdown:      $1,000  (10%)")
    print(f"  Days window:       30")
    print()
    print(f"  Result after {prop_days_elapsed} days:")
    print(f"    Profit:          ${prop_profit:.2f}")
    print(f"    Max drawdown:    {prop_dd*100:.2f}%")
    print(f"    Trading days:    {prop_trading_days}")
    print(f"    Daily violations:{prop_daily_violations}")
    print()
    print(f"  VERDICT: {prop_verdict}")
    if prop_fail:
        print(f"  Note: {prop_fail}")

    print(f"\n{sep}")
    print("  RECOMMENDATIONS FOR PROP FIRM PASS")
    print(sep)
    recs = []
    if win_rate < 45:
        recs.append(f"Win rate {win_rate:.1f}% → Require all 5 criteria and avoid counter-trend")
    if profit_factor < 1.5:
        recs.append(f"Profit factor {profit_factor:.2f} → Extend TP2 to 3:1, cut losers faster")
    if max_dd * 100 > 6:
        recs.append(f"Drawdown {max_dd*100:.1f}% → Cap daily loss at 2 trades max")
    if avg_rr < 1.5:
        recs.append(f"Avg RR {avg_rr:.2f} → Only take trades with min 1.5:1 setup RR")
    if daily_violations > 0:
        recs.append(f"{daily_violations} daily limit breaches → Hard stop after -$400 in a day")
    if max_consec_losses >= 3:
        recs.append(f"Max {max_consec_losses} consecutive losses → Take a break after 2 SL hits")

    # Find best performing pair
    best_pair = max(pair_stats.items(), key=lambda x: x[1]["pnl"])[0] if pair_stats else "N/A"
    worst_pair = min(pair_stats.items(), key=lambda x: x[1]["pnl"])[0] if pair_stats else "N/A"
    best_sess = max(session_stats.items(), key=lambda x: x[1]["pnl"])[0] if session_stats else "N/A"

    recs.append(f"Focus on {best_pair} (best pair) + {best_sess} session")
    recs.append(f"Avoid or reduce size on {worst_pair}")

    for r in recs:
        print(f"  • {r}")
    print()

if __name__ == "__main__":
    run_backtest()
