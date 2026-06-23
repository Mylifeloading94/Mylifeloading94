"""
AI Forex Trading Agent
Scans every 15 minutes, max 3 trades/day, trailing SL, Telegram alerts.
Markets: Major/Minor Forex, Gold (XAUUSD), SPX500, NAS100
"""

import requests, time, datetime, json, os

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE        = "https://bsb-oms.tradelocker.com:8443/backend-api"
EMAIL       = os.environ["TL_EMAIL"]
PASSWORD    = os.environ["TL_PASSWORD"]
SERVER      = os.environ.get("TL_SERVER", "GENFX")
ACCOUNT_ID  = int(os.environ.get("TL_ACCOUNT_ID", "2265464"))
USER_ID     = os.environ.get("TL_USER_ID", "6fab173e-1a6c-4a97-a199-ea4eab9518c6")
TG_TOKEN    = os.environ["TG_BOT_TOKEN"]
TG_CHAT     = os.environ["TG_CHAT_ID"]
RISK_PCT    = 0.02
MAX_TRADES  = 3
SCAN_EVERY  = 900   # 15 minutes
UPDATE_EVERY= 14400 # 4 hours
TG_ALERTS   = False  # set True to resume Telegram trade alerts

MARKETS = {
    # Major Forex
    "EURUSD": {"id":278, "info":452, "trade":9912, "pip":0.0001, "pip_val":10.00,  "type":"forex",  "emoji":"🇪🇺"},
    "GBPUSD": {"id":279, "info":452, "trade":9912, "pip":0.0001, "pip_val":10.00,  "type":"forex",  "emoji":"🇬🇧"},
    "USDJPY": {"id":283, "info":452, "trade":9912, "pip":0.01,   "pip_val":6.70,   "type":"forex",  "emoji":"🇯🇵"},
    "USDCHF": {"id":280, "info":452, "trade":9912, "pip":0.0001, "pip_val":10.00,  "type":"forex",  "emoji":"🇨🇭"},
    "USDCAD": {"id":281, "info":452, "trade":9912, "pip":0.0001, "pip_val":7.30,   "type":"forex",  "emoji":"🇨🇦"},
    "AUDUSD": {"id":277, "info":452, "trade":9912, "pip":0.0001, "pip_val":10.00,  "type":"forex",  "emoji":"🇦🇺"},
    "NZDUSD": {"id":284, "info":452, "trade":9912, "pip":0.0001, "pip_val":10.00,  "type":"forex",  "emoji":"🇳🇿"},
    # Minor Forex
    "GBPJPY": {"id":243, "info":452, "trade":9912, "pip":0.01,   "pip_val":6.70,   "type":"forex",  "emoji":"🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "EURJPY": {"id":238, "info":452, "trade":9912, "pip":0.01,   "pip_val":6.70,   "type":"forex",  "emoji":"🇪🇺"},
    "AUDJPY": {"id":229, "info":452, "trade":9912, "pip":0.01,   "pip_val":6.70,   "type":"forex",  "emoji":"🇦🇺"},
    "EURGBP": {"id":235, "info":452, "trade":9912, "pip":0.0001, "pip_val":12.50,  "type":"forex",  "emoji":"🇪🇺"},
    "GBPCAD": {"id":241, "info":452, "trade":9912, "pip":0.0001, "pip_val":7.30,   "type":"forex",  "emoji":"🇬🇧"},
    # Gold
    "XAUUSD": {"id":314, "info":452, "trade":9912, "pip":0.1,    "pip_val":1.00,   "type":"metal",  "emoji":"🥇"},
    # Indices
    "SPX500": {"id":307, "info":452, "trade":9912, "pip":1.0,    "pip_val":1.00,   "type":"index",  "emoji":"📈"},
    "NAS100": {"id":306, "info":452, "trade":9912, "pip":1.0,    "pip_val":1.00,   "type":"index",  "emoji":"💻"},
}

STATE_FILE = "/home/user/agent_state.json"

# ─── STATE ────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"trades_today": 0, "trade_date": "", "last_update": 0, "last_engage": 0}

def save_state(s):
    json.dump(s, open(STATE_FILE, "w"))

def reset_daily_if_needed(state):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if state["trade_date"] != today:
        state["trades_today"] = 0
        state["trade_date"]   = today
    return state

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def tg_send(text):
    if not TG_ALERTS:
        return  # alerts paused — execute on TL only until strategy is validated
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  json={"chat_id": TG_CHAT, "text": text}, timeout=10)

