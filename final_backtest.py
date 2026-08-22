"""
THE HEADLINE $10,000 RESULT.

A walk-forward PORTFOLIO simulation: for each 3-month block the parameters and
watchlist are those selected on data available strictly before that block, the
portfolio engine trades the block with full risk management, and the closing
balance carries into the next block.

This is "how the account would actually have performed", with no window ever
used for both selection and evaluation.
"""
import json
import numpy as np, pandas as pd

import tl_data, strategy as st, backtest as bt, signal_sim as ss
import metrics, config

pd.set_option("display.width", 240)
START_BAL = 10_000.0
TRAIN_START = pd.Timestamp("2024-04-01", tz="UTC")
FRAMES = {s: tl_data.load(s) for s in tl_data.SYMBOLS}
# M1 is loaded so the trailing stop is resolved intrabar rather than on H4 bars
M1 = {s: tl_data.load_m1(s) for s in tl_data.SYMBOLS}
CTX = {}


def ctx_for(sym, p):
    k = (sym, p.tf_minutes, p.sl_atr_buffer, p.tp_r, p.require_bias,
         p.time_stop_bars, p.sessions)
    if k not in CTX:
        CTX[k] = st.Context(sym, FRAMES[sym], p)
    return CTX[k]


def pooled(rows):
    if not rows:
        return None
    r = np.array([x["r"] for x in rows])
    gp, gl = r[r > 0].sum(), -r[r <= 0].sum()
    return dict(n=len(r), wr=100 * (r > 0).mean(),
                pf=gp / gl if gl > 0 else 99.0, exp=r.mean())


def select(tr_s, tr_e):
    """Choose score threshold and watchlist using ONLY data before tr_e."""
    p = config.locked_params()
    per = {}
    allr = []
    for s in tl_data.SYMBOLS:
        r = ss.simulate_symbol(s, FRAMES[s], p, tr_s, tr_e, ctx=ctx_for(s, p),
                               m1=M1[s])
        per[s] = r
        allr += r
    best_thr, best_pf = 60, -1
    for thr in (50, 55, 60, 65, 70):
        rr = [x for x in allr if x["score"] >= thr]
        k = pooled(rr)
        if k and k["n"] >= 25 and k["pf"] > best_pf:
            best_pf, best_thr = k["pf"], thr
    wl = []
    for s, r in per.items():
        rr = [x for x in r if x["score"] >= best_thr]
        k = pooled(rr)
        if k and k["n"] >= 3 and k["pf"] > 1.2:
            wl.append(s)
    if len(wl) < 3:
        wl = list(tl_data.SYMBOLS)
    return best_thr, wl, len(allr), best_pf


def run(variant, tp_r=None):
    """variant: 'filtered' uses the selected watchlist, 'all_pairs' the universe.
    tp_r overrides the locked target so the win-rate / profit-factor trade-off
    can be reported with full portfolio statistics."""
    balance = START_BAL
    all_trades, eq_parts, blocks = [], [], []
    cuts = pd.date_range("2025-04-01", "2026-07-01", freq="3MS", tz="UTC")
    for cut in cuts:
        te_s = cut
        te_e = min(cut + pd.offsets.MonthBegin(3) - pd.Timedelta(seconds=1),
                   pd.Timestamp("2026-08-22 23:59", tz="UTC"))
        if te_s >= pd.Timestamp("2026-08-22", tz="UTC"):
            break
        thr, wl, tn, tpf = select(TRAIN_START, cut - pd.Timedelta(seconds=1))
        syms = wl if variant == "filtered" else list(tl_data.SYMBOLS)

        p = config.locked_params()
        p.min_score = thr
        if tp_r is not None:
            p.tp_r = tp_r
            p.min_rr_after_costs = min(0.30, tp_r * 0.5)
        cfg = config.locked_risk(balance)
        tr, eq = bt.run(FRAMES, p, cfg, te_s, te_e, syms, m1=M1)
        pnl = sum(t.pnl for t in tr)
        blocks.append(dict(block=f"{te_s:%Y-%m}..{te_e:%Y-%m}", thr=thr,
                           watchlist=len(wl), train_n=tn, train_pf=round(tpf, 3),
                           trades=len(tr),
                           wr=round(100 * np.mean([t.pnl > 0 for t in tr]), 1) if tr else 0.0,
                           pnl=round(pnl, 2), start_bal=round(balance, 2),
                           end_bal=round(balance + pnl, 2)))
        balance += pnl
        all_trades += tr
        if len(eq):
            eq_parts.append(eq)
    equity = pd.concat(eq_parts) if eq_parts else pd.DataFrame()
    equity = equity[~equity.index.duplicated(keep="last")].sort_index()
    return all_trades, equity, blocks, balance


out = {}
VARIANTS = [("all_pairs", None), ("filtered", None), ("all_pairs_hiwr", 0.6)]
for variant, tp_override in VARIANTS:
    base_variant = "filtered" if variant == "filtered" else "all_pairs"
    trades, equity, blocks, final = run(base_variant, tp_override)
    summ = metrics.summarize(trades, START_BAL, TRAIN_START,
                             pd.Timestamp("2026-08-22", tz="UTC"), equity)
    out[variant] = dict(summary=summ, blocks=blocks)
    print("=" * 80)
    label = variant.upper() + (f"  (target {tp_override}R)" if tp_override else "")
    print(f"WALK-FORWARD PORTFOLIO - {label}   $10,000   2025-04-01 .. 2026-08-22")
    print("=" * 80)
    print(pd.DataFrame(blocks).to_string(index=False))
    order = ["start_balance","end_balance","net_profit","net_profit_pct","total_trades",
             "winning_trades","losing_trades","win_rate","avg_win","avg_loss",
             "profit_factor","expectancy","expectancy_r","avg_rr","realized_rr",
             "max_dd_abs","max_dd_pct","recovery_factor","sharpe","sortino",
             "largest_win","largest_loss","trades_per_day","longest_win_streak",
             "longest_loss_streak","avg_duration_hours"]
    print()
    for k in order:
        v = summ.get(k)
        print(f"  {k:22s} {v:>12.3f}" if isinstance(v, (int, float)) else f"  {k:22s} {v}")
    mo = metrics.monthly(trades, START_BAL)
    print("\n--- MONTHLY ---")
    print(mo.round(2).to_string(index=False) if len(mo) else "  none")
    out[variant]["monthly"] = mo.to_dict("records") if len(mo) else []
    if variant == "all_pairs" and trades:
        pd.DataFrame([{
            "symbol": t.symbol, "dir": "LONG" if t.direction > 0 else "SHORT",
            "entry_time": t.entry_time, "exit_time": t.exit_time,
            "entry": t.entry, "stop": t.stop_initial, "target": t.target,
            "exit": t.exit, "lots": t.lots, "score": t.score,
            "pnl": round(t.pnl, 2), "R": round(t.r_multiple, 3),
            "reason": t.reason, "mfe_r": round(t.mfe_r, 2), "mae_r": round(t.mae_r, 2),
        } for t in sorted(trades, key=lambda x: x.entry_time)]).to_csv("trades_walkforward.csv", index=False)
    print()

json.dump(out, open("final_results.json", "w"), indent=1, default=str)
