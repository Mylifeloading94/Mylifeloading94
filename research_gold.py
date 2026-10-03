"""
Grid research for the two gold bots. Results stream to results/research_<mode>.jsonl
so a container reclaim loses nothing.

SPLIT DISCIPLINE (enforced here, not just intended):
    train      2019-01-01 .. 2022-12-31   <- configs are SELECTED on this only
    validation 2023-01-01 .. 2024-12-31   <- reported for shortlisted configs
    test       2025-01-01 .. today        <- NOT computed here. select_gold.py
                                             scores the finalists on it once.

Usage: python3 research_gold.py scalp|intraday [workers]
"""
import itertools, json, os, sys, time
from multiprocessing import Pool

import numpy as np
import pandas as pd

import xau_engine as E
import xau_strategies as S

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_END = pd.Timestamp("2023-01-01", tz="UTC")
VALID_END = pd.Timestamp("2025-01-01", tz="UTC")
_M1 = None
_TF = {}


def _init():
    global _M1
    _M1 = E.load_m1()


def tf_bars(rule):
    if rule not in _TF:
        _TF[rule] = E.to_tf(_M1, rule)
    return _TF[rule]


def split_stats(t):
    out = {}
    if t is None or len(t) == 0:
        return dict(train=E.stats(t), valid=E.stats(t), yrs={})
    tr = t[t.entry_time < TRAIN_END]
    va = t[(t.entry_time >= TRAIN_END) & (t.entry_time < VALID_END)]
    yrs = {y: round(s["pf"], 2) for y, s in E.by_year(tr).items()}
    return dict(train=E.stats(tr), valid=E.stats(va), yrs=yrs)


def one(cfg):
    fam, rule, hold, tp, params = cfg["fam"], cfg["tf"], cfg["hold"], cfg["tp"], cfg["p"]
    b = tf_bars(rule)
    L, Sh, R = S.STRATEGIES[fam](b, **params)
    t = E.run(_M1, b, rule, L, Sh, R, hold_min=hold, tp_mult=tp)
    r = dict(cfg)
    r.update(split_stats(t))
    return r


def grid(mode):
    cfgs = []
    sides = ("both", "long")
    if mode == "scalp":
        combos = [("1min", (5, 10, 15)), ("5min", (10, 15))]
        for rule, holds in combos:
            for hold in holds:
                for tp in (0.0, 0.5, 1.0):
                    for sl in (1.0, 2.0, 4.0):
                        for side in sides:
                            for bo, thr in itertools.product((10, 20), (70, 75, 80)):
                                cfgs.append(dict(fam="momentum", tf=rule, hold=hold, tp=tp,
                                                 p=dict(bo_len=bo, rsi_thr=float(thr), sl_atr=sl, side=side)))
                            for dip in (5.0, 10.0, 20.0):
                                cfgs.append(dict(fam="pullback", tf=rule, hold=hold, tp=tp,
                                                 p=dict(dip=dip, sl_atr=sl, side=side)))
                            for k, rt, ax in itertools.product((2.0, 2.5, 3.0), (15.0, 25.0), (25.0, 99.0)):
                                cfgs.append(dict(fam="fade", tf=rule, hold=hold, tp=tp,
                                                 p=dict(bb_k=k, rsi_thr=rt, adx_max=ax, sl_atr=sl, side=side)))
    else:
        for rule, holds in (("15min", (60, 120, 240)), ("1h", (120, 240))):
            for hold in holds:
                for tp in (0.0, 1.0, 2.0):
                    for sl in (1.5, 3.0, 6.0):
                        for side in sides:
                            for bo, thr in itertools.product((10, 20, 40), (65, 70, 75, 80)):
                                cfgs.append(dict(fam="momentum", tf=rule, hold=hold, tp=tp,
                                                 p=dict(bo_len=bo, rsi_thr=float(thr), sl_atr=sl, side=side)))
                            for dip in (10.0, 20.0, 30.0):
                                cfgs.append(dict(fam="pullback", tf=rule, hold=hold, tp=tp,
                                                 p=dict(dip=dip, sl_atr=sl, side=side)))
                            for k, rt, ax in itertools.product((2.0, 2.5, 3.0), (20.0, 30.0), (25.0, 99.0)):
                                cfgs.append(dict(fam="fade", tf=rule, hold=hold, tp=tp,
                                                 p=dict(bb_k=k, rsi_thr=rt, adx_max=ax, sl_atr=sl, side=side)))
                            for tr in (0, 200):
                                cfgs.append(dict(fam="session_breakout", tf=rule, hold=hold, tp=tp,
                                                 p=dict(sl_atr=sl, side=side, trend_ema=tr)))
    return cfgs


def main():
    mode = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    out = os.path.join(HERE, "results", f"research_{mode}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = set()
    if os.path.exists(out):
        done = {json.dumps({k: json.loads(l)[k] for k in ("fam", "tf", "hold", "tp", "p")}, sort_keys=True)
                for l in open(out)}
    cfgs = [c for c in grid(mode) if json.dumps(c, sort_keys=True) not in done]
    print(f"{mode}: {len(cfgs)} configs to run ({len(done)} already done)", flush=True)
    t0 = time.time()
    with Pool(workers, initializer=_init) as pool, open(out, "a") as f:
        for n, r in enumerate(pool.imap_unordered(one, cfgs, chunksize=2), 1):
            f.write(json.dumps(r, default=float) + "\n")
            f.flush()
            if n % 50 == 0:
                print(f"  {n}/{len(cfgs)}  {time.time()-t0:.0f}s", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
