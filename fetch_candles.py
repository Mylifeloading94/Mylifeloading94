"""
Multi-instrument M1 BID/ASK history from Dukascopy's pre-aggregated candle files.

One file per (instrument, day, side) instead of 24 tick files -> ~12x fewer
requests than fetch_xauusd_m1.py. Output per instrument: data/candles/<SYM>/YYYYMMDD.parquet
with the SAME columns xau_engine uses (bo,bh,bl,bc,ao,ah,al,ac,n), so the whole
backtest stack works unchanged.

Dukascopy month in the URL is ZERO-indexed. Candle record (24 bytes, big-endian):
    uint32 seconds-from-day-start, uint32 open, close, low, high (price*scale), float32 volume
Rate limiting is burst-triggered (HTTP 429); workers back off exponentially.

Usage: python3 fetch_candles.py SYM[,SYM...] [start=2019-01-01] [workers=8]
"""
import datetime as dt, lzma, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://datafeed.dukascopy.com/datafeed"
REC = np.dtype([("t", ">u4"), ("o", ">u4"), ("c", ">u4"), ("l", ">u4"), ("h", ">u4"), ("v", ">f4")])
_TL = threading.local()

FOREX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
         "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
         "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
         "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD", "NZDJPY", "NZDCHF", "NZDCAD",
         "CADJPY", "CADCHF", "CHFJPY"]
INDICES = {"SPX500": "USA500IDXUSD", "NAS100": "USATECHIDXUSD"}
ALIASES = {**{p: p for p in FOREX}, **INDICES, "XAUUSD": "XAUUSD"}


def scale(sym):
    """Price divisor encoded in the files."""
    if sym in INDICES or sym == "XAUUSD":
        return 1000.0
    return 1000.0 if sym.endswith("JPY") else 100000.0


def _get(url):
    for attempt in range(8):
        if not hasattr(_TL, "s"):
            _TL.s = requests.Session()
        try:
            r = _TL.s.get(url, timeout=40)
        except Exception:
            _TL.s = requests.Session(); time.sleep(2 ** min(attempt, 5)); continue
        if r.status_code == 200:
            return r.content
        if r.status_code == 404:
            return b""
        time.sleep(min(60, 3 * 2 ** attempt))              # 429 / 5xx: back off
    raise RuntimeError("gave up: " + url)


def decode(blob, day, div):
    if not blob:
        return None
    raw = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(blob)
    n = len(raw) // 24
    if n == 0:
        return None
    a = np.frombuffer(raw[:n * 24], dtype=REC)
    ts = pd.Timestamp(day, tz="UTC") + pd.to_timedelta(a["t"].astype("int64"), unit="s")
    return pd.DataFrame({"o": a["o"] / div, "h": a["h"] / div, "l": a["l"] / div, "c": a["c"] / div,
                         "v": a["v"].astype("float32")}, index=ts)


def build_day(sym, day):
    code = ALIASES[sym]; div = scale(sym)
    path = os.path.join(HERE, "data", "candles", sym, f"{day:%Y%m%d}.parquet")
    if os.path.exists(path):
        return "cached"
    side = {}
    for s in ("BID", "ASK"):
        url = f"{BASE}/{code}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{s}_candles_min_1.bi5"
        side[s] = decode(_get(url), day, div)
    if side["BID"] is None or side["ASK"] is None:
        out = pd.DataFrame()
    else:
        b, a = side["BID"], side["ASK"]
        idx = b.index.intersection(a.index)
        b, a = b.loc[idx], a.loc[idx]
        out = pd.DataFrame({"bo": b.o, "bh": b.h, "bl": b.l, "bc": b.c,
                            "ao": a.o, "ah": a.h, "al": a.l, "ac": a.c, "n": b.v}).astype("float32")
        out.index.name = "time"
    if day < dt.datetime.now(dt.timezone.utc).date():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out.to_parquet(path)
    return "ok" if len(out) else "empty"


def fetch(syms, start, workers):
    today = dt.datetime.now(dt.timezone.utc).date()
    days = [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]
    days = [d for d in days if d.weekday() != 5]
    jobs = [(s, d) for d in days for s in syms]            # day-major: all symbols progress together
    todo = [j for j in jobs if not os.path.exists(os.path.join(HERE, "data", "candles", j[0], f"{j[1]:%Y%m%d}.parquet"))]
    print(f"{len(syms)} symbols, {len(days)} days -> {len(todo)} (symbol,day) jobs, {workers} workers", flush=True)
    done = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(j, ex.submit(build_day, *j)) for j in todo]
        for j, f in futs:
            try:
                f.result()
            except Exception as e:
                failed += 1
                print(f"  FAILED {j[0]} {j[1]}: {e}", flush=True)
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(todo)} ({failed} failed) at {j[1]}", flush=True)
    print(f"finished {done} jobs, {failed} failed", flush=True)


def load(sym):
    import glob
    files = sorted(glob.glob(os.path.join(HERE, "data", "candles", sym, "*.parquet")))
    parts = [pd.read_parquet(f) for f in files]
    parts = [p for p in parts if len(p)]
    df = pd.concat(parts).sort_index()
    return df[~df.index.duplicated(keep="first")]


if __name__ == "__main__":
    syms = (sys.argv[1] if len(sys.argv) > 1 else ",".join(FOREX + list(INDICES))).split(",")
    start = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date(2019, 1, 1)
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    fetch(syms, start, workers)
