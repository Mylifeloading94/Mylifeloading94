#!/usr/bin/env python3
"""
XAUUSD SMC Sniper Engine — command line entry point.

  python3 xau_bot.py scan                 one full scan, printed to the terminal
  python3 xau_bot.py run                  the 60-second live scanner loop
  python3 xau_bot.py serve                the web dashboard (TradingView + SMC chart)
  python3 xau_bot.py backtest             rebuild the validated win-rate statistics
  python3 xau_bot.py stats                show the validated historical performance
  python3 xau_bot.py perf                 show live-tracked performance
  python3 xau_bot.py history              show the signal history
  python3 xau_bot.py chart --out x.html   write the dashboard to a static file
  python3 xau_bot.py selftest             internal consistency checks

Stdlib only — no third-party packages required.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from xausmc import render
from xausmc.config import MODES, EngineConfig
from xausmc.engine import Engine


def _cfg(args) -> EngineConfig:
    cfg = EngineConfig.load(getattr(args, "config", None))
    if getattr(args, "provider", None):
        cfg.provider = args.provider
    if getattr(args, "state_dir", None):
        cfg.state_dir = args.state_dir
    if getattr(args, "modes", None):
        cfg.modes = tuple(m.strip().upper() for m in args.modes.split(","))
    if getattr(args, "balance", None):
        cfg.risk.account_balance = args.balance
    if getattr(args, "risk", None):
        cfg.risk.risk_per_trade_pct = args.risk / 100.0
    if getattr(args, "any_session", False):
        cfg.risk.allowed_sessions = ("ASIA", "LONDON", "LONDON_NY_OVERLAP", "NEW_YORK", "ROLLOVER")
    return cfg


# --------------------------------------------------------------------------
def cmd_scan(args) -> int:
    eng = Engine(_cfg(args))
    res = eng.scan()
    if args.json:
        print(json.dumps({"feed": res.feed.__dict__, "price": res.price, "bias": res.bias,
                          "regime": res.regime, "session": res.session,
                          "headline": res.headline,
                          "setups": [s.as_dict() for s in res.setups],
                          "rejected": [{"mode": s.mode, "pattern": s.pattern,
                                        "direction": s.direction, "score": s.score,
                                        "reason": s.invalid_reason} for s in res.rejected],
                          "guard": res.guard.__dict__, "notes": res.notes},
                         indent=2, default=str))
        return 0
    ctx = eng._contexts.get(res.best.mode) if res.best else eng._contexts.get("INTRADAY")
    series = ctx.ltf.series if ctx else None
    print(render.dashboard(res, eng, series, show_confluence=not args.brief))
    return 0


def cmd_run(args) -> int:
    eng = Engine(_cfg(args))
    print(f"XAUUSD SMC sniper — scanning every {args.interval}s. Ctrl-C to stop.\n")
    try:
        while True:
            t0 = time.time()
            res = eng.scan()
            ctx = eng._contexts.get(res.best.mode) if res.best else eng._contexts.get("INTRADAY")
            print("\033[2J\033[H" if not args.no_clear else "")
            print(render.dashboard(res, eng, ctx.ltf.series if ctx else None,
                                   show_confluence=not args.brief))
            wait = max(5.0, args.interval - (time.time() - t0))
            time.sleep(wait)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def cmd_serve(args) -> int:
    from xausmc.web import serve
    eng = Engine(_cfg(args))
    serve(eng, args.host, args.port, args.interval, args.tv_symbol)
    return 0


def cmd_chart(args) -> int:
    from xausmc.web import render_page
    eng = Engine(_cfg(args))
    res = eng.scan()
    html = render_page(eng, res, args.tv_symbol, args.interval)
    with open(args.out, "w") as fh:
        fh.write(html)
    print(f"wrote {args.out} ({len(html):,} bytes) — {res.headline}")
    return 0


def cmd_backtest(args) -> int:
    from xausmc import backtest
    cfg = _cfg(args)
    print("HISTORICAL BACKTEST — this produces the win rates the live bot is allowed to show.")
    print(f"  provider={args.provider}  min_grade={args.min_grade}  spread=${args.spread}")
    plan = None
    if args.bars or args.base_tf:
        plan = [(args.base_tf or "M5", args.bars or 150_000, list(cfg.modes))]
    store, meta = backtest.run_multi(cfg, plan=plan, provider=args.provider,
                                     min_grade=args.min_grade, spread=args.spread,
                                     out_dir=cfg.state_dir)
    print()
    print(render.stats_panel(store, limit=25))
    print(f"\n  wrote {cfg.path('stats.json')} and {cfg.path('backtest_trades.json')}")
    return 0


def cmd_stats(args) -> int:
    from xausmc.stats import StatsStore
    cfg = _cfg(args)
    store = StatsStore.load(cfg.path("stats.json"))
    print(render.stats_panel(store, limit=args.limit))
    if args.breakdowns:
        for name, buckets in store.breakdowns.items():
            print(render.rule("─", name.replace("_", " ").upper()))
            for k, b in sorted(buckets.items()):
                print(f"  {k:26} n={b.n:<5} {b.win_rate:>5.1f}%  PF {b.profit_factor:>5.2f}  "
                      f"avg R:R 1:{b.target_rr:<5.2f} expectancy {b.expectancy_r:+.2f}R")
    return 0


def cmd_perf(args) -> int:
    from xausmc.performance import build
    eng = Engine(_cfg(args))
    print(render.performance_panel(build(eng.journal)))
    return 0


def cmd_history(args) -> int:
    eng = Engine(_cfg(args))
    print(render.history_panel(eng.journal, args.limit))
    return 0


def cmd_config(args) -> int:
    cfg = _cfg(args)
    path = cfg.save(args.out)
    print(f"wrote {path}")
    print(json.dumps({"modes": list(cfg.modes), "timeframes": cfg.timeframes,
                      "state_dir": cfg.state_dir}, indent=2))
    return 0


def cmd_selftest(args) -> int:
    from xausmc.selftest import run_selftest
    return run_selftest()


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="xau_bot.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to a JSON config file")
    p.add_argument("--state-dir", help="where signals.jsonl / stats.json live (default: state)")
    p.add_argument("--provider", choices=["tradelocker", "binance", "yahoo"],
                   help="force a data provider instead of auto-failover")
    p.add_argument("--modes", help="comma separated: SCALP,INTRADAY,SWING")
    p.add_argument("--balance", type=float, help="account balance for position sizing")
    p.add_argument("--risk", type=float, help="risk per trade, in percent (e.g. 0.5)")
    p.add_argument("--any-session", action="store_true",
                   help="do not filter setups by trading session")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="one full scan")
    s.add_argument("--json", action="store_true")
    s.add_argument("--brief", action="store_true", help="hide the confluence breakdown")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("run", help="continuous 60-second scanner")
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--brief", action="store_true")
    s.add_argument("--no-clear", action="store_true", help="do not clear the screen each scan")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("serve", help="web dashboard with the TradingView chart")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--tv-symbol", default="OANDA:XAUUSD")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("chart", help="write the dashboard to a static HTML file")
    s.add_argument("--out", default="xauusd_dashboard.html")
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--tv-symbol", default="OANDA:XAUUSD")
    s.set_defaults(fn=cmd_chart)

    s = sub.add_parser("backtest", help="rebuild the validated win-rate statistics")
    s.add_argument("--provider", default="binance", choices=["binance", "yahoo", "tradelocker"])
    s.add_argument("--bars", type=int, help="override the bar count for a single-base run")
    s.add_argument("--base-tf", choices=["M1", "M5", "M15"],
                   help="override the base timeframe for a single-base run")
    s.add_argument("--min-grade", default="C", choices=["A+", "A", "B", "C"])
    s.add_argument("--spread", type=float, default=0.25, help="XAUUSD spread in USD")
    s.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("stats", help="show validated historical performance")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--breakdowns", action="store_true")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("perf", help="show live-tracked performance")
    s.set_defaults(fn=cmd_perf)

    s = sub.add_parser("history", help="show the signal history")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(fn=cmd_history)

    s = sub.add_parser("config", help="write a config file you can edit")
    s.add_argument("--out", default="xausmc.config.json")
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("selftest", help="internal consistency checks")
    s.set_defaults(fn=cmd_selftest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
