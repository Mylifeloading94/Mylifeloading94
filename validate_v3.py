"""Walk-forward + Monte Carlo for V2. No parameter is chosen here."""
import sys, json; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.optimization.monte_carlo import simulate
from xauusd_bot.research.loader import load
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self,F): self.F=F; self.m1=None
news = NewsFilter.load(Config().news)
V2 = {'exits.stop_scale':3.0,'exits.tp_model':'full','exits.tp1_r':1.00,'exits.tp2_r':1.00,
      'exits.breakeven_at_r':99.0,'exits.trail_start_r':99.0,'exits.max_hold_minutes':480,
      'exits.max_sl_atr':4.0,'gate.require_retest':True,'gate.require_m15_alignment':True,
      'costs.max_cost_to_target_ratio':0.03,
      'sessions.enabled_sessions':("ASIA","LONDON","OVERLAP","NEWYORK"),
      'sessions.trade_start_utc':0,'sessions.trade_end_utc':20,
      'score.threshold':0.0,'risk.min_rr':0.9,'risk.max_daily_trades':6,
      'instrument.min_lot':0.001,'instrument.lot_step':0.001}

# ---- rolling walk-forward with the geometry FIXED (no per-window refit):
# this measures whether the ONE configuration holds up through time.
print("WALK-FORWARD — V2 held fixed, rolling 6-month blocks 2019-2026")
print(f"{'block':<26}{'n':>6}{'win%':>8}{'PF':>7}{'ret%':>9}{'dd%':>7}{'expR':>8}")
blocks, all_tr = [], []
start = pd.Timestamp("2019-01-01", tz="UTC")
while start < pd.Timestamp("2026-07-01", tz="UTC"):
    end = start + pd.DateOffset(months=6)
    try: F = load(str(start.date()), str(end.date()))
    except Exception: start = end; continue
    if len(F) < 20000: start = end; continue
    cfg = Config().with_overrides(**V2); cfg.initial_equity = 500.0
    res,_ = run(Prep(F), cfg, news, 500.0)
    m = compute(res.trades, res.equity, 500.0)
    blocks.append({'block':f"{start.date()}..{end.date()}", 'n':m['trades'],
                   'win':round(m['win_rate'],1), 'pf':round(min(m['profit_factor'],9.99),2),
                   'ret':round(m['net_return_pct'],2), 'dd':round(m['max_dd_pct'],2),
                   'expR':round(m['expectancy_r'],3)})
    print(f"{blocks[-1]['block']:<26}{m['trades']:>6}{m['win_rate']:>8.1f}"
          f"{min(m['profit_factor'],9.99):>7.2f}{m['net_return_pct']:>9.2f}"
          f"{m['max_dd_pct']:>7.2f}{m['expectancy_r']:>8.3f}", flush=True)
    if len(res.trades): all_tr.append(res.trades)
    del F; start = end

b = pd.DataFrame(blocks); b.to_csv('xauusd_bot/reports/v3_walkforward.csv', index=False)
traded = b[b['n'] >= 15]
print(f"\nblocks with >=15 trades: {len(traded)}")
print(f"  profitable blocks     : {int((traded['pf']>1).sum())}/{len(traded)} "
      f"({100*(traded['pf']>1).mean():.0f}%)")
print(f"  median block PF       : {traded['pf'].median():.2f}")
print(f"  median block win rate : {traded['win'].median():.1f}%")
print(f"  mean block expectancy : {traded['expR'].mean():+.3f}R")
print(f"  worst block return    : {traded['ret'].min():.2f}%")

T = pd.concat(all_tr, ignore_index=True)
T.to_csv('xauusd_bot/reports/v3_all_trades.csv', index=False)
r = T['r_multiple']
gl = -r[r<0].sum()
print(f"\nALL BLOCKS POOLED: n={len(T)}  win={100*(r>0).mean():.1f}%  "
      f"PF={r[r>0].sum()/gl:.2f}  expR={r.mean():+.3f}")

print("\nMONTE CARLO on the pooled trades (5000 resamples)")
mc = simulate(T, 500.0, n=5000)
for k,v in mc.items(): print(f"  {k:24s} {v if isinstance(v,int) else round(v,4)}")

wf = {'windows':len(traded), 'profitable_windows':int((traded['pf']>1).sum()),
      'pct_profitable':round(100*(traded['pf']>1).mean(),1),
      'mean_oos_pf':round(traded['pf'].mean(),2),
      'median_oos_pf':round(traded['pf'].median(),2),
      'mean_oos_expR':round(traded['expR'].mean(),3),
      'worst_oos_ret':round(traded['ret'].min(),2),
      'total_oos_trades':int(traded['n'].sum())}
json.dump({'mc':mc,'wf_stability':wf}, open('xauusd_bot/reports/validation_v3.json','w'),
          indent=2, default=str)
from xauusd_bot.deployment_gate import run_checks, render
print("\n" + render(run_checks('xauusd_bot/reports/validation_v3.json', run_tests=False)))
