"""
Profit-focused optimizer. Target: Profit Factor > 1.5, positive net.
Win rate is whatever it needs to be. Searches RR targets, runners,
quality filters, per-pair edge, and trade management.
"""

import requests, time, datetime
from collections import defaultdict

BASE = "https://demo.tradelocker.com/backend-api"
EMAIL="carlinpool94@gmail.com"; PASSWORD="Tinapool321!?"; SERVER="GenFX"
LOOKBACK_DAYS=90

PAIRS={"EURUSD":{"id":278,"r":452},"GBPUSD":{"id":279,"r":452},
       "USDJPY":{"id":283,"r":452},"USDCAD":{"id":281,"r":452},
       "AUDUSD":{"id":277,"r":452},"GBPJPY":{"id":243,"r":452},
       "EURJPY":{"id":238,"r":452}}

def auth():
    r=requests.post(f"{BASE}/auth/jwt/token",json={"email":EMAIL,"password":PASSWORD,"server":SERVER})
    h={"Authorization":f"Bearer {r.json()['accessToken']}"}
    a=requests.get(f"{BASE}/auth/jwt/all-accounts",headers=h).json()["accounts"][0]
    return {**h,"accNum":str(a["accNum"])}

def fetch(h,iid,rid,res,days):
    now=int(time.time()*1000);frm=now-days*86400*1000
    return requests.get(f"{BASE}/trade/history",headers=h,params={"tradableInstrumentId":iid,"routeId":rid,"resolution":res,"from":frm,"to":now}).json().get("d",{}).get("barDetails",[])

def atr(b,p=14):
    t=[max(b[i]["h"]-b[i]["l"],abs(b[i]["h"]-b[i-1]["c"]),abs(b[i]["l"]-b[i-1]["c"])) for i in range(1,len(b))]
    return sum(t[-p:])/min(len(t),p) if t else 0

def trend(b):
    if len(b)<24:return "neutral"
    r=b[-24:];m=len(r)//2;fh,sh=r[:m],r[m:]
    hh=max(x["h"] for x in sh)>max(x["h"] for x in fh);hl=min(x["l"] for x in sh)>min(x["l"] for x in fh)
    lh=max(x["h"] for x in sh)<max(x["h"] for x in fh);ll=min(x["l"] for x in sh)<min(x["l"] for x in fh)
    if hh and hl:return "bullish"
    if lh and ll:return "bearish"
    return "neutral"

def ob(b,d,lb=40):
    r=b[-lb:] if len(b)>=lb else b;n=len(r)
    for i in range(n-4,1,-1):
        if d=="bullish" and r[i]["c"]<r[i]["o"] and sum(1 for j in range(1,4) if i+j<n and r[i+j]["c"]>r[i+j]["o"])>=2:
            return {"high":r[i]["h"],"low":r[i]["l"]}
        if d=="bearish" and r[i]["c"]>r[i]["o"] and sum(1 for j in range(1,4) if i+j<n and r[i+j]["c"]<r[i+j]["o"])>=2:
            return {"high":r[i]["h"],"low":r[i]["l"]}
    return None

def fvg(b,d,lb=30):
    r=b[-lb:] if len(b)>=lb else b
    for i in range(2,len(r)):
        if d=="bullish" and r[i]["l"]>r[i-2]["h"]:return True
        if d=="bearish" and r[i]["h"]<r[i-2]["l"]:return True
    return False

def sweep(b,d,lb=25):
    r=b[-lb:] if len(b)>=lb else b
    for i in range(5,len(r)):
        w=r[max(0,i-10):i]
        if d=="bullish" and r[i]["l"]<min(x["l"] for x in w) and r[i]["c"]>min(x["l"] for x in w):return True
        if d=="bearish" and r[i]["h"]>max(x["h"] for x in w) and r[i]["c"]<max(x["h"] for x in w):return True
    return False

def bos(b,d,lb=30):
    r=b[-lb:] if len(b)>=lb else b
    if len(r)<8:return False
    m=len(r)//2;e,l=r[:m],r[m:]
    if d=="bullish":return any(x["c"]>max(y["h"] for y in e) for x in l)
    return any(x["c"]<min(y["l"] for y in e) for x in l)

def london(ts):
    dt=datetime.datetime.utcfromtimestamp(ts/1000)
    return dt.weekday()<5 and 7<=dt.hour<12

def detect(b1,b4,name,i,cfg):
    if i<50:return None
    c=b1[i]
    if not london(c["t"]):return None
    h4=[b for b in b4 if b["t"]<=c["t"]]
    if len(h4)<24:return None
    d=trend(h4)
    if d=="neutral":return None
    hist=b1[:i+1];ps=0.01 if "JPY" in name else 0.0001;a=atr(hist[-20:])
    if a==0:return None
    price=c["c"];score=0
    o=ob(hist,d)
    if o and o["low"]<=price<=o["high"]:score+=1
    if fvg(hist,d):score+=1
    if sweep(hist,d):score+=1
    if bos(hist,d):score+=1
    body=abs(c["c"]-c["o"]);rng=c["h"]-c["l"];bp=body/rng if rng else 0
    if d=="bullish" and c["c"]>c["o"] and bp>=0.4:score+=1
    elif d=="bearish" and c["c"]<c["o"] and bp>=0.4:score+=1
    if score<cfg["min_score"]:return None
    if d=="bullish":
        entry=c["c"];sl=(o["low"] if o else entry-a)-a*0.1;risk=entry-sl
    else:
        entry=c["c"];sl=(o["high"] if o else entry+a)+a*0.1;risk=sl-entry
    rp=risk/ps
    if rp>cfg["max_sl"] or rp<5:return None
    sign=1 if d=="bullish" else -1
    return {"d":d,"entry":entry,"sl":sl,"risk":risk,"ps":ps,"score":score,"name":name,
            "tp_final":entry+risk*cfg["rr"]*sign,
            "tp_partial":entry+risk*cfg["rr_partial"]*sign,"t":c["t"]}

