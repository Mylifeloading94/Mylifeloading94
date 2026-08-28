"""
Internal consistency checks — deterministic, offline, no network.

These are the invariants the rest of the system is allowed to assume, and the
ones that protect the claims on the dashboard: no fabricated prices, no
probability without a sample, honest fills, coherent trade geometry.

    python3 xau_bot.py selftest
"""
from __future__ import annotations

import math

from .candles import Bar, Series, atr, make_series, resample, to_pips, tf_seconds
from .config import GRADE_BANDS, GRADE_WEIGHTS, MODES, EngineConfig, StrategyConfig
from .feed import DataFeed, FeedStatus, Provider
from .grading import apply_history_veto, grade
from .invalidation import revalidate
from .setups import Setup, build_context, detect
from .smc import analyze_structure, fair_value_gaps, order_blocks, premium_discount, swings
from .stats import StatsStore, apply_probability, compute_bucket

_FAILS: list[str] = []
_RUN = 0


def check(name: str, cond: bool, detail: str = ""):
    global _RUN
    _RUN += 1
    if not cond:
        _FAILS.append(f"{name}{' — ' + detail if detail else ''}")


def _synth(n: int = 400, start: float = 2000.0, seed: int = 7, tf: str = "M15") -> Series:
    """
    Deterministic pseudo-random walk with alternating trend legs and periodic
    stop-hunt spikes, so the SMC detectors have something real to find. No
    external data, identical on every machine.
    """
    rows, price, s = [], start, seed
    span = tf_seconds(tf)
    for i in range(n):
        s = (1103515245 * s + 12345) % (2 ** 31)
        leg = (i // 80) % 2
        drift = 0.45 if leg == 0 else -0.45
        step = ((s / 2 ** 31) - 0.5) * 5.0 + drift
        o = price
        c = price + step
        hi = max(o, c) + abs(step) * 0.5 + 0.3
        lo = min(o, c) - abs(step) * 0.5 - 0.3
        if i % 37 == 0:                      # periodic liquidity sweep wick
            if leg == 0:
                lo -= 4.0
            else:
                hi += 4.0
        if i % 37 == 1:                      # followed by displacement
            c = o + (6.0 if leg == 0 else -6.0)
            hi, lo = max(hi, c + 0.4), min(lo, c - 0.4)
        rows.append((1_700_000_000 + i * span, o, hi, lo, c, 100.0))
        price = c
    return make_series(tf, rows, "synthetic", "TEST")


def _synth_stack(n: int = 7000) -> dict:
    """An M5 base plus every timeframe derived from it — one coherent market."""
    base = _synth(n, tf="M5")
    return {"M1": base, "M5": base, "M15": resample(base, "M15"),
            "H1": resample(base, "H1"), "H4": resample(base, "H4")}


# --------------------------------------------------------------------------
def t_candles():
    s = _synth(240)
    check("candles/ordering", all(s.bars[i].ts < s.bars[i + 1].ts for i in range(len(s) - 1)))
    check("candles/ohlc coherent",
          all(b.h >= max(b.o, b.c) and b.l <= min(b.o, b.c) for b in s.bars))

    h1 = resample(s, "H1")
    check("resample/count", len(h1) == math.ceil(len(s) / 4) or len(h1) == len(s) // 4 + 1,
          f"{len(h1)} from {len(s)} M15")
    grp = s.bars[:4]
    check("resample/ohlc", h1[0].o == grp[0].o and h1[0].c == grp[-1].c
          and h1[0].h == max(b.h for b in grp) and h1[0].l == min(b.l for b in grp))

    # anti-lookahead: before(T) may only contain bars that CLOSED by T
    cut = s.bars[100].ts + tf_seconds("M15")
    before = s.before(cut)
    check("candles/before is causal", all(b.ts + tf_seconds("M15") <= cut for b in before.bars))
    check("candles/before includes the just-closed bar", before.bars[-1].ts == s.bars[100].ts)

    check("atr/positive", atr(s.bars[-60:], 14) > 0)
    check("atr/insufficient data returns zero", atr(s.bars[:5], 14) == 0.0)
    check("pips/gold conversion", abs(to_pips(1.0) - 10.0) < 1e-9, "1.00 USD must be 10 pips")


def t_smc():
    # a clean zigzag: swing detection must find the pivots
    rows, ts = [], 1_700_000_000
    for i in range(60):
        phase = i % 10                       # 0..4 up, 5..9 down — unique extremes
        base = 100 + (phase if phase <= 5 else 10 - phase)
        rows.append((ts + i * 900, base, base + 1, base - 1, base + 0.5))
    z = make_series("M15", rows, "synthetic", "TEST")
    sw = swings(z.bars, 2)
    check("smc/swings found", len(sw) > 0)
    check("smc/swing kinds", {x.kind for x in sw} <= {"high", "low"})

    # a constructed bullish FVG: bar[i].low strictly above bar[i-2].high
    rows = [(1_700_000_000 + i * 900, 100, 101, 99, 100.5) for i in range(30)]
    rows[27] = (rows[27][0], 100.6, 100.8, 99.8, 99.9)      # bearish -> the order block
    rows[28] = (rows[28][0], 100.5, 112, 100.4, 111.5)      # displacement
    rows[29] = (rows[29][0], 111.5, 113, 105, 112.0)        # low 105 > high 101 -> gap
    g = make_series("M15", rows, "synthetic", "TEST")
    fv = fair_value_gaps(g.bars, min_size_atr=0.0)
    bull = [x for x in fv if x.direction == "bullish"]
    check("smc/fvg detected", len(bull) >= 1, f"got {len(fv)} gaps")
    if bull:
        f = bull[-1]
        check("smc/fvg bounds", f.bottom < f.top and f.size > 0)
        check("smc/fvg contains its own midpoint", f.contains(f.mid))

    obs = order_blocks(g.bars, disp_mult=0.5)
    check("smc/order block found", len(obs) >= 1)

    s = _synth(600)
    st = analyze_structure(s.bars, 2)
    check("smc/structure trend value", st.trend in ("bullish", "bearish", "ranging"))
    check("smc/structure events ordered",
          all(st.events[i].idx <= st.events[i + 1].idx for i in range(len(st.events) - 1)))
    check("smc/first event is a CHoCH",
          not st.events or st.events[0].kind == "CHOCH",
          "the first break from 'ranging' cannot be a continuation")
    check("smc/range sane", st.range_low < st.range_high)

    pd = premium_discount(st, (st.range_high + st.range_low) / 2)
    check("smc/equilibrium is equilibrium", pd.zone == "EQUILIBRIUM", f"got {pd.zone}")
    check("smc/premium above eq", premium_discount(st, st.range_high).zone == "PREMIUM")
    check("smc/discount below eq", premium_discount(st, st.range_low).zone == "DISCOUNT")
    lo, hi = pd.ote("bullish")
    check("smc/ote band inside range", st.range_low <= lo < hi <= st.range_high)


def t_grading():
    check("grading/weights total 100", abs(sum(GRADE_WEIGHTS.values()) - 100) < 1e-9,
          str(sum(GRADE_WEIGHTS.values())))
    check("grading/history is not a scored component", "historical" not in GRADE_WEIGHTS,
          "history must be a veto, never a score input (circularity)")
    bands = [lo for _, lo in GRADE_BANDS]
    check("grading/bands descend", bands == sorted(bands, reverse=True))


def t_setup_geometry():
    """Every setup the detector emits must be internally coherent."""
    cfg = StrategyConfig()
    stack = _synth_stack()
    checked = 0
    for mode_name in ("SCALP", "INTRADAY", "SWING"):
        mode = MODES[mode_name]
        ctx = build_context(mode, {tf: stack[tf] for tf in mode.timeframes}, cfg)
        check(f"setup/{mode_name} context builds", ctx is not None)
        if ctx is None:
            continue
        for st in detect(ctx):
            checked += 1
            sign = 1 if st.direction == "BUY" else -1
            check("setup/stop on the losing side",
                  (st.sl < st.entry) if st.direction == "BUY" else (st.sl > st.entry),
                  f"{st.direction} entry {st.entry} sl {st.sl}")
            check("setup/targets ordered away from entry",
                  sign * (st.tp1 - st.entry) > 0 and sign * (st.tp2 - st.tp1) >= 0)
            if st.tp3:
                check("setup/tp3 beyond tp2", sign * (st.tp3 - st.tp2) >= 0)
                check("setup/tp3 within reach", st.rr_tp3 <= mode.tp_r[2] * 2.0 + 0.01,
                      f"tp3 at 1:{st.rr_tp3} is not a level this trade can be judged on")
            check("setup/headline rr within reach", st.rr <= mode.tp_r[1] * 2.0 + 0.01,
                  f"rr 1:{st.rr} exceeds the reach cap")
            risk = abs(st.entry - st.sl)
            check("setup/rr matches geometry",
                  abs(st.rr - abs(st.tp2 - st.entry) / risk) < 0.02)
            check("setup/sl pips match price distance",
                  abs(st.sl_pips - to_pips(risk)) < 0.2)
            check("setup/stop distance inside the mode band",
                  mode.min_sl_pips <= st.sl_pips <= mode.max_sl_pips)
            check("setup/entry zone contains a limit entry",
                  st.entry_type != "LIMIT" or st.entry_low - 1e-6 <= st.entry <= st.entry_high + 1e-6)
    check("setup/detector produced something to check on synthetic data", checked > 0,
          "the geometry assertions never ran")


def t_probability_honesty():
    empty = StatsStore()
    s = Setup(pattern="LIQUIDITY_SWEEP_REVERSAL", mode="INTRADAY", grade="A+", direction="BUY")
    apply_probability(s, empty, min_sample=30)
    check("stats/no sample means no probability", s.probability is None and s.sample_size == 0)
    check("stats/absence is explained", bool(s.prob_note))

    trades = [{"pattern": "P", "mode": "INTRADAY", "grade": "A", "direction": "BUY",
               "r_multiple": r, "target_rr": 2.0, "session": "LONDON", "exec_tf": "M15"}
              for r in ([2.0] * 6 + [-1.0] * 4)]
    store = StatsStore.from_trades(trades)
    s2 = Setup(pattern="P", mode="INTRADAY", grade="A", direction="BUY")
    apply_probability(s2, store, min_sample=10)
    check("stats/win rate is measured", s2.probability == 60.0, str(s2.probability))
    check("stats/sample size reported", s2.sample_size == 10)
    check("stats/profit factor", abs((s2.profit_factor or 0) - 3.0) < 1e-6, str(s2.profit_factor))

    s3 = Setup(pattern="P", mode="INTRADAY", grade="A", direction="BUY")
    apply_probability(s3, store, min_sample=50)
    check("stats/insufficient sample publishes nothing", s3.probability is None)

    b = compute_bucket("x", trades)
    check("stats/expectancy", abs(b.expectancy_r - 0.8) < 1e-9, str(b.expectancy_r))
    check("stats/max drawdown is non-positive", b.max_drawdown_r <= 0)

    losing = [{"pattern": "P", "mode": "INTRADAY", "grade": "A+", "direction": "BUY",
               "r_multiple": r, "target_rr": 2.0} for r in ([1.0] * 3 + [-1.0] * 9)]
    s4 = Setup(pattern="P", mode="INTRADAY", grade="A+", direction="BUY", status="VALID")
    apply_probability(s4, StatsStore.from_trades(losing), min_sample=10)
    apply_history_veto(s4, min_sample=10, min_pf=1.0)
    check("stats/measured losers are vetoed",
          s4.status == "INVALID" and s4.history_flag == "VALIDATED_NEGATIVE", s4.invalid_reason)


def t_feed_honesty():
    class Dead(Provider):
        name, symbol, kind, priority = "dead", "TEST", "test", 1

        def fetch(self, tf, bars):
            raise RuntimeError("upstream down")

    class Stale(Provider):
        name, symbol, kind, priority = "stale", "TEST", "test", 2

        def fetch(self, tf, bars):
            old = 1_600_000_000
            return make_series(tf, [(old + i * tf_seconds(tf), 100, 101, 99, 100)
                                    for i in range(120)], self.name, self.symbol)

    feed = DataFeed(providers=[Dead(), Stale()])
    snap = feed.snapshot({"M15": 100})
    check("feed/stale data is never presented as live", snap.status.state != "LIVE",
          snap.status.state)
    check("feed/banner says unavailable", "UNAVAILABLE" in snap.status.banner.upper()
          or "CLOSED" in snap.status.banner.upper(), snap.status.banner)
    check("feed/provider errors are surfaced", any("dead" in e for e in snap.status.errors))

    dead_only = DataFeed(providers=[Dead()])
    snap2 = dead_only.snapshot({"M15": 100})
    check("feed/total failure yields no price", snap2.price is None)
    check("feed/total failure state", snap2.status.state == "UNAVAILABLE")

    check("feed/proxy quality is labelled",
          FeedStatus(state="LIVE", is_true_xauusd=False).quality == "LIVE_PROXY_REALTIME")
    check("feed/delayed proxy is labelled",
          FeedStatus(state="LIVE", is_true_xauusd=False, delayed_by_sec=900).quality
          == "LIVE_PROXY_DELAYED")
    check("feed/true spot is labelled",
          FeedStatus(state="LIVE", is_true_xauusd=True).quality == "LIVE_XAUUSD_SPOT")


def t_invalidation():
    cfg = StrategyConfig()
    stack = _synth_stack()
    ctx = build_context(MODES["INTRADAY"],
                        {tf: stack[tf] for tf in MODES["INTRADAY"].timeframes}, cfg)
    check("invalidation/context built", ctx is not None)
    if ctx is None:
        return
    price = ctx.price
    st = Setup(id="t", mode="INTRADAY", pattern="LIQUIDITY_SWEEP_REVERSAL", direction="BUY",
               entry=price, entry_low=price - 1, entry_high=price + 1, entry_type="MARKET",
               entry_state="ARMED", sl=price - 10, tp1=price + 10, tp2=price + 25,
               signal_ts=ctx.ts, grade="A")
    st.anchors = {"poi": {"kind": "FVG", "top": price + 1, "bottom": price - 1},
                  "sweep": {}, "mss": {"kind": "MSS"}}

    v = revalidate(st, ctx, cfg, price, high_since=price, low_since=price - 50)
    check("invalidation/stop hit is caught", not v.valid and "STOP LOSS" in v.reason.upper(),
          v.reason)

    st2 = Setup(**{**st.__dict__})
    st2.sl = price - 10
    v2 = revalidate(st2, ctx, cfg, price, high_since=price, low_since=price)
    check("invalidation/returns a reason whenever it invalidates",
          v2.valid or bool(v2.reason))

    st3 = Setup(**{**st.__dict__})
    st3.tp2 = price + 0.5          # R:R collapses to well under the mode minimum
    v3 = revalidate(st3, ctx, cfg, price, high_since=price, low_since=price)
    check("invalidation/decayed R:R is caught",
          not v3.valid and "risk/reward" in v3.reason, v3.reason)


def t_backtest_fills():
    from .backtest import _simulate
    mode = MODES["INTRADAY"]
    ts = 1_700_000_000

    def series(rows):
        return make_series("M5", [(ts + i * 300, *r) for i, r in enumerate(rows)], "synthetic", "T")

    # a limit that is merely TOUCHED must not fill
    plan = Setup(direction="BUY", entry=100.0, sl=95.0, tp1=105.0, tp2=110.0,
                 entry_type="LIMIT", mode="INTRADAY")
    touch = series([(101, 102, 100.0, 101)] * 60)          # low == entry exactly
    out = _simulate(plan, touch, 0, mode, spread=0.2)
    check("backtest/touch does not fill", out[0] == "EXPIRED", f"{out[0]}: {out[1]}")

    # trade-through fills
    through = series([(101, 102, 99.0, 101)] + [(101, 111, 100.5, 110.5)] * 60)
    out2 = _simulate(plan, through, 0, mode, spread=0.2)
    check("backtest/trade-through fills", out2[0] in ("WIN", "LOSS", "TIMESTOP"), out2[0])

    # a bar that hits both target and stop must be booked as a loss
    both = series([(101, 102, 99.0, 101)] + [(100, 111, 94.0, 96)] * 60)
    out3 = _simulate(plan, both, 0, mode, spread=0.2)
    check("backtest/both-hit is a loss", out3[0] == "LOSS" and out3[2] <= 0,
          f"{out3[0]} r={out3[2]}")

    # spread is paid on entry: the buy fills above the limit
    check("backtest/spread is paid", out2[7] > plan.entry, f"fill {out2[7]} vs entry {plan.entry}")


def t_config():
    cfg = EngineConfig()
    check("config/scan interval is 60s", cfg.scan_interval_sec == 60)
    for name, m in MODES.items():
        check(f"config/{name} timeframes distinct", len(m.timeframes) >= 3)
        check(f"config/{name} exec faster than bias",
              tf_seconds(m.ltf) <= tf_seconds(m.htf))
        check(f"config/{name} trigger fastest", tf_seconds(m.ttf) <= tf_seconds(m.ltf))
        check(f"config/{name} targets ascend", list(m.tp_r) == sorted(m.tp_r))
        check(f"config/{name} min rr below tp2", m.min_rr <= m.tp_r[1] * 1.5)
    check("config/daily ceiling is a ceiling not a quota",
          cfg.risk.max_setups_per_day >= cfg.risk.target_setups_per_day)


TESTS = [t_candles, t_smc, t_grading, t_setup_geometry, t_probability_honesty,
         t_feed_honesty, t_invalidation, t_backtest_fills, t_config]


def run_selftest() -> int:
    global _FAILS, _RUN
    _FAILS, _RUN = [], 0
    for fn in TESTS:
        name = fn.__name__[2:]
        before_fails, before_run = len(_FAILS), _RUN
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001 - report as a failure
            _FAILS.append(f"{name}: raised {type(exc).__name__}: {exc}")
        ran, failed = _RUN - before_run, len(_FAILS) - before_fails
        mark = "ok  " if failed == 0 else "FAIL"
        print(f"  [{mark}] {name:22} {ran:3} checks"
              + (f"  {failed} failed" if failed else ""))
    print()
    if _FAILS:
        for f in _FAILS:
            print(f"  FAILED: {f}")
        print(f"\n  {len(_FAILS)} of {_RUN} checks failed")
        return 1
    print(f"  all {_RUN} checks passed")
    return 0
