"""Does the Brad-Gold setup (sweep at a POI, trend-aligned) predict direction at ANY horizon? No exits, no stops, no costs:
signed move after the signal bar's close, in ATR units, by period, versus random bars (random direction)."""
import numpy as np, pandas as pd, xau_engine as E, xau_strategies as S, liq_scalp as LS, smc
m1 = E.load_m1(); b15 = E.to_tf(m1, "15min"); b1h = E.to_tf(m1, "1h"); atr = S.atr(b15).to_numpy(); close = b15.close.to_numpy(); idx = b15.index
TR = pd.Timestamp("2023-01-01", tz="UTC"); VA = pd.Timestamp("2025-01-01", tz="UTC"); rng = np.random.default_rng(0)
kzm, _ = smc.kill_zone_mask(b15, 15)
print("signed forward move in ATR (positive = price goes the setup's way). null = random bars, random direction")
print(f"{'variant':26s} {'hold':>5s} | {'train 2019-22':^24s} | {'valid 2023-24':^24s} | {'test 2025+':^24s} | null 95% band")
for name, kw in (("E1 aligned", dict(aligned=True)), ("E1 15M-only", dict(aligned=False)), ("E1 aligned + kill zone", dict(aligned=True, kz=True))):
    sg = LS.generate(b15, b1h, entry="E1", need_target=False, **kw); t = sg.t.to_numpy(); d = sg.dir.to_numpy()
    for hb in (4, 8, 16, 24):
        ok = t + hb < len(b15); tt = t[ok]
        mv = ((close[tt + hb] - close[tt]) / atr[tt]) * d[ok]; ts = idx[tt]
        cells = []
        for lo, hi in ((None, TR), (TR, VA), (VA, None)):
            m = np.ones(len(mv), bool)
            if lo is not None: m &= ts >= lo
            if hi is not None: m &= ts < hi
            x = mv[m]; cells.append(f"n={m.sum():4d} {x.mean():+.3f} t={x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+5.2f}")
        pool = np.flatnonzero(np.isfinite(atr) & (np.arange(len(b15)) + hb < len(b15)))
        nulls = [(((close[(i := rng.choice(pool, len(mv), replace=False)) + hb] - close[i]) / atr[i]) * rng.choice([-1, 1], len(mv))).mean() for _ in range(400)]
        print(f"{name:26s} {hb*15/60:4.0f}h | {cells[0]:24s} | {cells[1]:24s} | {cells[2]:24s} | [{np.percentile(nulls,2.5):+.2f},{np.percentile(nulls,97.5):+.2f}]")
