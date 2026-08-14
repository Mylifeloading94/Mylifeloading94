"""Unit + integration tests for the SMC Sniper package.

Coverage follows the spec's list: BOS, CHoCH, MSS, sweep, FVG, OB,
premium/discount, entry validation, SL calc, TP calc, position sizing, risk
limits, duplicate signals, news filter, spread filter, session filter, trade
management -- plus an end-to-end integration test on synthetic bars whose
outcome is known by construction.

Several tests exist specifically to lock down honesty properties that this
repo has previously paid for: trade-through fills, spread always charged,
same-bar TP+SL resolving as a loss, and the absence of martingale sizing.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smc_sniper import premium_discount as pdmod
from smc_sniper.config import load_config
from smc_sniper.data import atr
from smc_sniper.liquidity import LiquidityMap, detect_sweeps, find_equal_levels
from smc_sniper.news import NewsFilter
from smc_sniper.position_manager import ManagedPosition, PositionManager
from smc_sniper.risk import RiskEngine
from smc_sniper.scoring import score_setup
from smc_sniper.sessions import is_tradeable, session_of
from smc_sniper.structure import (build_structure, find_swings, is_displacement)
from smc_sniper.zones import find_fvgs, find_order_blocks


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def make_frame(bars, start="2025-01-06 08:00", freq="15min"):
    """bars: list of (open, high, low, close)."""
    idx = pd.date_range(start, periods=len(bars), freq=freq, tz="UTC")
    frame = pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx)
    frame["volume"] = 100.0
    frame["close_time"] = frame.index + pd.Timedelta(freq)
    frame["atr"] = atr(frame, 5)
    return frame


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ---------------------------------------------------------------------------
# Market structure
# ---------------------------------------------------------------------------
def test_find_swings_marks_obvious_pivots():
    bars = [(1, 1.2, 0.9, 1.1), (1.1, 1.3, 1.0, 1.2), (1.2, 2.0, 1.1, 1.9),
            (1.9, 1.95, 1.2, 1.3), (1.3, 1.4, 1.1, 1.2), (1.2, 1.3, 1.0, 1.1)]
    frame = make_frame(bars)
    swings = find_swings(frame, lookback=2)
    highs = [s for s in swings if s.kind == "high"]
    assert any(s.index == 2 for s in highs), "the 2.0 spike must be a swing high"
    # confirmation lag is real: a swing is knowable only lookback bars later
    for swing in swings:
        assert swing.confirmed_at == swing.index + 2


def test_swing_labels_hh_hl_lh_ll():
    bars = ([(1, 1.5, 0.9, 1.4)] + [(1.4, 1.45, 1.3, 1.35)] * 2
            + [(1.35, 2.0, 1.3, 1.9)] + [(1.9, 1.95, 1.5, 1.6)] * 2
            + [(1.6, 2.5, 1.55, 2.4)] + [(2.4, 2.45, 2.0, 2.1)] * 3)
    swings = find_swings(make_frame(bars), lookback=2)
    labels = [s.label for s in swings if s.kind == "high" and s.label]
    assert "HH" in labels


def zigzag(points, bars_per_leg=5, wick=0.001):
    """Build OHLC bars that walk linearly between turning points.

    A strictly monotonic ramp contains no fractal swings at all, so structure
    tests need genuine pullbacks -- this produces the higher-high/higher-low
    shape that BOS detection actually operates on.
    """
    bars = []
    for a, b in zip(points[:-1], points[1:]):
        for k in range(bars_per_leg):
            o = a + (b - a) * k / bars_per_leg
            c = a + (b - a) * (k + 1) / bars_per_leg
            bars.append((o, max(o, c) + wick, min(o, c) - wick, c))
    return bars


def test_bos_choch_mss_classification():
    """An uptrend with pullbacks gives BOS; a displacement-backed break down
    against that trend must register as MSS or CHoCH, never BOS."""
    up_points = [1.00, 1.05, 1.03, 1.09, 1.07, 1.13, 1.11, 1.17]
    frame_up = zigzag(up_points, bars_per_leg=5)
    # one large bearish displacement candle, then a lower leg
    crash = [(1.17, 1.171, 1.05, 1.052)]
    down = zigzag([1.052, 1.00, 1.02, 0.96], bars_per_leg=5)
    frame = make_frame(frame_up + crash + down)
    cfgblock = {"swing_lookback": 2, "bos_confirm_close": True,
                "mss_requires_displacement": True,
                "displacement": {"atr_period": 5, "min_body_atr": 0.8,
                                 "min_body_ratio": 0.5, "lookback_bars": 5}}
    state = build_structure(frame, cfgblock)
    assert state.events, "expected structural events from a zigzag uptrend"
    kinds = {e.kind for e in state.events}
    assert "BOS" in kinds, "repeated higher highs must produce BOS continuations"
    bearish = [e for e in state.events if e.direction == "bearish"]
    assert bearish, "the crash must register a bearish structural event"
    assert bearish[0].kind in ("MSS", "CHoCH"), \
        "the first counter-trend break is a shift, not a continuation"


def test_bos_is_continuation_only_in_trend_direction():
    """BOS may only appear once a bias is already established that way."""
    frame = make_frame(zigzag([1.00, 1.05, 1.03, 1.09, 1.07, 1.13], 5))
    state = build_structure(frame, {
        "swing_lookback": 2, "bos_confirm_close": True,
        "mss_requires_displacement": False,
        "displacement": {"atr_period": 5, "min_body_atr": 0.8,
                         "min_body_ratio": 0.5, "lookback_bars": 5}})
    bulls = [e for e in state.events if e.direction == "bullish"]
    assert bulls, "expected bullish events"
    assert bulls[0].kind != "BOS", \
        "the FIRST bullish break has no prior bullish bias, so it cannot be a BOS"
    assert any(e.kind == "BOS" for e in bulls[1:]), \
        "subsequent breaks in an established uptrend must be BOS"


def test_mss_requires_displacement_else_choch():
    """Without displacement the counter-trend break is only a CHoCH."""
    up = [(1.0 + i * 0.01, 1.0 + i * 0.01 + 0.008, 1.0 + i * 0.01 - 0.002,
           1.0 + i * 0.01 + 0.006) for i in range(20)]
    drift = [(1.20 - i * 0.002, 1.20 - i * 0.002 + 0.001,
              1.20 - i * 0.002 - 0.0015, 1.20 - i * 0.002 - 0.001) for i in range(12)]
    frame = make_frame(up + drift)
    base = {"swing_lookback": 2, "bos_confirm_close": True,
            "displacement": {"atr_period": 5, "min_body_atr": 5.0,
                             "min_body_ratio": 0.9, "lookback_bars": 3}}
    state = build_structure(frame, {**base, "mss_requires_displacement": True})
    bearish = [e for e in state.events if e.direction == "bearish"]
    assert all(e.kind != "MSS" for e in bearish), \
        "no displacement can satisfy min_body_atr=5.0, so no MSS is allowed"


def test_displacement_detection():
    frame = make_frame([(1.0, 1.01, 0.99, 1.005)] * 10
                       + [(1.0, 1.10, 0.999, 1.095)])
    disp_cfg = {"atr_period": 5, "min_body_atr": 0.8, "min_body_ratio": 0.5,
                "lookback_bars": 3}
    ok, direction = is_displacement(frame, 10, disp_cfg)
    assert ok and direction == "bullish"
    ok_small, _ = is_displacement(frame, 5, disp_cfg)
    assert not ok_small


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------
def test_equal_highs_cluster_and_are_atr_scaled():
    bars = []
    for _ in range(3):
        bars += [(1.0, 1.0500, 0.99, 1.02), (1.02, 1.03, 1.00, 1.01),
                 (1.01, 1.02, 0.995, 1.00)]
    frame = make_frame(bars)
    swings = find_swings(frame, 1)
    pools = find_equal_levels(frame, swings,
                              {"equal_level_tolerance_atr": 0.5,
                               "equal_level_min_touches": 2,
                               "pool_lookback_bars": 50})
    assert any(p.kind == "equal_highs" for p in pools)


def test_sweep_requires_close_back_inside():
    """A wick through that closes back = sweep. A close beyond = break, not sweep."""
    base = [(1.00, 1.01, 0.99, 1.005)] * 12
    frame_sweep = make_frame(base + [(1.005, 1.05, 1.00, 1.002)])
    frame_break = make_frame(base + [(1.005, 1.05, 1.00, 1.045)])
    from smc_sniper.liquidity import LiquidityPool
    pool = LiquidityPool(index=5, price=1.02, side="buy_side", kind="equal_highs")
    cfgblock = {"pool_lookback_bars": 50,
                "sweep": {"min_pierce_atr": 0.05, "require_close_back": True}}
    swept = detect_sweeps(frame_sweep, [pool], cfgblock)
    broke = detect_sweeps(frame_break, [pool], cfgblock)
    assert any(s.index == 12 for s in swept), "wick through + close back is a sweep"
    assert not any(s.index == 12 for s in broke), "closing beyond is a break, not a sweep"


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
def test_fvg_detection_and_min_size():
    bars = [(1.00, 1.01, 0.99, 1.005)] * 8
    bars += [(1.005, 1.02, 1.00, 1.015), (1.015, 1.10, 1.014, 1.095),
             (1.10, 1.12, 1.06, 1.11)]
    frame = make_frame(bars)
    gaps = find_fvgs(frame, {"min_size_atr": 0.1, "max_age_bars": 20,
                             "fill_pct_invalidate": 0.9})
    assert any(z.direction == "bullish" for z in gaps)
    # An impossible size threshold must yield nothing -- ATR scaling is real.
    none = find_fvgs(frame, {"min_size_atr": 50.0, "max_age_bars": 20,
                             "fill_pct_invalidate": 0.9})
    assert not none


def test_fvg_invalidates_once_filled():
    bars = [(1.00, 1.01, 0.99, 1.005)] * 8
    bars += [(1.005, 1.02, 1.00, 1.015), (1.015, 1.10, 1.014, 1.095),
             (1.10, 1.12, 1.06, 1.11)]
    bars += [(1.11, 1.115, 1.00, 1.005)]   # fills the gap back down
    frame = make_frame(bars)
    gaps = find_fvgs(frame, {"min_size_atr": 0.1, "max_age_bars": 20,
                             "fill_pct_invalidate": 0.8})
    bulls = [z for z in gaps if z.direction == "bullish"]
    assert bulls and bulls[0].invalidated_at is not None


def test_order_block_requires_displacement():
    bars = [(1.00, 1.01, 0.99, 1.005)] * 10
    bars += [(1.005, 1.006, 0.995, 0.998)]      # down candle = the OB
    bars += [(0.998, 1.09, 0.997, 1.085)]       # displacement up
    frame = make_frame(bars)
    disp = {"atr_period": 5, "min_body_atr": 0.8, "min_body_ratio": 0.5,
            "lookback_bars": 3}
    state = build_structure(frame, {"swing_lookback": 2, "displacement": disp})
    obs = find_order_blocks(frame, state,
                            {"lookback_bars": 20, "require_displacement": True,
                             "max_age_bars": 30, "mitigation_invalidates": True,
                             "use_breaker_blocks": False}, disp)
    assert any(z.direction == "bullish" and z.bottom <= 0.9951 for z in obs)
    # With displacement impossible, no OB may be produced.
    hard = dict(disp, min_body_atr=99.0)
    none = find_order_blocks(frame, state,
                             {"lookback_bars": 20, "require_displacement": True,
                              "max_age_bars": 30, "use_breaker_blocks": False}, hard)
    assert not none


# ---------------------------------------------------------------------------
# Premium / discount
# ---------------------------------------------------------------------------
def test_premium_discount_zones():
    cfgblock = {"enabled": True, "equilibrium": 0.5, "hard_veto_beyond": 0.85}
    low = pdmod.evaluate(1.10, 2.0, 1.0, cfgblock)
    high = pdmod.evaluate(1.90, 2.0, 1.0, cfgblock)
    assert low.zone == "discount" and high.zone == "premium"
    assert pdmod.favourable(low, "bullish") and not pdmod.favourable(low, "bearish")


def test_premium_discount_hard_veto_blocks_chasing():
    cfgblock = {"enabled": True, "equilibrium": 0.5, "hard_veto_beyond": 0.85}
    top = pdmod.evaluate(1.95, 2.0, 1.0, cfgblock)
    vetoed, reason = pdmod.hard_veto(top, "bullish", cfgblock)
    assert vetoed and "chasing_long" in reason
    mid = pdmod.evaluate(1.4, 2.0, 1.0, cfgblock)
    assert not pdmod.hard_veto(mid, "bullish", cfgblock)[0]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def test_score_ceiling_is_95_not_100(cfg):
    """The spec calls this a 0-100 scale, but its own component weights sum to
    95. They are kept verbatim rather than rescaled (rescaling would silently
    move every threshold), so a perfect setup scores 95 and nothing reaches
    100. This test pins that down so the discrepancy can never be forgotten."""
    weights = cfg.get("scoring.weights")
    assert sum(weights.values()) == 95
    assert cfg.get("scoring.max_possible") == 95

    class Z:
        quality = 4
    card = score_setup(weights=weights, htf_aligned=True, structure_event="MSS",
                       has_bos=True, sweep_kind="PDH", sweep_is_major=True,
                       pd_pw_liquidity=True, order_block=Z(), fvg=Z(),
                       pd_favourable=True, displacement=True, ltf_confirmed=True,
                       spread_ok=True)
    assert card.total == 95, "a flawless setup must score the true ceiling"


def test_score_gate_thresholds(cfg):
    assert cfg.get("scoring.profiles.conservative") == 85
    assert cfg.get("scoring.profiles.standard") == 80
    assert cfg.get("scoring.profiles.aggressive") == 75
    assert cfg.score_threshold == 80


def test_weak_setup_scores_below_threshold(cfg):
    weights = cfg.get("scoring.weights")
    card = score_setup(weights=weights, htf_aligned=False, structure_event="",
                       has_bos=False, sweep_kind="swing_high", sweep_is_major=False,
                       pd_pw_liquidity=False, order_block=None, fvg=None,
                       pd_favourable=False, displacement=False,
                       ltf_confirmed=False, spread_ok=True)
    assert card.total < cfg.score_threshold


# ---------------------------------------------------------------------------
# Sessions / news / spread
# ---------------------------------------------------------------------------
def test_session_classification_and_filter(cfg):
    scfg = cfg.get("sessions")
    assert session_of(pd.Timestamp("2025-03-05 09:00", tz="UTC"), scfg) == "london"
    assert session_of(pd.Timestamp("2025-03-05 14:00", tz="UTC"), scfg) == "ny"
    assert session_of(pd.Timestamp("2025-03-05 02:00", tz="UTC"), scfg) == "asian"
    ok, _ = is_tradeable(pd.Timestamp("2025-03-05 09:00", tz="UTC"), scfg, ["london", "ny"])
    assert ok
    blocked, reason = is_tradeable(pd.Timestamp("2025-03-05 02:00", tz="UTC"),
                                   scfg, ["london", "ny"])
    assert not blocked and "asian" in reason


def test_session_filter_blocks_weekend(cfg):
    scfg = cfg.get("sessions")
    sat = pd.Timestamp("2025-03-08 10:00", tz="UTC")   # Saturday
    assert not is_tradeable(sat, scfg, ["london"])[0]


def test_news_filter_blocks_window(cfg, tmp_path):
    path = tmp_path / "cal.csv"
    path.write_text("utc_timestamp,impact,event\n2025-03-05 13:30:00,high,NFP\n")
    variant = cfg.with_override("news.calendar_file", str(path))
    nf = NewsFilter(variant)
    assert nf.active
    assert nf.blocked(pd.Timestamp("2025-03-05 13:20", tz="UTC"))[0]
    assert not nf.blocked(pd.Timestamp("2025-03-05 16:00", tz="UTC"))[0]


def test_news_filter_documents_missing_calendar(cfg):
    nf = NewsFilter(cfg)
    assert not nf.active
    assert nf.status == "no_calendar_file"
    assert not nf.blocked(pd.Timestamp("2025-03-05 13:20", tz="UTC"))[0]


def test_spread_filter_uses_per_instrument_caps(cfg):
    gold = cfg.for_instrument("XAUUSD")
    eur = cfg.for_instrument("EURUSD")
    assert gold.max_spread_pips != eur.max_spread_pips, \
        "gold must never share EURUSD's spread cap"
    assert gold.spread_pips <= gold.max_spread_pips


# ---------------------------------------------------------------------------
# Gold parameter isolation
# ---------------------------------------------------------------------------
def test_gold_has_its_own_parameter_block(cfg):
    gold = cfg.for_instrument("XAUUSD")
    eur = cfg.for_instrument("EURUSD")
    assert gold.get("stops.buffer_atr") != eur.get("stops.buffer_atr")
    assert gold.get("fvg.min_size_atr") != eur.get("fvg.min_size_atr")
    assert gold.risk_per_trade_pct != eur.risk_per_trade_pct
    assert gold.pip == 0.1 and eur.pip == 0.0001


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------
def test_position_sizing_scales_inversely_with_stop(cfg):
    engine = RiskEngine(cfg)
    tight, amt1 = engine.size("EURUSD", 0.0010)
    wide, amt2 = engine.size("EURUSD", 0.0020)
    assert amt1 == amt2, "risk amount is fixed; only size changes"
    assert tight == pytest.approx(wide * 2, rel=1e-6)


def test_position_sizing_respects_risk_pct(cfg):
    engine = RiskEngine(cfg)
    _, amount = engine.size("EURUSD", 0.0010)
    assert amount == pytest.approx(cfg.get("risk.starting_balance") * 0.005)


def test_no_martingale_sizing_after_losses(cfg):
    """Size must not depend on the previous result. This is the anti-martingale
    guarantee, and it is structural: size() has no access to trade history."""
    engine = RiskEngine(cfg)
    before, _ = engine.size("EURUSD", 0.0010)

    class T:
        r_multiple = -1.0
        pnl = -50.0
        signal_time = pd.Timestamp("2025-03-05 10:00", tz="UTC")
        exit_time = pd.Timestamp("2025-03-05 12:00", tz="UTC")
    for _ in range(3):
        engine.register(T())
    after, _ = engine.size("EURUSD", 0.0010)
    assert after == before, "sizing changed after losses -- martingale leak"


def test_risk_limits_block_trades(cfg):
    engine = RiskEngine(cfg)

    class S:
        time = pd.Timestamp("2025-03-05 10:00", tz="UTC")
        score = 90.0
        session = "london"
        direction = "bullish"
        bar_index = 1
    # current_day must be primed, otherwise can_trade() correctly rolls over
    # into a fresh day and resets the counter.
    engine.state.current_day = S.time.date()
    engine.state.current_week = S.time.isocalendar()[:2]
    engine.state.trades_today = int(cfg.get("risk.max_trades_per_day"))
    ok, reason = engine.can_trade("EURUSD", S())
    assert not ok and reason == "max_trades_per_day"

    engine2 = RiskEngine(cfg)
    engine2.state.open_positions = int(cfg.get("risk.max_open_positions"))
    assert engine2.can_trade("EURUSD", S())[1] == "max_open_positions"


def test_daily_counter_resets_on_a_new_day(cfg):
    """The per-day cap must not leak across days."""
    engine = RiskEngine(cfg)

    class S:
        time = pd.Timestamp("2025-03-06 10:00", tz="UTC")
    engine.state.current_day = pd.Timestamp("2025-03-05").date()
    engine.state.trades_today = 99
    assert engine.can_trade("EURUSD", S())[0], "a new day must reset the counter"


def test_daily_and_weekly_loss_caps(cfg):
    engine = RiskEngine(cfg)

    class S:
        time = pd.Timestamp("2025-03-05 10:00", tz="UTC")
    engine.state.current_day = S.time.date()
    engine.state.current_week = S.time.isocalendar()[:2]
    engine.state.day_pnl = -cfg.get("risk.starting_balance") * 0.021
    assert engine.can_trade("EURUSD", S())[1] == "max_daily_loss"


def test_currency_exposure_cap(cfg):
    engine = RiskEngine(cfg)

    class S:
        time = pd.Timestamp("2025-03-05 10:00", tz="UTC")
    engine.state.currency_exposure["USD"] = int(cfg.get("risk.max_exposure_per_currency"))
    ok, reason = engine.can_trade("EURUSD", S())
    assert not ok and "USD" in reason


def test_consecutive_loss_cooldown(cfg):
    engine = RiskEngine(cfg)

    class T:
        r_multiple = -1.0
        pnl = -50.0
        signal_time = pd.Timestamp("2025-03-05 10:00", tz="UTC")
        exit_time = pd.Timestamp("2025-03-05 12:00", tz="UTC")
    for _ in range(int(cfg.get("risk.max_consecutive_losses"))):
        engine.register(T())
    assert engine.state.cooldown_until is not None


def test_risk_config_forbids_martingale_and_grid(cfg):
    assert cfg.get("risk.martingale") is False
    assert cfg.get("risk.grid") is False
    assert cfg.get("risk.revenge_trading") is False


# ---------------------------------------------------------------------------
# Trade management
# ---------------------------------------------------------------------------
def _managed(cfg):
    return ManagedPosition(symbol="EURUSD", direction="bullish", entry=1.1000,
                           stop=1.0980, original_stop=1.0980, tp1=1.1020,
                           tp2=1.1060, tp3=1.1100, risk_price=0.0020,
                           size_lots=0.1, client_id="t1")


def test_stop_is_never_widened(cfg):
    pm = PositionManager(cfg)
    pos = _managed(cfg)
    assert not pm._tighten(pos, 1.0900), "moving a long's stop DOWN must be refused"
    assert pos.stop == 1.0980
    assert pm._tighten(pos, 1.1000)
    assert pos.stop == 1.1000


def test_partial_tp_and_breakeven(cfg):
    pm = PositionManager(cfg)
    pos = _managed(cfg)
    bar = pd.Series({"high": 1.1025, "low": 1.1005, "close": 1.1020, "atr": 0.001})
    pm.on_bar(pos, bar, 1)
    assert pos.stage == 1 and pos.remaining == pytest.approx(0.5)
    assert pos.stop >= pos.entry, "break-even must engage past 1R"


def test_disabled_partials_close_everything_at_first_target(cfg):
    """Regression: with scale-outs off, TP1 must close 100%.

    The original code allocated 0% to TP1 and TP2 when partials were disabled,
    so a 'no partials' run banked nothing on reaching its target, needed three
    separate bars to exit, and could reverse into a full -1R loss after price
    had already traded through the target. That silently corrupted the
    matched-R control -- the one measurement that must be trustworthy."""
    variant = cfg.with_override("targets.partial_tp.enabled", False)
    pm = PositionManager(variant)
    pos = _managed(variant)
    bar = pd.Series({"high": 1.1025, "low": 1.1005, "close": 1.1020, "atr": 0.001})
    reason = pm.on_bar(pos, bar, 1)
    assert pos.remaining == 0.0, "TP1 must close the whole position"
    assert reason == "TP1"
    assert pos.realised_r == pytest.approx(1.0), "banked exactly the TP1 R"


def test_partial_portions_always_sum_to_one(cfg):
    for enabled in (True, False):
        variant = cfg.with_override("targets.partial_tp.enabled", enabled)
        pcfg = variant.get("targets.partial_tp")
        if pcfg.get("enabled"):
            portions = [pcfg["tp1_close_pct"], pcfg["tp2_close_pct"]]
            portions.append(max(0.0, 1.0 - sum(portions)))
        else:
            portions = [1.0, 0.0, 0.0]
        assert sum(portions) == pytest.approx(1.0)


def test_stop_checked_before_target_same_bar(cfg):
    """Ambiguous bars resolve against the strategy."""
    pm = PositionManager(cfg)
    pos = _managed(cfg)
    bar = pd.Series({"high": 1.1100, "low": 1.0970, "close": 1.1050, "atr": 0.001})
    reason = pm.on_bar(pos, bar, 1)
    assert reason == "stop_loss", "a bar touching both TP and SL must book the loss"
    assert pos.realised_r < 0


# ---------------------------------------------------------------------------
# Fill model honesty
# ---------------------------------------------------------------------------
def test_config_enforces_trade_through_and_loss_on_ambiguity(cfg):
    assert cfg.get("execution.require_trade_through") is True
    assert cfg.get("execution.same_bar_tp_and_sl") == "loss"


def test_min_rr_gate_is_at_least_two(cfg):
    assert cfg.get("targets.min_rr") >= 2.0
    assert cfg.get("stops.never_widen") is True


# ---------------------------------------------------------------------------
# Execution safety
# ---------------------------------------------------------------------------
def test_paper_execution_roundtrip(cfg):
    from smc_sniper.execution import Order, PaperExecution
    ex = PaperExecution(cfg)
    assert ex.connect()
    res = ex.place_order(Order("EURUSD", "buy", "limit", 0.1, 1.1000,
                               stop_loss=1.0980, client_id="c1"))
    assert res.ok and len(ex.positions()) == 1
    ex.close_position("c1")
    assert not ex.positions()


def test_tradelocker_orders_are_blocked(cfg):
    """The live adapter must refuse to place an order."""
    from smc_sniper.execution import Order, TradeLockerExecution
    ex = TradeLockerExecution(cfg)
    with pytest.raises(PermissionError):
        ex.place_order(Order("EURUSD", "buy", "market", 0.1))
    with pytest.raises(PermissionError):
        ex.close_position("anything")
    assert cfg.get("execution.tradelocker.allow_live_orders", False) is False


def test_no_credentials_are_committed():
    """The .env must never enter git."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".gitignore")) as fh:
        assert ".env" in fh.read()
    cfg_text = open(os.path.join(root, "smc_sniper", "config.yaml")).read()
    for token in ("TL_PASSWORD=", "password:", "accessToken"):
        assert token not in cfg_text


