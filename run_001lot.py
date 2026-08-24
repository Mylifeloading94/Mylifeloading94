"""Backtest forced to the standard 0.01 minimum lot on a $500 account.

At 0.01 lots XAUUSD is $1 per $1 of gold movement, so risk per trade is set by
the stop distance, NOT by a risk percentage. This script reports what that
actually costs.
"""
import sys; sys.path.insert(0, '.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute, render, breakdown
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, HOLDOUT, slice_df
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self, F): self.F = F; self.m1 = None

F = pd.read_pickle('data_cache/F_2026.pkl')
news = NewsFilter.load(Config().news)

# 0.01 min lot + explicit override so the sizer takes the trade instead of
# rejecting it. The hard cap decides which setups are still refused.
def cfg_for(cap, **extra):
    return Config().with_overrides(**{
        'instrument.min_lot': 0.01, 'instrument.lot_step': 0.01,
        'risk.allow_min_lot_override': True,
        'risk.max_risk_percent_hard_cap': cap, **extra})

print("What 0.01 lots costs on $500, by stop distance")
print("  stop $  |  loss $  |  % of $500")
for sl in (1.5, 2, 3, 5, 8, 12, 20):
    print(f"   {sl:5.1f}  |  {sl*1.0:6.2f}  |   {100*sl/500:5.2f}%")

for cap in (1.0, 2.0, 3.0, 100.0):
    cfg = cfg_for(cap); cfg.initial_equity = 500.0
    res, _ = run(Prep(F), cfg, news, 500.0)
    m = compute(res.trades, res.equity, 500.0)
    print("\n" + "="*78)
    print(f"FULL SAMPLE — 0.01 lot, hard risk cap {cap:g}% per trade")
    print("="*78)
    print("  rejections:", dict(sorted(res.rejections.items(), key=lambda x: -x[1])))
    print(render(m, "RESULT"))
    if len(res.trades):
        t = res.trades
        print(f"\n  risk per trade: min {t.risk_percent.min():.2f}%  "
              f"median {t.risk_percent.median():.2f}%  max {t.risk_percent.max():.2f}%")
        print(f"  trades risking >1.5% (one loss = instant daily lock): "
              f"{int((t.risk_percent > 1.5).sum())}/{len(t)}")
        print(f"  largest single loss: ${t.pnl.min():.2f} "
              f"({100*t.pnl.min()/500:.2f}% of starting equity)")
        print("\n" + breakdown(t, 'strategy').to_string(index=False))
        t.to_csv(f'xauusd_bot/reports/trades_001lot_cap{cap:g}.csv', index=False)
