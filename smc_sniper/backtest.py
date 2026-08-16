"""Phase 6 -- The backtesting engine.

The fill model is where backtests lie, so the rules are stated up front and are
not configurable into dishonesty:

1. **Trade-through only.** A limit at price P fills only if price trades
   strictly *beyond* P (``low < P`` for a buy limit). A touch (``low == P``) is
   not a fill. Touch-fills previously turned an honest 45% win rate into a
   published 70% in this repo.
2. **Spread is always paid at entry.** Bars are broker BID, so a long enters at
   ``P + spread`` and a short is charged the same spread at entry. Charging the
   short at entry rather than exit is marginally *conservative*.
3. **Slippage** is added against the trade on entry and on stop exits.
4. **Same-bar TP and SL resolves as a loss.** Intrabar order is unknowable from
   OHLC, so ambiguity always resolves against the strategy.
5. **A fill bar that also reaches the stop is a loss**, same reasoning.
6. **Commission** is charged per round turn.

No lookahead: signals are generated from bars closed at or before the signal
bar, and management only ever reads bars strictly after entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .risk import RiskEngine
from .signal_engine import PairContext, Rejection, Signal, generate_signals


@dataclass
class Trade:
    symbol: str
    setup_id: str
    signal_id: str
    direction: str
    side: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float               # effective fill, spread+slippage included
    limit_price: float         # the resting limit
    stop: float
    tp1: float
    tp2: float
    tp3: float
    exit_price: float
    exit_reason: str
    r_multiple: float          # realised R, net of costs, partials included
    gross_r: float
    risk_price: float
    size_lots: float
    risk_amount: float
    pnl: float
    score: float
    session: str
    setup_type: str
    liquidity_type: str
    htf_bias: str
    zone_kind: str
    rr_tp2: float
    bars_held: int
    mae_r: float               # max adverse excursion in R
    mfe_r: float               # max favourable excursion in R
    partials: list = field(default_factory=list)
    balance_after: float = 0.0


# Set just before a fork-based Pool is created; workers inherit it via
# copy-on-write so the (large) contexts never have to be pickled.
_PARALLEL_STATE: tuple | None = None


def _generate_for_symbol(symbol: str):
    """Pool worker: generate signals for one pair from the inherited state."""
    contexts, cfg = _PARALLEL_STATE
    sigs, rejs = generate_signals(contexts[symbol], cfg)
    return symbol, sigs, rejs


def _flip_times(ctx, kinds: tuple[str, ...]) -> dict:
    """Close times of setup-timeframe structure events, bucketed by direction.

    Cached on the context because contexts are shared between config variants
    and the events themselves never change -- only which ``kinds`` count does.
    Indexing on ``close_time`` (not the event bar's own timestamp) is what
    keeps the early-exit rule free of lookahead: the event is knowable only
    once the bar that produced it has closed.
    """
    cache = getattr(ctx, "_flip_cache", None)
    if cache is None:
        cache = {}
        ctx._flip_cache = cache
    if kinds not in cache:
        close_times = ctx.setup["close_time"].values
        out = {}
        for d in ("bullish", "bearish"):
            stamps = [close_times[e.index] for e in ctx.setup_state.events
                      if e.direction == d and e.kind in kinds
                      and 0 <= e.index < len(close_times)]
            out[d] = np.array(sorted(stamps), dtype="datetime64[ns]")
        cache[kinds] = out
    return cache[kinds]


def _spread_multiplier(ts: pd.Timestamp, cfg) -> float:
    from .sessions import session_of
    name = session_of(ts, cfg.get("sessions"))
    widen = cfg.get("execution.spread_widen_session", {}) or {}
    return float(widen.get(name, 1.0))


class Backtester:
    """Event-driven, multi-timeframe, cost-aware backtester."""

    def __init__(self, cfg, engine):
        self.cfg = cfg
        self.engine = engine
        self.stack = cfg.stack
        self._signal_cache = None
        self.risk_engine = RiskEngine(cfg)

    # -- signal generation ----------------------------------------------
    def bind(self, contexts: dict[str, PairContext]) -> dict[str, PairContext]:
        """Point cached contexts at THIS backtester's config.

        Contexts are expensive, so variants reuse them -- but a reused context
        still carries the config it was built with. Without this rebind, a
        perturbation or matched-R run silently evaluates the BASELINE config
        and reports identical numbers for every parameter value, which looks
        like admirable robustness and is actually a broken experiment.

        Note the limit: rebinding fixes parameters consumed at signal time
        (thresholds, stops, targets, sessions). Parameters that shape the
        context itself -- swing lookback, displacement, liquidity, order
        blocks, FVG sizing -- require a full rebuild, which
        :func:`walkforward.perturbation_check` does explicitly.
        """
        for ctx in contexts.values():
            ctx.cfg = self.cfg
            ctx.icfg = self.cfg.for_instrument(ctx.symbol)
            ctx.stack = self.cfg.stack
        self._signal_cache = None
        return contexts

    def build_contexts(self, symbols=None) -> dict[str, PairContext]:
        out = {}
        for symbol in (symbols or self.cfg.symbols):
            ctx = PairContext(self.engine, symbol, self.cfg)
            if ctx.ok:
                out[symbol] = ctx
            else:
                print(f"  [skip] {symbol}: missing data for stack {self.stack['name']}")
        return out

    def collect_signals(self, contexts: dict[str, PairContext], use_cache: bool = True,
                        n_jobs: int | None = None):
        """Generate signals once and cache them.

        Signal generation is the expensive step and is independent of the risk
        engine, so walk-forward folds and train/test splits reuse one pass.

        ``n_jobs`` > 1 fans the per-pair work across processes. Pairs are
        completely independent at this stage -- the portfolio-level risk engine
        runs afterwards, sequentially, over the merged and time-sorted list, so
        parallelism cannot change the result. On Linux the fork start method
        lets workers inherit the already-built contexts instead of pickling
        them; only the (small) signal lists come back.
        """
        if use_cache and self._signal_cache is not None:
            return self._signal_cache

        n_jobs = n_jobs if n_jobs is not None else int(self.cfg.get("backtest.n_jobs", 1))
        items = list(contexts.items())
        signals: list[tuple[str, Signal]] = []
        rejections: list[Rejection] = []

        if n_jobs and n_jobs > 1 and len(items) > 1:
            import multiprocessing as mp
            global _PARALLEL_STATE
            _PARALLEL_STATE = (contexts, self.cfg)
            try:
                ctx_mp = mp.get_context("fork")
                with ctx_mp.Pool(min(n_jobs, len(items))) as pool:
                    for symbol, sigs, rejs in pool.imap_unordered(
                            _generate_for_symbol, [s for s, _ in items]):
                        signals.extend((symbol, s) for s in sigs)
                        rejections.extend(rejs)
            except (OSError, ValueError, ImportError):
                # Fall back to serial rather than lose the run.
                signals, rejections = [], []
                for symbol, ctx in items:
                    sigs, rejs = generate_signals(ctx, self.cfg)
                    signals.extend((symbol, s) for s in sigs)
                    rejections.extend(rejs)
        else:
            for symbol, ctx in items:
                sigs, rejs = generate_signals(ctx, self.cfg)
                signals.extend((symbol, s) for s in sigs)
                rejections.extend(rejs)

        signals.sort(key=lambda pair: pair[1].time)
        if use_cache:
            self._signal_cache = (signals, rejections)
        return signals, rejections

    # -- fill + management ------------------------------------------------
    def simulate_trade(self, ctx: PairContext, sig: Signal) -> Trade | None:
        """Resolve one signal into a filled trade, or None if never filled."""
        cfg = self.cfg
        icfg = ctx.icfg
        entry_tf = self.stack["entry_tf"]
        eframe = ctx.entry_frame
        pip = icfg.pip

        # Entry-timeframe bar strictly AFTER the signal bar closes.
        sig_close = ctx.setup["close_time"].iloc[sig.bar_index]
        start = int(eframe.index.searchsorted(sig_close, side="left"))
        if start >= len(eframe):
            return None

        # The limit expires with the setup bar window.
        expiry_idx = min(sig.valid_until_bar, len(ctx.setup) - 1)
        expiry_time = ctx.setup["close_time"].iloc[expiry_idx]
        end = int(eframe.index.searchsorted(expiry_time, side="left"))

        spread_price = sig.spread_pips * pip * _spread_multiplier(sig.time, cfg)
        slip = float(cfg.get("execution.slippage_pips", 0.2)) * pip
        long = sig.direction == "bullish"
        tp_through = bool(cfg.get("execution.tp_trade_through", False))

        highs, lows = eframe["high"].values, eframe["low"].values
        opens = eframe["open"].values

        # --- find the fill (trade-through, never a touch) ---------------
        fill_i = None
        for j in range(start, min(end + 1, len(eframe))):
            if long and lows[j] < sig.entry:
                fill_i = j
                break
            if not long and highs[j] > sig.entry:
                fill_i = j
                break
        if fill_i is None:
            return None

        # Effective fill: spread + slippage, always against us.
        if long:
            entry_px = sig.entry + spread_price + slip
        else:
            entry_px = sig.entry - spread_price - slip

        risk_price = abs(entry_px - sig.stop)
        if risk_price <= 0:
            return None

        # --- position sizing --------------------------------------------
        size_lots, risk_amount = self.risk_engine.size(sig.symbol, risk_price)

        tps = [sig.tp1, sig.tp2, sig.tp3]
        # Portions closed at TP1 / TP2 / TP3. These MUST sum to 1.0.
        # When scale-outs are disabled the FIRST target closes the whole
        # position -- otherwise a "no partials" run allocates 0% to TP1 and
        # TP2, banks nothing on reaching its target, needs three separate bars
        # to exit, and can reverse into a full -1R loss after price already
        # traded through the target. That bug silently corrupted the matched-R
        # control, which is the one measurement that has to be trustworthy.
        pcfg = icfg.get("targets.partial_tp")
        if pcfg.get("enabled", True):
            closes_pct = [float(pcfg.get("tp1_close_pct", 0.5)),
                          float(pcfg.get("tp2_close_pct", 0.3))]
            closes_pct.append(max(0.0, 1.0 - closes_pct[0] - closes_pct[1]))
        else:
            closes_pct = [1.0, 0.0, 0.0]

        be_cfg = icfg.get("targets.breakeven")
        tr_cfg = icfg.get("targets.trailing")
        max_hold = int(icfg.get("targets.max_hold_bars", 96))

        stop = sig.stop
        remaining = 1.0
        realised_r = 0.0
        partials: list = []
        tp_stage = 0
        mae_r = mfe_r = 0.0
        exit_reason = "time_stop"
        exit_price = float(eframe["close"].values[min(fill_i + max_hold, len(eframe) - 1)])
        exit_time = eframe.index[min(fill_i + max_hold, len(eframe) - 1)]
        bars_held = 0
        sign = 1.0 if long else -1.0

        def r_of(price: float) -> float:
            return sign * (price - entry_px) / risk_price

        # --- intraday flat (v3 scalping, opt-in) -------------------------
        # A scalp is flat by the end of its session. The deadline is the first
        # entry bar at or after `flat_by_utc_hour` on the entry's own UTC day
        # (rolling to the next day when the fill is already past it), and the
        # exit takes that bar's OPEN with slippage against us -- the first
        # price actually reachable once the deadline passes, never a close the
        # position could not have got out at.
        intraday_cfg = icfg.get("targets.intraday", {}) or {}
        flat_deadline = None
        if intraday_cfg.get("enabled", False):
            flat_hour = int(intraday_cfg.get("flat_by_utc_hour", 21))
            fill_ts = eframe.index[fill_i]
            flat_deadline = fill_ts.normalize() + pd.Timedelta(hours=flat_hour)
            if fill_ts >= flat_deadline:
                flat_deadline += pd.Timedelta(days=1)

        # --- early structural invalidation (v2, opt-in) ------------------
        # If the setup timeframe shifts AGAINST the position while the trade is
        # still near flat, take the smaller loss instead of riding to the full
        # stop. The exit price is the OPEN of the first entry bar that starts
        # after the event's bar closed -- the first price actually reachable.
        inv_cfg = icfg.get("filters.structural_invalidation", {}) or {}
        inval_time = None
        max_r_exit = float(inv_cfg.get("max_r_to_exit", 0.5))
        if inv_cfg.get("enabled", False):
            kinds = tuple(inv_cfg.get("kinds", ["MSS", "BOS"]))
            against = "bearish" if long else "bullish"
            stamps = _flip_times(ctx, kinds)[against]
            entry_stamp = np.datetime64(eframe.index[fill_i].tz_localize(None))
            pos = int(np.searchsorted(stamps, entry_stamp, side="right"))
            if pos < len(stamps):
                inval_time = stamps[pos]
        ebar_times = eframe.index.tz_localize(None).values if inval_time is not None else None

        # A fill bar that also reaches the stop is a loss (rule 5).
        limit_j = min(fill_i + max_hold, len(eframe) - 1)
        for j in range(fill_i, limit_j + 1):
            bars_held = j - fill_i
            hi, lo = highs[j], lows[j]
            mae_r = min(mae_r, r_of(lo if long else hi))
            mfe_r = max(mfe_r, r_of(hi if long else lo))

            stop_hit = (lo <= stop) if long else (hi >= stop)
            nxt = tps[tp_stage] if tp_stage < 3 else None
            tp_hit = False
            if nxt is not None:
                # v5 AUDIT FIX (`execution.tp_trade_through`). A take-profit is
                # a resting limit exactly like the entry, so the same rule has
                # to apply to it: a touch is not a fill. The engine required
                # trade-through on the ENTRY limit (rule 1) but accepted a
                # touch on the TARGET -- an asymmetry that always resolved in
                # the strategy's favour. Default off so v2 stays reproducible.
                if tp_through:
                    tp_hit = (hi > nxt) if long else (lo < nxt)
                else:
                    tp_hit = (hi >= nxt) if long else (lo <= nxt)

            # Rule 4/5: ambiguity resolves against us.
            if stop_hit:
                px = stop - slip if long else stop + slip
                realised_r += remaining * r_of(px)
                exit_price, exit_reason, exit_time = float(px), (
                    "stop_loss" if stop == sig.stop else "breakeven_or_trail"), eframe.index[j]
                remaining = 0.0
                break

            # Structural invalidation is checked AFTER the stop and BEFORE the
            # target, so every ambiguous bar still resolves against us.
            if inval_time is not None and ebar_times[j] >= inval_time:
                px = opens[j] - slip if long else opens[j] + slip
                if r_of(px) < max_r_exit:
                    realised_r += remaining * r_of(px)
                    exit_price, exit_reason = float(px), "structure_invalidated"
                    exit_time = eframe.index[j]
                    remaining = 0.0
                    break
                inval_time = None   # already profitable; let management run

            # Intraday flat, checked AFTER the stop and BEFORE the target so
            # every ambiguous bar still resolves against the strategy.
            if flat_deadline is not None and eframe.index[j] >= flat_deadline:
                px = opens[j] - slip if long else opens[j] + slip
                realised_r += remaining * r_of(px)
                exit_price, exit_reason = float(px), "session_flat"
                exit_time = eframe.index[j]
                remaining = 0.0
                break

            if tp_hit:
                px = nxt
                part = closes_pct[tp_stage]
                # Close the remainder once nothing is allocated to later stages.
                if part >= remaining or sum(closes_pct[tp_stage + 1:]) <= 0:
                    part = remaining
                realised_r += part * r_of(px)
                remaining -= part
                partials.append({"stage": f"TP{tp_stage + 1}", "price": float(px),
                                 "portion": round(part, 3), "r": round(r_of(px), 3),
                                 "time": str(eframe.index[j])})
                tp_stage += 1
                if remaining <= 1e-9:
                    exit_price, exit_reason, exit_time = float(px), f"TP{tp_stage}", eframe.index[j]
                    break

            # Break-even / trailing management (never widens a stop).
            cur_r = r_of(hi if long else lo)
            if be_cfg.get("enabled", True) and cur_r >= float(be_cfg.get("trigger_r", 1.0)):
                be = entry_px + sign * float(be_cfg.get("offset_r", 0.05)) * risk_price
                stop = max(stop, be) if long else min(stop, be)
            if tr_cfg.get("enabled", True) and cur_r >= float(tr_cfg.get("start_after_r", 2.0)):
                atr_j = eframe["atr"].values[j]
                if np.isfinite(atr_j):
                    trail = (hi - float(tr_cfg.get("atr_mult", 1.5)) * atr_j) if long else \
                            (lo + float(tr_cfg.get("atr_mult", 1.5)) * atr_j)
                    stop = max(stop, trail) if long else min(stop, trail)
        else:
            if remaining > 1e-9:
                realised_r += remaining * r_of(exit_price)
                remaining = 0.0

        if remaining > 1e-9:
            realised_r += remaining * r_of(exit_price)

        # Commission per round turn, expressed in R.
        comm = float(cfg.get("execution.commission_per_lot_rt", 7.0)) * size_lots
        gross_r = realised_r
        net_r = realised_r - (comm / risk_amount if risk_amount > 0 else 0.0)
        pnl = net_r * risk_amount

        return Trade(
            symbol=sig.symbol, setup_id=sig.setup_id, signal_id=sig.signal_id,
            direction=sig.direction, side=sig.side, signal_time=sig.time,
            entry_time=eframe.index[fill_i], exit_time=exit_time,
            entry=float(entry_px), limit_price=float(sig.entry), stop=float(sig.stop),
            tp1=sig.tp1, tp2=sig.tp2, tp3=sig.tp3, exit_price=float(exit_price),
            exit_reason=exit_reason, r_multiple=float(net_r), gross_r=float(gross_r),
            risk_price=float(risk_price), size_lots=size_lots, risk_amount=risk_amount,
            pnl=float(pnl), score=sig.score, session=sig.session,
            setup_type=sig.setup_type, liquidity_type=sig.liquidity_type,
            htf_bias=sig.htf_bias, zone_kind=sig.zone_kind, rr_tp2=sig.rr_tp2,
            bars_held=bars_held, mae_r=float(mae_r), mfe_r=float(mfe_r),
            partials=partials,
        )

    # -- full run ---------------------------------------------------------
    def run(self, symbols=None, contexts=None, start=None, end=None,
            collect_rejections: bool = True, allowed_symbols=None):
        """Run the portfolio backtest. Returns ``(trades, rejections, contexts)``.

        ``allowed_symbols`` restricts which pairs may trade *without*
        regenerating signals -- used by the pair-selection protocol, where the
        selection is made on TRAIN and then applied unchanged to TEST.
        """
        if contexts is None:
            contexts = self.build_contexts(symbols)
        elif contexts:
            # Contexts are shared between variants (matched-R, perturbation),
            # so check what they are CURRENTLY bound to rather than trusting a
            # once-only flag -- another Backtester may have rebound them since.
            first = next(iter(contexts.values()))
            if first.cfg is not self.cfg:
                self.bind(contexts)
        signals, rejections = self.collect_signals(contexts)
        self.n_signals_total = len(signals)
        if allowed_symbols is not None:
            allowed = set(allowed_symbols)
            signals = [(s, g) for s, g in signals if s in allowed]
            rejections = [r for r in rejections if r.symbol in allowed]
        if start is not None:
            signals = [(s, g) for s, g in signals if g.time >= start]
            rejections = [r for r in rejections if r.time >= start]
        if end is not None:
            signals = [(s, g) for s, g in signals if g.time < end]
            rejections = [r for r in rejections if r.time < end]

        self.risk_engine = RiskEngine(self.cfg)
        book_on_exit = self.risk_engine.book_on_exit
        pending: list[Trade] = []      # filled but not yet closed, by exit_time
        trades: list[Trade] = []
        # A position occupies a slot from the moment its order is placed until
        # it closes -- a resting limit ties up risk budget just as a filled one
        # does -- so the interval is [signal_time, exit_time).
        enforce = bool(self.cfg.get("risk.enforce_concurrency", False))
        open_trades: list[Trade] = []
        for symbol, sig in signals:
            if book_on_exit:
                # Everything that has genuinely CLOSED by the time this setup
                # appears is booked first; nothing still open contributes to
                # the daily/weekly loss gates or the consecutive-loss counter.
                while pending and pending[0].exit_time <= sig.time:
                    self.risk_engine.register(pending.pop(0), count_entry=False)
            if enforce:
                open_trades = [t for t in open_trades if t.exit_time > sig.time]
                self.risk_engine.set_open_positions(open_trades)
            ok, reason = self.risk_engine.can_trade(symbol, sig)
            if not ok:
                if collect_rejections:
                    rejections.append(Rejection(symbol, sig.bar_index, sig.time,
                                                sig.direction, "risk", reason,
                                                sig.score, sig.session))
                continue
            trade = self.simulate_trade(contexts[symbol], sig)
            if trade is None:
                if collect_rejections:
                    rejections.append(Rejection(symbol, sig.bar_index, sig.time,
                                                sig.direction, "no_fill",
                                                "limit_never_traded_through",
                                                sig.score, sig.session))
                continue
            if book_on_exit:
                self.risk_engine.note_entry(sig.time)
                pending.append(trade)
                pending.sort(key=lambda t: t.exit_time)
            else:
                self.risk_engine.register(trade)
            trade.balance_after = self.risk_engine.balance
            trades.append(trade)
            if enforce:
                open_trades.append(trade)

        for trade in pending:
            self.risk_engine.register(trade, count_entry=False)
        trades.sort(key=lambda t: t.exit_time)
        if book_on_exit:
            # The running-balance column follows the exit clock too.
            bal = self.risk_engine.start_balance
            for trade in trades:
                bal += trade.pnl
                trade.balance_after = bal
        return trades, rejections, contexts


def trades_to_frame(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        row = t.__dict__.copy()
        row["partials"] = len(t.partials)
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame.sort_values("exit_time").reset_index(drop=True)


def rejections_to_frame(rejections: list[Rejection]) -> pd.DataFrame:
    if not rejections:
        return pd.DataFrame()
    return pd.DataFrame([{
        "symbol": r.symbol, "time": r.time, "direction": r.direction,
        "step": r.step, "reason": r.reason, "score": r.score, "session": r.session,
    } for r in rejections])
