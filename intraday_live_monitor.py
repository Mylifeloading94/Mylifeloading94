"""
Live monitor for the intraday ORB scalp strategy — EURUSD, AUDUSD,
USDCHF, USDCAD, NZDUSD (LIVE_PAIRS), Tuesday-Thursday, session-gated,
same-day time-stop. Expanded from the original 2-pair ORB_CORE set to
this 5-pair set on 2026-07-21 to match the backtest validated against
the $150,000 AQUA account (268 trades taken, WR=60.4%, PF=2.21,
+147.72% with a 2% daily-loss cap, see aqua_backtest_report.xlsx).

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
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import price_action_strategy as pa
import intraday_strategy as ist
import pa_data
import live_monitor as lm  # reuse auth/instrument/position/quote plumbing

STATE_PATH = os.path.join(os.path.dirname(__file__), "intraday_active.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "intraday_live_monitor_log.json")
BASE = lm.BASE
BASE_RISK_PCT = 0.01  # 1% risk per trade, explicit user choice (2026-07-21, new AQUA account)
MIN_QTY = 0.01
FRESH_BAR_TOLERANCE = 2  # signal must be within the last N closed 5m bars (~10 min)
BAR_MINUTES = 5
LOT_STEP = 0.01

# 5-pair set backtested and approved 2026-07-21 (aqua_backtest_report.xlsx).
LIVE_PAIRS = ["EURUSD", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD"]

# Lot-size math confirmed against this account's real fill history (see
# trading_backtest_full_stats.xlsx "Lot Size" column, 2026-07-20).
# EURUSD/AUDUSD/NZDUSD: base=non-USD, quote=USD -> standard 100k contract.
# USDCHF/USDCAD: base=USD, quote=CHF/CAD -> adjust by current price to
# convert the quote-currency P&L back to USD.
CONTRACT_SIZE = 100_000
USD_BASE_PAIRS = {"USDCHF", "USDCAD"}
USD_QUOTE_PAIRS = {"EURUSD", "AUDUSD", "NZDUSD"}


def get_account_balance(env):
    """Match on TL_ACCOUNT_ID explicitly -- accounts[0] silently picked the
    wrong sub-account when a login has more than one (e.g. this AQUA login
    has both a $100k and a $150k demo account under the same credentials)."""
    r = requests.post(f"{BASE}/auth/jwt/token", json={
        "email": env["TL_EMAIL"], "password": env["TL_PASSWORD"], "server": env["TL_SERVER"],
    })
    r.raise_for_status()
    token = r.json()["accessToken"]
    resp = requests.get(f"{BASE}/auth/jwt/all-accounts", headers={"Authorization": f"Bearer {token}"}).json()
    accounts = resp["accounts"]
    target_id = str(env["TL_ACCOUNT_ID"])
    for acct in accounts:
        if str(acct["id"]) == target_id:
            return float(acct["accountBalance"])
    raise RuntimeError(f"TL_ACCOUNT_ID={target_id} not found among accounts: {[a['id'] for a in accounts]}")


def compute_lot_size(name, risk_amt, stop_dist, ref_price):
    if stop_dist <= 0:
        return MIN_QTY
    if name in USD_QUOTE_PAIRS:
        value_per_unit_per_lot = CONTRACT_SIZE
    elif name in USD_BASE_PAIRS:
        value_per_unit_per_lot = CONTRACT_SIZE / ref_price
    else:
        raise ValueError(f"no confirmed lot formula for {name}")
    lots = risk_amt / (stop_dist * value_per_unit_per_lot)
    lots = max(MIN_QTY, round(lots / LOT_STEP) * LOT_STEP)
    return round(lots, 2)


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


LIVE_DATA_DIR = os.path.join(os.path.dirname(__file__), "pa_data_5m_live")


def fetch_fresh_5m(name):
    """Uses its own cache dir (pa_data_5m_live/), never pa_data_5m/ --
    that path is the shared 60-day backtest dataset intraday_strategy.py's
    validation numbers are computed from; overwriting it with a short live
    fetch here would silently corrupt that dataset (this happened once --
    a 10-day live fetch truncated the committed 60-day EURUSD/USDCHF
    backtest cache from the shell)."""
    os.makedirs(LIVE_DATA_DIR, exist_ok=True)
    symbol = pa_data.WATCHLIST[name]
    data = pa_data.fetch(symbol, range_="10d", interval="5m")
    path = os.path.join(LIVE_DATA_DIR, f"{name}.csv")
    pa_data.to_csv(data, path)
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("time").drop(columns=["timestamp"]).sort_index()
    df = df[~df.index.duplicated(keep="first")].dropna(subset=["open", "high", "low", "close"])
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
    signals = ist.generate_orb_signals(df, weekdays=ist.ALLOWED_WEEKDAYS, pair=name, session_banned=ist.SESSION_BANNED)
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


def place_trade(headers, account_id, instrument, sig, name, balance):
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

    risk_amt = balance * BASE_RISK_PCT
    stop_dist = abs(ref_price - stop)
    qty = compute_lot_size(name, risk_amt, stop_dist, ref_price)

    body = {
        "tradableInstrumentId": instrument_id,
        "routeId": trade_route,
        "type": "market",
        "side": side,
        "qty": qty,
        "validity": "IOC",
        "stopLoss": stop,
        "stopLossType": "absolute",
        "takeProfit": target,
        "takeProfitType": "absolute",
    }
    resp = requests.post(f"{BASE}/trade/accounts/{account_id}/orders", headers=headers, json=body)
    result = resp.json()
    log_event({
        "action": "place_trade", "pair": name, "side": side, "qty": qty,
        "risk_pct": BASE_RISK_PCT, "risk_amt": round(risk_amt, 2), "balance_at_entry": balance,
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
    no_new_entries = os.environ.get("INTRADAY_NO_NEW_ENTRIES") == "1"
    env = lm.load_env()
    headers = lm.auth(env)
    account_id = env["TL_ACCOUNT_ID"]

    instruments = lm.get_instruments(headers, account_id)
    positions = lm.get_positions(headers, account_id)
    open_by_iid = {str(p[1]): p for p in positions}
    balance = get_account_balance(env)

    state = load_state()
    now = datetime.datetime.utcnow()

    print(f"=== Intraday (LIVE_PAIRS) live monitor run {now.isoformat()} UTC ===")
    print(f"Account balance: ${balance:,.2f}  |  risk per trade: {BASE_RISK_PCT*100:.0f}% = ${balance*BASE_RISK_PCT:,.2f}")
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

    # 2) look for fresh entries on LIVE_PAIRS only
    if no_new_entries:
        print("INTRADAY_NO_NEW_ENTRIES=1 set -- skipping new-entry scan, time-stops above still apply.")
        return
    for name in LIVE_PAIRS:
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
        result = place_trade(headers, account_id, instrument, sig, name, balance)
        print(f"  order result: {result}")
        if result.get("s") == "ok" or "d" in result:
            state[iid] = {"pair": name, "deadline_time": sig["deadline_time"]}
            save_state(state)


if __name__ == "__main__":
    main()
