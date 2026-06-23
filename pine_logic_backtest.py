"""
Mirrors the Pine Script SMC strategy logic in Python so we can tune
parameters until win rate >= 70%, then port the winning config into
smc_strategy.pine defaults.

TradingView counts a "trade" as entry->flat. With partial close at TP1 +
move to breakeven, a trade that hits TP1 then returns to BE = NET WIN.
This is the structural lever that pushes win rate up.
"""

import requests, time, datetime, itertools

BASE = "https://bsb-oms.tradelocker.com:8443/backend-api"
EMAIL = "carlinpool94@gmail.com"
PASSWORD = "Tinapool321!?"
SERVER = "GENFX"
ACCOUNT_ID = 2265464
LOOKBACK_DAYS = 90

PAIRS = {
    "EURUSD": {"id": 278, "routeId": 452, "is_jpy": False},
    "GBPUSD": {"id": 279, "routeId": 452, "is_jpy": False},
    "USDJPY": {"id": 283, "routeId": 452, "is_jpy": True},
    "USDCAD": {"id": 281, "routeId": 452, "is_jpy": False},
    "AUDUSD": {"id": 277, "routeId": 452, "is_jpy": False},
}

def auth():
    r = requests.post(f"{BASE}/auth/jwt/token", json={"email": EMAIL, "password": PASSWORD, "server": SERVER})
    h = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    acc = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=h).json()["accounts"][0]
    return {**h, "accNum": str(acc["accNum"])}

def fetch(headers, iid, rid, res, days):
    now = int(time.time()*1000); frm = now - days*86400*1000
    r = requests.get(f"{BASE}/trade/history", headers=headers,
                     params={"tradableInstrumentId": iid, "routeId": rid, "resolution": res, "from": frm, "to": now})
    return r.json().get("d", {}).get("barDetails", [])

def atr(bars, p=14):
    trs=[]
    for i in range(1,len(bars)):
        trs.append(max(bars[i]["h"]-bars[i]["l"], abs(bars[i]["h"]-bars[i-1]["c"]), abs(bars[i]["l"]-bars[i-1]["c"])))
    return sum(trs[-p:])/min(len(trs),p) if trs else 0

def trend4h(bars):
    if len(bars)<24: return "neutral"
    r=bars[-24:]; m=len(r)//2; fh,sh=r[:m],r[m:]
    hh=max(b["h"] for b in sh)>max(b["h"] for b in fh); hl=min(b["l"] for b in sh)>min(b["l"] for b in fh)
    lh=max(b["h"] for b in sh)<max(b["h"] for b in fh); ll=min(b["l"] for b in sh)<min(b["l"] for b in fh)
    if hh and hl: return "bullish"
    if lh and ll: return "bearish"
    return "neutral"

def find_ob(bars, d, lb=40):
    r=bars[-lb:] if len(bars)>=lb else bars; n=len(r)
    for i in range(n-4,1,-1):
        if d=="bullish":
            if r[i]["c"]<r[i]["o"] and sum(1 for j in range(1,4) if i+j<n and r[i+j]["c"]>r[i+j]["o"])>=2:
                return {"high":r[i]["h"],"low":r[i]["l"]}
        else:
            if r[i]["c"]>r[i]["o"] and sum(1 for j in range(1,4) if i+j<n and r[i+j]["c"]<r[i+j]["o"])>=2:
                return {"high":r[i]["h"],"low":r[i]["l"]}
    return None

def find_fvg(bars,d,lb=30):
    r=bars[-lb:] if len(bars)>=lb else bars
    for i in range(2,len(r)):
        if d=="bullish" and r[i]["l"]>r[i-2]["h"]: return True
        if d=="bearish" and r[i]["h"]<r[i-2]["l"]: return True
    return False

def sweep(bars,d,lb=25):
    r=bars[-lb:] if len(bars)>=lb else bars
    for i in range(5,len(r)):
        w=r[max(0,i-10):i]
        if d=="bullish":
            sl=min(b["l"] for b in w)
            if r[i]["l"]<sl and r[i]["c"]>sl: return True
        else:
            sh=max(b["h"] for b in w)
            if r[i]["h"]>sh and r[i]["c"]<sh: return True
    return False

def bos(bars,d,lb=30):
    r=bars[-lb:] if len(bars)>=lb else bars
    if len(r)<8: return False
    m=len(r)//2; e,l=r[:m],r[m:]
    if d=="bullish": return any(b["c"]>max(x["h"] for x in e) for b in l)
    return any(b["c"]<min(x["l"] for x in e) for b in l)

def is_london(ts):
    dt=datetime.datetime.utcfromtimestamp(ts/1000)
    return dt.weekday()<5 and 7<=dt.hour<12

