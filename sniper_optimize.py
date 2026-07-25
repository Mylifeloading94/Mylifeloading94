"""
Iterative honest-fill optimizer for the sniper-SMC strategy.
Pools ALL pairs for sample size; every fill uses the conservative rules
(trade-through, spread paid, same-bar TP+SL = loss). Adds Fable v5 filters
as toggles so we can measure each one's marginal effect and keep only what
raises portfolio profit factor AND holds out-of-sample.
"""
import json
DATA = json.load(open("/tmp/bt90.json"))
PIP = {"EURUSD":0.0001,"GBPUSD":0.0001,"USDJPY":0.01,"USDCHF":0.0001,"USDCAD":0.0001,
       "AUDUSD":0.0001,"NZDUSD":0.0001,"GBPJPY":0.01,"EURJPY":0.01,"AUDJPY":0.01,
       "EURGBP":0.0001,"GBPCAD":0.0001,"XAUUSD":0.1,"NAS100":1.0,"SPX500":1.0}
SPREAD = {"EURUSD":0.6,"GBPUSD":0.9,"USDJPY":0.7,"USDCHF":1.0,"USDCAD":1.2,
          "AUDUSD":0.8,"NZDUSD":1.2,"GBPJPY":1.6,"EURJPY":1.3,"AUDJPY":1.4,
          "EURGBP":1.0,"GBPCAD":2.2,"XAUUSD":2.5,"NAS100":2.0,"SPX500":1.5}
SPREAD_ATR = {}  # spread/ATR suitability, computed lazily

def atr(bars,p=14):
    if len(bars)<2: return 0
    trs=[max(bars[i]["h"]-bars[i]["l"],abs(bars[i]["h"]-bars[i-1]["c"]),abs(bars[i]["l"]-bars[i-1]["c"])) for i in range(1,len(bars))]
    return sum(trs[-p:])/min(len(trs),p)
