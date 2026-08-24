"""One-parameter-at-a-time sweeps. Looking for PLATEAUS, not peaks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.config import Config
from xauusd_bot.optimization.objective import score as obj_score
from xauusd_bot.pipeline import run


class _Prep:
    def __init__(self, F): self.F = F; self.m1 = None


def sweep(F: pd.DataFrame, base: Config, key: str, values: list, news=None,
          equity0: float = 500.0) -> pd.DataFrame:
    rows = []
    for v in values:
        cfg = base.with_overrides(**{key: v}); cfg.initial_equity = equity0
        res, _ = run(_Prep(F), cfg, news, equity0)
        m = compute(res.trades, res.equity, equity0)
        rows.append({"param": key, "value": v, "trades": m["trades"],
                     "win%": round(m["win_rate"], 1),
                     "PF": round(min(m["profit_factor"], 9.99), 2),
                     "ret%": round(m["net_return_pct"], 2),
                     "dd%": round(m["max_dd_pct"], 2),
                     "expR": round(m["expectancy_r"], 3),
                     "obj": round(obj_score(m), 3)})
    return pd.DataFrame(rows)


def robustness(df: pd.DataFrame) -> dict:
    """A parameter is robust if neighbours of the best value also work."""
    if df.empty or df["trades"].sum() == 0:
        return {"robust": False, "reason": "no trades"}
    d = df.reset_index(drop=True)
    b = int(d["obj"].idxmax())
    neigh = d.iloc[max(0, b - 1):b + 2]
    ok = (neigh["PF"] > 1.0).all() and (neigh["expR"] > 0).all()
    return {"best_value": d.loc[b, "value"], "best_obj": d.loc[b, "obj"],
            "neighbours_ok": bool(ok),
            "pct_values_profitable": round(100 * (d["PF"] > 1).mean(), 1),
            "obj_spread": round(float(d["obj"].max() - d["obj"].min()), 3),
            "robust": bool(ok and (d["PF"] > 1).mean() >= 0.5)}
