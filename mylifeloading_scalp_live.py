"""
"Mylifeloading Scalp" live monitor -- 17-pair, per-pair-tuned ORB scalp
strategy, one distinct (timeframe, session) setup per pair rather than
one shared rule for all pairs.

Origin: full-watchlist scan across 21 pairs x {5m, 15m} x {Asian,
London, NY} x {ORB, TWAP}, 128 valid combos, every one split-half
validated (PF >= 1.3 on BOTH halves independently). TWAP never won --
every surviving setup below is ORB. See scalp_watchlist_scan.xlsx
(2026-07-21) for the full scan, per-combo numbers, and the correlation-
risk writeup that explains why this is run with a fixed lot size
instead of naive per-trade risk-% sizing (pooling all 17 pairs' 2%-risk
bets on one account is not real diversification -- 12.1 of 17 pairs
signal on the same calendar day on average).

Sizing (explicit user choice, 2026-07-21): fixed 0.20 lots on every FX
pair, fixed 0.01 lots on NAS100/SPX500/US30 (index contract size is
unconfirmed via this broker's API -- 0.01 matches the broker minimum
and the same caution already documented in live_monitor.py).

No weekday filter is applied here (unlike intraday_live_monitor.py's
Tue-Thu-only rule) -- the watchlist scan was not weekday-filtered, so
applying one now would be an unvalidated assumption, not a backtested
rule. Revisit this if a future scan tests it.

Two pairs (GBPAUD, EURAUD) are flagged "Low confidence" in the scan --
their train/test profit factor disagreed by 2.5x+, more likely a small-
sample fluke than a stable edge. They are included here as requested;
review the scan output before trusting their signals as much as the
rest.

Separate from live_monitor.py (swing) and intraday_live_monitor.py (the
original 5-pair Tue-Thu ORB_CORE system) -- runs independently, its own
state/log files, checks the broker's live position list before opening
anything so it can't double up on an instrument the other scripts hold.

DATA SOURCE (updated 2026-07-21): live signal detection pulls bars from
TradeLocker's own /trade/history endpoint -- the actual feed trades
fill against -- instead of Yahoo Finance. This removes both a feed-
mismatch risk (Yahoo vs. the broker's own intrabar highs/lows) and the
recurring Yahoo 500/404/connection-reset errors seen in this account's
first hours live. scalp_scan.py (backtesting) still uses Yahoo, since
its multi-month history depth isn't something TradeLocker's history
endpoint has been tested for -- only live detection changed here, which
only ever needs the last ~2 days of bars to find today's session range.

Run manually (intended to run every few minutes):
    python3 mylifeloading_scalp_live.py
"""
import os
import sys
import json
import datetime
import requests
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import price_action_strategy as pa
import live_monitor as lm

STATE_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_scalp_active.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_scalp_log.json")
BASE = lm.BASE

FX_LOT = 0.20
INDEX_LOT = 0.01
INDEX_PAIRS = {"NAS100", "SPX500", "US30"}

# BANNED 2026-07-22 (explicit, locked-in user instruction): these 6 pairs
# came out net-negative in the 1% risk backtest (mylifeloading_scalp_1pct_backtest.xlsx)
# and must never be traded on this account -- SPX500, US30, AUDJPY, NAS100,
# NZDJPY, AUDUSD. Do not re-add without a fresh backtest showing they've
# turned profitable AND explicit user sign-off.
BANNED_PAIRS = {"SPX500", "US30", "AUDJPY", "NAS100", "NZDJPY", "AUDUSD"}

# One validated (timeframe, session) setup per pair -- see module docstring.
PAIR_CONFIG = {
    "CADJPY": {"timeframe": "15m", "session": "London"},
    "EURAUD": {"timeframe": "15m", "session": "London"},   # Low confidence
    "EURJPY": {"timeframe": "15m", "session": "London"},
    "EURUSD": {"timeframe": "5m", "session": "Asian"},
    "GBPAUD": {"timeframe": "15m", "session": "London"},   # Low confidence
    "GBPCAD": {"timeframe": "15m", "session": "London"},
    "GBPUSD": {"timeframe": "15m", "session": "London"},
    "NZDUSD": {"timeframe": "15m", "session": "Asian"},
    "USDCHF": {"timeframe": "15m", "session": "NY"},
    "USDJPY": {"timeframe": "15m", "session": "London"},
    "XAUUSD": {"timeframe": "15m", "session": "NY"},
}
assert not (BANNED_PAIRS & set(PAIR_CONFIG)), "a banned pair is still in PAIR_CONFIG"
SESSION_HOURS = {"Asian": (0, 3), "London": (7, 10), "NY": (12, 15)}

