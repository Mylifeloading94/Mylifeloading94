"""Module 5 - market structure: last confirmed micro swing high and bullish MSS detection.
(Bearish logic is obtained by running the same code on mirrored prices.)"""
import numpy as np


def last_pivot_high(n, piv_highs):
    """Arrays (price, pivot_index) of the most recent micro pivot high confirmed at or before each bar."""
    price = np.full(n, np.nan); idx = np.full(n, -1, dtype=int); k = 0; cur = (np.nan, -1)
    for i in range(n):
        while k < len(piv_highs) and piv_highs[k][0] <= i:
            cur = (piv_highs[k][2], piv_highs[k][1]); k += 1
        price[i], idx[i] = cur
    return price, idx


def bullish_mss(c, i, level):
    """Close breaks above the micro swing high on this bar (fresh break, not a continuation)."""
    return level == level and c[i] > level and c[i - 1] <= level
