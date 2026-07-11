"""
The Daily Sweep System — scanner + honest-fill backtest.
Daily bias -> NY-open sweep against bias -> FVG confirmation -> limit at 50% FVG,
stop beyond sweep + buffer, target = PDH/PDL, minimum 2R.

Honest-fill rules (same as sniper): trade-through fills, spread paid,
same-bar TP+SL = loss. Validate out-of-sample + perturbation before trusting.

BACKTEST FINDING (be honest): a MECHANICAL version of this system was
net-NEGATIVE across every parameter combination on 90d GenFX data
(-3.4R to -7.6R; ~9-26 trades). That does NOT condemn the system — the PDF
describes a DISCRETIONARY manual method (visual bias, best-trap-location
judgement, DXY inverse confirmation, news timing, FVG-quality discretion) that
a mechanical scanner cannot reproduce. Use this as a MANUAL playbook / alert
aid, not an auto-trader. For a mechanically-validated edge, use sniper_smc.py
(70% WR / PF 2.17, holds out-of-sample + perturbation).
"""
import json

# Per-instrument stop buffers (in price units) and pip sizes
PIP = {"EURUSD":0.0001,"GBPUSD":0.0001,"USDJPY":0.01,"USDCHF":0.0001,"USDCAD":0.0001,
       "AUDUSD":0.0001,"NZDUSD":0.0001,"GBPJPY":0.01,"EURJPY":0.01,"AUDJPY":0.01,
       "EURGBP":0.0001,"GBPCAD":0.0001,"XAUUSD":0.1,"NAS100":1.0,"SPX500":1.0}
SPREAD = {"EURUSD":0.6,"GBPUSD":0.9,"USDJPY":0.7,"USDCHF":1.0,"USDCAD":1.2,
          "AUDUSD":0.8,"NZDUSD":1.2,"GBPJPY":1.6,"EURJPY":1.3,"AUDJPY":1.4,
          "EURGBP":1.0,"GBPCAD":2.2,"XAUUSD":2.5,"NAS100":2.0,"SPX500":1.5}
# buffer beyond sweep extreme, in PIPS (mid of PDF ranges)
BUFFER_PIPS = {"EURUSD":4,"GBPUSD":4,"USDCHF":4,"USDCAD":4,"AUDUSD":4,"NZDUSD":4,"EURGBP":4,
               "USDJPY":6,"GBPJPY":6,"EURJPY":6,"AUDJPY":6,"GBPCAD":6,
               "XAUUSD":22,"SPX500":4,"NAS100":20,"US30":40}