ORB_MINUTES = 30
BREAKOUT_WINDOW_MIN = 60
SESSION_END_OFFSET_MIN = 180
TARGET_R = 1.5
STOP_BUFFER_ATR = 0.15
FILL_WINDOW_MIN = 15
FRESH_TOLERANCE_MIN = 10  # signal must be within the last ~10 minutes


def load_env():
    return lm.load_env()


TL_RESOLUTION = {"5m": "5m", "15m": "15m"}


def fetch_bars(headers, instrument, timeframe):
    """Pulls bars from TradeLocker's own /trade/history endpoint -- the
    actual price feed trades fill against -- instead of Yahoo Finance.
    Backtesting (scalp_scan.py) still uses Yahoo for its deep multi-month
    history; this is live-signal-detection only, where 2 days of bars is
    plenty to find the current session's opening range and breakout."""
    iid = instrument["tradableInstrumentId"]
    route = lm.find_route(instrument, "INFO")
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=2)
    params = {
        "tradableInstrumentId": iid, "routeId": route,
        "resolution": TL_RESOLUTION[timeframe],
        "from": int(start.timestamp() * 1000), "to": int(end.timestamp() * 1000),
    }
    r = requests.get(f"{BASE}/trade/history", headers=headers, params=params)
    r.raise_for_status()
    resp = r.json()
    if resp.get("s") == "error":
        raise RuntimeError(f"TradeLocker history error: {resp.get('errmsg')}")
    bars = resp["d"]["barDetails"]
    df = pd.DataFrame({
        "open": [b["o"] for b in bars], "high": [b["h"] for b in bars],
        "low": [b["l"] for b in bars], "close": [b["c"] for b in bars],
    })
    df.index = pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True)
    df = df[~df.index.duplicated(keep="first")].dropna().sort_index()
    return df


def tag_session(df, start_h, end_h):
    hours = df.index.hour
    dates = df.index.date
    mask = (hours >= start_h) & (hours < end_h)
    session_id = np.full(len(df), None, dtype=object)
    for i in np.where(mask)[0]:
        session_id[i] = str(dates[i])
    session_open_i = np.full(len(df), -1)
    first_idx = {}
    for i, sid in enumerate(session_id):
        if sid is not None and sid not in first_idx:
            first_idx[sid] = i
    for i, sid in enumerate(session_id):
        session_open_i[i] = first_idx.get(sid, -1) if sid else -1
    return session_id, session_open_i


