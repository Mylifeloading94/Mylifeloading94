#!/usr/bin/env python3
"""The v6 deliverable: $100,000 over the FULL ~1200-day TradeLocker window.

The owner has twice been handed a 90-day $100k run containing 5-7 trades. Seven
trades evaluate nothing. This runs the same adopted configuration over the whole
broker history -- ~1200 days, 195 trades -- compounding trade by trade, at 1%
and 2% risk, and reports it in dollars with the statistics that price it:

  end balance, profit $, ROI %, CAGR, max drawdown %, longest losing streak,
  trades, trades/day, win rate, profit factor, expectancy + CLUSTER CI,
  total pips, and an explicit risk-of-ruin arithmetic on the recorded
  14-trade losing streak.

The 90-day window is produced too, for continuity, and labelled as non-evidence.

    python3 run_v6_100k.py --full             # the headline
    python3 run_v6_100k.py --days 90          # continuity only

Writes ``reports/v6_100k/``. Nothing here places an order; cached broker bars
are read and nothing else.
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
OUT = os.path.join(REPO, "reports", "v6_100k")


# ---------------------------------------------------------------------------
# Cluster bootstrap -- identical definition to tune_v5.py, kept here so the
# deliverable script does not depend on the tuning harness.
# ---------------------------------------------------------------------------
def cluster_ids(frame: pd.DataFrame, hours: float = 24.0) -> pd.DataFrame:
    f = frame.sort_values("signal_time").reset_index(drop=True)
    f["signal_time"] = pd.to_datetime(f["signal_time"], utc=True)
    ids = np.zeros(len(f), dtype=int)
    nxt = 0
    last: dict = {}
    for i, row in f.iterrows():
        key = (row.symbol, row.direction)
        prev = last.get(key)
        if prev is not None and (row.signal_time - prev[1]).total_seconds() <= hours * 3600:
            ids[i] = prev[0]
        else:
            ids[i] = nxt
            nxt += 1
        last[key] = (ids[i], row.signal_time)
    f["cluster"] = ids
    return f


def cluster_bootstrap(frame, iterations=5000, ci=0.95, seed=7, hours=24.0):
    f = cluster_ids(frame, hours)
    groups = [g["r_multiple"].values for _, g in f.groupby("cluster")]
    n_c = len(groups)
    rng = np.random.default_rng(seed)
    stats = np.empty(iterations)
    for it in range(iterations):
        pick = rng.integers(0, n_c, size=n_c)
        stats[it] = np.concatenate([groups[k] for k in pick]).mean()
    lo = (1 - ci) / 2 * 100
    return float(np.percentile(stats, lo)), float(np.percentile(stats, 100 - lo)), n_c


def total_pips(cfg, ledger: pd.DataFrame) -> float:
    """Signed pips captured, using each instrument's own pip size.

    Pips are reported because the owner asked for them, with the caveat that
    summing pips across XAUUSD (pip 0.1, $10/pip/lot) and USDJPY (pip 0.01) adds
    quantities that are not the same unit of money. The dollar column is the one
    that means something.
    """
    if ledger is None or ledger.empty:
        return 0.0
    pips = {s: float(cfg.get(f"markets.{s}.pip", 0.0001))
            for s in ledger["symbol"].unique()}
    tot = 0.0
    for _, row in ledger.iterrows():
        pip = pips[row["symbol"]]
        move = (row["exit_price"] - row["entry"]) if row["direction"] == "bullish" \
            else (row["entry"] - row["exit_price"])
        tot += move / pip
    return float(tot)


def period_tables(ledger: pd.DataFrame, start_balance: float,
                  first_day: pd.Timestamp, last_day: pd.Timestamp) -> dict:
    """Continuous Daily / Weekly / Monthly / Yearly tables.

    Continuous is load-bearing: a flat day is a row, not a gap. A table of only
    the active days flatters any system that trades in bursts, and the flat
    stretches ARE the product for a sniper stack that trades once a week.
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
        out["roi_pct"] = ((out["end_balance"] / out["start_balance"] - 1.0) * 100.0).round(4)
        out["cum_roi_pct"] = ((out["end_balance"] / start_balance - 1.0) * 100.0).round(4)
        out["profit"] = out["profit"].round(2)
        out.insert(0, label, out.index)
        return out[[label, "pairs", "trades", "profit", "roi_pct",
                    "cum_roi_pct"]].reset_index(drop=True)

    daily = finish(frame, "date")
    daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")

    def regroup(rule: str, label: str, fmt: str) -> pd.DataFrame:
        agg = frame.resample(rule).agg({"trades": "sum", "profit": "sum",
                                        "end_balance": "last"})
        agg["start_balance"] = agg["end_balance"].shift(1).fillna(start_balance)
        agg["pairs"] = frame["pairs"].resample(rule).apply(
            lambda s: ", ".join(sorted({p for row in s if row for p in row.split(", ")})))
        out = finish(agg, label)
        out[label] = pd.to_datetime(out[label]).dt.strftime(fmt)
        return out

    weekly = regroup("W-SUN", "week_ending", "%Y-%m-%d")
    monthly = regroup("ME", "month", "%Y-%m")
    yearly = regroup("YE", "year", "%Y")

    curve = np.concatenate([[start_balance], frame["end_balance"].values])
    peak = np.maximum.accumulate(curve)
    max_dd = max(0.0, float(-((curve - peak) / peak).min() * 100))
    return {"daily": daily, "weekly": weekly, "monthly": monthly,
            "yearly": yearly, "max_dd_pct": max_dd}


