"""Phase 9 -- Telegram notification engine (dry-run).

No bot token exists, so this module **never sends anything**. It formats
messages and records them; ``dry_run`` defaults to true and the token is only
ever read from an environment variable, never from a committed file.

Balance is withheld from every message unless ``telegram.show_balance`` is
explicitly enabled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _fmt(value: float, digits: int = 5) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


@dataclass
class TelegramEngine:
    cfg: object
    sent: list = field(default_factory=list)

    def __post_init__(self):
        self.tcfg = self.cfg.get("telegram", {}) or {}
        self.enabled = bool(self.tcfg.get("enabled", False))
        self.dry_run = bool(self.tcfg.get("dry_run", True))
        self.show_balance = bool(self.tcfg.get("show_balance", False))
        self.token = os.environ.get(self.tcfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
        self.chat_id = os.environ.get(self.tcfg.get("chat_id_env", "TELEGRAM_CHAT_ID"))

    # -- transport --------------------------------------------------------
    def send(self, text: str, kind: str = "info") -> dict:
        """Record a message. Sends only if enabled, not dry-run, and configured."""
        record = {"kind": kind, "text": text, "sent": False, "reason": ""}
        if not self.enabled:
            record["reason"] = "telegram disabled in config"
        elif self.dry_run:
            record["reason"] = "dry_run=true -- message formatted, not sent"
        elif not (self.token and self.chat_id):
            record["reason"] = "no TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in env"
        else:
            # Real send would go here. Never exercised in this repository.
            record["reason"] = "live send path not enabled in this build"
        self.sent.append(record)
        return record

    def _notify_on(self, key: str) -> bool:
        return bool((self.tcfg.get("notify", {}) or {}).get(key, True))

    # -- message formatters ------------------------------------------------
    def new_signal(self, sig) -> dict | None:
        if not self._notify_on("new_signal"):
            return None
        ex = sig.explanation
        lines = [
            f"SNIPER SIGNAL -- {ex['pair']} {ex['direction']}",
            f"Score: {ex['score']}/100  ({ex['confidence']} confidence)",
            f"HTF bias: {ex['htf_bias']}   Session: {ex['session']}",
            f"Liquidity: {ex['liquidity']}   Structure: {ex['structure']}",
            f"Setup: {ex['setup_type']}  |  Zone: {ex['zone']}",
            "",
            f"Entry : {_fmt(ex['entry'])}",
            f"Stop  : {_fmt(ex['stop_loss'])}  ({ex['stop_pips']} pips)",
            f"TP1   : {_fmt(ex['tp1'])}  ({ex['rr_tp1']}R)",
            f"TP2   : {_fmt(ex['tp2'])}  ({ex['rr_tp2']}R)",
            f"TP3   : {_fmt(ex['tp3'])}  ({ex['rr_tp3']}R)",
            f"Risk  : {ex['risk_pct']}%   Spread: {ex['spread_pips']} pips",
            "",
            "Why:",
        ]
        lines += [f"  - {r}" for r in ex["reasons"]]
        return self.send("\n".join(lines), "new_signal")

    def entry_filled(self, trade) -> dict | None:
        if not self._notify_on("entry_filled"):
            return None
        return self.send(
            f"FILLED {trade.symbol} {trade.side.upper()} @ {_fmt(trade.entry)}\n"
            f"Stop {_fmt(trade.stop)}  |  size {trade.size_lots} lots", "entry_filled")

    def tp_hit(self, trade, stage: str, price: float, portion: float) -> dict | None:
        if not self._notify_on("tp_hit"):
            return None
        return self.send(
            f"{stage} HIT {trade.symbol} @ {_fmt(price)} -- closed {portion:.0%}",
            "tp_hit")

    def breakeven_moved(self, trade, price: float) -> dict | None:
        if not self._notify_on("breakeven_moved"):
            return None
        return self.send(f"BREAK-EVEN {trade.symbol} -- stop moved to {_fmt(price)}",
                         "breakeven_moved")

    def sl_hit(self, trade) -> dict | None:
        if not self._notify_on("sl_hit"):
            return None
        return self.send(
            f"STOPPED {trade.symbol} @ {_fmt(trade.exit_price)} "
            f"({trade.r_multiple:+.2f}R)", "sl_hit")

    def daily_summary(self, stats: dict) -> dict | None:
        if not self._notify_on("daily_summary"):
            return None
        lines = [
            "DAILY SUMMARY",
            f"Trades: {stats.get('trades', 0)}   "
            f"Wins: {stats.get('wins', 0)}   Losses: {stats.get('losses', 0)}",
            f"Win rate: {stats.get('win_rate', 0):.1f}%   "
            f"Net R: {stats.get('total_r', 0):+.2f}",
        ]
        if self.show_balance:
            lines.append(f"Balance: {stats.get('final_balance', 0):.2f}")
        return self.send("\n".join(lines), "daily_summary")

    def error(self, message: str) -> dict | None:
        if not self._notify_on("error"):
            return None
        return self.send(f"ERROR: {message}", "error")
