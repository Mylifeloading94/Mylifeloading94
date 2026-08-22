"""
LOCKED strategy configuration  (v2 - H4).

WHAT CHANGED FROM v1 AND WHY
----------------------------
v1 ran the signal on M15 and failed out of sample (-19.26%, PF 0.36). Two real
faults were found afterwards:

1. A DATA BUG. The daily EMA200 bias needs 200 daily bars of warm-up. The M15
   feed only reached back to Feb 2025, so only 32% of the v1 in-sample window
   had a usable daily bias, against 100% of the test window. In-sample and
   out-of-sample were effectively running DIFFERENT strategies, which is why
   selection did not transfer. Data now reaches back to 2023-06; both windows
   are at 100% coverage.

2. THE TIMEFRAME WAS WRONG FOR THE COST STRUCTURE. Round-trip cost is ~14% of
   the stop at M15, ~4% at H1, ~2% at H4. Measured in-sample median profit
   factor by signal timeframe:
        M15  0.735
        H1   0.785
        H4   1.413      <- and 100% of 240 H4 configurations beat PF 1.0
   The edge was always being eaten by costs, not absent.

The quality score also only starts working at H4. In-sample median PF by score
threshold is monotonic there (1.202 -> 1.365 -> 1.687 for thresholds 0/60/70),
where at M15 it was flat and out-of-sample slightly negative.

SELECTION DISCIPLINE
--------------------
Everything below was chosen on 2024-04-01 .. 2025-12-31 and frozen BEFORE the
2026 window was evaluated. Where a parameter could be pushed to flatter the
in-sample metric, the looser value was taken instead (see min_score and
min_rr_after_costs).
"""
import strategy as st
import backtest as bt

# Warm-up starts 2023-06; the daily EMA200 is fully warmed by 2024-04.
IS_START = "2024-04-01"
IS_END   = "2025-12-31 23:59"
OOS_START = "2026-01-01"
OOS_END   = "2026-08-22 23:59"


# Two validated modes. Both were confirmed by walk-forward; they trade the
# same signal and differ only in where the target sits.
#
#   "balanced"      target 1.0R -> 59.1% win rate, PF 1.36, +7.13%
#                   Chosen by the training data itself in 5 of 6 walk-forward
#                   cycles, so this is the evidence-backed default.
#   "high_win_rate" target 0.6R -> 70.8% win rate, PF 1.33, +4.35%
#                   Meets the brief's 70-90% win-rate target, at the cost of a
#                   0.51 reward-to-risk ratio and slightly lower net profit.
MODE = "balanced"

TARGET_R = {"balanced": 1.0, "high_win_rate": 0.6}


def locked_params(mode=None):
    p = st.default_params()

    # --- signal timeframe -------------------------------------------------
    p.tf_minutes = 240                # H4. Context = D1 / W1.

    # Intraday session filtering is meaningless on 4-hour bars.
    p.sessions = ((0, 24),)
    # In-sample prefers 12 bars (PF 1.568) but 40+ is a FLAT PLATEAU
    # (1.458 at every value from 40 to 400, because almost nothing exits on
    # time). A plateau is more trustworthy than a point optimum, so the
    # plateau is taken and one fitted parameter disappears.
    #
    # DISCLOSURE: this parameter was re-examined AFTER the 2026 window had
    # been run once, because time-exits were visibly carrying the loss there.
    # That re-examination was done on in-sample data only, but the 2026 split
    # has now been looked at twice and its status as a clean out-of-sample
    # test is correspondingly weaker. The walk-forward in walkforward.py --
    # which never reuses a window for both selection and evaluation -- is the
    # primary evidence for this build.
    p.time_stop_bars = 40

    # --- entry ------------------------------------------------------------
    p.entry_mode = "retrace"
    p.retr_frac = 0.62
    p.entry_expiry = 6

    # --- stop / target ----------------------------------------------------
    p.sl_atr_buffer = 0.5             # in-sample median PF 1.458 vs 1.321 at 1.0
    p.tp_r = TARGET_R[mode or MODE]
    p.tp1_frac = 0.0                  # partials measurably reduced expectancy
    p.breakeven_after_tp1 = False     # so did breakeven stops
    p.trail_atr = 0.0                 # trail arms at 1R, so it is inert at tp_r=1.0

    # --- trend filter -----------------------------------------------------
    # Keeping it: in-sample median PF 1.450 with vs 1.326 without, and a higher
    # worst case (1.163 vs 1.001).
    p.require_bias = True

    # --- gates ------------------------------------------------------------
    # Deliberately NOT tuned; at H4 the spread is a trivial share of the stop
    # and tightening this gate changed nothing (median PF 1.413 either way).
    p.max_spread_atr_hard = 0.45
    p.min_rr_after_costs = 0.30

    # In-sample threshold curve (n / win rate / profit factor):
    #     55 -> 132 / 61.4% / 1.510
    #     60 -> 126 / 61.9% / 1.547
    #     65 -> 108 / 63.0% / 1.624
    #     70 ->  82 / 63.4% / 1.685
    #     75 ->  52 / 63.5% / 1.719
    # PF keeps climbing as the threshold rises, so the tempting choice is 75.
    # 60 is taken instead: the LOOSEST value that still clears the brief's 60%
    # win-rate requirement, which keeps the largest sample and is the choice
    # least able to be accused of chasing the in-sample metric.
    p.min_score = 60
    p.min_rr_after_costs = min(0.30, p.tp_r * 0.5)
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
