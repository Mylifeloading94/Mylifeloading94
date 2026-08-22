"""
TradeLocker live/demo execution bot.

Implements exactly the rules in config.locked_params() and config.locked_risk()
against the TradeLocker REST API: M15 scan on the bar close, resting limit entry
inside the displacement leg, hard stop and target on every order, and the full
risk stack (fixed-fractional sizing, daily loss cap, concurrency and currency
caps, consecutive-loss lockout, session and spread filters).

    !!  READ THIS BEFORE RUNNING  !!
    The strategy this bot executes FAILED its out-of-sample backtest:
    2026-01-01..2026-08-22 returned -19.26% with a profit factor of 0.36.
    See REPORT.md. It is wired up so the logic is inspectable and re-testable,
    NOT because it is fit to trade. It refuses to run against a live account
    unless you explicitly override, and it defaults to demo.

Environment:
    TL_EMAIL, TL_PASSWORD, TL_SERVER, TL_ENV=demo|live

Usage:
    python3 live_bot.py --dry-run          # scan and print signals, place nothing
    python3 live_bot.py --demo             # trade the demo account
    python3 live_bot.py --live --i-understand-the-backtest-failed
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import numpy as np
import pandas as pd

import tl_data
import strategy as st
import config
from strategy import PIP, CONTRACT, QUOTE, BASE, SPREAD_PIPS

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_state.json")
POLL_SECONDS = 60


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S}Z] {msg}", flush=True)


# ---------------------------------------------------------------------------
class Broker:
    def __init__(self, client: tl_data.TLClient):
        self.c = client

    def account(self):
        r = self.c.session.get(
            f"{self.c.base}/trade/accounts/{self.c.account_id}/state",
            headers=self.c.headers, timeout=30)
        if r.status_code != 200:
            r = self.c.session.get(f"{self.c.base}/auth/jwt/all-accounts",
                                   headers={"Authorization": f"Bearer {self.c.access}"},
                                   timeout=30)
            a = r.json()["accounts"][0]
            return {"balance": float(a["accountBalance"]), "equity": float(a["accountBalance"])}
        d = r.json().get("d", {}).get("accountDetailsData", [])
        return {"balance": float(d[0]) if d else 0.0,
                "equity": float(d[1]) if len(d) > 1 else 0.0}

    def positions(self):
        r = self.c.session.get(
            f"{self.c.base}/trade/accounts/{self.c.account_id}/positions",
            headers=self.c.headers, timeout=30)
        r.raise_for_status()
        return r.json().get("d", {}).get("positions", [])

    def orders(self):
        r = self.c.session.get(
            f"{self.c.base}/trade/accounts/{self.c.account_id}/orders",
            headers=self.c.headers, timeout=30)
        r.raise_for_status()
        return r.json().get("d", {}).get("orders", [])

    def place_limit(self, symbol, side, qty, price, stop_loss, take_profit):
        body = {
            "tradableInstrumentId": tl_data.INSTRUMENTS[symbol],
            "routeId": tl_data.TRADE_ROUTE,
            "qty": round(qty, 2),
            "side": side,                       # "buy" | "sell"
            "type": "limit",
            "price": round(price, 5),
            "validity": "GTC",
            "stopLoss": round(stop_loss, 5),
            "stopLossType": "absolute",
            "takeProfit": round(take_profit, 5),
            "takeProfitType": "absolute",
        }
        r = self.c.session.post(
            f"{self.c.base}/trade/accounts/{self.c.account_id}/orders",
            headers={**self.c.headers, "Content-Type": "application/json"},
            json=body, timeout=30)
        return r.status_code, r.text

    def cancel(self, order_id):
        return self.c.session.delete(
            f"{self.c.base}/trade/accounts/{self.c.account_id}/orders/{order_id}",
            headers=self.c.headers, timeout=30).status_code


# ---------------------------------------------------------------------------
def usd_per_unit(symbol, price, rates):
    """USD value of one full price unit, per standard lot."""
    q = QUOTE[symbol]
    if q == "USD":
        return CONTRACT[symbol]
    direct = f"USD{q}"
    if direct in rates and rates[direct]:
        return CONTRACT[symbol] / rates[direct]
    inv = f"{q}USD"
    if inv in rates and rates[inv]:
        return CONTRACT[symbol] * rates[inv]
    return CONTRACT[symbol] / price          # last-resort approximation


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:                     # noqa: BLE001
            pass
    return {"day": None, "day_start_equity": None, "day_pnl": 0.0,
            "day_trades": 0, "consec_losses": 0, "placed": {}}


def save_state(s):
    json.dump(s, open(STATE_FILE, "w"), indent=1, default=str)


def run(mode, dry_run):
    p = config.locked_params()
    cfg = config.locked_risk()
    watchlist = [s for s in open("watchlist.txt").read().split() if s in tl_data.INSTRUMENTS]
    log(f"mode={mode} dry_run={dry_run} watchlist={watchlist}")

    client = tl_data.TLClient()
    broker = Broker(client)
    acct = broker.account()
    log(f"account {client.account_id} balance={acct['balance']:.2f} equity={acct['equity']:.2f}")

    state = load_state()
    seen_bar = {}

    while True:
        try:
            now = dt.datetime.now(dt.timezone.utc)
            today = now.date().isoformat()
            if state.get("day") != today:
                state.update(day=today, day_start_equity=acct["equity"],
                             day_pnl=0.0, day_trades=0, consec_losses=0)
                save_state(state)

            acct = broker.account()
            equity = acct["equity"] or acct["balance"]
            open_pos = broker.positions()
            open_syms = set()
            for pos in open_pos:
                for s, iid in tl_data.INSTRUMENTS.items():
                    if str(pos[1]) == str(iid) if len(pos) > 1 else False:
                        open_syms.add(s)

            # ---- daily guards -------------------------------------------
            dse = state.get("day_start_equity") or equity
            if dse and (equity - dse) / dse <= -cfg.max_daily_loss:
                log("daily loss cap reached - standing down until tomorrow")
                time.sleep(POLL_SECONDS); continue
            if state["day_trades"] >= cfg.max_trades_per_day:
                time.sleep(POLL_SECONDS); continue
            if state["consec_losses"] >= cfg.max_consecutive_losses:
                log("consecutive-loss lockout active")
                time.sleep(POLL_SECONDS); continue
            if len(open_pos) >= cfg.max_concurrent:
                time.sleep(POLL_SECONDS); continue

            # ---- refresh rates used for USD conversion -------------------
            rates = {}
            for cross in ("USDJPY", "USDCAD", "USDCHF", "USDSGD", "NZDUSD",
                          "AUDUSD", "GBPUSD", "EURUSD"):
                try:
                    b = client.bars(cross, "15m", now - dt.timedelta(days=3), now)
                    if b:
                        rates[cross] = float(b[-1]["c"])
                except Exception:              # noqa: BLE001
                    pass

            # ---- scan ----------------------------------------------------
            for sym in watchlist:
                if sym in open_syms:
                    continue
                try:
                    bars = client.bars(sym, "15m", now - dt.timedelta(days=40), now)
                except Exception as exc:       # noqa: BLE001
                    log(f"{sym}: history failed {exc}"); continue
                if len(bars) < 400:
                    continue
                df = tl_data.bars_to_frame(bars)
                # the final bar may still be forming - drop it
                df = df.iloc[:-1]
                last_ts = df.index[-1]
                if seen_bar.get(sym) == last_ts:
                    continue
                seen_bar[sym] = last_ts

                ctx = st.Context(sym, df, p)
                sig = st.evaluate(ctx, len(df) - 1)
                if sig is None:
                    continue

                risk_pct = cfg.risk_pct_gold if sym == "XAUUSD" else cfg.risk_pct
                risk_px = abs(sig.entry_ref - sig.stop)
                unit = usd_per_unit(sym, sig.entry_ref, rates)
                lots = np.floor((equity * risk_pct) / (risk_px * unit) / cfg.lot_step) * cfg.lot_step
                lots = float(np.clip(round(lots, 2), 0.0, cfg.max_lot))
                if lots < cfg.min_lot:
                    log(f"{sym}: size below minimum lot - skipped")
                    continue

                side = "buy" if sig.direction > 0 else "sell"
                log(f"SIGNAL {sym} {side.upper()} score={sig.score} "
                    f"entry={sig.entry_ref:.5f} sl={sig.stop:.5f} tp={sig.target:.5f} "
                    f"lots={lots} riskUSD={risk_px*unit*lots:.2f}")
                if dry_run:
                    continue
                code, txt = broker.place_limit(sym, side, lots, sig.entry_ref,
                                               sig.stop, sig.target)
                log(f"  -> order {code}: {txt[:200]}")
                if code in (200, 201):
                    state["day_trades"] += 1
                    save_state(state)

            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log("stopped"); return
        except Exception as exc:               # noqa: BLE001
            log(f"loop error: {exc}")
            time.sleep(POLL_SECONDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--i-understand-the-backtest-failed", action="store_true",
                    dest="ack")
    a = ap.parse_args()

    if a.live and not a.ack:
        print(__doc__)
        print("REFUSING to trade live. The out-of-sample backtest of this exact "
              "configuration lost 19.26% with a profit factor of 0.36.\n"
              "If you have read REPORT.md and still want to proceed, re-run with\n"
              "  --live --i-understand-the-backtest-failed")
        sys.exit(2)

    # --dry-run places nothing, so let it read whichever environment the
    # credentials in TL_ENV belong to; only an explicit --live/--demo pins it.
    if a.live:
        os.environ["TL_ENV"] = "live"
    elif a.demo:
        os.environ["TL_ENV"] = "demo"
    mode = os.environ.get("TL_ENV", "demo")
    if not (a.live or a.demo or a.dry_run):
        print(__doc__); sys.exit(0)
    run(mode, a.dry_run)


if __name__ == "__main__":
    main()
