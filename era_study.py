"""
Separate 'no signal' from 'signal eaten by costs'.

Runs the identical entry set through the excursion study twice — with real
costs and with costs set to zero — in the expensive era (gold ~$1200-2000,
spread = 30-60% of a 1-ATR move) and the cheap era (gold $2400-4600, spread
= 7-25%).

If gross expectancy is positive but net is negative, the strategies work and
the cost model is the binding constraint. If gross is also negative, the
entries carry no directional information and no exit or cost regime saves them.
"""
import sys, pickle; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.research.loader import load
from xauusd_bot.research.excursion import collect, evaluate
from xauusd_bot.strategy import regime_engine, selector

pd.set_option('display.width', 200)

BASE = Config().with_overrides(**{
    'sessions.enabled_sessions': ("ASIA","LONDON","OVERLAP","NEWYORK"),
    'sessions.trade_start_utc': 0, 'sessions.trade_end_utc': 21})
ZERO = BASE.with_overrides(**{
    'costs.base_spread': 0.0001, 'costs.entry_slippage': 0.0, 'costs.max_spread': 99.0,
    'costs.spread_by_session': {k: 0.0001 for k in
                                ("ASIA","LONDON","OVERLAP","NEWYORK","CLOSED")}})

ERAS = [("EXPENSIVE 2016-2019 (gold $1250-1400)", "2016-01-01", "2020-01-01"),
        ("MID       2021-2023 (gold $1800-2000)", "2021-01-01", "2024-01-01"),
        ("CHEAP     2024-2026 (gold $2400-4600)", "2024-01-01", "2026-08-25")]

GEOMS = [(1.0, 1.0), (1.3, 1.0), (1.6, 1.0), (1.6, 1.5), (2.0, 1.5), (2.0, 2.0)]

for label, a, b in ERAS:
    F = load(a, b)
    R = regime_engine.classify(F, BASE.regime)
    sig, _ = selector.select(F, R, BASE)
    print("\n" + "="*94)
    print(f"{label}   {len(F):,} M1 bars")
    print("="*94)
    for costlabel, cfg in (("NET  (real costs)", BASE), ("GROSS (zero cost)", ZERO)):
        ex = collect(F, R, sig, cfg, horizon=240, cooldown=20)
        if len(ex) == 0:
            print(f"  {costlabel}: no signals"); continue
        print(f"  {costlabel}  n={len(ex):,}")
        print(f"    {'stopx':>6}{'tgtR':>6}{'win%':>8}{'PF':>8}{'expR':>9}{'totR':>9}")
        for sm, tr in GEOMS:
            m = evaluate(ex, sm, tr, cfg)
            print(f"    {sm:>6.1f}{tr:>6.2f}{m['win_rate']:>8.1f}"
                  f"{min(m['profit_factor'],99):>8.2f}{m['expectancy_r']:>9.3f}{m['total_r']:>9.1f}")
        if costlabel.startswith("GROSS"):
            print("    per strategy (stop x1.6, target 1.0R, gross):")
            for s in ("TREND_CONTINUATION","LIQUIDITY_REVERSAL","BREAKOUT"):
                mk = (ex.meta['strategy'] == s).values
                if mk.sum() < 30: continue
                m = evaluate(ex, 1.6, 1.0, cfg, mask=mk)
                print(f"      {s:<20} n={m['n']:>5} win={m['win_rate']:>5.1f}% "
                      f"PF={min(m['profit_factor'],99):>5.2f} expR={m['expectancy_r']:+.3f}")
    del F, R, sig
