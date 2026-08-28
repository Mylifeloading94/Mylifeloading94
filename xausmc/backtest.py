"""
Historical validation engine (spec §9 / §18).

This is HISTORICAL/BACKTEST DATA. Nothing it produces is a live signal, and the
numbers it emits are the ONLY source of the probabilities the live bot shows.

It runs the identical `setups.detect` + `grading.grade` code path the live
scanner runs, walking history bar by bar with a strict anti-lookahead gate:
at simulated time T the engine may only see bars that had CLOSED by T.

Fill model — deliberately pessimistic, because optimistic fills are how
backtests lie (this repo has been burned by exactly that before):
  * a LIMIT fills only on trade-through (buy needs low <= entry - 1 pip)
  * the fill pays the spread
  * a bar that touches BOTH target and stop is booked as a LOSS
  * a bar that fills the order and breaches the stop is booked as a LOSS
  * unfilled orders expire; open trades hit a time stop

Trade management (fixed, and identical for every trade so the R multiples are
comparable): 50% off at TP1 and stop to breakeven, the remainder runs to TP2.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .candles import PIP, Series, resample, tf_seconds
from .config import MODES, EngineConfig, ModeSpec
from .feed import historical
from .grading import grade
from .sessions import session_at
from .setups import build_context, detect
from .stats import StatsStore

GRADE_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1, "INVALID": 0}
DEFAULT_SPREAD = 0.25          # USD on XAUUSD (2.5 pips) — retail-typical


@dataclass
class BTTrade:
    id: str = ""
    pattern: str = ""
    mode: str = ""
    grade: str = ""
    direction: str = ""
    session: str = ""
    exec_tf: str = ""
    score: float = 0.0
    signal_ts: int = 0
    fill_ts: int = 0
    exit_ts: int = 0
    entry: float = 0.0
    fill: float = 0.0
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    target_rr: float = 0.0
    r_multiple: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    outcome: str = ""          # WIN | LOSS | BREAKEVEN | TIMESTOP | EXPIRED
    exit_reason: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class BacktestResult:
    trades: list[BTTrade] = field(default_factory=list)
    signals: int = 0
    filled: int = 0
    expired: int = 0
    bars_scanned: int = 0
    meta: dict = field(default_factory=dict)

    def resolved(self) -> list[dict]:
        return [t.as_dict() for t in self.trades if t.outcome in ("WIN", "LOSS", "BREAKEVEN", "TIMESTOP")]


def _simulate(trade_setup, sim: Series, from_idx: int, mode: ModeSpec,
              spread: float) -> tuple[str, str, float, float, float, int, int, float]:
    """
    Walk the trigger-timeframe bars forward from `from_idx` and resolve one setup.
    Expiry and the time stop are defined in EXECUTION-timeframe bars, so they are
    converted into trigger-timeframe bars here.
    Returns (outcome, reason, r_multiple, mfe_r, mae_r, fill_ts, exit_ts, fill_px).
    """
    ratio = max(1, tf_seconds(mode.ltf) // tf_seconds(mode.ttf))
    buy = trade_setup.direction == "BUY"
    sign = 1 if buy else -1
    entry, sl, tp1, tp2 = trade_setup.entry, trade_setup.sl, trade_setup.tp1, trade_setup.tp2
    half_spread = spread / 2.0
    fill_px = entry + sign * half_spread          # pay the spread on entry
    risk = abs(fill_px - sl)
    if risk <= 0:
        return "EXPIRED", "degenerate risk after spread", 0.0, 0.0, 0.0, 0, 0, 0.0

    bars = sim.bars
    expiry = from_idx + mode.max_age_bars * 3 * ratio
    time_stop = mode.typical_hold_bars * ratio
    filled_at = -1
    fill_ts = exit_ts = 0
    mfe = mae = 0.0
    half_out = False

    for i in range(from_idx, len(bars)):
        b = bars[i]
        if filled_at < 0:
            if trade_setup.entry_type == "MARKET" and i == from_idx:
                filled_at, fill_ts = i, b.ts
            else:
                # trade-through required: a touch is not a fill
                hit = (b.l <= entry - PIP) if buy else (b.h >= entry + PIP)
                if hit:
                    filled_at, fill_ts = i, b.ts
                elif i >= expiry:
                    return "EXPIRED", "entry zone never filled before expiry", 0.0, 0.0, 0.0, 0, b.ts, 0.0
                else:
                    continue
            # the fill bar itself can stop us out
            if (buy and b.l <= sl) or (not buy and b.h >= sl):
                return "LOSS", "stop hit on the fill bar", -1.0, 0.0, -1.0, fill_ts, b.ts, fill_px

        adverse = (fill_px - b.l) if buy else (b.h - fill_px)
        favour = (b.h - fill_px) if buy else (fill_px - b.l)
        mae = min(mae, -max(0.0, adverse) / risk)
        mfe = max(mfe, max(0.0, favour) / risk)

        hit_sl = (b.l <= sl) if buy else (b.h >= sl)
        hit_tp1 = (b.h >= tp1) if buy else (b.l <= tp1)
        hit_tp2 = (b.h >= tp2) if buy else (b.l <= tp2)
        exit_ts = b.ts

        if hit_sl and (hit_tp1 or hit_tp2):
            # ambiguous intrabar order -> assume the worst
            r = (0.5 * abs(tp1 - fill_px) / risk - 0.5) if half_out else -1.0
            return ("WIN" if r > 0.02 else "LOSS"), "stop and target in the same bar — booked as the stop", \
                round(r, 3), mfe, mae, fill_ts, exit_ts, fill_px
        if hit_sl:
            if half_out:
                r = 0.5 * abs(tp1 - fill_px) / risk        # runner stopped at breakeven
                return ("WIN" if r > 0.02 else "BREAKEVEN"), "runner stopped at breakeven after TP1", \
                    round(r, 3), mfe, mae, fill_ts, exit_ts, fill_px
            return "LOSS", "stop loss hit", -1.0, mfe, mae, fill_ts, exit_ts, fill_px
        if hit_tp2:
            r = (0.5 * abs(tp1 - fill_px) / risk + 0.5 * abs(tp2 - fill_px) / risk) if half_out \
                else abs(tp2 - fill_px) / risk
            return "WIN", "TP2 reached", round(r, 3), mfe, mae, fill_ts, exit_ts, fill_px
        if hit_tp1 and not half_out:
            half_out = True
            sl = fill_px                                    # stop to breakeven
        if filled_at >= 0 and i - filled_at >= time_stop:
            close_r = sign * (b.c - fill_px) / risk
            r = (0.5 * abs(tp1 - fill_px) / risk + 0.5 * close_r) if half_out else close_r
            return "TIMESTOP", f"time stop after {mode.typical_hold_bars} {mode.ltf} bars", \
                round(r, 3), mfe, mae, fill_ts, exit_ts, fill_px

    return "EXPIRED", "ran out of history", 0.0, mfe, mae, fill_ts, exit_ts, fill_px


def run_mode(mode_name: str, series_by_tf: dict[str, Series], cfg: EngineConfig,
             min_grade: str = "C", spread: float = DEFAULT_SPREAD,
             warmup: int = 300, progress: bool = True) -> BacktestResult:
    mode = MODES[mode_name]
    ltf, ttf = series_by_tf[mode.ltf], series_by_tf[mode.ttf]
    res = BacktestResult(meta={"mode": mode_name, "spread": spread, "min_grade": min_grade})
    span = tf_seconds(mode.ltf)
    ttf_ts = [b.ts for b in ttf.bars]
    open_until = 0                      # no overlapping trades within a mode
    t0 = time.time()

    # HTF/MTF analyses only change when their own bar closes -> cache by window end
    for i in range(warmup, len(ltf.bars) - 1):
        now_ts = ltf.bars[i].ts + span
        res.bars_scanned += 1
        if progress and res.bars_scanned % 500 == 0:
            print(f"    {mode_name}: {res.bars_scanned}/{len(ltf.bars) - warmup} bars "
                  f"({time.time() - t0:.0f}s, {len(res.trades)} trades)", flush=True)
        if now_ts <= open_until:
            continue
        sess = session_at(now_ts)
        if sess.name not in cfg.risk.allowed_sessions:
            continue

        view = {tf: s.before(now_ts).tail(MODES[mode_name].bars.get(tf, 300))
                for tf, s in series_by_tf.items() if tf in mode.timeframes}
        if any(len(v) < 60 for v in view.values()):
            continue
        ctx = build_context(mode, view, cfg.strategy, ts=now_ts)
        if ctx is None:
            continue
        cands = [grade(s, cfg.strategy) for s in detect(ctx, "HISTORICAL", "backtest")]
        cands = [s for s in cands if s.status == "VALID"
                 and GRADE_RANK[s.grade] >= GRADE_RANK[min_grade]]
        if not cands:
            continue
        best = max(cands, key=lambda s: s.score)
        res.signals += 1

        import bisect
        j = bisect.bisect_right(ttf_ts, now_ts - 1)
        if j >= len(ttf.bars):
            continue
        outcome, reason, r, mfe, mae, fts, xts, fpx = _simulate(best, ttf, j, mode, spread)
        if outcome == "EXPIRED":
            res.expired += 1
        else:
            res.filled += 1
            open_until = xts
        res.trades.append(BTTrade(
            id=best.id, pattern=best.pattern, mode=mode_name, grade=best.grade,
            direction=best.direction, session=sess.name, exec_tf=mode.ltf, score=best.score,
            signal_ts=now_ts, fill_ts=fts, exit_ts=xts, entry=best.entry, fill=round(fpx, 2),
            sl=best.sl, tp1=best.tp1, tp2=best.tp2, target_rr=best.rr,
            r_multiple=r, mfe_r=round(mfe, 3), mae_r=round(mae, 3),
            outcome=outcome, exit_reason=reason))
    return res


def load_history(provider: str, base_tf: str, bars: int,
                 cache_dir: str | None = None) -> dict[str, Series]:
    """Fetch one deep base series and derive every higher timeframe from it."""
    base = historical(provider, base_tf, bars, cache_dir)
    out = {base_tf: base}
    for tf in ("M5", "M15", "H1", "H4"):
        if tf_seconds(tf) > tf_seconds(base_tf):
            out[tf] = resample(base, tf)
    return out


# Each mode needs its own base timeframe: SCALP executes on M5 and triggers on
# M1, so it cannot be derived from an M5 base. Bars are chosen so every mode
# sees a comparable calendar span.
DEFAULT_PLAN = [
    ("M5", 150_000, ["INTRADAY", "SWING"]),   # ~520 days
    ("M1", 120_000, ["SCALP"]),               # ~83 days
]


def run_multi(cfg: EngineConfig, plan=None, provider: str = "binance", min_grade: str = "C",
              spread: float = DEFAULT_SPREAD, out_dir: str | None = None,
              progress: bool = True) -> tuple[StatsStore, dict]:
    """Run several modes, each from the base timeframe it actually needs, and
    pool the resolved trades into one stats store."""
    plan = plan or DEFAULT_PLAN
    out_dir = out_dir or cfg.state_dir
    os.makedirs(out_dir, exist_ok=True)
    all_trades: list[dict] = []
    per_mode: dict[str, dict] = {}
    spans: dict[str, list[int]] = {}

    for base_tf, bars, modes in plan:
        if progress:
            print(f"  fetching {bars} {base_tf} bars from {provider} ...", flush=True)
        series = load_history(provider, base_tf, bars, os.path.join(out_dir, "cache"))
        if progress:
            print("    " + "  ".join(f"{tf}:{len(s)}" for tf, s in
                                     sorted(series.items(), key=lambda kv: tf_seconds(kv[0]))),
                  flush=True)
        spans[base_tf] = [series[base_tf].bars[0].ts, series[base_tf].bars[-1].ts]
        for m in modes:
            need = set(MODES[m].timeframes)
            if not need.issubset(series):
                per_mode[m] = {"skipped": f"needs {sorted(need - set(series))}"}
                continue
            if progress:
                print(f"  running {m} on a {base_tf} base ...", flush=True)
            r = run_mode(m, series, cfg, min_grade, spread, progress=progress)
            rt = r.resolved()
            all_trades.extend(rt)
            per_mode[m] = {"base_tf": base_tf, "signals": r.signals, "filled": r.filled,
                           "expired": r.expired, "resolved": len(rt),
                           "bars_scanned": r.bars_scanned}
            if progress:
                print(f"    -> {r.signals} signals, {r.filled} filled, {len(rt)} resolved",
                      flush=True)

    meta = _meta(provider, all_trades, spread, min_grade, per_mode, spans)
    store = StatsStore.from_trades(all_trades, meta)
    store.save(os.path.join(out_dir, "stats.json"))
    with open(os.path.join(out_dir, "backtest_trades.json"), "w") as fh:
        json.dump(all_trades, fh, indent=1)
    return store, meta


def _meta(provider, trades, spread, min_grade, per_mode, spans) -> dict:
    first = min((t["signal_ts"] for t in trades), default=0)
    last = max((t["exit_ts"] or t["signal_ts"] for t in trades), default=0)
    return {
        "kind": "HISTORICAL_BACKTEST",
        "generated_at": int(time.time()),
        "provider": provider,
        "instrument": {"binance": "PAXGUSDT (PAX Gold — spot-gold proxy, trades 24/7)",
                       "yahoo": "GC=F (COMEX gold futures — proxy, carries basis)",
                       "tradelocker": "XAUUSD (broker spot)"}.get(provider, provider),
        "history_from": first, "history_to": last, "base_spans": spans,
        "spread_usd": spread, "min_grade": min_grade,
        "fill_model": ("trade-through limits only, spread paid on entry, "
                       "both-hit bars booked as losses, 50% off at TP1 then a "
                       "breakeven runner to TP2, time stop at the mode's hold limit"),
        "per_mode": per_mode,
        "disclaimer": ("Backtested on historical proxy data. Past performance is "
                       "not a prediction and not a guarantee of future results."),
    }


def run(cfg: EngineConfig, modes: list[str] | None = None, provider: str = "binance",
        bars: int = 40000, base_tf: str = "M5", min_grade: str = "C",
        spread: float = DEFAULT_SPREAD, out_dir: str | None = None,
        progress: bool = True) -> tuple[StatsStore, dict]:
    modes = modes or list(cfg.modes)
    out_dir = out_dir or cfg.state_dir
    os.makedirs(out_dir, exist_ok=True)

    if progress:
        print(f"  fetching {bars} {base_tf} bars from {provider} ...", flush=True)
    series = load_history(provider, base_tf, bars, os.path.join(out_dir, "cache"))
    if progress:
        for tf, s in sorted(series.items(), key=lambda kv: tf_seconds(kv[0])):
            print(f"    {tf:3} {len(s):6} bars", flush=True)

    all_trades: list[dict] = []
    per_mode: dict[str, dict] = {}
    for m in modes:
        need = set(MODES[m].timeframes)
        if not need.issubset(series):
            per_mode[m] = {"skipped": f"needs {sorted(need - set(series))}, "
                                      f"not derivable from {base_tf}"}
            if progress:
                print(f"  {m}: SKIPPED ({per_mode[m]['skipped']})", flush=True)
            continue
        if progress:
            print(f"  running {m} ...", flush=True)
        r = run_mode(m, series, cfg, min_grade, spread, progress=progress)
        rt = r.resolved()
        all_trades.extend(rt)
        per_mode[m] = {"signals": r.signals, "filled": r.filled, "expired": r.expired,
                       "resolved": len(rt), "bars_scanned": r.bars_scanned}
        if progress:
            print(f"    -> {r.signals} signals, {r.filled} filled, {len(rt)} resolved", flush=True)

    first = min((t["signal_ts"] for t in all_trades), default=0)
    last = max((t["exit_ts"] or t["signal_ts"] for t in all_trades), default=0)
    meta = {
        "kind": "HISTORICAL_BACKTEST",
        "generated_at": int(time.time()),
        "provider": provider,
        "instrument": {"binance": "PAXGUSDT (PAX Gold — spot-gold proxy)",
                       "yahoo": "GC=F (COMEX gold futures — proxy)",
                       "tradelocker": "XAUUSD (broker spot)"}.get(provider, provider),
        "base_timeframe": base_tf,
        "base_bars": len(series[base_tf]),
        "history_from": first, "history_to": last,
        "spread_usd": spread, "min_grade": min_grade,
        "fill_model": "trade-through limits, spread paid, both-hit=loss, 50% at TP1 then BE runner",
        "per_mode": per_mode,
    }
    store = StatsStore.from_trades(all_trades, meta)
    store.save(os.path.join(out_dir, "stats.json"))
    with open(os.path.join(out_dir, "backtest_trades.json"), "w") as fh:
        json.dump(all_trades, fh, indent=1)
    return store, meta
