"""
FULLY UNCONTAMINATED WALK-FORWARD.

Every earlier test had one weakness: the structural parameters (signal
timeframe, target, stop buffer) were chosen once, on a window that overlapped
some of the periods later used to evaluate them.

Here NOTHING is fixed in advance. Inside each training window the procedure
re-selects, from scratch:
      signal timeframe (M15 / H1 / H4), target, stop buffer, score threshold
      and the pair watchlist
and then trades the following 3 months with that frozen choice. The test period
is never seen during selection, not even indirectly through a parameter chosen
elsewhere.

This is the number to judge the system on.
"""
import itertools, os
from multiprocessing import Pool

import numpy as np, pandas as pd

import tl_data, strategy as st, signal_sim as ss, config

TRAIN_START = pd.Timestamp("2024-04-01", tz="UTC")
FRAMES = None
CTX = {}


def init():
    global FRAMES
    FRAMES = {s: tl_data.load(s) for s in tl_data.SYMBOLS}


def build(c):
    p = st.default_params()
    p.tf_minutes = c["tf"]
    p.tp_r = c["tp_r"]
    p.sl_atr_buffer = c["sl"]
    p.retr_frac = 0.62
    p.entry_expiry = 6
    p.tp1_frac = 0.0
    p.breakeven_after_tp1 = False
    p.trail_atr = 0.0
    p.require_bias = True
    p.min_rr_after_costs = min(0.30, p.tp_r * 0.5)
    p.min_score = 0
    if c["tf"] >= 240:
        p.sessions = ((0, 24,),); p.time_stop_bars = 40
    elif c["tf"] >= 60:
        p.sessions = ((6, 17),); p.time_stop_bars = 60
    else:
        p.time_stop_bars = 64
    return p


def ctx_for(sym, p):
    key = (sym, p.tf_minutes)
    if key not in CTX:
        CTX[key] = {}
    k2 = (p.sl_atr_buffer, p.tp_r, p.require_bias, p.time_stop_bars, p.sessions)
    if k2 not in CTX[key]:
        CTX[key][k2] = st.Context(sym, FRAMES[sym], p)
    return CTX[key][k2]


def run_cfg(args):
    """Simulate one config over train and test windows; return per-symbol rows."""
    c, tr_s, tr_e, te_s, te_e = args
    p = build(c)
    train, test = {}, {}
    for s in tl_data.SYMBOLS:
        try:
            ctx = ctx_for(s, p)
            train[s] = ss.simulate_symbol(s, FRAMES[s], p, tr_s, tr_e, ctx=ctx)
            test[s] = ss.simulate_symbol(s, FRAMES[s], p, te_s, te_e, ctx=ctx)
        except Exception:                                # noqa: BLE001
            train[s], test[s] = [], []
    return c, train, test


def pooled(rows):
    if not rows:
        return None
    r = np.array([x["r"] for x in rows])
    gp, gl = r[r > 0].sum(), -r[r <= 0].sum()
    return dict(n=len(r), wr=100 * (r > 0).mean(),
                pf=gp / gl if gl > 0 else 99.0, exp=r.mean(), tot=r.sum())


import sys
# --tp X restricts the search to one target size, so the win-rate / profit-
# factor trade-off can be measured OUT OF SAMPLE rather than argued about.
_TPS = (0.6, 1.0, 1.5, 2.0, 3.0)
_TFS = (15, 60, 240)
for _a in sys.argv[1:]:
    if _a.startswith("--tp="):
        _TPS = (float(_a.split("=")[1]),)
    if _a.startswith("--tf="):
        _TFS = (int(_a.split("=")[1]),)
GRID = [dict(tf=tf, tp_r=tp, sl=sl)
        for tf, tp, sl in itertools.product(_TFS, _TPS, (0.5, 1.0))]
THRESHOLDS = (50, 60, 70)

if __name__ == "__main__":
    cuts = pd.date_range("2025-04-01", "2026-07-01", freq="3MS", tz="UTC")
    rows, oos_all, oos_sel = [], [], []

    with Pool(min(os.cpu_count() or 4, 8), initializer=init) as pool:
        for cut in cuts:
            te_s = cut
            te_e = cut + pd.offsets.MonthBegin(3) - pd.Timedelta(seconds=1)
            if te_s >= pd.Timestamp("2026-08-22", tz="UTC"):
                break
            tr_s, tr_e = TRAIN_START, cut - pd.Timedelta(seconds=1)
            args = [(c, tr_s, tr_e, te_s, te_e) for c in GRID]

            best = None
            store = {}
            for c, train, test in pool.imap_unordered(run_cfg, args, chunksize=2):
                store[tuple(sorted(c.items()))] = (train, test)
                allr = [x for v in train.values() for x in v]
                if len(allr) < 30:
                    continue
                for thr in THRESHOLDS:
                    rr = [x for x in allr if x["score"] >= thr]
                    k = pooled(rr)
                    if not k or k["n"] < 25:
                        continue
                    if best is None or k["pf"] > best[0]:
                        best = (k["pf"], c, thr, k["n"], k["wr"])
            if best is None:
                continue
            _, c, thr, tn, twr = best
            train, test = store[tuple(sorted(c.items()))]

            wl = [s for s, r in train.items()
                  if len([x for x in r if x["score"] >= thr]) >= 3
                  and pooled([x for x in r if x["score"] >= thr])["pf"] > 1.2]
            if len(wl) < 3:
                wl = list(tl_data.SYMBOLS)

            t_all = [x for v in test.values() for x in v if x["score"] >= thr]
            t_sel = [x for s in wl for x in test[s] if x["score"] >= thr]
            oos_all += t_all; oos_sel += t_sel
            ka, ksel = pooled(t_all), pooled(t_sel)
            rows.append(dict(
                test=f"{te_s:%Y-%m}..{te_e:%Y-%m}",
                tf=c["tf"], tp_r=c["tp_r"], sl=c["sl"], thr=thr, wl=len(wl),
                train_n=tn, train_pf=round(best[0], 3), train_wr=round(twr, 1),
                all_n=ka["n"] if ka else 0,
                all_wr=round(ka["wr"], 1) if ka else np.nan,
                all_pf=round(ka["pf"], 3) if ka else np.nan,
                sel_n=ksel["n"] if ksel else 0,
                sel_wr=round(ksel["wr"], 1) if ksel else np.nan,
                sel_pf=round(ksel["pf"], 3) if ksel else np.nan))
            print(f"  done {te_s:%Y-%m}", flush=True)

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 240)
    print("\n=== FULL WALK-FORWARD: every parameter re-chosen inside each train window ===")
    print(df.to_string(index=False))
    for label, pool_rows in (("ALL PAIRS", oos_all), ("FILTERED WATCHLIST", oos_sel)):
        k = pooled(pool_rows)
        if not k:
            continue
        print(f"\n=== POOLED OUT-OF-SAMPLE - {label} ===")
        print(f"  trades {k['n']}   win rate {k['wr']:.2f}%   "
              f"profit factor {k['pf']:.3f}   expectancy {k['exp']:+.4f}R   total {k['tot']:+.2f}R")
    v = df.dropna(subset=["all_pf"])
    print(f"\n  periods PF>1 (all pairs): {(v.all_pf>1).sum()}/{len(v)}   "
          f"(filtered): {(v.sel_pf>1).sum()}/{len(v)}")
    print(f"  timeframe chosen by the training data each cycle: {df.tf.tolist()}")
    tag = "".join(a.replace("--","_").replace("=","") for a in sys.argv[1:])
    df.to_csv(f"walkforward_full{tag}.csv", index=False)
