"""The A+ entry sequence -- where every layer is assembled into a signal.

The spec's 12-step checklist, implemented literally and in order:

  1. HTF bias established (hard requirement -- never trade against it)
  2. Price in the right half of the structural leg (soft; hard veto at extremes)
  3. Price approaches a liquidity pool
  4. The pool is swept (wick through, close back)
  5. Displacement away from the sweep
  6. MSS / CHoCH / BOS confirms the shift
  7. An order block and/or FVG forms in the displacement leg
  8. Price retraces into that zone  (-> resting limit order)
  9. LTF confirmation on the entry timeframe
 10. R:R meets the minimum, else skip
 11. Spread is acceptable
 12. Execute

Every candidate that fails is recorded as a :class:`Rejection` with the failing
step, the reason and the score it had reached -- the decision log is meant to
show what was *not* traded as much as what was.

NO CONFIRMATION = NO TRADE.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import premium_discount as pdmod
from .data import MTFView
from .liquidity import MAJOR_POOLS, STRONG_POOLS, LiquidityMap
from .scoring import ScoreCard, score_setup
from .sessions import is_tradeable, session_of
from .structure import StructureState, build_structure, displacement_near
from .zones import Zone, ZoneMap


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    setup_id: str
    signal_id: str
    symbol: str
    direction: str                # bullish | bearish
    side: str                     # buy | sell
    bar_index: int
    time: pd.Timestamp
    entry: float                  # limit price (pre-spread)
    stop: float
    tp1: float
    tp2: float
    tp3: float
    risk_price: float             # |entry - stop| in price units
    rr_tp1: float
    rr_tp2: float
    rr_tp3: float
    score: float
    scorecard: ScoreCard
    session: str
    setup_type: str               # e.g. "sweep+MSS+OB+FVG"
    liquidity_type: str           # pool kind that was swept
    htf_bias: str
    structure_event: str
    zone_kind: str
    atr: float
    spread_pips: float
    valid_until_bar: int
    explanation: dict = field(default_factory=dict)


@dataclass
class Rejection:
    symbol: str
    bar_index: int
    time: pd.Timestamp
    direction: str
    step: str
    reason: str
    score: float
    session: str
    state: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-symbol precomputation
# ---------------------------------------------------------------------------
def _bias_array(state: StructureState, n: int, min_swings: int) -> np.ndarray:
    """Vectorised ``bias_at`` -- the committed bias at every bar index."""
    out = np.array(["neutral"] * n, dtype=object)
    swing_confirms = np.array([s.confirmed_at for s in state.swings], dtype=int)
    swing_counts = np.searchsorted(np.sort(swing_confirms), np.arange(n), side="right")
    bias = "neutral"
    ev = 0
    events = [e for e in state.events if e.kind in ("BOS", "MSS")]
    for i in range(n):
        while ev < len(events) and events[ev].index <= i:
            bias = events[ev].direction
            ev += 1
        out[i] = bias if swing_counts[i] >= min_swings else "neutral"
    return out


def _leg_arrays(state: StructureState, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Running (leg_high, leg_low) from the latest confirmed swings."""
    highs = np.full(n, np.nan)
    lows = np.full(n, np.nan)
    hi = lo = np.nan
    swings = sorted(state.swings, key=lambda s: s.confirmed_at)
    k = 0
    for i in range(n):
        while k < len(swings) and swings[k].confirmed_at <= i:
            if swings[k].kind == "high":
                hi = swings[k].price
            else:
                lo = swings[k].price
            k += 1
        highs[i], lows[i] = hi, lo
    return highs, lows


