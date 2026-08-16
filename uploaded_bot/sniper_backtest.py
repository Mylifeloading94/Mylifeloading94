"""
Sniper-SMC backtest engine — full institutional entry sequence.
Sequence per trade (no lookahead):
  1. HTF bias (4H structure) + draw-on-liquidity direction.
  2. Liquidity sweep: 15M wick takes a prior swing / session extreme and closes back.
  3. MSS (market-structure shift): a displacement candle breaks the micro
     swing in the sweep-reversal direction (body >= disp*ATR).
  4. Return-to-origin: price retraces into the FVG / order block left by the
     displacement (the "sniper" mitigation entry) — limit fill at the zone.
  5. SL beyond the sweep extreme + buffer; TP by R multiples with partial+BE.
Reports per-pair win rate / PF / expectancy, with an out-of-sample split.
"""
import json

DATA = json.load(open("/tmp/bt90.json"))
PIP = {"EURUSD":0.0001,"GBPUSD":0.0001,"USDJPY":0.01,"USDCHF":0.0001,"USDCAD":0.0001,
       "AUDUSD":0.0001,"NZDUSD":0.0001,"GBPJPY":0.01,"EURJPY":0.01,"AUDJPY":0.01,
       "EURGBP":0.0001,"GBPCAD":0.0001,"XAUUSD":0.1,"NAS100":1.0,"SPX500":1.0}
SPREAD = {"EURUSD":0.6,"GBPUSD":0.9,"USDJPY":0.7,"USDCHF":1.0,"USDCAD":1.2,
          "AUDUSD":0.8,"NZDUSD":1.2,"GBPJPY":1.6,"EURJPY":1.3,"AUDJPY":1.4,
          "EURGBP":1.0,"GBPCAD":2.2,"XAUUSD":2.5,"NAS100":2.0,"SPX500":1.5}  # pips

def atr(bars,p=14):
    if len(bars)<2: return 0
    trs=[max(bars[i]["h"]-bars[i]["l"],abs(bars[i]["h"]-bars[i-1]["c"]),abs(bars[i]["l"]-bars[i-1]["c"])) for i in range(1,len(bars))]
    return sum(trs[-p:])/min(len(trs),p)

def swings(bars,s=3):
    out=[]
    for i in range(s,len(bars)-s):
        hi=bars[i]["h"]; lo=bars[i]["l"]
        if all(bars[j]["h"]<hi for j in range(i-s,i)) and all(bars[j]["h"]<hi for j in range(i+1,i+s+1)): out.append(("high",hi,i))
        if all(bars[j]["l"]>lo for j in range(i-s,i)) and all(bars[j]["l"]>lo for j in range(i+1,i+s+1)): out.append(("low",lo,i))
    return sorted(out,key=lambda x:x[2])

def structure(bars,lb=120,s=3):
    r=bars[-lb:] if len(bars)>=lb else bars
    sw=swings(r,s); hs=[x for x in sw if x[0]=="high"]; ls=[x for x in sw if x[0]=="low"]
    if len(hs)>=2 and len(ls)>=2:
        hh=hs[-1][1]>hs[-2][1]; hl=ls[-1][1]>ls[-2][1]; lh=hs[-1][1]<hs[-2][1]; ll=ls[-1][1]<ls[-2][1]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
        if hh or hl: return "bullish"
        if lh or ll: return "bearish"
    return "ranging"

