"""
Pure Smart-Money-Concepts engine for XAUUSD.

No broker, no network, no third-party packages — every function here takes
plain bar dicts ({"t","o","h","l","c"}) and returns plain data, so the whole
strategy is unit-testable and backtestable without a connection.

Implements section 1-3 and 5 of the strategy document:
  H4 bias -> H1 structure/CHoCH -> M15 sweep + CHoCH + OB/FVG in discount
  -> M5 confirmation -> graded setup (A+ / A / B / C).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

Bar = Dict[str, float]


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
def normalize_bars(raw: List[Any]) -> List[Bar]:
    """Accept TradeLocker barDetails (dicts or [t,o,h,l,c,v] lists)."""
    out: List[Bar] = []
    for b in raw or []:
        try:
            if isinstance(b, dict):
                out.append({
                    "t": float(b.get("t", b.get("time", 0)) or 0),
                    "o": float(b["o"]), "h": float(b["h"]),
                    "l": float(b["l"]), "c": float(b["c"]),
                })
            elif isinstance(b, (list, tuple)) and len(b) >= 5:
                out.append({"t": float(b[0]), "o": float(b[1]), "h": float(b[2]),
                            "l": float(b[3]), "c": float(b[4])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def atr(bars: List[Bar], period: int = 14) -> float:
    """Wilder-style simple ATR over the last `period` completed bars."""
    if len(bars) < 2:
        return 0.0
    window = bars[-(period + 1):]
    trs = []
    for prev, cur in zip(window, window[1:]):
        trs.append(max(cur["h"] - cur["l"],
                       abs(cur["h"] - prev["c"]),
                       abs(cur["l"] - prev["c"])))
    return sum(trs) / len(trs) if trs else 0.0


def is_swing_high(bars: List[Bar], i: int, strength: int) -> bool:
    if i - strength < 0 or i + strength >= len(bars):
        return False
    h = bars[i]["h"]
    for k in range(i - strength, i + strength + 1):
        if k != i and bars[k]["h"] >= h:
            return False
    return True


def is_swing_low(bars: List[Bar], i: int, strength: int) -> bool:
    if i - strength < 0 or i + strength >= len(bars):
        return False
    l = bars[i]["l"]
    for k in range(i - strength, i + strength + 1):
        if k != i and bars[k]["l"] <= l:
            return False
    return True


def swings(bars: List[Bar], strength: int = 2) -> List[Dict[str, Any]]:
    """Confirmed fractal swings. A swing at i is only *known* at i+strength."""
    out = []
    for i in range(strength, len(bars) - strength):
        if is_swing_high(bars, i, strength):
            out.append({"idx": i, "price": bars[i]["h"], "kind": "high",
                        "confirmed_at": i + strength})
        if is_swing_low(bars, i, strength):
            out.append({"idx": i, "price": bars[i]["l"], "kind": "low",
                        "confirmed_at": i + strength})
    return sorted(out, key=lambda s: s["idx"])


# ---------------------------------------------------------------------------
# Market structure: BOS / CHoCH state machine
# ---------------------------------------------------------------------------
def structure_events(bars: List[Bar], strength: int = 2) -> List[Dict[str, Any]]:
    """
    Walk the series forward and emit BOS / CHoCH events.

    A break is a CLOSE through the most recent confirmed swing. Breaking with
    the prevailing trend = BOS (continuation); breaking against it = CHoCH
    (change of character). No look-ahead: a fractal at index i only becomes
    usable at bar i+strength.
    """
    n = len(bars)
    events: List[Dict[str, Any]] = []
    trend: Optional[str] = None
    hi: Optional[tuple] = None   # (idx, price) unbroken confirmed swing high
    lo: Optional[tuple] = None

    for j in range(strength, n):
        i = j - strength                      # fractal that just became visible
        if is_swing_high(bars, i, strength):
            hi = (i, bars[i]["h"])
        if is_swing_low(bars, i, strength):
            lo = (i, bars[i]["l"])

        c = bars[j]["c"]
        if hi is not None and c > hi[1]:
            kind = "CHoCH" if trend == "bear" else "BOS"
            events.append({"idx": j, "kind": kind, "dir": "bull",
                           "level": hi[1], "ref_idx": hi[0], "t": bars[j].get("t")})
            trend = "bull"
            seg = bars[hi[0]:j + 1]
            k = min(range(len(seg)), key=lambda x: seg[x]["l"])
            lo = (hi[0] + k, seg[k]["l"])     # new protected low
            hi = None
        elif lo is not None and c < lo[1]:
            kind = "CHoCH" if trend == "bull" else "BOS"
            events.append({"idx": j, "kind": kind, "dir": "bear",
                           "level": lo[1], "ref_idx": lo[0], "t": bars[j].get("t")})
            trend = "bear"
            seg = bars[lo[0]:j + 1]
            k = max(range(len(seg)), key=lambda x: seg[x]["h"])
            hi = (lo[0] + k, seg[k]["h"])     # new protected high
            lo = None
    return events


def bias(bars: List[Bar], strength: int = 2) -> str:
    """'bullish' / 'bearish' / 'none' from the last structure event."""
    ev = structure_events(bars, strength)
    if not ev:
        return "none"
    return "bullish" if ev[-1]["dir"] == "bull" else "bearish"


def last_event(bars: List[Bar], direction: str, kinds=("CHoCH", "BOS"),
               strength: int = 2, within: int = 30) -> Optional[Dict[str, Any]]:
    """Most recent BOS/CHoCH in `direction` inside the last `within` bars."""
    want = "bull" if direction == "bullish" else "bear"
    n = len(bars)
    for e in reversed(structure_events(bars, strength)):
        if e["dir"] == want and e["kind"] in kinds and n - 1 - e["idx"] <= within:
            return e
    return None


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------
def find_sweep(bars: List[Bar], direction: str, lookback: int = 20,
               recent: int = 3) -> Optional[Dict[str, Any]]:
    """
    Liquidity grab in the last `recent` closed bars: price takes the prior
    `lookback`-bar extreme and CLOSES back inside it (stop hunt, not a break).

    direction 'bullish' -> sweep of a previous LOW.
    """
    n = len(bars)
    if n < lookback + recent + 2:
        return None
    best = None
    for idx in range(n - recent, n):
        pool = bars[idx - lookback:idx]
        if not pool:
            continue
        c = bars[idx]
        if direction == "bullish":
            level = min(b["l"] for b in pool)
            if c["l"] < level and c["c"] > level:
                pen = level - c["l"]
                best = {"idx": idx, "level": level, "extreme": c["l"],
                        "penetration": pen, "bars_ago": n - 1 - idx}
        else:
            level = max(b["h"] for b in pool)
            if c["h"] > level and c["c"] < level:
                pen = c["h"] - level
                best = {"idx": idx, "level": level, "extreme": c["h"],
                        "penetration": pen, "bars_ago": n - 1 - idx}
    return best


def equal_levels(bars: List[Bar], direction: str, tolerance: float,
                 lookback: int = 40) -> bool:
    """True when a cluster of equal highs/lows (obvious liquidity) exists."""
    w = bars[-lookback:]
    if len(w) < 6:
        return False
    vals = [b["h"] for b in w] if direction == "bearish" else [b["l"] for b in w]
    ref = max(vals) if direction == "bearish" else min(vals)
    return sum(1 for v in vals if abs(v - ref) <= tolerance) >= 2


def liquidity_targets(bars: List[Bar], direction: str, price: float,
                      strength: int = 2, lookback: int = 80) -> List[float]:
    """Swing highs above (for longs) / lows below (for shorts), nearest first."""
    w = bars[-lookback:]
    out = []
    for s in swings(w, strength):
        if direction == "bullish" and s["kind"] == "high" and s["price"] > price:
            out.append(s["price"])
        if direction == "bearish" and s["kind"] == "low" and s["price"] < price:
            out.append(s["price"])
    out = sorted(set(out), reverse=(direction == "bearish"))
    return out


# ---------------------------------------------------------------------------
# Zones: order blocks and fair value gaps
# ---------------------------------------------------------------------------
def find_order_block(bars: List[Bar], direction: str, impulse_idx: int,
                     max_back: int = 12) -> Optional[Dict[str, Any]]:
    """
    Last opposite-colour candle before the impulse that broke structure.
    Zone = that candle's full range (wick to wick).
    """
    start = max(0, impulse_idx - max_back)
    for i in range(impulse_idx - 1, start - 1, -1):
        b = bars[i]
        down = b["c"] < b["o"]
        if (direction == "bullish" and down) or (direction == "bearish" and not down):
            return {"type": "OB", "idx": i, "low": b["l"], "high": b["h"],
                    "top": b["h"] if direction == "bullish" else b["h"],
                    "bottom": b["l"]}
    return None


def find_fvg(bars: List[Bar], direction: str, impulse_idx: int,
             span: int = 6) -> Optional[Dict[str, Any]]:
    """
    Three-candle imbalance inside/around the impulse leg.
    Bullish FVG: high[i-1] < low[i+1]  ->  gap (high[i-1], low[i+1]).
    Returns the gap nearest the impulse (freshest).
    """
    lo_i = max(1, impulse_idx - span)
    hi_i = min(len(bars) - 2, impulse_idx + 1)
    found = None
    for i in range(lo_i, hi_i + 1):
        a, c = bars[i - 1], bars[i + 1]
        if direction == "bullish" and a["h"] < c["l"]:
            found = {"type": "FVG", "idx": i, "low": a["h"], "high": c["l"],
                     "top": c["l"], "bottom": a["h"]}
        if direction == "bearish" and a["l"] > c["h"]:
            found = {"type": "FVG", "idx": i, "low": c["h"], "high": a["l"],
                     "top": a["l"], "bottom": c["h"]}
    return found


def fib_position(price: float, low: float, high: float) -> float:
    """0.0 at the swing low, 1.0 at the swing high."""
    if high <= low:
        return 0.5
    return (price - low) / (high - low)


def retrace_depth(price: float, low: float, high: float, direction: str) -> float:
    """How deep into the impulse leg the price sits (1.0 = full retrace)."""
    if high <= low:
        return 0.0
    if direction == "bullish":
        return (high - price) / (high - low)
    return (price - low) / (high - low)


# ---------------------------------------------------------------------------
# M5 confirmation
# ---------------------------------------------------------------------------
def m5_confirmation(bars: List[Bar], direction: str, zone: Dict[str, float],
                    strength: int = 2, window: int = 12) -> Optional[str]:
    """
    Price must have TOUCHED the zone in the recent window and then printed a
    rejection candle (engulfing / hammer-pin) or a 5M BOS in-direction.
    Returns the trigger name, or None.
    """
    if len(bars) < window + strength * 2 + 2:
        return None
    w = bars[-window:]
    touched = any(b["l"] <= zone["top"] for b in w) if direction == "bullish" \
        else any(b["h"] >= zone["bottom"] for b in w)
    if not touched:
        return None

    prev, last = bars[-2], bars[-1]
    rng = max(last["h"] - last["l"], 1e-9)
    body = abs(last["c"] - last["o"])
    upper = last["h"] - max(last["o"], last["c"])
    lower = min(last["o"], last["c"]) - last["l"]

    if direction == "bullish":
        engulf = (last["c"] > last["o"] and prev["c"] < prev["o"]
                  and last["c"] >= prev["o"] and last["o"] <= prev["c"])
        hammer = (lower >= 2 * body and lower >= rng * 0.5 and last["c"] > last["o"])
        if engulf:
            return "M5 bullish engulfing"
        if hammer:
            return "M5 hammer rejection"
        ev = structure_events(bars[-(window + strength * 6):], strength)
        if ev and ev[-1]["dir"] == "bull" and ev[-1]["idx"] >= len(bars[-(window + strength * 6):]) - 3:
            return "M5 BOS"
    else:
        engulf = (last["c"] < last["o"] and prev["c"] > prev["o"]
                  and last["c"] <= prev["o"] and last["o"] >= prev["c"])
        star = (upper >= 2 * body and upper >= rng * 0.5 and last["c"] < last["o"])
        if engulf:
            return "M5 bearish engulfing"
        if star:
            return "M5 shooting-star rejection"
        ev = structure_events(bars[-(window + strength * 6):], strength)
        if ev and ev[-1]["dir"] == "bear" and ev[-1]["idx"] >= len(bars[-(window + strength * 6):]) - 3:
            return "M5 BOS"
    return None


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
@dataclass
class Setup:
    symbol: str
    direction: str                  # "bullish" | "bearish"
    grade: str                      # "A+" | "A" | "B" | "C"
    entry: float
    sl: float
    tp1: float
    tp2: float
    risk_usd_per_lot: float
    sl_pips: float
    rr_tp1: float
    rr_tp2: float
    zone_type: str
    zone_top: float
    zone_bottom: float
    fib_pos: float                  # premium/discount position of the entry
    retrace: float                  # depth into the impulse leg
    sweep_level: float
    atr_m15: float
    reasons: List[str] = field(default_factory=list)
    rejected: Optional[str] = None

    @property
    def side(self) -> str:
        return "buy" if self.direction == "bullish" else "sell"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _grade(h4_aligned: bool, h1_choch: bool, m15_choch: bool, swept: bool,
           major_liquidity: bool, deep_ote: bool, m5_ok: bool) -> str:
    """Section 5 of the strategy document."""
    if not m5_ok:
        return "C"
    if h4_aligned and h1_choch and swept and major_liquidity and deep_ote and m5_ok:
        return "A+"
    if h4_aligned and (m15_choch or h1_choch) and swept and m5_ok:
        return "A"
    if (m15_choch or swept) and m5_ok:
        return "B"
    return "C"


def analyze(symbol: str, h4: List[Bar], h1: List[Bar], m15: List[Bar],
            m5: List[Bar], cfg) -> Optional[Setup]:
    """
    Run the full top-down sequence. Returns a Setup (possibly graded "C" with
    `rejected` set, for logging) or None when there is nothing to look at.
    """
    if len(h4) < 30 or len(h1) < 40 or len(m15) < 60 or len(m5) < 40:
        return None

    a15 = atr(m15, 14)
    if a15 <= 0:
        return None

    h4_bias = bias(h4, cfg.swing_strength_htf)
    h1_bias = bias(h1, cfg.swing_strength_htf)

    candidates = []
    for direction in ("bullish", "bearish"):
        r = _analyze_direction(symbol, direction, h4_bias, h1_bias,
                               h1, m15, m5, a15, cfg)
        if r is not None:
            candidates.append(r)
    if not candidates:
        return None
    # Prefer the best grade, then the best R:R
    candidates.sort(key=lambda s: (-_grade_rank(s.grade), -s.rr_tp2))
    return candidates[0]


def _grade_rank(g: str) -> int:
    order = {"C": 0, "B": 1, "A": 2, "A+": 3}
    return order.get(g, 0)


def _analyze_direction(symbol, direction, h4_bias, h1_bias, h1, m15, m5,
                       a15, cfg) -> Optional[Setup]:
    sign = 1 if direction == "bullish" else -1
    reasons: List[str] = []

    # --- 1. H4 bias -------------------------------------------------------
    h4_aligned = (h4_bias == direction)
    h1_choch_ev = last_event(h1, direction, ("CHoCH",),
                             cfg.swing_strength_htf, within=20)
    h1_bos_ev = last_event(h1, direction, ("BOS", "CHoCH"),
                           cfg.swing_strength_htf, within=20)
    if not h4_aligned and h1_choch_ev is None:
        # Counter-trend is only allowed on a fresh H1 CHoCH (section 2.1)
        return None
    if h4_aligned:
        reasons.append(f"H4 bias {h4_bias}")
    if h1_choch_ev is not None:
        reasons.append("H1 CHoCH")
    elif h1_bos_ev is not None:
        reasons.append("H1 BOS")

    # --- 2. M15 liquidity sweep ------------------------------------------
    sweep = find_sweep(m15, direction, cfg.sweep_lookback, cfg.sweep_recent_bars)
    if sweep is None:
        # A sweep is mandatory for A/A+; B needs at least M15 structure
        sweep = find_sweep(m15, direction, cfg.sweep_lookback,
                           cfg.sweep_recent_bars + 3)
    swept = sweep is not None
    if swept:
        reasons.append(f"M15 sweep of {sweep['level']:.2f}")

    # --- 3. M15 CHoCH / BOS after the sweep -------------------------------
    m15_ev = last_event(m15, direction, ("CHoCH", "BOS"),
                        cfg.swing_strength_ltf, within=cfg.zone_max_age_bars + 6)
    if m15_ev is None:
        return None
    if swept and m15_ev["idx"] < sweep["idx"]:
        return None                       # shift must come AFTER the grab
    m15_choch = m15_ev["kind"] == "CHoCH"
    reasons.append(f"M15 {m15_ev['kind']}")

    # --- 4. Zone: OB or FVG inside the impulse leg ------------------------
    impulse_idx = m15_ev["idx"]
    ob = find_order_block(m15, direction, impulse_idx)
    fvg = find_fvg(m15, direction, impulse_idx)
    zone = ob or fvg
    if zone is None:
        return None
    if fvg is not None and ob is not None:
        # Prefer the zone that keeps the entry deeper in discount/premium
        zone = ob if (direction == "bullish" and ob["top"] <= fvg["top"]) or \
                     (direction == "bearish" and ob["bottom"] >= fvg["bottom"]) else fvg
    if len(m15) - 1 - zone["idx"] > cfg.zone_max_age_bars + 8:
        return None                       # stale zone
    reasons.append(f"{zone['type']} zone {zone['bottom']:.2f}-{zone['top']:.2f}")

    # --- 5. Premium / discount -------------------------------------------
    leg_start = sweep["idx"] if swept else max(0, impulse_idx - 20)
    leg = m15[leg_start:impulse_idx + 1]
    if len(leg) < 3:
        return None
    leg_low = min(b["l"] for b in leg)
    leg_high = max(b["h"] for b in leg)
    entry = zone["top"] if direction == "bullish" else zone["bottom"]
    fpos = fib_position(entry, leg_low, leg_high)
    if direction == "bullish" and fpos >= cfg.discount_max:
        return None                       # not in discount
    if direction == "bearish" and fpos <= (1.0 - cfg.discount_max):
        return None                       # not in premium
    depth = retrace_depth(entry, leg_low, leg_high, direction)
    reasons.append(f"{'discount' if direction=='bullish' else 'premium'} "
                   f"{fpos*100:.0f}% / retrace {depth:.2f}")

    # --- 6. M5 confirmation ----------------------------------------------
    trigger = m5_confirmation(m5, direction, zone, cfg.swing_strength_ltf)
    if trigger is None:
        return None
    reasons.append(trigger)

    # --- 7. Stop loss -----------------------------------------------------
    buffer = max(cfg.sl_buffer_pips, cfg.sl_atr_mult * a15)
    if direction == "bullish":
        anchor = min(zone["bottom"], sweep["extreme"] if swept else zone["bottom"])
        sl = anchor - buffer
    else:
        anchor = max(zone["top"], sweep["extreme"] if swept else zone["top"])
        sl = anchor + buffer
    risk = abs(entry - sl)
    if risk < cfg.min_sl_pips or risk > cfg.max_sl_pips:
        return None

    # --- 8. Targets -------------------------------------------------------
    tp1 = entry + sign * risk * cfg.tp1_r
    pools = liquidity_targets(m15, direction, entry, cfg.swing_strength_ltf)
    if cfg.require_dol_room:
        # "Draw on liquidity": there must be a pool far enough away to pay for
        # the risk. Minor pullback highs between entry and target are normal
        # and are NOT treated as blockers — the furthest reachable pool is what
        # defines the trip.
        if not pools:
            return None
        target_pool = max(pools) if direction == "bullish" else min(pools)
        room_r = abs(target_pool - entry) / risk if risk else 0
        if room_r < cfg.min_rr:
            return None                   # no paid trip to liquidity
        reasons.append(f"DOL {target_pool:.2f} ({room_r:.1f}R room)")
    tp2 = entry + sign * risk * cfg.tp2_r
    for p in pools:
        r_mult = abs(p - entry) / risk if risk else 0
        if cfg.tp2_r <= r_mult <= cfg.tp2_r_max:
            tp2 = p
            break

    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk
    if rr1 < cfg.min_rr:
        return None

    # --- 9. Grade ---------------------------------------------------------
    # Equal highs/lows must exist BEFORE the raid — that is the pool
    # the sweep harvested, not the sweep candle itself.
    pre_sweep = m15[:sweep["idx"]] if swept else []
    major_liq = swept and equal_levels(pre_sweep, direction, a15 * 0.15, 40)
    deep_ote = depth >= cfg.ote_aplus
    grade = _grade(h4_aligned, h1_choch_ev is not None, m15_choch, swept,
                   major_liq, deep_ote, True)

    return Setup(
        symbol=symbol, direction=direction, grade=grade,
        entry=round(entry, 2), sl=round(sl, 2),
        tp1=round(tp1, 2), tp2=round(tp2, 2),
        risk_usd_per_lot=round(risk, 2), sl_pips=round(risk, 2),
        rr_tp1=round(rr1, 2), rr_tp2=round(rr2, 2),
        zone_type=zone["type"], zone_top=round(zone["top"], 2),
        zone_bottom=round(zone["bottom"], 2),
        fib_pos=round(fpos, 3), retrace=round(depth, 3),
        sweep_level=round(sweep["level"], 2) if swept else 0.0,
        atr_m15=round(a15, 2), reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Market-entry repricing
# ---------------------------------------------------------------------------
def reprice_for_market_entry(setup: Setup, bid: float, ask: float, cfg) -> Optional[Setup]:
    """
    The setup is priced at the OB/FVG edge. When entering at market on the M5
    confirmation (the document's stated alternative), re-price against the
    real fill so R:R, stop distance and lot size stay honest — and refuse to
    chase if price has already run away from the zone.
    """
    if bid <= 0 or ask <= 0:
        return None
    long = setup.direction == "bullish"
    fill = ask if long else bid
    risk = abs(fill - setup.sl)
    if risk <= 0:
        return None

    original_risk = abs(setup.entry - setup.sl)
    chase = (fill - setup.entry) if long else (setup.entry - fill)
    if original_risk > 0 and chase > cfg.max_chase_r * original_risk:
        setup.rejected = (f"price ran {chase:.2f} beyond the zone "
                          f"({chase/original_risk:.2f}R) — not chasing")
        return None
    if risk < cfg.min_sl_pips or risk > cfg.max_sl_pips:
        setup.rejected = f"stop distance {risk:.2f} outside limits"
        return None

    sign = 1 if long else -1
    tp1 = fill + sign * risk * cfg.tp1_r
    tp2 = fill + sign * risk * cfg.tp2_r
    if abs(setup.tp2 - setup.entry) / original_risk > cfg.tp2_r and original_risk:
        tp2 = setup.tp2                      # keep a liquidity-anchored TP2

    rr1 = abs(tp1 - fill) / risk
    rr2 = abs(tp2 - fill) / risk
    if rr1 < cfg.min_rr:
        setup.rejected = f"R:R to TP1 {rr1:.2f} below {cfg.min_rr}"
        return None

    setup.entry = round(fill, 2)
    setup.sl = round(setup.sl, 2)
    setup.tp1 = round(tp1, 2)
    setup.tp2 = round(tp2, 2)
    setup.risk_usd_per_lot = round(risk, 2)
    setup.sl_pips = round(risk, 2)
    setup.rr_tp1 = round(rr1, 2)
    setup.rr_tp2 = round(rr2, 2)
    return setup


def fingerprint(setup: Setup) -> str:
    """Stable id for a setup so the same zone is not traded twice."""
    return (f"{setup.symbol}:{setup.direction}:{setup.zone_type}:"
            f"{setup.zone_bottom:.2f}-{setup.zone_top:.2f}:{setup.sweep_level:.2f}")
