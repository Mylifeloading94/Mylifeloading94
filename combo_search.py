"""
Constrained combination search on TRAIN (2024-2025) only.

Deliberately small: 4 pre-motivated filter axes, coarse grids. Selection
criterion targets the user's goal - maximise WIN RATE subject to PF >= 1.20
and at least 200 trades so the result is not noise.
"""
import sys, pickle, itertools; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.research.excursion import evaluate

pd.set_option('display.width', 220)
BASE = Config()
ex = pickle.load(open('data_cache/ex_2425.pkl','rb'))
M = ex.meta
rt = M['spread'].values + 2 * BASE.costs.entry_slippage

rows = []
for sm in (1.6, 2.0, 2.5, 3.0):
    for tr in (1.0, 1.25, 1.5, 2.0, 2.5):
        tgt = M['struct_sl_dist'].values * sm * tr
        ratio = rt / np.maximum(tgt, 1e-9)
        for cthr in (0.02, 0.03, 0.05):
            for strat in ("all", "trend", "trend+breakout", "no_liquidity_only"):
                if strat == "all":
                    sm_mask = np.ones(len(M), bool)
                elif strat == "trend":
                    sm_mask = (M['strategy'] == "TREND_CONTINUATION").values
                elif strat == "trend+breakout":
                    sm_mask = M['strategy'].isin(["TREND_CONTINUATION","BREAKOUT"]).values
                else:
                    sm_mask = (M['strategy'] != "LIQUIDITY_REVERSAL").values
                for qual in ("none", "retest", "m15", "retest+m15"):
                    q = np.ones(len(M), bool)
                    if "retest" in qual: q &= M['c_retest'].values.astype(bool)
                    if "m15" in qual: q &= M['c_m15'].values.astype(bool)
                    mask = (ratio <= cthr) & sm_mask & q
                    m = evaluate(ex, sm, tr, BASE, mask=mask)
                    if m['n'] < 120: continue
                    rows.append({"stopx": sm, "tgtR": tr, "cost<=": cthr, "strat": strat,
                                 "qual": qual, "n": m['n'],
                                 "win%": round(m['win_rate'], 1),
                                 "PF": round(min(m['profit_factor'], 99), 2),
                                 "expR": round(m['expectancy_r'], 3),
                                 "totR": round(m['total_r'], 1)})
d = pd.DataFrame(rows)
d.to_csv('xauusd_bot/reports/combo_train_2425.csv', index=False)
print(f"{len(d)} combinations with n>=120\n")

good = d[(d['PF'] >= 1.20) & (d['n'] >= 200)].sort_values('win%', ascending=False)
print("TOP 20 BY WIN RATE  (PF >= 1.20, n >= 200)")
print(good.head(20).to_string(index=False))
print("\nTOP 12 BY EXPECTANCY (n >= 200)")
print(d[d['n'] >= 200].sort_values('expR', ascending=False).head(12).to_string(index=False))
print("\nTOP 12 BY TOTAL R (n >= 200)")
print(d[d['n'] >= 200].sort_values('totR', ascending=False).head(12).to_string(index=False))

# how sensitive is the best win-rate pick to its neighbours?
if len(good):
    b = good.iloc[0]
    print(f"\nNeighbourhood of the best win-rate pick "
          f"(stopx {b['stopx']}, tgt {b['tgtR']}R, cost<={b['cost<=']}, "
          f"{b['strat']}, {b['qual']}):")
    nb = d[(d['strat'] == b['strat']) & (d['qual'] == b['qual']) &
           (d['cost<='] == b['cost<='])]
    print(nb.sort_values(['stopx','tgtR']).to_string(index=False))
