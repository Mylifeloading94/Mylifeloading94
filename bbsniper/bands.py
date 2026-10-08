"""Module 7 - Bollinger logic (bullish form)."""
import numpy as np


def at_lower_extreme(i, l, lo, up, approach):
    """Price approaches (within `approach` x band width) or pierces the lower band."""
    return l[i] <= lo[i] + approach * (up[i] - lo[i])


def pierced_lower(i, l, lo):
    return l[i] <= lo[i]


def squeezed_recently(i, bw_pct, pct, bars=10):
    w = bw_pct[max(0, i - bars):i]
    return len(w) > 0 and np.nanmin(w) < pct


def band_breakout_up(i, c, up, h, rng):
    """Close outside the upper band AND above the consolidation high (buy-side liquidity taken)."""
    if i < rng: return None
    lvl = h[i - rng:i].max()
    return lvl if (c[i] > up[i] and c[i] > lvl) else None


def touched_mean(i, l, ema_f, mid):
    """Trend pullback into the EMA20 / middle band."""
    return l[i] <= max(ema_f[i], mid[i])