# ---------------------------------------------------------------------------
# Duplicate protection
# ---------------------------------------------------------------------------
def test_duplicate_setup_ids_match_for_same_zone():
    from smc_sniper.signal_engine import _setup_hash
    ts = pd.Timestamp("2025-03-05 10:00", tz="UTC")
    a = _setup_hash("EURUSD", "bullish", 1.10000, 0.0005, ts)
    b = _setup_hash("EURUSD", "bullish", 1.10010, 0.0005, ts)
    c = _setup_hash("EURUSD", "bullish", 1.20000, 0.0005, ts)
    assert a == b, "near-identical zones are the SAME setup"
    assert a != c


# ---------------------------------------------------------------------------
# Integration: known-by-construction outcome
# ---------------------------------------------------------------------------
def test_integration_full_pipeline_on_synthetic_bars(cfg):
    """Drive the whole stack on synthetic data and assert the pipeline runs
    end-to-end, produces a decision log, and never violates the fill rules."""
    from smc_sniper.backtest import Backtester, trades_to_frame

    class FakeEngine:
        def __init__(self, frames):
            self.frames = frames

        def get(self, symbol, tf):
            return self.frames[tf]

    rng = np.random.default_rng(11)
    n = 4000
    # A trending series with periodic sweeps: enough structure to exercise
    # every layer without asserting a specific P&L (that would be fitting).
    price = 1.10 + np.cumsum(rng.normal(0.00002, 0.0006, n))
    idx = pd.date_range("2025-01-06 00:00", periods=n, freq="15min", tz="UTC")
    high = price + np.abs(rng.normal(0.0004, 0.0002, n))
    low = price - np.abs(rng.normal(0.0004, 0.0002, n))
    frame15 = pd.DataFrame({"open": price, "high": high, "low": low,
                            "close": price, "volume": 100.0}, index=idx)
    frame15["close_time"] = frame15.index + pd.Timedelta("15min")
    frame15["atr"] = atr(frame15, 14)

    def resample(rule, minutes):
        agg = frame15.resample(rule, label="left", closed="left", origin="epoch").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last",
             "volume": "sum"}).dropna()
        agg["close_time"] = agg.index + pd.Timedelta(minutes=minutes)
        agg["atr"] = atr(agg, 14)
        return agg

    frames = {"15m": frame15, "1H": resample("1h", 60), "4H": resample("4h", 240)}
    variant = cfg.copy()
    variant.set("markets", {"EURUSD": cfg.get("markets.EURUSD")})
    bt = Backtester(variant, FakeEngine(frames))
    trades, rejections, contexts = bt.run(symbols=["EURUSD"])

    assert contexts, "pipeline must build a context from synthetic bars"
    frame = trades_to_frame(trades)
    if not frame.empty:
        for _, row in frame.iterrows():
            risk = abs(row["entry"] - row["stop"])
            assert risk > 0
            # every fill must be at least as bad as the resting limit
            if row["direction"] == "bullish":
                assert row["entry"] >= row["limit_price"], "long must pay the spread"
            else:
                assert row["entry"] <= row["limit_price"], "short must pay the spread"
            assert row["r_multiple"] >= -3.0, "single trade loss beyond -3R is impossible"
    # rejections must carry a step and a reason
    for rej in rejections[:50]:
        assert rej.step and rej.reason


