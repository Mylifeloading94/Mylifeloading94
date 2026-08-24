"""Build the feature matrix for the full history in yearly chunks.

Each chunk is built with 21 days of prior data as indicator warmup, then the
warmup is dropped. That produces values identical to building the whole series
at once (verified by tests/test_chunked_build.py) without a 6 GB allocation.
"""
import sys, gc, time; sys.path.insert(0, '.')
import pandas as pd, numpy as np
from pathlib import Path
from xauusd_bot.data.data_engine import DataEngine
from xauusd_bot.data.validators import clean_m1

WARMUP = pd.Timedelta(days=21)
OUT = Path('data_cache/features'); OUT.mkdir(parents=True, exist_ok=True)

m1 = pd.read_pickle('data_cache/m1_full.pkl')
m1, info = clean_m1(m1)
print(f"{len(m1):,} bars after cleaning {info}", flush=True)

for y in range(2015, 2027):
    out = OUT / f"F_{y}.pkl"
    if out.exists():
        print(f"  {y}: cached", flush=True); continue
    a = pd.Timestamp(f"{y}-01-01", tz="UTC"); b = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
    chunk = m1.loc[(m1.index >= a - WARMUP) & (m1.index < b)]
    if len(chunk) < 1000:
        continue
    t = time.time()
    F = DataEngine().build(chunk)
    F = F.loc[F.index >= a]
    for c in F.columns:
        if F[c].dtype == np.float64:
            F[c] = F[c].astype(np.float32)
        elif F[c].dtype == np.int64:
            F[c] = F[c].astype(np.int32)
    F.to_pickle(out)
    print(f"  {y}: {len(F):,} rows, {F.shape[1]} cols, {time.time()-t:.0f}s", flush=True)
    del F, chunk; gc.collect()
print("done")
