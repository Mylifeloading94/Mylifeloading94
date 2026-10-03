import itertools, json
from multiprocessing import Pool
import numpy as np, pandas as pd
import xau_engine as E, smc, smc_exec as X
TR=pd.Timestamp("2023-01-01",tz="UTC"); VA=pd.Timestamp("2025-01-01",tz="UTC")
_M1=None; _B={}
def init():
    global _M1; _M1=E.load_m1()
def job(a):
    rule,tfm,liq,entry,bias=a
    b=_B.setdefault(rule,E.to_tf(_M1,rule)); sg=smc.generate(b,tfm,liq=liq,entry=entry,bias=bias); out=[]
    for rr in (1,2,3):
        t=X.run_orders(_M1,b,tfm,sg,rr,market=True)
        s=lambda x:E.stats(x)
        out.append(dict(tf=rule,liq=liq,entry=entry,bias=bias,rr=rr,n=len(t),tr=s(t[t.entry_time<TR]),va=s(t[(t.entry_time>=TR)&(t.entry_time<VA)]),te=s(t[t.entry_time>=VA]),al=s(t)))
    return out
if __name__=="__main__":
    combos=[(c[0][0],c[0][1],c[1],c[2],c[3]) for c in itertools.product((("5min",5),("15min",15)),("session","swing"),("mid","edge"),(False,True))]
    # entry type only changes the LIMIT level, which market entry ignores -> dedupe on (tf, liq, bias)
    combos=[c for c in combos if c[3]=="mid"]
    allr=[]
    with Pool(4,initializer=init) as p:
        for r in p.imap_unordered(job,combos): allr+=r
    json.dump(allr,open("results/smc_market_diag.json","w"),indent=1,default=float)
    f=lambda s:f"n={s['n']:4d} WR {s['wr']:4.1f} PF {s['pf']:4.2f} R {s['tot_r']:+6.1f}"
    print(f"MARKET-entry SMC (same signals, structural stop, no limit): {len(allr)} configs")
    print(f"{'config':32s} | {'train':^26s} | {'valid':^26s}")
    for r in sorted(allr,key=lambda r:-r['tr']['pf']):
        print(f"{r['tf']:5s} {r['liq']:7s} bias={'Y' if r['bias'] else 'N'} rr{r['rr']}".ljust(32)+f" | {f(r['tr']):26s} | {f(r['va']):26s}")
    print("\nmedian PF  train %.2f  valid %.2f  | qualifiers (PF>1.05 both): %d"%(np.median([r['tr']['pf'] for r in allr]),np.median([r['va']['pf'] for r in allr]),sum(1 for r in allr if r['tr']['pf']>1.05 and r['va']['pf']>1.05)))
