"""
Win-rate backtest harness for the SMC agent.
Walks 15M bars, reconstructs multi-TF context as-of each bar (no lookahead),
applies an entry rule config, simulates the trade forward bar-by-bar,
and reports win rate / profit factor / expectancy.

Tests multiple EXIT structures to find the one that hits 70%+ win rate.
"""
import json, math

DATA = json.load(open("/tmp/backtest_data.json"))

PIP = {"EURUSD":0.0001,"GBPUSD":0.0001,"USDJPY":0.01,"USDCHF":0.0001,"USDCAD":0.0001,
       "AUDUSD":0.0001,"NZDUSD":0.0001,"AUDJPY":0.01,"EURJPY":0.01,"XAUUSD":0.1}

# ── Indicators (self-contained, no lookahead) ─────────────────────────────────
def atr(bars, p=14):
    if len(bars) < 2: return 0
    trs=[max(bars[i]["h"]-bars[i]["l"],abs(bars[i]["h"]-bars[i-1]["c"]),abs(bars[i]["l"]-bars[i-1]["c"])) for i in range(1,len(bars))]
    return sum(trs[-p:])/min(len(trs),p)

def ema(vals,p):
    if not vals: return 0
    k=2/(p+1); e=vals[0]
    for v in vals[1:]: e=v*k+e*(1-k)
    return e

def swings(bars, s=3):
    out=[]
    for i in range(s,len(bars)-s):
        hi=bars[i]["h"]; lo=bars[i]["l"]
        if all(bars[j]["h"]<hi for j in range(i-s,i)) and all(bars[j]["h"]<hi for j in range(i+1,i+s+1)):
            out.append(("high",hi,i))
        if all(bars[j]["l"]>lo for j in range(i-s,i)) and all(bars[j]["l"]>lo for j in range(i+1,i+s+1)):
            out.append(("low",lo,i))
    return sorted(out,key=lambda x:x[2])

def structure(bars, lb=80, s=3):
    r=bars[-lb:] if len(bars)>=lb else bars
    sw=swings(r,s)
    hs=[x for x in sw if x[0]=="high"]; ls=[x for x in sw if x[0]=="low"]
    if len(hs)>=2 and len(ls)>=2:
        hh=hs[-1][1]>hs[-2][1]; hl=ls[-1][1]>ls[-2][1]
        lh=hs[-1][1]<hs[-2][1]; ll=ls[-1][1]<ls[-2][1]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
        if hh or hl: return "bullish"
        if lh or ll: return "bearish"
    return "ranging"

def find_fvg(bars,d,lb=30):
    r=bars[-lb:] if len(bars)>=lb else bars
    for i in range(2,len(r)):
        if d=="bullish" and r[i]["l"]>r[i-2]["h"]: return True
        if d=="bearish" and r[i]["h"]<r[i-2]["l"]: return True
    return False

def liq_sweep(bars,d,lb=30):
    r=bars[-lb:] if len(bars)>=lb else bars
    for i in range(5,len(r)):
        w=r[max(0,i-8):i]
        if d=="bullish":
            lo=min(b["l"] for b in w)
            if r[i]["l"]<lo and r[i]["c"]>lo: return True
        else:
            hi=max(b["h"] for b in w)
            if r[i]["h"]>hi and r[i]["c"]<hi: return True
    return False

def find_ob(bars,d,lb=50):
    r=bars[-lb:] if len(bars)>=lb else bars; n=len(r)
    for i in range(n-5,1,-1):
        if d=="bullish" and r[i]["c"]<r[i]["o"]:
            if sum(1 for j in range(1,4) if i+j<n and r[i+j]["c"]>r[i+j]["o"])>=2:
                ob={"h":r[i]["o"],"l":r[i]["c"]}
                if any(r[j]["c"]<ob["l"] for j in range(i+1,n)): continue
                return ob
        if d=="bearish" and r[i]["c"]>r[i]["o"]:
            if sum(1 for j in range(1,4) if i+j<n and r[i+j]["c"]<r[i+j]["o"])>=2:
                ob={"h":r[i]["c"],"l":r[i]["o"]}
                if any(r[j]["c"]>ob["h"] for j in range(i+1,n)): continue
                return ob
    return None

