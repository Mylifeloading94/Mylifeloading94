"""Phase 5 -- The 0-100 scoring engine.

Every candidate setup is scored against the spec's component table. The score
gates the trade: conservative 85+, standard 80+ (default), aggressive 75+.

Component weights (sum = 100):

    ==========================  ======
    HTF aligned                   +15
    MSS / CHoCH                   +10
    BOS                           +10
    Major liquidity sweep         +15
    PD / PW liquidity              +5
    Valid order block             +10
    Valid FVG                     +10
    Premium / discount location    +5
    Displacement                   +5
    LTF confirmation               +5
    Favourable spread              +5
    ==========================  ======

Two things matter about how this is used. First, the threshold is a *gate*, not
a ranking -- the system is happy to take zero trades in a week. Second, the
score is recorded on every rejected setup too, so the decision log shows what
was skipped and why, not just what was taken.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreCard:
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return float(sum(self.components.values()))

    def add(self, name: str, points: float, reason: str = "") -> None:
        if points:
            self.components[name] = points
            if reason:
                self.reasons.append(reason)

    def missing(self, weights: dict) -> list[str]:
        return [k for k in weights if k not in self.components]

    def as_dict(self) -> dict:
        return {"total": self.total, "components": dict(self.components),
                "reasons": list(self.reasons)}


def score_setup(*, weights: dict, htf_aligned: bool, structure_event: str,
                has_bos: bool, sweep_kind: str | None, sweep_is_major: bool,
                pd_pw_liquidity: bool, order_block, fvg, pd_favourable: bool,
                displacement: bool, ltf_confirmed: bool,
                spread_ok: bool) -> ScoreCard:
    """Build the score card for one candidate setup."""
    card = ScoreCard()

    if htf_aligned:
        card.add("htf_aligned", weights["htf_aligned"], "HTF bias aligned")
    if structure_event in ("MSS", "CHoCH"):
        card.add("mss_choch", weights["mss_choch"], f"{structure_event} confirmed")
    if has_bos:
        card.add("bos", weights["bos"], "BOS in trade direction")
    if sweep_kind and sweep_is_major:
        card.add("major_sweep", weights["major_sweep"], f"major sweep of {sweep_kind}")
    if pd_pw_liquidity:
        card.add("pd_pw_liquidity", weights["pd_pw_liquidity"],
                 "previous day/week liquidity taken")
    if order_block is not None:
        card.add("valid_ob", weights["valid_ob"],
                 f"valid order block (q{order_block.quality})")
    if fvg is not None:
        card.add("valid_fvg", weights["valid_fvg"], "valid FVG in zone")
    if pd_favourable:
        card.add("premium_discount", weights["premium_discount"],
                 "entry in discount/premium")
    if displacement:
        card.add("displacement", weights["displacement"], "displacement confirmed")
    if ltf_confirmed:
        card.add("ltf_confirmation", weights["ltf_confirmation"],
                 "LTF entry confirmation")
    if spread_ok:
        card.add("favorable_spread", weights["favorable_spread"], "spread within limit")
    return card
