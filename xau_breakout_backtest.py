"""
XAU Breakout Pro — validation + account backtest.

Two engines (times UTC):
  SCALP    (M5) : Asian range 00:00-06:00, first M5 close beyond it between
                  06:00-10:00, in the daily-trend direction. SL 1.5 x ATR(M5).
  INTRADAY (H1) : previous-day high/low, first H1 close beyond it between
                  06:00-16:00, in the daily-trend direction. SL 1.5 x ATR(H1).
  Daily trend   : D1 close and EMA20 both on the same side of EMA50.
Exits: TP1 = 1R closes half and moves SL to breakeven + 3 pips, runner to TP2,
time stop (scalp 10h, intraday 24h). One trade per engine per day.

Execution is simulated on M1 BID data with a 3-pip spread, trade-through
fills, stop-before-target inside a bar.

Usage: python3 xau_breakout_backtest.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xau_research as xr  # noqa: E402

CONTRACT = 100.0
LOT_STEP = 0.01

ENGINES = {
    "SCALP": dict(tf="5min", kind="asia", window=(6, 10), sl_atr=1.5, tp1_r=1.0, tp2_r=2.0,
                  tstop_min=600, sl_min_pips=25, sl_max_pips=200),
    "INTRADAY": dict(tf="1h", kind="pdhl", window=(6, 16), sl_atr=1.5, tp1_r=1.0, tp2_r=3.0,
                     tstop_min=1440, sl_min_pips=80, sl_max_pips=600),
}


def build_signals(m1, h1, eng, bias):
    tf = xr.resample(m1, eng["tf"]) if eng["tf"] != "1h" else h1[(h1.index >= m1.index[0]) & (h1.index <= m1.index[-1])]
    if eng["kind"] == "asia":
        return xr.range_break_signals(tf, (0, 6), eng["window"], bias, eng["sl_atr"])
    return xr.pdhl_break_signals(tf, bias, eng["sl_atr"], eng["window"])


def lots_for(eq, risk_pct, R, min_lot_cap_pct):
    total = eq * risk_pct / 100 / (R * CONTRACT)
    total = np.floor(total / LOT_STEP + 1e-9) * LOT_STEP
    if total < 0.01:
        if 0.01 * R * CONTRACT <= eq * min_lot_cap_pct / 100:
            total = 0.01
        else:
            return 0.0, 0.0
    if total >= 0.02:
        leg1 = np.floor(total / 2 / LOT_STEP + 1e-9) * LOT_STEP
        return round(total, 2), leg1 / total
    return round(total, 2), 0.0     # single lot: no partial, BE at TP1, runner to TP2


def simulate(m, sigs_by_engine, balance, risk_pct, min_lot_cap_pct=3.0, daily_loss_pct=4.0, sized=True):
    """Chronological portfolio sim. sized=False -> pure R results (half off at TP1)."""
    events = []
    for name, sigs in sigs_by_engine.items():
        for s in sigs:
            events.append((pd.Timestamp(s["time"]), name, s))
    events.sort(key=lambda x: x[0])
    eq = balance
    busy = {k: -1 for k in sigs_by_engine}
    open_trades = []       # (exit_idx, pnl)
    trades = []
    day_start = {}
    for ts, name, s in events:
        eng = ENGINES[name]
        i0 = m.idx(ts)
        if i0 >= len(m.t) or i0 <= busy[name]:
            continue
        # realise trades that closed before this entry
        still = []
        for x in open_trades:
            if x[0] < i0:
                eq += x[1]
            else:
                still.append(x)
        open_trades = still
        day = ts.date()
        day_start.setdefault(day, eq)
        if sized and (eq - day_start[day]) / day_start[day] * 100 <= -daily_loss_pct:
            continue
        d = s["dir"]
        entry = m.o[i0] + (xr.SPREAD if d > 0 else 0.0)
        R = d * (entry - s["sl"])
        if not np.isfinite(R) or R <= 0:
            continue
        R = max(R, eng["sl_min_pips"] * xr.PIP)
        if R > eng["sl_max_pips"] * xr.PIP:
            continue
        sl = entry - d * R
        tp1, tp2 = entry + d * eng["tp1_r"] * R, entry + d * eng["tp2_r"] * R
        if sized:
            lots, frac = lots_for(eq, risk_pct, R, min_lot_cap_pct)
            if lots <= 0:
                continue
        else:
            lots, frac = 1.0, 0.5
        r = xr.sim_trade(m, i0, d, entry, sl, tp1, tp2, tstop=i0 + eng["tstop_min"], tp1_frac=frac)
        if r is None:
            continue
        res_r, fi, xi = r
        pnl = res_r * lots * R * CONTRACT if sized else res_r
        busy[name] = xi
        open_trades.append((xi, pnl))
        trades.append(dict(engine=name, time=ts, side="BUY" if d > 0 else "SELL", entry=round(entry, 2),
                           sl_pips=round(R / xr.PIP, 1), lots=lots, R=round(res_r, 3),
                           pnl=round(pnl, 2), exit=pd.Timestamp(m.t[xi])))
    for x in open_trades:
        eq += x[1]
    return pd.DataFrame(trades), eq


def stats(df, col="R"):
    if len(df) == 0:
        return dict(n=0)
    r = df[col].values
    gw, gl = r[r > 0].sum(), -r[r <= 0].sum()
    return dict(n=len(r), win_rate=round(100 * (r > 0).mean(), 1),
                profit_factor=round(gw / gl, 2) if gl > 0 else None,
                total=round(r.sum(), 2), avg=round(r.mean(), 3))


def equity_dd(df, balance):
    if len(df) == 0:
        return 0.0
    eq = balance + df.sort_values("exit")["pnl"].cumsum().values
    eq = np.concatenate([[balance], eq])
    peak = np.maximum.accumulate(eq)
    return round(float(((peak - eq) / peak).max() * 100), 2)


def main():
    m1 = xr.load_m1_all()
    h1 = xr.load("XAUUSD_H1.csv")
    d1 = xr.resample(h1, "1D")
    bias_d1 = xr.ema_bias(d1, 20, 50)
    m = xr.M1(m1)
    print(f"M1 data {m1.index[0]} -> {m1.index[-1]} ({len(m1)} bars)")

    sigs = {k: build_signals(m1, h1, e, bias_d1) for k, e in ENGINES.items()}
    out = {}

    # ---- 1. edge in R, whole sample, per engine and per month
    rdf, _ = simulate(m, sigs, 0, 0, sized=False)
    rdf["month"] = rdf["time"].dt.strftime("%Y-%m")
    out["edge_R"] = {k: stats(rdf[rdf.engine == k]) for k in ENGINES}
    out["edge_R"]["ALL"] = stats(rdf)
    out["by_month_R"] = {mo: stats(g) for mo, g in rdf.groupby("month")}
    print(json.dumps(out["edge_R"], indent=1))
    for mo, s in out["by_month_R"].items():
        print(mo, s)

    # ---- 2. $500 account, 90 days before 1 Oct 2026
    start, end = pd.Timestamp("2026-07-03"), pd.Timestamp("2026-10-01")
    sub = {k: [s for s in v if start <= pd.Timestamp(s["time"]) < end] for k, v in sigs.items()}
    acct = {}
    for risk in (1.0, 2.0):
        tdf, final = simulate(m, sub, 500.0, risk)
        acct[f"risk_{risk}%"] = dict(final_balance=round(final, 2), return_pct=round((final / 500 - 1) * 100, 2),
                                     max_dd_pct=equity_dd(tdf, 500.0), **stats(tdf, "pnl"),
                                     by_engine={k: stats(tdf[tdf.engine == k], "pnl") for k in ENGINES})
        if risk == 2.0:
            tdf.to_csv(os.path.join(HERE, "xau_breakout_trades_90d.csv"), index=False)
    out["account_500_90d"] = acct
    print(json.dumps(acct, indent=1))

    # ---- 3. same over the full sample (Apr-Sep) for context
    tdf, final = simulate(m, sigs, 500.0, 2.0)
    out["account_500_full"] = dict(start=str(m1.index[0].date()), final_balance=round(final, 2),
                                   return_pct=round((final / 500 - 1) * 100, 2),
                                   max_dd_pct=equity_dd(tdf, 500.0), **stats(tdf, "pnl"))
    print(json.dumps(out["account_500_full"], indent=1))
    with open(os.path.join(HERE, "xau_breakout_results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    main()
