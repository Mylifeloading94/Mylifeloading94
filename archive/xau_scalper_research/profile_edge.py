"""
Where does XAUUSD actually offer an edge?

!! ALIGNMENT WARNING - THIS MODULE PRODUCED A WRONG ANSWER ONCE !!
    `barrier_outcomes` fills at `entry_pos + 1`. If you pass the M1 position of
    an M5 bar's OPEN, you are entering ONE MINUTE INTO a bar whose CLOSE the
    features were computed from -- four minutes of look-ahead. That bug
    reported a 76% momentum edge on gold that does not exist; corrected, the
    same setups sit at the ~59% unconditional baseline with negative
    expectancy. Always pass the position of the signal bar's CLOSE.
    See README.md in this directory.

Walks every candidate entry forward over M1 bars and records which barrier is
touched first. Done unconditionally it gives the baseline (should be ~50% minus
costs); sliced by hour, session and volatility it shows whether any condition
is genuinely better than a coin flip.

Nothing is assumed about the strategy here. This is measurement first.
"""
import numpy as np
import pandas as pd

PIP = 0.10
SPREAD_PIPS = 3.0
SLIP_PIPS = 0.5


def forward_matrix(arr, starts, width):
    """(len(starts), width) matrix of arr[s : s+width], zero-padded at the end."""
    n = len(arr)
    idx = starts[:, None] + np.arange(width)[None, :]
    valid = idx < n
    idx = np.clip(idx, 0, n - 1)
    return arr[idx], valid


def barrier_outcomes(m1, entry_pos, tp_px, sl_px, direction, max_bars, chunk=20000):
    """First-touch outcome for each entry.

    Returns (result, bars) where result is +1 target, -1 stop, 0 neither
    within `max_bars`. A bar spanning both barriers counts as a STOP, since
    intrabar order cannot be recovered from OHLC.
    """
    o = m1["open"].values.astype(np.float64)
    h = m1["high"].values.astype(np.float64)
    l = m1["low"].values.astype(np.float64)
    n = len(o)

    entry_pos = entry_pos[entry_pos + 1 + max_bars < n]
    fill = entry_pos + 1
    cost = (SPREAD_PIPS / 2 + SLIP_PIPS) * PIP
    entry_px = o[fill] + direction * cost

    res = np.zeros(len(fill), dtype=np.int8)
    bars = np.full(len(fill), max_bars, dtype=np.int32)

    for a in range(0, len(fill), chunk):
        b = min(a + chunk, len(fill))
        s = fill[a:b]
        H, _ = forward_matrix(h, s, max_bars)
        L, _ = forward_matrix(l, s, max_bars)
        e = entry_px[a:b][:, None]
        if direction > 0:
            hit_tp = H >= (e + tp_px)
            hit_sl = L <= (e - sl_px)
        else:
            hit_tp = L <= (e - tp_px)
            hit_sl = H >= (e + sl_px)

        first_tp = np.where(hit_tp.any(1), hit_tp.argmax(1), max_bars + 1)
        first_sl = np.where(hit_sl.any(1), hit_sl.argmax(1), max_bars + 1)
        # ties (same bar) resolve against us
        r = np.where(first_sl <= first_tp, -1, 1).astype(np.int8)
        r[(first_tp > max_bars) & (first_sl > max_bars)] = 0
        res[a:b] = r
        bars[a:b] = np.minimum(first_tp, first_sl).clip(0, max_bars)
    return entry_pos, res, bars, entry_px


def summarise(res):
    n = len(res)
    if n == 0:
        return dict(n=0, wr=np.nan, tp=0, sl=0, none=0)
    tp = int((res == 1).sum()); sl = int((res == -1).sum()); nz = int((res == 0).sum())
    dec = tp + sl
    return dict(n=n, wr=100 * tp / dec if dec else np.nan, tp=tp, sl=sl, none=nz)


def expectancy(res, tp_px, sl_px):
    """R-multiple expectancy, timeouts marked flat."""
    r = np.where(res == 1, tp_px / sl_px, np.where(res == -1, -1.0, 0.0))
    return r.mean(), r