def sim(s,fut,cfg):
    d=s["d"];e=s["entry"];sl=s["sl"];tpf=s["tp_final"];tpp=s["tp_partial"];ps=s["ps"]
    partial_hit=False;closed=0.0;pips=0.0
    pc=cfg["partial_close"]/100.0
    for bar in fut[:cfg["max_hold"]]:
        h,l=bar["h"],bar["l"]
        if d=="bullish":
            if cfg["partial_close"]>0 and not partial_hit and h>=tpp:
                partial_hit=True;pips+=(tpp-e)/ps*pc;closed+=pc
            cur=e if (partial_hit and cfg["be"]) else sl
            if l<=cur: pips+=(cur-e)/ps*(1-closed);return pips
            if h>=tpf: pips+=(tpf-e)/ps*(1-closed);return pips
        else:
            if cfg["partial_close"]>0 and not partial_hit and l<=tpp:
                partial_hit=True;pips+=(e-tpp)/ps*pc;closed+=pc
            cur=e if (partial_hit and cfg["be"]) else sl
            if h>=cur: pips+=(e-cur)/ps*(1-closed);return pips
            if l<=tpf: pips+=(e-tpf)/ps*(1-closed);return pips
    last=fut[-1]["c"] if fut else e
    pips+=((last-e)/ps if d=="bullish" else (e-last)/ps)*(1-closed)
    return pips

def run(cfg,data,pairs):
    trades=[]
    for name in pairs:
        b1,b4=data[name];last=-10
        for i in range(50,len(b1)-1):
            if i-last<6:continue
            s=detect(b1,b4,name,i,cfg)
            if not s:continue
            trades.append(sim(s,b1[i+1:],cfg));last=i
    if not trades:return None
    w=[t for t in trades if t>0]
    gp=sum(t for t in trades if t>0);gl=abs(sum(t for t in trades if t<0))
    return {"wr":len(w)/len(trades)*100,"n":len(trades),"pf":gp/gl if gl else 999,"net":sum(trades)}

if __name__=="__main__":
    print("Fetching...");h=auth();data={}
    for n,c in PAIRS.items():
        data[n]=(fetch(h,c["id"],c["r"],"1H",LOOKBACK_DAYS),fetch(h,c["id"],c["r"],"4H",LOOKBACK_DAYS))
    print("done\n")

    # First: find which pairs have edge individually (simple 1:2 RR, no partial, score 4)
    base={"min_score":4,"max_sl":20,"rr":2.0,"rr_partial":1.0,"partial_close":0,"be":False,"max_hold":120}
    print("PER-PAIR EDGE (score4, 1:2 RR, hold to TP/SL):")
    pair_pf={}
    for n in PAIRS:
        r=run(base,data,[n])
        if r:
            pair_pf[n]=r["pf"]
            print(f"  {n}: WR {r['wr']:.0f}%  PF {r['pf']:.2f}  N {r['n']}  net {r['net']:+.0f}p")
    good=[n for n,pf in pair_pf.items() if pf>=1.0]
    print(f"\n  Pairs with PF>=1.0: {good}")

    if not good:
        good=sorted(pair_pf,key=pair_pf.get,reverse=True)[:3]
        print(f"  None profitable alone. Using top-3 least-bad: {good}")

    print("\nOPTIMIZING (best pairs only) for Profit Factor...\n")
    print(f"{'minS':>4} {'maxSL':>5} {'rr':>4} {'part':>5} {'pclose':>6} {'BE':>3} {'hold':>4} | {'WR':>5} {'N':>4} {'PF':>5} {'net':>7}")
    print("-"*78)
    best=None
    for ms in [4,5]:
        for msl in [12,15,20,25]:
            for rr in [2.0,2.5,3.0,4.0]:
                for (part,pc,be) in [(0,0,False),(1.0,50,True),(1.0,33,True)]:
                    for hold in [60,120]:
                        cfg={"min_score":ms,"max_sl":msl,"rr":rr,"rr_partial":part,
                             "partial_close":pc,"be":be,"max_hold":hold}
                        r=run(cfg,data,good)
                        if not r or r["n"]<10:continue
                        flag=" <<<" if r["pf"]>=1.5 else (" *" if r["pf"]>=1.2 else "")
                        if r["pf"]>=1.2:
                            print(f"{ms:>4} {msl:>5} {rr:>4} {part:>5} {pc:>6} {str(be):>3} {hold:>4} | {r['wr']:>4.0f}% {r['n']:>4} {r['pf']:>5.2f} {r['net']:>7.0f}{flag}")
                        if best is None or r["pf"]>best[1]["pf"]:
                            best=(cfg,r)
    print("\n"+"="*78)
    if best:
        c,r=best
        print(f"BEST CONFIG: WR {r['wr']:.0f}% | PF {r['pf']:.2f} | {r['n']} trades | net {r['net']:+.0f} pips")
        print(f"  Pairs:        {good}")
        print(f"  Min score:    {c['min_score']}")
        print(f"  Max SL pips:  {c['max_sl']}")
        print(f"  TP RR:        1:{c['rr']}")
        print(f"  Partial:      {c['partial_close']}% at 1:{c['rr_partial']}" if c['partial_close'] else "  Partial:      none (full to TP)")
        print(f"  Move to BE:   {c['be']}")
        print(f"  Max hold:     {c['max_hold']} bars")
