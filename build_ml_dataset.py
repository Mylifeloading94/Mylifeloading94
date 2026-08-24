"""Build the learned-model dataset year by year (memory-flat)."""
import sys, gc; sys.path.insert(0,'.')
import numpy as np, pandas as pd
from pathlib import Path
from xauusd_bot.ml.features import build, triple_barrier

TARGET_ATR, STOP_ATR, HORIZON = 0.8, 1.2, 120
STRIDE = 5                      # sample every 5th minute to limit label overlap
OUT = Path('data_cache/ml'); OUT.mkdir(parents=True, exist_ok=True)

for y in range(2015, 2027):
    p = Path(f'data_cache/features/F_{y}.pkl')
    if not p.exists(): continue
    out = OUT / f'ds_{y}.pkl'
    if out.exists():
        print(f'  {y}: cached', flush=True); continue
    F = pd.read_pickle(p)
    X = build(F)
    Y = triple_barrier(F, TARGET_ATR, STOP_ATR, HORIZON)
    keep = np.zeros(len(F), bool); keep[::STRIDE] = True
    # only bars we could actually trade: inside the FX week, both labels resolved
    keep &= (Y['y_long'] >= 0).values & (Y['y_short'] >= 0).values
    keep &= np.isfinite(X['atr_pct'].values)
    keep &= (F['dow'] < 5).values
    df = X[keep].copy()
    df['y_long'] = Y['y_long'][keep].values.astype(np.int8)
    df['y_short'] = Y['y_short'][keep].values.astype(np.int8)
    df['atr'] = Y['atr'][keep].values.astype(np.float32)
    df['target_px'] = Y['target_px'][keep].values.astype(np.float32)
    df['stop_px'] = Y['stop_px'][keep].values.astype(np.float32)
    df['t_long'] = Y['t_long'][keep].values.astype(np.int16)
    df['t_short'] = Y['t_short'][keep].values.astype(np.int16)
    df['close'] = F['close'][keep].values.astype(np.float32)
    df['session'] = F['session'][keep].values
    df.to_pickle(out)
    print(f'  {y}: {len(df):,} samples  long_win={df.y_long.mean():.3f} '
          f'short_win={df.y_short.mean():.3f}', flush=True)
    del F, X, Y, df; gc.collect()
print('done')
