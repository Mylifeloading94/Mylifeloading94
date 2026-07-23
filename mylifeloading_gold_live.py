"""
"Mylifeloading Gold" live monitor -- XAUUSD-only, 15m Breakout + Retest
strategy, locked in 2026-07-22 after a dedicated 90-day backtest
(mylifeloading_gold_strategy_backtest.xlsx, S3 sheet).

Setup: on the 15m chart, find N-bar consolidation ranges (width < a
multiple of ATR), wait for a strong-bodied close beyond the range
(breakout), then wait up to K bars for price to pull back and retest the
broken level with a confirmation candle back in the breakout direction --
that retest candle is the entry.

Target was deliberately shrunk to a fixed 0.3R (instead of the original
measured-move target) to hit the user's explicit ">=60%, aim for 80%"
win-rate request. This is a real tradeoff, not a free upgrade: at 0.3R
target / 1R stop, breakeven win rate is 76.9%, so the strategy only nets
out profitable (PF 1.22 in the 90-day backtest, both directions, 114
trades, split-half consistent at ~80% WR on each half) because it clears
that bar -- a single stop-out erases about 3-4 average wins. This is a
thinner, more streak-sensitive edge than the 60%-WR / PF-1.72 version of
the same setup (measured-move target) that was also tested; see the
Summary tab of the backtest workbook for that comparison.

Sizing: 2% of current account equity per trade (explicit user choice,
2026-07-22), NOT a fixed lot like the FX scalp bot -- position size scales
with the account balance every trade, same compounding-risk methodology
used in the backtest spreadsheet.

Separate from mylifeloading_scalp_live.py (11-pair FX ORB scalp, paused)
and live_monitor.py/intraday_live_monitor.py -- runs independently, own
state/log files, checks the broker's live position list before opening
anything so it can't double up on an XAUUSD position another script holds.

Run manually (intended to run every ~1-5 minutes):
    python3 mylifeloading_gold_live.py
"""
import os
import sys
import json
import datetime
import requests
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import live_monitor as lm

STATE_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_gold_active.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_gold_log.json")
TRADED_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_gold_traded.json")
# Presence of this file halts all NEW entries. Time-stop closes on any
# already-open position still run. Delete the file to resume.
PAUSE_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_gold_PAUSED")
BASE = lm.BASE

INSTRUMENT_NAME = "XAUUSD"
RISK_PCT = 0.02  # explicit user choice, 2026-07-22
PIP = 0.01  # XAUUSD "cent-pip" convention (see backtest workbook note)
DOLLAR_PER_PIP_PER_LOT = 1.0  # 100oz/lot x $0.01 = $1/pip/1.00 lot -- standard
# convention, not separately confirmed against this broker's contract spec.

# Strategy params -- must stay identical to strat3_breakout_retest.py's
# locked-in config (range_n=20, mult=4.0, body=0.5, tol=0.3, K=20,
# target_R fixed at 0.3, stop_buf=0.10) or live drifts from the backtest.
RANGE_N = 20
RANGE_ATR_MULT = 4.0
BODY_FRAC = 0.5
RETEST_K = 20
RETEST_TOL_ATR = 0.3
STOP_BUF_ATR = 0.10
TARGET_R = 0.3
COOLDOWN_BARS = 8
MAX_HOLD_BARS = 96  # 24h time-stop, matches backtest's simulate_trades default
FRESH_TOLERANCE_MIN = 20  # a confirmed entry bar older than this is stale, skip it


def atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    return pd.Series(tr, index=df.index).rolling(n).mean()


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


def save_state(state):
    json.dump(state, open(STATE_PATH, "w"), indent=2)


def load_traded():
    if not os.path.exists(TRADED_PATH):
        return set()
    try:
        raw = json.load(open(TRADED_PATH))
    except Exception:
        return set()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=5)).isoformat()
    return {k for k in raw if k >= cutoff}


def save_traded(keys):
    json.dump(sorted(keys), open(TRADED_PATH, "w"), indent=2)


def log_event(event):
    events = []
    if os.path.exists(LOG_PATH):
        try:
            events = json.load(open(LOG_PATH))
        except Exception:
            events = []
    event["ts"] = datetime.datetime.utcnow().isoformat()
    events.append(event)
    json.dump(events[-2000:], open(LOG_PATH, "w"), indent=2)


