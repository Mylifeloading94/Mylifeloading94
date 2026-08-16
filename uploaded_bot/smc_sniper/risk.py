"""
SMC Sniper — Risk Management + Position Sizing (spec §8-9, §27).

Position size is ALWAYS derived from (equity, entry, stop, instrument pip
value) — never a fixed lot size. If the stop distance changes, size changes
so planned dollar risk stays constant at RISK_PER_TRADE.

Safety invariants enforced here (spec §27 — these raise, they don't warn):
  - No trade without a stop loss.
  - Never risk more than CONFIG.MAX_RISK_PER_TRADE of equity.
  - Never widen a stop after entry (no fixed 'entry price' comparison is
    possible without a broker-position handle, so `assert_sl_not_widened`
    is provided for the position-management module to call on every SL
    modification attempt).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Optional

from .config import SniperConfig, CONFIG, INSTRUMENTS


class RiskViolation(Exception):
    """Raised when a proposed trade would breach a hard safety invariant."""


@dataclass
class PositionSize:
    symbol: str
    lots: float
    risk_pips: float
    dollar_risk: float
    risk_pct: float
    pip_val_per_lot: float


def _instrument_spec(symbol: str) -> Dict:
    spec = INSTRUMENTS.get(symbol)
    if spec is None:
        raise RiskViolation(f"{symbol} is not in the configured watchlist/instrument table.")
    if not spec.get("configured", False):
        raise RiskViolation(
            f"{symbol} has no verified broker spec (pip value / contract size) — "
            f"refusing to size a trade on an unconfigured instrument (safety §27)."
        )
    return spec


def position_size(
    symbol: str,
    equity: float,
    entry: float,
    stop_loss: float,
    cfg: SniperConfig = CONFIG,
    risk_pct: Optional[float] = None,
) -> PositionSize:
    """Compute lot size so that (stop_distance * pip_value * lots) ==
    equity * risk_pct, clamped never to exceed MAX_RISK_PER_TRADE."""
    if stop_loss is None:
        raise RiskViolation(f"{symbol}: no stop loss supplied — refusing to size a trade (safety §27).")
    if entry == stop_loss:
        raise RiskViolation(f"{symbol}: entry == stop loss, zero risk distance is not tradeable.")
    if equity <= 0:
        raise RiskViolation(f"{symbol}: non-positive equity ({equity}).")

    risk_pct = cfg.RISK_PER_TRADE if risk_pct is None else risk_pct
    if risk_pct > cfg.MAX_RISK_PER_TRADE:
        raise RiskViolation(
            f"{symbol}: requested risk_pct {risk_pct:.4f} exceeds MAX_RISK_PER_TRADE "
            f"{cfg.MAX_RISK_PER_TRADE:.4f} — hard ceiling, never exceeded."
        )

    spec = _instrument_spec(symbol)
    pip = spec["pip"]
    pip_val = spec["pip_val"]  # $ per 1.0 lot per pip, from broker contract specs

    risk_pips = abs(entry - stop_loss) / pip
    dollar_risk = equity * risk_pct

    # Always round DOWN to the nearest 0.01 lot: planned risk must never
    # exceed the target (§8 — "never risk more than the configured risk
    # percentage" is a ceiling, not a nearest-fit).
    raw_lots = dollar_risk / (risk_pips * pip_val) if risk_pips * pip_val > 0 else 0.0
    lots = max(0.01, math.floor(raw_lots * 100) / 100)

    actual_dollar_risk = lots * risk_pips * pip_val
    actual_risk_pct = actual_dollar_risk / equity

    if actual_risk_pct > cfg.MAX_RISK_PER_TRADE * 1.10:
        # Even the minimum 0.01 lot risks meaningfully more than allowed
        # (equity too small relative to this instrument's stop distance) —
        # refuse rather than silently over-risk.
        raise RiskViolation(
            f"{symbol}: minimum lot size (0.01) risks {actual_risk_pct:.2%} of equity, "
            f"exceeds MAX_RISK_PER_TRADE {cfg.MAX_RISK_PER_TRADE:.2%} — equity too small "
            f"for this stop distance on this instrument."
        )

    return PositionSize(
        symbol=symbol, lots=lots, risk_pips=round(risk_pips, 1),
        dollar_risk=round(actual_dollar_risk, 2), risk_pct=round(actual_risk_pct, 4),
        pip_val_per_lot=pip_val,
    )


def required_sl_buffer(atr: float, spread_pips: float, pip: float, cfg: SniperConfig = CONFIG) -> float:
    """Minimum SL buffer beyond the structural invalidation point (§9):
    the larger of a volatility buffer and a spread buffer, in price units."""
    vol_buf = cfg.VOLATILITY_BUFFER_ATR * atr
    spread_buf = cfg.SPREAD_BUFFER_MULT * spread_pips * pip
    return max(vol_buf, spread_buf)


def assert_sl_not_widened(symbol: str, direction: str, original_sl: float, proposed_sl: float) -> None:
    """Call before ANY live SL modification. Moving SL further from price
    (i.e. increasing planned loss) is never permitted (§9, §27)."""
    if direction == "bullish" and proposed_sl < original_sl:
        raise RiskViolation(f"{symbol}: proposed SL {proposed_sl} is BELOW original {original_sl} "
                             f"(widens risk on a long) — forbidden.")
    if direction == "bearish" and proposed_sl > original_sl:
        raise RiskViolation(f"{symbol}: proposed SL {proposed_sl} is ABOVE original {original_sl} "
                             f"(widens risk on a short) — forbidden.")


def spread_is_acceptable(symbol: str, current_spread_pips: float, cfg: SniperConfig = CONFIG) -> bool:
    cap = cfg.MAX_SPREAD_PIPS.get(symbol)
    if cap is None:
        return False  # unconfigured instrument -> refuse, don't assume
    return current_spread_pips <= cap
