"""
Objective confluence grading (spec §8).

Ten weighted market components, totalling 100. No component is subjective and none
is a free gift: each is computed from a fact the SMC engine measured. Hard
gates run first — a setup that fails one is INVALID whatever it scores.

Historical performance is applied separately, as a veto (apply_history_veto).

  A+  90-100   sniper: full institutional alignment
  A   80-89    strong, one minor confluence missing
  B   70-79    tradeable but second-tier
  C   60-69    weak — the engine's own advice is to skip it
  INVALID <60  or a hard gate failed
"""
from __future__ import annotations

from .config import GRADE_ADVICE, GRADE_BANDS, GRADE_WEIGHTS, MODES, StrategyConfig
from .setups import Setup

REVERSAL_PATTERNS = {"LIQUIDITY_SWEEP_REVERSAL", "PREMIUM_DISCOUNT_REVERSAL"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# --------------------------------------------------------------------------
# Component scorers — each returns a 0..1 fraction of its weight
# --------------------------------------------------------------------------
def _htf_bias(f: dict, pattern: str) -> tuple[float, str]:
    htf_ok, mtf_ok = f["htf_aligned"], f["mtf_aligned"]
    if htf_ok and mtf_ok:
        return 1.0, "HTF+MTF both aligned with the trade"
    if htf_ok:
        return 0.70, "HTF aligned, MTF neutral/opposed"
    if mtf_ok:
        return 0.50, "MTF aligned, HTF neutral/opposed"
    if pattern in REVERSAL_PATTERNS and f["entry_pd_favourable"]:
        return 0.55, "counter-trend, but taken from the correct half of the HTF range"
    if f["htf_trend"] == "ranging" and f["mtf_trend"] == "ranging":
        return 0.35, "no HTF trend — range conditions"
    return 0.0, "HTF bias opposes the trade"


def _liquidity(f: dict) -> tuple[float, str]:
    if f["pool_is_session"]:
        base, why = 0.95, f"swept a session/daily pool ({f['pool_kind'].upper()})"
    elif f["pool_is_equal"]:
        base, why = 0.90, f"swept equal highs/lows (x{f['pool_strength']})"
    elif f["pool_strength"] >= 2:
        base, why = 0.75, f"swept a clustered swing pool (x{f['pool_strength']})"
    elif f["pool_kind"] != "range_extreme":
        base, why = 0.55, "swept a single swing point"
    else:
        base, why = 0.35, "swept an N-bar extreme (no named pool)"
    rej = _clamp((f["sweep_rejection_atr"] - 0.2) / 1.0)      # how hard it rejected
    return _clamp(base * (0.80 + 0.20 * rej) + 0.05 * rej), why


def _structure(f: dict) -> tuple[float, str]:
    s = 0.45 if f["ltf_structure_events"] >= 2 else 0.20
    if f["ltf_structure_trend"] == f["direction"]:
        s += 0.35
    if f["regime"] == "TRENDING":
        s += 0.20
    elif f["regime"] == "VOLATILE":
        s -= 0.15
    return _clamp(s), f"execution-TF structure {f['ltf_structure_trend']} / regime {f['regime']}"


def _mss_bos(f: dict, mode: str) -> tuple[float, str]:
    base = 1.0 if f["mss_kind"] == "MSS" else 0.85
    max_age = MODES[mode].max_age_bars or 1
    fresh = _clamp(1.0 - (f["bars_since_mss"] / (2.0 * max_age)))
    return _clamp(base * (0.65 + 0.35 * fresh)), \
        f"{f['mss_kind']} confirmed {f['bars_since_mss']} bars ago"


def _displacement(f: dict) -> tuple[float, str]:
    size = f["mss_displacement_atr"]
    mag = _clamp((size - 0.8) / 1.4)                            # 0.8x ATR -> 0, 2.2x -> 1
    body = _clamp(f["mss_body_ratio"] / 0.75)
    return _clamp(0.35 + 0.45 * mag + 0.20 * body), f"displacement {size:.2f}x ATR"


def _fvg(f: dict) -> tuple[float, str]:
    if not f["has_fvg"]:
        return 0.15, "no unmitigated FVG — entry rests on the order block alone"
    fill = f["fvg_fill_pct"] or 0.0
    if fill < 0.25:
        base = 1.0
    elif fill < 0.50:
        base = 0.80
    elif fill < 0.75:
        base = 0.60
    else:
        base = 0.35
    size = f.get("fvg_size_atr") or 0.0
    return _clamp(base * (0.9 + 0.1 * _clamp(size / 0.5))), \
        f"FVG {int(fill * 100)}% filled, {size:.2f}x ATR wide"


def _order_block(f: dict) -> tuple[float, str]:
    if not f["has_ob"]:
        return 0.20, "no aligned order block"
    if f["ob_mitigated"]:
        return 0.60, "order block present but already mitigated"
    imp = _clamp(((f.get("ob_impulse_atr") or 1.0) - 0.8) / 1.2)
    return _clamp(0.80 + 0.20 * imp), f"fresh order block, {f.get('ob_impulse_atr')}x ATR impulse"


def _premium_discount(f: dict) -> tuple[float, str]:
    pos = f["entry_pd_position"]
    if f["entry_in_ote"]:
        return 1.0, f"entry inside the OTE golden pocket (range pos {pos:.2f})"
    if f["entry_pd_favourable"]:
        return 0.75, f"entry in the correct half of the range (pos {pos:.2f})"
    if 0.44 <= pos <= 0.56:
        return 0.40, "entry at equilibrium"
    return 0.0, f"entry in the WRONG half of the range (pos {pos:.2f})"


def _session(f: dict) -> tuple[float, str]:
    if f["is_prime_killzone"]:
        return 1.0, f"prime killzone ({f['killzone']})"
    if f["killzone"]:
        return 0.75, f"killzone ({f['killzone']})"
    if f["session"] in ("LONDON", "LONDON_NY_OVERLAP", "NEW_YORK"):
        return 0.55, f"{f['session']} session, outside the killzone"
    if f["session"] == "ASIA":
        return 0.30, "Asia session — thin XAUUSD conditions"
    return 0.05, "rollover / illiquid hours"


def _volatility(f: dict) -> tuple[float, str]:
    v = f["volatility"]
    return ({"NORMAL": 1.0, "ELEVATED": 0.70, "DEAD": 0.20, "EXTREME": 0.0}.get(v, 0.5),
            f"volatility {v} (ATR at the {int(f['atr_pctile'] * 100)}th percentile)")


# --------------------------------------------------------------------------
# Hard gates + grading
# --------------------------------------------------------------------------
def hard_gates(setup: Setup, cfg: StrategyConfig) -> str | None:
    f = setup.features
    mode = MODES[setup.mode]
    if setup.rr < mode.min_rr:
        return f"risk/reward {setup.rr:.2f} below the {mode.name} minimum of {mode.min_rr}"
    if not f["regime_tradeable"]:
        return f"market volatility unsuitable ({f['volatility']})"
    if f["htf_conflicted"] and setup.pattern not in REVERSAL_PATTERNS:
        return "higher-timeframe bias is conflicted and this is not a reversal pattern"
    if f["entry_pd_position"] is not None and not f["entry_pd_favourable"] \
            and not (0.40 <= f["entry_pd_position"] <= 0.60):
        return "entry sits in the wrong half of the higher-timeframe range"
    return None


def grade(setup: Setup, cfg: StrategyConfig) -> Setup:
    """
    Score, grade and gate a setup in place, from market facts only. Identical in
    the live scanner and the backtest — that is what makes the grade buckets
    mean the same thing in both. Returns the same object.
    """
    f = setup.features
    scorers = {
        "htf_bias": _htf_bias(f, setup.pattern),
        "liquidity": _liquidity(f),
        "structure": _structure(f),
        "mss_bos": _mss_bos(f, setup.mode),
        "displacement": _displacement(f),
        "fvg": _fvg(f),
        "order_block": _order_block(f),
        "premium_discount": _premium_discount(f),
        "session": _session(f),
        "volatility": _volatility(f),
    }
    total = 0.0
    setup.component_scores, setup.confluences, setup.missing = {}, [], []
    for name, (frac, why) in scorers.items():
        w = GRADE_WEIGHTS[name]
        pts = round(frac * w, 2)
        total += pts
        setup.component_scores[name] = {"points": pts, "max": w,
                                        "fraction": round(frac, 3), "note": why}
        (setup.confluences if frac >= 0.60 else setup.missing).append(f"{name}: {why}")

    setup.score = round(total, 1)
    setup.grade = next((g for g, lo in GRADE_BANDS if total >= lo), "INVALID")

    gate = hard_gates(setup, cfg)
    if gate:
        setup.grade, setup.status, setup.invalid_reason = "INVALID", "INVALID", gate
    elif len(setup.confluences) < cfg.min_confluences:
        setup.grade, setup.status = "INVALID", "INVALID"
        setup.invalid_reason = (f"only {len(setup.confluences)} confluences present, "
                                f"{cfg.min_confluences} required")
    elif setup.grade == "INVALID":
        setup.status, setup.invalid_reason = "INVALID", f"confluence score {setup.score} below 60"
    else:
        setup.status, setup.invalid_reason = "VALID", ""
    setup.advice = GRADE_ADVICE.get(setup.grade, "")
    return setup


def apply_history_veto(setup: Setup, min_sample: int, min_pf: float = 1.0) -> Setup:
    """
    One-way use of measured history (spec §8/§9): a configuration whose OWN
    backtested sample is large enough AND loses money is struck out, whatever
    its confluence score says. History can only remove a setup here — it can
    never promote one, because a statistic that promotes the grade it was
    bucketed by is circular.
    """
    setup.history_flag = "UNVALIDATED"
    if setup.sample_size >= min_sample and setup.profit_factor is not None:
        pf, wr = setup.profit_factor, (setup.probability or 0.0)
        if pf < min_pf:
            setup.history_flag = "VALIDATED_NEGATIVE"
            setup.grade, setup.status = "INVALID", "INVALID"
            setup.invalid_reason = (
                f"this configuration has a MEASURED negative expectancy "
                f"(PF {pf:.2f}, {wr:.1f}% over n={setup.sample_size}) — vetoed")
        elif pf >= 1.5 and wr >= 55:
            setup.history_flag = "VALIDATED_STRONG"
        else:
            setup.history_flag = "VALIDATED_WEAK"
    return setup
