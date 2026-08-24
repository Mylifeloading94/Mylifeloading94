"""Load the chunked feature matrix for a date range."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

FEAT = Path("data_cache/features")

TRAIN = ("2015-01-01", "2022-01-01")     # 7 years - optimise here ONLY
VALID = ("2022-01-01", "2024-01-01")     # 2 years - model selection
TEST  = ("2024-01-01", "2026-08-25")     # 2.6 years - opened once, at the end


def load(start: str, end: str) -> pd.DataFrame:
    a, b = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    frames = []
    for y in range(a.year, b.year + 1):
        p = FEAT / f"F_{y}.pkl"
        if not p.exists():
            continue
        f = pd.read_pickle(p)
        f = f.loc[(f.index >= a) & (f.index < b)]
        if len(f):
            frames.append(f)
    if not frames:
        raise FileNotFoundError(f"no features for {start}..{end}")
    return pd.concat(frames).sort_index()
