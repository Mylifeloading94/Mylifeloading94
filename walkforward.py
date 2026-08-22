"""
Walk-forward validation.

Rolling 3-month train windows select the best target size and pair watchlist;
the following 1 month is then traded with that choice, out of sample. This
tests whether ANY selection rule survives contact with the next period, rather
than whether one particular split happened to fail.

Reported for completeness -- nothing here is used to choose the shipped config.
"""
import numpy as np, pandas as pd
import tl_data, strategy as st, signal_sim as ss, config

frames={s:tl_data.load(s) for s in tl_data.SYMBOLS}
CTX_CACHE={}

def sim(sym,p,s,e):
    return ss.simulate_symbol(sym, frames[sym], p, s, e)

def pooled(rows):
    if not rows: return None
    r=np.array([x["r"] for x in rows])
    gp,gl=r[r>0].sum(),-r[r<=0].sum()
    return dict(n=len(r),wr=100*(r>0).mean(),pf=gp/gl if gl>0 else 99.0,exp=r.mean())

months=pd.date_range("2025-06-01","2026-08-01",freq="MS",tz="UTC")
rows=[]
for i in range(3,len(months)):
    tr_s,tr_e = months[i-3], months[i]-pd.Timedelta(seconds=1)
    te_s,te_e = months[i], (months[i]+pd.offsets.MonthBegin(1))-pd.Timedelta(seconds=1)
    if te_s > pd.Timestamp("2026-08-01",tz="UTC"): break

    # --- train: pick target size and watchlist ---
    best=None
    for tp in (0.6,1.0,1.5,2.0,2.5):
        p=config.locked_params(); p.tp_r=tp; p.min_rr_after_costs=min(0.30,tp*0.5)
        per={}
        allr=[]
        for s in tl_data.SYMBOLS:
            r=sim(s,p,tr_s,tr_e); per[s]=r; allr+=r
        k=pooled(allr)
        if k and k["n"]>=20 and (best is None or k["pf"]>best[1]["pf"]):
            best=(tp,k,per)
    if best is None:
        continue
    tp,k_tr,per=best
    wl=[s for s,r in per.items() if len(r)>=3 and pooled(r) and pooled(r)["pf"]>1.2]
    if not wl: wl=list(tl_data.SYMBOLS)

    # --- test: next month, frozen choice ---
    p=config.locked_params(); p.tp_r=tp; p.min_rr_after_costs=min(0.30,tp*0.5)
    ter=[]
    for s in wl: ter+=sim(s,p,te_s,te_e)
    k_te=pooled(ter)
    rows.append(dict(test_month=str(te_s.to_period("M")), tp_r=tp, n_wl=len(wl),
                     train_n=k_tr["n"], train_pf=k_tr["pf"], train_wr=k_tr["wr"],
                     test_n=k_te["n"] if k_te else 0,
                     test_pf=k_te["pf"] if k_te else float("nan"),
                     test_wr=k_te["wr"] if k_te else float("nan"),
                     test_exp=k_te["exp"] if k_te else float("nan")))

df=pd.DataFrame(rows)
pd.set_option("display.width",200)
print("=== WALK-FORWARD: train 3 months -> trade 1 month ===")
print(df.round(3).to_string(index=False))
v=df.dropna(subset=["test_pf"])
if len(v):
    tot_n=v.test_n.sum()
    print(f"\n  train PF (mean): {v.train_pf.mean():.3f}   test PF (mean): {v.test_pf.mean():.3f}")
    print(f"  months where test PF > 1: {(v.test_pf>1).sum()} / {len(v)}")
    print(f"  total out-of-sample trades: {int(tot_n)}")
    print(f"  mean out-of-sample expectancy: {v.test_exp.mean():+.4f}R")
    if v.train_pf.std()>0 and v.test_pf.std()>0:
        print(f"  correlation train PF vs test PF: {np.corrcoef(v.train_pf,v.test_pf)[0,1]:+.3f}")
df.to_csv("walkforward.csv",index=False)