class PairContext:
    """All precomputed layers for one symbol under one timeframe stack."""

    def __init__(self, engine, symbol: str, cfg):
        self.symbol = symbol
        self.cfg = cfg
        self.icfg = cfg.for_instrument(symbol)
        self.stack = cfg.stack
        self.view = MTFView(engine, symbol, self.stack)
        self.ok = self.view.ok
        if not self.ok:
            return

        struct_cfg = self.icfg.get("structure")
        self.setup = self.view.frames[self.stack["setup_tf"]]
        self.bias_frame = self.view.frames[self.stack["bias_tf"]]
        self.struct_frame = self.view.frames[self.stack["structure_tf"]]
        self.entry_frame = self.view.frames[self.stack["entry_tf"]]

        # Structure on each layer
        self.bias_state = build_structure(self.bias_frame, struct_cfg)
        self.struct_state = build_structure(self.struct_frame, struct_cfg)
        self.setup_state = build_structure(self.setup, struct_cfg)

        min_swings = int(struct_cfg.get("min_swings_for_bias", 4))
        self.bias_by_bar = _bias_array(self.bias_state, len(self.bias_frame), min_swings)
        self.struct_bias_by_bar = _bias_array(self.struct_state,
                                              len(self.struct_frame), min_swings)
        self.leg_high, self.leg_low = _leg_arrays(self.struct_state,
                                                  len(self.struct_frame))

        # Setup-timeframe liquidity and zones
        self.liq = LiquidityMap(self.setup, self.setup_state.swings,
                                self.icfg.get("liquidity"))
        self.zones = ZoneMap(self.setup, self.setup_state,
                             self.icfg.get("order_blocks"), self.icfg.get("fvg"),
                             struct_cfg.get("displacement"))
        self.events_by_bar: dict[int, list] = {}
        for event in self.setup_state.events:
            self.events_by_bar.setdefault(event.index, []).append(event)

    def htf_bias(self, i: int) -> str:
        j = self.view.index_at(self.stack["bias_tf"], i)
        return self.bias_by_bar[j] if j >= 0 else "neutral"

    def structure_bias(self, i: int) -> str:
        j = self.view.index_at(self.stack["structure_tf"], i)
        return self.struct_bias_by_bar[j] if j >= 0 else "neutral"

    def structural_leg(self, i: int) -> tuple[float | None, float | None]:
        j = self.view.index_at(self.stack["structure_tf"], i)
        if j < 0:
            return None, None
        hi, lo = self.leg_high[j], self.leg_low[j]
        return (None if not np.isfinite(hi) else float(hi),
                None if not np.isfinite(lo) else float(lo))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pick_entry_zone(ob: Zone | None, fvg: Zone | None,
                     direction: str) -> tuple[Zone | None, str]:
    """Entry zone: the OB/FVG overlap when they intersect, else FVG, else OB.

    Preferring the overlap is the spec's "higher probability when the FVG forms
    inside the order block" -- it is a *narrower* zone, which means a deeper,
    less likely fill, not an easier one.
    """
    if ob is not None and fvg is not None:
        top = min(ob.top, fvg.top)
        bottom = max(ob.bottom, fvg.bottom)
        if top > bottom:
            overlap = Zone(max(ob.index, fvg.index), top, bottom, direction,
                           "order_block", ob.quality, True, ob.structure_event,
                           label="ob_fvg_overlap")
            return overlap, "OB+FVG overlap"
        return fvg, "FVG"
    if fvg is not None:
        return fvg, "FVG"
    if ob is not None:
        return ob, "OB"
    return None, ""


def _ltf_confirmation(ctx: PairContext, i: int, direction: str) -> bool:
    """Confirmation on the entry timeframe.

    Requires a displacement-style push in the trade direction among the entry
    bars belonging to this setup bar. When the entry timeframe *is* the setup
    timeframe this collapses to "the setup bar itself confirmed", which is
    weaker -- and is scored honestly as such (it is only worth +5).
    """
    entry_tf = ctx.stack["entry_tf"]
    j = ctx.view.index_at(entry_tf, i)
    if j < 1:
        return False
    disp_cfg = ctx.icfg.get("structure.displacement")
    return displacement_near(ctx.entry_frame, j, disp_cfg, direction)


