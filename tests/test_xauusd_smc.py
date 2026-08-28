"""
Test suite for the XAUUSD SMC bot.

Everything here runs offline against synthetic price data — no broker, no
network, no credentials. Run with:  python3 -m unittest discover -s tests -v
"""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xauusd_smc import smc                                    # noqa: E402
from xauusd_smc.config import Config, PIP_USD, USD_PER_PIP_PER_LOT  # noqa: E402
from xauusd_smc.news import NewsFilter                        # noqa: E402
from xauusd_smc.risk import RiskManager, money_risk, position_size  # noqa: E402
from xauusd_smc.tradelocker import parse_position             # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic bar builders
# ---------------------------------------------------------------------------
def bar(o, h, l, c, t=0):
    return {"t": float(t), "o": float(o), "h": float(h), "l": float(l), "c": float(c)}


def _wick(i, seed=0):
    """Deterministic, non-repeating wick so fractals have unique extremes."""
    return 0.4 + 0.9 * (((i * 7919 + seed * 104729) % 17) / 17.0)


def leg(start, end, n, t0=0, seed=0):
    out, step = [], (end - start) / max(n, 1)
    for i in range(n):
        o = start + step * i
        c = o + step
        out.append(bar(o, max(o, c) + _wick(t0 + i, seed),
                       min(o, c) - _wick(t0 + i, seed + 3), c, t0 + i))
    return out


def zig(start, points, n_each, seed=0):
    bars, cur, t = [], start, 0
    for k, p in enumerate(points):
        bars += leg(cur, p, n_each, t, seed + k)
        cur, t = p, t + n_each
    return bars


def mirror(bars, pivot=6700.0):
    """Reflect a series about `pivot` — turns a long setup into its short twin."""
    return [bar(pivot - b["o"], pivot - b["l"], pivot - b["h"], pivot - b["c"], b["t"])
            for b in bars]


def aplus_long():
    """H4/H1/M15/M5 series containing one textbook A+ long."""
    h4 = zig(3200, [3260, 3235, 3300, 3275, 3340, 3320, 3380], 6)
    h1 = zig(3380, [3330, 3350, 3315, 3345, 3325, 3395], 9)
    m15 = zig(3345, [3318.0, 3336, 3318.2, 3334, 3326], 11) + [
        bar(3326, 3327, 3310.0, 3322, 55),    # liquidity sweep of the equal lows
        bar(3319, 3320.0, 3314, 3315, 56),    # order block (last down candle)
        bar(3315, 3350, 3314.5, 3348, 57),    # displacement -> CHoCH
        bar(3348, 3349, 3336, 3338, 58),
        bar(3338, 3339, 3327, 3328, 59),
        bar(3328, 3329, 3321, 3322, 60),      # back into the zone
    ]
    m5 = zig(3348, [3335, 3341, 3322], 14) + [
        bar(3323, 3324, 3319.0, 3320, 48),    # tags the order block
        bar(3319.5, 3327, 3319.0, 3324, 49),  # bullish engulfing confirmation
    ]
    return h4, h1, m15, m5


# ---------------------------------------------------------------------------
class TestPrimitives(unittest.TestCase):
    def test_normalize_accepts_dicts_and_arrays(self):
        rows = [{"t": 1, "o": 1, "h": 2, "l": 0.5, "c": 1.5},
                [2, 1.5, 2.5, 1.0, 2.0, 99], "garbage", {"o": 1}]
        out = smc.normalize_bars(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["h"], 2.5)

    def test_atr_is_positive_and_scales(self):
        bars = [bar(100 + i, 103 + i, 98 + i, 101 + i, i) for i in range(20)]
        self.assertGreater(smc.atr(bars, 14), 0)

    def test_structure_events_bos_and_choch(self):
        up = zig(3200, [3260, 3235, 3300, 3275, 3340], 6)
        self.assertEqual(smc.bias(up, 2), "bullish")
        flip = up + leg(3340, 3180, 14, t0=len(up))
        self.assertEqual(smc.bias(flip, 2), "bearish")
        kinds = [e["kind"] for e in smc.structure_events(flip, 2) if e["dir"] == "bear"]
        self.assertIn("CHoCH", kinds)

    def test_no_lookahead_in_swings(self):
        """A swing is only visible `strength` bars after it prints."""
        bars = zig(3300, [3340, 3310, 3360], 8)
        early = smc.structure_events(bars[:-3], 2)
        late = smc.structure_events(bars, 2)
        self.assertEqual([e["idx"] for e in early],
                         [e["idx"] for e in late if e["idx"] < len(bars) - 3])

    def test_sweep_requires_close_back_inside(self):
        base = zig(3345, [3318.0, 3336, 3318.2, 3334, 3326], 11)
        swept = base + [bar(3326, 3327, 3310.0, 3322, 55)]
        self.assertIsNotNone(smc.find_sweep(swept, "bullish", 20, 3))
        # A clean break-and-close-below is NOT a sweep.
        broken = base + [bar(3326, 3327, 3310.0, 3312, 55)]
        self.assertIsNone(smc.find_sweep(broken, "bullish", 20, 3))

    def test_fib_and_retrace(self):
        self.assertAlmostEqual(smc.fib_position(3320, 3310, 3350), 0.25)
        self.assertAlmostEqual(smc.retrace_depth(3320, 3310, 3350, "bullish"), 0.75)
        self.assertAlmostEqual(smc.retrace_depth(3340, 3310, 3350, "bearish"), 0.75)


