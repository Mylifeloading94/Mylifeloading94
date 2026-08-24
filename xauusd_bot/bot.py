#!/usr/bin/env python3
"""
XAUUSD TradeLocker bot entry point.

    python xauusd_bot/bot.py --mode demo
    python xauusd_bot/bot.py --mode live --confirm-live

The bot refuses to place any order until the deployment gate passes. It also
refuses to start live without --confirm-live AND LIVE_TRADING=true.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from xauusd_bot.config import from_env
from xauusd_bot.data.data_engine import DataEngine
from xauusd_bot.deployment_gate import passed, render, run_checks
from xauusd_bot.execution.execution_guard import ExecutionGuard
from xauusd_bot.execution.order_manager import OrderManager
from xauusd_bot.execution.position_manager import PositionManager
from xauusd_bot.execution.tradelocker_client import (TradeLockerClient, TradeLockerError,
                                                     TransportError)
from xauusd_bot.journal.trade_journal import TradeJournal
from xauusd_bot.monitoring.alerts import Alerter
from xauusd_bot.monitoring.dashboard import DashboardState, render as render_dash
from xauusd_bot.news.news_filter import NewsFilter
from xauusd_bot.risk.kill_switch import KillSwitch
from xauusd_bot.risk.risk_manager import RiskManager
from xauusd_bot.strategy import regime_engine, selector, setup_scorer
from xauusd_bot.backtesting.simulator import spread_series

RESOLUTION_MINUTES = 1


def build_state(client, cfg, ins) -> tuple[pd.DataFrame, float]:
    """Pull recent M1 history from the broker and build the feature matrix."""
    end = int(time.time() * 1000)
    start = end - 1000 * 60 * 60 * 24 * 12          # 12 days of M1
    raw = client.history(ins, "1", start, end)
    bars = (raw.get("d") or {}).get("barDetails") or raw.get("barDetails") or []
    if not bars:
        raise TradeLockerError("no history returned")
    df = pd.DataFrame(bars)
    cols = {c.lower(): c for c in df.columns}
    df = df.rename(columns={cols.get("t", "t"): "t", cols.get("o", "o"): "open",
                            cols.get("h", "h"): "high", cols.get("l", "l"): "low",
                            cols.get("c", "c"): "close"})
    df["time"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    m1 = df.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
    age = (pd.Timestamp.utcnow() - m1.index[-1]).total_seconds()
    return DataEngine().build(m1), age


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["demo", "live"], default="demo")
    ap.add_argument("--confirm-live", action="store_true")
    ap.add_argument("--skip-gate", action="store_true",
                    help="print the gate but continue (dry inspection only)")
    ap.add_argument("--once", action="store_true", help="single iteration then exit")
    ap.add_argument("--poll", type=int, default=20, help="seconds between iterations")
    a = ap.parse_args()

    alert = Alerter()
    cfg = from_env()
    cfg.initial_equity = float(os.environ.get("INITIAL_EQUITY", 500))

    checks = run_checks()
    print(render(checks))
    gate_ok = passed(checks)
    if not gate_ok and not a.skip_gate:
        alert.send("CRITICAL", "deployment gate FAILED - no orders will be placed")
        return 2

    if a.mode == "live":
        if not a.confirm_live:
            print("live mode requires --confirm-live"); return 2
        if not cfg.live_trading:
            print("live mode requires LIVE_TRADING=true in the environment"); return 2

    kill = KillSwitch()
    journal = TradeJournal()
    news = NewsFilter.load(cfg.news)
    client = TradeLockerClient(env=a.mode)
    dash = DashboardState(mode=a.mode)

    try:
        client.login()
        acct = client.select_account()
        ins = client.find_gold()
    except (TradeLockerError, TransportError) as e:
        alert.send("CRITICAL", f"cannot start: {e}")
        return 3

    # adopt the broker's real contract specification rather than assuming
    cfg.instrument.min_lot = ins.min_lot
    cfg.instrument.lot_step = ins.lot_step
    dash.account_id, dash.api_status = acct.id, "CONNECTED"
    alert.send("INFO", f"connected {a.mode} acct={acct.id} instrument={ins.name} "
                       f"min_lot={ins.min_lot}")

    guard = ExecutionGuard(client, cfg, kill)
    risk = RiskManager(cfg, acct.balance or cfg.initial_equity)
    om = OrderManager(guard, risk, cfg, ins)
    pm = PositionManager(client, cfg, ins)
    live_pos = None

    while True:
        try:
            state = client.account_state()
            d = state.get("d", state)
            equity = float(d.get("equity") or d.get("accountBalance") or acct.balance)
            F, age = build_state(client, cfg, ins)
            guard.last_quote_ts = time.time() - age
            row = F.iloc[-1]
            R = regime_engine.classify(F, cfg.regime)
            sig, _ = selector.select(F, R, cfg)
            sp = spread_series(F, cfg)
            sc = setup_scorer.score(F, sig, sp, cfg)

            ts = F.index[-1]
            risk.on_bar(ts, row["tday"], equity)
            risk.check_locks(ts)

            dash.balance = float(d.get("accountBalance") or equity)
            dash.equity = equity
            dash.price = float(row["close"])
            dash.spread = float(sp.iloc[-1])
            dash.spread_state = ("BLOCKED" if dash.spread > cfg.costs.max_spread
                                 else "WARNING" if dash.spread > cfg.costs.max_spread * 0.7
                                 else "NORMAL")
            dash.regime = str(R["regime"].iloc[-1])
            dash.regime_conf = float(R["regime_conf"].iloc[-1])
            dash.active_strategy = str(sig["strategy"].iloc[-1]) or "-"
            dash.setup_score = float(sc["setup_score"].iloc[-1])
            dash.trades_today = risk.s.trades_today
            dash.consecutive_losses = risk.s.consecutive_losses
            dash.daily_risk_remaining = max(
                0.0, cfg.risk.max_daily_loss_percent + risk._daily_pl_pct())
            dash.daily_pl = risk._daily_pl_pct()
            dash.weekly_pl = risk._weekly_pl_pct()
            dash.data_status = f"OK ({age:.0f}s)" if age < cfg.execution.max_data_age_seconds \
                else f"STALE ({age:.0f}s)"
            dash.kill_switch = "TRIPPED: " + "; ".join(kill.reasons) if kill.tripped else "clear"

            broker_positions = client.positions()
            dash.open_position = (f"{len(broker_positions)} open"
                                  if broker_positions else "none")
            dash.bot_status = "HALTED" if kill.tripped else (
                "LOCKED" if (risk.s.daily_locked or risk.s.weekly_locked) else "SCANNING")

            # manage an existing position
            if live_pos and broker_positions:
                for act in pm.manage(live_pos, dash.price):
                    journal.record_event("MANAGE", act, ts)
                    alert.send("INFO", act)
            elif live_pos and not broker_positions:
                journal.record_event("CLOSED", f"position {live_pos.position_id} gone", ts)
                risk.on_close(0.0, equity, ts)
                live_pos = None

            # end-of-day flat
            if row["hour"] >= cfg.sessions.flat_by_utc and broker_positions:
                alert.send("INFO", pm.flatten_all())
                live_pos = None

            # new entry
            direction = int(sig["dir"].iloc[-1])
            can_trade = (not kill.tripped and guard.data_is_fresh()
                         and dash.spread_state != "BLOCKED"
                         and not news.blackout_mask(F.index[-1:]).iloc[0]
                         and dash.setup_score >= cfg.score.threshold
                         and live_pos is None and not broker_positions)
            if direction != 0 and can_trade and gate_ok:
                stop = float(sig["sl"].iloc[-1])
                rdist = abs(dash.price - stop)
                tp1 = dash.price + direction * cfg.exits.tp1_r * rdist
                tp2 = dash.price + direction * cfg.exits.tp2_r * rdist
                out, why = om.open_trade(direction, dash.price, stop, tp1, tp2,
                                         float(row["M5_atr"]))
                journal.record_signal(ts=ts, regime=dash.regime, regime_conf=dash.regime_conf,
                                      strategy=dash.active_strategy, direction=direction,
                                      setup_score=dash.setup_score, spread=dash.spread,
                                      decision=why, reject_reason="" if out else why)
                if isinstance(out, tuple):
                    _, live_pos = out
                    alert.send("INFO", f"OPENED {dash.active_strategy} {direction:+d} "
                                       f"@ {live_pos.entry} sl={live_pos.stop}")
                else:
                    alert.send("INFO", f"no trade: {why}")
            elif direction != 0:
                journal.record_signal(ts=ts, regime=dash.regime, regime_conf=dash.regime_conf,
                                      strategy=dash.active_strategy, direction=direction,
                                      setup_score=dash.setup_score, spread=dash.spread,
                                      decision="BLOCKED",
                                      reject_reason="gate/guard/session conditions")

            print("\033[2J\033[H" + render_dash(dash))

        except TransportError as e:
            kill.trip(f"transport failure: {e}")
            alert.send("WARN", f"disconnected: {e} - reconciling")
            try:
                client.login(); client.select_account(acct.id)
                out = guard.reconcile()
                if out.get("ok"):
                    kill.reset(operator_ack=True)
                    alert.send("INFO", f"reconciled: {out}")
            except (TradeLockerError, TransportError) as e2:
                alert.send("CRITICAL", f"reconnect failed: {e2}")
        except TradeLockerError as e:
            alert.send("WARN", f"api error: {e}")
        except KeyboardInterrupt:
            alert.send("INFO", "shutdown requested")
            break

        if a.once:
            break
        time.sleep(a.poll)

    journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