def _build_targets(ctx: PairContext, i: int, direction: str, entry: float,
                   stop: float, atr_value: float) -> tuple[float, float, float]:
    """Liquidity-based TP1/TP2/TP3 with R-multiple fallbacks.

    TP1 = nearest internal liquidity, TP2 = previous swing, TP3 = external
    (PDH/PDL/PWH/PWL). Where no pool exists at that leg the configured R
    fallback is used, so targets are never silently shrunk to whatever happens
    to be close.
    """
    tcfg = ctx.icfg.get("targets")
    risk = abs(entry - stop)
    fb = tcfg.get("tp_fallback_r", [1.5, 3.0, 5.0])
    mins = tcfg.get("tp_min_r", [1.0, 2.0, 3.0])
    swing_kinds = {"swing_high", "swing_low", "equal_highs", "equal_lows"}
    ext_kinds = MAJOR_POOLS

    # A target must be far enough away to be worth the risk. Without this the
    # "nearest liquidity" is almost always a trivial micro-swing a few pips
    # out, which silently collapses every trade to a sub-1R scalp -- the exact
    # TP-shrinking failure this repo has caught three times. Requiring a
    # minimum R pushes targets FURTHER, which lowers win rate: the honest
    # direction, and the matched-R control in validate.py proves it.
    def _nearest(side_fn, floor_r: float, kinds=None):
        threshold = entry + sign * floor_r * risk
        pool = side_fn(i, threshold, kinds)
        return pool.price if pool else None

    sign = 1.0 if direction == "bullish" else -1.0
    side_fn = ctx.liq.next_pool_above if direction == "bullish" else ctx.liq.next_pool_below

    tp1 = _nearest(side_fn, mins[0]) or entry + sign * fb[0] * risk
    tp2 = _nearest(side_fn, mins[1], swing_kinds) or entry + sign * fb[1] * risk
    tp3 = _nearest(side_fn, mins[2], ext_kinds) or entry + sign * fb[2] * risk

    # Enforce a strictly widening ladder.
    if direction == "bullish":
        tp2 = max(tp2, tp1 + 0.25 * risk)
        tp3 = max(tp3, tp2 + 0.25 * risk)
    else:
        tp2 = min(tp2, tp1 - 0.25 * risk)
        tp3 = min(tp3, tp2 - 0.25 * risk)

    if tcfg.get("mode") == "fixed_rr":
        # Matched-R control mode: one flat target at a fixed multiple.
        rr = float(tcfg.get("fixed_rr", 3.0))
        if direction == "bullish":
            tp1 = tp2 = tp3 = entry + rr * risk
        else:
            tp1 = tp2 = tp3 = entry - rr * risk
    return float(tp1), float(tp2), float(tp3)


