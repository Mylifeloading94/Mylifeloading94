"""
"Mylifeloading Portfolio" live monitor -- THE single, main live strategy on
this account, locked in 2026-07-23. Everything else (mylifeloading_gold_live.py
standalone, mylifeloading_scalp_live.py, live_monitor.py, intraday_live_monitor.py)
is paused and superseded. See ALL_STRATEGIES_PAUSED guard in live_monitor.py /
intraday_live_monitor.py, and the PAUSE files next to the other two scripts.

Strategy: "Edge Model v3 (STRICT)" -- BOS + Fair Value Gap + retest, rules
originally extracted from a YouTube course promo's narration, backtested
honestly (NOT the video's cherry-picked marketing claims), then tightened
with two quality filters (confirmation candle needs a real body; setups
with excessive stop distance are rejected as sloppy/illiquid structure).

Run on 6 instruments, each with its OWN independently re-validated
parameters -- the exact gold config does NOT transfer to FX as-is (tested
on 10 pairs, 8 lost money outright), so each FX pair here went through its
own 720-combination parameter search and had to independently clear the
same split-half bar (both the first and second halves of the 90-day
backtest window must clear PF >= 1.3) before being included:

  XAUUSD: swing 4/4, target 0.5R, confirm body >=30%, max stop <=2.0x ATR
  CADJPY: swing 4/4, target 0.4R, confirm body >=30%, max stop <=2.0x ATR
  EURUSD: swing 3/3, target 0.5R, confirm body >=30%, max stop <=1.5x ATR, min FVG >=0.1x ATR
  GBPCAD: swing 4/4, target 0.5R, confirm body >=30%, max stop <=2.0x ATR, min FVG >=0.1x ATR (weakest pass -- first to drop if it underperforms)
  GBPUSD: swing 3/3, target 0.5R, confirm body >=40%, max stop <=2.0x ATR, min FVG >=0.1x ATR
  NZDUSD: swing 4/4, target 0.5R, confirm body >=50%, max stop <=3.0x ATR, min FVG >=0.1x ATR

5 pairs (EURAUD, EURJPY, GBPAUD, USDCHF, USDJPY) found NO configuration
that passed even after the full search and are explicitly NOT traded.

90-day combined backtest (mylifeloading_portfolio_gold_fx_100k_backtest.xlsx):
259 signals, 235 taken, 79.6% win rate, PF 1.68, $100k -> $194,601.70
(+94.6%), max drawdown 7.77%.

CONCURRENCY CAVEAT (real, not hypothetical -- read before trusting sizing):
59 of 67 backtest trading days had 2+ of these 6 instruments signal on the
same day, up to all 6 at once. The daily loss cap below only blocks NEW
entries once today's REALIZED loss hits its threshold -- it does NOT cap
how many 2%-risk positions can be open AT THE SAME TIME before any of them
close. Running 6 instruments on one account is not full diversification;
treat the backtest ROI as an upper bound.

Sizing: 2% of current account equity per trade, scaled per-instrument by
its own pip value. Daily loss cap: 2% of TODAY'S OPENING BALANCE, shared
across the whole account (not per-instrument) -- tracked via the account's
actual balance, so it naturally aggregates whatever this script does.

Run manually (intended to run every ~1-5 minutes):
    python3 mylifeloading_portfolio_live.py
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

STATE_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_portfolio_active.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_portfolio_log.json")
TRADED_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_portfolio_traded.json")
# Presence of this file halts all NEW entries on every instrument. Time-stop
# closes on already-open positions still run. Delete the file to resume.
PAUSE_PATH = os.path.join(os.path.dirname(__file__), "mylifeloading_portfolio_PAUSED")
BASE = lm.BASE

RISK_PCT = 0.02
STOP_BUF_ATR = 0.15
RETEST_K = 40
MAX_HOLD_BARS = 96  # 24h time-stop
FRESH_TOLERANCE_MIN = 20
SESSION_HOURS = {"Asian": (0, 8), "London": (7, 16), "NY": (12, 21)}  # UTC

# Per-instrument: pip size, $/pip/1.00 lot, and its own re-validated strategy
# params. $/pip/lot values are simplified fixed approximations consistent
# with the convention already used elsewhere in this repo -- not live
# cross-rate-adjusted.
INSTRUMENTS = {
    "XAUUSD": {"pip": 0.01, "pip_val": 1.00,
               "params": dict(swing_left=4, swing_right=4, fixed_R=0.5, min_fvg_atr=0.0,
                               confirm_body_frac=0.3, max_risk_atr=2.0)},
    "CADJPY": {"pip": 0.01, "pip_val": 6.70,
               "params": dict(swing_left=4, swing_right=4, fixed_R=0.4, min_fvg_atr=0.0,
                               confirm_body_frac=0.3, max_risk_atr=2.0)},
    "EURUSD": {"pip": 0.0001, "pip_val": 10.00,
               "params": dict(swing_left=3, swing_right=3, fixed_R=0.5, min_fvg_atr=0.1,
                               confirm_body_frac=0.3, max_risk_atr=1.5)},
    "GBPCAD": {"pip": 0.0001, "pip_val": 7.30,
               "params": dict(swing_left=4, swing_right=4, fixed_R=0.5, min_fvg_atr=0.1,
                               confirm_body_frac=0.3, max_risk_atr=2.0)},
    "GBPUSD": {"pip": 0.0001, "pip_val": 10.00,
               "params": dict(swing_left=3, swing_right=3, fixed_R=0.5, min_fvg_atr=0.1,
                               confirm_body_frac=0.4, max_risk_atr=2.0)},
    "NZDUSD": {"pip": 0.0001, "pip_val": 10.00,
               "params": dict(swing_left=4, swing_right=4, fixed_R=0.5, min_fvg_atr=0.1,
                               confirm_body_frac=0.5, max_risk_atr=3.0)},
}


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
    return {k for k in raw if k.split("|")[-1] >= cutoff}


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
    json.dump(events[-3000:], open(LOG_PATH, "w"), indent=2)


def fetch_bars(headers, instrument, days=15):
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


def find_latest_signal(df, params):
    """Ports strat4_edge_model.py's generate_signals() -- swing structure ->
    fresh BOS -> real FVG (displacement) -> retrace into the FVG ->
    high-conviction confirmation close back outside it -> fixed-R target --
    but only reports the single most recent signal, since live only cares
    about "is there a fresh entry right now". Parameter-identical to each
    instrument's locked backtest config."""
    swing_left, swing_right = params["swing_left"], params["swing_right"]
    fixed_R = params["fixed_R"]
    min_fvg_atr = params["min_fvg_atr"]
    confirm_body_frac = params["confirm_body_frac"]
    max_risk_atr = params["max_risk_atr"]

    df = df.copy()
    df["atr"] = atr(df, 14)
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    atr_ = df["atr"].values
    n = len(df)

    highs, lows = find_fractals(df, swing_left, swing_right)
    piv = sorted([(ci, p, "H") for _, ci, p in highs] + [(ci, p, "L") for _, ci, p in lows])

    latest = None
    last_bos_i = -1
    piv_ptr = 0
    cur_high_pivot = cur_low_pivot = None
    cur_high_origin = cur_low_origin = None
    last_piv_price = {"H": None, "L": None}

    busy_until = 0
    i = swing_left + swing_right + 5
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
            last_bos_i = bos_i
            i += 1
            continue
        if (fvg["top"] - fvg["bottom"]) < min_fvg_atr * atr_[bos_i]:
            last_bos_i = bos_i
            i += 1
            continue

        entry_i = None
        for j in range(bos_i + 1, min(n, bos_i + 1 + RETEST_K)):
            bar_range = h[j] - l[j]
            body_ok = bar_range > 0 and abs(c[j] - o[j]) / bar_range >= confirm_body_frac
            if direction == 1:
                touched = l[j] <= fvg["top"]
                confirm = c[j] > o[j] and c[j] > fvg["top"] and body_ok
            else:
                touched = h[j] >= fvg["bottom"]
                confirm = c[j] < o[j] and c[j] < fvg["bottom"] and body_ok
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
        if risk > max_risk_atr * atr_[entry_i]:
            i = entry_i + 1
            continue

        latest = {
            "entry_time": df.index[entry_i], "dir": direction,
            "bar_entry": entry_price, "stop": stop, "r_unit": risk,
            "target_R": fixed_R,
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


def place_trade(headers, account_id, instrument, name, sig, pip, pip_val):
    instrument_id = instrument["tradableInstrumentId"]
    trade_route = lm.find_route(instrument, "TRADE")
    info_route = lm.find_route(instrument, "INFO")
    quote = lm.get_quote(headers, instrument_id, info_route)

    direction = sig["dir"]
    side = "buy" if direction == 1 else "sell"
    ref_price = quote["ap"] if direction == 1 else quote["bp"]
    r_unit = sig["r_unit"]
    target_R = sig["target_R"]
    stop = round(ref_price - r_unit, 5) if direction == 1 else round(ref_price + r_unit, 5)
    target = round(ref_price + target_R * r_unit, 5) if direction == 1 else round(ref_price - target_R * r_unit, 5)

    balance = get_balance(headers, account_id)
    dollar_risk = balance * RISK_PCT
    stop_pips = r_unit / pip
    qty = round(dollar_risk / (stop_pips * pip_val), 2) if stop_pips > 0 else 0.01
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
        "action": "place_trade", "pair": name, "side": side, "qty": qty, "balance": balance,
        "risk_pct": RISK_PCT, "dollar_risk": round(dollar_risk, 2),
        "ref_price": ref_price, "stop": stop, "target": target,
        "signal_entry_time": str(sig["entry_time"]), "result": result,
    })
    return result, qty


