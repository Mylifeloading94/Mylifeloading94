"""Walk-forward + Monte Carlo + final holdout. Holdout opened exactly ONCE."""
import sys, json; sys.path.insert(0,'.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute, render, breakdown
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, HOLDOUT, slice_df
from xauusd_bot.optimization.walk_forward import run_walk_forward, stability
from xauusd_bot.optimization.monte_carlo import simulate
from xauusd_bot.optimization.sensitivity import sweep, robustness
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self,F): self.F=F; self.m1=None

F=pd.read_pickle('data_cache/F_2026.pkl')
news=NewsFilter.load(Config().news)
MICRO={'instrument.min_lot':0.001,'instrument.lot_step':0.001}
CHOSEN={**MICRO,'score.threshold':80.0,'exits.tp2_r':2.5,'exits.trail_atr_mult':1.0,
        'toggles.breakout':False,'sessions.enabled_sessions':("OVERLAP","NEWYORK")}
base=Config().with_overrides(**MICRO); base.initial_equity=500.0
pd.set_option('display.width',220)

print("="*78); print("WALK-FORWARD (rolling 75d train / 25d test, re-optimised each window)")
print("="*78)
grid=[{'score.threshold':t,'toggles.breakout':b,'sessions.enabled_sessions':s}
      for t in (75.0,80.0) for b in (True,False)
      for s in (("LONDON","OVERLAP","NEWYORK"),("OVERLAP","NEWYORK"))]
wf=run_walk_forward(F,base,grid,news,train_days=75,test_days=25,equity0=500.0)
wf.to_csv('xauusd_bot/reports/walk_forward.csv',index=False)
print("\n"+wf.drop(columns=['params']).to_string(index=False))
st=stability(wf)
print("\nSTABILITY:")
for k,v in st.items():
    if k!='param_stability': print(f"  {k:22s} {v}")
print("  parameter stability across windows:")
for k,v in st.get('param_stability',{}).items():
    print(f"    {k:32s} distinct={v['distinct']} stable={v['stable']}  {v['values']}")

print("\n"+"="*78); print("SENSITIVITY (in-sample; looking for plateaus)"); print("="*78)
IS=slice_df(F,IN_SAMPLE)
for key,vals in [('score.threshold',[70.,75.,80.,85.,90.]),
                 ('exits.atr_mult_sl',[0.8,1.0,1.1,1.3,1.6]),
                 ('exits.tp1_r',[1.2,1.5,1.8,2.1]),
                 ('regime.min_confidence',[0.45,0.55,0.65,0.75]),
                 ('risk.min_rr',[1.2,1.5,1.8,2.2])]:
    s=sweep(IS,base,key,vals,news)
    rb=robustness(s)
    print(f"\n{key}:\n{s.to_string(index=False)}\n  -> robust={rb['robust']} "
          f"({rb['pct_values_profitable']}% of values PF>1, neighbours_ok={rb['neighbours_ok']})")

print("\n"+"="*78); print("FINAL OUT-OF-SAMPLE HOLDOUT - opened once, config frozen"); print("="*78)
HO=slice_df(F,HOLDOUT)
print(f"holdout: {HO.index[0]} -> {HO.index[-1]}")
results={}
for label,ov in [("FROZEN (IS-selected)",CHOSEN),("UNTUNED BASELINE",MICRO)]:
    cfg=Config().with_overrides(**ov); cfg.initial_equity=500.0
    res,_=run(Prep(HO),cfg,news,500.0)
    m=compute(res.trades,res.equity,500.0)
    results[label]=(m,res)
    print("\n"+render(m,label))
    if len(res.trades):
        print(breakdown(res.trades,'strategy').to_string(index=False))

print("\n"+"="*78); print("MONTE CARLO (full-sample trades, untuned baseline)"); print("="*78)
cfg=Config().with_overrides(**MICRO); cfg.initial_equity=500.0
res_full,_=run(Prep(F),cfg,news,500.0)
mc=simulate(res_full.trades,500.0,n=5000)
for k,v in mc.items(): print(f"  {k:24s} {v if isinstance(v,int) else round(v,4)}")
json.dump({'mc':mc,'wf_stability':{k:v for k,v in st.items() if k!='param_stability'}},
          open('xauusd_bot/reports/validation.json','w'),indent=2,default=str)