# ─── AUTH ─────────────────────────────────────────────────────────────────────
def auth():
    r = requests.post(f"{BASE}/auth/jwt/token",
                      json={"email":EMAIL,"password":PASSWORD,"server":SERVER}, timeout=15)
    h = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    acc = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=h, timeout=15).json()["accounts"][0]
    return {**h, "accNum": str(acc["accNum"])}, acc["id"]

# ─── DATA ─────────────────────────────────────────────────────────────────────
def fetch_bars(headers, iid, rid, res, days=30):
    now_ms = int(time.time()*1000); frm_ms = now_ms - days*86400*1000
    for attempt in range(4):
        try:
            r = requests.get(f"{BASE}/trade/history", headers=headers, params={
                "tradableInstrumentId":iid,"routeId":rid,"resolution":res,
                "from":frm_ms,"to":now_ms}, timeout=15)
            if r.status_code==429 or not r.text.strip():
                time.sleep(2**attempt); continue
            return r.json().get("d",{}).get("barDetails",[])
        except Exception:
            time.sleep(2**attempt)
    return []

# ─── INDICATORS ───────────────────────────────────────────────────────────────
def atr(bars, p=14):
    trs=[max(bars[i]["h"]-bars[i]["l"],abs(bars[i]["h"]-bars[i-1]["c"]),
             abs(bars[i]["l"]-bars[i-1]["c"])) for i in range(1,len(bars))]
    return sum(trs[-p:])/min(len(trs),p) if trs else 0

def market_structure(bars):
    if len(bars)<24: return "neutral",0
    r=bars[-24:]; m=len(r)//2; e,l=r[:m],r[m:]
    hh=max(b["h"] for b in l)>max(b["h"] for b in e)
    hl=min(b["l"] for b in l)>min(b["l"] for b in e)
    lh=max(b["h"] for b in l)<max(b["h"] for b in e)
    ll=min(b["l"] for b in l)<min(b["l"] for b in e)
    if hh and hl: return "bullish",2
    if lh and ll: return "bearish",2
    if hh or hl:  return "bullish",1
    if lh or ll:  return "bearish",1
    return "neutral",0

def find_ob(bars, d, lb=40):
    """Find the most recent UNMITIGATED order block."""
    r = bars[-lb:] if len(bars) >= lb else bars
    n = len(r)
    # Search from 5 bars back (need at least 4 bars after OB to confirm + leave room for current price)
    for i in range(n - 5, 1, -1):
        if d == "bullish" and r[i]["c"] < r[i]["o"]:
            # Need 2 of next 3 bars bullish to confirm impulse
            if sum(1 for j in range(1, 4) if i + j < n and r[i + j]["c"] > r[i + j]["o"]) >= 2:
                ob = {"high": r[i]["o"], "low": r[i]["c"]}  # body of bearish candle
                # Mitigation check: any subsequent candle CLOSED below OB low = mitigated
                if any(r[j]["c"] < ob["low"] for j in range(i + 1, n)):
                    continue  # consumed, skip
                ob["mid"] = (ob["high"] + ob["low"]) / 2
                return ob
        if d == "bearish" and r[i]["c"] > r[i]["o"]:
            if sum(1 for j in range(1, 4) if i + j < n and r[i + j]["c"] < r[i + j]["o"]) >= 2:
                ob = {"high": r[i]["c"], "low": r[i]["o"]}  # body of bullish candle
                if any(r[j]["c"] > ob["high"] for j in range(i + 1, n)):
                    continue
                ob["mid"] = (ob["high"] + ob["low"]) / 2
                return ob
    return None


