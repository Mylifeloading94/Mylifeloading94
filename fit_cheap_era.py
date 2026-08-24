"""
Fit on 2024-2025 ONLY. 2026 is held back and opened once at the end.

Hypothesis from the cost analysis + era study: the edge is real but small, and
survives only when the round-trip cost is a small fraction of the target. So:
  1. widen the stop and target so cost/target is small,
  2. add an explicit cost-to-target filter (generalises across volatility eras),
  3. search entry filters for WIN RATE subject to PF staying above 1.2.
"""
import sys, pickle; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.research.loader import load
from xauusd_bot.research.excursion import collect, evaluate
from xauusd_bot.strategy import regime_engine, selector

pd.set_option('display.width', 220)
BASE = Config().with_overrides(**{
    'sessions.enabled_sessions': ("ASIA","LONDON","OVERLAP","NEWYORK"),
    'sessions.trade_start_utc': 0, 'sessions.trade_end_utc': 21})

F = load("2024-01-01", "2026-01-01")
print(f"TRAIN 2024-2025: {len(F):,} M1 bars", flush=True)
R = regime_engine.classify(F, BASE.regime)
sig, _ = selector.select(F, R, BASE)
ex = collect(F, R, sig, BASE, horizon=480, cooldown=20)
print(f"signals: {len(ex):,}", flush=True)
with open('data_cache/ex_2425.pkl','wb') as f: pickle.dump(ex, f)
del F, R, sig

M = ex.meta
# cost / target ratio: round trip cost divided by the target distance
rt_cost = M['spread'].values + 2 * BASE.costs.entry_slippage

print("\n" + "="*100)
print("GEOMETRY GRID on 2024-2025 (net of real costs)")
print("="*100)
print(f"{'stopx':>6}{'tgtR':>6}{'n':>7}{'win%':>8}{'PF':>8}{'expR':>9}{'totR':>9}")
res = []
for sm in (1.0, 1.3, 1.6, 2.0, 2.5, 3.0):
    for tr in (0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
        m = evaluate(ex, sm, tr, BASE)
        res.append((sm, tr, m))
        print(f"{sm:>6.1f}{tr:>6.2f}{m['n']:>7}{m['win_rate']:>8.1f}"
              f"{min(m['profit_factor'],99):>8.2f}{m['expectancy_r']:>9.3f}{m['total_r']:>9.1f}")

print("\nBest by expectancy:")
for sm, tr, m in sorted(res, key=lambda x: -x[2]['expectancy_r'])[:6]:
    print(f"  stop x{sm} tgt {tr}R -> win {m['win_rate']:.1f}% PF {min(m['profit_factor'],99):.2f} "
          f"expR {m['expectancy_r']:+.3f}")
print("Best WIN RATE with PF >= 1.15:")
ok = [x for x in res if x[2]['profit_factor'] >= 1.15]
for sm, tr, m in sorted(ok, key=lambda x: -x[2]['win_rate'])[:6]:
    print(f"  stop x{sm} tgt {tr}R -> win {m['win_rate']:.1f}% PF {min(m['profit_factor'],99):.2f} "
          f"expR {m['expectancy_r']:+.3f}")

# ---- cost/target filter -------------------------------------------------
print("\n" + "="*100)
print("COST-TO-TARGET FILTER  (stop x2.0, target 2.0R) — only trade when the")
print("round trip is a small fraction of what you are trying to win")
print("="*100)
SM, TR = 2.0, 2.0
tgt_dist = M['struct_sl_dist'].values * SM * TR
ratio = rt_cost / np.maximum(tgt_dist, 1e-9)
print(f"cost/target ratio: median {np.median(ratio)*100:.1f}%  "
      f"p10 {np.percentile(ratio,10)*100:.1f}%  p90 {np.percentile(ratio,90)*100:.1f}%")
print(f"{'max cost/tgt':>13}{'n':>7}{'win%':>8}{'PF':>8}{'expR':>9}{'totR':>9}")
for thr in (0.02, 0.03, 0.04, 0.05, 0.07, 0.10, 1.0):
    m = evaluate(ex, SM, TR, BASE, mask=(ratio <= thr))
    if m['n'] == 0: continue
    print(f"{thr*100:>12.0f}%{m['n']:>7}{m['win_rate']:>8.1f}"
          f"{min(m['profit_factor'],99):>8.2f}{m['expectancy_r']:>9.3f}{m['total_r']:>9.1f}")

# ---- entry filters ------------------------------------------------------
print("\n" + "="*100)
print("ENTRY FILTERS (stop x2.0, target 2.0R, cost/target <= 5%)")
print("="*100)
base_mask = ratio <= 0.05
def show(name, extra):
    m = evaluate(ex, SM, TR, BASE, mask=base_mask & extra)
    if m['n'] < 40: return None
    print(f"  {name:<44} n={m['n']:>5} win={m['win_rate']:>5.1f}% "
          f"PF={min(m['profit_factor'],99):>5.2f} expR={m['expectancy_r']:+.3f} "
          f"totR={m['total_r']:>7.1f}")
    return m
show("(no filter)", np.ones(len(M), bool))
print("  --- direction ---")
show("longs only", (M['dir'] == 1).values)
show("shorts only", (M['dir'] == -1).values)
print("  --- strategy ---")
for s in ("TREND_CONTINUATION","LIQUIDITY_REVERSAL","BREAKOUT"):
    show(f"strategy = {s}", (M['strategy'] == s).values)
print("  --- session ---")
for s in ("ASIA","LONDON","OVERLAP","NEWYORK"):
    show(f"session = {s}", (M['session'] == s).values)
print("  --- regime ---")
for r in M['regime'].value_counts().index[:8]:
    show(f"regime = {r}", (M['regime'] == r).values)
print("  --- signal quality components ---")
for c in ("c_h1","c_m15","c_m5mom","c_vwap","c_liq","c_ltf","c_retest"):
    show(f"{c} true", M[c].values.astype(bool))
print("  --- context ---")
show("M15 ADX > 25", (M['adx15'] > 25).values)
show("M15 ADX < 20", (M['adx15'] < 20).values)
show("ATR rank > 0.5", (M['atr_rank'] > 0.5).values)
show("ATR rank < 0.5", (M['atr_rank'] < 0.5).values)
show("|extension| < 2 ATR", (M['ext_atr'].abs() < 2).values)
show("regime confidence > 0.7", (M['regime_conf'] > 0.7).values)