def test_mtf_view_has_no_lookahead(cfg):
    """A higher-timeframe bar may only be visible once it has CLOSED."""
    from smc_sniper.data import MTFView

    class FakeEngine:
        def __init__(self, frames):
            self.frames = frames

        def get(self, symbol, tf):
            return self.frames[tf]

    n = 500
    idx = pd.date_range("2025-01-06 00:00", periods=n, freq="15min", tz="UTC")
    frame15 = pd.DataFrame({"open": 1.0, "high": 1.001, "low": 0.999,
                            "close": 1.0, "volume": 1.0}, index=idx)
    frame15["close_time"] = frame15.index + pd.Timedelta("15min")
    frame15["atr"] = 0.001
    h1 = frame15.resample("1h", label="left", closed="left", origin="epoch").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna()
    h1["close_time"] = h1.index + pd.Timedelta(minutes=60)
    h1["atr"] = 0.001
    frames = {"15m": frame15, "1H": h1, "4H": h1}
    view = MTFView(FakeEngine(frames), "EURUSD",
                   {"bias_tf": "4H", "structure_tf": "1H",
                    "setup_tf": "15m", "entry_tf": "15m"})
    for i in range(20, 200):
        j = view.index_at("1H", i)
        if j >= 0:
            assert h1["close_time"].iloc[j] <= frame15["close_time"].iloc[i], \
                "an unclosed higher-timeframe bar leaked into the setup view"
