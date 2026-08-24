"""
Data splits. Defined ONCE, up front, before any parameter is touched.

The final holdout is never read by the optimizer, the sensitivity sweep, the
walk-forward runner or the strategy-selection step. It is opened once, after
the configuration is frozen.
"""
from __future__ import annotations

import pandas as pd

# Available real data: 2026-01-01 -> 2026-08-21 (7.7 months). That is SHORT.
# 6/2-month walk-forward as the spec describes needs multiple years; with this
# window we get one training block and two forward blocks, and we say so.
IN_SAMPLE = ("2026-01-01", "2026-05-31")       # optimise here only
VALIDATION = ("2026-05-31", "2026-07-11")      # ~6 weeks, model selection
HOLDOUT = ("2026-07-11", "2026-08-25")         # ~6 weeks, opened ONCE

WALK_FORWARD_TRAIN_DAYS = 75
WALK_FORWARD_TEST_DAYS = 25


def slice_df(df: pd.DataFrame, span: tuple[str, str]) -> pd.DataFrame:
    a = pd.Timestamp(span[0], tz="UTC")
    b = pd.Timestamp(span[1], tz="UTC")
    return df.loc[(df.index >= a) & (df.index < b)]


def walk_forward_windows(index: pd.DatetimeIndex,
                         train_days: int = WALK_FORWARD_TRAIN_DAYS,
                         test_days: int = WALK_FORWARD_TEST_DAYS,
                         step_days: int | None = None):
    """Rolling (train, test) date windows across the available history."""
    step = step_days or test_days
    start, end = index[0].normalize(), index[-1].normalize()
    out = []
    tr_start = start
    while True:
        tr_end = tr_start + pd.Timedelta(days=train_days)
        te_end = tr_end + pd.Timedelta(days=test_days)
        if te_end > end + pd.Timedelta(days=1):
            break
        out.append(((tr_start, tr_end), (tr_end, te_end)))
        tr_start = tr_start + pd.Timedelta(days=step)
    return out