def fetch_bars(headers, instrument, days=6):
    """15m bars from TradeLocker's own /trade/history -- same feed trades
    fill against. days=6 comfortably covers RANGE_N + ATR warmup + the
    RETEST_K lookback window with margin for weekends/thin sessions."""
    iid = instrument["tradableInstrumentId"]
    route = lm.find_route(instrument, "INFO")
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=days)
    params = {
        "tradableInstrumentId": iid, "routeId": route, "resolution": "15m",
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


def find_latest_signal(df):
    """Ports strat3_breakout_retest.py's generate_signals() -- range ->
    breakout -> retest+confirmation -> fixed 0.3R target -- but only scans
    forward far enough to report the single most recent signal (if any),
    since live only cares about "is there a fresh entry right now". Kept
    parameter-identical to the backtest so live doesn't drift from it."""
    df = df.copy()
    df["atr"] = atr(df, 14)
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    atr_ = df["atr"].values
    n = len(df)

    latest = None
    last_entry_i = -999
    i = RANGE_N + 20
    while i < n - 1:
        if np.isnan(atr_[i]) or atr_[i] <= 0:
            i += 1
            continue
        if i - last_entry_i < COOLDOWN_BARS:
            i += 1
            continue
        lo = i - RANGE_N
        rng_high = h[lo:i].max()
        rng_low = l[lo:i].min()
        rng_width = rng_high - rng_low
        if rng_width <= 0 or rng_width > RANGE_ATR_MULT * atr_[i]:
            i += 1
            continue
        body = abs(c[i] - o[i])
        bar_range = h[i] - l[i]
        if bar_range <= 0 or body / bar_range < BODY_FRAC:
            i += 1
            continue

        direction = None
        if c[i] > rng_high:
            direction = 1
        elif c[i] < rng_low:
            direction = -1
        if direction is None:
            i += 1
            continue

        level = rng_high if direction == 1 else rng_low
        tol = RETEST_TOL_ATR * atr_[i]
        entry_i = None
        for j in range(i + 1, min(n, i + 1 + RETEST_K)):
            if direction == 1:
                touched = l[j] <= level + tol
                confirm = c[j] > o[j] and c[j] > level - tol
            else:
                touched = h[j] >= level - tol
                confirm = c[j] < o[j] and c[j] < level + tol
            if touched and confirm:
                entry_i = j
                break
        if entry_i is None:
            i += 1
            continue

        stop = (rng_low - STOP_BUF_ATR * atr_[entry_i]) if direction == 1 else (rng_high + STOP_BUF_ATR * atr_[entry_i])
        risk = (c[entry_i] - stop) if direction == 1 else (stop - c[entry_i])
        if risk <= 0:
            last_entry_i = entry_i
            i = entry_i + 1
            continue

        latest = {
            "entry_time": df.index[entry_i], "dir": direction,
            "bar_entry": c[entry_i], "stop": stop, "r_unit": risk,
        }
        last_entry_i = entry_i
        i = entry_i + 1

    return latest


def get_balance(headers, account_id):
    r = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=headers)
    r.raise_for_status()
    for acc in r.json().get("accounts", []):
        if acc["id"] == str(account_id):
            return float(acc["accountBalance"])
    raise RuntimeError(f"account {account_id} not found in all-accounts response")


def place_trade(headers, account_id, instrument, sig):
    instrument_id = instrument["tradableInstrumentId"]
    trade_route = lm.find_route(instrument, "TRADE")
    info_route = lm.find_route(instrument, "INFO")
    quote = lm.get_quote(headers, instrument_id, info_route)

    direction = sig["dir"]
    side = "buy" if direction == 1 else "sell"
    ref_price = quote["ap"] if direction == 1 else quote["bp"]
    r_unit = sig["r_unit"]
    stop = round(ref_price - r_unit, 3) if direction == 1 else round(ref_price + r_unit, 3)
    target = round(ref_price + TARGET_R * r_unit, 3) if direction == 1 else round(ref_price - TARGET_R * r_unit, 3)

    balance = get_balance(headers, account_id)
    dollar_risk = balance * RISK_PCT
    stop_pips = r_unit / PIP
    qty = round(dollar_risk / (stop_pips * DOLLAR_PER_PIP_PER_LOT), 2) if stop_pips > 0 else 0.01
    qty = max(qty, 0.01)

    body = {
        "tradableInstrumentId": instrument_id, "routeId": trade_route, "type": "market",
        "side": side, "qty": qty, "validity": "IOC",
        "stopLoss": stop, "stopLossType": "absolute",
        "takeProfit": target, "takeProfitType": "absolute",
    }
    resp = requests.post(f"{BASE}/trade/accounts/{account_id}/orders", headers=headers, json=body)
    result = resp.json()
    log_event({
        "action": "place_trade", "side": side, "qty": qty, "balance": balance,
        "risk_pct": RISK_PCT, "dollar_risk": round(dollar_risk, 2),
        "ref_price": ref_price, "stop": stop, "target_0_3R": target,
        "signal_entry_time": str(sig["entry_time"]), "result": result,
    })
    return result, qty


