"""
Full-history, candle-by-candle ACCOUNT replay of the intraday bot ($10,000 start,
real 0.01-lot steps, compounding, mark-to-market drawdown). Scenarios run in parallel.
"""
import json, os, sys, time
from multiprocessing import Pool
import numpy as np, pandas as pd
import xau_engine as E, replay_engine as R

CFG = json.load(open("configs/gold_intraday.json"))
SCEN = {
    "A_risk0.5":            dict(risk_pct=0.5),
    "B_risk1.0":            dict(risk_pct=1.0),
    "C_risk1.0_controls":   dict(risk_pct=1.0, dd_brake=(5.0, 0.5), daily_loss_pct=2.0),
    "D_risk1.0_costs":      dict(risk_pct=1.0, commission_per_lot=7.0, slip=0.10),
}


def run(name):
    m1 = E.load_m1(); t0 = time.time()
    t, eq, info = R.replay(m1, CFG, "2019-01-01", "2026-10-03", **SCEN[name])
    os.makedirs("results/account", exist_ok=True)
    t.to_csv(f"results/account/{name}_trades.csv", index=False)
    eq.resample("1D").last().dropna().to_csv(f"results/account/{name}_equity_daily.csv")
    a = R.account_stats(t, eq)
    a.update(info); a["secs"] = time.time() - t0
    return name, a


if __name__ == "__main__":
    with Pool(4) as p:
        res = dict(p.map(run, list(SCEN)))
    json.dump(res, open("results/account/summary.json", "w"), indent=2, default=float)
    print(f"{'scenario':20s} {'n':>4} {'WR%':>5} {'PF($)':>6} {'net $':>9} {'final $':>9} {'CAGR%':>6} {'maxDD%':>7} {'Sharpe':>6} {'skipped':>7}")
    for k, a in res.items():
        print(f"{k:20s} {a['n']:4d} {a['wr']:5.1f} {a['pf']:6.2f} {a['net_usd']:9.0f} {a['final']:9.0f} {a['cagr_pct']:6.2f} {a['max_dd_pct']:7.2f} {a['sharpe']:6.2f} {a['skipped_below_min_lot']:7d}")
