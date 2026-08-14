"""Performance metrics and bootstrap confidence intervals.

Every headline number the reports quote is computed here, once. Win rate is
counted on **net** R (costs included), and a trade that scratches to exactly
zero counts as a loss, not a win -- the conservative convention.

Bootstrap CIs are included because a point win rate on 100-300 trades is close
to meaningless on its own. This repo's history contains a 70% that was really
45%; a confidence interval makes that kind of gap visible instead of arguable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe(numer: float, denom: float, default: float = 0.0) -> float:
    return numer / denom if denom else default


def compute_metrics(trades: pd.DataFrame, starting_balance: float = 10000.0) -> dict:
    """Full metric set for a trade frame."""
    if trades is None or trades.empty:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_r": 0.0,
                "net_profit": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0,
                "sortino": 0.0, "avg_r": 0.0}

    r = trades["r_multiple"].values.astype(float)
    pnl = trades["pnl"].values.astype(float)
    wins = r > 0
    losses = ~wins

    gross_win = pnl[wins].sum()
    gross_loss = -pnl[losses].sum()

    equity = starting_balance + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[starting_balance], equity]))
    dd = (np.concatenate([[starting_balance], equity]) - peak) / peak
    max_dd = float(-dd.min() * 100)

    # R-based Sharpe/Sortino (per-trade, then annualised by trade frequency).
    if len(trades) > 1:
        span_days = max((pd.to_datetime(trades["exit_time"]).max()
                         - pd.to_datetime(trades["exit_time"]).min()).days, 1)
        per_year = len(trades) * 365.0 / span_days
    else:
        per_year = 1.0
    std = r.std(ddof=1) if len(r) > 1 else 0.0
    downside = r[r < 0].std(ddof=1) if (r < 0).sum() > 1 else 0.0
    sharpe = float(_safe(r.mean(), std) * np.sqrt(per_year)) if std else 0.0
    sortino = float(_safe(r.mean(), downside) * np.sqrt(per_year)) if downside else 0.0

    streak_w = streak_l = best_w = best_l = 0
    for won in wins:
        if won:
            streak_w += 1
            streak_l = 0
        else:
            streak_l += 1
            streak_w = 0
        best_w = max(best_w, streak_w)
        best_l = max(best_l, streak_l)

    return {
        "trades": int(len(trades)),
        "wins": int(wins.sum()),
        "losses": int(losses.sum()),
        "win_rate": float(wins.mean() * 100),
        "loss_rate": float(losses.mean() * 100),
        "profit_factor": float(_safe(gross_win, gross_loss, float("inf") if gross_win else 0.0)),
        "net_profit": float(pnl.sum()),
        "net_profit_pct": float(pnl.sum() / starting_balance * 100),
        "expectancy_r": float(r.mean()),
        "avg_r": float(r.mean()),
        "total_r": float(r.sum()),
        "avg_winner_r": float(r[wins].mean()) if wins.any() else 0.0,
        "avg_loser_r": float(r[losses].mean()) if losses.any() else 0.0,
        "avg_winner": float(pnl[wins].mean()) if wins.any() else 0.0,
        "avg_loser": float(pnl[losses].mean()) if losses.any() else 0.0,
        "max_consecutive_wins": int(best_w),
        "max_consecutive_losses": int(best_l),
        "max_drawdown_pct": max_dd,
        "sharpe": sharpe,
        "sortino": sortino,
        "avg_rr_planned": float(trades["rr_tp2"].mean()) if "rr_tp2" in trades else 0.0,
        "avg_bars_held": float(trades["bars_held"].mean()) if "bars_held" in trades else 0.0,
        "final_balance": float(starting_balance + pnl.sum()),
    }


def bootstrap_ci(values: np.ndarray, statistic="mean", iterations: int = 5000,
                 ci: float = 0.95, seed: int = 7) -> tuple[float, float]:
    """Percentile bootstrap CI for a per-trade statistic."""
    values = np.asarray(values, dtype=float)
    if len(values) < 5:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(iterations, len(values)))
    samples = values[idx]
    stat = samples.mean(axis=1) if statistic == "mean" else (samples > 0).mean(axis=1) * 100
    lo = (1 - ci) / 2 * 100
    return float(np.percentile(stat, lo)), float(np.percentile(stat, 100 - lo))


def win_rate_ci(trades: pd.DataFrame, iterations: int = 5000,
                ci: float = 0.95) -> tuple[float, float]:
    if trades is None or trades.empty:
        return (float("nan"), float("nan"))
    return bootstrap_ci(trades["r_multiple"].values, "win_rate", iterations, ci)


def expectancy_ci(trades: pd.DataFrame, iterations: int = 5000,
                  ci: float = 0.95) -> tuple[float, float]:
    if trades is None or trades.empty:
        return (float("nan"), float("nan"))
    return bootstrap_ci(trades["r_multiple"].values, "mean", iterations, ci)


def breakdown(trades: pd.DataFrame, by: str, starting_balance: float = 10000.0) -> pd.DataFrame:
    """Per-group metrics (pair, session, setup_type, ...)."""
    if trades is None or trades.empty or by not in trades:
        return pd.DataFrame()
    rows = []
    for key, group in trades.groupby(by):
        m = compute_metrics(group, starting_balance)
        rows.append({by: key, "trades": m["trades"], "win_rate": round(m["win_rate"], 2),
                     "profit_factor": round(m["profit_factor"], 3),
                     "expectancy_r": round(m["expectancy_r"], 4),
                     "total_r": round(m["total_r"], 2),
                     "net_profit": round(m["net_profit"], 2),
                     "max_dd_pct": round(m["max_drawdown_pct"], 2)})
    return pd.DataFrame(rows).sort_values("expectancy_r", ascending=False).reset_index(drop=True)


def periodic(trades: pd.DataFrame, freq: str = "ME",
             starting_balance: float = 10000.0) -> pd.DataFrame:
    """Monthly (``ME``) or weekly (``W``) performance."""
    if trades is None or trades.empty:
        return pd.DataFrame()
    frame = trades.copy()
    frame["exit_time"] = pd.to_datetime(frame["exit_time"])
    rows = []
    for period, group in frame.groupby(pd.Grouper(key="exit_time", freq=freq)):
        if group.empty:
            continue
        m = compute_metrics(group, starting_balance)
        rows.append({"period": str(period.date()), "trades": m["trades"],
                     "win_rate": round(m["win_rate"], 2),
                     "profit_factor": round(m["profit_factor"], 3),
                     "total_r": round(m["total_r"], 3),
                     "net_profit": round(m["net_profit"], 2)})
    return pd.DataFrame(rows)


def equity_curve(trades: pd.DataFrame, starting_balance: float = 10000.0) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    frame = trades[["exit_time", "pnl", "r_multiple"]].copy()
    frame["equity"] = starting_balance + frame["pnl"].cumsum()
    frame["cum_r"] = frame["r_multiple"].cumsum()
    peak = frame["equity"].cummax()
    frame["drawdown_pct"] = (frame["equity"] - peak) / peak * 100
    return frame
