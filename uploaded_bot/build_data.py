#!/usr/bin/env python3
"""Build the DATA payload the uploaded sniper engine expects, from REAL
TradeLocker broker history.

READ-ONLY. Touches only ``GET /trade/history`` and the auth/account endpoints.
No order endpoint is imported or called anywhere in this file.

Output: ``uploaded_bot/data_90d.json`` shaped exactly like the ``/tmp/bt90.json``
the uploaded ``sniper_backtest.py`` loads:

    {SYMBOL: {"15m": [{t,o,h,l,c}, ...], "4H": [...]}, ...}

Bars are the broker's own OHLC. 15m comes from the repo's TradeLocker cache
(``smc_data/tradelocker/<SYM>_15m.csv``) when fresh, else straight from the API.
4H is resampled from the broker's 1H series (the broker serves 1H, not 4H).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from typing import Dict, List

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CACHE = os.path.join(REPO, "smc_data", "tradelocker")

# The uploaded package's own pair universe (sniper_smc.SNIPER_PAIRS).
SNIPER_PAIRS = ["NAS100", "USDJPY", "GBPJPY", "GBPUSD", "AUDJPY", "USDCAD"]

# Instrument ids from the uploaded trading_agent.MARKETS.
MARKETS = {
    "EURUSD": 278, "GBPUSD": 279, "USDJPY": 283, "USDCHF": 282, "USDCAD": 281,
    "AUDUSD": 277, "NZDUSD": 280, "GBPJPY": 243, "EURJPY": 238, "AUDJPY": 229,
    "EURGBP": 237, "GBPCAD": 241, "XAUUSD": 314, "NAS100": 306, "SPX500": 307,
}

BASE_URL = "https://demo.tradelocker.com/backend-api"
# The uploaded trading_agent.py hard-codes INFO_ROUTE = 674, which this account
# answers with an empty payload. The real INFO route is resolved per-instrument
# from /trade/accounts/<id>/instruments below.
INFO_ROUTE = 674

DAYS_TRADE = 90      # the reported window
DAYS_WARMUP = 35     # extra history so bar 0 of the window has full context


def _load_env() -> None:
    path = os.path.join(REPO, ".env")
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def auth() -> Dict[str, str]:
    _load_env()
    r = requests.post(
        f"{BASE_URL}/auth/jwt/token",
        json={"email": os.environ["TL_EMAIL"],
              "password": os.environ["TL_PASSWORD"],
              "server": os.environ["TL_SERVER"]},
        timeout=20,
    )
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['accessToken']}"}
    accs = requests.get(f"{BASE_URL}/auth/jwt/all-accounts", headers=h, timeout=20).json()
    target = os.environ.get("TL_ACCOUNT_ID")
    acc = next((a for a in accs["accounts"] if str(a["id"]) == str(target)), accs["accounts"][0])
    h["accNum"] = str(acc["accNum"])
    return h


def info_routes(headers) -> Dict[int, int]:
    """Map tradableInstrumentId -> INFO routeId for this account (read-only)."""
    acc = os.environ["TL_ACCOUNT_ID"]
    r = requests.get(f"{BASE_URL}/trade/accounts/{acc}/instruments",
                     headers=headers, params={"locale": "en"}, timeout=30)
    r.raise_for_status()
    out = {}
    for i in r.json().get("d", {}).get("instruments", []):
        for rt in i.get("routes", []):
            if rt.get("type") == "INFO":
                out[int(i["tradableInstrumentId"])] = int(rt["id"])
    return out


def fetch_history(headers, iid: int, resolution: str, frm_ms: int, to_ms: int,
                  route: int = INFO_ROUTE) -> List[dict]:
    """Read-only /trade/history. Chunked: the broker answers an over-long
    range with an empty payload rather than a truncated one."""
    span = {"15m": 25, "1H": 120, "4H": 400}.get(resolution, 60) * 86400_000
    out: List[dict] = []
    cur = frm_ms
    while cur < to_ms:
        end = min(cur + span, to_ms)
        for attempt in range(4):
            try:
                r = requests.get(
                    f"{BASE_URL}/trade/history", headers=headers,
                    params={"tradableInstrumentId": iid, "routeId": route,
                            "resolution": resolution, "from": cur, "to": end},
                    timeout=30,
                )
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                bars = r.json().get("d", {}).get("barDetails", [])
                out.extend(bars)
                break
            except Exception:
                time.sleep(2 ** attempt)
        cur = end
        time.sleep(0.25)
    seen, dedup = set(), []
    for b in sorted(out, key=lambda x: x["t"]):
        if b["t"] in seen:
            continue
        seen.add(b["t"])
        dedup.append({"t": int(b["t"]), "o": float(b["o"]), "h": float(b["h"]),
                      "l": float(b["l"]), "c": float(b["c"])})
    return dedup


def from_cache(symbol: str, interval: str, frm_ms: int) -> List[dict]:
    path = os.path.join(CACHE, f"{symbol}_{interval}.csv")
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            ts = int(float(row["timestamp"])) * 1000
            if ts < frm_ms:
                continue
            out.append({"t": ts, "o": float(row["open"]), "h": float(row["high"]),
                        "l": float(row["low"]), "c": float(row["close"])})
    return sorted(out, key=lambda b: b["t"])


def resample_4h(bars_1h: List[dict]) -> List[dict]:
    """1H -> 4H on the 00/04/08/12/16/20 UTC grid."""
    buckets: Dict[int, dict] = {}
    for b in bars_1h:
        key = (b["t"] // 3600_000) // 4 * 4 * 3600_000
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = {"t": key, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
    return [buckets[k] for k in sorted(buckets)]


def main() -> int:
    now_ms = int(time.time() * 1000)
    frm_ms = now_ms - (DAYS_TRADE + DAYS_WARMUP) * 86400_000
    headers = auth()
    routes = info_routes(headers)
    print(f"authenticated (read-only). window from {frm_ms} to {now_ms}", flush=True)

    data: Dict[str, dict] = {}
    missing: List[str] = []
    for sym in SNIPER_PAIRS:
        iid = MARKETS.get(sym)
        if iid is None:
            missing.append(f"{sym} (no instrument id)")
            continue

        b15 = from_cache(sym, "15m", frm_ms)
        stale = (not b15) or (now_ms - b15[-1]["t"] > 3 * 86400_000)
        if stale:
            b15 = fetch_history(headers, iid, "15m", frm_ms, now_ms, routes.get(iid, INFO_ROUTE))
        b1h = from_cache(sym, "1H", frm_ms)
        if (not b1h) or (now_ms - b1h[-1]["t"] > 3 * 86400_000):
            b1h = fetch_history(headers, iid, "1H", frm_ms, now_ms, routes.get(iid, INFO_ROUTE))
        b4h = resample_4h(b1h)

        if len(b15) < 2000 or len(b4h) < 150:
            missing.append(f"{sym} (15m={len(b15)} 4H={len(b4h)} — insufficient broker history)")
            print(f"  SKIP  {sym}: 15m={len(b15)} 4H={len(b4h)}", flush=True)
            continue

        data[sym] = {"15m": b15, "4H": b4h}
        src = "api" if stale else "cache"
        print(f"  ok    {sym:8s} 15m={len(b15):6d} ({src})  4H={len(b4h):5d}", flush=True)

    out = os.path.join(HERE, "data_90d.json")
    with open(out, "w") as fh:
        json.dump({"bars": data, "now_ms": now_ms,
                   "trade_window_start_ms": now_ms - DAYS_TRADE * 86400_000,
                   "unavailable": missing}, fh)
    print(f"\nwrote {out}  pairs={list(data)}  unavailable={missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
