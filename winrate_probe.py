"""
Direct test of the brief's headline requirement:
  can this setup produce a 60-90% win rate AND a profit factor above 1?

Sweeps the target down into the range where high win rates live, and reports
win rate and profit factor TOGETHER. In-sample 2025 only.
"""
import itertools, os
from multiprocessing import Pool
import numpy as np, pandas as pd
import tl_data, strategy as st, signal_sim as ss

IS_START=pd.Timestamp("2025-03-01",tz="UTC"); IS_END=pd.Timestamp("2025-12-31 23:59",tz="UTC")
FRAMES=None
def init():
    global FRAMES; FRAMES={s: tl_data.load(s) for s in tl_data.SYMBOLS}

def one(c):
    p=st.default_params()
    for k,v in c.items(): setattr(p,k,v)
    p.min_score=0
    p.min_rr_after_costs = min(p.min_rr_after_costs, p.tp_r*0.6)   # don't self-veto
    rows=[]
    for s in tl_data.SYMBOLS:
        rows += ss.simulate_symbol(s, FRAMES[s], p, IS_START, IS_END)
    if len(rows)<40: return None
    r=np.array([x["r"] for x in rows]); sc=np.array([x["score"] for x in rows])
    out=[]
    for thr in (0,60,65,70,75):
        m=sc>=thr; rr=r[m]
        if len(rr)<40: continue
        gp=rr[rr>0].sum(); gl=-rr[rr<=0].sum()
        out.append({**c,"min_score":thr,"n":len(rr),
                    "wr":float((rr>0).mean()*100),
                    "pf":float(gp/gl) if gl>0 else 99.0,
                    "exp":float(rr.mean())})
    return out

GRID=dict(tp_r=[0.6,0.8,1.0,1.25,1.5,2.0,2.5],
          tp1_frac=[0.0],
          breakeven_after_tp1=[False],
          sl_atr_buffer=[0.5,0.8,1.1],
          retr_frac=[0.5,0.62])

if __name__=="__main__":
    keys=list(GRID); combos=[dict(zip(keys,v)) for v in itertools.product(*[GRID[k] for k in keys])]
    res=[]
    with Pool(min(os.cpu_count() or 4,8), initializer=init) as pool:
        for r in pool.imap_unordered(one, combos, chunksize=2):
            if r: res+=r
    df=pd.DataFrame(res); df.to_csv("winrate_probe.csv",index=False)
    pd.set_option("display.width",200)
    print("=== configs achieving WR >= 60% ===")
    hi=df[df.wr>=60].sort_values("pf",ascending=False)
    print(hi.to_string(index=False) if len(hi) else "  NONE")
    if len(hi):
        print(f"\n  of those, PF > 1.0: {(hi.pf>1).sum()} / {len(hi)}")
        print(f"  best PF among WR>=60%: {hi.pf.max():.3f}")
    print("\n=== win rate vs profit factor by target size (min_score=70) ===")
    t=df[df.min_score==70].groupby("tp_r").agg(n=("n","mean"),wr=("wr","mean"),pf=("pf","mean"),exp=("exp","mean"))
    print(t.round(3).to_string())