def ob_rejection(bars, ob, d):
    """Check if the last 1-2 candles show rejection from the OB (entry confirmation)."""
    if not ob or len(bars) < 2:
        return False
    last = bars[-1]
    prev = bars[-2]
    if d == "bullish":
        # Last candle: bullish close AND lower wick (rejection off OB low)
        bullish_close = last["c"] > last["o"]
        lower_wick = (min(last["o"], last["c"]) - last["l"]) > abs(last["c"] - last["o"]) * 0.3
        touched_ob = last["l"] <= ob["high"] and last["c"] >= ob["low"]
        return bullish_close and lower_wick and touched_ob
    else:
        bearish_close = last["c"] < last["o"]
        upper_wick = (last["h"] - max(last["o"], last["c"])) > abs(last["c"] - last["o"]) * 0.3
        touched_ob = last["h"] >= ob["low"] and last["c"] <= ob["high"]
        return bearish_close and upper_wick and touched_ob

def find_fvg(bars, d, lb=30):
    r=bars[-lb:] if len(bars)>=lb else bars
    for i in range(2,len(r)):
        if d=="bullish" and r[i]["l"]>r[i-2]["h"]: return True
        if d=="bearish" and r[i]["h"]<r[i-2]["l"]: return True
    return False

def liq_sweep(bars, d, lb=25):
    r=bars[-lb:] if len(bars)>=lb else bars
    for i in range(5,len(r)):
        w=r[max(0,i-8):i]
        if d=="bullish":
            sl=min(b["l"] for b in w)
            if r[i]["l"]<sl and r[i]["c"]>sl: return True
        else:
            sh=max(b["h"] for b in w)
            if r[i]["h"]>sh and r[i]["c"]<sh: return True
    return False

def bos(bars, d, lb=30):
    r=bars[-lb:] if len(bars)>=lb else bars
    if len(r)<8: return False
    m=len(r)//2; e,l=r[:m],r[m:]
    if d=="bullish": return any(b["c"]>max(x["h"] for x in e) for b in l)
    return any(b["c"]<min(x["l"] for x in e) for b in l)

def momentum(bars, d):
    if len(bars)<3: return False
    last3=bars[-3:]
    if d=="bullish": return all(b["c"]>b["o"] for b in last3[-2:])
    return all(b["c"]<b["o"] for b in last3[-2:])

# ─── ANALYZE ──────────────────────────────────────────────────────────────────
MIN_RISK_PIPS = 8   # below this SL gets crushed by spread/slippage

def analyze(name, cfg, headers):
    time.sleep(1)
    b1 = fetch_bars(headers, cfg["id"], cfg["info"], "1H", 30)
    time.sleep(0.5)
    b4 = fetch_bars(headers, cfg["id"], cfg["info"], "4H", 30)
    if len(b1)<50 or len(b4)<20: return None

    d4, str4 = market_structure(b4)
    d1, str1 = market_structure(b1)
    if d4=="neutral": return None
    if d1!=d4: return None  # both TFs must agree

    price = b1[-1]["c"]
    a     = atr(b1[-20:])
    if a==0: return None

    score=0; reasons=[]
    if str4>=2: score+=2; reasons.append("4H & 1H trend aligned")
    elif str4==1: score+=1

    ob = find_ob(b1, d4)
    in_ob = ob and ob["low"] <= price <= ob["high"]
    approaching = ob and (
        (d4=="bullish" and ob["low"]-a*0.5 <= price <= ob["high"]+a*0.3) or
        (d4=="bearish" and ob["low"]-a*0.3 <= price <= ob["high"]+a*0.5)
    )
    # Require rejection confirmation when inside OB — not just location
    has_rejection = ob_rejection(b1, ob, d4)
    if in_ob and has_rejection: score+=2; reasons.append("OB rejection confirmed")
    elif in_ob:                 score+=1; reasons.append("price inside Order Block")
    elif approaching:           score+=1; reasons.append("approaching Order Block")

    if find_fvg(b1,d4): score+=1; reasons.append("FVG confirmed")
    if liq_sweep(b1,d4):score+=2; reasons.append("liquidity sweep")
    if bos(b1,d4):      score+=1; reasons.append("BOS confirmed")
    if momentum(b1,d4): score+=1; reasons.append("momentum aligned")

    if score<6: return None

    # ── LEVELS: SL anchored to recent structure, not OB boundary ──────────────
    pip  = cfg["pip"]
    entry = price  # always enter at current market price

    if d4 == "bullish":
        # SL = lowest low of last 15 bars minus 2-pip buffer
        struct_low = min(b["l"] for b in b1[-15:])
        sl = round(struct_low - 2 * pip, 5)
    else:
        struct_high = max(b["h"] for b in b1[-15:])
        sl = round(struct_high + 2 * pip, 5)

    risk      = abs(entry - sl)
    risk_pips = round(risk / pip, 1)

    # Hard floor: reject setups with SL too tight to survive spread/noise
    if risk_pips < MIN_RISK_PIPS:
        return None

    sign = 1 if d4=="bullish" else -1
    tp1  = round(entry + risk*1.5*sign, 5)
    tp2  = round(entry + risk*2.5*sign, 5)

    return {
        "name":name,"direction":d4,"score":score,"entry":round(entry,5),
        "sl":round(sl,5),"tp1":tp1,"tp2":tp2,"rr":"1:2.5","risk_pips":risk_pips,
        "reasons":", ".join(reasons),"cfg":cfg
    }

