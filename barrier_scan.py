"""
Does ANYTHING in the feature set predict gold's direction?

Triple-barrier labelling: symmetric barriers at +/- k*ATR, record which is
touched first within the horizon. P(up first) = 50% means no directional
information. Exit-independent and COST-INDEPENDENT, so it isolates the only
question that matters: is there an edge to harvest at all?

Processed year by year and accumulated, so memory stays flat.
"""
import sys; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from collections import defaultdict
from xauusd_bot.config import Config
from xauusd_bot.strategy.regime_engine import classify

H, K = 120, 1.0
YEARS = list(range(2015, 2027))
ERA = {y: ("cheap" if y >= 2024 else "expensive") for y in YEARS}

acc = defaultdict(lambda: [0, 0])
acc_era = defaultdict(lambda: defaultdict(lambda: [0, 0]))

def label_year(F):
    close = F['close'].values.astype(np.float64)
    high = F['high'].values.astype(np.float64)
    low = F['low'].values.astype(np.float64)
    atr = F['M5_atr'].ffill().values.astype(np.float64)
    n = len(F); b = K * atr
    up_lvl, dn_lvl = close + b, close - b
    fu = np.full(n, H + 1, np.int32); fd = np.full(n, H + 1, np.int32)
    for s in range(1, H + 1):
        m = n - s
        su, sd = fu[:m], fd[:m]
        su[(high[s:] >= up_lvl[:m]) & (su > H)] = s
        sd[(low[s:] <= dn_lvl[:m]) & (sd > H)] = s
    lab = np.where(fu < fd, 1, np.where(fd < fu, -1, 0))
    valid = np.isfinite(b) & (b > 0) & (lab != 0)
    valid[-(H + 2):] = False
    return lab, valid

def add(name, mask, lab, valid, year):
    m = np.asarray(mask) & valid
    k = int(m.sum())
    if k == 0: return
    u = int((lab[m] == 1).sum())
    acc[name][0] += k; acc[name][1] += u
    e = acc_era[ERA[year]][name]; e[0] += k; e[1] += u

for y in YEARS:
    try:
        F = pd.read_pickle(f'data_cache/features/F_{y}.pkl')
    except FileNotFoundError:
        continue
    lab, valid = label_year(F)
    R = classify(F, Config().regime)
    g = lambda c: F[c].values
    add("BASELINE (all bars)", np.ones(len(F), bool), lab, valid, y)
    for reg in ("STRONG_BULL","BULL","BEAR","STRONG_BEAR","LIQUIDITY_REVERSAL",
                "COMPRESSION","EXPANSION","CHOPPY","NEUTRAL","HIGH_VOLATILITY"):
        add(f"regime={reg}", R['regime'].values == reg, lab, valid, y)
    add("H1 EMA20>EMA50", g('H1_ema_spread') > 0, lab, valid, y)
    add("H1 EMA20<EMA50", g('H1_ema_spread') < 0, lab, valid, y)
    add("M15 structure bullish", g('M15_struct_bias') > 0, lab, valid, y)
    add("M15 structure bearish", g('M15_struct_bias') < 0, lab, valid, y)
    add("M15 ADX>30 & trend up", (g('M15_adx') > 30) & (g('M15_ema_spread') > 0), lab, valid, y)
    add("M15 ADX>30 & trend down", (g('M15_adx') > 30) & (g('M15_ema_spread') < 0), lab, valid, y)
    add("M3 BOS up", g('M3_bos') > 0, lab, valid, y)
    add("M3 BOS down", g('M3_bos') < 0, lab, valid, y)
    add("M5 CHoCH up", g('M5_choch') > 0, lab, valid, y)
    add("M5 CHoCH down", g('M5_choch') < 0, lab, valid, y)
    add("M5 displacement up", g('M5_disp') > 0, lab, valid, y)
    add("M5 displacement down", g('M5_disp') < 0, lab, valid, y)
    vd = g('M15_vwap_dist_atr')
    add("price >1.5 ATR ABOVE vwap", vd > 1.5, lab, valid, y)
    add("price >1.5 ATR BELOW vwap", vd < -1.5, lab, valid, y)
    atr5 = np.maximum(g('M5_atr'), 1e-9)
    ext = (g('close') - g('M15_ema_f')) / atr5
    add("extended >3 ATR above EMA20", ext > 3, lab, valid, y)
    add("extended >3 ATR below EMA20", ext < -3, lab, valid, y)
    add("trading above prev day high", g('high') > g('pdh'), lab, valid, y)
    add("trading below prev day low", g('low') < g('pdl'), lab, valid, y)
    add("swept PDH, closed back under", (g('high') > g('pdh')) & (g('close') < g('pdh')), lab, valid, y)
    add("swept PDL, closed back over", (g('low') < g('pdl')) & (g('close') > g('pdl')), lab, valid, y)
    for s in ("ASIA","LONDON","OVERLAP","NEWYORK"):
        add(f"session={s}", g('session') == s, lab, valid, y)
    add("low vol (ATR rank<0.2)", g('M15_atr_rank') < 0.2, lab, valid, y)
    add("high vol (ATR rank>0.8)", g('M15_atr_rank') > 0.8, lab, valid, y)
    add("M5 RSI>70", g('M5_rsi') > 70, lab, valid, y)
    add("M5 RSI<30", g('M5_rsi') < 30, lab, valid, y)
    add("M15 RSI>70", g('M15_rsi') > 70, lab, valid, y)
    add("M15 RSI<30", g('M15_rsi') < 30, lab, valid, y)
    print(f"  {y}: {int(valid.sum()):,} labelled", flush=True)
    del F, R, lab, valid

def table(d):
    rows = []
    for name, (k, u) in d.items():
        if k < 2000: continue
        p = u / k
        z = (p - 0.5) / np.sqrt(p * (1 - p) / k)
        rows.append({"condition": name, "n": k, "P(up)%": round(100 * p, 2),
                     "z": round(z, 1),
                     "sig": "***" if abs(z) > 4 else ("**" if abs(z) > 3 else
                            ("*" if abs(z) > 2 else ""))})
    return pd.DataFrame(rows).sort_values("z")

print("\n" + "="*82)
print("DIRECTIONAL EDGE 2015-2026   (P(up barrier first); 50% = no information)")
print("="*82)
t = table(acc); print(t.to_string(index=False))
t.to_csv('xauusd_bot/reports/barrier_scan_all.csv', index=False)
for era, span in (("expensive","2015-2023"), ("cheap","2024-2026")):
    print("\n" + "="*82); print(f"ERA = {era}  ({span})"); print("="*82)
    te = table(acc_era[era]); print(te.to_string(index=False))
    te.to_csv(f'xauusd_bot/reports/barrier_scan_{era}.csv', index=False)
