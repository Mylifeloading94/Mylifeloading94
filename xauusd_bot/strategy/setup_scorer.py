"""
Setup Quality Score (0-100). Weights come from config so sensitivity testing
can sweep them; the threshold is validated, never assumed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from xauusd_bot.config import Config


def score(F: pd.DataFrame, sig: pd.DataFrame, spread: pd.Series, cfg: Config) -> pd.DataFrame:
    w = cfg.score
    atr_rank = F["M15_atr_rank"].fillna(0.5)
    atr_ok = (atr_rank > 0.15) & (atr_rank < 0.95)
    spread_ok = spread <= (cfg.costs.max_spread * 0.7)

    s = (sig["c_h1"].astype(float) * w.w_h1_regime
         + sig["c_m15"].astype(float) * w.w_m15_structure
         + sig["c_m5mom"].astype(float) * w.w_m5_momentum
         + sig["c_vwap"].astype(float) * w.w_vwap
         + sig["c_liq"].astype(float) * w.w_liquidity
         + sig["c_ltf"].astype(float) * w.w_ltf_structure
         + sig["c_retest"].astype(float) * w.w_retest
         + atr_ok.astype(float) * w.w_atr
         + spread_ok.astype(float) * w.w_spread)
    s = s.where(sig["dir"] != 0, 0.0)
    grade = pd.Series("NO_TRADE", index=F.index, dtype=object)
    grade[s >= w.grade_b] = "B"
    grade[s >= w.grade_a] = "A"
    grade[s >= w.grade_a_plus] = "A+"
    return pd.DataFrame({"setup_score": s.round(1), "grade": grade}, index=F.index)
