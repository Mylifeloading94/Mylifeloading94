"""
Does the candle-by-candle replay reproduce the vectorised backtest TRADE FOR TRADE?

  python3 check_replay_engine.py                 # one month smoke test
  python3 check_replay_engine.py 2019 2026       # full years, in parallel
"""
import json, sys, time
from multiprocessing import Pool
import numpy as np, pandas as pd
import xau_engine as E, xau_strategies as S
import replay_engine as R
import bot_gold as B

CFG = json.load(open("configs/gold_intraday.json"))


def vec_trades(m1):
    b = E.to_tf(m1, CFG["tf"])
    L, Sh, Rk = S.STRATEGIES[CFG["fam"]](b, **CFG["p"])
    return E.run(m1, b, CFG["tf"], L, Sh, Rk, hold_min=CFG["hold"], tp_mult=CFG["tp"])


def one(args):
    start, end = args
    m1 = E.load_m1()
    t0 = time.time()
    rt, eq, info = R.replay(m1, CFG, start, end, sizing="fractional")
    return start, end, rt, time.time() - t0


def compare(vt, rt, start, end, label):
    s, e = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    v = vt[(vt.entry_time >= s) & (vt.entry_time < e)].reset_index(drop=True)
    r = rt.reset_index(drop=True)
    key = lambda df: set(zip(df.entry_time, df.dir))
    kv, kr = key(v), key(r)
    both = kv & kr
    m = v.merge(r, on=["entry_time", "dir"], suffixes=("_v", "_r"))
    dr = (m.r_v - m.r_r).abs()
    print(f"{label:>12}: vectorised {len(v):4d} | replay {len(r):4d} | same entry {len(both):4d} | "
          f"only-vec {len(kv-kr):2d} | only-replay {len(kr-kv):2d} | max |dR| on matches {dr.max() if len(dr) else 0:.2e}")
    return len(v), len(r), len(both), len(kv - kr), len(kr - kv), float(dr.max() if len(dr) else 0)


if __name__ == "__main__":
    m1 = E.load_m1()
    vt = vec_trades(m1)
    if len(sys.argv) == 1:
        s, e = "2024-03-01", "2024-04-01"
        t0 = time.time(); rt, eq, info = R.replay(m1, CFG, s, e, sizing="fractional")
        print(f"replayed {s}..{e} in {time.time()-t0:.1f}s")
        compare(vt, rt, s, e, "smoke")
    else:
        y0, y1 = int(sys.argv[1]), int(sys.argv[2])
        jobs = [(f"{y}-01-01", f"{y+1}-01-01") for y in range(y0, y1 + 1)]
        tot = np.zeros(5, int); worst = 0.0
        with Pool(4) as p:
            for s, e, rt, dt in sorted(p.map(one, jobs)):
                a = compare(vt, rt, s, e, s[:4]); tot += a[:5]; worst = max(worst, a[5])
        print(f"\nTOTAL vectorised {tot[0]} | replay {tot[1]} | identical entries {tot[2]} | only-vec {tot[3]} | only-replay {tot[4]} | worst |dR| {worst:.2e}")
