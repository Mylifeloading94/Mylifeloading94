"""
TRAIN-ONLY research: what stop/target geometry produces a high win rate with
positive expectancy? Uses the forward-excursion study so every exit rule is
evaluated on an IDENTICAL entry set.
"""
import sys, pickle; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.research.loader import load, TRAIN
from xauusd_bot.research.excursion import collect, evaluate
from xauusd_bot.strategy import regime_engine, selector

pd.set_option('display.width', 200)
cfg = Config()
# widen the session gate for the study so the DATA decides, not my assumption
cfg = cfg.with_overrides(**{'sessions.enabled_sessions':
                            ("ASIA","LONDON","OVERLAP","NEWYORK"),
                            'sessions.trade_start_utc': 0,
                            'sessions.trade_end_utc': 21})

F = load(*TRAIN)
print(f"TRAIN: {F.index[0]} -> {F.index[-1]}  ({len(F):,} M1 bars)", flush=True)
R = regime_engine.classify(F, cfg.regime)
sig, counts = selector.select(F, R, cfg)
print("selector:", counts, flush=True)

ex = collect(F, R, sig, cfg, horizon=240, cooldown=20)
print(f"signals captured: {len(ex):,}", flush=True)
print(ex.meta['strategy'].value_counts().to_string())
with open('data_cache/ex_train.pkl','wb') as f: pickle.dump(ex, f)

print("\n" + "="*96)
print("EXIT GEOMETRY GRID  (stop = mult x structural distance, target = R x stop)")
print("="*96)
print(f"{'stopx':>6}{'tgtR':>6}{'n':>7}{'win%':>8}{'PF':>8}{'expR':>9}{'payoff':>8}{'totR':>9}")
best = []
for sm in (0.8, 1.0, 1.3, 1.6, 2.0, 2.5):
    for tr in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5):
        m = evaluate(ex, sm, tr, cfg)
        if m['n'] == 0: continue
        best.append((sm, tr, m))
        print(f"{sm:>6.1f}{tr:>6.2f}{m['n']:>7}{m['win_rate']:>8.1f}"
              f"{min(m['profit_factor'],99):>8.2f}{m['expectancy_r']:>9.3f}"
              f"{m['payoff']:>8.2f}{m['total_r']:>9.1f}")

print("\nTop 10 by expectancy (train):")
for sm, tr, m in sorted(best, key=lambda x: -x[2]['expectancy_r'])[:10]:
    print(f"  stop x{sm:.1f} target {tr:.2f}R -> win {m['win_rate']:.1f}% "
          f"PF {min(m['profit_factor'],99):.2f} expR {m['expectancy_r']:+.3f} n={m['n']}")
print("\nTop 10 by WIN RATE among those with expR > 0:")
pos = [b for b in best if b[2]['expectancy_r'] > 0]
for sm, tr, m in sorted(pos, key=lambda x: -x[2]['win_rate'])[:10]:
    print(f"  stop x{sm:.1f} target {tr:.2f}R -> win {m['win_rate']:.1f}% "
          f"PF {min(m['profit_factor'],99):.2f} expR {m['expectancy_r']:+.3f} n={m['n']}")

print("\n" + "="*96)
print("PER-STRATEGY at a few geometries")
print("="*96)
for strat in ex.meta['strategy'].unique():
    if not strat: continue
    mk = (ex.meta['strategy'] == strat).values
    print(f"\n{strat}  (n={int(mk.sum())})")
    print(f"{'stopx':>6}{'tgtR':>6}{'n':>7}{'win%':>8}{'PF':>8}{'expR':>9}")
    for sm, tr in [(1.0,1.0),(1.0,1.5),(1.3,0.75),(1.3,1.0),(1.6,0.75),(1.6,1.0),(2.0,0.75)]:
        m = evaluate(ex, sm, tr, cfg, mask=mk)
        if m['n']: print(f"{sm:>6.1f}{tr:>6.2f}{m['n']:>7}{m['win_rate']:>8.1f}"
                         f"{min(m['profit_factor'],99):>8.2f}{m['expectancy_r']:>9.3f}")
