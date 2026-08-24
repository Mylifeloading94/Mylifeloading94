"""
Does the learned model do better at a different geometry or horizon?

Features are unchanged (already cached); only the labels are recomputed. This
isolates 'is the edge horizon-specific?' from 'are the features useless?'.
"""
import sys, gc; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from xauusd_bot.ml.features import triple_barrier

META = ['y_long','y_short','atr','target_px','stop_px','close','session']
def drop_meta(d):
    return d.drop(columns=[c for c in d.columns
                           if c in META or c in ('t_long','t_short')])
GEOMS = [
    ("very high win  T=0.5 S=1.5 H=60",  0.5, 1.5, 60),
    ("high win       T=0.8 S=1.2 H=120", 0.8, 1.2, 120),
    ("symmetric      T=1.0 S=1.0 H=240", 1.0, 1.0, 240),
    ("V3-like        T=1.5 S=1.5 H=480", 1.5, 1.5, 480),
    ("runner         T=2.0 S=1.0 H=480", 2.0, 1.0, 480),
]

def relabel(t_atr, s_atr, hor):
    parts = []
    for y in range(2015, 2027):
        ds = Path(f'data_cache/ml/ds_{y}.pkl')
        fp = Path(f'data_cache/features/F_{y}.pkl')
        if not (ds.exists() and fp.exists()): continue
        d = pd.read_pickle(ds)
        F = pd.read_pickle(fp)
        Y = triple_barrier(F, t_atr, s_atr, hor).reindex(d.index)
        d = d.drop(columns=[c for c in ('y_long','y_short','target_px','stop_px',
                                        't_long','t_short') if c in d])
        d['y_long'] = Y['y_long'].values; d['y_short'] = Y['y_short'].values
        d['target_px'] = Y['target_px'].values; d['stop_px'] = Y['stop_px'].values
        d = d[(d.y_long >= 0) & (d.y_short >= 0)]
        parts.append(d)
        del F, Y; gc.collect()
    return pd.concat(parts).sort_index()

print(f"{'geometry':<34}{'side':>6}{'base%':>8}{'AUCva':>8}{'AUCte':>8}"
      f"{'bestThr':>9}{'win%':>7}{'n/day':>7}{'avg$':>8}{'PF':>6}")
for label, T, S, H in GEOMS:
    D = relabel(T, S, H)
    tr = D[D.index.year <= 2022]; va = D[(D.index.year >= 2023) & (D.index.year <= 2024)]
    te = D[D.index.year >= 2025]
    emb = H // 5 + 2
    tr = tr.iloc[:-emb]; va = va.iloc[:-emb]
    days_te = len(pd.unique(te.index.date))
    for side in ('long','short'):
        Xtr = drop_meta(tr); Xva = drop_meta(va); Xte = drop_meta(te)
        ytr = tr[f'y_{side}'].values; yva = va[f'y_{side}'].values; yte = te[f'y_{side}'].values
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_depth=5,
                                           min_samples_leaf=200, l2_regularization=1.0,
                                           early_stopping=True, validation_fraction=0.15,
                                           n_iter_no_change=25, random_state=7)
        m.fit(Xtr, ytr)
        pva = m.predict_proba(Xva)[:,1]; pte = m.predict_proba(Xte)[:,1]
        auc_va = roc_auc_score(yva, pva); auc_te = roc_auc_score(yte, pte)
        # pick the threshold on VALIDATION, report it on TEST
        rt_va = va['cost_over_atr'].values * va['atr'].values
        best_thr, best = 0.5, -1e18
        for thr in np.arange(0.50, 0.86, 0.025):
            sel = pva >= thr
            if sel.sum() < 100: continue
            won = yva[sel] == 1
            pnl = np.where(won, va['target_px'].values[sel]-rt_va[sel],
                                -va['stop_px'].values[sel]-rt_va[sel])
            if pnl.sum() > best: best, best_thr = pnl.sum(), thr
        sel = pte >= best_thr
        rt_te = te['cost_over_atr'].values * te['atr'].values
        won = yte[sel] == 1
        pnl = np.where(won, te['target_px'].values[sel]-rt_te[sel],
                            -te['stop_px'].values[sel]-rt_te[sel])
        gw, gl = pnl[pnl>0].sum(), -pnl[pnl<0].sum()
        print(f"{label:<34}{side:>6}{100*yte.mean():>8.1f}{auc_va:>8.4f}{auc_te:>8.4f}"
              f"{best_thr:>9.3f}{100*won.mean() if sel.sum() else 0:>7.1f}"
              f"{sel.sum()/days_te:>7.2f}{pnl.mean() if sel.sum() else 0:>8.3f}"
              f"{min(gw/gl if gl>0 else 99,99):>6.2f}", flush=True)
    del D, tr, va, te; gc.collect()
