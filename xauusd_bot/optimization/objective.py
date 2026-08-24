"""
Composite optimisation objective (spec section 46).

Explicitly NOT "highest profit". Robustness terms dominate, and small samples,
concentrated profits and deep drawdowns are penalised.
"""
from __future__ import annotations

import numpy as np


def score(m: dict, min_trades: int = 25) -> float:
    n = m.get("trades", 0)
    if n == 0:
        return -10.0
    pf = m["profit_factor"]
    pf = 5.0 if not np.isfinite(pf) else min(pf, 5.0)
    exp_r = m["expectancy_r"]
    dd = max(m["max_dd_pct"], 0.25)
    wr = m["win_rate"] / 100.0

    s = 0.0
    s += 2.0 * np.tanh((pf - 1.0) * 1.2)            # out-of-sample PF, saturating
    s += 1.5 * np.tanh(exp_r * 4.0)                 # expectancy in R
    s += 1.0 * np.tanh(m["net_return_pct"] / dd / 3.0)   # return per unit of DD
    s += 0.5 * np.tanh((wr - 0.45) * 6.0)           # win rate, mildly rewarded
    s -= 1.2 * np.tanh(dd / 12.0)                   # drawdown penalty

    # sample-size penalty: an 8-trade "PF 6" result is noise, not an edge
    if n < min_trades:
        s *= n / min_trades
        s -= 0.5 * (1 - n / min_trades)

    # profit concentration penalty
    top5 = m.get("top5_pct_of_profit")
    if top5 is not None and np.isfinite(top5) and top5 > 60 and n > 10:
        s -= 0.5 * min((top5 - 60) / 40.0, 1.0)

    # month dependency penalty
    tm, pm = m.get("total_months", 0), m.get("positive_months", 0)
    if tm >= 3:
        s += 0.5 * (pm / tm - 0.5)
    return float(s)