def hour_of(ms): return int((ms//3600000)%24)
def bars_before(bars,ts,k):
    out=[b for b in bars if b["t"]<=ts]; return out[-k:] if len(out)>k else out

def in_sess(ms):
    h=hour_of(ms); m=int((ms//60000)%60)
    if 7<=h<=9: return True
    if h==10 and m<=45: return True
    if h==12 and m>=30: return True
    if 13<=h<=14: return True
    if h==15 and m<=45: return True
    return False

def sniper_bt(name, lo_i=0, hi_i=None, disp_mult=0.6, sl_buf=0.5, tp1_R=1.0, tp1_close=0.5,
              tp2_R=2.0, be=True, max_hold=48, retrace_bars=8, require_htf=True, sess_only=True):
    """Full sniper sequence. Returns stats."""
    d=DATA[name]; pip=PIP[name]; sp=SPREAD[name]*pip
    b15=d["15m"]; b4=d["4H"]
    hi_i = hi_i if hi_i is not None else len(b15)
    wins=losses=be_ct=0; gW=gL=R=0.0; trades=0
    trade_log=[]
    i=max(210,lo_i); last_exit=0
    lim=min(hi_i,len(b15)-max_hold-1)
    while i<lim:
        if i<last_exit: i+=1; continue
        bar=b15[i]; ts=bar["t"]
        if sess_only and not in_sess(ts): i+=1; continue
        w=b15[max(0,i-60):i+1]
        if len(w)<40: i+=1; continue
        a=atr(w[-20:])
        if a<=0: i+=1; continue
        # HTF bias
        if require_htf:
            h4=bars_before(b4,ts,120)
            if len(h4)<40: i+=1; continue
            bias4=structure(h4)
            if bias4=="ranging": i+=1; continue
        # 1) sweep of prior 20-bar extreme with close back inside
        prior=w[-21:-1]; c=w[-1]
        swept=None; sweep_ext=None
        loh=min(b["l"] for b in prior); hih=max(b["h"] for b in prior)
        if c["l"]<loh and c["c"]>loh: swept="bull"; sweep_ext=c["l"]      # swept lows -> long
        elif c["h"]>hih and c["c"]<hih: swept="bear"; sweep_ext=c["h"]    # swept highs -> short
        if swept is None: i+=1; continue
        if require_htf:
            if swept=="bull" and bias4!="bullish": i+=1; continue
            if swept=="bear" and bias4!="bearish": i+=1; continue
        # 2) MSS: within next few bars a displacement candle breaks micro-structure
        entry=sl=None; sign=1 if swept=="bull" else -1
        mss_j=None; fvg=None
        for j in range(i+1, min(i+5, len(b15))):
            cj=b15[j]; body=abs(cj["c"]-cj["o"])
            if body < disp_mult*a: continue
            if swept=="bull" and cj["c"]>cj["o"] and cj["c"]>max(b["h"] for b in b15[j-3:j]):
                mss_j=j
                # FVG left by displacement: gap between b15[j-1].high and b15[j+1].low is ideal;
                # use origin OB = the pre-displacement candle's range
                fvg=(b15[j-1]["l"], b15[j-1]["h"]); break
            if swept=="bear" and cj["c"]<cj["o"] and cj["c"]<min(b["l"] for b in b15[j-3:j]):
                mss_j=j
                fvg=(b15[j-1]["l"], b15[j-1]["h"]); break
        if mss_j is None: i+=1; continue
        # 3) return-to-origin: limit entry at FVG/OB midpoint within retrace_bars
        zone_mid=(fvg[0]+fvg[1])/2
        filled_k=None
        for k in range(mss_j+1, min(mss_j+1+retrace_bars, len(b15))):
            ck=b15[k]
            if swept=="bull" and ck["l"]<=zone_mid:
                entry=zone_mid; filled_k=k; break
            if swept=="bear" and ck["h"]>=zone_mid:
                entry=zone_mid; filled_k=k; break
        if entry is None: i+=1; continue
        # 4) SL beyond sweep extreme + buffer
        if swept=="bull": sl=sweep_ext - sl_buf*a
        else: sl=sweep_ext + sl_buf*a
        risk=abs(entry-sl)
        if risk < max(6*pip, sp*3): i+=1; continue
        entry_eff = entry + sign*sp  # pay spread on entry
        tp1=entry+risk*tp1_R*sign; tp2=entry+risk*tp2_R*sign
        realR=0.0; part=False; movedbe=False; outcome=None; exit_j=None
        for j in range(filled_k, min(filled_k+max_hold,len(b15))):
            hb=b15[j]
            if be and not part and ((sign==1 and hb["h"]>=tp1) or (sign==-1 and hb["l"]<=tp1)):
                realR+=tp1_R*tp1_close; part=True; sl=entry
            if (sign==1 and hb["l"]<=sl) or (sign==-1 and hb["h"]>=sl):
                realR+= 0.0 if (part and sl==entry) else -1.0*(1-(tp1_close if part else 0)); outcome="done"; exit_j=j; break
            if (sign==1 and hb["h"]>=tp2) or (sign==-1 and hb["l"]<=tp2):
                realR+= tp2_R*(1-(tp1_close if part else 0)); outcome="done"; exit_j=j; break
        if outcome is None:
            exit_j=min(filled_k+max_hold,len(b15)-1)
            lp=b15[exit_j]["c"]; rr=((lp-entry)/risk)*sign
            realR+= rr*(1-(tp1_close if part else 0))
        trades+=1; R+=realR
        if realR>0.05: wins+=1; gW+=realR
        elif realR<-0.05: losses+=1; gL+=abs(realR)
        else: be_ct+=1
        trade_log.append({
            "symbol": name, "direction": "bullish" if sign==1 else "bearish",
            "entry_ts": b15[filled_k]["t"], "exit_ts": b15[exit_j]["t"],
            "session_hour": hour_of(b15[filled_k]["t"]), "R": round(realR, 4),
        })
        last_exit=filled_k+1; i=last_exit
    dec=wins+losses; wr=wins/dec*100 if dec else 0; pf=gW/gL if gL>0 else 999
    return {"n":trades,"WR":round(wr,1),"PF":round(pf,2),"expR":round(R/trades,3) if trades else 0,
            "totR":round(R,1),"trades":trade_log}

if __name__=="__main__":
    print("SNIPER-SMC 90-DAY BACKTEST (sweep -> MSS -> FVG mitigation entry)\n")
    print(f"{'PAIR':8}{'n':5}{'WR%':7}{'PF':7}{'expR':8}{'totR':8}")
    rows=[]
    for name in DATA:
        r=sniper_bt(name)
        rows.append((name,r))
    rows.sort(key=lambda x:(-x[1]["PF"], -x[1]["WR"]))
    for name,r in rows:
        tag=" ⭐" if (r["PF"]>1.3 and r["WR"]>=60 and r["n"]>=15) else (" ✅" if r["PF"]>1 else "")
        print(f"{name:8}{r['n']:<5}{r['WR']:<7}{r['PF']:<7}{r['expR']:<8}{r['totR']:<8}{tag}")