def close_position(headers, account_id, position_id):
    resp = requests.delete(f"{BASE}/trade/accounts/{account_id}/positions/{position_id}", headers=headers)
    result = resp.json() if resp.content else {"status": resp.status_code}
    if resp.status_code == 404:
        resp2 = requests.delete(f"{BASE}/trade/accounts/{account_id}/positions", headers=headers)
        result = {"per_id_404": result, "bulk_close_all": resp2.json() if resp2.content else {"status": resp2.status_code}}
    log_event({"action": "time_stop_close", "position_id": position_id, "result": result})
    return result


def main():
    env = lm.load_env()
    headers = lm.auth(env)
    account_id = env["TL_ACCOUNT_ID"]

    instruments = lm.get_instruments(headers, account_id)
    positions = lm.get_positions(headers, account_id)
    open_by_iid = {str(p[1]): p for p in positions}

    state = load_state()
    traded = load_traded()
    now = datetime.datetime.utcnow()

    print(f"=== Mylifeloading Gold live monitor run {now.isoformat()} UTC ===")
    print(f"Open positions on account: {len(positions)}")

    for iid, rec in list(state.items()):
        if iid not in open_by_iid:
            state.pop(iid, None)
            continue
        deadline = datetime.datetime.fromisoformat(rec["deadline_time"].split("+")[0])
        if now >= deadline:
            pos = open_by_iid[iid]
            print(f"XAUUSD: past time-stop deadline ({rec['deadline_time']}) -> closing")
            close_position(headers, account_id, pos[0])
            state.pop(iid, None)
    save_state(state)

    if os.path.exists(PAUSE_PATH):
        print("PAUSED: new entries disabled by user (delete mylifeloading_gold_PAUSED to resume) -- skipping")
        return

    if INSTRUMENT_NAME not in instruments:
        print(f"{INSTRUMENT_NAME}: not found on broker, skipping")
        return
    instrument = instruments[INSTRUMENT_NAME]
    iid = str(instrument["tradableInstrumentId"])
    if iid in open_by_iid:
        print(f"{INSTRUMENT_NAME}: position already open, skipping (one at a time)")
        return

    try:
        df = fetch_bars(headers, instrument)
        sig = find_latest_signal(df)
    except Exception as e:
        print(f"{INSTRUMENT_NAME}: ERROR checking signal ({e}) -- skipping this cycle")
        log_event({"action": "check_error", "error": str(e)})
        return

    if sig is None:
        print(f"{INSTRUMENT_NAME}: no trade (no breakout+retest signal in current window)")
        return

    age_min = (now - sig["entry_time"].tz_localize(None)).total_seconds() / 60
    if age_min > FRESH_TOLERANCE_MIN:
        print(f"{INSTRUMENT_NAME}: no trade (last signal at {sig['entry_time']} is {age_min:.0f} min old, stale)")
        return

    entry_key = str(sig["entry_time"])
    if entry_key in traded:
        print(f"{INSTRUMENT_NAME}: already traded this signal ({entry_key}), skipping")
        return

    print(f"{INSTRUMENT_NAME}: FRESH SIGNAL dir={'LONG' if sig['dir']==1 else 'SHORT'} "
          f"(bar {sig['entry_time']}, r_unit={sig['r_unit']:.3f}) -> placing trade")
    result, qty = place_trade(headers, account_id, instrument, sig)
    print(f"  order result: {result} (qty={qty})")
    if result.get("s") == "ok" or "d" in result:
        deadline_time = sig["entry_time"] + datetime.timedelta(minutes=15 * MAX_HOLD_BARS)
        state[iid] = {"deadline_time": str(deadline_time)}
        save_state(state)
        traded.add(entry_key)
        save_traded(traded)


if __name__ == "__main__":
    main()
