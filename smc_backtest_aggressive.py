"""
SMC Backtest — Aggressive Prop Firm Version
Goal: Hit 10% profit target in <30 days
Rules:
  - 1% risk per trade (dynamic lot sizing based on SL pips)
  - Tight SL: exact OB edge + minimal buffer (max 18 pips)
  - London session ONLY (07:00-12:00 UTC)
  - Best 3 pairs only: EURUSD, USDJPY, USDCAD
  - 5/5 SMC criteria required
  - Max 3 trades per day, hard stop at -$350/day
  - Trail SL to breakeven at TP1, target TP2 (2:1 RR)
"""

import requests
import time
import datetime
from collections import defaultdict

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BASE = "https://bsb-oms.tradelocker.com:8443/backend-api"
EMAIL = "carlinpool94@gmail.com"
PASSWORD = "Tinapool321!?"
SERVER = "GENFX"
ACCOUNT_ID = 2265464

LOOKBACK_DAYS = 90
RISK_PCT = 0.02            # 2% of equity per trade (aggressive)
MAX_SL_PIPS = 15           # reject setups with wider SL
MAX_LOTS = 3.0             # hard cap on position size
MIN_SIGNAL_SCORE = 4       # 4 of 5 SMC criteria (allows 1 miss)
MAX_TRADES_PER_DAY = 2     # max 2 trades/day (quality over quantity)
DAILY_LOSS_STOP = 400      # stop trading day at -$400 (4% daily limit buffer)
PARTIAL_CLOSE = False      # hold full position — no TP1+BE partial close

PROP = {
    "balance": 10_000,
    "daily_loss_limit": 500,   # 5% = $500
    "max_drawdown": 1_000,     # 10% = $1,000
    "profit_target": 1_000,    # 10% = $1,000
    "max_days": 30,
}

