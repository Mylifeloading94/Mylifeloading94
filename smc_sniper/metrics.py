"""Performance metrics and bootstrap confidence intervals.

Every headline number the reports quote is computed here, once. Win rate is
counted on **net** R (costs included), and a trade that scratches to exactly
zero counts as a loss, not a win -- the conservative convention.

Bootstrap CIs are included because a point win rate on 100-300 trades is close
to meaningless on its own. This repo's history contains a 70% that was really
45%; a confidence interval makes that kind of gap visible instead of arguable.
"""
from __future__ import annotations

from statistics import NormalDist

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

    # v5 AUDIT. A break-even exit is a SCRATCH, and this engine books it as a
    # win because it lands a hair above zero (stop moved to entry + 0.05R, less
    # slippage). Measured on the v2 swing ledger: 7 of 153 trades exit at
    # +0.010R to +0.045R having banked no partial at all -- price tagged +1R
    # intrabar, which is enough to trigger the break-even move but not enough
    # to reach a TP1 that sits further out, and the position then scratched.
    # With a +/-0.10R scratch band the v2 swing ledger holds 10 such trades
    # (7 booked as wins, 3 as losses) and the headline win rate goes from
    # 54.90% to 53.85% -- an inflation of about one point, not the ~15 points
    # the same defect class was worth in the uploaded bot, because here the
    # partial P/L is genuinely realised rather than assumed.
    #
    # The P/L is honest (each of those trades really did make a few dollars),
    # so `win_rate` is left alone and the scratch-adjusted figure is reported
    # NEXT TO it rather than instead of it. A flat-R configuration with
    # management stripped off has no scratch band at all, which is one reason
    # to prefer one when a win rate is going to be quoted.
    scratch_band = 0.10
    scratches = np.abs(r) < scratch_band
    decisive = ~scratches

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
        "scratches": int(scratches.sum()),
        "win_rate_ex_scratch": float(_safe((wins & decisive).sum(),
                                           decisive.sum()) * 100),
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


# ---------------------------------------------------------------------------
# Multiple-testing correction: the Probabilistic and Deflated Sharpe Ratios
# ---------------------------------------------------------------------------
# ADDED IN v7, from outside research rather than from this repo's own habits.
#
# Bailey, D. H. & Lopez de Prado, M. (2014), "The Deflated Sharpe Ratio:
# Correcting for Selection Bias, Backtest Overfitting, and Non-Normality",
# Journal of Portfolio Management 40(5), 94-107.
#   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
# and Bailey, Borwein, Lopez de Prado & Zhu (2014), "The Probability of
# Backtest Overfitting", https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
#
# WHY IT BELONGS HERE. This repo already prices correlation (the cluster
# bootstrap) and already refuses to select on the full window. It does NOT
# price the one remaining source of optimism: **the number of configurations
# that were measured before one was kept.** Several hundred variants have been
# scored across v2-v7. The maximum of several hundred noisy Sharpe estimates is
# well above zero even when every one of them has zero true edge, and the
# ordinary interval says nothing about that. The DSR is the standard correction
# and it is applied here to the per-trade R series, where the "return period"
# is one trade.
#
# It is expected to be unflattering. That is the point of running it.
EULER_MASCHERONI = 0.5772156649015329


def sharpe_stats(returns) -> dict:
    """Per-observation Sharpe and the higher moments the PSR needs."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return {"n": n, "sr": float("nan"), "skew": float("nan"),
                "kurt": float("nan"), "se": float("nan")}
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    sr = mu / sd if sd > 0 else float("nan")
    z = (r - mu) / sd if sd > 0 else r * 0.0
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())          # NON-excess kurtosis, per the paper
    # Mertens / Lo standard error of the Sharpe estimator under non-normality.
    var = (1.0 - skew * sr + 0.25 * (kurt - 1.0) * sr ** 2) / (n - 1)
    return {"n": n, "sr": sr, "skew": skew, "kurt": kurt,
            "se": float(np.sqrt(var)) if var > 0 else float("nan")}


def probabilistic_sharpe(returns, benchmark_sr: float = 0.0) -> float:
    """P(true Sharpe > benchmark), corrected for skew, kurtosis and sample size."""
    st = sharpe_stats(returns)
    if not np.isfinite(st["sr"]) or not np.isfinite(st["se"]) or st["se"] <= 0:
        return float("nan")
    return float(NormalDist().cdf((st["sr"] - benchmark_sr) / st["se"]))


def expected_max_sharpe(n_trials: int, trial_sr_std: float) -> float:
    """E[max SR] over `n_trials` independent zero-skill trials.

    Bailey & Lopez de Prado's approximation:
        E[max] ~ sd(SR_k) * [ (1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N*e)) ]
    with g the Euler-Mascheroni constant. `trial_sr_std` is the dispersion of
    the Sharpe estimates ACROSS the trials that were actually run -- a strategy
    search over near-identical variants has a small dispersion and is deflated
    less than one that ranged widely.
    """
    nd = NormalDist()
    n = max(int(n_trials), 2)
    g = EULER_MASCHERONI
    maxz = ((1.0 - g) * nd.inv_cdf(1.0 - 1.0 / n)
            + g * nd.inv_cdf(1.0 - 1.0 / (n * np.e)))
    return float(trial_sr_std * maxz)


def deflated_sharpe(returns, n_trials: int, trial_sr_std: float) -> dict:
    """DSR = PSR evaluated against the Sharpe a zero-skill search would produce.

    Returns the components as well as the probability, because the components
    are what make the number auditable: a DSR of 0.6 on 400 trials means
    something different from a DSR of 0.6 on 4.
    """
    st = sharpe_stats(returns)
    sr0 = expected_max_sharpe(n_trials, trial_sr_std)
    return {**st, "n_trials": int(n_trials), "trial_sr_std": float(trial_sr_std),
            "sr0": sr0, "psr_vs_zero": probabilistic_sharpe(returns, 0.0),
            "dsr": probabilistic_sharpe(returns, sr0)}
