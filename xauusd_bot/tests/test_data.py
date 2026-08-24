import numpy as np
import pandas as pd

from xauusd_bot.data.data_engine import DataEngine, resample
from xauusd_bot.data.sessions import session_of, trading_day
from xauusd_bot.data.validators import clean_m1, validate_m1


def test_detects_duplicates_and_invalid_ohlc(synthetic_m1):
    df = pd.concat([synthetic_m1, synthetic_m1.iloc[100:110]]).sort_index()
    bad = df.copy()
    bad.iloc[5, bad.columns.get_loc("high")] = bad.iloc[5]["low"] - 1.0
    r = validate_m1(bad)
    assert r.duplicates == 10
    assert r.invalid_ohlc >= 1
    assert any("duplicate" in p for p in r.problems)


def test_clean_drops_but_never_interpolates(synthetic_m1):
    gapped = synthetic_m1.drop(synthetic_m1.index[500:560])
    cleaned, info = clean_m1(gapped)
    assert len(cleaned) == len(gapped), "cleaning must not invent bars"
    deltas = cleaned.index.to_series().diff().dt.total_seconds().div(60)
    assert deltas.max() >= 60, "the gap was silently filled"


def test_missing_candles_are_reported(synthetic_m1):
    gapped = synthetic_m1.drop(synthetic_m1.index[1000:1200])
    r = validate_m1(gapped)
    assert r.missing_minutes_in_session >= 200
    assert len(r.gaps_over_5min) >= 1


def test_stale_bar_gap_is_measured(synthetic_m1):
    gapped = synthetic_m1.drop(synthetic_m1.index[3000:3100])
    F = DataEngine().build(gapped)
    assert F["bar_gap_min"].max() >= 100


def test_resample_close_time_is_after_label(synthetic_m1):
    for tf, mins in (("M3", 3), ("M5", 5), ("M15", 15), ("H1", 60)):
        df = resample(synthetic_m1, tf)
        assert ((df["close_time"] - df.index) == pd.Timedelta(minutes=mins)).all()


def test_session_and_trading_day_boundaries():
    idx = pd.date_range("2026-03-02 20:00", periods=8, freq="1h", tz="UTC")
    s = session_of(idx)
    assert s.iloc[0] == "NEWYORK" and s.iloc[1] == "CLOSED" and s.iloc[3] == "ASIA"
    td = trading_day(idx)
    assert td.iloc[0] != td.iloc[1], "trading day must roll at 21:00 UTC"