# ---------------------------------------------------------------------------
class TestSetupDetection(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.h4, self.h1, self.m15, self.m5 = aplus_long()

    def test_detects_aplus_long_with_correct_geometry(self):
        s = smc.analyze("XAUUSD", self.h4, self.h1, self.m15, self.m5, self.cfg)
        self.assertIsNotNone(s)
        self.assertEqual(s.direction, "bullish")
        self.assertEqual(s.grade, "A+")
        self.assertEqual(s.entry, 3320.0)          # top of the order block
        self.assertLess(s.sl, 3310.0)              # below the sweep low + buffer
        self.assertGreaterEqual(s.rr_tp1, 2.0)     # doc: R:R >= 1:2 to TP1
        self.assertLess(s.fib_pos, 0.5)            # bought in discount
        self.assertGreaterEqual(s.retrace, 0.705)  # A+ needs the deep retrace
        self.assertTrue(any("sweep" in r for r in s.reasons))
        self.assertTrue(any("M5" in r for r in s.reasons))

    def test_detects_mirrored_short(self):
        cfg = Config()
        s = smc.analyze("XAUUSD", mirror(self.h4), mirror(self.h1),
                        mirror(self.m15), mirror(self.m5), cfg)
        self.assertIsNotNone(s)
        self.assertEqual(s.direction, "bearish")
        self.assertIn(s.grade, ("A", "A+"))
        self.assertGreater(s.sl, s.entry)          # stop above a short entry
        self.assertLess(s.tp1, s.entry)
        self.assertGreater(s.fib_pos, 0.5)         # sold in premium

    def test_no_setup_before_the_m5_confirmation(self):
        """Without the confirmation candle there is no trade."""
        s = smc.analyze("XAUUSD", self.h4, self.h1, self.m15, self.m5[:-1], self.cfg)
        self.assertIsNone(s)

    def test_counter_h4_needs_an_h1_choch_and_is_downgraded(self):
        """Doc 2.1: trade with H4 unless a H1 CHoCH occurs — and that is not A."""
        bear_h4 = zig(3400, [3340, 3360, 3300, 3330, 3250], 6)
        s = smc.analyze("XAUUSD", bear_h4, self.h1, self.m15, self.m5, self.cfg)
        self.assertIsNotNone(s)                      # allowed: H1 CHoCH is bullish
        self.assertEqual(s.grade, "B")               # but never A/A+ without H4
        self.assertFalse(self.cfg.grade_allowed(s.grade))   # so MIN_GRADE=A skips it

    def test_no_setup_when_both_htfs_oppose(self):
        bear_h4 = zig(3400, [3340, 3360, 3300, 3330, 3250], 6)
        bear_h1 = zig(3400, [3350, 3370, 3310, 3340, 3260], 9)
        self.assertIsNone(smc.analyze("XAUUSD", bear_h4, bear_h1,
                                      self.m15, self.m5, self.cfg))

    def test_premium_entry_is_rejected_for_longs(self):
        """Move the order block above the 50% level -> not a discount buy."""
        cfg = Config()
        m15 = list(self.m15)
        m15[56] = bar(3345, 3346.0, 3340, 3341, 56)   # OB now in premium
        s = smc.analyze("XAUUSD", self.h4, self.h1, m15, self.m5, cfg)
        if s is not None:
            self.assertNotEqual(s.direction, "bullish")

    def test_fingerprint_is_stable(self):
        s1 = smc.analyze("XAUUSD", self.h4, self.h1, self.m15, self.m5, self.cfg)
        s2 = smc.analyze("XAUUSD", self.h4, self.h1, self.m15, self.m5, self.cfg)
        self.assertEqual(smc.fingerprint(s1), smc.fingerprint(s2))


# ---------------------------------------------------------------------------
class TestRepricing(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.h4, self.h1, self.m15, self.m5 = aplus_long()
        self.setup = smc.analyze("XAUUSD", self.h4, self.h1, self.m15, self.m5, self.cfg)

    def test_market_entry_keeps_rr_honest(self):
        p = smc.reprice_for_market_entry(self.setup, 3323.7, 3324.0, self.cfg)
        self.assertIsNotNone(p)
        self.assertEqual(p.entry, 3324.0)                  # paid the ask
        self.assertAlmostEqual(p.rr_tp1, 2.0, places=2)    # 2R from the real fill
        self.assertAlmostEqual(abs(p.entry - p.sl), p.sl_pips, places=2)

    def test_refuses_to_chase(self):
        p = smc.reprice_for_market_entry(self.setup, 3339.0, 3339.3, self.cfg)
        self.assertIsNone(p)
        self.assertIn("chas", self.setup.rejected)


# ---------------------------------------------------------------------------
class TestSizing(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_matches_the_strategy_document_example(self):
        """Doc: $1,500 risk, 30-pip stop -> 5.0 lots."""
        lots = position_size(1500.0, 30.0 * PIP_USD, self.cfg)
        self.assertAlmostEqual(lots, 5.0, places=2)
        self.assertAlmostEqual(money_risk(lots, 30.0 * PIP_USD), 1500.0, places=2)

    def test_never_exceeds_the_risk_budget(self):
        for stop in (3.5, 7.3, 12.5, 21.0, 47.9):
            lots = position_size(1500.0, stop, self.cfg)
            self.assertLessEqual(money_risk(lots, stop),
                                 1500.0 * self.cfg.risk_overrun_tolerance)

    def test_hard_lot_cap(self):
        lots = position_size(1500.0, 0.5, self.cfg)   # absurdly tight stop
        self.assertLessEqual(lots, self.cfg.max_lots)

    def test_grade_risk_ladder(self):
        self.assertAlmostEqual(self.cfg.risk_pct("A+"), 0.030)
        self.assertAlmostEqual(self.cfg.risk_pct("A"), 0.025)
        self.assertAlmostEqual(self.cfg.risk_pct("B"), 0.015)
        self.assertEqual(self.cfg.risk_pct("C"), 0.0)

    def test_min_grade_gate(self):
        cfg = Config(min_grade="A")
        self.assertTrue(cfg.grade_allowed("A+"))
        self.assertTrue(cfg.grade_allowed("A"))
        self.assertFalse(cfg.grade_allowed("B"))
        self.assertFalse(cfg.grade_allowed("C"))
        self.assertTrue(Config(min_grade="B").grade_allowed("B"))


# ---------------------------------------------------------------------------
class TestRiskLimits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(
            state_file=os.path.join(self.tmp.name, "state.json"),
            journal_file=os.path.join(self.tmp.name, "journal.jsonl"))
        self.rm = RiskManager(self.cfg, 50_000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_slate_allows_trading(self):
        self.assertIsNone(self.rm.blocked_reason(50_000.0, 0))

    def test_two_consecutive_losses_stop_the_day(self):
        self.rm.state.open_trades = {"1": {"symbol": "XAUUSD"}, "2": {"symbol": "XAUUSD"}}
        self.rm.register_close("1", -1500.0, "sl")
        self.assertIsNone(self.rm.blocked_reason(48_500.0, 0))
        self.rm.register_close("2", -1500.0, "sl")
        reason = self.rm.blocked_reason(47_000.0, 0)
        self.assertIsNotNone(reason)
        self.assertIn("consecutive losses", reason)

    def test_a_win_resets_the_loss_streak(self):
        self.rm.state.open_trades = {"1": {}, "2": {}}
        self.rm.register_close("1", -1500.0, "sl")
        self.rm.register_close("2", +3000.0, "tp")
        self.assertEqual(self.rm.state.consecutive_losses, 0)

    def test_daily_drawdown_limit(self):
        reason = self.rm.blocked_reason(50_000.0 * 0.93, 0)   # -7% > 6% limit
        self.assertIn("daily stop", reason)

    def test_weekly_drawdown_limit(self):
        self.rm.cfg.daily_loss_pct = 0.99                      # isolate the weekly rule
        reason = self.rm.blocked_reason(50_000.0 * 0.88, 0)    # -12% > 10% limit
        self.assertIn("weekly stop", reason)

    def test_max_open_positions_and_daily_trade_cap(self):
        self.assertIn("open", self.rm.blocked_reason(50_000.0, 1))
        self.rm.state.trades_today = self.cfg.max_trades_per_day
        self.assertIn("max trades", self.rm.blocked_reason(50_000.0, 0))

    def test_state_survives_a_restart(self):
        self.rm.state.trades_today = 2
        self.rm.state.consecutive_losses = 1
        self.rm.save()
        again = RiskManager(self.cfg, 50_000.0)
        self.assertEqual(again.state.trades_today, 2)
        self.assertEqual(again.state.consecutive_losses, 1)

    def test_new_day_resets_counters(self):
        self.rm.state.trades_today = 3
        self.rm.state.consecutive_losses = 2
        self.rm.state.day = "1999-01-01"
        msgs = self.rm.roll_periods(50_000.0)
        self.assertTrue(msgs)
        self.assertEqual(self.rm.state.trades_today, 0)
        self.assertEqual(self.rm.state.consecutive_losses, 0)


# ---------------------------------------------------------------------------
class TestNewsFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(news_file=os.path.join(self.tmp.name, "news.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_calendar_event_blocks_the_window(self):
        with open(self.cfg.news_file, "w") as f:
            f.write('[{"time": "2026-09-04T12:30:00Z", "title": "NFP", "impact": "high"}]')
        n = NewsFilter(self.cfg)
        at = dt.datetime(2026, 9, 4, 12, 40, tzinfo=dt.timezone.utc)
        self.assertIn("NFP", n.blackout(at))
        clear = dt.datetime(2026, 9, 4, 13, 30, tzinfo=dt.timezone.utc)
        self.assertIsNone(n.blackout(clear))

    def test_fallback_blocks_classic_release_slots(self):
        n = NewsFilter(self.cfg)
        blocked = n.blackout(dt.datetime(2026, 9, 4, 12, 35, tzinfo=dt.timezone.utc))
        self.assertIsNotNone(blocked)
        self.assertIsNone(n.blackout(dt.datetime(2026, 9, 4, 9, 5, tzinfo=dt.timezone.utc)))

    def test_fallback_can_be_disabled(self):
        cfg = Config(news_file=os.path.join(self.tmp.name, "none.json"),
                     news_fallback_blackout=False)
        n = NewsFilter(cfg)
        self.assertIsNone(n.blackout(dt.datetime(2026, 9, 4, 12, 35, tzinfo=dt.timezone.utc)))


# ---------------------------------------------------------------------------
class TestBrokerHelpers(unittest.TestCase):
    def test_position_row_parsing(self):
        row = [1234567, 314, 9912, "buy", 0.5, 3350.5, 0, 0, 1_700_000_000_000, -12.5]
        p = parse_position(row)
        self.assertEqual(p["id"], "1234567")
        self.assertEqual(p["side"], "buy")
        self.assertAlmostEqual(p["qty"], 0.5)
        self.assertAlmostEqual(p["entry"], 3350.5)
        self.assertAlmostEqual(p["pnl"], -12.5)
        self.assertIsNone(parse_position([]))
        self.assertIsNone(parse_position(None))

    def test_pnl_to_price_conversion_matches_sizing(self):
        """The breakeven logic infers price from P/L — check the maths round-trips."""
        lots, move = 2.0, 7.5
        pnl = lots * (move / PIP_USD) * USD_PER_PIP_PER_LOT
        inferred = pnl / (lots * USD_PER_PIP_PER_LOT) * PIP_USD
        self.assertAlmostEqual(inferred, move)


# ---------------------------------------------------------------------------
class TestSessionGate(unittest.TestCase):
    def setUp(self):
        from xauusd_smc.bot import Bot
        self.bot = Bot(Config())

    def test_london_and_ny_open_weekdays_only(self):
        self.assertTrue(self.bot.in_session(dt.datetime(2026, 9, 2, 9, 0, tzinfo=dt.timezone.utc)))
        self.assertTrue(self.bot.in_session(dt.datetime(2026, 9, 2, 14, 0, tzinfo=dt.timezone.utc)))
        self.assertFalse(self.bot.in_session(dt.datetime(2026, 9, 2, 3, 0, tzinfo=dt.timezone.utc)))
        self.assertFalse(self.bot.in_session(dt.datetime(2026, 9, 2, 23, 0, tzinfo=dt.timezone.utc)))
        self.assertFalse(self.bot.in_session(dt.datetime(2026, 9, 5, 9, 0, tzinfo=dt.timezone.utc)))


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# End-to-end cycle test with a fake broker / fake Telegram
# ---------------------------------------------------------------------------
class FakeBroker:
    """Stands in for TradeLocker — records what the bot would send."""

    def __init__(self, series, quote):
        self.series = series
        self._quote = quote
        self.account_id = "999"
        self.orders = []
        self.closed = []
        self.modified = []
        self._positions = []
        self._next_id = 5001

    def login(self):
        pass

    def equity(self):
        return 50_000.0

    def instrument(self, symbol):
        return {"name": symbol, "tradableInstrumentId": 314,
                "_trade_route": 9912, "_info_route": 452}

    def bars(self, symbol, tf, days):
        # The bot drops the final (forming) bar, so hand it one extra.
        s = self.series[tf]
        return s + [dict(s[-1], t=s[-1]["t"] + 1)]

    def quote(self, symbol):
        return self._quote

    def open_position_ids(self):
        return {p["id"] for p in self._positions}

    def place_market_order(self, symbol, side, qty, stop_loss, take_profit):
        self.orders.append({"symbol": symbol, "side": side, "qty": qty,
                            "sl": stop_loss, "tp": take_profit})
        oid = self._next_id
        self._next_id += 1
        self._positions.append({"id": str(oid), "instrument_id": 314, "side": side,
                                "qty": qty, "entry": self._quote["ask"], "pnl": 0.0})
        return {"ok": True, "order_id": oid, "raw": {"s": "ok"}}

    def new_position_for(self, symbol, known, **kw):
        for p in self._positions:
            if p["id"] not in known:
                return p
        return None

    def positions(self):
        # Emit rows in the real TradeLocker column order so the production
        # parser is exercised, not bypassed.
        return [[p["id"], 314, 9912, p["side"], p["qty"], p["entry"],
                 0, 0, 1_700_000_000_000, p["pnl"]] for p in self._positions]

    def close_position(self, pid, qty=None):
        self.closed.append((pid, qty))
        for p in self._positions:
            if p["id"] == str(pid) and qty:
                p["qty"] = round(p["qty"] - qty, 2)
        return True

    def modify_position(self, pid, stop_loss=None, take_profit=None):
        self.modified.append((pid, stop_loss, take_profit))
        return True


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send(self, text, silent=False):
        self.messages.append(text)
        return True

    def photo(self, path, caption=""):
        self.messages.append(caption)
        return True


class TestBotCycle(unittest.TestCase):
    def setUp(self):
        from xauusd_smc.bot import Bot
        self.tmp = tempfile.TemporaryDirectory()
        h4, h1, m15, m5 = aplus_long()
        self.cfg = Config(
            session_only=False, news_fallback_blackout=False,
            state_file=os.path.join(self.tmp.name, "state.json"),
            journal_file=os.path.join(self.tmp.name, "journal.jsonl"),
            chart_dir=os.path.join(self.tmp.name, "charts"))
        self.bot = Bot(self.cfg)
        self.broker = FakeBroker({"H4": h4, "H1": h1, "M15": m15, "M5": m5},
                                 {"bid": 3323.7, "ask": 3324.0, "spread": 0.30,
                                  "mid": 3323.85})
        self.bot.broker = self.broker
        self.tg = FakeTelegram()
        self.bot.tg = self.tg

    def tearDown(self):
        self.tmp.cleanup()

    def test_cycle_places_the_order_and_alerts_telegram(self):
        setup = self.bot.cycle()
        self.assertIsNotNone(setup)
        self.assertEqual(len(self.broker.orders), 1)
        order = self.broker.orders[0]
        self.assertEqual(order["side"], "buy")
        self.assertEqual(order["symbol"], "XAUUSD")
        self.assertLess(order["sl"], setup.entry)        # stop below a long entry
        self.assertGreater(order["tp"], setup.entry)
        self.assertGreater(order["qty"], 0)
        # risk actually sent to the broker stays inside the 3% budget
        risk = money_risk(order["qty"], abs(setup.entry - order["sl"]))
        self.assertLessEqual(risk, 50_000 * 0.03 * self.cfg.risk_overrun_tolerance)
        # Telegram alert fired straight after the fill
        self.assertTrue(any("TRADE PLACED" in m for m in self.tg.messages))
        self.assertTrue(any("XAUUSD BUY" in m for m in self.tg.messages))
        self.assertEqual(len(self.bot.risk.state.open_trades), 1)

    def test_second_cycle_does_not_duplicate_the_same_setup(self):
        self.bot.cycle()
        self.bot.cycle()
        self.assertEqual(len(self.broker.orders), 1)

    def test_spread_filter_blocks_the_trade(self):
        self.broker._quote = {"bid": 3323.0, "ask": 3324.0, "spread": 1.0, "mid": 3323.5}
        self.assertIsNone(self.bot.cycle())
        self.assertEqual(self.broker.orders, [])

    def test_risk_halt_blocks_new_trades(self):
        self.bot.cycle()                       # opens one
        self.bot.risk.latch_halt("daily stop — 2 consecutive losses")
        self.broker._positions = []            # pretend it closed
        self.bot.cycle()
        self.assertEqual(len(self.broker.orders), 1)

    def test_tp1_closes_half_and_moves_stop_to_breakeven(self):
        self.bot.cycle()
        rec = list(self.bot.risk.state.open_trades.values())[0]
        pos = self.broker._positions[0]
        # Drive unrealized P/L past TP1 (2R in profit).
        move = rec["tp1"] - rec["entry"]
        pos["pnl"] = pos["qty"] * (move / PIP_USD) * USD_PER_PIP_PER_LOT
        self.bot.manage_positions()
        self.assertEqual(len(self.broker.closed), 1)
        closed_qty = self.broker.closed[0][1]
        self.assertAlmostEqual(closed_qty, round(rec["lots"] * 0.5, 2), places=2)
        self.assertEqual(self.broker.modified[0][1], rec["entry"])   # SL -> entry
        self.assertTrue(any("BREAKEVEN" in m or "RISK REMOVED" in m
                            for m in self.tg.messages))

    def test_closed_position_is_reported_and_counted(self):
        self.bot.cycle()
        pid = list(self.bot.risk.state.open_trades)[0]
        self.bot.risk.state.open_trades[pid]["last_pnl"] = -1480.0
        self.broker._positions = []            # broker says it is gone
        self.bot.manage_positions()
        self.assertEqual(self.bot.risk.state.consecutive_losses, 1)
        self.assertTrue(any("TRADE CLOSED" in m for m in self.tg.messages))
        self.assertEqual(self.bot.risk.state.open_trades, {})

    def test_dry_run_never_sends_an_order(self):
        self.cfg.dry_run = True
        setup = self.bot.cycle()
        self.assertIsNotNone(setup)
        self.assertEqual(self.broker.orders, [])
        self.assertTrue(any("DRY RUN" in m for m in self.tg.messages))

    def test_untracked_broker_position_still_blocks_a_new_trade(self):
        """A position opened by hand must count against MAX_OPEN_POSITIONS."""
        self.broker._positions.append({"id": "9999", "instrument_id": 314,
                                       "side": "sell", "qty": 1.0,
                                       "entry": 3330.0, "pnl": 0.0})
        self.assertIsNone(self.bot.cycle())
        self.assertEqual(self.broker.orders, [])

    def test_dry_run_trade_is_not_reported_as_closed(self):
        self.cfg.dry_run = True
        self.bot.cycle()
        self.bot.manage_positions()
        self.assertFalse(any("TRADE CLOSED" in m for m in self.tg.messages))
        self.assertEqual(self.bot.risk.state.consecutive_losses, 0)
