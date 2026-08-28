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
from xausmc.config import EngineConfig
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


def cmd_trade(args) -> int:
    """Automatic execution loop against TradeLocker."""
    import os

    from xausmc.broker import BrokerError, TradeLockerBroker
    from xausmc.executor import ExecConfig, Executor

    cfg = _cfg(args)
    cfg.modes = tuple(m.strip().upper() for m in args.modes.split(","))
    ex = ExecConfig(modes=cfg.modes, min_grade=args.min_grade,
                    risk_pct=args.risk / 100.0, max_open=args.max_open,
                    max_trades_per_day=args.max_trades, poll_sec=args.interval,
                    daily_loss_pct=args.daily_loss / 100.0,
                    max_consecutive_losses=args.max_consecutive_losses,
                    dry_run=not args.execute)

    env = os.environ.get("TL_ENV", "demo").lower()
    print(render.rule("═", f"AUTOMATIC EXECUTION — {env.upper()}"))
    mode_line = ("DRY RUN — orders are printed, nothing is sent"
                 if ex.dry_run else "EXECUTING — orders will be sent to the broker")
    print(f"  {render.BOLD}{mode_line}{render.RESET}")
    if not ex.dry_run and env == "live":
        print(f"  {render.RED}{render.BOLD}THIS IS A LIVE ACCOUNT. REAL MONEY.{render.RESET}")
    print(f"  filter    {'/'.join(ex.modes)} setups, grade {ex.min_grade} and above")
    print(f"  risk      {args.risk:.2f}% per trade · max {ex.max_open} open · "
          f"max {ex.max_trades_per_day}/day")
    print(f"  stand-down  daily loss {args.daily_loss:.1f}% · "
          f"{ex.max_consecutive_losses} consecutive losses")
    print(f"  scan      every {ex.poll_sec}s")

    try:
        broker = TradeLockerBroker(env=env)
        acct = broker.connect()
    except BrokerError as exc:
        print(f"\n  {render.RED}broker connection failed:{render.RESET} {exc}")
        print(f"  {render.DIM}Set TL_EMAIL, TL_PASSWORD, TL_SERVER (and TL_ENV=demo|live) "
              f"in the environment.{render.RESET}")
        return 1

    print(f"  account   {acct.id} ({acct.env}) · balance {acct.balance:,.2f} "
          f"{acct.currency} · equity {acct.equity:,.2f}")
    try:
        ins = broker.instrument("XAUUSD")
        bid, ask = broker.quote("XAUUSD")
        print(f"  instrument {ins['name']} id={ins['id']} · bid {bid} / ask {ask}")
    except BrokerError as exc:
        print(f"\n  {render.RED}instrument check failed:{render.RESET} {exc}")
        return 1
    print(render.rule("─"))

    engine = Engine(cfg)
    ex_engine = Executor(engine, broker, ex)
    try:
        while True:
            t0 = time.time()
            try:
                out = ex_engine.cycle()
            except BrokerError as exc:
                print(f"  {render.RED}broker error:{render.RESET} {exc}")
                out = {}
            res = out.get("scan")
            stamp = time.strftime("%H:%M:%S", time.gmtime())
            if res is not None:
                print(f"  {render.DIM}{stamp}{render.RESET} {res.headline} · "
                      f"equity {out.get('equity', 0):,.2f} · open "
                      f"{out.get('open_positions', 0)} · basis {out.get('basis', 0):+.2f}")
            for n in out.get("notes", []):
                print(f"      {render.DIM}{n}{render.RESET}")
            for b in out.get("blocked", []):
                print(f"      {render.YELLOW}blocked:{render.RESET} {b}")
            for p in out.get("placed", []):
                tag = "[dry run] would send" if p.get("dry_run") else "SENT"
                if p.get("error"):
                    print(f"      {render.RED}skipped:{render.RESET} {p['error']}")
                    continue
                print(f"      {render.GREEN}{tag}{render.RESET} {p['side'].upper()} "
                      f"{p['qty']} lots {p['symbol']} {p['order_type']} @ {p['entry']:,.2f} "
                      f"SL {p['stop_loss']:,.2f} TP {p['take_profit']:,.2f} "
                      f"({p['sl_pips']} pips, ${p['risk_usd']} risk, grade {p['grade']})")
            if args.once:
                break
            time.sleep(max(5.0, ex.poll_sec - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\n  stopped. Open positions keep their broker-side stop loss and take "
              "profit — this loop is not what protects them.")
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

    s = sub.add_parser("trade", help="automatic execution loop against TradeLocker")
    s.add_argument("--execute", action="store_true",
                   help="actually send orders. Without this it is a dry run.")
    s.add_argument("--risk", type=float, default=0.5, dest="risk",
                   help="risk per trade in percent of equity (default 0.5)")
    s.add_argument("--modes", default="SCALP", help="comma separated (default SCALP)")
    s.add_argument("--min-grade", default="A", choices=["A+", "A", "B", "C"],
                   help="lowest grade to execute (default A)")
    s.add_argument("--max-open", type=int, default=1)
    s.add_argument("--max-trades", type=int, default=6, help="per day")
    s.add_argument("--daily-loss", type=float, default=6.0,
                   help="stand down for the day after this percent of equity is lost")
    s.add_argument("--max-consecutive-losses", type=int, default=3)
    s.add_argument("--interval", type=int, default=60, help="seconds between scans")
    s.add_argument("--once", action="store_true", help="run a single cycle and exit")
    s.set_defaults(fn=cmd_trade)

    s = sub.add_parser("selftest", help="internal consistency checks")
    s.set_defaults(fn=cmd_selftest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
