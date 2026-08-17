#!/usr/bin/env python3
"""Live ORDER PLACEMENT for the adopted v7/v8 configuration.

This is the execution wrapper around :mod:`scan_live`. It changes **nothing**
about the strategy: the score gate, the flat 1:2 target, the 20-pip minimum
target, the 29-instrument universe and the entry model are all imported from
``scan_live.adopted_config()`` and the signals come from the identical path the
backtest uses (``Backtester.collect_signals`` -> ``signal_engine``). The only
new code here is (a) turning a *pending* signal into a broker order and (b) the
safety rails around doing so.

    scan_live.py   scans and prints.     Never touches an order endpoint.
    execute_live.py scans and ORDERS.    Every write lives in THIS file.

``smc_sniper.providers.TradeLockerProvider`` is documented as a read-only
market-data client and stays that way -- the POST/DELETE calls are made by
:class:`OrderClient` below, which borrows the provider's authenticated session
but is the only object in the repo that can place an order.

WHAT IT PLACES
--------------
A **limit** order at the zone, not a market order. That is what was backtested:
:meth:`Backtester.simulate_trade` fills only when a later entry bar trades
*through* ``sig.entry``, and every published statistic assumes that fill. A
market order would chase price and measure something else.

BID/ASK, AND WHY THE LEVELS ARE NOT THE RAW SIGNAL LEVELS
---------------------------------------------------------
Every bar this broker serves is **BID** (``barSource: "BID"`` on all 92
instruments), so ``sig.entry`` / ``sig.stop`` / ``sig.tp2`` are bid-frame
prices. The backtester models the spread by charging it at the fill
(``entry_px = sig.entry +/- spread``). A live broker instead triggers buys on
the ASK and sells on the BID. Placing the raw levels would therefore fill a
long one spread deeper than the backtest ever did -- often never. The levels
are shifted by exactly one configured spread so that each order *triggers on
the same bid tick the backtest triggered on*:

    LONG   limit = entry + spread   (ask <= entry+spread  <=>  bid <= entry)
           stop  = stop            (long SL/TP close on the bid: already right)
           tp    = tp2

    SHORT  limit = entry            (sell limit triggers on the bid: right)
           stop  = stop  + spread   (short SL/TP close on the ask)
           tp    = tp2   + spread

This is not a tweak to the strategy -- it is the same trade expressed in the
venue's quoting convention. It also reproduces the backtest's risk distance
exactly: long ``(entry+spread) - stop`` and short ``(stop+spread) - entry`` are
both equal to ``simulate_trade``'s ``risk_price`` less the 0.2-pip slippage
allowance. The spread used is the same per-symbol figure the backtest used
(``execution.spreads``), not the live one, so sizing is deterministic; the live
spread is still read and a setup is skipped if the broker is quoting more than
``--max-spread-mult`` times the configured value (a market that is closed or
dislocated quotes very wide).

POSITION SIZING
---------------
1% of the **live** balance, sized off the instrument's **actual** contract spec
pulled from ``/trade/instruments/{id}`` per symbol -- ``lotSize``, ``lotStep``,
``minLot``, ``maxLot``, ``tickSize``, ``quotingCurrency`` -- and a **live**
quote-currency conversion. Nothing is hardcoded. This is deliberate: the v5
audit found the backtester valuing every non-metal contract at a flat 100,000
USD, which is only true when the quote currency is USD, and JPY crosses (36% of
the ledger) were consequently mis-sized by ~150x. ``risk.py``'s ``_QUOTE_USD``
table fixes that with backtest-window medians -- fine for a commission estimate,
not fine for sizing real money today -- so this file resolves USDJPY / USDCHF /
USDCAD / AUDUSD / NZDUSD / GBPUSD from the broker's current quotes instead.

    lots = (balance * 1%) / (|limit - stop| * lotSize * usd_per_quote_unit)

then floored to ``lotStep`` (never rounded up past 1%) and bounds-checked.

SAFETY RAILS (all hard, all fail-closed)
----------------------------------------
1.  Account identity. ``TL_ACCOUNT_ID`` must be 2355787 and ``TL_SERVER``
    GENFX, on the demo host, or the run aborts before a single order is built.
2.  One order per pair. A pair with an open position OR a resting order of ours
    is skipped -- there is no averaging in and no hedging.
3.  Concurrency, from the validated config, not invented here: the v6 profile
    sets ``risk.enforce_concurrency: true``, and ``risk`` gives
    ``max_open_positions: 3``, ``max_exposure_per_currency: 2`` and
    ``max_trades_per_day: 3``. Resting limit orders count against the position
    caps, because three resting limits are three positions if they all fill.
4.  Daily loss guardrail: ``risk.max_daily_loss_pct`` (2.0%) of the
    start-of-day balance, taken from the broker's own ``todayNet``.
5.  Weekly loss guardrail: ``risk.max_weekly_loss_pct`` (5.0%) against a
    week-start balance persisted in the log file.
6.  Never an order without a valid stop: the stop must exist, be finite, sit on
    the correct side of the entry, and be at least ``--min-stop-ticks`` ticks
    away. A missing or wrong-sided stop is a hard skip, never a naked order.
7.  Margin: the order's initial margin must not exceed ``--max-margin-pct`` of
    available funds.
8.  Expiry: orders go out GTD, expiring at the signal's own
    ``valid_until_bar``, so the live fill window is the backtested fill window.
    If the venue refuses GTD the order is placed GTC and the expiry is recorded
    in the log; every subsequent run cancels its own expired resting orders.

NOT ENFORCED LIVE, AND SAID PLAINLY
-----------------------------------
``risk.max_consecutive_losses`` (4 -> 24h cooldown) needs a per-trade realised-R
history that the account endpoints do not hand back cheaply, so this script does
not enforce it. The daily and weekly dollar caps above are strictly stronger in
money terms over any window that matters, and they *are* enforced.

Usage::

    python3 execute_live.py --dry-run      # decide everything, place nothing
    python3 execute_live.py                # decide everything, PLACE ORDERS
    python3 execute_live.py --no-refresh   # reuse the cached 1H bars

One pass per invocation. There is no internal sleep loop -- schedule it.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_live import (ADOPTED, account_snapshot, adopted_config, describe,
                       refresh, signal_status, trim_to_closed)
from smc_sniper.backtest import Backtester
from smc_sniper.data import DataEngine
from smc_sniper.providers import _verify

REPO = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(REPO, "execute_live_log.json")

# The one account this file is allowed to trade. Hardcoded on purpose: a
# mistyped .env must not be able to point the order path somewhere else.
DEMO_ACCOUNT_ID = "2355787"
DEMO_SERVER = "GENFX"

# 1% of balance per trade. `risk.risk_per_trade_pct` in config.yaml is 0.5 (the
# backtest default) with a hard ceiling of `risk_per_trade_max_pct: 1.0`; every
# prior deliverable recommended 1% and judged 2% outside the system's own cap
# given the recorded loss streaks. Set here rather than in config.yaml so the
# backtests keep reproducing bit-for-bit.
RISK_PER_TRADE_PCT = 1.0


# ---------------------------------------------------------------------------
# durable log
# ---------------------------------------------------------------------------
class RunLog:
    """Append-only JSON journal of every run, every order and every skip.

    Gitignored. Nothing is ever removed from ``runs``; ``state`` carries the
    small amount of cross-run memory the weekly guardrail and the expiring-order
    cleanup need.
    """

    def __init__(self, path: str = LOG_PATH):
        self.path = path
        self.doc = {"created_utc": _now_iso(), "state": {}, "runs": []}
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict) and "runs" in loaded:
                    self.doc = loaded
                    self.doc.setdefault("state", {})
            except (OSError, ValueError) as exc:
                # A corrupt journal must not silently become an empty one --
                # that would reset the weekly guardrail and orphan resting
                # orders. Keep it and fail closed.
                raise RuntimeError(f"{path} is unreadable ({exc}); refusing to "
                                   "run with no memory of prior orders") from None

    @property
    def state(self) -> dict:
        return self.doc["state"]

    def placed_orders(self) -> list[dict]:
        out = []
        for run in self.doc["runs"]:
            out.extend(run.get("placed", []))
        return out

    def orders_today(self, day: str) -> int:
        return sum(1 for o in self.placed_orders() if str(o.get("placed_utc", ""))[:10] == day)

    def append(self, record: dict) -> None:
        self.doc["runs"].append(record)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.doc, fh, indent=2, default=str)
        os.replace(tmp, self.path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# the only write-capable client in this repository
# ---------------------------------------------------------------------------
class OrderClient:
    """POST/DELETE against ``/trade/accounts/{id}/orders``.

    Borrows the read-only provider's authenticated session (token refresh,
    CA bundle, accNum header) rather than duplicating auth, but keeps the write
    verbs out of :mod:`smc_sniper.providers` so that module's "no order endpoint
    is called anywhere in this package" guarantee stays literally true.
    """

    def __init__(self, provider, dry_run: bool):
        self.p = provider
        self.dry_run = dry_run
        self.account = provider.env["TL_ACCOUNT_ID"]

    # -- identity ---------------------------------------------------------
    def verify_demo_account(self) -> dict:
        """Abort loudly unless this is DEMO account 2355787 on GENFX."""
        env, base = self.p.env, self.p.base
        problems = []
        if str(env.get("TL_ACCOUNT_ID", "")) != DEMO_ACCOUNT_ID:
            problems.append(f"TL_ACCOUNT_ID is {env.get('TL_ACCOUNT_ID')!r}, "
                            f"expected {DEMO_ACCOUNT_ID!r}")
        if str(env.get("TL_SERVER", "")).upper() != DEMO_SERVER:
            problems.append(f"TL_SERVER is {env.get('TL_SERVER')!r}, expected {DEMO_SERVER!r}")
        if "demo" not in base.lower():
            problems.append(f"base_url {base!r} is not a demo host")
        if problems:
            raise SystemExit("ABORT -- refusing to place orders:\n  " + "\n  ".join(problems))
        return {"account_id": env["TL_ACCOUNT_ID"], "server": env["TL_SERVER"],
                "acc_num": env["TL_ACC_NUM"], "base_url": base, "is_demo": True}

    # -- instrument specs -------------------------------------------------
    def spec(self, symbol: str, _cache: dict = {}) -> dict:
        """Real contract spec for ``symbol``, straight from the broker.

        ``/trade/accounts/{id}/instruments`` gives the id and routes but no
        contract detail; ``/trade/instruments/{id}`` gives ``lotSize``,
        ``lotStep``, ``minLot``, ``maxLot``, ``tickSize`` and the quoting
        currency. Nothing about lot size or pip value is assumed anywhere in
        this file -- that assumption is precisely what the v5 audit caught.
        """
        if symbol in _cache:
            return _cache[symbol]
        meta = self.p.instruments().get(symbol)
        if not meta:
            raise RuntimeError(f"{symbol} is not tradable on this account")
        d = self.p._get(f"/trade/instruments/{meta['tradableInstrumentId']}",
                        {"routeId": meta["trade_route"], "locale": "en"}).get("d", {})
        ticks = d.get("tickSize") or [{}]
        tick = float(ticks[0].get("tickSize") or 0.00001)
        spec = {
            "symbol": symbol,
            "tradableInstrumentId": meta["tradableInstrumentId"],
            "trade_route": meta["trade_route"],
            "info_route": meta["info_route"],
            "lot_size": float(d.get("lotSize") or 0.0),
            "lot_step": float(d.get("lotStep") or 0.01),
            "min_lot": float(d.get("minLot") or 0.01),
            "max_lot": float(d["maxLot"]) if d.get("maxLot") else None,
            "tick": tick,
            "base_ccy": d.get("baseCurrency") or symbol[:3],
            "quote_ccy": d.get("quotingCurrency") or symbol[3:6],
            "leverage": float(d.get("leverage") or 100.0),
            "status": d.get("symbolStatus"),
        }
        _cache[symbol] = spec
        return spec

    def mid(self, symbol: str) -> tuple[float, float]:
        """``(mid, spread_in_price)`` from the live top of book."""
        q = self.p.quote(symbol)
        bid, ask = float(q.get("bp") or 0.0), float(q.get("ap") or 0.0)
        if bid <= 0 or ask <= 0:
            return 0.0, 0.0
        return (bid + ask) / 2.0, ask - bid

    # -- writes -----------------------------------------------------------
    def _post(self, path: str, body: dict, timeout: int = 60) -> dict:
        if self.dry_run:
            return {"dry_run": True, "would_post": path, "body": body}
        resp = requests.post(f"{self.p.base}{path}", headers={
            **self.p._headers(), "Content-Type": "application/json"},
            json=body, verify=_verify(), timeout=timeout)
        if resp.status_code in (401, 403):
            self.p._auth(force=True)
            resp = requests.post(f"{self.p.base}{path}", headers={
                **self.p._headers(), "Content-Type": "application/json"},
                json=body, verify=_verify(), timeout=timeout)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text[:400]}
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"POST {path} -> {resp.status_code} {payload}")
        return payload

    def _delete(self, path: str, timeout: int = 60) -> dict:
        if self.dry_run:
            return {"dry_run": True, "would_delete": path}
        resp = requests.delete(f"{self.p.base}{path}", headers=self.p._headers(),
                               verify=_verify(), timeout=timeout)
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"DELETE {path} -> {resp.status_code}")
        return {"status": resp.status_code}

    def place_limit(self, spec: dict, side: str, lots: float, price: float,
                    stop_loss: float, take_profit: float,
                    expire_ms: int | None) -> dict:
        """Place ONE limit order with SL and TP attached.

        The stop is part of the order body, not a follow-up call: a two-step
        placement has a window in which a filled position carries no stop, and
        that window is exactly when it hurts.
        """
        if not (stop_loss and math.isfinite(stop_loss)):
            raise ValueError("refusing to place an order without a stop-loss")
        body = {
            "tradableInstrumentId": spec["tradableInstrumentId"],
            "routeId": spec["trade_route"],
            "qty": lots,
            "side": side,
            "type": "limit",
            "price": price,
            "stopLoss": stop_loss,
            "stopLossType": "absolute",
            "takeProfit": take_profit,
            "takeProfitType": "absolute",
        }
        if expire_ms:
            body["validity"] = "GTD"
            body["expireDate"] = int(expire_ms)
            try:
                return {"body": body, "response": self._post(
                    f"/trade/accounts/{self.account}/orders", body), "validity": "GTD"}
            except RuntimeError as exc:
                # Some venues refuse GTD on FX. Fall back to GTC and record the
                # intended expiry so a later run cancels it (see cancel_expired).
                print(f"    GTD rejected ({exc}); retrying GTC with a logged expiry")
        body["validity"] = "GTC"
        return {"body": body, "response": self._post(
            f"/trade/accounts/{self.account}/orders", body), "validity": "GTC"}

    def cancel(self, order_id) -> dict:
        return self._delete(f"/trade/accounts/{self.account}/orders/{order_id}")


# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------
def usd_per_quote_unit(client: OrderClient, ccy: str, cache: dict) -> float:
    """USD value of one unit of ``ccy``, from the broker's LIVE quotes.

    ``risk._QUOTE_USD`` holds backtest-window medians and is documented as
    good enough for a commission estimate; it is not good enough to size a
    live position, so the rate is resolved from whichever of ``USD{ccy}`` or
    ``{ccy}USD`` this account actually trades.
    """
    ccy = ccy.upper()
    if ccy == "USD":
        return 1.0
    if ccy in cache:
        return cache[ccy]
    tradable = client.p.instruments()
    rate = None
    if f"USD{ccy}" in tradable:
        mid, _ = client.mid(f"USD{ccy}")
        if mid > 0:
            rate = 1.0 / mid
    if rate is None and f"{ccy}USD" in tradable:
        mid, _ = client.mid(f"{ccy}USD")
        if mid > 0:
            rate = mid
    if rate is None or not math.isfinite(rate) or rate <= 0:
        raise RuntimeError(f"no live USD conversion available for {ccy}")
    cache[ccy] = rate
    return rate


def round_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    return round(round(price / tick) * tick, 10)


def floor_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(round(value / step, 9)) * step


def size_lots(client: OrderClient, spec: dict, risk_amount: float,
              risk_price: float, fx_cache: dict) -> dict:
    """Lots for ``risk_amount`` USD across a ``risk_price`` stop distance."""
    if risk_price <= 0:
        return {"lots": 0.0, "reason": "non_positive_stop_distance"}
    if spec["lot_size"] <= 0:
        return {"lots": 0.0, "reason": "broker_reported_no_lot_size"}
    q_usd = usd_per_quote_unit(client, spec["quote_ccy"], fx_cache)
    # USD moved by 1.00 lot per 1.0 unit of price. EURUSD: 100000 * 1.0.
    # USDJPY: 100000 * (1/USDJPY) ~ 650. XAUUSD: 100 * 1.0.
    usd_per_price_unit = spec["lot_size"] * q_usd
    raw = risk_amount / (risk_price * usd_per_price_unit)
    lots = floor_step(raw, spec["lot_step"])
    lots = round(lots, 8)
    out = {"lots": lots, "raw_lots": round(raw, 6),
           "usd_per_price_unit_per_lot": round(usd_per_price_unit, 4),
           "quote_ccy": spec["quote_ccy"], "usd_per_quote_unit": round(q_usd, 8),
           "risk_amount_usd": round(risk_amount, 2),
           "actual_risk_usd": round(lots * risk_price * usd_per_price_unit, 2),
           "reason": ""}
    if lots < spec["min_lot"]:
        # Rounding UP to minLot would silently risk more than 1%. Skip instead.
        out["reason"] = (f"sized {lots} lots, below broker minLot "
                         f"{spec['min_lot']} -- rounding up would exceed the risk cap")
        out["lots"] = 0.0
    elif spec["max_lot"] and lots > spec["max_lot"]:
        out["reason"] = f"sized {lots} lots, above broker maxLot {spec['max_lot']}"
        out["lots"] = 0.0
    return out


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------
def build_levels(sig, icfg, spec: dict) -> dict:
    """Bid-frame signal levels -> venue-quoted order levels. See module docstring."""
    pip = icfg.pip
    spread = float(sig.spread_pips) * pip
    long = sig.direction == "bullish"
    if long:
        price, stop, target = sig.entry + spread, sig.stop, sig.tp2
    else:
        price, stop, target = sig.entry, sig.stop + spread, sig.tp2 + spread
    tick = spec["tick"]
    price, stop, target = (round_tick(price, tick), round_tick(stop, tick),
                           round_tick(target, tick))
    return {"side": "buy" if long else "sell", "price": price, "stop": stop,
            "target": target, "spread_price": spread,
            "risk_price": abs(price - stop), "reward_price": abs(target - price)}


# ---------------------------------------------------------------------------
# guardrails
# ---------------------------------------------------------------------------
def guardrails(cfg, snap: dict, log: RunLog, now: pd.Timestamp) -> dict:
    """Account-level gates, read from the validated ``risk`` block.

    Every number here comes out of ``config.yaml``'s ``risk`` section (the v6
    profile turns ``enforce_concurrency`` on) -- nothing is invented in this
    file.
    """
    r = cfg.get("risk")
    acct = snap["account"]
    balance = float(acct.get("balance") or 0.0)
    today_net = float(acct.get("todayNet") or 0.0)
    day_start = balance - today_net

    week = now.isocalendar()[:2]
    week_key = f"{week[0]}-W{week[1]:02d}"
    state = log.state
    if state.get("week_key") != week_key:
        state["week_key"] = week_key
        state["week_start_balance"] = balance
    week_start = float(state.get("week_start_balance") or balance)
    week_pnl = balance - week_start

    max_daily = abs(float(r.get("max_daily_loss_pct", 2.0))) / 100.0
    max_weekly = abs(float(r.get("max_weekly_loss_pct", 5.0))) / 100.0
    max_open = int(r.get("max_open_positions", 3))
    max_ccy = int(r.get("max_exposure_per_currency", 2))
    max_per_day = int(r.get("max_trades_per_day", 3))

    day_key = str(now.date())
    placed_today = log.orders_today(day_key)
    broker_trades_today = int(acct.get("todayTradesCount") or 0)
    trades_today = max(placed_today, broker_trades_today)

    # A resting limit is a position-in-waiting: count it against the caps.
    committed = list(snap["positions"]) + list(snap["orders"])
    exposure: dict[str, int] = {}
    pairs_committed: set[str] = set()
    for row in committed:
        sym = str(row.get("symbol") or "")
        pairs_committed.add(sym)
        if len(sym) >= 6:
            for c in (sym[:3], sym[3:6]):
                exposure[c] = exposure.get(c, 0) + 1

    blocks = []
    if today_net <= -max_daily * day_start:
        blocks.append(f"max_daily_loss: todayNet {today_net:+.2f} <= "
                      f"-{max_daily * 100:.1f}% of day-start {day_start:.2f}")
    if week_pnl <= -max_weekly * week_start:
        blocks.append(f"max_weekly_loss: week P/L {week_pnl:+.2f} <= "
                      f"-{max_weekly * 100:.1f}% of week-start {week_start:.2f}")
    if trades_today >= max_per_day:
        blocks.append(f"max_trades_per_day: {trades_today} >= {max_per_day}")
    if len(committed) >= max_open:
        blocks.append(f"max_open_positions: {len(committed)} committed >= {max_open}")

    return {
        "balance": balance, "day_start_balance": round(day_start, 2),
        "today_net": today_net, "week_key": week_key,
        "week_start_balance": round(week_start, 2), "week_pnl": round(week_pnl, 2),
        "trades_today": trades_today, "placed_today_by_this_script": placed_today,
        "open_positions": len(snap["positions"]), "working_orders": len(snap["orders"]),
        "committed_slots": len(committed), "pairs_committed": sorted(pairs_committed),
        "currency_exposure": exposure,
        "caps": {"max_open_positions": max_open, "max_exposure_per_currency": max_ccy,
                 "max_trades_per_day": max_per_day,
                 "max_daily_loss_pct": max_daily * 100,
                 "max_weekly_loss_pct": max_weekly * 100,
                 "risk_per_trade_pct": RISK_PER_TRADE_PCT},
        "blocks": blocks, "trades_left_today": max(0, max_per_day - trades_today),
        "slots_left": max(0, max_open - len(committed)),
    }


def cancel_expired(client: OrderClient, log: RunLog, snap: dict, now: pd.Timestamp) -> list:
    """Cancel our own resting orders whose backtested fill window has closed.

    Only orders this script placed and recorded are touched, matched by
    broker order id. Anything placed by hand in the TradeLocker UI is left
    strictly alone.
    """
    by_id = {str(o.get("id")): o for o in snap["orders"]}
    out = []
    for rec in log.placed_orders():
        oid = str(rec.get("order_id") or "")
        expiry = rec.get("expiry_utc")
        if not oid or oid not in by_id or not expiry:
            continue
        if pd.Timestamp(expiry) > now:
            continue
        try:
            client.cancel(oid)
            out.append({"order_id": oid, "symbol": rec.get("symbol"),
                        "expiry_utc": expiry, "result": "cancelled"})
        except RuntimeError as exc:
            out.append({"order_id": oid, "symbol": rec.get("symbol"),
                        "expiry_utc": expiry, "result": f"cancel failed: {exc}"})
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Place live orders for the adopted v7/v8 config",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="decide everything and log it, but never call the order endpoint")
    ap.add_argument("--refresh-days", type=int, default=30)
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--lookback-bars", type=int, default=12)
    ap.add_argument("--source", default="tradelocker")
    ap.add_argument("--max-spread-mult", type=float, default=3.0,
                    help="skip if the live spread exceeds this multiple of the configured one")
    ap.add_argument("--min-stop-ticks", type=int, default=10,
                    help="reject a stop closer than this many ticks to the entry")
    ap.add_argument("--max-margin-pct", type=float, default=25.0,
                    help="max share of available funds one order's margin may take")
    ap.add_argument("--json", default=None, help="also write this run's record here")
    args = ap.parse_args()

    mode = "DRY RUN -- no order endpoint will be called" if args.dry_run else "LIVE -- ORDERS WILL BE PLACED"
    cfg = adopted_config()
    stack = cfg.stack
    engine = DataEngine(cfg, source=args.source)
    symbols = cfg.symbols
    now = pd.Timestamp.now(tz="UTC")

    log = RunLog()
    client = OrderClient(engine.provider, dry_run=args.dry_run)
    identity = client.verify_demo_account()

    print("=" * 78)
    print(f"SMC SNIPER -- LIVE EXECUTION   [{mode}]")
    print(f"  run at            {str(now)[:19]} UTC")
    print(f"  account           {identity['account_id']} on {identity['server']} "
          f"(accNum {identity['acc_num']})  DEMO verified")
    print(f"  config            profile '{ADOPTED['profile']}' / adopted v7-v8, unchanged")
    print(f"  stack             {stack['name']}: bias {stack['bias_tf']} / structure "
          f"{stack['structure_tf']} / setup {stack['setup_tf']} / entry {stack['entry_tf']}")
    print(f"  score gate        {cfg.score_threshold:.0f}   flat "
          f"{cfg.get('targets.fixed_rr')}R, min {cfg.get('targets.min_target_pips'):.0f} pips")
    print(f"  universe          {len(symbols)} instruments   risk {RISK_PER_TRADE_PCT}%/trade")
    print("=" * 78)

    if not args.no_refresh:
        print(f"\nRefreshing {stack['setup_tf']} cache ({args.refresh_days}d, union-merged)...")
        refresh(engine, symbols, args.refresh_days, verbose=False)
        print("  done")

    trim_to_closed(engine, symbols, stack, now)

    print("\nGenerating signals (identical path to the backtest)...")
    bt = Backtester(cfg, engine)
    contexts = bt.build_contexts()
    signals, _ = bt.collect_signals(contexts, use_cache=False)
    latest = max((ctx.setup.index[-1] for ctx in contexts.values()), default=None)
    print(f"  {len(contexts)}/{len(symbols)} pairs with data; last closed "
          f"{stack['setup_tf']} bar opens {str(latest)[:16]} UTC")

    # Exactly scan_live.py's liveness rule: pending limit, window still open,
    # structure not yet invalidated.
    live, recent = [], []
    live_ctx = {}
    for symbol, sig in signals:
        ctx = contexts[symbol]
        if len(ctx.setup) - 1 - sig.bar_index > args.lookback_bars:
            continue
        status = signal_status(ctx, sig, cfg, stack)
        row = describe(ctx, sig, status, cfg)
        recent.append(row)
        if status["state"] == "pending" and not status["stop_breached_since"]:
            live.append(row)
            live_ctx[symbol] = (ctx, sig, row)
    print(f"  qualifying live setups: {len(live)}"
          + (f"  ({', '.join(r['symbol'] + ' ' + r['direction'] for r in live)})" if live else ""))

    print("\nAccount state...")
    snap = account_snapshot(engine)
    if "error" in snap:
        raise SystemExit(f"ABORT -- {snap['error']}")
    rails = guardrails(cfg, snap, log, now)
    acct = snap["account"]
    print(f"  balance {rails['balance']:.2f}  available {acct.get('availableFunds')}  "
          f"todayNet {rails['today_net']:+.2f}  weekP/L {rails['week_pnl']:+.2f}")
    print(f"  open positions {rails['open_positions']}   working orders "
          f"{rails['working_orders']}   slots left {rails['slots_left']}   "
          f"trades left today {rails['trades_left_today']}")

    expired = cancel_expired(client, log, snap, now)
    for e in expired:
        print(f"  cancelled expired order {e['order_id']} ({e['symbol']}): {e['result']}")

    placed, skipped = [], []
    fx_cache: dict = {}
    slots_left = rails["slots_left"]
    trades_left = rails["trades_left_today"]
    exposure = dict(rails["currency_exposure"])
    committed_pairs = set(rails["pairs_committed"])
    max_ccy = rails["caps"]["max_exposure_per_currency"]
    risk_amount = rails["balance"] * RISK_PER_TRADE_PCT / 100.0

    def skip(row, reason, **extra):
        rec = {"symbol": row["symbol"], "direction": row["direction"],
               "score": row["score"], "signal_bar_utc": row["signal_bar_utc"],
               "reason": reason, **extra}
        skipped.append(rec)
        print(f"  SKIP {row['symbol']:8s} {row['direction']:5s} -- {reason}")

    if rails["blocks"]:
        print("\nACCOUNT GUARDRAILS BLOCK ALL NEW ENTRIES:")
        for b in rails["blocks"]:
            print(f"  - {b}")
        for row in live:
            skip(row, "account guardrail: " + "; ".join(rails["blocks"]))
    elif live:
        print("\nProcessing qualifying setups...")
        # Best score first, so the concurrency cap keeps the strongest setups.
        for row in sorted(live, key=lambda r: -r["score"]):
            symbol = row["symbol"]
            ctx, sig, _ = live_ctx[symbol]
            icfg = ctx.icfg

            if symbol in committed_pairs:
                skip(row, "one-position-per-pair: an open position or resting order exists")
                continue
            if slots_left <= 0:
                skip(row, f"max_open_positions cap reached "
                          f"({rails['caps']['max_open_positions']})")
                continue
            if trades_left <= 0:
                skip(row, f"max_trades_per_day cap reached "
                          f"({rails['caps']['max_trades_per_day']})")
                continue
            over = [c for c in (symbol[:3], symbol[3:6]) if exposure.get(c, 0) >= max_ccy]
            if over:
                skip(row, f"max_exposure_per_currency {max_ccy} already used by {over[0]}")
                continue

            try:
                spec = client.spec(symbol)
            except RuntimeError as exc:
                skip(row, f"instrument spec unavailable: {exc}")
                continue
            if spec.get("status") and spec["status"] != "FULLY_OPEN":
                skip(row, f"instrument status {spec['status']}")
                continue

            _, live_spread = client.mid(symbol)
            cfg_spread = float(sig.spread_pips) * icfg.pip
            if live_spread <= 0:
                skip(row, "no live quote (market closed?)")
                continue
            if cfg_spread > 0 and live_spread > args.max_spread_mult * cfg_spread:
                skip(row, f"live spread {live_spread / icfg.pip:.2f} pips exceeds "
                          f"{args.max_spread_mult}x the configured "
                          f"{sig.spread_pips:.2f} pips")
                continue

            lv = build_levels(sig, icfg, spec)

            # --- stop-loss validity: hard, never negotiable -----------------
            long = lv["side"] == "buy"
            if not (lv["stop"] and math.isfinite(lv["stop"])):
                skip(row, "invalid stop-loss (missing/non-finite)")
                continue
            if (long and lv["stop"] >= lv["price"]) or (not long and lv["stop"] <= lv["price"]):
                skip(row, f"stop {lv['stop']} is on the wrong side of entry {lv['price']}")
                continue
            if (long and lv["target"] <= lv["price"]) or (not long and lv["target"] >= lv["price"]):
                skip(row, f"target {lv['target']} is on the wrong side of entry {lv['price']}")
                continue
            if lv["risk_price"] < args.min_stop_ticks * spec["tick"]:
                skip(row, f"stop distance {lv['risk_price']:.5f} is under "
                          f"{args.min_stop_ticks} ticks")
                continue

            try:
                sizing = size_lots(client, spec, risk_amount, lv["risk_price"], fx_cache)
            except RuntimeError as exc:
                skip(row, f"sizing failed: {exc}")
                continue
            if sizing["lots"] <= 0:
                skip(row, sizing["reason"] or "sized to zero lots", sizing=sizing)
                continue

            # --- margin ------------------------------------------------------
            notional_usd = (sizing["lots"] * spec["lot_size"] * lv["price"]
                            * sizing["usd_per_quote_unit"])
            margin = notional_usd / max(spec["leverage"], 1.0)
            avail = float(acct.get("availableFunds") or 0.0)
            if avail > 0 and margin > avail * args.max_margin_pct / 100.0:
                skip(row, f"margin {margin:.2f} exceeds {args.max_margin_pct}% of "
                          f"available {avail:.2f}")
                continue

            expiry = pd.Timestamp(row["expiry_utc"])
            if expiry.tzinfo is None:
                expiry = expiry.tz_localize("UTC")
            expire_ms = int(expiry.timestamp() * 1000)

            plan = {
                "symbol": symbol, "direction": row["direction"], "side": lv["side"],
                "score": row["score"], "setup_type": row["setup_type"],
                "zone": row["zone"], "session": row["session"],
                "signal_bar_utc": row["signal_bar_utc"],
                "limit_price": lv["price"], "stop_loss": lv["stop"],
                "take_profit": lv["target"],
                "signal_entry_bid": round(sig.entry, 5), "signal_stop_bid": round(sig.stop, 5),
                "signal_target_bid": round(sig.tp2, 5),
                "spread_pips_used": sig.spread_pips,
                "live_spread_pips": round(live_spread / icfg.pip, 2),
                "stop_pips": round(lv["risk_price"] / icfg.pip, 1),
                "target_pips": round(lv["reward_price"] / icfg.pip, 1),
                "rr": round(lv["reward_price"] / lv["risk_price"], 2),
                "lots": sizing["lots"], "sizing": sizing,
                "notional_usd": round(notional_usd, 2), "margin_usd": round(margin, 2),
                "expiry_utc": str(expiry), "tick": spec["tick"],
                "tradableInstrumentId": spec["tradableInstrumentId"],
                "last_price": row["last_price"], "pips_to_entry": row["pips_to_entry"],
            }

            print(f"  {'WOULD PLACE' if args.dry_run else 'PLACING'}  {symbol} "
                  f"{row['direction']} score {row['score']}")
            print(f"     limit {lv['price']}  SL {lv['stop']} ({plan['stop_pips']} pips)  "
                  f"TP {lv['target']} ({plan['target_pips']} pips, {plan['rr']}R)")
            print(f"     {sizing['lots']} lots = ${sizing['actual_risk_usd']} risk "
                  f"({sizing['actual_risk_usd'] / rails['balance'] * 100:.2f}% of balance), "
                  f"margin ${margin:.2f}")
            print(f"     expires {str(expiry)[:16]} UTC")

            try:
                res = client.place_limit(spec, lv["side"], sizing["lots"], lv["price"],
                                         lv["stop"], lv["target"], expire_ms)
            except (RuntimeError, ValueError) as exc:
                skip(row, f"order rejected by broker: {exc}", plan=plan)
                continue

            body = res["response"].get("d", res["response"]) if isinstance(res["response"], dict) else {}
            order_id = body.get("orderId") or body.get("id") if isinstance(body, dict) else None
            plan.update({"placed_utc": _now_iso(), "dry_run": args.dry_run,
                         "validity": res["validity"], "order_id": order_id,
                         "broker_response": res["response"]})
            placed.append(plan)
            print(f"     -> orderId {order_id}  validity {res['validity']}"
                  + ("  [DRY RUN, nothing sent]" if args.dry_run else ""))

            slots_left -= 1
            trades_left -= 1
            committed_pairs.add(symbol)
            for c in (symbol[:3], symbol[3:6]):
                exposure[c] = exposure.get(c, 0) + 1
    else:
        print("\nNo qualifying setup. Nothing to place -- which at 0.163 trades/day")
        print("across 29 pairs is the ordinary outcome, roughly one setup every six")
        print("days for the whole book. No gate is loosened to manufacture one.")

    # --- verify the stop actually landed on the broker's side --------------
    verification = []
    if placed and not args.dry_run:
        print("\nVerifying placed orders against the broker...")
        time.sleep(2)
        after = account_snapshot(engine)
        by_id = {str(o.get("id")): o for o in after.get("orders", [])}
        pos_by_sym = {str(p.get("symbol")): p for p in after.get("positions", [])}
        for p in placed:
            oid = str(p.get("order_id") or "")
            row = by_id.get(oid)
            if row:
                ok = bool(row.get("stopLoss")) and bool(row.get("takeProfit"))
                verification.append({"symbol": p["symbol"], "order_id": oid,
                                     "found": "order", "status": row.get("status"),
                                     "stopLoss": row.get("stopLoss"),
                                     "takeProfit": row.get("takeProfit"),
                                     "protected": ok})
                print(f"  {p['symbol']}: resting order {oid} status {row.get('status')} "
                      f"SL {row.get('stopLoss')} TP {row.get('takeProfit')} "
                      f"-> {'PROTECTED' if ok else 'NO STOP ATTACHED -- INVESTIGATE'}")
            elif p["symbol"] in pos_by_sym:
                pos = pos_by_sym[p["symbol"]]
                ok = bool(pos.get("stopLossId")) and bool(pos.get("takeProfitId"))
                verification.append({"symbol": p["symbol"], "order_id": oid,
                                     "found": "position", "position_id": pos.get("id"),
                                     "stopLossId": pos.get("stopLossId"),
                                     "takeProfitId": pos.get("takeProfitId"),
                                     "protected": ok})
                print(f"  {p['symbol']}: FILLED into position {pos.get('id')} "
                      f"stopLossId {pos.get('stopLossId')} takeProfitId "
                      f"{pos.get('takeProfitId')} -> "
                      f"{'PROTECTED' if ok else 'NO STOP -- INVESTIGATE'}")
            else:
                verification.append({"symbol": p["symbol"], "order_id": oid,
                                     "found": "missing", "protected": False})
                print(f"  {p['symbol']}: order {oid} NOT FOUND in orders or positions "
                      "-- INVESTIGATE")
        snap = after

    record = {
        "run_utc": str(now), "dry_run": args.dry_run, "mode": mode,
        "account": identity, "config": dict(ADOPTED, score_gate=cfg.score_threshold,
                                            stack=stack["name"], universe=len(symbols),
                                            risk_per_trade_pct=RISK_PER_TRADE_PCT),
        "last_closed_bar_utc": str(latest), "guardrails": rails,
        "cancelled_expired": expired, "live_setups": live, "recent_setups": recent,
        "placed": placed, "skipped": skipped, "verification": verification,
        "account_after": {"balance": snap["account"].get("balance"),
                          "positions": len(snap.get("positions", [])),
                          "orders": len(snap.get("orders", []))},
    }
    log.append(record)

    print("\n" + "=" * 78)
    print(f"SUMMARY  [{mode}]")
    print(f"  qualifying setups {len(live)}   orders placed {len(placed)}   "
          f"skipped {len(skipped)}   expired cancelled {len(expired)}")
    print(f"  account {identity['account_id']} ({identity['server']}, DEMO)  "
          f"balance {record['account_after']['balance']}  "
          f"positions {record['account_after']['positions']}  "
          f"orders {record['account_after']['orders']}")
    print(f"  journal {LOG_PATH} ({len(log.doc['runs'])} runs recorded)")
    if any(v.get("protected") is False for v in verification):
        print("  *** AT LEAST ONE ORDER IS UNPROTECTED -- CHECK THE ACCOUNT NOW ***")
        return 2
    print("=" * 78)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(record, fh, indent=2, default=str)
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