def in_active_breakout_window(df, session_id, session_open_i, bar_min):
    n = len(df)
    last_i = n - 1
    sid = session_id[last_i]
    if sid is None:
        return False, None
    open_i = session_open_i[last_i]
    if open_i < 0:
        return False, None
    range_bars = max(1, ORB_MINUTES // bar_min)
    breakout_bars = max(1, BREAKOUT_WINDOW_MIN // bar_min)
    range_end = open_i + range_bars
    window_end = range_end + breakout_bars
    if not (range_end <= last_i < min(window_end, n)):
        return False, None
    return True, (open_i, range_end, min(window_end, n))


def scan_for_signal(df, bar_min, open_i, range_end, window_end):
    """Scans the full breakout window from range_end onward (matching the
    backtest's generate_orb exactly, not just the latest bar) so a signal
    isn't missed if this poll lands a bar or two after it actually fired."""
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    atr_ = pa.atr(df, 14).values
    n = len(df)
    r_high = h[open_i:range_end].max()
    r_low = l[open_i:range_end].min()
    if r_high - r_low <= 0:
        return None
    deadline_offset = max(1, SESSION_END_OFFSET_MIN // bar_min)
    deadline_i = min(open_i + deadline_offset, n - 1)
    for j in range(range_end, window_end):
        if np.isnan(atr_[j]) or atr_[j] <= 0:
            continue
        if c[j] > r_high:
            return {"i": j, "dir": 1, "entry": r_high + 1e-9, "stop": r_low - STOP_BUFFER_ATR * atr_[j], "deadline_i": deadline_i}
        if c[j] < r_low:
            return {"i": j, "dir": -1, "entry": r_low - 1e-9, "stop": r_high + STOP_BUFFER_ATR * atr_[j], "deadline_i": deadline_i}
    return None


def check_fresh_signal(name, headers, instrument):
    cfg = PAIR_CONFIG[name]
    df = fetch_bars(headers, instrument, cfg["timeframe"])
    bar_min = 5 if cfg["timeframe"] == "5m" else 15
    sh, eh = SESSION_HOURS[cfg["session"]]
    session_id, session_open_i = tag_session(df, sh, eh)
    active, window = in_active_breakout_window(df, session_id, session_open_i, bar_min)
    if not active:
        return None, f"outside {cfg['session']} breakout window"
    open_i, range_end, window_end = window
    sig = scan_for_signal(df, bar_min, open_i, range_end, window_end)
    if sig is None:
        return None, "no fresh signal"
    last_i = len(df) - 1
    fresh_bars = max(1, FRESH_TOLERANCE_MIN // bar_min)
    if last_i - sig["i"] > fresh_bars:
        return None, "signal is stale (older than freshness tolerance)"
    sig["r_unit"] = abs(sig["entry"] - sig["stop"])
    sig["signal_time"] = str(df.index[sig["i"]])
    sig["deadline_time"] = str(df.index[sig["deadline_i"]])
    return sig, "fresh signal"


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


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH))
        except Exception:
            return {}
    return {}


def save_state(state):
    json.dump(state, open(STATE_PATH, "w"), indent=2)


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
    target = round(ref_price + TARGET_R * r_unit, 5) if direction == 1 else round(ref_price - TARGET_R * r_unit, 5)
    qty = INDEX_LOT if name in INDEX_PAIRS else FX_LOT

    body = {
        "tradableInstrumentId": instrument_id, "routeId": trade_route, "type": "market",
        "side": side, "qty": qty, "validity": "IOC",
        "stopLoss": stop, "stopLossType": "absolute",
        "takeProfit": target, "takeProfitType": "absolute",
    }
    resp = requests.post(f"{BASE}/trade/accounts/{account_id}/orders", headers=headers, json=body)
    result = resp.json()
    log_event({
        "action": "place_trade", "pair": name, "side": side, "qty": qty,
        "timeframe": PAIR_CONFIG[name]["timeframe"], "session": PAIR_CONFIG[name]["session"],
        "ref_price": ref_price, "stop": stop, "target_1_5R": target,
        "signal_time": sig["signal_time"], "deadline_time": sig["deadline_time"], "result": result,
    })
    return result


def close_position(headers, account_id, position_id, name):
    resp = requests.delete(f"{BASE}/trade/accounts/{account_id}/positions/{position_id}", headers=headers)
    result = resp.json() if resp.content else {"status": resp.status_code}
    if resp.status_code == 404:
        resp2 = requests.delete(f"{BASE}/trade/accounts/{account_id}/positions", headers=headers)
        result = {"per_id_404": result, "bulk_close_all": resp2.json() if resp2.content else {"status": resp2.status_code}}
    log_event({"action": "time_stop_close", "pair": name, "position_id": position_id, "result": result})
    return result


def main():
    env = load_env()
    headers = lm.auth(env)
    account_id = env["TL_ACCOUNT_ID"]

    instruments = lm.get_instruments(headers, account_id)
    positions = lm.get_positions(headers, account_id)
    open_by_iid = {str(p[1]): p for p in positions}

    state = load_state()
    now = datetime.datetime.utcnow()

    print(f"=== Mylifeloading Scalp live monitor run {now.isoformat()} UTC ===")
    print(f"Open positions on account: {len(positions)}")

    for iid, rec in list(state.items()):
        if iid not in open_by_iid:
            state.pop(iid, None)
            continue
        deadline = datetime.datetime.fromisoformat(rec["deadline_time"].split("+")[0])
        if now >= deadline:
            pos = open_by_iid[iid]
            print(f"{rec['pair']}: past time-stop deadline ({rec['deadline_time']}) -> closing")
            close_position(headers, account_id, pos[0], rec["pair"])
            state.pop(iid, None)
    save_state(state)

    for name in PAIR_CONFIG:
        if name not in instruments:
            print(f"{name}: not found on broker, skipping")
            continue
        instrument = instruments[name]
        iid = str(instrument["tradableInstrumentId"])
        if iid in open_by_iid:
            print(f"{name}: position already open, skipping (one at a time)")
            continue

        try:
            sig, reason = check_fresh_signal(name, headers, instrument)
        except Exception as e:
            print(f"{name}: ERROR checking signal ({e}) -- skipping this pair this cycle")
            log_event({"action": "check_error", "pair": name, "error": str(e)})
            continue
        if sig is None:
            print(f"{name}: no trade ({reason})")
            continue

        qty = INDEX_LOT if name in INDEX_PAIRS else FX_LOT
        print(f"{name}: FRESH SIGNAL dir={'LONG' if sig['dir']==1 else 'SHORT'} "
              f"(bar {sig['signal_time']}, deadline {sig['deadline_time']}, qty={qty}) -> placing trade")
        result = place_trade(headers, account_id, instrument, sig, name)
        print(f"  order result: {result}")
        if result.get("s") == "ok" or "d" in result:
            state[iid] = {"pair": name, "deadline_time": sig["deadline_time"]}
            save_state(state)


if __name__ == "__main__":
    main()
