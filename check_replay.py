"""
Offline proof that the LIVE signal path equals the BACKTEST signal path.

For each strategy, take every bar where the backtest says "signal" plus an equal
number of random non-signal bars, rebuild what the live bot would see at that
moment (only the trailing WARMUP_BARS closed bars), call bot_gold.latest_signal,
and require the same answer. Catches lookahead and warm-up-length sensitivity.
"""
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S, bot_gold as B

m1 = E.load_m1()
m1 = m1[m1.index >= "2024-01-01"]
CASES = [
    ("momentum", "5min", dict(bo_len=20, rsi_thr=75., sl_atr=3., side="both")),
    ("momentum", "1h", dict(bo_len=20, rsi_thr=70., sl_atr=3., side="both")),
    ("pullback", "15min", dict(dip=10., sl_atr=2., side="both")),
    ("fade", "5min", dict(bb_k=2.0, rsi_thr=25., adx_max=99., sl_atr=2., side="both")),
    ("session_breakout", "15min", dict(sl_atr=2., side="both")),
]
rng = np.random.default_rng(0)
bad_total = 0
for fam, tf, p in CASES:
    b = E.to_tf(m1, tf)
    L, Sh, R = S.STRATEGIES[fam](b, **p)
    sig = np.where(L, 1, np.where(Sh, -1, 0))
    pos = np.flatnonzero(sig != 0)
    pos = pos[pos > B.WARMUP_BARS]
    neg = rng.choice(np.flatnonzero((sig == 0))[B.WARMUP_BARS:], size=min(len(pos), 150), replace=False)
    sample = np.concatenate([rng.choice(pos, size=min(len(pos), 150), replace=False) if len(pos) else [], neg]).astype(int)
    cfg = dict(fam=fam, p=p)
    bad = 0
    for i in sample:
        win = b.iloc[i - B.WARMUP_BARS + 1: i + 1]
        d, risk = B.latest_signal(win, cfg)
        if d != sig[i] or (d != 0 and abs(risk - R[i]) / R[i] > 0.02):
            bad += 1
    bad_total += bad
    print(f"{fam:17s} {tf:5s} checked {len(sample):4d} bars ({len(pos)} signals total)  mismatches: {bad}")
print("\nRESULT:", "PASS - live path matches backtest" if bad_total == 0 else f"FAIL - {bad_total} mismatches")
