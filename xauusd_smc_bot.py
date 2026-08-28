#!/usr/bin/env python3
"""
XAUUSD SMC trading bot — entry point.

    python3 xauusd_smc_bot.py --check       # verify credentials + connectivity
    python3 xauusd_smc_bot.py --once        # run a single scan and exit
    python3 xauusd_smc_bot.py --dry-run     # scan + alert, never send orders
    python3 xauusd_smc_bot.py               # run forever, scanning every 60s

Credentials are read from the environment or a gitignored .env file:
    TL_ENV, TL_EMAIL, TL_PASSWORD, TL_SERVER, TL_ACCOUNT_ID
    TG_BOT_TOKEN, TG_CHAT_ID
See .env.example.
"""
from __future__ import annotations

import argparse
import logging
import sys

from xauusd_smc.bot import Bot, setup_logging
from xauusd_smc.config import Config
from xauusd_smc.tradelocker import TradeLockerError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="XAUUSD SMC bot")
    p.add_argument("--once", action="store_true", help="single scan then exit")
    p.add_argument("--check", action="store_true",
                   help="verify credentials, instrument and Telegram, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="analyse and alert but never place an order")
    p.add_argument("--env", choices=["demo", "live"], help="override TL_ENV")
    p.add_argument("--min-grade", choices=["B", "A", "A+"], help="override MIN_GRADE")
    p.add_argument("--interval", type=int, help="override scan seconds")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.from_env()
    if args.env:
        cfg.tl_env = args.env
    if args.dry_run:
        cfg.dry_run = True
    if args.min_grade:
        cfg.min_grade = args.min_grade
    if args.interval:
        cfg.scan_seconds = args.interval

    setup_logging(cfg, args.verbose)
    log = logging.getLogger("xauusd_smc")

    missing = cfg.missing_credentials()
    if missing:
        log.error("missing credentials: %s", ", ".join(missing))
        log.error("copy .env.example to .env and fill it in (the .env file is "
                  "gitignored), or export the variables in your shell.")
        return 2

    if cfg.is_live and cfg.confirm_live != "I_UNDERSTAND":
        log.error("TL_ENV=live requires TL_CONFIRM_LIVE=I_UNDERSTAND. Refusing to "
                  "trade real money without that explicit acknowledgement.")
        return 2

    bot = Bot(cfg)

    if args.check:
        try:
            bot.broker.login()
            equity = bot.broker.equity()
            ins = bot.broker.instrument(cfg.symbol)
            quote = bot.broker.quote(cfg.symbol)
            log.info("✅ TradeLocker OK — %s account %s, equity $%.2f",
                     cfg.tl_env, bot.broker.account_id, equity)
            log.info("✅ Instrument %s id=%s trade_route=%s",
                     ins.get("name"), ins.get("tradableInstrumentId"),
                     ins.get("_trade_route"))
            log.info("✅ Quote bid=%.2f ask=%.2f spread=$%.2f",
                     quote.get("bid", 0), quote.get("ask", 0), quote.get("spread", 0))
            for tf in ("H4", "H1", "M15", "M5"):
                log.info("✅ %s bars: %d", tf, len(bot.bars(tf)))
            ok = bot.tg.send("✅ <b>XAUUSD SMC BOT — connection check passed</b>\n\n"
                             f"{cfg.tl_env.upper()} account "
                             f"<code>{bot.broker.account_id}</code>\n"
                             f"Equity ${equity:,.2f} • spread "
                             f"${quote.get('spread', 0):.2f}")
            log.info("%s Telegram", "✅" if ok else "❌")
            return 0
        except (TradeLockerError, KeyError, ValueError) as e:
            log.error("❌ check failed: %s", e)
            return 1

    if args.once:
        try:
            bot.broker.login()
            setup = bot.cycle()
            log.info("single scan complete — %s",
                     f"{setup.grade} {setup.direction}" if setup else "no setup")
            return 0
        except (TradeLockerError, KeyError, ValueError) as e:
            log.error("scan failed: %s", e)
            return 1

    bot.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