def day_key(ms): return ms // 86400000
def hour_of(ms): return int((ms//3600000)%24)
def minute_of(ms): return int((ms//60000)%60)

def to_daily(b15):
    """Aggregate 15m bars into UTC-daily candles."""
    days={}
    for b in b15:
        k=day_key(b["t"])
        if k not in days: days[k]={"o":b["o"],"h":b["h"],"l":b["l"],"c":b["c"],"t":b["t"]}
        else:
            d=days[k]; d["h"]=max(d["h"],b["h"]); d["l"]=min(d["l"],b["l"]); d["c"]=b["c"]
    return [days[k] for k in sorted(days)]

def daily_bias(completed_dailies):
    """HH+HL (last completed day vs prior) -> bullish; LH+LL -> bearish; else None."""
    if len(completed_dailies) < 2: return None
    d = completed_dailies[-2:]
    if d[-1]["h"] > d[-2]["h"] and d[-1]["l"] > d[-2]["l"]: return "bullish"
    if d[-1]["h"] < d[-2]["h"] and d[-1]["l"] < d[-2]["l"]: return "bearish"
    return None

def in_ny_killzone(ms, is_index=False):
    """09:30-11:00 ET = 13:30-15:00 UTC (EDT). Forex/gold extend from 12:30 UTC."""
    h=hour_of(ms); m=minute_of(ms)
    start_ok = (h==13 and m>=30) or (h==14) or (h==12 and m>=30 and not is_index)
    end_ok = h<15 or (h==15 and m==0)
    return start_ok and end_ok

def backtest_ds(DATA, name, lo_frac=0.0, hi_frac=1.0, min_rr=2.0, fvg_min=0.10,
                disp_mult=0.5, entry_pct=0.5, be_at=1.5, max_hold=32):
    pip=PIP[name]; sp=SPREAD[name]*pip; buf=BUFFER_PIPS.get(name,5)*pip
    b15=DATA[name]["15m"]
    N=len(b15); lo_i=int(N*lo_frac); hi_i=int(N*hi_frac)
    dailies_all=to_daily(b15)
    is_index = name in ("NAS100","SPX500","US30")
    W=L=BE=0; gW=gL=R=0.0; trades=0
    traded_days=set()
    i=max(210,lo_i); last=0; lim=min(hi_i,N-max_hold-1)
    while i<lim:
        if i<last: i+=1; continue
        bar=b15[i]; ts=bar["t"]
        if not in_ny_killzone(ts, is_index): i+=1; continue
        dk=day_key(ts)
        if (name,dk) in traded_days: i+=1; continue   # max 1/instrument/day
        # dailies up to (not incl) today
        dl=[d for d in dailies_all if day_key(d["t"])<dk]
        if len(dl)<2: i+=1; continue
        bias=daily_bias(dl)   # dl = completed days only (today excluded)
        if bias is None: i+=1; continue
        pdh=dl[-1]["h"]; pdl=dl[-1]["l"]
        w=b15[max(0,i-40):i+1]; price=bar["c"]
        # sweep AGAINST bias of a recent 1H (=4x15m) low/high
        recent=w[-16:-1]
        swept=sweep_ext=None
        if bias=="bullish":
            lo=min(b["l"] for b in recent)
            if bar["l"]<lo and bar["c"]>lo: swept,sweep_ext="bull",bar["l"]
        else:
            hi=max(b["h"] for b in recent)
            if bar["h"]>hi and bar["c"]<hi: swept,sweep_ext="bear",bar["h"]
        if swept is None: i+=1; continue
        # FVG (displacement) in bias direction within next 4 bars, on 15m
        # displacement FVG in bias direction within 4 bars. Displacement = c3 body
        # >= disp_mult * avg range of last 14 bars; gap >= fvg_min pips.
        avg_rng = sum(b["h"]-b["l"] for b in w[-14:])/14
        fvg=None
        for j in range(i+1, min(i+5,len(b15))):
            if j-2<0: continue
            c1,c3=b15[j-2],b15[j]
            if abs(c3["c"]-c3["o"]) < disp_mult*avg_rng: continue   # need displacement
            if bias=="bullish" and c3["l"]>c1["h"] and (c3["l"]-c1["h"])>=fvg_min*pip:
                fvg=(c1["h"],c3["l"]); mss_j=j; break
            if bias=="bearish" and c3["h"]<c1["l"] and (c1["l"]-c3["h"])>=fvg_min*pip:
                fvg=(c3["h"],c1["l"]); mss_j=j; break
        if fvg is None: i+=1; continue
        # entry at CE (50% by default)
        if bias=="bullish":
            E=fvg[0]+(fvg[1]-fvg[0])*(1-entry_pct) if False else (fvg[0]+fvg[1])/2
            sl=sweep_ext-buf; sign=1; target=pdh
        else:
            E=(fvg[0]+fvg[1])/2; sl=sweep_ext+buf; sign=-1; target=pdl
        risk=abs(E-sl)
        if risk<max(6*pip,3*sp): i+=1; continue
        rr=abs(target-E)/risk
        if rr<min_rr: i+=1; continue   # min 2R or skip
        # trade-through fill
        filled=None
        for k in range(mss_j+1, min(mss_j+1+16,len(b15))):
            ck=b15[k]
            if bias=="bullish" and ck["l"]<=E-1*pip: filled=k; break
            if bias=="bearish" and ck["h"]>=E+1*pip: filled=k; break
            if (bias=="bullish" and ck["c"]<sweep_ext) or (bias=="bearish" and ck["c"]>sweep_ext): break
        if filled is None: i+=1; continue
        entry=E+sign*sp
        tp=target
        be_price=entry; moved=False; outcome=None; realR=0.0
        for j in range(filled, min(filled+max_hold,len(b15))):
            hb=b15[j]
            if not moved and ((sign==1 and hb["h"]>=entry+risk*be_at) or (sign==-1 and hb["l"]<=entry-risk*be_at)):
                sl=be_price; moved=True
            hit_sl=(sign==1 and hb["l"]<=sl) or (sign==-1 and hb["h"]>=sl)
            hit_tp=(sign==1 and hb["h"]>=tp) or (sign==-1 and hb["l"]<=tp)
            if hit_sl and hit_tp and j==filled: realR=-1.0; outcome="d"; break
            if hit_sl:
                realR = 0.0 if (moved and sl==be_price) else -1.0; outcome="d"; break
            if hit_tp:
                realR = abs(tp-entry)/risk; outcome="d"; break
        if outcome is None:
            lp=b15[min(filled+max_hold,len(b15)-1)]["c"]; realR=((lp-entry)/risk)*sign
        trades+=1; R+=realR; traded_days.add((name,dk))
        if realR>0.05: W+=1; gW+=realR
        elif realR<-0.05: L+=1; gL+=abs(realR)
        else: BE+=1
        last=filled+1; i=last
    dec=W+L; wr=W/dec*100 if dec else 0; pf=gW/gL if gL>0 else 999
    return {"n":trades,"WR":round(wr,1),"PF":round(pf,2),"expR":round(R/trades,3) if trades else 0,"totR":round(R,1)}

if __name__=="__main__":
    DATA=json.load(open("/tmp/bt90.json"))
    print("THE DAILY SWEEP SYSTEM — 90d honest-fill backtest\n")
    print(f"{'PAIR':8}{'n':5}{'WR%':7}{'PF':7}{'expR':8}{'totR':8}")
    agg={"W":0,"L":0,"R":0.0,"n":0}
    rows=[]
    for name in DATA:
        r=backtest_ds(DATA,name); rows.append((name,r))
    rows.sort(key=lambda x:-x[1]["totR"])
    for name,r in rows:
        tag=" ⭐" if (r["PF"]>1.3 and r["n"]>=8) else (" 📈" if r["PF"]>1 else "")
        print(f"{name:8}{r['n']:<5}{r['WR']:<7}{r['PF']:<7}{r['expR']:<8}{r['totR']:<8}{tag}")
    tot_n=sum(r['n'] for _,r in rows); tot_R=sum(r['totR'] for _,r in rows)
    print(f"\nPortfolio: {tot_n} trades, {tot_R:+.1f}R")


# ── LIVE SCANNER (discretionary aid — alerts you to forming setups) ──────────
def scan_live(headers):
    """Scan instruments for a live Daily-Sweep setup during the NY killzone.
    Returns candidate alerts. This is a DISCRETIONARY aid — confirm manually."""
    import trading_agent as ta, datetime
    now = datetime.datetime.utcnow()
    out = []
    INSTR = ["EURUSD","GBPUSD","USDJPY","XAUUSD","NAS100","SPX500"]
    for name in INSTR:
        if name not in ta.MARKETS: continue
        cfg = ta.MARKETS[name]; pip = PIP.get(name, cfg["pip"])
        b15 = ta.fetch_bars(headers, cfg["id"], "15m", 12)
        if len(b15) < 100: continue
        is_index = name in ("NAS100","SPX500","US30")
        if not in_ny_killzone(b15[-1]["t"], is_index):
            continue
        dailies = to_daily(b15)
        dk = day_key(b15[-1]["t"])
        dl = [d for d in dailies if day_key(d["t"]) < dk]
        if len(dl) < 2: continue
        bias = daily_bias(dl)
        if bias is None: continue
        pdh, pdl = dl[-1]["h"], dl[-1]["l"]
        w = b15[-40:]; bar = w[-1]; recent = w[-16:-1]
        swept = None
        if bias == "bullish":
            lo = min(x["l"] for x in recent)
            if bar["l"] < lo and bar["c"] > lo: swept, se = "bull", bar["l"]
        else:
            hi = max(x["h"] for x in recent)
            if bar["h"] > hi and bar["c"] < hi: swept, se = "bear", bar["h"]
        if swept is None: continue
        out.append({"name": name, "bias": bias, "sweep_extreme": se,
                    "target": pdh if bias == "bullish" else pdl,
                    "note": "sweep printed — watch for displacement FVG to confirm entry"})
    return out


def scan_live_main():
    import trading_agent as ta, datetime
    headers, aid, bal = ta.auth()
    print(f"Daily-Sweep live scan {datetime.datetime.utcnow().strftime('%H:%M UTC')} | bal ${bal:,.2f}")
    for s in scan_live(headers):
        print(f"  {s['name']} {s['bias'].upper()} — swept {s['sweep_extreme']} → target {s['target']} | {s['note']}")
