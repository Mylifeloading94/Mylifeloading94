"""0.01-lot report section + gate inputs."""
import sys, json; sys.path.insert(0,'.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.reports import full_report
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, HOLDOUT, slice_df
from xauusd_bot.optimization.walk_forward import stability
from xauusd_bot.optimization.monte_carlo import simulate
from xauusd_bot.news.news_filter import NewsFilter
from xauusd_bot.deployment_gate import run_checks, render as gate_render

class Prep:
    def __init__(self,F): self.F=F; self.m1=None

F=pd.read_pickle('data_cache/F_2026.pkl'); news=NewsFilter.load(Config().news)
def mk(cap):
    c=Config().with_overrides(**{'instrument.min_lot':0.01,'instrument.lot_step':0.01,
        'risk.allow_min_lot_override':True,'risk.max_risk_percent_hard_cap':cap})
    c.initial_equity=500.0; return c

out=["XAUUSD SYSTEM — 0.01 STANDARD-LOT BACKTEST",
     "Real HistData M1, 2026-01-01 -> 2026-08-21, $500 account",
     "",
     "At 0.01 lots XAUUSD moves $1 per $1 of gold. Risk per trade is therefore",
     "set by the stop distance, not by a risk percentage. The 0.50% target is",
     "unreachable: the sizer's min-lot rejection is overridden and the hard cap",
     "decides which setups are still refused.",
     "="*78]

for cap in (1.0, 2.0, 3.0, 100.0):
    res,_=run(Prep(F),mk(cap),news,500.0)
    m=compute(res.trades,res.equity,500.0)
    out.append("\n\n"+"#"*78+f"\n# FULL SAMPLE — 0.01 lot, hard cap {cap:g}%\n"+"#"*78)
    out.append(full_report(res.trades,res.equity,500.0,f"0.01 LOT / cap {cap:g}%",
        extra={"signals evaluated":res.signals_seen,
               "rejections":dict(sorted(res.rejections.items(),key=lambda x:-x[1]))}))
    if len(res.trades):
        t=res.trades
        out.append(f"\n  risk per trade: min {t.risk_percent.min():.2f}%  "
                   f"median {t.risk_percent.median():.2f}%  max {t.risk_percent.max():.2f}%")
        out.append(f"  trades risking >1.5% (one loss trips the daily lock): "
                   f"{int((t.risk_percent>1.5).sum())}/{len(t)}")

out.append("\n\n"+"#"*78+"\n# SPLITS — 0.01 lot / 2% cap\n"+"#"*78)
for name,span in [("in-sample Jan-May",IN_SAMPLE),("validation Jun-Jul",VALIDATION),
                  ("holdout Jul-Aug",HOLDOUT)]:
    res,_=run(Prep(slice_df(F,span)),mk(2.0),news,500.0)
    out.append("\n"+full_report(res.trades,res.equity,500.0,name.upper()))

wf=pd.read_csv('xauusd_bot/reports/walk_forward_001lot.csv')
wf['params']=wf['params'].apply(eval)
st=stability(wf)
out.append("\n\n"+"#"*78+"\n# WALK-FORWARD — 0.01 lot / 2% cap\n"+"#"*78)
out.append(wf.drop(columns=['params']).to_string(index=False))
out.append("\nstability: "+json.dumps({k:v for k,v in st.items() if k!='param_stability'},indent=2))
out.append("\nNOTE: windows carry 1-8 out-of-sample trades each. The mean OOS PF is")
out.append("dominated by one 5-trade window; the median is the honest figure.")

res,_=run(Prep(F),mk(2.0),news,500.0)
mc=simulate(res.trades,500.0,n=5000)
out.append("\n\n"+"#"*78+"\n# MONTE CARLO — 0.01 lot / 2% cap, 5000 resamples\n"+"#"*78)
for k,v in mc.items(): out.append(f"  {k:26s} {v if isinstance(v,int) else round(v,4)}")

json.dump({'mc':mc,'wf_stability':{k:v for k,v in st.items() if k!='param_stability'}},
          open('xauusd_bot/reports/validation_001lot.json','w'),indent=2,default=str)
gate=run_checks('xauusd_bot/reports/validation_001lot.json',run_tests=False)
out.append("\n\n"+"#"*78+"\n# DEPLOYMENT GATE — 0.01 lot / 2% cap\n"+"#"*78)
out.append(gate_render(gate))
open('xauusd_bot/reports/PERFORMANCE_REPORT_001LOT.txt','w').write("\n".join(out))
print(gate_render(gate))
