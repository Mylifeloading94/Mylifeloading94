"""Telegram notifications — trade alerts, management updates, errors."""
from __future__ import annotations

import logging
import os


import requests

log = logging.getLogger("xauusd_smc.notify")

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(cfg.tg_enabled and cfg.tg_token and cfg.tg_chat)
        if not self.enabled:
            log.warning("Telegram disabled (missing token/chat id)")

    def send(self, text: str, silent: bool = False) -> bool:
        if not self.enabled:
            log.info("[telegram-off] %s", text.replace("\n", " | ")[:200])
            return False
        try:
            r = requests.post(API.format(token=self.cfg.tg_token, method="sendMessage"),
                              json={"chat_id": self.cfg.tg_chat, "text": text,
                                    "parse_mode": "HTML",
                                    "disable_notification": silent},
                              timeout=20)
            if r.status_code != 200:
                log.error("telegram send failed %s: %s", r.status_code, r.text[:200])
                return False
            return True
        except requests.RequestException as e:
            log.error("telegram send error: %s", e)
            return False

    def photo(self, path: str, caption: str = "") -> bool:
        if not self.enabled or not path or not os.path.exists(path):
            return self.send(caption) if caption else False
        try:
            with open(path, "rb") as f:
                r = requests.post(API.format(token=self.cfg.tg_token, method="sendPhoto"),
                                  data={"chat_id": self.cfg.tg_chat, "caption": caption,
                                        "parse_mode": "HTML"},
                                  files={"photo": f}, timeout=40)
            if r.status_code != 200:
                log.error("telegram photo failed %s: %s", r.status_code, r.text[:200])
                return self.send(caption)
            return True
        except (requests.RequestException, OSError) as e:
            log.error("telegram photo error: %s", e)
            return self.send(caption)


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------
def trade_alert(setup, lots: float, risk_usd: float, equity: float,
                order_id, env: str, dry: bool) -> str:
    arrow = "📈" if setup.direction == "bullish" else "📉"
    side = "BUY" if setup.direction == "bullish" else "SELL"
    tag = "🧪 <b>DRY RUN</b> — not sent to broker\n\n" if dry else ""
    return (
        f"{tag}🔥 <b>TRADE PLACED</b> 🔥\n\n"
        f"{arrow} <b>{setup.symbol} {side}</b>  •  grade <b>{setup.grade}</b>\n"
        f"💰 Entry: <code>{setup.entry:.2f}</code>\n"
        f"🛑 Stop:  <code>{setup.sl:.2f}</code>  ({setup.sl_pips:.2f} pips)\n"
        f"🎯 TP1:   <code>{setup.tp1:.2f}</code>  ({setup.rr_tp1:.1f}R — close "
        f"50%, SL→BE)\n"
        f"🎯 TP2:   <code>{setup.tp2:.2f}</code>  ({setup.rr_tp2:.1f}R)\n\n"
        f"📦 Size: <b>{lots:.2f} lots</b>  •  risk <b>${risk_usd:,.0f}</b> "
        f"({risk_usd/equity*100:.1f}% of ${equity:,.0f})\n"
        f"🧠 {' | '.join(setup.reasons[:5])}\n"
        f"🏦 {env.upper()} • order <code>{order_id}</code>"
    )


def breakeven_alert(name: str, symbol: str, be_price: float, closed_lots: float) -> str:
    return (
        f"🔒 <b>TP1 HIT — RISK REMOVED</b>\n\n"
        f"{symbol} {name}\n"
        f"✅ Closed {closed_lots:.2f} lots (50%) at TP1\n"
        f"🛡 Stop moved to breakeven <code>{be_price:.2f}</code>\n"
        f"🏃 Runner active to TP2"
    )


def close_alert(symbol: str, side: str, pnl: float, pips: float, reason: str) -> str:
    icon = "🟢" if pnl >= 0 else "🔴"
    return (
        f"{icon} <b>TRADE CLOSED</b>\n\n"
        f"{symbol} {side.upper()}\n"
        f"P/L: <b>${pnl:,.2f}</b>  ({pips:+.2f} pips)\n"
        f"Reason: {reason}"
    )


def halt_alert(reason: str, detail: str) -> str:
    return f"⛔️ <b>TRADING HALTED</b>\n\n{reason}\n{detail}"
