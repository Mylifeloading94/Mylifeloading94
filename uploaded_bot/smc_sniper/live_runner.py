"""
SMC Sniper — Live Runner (spec §26 "Trade Execution" + §29 phases 8-10).

Wires the smc_sniper scanner pipeline (SCAN -> FILTER -> SCORE -> CONFIRM ->
SIZE) to the existing TradeLocker execution helpers in trading_agent.py, so
every order this places has already cleared MIN_SETUP_SCORE, R:R, spread,
news, correlation, and daily-guardrail checks — no "take everything"
bypass exists anywhere in this path.

SAFETY DEFAULT: `run_once(dry_run=True)` is the default in both the
function signature and the `__main__` block below. Dry-run prints exactly
what WOULD be traded (including the full signal explanation) and places
no order. Flipping to `dry_run=False` is a conscious, separate decision —
review dry-run output first, especially on an account with prior drawdown.

Credentials: read from TL_EMAIL / TL_PASSWORD / TL_SERVER environment
variables via trading_agent.auth() exactly as the rest of this repo
already does. This module never accepts credentials as arguments, and
never reads them from a config file or chat-supplied string.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

import trading_agent as ta
import sniper_smc as sn

from .config import CONFIG, SniperConfig
from .scanner import run_pipeline, ExecutionPlan
from .daily_guardrails import load_state, can_trade, record_trade_opened
from .news_filter import NewsCalendar, EmptyNewsCalendar
from .journal import log_entry
from .explain import format_explanation


def fetch_spread_pips(headers, instrument_id: int, pip: float) -> Optional[float]:
    """Best-effort current spread via GET /trade/quotes. Returns None
    ("unknown") on any failure — scanner.run_pipeline treats unknown
    spread as a reject, which is the safe default: never assume a tight
    spread just because the quote call failed."""
    try:
        r = requests.get(f"{ta.BASE_URL}/trade/quotes", headers=headers,
                          params={"tradableInstrumentId": instrument_id, "routeId": "INFO"}, timeout=10)
        d = r.json().get("d", {})
        bid = d.get("bid", d.get("bidPrice"))
        ask = d.get("ask", d.get("askPrice"))
        if bid is None or ask is None:
            return None
        return round((float(ask) - float(bid)) / pip, 1)
    except Exception:
        return None


def build_open_positions_context(headers, account_id, equity: float, cfg: SniperConfig = CONFIG) -> List[Dict]:
    """Best-effort correlation context from live positions. TradeLocker's
    position payload doesn't carry the dollar risk planned at entry, so
    this assumes CONFIG.RISK_PER_TRADE per open position as a conservative
    stand-in — deliberately an overestimate (a false correlation block is
    safe; understating live exposure is not)."""
    positions = ta.get_positions(headers, account_id)
    out = []
    for p in positions:
        try:
            iid = int(p[1])
        except (IndexError, TypeError, ValueError):
            continue
        name = ta.ID_TO_NAME.get(iid)
        if not name:
            continue
        side = p[3] if len(p) > 3 else None
        direction = "bullish" if side in ("buy", "bullish", 1) else "bearish"
        out.append({"symbol": name, "direction": direction, "dollar_risk": equity * cfg.RISK_PER_TRADE})
    return out


def execute_plan(headers, account_id, plan: ExecutionPlan, dry_run: bool = True) -> Optional[str]:
    """Places the order for an approved ExecutionPlan using the plan's own
    risk.position_size-derived lot size (2% risk, floor-rounded, safety-
    checked) rather than trading_agent.calc_lots, so every guarantee from
    smc_sniper.risk carries through to the live order. Returns the broker
    orderId, or None in dry-run / on rejection."""
    print(format_explanation(plan.setup))
    if dry_run:
        print(f"[DRY RUN] would place {plan.direction} {plan.symbol} {plan.sizing.lots} lots "
              f"SL {plan.stop_loss} TP {plan.tp2} (${plan.sizing.dollar_risk} risk)")
        return None

    cfg_inst = ta.MARKETS[plan.symbol]
    side = "buy" if plan.direction == "bullish" else "sell"
    body = {
        "tradableInstrumentId": cfg_inst["id"],
        "routeId": ta.TRADE_ROUTE,
        "type": "market",
        "side": side,
        "qty": plan.sizing.lots,
        "validity": "IOC",
        "stopLoss": plan.stop_loss,
        "takeProfit": plan.tp2,
        "stopLossType": "absolute",
        "takeProfitType": "absolute",
    }
    r = requests.post(f"{ta.BASE_URL}/trade/accounts/{account_id}/orders", headers=headers, json=body, timeout=15)
    d = r.json()
    if d.get("s") != "ok":
        print(f"  order rejected by broker: {d}")
        return None
    order_id = d.get("d", {}).get("orderId")
    print(f"  order placed: {order_id}")
    return order_id


def run_once(
    news_calendar: Optional[NewsCalendar] = None,
    cfg: SniperConfig = CONFIG,
    dry_run: bool = True,
    journal_csv: Optional[Path] = None,
) -> Dict:
    """One SCAN -> FILTER -> SCORE -> CONFIRM -> SIZE -> EXECUTE cycle,
    respecting every gate in scanner.run_pipeline. Meant to be called on a
    schedule (e.g. every 10-15 min during session hours) — same cadence as
    autopilot.py's existing loop, but routed through the smc_sniper scoring
    engine and safety modules instead of the older ad-hoc filters."""
    news_calendar = news_calendar or EmptyNewsCalendar()
    headers, account_id, equity = ta.auth()
    now = datetime.now(timezone.utc)

    daily_state = load_state(equity, now=now)
    ok, reason = can_trade(daily_state, equity, cfg, now)
    if not ok:
        return {"acted": False, "reason": reason}

    raw_setups = sn.scan_sniper(headers)
    if not raw_setups:
        return {"acted": False, "reason": "no sniper setups detected this scan"}

    open_positions = build_open_positions_context(headers, account_id, equity, cfg)
    current_spreads = {
        s["name"]: fetch_spread_pips(headers, s["cfg"]["id"], s["cfg"]["pip"]) for s in raw_setups
    }

    approved, rejected = run_pipeline(
        raw_setups, equity=equity, open_positions=open_positions,
        current_spreads=current_spreads, news_calendar=news_calendar,
        daily_state=daily_state, now=now, cfg=cfg,
    )

    placed = []
    for plan in approved:
        order_id = execute_plan(headers, account_id, plan, dry_run=dry_run)
        if not dry_run and order_id:
            record_trade_opened(daily_state)
            log_entry(
                trade_id=str(order_id), symbol=plan.symbol, direction=plan.direction,
                entry=plan.entry, stop_loss=plan.stop_loss, take_profit=plan.tp2,
                position_size_lots=plan.sizing.lots, account_equity=equity,
                dollar_risk=plan.sizing.dollar_risk, risk_pct=plan.sizing.risk_pct,
                setup_score=plan.score.total, htf_bias=str(plan.explanation["htf_bias"]),
                liquidity_swept=plan.explanation["liquidity"], structure_event=plan.explanation["structure"],
                order_block=plan.explanation["order_block"], fvg=plan.explanation["fvg"],
                premium_discount="n/a", session=plan.explanation["session"], news_status="clear",
                reason_for_entry=plan.explanation["reason"],
                csv_path=journal_csv or Path("smc_sniper_journal.csv"),
            )
            placed.append({"symbol": plan.symbol, "order_id": order_id, "lots": plan.sizing.lots})

    return {
        "acted": True, "approved": len(approved), "rejected": len(rejected),
        "placed": placed, "dry_run": dry_run,
        "rejected_reasons": [(r.symbol, r.reason) for r in rejected],
    }


if __name__ == "__main__":
    # Always starts dry. Flip dry_run=False here (or call run_once directly
    # with dry_run=False) only after reviewing dry-run output and confirming
    # TL_EMAIL/TL_PASSWORD are set via environment, not this file.
    result = run_once(dry_run=True)
    print(json.dumps(result, indent=2, default=str))
