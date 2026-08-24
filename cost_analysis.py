"""How big is the round-trip cost relative to the move you are trying to catch?

This is the structural constraint on scalping gold. If the spread plus slippage
is a large fraction of your target, no amount of signal quality survives.
"""
import sys; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.backtesting.simulator import spread_series

cfg = Config()
rows = []
for y in (2016, 2019, 2022, 2024, 2025, 2026):
    try:
        F = pd.read_pickle(f'data_cache/features/F_{y}.pkl')
    except FileNotFoundError:
        continue
    sp = spread_series(F, cfg)
    atr5 = F['M5_atr'].ffill()
    atr15 = F['M15_atr'].ffill()
    # round trip = full spread (in on ask, out on bid) + entry & exit slippage
    rt = sp + 2 * cfg.costs.entry_slippage
    rows.append({
        'year': y, 'avg_price': round(float(F['close'].mean()), 0),
        'M5_ATR': round(float(atr5.median()), 2),
        'M15_ATR': round(float(atr15.median()), 2),
        'spread': round(float(sp.median()), 3),
        'round_trip_$': round(float(rt.median()), 3),
        'cost_/_1xM5ATR_%': round(float((rt / atr5).median() * 100), 1),
        'cost_/_1xM15ATR_%': round(float((rt / atr15).median() * 100), 1),
    })
    del F
d = pd.DataFrame(rows)
print("ROUND-TRIP COST vs THE MOVE YOU ARE TRYING TO CATCH")
print(d.to_string(index=False))
print()
print("A 1x-M5-ATR target must overcome the last column before it earns a cent.")
print("Read it as: what fraction of your gross target the broker takes.")
print()
print("Break-even accuracy needed for a 1:1 trade at each cost level:")
for _, r in d.iterrows():
    c = r['cost_/_1xM5ATR_%'] / 100
    # win pays (1-c), loss costs (1+c); break-even W: W(1-c) = (1-W)(1+c)
    w = (1 + c) / 2
    print(f"  {int(r['year'])}: cost {100*c:5.1f}% of target -> need "
          f"{100*w:.1f}% win rate just to break even on a 1:1")
