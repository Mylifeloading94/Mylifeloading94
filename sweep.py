"""
In-sample (2025) parameter sweep.

Selection metric is PROFIT FACTOR with a minimum sample size, never win rate.
A high win rate with PF < 1 is a losing system, and this project has already
been burned by that once.

The 2026 window is not read anywhere in this file.
"""
import itertools, json, sys, os
from multiprocessing import Pool

import numpy as np
import pandas as pd

import tl_data, strategy as st, signal_sim as ss

IS_START = pd.Timestamp("2025-03-01", tz="UTC")
IS_END   = pd.Timestamp("2025-12-31 23:59", tz="UTC")

FRAMES = None

def init():
    global FRAMES
    FRAMES = {s: tl_data.load(s) for s in tl_data.SYMBOLS}

def one(combo):
    p = st.default_params()
    for k, v in combo.items():
        setattr(p, k, v)
    p.min_score = 0                      # threshold is chosen afterwards
    rows = []
    for s in tl_data.SYMBOLS:
        rows += ss.simulate_symbol(s, FRAMES[s], p, IS_START, IS_END)
    if not rows:
        return combo, {}
    r = np.array([x["r"] for x in rows])
    sc = np.array([x["score"] for x in rows])
    res = {}
    for thr in (0, 55, 60, 65, 70, 75):
        m = sc >= thr
        rr = r[m]
        if len(rr) < 30:
            continue
        gp = rr[rr > 0].sum(); gl = -rr[rr <= 0].sum()
        res[thr] = dict(n=int(len(rr)), wr=float((rr > 0).mean() * 100),
                        pf=float(gp / gl) if gl > 0 else 99.0,
                        exp=float(rr.mean()), total_r=float(rr.sum()))
    return combo, res


GRID = dict(
    retr_frac      = [0.35, 0.5, 0.62],
    sl_atr_buffer  = [0.5, 0.8, 1.1],
    tp_r           = [1.5, 2.0, 2.5, 3.0],
    tp1_frac       = [0.0, 0.5],
    breakeven_after_tp1 = [True, False],
    entry_expiry   = [6, 10],
)

def main():
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*[GRID[k] for k in keys])]
    # drop meaningless pairings (no partial => breakeven flag is inert)
    combos = [c for c in combos if not (c["tp1_frac"] == 0.0 and c["breakeven_after_tp1"] is True)]
    print(f"{len(combos)} combinations", flush=True)
    out = []
    with Pool(processes=min(os.cpu_count() or 4, 8), initializer=init) as pool:
        for i, (combo, res) in enumerate(pool.imap_unordered(one, combos, chunksize=4)):
            out.append((combo, res))
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(combos)}", flush=True)
    rows = []
    for combo, res in out:
        for thr, m in (res or {}).items():
            rows.append({**combo, "min_score": thr, **m})
    df = pd.DataFrame(rows)
    df.to_csv("sweep_insample.csv", index=False)
    ok = df[df.n >= 60].sort_values("pf", ascending=False)
    pd.set_option("display.width", 200)
    print("\n=== TOP 25 IN-SAMPLE BY PROFIT FACTOR (n >= 60) ===")
    print(ok.head(25).to_string(index=False))
    print(f"\nrows={len(df)}  with n>=60: {len(ok)}")

if __name__ == "__main__":
    main()
