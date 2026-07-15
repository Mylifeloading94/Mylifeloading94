"""
Live monitor — checks the LOCKED price_action_strategy.py watchlist
(SPX500/US30 PRIMARY, NAS100 SECONDARY, XAUUSD TERTIARY) for genuinely
fresh signals and places them on the connected TradeLocker/GenFX account.

"Fresh" = the signal (pattern) bar is one of the last 2 closed H1 bars.
This deliberately mirrors the honest-fill discipline from the backtest
(price_action_strategy.py FILL_WINDOW=3) — a signal older than that is a
stale/chased entry and is skipped, not force-traded. One open position per
instrument at a time (checked live against the account, not just assumed).

Credentials load from .env (gitignored, never committed) via TL_EMAIL /
TL_PASSWORD / TL_SERVER / TL_ACCOUNT_ID / TL_ACC_NUM.

Run manually:
    python3 live_monitor.py
Intended to be run on a recurring schedule (hourly, matching H1 bar closes)
by a wakeup/trigger — see the session notes for how this one was wired up.

CAVEAT: position sizing here is best-effort. Contract multipliers for
SPX500/US30/NAS100 aren't confirmed via the API (unlike XAUUSD, which was
empirically discovered: 0.01 lot minimum, ~100oz contract, forcing ~1.8%
risk on the first live trade — well above the intended 0.25% TERTIARY
target for that pair, a direct real-world hit of the "small accounts vs
broker minimums" caveat flagged earlier in this repo's history). This
script starts every new position at the broker's minimum lot step (0.01)
and logs the resulting real risk rather than guessing a multiplier and
being wrong. Review the actual $ risk on every fill before trusting it at
scale.
"""
import os
import sys
import json
import time
import datetime
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import price_action_strategy as pa
import pa_data

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
LOG_PATH = os.path.join(os.path.dirname(__file__), "live_monitor_log.json")
BASE = "https://demo.tradelocker.com/backend-api"
BASE_RISK_PCT = 0.01  # 1% base risk; scaled by RISK_TIER per instrument
MIN_QTY = 0.01
FRESH_BAR_TOLERANCE = 2  # signal must be within the last N closed bars


def load_env():
    env = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


def auth(env):
    r = requests.post(f"{BASE}/auth/jwt/token", json={
        "email": env["TL_EMAIL"], "password": env["TL_PASSWORD"], "server": env["TL_SERVER"],
    })
    r.raise_for_status()
    token = r.json()["accessToken"]
    return {"Authorization": f"Bearer {token}", "accNum": env["TL_ACC_NUM"], "Content-Type": "application/json"}


def get_instruments(headers, account_id):
    resp = requests.get(f"{BASE}/trade/accounts/{account_id}/instruments", headers=headers).json()
    return {i["name"]: i for i in resp.get("d", {}).get("instruments", [])}


def get_positions(headers, account_id):
    resp = requests.get(f"{BASE}/trade/accounts/{account_id}/positions", headers=headers).json()
    rows = resp.get("d", {}).get("positions", [])
    # columns: id, tradableInstrumentId, routeId, side, qty, avgPrice, stopLossId, takeProfitId, openDate, unrealizedPl, strategyId
    return rows


def get_quote(headers, instrument_id, route_id):
    resp = requests.get(f"{BASE}/trade/quotes", headers=headers,
                         params={"tradableInstrumentId": instrument_id, "routeId": route_id}).json()
    return resp["d"]


def find_route(instrument, kind):
    for r in instrument["routes"]:
        if r["type"] == kind:
            return r["id"]
    return None


def log_event(event):
    events = []
    if os.path.exists(LOG_PATH):
        try:
            events = json.load(open(LOG_PATH))
        except Exception:
            events = []
    event["ts"] = datetime.datetime.utcnow().isoformat()
    events.append(event)
    json.dump(events, open(LOG_PATH, "w"), indent=2)


def check_fresh_signal(name):
    """Refresh data, run the LOCKED strategy, return a signal dict if one is
    within FRESH_BAR_TOLERANCE bars of the most recent closed bar, else None."""
    symbol = pa_data.WATCHLIST[name]
    data = pa_data.fetch(symbol, range_="730d", interval="60m")
    pa_data.to_csv(data, f"{pa_data.CACHE_DIR}/{name}.csv")

    df = pa.load(name)
    h4 = pa.build_4h_trend(df)
    wick = pa.WICK_RATIO.get(name, 0.60)
    dfp, signals = pa.generate_signals(df, h4, wick_ratio=wick)
    last_i = len(dfp) - 1
    recent = [s for s in signals if s["i"] >= last_i - FRESH_BAR_TOLERANCE]
    if not recent:
        return None
    sig = recent[-1]
    sig["r_unit"] = abs(sig["entry"] - sig["stop"])
    sig["signal_time"] = str(dfp.index[sig["i"]])
    return sig


def place_trade(headers, account_id, instrument, sig, risk_mult, name):
    instrument_id = instrument["tradableInstrumentId"]
    trade_route = find_route(instrument, "TRADE")
    info_route = find_route(instrument, "INFO")
    quote = get_quote(headers, instrument_id, info_route)

    direction = sig["dir"]
    side = "buy" if direction == 1 else "sell"
    ref_price = quote["ap"] if direction == 1 else quote["bp"]
    r_unit = sig["r_unit"]
    stop = round(ref_price - r_unit, 2) if direction == 1 else round(ref_price + r_unit, 2)
    target = round(ref_price + pa.TP1_R * r_unit, 2) if direction == 1 else round(ref_price - pa.TP1_R * r_unit, 2)

    body = {
        "tradableInstrumentId": instrument_id,
        "routeId": trade_route,
        "type": "market",
        "side": side,
        "qty": MIN_QTY,
        "validity": "IOC",
        "stopLoss": stop,
        "stopLossType": "absolute",
        "takeProfit": target,
        "takeProfitType": "absolute",
    }
    resp = requests.post(f"{BASE}/trade/accounts/{account_id}/orders", headers=headers, json=body)
    result = resp.json()
    log_event({
        "action": "place_trade", "pair": name, "side": side, "qty": MIN_QTY,
        "ref_price": ref_price, "stop": stop, "target_2R": target,
        "risk_mult": risk_mult, "signal_time": sig["signal_time"], "result": result,
    })
    return result


def main():
    env = load_env()
    headers = auth(env)
    account_id = env["TL_ACCOUNT_ID"]

    instruments = get_instruments(headers, account_id)
    positions = get_positions(headers, account_id)
    open_instrument_ids = {p[1] for p in positions}

    print(f"=== Live monitor run {datetime.datetime.utcnow().isoformat()} UTC ===")
    print(f"Open positions: {len(positions)}")

    for name in pa.RECOMMENDED:
        if name not in instruments:
            print(f"{name}: not found on broker, skipping")
            continue
        instrument = instruments[name]
        iid = str(instrument["tradableInstrumentId"])
        if iid in open_instrument_ids:
            print(f"{name}: position already open, skipping (one at a time)")
            continue

        sig = check_fresh_signal(name)
        if sig is None:
            print(f"{name}: no fresh signal")
            continue

        risk_mult = pa.RISK_TIER.get(name, 1.0)
        print(f"{name}: FRESH SIGNAL dir={'LONG' if sig['dir']==1 else 'SHORT'} "
              f"(bar {sig['signal_time']}) -> placing trade at risk_mult={risk_mult}")
        result = place_trade(headers, account_id, instrument, sig, risk_mult, name)
        print(f"  order result: {result}")


if __name__ == "__main__":
    main()
