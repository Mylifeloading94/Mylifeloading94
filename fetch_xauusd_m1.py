"""
Build a bid/ask M1 history for XAUUSD from Dukascopy tick files, 2019 -> today.

Why M1 and not raw ticks: seven years is ~700M ticks, which does not fit in
memory. Each day is reduced to M1 bars that keep BOTH sides of the book
(bid OHLC and ask OHLC), so a backtest can still enter longs at the ask, exit
them at the bid, and pay the real spread. Intrabar ordering is then the only
thing lost, and the engine handles that conservatively (stop wins a tie).

Dukascopy month in the URL is ZERO-indexed (Jan=00).
Resumable: one parquet per COMPLETED day in data/m1/. A day is only written if
all 24 hours downloaded cleanly, so a proxy reset never leaves a silent hole.
Today is never written (its later hours do not exist yet).

Usage: python3 fetch_xauusd_m1.py [start=2019-01-01] [workers=12]
"""
import os, sys, lzma, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "m1")
BASE = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
POINT = 1000.0
_REC = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"), ("av", ">f4"), ("bv", ">f4")])
_TL = threading.local()


def _session():
    s = requests.Session()
    r = Retry(total=5, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504],
              allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=r, pool_maxsize=4))
    return s


def hour_ticks(day, hour):
    """(ms, bid, ask) arrays for one hour, or None if the hour is empty."""
    url = f"{BASE}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{hour:02d}h_ticks.bi5"
    for attempt in range(6):
        try:
            if not hasattr(_TL, "s"):
                _TL.s = _session()
            r = _TL.s.get(url, timeout=45)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            if not r.content:
                return None
            raw = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(r.content)
            n = len(raw) // 20
            if n == 0:
                return None
            a = np.frombuffer(raw[:n * 20], dtype=_REC)
            base = int(dt.datetime.combine(day, dt.time(hour), tzinfo=dt.timezone.utc).timestamp() * 1000)
            return base + a["ms"].astype(np.int64), a["bid"] / POINT, a["ask"] / POINT
        except Exception:
            _TL.s = _session()          # a reset must not poison later requests
            if attempt == 5:
                raise
    return None


def build_day(day):
    path = os.path.join(OUT, f"{day:%Y%m%d}.parquet")
    if os.path.exists(path):
        return "cached"
    parts = [p for h in range(24) if (p := hour_ticks(day, h)) is not None]
    if parts:
        ms = np.concatenate([p[0] for p in parts])
        bid = np.concatenate([p[1] for p in parts])
        ask = np.concatenate([p[2] for p in parts])
        df = pd.DataFrame({"m": ms // 60000, "bid": bid, "ask": ask})
        g = df.groupby("m", sort=True)
        out = pd.DataFrame({
            "bo": g.bid.first(), "bh": g.bid.max(), "bl": g.bid.min(), "bc": g.bid.last(),
            "ao": g.ask.first(), "ah": g.ask.max(), "al": g.ask.min(), "ac": g.ask.last(),
            "n": g.bid.size()})
        out.index = pd.to_datetime(out.index.to_numpy() * 60000, unit="ms", utc=True)
        out.index.name = "time"
        out = out.astype({c: "float32" for c in out.columns if c != "n"})
    else:
        out = pd.DataFrame()
    if day < dt.datetime.now(dt.timezone.utc).date():
        out.to_parquet(path)
    return "ok" if parts else "empty"


def main():
    start = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date(2019, 1, 1)
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    os.makedirs(OUT, exist_ok=True)
    days, d = [], start
    while d <= dt.datetime.now(dt.timezone.utc).date():
        if d.weekday() != 5:
            days.append(d)
        d += dt.timedelta(days=1)
    todo = [x for x in days if not os.path.exists(os.path.join(OUT, f"{x:%Y%m%d}.parquet"))]
    print(f"{len(days)} trading days, {len(todo)} to fetch, {workers} workers", flush=True)
    done = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(build_day, x): x for x in todo}
        for f in futs:
            try:
                f.result()
            except Exception as e:
                failed += 1
                print(f"  FAILED {futs[f]}: {type(e).__name__}", flush=True)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)} days ({failed} failed) last={futs[f]}", flush=True)
    print(f"finished: {done} days, {failed} failed", flush=True)


if __name__ == "__main__":
    main()
