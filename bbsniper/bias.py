"""Module 3 - higher-timeframe bias (15M by default). +1 bullish, -1 bearish, 0 neutral."""
import numpy as np


def bias(bars, ind, slope_bars=3):
    c, ef, es = bars["c"], ind["ema_f"], ind["ema_s"]
    rising = np.r_[np.zeros(slope_bars, bool), ef[slope_bars:] > ef[:-slope_bars]]
    falling = np.r_[np.zeros(slope_bars, bool), ef[slope_bars:] < ef[:-slope_bars]]
    b = np.zeros(len(c), dtype=int)
    b[(c > es) & (ef > es)] = 1
    b[(c < es) & (ef < es)] = -1
    return b, rising, falling          # slope is a "preferably" condition: reported, not required


def trend(bars, ind):
    """Setup-timeframe trend used for the +1 '5M aligned' point."""
    c, ef, es = bars["c"], ind["ema_f"], ind["ema_s"]
    t = np.zeros(len(c), dtype=int); t[(ef > es) & (c > ef)] = 1; t[(ef < es) & (c < ef)] = -1
    return t
