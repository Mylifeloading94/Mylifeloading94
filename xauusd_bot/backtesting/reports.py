"""Full performance report (spec sections 37, 38, 47, 48)."""
from __future__ import annotations

import pandas as pd

from xauusd_bot.backtesting.metrics import breakdown, compute, render


def full_report(trades: pd.DataFrame, equity: pd.Series, initial_equity: float,
                title: str, extra: dict | None = None) -> str:
    m = compute(trades, equity, initial_equity)
    L = [render(m, title)]
    if m["trades"] == 0:
        return "\n".join(L)
    L.append("\n  Monthly P/L:")
    for k, v in m["monthly_pnl"].items():
        L.append(f"    {k}  ${v:+.2f}")
    L.append("\nSTRATEGY PERFORMANCE MATRIX")
    L.append(breakdown(trades, "strategy").to_string(index=False))
    L.append("\nREGIME PERFORMANCE")
    L.append(breakdown(trades, "regime").to_string(index=False))
    L.append("\nSESSION PERFORMANCE")
    L.append(breakdown(trades, "session").to_string(index=False))
    t = trades.copy()
    t["hour"] = pd.to_datetime(t["ts_open"]).dt.hour
    L.append("\nHOUR PERFORMANCE (UTC)")
    L.append(breakdown(t, "hour").sort_values("hour").to_string(index=False))
    L.append("\nSETUP-SCORE PERFORMANCE")
    t["score_bin"] = pd.cut(t["setup_score"], [0, 75, 80, 85, 90, 95, 101]).astype(str)
    L.append(breakdown(t, "score_bin").to_string(index=False))
    L.append("\nEXIT REASON")
    L.append(breakdown(trades, "exit_reason").to_string(index=False))
    L.append("\nDIRECTION")
    L.append(breakdown(trades, "direction").to_string(index=False))
    L.append("\nCOST IMPACT")
    L.append(f"  gross PF {m['gross_profit_factor']:.2f}  ->  net PF {m['profit_factor']:.2f}")
    L.append(f"  commission total   ${m['commission_total']:.2f}")
    L.append(f"  avg spread paid    ${m['avg_spread']:.3f} per trade "
             f"(cost ≈ ${m['avg_spread'] * trades['lots'].sum() * 100:.2f} across all lots)")
    L.append(f"  entry slippage     ${m['total_entry_slippage']:.2f} in price units")
    L.append(f"  exit slippage      ${m['total_exit_slippage']:.2f} in price units")
    L.append("\nPROFIT CONCENTRATION")
    L.append(f"  top 1 trade   {m['top1_pct_of_profit']:.1f}% of net profit")
    L.append(f"  top 5 trades  {m['top5_pct_of_profit']:.1f}%")
    L.append(f"  top 10 trades {m['top10_pct_of_profit']:.1f}%")
    L.append(f"  best month    {m['best_month_pct_of_profit']:.1f}%")
    if extra:
        L.append("\nADDITIONAL")
        for k, v in extra.items():
            L.append(f"  {k}: {v}")
    return "\n".join(L)
