#!/usr/bin/env python3
"""Deep intraday history fetch (TradeLocker, read-only).

Why this exists: a single ``/trade/history`` call on this broker returns at
most ~20-27k bars and answers an over-long range with an **empty** payload
rather than a truncated one. Earlier versions of this repo read that empty
payload as "5m history stops at ~120 days" and shelved the whole idea of a
validated scalping stack. It was wrong -- 5m bars are served at least 700 days
back, and 1m at least 200, once the request is chunked.

Usage::

    python3 fetch_deep.py --interval 5m  --days 700
    python3 fetch_deep.py --interval 15m --days 700
    python3 fetch_deep.py --interval 5m  --days 700 --symbols EURUSD,GBPUSD
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper.config import load_config
from smc_sniper.data import DataEngine


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--days", type=int, default=700)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    engine = DataEngine(cfg, source="tradelocker")
    symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
               or list(cfg.symbols))

    t0 = time.time()
    ok = 0
    for n, symbol in enumerate(symbols, 1):
        res = engine.download_deep(symbol, args.interval, args.days,
                                   verbose=args.verbose)
        tag = "ok  " if res.ok else "FAIL"
        span = f"{res.first[:10]}..{res.last[:10]}" if res.first else ""
        print(f"[{tag}] {n:2d}/{len(symbols)} {symbol:8s} {args.interval:4s} "
              f"{res.bars:7d} {span} {res.error}", flush=True)
        ok += bool(res.ok)
    print(f"done: {ok}/{len(symbols)} in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
