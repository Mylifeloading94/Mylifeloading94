#!/usr/bin/env python3
"""SMC Sniper -- paper / dry-run signal scan.

Pulls the latest bars, runs the same signal engine the backtest uses, and
reports any A+ setups that qualify right now. Nothing is ordered: execution is
the in-memory paper broker and Telegram is in dry-run.

    python3 run_paper.py                 # scan with the active stack
    python3 run_paper.py --refresh       # re-pull bars first
    python3 run_paper.py --recent 20     # show the last N signals, not just live

Forward paper results are marked PENDING DEMO RUN everywhere in the reports --
this scanner is the mechanism for producing them, and it has not been run
forward for any meaningful period yet.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper.backtest import Backtester
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine
from smc_sniper.execution import PaperExecution
from smc_sniper.logging_engine import DecisionLog
from smc_sniper.news import NewsFilter
from smc_sniper.risk import RiskEngine
from smc_sniper.telegram import TelegramEngine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--recent", type=int, default=10)
    args = ap.parse_args()

    cfg = load_config()
    if args.stack:
        cfg.set("active_stack", args.stack)
    source = args.source or cfg.get("data.provider", "tradelocker")
    engine = DataEngine(cfg, source=source)
    if args.refresh:
        engine.download_all(force=True)

    news = NewsFilter(cfg)
    execution = PaperExecution(cfg)
    telegram = TelegramEngine(cfg)
    risk = RiskEngine(cfg)
    log = DecisionLog(cfg, "paper_scan")

    print(f"SMC Sniper paper scan -- stack '{cfg.stack['name']}', source '{source}'")
    print(f"Execution: {execution.name} (no broker orders)   "
          f"Telegram: dry_run={telegram.dry_run}   News: {news.status}")

    bt = Backtester(cfg, engine)
    contexts = bt.build_contexts()
    signals, rejections = bt.collect_signals(contexts)
    print(f"\n{len(signals)} qualifying setups found across {len(contexts)} pairs "
          f"({len(rejections)} rejected).")

    if not signals:
        print("No setups met the gate. Staying flat is the correct outcome.")
        return 0

    latest = signals[-args.recent:]
    for symbol, sig in latest:
        blocked, reason = news.blocked(sig.time)
        ok, risk_reason = risk.can_trade(symbol, sig)
        status = ("NEWS BLACKOUT" if blocked else
                  ("RISK BLOCKED: " + risk_reason) if not ok else "ELIGIBLE")
        print("\n" + "-" * 66)
        print(json.dumps(sig.explanation, indent=2, default=str))
        print(f"STATUS: {status}")
        log.signal(sig)
        if status == "ELIGIBLE":
            telegram.new_signal(sig)

    print("\n" + "=" * 66)
    print(f"Telegram messages formatted (none sent): {len(telegram.sent)}")
    for record in telegram.sent[-3:]:
        print(f"  [{record['kind']}] not sent -- {record['reason']}")
    print(f"Decision log: {log.path}")
    print("\nForward paper-trading results: PENDING DEMO RUN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
