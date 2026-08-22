"""
IN-SAMPLE study of the SMC build (2024-04-01 .. 2025-12-31).

Answers three questions with measurements rather than opinion:
  1. does the M1 sniper drill-down actually beat an M15 entry?
  2. what target size fits the sniper stop?
  3. does the 20-pip trailing stop help, hurt, or do nothing?

The 2026 window is never read here.
"""
import itertools, os, sys
from multiprocessing import Pool

import numpy as np, pandas as pd

import tl_data, smc, smc_sim

IS_S = pd.Timestamp("2024-04-01", tz="UTC")
IS_E = pd.Timestamp("2025-12-31 23:59", tz="UTC")

SYMS = None
M15 = {}
M1 = {}


def init():
    global SYMS
    SYMS = [s for s in tl_data.SYMBOLS
            if os.path.exists(tl_data.m1_path(s))]
    for s in SYMS:
        M15[s] = tl_data.load(s)
        M1[s] = tl_data.load_m1(s)


def one(c):
    p = smc.default_smc()
    p.use_m1 = c["use_m1"]
    p.tp_r = c["tp_r"]
    p.trail_mode = c["trail_mode"]
    p.trail_step_pips = c["trail_pips"]
    p.trail_start_pips = c["trail_pips"]
    p.trail_gap_pips = c["trail_pips"]
    p.min_score = 0
    p.min_rr = min(1.5, c["tp_r"] * 0.6)
    p.m1_fill_bars = c.get("fill_bars", 8)
    rows = []
    for s in SYMS:
        try:
            rows += smc_sim.simulate_symbol(s, M15[s], p, IS_S, IS_E,
                                            m1=M1[s] if c["use_m1"] else None)
        except Exception:                                  # noqa: BLE001
            continue
    if len(rows) < 25:
        return []
    r = np.array([x["r"] for x in rows]); sc = np.array([x["score"] for x in rows])
    out = []
    for thr in (0, 60, 70):
        m = sc >= thr; rr = r[m]
        if len(rr) < 25:
            continue
        gp, gl = rr[rr > 0].sum(), -rr[rr <= 0].sum()
        out.append({**c, "min_score": thr, "n": int(len(rr)),
                    "wr": float((rr > 0).mean() * 100),
                    "pf": float(gp / gl) if gl > 0 else 99.0,
                    "exp": float(rr.mean())})
    return out


GRID = dict(
    use_m1     = [True, False],
    tp_r       = [1.5, 2.0, 3.0, 4.0],
    trail_mode = ["off", "gap"],
    trail_pips = [20.0],
    fill_bars  = [8, 24],
)

if __name__ == "__main__":
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*[GRID[k] for k in keys])]
    print(f"{len(combos)} combinations", flush=True)
    res = []
    with Pool(min(os.cpu_count() or 4, 6), initializer=init) as pool:
        for i, r in enumerate(pool.imap_unordered(one, combos, chunksize=1)):
            res += r
            print(f"  {i+1}/{len(combos)}", flush=True)
    df = pd.DataFrame(res)
    df.to_csv("smc_insample.csv", index=False)
    pd.set_option("display.width", 220)
    print("\n=== ALL RESULTS (sorted by profit factor) ===")
    print(df.sort_values("pf", ascending=False).round(3).to_string(index=False))
    print("\n=== fill window ===")
    print(df.groupby("fill_bars").agg(median_pf=("pf","median"), median_n=("n","median")).round(3).to_string())
    print("\n=== does the M1 sniper help? ===")
    print(df.groupby("use_m1").agg(median_pf=("pf","median"), median_wr=("wr","median"),
                                   median_n=("n","median")).round(3).to_string())
    print("\n=== does the 20-pip trail help? ===")
    print(df.groupby("trail_mode").agg(median_pf=("pf","median"), median_wr=("wr","median"),
                                       median_exp=("exp","median")).round(3).to_string())
    print("\n=== target size ===")
    print(df.groupby("tp_r").agg(median_pf=("pf","median"), median_wr=("wr","median")).round(3).to_string())
