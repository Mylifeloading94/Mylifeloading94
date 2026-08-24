"""Terminal monitoring dashboard (spec section 40)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DashboardState:
    bot_status: str = "IDLE"
    mode: str = "demo"
    account_id: object = None
    balance: float = 0.0
    equity: float = 0.0
    daily_pl: float = 0.0
    weekly_pl: float = 0.0
    open_position: str = "none"
    price: float = 0.0
    spread: float = 0.0
    spread_state: str = "NORMAL"
    regime: str = "-"
    regime_conf: float = 0.0
    active_strategy: str = "-"
    setup_score: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    daily_risk_remaining: float = 0.0
    api_status: str = "DISCONNECTED"
    data_status: str = "NO DATA"
    kill_switch: str = "clear"
    last_update: str = ""
    notes: list = field(default_factory=list)


def render(s: DashboardState) -> str:
    s.last_update = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    w = 62
    def row(k, v): return f"│ {k:<26}{str(v):>{w - 30}} │"
    L = ["┌" + "─" * (w - 2) + "┐",
         f"│ {'XAUUSD BOT — ' + s.mode.upper():<{w - 4}} │",
         "├" + "─" * (w - 2) + "┤",
         row("BOT STATUS", s.bot_status),
         row("ACCOUNT", s.account_id),
         row("BALANCE", f"${s.balance:,.2f}"),
         row("EQUITY", f"${s.equity:,.2f}"),
         row("DAILY P/L", f"{s.daily_pl:+.2f}%"),
         row("WEEKLY P/L", f"{s.weekly_pl:+.2f}%"),
         row("OPEN POSITION", s.open_position),
         "├" + "─" * (w - 2) + "┤",
         row("XAUUSD PRICE", f"{s.price:,.2f}"),
         row("SPREAD", f"${s.spread:.2f}  [{s.spread_state}]"),
         row("REGIME", s.regime),
         row("REGIME CONFIDENCE", f"{100 * s.regime_conf:.0f}%"),
         row("ACTIVE STRATEGY", s.active_strategy),
         row("SETUP SCORE", f"{s.setup_score:.0f}/100"),
         "├" + "─" * (w - 2) + "┤",
         row("TRADES TODAY", s.trades_today),
         row("CONSECUTIVE LOSSES", s.consecutive_losses),
         row("DAILY RISK REMAINING", f"{s.daily_risk_remaining:.2f}%"),
         row("API STATUS", s.api_status),
         row("DATA STATUS", s.data_status),
         row("KILL SWITCH", s.kill_switch),
         row("LAST UPDATE", s.last_update),
         "└" + "─" * (w - 2) + "┘"]
    for n in s.notes[-5:]:
        L.append(f"  • {n}")
    return "\n".join(L)
