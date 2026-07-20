"""
Live monitor for the intraday ORB scalp strategy — ORB_CORE pairs
(EURUSD, USDCHF) only, Tuesday-Thursday, session-gated, same-day
time-stop. See intraday_strategy.py's docstring "UPDATE (2026-07-20)"
section for the full validation numbers (n=117, WR=60.7%, PF=1.89).

This is deliberately separate from live_monitor.py (the swing strategy's
live executor) rather than merged into it: different timeframe (5m vs
1h), different freshness window, different risk tier, and — critically —
a same-day time-stop that the swing strategy doesn't have. Positions this
script opens must be flattened by session end even if price never hits
SL/TP; that deadline is tracked in INTRADAY_STATE_PATH (gitignored
runtime state) since the broker API doesn't carry it.

Trading days: only runs entries on Tue/Wed/Thu (ALLOWED_WEEKDAYS in
intraday_strategy.py) — this is not a scheduling nicety, it's part of
the validated edge (unfiltered WR=57.1%/PF=1.53 vs Tue-Thu WR=60.7%/
PF=1.89 on the same data). Running this on a Monday or Friday and taking
whatever it finds would trade a strategy that was never validated for
those days.

Session gating: only opens new entries while a London (07:00-10:00 UTC)
or NY (12:00-15:00 UTC) session's breakout window is active (opening
range formed, still inside BREAKOUT_WINDOW_BARS of the range close) —
mirrors generate_orb_signals()'s own session-bound logic exactly, so a
signal detected live is the same shape as one counted in the backtest.

Credentials load from .env (gitignored) via TL_EMAIL/TL_PASSWORD/
TL_SERVER/TL_ACCOUNT_ID/TL_ACC_NUM — same broker connection as
live_monitor.py.

Run manually (intended to run every few minutes during session windows
on Tue/Wed/Thu):
    python3 intraday_live_monitor.py
"""
import os
import sys
import json
import datetime
import requests

sys.path.insert(0, os.path.dirname(__file__))
import price_action_strategy as pa
import intraday_strategy as ist
import pa_data
import live_monitor as lm  # reuse auth/instrument/position/quote plumbing

STATE_PATH = os.path.join(os.path.dirname(__file__), "intraday_active.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "intraday_live_monitor_log.json")
BASE = lm.BASE
BASE_RISK_PCT = 0.005  # 0.5% base risk — below the swing SECONDARY tier, per this file's thinner validation
MIN_QTY = 0.01
FRESH_BAR_TOLERANCE = 2  # signal must be within the last N closed 5m bars (~10 min)
BAR_MINUTES = 5


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH))
        except Exception:
            return {}
    return {}


def save_state(state):
    json.dump(state, open(STATE_PATH, "w"), indent=2)


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


def fetch_fresh_5m(name):
    symbol = pa_data.WATCHLIST[name]
    data = pa_data.fetch(symbol, range_="10d", interval="5m")
    path = os.path.join(ist.DATA_DIR_5M, f"{name}.csv")
    os.makedirs(ist.DATA_DIR_5M, exist_ok=True)
    pa_data.to_csv(data, path)
    df = ist.load_5m(name)
    return ist.tag_sessions(df)


def in_active_session_window(df):
    """True if the most recent closed bar is inside a session's breakout
    window (range already formed, still within BREAKOUT_WINDOW_BARS of
    the range close) — matches generate_orb_signals()'s own gating."""
    last_i = len(df) - 1
    sid = df["session_id"].iloc[last_i]
    if sid is None:
        return False
    open_i = df["session_open_i"].iloc[last_i]
    if open_i < 0:
        return False
    range_end = open_i + ist.ORB_RANGE_BARS
    window_end = range_end + ist.BREAKOUT_WINDOW_BARS
    return range_end <= last_i < window_end


def check_fresh_signal(name):
    df = fetch_fresh_5m(name)
    if not in_active_session_window(df):
        return None, "outside session breakout window"
    weekday = df.index[-1].weekday()
    if weekday not in ist.ALLOWED_WEEKDAYS:
        return None, f"weekday={weekday} not in Tue-Thu"
    signals = ist.generate_orb_signals(df, weekdays=ist.ALLOWED_WEEKDAYS)
    last_i = len(df) - 1
    recent = [s for s in signals if s["i"] >= last_i - FRESH_BAR_TOLERANCE]
    if not recent:
        return None, "no fresh signal"
    sig = recent[-1]
    sig["r_unit"] = abs(sig["entry"] - sig["stop"])
    sig["signal_time"] = str(df.index[sig["i"]])
    sig["deadline_time"] = str(df.index[min(sig["i"] + ist.SESSION_END_OFFSET_BARS, last_i)]
                                if sig["i"] + ist.SESSION_END_OFFSET_BARS < len(df)
                                else df.index[-1] + datetime.timedelta(minutes=BAR_MINUTES * (sig["i"] + ist.SESSION_END_OFFSET_BARS - last_i)))
    return sig, "fresh signal"


