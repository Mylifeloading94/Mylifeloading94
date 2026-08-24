"""Backtester correctness: fills, costs, ordering, and the pessimistic rules."""
import numpy as np
import pandas as pd
import pytest

from xauusd_bot.backtesting import simulator as sim
from xauusd_bot.backtesting.engine import Backtester
from xauusd_bot.backtesting.metrics import compute
from xauusd_bot.config import Config
from xauusd_bot.data.data_engine import DataEngine
from xauusd_bot.strategy import regime_engine, selector, setup_scorer

MICRO = {"instrument.min_lot": 0.001, "instrument.lot_step": 0.001}
# The shipped config is deliberately selective; on short synthetic series it
# would produce too few trades to test mechanics. These tests therefore relax
# the entry gate and cost filter - they verify FILL and RISK behaviour, not
# the strategy's selectivity.
PERMISSIVE = {**MICRO, "gate.require_retest": False,
              "gate.require_m15_alignment": False,
              "costs.max_cost_to_target_ratio": 1.0,
              "exits.stop_scale": 1.0}


def _run(F, cfg, news=None):
    R = regime_engine.classify(F, cfg.regime)
    sig, _ = selector.select(F, R, cfg)
    sp = sim.spread_series(F, cfg)
    sc = setup_scorer.score(F, sig, sp, cfg)
    return Backtester(cfg).run(F, R, sig, sc, news, cfg.initial_equity)


def test_entry_is_never_the_signal_bar_close(synthetic_m1):
    cfg = Config().with_overrides(**PERMISSIVE); cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    res = _run(F, cfg)
    if res.trades.empty:
        pytest.skip("no trades on synthetic data")
    for _, t in res.trades.iterrows():
        i = F.index.get_loc(t["ts_open"])
        # the fill must be based on THIS bar's open, not the previous close
        assert abs(t["entry"] - F["open"].iloc[i]) < 5.0
        assert t["ts_close"] >= t["ts_open"]


def test_costs_always_hurt(synthetic_m1):
    """Widening the spread can only reduce net profit, never increase it."""
    F = DataEngine().build(synthetic_m1)
    base = Config().with_overrides(**PERMISSIVE); base.initial_equity = 500.0
    wide = base.with_overrides(**{"costs.base_spread": 1.0,
                                  "costs.spread_by_session": {k: 1.0 for k in
                                  ["ASIA", "LONDON", "OVERLAP", "NEWYORK", "CLOSED"]},
                                  "costs.max_spread": 5.0})
    a = compute(*_wrap(_run(F, base)), 500.0)
    b = compute(*_wrap(_run(F, wide)), 500.0)
    if a["trades"] == 0 or b["trades"] == 0:
        pytest.skip("no trades")
    assert b["expectancy_money"] <= a["expectancy_money"] + 1e-9


def _wrap(res):
    return res.trades, res.equity


def test_commission_reduces_pnl(synthetic_m1):
    F = DataEngine().build(synthetic_m1)
    base = Config().with_overrides(**PERMISSIVE); base.initial_equity = 500.0
    withc = base.with_overrides(**{"costs.commission_per_lot_round_turn": 50.0})
    a = _run(F, base); b = _run(F, withc)
    if a.trades.empty:
        pytest.skip("no trades")
    assert b.trades["pnl"].sum() < a.trades["pnl"].sum()
    assert b.trades["commission"].sum() > 0


def test_stop_wins_when_both_hit_in_one_bar():
    """The pessimistic rule, checked directly on the fill functions."""
    cfg = Config()
    bar = {"open": 4600.0, "high": 4620.0, "low": 4580.0, "close": 4610.0}
    f = sim.exit_fill_stop(bar, 4590.0, 1, 0.30, cfg)
    assert f.price < 4590.0, "long stop must fill at or below the stop level"
    fs = sim.exit_fill_stop(bar, 4610.0, -1, 0.30, cfg)
    assert fs.price > 4610.0, "short stop must fill at or above the stop level"


def test_gap_through_stop_fills_at_the_open():
    cfg = Config()
    bar = {"open": 4570.0, "high": 4575.0, "low": 4560.0, "close": 4565.0}
    f = sim.exit_fill_stop(bar, 4590.0, 1, 0.30, cfg)
    assert f.price < 4570.0 and f.kind == "stop_gap"


def test_targets_get_no_positive_slippage():
    cfg = Config()
    f = sim.exit_fill_limit(4620.0, 1, 0.40, cfg)
    assert f.price < 4620.0, "a limit fill must be worsened by half the spread"


def test_entry_fill_is_worse_than_mid():
    cfg = Config()
    long = sim.entry_fill(4600.0, 1, 0.40, cfg)
    short = sim.entry_fill(4600.0, -1, 0.40, cfg)
    assert long.price > 4600.0 and short.price < 4600.0


def test_risk_never_exceeds_configured_percent(synthetic_m1):
    cfg = Config().with_overrides(**PERMISSIVE); cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    res = _run(F, cfg)
    if res.trades.empty:
        pytest.skip("no trades")
    assert res.trades["risk_percent"].max() <= cfg.risk.risk_percent + 1e-6


def test_never_more_than_one_position_at_a_time(synthetic_m1):
    cfg = Config().with_overrides(**PERMISSIVE); cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    res = _run(F, cfg)
    if len(res.trades) < 2:
        pytest.skip("not enough trades")
    t = res.trades.sort_values("ts_open")
    assert (t["ts_open"].shift(-1).dropna().values >=
            t["ts_close"].iloc[:-1].values).all(), "overlapping positions"


def test_news_blackout_blocks_entries(synthetic_m1):
    cfg = Config().with_overrides(**PERMISSIVE); cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    a = _run(F, cfg)
    block = pd.Series(True, index=F.index)
    b = _run(F, cfg, block)
    assert len(b.trades) == 0, "trades opened during a total news blackout"
    assert a.rejections.get("news_blackout", 0) == 0


def test_spread_block(synthetic_m1):
    cfg = Config().with_overrides(**{**PERMISSIVE, "costs.max_spread": 0.01})
    cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    res = _run(F, cfg)
    assert len(res.trades) == 0
    assert res.rejections.get("spread_blocked", 0) > 0


def test_no_overnight_positions(synthetic_m1):
    cfg = Config().with_overrides(**PERMISSIVE); cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    res = _run(F, cfg)
    if res.trades.empty:
        pytest.skip("no trades")
    closes = pd.to_datetime(res.trades["ts_close"])
    assert (closes.dt.hour <= cfg.sessions.flat_by_utc).all(), "position held past the flat time"


def test_equity_curve_matches_trade_pnl(synthetic_m1):
    cfg = Config().with_overrides(**PERMISSIVE); cfg.initial_equity = 500.0
    F = DataEngine().build(synthetic_m1)
    res = _run(F, cfg)
    if res.trades.empty:
        pytest.skip("no trades")
    # journal fields are rounded to 4dp, so allow the accumulated rounding
    tol = max(1e-4, 1e-4 * len(res.trades))
    assert res.trades["equity_after"].iloc[-1] == pytest.approx(
        500.0 + res.trades["pnl"].sum(), abs=tol)
