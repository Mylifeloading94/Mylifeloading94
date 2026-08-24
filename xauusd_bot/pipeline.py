"""
One place that turns raw M1 bars into a backtest result, so the backtester,
walk-forward, sensitivity and Monte-Carlo runners all use IDENTICAL logic.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from xauusd_bot.backtesting.engine import Backtester, BacktestResult
from xauusd_bot.backtesting.simulator import spread_series
from xauusd_bot.config import Config
from xauusd_bot.data.data_engine import DataEngine, FeatureParams
from xauusd_bot.news.news_filter import NewsFilter
from xauusd_bot.strategy import regime_engine, selector, setup_scorer


@dataclass
class Prepared:
    F: pd.DataFrame
    m1: pd.DataFrame


def prepare(m1: pd.DataFrame, fp: FeatureParams | None = None) -> Prepared:
    return Prepared(F=DataEngine(fp).build(m1), m1=m1)


def run(prep: Prepared, cfg: Config, news: NewsFilter | None = None,
        equity0: float | None = None) -> tuple[BacktestResult, dict]:
    F = prep.F
    R = regime_engine.classify(F, cfg.regime)
    sig, sel_counts = selector.select(F, R, cfg)
    sp = spread_series(F, cfg)
    scores = setup_scorer.score(F, sig, sp, cfg)
    mask = news.blackout_mask(F.index) if news is not None else None
    res = Backtester(cfg).run(F, R, sig, scores, mask, equity0)
    ctx = {"selector": sel_counts, "regimes": R["regime"].value_counts().to_dict()}
    res.stats.update(ctx)
    return res, {"R": R, "sig": sig, "scores": scores, "spread": sp}