def trade_rows(ledger: pd.DataFrame, start_balance: float, risk_pct: float) -> pd.DataFrame:
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
        "r_multiple": led["r_multiple"].round(4),
        "balance_after": running.round(2),
    })


def run_one(cfg, engine, contexts, start, end, balance, risk_pct):
    variant = cfg.copy()
    variant.set("risk.starting_balance", balance)
    variant.set("risk.compounding", True)
    variant.set("risk.risk_per_trade_pct", risk_pct)
    # `Config.risk_per_trade_pct` CLAMPS to `risk.risk_per_trade_max_pct` (1.0),
    # so asking for 2% without raising the cap silently returns a 1% run.
    variant.set("risk.risk_per_trade_max_pct", max(risk_pct, 1.0))
    # The daily/weekly loss gates are percentages of the account, so at 2% an
    # untouched `max_daily_loss_pct: 2.0` is tripped by ONE losing trade and the
    # run measures the circuit breaker instead of the strategy. Scaled by the
    # same factor as the risk step-up so 1% and 2% stay comparable.
    scale = risk_pct / 0.5
    variant.set("risk.max_daily_loss_pct",
                round(float(variant.get("risk.max_daily_loss_pct", 2.0)) * scale, 3))
    variant.set("risk.max_weekly_loss_pct",
                round(float(variant.get("risk.max_weekly_loss_pct", 5.0)) * scale, 3))
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
    n = m["trades"]
    wlo, whi = win_rate_ci(ledger, 5000) if n else (np.nan, np.nan)
    elo, ehi = expectancy_ci(ledger, 5000) if n else (np.nan, np.nan)
    if n >= 30:
        clo, chi, n_c = cluster_bootstrap(ledger, 5000)
    else:
        clo = chi = np.nan
        n_c = 0

    end_bal = round(balance + ledger["pnl"].sum(), 2) if n else balance
    years = max((end - start).days, 1) / 365.25
    cagr = ((end_bal / balance) ** (1 / years) - 1.0) * 100.0 if end_bal > 0 else -100.0
    weekdays = int(np.busday_count(start.date(), end.date()))
    span_days = max((end - start).days, 1)

    summary = {
        "risk_pct": risk_pct,
        "window_days": span_days,
        "window_years": round(years, 2),
        "start_balance": balance,
        "end_balance": end_bal,
        "total_profit": round(float(ledger["pnl"].sum()), 2) if n else 0.0,
        "total_roi_pct": round((end_bal / balance - 1) * 100, 3),
        "cagr_pct": round(cagr, 3),
        "trades": n,
        "trades_per_day_calendar": round(n / span_days, 3),
        "trades_per_weekday": round(n / max(weekdays, 1), 3),
        "win_rate_pct": round(m["win_rate"], 2) if n else 0.0,
        "win_rate_ci": f"[{wlo:.2f}, {whi:.2f}]" if n else "",
        "profit_factor": round(m["profit_factor"], 3) if n else 0.0,
        "expectancy_r": round(m["expectancy_r"], 4) if n else 0.0,
        "expectancy_ci_naive": (f"[{elo:+.4f}, {ehi:+.4f}]" if n >= 30
                                else f"n={n} -- not computable"),
        "clusters": n_c,
        "expectancy_ci_cluster": (f"[{clo:+.4f}, {chi:+.4f}]" if n >= 30
                                  else f"n={n} -- not computable"),
        "cluster_ci_clears_zero": ("sample too small to say" if n < 30 else
                                   ("NO -- spans zero" if clo < 0 < chi else "YES")),
        "max_drawdown_pct": round(per["max_dd_pct"], 2),
        "max_consecutive_losses": m.get("max_consecutive_losses", 0) if n else 0,
        "max_consecutive_wins": m.get("max_consecutive_wins", 0) if n else 0,
        "total_pips": round(total_pips(cfg, ledger), 1),
        "active_days": int((per["daily"]["trades"] > 0).sum()),
        "avg_win_r": round(float(ledger.loc[ledger.r_multiple > 0, "r_multiple"].mean()), 3) if n else 0.0,
        "avg_loss_r": round(float(ledger.loc[ledger.r_multiple <= 0, "r_multiple"].mean()), 3) if n else 0.0,
    }
    return ledger, per, summary


