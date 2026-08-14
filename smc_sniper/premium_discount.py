"""Phase 4 -- Premium / discount (equilibrium).

The current structural leg is split at its 50% equilibrium. Below EQ is
*discount* (where longs want to buy), above EQ is *premium* (where shorts want
to sell).

Per the spec this is a **soft** rule: a long taken outside discount is not
vetoed, it simply forfeits the +5 score. Structure sometimes legitimately
invalidates the location preference. A hard veto applies only past
``hard_veto_beyond`` -- buying the top 15% of a leg or selling the bottom 15%
is a chase, and this system does not chase.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PDState:
    leg_high: float
    leg_low: float
    equilibrium: float
    position: float          # 0.0 at leg low, 1.0 at leg high
    zone: str                # "discount" | "premium" | "equilibrium"

    @property
    def in_discount(self) -> bool:
        return self.zone == "discount"

    @property
    def in_premium(self) -> bool:
        return self.zone == "premium"


def evaluate(price: float, leg_high: float | None, leg_low: float | None,
             cfg: dict) -> PDState | None:
    """Locate ``price`` within the structural leg."""
    if leg_high is None or leg_low is None or leg_high <= leg_low:
        return None
    eq_frac = float(cfg.get("equilibrium", 0.5))
    span = leg_high - leg_low
    position = (price - leg_low) / span
    equilibrium = leg_low + eq_frac * span
    if position < eq_frac - 0.02:
        zone = "discount"
    elif position > eq_frac + 0.02:
        zone = "premium"
    else:
        zone = "equilibrium"
    return PDState(leg_high, leg_low, equilibrium, position, zone)


def favourable(pd_state: PDState | None, direction: str) -> bool:
    """Does location earn the +5? (Longs in discount, shorts in premium.)"""
    if pd_state is None:
        return False
    return (direction == "bullish" and pd_state.in_discount) or \
           (direction == "bearish" and pd_state.in_premium)


def hard_veto(pd_state: PDState | None, direction: str, cfg: dict) -> tuple[bool, str]:
    """Block only genuine chases at the extremes of the leg."""
    if pd_state is None or not cfg.get("enabled", True):
        return False, ""
    beyond = float(cfg.get("hard_veto_beyond", 0.85))
    if direction == "bullish" and pd_state.position > beyond:
        return True, f"chasing_long_at_{pd_state.position:.2f}_of_leg"
    if direction == "bearish" and pd_state.position < (1.0 - beyond):
        return True, f"chasing_short_at_{pd_state.position:.2f}_of_leg"
    return False, ""
