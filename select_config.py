import sys; sys.path.insert(0,'.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute, render, breakdown
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, slice_df
from xauusd_bot.optimization.objective import score as obj
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self,F): self.F=F; self.m1=None

F=pd.read_pickle('data_cache/F_2026.pkl')
IS=slice_df(F,IN_SAMPLE); VA=slice_df(F,VALIDATION)
news=NewsFilter.load(Config().news)
MICRO={'instrument.min_lot':0.001,'instrument.lot_step':0.001}
CHOSEN={**MICRO,'score.threshold':80.0,'exits.tp2_r':2.5,'exits.trail_atr_mult':1.0,
        'toggles.breakout':False,'sessions.enabled_sessions':("OVERLAP","NEWYORK")}

def ev(F_,ov,label):
    cfg=Config().with_overrides(**ov); cfg.initial_equity=500.0
    res,_=run(Prep(F_),cfg,news,500.0)
    m=compute(res.trades,res.equity,500.0)
    print(f"{label:34s} n={m['trades']:4d} win={m['win_rate']:5.1f}% PF={min(m['profit_factor'],9.99):5.2f} "
          f"ret={m['net_return_pct']:+6.2f}% dd={m['max_dd_pct']:5.2f}% expR={m['expectancy_r']:+.3f} obj={obj(m):+.3f}")
    return m,res

print("=== IN-SAMPLE: strategy mix (all else at chosen values) ===")
for name,tog in [("trend+liq (chosen)",{}),
                 ("trend only",{'toggles.liquidity_reversal':False}),
                 ("liquidity only",{'toggles.trend_continuation':False}),
                 ("all three",{'toggles.breakout':True})]:
    ev(IS,{**CHOSEN,**tog},"IS  "+name)

print("\n=== VALIDATION (never seen by the optimiser) ===")
for name,ov in [("baseline default",MICRO),
                ("chosen config",CHOSEN),
                ("chosen + trend only",{**CHOSEN,'toggles.liquidity_reversal':False}),
                ("chosen + all three",{**CHOSEN,'toggles.breakout':True})]:
    ev(VA,ov,"VAL "+name)

print("\n=== chosen config, IS detail ===")
m,res=ev(IS,CHOSEN,"IS  chosen")
print(render(m,"IS CHOSEN"))
for by in ("strategy","session","grade","direction"):
    b=breakdown(res.trades,by)
    if len(b): print(f"\nby {by}:\n{b.to_string(index=False)}")