def _setup_hash(symbol: str, direction: str, zone_price: float,
                tol: float, bar_time) -> str:
    bucket = round(zone_price / tol) if tol > 0 else zone_price
    raw = f"{symbol}|{direction}|{bucket}|{pd.Timestamp(bar_time).date()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate_signals(ctx: PairContext, cfg,
                     log_rejections: bool = True) -> tuple[list[Signal], list[Rejection]]:
    """Walk the setup timeframe and emit signals + rejections."""
    if not ctx.ok:
        return [], []

    icfg = ctx.icfg
    frame = ctx.setup
    n = len(frame)
    threshold = cfg.score_threshold
    weights = icfg.get("scoring.weights")
    liq_cfg = icfg.get("liquidity")
    max_bars_since_sweep = int(liq_cfg.get("sweep", {}).get("max_bars_since_sweep", 6))
    disp_cfg = icfg.get("structure.displacement")
    pd_cfg = icfg.get("premium_discount")
    stops_cfg = icfg.get("stops")
    tcfg = icfg.get("targets")
    sess_cfg = icfg.get("sessions")
    allowed_sessions = icfg.allowed_sessions
    dedupe_cfg = icfg.get("dedupe")
    entry_valid_bars = int(icfg.get("entry.valid_bars", 8))
    fvg_fill = float(icfg.get("fvg.entry_fill_pct", 0.5))
    spread_pips = icfg.spread_pips
    max_spread = icfg.max_spread_pips

    highs, lows = frame["high"].values, frame["low"].values
    closes = frame["close"].values
    atr_vals = frame["atr"].values
    times = frame.index

    signals: list[Signal] = []
    rejections: list[Rejection] = []
    last_setup_bar: dict[str, int] = {}
    seen_setups: dict[str, int] = {}

    def reject(i, direction, step, reason, score=0.0, state=None):
        if log_rejections:
            rejections.append(Rejection(ctx.symbol, i, times[i], direction, step,
                                        reason, score, session_of(times[i], sess_cfg),
                                        state or {}))

    for i in range(30, n):
        bar_atr = atr_vals[i]
        if not np.isfinite(bar_atr) or bar_atr <= 0:
            continue
        ts = times[i]

        # --- step 1: HTF bias (hard) -----------------------------------
        htf = ctx.htf_bias(i)
        if htf == "neutral":
            continue
        direction = htf
        side = "buy" if direction == "bullish" else "sell"

        # --- step 3-4: sweep -------------------------------------------
        # Checked BEFORE the session gate so the rejection log records real
        # candidate setups rather than every out-of-hours bar.
        sweep = ctx.liq.recent_sweep(i, direction, max_bars_since_sweep)
        if sweep is None:
            continue

        # --- session gate ---------------------------------------------
        ok_sess, sess_reason = is_tradeable(ts, sess_cfg, allowed_sessions)
        if not ok_sess:
            reject(i, direction, "session", sess_reason)
            continue
        sweep_major = sweep.pool.kind in STRONG_POOLS
        pd_pw = sweep.pool.kind in MAJOR_POOLS

        # --- step 5: displacement --------------------------------------
        has_disp = displacement_near(frame, i, disp_cfg, direction)

        # --- step 6: structure event -----------------------------------
        kinds_seen: set[str] = set()
        for j in range(sweep.index, i + 1):
            for event in ctx.events_by_bar.get(j, []):
                if event.direction == direction:
                    kinds_seen.add(event.kind)
        has_bos = "BOS" in kinds_seen
        # MSS outranks CHoCH outranks BOS for the "shift" component.
        struct_kind = next((k for k in ("MSS", "CHoCH", "BOS") if k in kinds_seen), "")
        if not struct_kind:
            reject(i, direction, "structure", "no_structure_event_after_sweep")
            continue
        if not has_disp:
            reject(i, direction, "displacement", "no_displacement_after_sweep")
            continue

        # --- step 7: zone ----------------------------------------------
        ob, fvg = ctx.zones.best_zone(i, direction, closes[i], bar_atr)
        zone, zone_label = _pick_entry_zone(ob, fvg, direction)
        if zone is None:
            reject(i, direction, "zone", "no_valid_ob_or_fvg")
            continue

        # --- step 8: entry (a resting limit -- price must come back) ----
        entry = zone.entry_price(fvg_fill)
        if direction == "bullish" and entry >= closes[i]:
            reject(i, direction, "entry", "zone_not_below_price")
            continue
        if direction == "bearish" and entry <= closes[i]:
            reject(i, direction, "entry", "zone_not_above_price")
            continue

        # --- step 2: premium / discount --------------------------------
        leg_hi, leg_lo = ctx.structural_leg(i)
        pd_state = pdmod.evaluate(entry, leg_hi, leg_lo, pd_cfg)
        vetoed, veto_reason = pdmod.hard_veto(pd_state, direction, pd_cfg)
        if vetoed:
            reject(i, direction, "premium_discount", veto_reason)
            continue
        pd_ok = pdmod.favourable(pd_state, direction)

        # --- stop: structural, beyond the sweep extreme -----------------
        buffer_atr = float(stops_cfg.get("buffer_atr", 0.25))
        if direction == "bullish":
            anchor = min(sweep.extreme, zone.bottom, lows[max(0, i - 3):i + 1].min())
            stop = anchor - buffer_atr * bar_atr
        else:
            anchor = max(sweep.extreme, zone.top, highs[max(0, i - 3):i + 1].max())
            stop = anchor + buffer_atr * bar_atr
        risk_price = abs(entry - stop)
        min_stop = float(stops_cfg.get("min_stop_atr", 0.35)) * bar_atr
        max_stop = float(stops_cfg.get("max_stop_atr", 3.0)) * bar_atr
        if risk_price < min_stop:
            reject(i, direction, "stop", f"stop_too_tight_{risk_price / bar_atr:.2f}atr")
            continue
        if risk_price > max_stop:
            reject(i, direction, "stop", f"stop_too_wide_{risk_price / bar_atr:.2f}atr")
            continue
        # Execution viability: risk must dwarf the round-trip cost, otherwise
        # the spread quietly eats the R-multiple and every target under-delivers.
        cost_price = (spread_pips + float(icfg.get("execution.slippage_pips", 0.2))) * icfg.pip
        min_over_cost = float(stops_cfg.get("min_stop_over_cost", 0.0))
        if min_over_cost > 0 and risk_price < min_over_cost * cost_price:
            reject(i, direction, "cost",
                   f"stop_{risk_price / cost_price:.1f}x_cost<{min_over_cost}x", 0.0)
            continue

        # --- targets ----------------------------------------------------
        tp1, tp2, tp3 = _build_targets(ctx, i, direction, entry, stop, bar_atr)
        sign = 1.0 if direction == "bullish" else -1.0
        rr1 = sign * (tp1 - entry) / risk_price
        rr2 = sign * (tp2 - entry) / risk_price
        rr3 = sign * (tp3 - entry) / risk_price

        # --- step 9: LTF confirmation -----------------------------------
        ltf_ok = _ltf_confirmation(ctx, i, direction)

        # --- step 11: spread --------------------------------------------
        spread_ok = spread_pips <= max_spread
        if not spread_ok:
            reject(i, direction, "spread", f"spread_{spread_pips}>{max_spread}")
            continue

        # --- score -------------------------------------------------------
        # The bias timeframe agreeing is a HARD gate (step 1). The +15 is only
        # earned when the structure timeframe agrees too -- i.e. full "4H+1H
        # bias" alignment per the spec, which makes the component a real
        # discriminator rather than a constant.
        card = score_setup(
            weights=weights, htf_aligned=(ctx.structure_bias(i) == direction),
            structure_event=struct_kind, has_bos=has_bos,
            sweep_kind=sweep.pool.kind, sweep_is_major=sweep_major,
            pd_pw_liquidity=pd_pw, order_block=ob, fvg=fvg,
            pd_favourable=pd_ok, displacement=has_disp,
            ltf_confirmed=ltf_ok, spread_ok=spread_ok,
        )
        score = card.total

        # --- step 10: R:R ------------------------------------------------
        min_rr = float(tcfg.get("min_rr", 2.0))
        if rr2 < min_rr:
            reject(i, direction, "risk_reward", f"rr2_{rr2:.2f}<{min_rr}", score)
            continue

        # --- step 12: score gate ----------------------------------------
        if score < threshold:
            reject(i, direction, "score", f"score_{score:.0f}<{threshold:.0f}", score,
                   {"missing": card.missing(weights)})
            continue

        # --- duplicate-setup protection ----------------------------------
        tol = float(dedupe_cfg.get("same_zone_tolerance_atr", 0.35)) * bar_atr
        setup_id = _setup_hash(ctx.symbol, direction, zone.mid, tol, ts)
        if dedupe_cfg.get("enabled", True):
            cooldown = int(dedupe_cfg.get("cooldown_bars", 8))
            prev = last_setup_bar.get(direction)
            if prev is not None and i - prev < cooldown:
                reject(i, direction, "dedupe", f"cooldown_{i - prev}<{cooldown}", score)
                continue
            if seen_setups.get(setup_id, 0) >= int(dedupe_cfg.get("max_signals_per_setup_id", 1)):
                reject(i, direction, "dedupe", "duplicate_setup_id", score)
                continue

        setup_type = "+".join(
            p for p in ["sweep", struct_kind, "OB" if ob else "", "FVG" if fvg else ""] if p)
        signal = Signal(
            setup_id=setup_id,
            signal_id=hashlib.sha1(f"{setup_id}|{ts}".encode()).hexdigest()[:12],
            symbol=ctx.symbol, direction=direction, side=side, bar_index=i, time=ts,
            entry=float(entry), stop=float(stop), tp1=tp1, tp2=tp2, tp3=tp3,
            risk_price=float(risk_price), rr_tp1=float(rr1), rr_tp2=float(rr2),
            rr_tp3=float(rr3), score=score, scorecard=card,
            session=session_of(ts, sess_cfg), setup_type=setup_type,
            liquidity_type=sweep.pool.kind, htf_bias=htf, structure_event=struct_kind,
            zone_kind=zone_label, atr=float(bar_atr), spread_pips=spread_pips,
            valid_until_bar=i + entry_valid_bars,
        )
        signal.explanation = build_explanation(signal, ctx)
        signals.append(signal)
        last_setup_bar[direction] = i
        seen_setups[setup_id] = seen_setups.get(setup_id, 0) + 1

    return signals, rejections