def close_position(headers, account_id, position_id, name):
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
    traded = load_traded()
    now = datetime.datetime.utcnow()

    print(f"=== Mylifeloading Portfolio live monitor run {now.isoformat()} UTC ===")
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

    if os.path.exists(PAUSE_PATH):
        print("PAUSED: new entries disabled by user (delete mylifeloading_portfolio_PAUSED to resume) -- skipping")
        return

    for name, cfg in INSTRUMENTS.items():
        if name not in instruments:
            print(f"{name}: not found on broker, skipping")
            continue
        instrument = instruments[name]
        iid = str(instrument["tradableInstrumentId"])
        if iid in open_by_iid:
            print(f"{name}: position already open, skipping (one at a time)")
            continue

        try:
            df = fetch_bars(headers, instrument)
            sig = find_latest_signal(df, cfg["params"])
        except Exception as e:
            print(f"{name}: ERROR checking signal ({e}) -- skipping this cycle")
            log_event({"action": "check_error", "pair": name, "error": str(e)})
            continue

        if sig is None:
            print(f"{name}: no trade (no fresh BOS+FVG+retest signal in current window)")
            continue

        age_min = (now - sig["entry_time"].tz_localize(None)).total_seconds() / 60
        if age_min > FRESH_TOLERANCE_MIN:
            print(f"{name}: no trade (last signal at {sig['entry_time']} is {age_min:.0f} min old, stale)")
            continue

        entry_key = f"{name}|{sig['entry_time']}"
        if entry_key in traded:
            print(f"{name}: already traded this signal ({entry_key}), skipping")
            continue

        print(f"{name}: FRESH SIGNAL dir={'LONG' if sig['dir']==1 else 'SHORT'} "
              f"(bar {sig['entry_time']}, r_unit={sig['r_unit']:.5f}, target={sig['target_R']}R) -> placing trade")
        result, qty = place_trade(headers, account_id, instrument, name, sig, cfg["pip"], cfg["pip_val"])
        print(f"  order result: {result} (qty={qty})")
        if result.get("s") == "ok" or "d" in result:
            deadline_time = sig["entry_time"] + datetime.timedelta(minutes=15 * MAX_HOLD_BARS)
            state[iid] = {"pair": name, "deadline_time": str(deadline_time)}
            save_state(state)
            traded.add(entry_key)
            save_traded(traded)


if __name__ == "__main__":
    main()
