"""
LOCKED strategy configuration.

Chosen on 2025 in-sample data (2025-03-01 .. 2025-12-31) BEFORE the 2026 test
window was ever evaluated. Selection rule was the robustness of the parameter
NEIGHBOURHOOD -- profit factor had to hold up across every quality threshold,
not peak at one of them -- rather than the single best in-sample cell.

Measured in-sample neighbourhood (tp_r 0.6 / sl_buffer 0.5 / retrace 0.62):
    profit factor 1.34 - 1.74 across all five score thresholds
    win rate ~76%, ~80-99 trades

The high-R:R family (tp_r 1.5-2.5) was REJECTED: its profit factor fell below
1.0 at some thresholds, i.e. it was not robust.

Read `REPORT.md` before trusting any of these numbers.
"""
import strategy as st
import backtest as bt

# In-sample (selection) and out-of-sample (reporting) windows.
IS_START = "2025-03-01"
IS_END   = "2025-12-31 23:59"
OOS_START = "2026-01-01"
OOS_END   = "2026-08-22 23:59"


def locked_params():
    p = st.default_params()

    # entry
    p.entry_mode = "retrace"
    p.retr_frac = 0.62
    p.entry_expiry = 6

    # stop / target
    p.sl_atr_buffer = 0.5
    p.tp_r = 0.6
    p.tp1_frac = 0.0                 # partials measurably hurt expectancy
    p.breakeven_after_tp1 = False    # so did breakeven stops
    p.time_stop_bars = 64

    # A 0.6R target cannot clear a 1.5 R:R gate, so the gate is re-based to
    # mean "round-trip cost may not eat more than half the target".
    #
    # This gate is an OVERFITTING TRAP and is deliberately NOT tuned. Measured
    # in-sample sensitivity:
    #     0.30 -> n=116  wr 75.9%  pf 1.54
    #     0.36 -> n= 85  wr 78.8%  pf 1.86
    #     0.40 -> n= 57  wr 82.5%  pf 2.39
    #     0.45 -> n= 26  wr 84.6%  pf 2.86
    #     0.50 -> n=  8  wr 100.0% pf  inf
    # Tightening it manufactures a spectacular win rate purely by shrinking
    # the sample. The LOOSEST value is taken on purpose: it keeps the largest
    # sample and is the one choice that cannot be accused of chasing the
    # in-sample metric.
    p.min_rr_after_costs = 0.30

    # The score's measured discriminating power in-sample is WEAK
    # (corr +0.065 with R). It is kept as an auditable gate and a light
    # filter, not as the source of the edge. Threshold set mid-range rather
    # than at the in-sample peak.
    p.min_score = 60
    return p


def locked_risk(start_balance=10_000.0):
    return bt.RiskConfig(
        start_balance=start_balance,
        risk_pct=0.005,
        risk_pct_gold=0.0035,
        max_daily_loss=0.02,
        max_concurrent=3,
        max_per_currency=2,
        max_consecutive_losses=4,
        max_trades_per_day=3,
    )
