"""
FINAL OUT-OF-SAMPLE BACKTEST.

Window   : 2026-01-01 .. 2026-08-22   (data ends Fri 2026-08-21 20:45 UTC)
Balance  : $10,000
Config   : config.locked_params(), fixed on 2025 data before this window was read
Watchlist: chosen on 2025 data (watchlist.txt), frozen before this window was read

Also reports, for contrast, what the same period looks like on all 24 pairs and
what a watchlist chosen ON the test data would have produced -- the size of that
gap is the size of the selection bias this design avoids.
"""
import json
import numpy as np, pandas as pd

import tl_data, strategy as st, backtest as bt, signal_sim as ss
import metrics, config

pd.set_option("display.width", 220)
S = pd.Timestamp(config.OOS_START, tz="UTC")
E = pd.Timestamp(config.OOS_END, tz="UTC")
START_BAL = 10_000.0

p = config.locked_params()
cfg = config.locked_risk(START_BAL)
watchlist = open("watchlist.txt").read().split()
frames = {s: tl_data.load(s) for s in tl_data.SYMBOLS}

print("=" * 78)
print("OUT-OF-SAMPLE BACKTEST  2026-01-01 -> 2026-08-22   $10,000")
print("=" * 78)
print(f"watchlist (chosen on 2025): {watchlist}\n")

# Run BOTH: the mechanically-filtered watchlist the brief asks for, and the
# full 24-pair universe. Per-pair selection was shown to be noise in v1, so
# reporting only the filtered version would overstate what selection buys.
variants = {"filtered": watchlist, "all_pairs": tl_data.SYMBOLS}
results = {}
for name, syms in variants.items():
    tr_v, eq_v = bt.run(frames, p, cfg, S, E, syms)
    results[name] = (tr_v, eq_v, metrics.summarize(tr_v, START_BAL, S, E, eq_v))
    m = results[name][2]
    print(f"  {name:10s} trades={m.get('total_trades',0):4d} "
          f"WR={m.get('win_rate',0):5.1f}%  PF={m.get('profit_factor',0):5.2f}  "
          f"net={m.get('net_profit',0):+9.2f} ({m.get('net_profit_pct',0):+6.2f}%)  "
          f"maxDD={m.get('max_dd_pct',0):5.2f}%")
print()

PRIMARY = "all_pairs"
trades, eq, summ = results[PRIMARY]
print(f"[primary reported variant: {PRIMARY}]\n")

print("--- OVERALL ---")
order = ["start_balance","end_balance","net_profit","net_profit_pct","total_trades",
         "winning_trades","losing_trades","win_rate","avg_win","avg_loss",
         "profit_factor","expectancy","expectancy_r","avg_rr","realized_rr",
         "max_dd_abs","max_dd_pct","recovery_factor","sharpe","sortino",
         "largest_win","largest_loss","trades_per_day","longest_win_streak",
         "longest_loss_streak","avg_duration_hours"]
for k in order:
    v = summ.get(k)
    print(f"  {k:22s} {v:>12.3f}" if isinstance(v,(int,float)) else f"  {k:22s} {v}")

print("\n--- MONTHLY ---")
mo = metrics.monthly(trades, START_BAL)
print(mo.round(2).to_string(index=False) if len(mo) else "  no trades")

# ---------------- per-pair, all 24 -------------------------------------
print("\n--- PER-PAIR (all 24 tested, single-pair backtests, $10,000 each) ---")
rows = []
for s in tl_data.SYMBOLS:
    tr, e1 = bt.run(frames, p, cfg, S, E, [s])
    m = metrics.summarize(tr, START_BAL, S, E, e1)
    if m["total_trades"] == 0:
        rows.append(dict(symbol=s, trades=0, win_rate=0, net=0.0, roi=0.0, pf=0.0,
                         max_dd_pct=0.0, avg_trade=0.0, avg_rr=0.0, wstreak=0,
                         lstreak=0, tpd=0.0))
        continue
    rows.append(dict(symbol=s, trades=m["total_trades"], win_rate=m["win_rate"],
                     net=m["net_profit"], roi=m["net_profit_pct"],
                     pf=m["profit_factor"], max_dd_pct=m["max_dd_pct"],
                     avg_trade=m["expectancy"], avg_rr=m["avg_rr"],
                     wstreak=m["longest_win_streak"], lstreak=m["longest_loss_streak"],
                     tpd=m["trades_per_day"]))
pp = pd.DataFrame(rows).sort_values("pf", ascending=False)
print(pp.round(3).to_string(index=False))

# ---------------- selection-bias demonstration --------------------------
best_oos = pp[(pp.trades >= 5) & (pp.win_rate >= 60) & (pp.pf >= 1.15)].symbol.tolist()
print(f"\n--- SELECTION-BIAS CHECK ---")
print(f"  watchlist chosen on 2025 (honest, used above): {watchlist}")
print(f"  watchlist that 2026 itself would have chosen : {best_oos}")
print(f"  overlap: {sorted(set(watchlist) & set(best_oos))}")

out = {"summary": summ,
       "monthly": mo.to_dict("records") if len(mo) else [],
       "per_pair": pp.to_dict("records"),
       "watchlist_insample": watchlist,
       "watchlist_if_fitted_to_2026": best_oos}
json.dump(out, open("backtest_results.json","w"), indent=1, default=str)

# ---------------- trade log --------------------------------------------
if trades:
    tl = pd.DataFrame([{
        "symbol": t.symbol, "dir": "LONG" if t.direction>0 else "SHORT",
        "entry_time": t.entry_time, "exit_time": t.exit_time,
        "entry": t.entry, "stop": t.stop_initial, "target": t.target,
        "exit": t.exit, "lots": t.lots, "score": t.score,
        "pnl": round(t.pnl,2), "R": round(t.r_multiple,3), "reason": t.reason,
        "bars": t.bars_held, "mfe_r": round(t.mfe_r,2), "mae_r": round(t.mae_r,2),
    } for t in sorted(trades, key=lambda x: x.entry_time)])
    tl.to_csv("trades_oos_2026.csv", index=False)
    print(f"\ntrade log written: trades_oos_2026.csv ({len(tl)} rows)")
    print("\n--- EXIT REASON BREAKDOWN ---")
    print(tl.groupby("reason").agg(n=("R","size"), avg_R=("R","mean"), total_pnl=("pnl","sum")).round(3).to_string())