# ─── PLACE TRADE ──────────────────────────────────────────────────────────────
def calc_lots(risk_pips, pip_val, balance, risk_pct=RISK_PCT):
    """Position size: lots = risk_dollars / (risk_pips * pip_value_per_lot)."""
    risk_dollars = balance * risk_pct
    raw = risk_dollars / (risk_pips * pip_val) if risk_pips * pip_val > 0 else 0.01
    # Clamp to broker min/max and round to 2 dp
    return round(max(0.01, min(raw, 10.0)), 2)

def place_trade(headers, aid, setup, balance=25000.0):
    cfg  = setup["cfg"]
    side = "buy" if setup["direction"]=="bullish" else "sell"
    lots = calc_lots(setup["risk_pips"], cfg["pip_val"], balance)
    body = {
        "tradableInstrumentId": cfg["id"],
        "routeId":              cfg["trade"],
        "type":                 "market",
        "side":                 side,
        "qty":                  lots,
        "validity":             "IOC",
        "stopLoss":             setup["sl"],
        "takeProfit":           setup["tp2"],
        "stopLossType":         "absolute",
        "takeProfitType":       "absolute",
    }
    r = requests.post(f"{BASE}/trade/accounts/{aid}/orders", headers=headers, json=body, timeout=15)
    d = r.json()
    return d.get("s")=="ok", d.get("d",{}).get("orderId")

# ─── TELEGRAM ALERT ───────────────────────────────────────────────────────────
def send_alert(setup):
    now   = datetime.datetime.utcnow().strftime("%H:%M UTC")
    arrow = "📈" if setup["direction"]=="bullish" else "📉"
    side  = "BUY" if setup["direction"]=="bullish" else "SELL"
    pip   = setup["cfg"]["pip"]
    tp1_pips = round(abs(setup["tp1"]-setup["entry"])/pip,1)
    tp2_pips = round(abs(setup["tp2"]-setup["entry"])/pip,1)

    msg = f"""🔥TRADE ALERT🔥

{arrow} {setup['name']} {side}
💰 Entry: {round(setup['entry'],5)}
🛑 Stop Loss: {round(setup['sl'],5)}
🎯 TP1: {round(setup['tp1'],5)} (+{tp1_pips} pips)
🎯 TP2: {round(setup['tp2'],5)} (+{tp2_pips} pips)
📊 RR: {setup['rr']}
🧠 Reason: {setup['reasons'].title()}
🕐 {now}"""
    tg_send(msg)

# ─── 4H UPDATE ────────────────────────────────────────────────────────────────
def send_position_update(headers, aid):
    raw = requests.get(f"{BASE}/trade/accounts/{aid}/positions", headers=headers, timeout=15).json()
    positions = raw.get("d",{}).get("positions",[])

    IMAP = {v["id"]:k for k,v in MARKETS.items()}
    now  = datetime.datetime.utcnow().strftime("%H:%M UTC")

    if not positions:
        tg_send(f"📊 TRADE UPDATE — {now}\n\nNo open positions. Watching for next setup. 👀")
        return

    lines=[f"📊 TRADE UPDATE — {now}\n"]
    total_pips=0
    for p in positions:
        iid  = int(p[1]); name=IMAP.get(iid,f"ID:{iid}")
        side = p[3].upper(); entry=float(p[5]); pnl_usd=float(p[9])
        cfg  = MARKETS.get(name)
        if cfg:
            # estimate pips from USD pnl (approximate)
            pip_val = cfg["pip_val"]
            pips    = round(pnl_usd / (pip_val*float(p[4])), 1) if pip_val else 0
        else:
            pips = 0
        total_pips += pips
        icon = "🟢" if pips>=0 else "🔴"
        lines.append(f"{icon} {name} {side} — {pips:+.1f} pips")

    status = "🟢" if total_pips>=0 else "🔴"
    lines.append(f"\n{status} Total: {total_pips:+.1f} pips")
    tg_send("\n".join(lines))