def place_trade(headers, account_id, instrument, sig, name):
    instrument_id = instrument["tradableInstrumentId"]
    trade_route = lm.find_route(instrument, "TRADE")
    info_route = lm.find_route(instrument, "INFO")
    quote = lm.get_quote(headers, instrument_id, info_route)

    direction = sig["dir"]
    side = "buy" if direction == 1 else "sell"
    ref_price = quote["ap"] if direction == 1 else quote["bp"]
    r_unit = sig["r_unit"]
    stop = round(ref_price - r_unit, 5) if direction == 1 else round(ref_price + r_unit, 5)
    target = round(ref_price + ist.TARGET_R * r_unit, 5) if direction == 1 else round(ref_price - ist.TARGET_R * r_unit, 5)

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
        "ref_price": ref_price, "stop": stop, "target_1_5R": target,
        "signal_time": sig["signal_time"], "deadline_time": sig["deadline_time"], "result": result,
    })
    return result


def close_position(headers, account_id, position_id, name):
    """Per-ID DELETE 404s on this broker for large numeric position IDs
    (a known TradeLocker/GenFX backend bug, seen earlier in this repo's
    live trading). Fall back to the bulk close-all-positions endpoint if
    the per-ID call fails -- safe here because this account only runs
    this repo's automated strategies, so "close everything" and "close
    this one" are equivalent in practice."""
    resp = requests.delete(f"{BASE}/trade/accounts/{account_id}/positions/{position_id}", headers=headers)
    result = resp.json() if resp.content else {"status": resp.status_code}
    if resp.status_code == 404:
        resp2 = requests.delete(f"{BASE}/trade/accounts/{account_id}/positions", headers=headers)
        result = {"per_id_404": result, "bulk_close_all": resp2.json() if resp2.content else {"status": resp2.status_code}}
    log_event({"action": "time_stop_close", "pair": name, "position_id": position_id, "result": result})
    return result


def main():
    env = lm.load_env()
    headers = lm.auth(env)
    account_id = env["TL_ACCOUNT_ID"]

    instruments = lm.get_instruments(headers, account_id)
    positions = lm.get_positions(headers, account_id)
    open_by_iid = {str(p[1]): p for p in positions}

    state = load_state()
    now = datetime.datetime.utcnow()

    print(f"=== Intraday (ORB_CORE) live monitor run {now.isoformat()} UTC ===")
    print(f"Open positions on account: {len(positions)}")

    # 1) time-stop: flatten any tracked intraday position past its deadline
    for iid, rec in list(state.items()):
        if iid not in open_by_iid:
            state.pop(iid, None)  # already closed (SL/TP hit) -- drop tracking
            continue
        deadline = datetime.datetime.fromisoformat(rec["deadline_time"].split("+")[0])
        if now >= deadline:
            pos = open_by_iid[iid]
            print(f"{rec['pair']}: past time-stop deadline ({rec['deadline_time']}) -> closing")
            close_position(headers, account_id, pos[0], rec["pair"])
            state.pop(iid, None)
    save_state(state)

    # 2) look for fresh entries on ORB_CORE pairs only
    for name in ist.ORB_CORE:
        if name not in instruments:
            print(f"{name}: not found on broker, skipping")
            continue
        instrument = instruments[name]
        iid = str(instrument["tradableInstrumentId"])
        if iid in open_by_iid:
            print(f"{name}: position already open, skipping (one at a time)")
            continue

        sig, reason = check_fresh_signal(name)
        if sig is None:
            print(f"{name}: no trade ({reason})")
            continue

        print(f"{name}: FRESH SIGNAL dir={'LONG' if sig['dir']==1 else 'SHORT'} "
              f"(bar {sig['signal_time']}, deadline {sig['deadline_time']}) -> placing trade")
        result = place_trade(headers, account_id, instrument, sig, name)
        print(f"  order result: {result}")
        if result.get("s") == "ok" or "d" in result:
            state[iid] = {"pair": name, "deadline_time": sig["deadline_time"]}
            save_state(state)


if __name__ == "__main__":
    main()
