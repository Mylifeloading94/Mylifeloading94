import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="session")
def synthetic_m1():
    """Deterministic synthetic M1 with trends, ranges and a shock."""
    rng = np.random.default_rng(11)
    n = 20000
    idx = pd.date_range("2025-01-06 00:00", periods=n, freq="1min", tz="UTC")
    drift = np.concatenate([np.full(6000, 0.02), np.full(6000, -0.02),
                            np.zeros(4000), np.full(4000, 0.05)])
    step = drift + rng.standard_normal(n) * 0.35
    close = 2000 + np.cumsum(step)
    high = close + np.abs(rng.standard_normal(n)) * 0.4
    low = close - np.abs(rng.standard_normal(n)) * 0.4
    op = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame({"open": op, "high": np.maximum.reduce([high, op, close]),
                       "low": np.minimum.reduce([low, op, close]), "close": close}, index=idx)
    df.index.name = "time"
    return df


@pytest.fixture(scope="session")
def real_m1():
    p = Path("data_cache/m1_2026.pkl")
    if not p.exists():
        pytest.skip("real data cache not built")
    return pd.read_pickle(p).loc["2026-03-01":"2026-04-01"]
