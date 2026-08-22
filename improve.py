"""
Improvement search, IN-SAMPLE ONLY.

Runs after the D1-warmup fix, so in-sample and out-of-sample finally exercise
the same strategy. Tests structurally different ideas rather than re-tuning the
same one:

  * signal timeframe M15 / H1 / H4   (cost drag falls from ~14% -> ~4% -> ~2%
    of the stop as the timeframe rises)
  * with and without the higher-timeframe trend filter (a sweep is a
    counter-trend event locally, so the filter may be removing the good ones)
  * fixed target vs ATR trailing runner
  * a tighter spread/ATR cost-efficiency gate

Selection metric is profit factor over a minimum sample. Win rate is reported
but never optimised for -- a high win rate with PF < 1 is a losing system.
"""
import itertools, os, sys
from multiprocessing import Pool

import numpy as np, pandas as pd

import tl_data, strategy as st, signal_sim as ss

IS_START = pd.Timestamp("2024-04-01", tz="UTC")     # full D1 EMA200 warmup by here
IS_END   = pd.Timestamp("2025-12-31 23:59", tz="UTC")

FRAMES = None
def init():
    global FRAMES
    FRAMES = {s: tl_data.load(s) for s in tl_data.SYMBOLS}


def make(c):
    p = st.default_params()
    tf = c["tf_minutes"]
    p.tf_minutes = tf
    p.require_bias = c["require_bias"]
    p.tp_r = c["tp_r"]
    p.sl_atr_buffer = c["sl_atr_buffer"]
    p.retr_frac = 0.62
    p.entry_expiry = 6
    p.tp1_frac = 0.0
    p.breakeven_after_tp1 = False
    p.trail_atr = c["trail_atr"]
    p.trail_start_r = 1.0 if c["trail_atr"] > 0 else 0.0
    p.max_spread_atr_hard = c["spread_gate"]
    p.min_rr_after_costs = min(0.30, p.tp_r * 0.5)
    p.min_score = 0
    # scale the bar-count parameters with the timeframe
    scale = 15 / tf
    p.time_stop_bars = max(12, int(64 * scale))
    # sessions: intraday filtering is meaningless once bars are 4h long
    if tf >= 240:
        p.sessions = ((0, 24),)
    elif tf >= 60:
        p.sessions = ((6, 17),)
    return p


def one(c):
    p = make(c)
    rows = []
    for s in tl_data.SYMBOLS:
        try:
            rows += ss.simulate_symbol(s, FRAMES[s], p, IS_START, IS_END)
        except Exception:                                   # noqa: BLE001
            continue
    if len(rows) < 40:
        return []
    r = np.array([x["r"] for x in rows]); sc = np.array([x["score"] for x in rows])
    out = []
    for thr in (0, 60, 70):
        m = sc >= thr; rr = r[m]
        if len(rr) < 40:
            continue
        gp, gl = rr[rr > 0].sum(), -rr[rr <= 0].sum()
        out.append({**c, "min_score": thr, "n": int(len(rr)),
                    "wr": float((rr > 0).mean() * 100),
                    "pf": float(gp / gl) if gl > 0 else 99.0,
                    "exp": float(rr.mean()), "total_r": float(rr.sum())})
    return out


GRID = dict(
    tf_minutes    = [15, 60, 240],
    require_bias  = [True, False],
    tp_r          = [0.6, 1.0, 1.5, 2.0, 3.0],
    sl_atr_buffer = [0.5, 1.0],
    trail_atr     = [0.0, 1.5],
    spread_gate   = [0.45, 0.20],
)

if __name__ == "__main__":
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*[GRID[k] for k in keys])]
    print(f"{len(combos)} combinations", flush=True)
    res = []
    with Pool(min(os.cpu_count() or 4, 8), initializer=init) as pool:
        for i, r in enumerate(pool.imap_unordered(one, combos, chunksize=1)):
            res += r
            if (i + 1) % 30 == 0:
                print(f"  {i+1}/{len(combos)}", flush=True)
    df = pd.DataFrame(res)
    df.to_csv("improve_insample.csv", index=False)
    pd.set_option("display.width", 240)
    ok = df[df.n >= 60].sort_values("pf", ascending=False)
    print("\n=== TOP 25 IN-SAMPLE BY PROFIT FACTOR (n >= 60) ===")
    print(ok.head(25).round(3).to_string(index=False))
    print("\n=== best PF by signal timeframe ===")
    print(df[df.n >= 60].groupby("tf_minutes").agg(
        best_pf=("pf", "max"), median_pf=("pf", "median"),
        best_wr=("wr", "max"), n_cfg=("pf", "size")).round(3).to_string())
    print("\n=== best PF by trend filter ===")
    print(df[df.n >= 60].groupby("require_bias").agg(
        best_pf=("pf", "max"), median_pf=("pf", "median")).round(3).to_string())
    print(f"\nconfigs with PF > 1.20 and n >= 60: {((df.pf > 1.20) & (df.n >= 60)).sum()}")
