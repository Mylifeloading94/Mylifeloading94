"""
SMC Sniper — Correlation Manager (spec §14).

Generalizes the pair-level correlation filter already used elsewhere in
this repo (trading_agent.passes_correlation / usd_exposure_ok) into a
currency-exposure model: every symbol is decomposed into its base/quote
currencies (XAUUSD treated as XAU/USD), each open position contributes
signed dollar risk to those currencies, and a proposed trade is rejected
if it would push any single currency's same-direction combined risk above
CONFIG.MAX_CORRELATED_RISK (as a fraction of equity), or if too many
positions already touch that currency (CONFIG.MAX_OPEN_PER_CURRENCY).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .config import SniperConfig, CONFIG


@dataclass
class CorrelationResult:
    allowed: bool
    reason: str
    exposure: Dict[str, Dict[str, float]]


def parse_currencies(symbol: str) -> Tuple[str, str]:
    if symbol == "XAUUSD":
        return "XAU", "USD"
    if len(symbol) == 6:
        return symbol[:3], symbol[3:]
    raise ValueError(f"Cannot parse base/quote currencies from symbol {symbol!r}")


def currency_sides(symbol: str, direction: str) -> Dict[str, str]:
    """direction 'bullish' = buy the pair = long base / short quote."""
    base, quote = parse_currencies(symbol)
    if direction == "bullish":
        return {base: "long", quote: "short"}
    return {base: "short", quote: "long"}


def _exposure_map(positions: List[Dict]) -> Dict[str, Dict[str, float]]:
    exposure: Dict[str, Dict[str, float]] = {}
    for p in positions:
        for ccy, side in currency_sides(p["symbol"], p["direction"]).items():
            slot = exposure.setdefault(ccy, {"long": 0.0, "short": 0.0})
            slot[side] += p.get("dollar_risk", 0.0)
    return exposure


def check_correlation(
    symbol: str,
    direction: str,
    dollar_risk: float,
    equity: float,
    open_positions: List[Dict],
    cfg: SniperConfig = CONFIG,
) -> CorrelationResult:
    """`open_positions`: list of {"symbol", "direction", "dollar_risk"} for
    currently-open trades. Returns whether the proposed trade may be taken."""
    base, quote = parse_currencies(symbol)

    for ccy in (base, quote):
        touching = sum(1 for p in open_positions if ccy in parse_currencies(p["symbol"]))
        if touching >= cfg.MAX_OPEN_PER_CURRENCY:
            return CorrelationResult(
                False,
                f"{symbol}: {ccy} already has {touching} open position(s), "
                f"at MAX_OPEN_PER_CURRENCY={cfg.MAX_OPEN_PER_CURRENCY}.",
                _exposure_map(open_positions),
            )

    proposed = {"symbol": symbol, "direction": direction, "dollar_risk": dollar_risk}
    exposure = _exposure_map(open_positions + [proposed])

    if equity <= 0:
        return CorrelationResult(False, "non-positive equity", exposure)

    for ccy, sides in exposure.items():
        for side, amt in sides.items():
            frac = amt / equity
            if frac > cfg.MAX_CORRELATED_RISK + 1e-9:
                return CorrelationResult(
                    False,
                    f"{symbol}: combined {side} risk on {ccy} would be {frac:.2%} of equity, "
                    f"exceeds MAX_CORRELATED_RISK={cfg.MAX_CORRELATED_RISK:.2%}.",
                    exposure,
                )

    return CorrelationResult(True, "ok", exposure)
