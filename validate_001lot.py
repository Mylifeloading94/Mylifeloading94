import sys; sys.path.insert(0,'.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, HOLDOUT, slice_df
from xauusd_bot.optimization.walk_forward import run_walk_forward, stability
from xauusd_bot.optimization.monte_carlo import simulate
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self,F): self.F=F; self.m1=None

F=pd.read_pickle('data_cache/F_2026.pkl'); news=NewsFilter.load(Config().news)
LOT01={'instrument.min_lot':0.01,'instrument.lot_step':0.01,
       'risk.allow_min_lot_override':True}
def mk(cap,**x):
    c=Config().with_overrides(**{**LOT01,'risk.max_risk_percent_hard_cap':cap,**x})
    c.initial_equity=500.0; return c

print("SPLITS — 0.01 lot")
print(f"{'window':<28}{'cap':>5}{'n':>5}{'win%':>7}{'PF':>7}{'ret%':>9}{'dd%':>8}{'expR':>8}")
for cap in (2.0,3.0):
    for name,span in [("full sample",None),("in-sample Jan-May",IN_SAMPLE),
                      ("validation Jun-Jul",VALIDATION),("holdout Jul-Aug",HOLDOUT)]:
        Fx=F if span is None else slice_df(F,span)
        res,_=run(Prep(Fx),mk(cap),news,500.0); m=compute(res.trades,res.equity,500.0)
        print(f"{name:<28}{cap:>5.0f}{m['trades']:>5}{m['win_rate']:>7.1f}"
              f"{min(m['profit_factor'],9.99):>7.2f}{m['net_return_pct']:>9.2f}"
              f"{m['max_dd_pct']:>8.2f}{m['expectancy_r']:>8.3f}")

print("\nSTRATEGY ISOLATION at 0.01 lot / 2% cap (full sample)")
print(f"{'config':<34}{'n':>5}{'win%':>7}{'PF':>7}{'ret%':>9}{'dd%':>8}{'expR':>8}")
for name,tog in [("all three",{}),
                 ("trend only",{'toggles.liquidity_reversal':False,'toggles.breakout':False}),
                 ("trend + liquidity",{'toggles.breakout':False}),
                 ("liquidity only",{'toggles.trend_continuation':False,'toggles.breakout':False})]:
    res,_=run(Prep(F),mk(2.0,**tog),news,500.0); m=compute(res.trades,res.equity,500.0)
    print(f"{name:<34}{m['trades']:>5}{m['win_rate']:>7.1f}{min(m['profit_factor'],9.99):>7.2f}"
          f"{m['net_return_pct']:>9.2f}{m['max_dd_pct']:>8.2f}{m['expectancy_r']:>8.3f}")

print("\nTREND-ONLY across the splits (the one that looked good in-sample)")
print(f"{'window':<28}{'n':>5}{'win%':>7}{'PF':>7}{'ret%':>9}{'expR':>8}")
tr={'toggles.liquidity_reversal':False,'toggles.breakout':False}
for name,span in [("full sample",None),("in-sample Jan-May",IN_SAMPLE),
                  ("validation Jun-Jul",VALIDATION),("holdout Jul-Aug",HOLDOUT)]:
    Fx=F if span is None else slice_df(F,span)
    res,_=run(Prep(Fx),mk(2.0,**tr),news,500.0); m=compute(res.trades,res.equity,500.0)
    print(f"{name:<28}{m['trades']:>5}{m['win_rate']:>7.1f}{min(m['profit_factor'],9.99):>7.2f}"
          f"{m['net_return_pct']:>9.2f}{m['expectancy_r']:>8.3f}")

print("\nWALK-FORWARD — 0.01 lot / 2% cap")
grid=[{'score.threshold':t,'toggles.breakout':b,
       'sessions.enabled_sessions':s}
      for t in (75.0,80.0) for b in (True,False)
      for s in (("LONDON","OVERLAP","NEWYORK"),("OVERLAP","NEWYORK"))]
wf=run_walk_forward(F,mk(2.0),grid,news,75,25,500.0)
wf.to_csv('xauusd_bot/reports/walk_forward_001lot.csv',index=False)
st=stability(wf)
for k,v in st.items():
    if k!='param_stability': print(f"  {k:22s} {v}")

print("\nMONTE CARLO — 0.01 lot / 2% cap, 5000 resamples")
res,_=run(Prep(F),mk(2.0),news,500.0)
mc=simulate(res.trades,500.0,n=5000)
for k,v in mc.items(): print(f"  {k:24s} {v if isinstance(v,int) else round(v,4)}")