def hour_of(ms): return int((ms//3600000)%24)

# ── Align higher-TF context as-of a 15M timestamp (no lookahead) ──────────────
def bars_before(bars, ts, k):
    # bars with timestamp <= ts (closed), last k
    out=[b for b in bars if b["t"]<=ts]
    return out[-k:] if len(out)>k else out

# ── Backtest one config ───────────────────────────────────────────────────────
def backtest(cfg):
    """
    cfg keys:
      min_conf:   minimum confluence count required (0-6)
      loc_buy:    max 15M range pos for buys (e.g. 0.40)
      loc_sell:   min 15M range pos for sells (e.g. 0.60)
      max_ext:    max ATR-distance from 15M EMA20 (e.g. 2.0)
      need_confirm: require confirmation candle (bool)
      sessions:   set of allowed UTC hours (or None = all)
      tp1_R, tp2_R: R multiples for targets
      be_at_R:    move SL to breakeven after this R reached (0 = off)
      partial_at_tp1: fraction closed at TP1 (0-1); rest runs to TP2
      sl_atr_mult: SL = entry -/+ this * ATR(15M), floored at swing
      max_hold:   max 15M bars to hold before timeout-close at market
    """
    wins=0; losses=0; be=0; R_sum=0.0; trades=0
    gross_win=0.0; gross_loss=0.0
    per_pair={}
    for name, d in DATA.items():
        pip=PIP[name]
        b15=d["15m"]; b1=d["1H"]; b4=d["4H"]
        i=210
        last_exit_idx=0
        while i < len(b15)-cfg["max_hold"]-1:
            if i < last_exit_idx:  # no overlapping trades on same pair
                i+=1; continue
            bar=b15[i]; ts=bar["t"]
            # session filter
            if cfg["sessions"] is not None and hour_of(ts) not in cfg["sessions"]:
                i+=1; continue
            # higher-TF context as-of now
            h1=bars_before(b1, ts, 80); h4=bars_before(b4, ts, 80)
            if len(h1)<60 or len(h4)<40: i+=1; continue
            d4=structure(h4,80,3); d1=structure(h1,60,2)
            if d4=="ranging" or d1=="ranging" or d4!=d1: i+=1; continue
            bias=d4
            w15=b15[max(0,i-49):i+1]  # last 50 incl current
            price=bar["c"]
            a15=atr(w15[-30:],14)
            if a15<=0: i+=1; continue
            r40=w15[-40:]; hi=max(b["h"] for b in r40); lo=min(b["l"] for b in r40)
            if hi<=lo: i+=1; continue
            pos=(price-lo)/(hi-lo)
            # location
            if bias=="bullish" and pos>cfg["loc_buy"]: i+=1; continue
            if bias=="bearish" and pos<cfg["loc_sell"]: i+=1; continue
            # extension
            e20=ema([b["c"] for b in w15],20)
            if abs(price-e20)>cfg["max_ext"]*a15: i+=1; continue
            # confirmation candle
            last=w15[-1]; body=abs(last["c"]-last["o"]) or (hi-lo)*1e-4
            if bias=="bullish":
                wick=min(last["o"],last["c"])-last["l"]
                confirmed = last["c"]>last["o"] and wick>=body*0.5
            else:
                wick=last["h"]-max(last["o"],last["c"])
                confirmed = last["c"]<last["o"] and wick>=body*0.5
            if cfg["need_confirm"] and not confirmed: i+=1; continue
            # confluence count
            conf=0
            if find_fvg(w15,bias): conf+=1
            if liq_sweep(w15,bias): conf+=1
            ob=find_ob(h1,bias)
            if ob and ob["l"]<=price<=ob["h"]: conf+=1
            if find_fvg(h1,bias): conf+=1
            # 1H liquidity sweep
            if liq_sweep(h1,bias): conf+=1
            # momentum (2 closes)
            if bias=="bullish" and all(b["c"]>b["o"] for b in w15[-2:]): conf+=1
            if bias=="bearish" and all(b["c"]<b["o"] for b in w15[-2:]): conf+=1
            if conf < cfg["min_conf"]: i+=1; continue

            # ── Entry ──
            entry=price
            sl_atr = a15*cfg["sl_atr_mult"]
            if bias=="bullish":
                swing=min(b["l"] for b in w15[-10:])
                sl=min(swing-2*pip, entry-sl_atr)
                sign=1
            else:
                swing=max(b["h"] for b in w15[-10:])
                sl=max(swing+2*pip, entry+sl_atr)
                sign=-1
            risk=abs(entry-sl)
            if risk<=0: i+=1; continue
            tp1=entry+risk*cfg["tp1_R"]*sign
            tp2=entry+risk*cfg["tp2_R"]*sign
            be_price=entry
            moved_be=False; part_done=False; realizedR=0.0
            outcome=None
            # ── Simulate forward ──
            for j in range(i+1, min(i+1+cfg["max_hold"], len(b15))):
                hb=b15[j]
                # breakeven trigger
                if cfg["be_at_R"]>0 and not moved_be:
                    if sign==1 and hb["h"]>=entry+risk*cfg["be_at_R"]:
                        sl=be_price; moved_be=True
                    if sign==-1 and hb["l"]<=entry-risk*cfg["be_at_R"]:
                        sl=be_price; moved_be=True
                # partial at TP1
                if cfg["partial_at_tp1"]>0 and not part_done:
                    if (sign==1 and hb["h"]>=tp1) or (sign==-1 and hb["l"]<=tp1):
                        realizedR += cfg["tp1_R"]*cfg["partial_at_tp1"]
                        part_done=True
                        if not moved_be: sl=be_price; moved_be=True  # BE after partial
                # SL hit
                if (sign==1 and hb["l"]<=sl) or (sign==-1 and hb["h"]>=sl):
                    if moved_be and sl==be_price:
                        realizedR += 0.0*(1-cfg["partial_at_tp1"])  # rest at BE
                        outcome="be" if realizedR<=0.01 else "win_partial"
                    else:
                        realizedR += -1.0*(1-(cfg["partial_at_tp1"] if part_done else 0))
                        outcome="loss"
                    break
                # TP2 (full runner) hit
                if (sign==1 and hb["h"]>=tp2) or (sign==-1 and hb["l"]<=tp2):
                    realizedR += cfg["tp2_R"]*(1-(cfg["partial_at_tp1"] if part_done else 0))
                    outcome="win"
                    break
            if outcome is None:
                # timeout close at last price
                lastp=b15[min(i+cfg["max_hold"], len(b15)-1)]["c"]
                rr=((lastp-entry)/risk)*sign
                realizedR += rr*(1-(cfg["partial_at_tp1"] if part_done else 0))
                outcome="win" if realizedR>0 else ("be" if abs(realizedR)<0.05 else "loss")
            trades+=1
            R_sum+=realizedR
            pp=per_pair.setdefault(name,[0,0,0.0])
            if realizedR>0.05: wins+=1; gross_win+=realizedR; pp[0]+=1
            elif realizedR<-0.05: losses+=1; gross_loss+=abs(realizedR); pp[1]+=1
            else: be+=1
            pp[2]+=realizedR
            last_exit_idx=j if outcome else i+cfg["max_hold"]
            i=last_exit_idx+1
    decided = wins+losses
    wr = wins/decided*100 if decided else 0
    pf = gross_win/gross_loss if gross_loss>0 else 999
    exp = R_sum/trades if trades else 0
    return {"trades":trades,"wins":wins,"losses":losses,"be":be,"win_rate":round(wr,1),
            "profit_factor":round(pf,2),"expectancy_R":round(exp,3),"total_R":round(R_sum,1),
            "per_pair":per_pair}

if __name__=="__main__":
    # Baseline = current strategy
    base = {"min_conf":0,"loc_buy":0.40,"loc_sell":0.60,"max_ext":2.0,"need_confirm":True,
            "sessions":None,"tp1_R":1.5,"tp2_R":2.5,"be_at_R":0,"partial_at_tp1":0,
            "sl_atr_mult":1.2,"max_hold":48}
    r=backtest(base)
    print("BASELINE (current: TP 1:2.5 full, confirm, 15M gate, all sessions):")
    print(f"  trades={r['trades']} win_rate={r['win_rate']}% PF={r['profit_factor']} exp={r['expectancy_R']}R totalR={r['total_R']}")
