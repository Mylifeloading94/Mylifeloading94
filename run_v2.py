"""
V2 configuration through the REAL backtester (costs, fills, risk locks,
session flat, everything). Train sanity-check first, then the 2026 holdout.
"""
import sys, json; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute, render, breakdown
from xauusd_bot.research.loader import load
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self,F): self.F=F; self.m1=None

news = NewsFilter.load(Config().news)

V2 = {
    # geometry validated on 2024-25: wide stop, proportional target
    'exits.stop_scale': 2.5,
    'exits.tp_model': 'full',
    'exits.tp1_r': 1.25,
    'exits.tp2_r': 1.25,
    'exits.breakeven_at_r': 99.0,      # OFF - never validated, adds a free parameter
    'exits.trail_start_r': 99.0,       # OFF
    'exits.max_hold_minutes': 480,
    'exits.max_sl_atr': 4.0,
    # hard component requirements found on train
    'gate.require_retest': True,
    'gate.require_m15_alignment': True,
    # only trade when the round trip is <=3% of the target
    'costs.max_cost_to_target_ratio': 0.03,
    # let the data pick sessions rather than my assumption
    'sessions.enabled_sessions': ("ASIA","LONDON","OVERLAP","NEWYORK"),
    'sessions.trade_start_utc': 0,
    'sessions.trade_end_utc': 20,
    # the numeric score is superseded by the hard gate; keep it permissive
    'score.threshold': 0.0,
    'risk.min_rr': 1.2,
    'risk.max_daily_trades': 6,
}
MICRO = {'instrument.min_lot': 0.001, 'instrument.lot_step': 0.001}
LOT01 = {'instrument.min_lot': 0.01, 'instrument.lot_step': 0.01,
         'risk.allow_min_lot_override': True, 'risk.max_risk_percent_hard_cap': 5.0}

def go(F, ov, label, eq=500.0):
    cfg = Config().with_overrides(**ov); cfg.initial_equity = eq
    res, _ = run(Prep(F), cfg, news, eq)
    m = compute(res.trades, res.equity, eq)
    print("\n" + "="*76); print(label); print("="*76)
    print("  rejections:", dict(sorted(res.rejections.items(), key=lambda x:-x[1])[:6]))
    print(render(m, "RESULT"))
    return m, res

TR = load("2024-01-01","2026-01-01")
print(f"TRAIN 2024-2025: {len(TR):,} bars", flush=True)
m, res = go(TR, {**V2, **MICRO}, "TRAIN 2024-2025 — V2, micro lot, $500")
if len(res.trades):
    for by in ("strategy","session","direction","exit_reason"):
        b = breakdown(res.trades, by)
        if len(b): print(f"\nby {by}:\n{b.to_string(index=False)}")
    res.trades.to_csv('xauusd_bot/reports/trades_v2_train.csv', index=False)
    print(f"\n  stop distance $: median {res.trades.r_distance.median():.2f}  "
          f"p90 {res.trades.r_distance.quantile(.9):.2f}")
    print(f"  risk% per trade: median {res.trades.risk_percent.median():.3f}")
del TR

print("\n\n" + "#"*76)
print("# HOLDOUT — 2026 (not used to choose the V2 geometry, gate or filters)")
print("#"*76)
HO = load("2026-01-01","2026-08-25")
m26, r26 = go(HO, {**V2, **MICRO}, "HOLDOUT 2026 — V2, micro lot, $500")
if len(r26.trades):
    for by in ("strategy","session","direction","exit_reason"):
        b = breakdown(r26.trades, by)
        if len(b): print(f"\nby {by}:\n{b.to_string(index=False)}")
    r26.trades.to_csv('xauusd_bot/reports/trades_v2_2026.csv', index=False)
    print(f"\n  median stop $ {r26.trades.r_distance.median():.2f}   "
          f"median risk% {r26.trades.risk_percent.median():.3f}")
m26b, r26b = go(HO, {**V2, **LOT01}, "HOLDOUT 2026 — V2, 0.01 standard lot, $500")
if len(r26b.trades):
    print(f"  risk per trade at 0.01 lot: median "
          f"{r26b.trades.risk_percent.median():.2f}%  max "
          f"{r26b.trades.risk_percent.max():.2f}%")
del HO

print("\n\n" + "#"*76)
print("# EVERY YEAR — does the cost filter keep it out of the wrong regimes?")
print("#"*76)
print(f"{'year':>6}{'n':>6}{'win%':>8}{'PF':>7}{'ret%':>9}{'dd%':>7}{'expR':>8}")
rows=[]
for y in range(2015, 2027):
    try: Fy = load(f"{y}-01-01", f"{y+1}-01-01")
    except Exception: continue
    cfg = Config().with_overrides(**{**V2, **MICRO}); cfg.initial_equity = 500.0
    res,_ = run(Prep(Fy), cfg, news, 500.0)
    mm = compute(res.trades, res.equity, 500.0)
    rows.append({'year':y, **{k:mm[k] for k in
                 ('trades','win_rate','profit_factor','net_return_pct','max_dd_pct','expectancy_r')}})
    print(f"{y:>6}{mm['trades']:>6}{mm['win_rate']:>8.1f}"
          f"{min(mm['profit_factor'],9.99):>7.2f}{mm['net_return_pct']:>9.2f}"
          f"{mm['max_dd_pct']:>7.2f}{mm['expectancy_r']:>8.3f}", flush=True)
    del Fy
pd.DataFrame(rows).to_csv('xauusd_bot/reports/v2_by_year.csv', index=False)
