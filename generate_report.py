"""Assemble the complete performance report over the real Jan-Aug 2026 data."""
import sys, json; sys.path.insert(0,'.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.reports import full_report
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, HOLDOUT, slice_df
from xauusd_bot.optimization.monte_carlo import simulate
from xauusd_bot.news.news_filter import NewsFilter
from xauusd_bot.deployment_gate import run_checks, render as gate_render

class Prep:
    def __init__(self,F): self.F=F; self.m1=None

F=pd.read_pickle('data_cache/F_2026.pkl')
news=NewsFilter.load(Config().news)
MICRO={'instrument.min_lot':0.001,'instrument.lot_step':0.001}
CHOSEN={**MICRO,'score.threshold':80.0,'exits.tp2_r':2.5,'exits.trail_atr_mult':1.0,
        'toggles.breakout':False,'sessions.enabled_sessions':("OVERLAP","NEWYORK")}

out=[]
out.append("XAUUSD AUTOMATED SCALPING SYSTEM — BACKTEST REPORT")
out.append("Real HistData M1 bars, 2026-01-01 -> 2026-08-21, $500 starting equity")
out.append("="*78)
out.append(open('xauusd_bot/reports/data_quality.txt').read())

for label, ov, span in [
    ("FULL SAMPLE — untuned default config", MICRO, None),
    ("FULL SAMPLE — IS-selected config", CHOSEN, None),
    ("IN-SAMPLE (Jan 1 - May 31)", MICRO, IN_SAMPLE),
    ("VALIDATION (May 31 - Jul 11)", MICRO, VALIDATION),
    ("HOLDOUT (Jul 11 - Aug 21) — untuned", MICRO, HOLDOUT),
    ("HOLDOUT (Jul 11 - Aug 21) — IS-selected/frozen", CHOSEN, HOLDOUT),
]:
    Fx = F if span is None else slice_df(F, span)
    cfg = Config().with_overrides(**ov); cfg.initial_equity=500.0
    res,_ = run(Prep(Fx), cfg, news, 500.0)
    out.append("\n\n" + "#"*78 + f"\n# {label}\n" + "#"*78)
    out.append(full_report(res.trades, res.equity, 500.0, label,
                           extra={"signals evaluated": res.signals_seen,
                                  "rejections": dict(sorted(res.rejections.items(),
                                                            key=lambda x:-x[1]))}))
    if span is None and ov is MICRO:
        mc = simulate(res.trades, 500.0, n=5000)
        out.append("\nMONTE CARLO (5000 resamples: reshuffle, 10% missed trades, "
                   "cost shocks, R noise)")
        for k,v in mc.items():
            out.append(f"  {k:26s} {v if isinstance(v,int) else round(v,4)}")

out.append("\n\n"+"#"*78+"\n# WALK-FORWARD\n"+"#"*78)
wf=pd.read_csv('xauusd_bot/reports/walk_forward.csv')
out.append(wf.drop(columns=['params']).to_string(index=False))
v=json.load(open('xauusd_bot/reports/validation.json'))
out.append("\nstability: " + json.dumps(v['wf_stability'], indent=2))
out.append("\n\n"+"#"*78+"\n# DEPLOYMENT GATE\n"+"#"*78)
out.append(gate_render(run_checks(run_tests=False)))

txt="\n".join(out)
open('xauusd_bot/reports/PERFORMANCE_REPORT.txt','w').write(txt)
print(txt[-6000:])
