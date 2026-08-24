import numpy as np
import pandas as pd

from xauusd_bot.backtesting.simulator import spread_series
from xauusd_bot.config import Config
from xauusd_bot.data.data_engine import DataEngine
from xauusd_bot.strategy import (breakout, liquidity_reversal, regime_engine, selector,
                                 setup_scorer, trend_continuation)


def test_regime_labels_and_confidence_bounded(synthetic_m1):
    cfg = Config()
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    assert set(R["regime"].unique()) <= set(regime_engine.REGIMES)
    assert R["regime_conf"].between(0, 1).all()
    assert R["strategy"].isin(["TREND_CONTINUATION", "LIQUIDITY_REVERSAL", "BREAKOUT",
                               "WAIT", "NO_TRADE", "STRICT"]).all()


def test_low_confidence_is_routed_to_no_trade(synthetic_m1):
    cfg = Config()
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    low = R["regime_conf"] < cfg.regime.min_confidence
    tradeable = R.loc[low, "strategy"].isin(
        ["TREND_CONTINUATION", "LIQUIDITY_REVERSAL", "BREAKOUT"])
    assert not tradeable.any()


def test_only_one_strategy_owns_a_bar(synthetic_m1):
    cfg = Config()
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    sig, counts = selector.select(F, R, cfg)
    fired = sig["dir"] != 0
    assert (sig.loc[fired, "strategy"] != "").all()
    assert sig.loc[~fired, "dir"].eq(0).all()
    # a bar can never carry two strategies
    assert sig["strategy"].map(lambda s: len(str(s).split(","))).max() == 1


def test_conflicting_directions_produce_no_trade(synthetic_m1):
    cfg = Config()
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    parts = {
        "T": trend_continuation.signals(F, R, cfg),
        "L": liquidity_reversal.signals(F, R, cfg),
        "B": breakout.signals(F, R, cfg),
    }
    d = np.stack([p["dir"].values for p in parts.values()])
    conflict = ((d > 0).any(axis=0)) & ((d < 0).any(axis=0))
    sig, _ = selector.select(F, R, cfg)
    assert (sig["dir"].values[conflict] == 0).all()


def test_stops_are_always_on_the_losing_side(synthetic_m1):
    cfg = Config()
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    sig, _ = selector.select(F, R, cfg)
    fired = (sig["dir"] != 0) & sig["sl"].notna()
    longs = fired & (sig["dir"] > 0)
    shorts = fired & (sig["dir"] < 0)
    assert (sig.loc[longs, "sl"] < F.loc[longs, "close"]).all()
    assert (sig.loc[shorts, "sl"] > F.loc[shorts, "close"]).all()


def test_setup_score_is_bounded_and_zero_when_flat(synthetic_m1):
    cfg = Config()
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    sig, _ = selector.select(F, R, cfg)
    sc = setup_scorer.score(F, sig, spread_series(F, cfg), cfg)
    assert sc["setup_score"].between(0, 100).all()
    assert (sc.loc[sig["dir"] == 0, "setup_score"] == 0).all()
    assert (sc.loc[sig["dir"] == 0, "grade"] == "NO_TRADE").all()


def test_strategy_toggles_actually_disable(synthetic_m1):
    F = DataEngine().build(synthetic_m1)
    for flag, name in [("toggles.trend_continuation", "TREND_CONTINUATION"),
                       ("toggles.liquidity_reversal", "LIQUIDITY_REVERSAL"),
                       ("toggles.breakout", "BREAKOUT")]:
        cfg = Config().with_overrides(**{flag: False})
        R = regime_engine.classify(F, cfg.regime)
        sig, _ = selector.select(F, R, cfg)
        assert (sig["strategy"] != name).all(), f"{name} fired while disabled"


def test_no_trades_outside_enabled_sessions(synthetic_m1):
    cfg = Config().with_overrides(**{"sessions.enabled_sessions": ("OVERLAP",)})
    F = DataEngine().build(synthetic_m1)
    R = regime_engine.classify(F, cfg.regime)
    sig, _ = selector.select(F, R, cfg)
    fired = sig["dir"] != 0
    assert (F.loc[fired, "session"] == "OVERLAP").all()
