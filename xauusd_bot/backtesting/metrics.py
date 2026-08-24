"""Performance analytics. Everything the spec's section 37 asks for."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe(x, d=0.0):
    return d if (x is None or (isinstance(x, float) and not np.isfinite(x))) else x


def compute(trades: pd.DataFrame, equity: pd.Series, initial_equity: float) -> dict:
    m: dict = {"trades": 0}
    if trades is None or trades.empty:
        m.update({"win_rate": 0, "profit_factor": 0, "net_return_pct": 0,
                  "max_dd_pct": 0, "expectancy_r": 0, "final_equity": initial_equity})
        return m

    t = trades.copy()
    pnl = t["pnl"]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()

    m["trades"] = len(t)
    m["wins"] = int((pnl > 0).sum())
    m["losses"] = int((pnl < 0).sum())
    m["scratches"] = int((pnl == 0).sum())
    m["win_rate"] = 100.0 * m["wins"] / m["trades"]
    m["loss_rate"] = 100.0 * m["losses"] / m["trades"]
    m["profit_factor"] = _safe(gross_win / gross_loss if gross_loss > 0 else np.inf, 0)
    m["gross_profit"] = float(gross_win)
    m["gross_loss"] = float(gross_loss)
    m["net_profit"] = float(pnl.sum())
    m["commission_total"] = float(t["commission"].sum())
    # gross PF = before commission (spread/slippage are inside the fill prices)
    gross_pnl = pnl + t["commission"]
    gw2 = gross_pnl[gross_pnl > 0].sum(); gl2 = -gross_pnl[gross_pnl < 0].sum()
    m["gross_profit_factor"] = _safe(gw2 / gl2 if gl2 > 0 else np.inf, 0)
    m["net_profit_factor"] = m["profit_factor"]

    m["final_equity"] = float(equity.iloc[-1])
    m["net_return_pct"] = 100.0 * (m["final_equity"] - initial_equity) / initial_equity

    eq = equity.dropna()
    peak = eq.cummax()
    dd = (peak - eq) / peak
    m["max_dd_pct"] = float(100 * dd.max())
    m["avg_dd_pct"] = float(100 * dd[dd > 0].mean()) if (dd > 0).any() else 0.0
    m["recovery_factor"] = _safe(m["net_return_pct"] / m["max_dd_pct"] if m["max_dd_pct"] > 0 else np.inf, 0)

    r = t["r_multiple"]
    m["expectancy_r"] = float(r.mean())
    m["expectancy_money"] = float(pnl.mean())
    m["avg_r"] = float(r.mean())
    m["avg_winner"] = float(wins.mean()) if len(wins) else 0.0
    m["avg_loser"] = float(losses.mean()) if len(losses) else 0.0
    m["avg_winner_r"] = float(r[r > 0].mean()) if (r > 0).any() else 0.0
    m["avg_loser_r"] = float(r[r < 0].mean()) if (r < 0).any() else 0.0
    m["largest_winner"] = float(pnl.max())
    m["largest_loser"] = float(pnl.min())
    m["payoff_ratio"] = _safe(abs(m["avg_winner"] / m["avg_loser"]) if m["avg_loser"] else np.inf, 0)

    streak_w = streak_l = bw = bl = 0
    for p in pnl:
        if p > 0:
            streak_w += 1; streak_l = 0
        elif p < 0:
            streak_l += 1; streak_w = 0
        bw, bl = max(bw, streak_w), max(bl, streak_l)
    m["max_win_streak"], m["max_loss_streak"] = bw, bl

    # daily returns from the equity curve (trading days only)
    daily = eq.resample("1D").last().dropna()
    dret = daily.pct_change().dropna()
    if len(dret) > 2 and dret.std() > 0:
        m["sharpe"] = float(np.sqrt(252) * dret.mean() / dret.std())
        downside = dret[dret < 0]
        m["sortino"] = float(np.sqrt(252) * dret.mean() / downside.std()) \
            if len(downside) > 1 and downside.std() > 0 else float("inf")
    else:
        m["sharpe"] = m["sortino"] = 0.0
    m["trading_days"] = int(t["ts_open"].dt.date.nunique())
    span_days = max(1, (t["ts_close"].max() - t["ts_open"].min()).days)
    m["trades_per_day"] = m["trades"] / max(1, m["trading_days"])
    m["calendar_days"] = span_days

    # profit concentration (spec section 47)
    sp = pnl.sort_values(ascending=False)
    net = m["net_profit"]
    if net > 0:
        m["top1_pct_of_profit"] = float(100 * sp.iloc[0] / net)
        m["top5_pct_of_profit"] = float(100 * sp.iloc[:5].sum() / net)
        m["top10_pct_of_profit"] = float(100 * sp.iloc[:10].sum() / net)
    else:
        m["top1_pct_of_profit"] = m["top5_pct_of_profit"] = m["top10_pct_of_profit"] = np.nan

    monthly = t.set_index("ts_close")["pnl"].resample("ME").sum()
    m["monthly_pnl"] = {str(k.date()): round(v, 2) for k, v in monthly.items()}
    m["positive_months"] = int((monthly > 0).sum())
    m["total_months"] = int(len(monthly))
    if net > 0 and len(monthly):
        m["best_month_pct_of_profit"] = float(100 * monthly.max() / net)
    else:
        m["best_month_pct_of_profit"] = np.nan

    m["long_trades"] = int((t["direction"] == "LONG").sum())
    m["short_trades"] = int((t["direction"] == "SHORT").sum())
    m["long_win_rate"] = float(100 * (t[t.direction == "LONG"]["pnl"] > 0).mean()) if m["long_trades"] else 0
    m["short_win_rate"] = float(100 * (t[t.direction == "SHORT"]["pnl"] > 0).mean()) if m["short_trades"] else 0
    m["avg_mfe_r"] = float(t["mfe_r"].mean())
    m["avg_mae_r"] = float(t["mae_r"].mean())
    m["avg_hold_min"] = float(t["bars_held"].mean())
    m["avg_spread"] = float(t["spread"].mean())
    m["total_entry_slippage"] = float(t["entry_slippage"].sum())
    m["total_exit_slippage"] = float(t["exit_slippage"].sum())
    return m


def breakdown(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    if trades is None or trades.empty or by not in trades.columns:
        return pd.DataFrame()
    g = trades.groupby(by)
    rows = []
    for k, d in g:
        p = d["pnl"]
        gw, gl = p[p > 0].sum(), -p[p < 0].sum()
        rows.append({
            by: k, "trades": len(d),
            "win%": round(100 * (p > 0).mean(), 1),
            "PF": round(gw / gl, 2) if gl > 0 else np.inf,
            "net": round(p.sum(), 2),
            "avg_R": round(d["r_multiple"].mean(), 3),
            "exp_$": round(p.mean(), 3),
        })
    return pd.DataFrame(rows).sort_values("trades", ascending=False).reset_index(drop=True)


def render(m: dict, title: str = "PERFORMANCE") -> str:
    if m["trades"] == 0:
        return f"{title}\n  NO TRADES\n"
    pf = m["profit_factor"]
    L = [title, "=" * len(title),
         f"  Trades                {m['trades']}   ({m['trades_per_day']:.2f}/trading day, "
         f"{m['trading_days']} active days)",
         f"  Win rate              {m['win_rate']:.1f}%   ({m['wins']}W / {m['losses']}L)",
         f"  Profit factor (net)   {pf:.2f}      gross {m['gross_profit_factor']:.2f}",
         f"  Net P/L               ${m['net_profit']:.2f}   ({m['net_return_pct']:+.2f}%)",
         f"  Final equity          ${m['final_equity']:.2f}",
         f"  Max drawdown          {m['max_dd_pct']:.2f}%    avg DD {m['avg_dd_pct']:.2f}%",
         f"  Recovery factor       {m['recovery_factor']:.2f}",
         f"  Expectancy            {m['expectancy_r']:+.3f}R   (${m['expectancy_money']:+.3f}/trade)",
         f"  Avg winner / loser    ${m['avg_winner']:.2f} / ${m['avg_loser']:.2f}   "
         f"payoff {m['payoff_ratio']:.2f}",
         f"  Avg R  win / loss     {m['avg_winner_r']:+.2f}R / {m['avg_loser_r']:+.2f}R",
         f"  Largest win / loss    ${m['largest_winner']:.2f} / ${m['largest_loser']:.2f}",
         f"  Max streak  W / L     {m['max_win_streak']} / {m['max_loss_streak']}",
         f"  Sharpe / Sortino      {m['sharpe']:.2f} / {m['sortino']:.2f}",
         f"  Long / Short          {m['long_trades']} ({m['long_win_rate']:.0f}% win) / "
         f"{m['short_trades']} ({m['short_win_rate']:.0f}% win)",
         f"  Avg MFE / MAE         {m['avg_mfe_r']:.2f}R / {m['avg_mae_r']:.2f}R",
         f"  Avg hold              {m['avg_hold_min']:.0f} min",
         f"  Profit concentration  top1 {m['top1_pct_of_profit']:.1f}%  "
         f"top5 {m['top5_pct_of_profit']:.1f}%  top10 {m['top10_pct_of_profit']:.1f}%",
         f"  Positive months       {m['positive_months']}/{m['total_months']}",
         f"  Costs                 commission ${m['commission_total']:.2f}, "
         f"avg spread ${m['avg_spread']:.3f}"]
    return "\n".join(L)