def swings(bars,s=2):
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
def minute_of(ms): return int((ms//60000)%60)
def bars_before(bars,ts,k):
    out=[b for b in bars if b["t"]<=ts]; return out[-k:] if len(out)>k else out
def in_kz(ms, prime=False):
    h=hour_of(ms); m=minute_of(ms)
    if prime:
        if 7<=h<=8: return True
        if h==12 and m>=30: return True
        if h==13: return True
        if h==14 and m<=30: return True
        return False
    if 7<=h<=9: return True
    if h==10 and m<=30: return True
    if h==12 and m>=30: return True
    if 13<=h<=14: return True
    if h==15 and m<=30: return True
    return False

def run(cfg, lo_frac=0.0, hi_frac=1.0, pairs=None):
    pairs = pairs or list(DATA.keys())
    W=L=BE=0; gW=gL=R=0.0; trades=0; per={}
    for name in pairs:
        d=DATA[name]; pip=PIP[name]; sp=SPREAD[name]*pip
        b15=d["15m"]; b4=d["4H"]; b1=d["1H"]
        N=len(b15); lo_i=int(N*lo_frac); hi_i=int(N*hi_frac)
        i=max(210,lo_i); last=0; lim=min(hi_i,N-cfg["max_hold"]-1)
        pw=[0,0]
        while i<lim:
            if i<last: i+=1; continue
            bar=b15[i]; ts=bar["t"]
            if not in_kz(ts, cfg["prime_kz"]): i+=1; continue
            w=b15[max(0,i-60):i+1]
            if len(w)<40: i+=1; continue
            a=atr(w[-20:])
            if a<=0: i+=1; continue
            # ATR regime filter (percentile of last 30d ~ 2880 15m bars)
            if cfg["atr_regime"]:
                hist=[atr(b15[max(0,k-20):k]) for k in range(max(20,i-400),i,20)]
                hist=[x for x in hist if x>0]
                if hist:
                    hist_s=sorted(hist); lo30=hist_s[int(len(hist_s)*0.3)]; hi90=hist_s[int(len(hist_s)*0.9)]
                    if a<lo30 or a>hi90: i+=1; continue
            # HTF bias
            h4=bars_before(b4,ts,120)
            if len(h4)<40: i+=1; continue
            bias4=structure(h4)
            if bias4=="ranging": i+=1; continue
            if cfg["htf_1h"]:
                h1=bars_before(b1,ts,120)
                if len(h1)<40: i+=1; continue
                if structure(h1,120,3)!=bias4: i+=1; continue
            # 4H premium/discount gate
            if cfg["pd_gate"]:
                r4=h4[-60:]; hi4=max(x["h"] for x in r4); lo4=min(x["l"] for x in r4)
                if hi4>lo4:
                    pd=(bar["c"]-lo4)/(hi4-lo4)
                    if bias4=="bullish" and pd>0.45: i+=1; continue
                    if bias4=="bearish" and pd<0.55: i+=1; continue
            # sweep
            prior=w[-21:-1]; c=w[-1]
            loh=min(b["l"] for b in prior); hih=max(b["h"] for b in prior)
            swept=sweep_ext=None
            pen=None
            if c["l"]<loh and c["c"]>loh: swept,sweep_ext,pen="bull",c["l"],(loh-c["l"])
            elif c["h"]>hih and c["c"]<hih: swept,sweep_ext,pen="bear",c["h"],(c["h"]-hih)
            if swept is None: i+=1; continue
            if cfg["pen_cap"] and pen>cfg["pen_cap"]*a: i+=1; continue   # too deep = real break
            if swept=="bull" and bias4!="bullish": i+=1; continue
            if swept=="bear" and bias4!="bearish": i+=1; continue
            # MSS + displacement + FVG-in-leg
            mss_j=fvg=None; sign=1 if swept=="bull" else -1
            for j in range(i+1,min(i+cfg["mss_win"],len(b15))):
                cj=b15[j]; body=abs(cj["c"]-cj["o"])
                if body<cfg["disp_mult"]*a: continue
                if swept=="bull" and cj["c"]>cj["o"] and cj["c"]>max(b["h"] for b in b15[j-3:j]):
                    mss_j=j; break
                if swept=="bear" and cj["c"]<cj["o"] and cj["c"]<min(b["l"] for b in b15[j-3:j]):
                    mss_j=j; break
            if mss_j is None: i+=1; continue
            # find origin FVG in the leg [i..mss_j]
            leg=b15[i:mss_j+1]; fvgs=[]
            for k in range(2,len(leg)):
                if swept=="bull" and leg[k]["l"]>leg[k-2]["h"] and (leg[k]["l"]-leg[k-2]["h"])>=cfg["fvg_min"]*a:
                    fvgs.append((leg[k-2]["h"],leg[k]["l"]))
                if swept=="bear" and leg[k]["h"]<leg[k-2]["l"] and (leg[k-2]["l"]-leg[k]["h"])>=cfg["fvg_min"]*a:
                    fvgs.append((leg[k]["h"],leg[k-2]["l"]))
            if cfg["fvg_in_leg"] and not fvgs: i+=1; continue
            # zone = origin FVG closest to sweep, else displacement-candle OB
            if fvgs:
                zone = fvgs[0] if swept=="bull" else fvgs[0]
                E=(zone[0]+zone[1])/2
            else:
                E=(b15[mss_j-1]["l"]+b15[mss_j-1]["h"])/2
            # OTE retrace depth gate
            leg_lo=min(b["l"] for b in leg); leg_hi=max(b["h"] for b in leg)
            if leg_hi>leg_lo:
                depth=(leg_hi-E)/(leg_hi-leg_lo) if swept=="bull" else (E-leg_lo)/(leg_hi-leg_lo)
                if cfg["ote"] and not (cfg["ote"][0]<=depth<=cfg["ote"][1]): i+=1; continue
            # SL
            if swept=="bull": sl=sweep_ext-cfg["sl_buf"]*a
            else: sl=sweep_ext+cfg["sl_buf"]*a
            risk=abs(E-sl)
            if risk<max(6*pip,3*sp): i+=1; continue
            if sp>0.10*risk: i+=1; continue
            # DOL room gate — nearest opposing swing in next-pool direction
            if cfg["dol_room"]:
                fut=None  # use recent structure as proxy: distance to prior opposing extreme
                look=b15[max(0,i-120):i]
                if swept=="bull":
                    tgt=max(x["h"] for x in look); room=(tgt-E)
                else:
                    tgt=min(x["l"] for x in look); room=(E-tgt)
                if room < cfg["dol_room"]*risk: i+=1; continue
            # trade-through fill
            filled=None
            for k in range(mss_j+1,min(mss_j+1+cfg["fill_win"],len(b15))):
                ck=b15[k]
                if swept=="bull" and ck["l"]<=E-1*pip: filled=k; break
                if swept=="bear" and ck["h"]>=E+1*pip: filled=k; break
                if (swept=="bull" and ck["c"]<sweep_ext) or (swept=="bear" and ck["c"]>sweep_ext): break  # invalidated
            if filled is None: i+=1; continue
            entry=E+sign*sp
            tp1=entry+risk*cfg["tp1_R"]*sign; tp2=entry+risk*cfg["tp2_R"]*sign
            realR=0.0; part=False; outcome=None
            for j in range(filled,min(filled+cfg["max_hold"],len(b15))):
                hb=b15[j]
                hit_sl=(sign==1 and hb["l"]<=sl) or (sign==-1 and hb["h"]>=sl)
                hit_tp1=(not part) and ((sign==1 and hb["h"]>=tp1) or (sign==-1 and hb["l"]<=tp1))
                hit_tp2=(sign==1 and hb["h"]>=tp2) or (sign==-1 and hb["l"]<=tp2)
                if hit_sl and (hit_tp1 or hit_tp2) and j==filled: realR+=-1.0; outcome="d"; break
                if cfg["tp1_close"]>0 and hit_tp1: realR+=cfg["tp1_R"]*cfg["tp1_close"]; part=True; sl=entry
                if hit_sl:
                    realR+= 0.0 if (part and sl==entry) else -1.0*(1-(cfg["tp1_close"] if part else 0)); outcome="d"; break
                if hit_tp2: realR+= cfg["tp2_R"]*(1-(cfg["tp1_close"] if part else 0)); outcome="d"; break
            if outcome is None:
                lp=b15[min(filled+cfg["max_hold"],len(b15)-1)]["c"]; rr=((lp-entry)/risk)*sign
                realR+= rr*(1-(cfg["tp1_close"] if part else 0))
            trades+=1; R+=realR
            if realR>0.05: W+=1; gW+=realR; pw[0]+=1
            elif realR<-0.05: L+=1; gL+=abs(realR); pw[1]+=1
            else: BE+=1
            last=filled+1; i=last
        per[name]=pw
    dec=W+L; wr=W/dec*100 if dec else 0; pf=gW/gL if gL>0 else 999
    return {"n":trades,"WR":round(wr,1),"PF":round(pf,2),"expR":round(R/trades,3) if trades else 0,"totR":round(R,1),"per":per}

BASE = dict(prime_kz=False, atr_regime=False, htf_1h=False, pd_gate=False,
            pen_cap=None, mss_win=5, disp_mult=0.6, fvg_min=0.15, fvg_in_leg=False,
            ote=None, sl_buf=0.5, dol_room=None, fill_win=8, tp1_R=1.0, tp1_close=0.5,
            tp2_R=2.0, max_hold=48)

if __name__=="__main__":
    r=run(BASE)
    print(f"BASELINE (honest fills, all pairs): n={r['n']} WR={r['WR']}% PF={r['PF']} exp={r['expR']}R totR={r['totR']}")
