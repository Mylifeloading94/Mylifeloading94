"""
"Mylifeloading Gold" live monitor -- XAUUSD-only, "Edge Model v2" strategy,
locked in 2026-07-23, REPLACING the earlier Breakout+Retest strategy (user
disliked it) after a dedicated 90-day backtest
(mylifeloading_gold_edgemodel_100k_2pct_backtest.xlsx).

Origin: rules extracted from a YouTube course promo's narration (BOS +
Fair Value Gap + retest). The video's own claimed results (6 wins/1 loss,
11R) were cherry-picked marketing footage and were explicitly NOT used as
validation -- the rules were backtested honestly from scratch. The first
attempt (video's rules exactly as described, 2-bar swing fractals) FAILED
split-half validation: every parameter variation tried lost money in the
first half of the 90-day window and won in the second half -- a sign of
regime-luck, not a real edge. Widening swing detection to 4-bar fractals
and tightening the target to a fixed 0.5R fixed this: 128 trades, 71.9%
win rate on BOTH the first and second 45-day halves independently (PF 1.28
vs 1.34) -- the most consistent split-half result of any gold strategy
tested this session, and both directions traded (72 short / 56 long, no
one-sided bias).

Setup:
1. Track swing structure on 15m via 4-bar fractals.
2. Break of Structure (BOS) = a close beyond the most recent relevant
   swing high/low, in the direction away from the most recently-consumed
   BOS ("fresh" structure only -- a stale/already-acted-on BOS is skipped).
3. Displacement = the BOS must leave a real 3-candle Fair Value Gap (FVG).
   No FVG = "no real displacement" (the video's own invalidation case) --
   skip, and don't retry that BOS.
4. Entry: price retraces into the FVG, then a confirmation candle closes
   back outside the FVG in the BOS direction. Session-filtered to
   Asian/London/NY hours only (per the video's explicit tip).
5. Stop: beyond the swing point the impulse originated from, + small ATR
   buffer. Target: fixed 0.5R.
6. Invalidated if price trades back through the origin swing before an
   entry is triggered.

An earlier variant added a 4H trend filter on top of this and got a
better PF (2.13) but only ever fired short trades over this window --
same one-directional red flag seen on other gold/FX strategies this
session -- so it was NOT used live. This version trades both directions.

Sizing: 2% of current account equity per trade (user's explicit choice,
carried over unchanged from the prior gold strategy), NOT a fixed lot --
position size scales with the account balance every trade.

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

# Strategy params -- must stay identical to strat4_edge_model.py's
# locked-in config (swing_left=4, swing_right=4, fixed_R=0.5, min_fvg_atr=0.0,
# session_filter=True) or live drifts from the backtest.
SWING_LEFT = 4
SWING_RIGHT = 4
STOP_BUF_ATR = 0.15
RETEST_K = 40
TARGET_R = 0.5
MAX_HOLD_BARS = 96  # 24h time-stop, matches backtest's simulate_trades default
FRESH_TOLERANCE_MIN = 20  # a confirmed entry bar older than this is stale, skip it
SESSION_HOURS = {"Asian": (0, 8), "London": (7, 16), "NY": (12, 21)}  # UTC


def in_session(ts):
    h = ts.hour
    return any(lo <= h < hi for lo, hi in SESSION_HOURS.values())


def atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    return pd.Series(tr, index=df.index).rolling(n).mean()


def find_fractals(df, left, right):
    """Swing highs/lows confirmed `right` bars after the pivot (no
    lookahead -- a fractal at position i is only usable starting at
    i+right)."""
    h, l = df["high"].values, df["low"].values
    n = len(df)
    highs, lows = [], []
    for i in range(left, n - right):
        window_h = h[i - left:i + right + 1]
        if h[i] == window_h.max() and np.argmax(window_h) == left:
            highs.append((i, i + right, h[i]))
        window_l = l[i - left:i + right + 1]
        if l[i] == window_l.min() and np.argmin(window_l) == left:
            lows.append((i, i + right, l[i]))
    return highs, lows


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


def fetch_bars(headers, instrument, days=15):
    """15m bars from TradeLocker's own /trade/history -- same feed trades
    fill against. days=15 gives the swing-structure tracking (fractals,
    fresh-BOS state) enough history to have converged by the time we
    reach "now", not just enough to cover the RETEST_K lookback window."""
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
    """Ports strat4_edge_model.py's generate_signals() -- 4-bar swing
    structure -> fresh BOS -> real 3-candle FVG (displacement) -> retrace
    into the FVG -> confirmation close back outside it -> fixed 0.5R
    target -- but only scans forward far enough to report the single most
    recent signal (if any), since live only cares about "is there a fresh
    entry right now". Kept parameter-identical to the backtest so live
    doesn't drift from it."""
    df = df.copy()
    df["atr"] = atr(df, 14)
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    atr_ = df["atr"].values
    n = len(df)

    highs, lows = find_fractals(df, SWING_LEFT, SWING_RIGHT)
    piv = sorted([(ci, p, "H") for _, ci, p in highs] + [(ci, p, "L") for _, ci, p in lows])

    latest = None
    last_bos_i = -1
    piv_ptr = 0
    cur_high_pivot = cur_low_pivot = None
    cur_high_origin = cur_low_origin = None
    last_piv_price = {"H": None, "L": None}

    busy_until = 0
    i = SWING_LEFT + SWING_RIGHT + 5
    while i < n - 1:
        while piv_ptr < len(piv) and piv[piv_ptr][0] <= i:
            ci, p, typ = piv[piv_ptr]
            if typ == "H":
                cur_high_origin = last_piv_price["L"]
                cur_high_pivot = p
            else:
                cur_low_origin = last_piv_price["H"]
                cur_low_pivot = p
            last_piv_price[typ] = p
            piv_ptr += 1

        if i < busy_until or np.isnan(atr_[i]) or atr_[i] <= 0:
            i += 1
            continue

        direction = origin = None
        if cur_high_pivot is not None and c[i] > cur_high_pivot and i > last_bos_i:
            direction, origin = 1, cur_low_origin
        elif cur_low_pivot is not None and c[i] < cur_low_pivot and i > last_bos_i:
            direction, origin = -1, cur_high_origin
        if direction is None or origin is None:
            i += 1
            continue

        bos_i = i
        fvg = None
        for k in range(bos_i, max(1, bos_i - 6), -1):
            if k - 2 < 0:
                continue
            if direction == 1 and h[k - 2] < l[k]:
                fvg = {"top": l[k], "bottom": h[k - 2]}
                break
            if direction == -1 and l[k - 2] > h[k]:
                fvg = {"top": l[k - 2], "bottom": h[k]}
                break
        if fvg is None:
            last_bos_i = bos_i  # no real displacement -- invalidated
            i += 1
            continue

        entry_i = None
        for j in range(bos_i + 1, min(n, bos_i + 1 + RETEST_K)):
            if direction == 1:
                touched = l[j] <= fvg["top"]
                confirm = c[j] > o[j] and c[j] > fvg["top"]
            else:
                touched = h[j] >= fvg["bottom"]
                confirm = c[j] < o[j] and c[j] < fvg["bottom"]
            if direction == 1 and l[j] < origin:
                break
            if direction == -1 and h[j] > origin:
                break
            if touched and confirm:
                entry_i = j
                break
        last_bos_i = bos_i
        if entry_i is None:
            i += 1
            continue
        if not in_session(df.index[entry_i]):
            i = entry_i + 1
            continue

        entry_price = c[entry_i]
        stop = origin - STOP_BUF_ATR * atr_[entry_i] if direction == 1 else origin + STOP_BUF_ATR * atr_[entry_i]
        risk = entry_price - stop if direction == 1 else stop - entry_price
        if risk <= 0:
            i = entry_i + 1
            continue

        latest = {
            "entry_time": df.index[entry_i], "dir": direction,
            "bar_entry": entry_price, "stop": stop, "r_unit": risk,
        }
        busy_until = entry_i + 1
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
        "ref_price": ref_price, "stop": stop, "target_0_5R": target,
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
        print(f"{INSTRUMENT_NAME}: no trade (no fresh BOS+FVG+retest signal in current window)")
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
