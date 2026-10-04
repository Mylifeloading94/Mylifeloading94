"""
Why does it lose? Compare the strategy-as-written trades with (a) RANDOM entries that use the identical stop and
target DISTANCES and direction, and (b) the MIRROR trade (opposite side, same distances). Same executor, same costs.
If the setup carried information, (a) would do clearly worse than the strategy and (b) clearly worse still.
"""
import numpy as np, pandas as pd, xau_engine as E, liq_scalp as LS, liq_exec as X

m1 = E.load_m1(); b15 = E.to_tf(m1, "15min"); b1h = E.to_tf(m1, "1h"); rng = np.random.default_rng(5)
tmin = E._min(m1.index); arr = [np.ascontiguousarray(m1[c].to_numpy("float64")) for c in ("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac")]
ask_o, bid_o = arr[4], arr[0]


def market_batch(act, d, risk, rr_plan):
    """Run market trades from M1 index `act` with stop distance `risk` and target distance rr_plan*risk."""
    fill = np.where(d == 1, ask_o[act], bid_o[act])
    stop = fill - d * risk; tgt = fill + d * rr_plan * risk; n = len(act)
    st = np.empty(n, np.int64); r = np.empty(n); fi = np.empty(n, np.int64); en = np.empty(n, np.int64); wy = np.empty(n, np.int64)
    X._sim_trade(act.astype(np.int64), d.astype(np.int64), np.zeros(n, np.int64), fill, stop, tgt, 0, 360, tmin, *arr, st, r, fi, en, wy)
    return r[st == 1]


def stat(r):
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    return f"n={len(r):4d} WR {100*(r>0).mean():4.1f}% PF {w/l if l>0 else np.inf:4.2f} mean R {r.mean():+.3f}"


for entry in ("E1", "E2"):
    sg = LS.generate(b15, b1h, entry=entry, aligned=True, tp_mode="swing15", min_rr=0.0)
    t = X.run(m1, b15, sg, risk_rules=False)
    d = t.dir.to_numpy(); risk = t.risk.to_numpy(); rr = t.rr_plan.to_numpy()
    # distances in ATR UNITS, so a random entry gets the same stop/target relative to ITS OWN volatility
    atr15 = LS.S.atr(b15).to_numpy(); b15_close_min = E._min(b15.index) + 15
    ti = np.searchsorted(E._min(b15.index), E._min(pd.DatetimeIndex(t.entry_time)), side="right") - 1
    risk_atr = risk / atr15[np.clip(ti, 0, len(atr15) - 1)]
    print(f"\n=== {entry} as written ({len(t)} trades, median planned RR {np.median(rr):.2f}) ===")
    print(f"  strategy        : {stat(t.r.to_numpy())}")
    # (a) random entries, same distances and direction
    pfs, wrs, means = [], [], []
    for _ in range(200):
        act = rng.integers(2000, len(tmin) - 2000, len(t))
        bi = np.clip(np.searchsorted(E._min(b15.index), tmin[act], side="right") - 1, 0, len(atr15) - 1)
        rk = risk_atr * atr15[bi]
        okr = np.isfinite(rk) & (rk > 0)
        r = market_batch(act[okr], d[okr], rk[okr], rr[okr])
        w, l = r[r > 0].sum(), -r[r <= 0].sum(); pfs.append(w / l); wrs.append(100 * (r > 0).mean()); means.append(r.mean())
    print(f"  random entries (ATR-matched): WR {np.mean(wrs):4.1f}% (95% band {np.percentile(wrs,2.5):.1f}-{np.percentile(wrs,97.5):.1f})  PF {np.mean(pfs):4.2f} (band {np.percentile(pfs,2.5):.2f}-{np.percentile(pfs,97.5):.2f})  mean R {np.mean(means):+.3f}")
    # (b) mirror: opposite direction at the strategy's own entry times
    act = np.searchsorted(tmin, E._min(b15.index)[sg.t.to_numpy()] + 15)
    ok = act < len(tmin); s2 = sg[ok]; act = act[ok]
    m = market_batch(act, -s2.dir.to_numpy(), s2.risk.to_numpy(), s2.rr.to_numpy())
    print(f"  mirror (reverse): {stat(m)}")
    z = (t.r.mean() - np.mean(means)) / np.std(means)
    print(f"  strategy mean R vs random-entry distribution: z = {z:+.2f}")
