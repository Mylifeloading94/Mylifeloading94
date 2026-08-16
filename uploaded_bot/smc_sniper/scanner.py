"""
SMC Sniper — Setup Scanner pipeline (spec §17, architecture module 8).

SCAN -> FILTER -> SCORE -> CONFIRM -> CALCULATE RISK -> EXECUTE.

This module does NOT talk to a broker or place orders — `sniper_smc.py`
(and trading_agent.py's execution helpers) own market data and order
routing. `run_pipeline` takes the raw setups sniper_smc.scan_sniper()
already found (instrument-allowed, HTF-aligned, liquidity-swept,
structure-confirmed, entry-zone-valid — all guaranteed by construction,
per scoring.py's docstring) plus live account/market context, and applies
every remaining checklist item from §17 before turning a setup into an
ExecutionPlan the execution module is allowed to act on.

If ANY check fails, the setup is rejected with a specific reason — per §16,
"no trade" is always a valid, and often correct, outcome.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .config import SniperConfig, CONFIG, INSTRUMENTS
from .scoring import score_setup, ScoreBreakdown
from .risk import position_size, spread_is_acceptable, RiskViolation, PositionSize
from .correlation import check_correlation
from .news_filter import NewsCalendar, is_blackout_active
from .daily_guardrails import DailyState, can_trade
from .explain import explain_setup


@dataclass
class ExecutionPlan:
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    sizing: PositionSize
    score: ScoreBreakdown
    explanation: Dict
    setup: Dict   # original setup dict (carries bars_15m / meta for journaling+charts)


@dataclass
class RejectedSetup:
    symbol: str
    reason: str


def run_pipeline(
    raw_setups: List[Dict],
    equity: float,
    open_positions: List[Dict],           # [{"symbol","direction","dollar_risk"}, ...]
    current_spreads: Dict[str, float],     # symbol -> current spread in pips
    news_calendar: NewsCalendar,
    daily_state: DailyState,
    now: Optional[datetime] = None,
    cfg: SniperConfig = CONFIG,
) -> Tuple[List[ExecutionPlan], List[RejectedSetup]]:
    now = now or datetime.now(timezone.utc)
    approved: List[ExecutionPlan] = []
    rejected: List[RejectedSetup] = []

    # --- global gate: daily guardrails (§15) apply before touching any setup
    ok, reason = can_trade(daily_state, equity, cfg, now)
    if not ok:
        return [], [RejectedSetup(s["name"], f"daily guardrail: {reason}") for s in raw_setups]

    remaining_slots = cfg.MAX_DAILY_TRADES - daily_state.trades_today
    if remaining_slots <= 0:
        return [], [RejectedSetup(s["name"], "no daily trade slots remaining") for s in raw_setups]

    # Rank the whole watchlist highest-score-first (§6: "continuously scan...
    # and rank opportunities from highest score to lowest") before running
    # the pass/fail gates below, so limited daily slots go to the best setups.
    raw_setups = sorted(raw_setups, key=lambda s: score_setup(s, cfg).total, reverse=True)

    # Running list of positions we'd hold if every approved-so-far plan in
    # this scan were opened, so correlation is checked against siblings too.
    hypothetical_open = list(open_positions)

    for setup in raw_setups:
        symbol = setup["name"]
        direction = setup["direction"]

        # 1. instrument allowed + fully specified
        if symbol not in cfg.watchlist:
            rejected.append(RejectedSetup(symbol, "instrument not in configured watchlist")); continue
        spec = INSTRUMENTS.get(symbol)
        if not spec or not spec.get("configured"):
            rejected.append(RejectedSetup(symbol, "instrument has no verified broker spec")); continue

        # 2. spread acceptable
        spread = current_spreads.get(symbol)
        if spread is None:
            rejected.append(RejectedSetup(symbol, "current spread unknown")); continue
        if not spread_is_acceptable(symbol, spread, cfg):
            rejected.append(RejectedSetup(symbol, f"spread {spread}p exceeds cap")); continue

        # 3. news blackout clear
        blocking_event = is_blackout_active(symbol, now, news_calendar, cfg)
        if blocking_event:
            rejected.append(RejectedSetup(
                symbol, f"news blackout: {blocking_event.title} at {blocking_event.time_utc.isoformat()}"
            )); continue

        # 4. setup must be a live/ready entry, not a pending limit awaiting mitigation
        if setup.get("state") != "ready":
            rejected.append(RejectedSetup(symbol, f"setup state={setup.get('state')}, not yet mitigated")); continue

        # 5. HTF bias / liquidity sweep / structure shift / entry zone —
        #    all guaranteed by sniper_smc.analyze_sniper's construction, but
        #    the scoring engine re-verifies each independently below.
        breakdown = score_setup(setup, cfg)
        if breakdown.total < cfg.MIN_SETUP_SCORE:
            rejected.append(RejectedSetup(
                symbol, f"score {breakdown.total} below MIN_SETUP_SCORE {cfg.MIN_SETUP_SCORE} ({breakdown.reasons})"
            )); continue

        # 6. risk/reward acceptable
        risk = abs(setup["entry"] - setup["sl"])
        reward = abs(setup["tp2"] - setup["entry"])
        rr = reward / risk if risk > 0 else 0.0
        if rr < cfg.MIN_RR:
            rejected.append(RejectedSetup(symbol, f"R:R {rr:.2f} below MIN_RR {cfg.MIN_RR}")); continue

        # 7. position size (also enforces "never trade without a stop", "never
        #    exceed max risk %")
        try:
            sizing = position_size(symbol, equity, setup["entry"], setup["sl"], cfg)
        except RiskViolation as e:
            rejected.append(RejectedSetup(symbol, f"risk sizing rejected: {e}")); continue

        # 8. correlation / correlated-currency exposure
        corr = check_correlation(symbol, direction, sizing.dollar_risk, equity, hypothetical_open, cfg)
        if not corr.allowed:
            rejected.append(RejectedSetup(symbol, f"correlation: {corr.reason}")); continue

        # 9. stop loss + take profit attached (structural, always true here,
        #    re-asserted so a future refactor can't silently drop one)
        if setup.get("sl") is None or setup.get("tp1") is None or setup.get("tp2") is None:
            rejected.append(RejectedSetup(symbol, "missing SL/TP — refusing to trade")); continue

        setup_with_score = dict(setup)
        setup_with_score["score"] = breakdown
        plan = ExecutionPlan(
            symbol=symbol, direction=direction, entry=setup["entry"], stop_loss=setup["sl"],
            tp1=setup["tp1"], tp2=setup["tp2"], sizing=sizing, score=breakdown,
            explanation=explain_setup(setup_with_score, cfg), setup=setup_with_score,
        )
        approved.append(plan)
        hypothetical_open.append({"symbol": symbol, "direction": direction, "dollar_risk": sizing.dollar_risk})

        if len(approved) >= remaining_slots:
            # Remaining setups this scan still get scored/explained for
            # visibility but can't be taken today — mark and stop consuming
            # daily-trade budget speculatively.
            for leftover in raw_setups[raw_setups.index(setup) + 1:]:
                if leftover["name"] not in {a.symbol for a in approved}:
                    rejected.append(RejectedSetup(leftover["name"], "daily trade slots exhausted by higher-ranked setups"))
            break

    approved.sort(key=lambda p: p.score.total, reverse=True)
    return approved, rejected
