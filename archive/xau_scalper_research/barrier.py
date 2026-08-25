"""
Barrier profiling for XAUUSD — the empirical foundation for the scalper.

For a candidate entry at time t, walk FORWARD over M1 bars and record which
barrier price touches first: +tp or -sl. Doing this over every bar, sliced by
hour / volatility regime / setup condition, shows where gold actually offers a
directional edge, instead of assuming a strategy and hoping.

Conventions (stated explicitly because gold pip usage varies):
    1 pip = $0.10        -> 25 pips = $2.50
    contract = 100 oz    -> $1.00 move = $100 per standard lot
    spread modelled at 3.0 pips ($0.30), charged on entry
"""
import numpy as np
import pandas as pd

PIP = 0.10
SPREAD_PIPS = 3.0
SLIP_PIPS = 0.5


def first_touch(m1_high, m1_low, start_idx, entry, tp, sl, direction, max_bars):
    """Which barrier is hit first from `start_idx`? +1 tp, -1 sl, 0 neither.

    Resolved on M1 bars. When a single M1 bar spans both barriers the result is
    recorded as a LOSS -- the conservative reading, since intrabar order is
    unknowable.
    """
    n = len(m1_high)
    stop_lvl = entry - direction * sl
    tp_lvl = entry + direction * tp
    end = min(n, start_idx + max_bars)
    for k in range(start_idx, end):
        hi, lo = m1_high[k], m1_low[k]
        if direction > 0:
            hit_sl = lo <= stop_lvl
            hit_tp = hi >= tp_lvl
        else:
            hit_sl = hi >= stop_lvl
            hit_tp = lo <= tp_lvl
        if hit_sl:
            return -1, k - start_idx
        if hit_tp:
            return 1, k - start_idx
    return 0, end - start_idx


def scan(m1, entries, tp_px, sl_px, direction, max_bars):
    """Vectorised-ish barrier scan over a list of positional entry indices."""
    h = m1["high"].values.astype(float)
    l = m1["low"].values.astype(float)
    o = m1["open"].values.astype(float)
    out = []
    cost = (SPREAD_PIPS / 2 + SLIP_PIPS) * PIP
    for i in entries:
        if i + 1 >= len(o):
            continue
        entry = o[i + 1] + direction * cost      # fill next bar, pay the spread
        res, bars = first_touch(h, l, i + 1, entry, tp_px, sl_px, direction, max_bars)
        out.append((i, res, bars, entry))
    return out