# ─── ENGAGEMENT ───────────────────────────────────────────────────────────────
ENGAGE_MSGS = [
    "💬 How is everyone doing this session? Drop your thoughts below 👇",
    "👀 What setups are you watching right now? Share with the group!",
    "❓ Any questions about today's signals? Ask away — we're here to help.",
    "📊 What markets are showing the cleanest structure right now?",
    "🔥 Stay disciplined traders. Quality over quantity — always.",
    "💡 Reminder: Let the trade come to you. Never chase entries.",
    "🧠 Risk management first. Profits follow discipline.",
]
_engage_idx = 0
def send_engagement():
    global _engage_idx
    tg_send(ENGAGE_MSGS[_engage_idx % len(ENGAGE_MSGS)])
    _engage_idx += 1

# ─── MAIN LOOP ────────────────────────────────────────────────────────────────
def run():
    print("🤖 Agent starting... (Telegram alerts PAUSED — TL execution only)")

    headers, aid = auth()
    token_time   = time.time()
    state        = load_state()

    while True:
        now_ts = time.time()

        # Refresh token every 20 min
        if now_ts - token_time > 1200:
            try: headers, aid = auth(); token_time = now_ts
            except: pass

        state = reset_daily_if_needed(state)

        # ── SCAN ──────────────────────────────────────────────────────────────
        if state["trades_today"] < MAX_TRADES:
            print(f"\n[{datetime.datetime.utcnow().strftime('%H:%M')}] Scanning {len(MARKETS)} markets...")
            setups=[]
            for name, cfg in MARKETS.items():
                try:
                    s = analyze(name, cfg, headers)
                    if s:
                        setups.append(s)
                        print(f"  ✅ {name} {s['direction'].upper()} score={s['score']}/9")
                    else:
                        print(f"  — {name} no setup")
                except Exception as e:
                    print(f"  ⚠️ {name} error: {e}")

            # Take only top setup per scan (max 1 new trade per scan to avoid overtrading)
            setups.sort(key=lambda x: x["score"], reverse=True)
            if setups:
                top = setups[0]
                print(f"\nBest setup: {top['name']} {top['direction']} score={top['score']}/9")
                # Fetch live balance for correct position sizing
                try:
                    accs = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=headers, timeout=10).json()
                    live_bal = float(accs["accounts"][0]["accountBalance"])
                except Exception:
                    live_bal = 25000.0
                ok, oid = place_trade(headers, aid, top, balance=live_bal)
                if ok:
                    state["trades_today"] += 1
                    save_state(state)
                    print(f"  ✅ Trade placed — order {oid} ({top['name']} {top['direction'].upper()} {top['risk_pips']}p risk)")
                else:
                    print(f"  ❌ Trade failed")
            else:
                print("  No high-conviction setups this scan.")
        else:
            print(f"[{datetime.datetime.utcnow().strftime('%H:%M')}] Daily limit reached ({MAX_TRADES} trades). Monitoring only.")

        # ── 4H UPDATE ─────────────────────────────────────────────────────────
        if now_ts - state["last_update"] >= UPDATE_EVERY:
            send_position_update(headers, aid)
            state["last_update"] = now_ts
            save_state(state)

        # ── ENGAGEMENT ────────────────────────────────────────────────────────
        if now_ts - state["last_engage"] >= UPDATE_EVERY:
            send_engagement()
            state["last_engage"] = now_ts
            save_state(state)

        print(f"  Trades today: {state['trades_today']}/{MAX_TRADES}. Next scan in 15 min.")
        time.sleep(SCAN_EVERY)

if __name__ == "__main__":
    run()
