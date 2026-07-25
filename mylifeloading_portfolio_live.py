"""
"Mylifeloading Portfolio" live monitor -- THE single, main live strategy on
this account, locked in 2026-07-23, revised to V4 on 2026-07-24. Everything
else (mylifeloading_gold_live.py standalone, mylifeloading_scalp_live.py,
live_monitor.py, intraday_live_monitor.py) is paused and superseded. See
ALL_STRATEGIES_PAUSED guard in live_monitor.py / intraday_live_monitor.py,
and the PAUSE files next to the other two scripts.

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
  GBPCAD: swing 4/4, target 0.5R, confirm body >=30%, max stop <=1.75x ATR (tightened from 2.0x on
          2026-07-24 -- this pair's widest-stop quartile ran PF 0.88 on a fresh 90d check, below
          breakeven, while the other three quartiles ran PF 1.33-2.00), min FVG >=0.1x ATR
          (still the weakest of the 6 pairs by PF -- first to drop if it keeps underperforming)
  GBPUSD: swing 3/3, target 0.5R, confirm body >=40%, max stop <=2.0x ATR, min FVG >=0.1x ATR
  NZDUSD: swing 4/4, target 0.5R, confirm body >=50%, max stop <=3.0x ATR, min FVG >=0.1x ATR

5 pairs (EURAUD, EURJPY, GBPAUD, USDCHF, USDJPY) found NO configuration
that passed even after the full search and are explicitly NOT traded.

V4 90-day backtest (mylifeloading_portfolio_backtest_v3.py, freshly refetched
from this account's own TradeLocker feed on 2026-07-24, not a cached/stale
number): 210 trades taken, 80.0% win rate, PF 1.80, $100k -> $216,323.69
(+116.3%), max drawdown 8.70%. This replaces V1's live numbers (haven-bloc
guard only: 230 trades, 77.8% win rate, PF 1.63, $200,822.81, DD 8.70%) --
V4 beat V1 on every metric on the same fresh window. See
mylifeloading_portfolio_backtest_v3.py for the full V0-V4 comparison and the
per-pair breakdown, and the "Investigation & Improvement Report" artifact
generated 2026-07-24 for the real-trade reconciliation.

CONCURRENCY CAVEAT (real, not hypothetical -- read before trusting sizing):
most backtest trading days have 2+ of these 6 instruments signal on the same
day, up to all 6 at once. The correlation guard below (CURRENCY_GUARD) stops
new entries that would duplicate an already-open position's net exposure to
any of the 7 currencies this book touches, but it does NOT cap total
simultaneous risk across genuinely uncorrelated pairs -- running 6
instruments on one account is still not full diversification even with the
guard on; treat the backtest ROI as an upper bound. There is no daily loss
cap (removed 2026-07-24 at the account owner's request) and no cap on how
many uncorrelated positions can be open at once -- only the per-trade 2%
sizing and the correlation guard constrain risk.

Sizing: 2% of current account equity per trade, scaled per-instrument by
its own pip value.

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

# Currency-netting correlation guard, v2 as of 2026-07-24. v1 (haven-bloc
# only, {USD, JPY, CHF}) was added after 5 of 6 real losses turned out to be
# simultaneously-open positions that were all the same macro bet -- e.g.
# EURUSD/GBPUSD/CADJPY/NZDUSD all bought within the same hour, XAUUSD/NZDUSD
# bought 8 seconds apart. But checking every pair of the 6 traded instruments
# for shared currency legs found v1 was still missing two real correlations:
# CADJPY <-> GBPCAD (both touch CAD) and GBPCAD <-> GBPUSD (both touch GBP).
# v2 nets exposure across ALL 7 currencies this book touches, not just 3 of
# them. A new entry is skipped if it would duplicate an already-open
# position's net direction on ANY shared currency. Validated on a fresh
# 90-day backtest (mylifeloading_portfolio_backtest_v3.py): full-guard V4
# beat the v1-guard baseline on every metric (80.0% win rate vs 77.8%, PF
# 1.80 vs 1.63, $216,324 vs $200,823 on $100k, same 8.70% max drawdown).
LEGS = {
    "XAUUSD": ("XAU", "USD"),
    "CADJPY": ("CAD", "JPY"),
    "EURUSD": ("EUR", "USD"),
    "GBPCAD": ("GBP", "CAD"),
    "GBPUSD": ("GBP", "USD"),
    "NZDUSD": ("NZD", "USD"),
}
ALL_CURRENCIES = {c for legs in LEGS.values() for c in legs}
# Setups with a stop smaller than this many ATRs are rejected as noise, not
# real structure -- the 90-day backtest's tightest risk_atr quartile ran
# PF 1.07 vs 1.98-3.49 for the wider quartiles. Backtest-supported floor,
# symmetric with each pair's existing max_risk_atr ceiling.
MIN_RISK_ATR = 0.8


def currency_exposure(pair, direction):
    """Net signed exposure to each currency this pair touches. +1 = long
    that currency, -1 = short, 0 = not held."""
    base, quote = LEGS[pair]
    sign = 1 if direction == 1 else -1
    return {base: sign, quote: -sign}

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
                               confirm_body_frac=0.3, max_risk_atr=1.75)},
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
        if risk < MIN_RISK_ATR * atr_[entry_i]:
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
    iid_to_name = {str(inst["tradableInstrumentId"]): name for name, inst in instruments.items()}
    open_exposures = []
    for p in positions:
        pair_name = iid_to_name.get(str(p[1]))
        if pair_name is None or pair_name not in LEGS:
            continue
        pos_dir = 1 if p[3] == "buy" else -1
        open_exposures.append(currency_exposure(pair_name, pos_dir))

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

        sig_expo = currency_exposure(name, sig["dir"])
        blocked_currency = next(
            (c for c in sig_expo if sig_expo[c] != 0
             and any(oe.get(c, 0) == sig_expo[c] for oe in open_exposures)),
            None,
        )
        if blocked_currency:
            print(f"{name}: signal skipped (correlated -- already have a same-side "
                  f"{blocked_currency} position open)")
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
            open_exposures.append(sig_expo)


if __name__ == "__main__":
    main()
