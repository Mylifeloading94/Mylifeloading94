"""
SMC strategy engine (spec §5) — the four setup families, across three modes.

  A. LIQUIDITY_SWEEP_REVERSAL   liquidity -> sweep -> MSS -> displacement -> FVG -> entry
  B. TREND_CONTINUATION         HTF bias -> liquidity -> BOS -> pullback -> OB/FVG -> entry
  C. BREAKOUT                   consolidation -> liquidity build -> displacement -> BOS -> retest
  D. PREMIUM_DISCOUNT_REVERSAL  HTF range -> premium/discount -> sweep -> MSS -> FVG/OB -> entry

Detection is deliberately sequence-driven, not indicator-driven (spec §16): a
setup only exists when the whole institutional sequence has ALREADY printed.
Nothing here predicts; it confirms.

The same `detect()` entry point is used by the live scanner and by the
backtest. That is not a convenience — it is the reason the published win rates
describe this engine and not a different one.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Sequence

from .candles import PIP, Bar, Series, atr, to_pips
from .config import MODES, ModeSpec, StrategyConfig
from .regime import Regime, classify
from .sessions import SessionInfo, session_at
from .smc import (FVG, Displacement, LiquidityPool, OrderBlock, PremiumDiscount, Structure,
                  Sweep, analyze_structure, detect_sweep, fair_value_gaps, find_displacement,
                  liquidity_pools, order_blocks, premium_discount, swings)

PATTERNS = ("LIQUIDITY_SWEEP_REVERSAL", "TREND_CONTINUATION", "BREAKOUT",
            "PREMIUM_DISCOUNT_REVERSAL")

# A liquidity draw further than this multiple of a target's R floor is treated as
# out of reach for the trade: quoting it would inflate the published R:R.
REACH_CAP = 2.0


# --------------------------------------------------------------------------
# Per-timeframe analysis + multi-timeframe context
# --------------------------------------------------------------------------
@dataclass
class TFAnalysis:
    tf: str
    series: Series
    structure: Structure
    pools: list[LiquidityPool]
    fvgs: list[FVG]
    obs: list[OrderBlock]
    pd: PremiumDiscount
    regime: Regime
    atr: float

    @property
    def bars(self) -> list[Bar]:
        return self.series.bars

    @property
    def price(self) -> float:
        return self.series.last.c if self.series.last else 0.0


def analyze_tf(series: Series, cfg: StrategyConfig, strength: int) -> TFAnalysis:
    bars = series.bars
    st = analyze_structure(bars, strength)
    price = bars[-1].c if bars else 0.0
    return TFAnalysis(
        tf=series.tf, series=series, structure=st,
        pools=liquidity_pools(bars, strength),
        fvgs=fair_value_gaps(bars, min_size_atr=cfg.fvg_min_size_atr),
        obs=order_blocks(bars, disp_mult=cfg.ob_disp_mult),
        pd=premium_discount(st, price),
        regime=classify(bars, st),
        atr=atr(bars[-60:] if len(bars) >= 60 else bars, 14))


@dataclass
class Context:
    mode: ModeSpec
    cfg: StrategyConfig
    analyses: dict[str, TFAnalysis]
    price: float
    ts: int
    session: SessionInfo

    @property
    def htf(self) -> TFAnalysis:
        return self.analyses[self.mode.htf]

    @property
    def mtf(self) -> TFAnalysis:
        return self.analyses[self.mode.mtf]

    @property
    def ltf(self) -> TFAnalysis:
        return self.analyses[self.mode.ltf]

    @property
    def ttf(self) -> TFAnalysis:
        return self.analyses[self.mode.ttf]

    @property
    def htf_bias(self) -> str:
        """Bias only when the two higher timeframes agree; otherwise ranging."""
        h, m = self.htf.structure.trend, self.mtf.structure.trend
        if h == m:
            return h
        if "ranging" in (h, m):
            return h if m == "ranging" else m
        return "conflicted"


def build_context(mode: ModeSpec, series_by_tf: dict[str, Series], cfg: StrategyConfig,
                  price: float | None = None, ts: int | None = None) -> Context | None:
    analyses: dict[str, TFAnalysis] = {}
    for tf in mode.timeframes:
        s = series_by_tf.get(tf)
        if s is None or len(s) < 60:
            return None
        strength = cfg.swing_strength_htf if tf in (mode.htf, mode.mtf) else cfg.swing_strength_ltf
        analyses[tf] = analyze_tf(s, cfg, strength)
    ltf = analyses[mode.ltf]
    p = price if price is not None else ltf.price
    t = ts if ts is not None else (ltf.bars[-1].ts if ltf.bars else 0)
    return Context(mode=mode, cfg=cfg, analyses=analyses, price=p, ts=t, session=session_at(t))


# --------------------------------------------------------------------------
# The detected sequence (shared by all four patterns)
# --------------------------------------------------------------------------
@dataclass
class Sequence:
    direction: str            # "bullish" | "bearish"
    sweep: Sweep
    mss_idx: int              # bar whose close confirmed the structure break
    mss_kind: str             # "MSS" (CHoCH) | "BOS"
    mss_level: float
    displacement: Displacement
    poi_kind: str             # "FVG" | "OB"
    poi_top: float
    poi_bottom: float
    fvg: FVG | None
    ob: OrderBlock | None
    leg_low: float
    leg_high: float
    bars_since_mss: int

    @property
    def poi_mid(self) -> float:
        return (self.poi_top + self.poi_bottom) / 2.0


def _micro_structure_break(bars: Sequence[Bar], j: int, direction: str, strength: int) -> tuple[bool, str, float]:
    """
    Did bar j's CLOSE break the execution-TF structure in `direction`?
    Returns (broke, "MSS"|"BOS", broken_level). MSS = the break reversed the
    prior micro-trend (a change of character); BOS = it extended it.
    """
    hist = bars[max(0, j - 40):j]
    if len(hist) < strength * 2 + 2:
        return False, "", 0.0
    sw = swings(hist, strength)
    prior = analyze_structure(hist, strength).trend
    c = bars[j].c
    if direction == "bullish":
        highs = [s.price for s in sw if s.kind == "high"]
        if not highs:
            return False, "", 0.0
        lvl = highs[-1]
        if c > lvl:
            return True, ("BOS" if prior == "bullish" else "MSS"), lvl
    else:
        lows = [s.price for s in sw if s.kind == "low"]
        if not lows:
            return False, "", 0.0
        lvl = lows[-1]
        if c < lvl:
            return True, ("MSS" if prior != "bearish" else "BOS"), lvl
    return False, "", 0.0


def find_sequences(ltf: TFAnalysis, cfg: StrategyConfig, mode: ModeSpec) -> list[Sequence]:
    """
    Scan the recent window for completed sweep -> MSS/BOS -> displacement -> POI
    sequences. Returns the freshest first. Nothing is emitted until every leg of
    the sequence has closed.
    """
    bars = ltf.bars
    n = len(bars)
    a = ltf.atr
    if n < 60 or a <= 0:
        return []
    out: list[Sequence] = []
    window_start = max(30, n - cfg.sweep_lookback_bars - cfg.mss_within_bars)
    for s_idx in range(n - 2, window_start, -1):
        sweep = detect_sweep(bars, ltf.pools, s_idx, a, cfg.min_sweep_rejection_atr)
        if sweep is None:
            continue
        direction = sweep.direction
        for j in range(s_idx + 1, min(s_idx + 1 + cfg.mss_within_bars, n)):
            broke, kind, level = _micro_structure_break(bars, j, direction, cfg.swing_strength_ltf)
            if not broke:
                continue
            disp = find_displacement(bars, s_idx + 1, j + 1, direction, a,
                                     cfg.displacement_atr, cfg.displacement_body_ratio)
            if disp is None:
                continue

            leg = bars[s_idx:j + 1]
            leg_low, leg_high = min(b.l for b in leg), max(b.h for b in leg)

            fvg = _pick_fvg(ltf.fvgs, direction, disp.idx, j)
            ob = _pick_ob(ltf.obs, direction, disp.idx)
            if fvg is not None:
                poi_kind, top, bottom = "FVG", fvg.top, fvg.bottom
            elif ob is not None:
                poi_kind, top, bottom = "OB", ob.top, ob.bottom
            else:
                continue                       # spec: entry must come from an FVG or OB

            bars_since = n - 1 - j
            if bars_since > mode.max_age_bars:
                continue
            out.append(Sequence(direction, sweep, j, kind, level, disp, poi_kind, top, bottom,
                                fvg, ob, leg_low, leg_high, bars_since))
            break                              # one sequence per sweep
    return out


def _pick_fvg(fvgs: list[FVG], direction: str, disp_idx: int, mss_idx: int) -> FVG | None:
    """The imbalance printed by this displacement, still substantially open."""
    cands = [g for g in fvgs
             if g.direction == direction and disp_idx <= g.idx <= mss_idx + 2 and g.filled_pct < 0.75]
    if not cands:
        return None
    return max(cands, key=lambda g: (g.size, g.idx))


def _pick_ob(obs: list[OrderBlock], direction: str, disp_idx: int) -> OrderBlock | None:
    cands = [o for o in obs if o.direction == direction and disp_idx - 6 <= o.idx <= disp_idx]
    if not cands:
        return None
    return max(cands, key=lambda o: (o.impulse_atr, o.idx))


# --------------------------------------------------------------------------
# Pattern classification
# --------------------------------------------------------------------------
def _is_consolidation(ltf: TFAnalysis, cfg: StrategyConfig, before_idx: int) -> tuple[bool, float, float]:
    """Was price coiled in a tight range immediately before the break?"""
    lo_i = max(0, before_idx - cfg.consolidation_bars)
    win = ltf.bars[lo_i:before_idx]
    if len(win) < max(8, cfg.consolidation_bars // 2) or ltf.atr <= 0:
        return False, 0.0, 0.0
    hi, lo = max(b.h for b in win), min(b.l for b in win)
    return ((hi - lo) <= cfg.consolidation_max_atr * ltf.atr), hi, lo


def classify_pattern(ctx: Context, seq: Sequence) -> str:
    d = seq.direction
    htf_pd = ctx.htf.pd
    swept_major = seq.sweep.pool is not None and (
        seq.sweep.pool.strength >= 2 or seq.sweep.pool.kind in
        ("pdh", "pdl", "asia_high", "asia_low", "equal_highs", "equal_lows"))

    # Ordered by how specific the structural precondition is, so a sequence that
    # satisfies several families lands in the family that describes it best.

    # C: expansion out of a measured compression — the rarest precondition
    coiled, _, _ = _is_consolidation(ctx.ltf, ctx.cfg, seq.sweep.idx)
    if coiled and seq.displacement.size_atr >= ctx.cfg.displacement_atr * 1.2:
        return "BREAKOUT"

    # B: HTF-aligned continuation break (BOS, not a change of character)
    if ctx.htf_bias == d and seq.mss_kind == "BOS":
        return "TREND_CONTINUATION"

    # D: at a HTF range extreme, taking the range's own liquidity
    at_extreme = (d == "bullish" and htf_pd.position <= 0.32) or \
                 (d == "bearish" and htf_pd.position >= 0.68)
    if at_extreme and swept_major:
        return "PREMIUM_DISCOUNT_REVERSAL"

    return "LIQUIDITY_SWEEP_REVERSAL"


# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------
@dataclass
class Setup:
    # identity
    id: str = ""
    signal_ts: int = 0                 # bar ts the sequence completed on
    created_ts: float = 0.0            # wall-clock when first published
    mode: str = ""
    pattern: str = ""
    direction: str = ""                # BUY | SELL

    # prices
    price_at_signal: float = 0.0
    entry: float = 0.0
    entry_low: float = 0.0
    entry_high: float = 0.0
    entry_type: str = "LIMIT"          # MARKET | LIMIT
    entry_state: str = "ARMED"         # ARMED (price in zone) | PENDING (awaiting retrace)
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float | None = None

    # geometry
    risk: float = 0.0
    rr: float = 0.0                    # to TP2 — the headline R:R
    rr_tp1: float = 0.0
    rr_tp3: float | None = None
    sl_pips: float = 0.0
    tp1_pips: float = 0.0
    tp2_pips: float = 0.0
    tp3_pips: float | None = None

    # scoring
    score: float = 0.0
    grade: str = "INVALID"
    features: dict = field(default_factory=dict)
    component_scores: dict = field(default_factory=dict)
    confluences: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    # probability (filled by stats.py — never invented here)
    probability: float | None = None
    sample_size: int = 0
    profit_factor: float | None = None
    avg_rr: float | None = None
    prob_bucket: str = ""
    prob_note: str = "no validated sample"
    history_flag: str = "UNVALIDATED"   # UNVALIDATED | VALIDATED_STRONG/WEAK/NEGATIVE

    # state
    status: str = "VALID"              # VALID | INVALID
    invalid_reason: str = ""
    # context
    session: str = ""
    killzone: str | None = None
    htf_bias: str = ""
    regime: str = ""
    volatility: str = ""
    data_quality: str = ""
    data_source: str = ""
    anchors: dict = field(default_factory=dict)

    @property
    def side(self) -> int:
        return 1 if self.direction == "BUY" else -1

    def key(self) -> tuple[str, str, str, str]:
        """Stats bucket: (pattern, mode, grade, direction)."""
        return (self.pattern, self.mode, self.grade, self.direction)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["anchors"] = {k: v for k, v in self.anchors.items() if k != "_ctx"}
        return d


def _mk_id(mode: str, pattern: str, direction: str, sweep_ts: int, mss_ts: int,
           zone_mid: float) -> str:
    """
    Identify the SEQUENCE, never the live price. A market entry re-prices every
    scan, so hashing the entry would mint a new setup id (and a new journal
    record) every 60 seconds for what is one and the same opportunity.
    """
    raw = f"{mode}|{pattern}|{direction}|{sweep_ts}|{mss_ts}|{zone_mid:.2f}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _targets(direction: str, entry: float, risk: float, pools: list[LiquidityPool],
             tp_r: tuple[float, ...], a: float, htf_pd: PremiumDiscount) -> list[float | None]:
    """
    Targets are DRAW-ON-LIQUIDITY first, R-multiple floors second: aim just
    short of the opposing pool institutions are actually reaching for, but never
    accept less than the mode's R floor — and never quote a level so far away
    that the R:R flatters the setup. A draw beyond REACH_CAP x the floor is not
    a level this trade can be judged on, so the floor is used instead.

    TP3 is published only when a genuine draw sits in its band (spec §7:
    "exact price when applicable"), never as a padded multiple.
    """
    sign = 1 if direction == "bullish" else -1
    want_side = "high" if direction == "bullish" else "low"
    buf = 0.10 * a
    draws = sorted(
        {(p.price - buf * sign) for p in pools
         if p.side == want_side and not p.swept and (p.price - entry) * sign > 0},
        key=lambda x: (x - entry) * sign)
    extreme = htf_pd.high if direction == "bullish" else htf_pd.low
    if (extreme - entry) * sign > 0:
        draws.append(extreme - buf * sign)

    out: list[float | None] = []
    used = 0.0
    for i, r in enumerate(tp_r):
        lo_d, hi_d = r * risk, r * REACH_CAP * risk
        cand = next((d for d in draws
                     if lo_d <= (d - entry) * sign <= hi_d and (d - entry) * sign > used), None)
        if cand is None and i == 2:
            out.append(None)
            continue
        px = cand if cand is not None else entry + sign * r * risk
        used = (px - entry) * sign
        out.append(round(px, 2))
    return out


def build_setup(ctx: Context, seq: Sequence, pattern: str, feed_quality: str = "",
                feed_source: str = "") -> Setup | None:
    mode = ctx.mode
    a = ctx.ltf.atr
    direction = seq.direction
    dir_label = "BUY" if direction == "bullish" else "SELL"
    sign = 1 if direction == "bullish" else -1
    price = ctx.price

    # -- entry zone (the POI) ---------------------------------------------
    zone_hi, zone_lo = max(seq.poi_top, seq.poi_bottom), min(seq.poi_top, seq.poi_bottom)
    tol = mode.entry_tolerance_atr * a
    if zone_lo - tol <= price <= zone_hi + tol:
        entry_type, entry_state, entry = "MARKET", "ARMED", price
    elif (direction == "bullish" and price > zone_hi) or (direction == "bearish" and price < zone_lo):
        entry_type, entry_state = "LIMIT", "PENDING"
        entry = (zone_hi + zone_lo) / 2.0
    else:
        # price has traded clean through the zone against us — the setup is spent
        return None

    # -- stop ---------------------------------------------------------------
    if direction == "bullish":
        sl = min(seq.sweep.extreme, zone_lo, seq.leg_low) - mode.sl_buffer_atr * a
    else:
        sl = max(seq.sweep.extreme, zone_hi, seq.leg_high) + mode.sl_buffer_atr * a
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    sl_pips = to_pips(risk)
    if sl_pips < mode.min_sl_pips or sl_pips > mode.max_sl_pips:
        return None

    tps = _targets(direction, entry, risk, ctx.htf.pools + ctx.ltf.pools, mode.tp_r, a, ctx.htf.pd)
    tp1, tp2, tp3 = tps[0], tps[1], tps[2]
    if tp1 is None or tp2 is None:
        return None
    rr = abs(tp2 - entry) / risk

    s = Setup(
        id=_mk_id(mode.name, pattern, dir_label, seq.sweep.ts,
                  ctx.ltf.bars[seq.mss_idx].ts, (zone_hi + zone_lo) / 2.0),
        signal_ts=ctx.ltf.bars[seq.mss_idx].ts, mode=mode.name, pattern=pattern,
        direction=dir_label, price_at_signal=round(price, 2),
        entry=round(entry, 2), entry_low=round(zone_lo, 2), entry_high=round(zone_hi, 2),
        entry_type=entry_type, entry_state=entry_state,
        sl=round(sl, 2), tp1=tp1, tp2=tp2, tp3=tp3,
        risk=round(risk, 2), rr=round(rr, 2), rr_tp1=round(abs(tp1 - entry) / risk, 2),
        rr_tp3=round(abs(tp3 - entry) / risk, 2) if tp3 else None,
        sl_pips=round(sl_pips, 1), tp1_pips=round(to_pips(tp1 - entry), 1),
        tp2_pips=round(to_pips(tp2 - entry), 1),
        tp3_pips=round(to_pips(tp3 - entry), 1) if tp3 else None,
        session=ctx.session.name, killzone=ctx.session.killzone, htf_bias=ctx.htf_bias,
        regime=ctx.ltf.regime.state, volatility=ctx.ltf.regime.volatility,
        data_quality=feed_quality, data_source=feed_source)

    s.features = extract_features(ctx, seq, s)
    s.anchors = {
        "sweep": {"ts": seq.sweep.ts, "price": round(seq.sweep.extreme, 2),
                  "pool": seq.sweep.pool.kind if seq.sweep.pool else "range_extreme",
                  "pool_price": round(seq.sweep.pool.price, 2) if seq.sweep.pool else None},
        "mss": {"ts": ctx.ltf.bars[seq.mss_idx].ts, "kind": seq.mss_kind,
                "level": round(seq.mss_level, 2)},
        "displacement": {"ts": seq.displacement.ts, "atr": round(seq.displacement.size_atr, 2)},
        "poi": {"kind": seq.poi_kind, "top": round(zone_hi, 2), "bottom": round(zone_lo, 2)},
        "htf_range": {"high": round(ctx.htf.pd.high, 2), "low": round(ctx.htf.pd.low, 2),
                      "eq": round(ctx.htf.pd.equilibrium, 2), "zone": ctx.htf.pd.zone},
        "ltf_tf": mode.ltf, "htf_tf": mode.htf,
    }
    return s


def extract_features(ctx: Context, seq: Sequence, s: Setup) -> dict:
    """Raw, objective facts about the setup. grading.py turns these into a score."""
    d = seq.direction
    ltf, htf, mtf = ctx.ltf, ctx.htf, ctx.mtf
    pd_htf, pd_ltf = htf.pd, ltf.pd
    pool = seq.sweep.pool

    entry_pd = PremiumDiscount(pd_htf.high, pd_htf.low, s.entry)
    fvg = seq.fvg
    ob = seq.ob

    return {
        "htf_trend": htf.structure.trend,
        "mtf_trend": mtf.structure.trend,
        "direction": d,
        "htf_aligned": htf.structure.trend == d,
        "mtf_aligned": mtf.structure.trend == d,
        "htf_conflicted": ctx.htf_bias == "conflicted",
        "pool_kind": pool.kind if pool else "range_extreme",
        "pool_strength": pool.strength if pool else 1,
        "pool_is_session": bool(pool and pool.kind in ("pdh", "pdl", "asia_high", "asia_low")),
        "pool_is_equal": bool(pool and pool.kind in ("equal_highs", "equal_lows")),
        "sweep_rejection_atr": round(seq.sweep.displacement_back, 2),
        "ltf_structure_trend": ltf.structure.trend,
        "ltf_structure_events": len(ltf.structure.events),
        "mss_kind": seq.mss_kind,
        "mss_displacement_atr": round(seq.displacement.size_atr, 2),
        "mss_body_ratio": round(seq.displacement.body_ratio, 2),
        "bars_since_mss": seq.bars_since_mss,
        "poi_kind": seq.poi_kind,
        "has_fvg": fvg is not None,
        "fvg_fill_pct": round(fvg.filled_pct, 2) if fvg else None,
        "fvg_size_atr": round(fvg.size / ltf.atr, 2) if fvg and ltf.atr else None,
        "has_ob": ob is not None,
        "ob_mitigated": bool(ob.mitigated) if ob else None,
        "ob_impulse_atr": round(ob.impulse_atr, 2) if ob else None,
        "htf_pd_zone": pd_htf.zone,
        "htf_pd_position": round(pd_htf.position, 3),
        "entry_pd_position": round(entry_pd.position, 3),
        "entry_pd_favourable": entry_pd.favourable(d),
        "entry_in_ote": entry_pd.in_ote(d, s.entry),
        "ltf_pd_position": round(pd_ltf.position, 3),
        "session": ctx.session.name,
        "killzone": ctx.session.killzone,
        "is_prime_killzone": ctx.session.is_prime,
        "regime": ltf.regime.state,
        "regime_tradeable": ltf.regime.tradeable,
        "volatility": ltf.regime.volatility,
        "atr_pctile": ltf.regime.atr_pctile,
        "rr": s.rr,
        "sl_pips": s.sl_pips,
        "entry_state": s.entry_state,
    }


def detect(ctx: Context, feed_quality: str = "", feed_source: str = "") -> list[Setup]:
    """All candidate setups for one mode, freshest sequence first, un-graded."""
    out: list[Setup] = []
    seen: set[tuple] = set()
    for seq in find_sequences(ctx.ltf, ctx.cfg, ctx.mode):
        pattern = classify_pattern(ctx, seq)
        s = build_setup(ctx, seq, pattern, feed_quality, feed_source)
        if s is None:
            continue
        k = (s.direction, s.pattern, round(s.entry, 1))
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out