def ruin_table(streak: int, risks=(1.0, 2.0), worst_r=-1.05):
    """What the recorded losing streak does to the account, compounded.

    The engine's losing trades average slightly worse than -1R (spread paid on
    exit, gap-through on the stop), so -1.05R is used rather than the nominal
    -1.00R. Compounding is fixed-fractional on the running balance, which is
    what the deliverable runs, so each successive loss risks less in dollars --
    this is the KIND number, and it is still what appears below.
    """
    rows = []
    for r in risks:
        bal = 1.0
        for _ in range(streak):
            bal *= (1.0 + (r / 100.0) * worst_r)
        rows.append({
            "risk_pct": r,
            "streak": streak,
            "drawdown_pct_from_streak": round((1 - bal) * 100, 2),
            "balance_after_streak_on_100k": round(bal * 100000, 2),
            "gain_needed_to_recover_pct": round((1 / bal - 1) * 100, 2),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--full", action="store_true",
                    help="use the entire cached broker window instead of --days")
    ap.add_argument("--balance", type=float, default=100000.0)
    ap.add_argument("--profile", default="v5")
    ap.add_argument("--stack", default=None)
    ap.add_argument("--source", default="tradelocker")
    ap.add_argument("--risks", default="1.0,2.0")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    cfg = load_config()
    if args.profile and args.profile.lower() not in ("", "none"):
        cfg = cfg.apply_profile(args.profile)
    if args.stack:
        cfg.set("active_stack", args.stack)

    engine = DataEngine(cfg, source=args.source)
    contexts = Backtester(cfg, engine).build_contexts()
    dstart, dend = walkforward.data_window(contexts)
    if args.full:
        start, end, label = dstart, dend, "full"
    else:
        end = dend
        start = end - pd.Timedelta(days=args.days)
        label = f"{args.days}d"
    tag_dir = os.path.join(OUT, args.tag or label)

    print("=" * 78)
    print(f"v6 DELIVERABLE -- ${args.balance:,.0f}, {label} window, compounding")
    print(f"  profile '{args.profile}'  stack '{cfg.stack['name']}'  "
          f"{len(contexts)} pairs  gate {cfg.score_threshold:.0f}")
    print(f"  window {str(start)[:10]} -> {str(end)[:10]}  "
          f"({(end - start).days} days)")
    print("=" * 78)

    os.makedirs(tag_dir, exist_ok=True)
    all_trades, summaries = [], []
    for risk_pct in [float(x) for x in args.risks.split(",")]:
        ledger, per, summary = run_one(cfg, engine, contexts, start, end,
                                       args.balance, risk_pct)
        rtag = f"{risk_pct:g}pct".replace(".", "_")
        for name in ("daily", "weekly", "monthly", "yearly"):
            per[name].insert(0, "risk_pct", risk_pct)
            per[name].to_csv(os.path.join(tag_dir, f"{name}_{rtag}.csv"), index=False)
        ledger.to_csv(os.path.join(tag_dir, f"ledger_{rtag}.csv"), index=False)
        all_trades.append(trade_rows(ledger, args.balance, risk_pct))
        summaries.append(summary)
        print(f"\n--- RISK {risk_pct}% ---")
        for k, v in summary.items():
            print(f"  {k:26s} {v}")

    pd.concat(all_trades, ignore_index=True).to_csv(
        os.path.join(tag_dir, "trades.csv"), index=False)
    sm = pd.DataFrame(summaries)
    sm.to_csv(os.path.join(tag_dir, "summary.csv"), index=False)

    streak = int(max(s["max_consecutive_losses"] for s in summaries)) or 14
    ruin = ruin_table(streak)
    ruin.to_csv(os.path.join(tag_dir, "risk_of_ruin.csv"), index=False)
    print(f"\n--- RISK OF RUIN on the recorded {streak}-trade losing streak ---")
    print(ruin.to_string(index=False))

    print(f"\nWrote {tag_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
