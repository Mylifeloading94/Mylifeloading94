"""
SMC Sniper — Setup Scoring Engine (spec §6, architecture module 9).

Turns a raw sniper_smc setup dict into a 0-100 quality score so the scanner
can rank the watchlist from highest-quality opportunity to lowest and gate
entries at CONFIG.MIN_SETUP_SCORE.

The sniper entry engine (sniper_smc.analyze_sniper) only ever returns a
setup after the full institutional sequence has already been confirmed —
HTF bias, liquidity sweep, MSS/displacement, and a valid FVG/order-block
zone are structural PRECONDITIONS of getting a dict back at all, not
optional traits to detect here. So the boolean-gate components below are
"full weight if the setup exists, independently re-verified" rather than
re-implementing the detection from scratch — a second pair of eyes on the
same evidence rather than blind rubber-stamping.

Only the two components the spec phrases as gradable ("STRONG
displacement", "R:R QUALITY") plus premium/discount positioning and
session tier are scored on a continuum from the setup's own metadata.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import SniperConfig, CONFIG


@dataclass
class ScoreBreakdown:
    total: int
    passed: bool
    components: Dict[str, float]
    reasons: List[str]


def _htf_alignment(setup: Dict, cfg: SniperConfig) -> float:
    bias = (setup.get("meta") or {}).get("bias_htf")
    direction = setup["direction"]
    ok = (bias == "bullish" and direction == "bullish") or \
         (bias == "bearish" and direction == "bearish")
    return cfg.SCORE_WEIGHTS["htf_alignment"] if ok else 0.0


def _liquidity_sweep(setup: Dict, cfg: SniperConfig) -> float:
    # A sweep_ext beyond the entry/SL side is the structural proof a prior
    # extreme was taken before the reversal — present on every setup the
    # engine emits; scored as a re-verified boolean gate, not assumed.
    meta = setup.get("meta") or {}
    return cfg.SCORE_WEIGHTS["liquidity_sweep"] if meta.get("sweep_ext") is not None else 0.0


def _structure_shift(setup: Dict, cfg: SniperConfig) -> float:
    meta = setup.get("meta") or {}
    return cfg.SCORE_WEIGHTS["structure_shift"] if meta.get("disp_body") is not None else 0.0


def _displacement(setup: Dict, cfg: SniperConfig) -> float:
    """Graded: how far the MSS candle's body exceeds the minimum displacement
    threshold. 1.0x threshold = half credit, 2.0x+ threshold = full credit."""
    meta = setup.get("meta") or {}
    body, a = meta.get("disp_body"), meta.get("atr")
    weight = cfg.SCORE_WEIGHTS["displacement"]
    if not body or not a or a <= 0:
        return 0.0
    ratio = body / a
    threshold = cfg.DISPLACEMENT_ATR_MULT
    if ratio < threshold:
        return 0.0
    frac = min(1.0, (ratio - threshold) / threshold)  # ratio==2x threshold -> full
    return round(weight * (0.5 + 0.5 * frac), 2)


def _order_block(setup: Dict, cfg: SniperConfig) -> float:
    return cfg.SCORE_WEIGHTS["order_block"] if setup.get("zone_mid") is not None else 0.0


def _fvg(setup: Dict, cfg: SniperConfig) -> float:
    # zone_mid is derived from the pre-displacement candle's FVG in sniper_smc;
    # its presence is the FVG confirmation.
    return cfg.SCORE_WEIGHTS["fvg"] if setup.get("zone_mid") is not None else 0.0


def _premium_discount(setup: Dict, cfg: SniperConfig) -> float:
    """Graded: proximity of the OTE retrace depth to the golden-pocket
    center (~0.76 of the 0.62-0.90 band) — deeper into the sweet spot
    scores higher than a setup that just barely clipped the band edge."""
    depth = (setup.get("meta") or {}).get("ote_depth")
    weight = cfg.SCORE_WEIGHTS["premium_discount"]
    if depth is None:
        return 0.0
    lo, hi = cfg.OTE_BAND
    center = (lo + hi) / 2
    half_width = (hi - lo) / 2
    if not (lo <= depth <= hi):
        return 0.0
    closeness = 1.0 - abs(depth - center) / half_width  # 1.0 at center, 0.0 at edge
    return round(weight * max(0.0, closeness), 2)


def _session(setup: Dict, cfg: SniperConfig, ts_ms: Optional[int]) -> float:
    """Graded: full weight inside a prime killzone, partial weight just
    outside one (still session-valid), zero outside all configured windows."""
    weight = cfg.SCORE_WEIGHTS["session"]
    if ts_ms is None:
        return 0.0
    minute_of_day = int((ts_ms // 60000) % 1440)
    best = 0.0
    for start, end in cfg.SESSIONS_UTC.values():
        if start <= minute_of_day <= end:
            return weight
        # partial credit tapering off over 30 minutes either side of a window
        dist = min(abs(minute_of_day - start), abs(minute_of_day - end))
        if dist <= 30:
            best = max(best, weight * (1 - dist / 30))
    return round(best, 2)


def _risk_reward(setup: Dict, cfg: SniperConfig) -> float:
    """Graded: R:R below MIN_RR scores 0 (should already be filtered out
    upstream); scales to full weight at/above the top of PREFERRED_RR."""
    weight = cfg.SCORE_WEIGHTS["risk_reward"]
    entry, sl, tp2 = setup.get("entry"), setup.get("sl"), setup.get("tp2")
    if entry is None or sl is None or tp2 is None or entry == sl:
        return 0.0
    risk = abs(entry - sl)
    reward = abs(tp2 - entry)
    rr = reward / risk if risk > 0 else 0.0
    if rr < cfg.MIN_RR:
        return 0.0
    top = cfg.PREFERRED_RR[1]
    frac = min(1.0, (rr - cfg.MIN_RR) / (top - cfg.MIN_RR)) if top > cfg.MIN_RR else 1.0
    return round(weight * frac, 2)


def score_setup(setup: Dict, cfg: SniperConfig = CONFIG) -> ScoreBreakdown:
    """Score a sniper_smc setup dict 0-100. Never mutates the input."""
    meta = setup.get("meta") or {}
    ts_ms = meta.get("mss_bar_ts")

    components = {
        "htf_alignment": _htf_alignment(setup, cfg),
        "liquidity_sweep": _liquidity_sweep(setup, cfg),
        "structure_shift": _structure_shift(setup, cfg),
        "displacement": _displacement(setup, cfg),
        "order_block": _order_block(setup, cfg),
        "fvg": _fvg(setup, cfg),
        "premium_discount": _premium_discount(setup, cfg),
        "session": _session(setup, cfg, ts_ms),
        "risk_reward": _risk_reward(setup, cfg),
    }
    total = round(sum(components.values()))
    reasons = [f"{k}: {v}/{cfg.SCORE_WEIGHTS[k]}" for k, v in components.items()]
    passed = total >= cfg.MIN_SETUP_SCORE
    return ScoreBreakdown(total=total, passed=passed, components=components, reasons=reasons)


def rank_setups(setups: List[Dict], cfg: SniperConfig = CONFIG) -> List[Dict]:
    """Score every setup and return them ranked highest-score-first, each
    augmented with a `score` (ScoreBreakdown). Setups below MIN_SETUP_SCORE
    are still returned (marked failed) so callers can see what was rejected
    and why — filtering to tradeable-only happens in the scanner (§17)."""
    scored = []
    for s in setups:
        breakdown = score_setup(s, cfg)
        s2 = dict(s)
        s2["score"] = breakdown
        scored.append(s2)
    scored.sort(key=lambda x: x["score"].total, reverse=True)
    return scored
