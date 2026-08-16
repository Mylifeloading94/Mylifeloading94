"""
SMC Sniper — Performance Dashboard / Backtest Report (spec §19).

Operates on a flat list of closed-trade records (the format sniper_backtest
.sniper_bt(...)["trades"] now returns, or smc_sniper.journal's exported
rows) so this module never has to fetch market data or authenticate to a
broker itself — it is pure math over whatever trade history is handed to
it, which keeps it testable with synthetic data and reusable for live
trade-journal review, not just backtests.

Each trade record must provide at minimum:
  {"symbol": str, "direction": "bullish"|"bearish", "entry_ts": ms,
   "exit_ts": ms, "R": float, "session_hour": int (UTC hour, optional)}
"""
from __future__ import annotations
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _streaks(results: List[float]) -> Dict[str, int]:
    max_w = max_l = cur_w = cur_l = 0
    for r in results:
        if r > 0.05:
            cur_w += 1; cur_l = 0
        elif r < -0.05:
            cur_l += 1; cur_w = 0
        else:
            cur_w = cur_l = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)
    return {"max_consecutive_wins": max_w, "max_consecutive_losses": max_l}


def _drawdown_series(r_series: List[float], risk_pct: float, starting_equity: float) -> Dict:
    equity = starting_equity
    peak = starting_equity
    max_dd_pct = 0.0
    curve = [equity]
    for r in r_series:
        equity *= (1 + r * risk_pct)
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd_pct = max(max_dd_pct, dd)
        curve.append(equity)
    return {"final_equity": round(equity, 2), "max_drawdown_pct": round(max_dd_pct, 4), "equity_curve": curve}


def _sharpe_sortino(r_series: List[float], trades_per_year: float) -> Dict:
    n = len(r_series)
    if n < 2:
        return {"sharpe": 0.0, "sortino": 0.0}
    mean = sum(r_series) / n
    var = sum((r - mean) ** 2 for r in r_series) / (n - 1)
    std = math.sqrt(var)
    sharpe = (mean / std) * math.sqrt(trades_per_year) if std > 0 else 0.0

    downside = [r for r in r_series if r < 0]
    if downside:
        dvar = sum(r ** 2 for r in downside) / n
        dstd = math.sqrt(dvar)
        sortino = (mean / dstd) * math.sqrt(trades_per_year) if dstd > 0 else 0.0
    else:
        sortino = float("inf") if mean > 0 else 0.0

    return {"sharpe": round(sharpe, 2), "sortino": round(sortino, 2) if sortino != float("inf") else "inf (no losing trades)"}


def compute_report(
    trades: List[Dict],
    starting_equity: float = 10_000.0,
    risk_pct: float = 0.02,
    session_labels: Optional[Dict[str, tuple]] = None,
) -> Dict:
    """Full §19 metrics dashboard. `session_labels`: optional
    {name: (start_min_utc, end_min_utc)} to bucket session_hour into named
    windows (e.g. CONFIG.SESSIONS_UTC); falls back to raw hour bucketing."""
    if not trades:
        return {"n": 0, "note": "no closed trades to report on"}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    r_series = [t["R"] for t in trades]
    wins = [r for r in r_series if r > 0.05]
    losses = [r for r in r_series if r < -0.05]
    n = len(trades)

    win_rate = round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")
    expectancy = round(sum(r_series) / n, 3)
    avg_win = round(sum(wins) / len(wins), 3) if wins else 0.0
    avg_loss = round(sum(losses) / len(losses), 3) if losses else 0.0

    span_days = max(1, (trades[-1]["exit_ts"] - trades[0]["entry_ts"]) / 86_400_000)
    trades_per_year = n / (span_days / 365.25)

    dd = _drawdown_series(r_series, risk_pct, starting_equity)
    sh_so = _sharpe_sortino(r_series, trades_per_year)
    streaks = _streaks(r_series)

    monthly: Dict[str, float] = defaultdict(float)
    yearly: Dict[str, float] = defaultdict(float)
    by_pair: Dict[str, Dict] = defaultdict(lambda: {"n": 0, "R": 0.0, "wins": 0, "losses": 0})
    by_direction: Dict[str, Dict] = defaultdict(lambda: {"n": 0, "R": 0.0, "wins": 0, "losses": 0})
    by_session: Dict[str, Dict] = defaultdict(lambda: {"n": 0, "R": 0.0, "wins": 0, "losses": 0})

    for t in trades:
        d = _dt(t["exit_ts"])
        monthly[d.strftime("%Y-%m")] += t["R"]
        yearly[d.strftime("%Y")] += t["R"]

        for bucket, key in ((by_pair, t["symbol"]), (by_direction, t["direction"])):
            b = bucket[key]
            b["n"] += 1; b["R"] += t["R"]
            b["wins"] += 1 if t["R"] > 0.05 else 0
            b["losses"] += 1 if t["R"] < -0.05 else 0

        sess_name = "unlabeled"
        hour = t.get("session_hour")
        if hour is not None:
            minute_of_day = hour * 60
            sess_name = "outside prime killzones"
            if session_labels:
                for label, (start, end) in session_labels.items():
                    if start <= minute_of_day <= end:
                        sess_name = label; break
            else:
                sess_name = f"{hour:02d}:00-{hour:02d}:59 UTC"
        b = by_session[sess_name]
        b["n"] += 1; b["R"] += t["R"]
        b["wins"] += 1 if t["R"] > 0.05 else 0
        b["losses"] += 1 if t["R"] < -0.05 else 0

    def _finalize(bucket: Dict[str, Dict]) -> Dict:
        out = {}
        for k, v in bucket.items():
            dec = v["wins"] + v["losses"]
            out[k] = {
                "n": v["n"], "totR": round(v["R"], 2),
                "WR": round(v["wins"] / dec * 100, 1) if dec else 0.0,
            }
        return out

    return {
        "n": n,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "expectancy_R": expectancy,
        "avg_win_R": avg_win,
        "avg_loss_R": avg_loss,
        "total_R": round(sum(r_series), 2),
        "final_equity": dd["final_equity"],
        "max_drawdown_pct": dd["max_drawdown_pct"],
        "sharpe": sh_so["sharpe"],
        "sortino": sh_so["sortino"],
        **streaks,
        "monthly_R": dict(sorted(monthly.items())),
        "yearly_R": dict(sorted(yearly.items())),
        "by_pair": _finalize(by_pair),
        "by_direction": _finalize(by_direction),
        "by_session": _finalize(by_session),
    }


def print_report(report: Dict) -> None:
    if report.get("n", 0) == 0:
        print("No closed trades to report on."); return
    print(f"n={report['n']}  WR={report['win_rate_pct']}%  PF={report['profit_factor']}  "
          f"expectancy={report['expectancy_R']}R  totalR={report['total_R']}")
    print(f"final_equity=${report['final_equity']:,.2f}  max_DD={report['max_drawdown_pct']:.2%}  "
          f"Sharpe={report['sharpe']}  Sortino={report['sortino']}")
    print(f"streaks: max_consec_wins={report['max_consecutive_wins']}  max_consec_losses={report['max_consecutive_losses']}")
    print("\nBy pair:")
    for k, v in report["by_pair"].items():
        print(f"  {k:8} n={v['n']:<4} WR={v['WR']:<6} totR={v['totR']}")
    print("\nBy session:")
    for k, v in report["by_session"].items():
        print(f"  {k:28} n={v['n']:<4} WR={v['WR']:<6} totR={v['totR']}")
    print("\nMonthly R:")
    for k, v in report["monthly_R"].items():
        print(f"  {k}: {v:+.2f}R")
