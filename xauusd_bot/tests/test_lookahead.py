"""
Anti-lookahead tests (spec section 30).

Method: truncate the data at time T, recompute everything, and assert that the
values at the surviving timestamps are IDENTICAL to those computed with the
full dataset. Any use of future information changes a past value.
"""
import numpy as np
import pandas as pd
import pytest

from xauusd_bot.config import Config
from xauusd_bot.data.data_engine import DataEngine, resample
from xauusd_bot.strategy import regime_engine, selector, setup_scorer
from xauusd_bot.backtesting.simulator import spread_series

CHECK_COLS = ["M15_ema_f", "M15_atr", "M15_struct_bias", "M15_bos", "H1_adx",
              "M5_atr", "M5_choch", "M3_bos", "M1_disp", "M15_vwap",
              "pdh", "pdl", "asia_high", "asia_low", "day_high", "sess_high"]


def _tail_stable(full: pd.DataFrame, trunc: pd.DataFrame, cols, tol=1e-9):
    """Values at shared timestamps (excluding the last few, which legitimately
    depend on nothing future but may sit mid-bar) must match exactly."""
    common = full.index.intersection(trunc.index)
    assert len(common) > 1000
    common = common[:-1]
    bad = {}
    for c in cols:
        a = full.loc[common, c]
        b = trunc.loc[common, c]
        if a.dtype == object or b.dtype == object:
            differ = (a.astype(str) != b.astype(str))
        else:
            differ = ~np.isclose(a.astype(float), b.astype(float),
                                 rtol=0, atol=tol, equal_nan=True)
        if differ.any():
            first = common[differ.values.argmax()]
            bad[c] = (int(differ.sum()), str(first))
    return bad


def test_features_do_not_repaint(synthetic_m1):
    cut = int(len(synthetic_m1) * 0.7)
    full = DataEngine().build(synthetic_m1)
    trunc = DataEngine().build(synthetic_m1.iloc[:cut])
    bad = _tail_stable(full, trunc, CHECK_COLS)
    assert not bad, f"features changed when future data was removed: {bad}"


def test_features_do_not_repaint_real_data(real_m1):
    cut = int(len(real_m1) * 0.75)
    full = DataEngine().build(real_m1)
    trunc = DataEngine().build(real_m1.iloc[:cut])
    bad = _tail_stable(full, trunc, CHECK_COLS)
    assert not bad, f"features repaint on real data: {bad}"


def test_signals_do_not_repaint(synthetic_m1):
    cfg = Config()
    cut = int(len(synthetic_m1) * 0.7)
    for df in (synthetic_m1, synthetic_m1.iloc[:cut]):
        pass
    Ff = DataEngine().build(synthetic_m1)
    Ft = DataEngine().build(synthetic_m1.iloc[:cut])
    Rf = regime_engine.classify(Ff, cfg.regime)
    Rt = regime_engine.classify(Ft, cfg.regime)
    sf, _ = selector.select(Ff, Rf, cfg)
    stt, _ = selector.select(Ft, Rt, cfg)
    common = Ft.index[:-1]
    assert (sf.loc[common, "dir"].values == stt.loc[common, "dir"].values).all(), \
        "signal direction changed when future bars were removed"
    a = sf.loc[common, "sl"].astype(float).values
    b = stt.loc[common, "sl"].astype(float).values
    assert np.allclose(a, b, equal_nan=True), "stop levels repaint"
    assert (Rf.loc[common, "regime"].values == Rt.loc[common, "regime"].values).all(), \
        "regime labels repaint"


def test_htf_bar_not_visible_before_it_closes(synthetic_m1):
    """An M15 bar labelled 09:00 must not be visible before 09:15."""
    F = DataEngine().build(synthetic_m1)
    m15 = resample(synthetic_m1, "M15")
    bar = m15.iloc[50]
    label, close_time = m15.index[50], bar["close_time"]
    # one minute BEFORE the bar closes, the aligned high must still be the
    # PREVIOUS bar's high
    before = F.loc[F.index < close_time]
    before = before.loc[before.index >= label]
    assert len(before) > 0
    prev_high = m15.iloc[49]["high"]
    assert np.allclose(before["M15_high"].dropna().unique(), prev_high), \
        "an unclosed M15 bar is visible to the strategy"
    at = F.loc[F.index >= close_time].iloc[0]
    assert np.isclose(at["M15_high"], bar["high"]), "closed M15 bar not visible on time"


def test_swings_are_confirmation_stamped(synthetic_m1):
    """A fractal swing needs k bars after it; it must be stamped at bar+k."""
    from xauusd_bot.data.structure import fractal_swings
    k = 2
    sw = fractal_swings(synthetic_m1.iloc[:3000], k)
    hits = sw["swing_high"].dropna()
    assert len(hits) > 5
    h = synthetic_m1["high"].iloc[:3000]
    for ts, price in list(hits.items())[:20]:
        i = h.index.get_loc(ts)
        assert np.isclose(h.iloc[i - k], price), \
            "swing price is not stamped k bars after the swing itself"


def test_no_future_in_previous_day_levels(real_m1):
    """PDH/PDL must equal the PREVIOUS trading day's extremes, never today's."""
    from xauusd_bot.data.sessions import trading_day
    F = DataEngine().build(real_m1)
    td = trading_day(F.index)
    daily_hi = F.groupby(td)["high"].max()
    days = list(daily_hi.index)
    for d0, d1 in zip(days[:-1], days[1:]):
        pdh_vals = F.loc[(td == d1).values, "pdh"].dropna().unique()
        if len(pdh_vals) == 0:
            continue
        assert np.allclose(pdh_vals, daily_hi.loc[d0]), \
            f"pdh on {d1} is not the completed high of {d0}"
