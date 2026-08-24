"""IN-SAMPLE diagnostics only (Jan 1 - May 31 2026). The validation and holdout
blocks are not touched by this script."""
import sys; sys.path.insert(0, '.')
import pandas as pd, numpy as np
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute, render, breakdown
from xauusd_bot.optimization.splits import IN_SAMPLE, slice_df
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self, F): self.F = F; self.m1 = None

F = pd.read_pickle('data_cache/F_2026.pkl')
IS = slice_df(F, IN_SAMPLE)
print(f"IN-SAMPLE: {IS.index[0]} -> {IS.index[-1]}  ({len(IS):,} M1 bars)")
news = NewsFilter.load(Config().news)
MICRO = {'instrument.min_lot': 0.001, 'instrument.lot_step': 0.001}
base = Config().with_overrides(**MICRO); base.initial_equity = 500.0

res, art = run(Prep(IS), base, news, 500.0)
t = res.trades
m = compute(t, res.equity, 500.0)
print(render(m, "IS BASELINE"))
print()
for by in ("strategy", "session", "grade", "direction", "exit_reason"):
    b = breakdown(t, by)
    if len(b): print(f"by {by}:\n{b.to_string(index=False)}\n")

# Does the setup score actually discriminate?
t2 = t.copy()
t2["score_bin"] = pd.cut(t2["setup_score"], [0, 75, 80, 85, 90, 95, 101])
print("setup score discrimination:")
print(t2.groupby("score_bin", observed=True).agg(
    n=("pnl", "size"), win=("pnl", lambda x: round(100*(x > 0).mean(), 1)),
    avgR=("r_multiple", "mean"), net=("pnl", "sum")).round(3).to_string())
print()
print("hour of day:")
t2["h"] = t2["ts_open"].dt.hour
print(t2.groupby("h").agg(n=("pnl", "size"), win=("pnl", lambda x: round(100*(x>0).mean(),1)),
                          avgR=("r_multiple","mean"), net=("pnl","sum")).round(3).to_string())
print()
print("MFE distribution (how far do trades actually run?):")
print(t2["mfe_r"].describe(percentiles=[.25,.5,.75,.9]).round(2).to_string())
print("\nMFE by outcome:")
print(t2.groupby(t2["pnl"] > 0)["mfe_r"].describe(percentiles=[.5]).round(2).to_string())
print("\nlosers: how many reached 1R first?", int(((t2.pnl<=0)&(t2.mfe_r>=1.0)).sum()), "of", int((t2.pnl<=0).sum()))
