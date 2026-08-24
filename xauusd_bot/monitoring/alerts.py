"""Alerting. Console always; Telegram only if explicitly configured."""
from __future__ import annotations

import os

import requests


class Alerter:
    def __init__(self):
        self.token = os.environ.get("TG_BOT_TOKEN")
        self.chat = os.environ.get("TG_CHAT_ID")

    def send(self, level: str, text: str) -> None:
        print(f"[{level}] {text}")
        if not (self.token and self.chat) or level == "DEBUG":
            return
        try:
            requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          json={"chat_id": self.chat, "text": f"[{level}] {text}"},
                          timeout=10)
        except requests.RequestException:
            pass
