import pandas as pd
import pytest

from xauusd_bot.config import Config
from xauusd_bot.risk.kill_switch import KillSwitch
from xauusd_bot.risk.position_sizer import size_position
from xauusd_bot.risk.risk_manager import RiskManager


def _cfg(**ov):
    c = Config().with_overrides(**ov) if ov else Config()
    return c


def test_size_derives_from_risk_not_hardcoded():
    c = _cfg(**{"instrument.min_lot": 0.001, "instrument.lot_step": 0.001})
    a = size_position(500, 4600, 4595, c)     # $5 stop
    b = size_position(1000, 4600, 4595, c)    # same stop, double equity
    assert b.lots == pytest.approx(2 * a.lots, rel=0.05)
    assert a.risk_percent_actual <= c.risk.risk_percent + 1e-9


def test_min_lot_rejection_is_explicit():
    # standard-contract broker: 0.01 minimum lot
    c = _cfg(**{"instrument.min_lot": 0.01, "instrument.lot_step": 0.01})
    r = size_position(500, 4600, 4590, c)     # $10 stop -> 2% at min lot
    assert not r.ok and "min lot" in r.reason
    assert r.lots == 0.0


def test_hard_risk_cap_enforced():
    c = _cfg(**{"instrument.min_lot": 0.01, "instrument.lot_step": 0.01,
                "risk.allow_min_lot_override": True,
                "risk.max_risk_percent_hard_cap": 1.0})
    r = size_position(500, 4600, 4590, c)     # min lot risks 2% > 1% cap
    assert not r.ok


def test_daily_loss_lock():
    c = _cfg()
    rm = RiskManager(c, 500.0)
    ts = pd.Timestamp("2026-03-02 10:00", tz="UTC")
    rm.on_bar(ts, "d1", 500.0)
    rm.on_bar(ts, "d1", 492.0)                # -1.6%
    rm.check_locks(ts)
    assert rm.s.daily_locked
    assert not rm.approve(4600, 4595, 4615, 1).approved


def test_weekly_loss_lock_survives_new_day():
    c = _cfg()
    rm = RiskManager(c, 500.0)
    t1 = pd.Timestamp("2026-03-02 10:00", tz="UTC")
    rm.on_bar(t1, "d1", 500.0)
    rm.on_bar(t1, "d1", 478.0)                # -4.4% on the week
    rm.check_locks(t1)
    assert rm.s.weekly_locked
    rm.on_bar(pd.Timestamp("2026-03-03 10:00", tz="UTC"), "d2", 478.0)
    assert rm.s.weekly_locked, "weekly lock must survive the daily rollover"
    assert not rm.approve(4600, 4595, 4615, 1).approved


def test_consecutive_losses_lock_and_daily_reset():
    c = _cfg()
    rm = RiskManager(c, 500.0)
    ts = pd.Timestamp("2026-03-02 10:00", tz="UTC")
    rm.on_bar(ts, "d1", 500.0)
    for _ in range(3):
        rm.on_close(-1.0, 499.0, ts)
    assert not rm.approve(4600, 4595, 4615, 1).approved
    rm.on_bar(pd.Timestamp("2026-03-03 10:00", tz="UTC"), "d2", 499.0)
    assert rm.s.consecutive_losses == 0, "must reset daily or the bot latches off forever"


def test_max_daily_trades():
    c = _cfg(**{"instrument.min_lot": 0.001, "instrument.lot_step": 0.001})
    rm = RiskManager(c, 500.0)
    ts = pd.Timestamp("2026-03-02 10:00", tz="UTC")
    rm.on_bar(ts, "d1", 500.0)
    for _ in range(c.risk.max_daily_trades):
        assert rm.approve(4600, 4595, 4615, 1).approved
        rm.on_open(); rm.s.open_positions = 0
    assert not rm.approve(4600, 4595, 4615, 1).approved


def test_only_one_open_position():
    c = _cfg(**{"instrument.min_lot": 0.001, "instrument.lot_step": 0.001})
    rm = RiskManager(c, 500.0)
    rm.on_bar(pd.Timestamp("2026-03-02 10:00", tz="UTC"), "d1", 500.0)
    assert rm.approve(4600, 4595, 4615, 1).approved
    rm.on_open()
    assert not rm.approve(4600, 4595, 4615, 1).approved


def test_rejects_bad_stops_and_poor_rr():
    c = _cfg(**{"instrument.min_lot": 0.001, "instrument.lot_step": 0.001})
    rm = RiskManager(c, 500.0)
    rm.on_bar(pd.Timestamp("2026-03-02 10:00", tz="UTC"), "d1", 500.0)
    assert not rm.approve(4600, 4605, 4615, 1).approved      # stop above entry on a long
    assert not rm.approve(4600, 4595, 4601, 1).approved      # RR 0.2
    assert not rm.approve(4600, float("nan"), 4615, 1).approved


def test_no_martingale_size_never_grows_after_loss():
    """Size is a pure function of (equity, risk%, stop distance). After a loss
    equity is lower, so the next size can only be smaller - never larger."""
    c = _cfg(**{"instrument.min_lot": 0.001, "instrument.lot_step": 0.001})
    before = size_position(500, 4600, 4595, c).lots
    after_loss = size_position(497.5, 4600, 4595, c).lots
    assert after_loss <= before


def test_kill_switch_requires_explicit_reset():
    k = KillSwitch()
    k.trip("unknown order state")
    assert not k.allow_new_trades()
    with pytest.raises(PermissionError):
        k.reset()
    k.reset(operator_ack=True)
    assert k.allow_new_trades()
