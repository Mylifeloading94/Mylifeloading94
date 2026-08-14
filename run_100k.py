#!/usr/bin/env python3
"""The $100,000 / 90-day deliverable.

Runs the adopted v2 config over the most recent N days of broker data on a
$100,000 account with trade-by-trade compounding, and produces continuous
Daily / Weekly / Monthly gain tables.

"Continuous" is load-bearing: every calendar day in the window gets a row, not
just the days that traded. At one to three trades a week a table of only the
active days would flatter the system by hiding the flat stretches, which ARE
the product. Weekends are marked rather than dropped, because the market is
genuinely shut and a reader should be able to see that.

    python3 run_100k.py                       # 90 days, $100k, config risk
    python3 run_100k.py --days 180 --risk 0.75
    python3 run_100k.py --stack sniper

Writes ``reports/100k/{daily,weekly,monthly,ledger,summary}.csv``. Adding the
sheets to the workbook is :mod:`add_100k_sheets`.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper.backtest import Backtester, trades_to_frame
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.metrics import compute_metrics, expectancy_ci, win_rate_ci
from smc_sniper import walkforward

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "reports", "100k")


def build_periods(ledger: pd.DataFrame, start_balance: float,
                  first_day: pd.Timestamp, last_day: pd.Timestamp) -> dict:
    """Daily / weekly / monthly tables over a CONTINUOUS calendar."""
    days = pd.date_range(first_day.normalize(), last_day.normalize(), freq="D", tz="UTC")
    frame = pd.DataFrame(index=days)
    frame.index.name = "date"

    if ledger is None or ledger.empty:
        frame["trades"] = 0
        frame["pnl"] = 0.0
        frame["wins"] = 0
    else:
        led = ledger.copy()
        led["exit_time"] = pd.to_datetime(led["exit_time"], utc=True)
        led["day"] = led["exit_time"].dt.normalize()
        grouped = led.groupby("day")
        frame["trades"] = grouped.size().reindex(days).fillna(0).astype(int)
        frame["pnl"] = grouped["pnl"].sum().reindex(days).fillna(0.0)
        frame["wins"] = grouped["r_multiple"].apply(lambda s: int((s > 0).sum())) \
            .reindex(days).fillna(0).astype(int)

    frame["end_balance"] = start_balance + frame["pnl"].cumsum()
    frame["start_balance"] = frame["end_balance"].shift(1).fillna(start_balance)
    frame["weekday"] = frame.index.day_name()

    def finish(table: pd.DataFrame, label: str) -> pd.DataFrame:
        out = table.copy()
        out["gain_usd"] = out["end_balance"] - out["start_balance"]
        out["period_roi_pct"] = out["gain_usd"] / out["start_balance"] * 100
        out["cumulative_roi_pct"] = (out["end_balance"] / start_balance - 1) * 100
        out["losses"] = out["trades"] - out["wins"]
        out.insert(0, label, out.index)
        cols = [label, "trades", "wins", "losses", "start_balance", "end_balance",
                "gain_usd", "period_roi_pct", "cumulative_roi_pct"]
        if "weekday" in out:
            cols.insert(1, "weekday")
        if "market_open" in out:
            cols.insert(2, "market_open")
        return out[cols].reset_index(drop=True)

    daily = frame.copy()
    # Saturday/Sunday: the venue is closed, so a flat row there is structural,
    # not a missed opportunity. Flagged rather than deleted.
    daily["market_open"] = np.where(daily.index.dayofweek >= 5, "closed", "open")
    daily_out = finish(daily, "date")
    daily_out["date"] = daily_out["date"].dt.strftime("%Y-%m-%d")

    def regroup(rule: str, label: str) -> pd.DataFrame:
        agg = frame.resample(rule).agg({"trades": "sum", "wins": "sum",
                                        "pnl": "sum", "end_balance": "last"})
        agg["start_balance"] = agg["end_balance"].shift(1).fillna(start_balance)
        return finish(agg.drop(columns=["pnl"]), label)

    weekly = regroup("W-SUN", "week_ending")
    weekly["week_ending"] = pd.to_datetime(weekly["week_ending"]).dt.strftime("%Y-%m-%d")
    monthly = regroup("ME", "month")
    monthly["month"] = pd.to_datetime(monthly["month"]).dt.strftime("%Y-%m")

    # Max drawdown on the daily equity path (a truer figure than trade-to-trade:
    # it includes the days a position sat open across a losing stretch).
    equity = frame["end_balance"].values
    peak = np.maximum.accumulate(np.concatenate([[start_balance], equity]))
    curve = np.concatenate([[start_balance], equity])
    max_dd = max(0.0, float(-((curve - peak) / peak).min() * 100))
    return {"daily": daily_out, "weekly": weekly, "monthly": monthly,
            "max_dd_pct": max_dd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--balance", type=float, default=100000.0)
    ap.add_argument("--risk", type=float, default=None,
                    help="risk %% per trade; default = config (spec range 0.25-1.0)")
    ap.add_argument("--stack", default="swing")
    ap.add_argument("--source", default="tradelocker")
    args = ap.parse_args()

    cfg = load_config()
    cfg.set("active_stack", args.stack)
    cfg.set("risk.starting_balance", args.balance)
    cfg.set("risk.compounding", True)      # the deliverable asks for compounding
    if args.risk is not None:
        cfg.set("risk.risk_per_trade_pct", args.risk)
    risk_pct = float(cfg.get("risk.risk_per_trade_pct"))

    engine = DataEngine(cfg, source=args.source)
    bt = Backtester(cfg, engine)
    contexts = bt.build_contexts()
    _, end = walkforward.data_window(contexts)
    start = end - pd.Timedelta(days=args.days)

    print("=" * 78)
    print(f"${args.balance:,.0f} ACCOUNT -- {args.days} DAY BACKTEST")
    print(f"  stack '{args.stack}'  |  {len(contexts)} pairs  |  risk {risk_pct}%/trade"
          f"  |  compounding ON")
    print(f"  window {str(start)[:10]} -> {str(end)[:10]}")
    print(f"  score gate {cfg.score_threshold:.0f}/{cfg.get('scoring.max_possible')}"
          f"  |  filters {cfg.get('filters.liquidity_exclude')}")
    print("=" * 78)

    trades, _, _ = bt.run(contexts=contexts, start=start, end=end,
                          collect_rejections=False)
    ledger = trades_to_frame(trades)
    metrics = compute_metrics(ledger, args.balance)
    periods = build_periods(ledger, args.balance, start, end)

    print(f"\nTrades          : {metrics['trades']}")
    if metrics["trades"]:
        print(f"Win rate        : {metrics['win_rate']:.2f}%")
        print(f"Profit factor   : {metrics['profit_factor']:.3f}")
        print(f"Expectancy      : {metrics['expectancy_r']:+.4f}R")
        lo, hi = expectancy_ci(ledger, 5000)
        print(f"Expectancy CI   : [{lo:+.4f}, {hi:+.4f}]"
              f"  {'SPANS ZERO' if lo < 0 < hi else 'clear of zero'}")
        print(f"End balance     : ${metrics['final_balance']:,.2f}")
        print(f"Net P/L         : ${metrics['net_profit']:+,.2f} "
              f"({metrics['net_profit'] / args.balance * 100:+.2f}%)")
        print(f"Max drawdown    : {periods['max_dd_pct']:.2f}% (daily equity path)")
        active = int((periods['daily']['trades'] > 0).sum())
        print(f"Active days     : {active} of {len(periods['daily'])} "
              f"({active / len(periods['daily']) * 100:.0f}%) -- the rest are flat")

    print("\n--- MONTHLY ---")
    print(periods["monthly"].to_string(index=False))
    print("\n--- WEEKLY ---")
    print(periods["weekly"].to_string(index=False))

    os.makedirs(OUT, exist_ok=True)
    for name in ("daily", "weekly", "monthly"):
        periods[name].to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    ledger.to_csv(os.path.join(OUT, "ledger.csv"), index=False)
    wr_lo, wr_hi = win_rate_ci(ledger, 5000) if metrics["trades"] else (0, 0)
    ex_lo, ex_hi = expectancy_ci(ledger, 5000) if metrics["trades"] else (0, 0)
    summary = pd.DataFrame([
        {"metric": "account_start_usd", "value": args.balance},
        {"metric": "account_end_usd", "value": round(metrics["final_balance"], 2)},
        {"metric": "net_profit_usd", "value": round(metrics["net_profit"], 2)},
        {"metric": "total_roi_pct",
         "value": round(metrics["net_profit"] / args.balance * 100, 3)},
        {"metric": "window_days", "value": args.days},
        {"metric": "window_start", "value": str(start)[:10]},
        {"metric": "window_end", "value": str(end)[:10]},
        {"metric": "risk_per_trade_pct", "value": risk_pct},
        {"metric": "compounding", "value": "yes"},
        {"metric": "pairs", "value": len(contexts)},
        {"metric": "trades", "value": metrics["trades"]},
        {"metric": "win_rate", "value": round(metrics["win_rate"], 2)},
        {"metric": "win_rate_ci_low", "value": round(wr_lo, 2)},
        {"metric": "win_rate_ci_high", "value": round(wr_hi, 2)},
        {"metric": "profit_factor", "value": round(metrics["profit_factor"], 3)},
        {"metric": "expectancy_r", "value": round(metrics["expectancy_r"], 4)},
        {"metric": "expectancy_ci_low", "value": round(ex_lo, 4)},
        {"metric": "expectancy_ci_high", "value": round(ex_hi, 4)},
        {"metric": "max_drawdown_pct_daily", "value": round(periods["max_dd_pct"], 2)},
        {"metric": "max_consecutive_losses",
         "value": metrics.get("max_consecutive_losses", 0)},
        {"metric": "trades_per_week",
         "value": round(metrics["trades"] / (args.days / 7.0), 2)},
    ])
    summary.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    print(f"\nWrote {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
