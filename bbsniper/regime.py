"""Module 2 - market regime (computed on the setup timeframe).
Codes: 2 trending up, -2 trending down, 0 ranging, 1 transitional, 3 squeeze, 4 expanding."""
import numpy as np

NAMES = {2: "TRENDING UP", -2: "TRENDING DOWN", 0: "RANGING", 1: "TRANSITIONAL", 3: "SQUEEZE", 4: "EXPANDING"}


def classify(bars, ind, cfg):
    c, adx, ef, es, bwp, bw = bars["c"], ind["adx"], ind["ema_f"], ind["ema_s"], ind["bw_pct"], ind["bw"]
    n = len(c); code = np.ones(n, dtype=int)
    bw_rising = np.r_[False, bw[1:] > bw[:-1]]
    code[adx < cfg["adx_weak"]] = 0
    code[(bwp > cfg["expand_pct"]) & bw_rising & (adx < cfg["adx_trend"])] = 4
    up = (adx > cfg["adx_trend"]) & (ef > es) & (c > es)
    dn = (adx > cfg["adx_trend"]) & (ef < es) & (c < es)
    code[up] = 2; code[dn] = -2
    code[(bwp < cfg["squeeze_pct"]) & (adx < cfg["adx_trend"])] = 3
    code[np.isnan(adx) | np.isnan(bwp)] = 1
    return code