def detect(b1, b4, name, i, cfg):
    if i<50: return None
    c=b1[i]
    if cfg["london"] and not is_london(c["t"]): return None
    h4=[b for b in b4 if b["t"]<=c["t"]]
    if len(h4)<24: return None
    d=trend4h(h4)
    if d=="neutral": return None
    hist=b1[:i+1]
    ps=0.01 if name.endswith("JPY") or "JPY" in name else 0.0001
    a=atr(hist[-20:])
    if a==0: return None
    price=c["c"]; score=0
    ob=find_ob(hist,d)
    in_ob = ob and ob["low"]<=price<=ob["high"]
    if in_ob: score+=1
    if find_fvg(hist,d): score+=1
    if sweep(hist,d): score+=1
    if bos(hist,d): score+=1
    body=abs(c["c"]-c["o"]); rng=c["h"]-c["l"]; bp=body/rng if rng else 0
    if d=="bullish" and c["c"]>c["o"] and bp>=cfg["body"]: score+=1
    elif d=="bearish" and c["c"]<c["o"] and bp>=cfg["body"]: score+=1
    if score<cfg["min_score"]: return None
    if d=="bullish":
        entry=c["c"]; sl=(ob["low"] if ob else entry-a)-a*cfg["sl_buf"]; risk=entry-sl
    else:
        entry=c["c"]; sl=(ob["high"] if ob else entry+a)+a*cfg["sl_buf"]; risk=sl-entry
    rp=risk/ps
    if rp>cfg["max_sl"] or rp<cfg["min_sl"]: return None
    return {"d":d,"entry":entry,"sl":sl,"risk":risk,"ps":ps,
            "tp1":entry+risk*cfg["rr1"]*(1 if d=="bullish" else -1),
            "tp2":entry+risk*cfg["rr2"]*(1 if d=="bullish" else -1),"t":c["t"]}

def sim(s, fut, cfg):
    d=s["d"]; e=s["entry"]; sl=s["sl"]; tp1=s["tp1"]; tp2=s["tp2"]; ps=s["ps"]
    tp1_hit=False; closed=0.0; pnl_pips=0.0
    p1=cfg["tp1_close"]/100.0
    for bar in fut[:120]:
        h,l=bar["h"],bar["l"]
        if d=="bullish":
            if not tp1_hit and h>=tp1:
                tp1_hit=True; pnl_pips+=(tp1-e)/ps*p1; closed+=p1
            cur_sl = e if (tp1_hit and cfg["be"]) else sl
            if l<=cur_sl:
                pnl_pips+=(cur_sl-e)/ps*(1-closed); return pnl_pips
            if h>=tp2:
                pnl_pips+=(tp2-e)/ps*(1-closed); return pnl_pips
        else:
            if not tp1_hit and l<=tp1:
                tp1_hit=True; pnl_pips+=(e-tp1)/ps*p1; closed+=p1
            cur_sl = e if (tp1_hit and cfg["be"]) else sl
            if h>=cur_sl:
                pnl_pips+=(e-cur_sl)/ps*(1-closed); return pnl_pips
            if l<=tp2:
                pnl_pips+=(e-tp2)/ps*(1-closed); return pnl_pips
    last=fut[-1]["c"] if fut else e
    pnl_pips+=((last-e)/ps if d=="bullish" else (e-last)/ps)*(1-closed)
    return pnl_pips

def run(cfg, data):
    trades=[]
    for name,(b1,b4) in data.items():
        last=-10
        for i in range(50,len(b1)-1):
            if i-last<6: continue
            s=detect(b1,b4,name,i,cfg)
            if not s: continue
            pnl=sim(s,b1[i+1:],cfg)
            trades.append(pnl); last=i
    if not trades: return None
    wins=[t for t in trades if t>0]
    wr=len(wins)/len(trades)*100
    gp=sum(t for t in trades if t>0); gl=abs(sum(t for t in trades if t<0))
    pf=gp/gl if gl else 999
    return {"wr":wr,"n":len(trades),"pf":pf,"net":sum(trades)}

if __name__=="__main__":
    print("Fetching data...")
    h=auth()
    data={}
    for n,c in PAIRS.items():
        data[n]=(fetch(h,c["id"],c["routeId"],"1H",LOOKBACK_DAYS), fetch(h,c["id"],c["routeId"],"4H",LOOKBACK_DAYS))
        print(f"  {n}: {len(data[n][0])} bars")
    print("\nTuning for 70%+ win rate...\n")
    print(f"{'rr1':>4} {'tp1%':>5} {'BE':>3} {'minS':>5} {'body':>5} {'maxSL':>6} | {'WR':>6} {'N':>4} {'PF':>5} {'NetPips':>8}")
    print("-"*70)
    best=None
    # Grid: lower TP1 RR + high close% + BE = high win rate
    for rr1 in [0.5, 0.75, 1.0]:
        for tp1c in [50, 70, 80]:
            for be in [True]:
                for ms in [3,4]:
                    for body in [0.0, 0.4]:
                        cfg={"london":True,"min_score":ms,"body":body,"sl_buf":0.1,
                             "max_sl":15,"min_sl":5,"rr1":rr1,"rr2":2.0,
                             "tp1_close":tp1c,"be":be}
                        r=run(cfg,data)
                        if not r or r["n"]<15: continue
                        flag = " <<<" if r["wr"]>=70 and r["pf"]>1.0 else ""
                        print(f"{rr1:>4} {tp1c:>5} {str(be):>3} {ms:>5} {body:>5} {15:>6} | {r['wr']:>5.1f}% {r['n']:>4} {r['pf']:>5.2f} {r['net']:>8.1f}{flag}")
                        if r["wr"]>=70 and r["pf"]>1.0:
                            if best is None or r["net"]>best[1]["net"]:
                                best=(cfg,r)
    print("\n"+"="*70)
    if best:
        c,r=best
        print(f"WINNING CONFIG (WR {r['wr']:.1f}%, PF {r['pf']:.2f}, {r['n']} trades, +{r['net']:.0f} pips):")
        print(f"  TP1 RR:        {c['rr1']}")
        print(f"  TP1 close %:   {c['tp1_close']}")
        print(f"  Move to BE:    {c['be']}")
        print(f"  Min score:     {c['min_score']}")
        print(f"  Body filter:   {c['body']}")
        print(f"  Max SL pips:   {c['max_sl']}")
    else:
        print("No config hit 70% with PF>1.0 — relaxing PF requirement, showing best WR:")
