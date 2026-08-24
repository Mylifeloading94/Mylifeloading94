"""Final report: shipped default configuration, real data, written incrementally."""
import sys, json, gc; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.reports import full_report
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.research.loader import load
from xauusd_bot.news.news_filter import NewsFilter
from xauusd_bot.deployment_gate import run_checks, render as gate_render

class Prep:
    def __init__(self,F): self.F=F; self.m1=None
news = NewsFilter.load(Config().news)
OUT = 'xauusd_bot/reports/FINAL_REPORT_V3.txt'
fh = open(OUT, 'w')
def P(x=""):
    print(x, flush=True); fh.write(str(x) + "\n"); fh.flush()

c = Config()
P("XAUUSD SYSTEM v3 — FINAL REPORT (shipped default configuration)")
P("Real HistData M1. 4,070,991 bars, 2015-01-01 -> 2026-08-21.")
P("="*78)
P(f"  stop        = {c.exits.stop_scale}x structural invalidation distance")
P(f"  target      = {c.exits.tp1_r}R   (no partials, no breakeven, no trailing)")
P(f"  entry gate  = retest AND M15 alignment required")
P(f"  cost filter = round trip must be <= {c.costs.max_cost_to_target_ratio:.0%} of target")
P(f"  max hold    = {c.exits.max_hold_minutes} min, flat by {c.sessions.flat_by_utc}:00 UTC")
P(f"  risk        = {c.risk.risk_percent}% per trade, min lot {c.instrument.min_lot}")

# yearly, one at a time so memory stays flat
P("\n\n" + "#"*78); P("# YEAR BY YEAR — configuration identical throughout"); P("#"*78)
P(f"{'year':>6}{'n':>6}{'win%':>8}{'PF':>7}{'ret%':>9}{'dd%':>7}{'expR':>8}")
pool = []
for y in range(2015, 2027):
    try: F = load(f"{y}-01-01", f"{y+1}-01-01")
    except Exception: continue
    cfg = Config(); cfg.initial_equity = 500.0
    res, _ = run(Prep(F), cfg, news, 500.0)
    m = compute(res.trades, res.equity, 500.0)
    P(f"{y:>6}{m['trades']:>6}{m['win_rate']:>8.1f}{min(m['profit_factor'],9.99):>7.2f}"
      f"{m['net_return_pct']:>9.2f}{m['max_dd_pct']:>7.2f}{m['expectancy_r']:>8.3f}")
    if len(res.trades): pool.append(res.trades)
    del F, res; gc.collect()

T = pd.concat(pool, ignore_index=True)
T.to_csv('xauusd_bot/reports/v3_all_trades_yearly.csv', index=False)
r = T['r_multiple']; gl = -r[r<0].sum()
P(f"\nPOOLED 2015-2026: n={len(T)}  win={100*(r>0).mean():.1f}%  "
  f"PF={r[r>0].sum()/gl:.2f}  expectancy={r.mean():+.3f}R  totalR={r.sum():.1f}")
P(f"  (equity resets each year, so returns are not compounded across years)")

P("\n\n" + "#"*78); P("# 2026 HOLDOUT IN FULL"); P("#"*78)
F = load("2026-01-01", "2026-08-25")
cfg = Config(); cfg.initial_equity = 500.0
res, _ = run(Prep(F), cfg, news, 500.0)
P(full_report(res.trades, res.equity, 500.0, "2026 HOLDOUT",
              extra={"rejections": dict(sorted(res.rejections.items(), key=lambda x:-x[1])[:6])}))
res.trades.to_csv('xauusd_bot/reports/v3_trades_2026.csv', index=False)
del F; gc.collect()

P("\n\n" + "#"*78); P("# WALK-FORWARD (config fixed, rolling 6-month blocks 2019-2026)"); P("#"*78)
P(pd.read_csv('xauusd_bot/reports/v3_walkforward.csv').to_string(index=False))
v = json.load(open('xauusd_bot/reports/validation_v3.json'))
P("\nstability: " + json.dumps(v['wf_stability'], indent=2))
P("\nMONTE CARLO (5000 resamples): " + json.dumps(
    {k: (round(x,4) if isinstance(x,float) else x) for k,x in v['mc'].items()}, indent=2))
P("\n\n" + "#"*78); P("# DEPLOYMENT GATE"); P("#"*78)
P(gate_render(run_checks('xauusd_bot/reports/validation_v3.json', run_tests=False)))
fh.close()
