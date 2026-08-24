"""
Train the learned entry model.

Split is strictly chronological with an embargo: labels look up to 120 minutes
forward, so samples within that window of a boundary are dropped. Without this
the test set shares outcome bars with the training set and every score is a lie.

The output that matters is not AUC - it is the table of confidence threshold
against WIN RATE, TRADES PER DAY and NET EXPECTANCY AFTER COSTS. A high win
rate is only worth anything if the last column is positive.
"""
import sys, json, pickle; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

TRAIN = range(2015, 2023)      # 2015-2022
VALID = (2023, 2024)
TEST  = (2025, 2026)
EMBARGO_ROWS = 120 // 5 + 2    # horizon / stride

def load(years):
    fr = []
    for y in years:
        p = Path(f'data_cache/ml/ds_{y}.pkl')
        if p.exists(): fr.append(pd.read_pickle(p))
    return pd.concat(fr).sort_index()

META = ['y_long','y_short','atr','target_px','stop_px','t_long','t_short','close','session']

def xy(df, side):
    X = df.drop(columns=META)
    y = df[f'y_{side}'].values
    return X, y

def net_pnl(df, side, won):
    """$ P&L per trade after the modelled round-trip cost."""
    rt = df['cost_over_atr'].values * df['atr'].values
    return np.where(won, df['target_px'].values - rt, -df['stop_px'].values - rt)

tr, va, te = load(TRAIN), load(VALID), load(TEST)
for name, d in (('train', tr), ('valid', va), ('test', te)):
    print(f"{name:6s} {len(d):>8,} samples  {d.index[0].date()} -> {d.index[-1].date()}  "
          f"long_win={d.y_long.mean():.3f} short_win={d.y_short.mean():.3f}", flush=True)
# embargo at each boundary
tr = tr.iloc[:-EMBARGO_ROWS]; va = va.iloc[:-EMBARGO_ROWS]
print(f"after embargo: train {len(tr):,}  valid {len(va):,}  test {len(te):,}\n", flush=True)

models, results = {}, {}
for side in ('long', 'short'):
    Xtr, ytr = xy(tr, side); Xva, yva = xy(va, side); Xte, yte = xy(te, side)
    m = HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.05, max_depth=5, max_leaf_nodes=31,
        min_samples_leaf=200, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, n_iter_no_change=30,
        random_state=7)
    m.fit(Xtr, ytr)
    models[side] = m
    p_va = m.predict_proba(Xva)[:, 1]
    p_te = m.predict_proba(Xte)[:, 1]
    results[side] = {'p_va': p_va, 'p_te': p_te}
    print(f"{side.upper():5s} iters={m.n_iter_}  AUC train-holdout={float(np.max(m.validation_score_)):.4f}  "
          f"AUC valid={roc_auc_score(yva, p_va):.4f}  AUC test={roc_auc_score(yte, p_te):.4f}",
          flush=True)

def table(df, p, y, label, days):
    print(f"\n{label}  (base win rate {y.mean()*100:.1f}%)")
    print(f"{'threshold':>10}{'trades':>9}{'per day':>9}{'win%':>8}"
          f"{'avg $':>9}{'total $':>10}{'PF':>7}")
    rows=[]
    for thr in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85):
        sel = p >= thr
        n = int(sel.sum())
        if n < 30: continue
        won = y[sel] == 1
        pnl = net_pnl(df[sel], None, won)
        gw, gl = pnl[pnl>0].sum(), -pnl[pnl<0].sum()
        rows.append({'thr':thr,'n':n,'per_day':n/days,'win':100*won.mean(),
                     'avg':pnl.mean(),'tot':pnl.sum(),
                     'pf':(gw/gl) if gl>0 else np.inf})
        print(f"{thr:>10.2f}{n:>9,}{n/days:>9.2f}{100*won.mean():>8.1f}"
              f"{pnl.mean():>9.3f}{pnl.sum():>10.1f}{min(gw/gl if gl>0 else 99,99):>7.2f}")
    return rows

days_va = len(pd.unique(va.index.date)); days_te = len(pd.unique(te.index.date))
out = {}
for side in ('long','short'):
    _, yva = xy(va, side); _, yte = xy(te, side)
    out[f'{side}_valid'] = table(va, results[side]['p_va'], yva,
                                 f"{side.upper()} — VALIDATION 2023-2024", days_va)
    out[f'{side}_test'] = table(te, results[side]['p_te'], yte,
                                f"{side.upper()} — TEST 2025-2026 (held out)", days_te)

with open('data_cache/ml/models.pkl','wb') as f:
    pickle.dump({'models':models, 'features':list(xy(tr,'long')[0].columns)}, f)
json.dump({k:[{kk:(float(vv) if isinstance(vv,(int,float,np.floating)) else vv)
               for kk,vv in r.items()} for r in v] for k,v in out.items()},
          open('xauusd_bot/reports/ml_thresholds.json','w'), indent=2)

# feature importance via permutation on a validation subsample
from sklearn.inspection import permutation_importance
Xva, yva = xy(va, 'long')
sub = np.random.default_rng(0).choice(len(Xva), size=min(20000, len(Xva)), replace=False)
pi = permutation_importance(models['long'], Xva.iloc[sub], yva[sub], n_repeats=3,
                            random_state=0, scoring='roc_auc', n_jobs=2)
imp = pd.Series(pi.importances_mean, index=Xva.columns).sort_values(ascending=False)
print("\nTop 20 features (permutation importance, LONG model, validation):")
print(imp.head(20).round(5).to_string())
imp.to_csv('xauusd_bot/reports/ml_feature_importance.csv')
