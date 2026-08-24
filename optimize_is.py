"""Coarse structural optimisation on IN-SAMPLE only."""
import sys; sys.path.insert(0, '.')
import pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.optimization.optimizer import search
from xauusd_bot.optimization.splits import IN_SAMPLE, VALIDATION, slice_df
from xauusd_bot.news.news_filter import NewsFilter

F = pd.read_pickle('data_cache/F_2026.pkl')
IS = slice_df(F, IN_SAMPLE)
news = NewsFilter.load(Config().news)
MICRO = {'instrument.min_lot': 0.001, 'instrument.lot_step': 0.001}
base = Config().with_overrides(**MICRO); base.initial_equity = 500.0

space = {
    'score.threshold': [75.0, 80.0, 85.0],
    'exits.tp2_r': [2.0, 2.5],
    'exits.trail_atr_mult': [1.0, 1.5],
    'toggles.breakout': [True, False],
    'sessions.enabled_sessions': [
        ("ASIA", "LONDON", "OVERLAP", "NEWYORK"),
        ("LONDON", "OVERLAP", "NEWYORK"),
        ("OVERLAP", "NEWYORK"),
    ],
}
r = search(IS, base, space, news, 500.0, verbose=True)
pd.set_option('display.width', 200)
r.to_csv('xauusd_bot/reports/optimize_is.csv', index=False)
print("\nTOP 15 BY COMPOSITE OBJECTIVE (in-sample):")
print(r.head(15).to_string(index=False))
print("\nWORST 5:"); print(r.tail(5).to_string(index=False))
print("\n--- marginal effect of each choice (mean objective) ---")
for k in space:
    print(f"\n{k}:")
    print(r.groupby(r[k].astype(str)).agg(n=('obj','size'), mean_obj=('obj','mean'),
          mean_PF=('PF','mean'), mean_trades=('trades','mean')).round(3).to_string())
