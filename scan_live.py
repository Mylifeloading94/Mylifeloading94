#!/usr/bin/env python3
"""Live setup scan: the adopted v7/v8 configuration pointed at TODAY's bars.

Everything in this repo up to now runs historical backtests. This is the same
machinery aimed at the present: refresh the broker's 1H cache, rebuild the
pair contexts, run the **identical** signal-generation path the backtest uses
(``Backtester.collect_signals`` -> ``signal_engine.generate_signals``), and
report which signals are still *live* -- i.e. emitted on a recently closed
setup bar, still inside their limit-order validity window, and not yet filled.

The configuration is the adopted one and is not re-tuned here. It mirrors
``run_v7_100k.py``'s defaults exactly:

    profile ``v6``  (swing stack: 1D bias / 4H structure / 1H setup / 1H entry)
    ``targets.fixed_rr``          2.0     flat 1:2
    ``targets.min_target_pips``   20      minimum target distance
    ``targets.min_rr_on_liquidity`` True  the RR gate reads real liquidity
    score gate                    80      (``scoring.profiles.standard``)
    universe                      all 29 configured instruments

**READ-ONLY.** The only endpoints touched are ``/trade/history`` (bars, via
:class:`~smc_sniper.providers.TradeLockerProvider`), ``/trade/accounts/{id}/
positions``, ``/trade/accounts/{id}/orders`` and ``/trade/accounts/{id}/state``.
No order-placement endpoint is called, imported, or reachable from this file.
``uploaded_bot.live_runner`` is deliberately not imported.

Usage::

    python3 scan_live.py                    # refresh 30d of 1H, scan, print
    python3 scan_live.py --no-refresh       # scan the existing cache
    python3 scan_live.py --json out.json    # machine-readable copy
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smc_sniper.backtest import Backtester
from smc_sniper.config import load_config
from smc_sniper.data import DataEngine, tf_minutes

REPO = os.path.dirname(os.path.abspath(__file__))

# The adopted v7/v8 configuration. Changing any of these makes the scan
# something other than the validated system, so they live here as constants
# and are echoed in the report header.
ADOPTED = {
    "profile": "v6",
    "targets.fixed_rr": 2.0,
    "targets.min_target_pips": 20.0,
    "targets.min_rr_on_liquidity": True,
}


def adopted_config():
    """Load the exact adopted configuration (same wiring as run_v7_100k.py)."""
    cfg = load_config().apply_profile(ADOPTED["profile"])
    cfg.set("targets.fixed_rr", ADOPTED["targets.fixed_rr"])
    cfg.set("targets.min_target_pips", ADOPTED["targets.min_target_pips"])
    cfg.set("targets.min_rr_on_liquidity", ADOPTED["targets.min_rr_on_liquidity"])
    return cfg


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def refresh(engine: DataEngine, symbols, days: int, verbose: bool = True):
    """Top the 1H cache up to now.

    ``download_deep`` merges into the cached CSV as a timestamp union, so a
    short refresh window can only ever ADD recent bars -- the 1,200-day history
    the backtests are validated on is never truncated. The swing stack's 4H and
    1D frames are resampled from this same 1H cache, so one interval is all
    that needs fetching.
    """
    out = []
    for sym in symbols:
        res = engine.download_deep(sym, "1H", days)
        out.append(res)
        if verbose:
            tag = "ok  " if res.ok else "FAIL"
            print(f"  [{tag}] {sym:8s} 1H  {res.bars:6d} bars  last {res.last[:16]}"
                  f"  {res.error}")
        time.sleep(0.2)
    return out


def trim_to_closed(engine: DataEngine, symbols, stack, now: pd.Timestamp):
    """Drop any bar that has not finished forming.

    The broker serves the in-progress bar like any other. Reading it would be
    lookahead of the worst kind on a live scan -- the "close" is just the last
    tick. Every frame the engine will hand to a context is truncated to bars
    whose ``close_time`` is already in the past, which is the same rule
    :class:`~smc_sniper.data.MTFView` enforces between timeframes.
    """
    tfs = {stack[r] for r in ("bias_tf", "structure_tf", "setup_tf", "entry_tf")
           if stack.get(r)}
    for sym in symbols:
        for tf in tfs:
            frame = engine.get(sym, tf)
            if frame.empty:
                continue
            engine._mem[(sym, "tf", tf)] = frame[frame["close_time"] <= now]


# ---------------------------------------------------------------------------
# liveness
# ---------------------------------------------------------------------------
def signal_status(ctx, sig, cfg, stack) -> dict:
    """Where a generated signal stands *right now*.

    Reproduces the fill-window arithmetic of
    :meth:`~smc_sniper.backtest.Backtester.simulate_trade` exactly -- same
    ``searchsorted`` boundaries, same ``entry.exact_expiry`` off-by-one fix,
    same trade-through (never touch) fill rule -- and then asks which side of
    "now" each boundary falls on.

    Returns one of:
      ``pending``  limit still resting, window still open  -> ACTIONABLE
      ``filled``   price already traded through the limit  -> entry is gone
      ``expired``  window closed without a fill            -> dead
    """
    icfg = ctx.icfg
    setup, eframe = ctx.setup, ctx.entry_frame
    n_s, n_e = len(setup), len(eframe)
    last_close = setup["close_time"].iloc[-1]

    sig_close = setup["close_time"].iloc[sig.bar_index]
    start = int(eframe.index.searchsorted(sig_close, side="left"))

    # Expiry may sit beyond the last formed bar; extrapolate on the setup grid
    # rather than clamping, or a young signal reads as though it has run out.
    if sig.valid_until_bar <= n_s - 1:
        expiry_time = setup["close_time"].iloc[sig.valid_until_bar]
    else:
        extra = sig.valid_until_bar - (n_s - 1)
        expiry_time = last_close + pd.Timedelta(minutes=extra * tf_minutes(stack["setup_tf"]))
    end = int(eframe.index.searchsorted(expiry_time, side="left"))
    if bool(icfg.get("entry.exact_expiry", False)):
        end -= 1

    long = sig.direction == "bullish"
    highs, lows = eframe["high"].values, eframe["low"].values
    fill_i = None
    for j in range(start, min(end + 1, n_e)):
        if (long and lows[j] < sig.entry) or (not long and highs[j] > sig.entry):
            fill_i = j
            break

    if fill_i is not None:
        state = "filled"
    elif expiry_time <= last_close:
        state = "expired"
    else:
        state = "pending"

    # How far price still has to travel back into the zone, and whether the
    # structure has already been broken while the order rested.
    price = float(eframe["close"].iloc[-1])
    pip = icfg.pip
    to_entry = (price - sig.entry) / pip * (1.0 if long else -1.0)
    if start < n_e:
        stop_hit = (bool(lows[start:n_e].min() < sig.stop) if long
                    else bool(highs[start:n_e].max() > sig.stop))
    else:
        stop_hit = False

    bars_left = 0
    if state == "pending":
        bars_left = max(0, sig.valid_until_bar - (n_s - 1))

    return {
        "state": state,
        "bars_since_signal": int(n_s - 1 - sig.bar_index),
        "bars_left_in_window": int(bars_left),
        "expiry_utc": str(expiry_time),
        "last_price": price,
        "pips_to_entry": round(to_entry, 1),
        "in_zone_now": bool(to_entry <= 0),
        "stop_breached_since": stop_hit,
        "fill_bar_utc": str(eframe.index[fill_i]) if fill_i is not None else "",
    }


def describe(ctx, sig, status, cfg) -> dict:
    """Flatten one live signal into a report row."""
    icfg = ctx.icfg
    pip = icfg.pip
    stop_pips = abs(sig.entry - sig.stop) / pip
    tgt_pips = abs(sig.tp2 - sig.entry) / pip
    # Flat-RR mode: the traded target is tp2 (tp1==tp2==tp3 with partials off).
    sweep = getattr(sig, "explanation", {}).get("liquidity", sig.liquidity_type)
    return {
        "symbol": sig.symbol,
        "direction": "LONG" if sig.direction == "bullish" else "SHORT",
        "side": sig.side,
        "score": round(sig.score, 1),
        "signal_bar_utc": str(sig.time),
        "session": sig.session,
        "setup_type": sig.setup_type,
        "liquidity_swept": sweep,
        "structure_event": sig.structure_event,
        "zone": sig.zone_kind,
        "htf_bias": sig.htf_bias,
        "entry": round(sig.entry, 5),
        "stop": round(sig.stop, 5),
        "target": round(sig.tp2, 5),
        "stop_pips": round(stop_pips, 1),
        "target_pips": round(tgt_pips, 1),
        "rr": round(sig.rr_tp2, 2),
        "atr": round(sig.atr, 5),
        "spread_pips": sig.spread_pips,
        **status,
    }


# ---------------------------------------------------------------------------
# account (read-only)
# ---------------------------------------------------------------------------
ACCOUNT_FIELDS = ["balance", "projectedBalance", "availableFunds", "blockedBalance",
                  "cashBalance", "unsettledCash", "withdrawalAvailable", "stocksValue",
                  "optionValue", "initialMarginReq", "maintMarginReq",
                  "marginWarningLevel", "blockedForStocks", "stockOrdersReq",
                  "stopOutLevel", "warningMarginReq", "marginBeforeWarning",
                  "todayGross", "todayNet", "todayFees", "todayVolume",
                  "todayTradesCount", "openGrossPnL", "openNetPnL", "positionsCount",
                  "ordersCount"]


def account_snapshot(engine: DataEngine) -> dict:
    """Balance, open positions and working orders. Read-only, no writes.

    Positions and orders come back as bare arrays; the column order is served
    by ``/trade/config`` and is read from there rather than hard-coded, since
    a broker-side column change would otherwise silently mislabel a position.
    """
    provider = engine.provider
    if getattr(provider, "name", "") != "tradelocker":
        return {"error": f"account state needs the tradelocker provider, got {provider.name}"}
    acct = provider.env["TL_ACCOUNT_ID"]
    conf = provider._get("/trade/config", {}).get("d", {})

    def cols(node):
        return [c.get("id") for c in (conf.get(node, {}) or {}).get("columns", [])]

    inst_by_id = {meta["tradableInstrumentId"]: name
                  for name, meta in provider.instruments().items()}

    def rows(payload, key, columns):
        out = []
        for row in payload.get("d", {}).get(key, []) or []:
            rec = dict(zip(columns, row))
            tid = rec.get("tradableInstrumentId")
            try:
                rec["symbol"] = inst_by_id.get(int(tid), str(tid))
            except (TypeError, ValueError):
                rec["symbol"] = str(tid)
            out.append(rec)
        return out

    positions = rows(provider._get(f"/trade/accounts/{acct}/positions", {}),
                     "positions", cols("positionsConfig"))
    orders = rows(provider._get(f"/trade/accounts/{acct}/orders", {}),
                  "orders", cols("ordersConfig"))
    state = provider._get(f"/trade/accounts/{acct}/state", {}).get("d", {})
    details = dict(zip(cols("accountDetailsConfig") or ACCOUNT_FIELDS,
                       state.get("accountDetailsData", [])))
    return {"positions": positions, "orders": orders, "account": details}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh-days", type=int, default=30,
                    help="days of 1H bars to top the cache up with (union-merged)")
    ap.add_argument("--no-refresh", action="store_true",
                    help="scan the existing cache without hitting the broker for bars")
    ap.add_argument("--lookback-bars", type=int, default=12,
                    help="how many recently closed setup bars to examine")
    ap.add_argument("--source", default="tradelocker")
    ap.add_argument("--json", default=None, help="write the full result here")
    ap.add_argument("--no-account", action="store_true")
    args = ap.parse_args()

    cfg = adopted_config()
    stack = cfg.stack
    engine = DataEngine(cfg, source=args.source)
    symbols = cfg.symbols
    now = pd.Timestamp.now(tz="UTC")

    print("=" * 78)
    print("SMC SNIPER -- LIVE SETUP SCAN (read-only; no order is ever placed)")
    print(f"  scanned at        {str(now)[:19]} UTC")
    print(f"  config            profile '{ADOPTED['profile']}' / adopted v7-v8, unchanged")
    print(f"  stack             {stack['name']}: bias {stack['bias_tf']} / structure "
          f"{stack['structure_tf']} / setup {stack['setup_tf']} / entry {stack['entry_tf']}")
    print(f"  score gate        {cfg.score_threshold:.0f}")
    print(f"  target            flat {cfg.get('targets.fixed_rr')}R, min "
          f"{cfg.get('targets.min_target_pips'):.0f} pips, RR gate on liquidity="
          f"{cfg.get('targets.min_rr_on_liquidity')}")
    print(f"  universe          {len(symbols)} instruments")
    print("=" * 78)

    if not args.no_refresh:
        print(f"\nRefreshing {stack['setup_tf']} cache ({args.refresh_days}d, union-merged)...")
        refresh(engine, symbols, args.refresh_days)

    trim_to_closed(engine, symbols, stack, now)

    print("\nBuilding contexts and generating signals (identical path to the backtest)...")
    bt = Backtester(cfg, engine)
    contexts = bt.build_contexts()
    signals, _ = bt.collect_signals(contexts, use_cache=False)

    latest = max((ctx.setup.index[-1] for ctx in contexts.values()), default=None)
    print(f"  {len(contexts)}/{len(symbols)} pairs with data; last closed "
          f"{stack['setup_tf']} bar opens {str(latest)[:16]} UTC; "
          f"{len(signals)} signals over the full history")

    live, recent = [], []
    for symbol, sig in signals:
        ctx = contexts[symbol]
        age = len(ctx.setup) - 1 - sig.bar_index
        if age > args.lookback_bars:
            continue
        status = signal_status(ctx, sig, cfg, stack)
        row = describe(ctx, sig, status, cfg)
        recent.append(row)
        if status["state"] == "pending" and not status["stop_breached_since"]:
            live.append(row)

    print("\n" + "=" * 78)
    if live:
        print(f"LIVE QUALIFYING SETUPS: {len(live)}")
        for row in live:
            print("-" * 78)
            print(f"  {row['symbol']}  {row['direction']}   score {row['score']}"
                  f"   ({row['setup_type']}, {row['zone']} zone)")
            print(f"    signal bar   {row['signal_bar_utc'][:16]} UTC  "
                  f"({row['bars_since_signal']} bars ago, {row['session']} session)")
            print(f"    sequence     swept {row['liquidity_swept']} -> "
                  f"{row['structure_event']}, HTF bias {row['htf_bias']}")
            print(f"    entry {row['entry']}   stop {row['stop']} "
                  f"({row['stop_pips']} pips)   target {row['target']} "
                  f"({row['target_pips']} pips, {row['rr']}R)")
            print(f"    price now    {row['last_price']}  ->  "
                  f"{'PRICE IS IN THE ZONE' if row['in_zone_now'] else str(row['pips_to_entry']) + ' pips of retrace still needed'}")
            print(f"    validity     {row['bars_left_in_window']} setup bars left, "
                  f"expires {row['expiry_utc'][:16]} UTC")
    else:
        print("LIVE QUALIFYING SETUPS: NONE")
        print("  No pair currently has a setup that clears every gate with its limit")
        print("  still resting. At 0.163 trades/day across 29 pairs this is the")
        print("  ordinary outcome -- roughly one setup every six days for the whole book.")

    other = [r for r in recent if r not in live]
    if other:
        print("\nRecently generated, no longer actionable "
              f"(last {args.lookback_bars} setup bars):")
        for row in other:
            note = row["state"]
            if row["state"] == "filled":
                note = f"filled {row['fill_bar_utc'][:16]} (entry already taken)"
            elif row["stop_breached_since"]:
                note = "invalidated (stop level traded through)"
            print(f"  {row['symbol']:8s} {row['direction']:5s} score {row['score']:5.1f}  "
                  f"{row['signal_bar_utc'][:16]}  {note}")

    result = {"scanned_at_utc": str(now), "config": dict(ADOPTED, score_gate=cfg.score_threshold,
                                                         stack=stack["name"],
                                                         universe=len(symbols)),
              "last_closed_bar_utc": str(latest), "live": live, "recent": recent}

    if not args.no_account:
        print("\n" + "=" * 78)
        print("ACCOUNT (read-only)")
        snap = account_snapshot(engine)
        result["account_snapshot"] = snap
        if "error" in snap:
            print(f"  {snap['error']}")
        else:
            acc = snap["account"]
            print(f"  balance {acc.get('balance')}   available {acc.get('availableFunds')}"
                  f"   open P/L {acc.get('openNetPnL')}")
            print(f"  open positions: {len(snap['positions'])}"
                  f"   working orders: {len(snap['orders'])}")
            for p in snap["positions"]:
                print(f"    {p.get('symbol'):8s} {p.get('side'):5s} qty {p.get('qty')} "
                      f"@ {p.get('avgPrice')}  uPnL {p.get('unrealizedPl')}  "
                      f"opened {str(p.get('openDate'))[:16]}")
            for o in snap["orders"]:
                print(f"    ORDER {o.get('symbol'):8s} {o.get('side'):5s} "
                      f"{o.get('type')} qty {o.get('qty')} @ {o.get('price')} "
                      f"({o.get('status')})")

    print("\nNo order was placed. This script has no order-placement code path.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result, fh, indent=2, default=str)
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