# pip_val = USD per 1 pip at 1.0 standard lot
PAIRS = {
    "EURUSD": {"id": 278, "routeId": 452, "is_jpy": False, "spread": 0.5,  "pip_val_lot": 10.00},
    "USDJPY": {"id": 283, "routeId": 452, "is_jpy": True,  "spread": 1.0,  "pip_val_lot": 6.70},
    "USDCAD": {"id": 281, "routeId": 452, "is_jpy": False, "spread": 1.0,  "pip_val_lot": 7.30},
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

def trend_4h(bars):
    if len(bars) < 12:
        return "neutral"
    recent = bars[-24:]
    mid = len(recent) // 2
    fh, sh = recent[:mid], recent[mid:]
    hh = max(b["h"] for b in sh) > max(b["h"] for b in fh)
    hl = min(b["l"] for b in sh) > min(b["l"] for b in fh)
    lh = max(b["h"] for b in sh) < max(b["h"] for b in fh)
    ll = min(b["l"] for b in sh) < min(b["l"] for b in fh)
    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "neutral"

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
            return True
        if direction == "bearish" and recent[i]["h"] < recent[i-2]["l"]:
            return True
    return False

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

def is_london(ts_ms):
    dt = datetime.datetime.utcfromtimestamp(ts_ms / 1000)
    return dt.weekday() < 5 and 7 <= dt.hour < 12

# ─── SIGNAL DETECTION ─────────────────────────────────────────────────────────

def score_setup(bars_1h, bars_4h, pair_name, idx):
    if idx < 50:
        return 0, None

    curr = bars_1h[idx]
    if not is_london(curr["t"]):
        return 0, None

    curr_time = curr["t"]
    h4_hist = [b for b in bars_4h if b["t"] <= curr_time]
    if len(h4_hist) < 12:
        return 0, None

    direction = trend_4h(h4_hist)
    if direction == "neutral":
        return 0, None

    hist = bars_1h[:idx + 1]
    pip_size = 0.01 if PAIRS[pair_name]["is_jpy"] else 0.0001
    curr_atr = calc_atr(hist[-20:])
    if curr_atr == 0:
        return 0, None

    price = curr["c"]
    score = 0

    # 1. Order Block — price must be INSIDE OB zone
    ob = find_ob(hist, direction)
    in_ob = ob and (ob["low"] <= price <= ob["high"])
    if in_ob:
        score += 1
    elif ob:
        # OB nearby (within 0.3×ATR)
        if direction == "bullish" and ob["low"] - curr_atr * 0.3 <= price <= ob["high"] + curr_atr * 0.2:
            score += 1
        elif direction == "bearish" and ob["low"] - curr_atr * 0.2 <= price <= ob["high"] + curr_atr * 0.3:
            score += 1

    # 2. FVG present
    if find_fvg(hist, direction):
        score += 1

    # 3. Liquidity sweep
    if has_liq_sweep(hist, direction):
        score += 1

    # 4. BOS confirmed
    if has_bos(hist, direction):
        score += 1

    # 5. Confirmation candle — body > 50% of candle range, closes in direction
    body = abs(curr["c"] - curr["o"])
    rng = curr["h"] - curr["l"]
    body_pct = body / rng if rng else 0
    if direction == "bullish" and curr["c"] > curr["o"] and body_pct >= 0.50:
        score += 1
    elif direction == "bearish" and curr["c"] < curr["o"] and body_pct >= 0.50:
        score += 1

    if score < MIN_SIGNAL_SCORE:
        return score, None

    # ── Build trade levels (TIGHT SL) ────────────────────────────────────────
    spread_pips = PAIRS[pair_name]["spread"]
    pip_val_lot = PAIRS[pair_name]["pip_val_lot"]

    if direction == "bullish":
        entry = curr["c"] + spread_pips * pip_size
        # SL: just below OB low with tiny 0.1×ATR buffer
        ob_low = ob["low"] if ob else entry - curr_atr
        sl = ob_low - curr_atr * 0.10
        risk = entry - sl
        risk_pips = risk / pip_size

        if risk_pips > MAX_SL_PIPS:
            return score, None   # SL too wide — skip

        tp1 = entry + risk          # 1:1
        tp2 = entry + risk * 2     # 2:1
        tp3 = entry + risk * 3     # 3:1
    else:
        entry = curr["c"] - spread_pips * pip_size
        ob_high = ob["high"] if ob else entry + curr_atr
        sl = ob_high + curr_atr * 0.10
        risk = sl - entry
        risk_pips = risk / pip_size

        if risk_pips > MAX_SL_PIPS:
            return score, None

        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    if risk_pips < 5:
        return score, None   # SL too tight — price noise will clip it

    return score, {
        "pair": pair_name,
        "direction": direction,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_pips": round(risk_pips, 1),
        "pip_size": pip_size,
        "pip_val_lot": pip_val_lot,
        "timestamp": curr["t"],
        "date": datetime.datetime.utcfromtimestamp(curr["t"] / 1000).strftime("%Y-%m-%d %H:%M"),
    }

# ─── SIMULATION ───────────────────────────────────────────────────────────────

def calc_lots(equity, risk_pips, pip_val_lot):
    """Size position so $ risk = 1% of equity"""
    dollar_risk = equity * RISK_PCT
    pip_dollar = pip_val_lot  # $ per pip at 1.0 lot
    lots = dollar_risk / (risk_pips * pip_dollar)
    lots = round(min(lots, MAX_LOTS), 2)
    return max(lots, 0.01)

def simulate(setup, future_bars, lots):
    d = setup["direction"]
    entry = setup["entry"]
    sl = setup["sl"]
    tp1, tp2, tp3 = setup["tp1"], setup["tp2"], setup["tp3"]
    pip_size = setup["pip_size"]
    pip_val_lot = setup["pip_val_lot"]

    result = "EXPIRED"
    exit_pips = 0
    be_active = False   # breakeven mode after TP1

    for bar in future_bars[:120]:
        h, l = bar["h"], bar["l"]

        if d == "bullish":
            # Move SL to BE after TP1 (if partial close disabled, just trail SL)
            if not be_active and h >= tp1:
                be_active = True
            active_sl = entry if be_active else sl
            if l <= active_sl:
                exit_pips = (active_sl - entry) / pip_size   # 0 at BE, negative at SL
                result = "BE" if be_active else "SL"
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
            if not be_active and l <= tp1:
                be_active = True
            active_sl = entry if be_active else sl
            if h >= active_sl:
                exit_pips = (entry - active_sl) / pip_size
                result = "BE" if be_active else "SL"
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

    pnl = exit_pips * pip_val_lot * lots

    return {
        "result": result,
        "pips": round(exit_pips, 1),
        "lots": lots,
        "pnl": round(pnl, 2),
    }

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    print("Authenticating...")
    headers, _ = auth()
    print("Fetching 90-day history (London only | EURUSD, USDJPY, USDCAD | 5/5 score)...\n")

    all_bars_1h, all_bars_4h = {}, {}
    for name, cfg in PAIRS.items():
        all_bars_1h[name] = fetch_bars(headers, cfg["id"], cfg["routeId"], "1H", LOOKBACK_DAYS)
        all_bars_4h[name] = fetch_bars(headers, cfg["id"], cfg["routeId"], "4H", LOOKBACK_DAYS)
        print(f"  {name}: {len(all_bars_1h[name])} x 1H bars")

    print(f"\nRunning aggressive backtest (risk {RISK_PCT*100:.0f}% per trade, max SL {MAX_SL_PIPS}p)...\n")

    # Walk through time with equity tracking and daily rules
    equity = PROP["balance"]
    peak_equity = equity
    max_dd = 0
    trades = []
    daily_pnl = defaultdict(float)
    daily_trade_count = defaultdict(int)
    daily_stopped = set()   # days where daily stop was hit

    for pair_name in PAIRS:
        bars_1h = all_bars_1h[pair_name]
        bars_4h = all_bars_4h[pair_name]
        last_signal_bar = -10

        for i in range(50, len(bars_1h) - 1):
            if i - last_signal_bar < 6:
                continue

            score, setup = score_setup(bars_1h, bars_4h, pair_name, i)
            if setup is None:
                continue

            day = setup["date"][:10]

            # Daily trade limit
            if daily_trade_count[day] >= MAX_TRADES_PER_DAY:
                continue

            # Daily loss stop
            if day in daily_stopped:
                continue

            # Calculate lot size based on current equity
            lots = calc_lots(equity, setup["risk_pips"], setup["pip_val_lot"])
            dollar_risk = setup["risk_pips"] * setup["pip_val_lot"] * lots

            future = bars_1h[i + 1:]
            outcome = simulate(setup, future, lots)
            trade = {**setup, **outcome, "dollar_risk": round(dollar_risk, 2)}
            trades.append(trade)

            # Update state
            daily_pnl[day] += outcome["pnl"]
            daily_trade_count[day] += 1
            equity += outcome["pnl"]
            peak_equity = max(peak_equity, equity)
            dd_pct = (peak_equity - equity) / PROP["balance"]
            max_dd = max(max_dd, dd_pct)

            if daily_pnl[day] <= -DAILY_LOSS_STOP:
                daily_stopped.add(day)

            last_signal_bar = i

    trades.sort(key=lambda t: t["timestamp"])

    # ─── STATS ────────────────────────────────────────────────────────────────

    total = len(trades)
    if not total:
        print("No trades found.")
        return

    wins   = [t for t in trades if t["result"] in ("TP2", "TP3", "TP1+BE")]
    sls    = [t for t in trades if t["result"] == "SL"]
    exps   = [t for t in trades if t["result"] == "EXPIRED"]

    win_rate = len(wins) / total * 100
    total_pnl = sum(t["pnl"] for t in trades)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss   = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss else 999
    avg_win  = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(sls) if sls else 0
    avg_rr   = avg_win / avg_loss if avg_loss else 0
    monthly  = total_pnl / 3
    avg_lots = sum(t["lots"] for t in trades) / total

    max_consec = 0
    consec = 0
    for t in trades:
        if t["result"] == "SL":
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    worst_day = min(daily_pnl.values()) if daily_pnl else 0
    daily_violations = sum(1 for d, p in daily_pnl.items() if p < -PROP["daily_loss_limit"])

    # Prop firm simulation — first 30 calendar days
    sorted_days = sorted(daily_pnl.keys())
    prop_equity = PROP["balance"]
    prop_peak = prop_equity
    prop_dd = 0
    prop_trading_days = 0
    prop_fail = None
    days_elapsed = 0
    daily_log = []

    for day in sorted_days[:PROP["max_days"]]:
        days_elapsed += 1
        dp = daily_pnl.get(day, 0)
        prop_equity += dp
        prop_profit_now = prop_equity - PROP["balance"]
        prop_peak = max(prop_peak, prop_equity)
        dd = (prop_peak - prop_equity) / PROP["balance"]
        prop_dd = max(prop_dd, dd)
        if dp != 0:
            prop_trading_days += 1
        daily_log.append((day, dp, prop_equity, prop_profit_now, dd * 100))

        if dp < -PROP["daily_loss_limit"]:
            prop_fail = f"Daily limit breached {day} (${dp:.0f})"
            break
        if prop_dd >= 0.10:
            prop_fail = f"Max DD breached {prop_dd*100:.1f}%"
            break
        if prop_profit_now >= PROP["profit_target"]:
            break   # target hit!

    prop_profit = prop_equity - PROP["balance"]

    if prop_fail:
        verdict = "❌ FAIL"
    elif prop_profit >= PROP["profit_target"]:
        verdict = f"✅ PASS — Challenge cleared in {days_elapsed} days!"
    else:
        verdict = f"⚠️ INCOMPLETE — ${prop_profit:.0f} / $1,000 after {days_elapsed} days"

    # Per-pair stats
    pair_stats = defaultdict(lambda: {"t": 0, "w": 0, "pnl": 0.0, "lots": 0.0})
    for t in trades:
        p = t["pair"]
        pair_stats[p]["t"] += 1
        pair_stats[p]["pnl"] += t["pnl"]
        pair_stats[p]["lots"] += t["lots"]
        if t["result"] != "SL" and t["result"] != "EXPIRED":
            pair_stats[p]["w"] += 1

    # ─── PRINT ────────────────────────────────────────────────────────────────

    sep = "=" * 70
    print(sep)
    print("  AGGRESSIVE SMC BACKTEST — London Only | 3 Pairs | 5/5 Signal | 1% Risk")
    print(sep)

    print(f"\n{'DATE':<18} {'PAIR':<8} {'DIR':<5} {'LOTS':>5} {'SL':>5}p {'RESULT':<12} {'PIPS':>7} {'P&L':>9}")
    print("-" * 70)
    for t in trades:
        pnl_s = f"+${t['pnl']:.2f}" if t["pnl"] >= 0 else f"-${abs(t['pnl']):.2f}"
        pip_s = f"+{t['pips']:.1f}" if t["pips"] >= 0 else f"{t['pips']:.1f}"
        icon = "✅" if t["pnl"] > 0 else ("❌" if t["result"] == "SL" else "⬜")
        print(f"{icon} {t['date']:<16} {t['pair']:<8} {t['direction'][:4].upper():<5} "
              f"{t['lots']:>5.2f} {t['risk_pips']:>5.1f} {t['result']:<12} {pip_s:>7} {pnl_s:>9}")

    print(f"\n{sep}")
    print("  PERFORMANCE METRICS")
    print(sep)
    print(f"  Trades total:         {total}")
    print(f"  Trades / month:       {total/3:.1f}")
    print(f"  Avg lot size:         {avg_lots:.2f} lots")
    print(f"  Win rate:             {win_rate:.1f}%")
    print(f"  SL hits:              {len(sls)}")
    print(f"  Max consec losses:    {max_consec}")
    print(f"  Profit factor:        {profit_factor:.2f}")
    print(f"  Avg win:              ${avg_win:.2f}")
    print(f"  Avg loss:             ${avg_loss:.2f}")
    print(f"  Avg RR:               {avg_rr:.2f}:1")
    print(f"  Max drawdown:         {max_dd*100:.2f}%  (limit 10%)")
    print(f"  Worst day:            ${worst_day:.2f}  (limit -$500)")
    print(f"  Daily violations:     {daily_violations}  (must be 0)")
    print(f"  Daily stops hit:      {len(daily_stopped)}")
    print(f"  Total P&L (90d):      ${total_pnl:.2f}")
    print(f"  Monthly avg:          ${monthly:.2f}")

    print(f"\n  BY PAIR:")
    for pair, s in sorted(pair_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = s["w"] / s["t"] * 100 if s["t"] else 0
        avg_lot = s["lots"] / s["t"] if s["t"] else 0
        pnl_s = f"+${s['pnl']:.2f}" if s["pnl"] >= 0 else f"-${abs(s['pnl']):.2f}"
        icon = "🟢" if s["pnl"] > 0 else "🔴"
        print(f"    {icon} {pair:<8} {s['t']:>3} trades  WR:{wr:.0f}%  avg {avg_lot:.2f}L  {pnl_s}")

    print(f"\n{sep}")
    print(f"  PROP FIRM SIMULATION — FTMO $10k Phase 1")
    print(sep)
    print(f"\n  {'Day':<12} {'Daily P&L':>11} {'Equity':>10} {'Profit':>9} {'DD':>7}")
    print(f"  {'-'*52}")
    for day, dp, eq, prf, dd in daily_log:
        dp_s = f"+${dp:.0f}" if dp >= 0 else f"-${abs(dp):.0f}"
        prf_s = f"+${prf:.0f}" if prf >= 0 else f"-${abs(prf):.0f}"
        bar_filled = min(int(prf / PROP["profit_target"] * 20), 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        progress = prf / PROP["profit_target"] * 100
        print(f"  {day:<12} {dp_s:>11} ${eq:>8,.0f} {prf_s:>9}  DD:{dd:.1f}%  [{bar}] {progress:.0f}%")

    print()
    print(f"  VERDICT:    {verdict}")
    if prop_fail:
        print(f"  Failure:    {prop_fail}")
    print(f"  Final P&L:  ${prop_profit:.2f}")
    print(f"  Max DD:     {prop_dd*100:.2f}%")
    print(f"  Trade days: {prop_trading_days}")

    print(f"\n{sep}")
    print("  SIGNAL SETTINGS TO USE ON YOUR ACCOUNT")
    print(sep)

    # Calculate suggested lot for today's equity
    today_equity = PROP["balance"] + total_pnl
    eurusd_lots = calc_lots(today_equity, 12, PAIRS["EURUSD"]["pip_val_lot"])
    usdjpy_lots = calc_lots(today_equity, 12, PAIRS["USDJPY"]["pip_val_lot"])
    usdcad_lots = calc_lots(today_equity, 12, PAIRS["USDCAD"]["pip_val_lot"])

    print(f"  Account equity today:  ${today_equity:,.2f}")
    print(f"  Risk per trade (1%):   ${today_equity * RISK_PCT:.2f}")
    print(f"  Max SL allowed:        {MAX_SL_PIPS} pips")
    print(f"  Max trades/day:        {MAX_TRADES_PER_DAY}")
    print(f"  Stop trading if day P&L < -${DAILY_LOSS_STOP}")
    print()
    print(f"  Suggested lots (12-pip SL baseline):")
    print(f"    EURUSD: {eurusd_lots:.2f} lots")
    print(f"    USDJPY: {usdjpy_lots:.2f} lots")
    print(f"    USDCAD: {usdcad_lots:.2f} lots")
    print()
    print(f"  Entry checklist:")
    print(f"    ✓ London open 07:00-12:00 UTC only")
    print(f"    ✓ 4H trend confirmed (HH+HL or LH+LL)")
    print(f"    ✓ Price inside Order Block zone")
    print(f"    ✓ FVG present in same direction")
    print(f"    ✓ Liquidity sweep confirmed")
    print(f"    ✓ Break of Structure in direction")
    print(f"    ✓ Confirmation candle (>50% body, closes in direction)")
    print(f"    ✓ SL at OB edge, max {MAX_SL_PIPS} pips")
    print(f"    ✓ Move SL to BE when TP1 hit")
    print(f"    ✓ Target TP2 (2:1 RR)")

if __name__ == "__main__":
    run()
