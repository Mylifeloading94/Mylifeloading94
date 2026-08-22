"""Performance statistics from a list of closed Trade objects."""
import numpy as np, pandas as pd

BARS_PER_YEAR = 252


def streaks(vals):
    """Longest run of wins and of losses."""
    best_w = best_l = cur_w = cur_l = 0
    for v in vals:
        if v > 0:
            cur_w += 1; cur_l = 0
        elif v < 0:
            cur_l += 1; cur_w = 0
        else:
            cur_w = cur_l = 0
        best_w = max(best_w, cur_w); best_l = max(best_l, cur_l)
    return best_w, best_l


def drawdown(equity):
    """Max drawdown in currency and percent from an equity series."""
    if len(equity) == 0:
        return 0.0, 0.0
    peak = equity.cummax()
    dd = equity - peak
    ddp = dd / peak
    return float(-dd.min()), float(-ddp.min() * 100)


def summarize(trades, start_balance, start, end, equity_curve=None):
    n = len(trades)
    if n == 0:
        return {"total_trades": 0, "start_balance": start_balance,
                "end_balance": start_balance, "net_profit": 0.0,
                "net_profit_pct": 0.0}

    trades = sorted(trades, key=lambda t: t.exit_time or t.entry_time)
    pnl = np.array([t.pnl for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gross_p, gross_l = wins.sum(), -losses.sum()

    if equity_curve is None or len(equity_curve) == 0:
        eq = pd.Series(start_balance + pnl.cumsum(),
                       index=[t.exit_time for t in trades])
    else:
        eq = equity_curve["equity"]

    end_balance = start_balance + pnl.sum()
    dd_abs, dd_pct = drawdown(eq)

    # daily returns for Sharpe / Sortino
    daily = eq.resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    sharpe = sortino = float("nan")
    if len(rets) > 5 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(BARS_PER_YEAR))
        downside = rets[rets < 0]
        if len(downside) > 1 and downside.std() > 0:
            sortino = float(rets.mean() / downside.std() * np.sqrt(BARS_PER_YEAR))

    durations = [
        (t.exit_time - t.entry_time).total_seconds() / 3600.0
        for t in trades if t.exit_time is not None
    ]
    days = max(1, len(pd.bdate_range(start, end)))
    w_streak, l_streak = streaks(pnl)
    rmults = np.array([t.r_multiple for t in trades])

    return {
        "start_balance": start_balance,
        "end_balance": end_balance,
        "net_profit": float(pnl.sum()),
        "net_profit_pct": float(pnl.sum() / start_balance * 100),
        "total_trades": n,
        "winning_trades": int((pnl > 0).sum()),
        "losing_trades": int((pnl < 0).sum()),
        "breakeven_trades": int((pnl == 0).sum()),
        "win_rate": float((pnl > 0).mean() * 100),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(gross_p / gross_l) if gross_l > 0 else float("inf"),
        "expectancy": float(pnl.mean()),
        "expectancy_r": float(rmults.mean()),
        "avg_rr": float(np.mean([t.planned_rr for t in trades])),
        "realized_rr": float(abs(wins.mean() / losses.mean())) if len(wins) and len(losses) else 0.0,
        "max_dd_abs": dd_abs,
        "max_dd_pct": dd_pct,
        "recovery_factor": float(pnl.sum() / dd_abs) if dd_abs > 0 else float("inf"),
        "sharpe": sharpe,
        "sortino": sortino,
        "largest_win": float(pnl.max()),
        "largest_loss": float(pnl.min()),
        "trading_days": days,
        "trades_per_day": n / days,
        "longest_win_streak": w_streak,
        "longest_loss_streak": l_streak,
        "avg_duration_hours": float(np.mean(durations)) if durations else 0.0,
    }


def monthly(trades, start_balance):
    if not trades:
        return pd.DataFrame()
    rows = [{"month": pd.Timestamp(t.exit_time).tz_convert(None).to_period("M"),
             "pnl": t.pnl, "win": t.pnl > 0, "time": t.exit_time}
            for t in sorted(trades, key=lambda x: x.exit_time)]
    df = pd.DataFrame(rows)
    out = []
    bal = start_balance
    for m, g in df.groupby("month", sort=True):
        p = g.pnl.values
        gp, gl = p[p > 0].sum(), -p[p < 0].sum()
        eq = pd.Series(bal + p.cumsum())
        peak = eq.cummax()
        dd = float(-(eq - peak).min())
        ddp = float(-((eq - peak) / peak).min() * 100)
        bal += p.sum()
        out.append({"month": str(m), "trades": len(p),
                    "win_rate": 100 * (p > 0).mean(),
                    "pnl": p.sum(),
                    "profit_factor": gp / gl if gl > 0 else float("inf"),
                    "max_dd": dd, "max_dd_pct": ddp,
                    "ending_balance": bal})
    return pd.DataFrame(out)
