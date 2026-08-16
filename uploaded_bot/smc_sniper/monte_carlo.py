"""
SMC Sniper — Monte Carlo Analysis (spec §21).

Resamples the historical trade R-multiples (bootstrap with replacement) to
estimate the DISTRIBUTION of outcomes the backtest's single realized path
doesn't show: expected/worst-case drawdown, losing-streak probability,
probability of recovering from a drawdown, and the spread of possible
returns. A 70%+ single-path backtest win rate is not, by itself, a reason
to trust the strategy — this is the check that's supposed to keep it
honest (§21: "should not be considered production-ready solely because the
backtest win rate exceeds 70%").
"""
from __future__ import annotations
import random
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class MonteCarloResult:
    n_simulations: int
    n_trades_per_sim: int
    starting_equity: float
    risk_pct: float
    median_final_equity: float
    p5_final_equity: float          # 5th percentile (bad-case)
    p95_final_equity: float         # 95th percentile (good-case)
    median_max_drawdown_pct: float
    worst_case_drawdown_pct: float  # 95th percentile of max drawdown
    prob_ruin: float                # fraction of sims breaching ruin_threshold_pct DD
    prob_losing_streak_geq: Dict[int, float]  # streak length -> probability of hitting it at least once
    prob_net_profitable: float


def _max_drawdown_pct(equity_curve: List[float]) -> float:
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    return max_dd


def _longest_losing_streak(r_series: List[float]) -> int:
    longest = cur = 0
    for r in r_series:
        if r < -0.05:
            cur += 1; longest = max(longest, cur)
        else:
            cur = 0
    return longest


def run_monte_carlo(
    historical_r: List[float],
    n_simulations: int = 5000,
    n_trades_per_sim: Optional[int] = None,
    starting_equity: float = 10_000.0,
    risk_pct: float = 0.02,
    ruin_threshold_pct: float = 0.20,
    streak_thresholds: Optional[List[int]] = None,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """Bootstrap-resample `historical_r` (the closed-trade R-multiples from
    a backtest or the live trade journal) into `n_simulations` alternate
    trade sequences of length `n_trades_per_sim` (defaults to the length of
    the historical sample) and summarize the resulting distribution."""
    if not historical_r:
        raise ValueError("historical_r is empty — nothing to resample")

    rng = random.Random(seed)
    n_trades_per_sim = n_trades_per_sim or len(historical_r)
    streak_thresholds = streak_thresholds or [2, 3, 4, 5]

    final_equities = []
    max_drawdowns = []
    streak_hits = {k: 0 for k in streak_thresholds}
    ruin_hits = 0
    profitable_hits = 0

    for _ in range(n_simulations):
        sample = [rng.choice(historical_r) for _ in range(n_trades_per_sim)]
        equity = starting_equity
        curve = [equity]
        for r in sample:
            equity *= (1 + r * risk_pct)
            curve.append(equity)
        final_equities.append(equity)

        dd = _max_drawdown_pct(curve)
        max_drawdowns.append(dd)
        if dd >= ruin_threshold_pct:
            ruin_hits += 1

        longest = _longest_losing_streak(sample)
        for k in streak_thresholds:
            if longest >= k:
                streak_hits[k] += 1

        if equity > starting_equity:
            profitable_hits += 1

    final_equities.sort()
    max_drawdowns.sort()

    def pct(sorted_list: List[float], p: float) -> float:
        idx = min(len(sorted_list) - 1, max(0, int(round(p * (len(sorted_list) - 1)))))
        return sorted_list[idx]

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades_per_sim=n_trades_per_sim,
        starting_equity=starting_equity,
        risk_pct=risk_pct,
        median_final_equity=round(pct(final_equities, 0.50), 2),
        p5_final_equity=round(pct(final_equities, 0.05), 2),
        p95_final_equity=round(pct(final_equities, 0.95), 2),
        median_max_drawdown_pct=round(pct(max_drawdowns, 0.50), 4),
        worst_case_drawdown_pct=round(pct(max_drawdowns, 0.95), 4),
        prob_ruin=round(ruin_hits / n_simulations, 4),
        prob_losing_streak_geq={k: round(v / n_simulations, 4) for k, v in streak_hits.items()},
        prob_net_profitable=round(profitable_hits / n_simulations, 4),
    )


def print_monte_carlo(result: MonteCarloResult) -> None:
    print(f"Monte Carlo — {result.n_simulations} sims x {result.n_trades_per_sim} trades, "
          f"${result.starting_equity:,.0f} start @ {result.risk_pct:.1%} risk/trade")
    print(f"  median final equity : ${result.median_final_equity:,.2f}")
    print(f"  5th pct (bad case)  : ${result.p5_final_equity:,.2f}")
    print(f"  95th pct (good case): ${result.p95_final_equity:,.2f}")
    print(f"  median max drawdown : {result.median_max_drawdown_pct:.2%}")
    print(f"  worst-case (p95) DD : {result.worst_case_drawdown_pct:.2%}")
    print(f"  P(ruin)             : {result.prob_ruin:.2%}")
    print(f"  P(net profitable)   : {result.prob_net_profitable:.2%}")
    print("  losing-streak probabilities:")
    for k, v in result.prob_losing_streak_geq.items():
        print(f"    P(>= {k} losses in a row): {v:.2%}")
