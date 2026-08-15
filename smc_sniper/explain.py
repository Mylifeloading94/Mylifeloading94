"""
SMC Sniper — Signal Explanation (spec §25).

Produces both a machine-readable dict and the human-readable block format
shown in the spec for every setup that clears MIN_SETUP_SCORE, so a trade
is never taken (or logged) without a legible reason.
"""
from __future__ import annotations
from typing import Dict

from .config import SniperConfig, CONFIG
from .scoring import ScoreBreakdown


def _session_label(ts_ms, cfg: SniperConfig) -> str:
    if ts_ms is None:
        return "unknown"
    minute_of_day = int((ts_ms // 60000) % 1440)
    for label, (start, end) in cfg.SESSIONS_UTC.items():
        if start <= minute_of_day <= end:
            return label.replace("_", " ").title()
    return "outside prime killzones"


def explain_setup(setup: Dict, cfg: SniperConfig = CONFIG) -> Dict:
    """Returns the machine-readable explanation dict. Requires `setup` to
    already carry a `score` (ScoreBreakdown) from scoring.rank_setups."""
    breakdown: ScoreBreakdown = setup["score"]
    meta = setup.get("meta") or {}
    direction_word = "LONG" if setup["direction"] == "bullish" else "SHORT"
    risk = abs(setup["entry"] - setup["sl"])
    reward = abs(setup["tp2"] - setup["entry"])
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    session = _session_label(meta.get("mss_bar_ts"), cfg)

    liquidity_desc = "sell-side liquidity swept" if setup["direction"] == "bullish" \
        else "buy-side liquidity swept"
    structure_desc = f"{direction_word.title()} MSS confirmed"
    reason = (
        f"{liquidity_desc.capitalize()}, followed by {'bullish' if setup['direction']=='bullish' else 'bearish'} "
        f"displacement and a market-structure shift. Price retraced into a validated "
        f"{'bullish' if setup['direction']=='bullish' else 'bearish'} order block/FVG "
        f"({breakdown.components.get('premium_discount', 0):.1f}/{cfg.SCORE_WEIGHTS['premium_discount']} OTE quality) "
        f"while maintaining the higher-timeframe {setup['direction']} bias."
    )

    return {
        "symbol": setup["name"],
        "direction": direction_word,
        "score": breakdown.total,
        "score_breakdown": breakdown.components,
        "htf_bias": meta.get("bias_htf"),
        "liquidity": liquidity_desc,
        "structure": structure_desc,
        "displacement": "confirmed" if meta.get("disp_body") else "not detected",
        "order_block": f"{direction_word.title()} zone @ {setup.get('zone_mid')}",
        "fvg": f"{direction_word.title()} FVG @ {setup.get('zone_mid')}",
        "entry": setup["entry"],
        "stop_loss": setup["sl"],
        "take_profit": setup["tp2"],
        "risk_pct": cfg.RISK_PER_TRADE,
        "rr": f"1:{rr}",
        "session": session,
        "reason": reason,
    }


def format_explanation(setup: Dict, cfg: SniperConfig = CONFIG) -> str:
    """Human-readable block matching the spec §25 example format."""
    e = explain_setup(setup, cfg)
    return (
        f"{e['direction']} {e['symbol']}\n\n"
        f"Score: {e['score']}/100\n\n"
        f"HTF Bias: {str(e['htf_bias']).title()}\n\n"
        f"Liquidity: {e['liquidity'].capitalize()}\n\n"
        f"Structure: {e['structure']}\n\n"
        f"Displacement: {e['displacement'].capitalize()}\n\n"
        f"Order Block: {e['order_block']}\n\n"
        f"FVG: {e['fvg']}\n\n"
        f"Entry: {e['entry']}\n\n"
        f"Stop Loss: {e['stop_loss']}\n\n"
        f"Take Profit: {e['take_profit']}\n\n"
        f"Risk: {e['risk_pct']:.0%}\n\n"
        f"R:R: {e['rr']}\n\n"
        f"Session: {e['session']}\n\n"
        f"Reason:\n\n\"{e['reason']}\""
    )
