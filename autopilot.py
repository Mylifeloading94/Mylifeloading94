"""
Autopilot — scan-and-trade one iteration, with hard guardrails.
Run every 10 min during London+NY hours. Priority: sniper -> honest-edge -> PA.
Correlation + USD-exposure enforced in EVERY branch (fixes the PA gap that let
GBPJPY short stack on a GBPUSD short). Safe-capped size, daily trade/loss limits,
channel post only on a placed trade or a closed-trade result.
"""
import os, json, time, datetime, requests
import trading_agent as ta
import sniper_smc as sn
import honest_edge as he

TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT  = os.environ.get("TG_CHAT_ID", "-1001190707115")
STATE    = "agent_state.json"
MAX_TRADES_DAY = 3
DAILY_LOSS_PCT = 0.02
TRADE_HOURS = range(7, 17)   # 07:00-16:59 UTC


def _ema(vals, p):
    k = 2/(p+1); e = vals[0]
    for v in vals[1:]: e = v*k + e*(1-k)
    return e

def _usd_side(nm, side):
    buy = side in ("buy", "bullish")
    if nm in {"USDJPY","USDCHF","USDCAD"}: return "long" if buy else "short"
    if nm in {"EURUSD","GBPUSD","AUDUSD","NZDUSD"}: return "short" if buy else "long"
    return None

def _load_state(balance):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    try: st = json.load(open(STATE))
    except: st = {}
    if st.get("trade_date") != today:
        st = {"trade_date": today, "trades_today": 0, "day_start_balance": balance, "open_ids": []}
        json.dump(st, open(STATE, "w"))
    return st

def _allowed(name, direction, open_names, open_dirs):
    """Correlation + USD cap + no duplicate pair — enforced for ALL setups."""
    if name in open_names: return False
    if not ta.passes_correlation(name, open_names): return False
    if not ta.usd_exposure_ok(name, direction, open_dirs, 1): return False
    my = _usd_side(name, direction)
    if my and my in {_usd_side(n, d) for n, d in open_dirs}: return False
    return True

def _pa_scan(headers, open_names, open_dirs):
    """Price-action fallback: 1H trend + pullback to EMA20 + 15M rejection."""
    for name, cfg in ta.MARKETS.items():
        pip = cfg["pip"]
        b1 = ta.fetch_bars(headers, cfg["id"], "1H", 20); time.sleep(0.1)
        b15 = ta.fetch_bars(headers, cfg["id"], "15m", 5)
        if len(b1) < 60 or len(b15) < 50: continue
        c1 = [b["c"] for b in b1]; e20 = _ema(c1[-60:], 20); e50 = _ema(c1[-60:], 50)
        price = b1[-1]["c"]; a1 = ta.atr(b1[-20:])
        if e20 > e50 and price > e50: trend = "up"
        elif e20 < e50 and price < e50: trend = "down"
        else: continue
        if abs(price - e20) > 0.6*a1: continue
        last = b15[-1]; rng = last["h"]-last["l"] or pip
        lw = min(last["o"],last["c"])-last["l"]; uw = last["h"]-max(last["o"],last["c"])
        rej = (last["c"]>last["o"] and lw>=rng*0.4) if trend=="up" else (last["c"]<last["o"] and uw>=rng*0.4)
        if not rej: continue
        direction = "bullish" if trend=="up" else "bearish"; sign = 1 if trend=="up" else -1
        if not _allowed(name, direction, open_names, open_dirs): continue
        if trend=="up": sl = round(min(b["l"] for b in b15[-6:])-2*pip, 5)
        else: sl = round(max(b["h"] for b in b15[-6:])+2*pip, 5)
        risk = abs(price-sl); rpips = round(risk/pip, 1)
        if rpips < 6: continue
        return {"name":name,"direction":direction,"entry":round(price,5),"sl":sl,
                "tp1":round(price+risk*1.5*sign,5),"tp2":round(price+risk*2.0*sign,5),
                "risk_pips":rpips,"cfg":cfg,"bars_15m":b15,"src":"price-action"}
    return None

def _post(setup, side, lots):
    cfg = setup["cfg"]; pip = cfg["pip"]; rp = setup["risk_pips"]
    ta.generate_chart(setup["bars_15m"], f"{setup['name']} • 15M", setup["entry"],
                      setup["sl"], setup["tp1"], setup["tp2"], setup["direction"], "/tmp/ap.png")
    tp1p = round(abs(setup["tp1"]-setup["entry"])/pip, 1); tp2p = round(abs(setup["tp2"]-setup["entry"])/pip, 1)
    arrow = "📈" if setup["direction"]=="bullish" else "📉"
    cap = (f"{arrow} <b>{setup['name']} {side.upper()}</b>\nEntry: {setup['entry']}\n"
           f"Stop Loss: {setup['sl']} (-{rp:.0f} pips)\nTP1: {setup['tp1']} (+{tp1p:.0f} pips)\n"
           f"TP2: {setup['tp2']} (+{tp2p:.0f} pips)")
    with open("/tmp/ap.png", "rb") as f:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                      data={"chat_id":TG_CHAT,"caption":cap,"parse_mode":"HTML"},
                      files={"photo":f}, timeout=30)

def run_once():
    headers, aid, balance = ta.auth()
    now = datetime.datetime.utcnow()
    st = _load_state(balance)

    if now.hour not in TRADE_HOURS:
        return f"autopilot {now:%H:%M}: outside trading hours, holding"
    if st["trades_today"] >= MAX_TRADES_DAY:
        return f"autopilot {now:%H:%M}: daily trade limit ({MAX_TRADES_DAY}) reached, holding"
    if balance <= (1-DAILY_LOSS_PCT)*st["day_start_balance"]:
        return f"autopilot {now:%H:%M}: -2% daily loss limit hit (${balance:,.2f}), holding"

    pos = ta.get_positions(headers, aid)
    open_names = set(); open_dirs = []
    for p in pos:
        nm = ta.ID_TO_NAME.get(int(p[1]))
        if nm: open_names.add(nm); open_dirs.append((nm, p[3]))

    setup = None
    for s in sn.scan_sniper(headers):
        if _allowed(s["name"], s["direction"], open_names, open_dirs):
            setup = {**s, "src": "sniper"}; break
    if not setup:
        for s in he.scan_edge(headers):
            if _allowed(s["name"], s["direction"], open_names, open_dirs):
                setup = {**s, "src": "honest-edge"}; break
    if not setup:
        setup = _pa_scan(headers, open_names, open_dirs)

    if not setup:
        return f"autopilot {now:%H:%M}: no valid setup, holding"

    cfg = setup["cfg"]; side = "buy" if setup["direction"]=="bullish" else "sell"
    lots = sn.safe_lots(setup["risk_pips"], cfg["pip_val"], balance)
    body = {"tradableInstrumentId":cfg["id"],"routeId":ta.TRADE_ROUTE,"type":"market","side":side,
            "qty":lots,"validity":"IOC","stopLoss":setup["sl"],"takeProfit":setup["tp2"],
            "stopLossType":"absolute","takeProfitType":"absolute"}
    r = requests.post(f"{ta.BASE_URL}/trade/accounts/{aid}/orders", headers=headers, json=body, timeout=15)
    if r.json().get("s") == "ok":
        st["trades_today"] += 1; json.dump(st, open(STATE, "w"))
        _post(setup, side, lots)
        return f"autopilot {now:%H:%M}: TOOK {setup['name']} {side.upper()} ({setup['src']}) {lots}L @ {setup['entry']} — posted"
    return f"autopilot {now:%H:%M}: order failed {r.json()}"

if __name__ == "__main__":
    print(run_once())
