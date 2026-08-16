#!/usr/bin/env python3
"""The v5 deliverable: $100,000, most recent 90 days, at 1% AND 2% risk.

Two independent runs of the same adopted configuration, compounding trade by
trade, written as the exact five columns the owner asked for -- Date, Pair,
Trades, Profit, ROI -- plus continuous Daily / Weekly / Monthly rollups and a
Summary block at each risk level.

    python3 run_v5_100k.py
    python3 run_v5_100k.py --days 90 --profile v5

Writes ``reports/v5_100k/`` and is consumed by ``build_v5_workbook.py``.
Nothing here places an order; only cached broker bars are read.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper import walkforward
from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.metrics import compute_metrics, expectancy_ci, win_rate_ci

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "v5_100k")


def period_tables(ledger: pd.DataFrame, start_balance: float,
                  first_day: pd.Timestamp, last_day: pd.Timestamp) -> dict:
    """Continuous Daily / Weekly / Monthly tables.

    Continuous is load-bearing: a flat day is a row, not a gap. A table of only
    the active days flatters any system that trades in bursts, and the flat
    stretches ARE the product for a sniper stack.
    """
    days = pd.date_range(first_day.normalize(), last_day.normalize(), freq="D", tz="UTC")
    frame = pd.DataFrame(index=days)
    frame.index.name = "date"

    if ledger is None or ledger.empty:
        frame["trades"] = 0
        frame["profit"] = 0.0
        pairs_by_day = pd.Series("", index=days)
    else:
        led = ledger.copy()
        led["exit_time"] = pd.to_datetime(led["exit_time"], utc=True)
        led["day"] = led["exit_time"].dt.normalize()
        g = led.groupby("day")
        frame["trades"] = g.size().reindex(days).fillna(0).astype(int)
        frame["profit"] = g["pnl"].sum().reindex(days).fillna(0.0)
        pairs_by_day = (g["symbol"].apply(lambda s: ", ".join(sorted(set(s))))
                        .reindex(days).fillna(""))

    frame["end_balance"] = start_balance + frame["profit"].cumsum()
    frame["start_balance"] = frame["end_balance"].shift(1).fillna(start_balance)
    frame["pairs"] = pairs_by_day

    def finish(tab: pd.DataFrame, label: str) -> pd.DataFrame:
        out = tab.copy()
        out["roi_pct"] = (out["end_balance"] / out["start_balance"] - 1.0) * 100.0
        out.insert(0, label, out.index)
        return out[[label, "pairs", "trades", "profit", "roi_pct"]].reset_index(drop=True)

    daily = finish(frame, "date")
    daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")

    def regroup(rule: str, label: str) -> pd.DataFrame:
        agg = frame.resample(rule).agg({"trades": "sum", "profit": "sum",
                                        "end_balance": "last"})
        agg["start_balance"] = agg["end_balance"].shift(1).fillna(start_balance)
        agg["pairs"] = frame["pairs"].resample(rule).apply(
            lambda s: ", ".join(sorted({p for row in s if row for p in row.split(", ")})))
        return finish(agg, label)

    weekly = regroup("W-SUN", "week_ending")
    weekly["week_ending"] = pd.to_datetime(weekly["week_ending"]).dt.strftime("%Y-%m-%d")
    monthly = regroup("ME", "month")
    monthly["month"] = pd.to_datetime(monthly["month"]).dt.strftime("%Y-%m")

    curve = np.concatenate([[start_balance], frame["end_balance"].values])
    peak = np.maximum.accumulate(curve)
    max_dd = max(0.0, float(-((curve - peak) / peak).min() * 100))
    return {"daily": daily, "weekly": weekly, "monthly": monthly, "max_dd_pct": max_dd}


def trade_rows(ledger: pd.DataFrame, start_balance: float, risk_pct: float) -> pd.DataFrame:
    """One row per trade: Date, Pair, Trades, Profit, ROI.

    ROI on a trade row is that trade's contribution measured against the
    balance it was actually sized from, so the column sums to the compounded
    result rather than to a nominal one.
    """
    if ledger is None or ledger.empty:
        return pd.DataFrame(columns=["risk_pct", "date", "pair", "trades",
                                     "profit", "roi_pct"])
    led = ledger.sort_values("exit_time").reset_index(drop=True)
    running = start_balance + led["pnl"].cumsum()
    opening = running.shift(1).fillna(start_balance)
    return pd.DataFrame({
        "risk_pct": risk_pct,
        "date": pd.to_datetime(led["exit_time"], utc=True).dt.strftime("%Y-%m-%d"),
        "pair": led["symbol"],
        "trades": 1,
        "profit": led["pnl"].round(2),
        "roi_pct": (led["pnl"] / opening * 100.0).round(4),
    })


def run_one(cfg, engine, contexts, start, end, balance, risk_pct):
    variant = cfg.copy()
    variant.set("risk.starting_balance", balance)
    variant.set("risk.compounding", True)
    variant.set("risk.risk_per_trade_pct", risk_pct)
    # Gold carries its own risk override; scale it by the same factor so the
    # "1% vs 2%" comparison is a clean doubling everywhere.
    gold = variant.get("instrument_overrides.XAUUSD.risk.risk_per_trade_pct", None)
    if gold is not None:
        variant.set("instrument_overrides.XAUUSD.risk.risk_per_trade_pct",
                    round(risk_pct * 0.7, 4))
    bt = Backtester(variant, engine)
    bt.bind(contexts)
    trades, _, _ = bt.run(contexts=contexts, start=start, end=end,
                          collect_rejections=False)
    ledger = trades_to_frame(trades)
    m = compute_metrics(ledger, balance)
    per = period_tables(ledger, balance, start, end)
    wlo, whi = win_rate_ci(ledger, 5000) if m["trades"] else (np.nan, np.nan)
    elo, ehi = expectancy_ci(ledger, 5000) if m["trades"] else (np.nan, np.nan)
    weekdays = int(np.busday_count(start.date(), end.date()))
    summary = {
        "risk_pct": risk_pct,
        "start_balance": balance,
        "end_balance": round(balance + ledger["pnl"].sum(), 2) if m["trades"] else balance,
        "total_profit": round(float(ledger["pnl"].sum()), 2) if m["trades"] else 0.0,
        "total_roi_pct": round(float(ledger["pnl"].sum()) / balance * 100, 3) if m["trades"] else 0.0,
        "trades": m["trades"],
        "win_rate_pct": round(m["win_rate"], 2),
        "win_rate_ci": f"[{wlo:.2f}, {whi:.2f}]" if m["trades"] else "",
        "profit_factor": round(m["profit_factor"], 3),
        "expectancy_r": round(m["expectancy_r"], 4),
        "expectancy_ci": f"[{elo:+.4f}, {ehi:+.4f}]" if m["trades"] else "",
        "ci_clears_zero": ("no -- spans zero" if (m["trades"] and elo < 0 < ehi)
                           else ("yes" if m["trades"] else "")),
        "max_drawdown_pct": round(per["max_dd_pct"], 2),
        "max_consecutive_losses": m.get("max_consecutive_losses", 0),
        "trades_per_day_calendar": round(m["trades"] / max((end - start).days, 1), 3),
        "trades_per_weekday": round(m["trades"] / max(weekdays, 1), 3),
        "active_days": int((per["daily"]["trades"] > 0).sum()),
        "window_days": (end - start).days,
    }
    return ledger, per, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--balance", type=float, default=100000.0)
    ap.add_argument("--profile", default="v5")
    ap.add_argument("--stack", default=None)
    ap.add_argument("--source", default="tradelocker")
    ap.add_argument("--risks", default="1.0,2.0")
    args = ap.parse_args()

    cfg = load_config()
    if args.profile and args.profile.lower() not in ("", "none"):
        cfg = cfg.apply_profile(args.profile)
    if args.stack:
        cfg.set("active_stack", args.stack)

    engine = DataEngine(cfg, source=args.source)
    contexts = Backtester(cfg, engine).build_contexts()
    _, end = walkforward.data_window(contexts)
    start = end - pd.Timedelta(days=args.days)

    print("=" * 78)
    print(f"v5 DELIVERABLE -- ${args.balance:,.0f}, {args.days} days, compounding")
    print(f"  profile '{args.profile}'  stack '{cfg.stack['name']}'  "
          f"{len(contexts)} pairs  gate {cfg.score_threshold:.0f}")
    print(f"  window {str(start)[:10]} -> {str(end)[:10]}")
    print("=" * 78)

    os.makedirs(OUT, exist_ok=True)
    all_trades, summaries = [], []
    for risk_pct in [float(x) for x in args.risks.split(",")]:
        ledger, per, summary = run_one(cfg, engine, contexts, start, end,
                                       args.balance, risk_pct)
        tag = f"{risk_pct:g}pct".replace(".", "_")
        for name in ("daily", "weekly", "monthly"):
            per[name].insert(0, "risk_pct", risk_pct)
            per[name].to_csv(os.path.join(OUT, f"{name}_{tag}.csv"), index=False)
        ledger.to_csv(os.path.join(OUT, f"ledger_{tag}.csv"), index=False)
        all_trades.append(trade_rows(ledger, args.balance, risk_pct))
        summaries.append(summary)
        print(f"\n--- RISK {risk_pct}% ---")
        for k, v in summary.items():
            print(f"  {k:26s} {v}")

    pd.concat(all_trades, ignore_index=True).to_csv(
        os.path.join(OUT, "trades.csv"), index=False)
    pd.DataFrame(summaries).to_csv(os.path.join(OUT, "summary.csv"), index=False)
    print(f"\nWrote {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
