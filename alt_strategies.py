"""
Structurally different hypotheses, tested honestly on IN-SAMPLE 2025 only.

Motivation: at M15 the round-trip cost is ~14% of the stop, and the sweep
signal shows no edge even at zero cost. Both problems ease on a higher
timeframe, where stops are wider relative to fixed costs and where
trend-persistence is the better-documented effect.

Families tested:
  A) Donchian breakout (trend following) on H1 and H4
  B) Pullback continuation to EMA in an established H4 trend
  C) Bollinger mean-reversion at range extremes

Each is deliberately simple -- few parameters, so there is little to overfit.
"""
import itertools
import numpy as np, pandas as pd
import tl_data, strategy as st

IS_S=pd.Timestamp("2025-03-01",tz="UTC"); IS_E=pd.Timestamp("2025-12-31 23:59",tz="UTC")
OOS_S=pd.Timestamp("2026-01-01",tz="UTC")

def frame(sym, rule):
    m15=tl_data.load(sym)
    return st.resample(m15, rule)

def simulate(sym, df, entries, atr_s, sl_mult, tp_mult, tstop):
    """entries: array of +1/-1/0 per bar. Fill at next open, ATR stop/target."""
    o,h,l,c = (df[k].values for k in ("open","high","low","close"))
    pip=st.PIP[sym]; spread=st.SPREAD_PIPS[sym]*pip
    cost_px = spread + st.SLIPPAGE_PIPS*pip
    n=len(df); out=[]; i=0
    while i < n-1:
        d=entries[i]
        if d==0 or not np.isfinite(atr_s[i]) or atr_s[i]<=0:
            i+=1; continue
        j=i+1
        entry=o[j]+d*(spread/2+st.SLIPPAGE_PIPS*pip)
        risk=sl_mult*atr_s[i]
        stop=entry-d*risk
        tgt=entry+d*tp_mult*risk
        r=None
        for k in range(j,min(n,j+tstop+1)):
            if (d>0 and l[k]<=stop) or (d<0 and h[k]>=stop):
                r=-1.0 - (st.STOP_SLIPPAGE_PIPS*pip)/risk; break
            if (d>0 and h[k]>=tgt) or (d<0 and l[k]<=tgt):
                r=tp_mult; break
        else:
            k=min(n-1,j+tstop); r=((c[k]-entry)*d)/risk
        # commission in R (approx, standard lot)
        pv = st.CONTRACT[sym]*pip if st.QUOTE[sym]=="USD" else st.CONTRACT[sym]*pip/entry
        r -= st.COMMISSION_PER_LOT/((risk/pip)*pv)
        out.append(r)
        i=k+1
    return np.array(out)

def stats(r):
    if len(r)==0: return None
    gp,gl=r[r>0].sum(), -r[r<=0].sum()
    return dict(n=len(r),wr=100*(r>0).mean(),pf=gp/gl if gl>0 else 99.0,exp=r.mean(),tot=r.sum())

def agg(res):
    if not res: return None
    r=np.concatenate(res); return stats(r)

RULES={"1h":"1h","4h":"4h"}
results=[]

for rule in ("1h","4h"):
    frames={s:frame(s,rule) for s in tl_data.SYMBOLS}
    for sym,df in frames.items():
        df["atr"]=st.atr(df,14)
    # ---- A) Donchian breakout ----
    for look,sl,tp,tstop in itertools.product((20,40,55),(1.5,2.0),(1.5,2.0,3.0),(40,)):
        res=[]
        for sym,df in frames.items():
            hh=df["high"].rolling(look).max().shift(1)
            ll=df["low"].rolling(look).min().shift(1)
            e=np.where(df["close"]>hh,1,np.where(df["close"]<ll,-1,0))
            e[:look+20]=0
            m=(df.index>=IS_S)&(df.index<=IS_E); e=np.where(m,e,0)
            res.append(simulate(sym,df,e,df["atr"].values,sl,tp,tstop))
        k=agg(res)
        if k and k["n"]>=100: results.append(dict(fam="donchian",tf=rule,look=look,sl=sl,tp=tp,**k))

    # ---- B) Pullback continuation ----
    for ef,es,sl,tp in itertools.product((20,),(50,),(1.5,2.0),(1.5,2.0,3.0)):
        res=[]
        for sym,df in frames.items():
            f=st.ema(df["close"],ef); s_=st.ema(df["close"],es)
            up=(f>s_)&(df["close"]>s_); dn=(f<s_)&(df["close"]<s_)
            touch_up=up&(df["low"]<=f)&(df["close"]>f)
            touch_dn=dn&(df["high"]>=f)&(df["close"]<f)
            e=np.where(touch_up,1,np.where(touch_dn,-1,0))
            e[:es+20]=0
            m=(df.index>=IS_S)&(df.index<=IS_E); e=np.where(m,e,0)
            res.append(simulate(sym,df,e,df["atr"].values,sl,tp,40))
        k=agg(res)
        if k and k["n"]>=100: results.append(dict(fam="pullback",tf=rule,look=ef,sl=sl,tp=tp,**k))

    # ---- C) Bollinger mean reversion ----
    for look,nsd,sl,tp in itertools.product((20,40),(2.0,2.5),(1.5,2.0),(1.0,1.5)):
        res=[]
        for sym,df in frames.items():
            ma=df["close"].rolling(look).mean(); sd=df["close"].rolling(look).std()
            lo_b=ma-nsd*sd; hi_b=ma+nsd*sd
            e=np.where((df["close"]<lo_b)&(df["close"]>df["close"].shift(1)),1,
               np.where((df["close"]>hi_b)&(df["close"]<df["close"].shift(1)),-1,0))
            e[:look+20]=0
            m=(df.index>=IS_S)&(df.index<=IS_E); e=np.where(m,e,0)
            res.append(simulate(sym,df,e,df["atr"].values,sl,tp,40))
        k=agg(res)
        if k and k["n"]>=100: results.append(dict(fam="bollinger",tf=rule,look=look,sl=sl,tp=tp,nsd=nsd,**k))

df=pd.DataFrame(results).sort_values("pf",ascending=False)
pd.set_option("display.width",200)
print("=== ALTERNATIVE FAMILIES, IN-SAMPLE 2025 (all pairs pooled) ===")
print(df.head(20).round(3).to_string(index=False))
print(f"\nconfigs with PF>1.10: {(df.pf>1.10).sum()} / {len(df)}")
print(f"configs with PF>1.00: {(df.pf>1.00).sum()} / {len(df)}")
df.to_csv("alt_strategies_insample.csv",index=False)
