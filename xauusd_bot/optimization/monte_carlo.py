"""
Monte Carlo on realised trades: resequencing, cost shocks, missed trades and
R-value perturbation. Answers "how bad could the same edge have felt?"
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def simulate(trades: pd.DataFrame, initial_equity: float, n: int = 5000,
             miss_prob: float = 0.10, cost_shock_r: float = 0.10,
             r_noise: float = 0.10, seed: int = 7) -> dict:
    if trades is None or trades.empty:
        return {"runs": 0}
    rng = np.random.default_rng(seed)
    r = trades["r_multiple"].values.astype(float)
    risk = trades["risk_money"].values.astype(float)
    base_risk = float(np.median(risk)) if len(risk) else initial_equity * 0.005
    k = len(r)

    finals, dds, streaks, ruined = [], [], [], 0
    for _ in range(n):
        order = rng.permutation(k)
        rr = r[order].copy()
        # randomly miss trades (latency, spread, being flat)
        keep = rng.random(k) > miss_prob
        rr = rr[keep]
        if len(rr) == 0:
            continue
        # extra cost per trade (worse spread/slippage than modelled) + R noise
        rr = rr - cost_shock_r * rng.random(len(rr))
        rr = rr * (1.0 + r_noise * rng.standard_normal(len(rr)))

        eq = initial_equity
        peak, mdd, cl, mcl = eq, 0.0, 0, 0
        for x in rr:
            eq += x * base_risk
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak)
            cl = cl + 1 if x < 0 else 0
            mcl = max(mcl, cl)
            if eq <= initial_equity * 0.5:
                ruined += 1
                break
        finals.append(eq); dds.append(100 * mdd); streaks.append(mcl)

    finals, dds = np.array(finals), np.array(dds)
    return {
        "runs": len(finals),
        "median_final": float(np.median(finals)),
        "p05_final": float(np.percentile(finals, 5)),
        "p95_final": float(np.percentile(finals, 95)),
        "prob_profit": float((finals > initial_equity).mean()),
        "median_max_dd_pct": float(np.median(dds)),
        "p95_max_dd_pct": float(np.percentile(dds, 95)),
        "worst_max_dd_pct": float(dds.max()),
        "median_losing_streak": float(np.median(streaks)),
        "worst_losing_streak": int(np.max(streaks)),
        "prob_ruin_50pct": ruined / max(1, n),
    }
