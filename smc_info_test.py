"""
Does the SMC + kill-zone setup carry ANY directional information? No exits, no fills, no costs:
the move from the signal bar's close over the next N bars, in ATR units, signed by the signal direction.
Null = the same measurement at random bars inside the same kill zones with a random direction.
"""
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S, smc

m1 = E.load_m1(); rng = np.random.default_rng(0)
print(f"{'TF':5s} {'liquidity':8s} {'horizon':>8s} | {'n':>5s} {'mean signed move (ATR)':>24s} {'t':>6s} | {'random-in-KZ null mean':>22s} {'null 95% band':>16s}")
for rule, tfm in (("15min", 15), ("5min", 5)):
    b = E.to_tf(m1, rule); atr = S.atr(b).to_numpy(); close = b.close.to_numpy(); kz, _ = smc.kill_zone_mask(b, tfm)
    for liq in ("session", "swing"):
        sg = smc.generate(b, tfm, liq=liq, entry="mid")
        for hb in (4, 12, 24):
            h = hb if tfm == 15 else hb * 3
            t = sg.t.to_numpy(); ok = t + h < len(b)
            mv = ((close[t[ok] + h] - close[t[ok]]) / atr[t[ok]]) * sg.dir.to_numpy()[ok]
            tt = mv.mean() / (mv.std(ddof=1) / np.sqrt(len(mv)))
            pool = np.flatnonzero(kz & (np.arange(len(b)) + h < len(b)) & np.isfinite(atr)); nulls = []
            for _ in range(500):
                idx = rng.choice(pool, len(mv), replace=False); d = rng.choice([-1, 1], len(mv))
                nulls.append((((close[idx + h] - close[idx]) / atr[idx]) * d).mean())
            print(f"{rule:5s} {liq:8s} {h*tfm/60:6.1f}h | {len(mv):5d} {mv.mean():+24.4f} {tt:+6.2f} | {np.mean(nulls):+22.4f} [{np.percentile(nulls,2.5):+.3f},{np.percentile(nulls,97.5):+.3f}]")
# what the kill zones DO have: movement (not direction)
b = E.to_tf(m1, "15min"); atr = S.atr(b); kz, zone = smc.kill_zone_mask(b, 15)
rng_ = ((b.high - b.low) / atr.shift(1)).to_numpy()
print("\nkill zones vs the rest: mean bar range in ATR units (M15)")
for z in ("london", "ny"):
    print(f"  {z:7s} {np.nanmean(rng_[zone == z]):.3f}")
print(f"  outside {np.nanmean(rng_[~kz]):.3f}")