def build_explanation(sig: Signal, ctx: PairContext) -> dict:
    """The spec's per-signal explanation block."""
    icfg = ctx.icfg
    pip = icfg.pip
    return {
        "pair": sig.symbol,
        "direction": "LONG" if sig.direction == "bullish" else "SHORT",
        "score": round(sig.score, 1),
        "confidence": ("HIGH" if sig.score >= 90 else
                       "MEDIUM" if sig.score >= 80 else "LOW"),
        "htf_bias": sig.htf_bias,
        "liquidity": sig.liquidity_type,
        "structure": sig.structure_event or ("BOS" if "BOS" in sig.setup_type else ""),
        "setup_type": sig.setup_type,
        "zone": sig.zone_kind,
        "session": sig.session,
        "entry": round(sig.entry, 5),
        "stop_loss": round(sig.stop, 5),
        "stop_pips": round(sig.risk_price / pip, 1),
        "tp1": round(sig.tp1, 5),
        "tp2": round(sig.tp2, 5),
        "tp3": round(sig.tp3, 5),
        "rr_tp1": round(sig.rr_tp1, 2),
        "rr_tp2": round(sig.rr_tp2, 2),
        "rr_tp3": round(sig.rr_tp3, 2),
        "risk_pct": icfg.risk_per_trade_pct,
        "spread_pips": sig.spread_pips,
        "reasons": list(sig.scorecard.reasons),
        "time_utc": str(sig.time),
    }
