"""
Evaluate the validated plateau's neighbours across the ENTIRE 2019-2026 span.

Not a search: five pre-identified points from the train plateau, each scored on
all data, all results reported. The win-rate/PF trade-off is a property of the
geometry, so the user can pick where on it they want to sit.
"""
import sys; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from xauusd_bot.config import Config
from xauusd_bot.pipeline import run
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.research.loader import load
from xauusd_bot.news.news_filter import NewsFilter

class Prep:
    def __init__(self,F): self.F=F; self.m1=None
news = NewsFilter.load(Config().news)
CORE = {'exits.tp_model':'full','exits.breakeven_at_r':99.0,'exits.trail_start_r':99.0,
        'exits.max_hold_minutes':480,'exits.max_sl_atr':4.0,
        'gate.require_retest':True,'gate.require_m15_alignment':True,
        'sessions.enabled_sessions':("ASIA","LONDON","OVERLAP","NEWYORK"),
        'sessions.trade_start_utc':0,'sessions.trade_end_utc':20,
        'score.threshold':0.0,'risk.min_rr':0.9,'risk.max_daily_trades':6,
        'instrument.min_lot':0.001,'instrument.lot_step':0.001}

POINTS = [
    ("stop x2.5  tgt 1.00R  cost<=3%", 2.5, 1.00, 0.03),
    ("stop x2.5  tgt 1.25R  cost<=3%", 2.5, 1.25, 0.03),
    ("stop x3.0  tgt 1.00R  cost<=3%", 3.0, 1.00, 0.03),
    ("stop x3.0  tgt 1.25R  cost<=3%", 3.0, 1.25, 0.03),
    ("stop x2.5  tgt 1.00R  cost<=2%", 2.5, 1.00, 0.02),
    ("stop x2.5  tgt 1.50R  cost<=3%", 2.5, 1.50, 0.03),
]
# load once per half-year block, evaluate all points on it
spans = []
s = pd.Timestamp("2019-01-01", tz="UTC")
while s < pd.Timestamp("2026-07-01", tz="UTC"):
    e = s + pd.DateOffset(months=6); spans.append((s, e)); s = e

agg = {p[0]: {"trades": [], "blocks": []} for p in POINTS}
for a, b in spans:
    try: F = load(str(a.date()), str(b.date()))
    except Exception: continue
    if len(F) < 20000: continue
    for name, sm, tr, ct in POINTS:
        cfg = Config().with_overrides(**{**CORE, 'exits.stop_scale': sm,
            'exits.tp1_r': tr, 'exits.tp2_r': tr,
            'costs.max_cost_to_target_ratio': ct})
        cfg.initial_equity = 500.0
        res, _ = run(Prep(F), cfg, news, 500.0)
        m = compute(res.trades, res.equity, 500.0)
        if len(res.trades): agg[name]["trades"].append(res.trades)
        agg[name]["blocks"].append(m)
    del F
    print(f"  block {a.date()} done", flush=True)

print("\n" + "="*104)
print("PLATEAU NEIGHBOURS — pooled over 2019-2026, config held fixed throughout")
print("="*104)
print(f"{'configuration':<34}{'n':>6}{'win%':>8}{'PF':>7}{'expR':>8}"
      f"{'totR':>8}{'blk+':>7}{'medPF':>7}{'medWin':>8}")
out = []
for name, *_ in POINTS:
    trs = agg[name]["trades"]
    if not trs: continue
    T = pd.concat(trs, ignore_index=True)
    r = T['r_multiple']; gl = -r[r<0].sum()
    blocks = [m for m in agg[name]["blocks"] if m['trades'] >= 15]
    pfs = [min(m['profit_factor'], 9.99) for m in blocks]
    wins = [m['win_rate'] for m in blocks]
    row = {"config": name, "n": len(T), "win%": round(100*(r>0).mean(),1),
           "PF": round(r[r>0].sum()/gl, 2) if gl>0 else 99,
           "expR": round(r.mean(),3), "totR": round(r.sum(),1),
           "blocks_profitable": f"{sum(p>1 for p in pfs)}/{len(pfs)}",
           "median_block_PF": round(float(np.median(pfs)),2),
           "median_block_win%": round(float(np.median(wins)),1)}
    out.append(row)
    print(f"{name:<34}{row['n']:>6}{row['win%']:>8.1f}{row['PF']:>7.2f}"
          f"{row['expR']:>8.3f}{row['totR']:>8.1f}{row['blocks_profitable']:>7}"
          f"{row['median_block_PF']:>7.2f}{row['median_block_win%']:>8.1f}")
    T.to_csv(f"xauusd_bot/reports/v2_trades_{name.replace(' ','').replace('<=','le')}.csv",
             index=False)
pd.DataFrame(out).to_csv('xauusd_bot/reports/plateau_full_span.csv', index=False)
