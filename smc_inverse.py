"""EXPLORATORY, post-hoc (the test period had already been seen): trade the INVERSE of M5 SMC setups
at market with a time exit and a 6-ATR stop. Saved so the number can be reproduced, not as a claim."""
import numpy as np, pandas as pd, xau_engine as E, xau_strategies as S, smc
m1 = E.load_m1(); b = E.to_tf(m1, "5min"); atr = S.atr(b).to_numpy()
TR = pd.Timestamp("2023-01-01", tz="UTC"); VA = pd.Timestamp("2025-01-01", tz="UTC")
f = lambda s: f"n={s['n']:4d} WR {s['wr']:4.1f} PF {s['pf']:4.2f} R {s['tot_r']:+6.1f}"
print("inverse of M5 SMC setups: market entry, time exit, 6-ATR stop")
for liq in ("session", "swing"):
    sg = smc.generate(b, 5, liq=liq, entry="mid")
    L = np.zeros(len(b), bool); Sh = np.zeros(len(b), bool)
    L[sg.t[sg.dir == -1].to_numpy()] = True; Sh[sg.t[sg.dir == 1].to_numpy()] = True
    for hold in (180, 360):
        t = E.run(m1, b, "5min", L, Sh, 6 * atr, hold_min=hold, tp_mult=0.0)
        print(f"{liq:8s} {hold//60}h | train {f(E.stats(t[t.entry_time < TR]))} | valid {f(E.stats(t[(t.entry_time >= TR) & (t.entry_time < VA)]))} | test {f(E.stats(t[t.entry_time >= VA]))}")
