"""
Grid / random search over the composite objective. Deliberately coarse: fine
grids on 7 months of data buy overfitting, not edge.
"""
from __future__ import annotations

import itertools
import random

import pandas as pd

from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.config import Config
from xauusd_bot.optimization.objective import score as obj_score
from xauusd_bot.pipeline import run


class _Prep:
    def __init__(self, F): self.F = F; self.m1 = None


def expand(space: dict) -> list[dict]:
    keys = list(space)
    return [dict(zip(keys, combo)) for combo in itertools.product(*[space[k] for k in keys])]


def search(F: pd.DataFrame, base: Config, space: dict, news=None, equity0=500.0,
           max_evals: int | None = None, seed: int = 3, verbose: bool = True) -> pd.DataFrame:
    grid = expand(space)
    if max_evals and len(grid) > max_evals:
        random.Random(seed).shuffle(grid)
        grid = grid[:max_evals]
    rows = []
    for i, params in enumerate(grid, 1):
        cfg = base.with_overrides(**params); cfg.initial_equity = equity0
        res, _ = run(_Prep(F), cfg, news, equity0)
        m = compute(res.trades, res.equity, equity0)
        rows.append({**params, "trades": m["trades"], "win%": round(m["win_rate"], 1),
                     "PF": round(min(m["profit_factor"], 9.99), 2),
                     "ret%": round(m["net_return_pct"], 2), "dd%": round(m["max_dd_pct"], 2),
                     "expR": round(m["expectancy_r"], 3), "obj": round(obj_score(m), 3)})
        if verbose and i % 10 == 0:
            print(f"    ...{i}/{len(grid)}")
    return pd.DataFrame(rows).sort_values("obj", ascending=False).reset_index(drop=True)
