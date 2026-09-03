"""
Download REAL XAUUSD tick data from Dukascopy and build M1/M5/M15 OHLC bars.

Dukascopy datafeed layout (NOTE: month is ZERO-INDEXED, Jan=00 .. Dec=11):
    /datafeed/XAUUSD/<YYYY>/<MM0>/<DD>/<HH>h_ticks.bi5

Each .bi5 is LZMA-compressed; payload is a packed array of 20-byte records,
big-endian: uint32 ms-offset-from-hour, uint32 ask*1000, uint32 bid*1000,
float32 ask volume, float32 bid volume.

Files are cached under data/ticks/ so re-runs are free. Empty (0-byte) files
are legitimate: weekends and market-closed hours.

Usage:  python3 fetch_xauusd_ticks.py [days_back]
"""
import os, sys, lzma, struct, datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HERE = os.path.dirname(os.path.abspath(__file__))
TICK_DIR = os.path.join(HERE, "data", "ticks")
OUT_DIR = os.path.join(HERE, "data")
BASE = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
POINT = 1000.0  # XAUUSD quoted to 3 decimals


def _session():
    s = requests.Session()
    r = Retry(total=6, backoff_factor=1.0,
              status_forcelist=[429, 500, 502, 503, 504],
              allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=r, pool_maxsize=16))
    return s


def hour_path(day: dt.date, hour: int) -> str:
    return os.path.join(TICK_DIR, f"{day:%Y%m%d}_{hour:02d}.bi5")


_TL = __import__("threading").local()


def _tls_session():
    """One Session per worker thread: a connection reset in one worker must
    not poison the pool the others are using (that wedged the first run)."""
    if not hasattr(_TL, "s"):
        _TL.s = _session()
    return _TL.s


def fetch_hour(args):
    """Download one hour of ticks to cache. Returns (ok, cached)."""
    day, hour, _unused = args
    sess = _tls_session()
    path = hour_path(day, hour)
    if os.path.exists(path):
        return True, True
    url = f"{BASE}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{hour:02d}h_ticks.bi5"
    for attempt in range(6):
        try:
            resp = sess.get(url, timeout=45)
            if resp.status_code == 404:      # no such hour -> treat as empty
                open(path, "wb").close()
                return True, False
            resp.raise_for_status()
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            os.replace(tmp, path)
            return True, False
        except Exception:
            _TL.s = _session()          # rebuild the poisoned connection pool
            sess = _TL.s
            if attempt == 5:
                return False, False
    return False, False


def decode_hour(day: dt.date, hour: int):
    """Yield (timestamp_ms, bid, ask) for a cached hour file."""
    path = hour_path(day, hour)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return
    blob = open(path, "rb").read()
    try:
        raw = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(blob)
    except Exception:
        return
    base = dt.datetime.combine(day, dt.time(hour), tzinfo=dt.timezone.utc)
    base_ms = int(base.timestamp() * 1000)
    for i in range(len(raw) // 20):
        ms, ask, bid, _av, _bv = struct.unpack(">IIIff", raw[i * 20:(i + 1) * 20])
        yield base_ms + ms, bid / POINT, ask / POINT


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    os.makedirs(TICK_DIR, exist_ok=True)
    end = dt.date.today()
    start = end - dt.timedelta(days=days_back)

    jobs, sess = [], _session()
    d = start
    while d <= end:
        if d.weekday() != 5:                    # Saturday is always empty
            jobs += [(d, h, sess) for h in range(24)]
        d += dt.timedelta(days=1)

    print(f"XAUUSD ticks {start} -> {end}: {len(jobs)} hour-files", flush=True)
    done = failed = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for ok, _cached in ex.map(fetch_hour, jobs):
            done += 1
            failed += (not ok)
            if done % 100 == 0:
                print(f"  {done}/{len(jobs)} fetched ({failed} failed)", flush=True)
    print(f"download complete: {done} files, {failed} failed", flush=True)

    print("decoding ticks -> bars", flush=True)
    rows = []
    for day, hour, _ in jobs:
        rows.extend(decode_hour(day, hour))
    if not rows:
        raise SystemExit("no ticks decoded - aborting rather than emit fake data")

    df = pd.DataFrame(rows, columns=["ms", "bid", "ask"])
    df = df.drop_duplicates("ms").sort_values("ms")
    df["time"] = pd.to_datetime(df["ms"], unit="ms", utc=True)
    df["mid"] = (df.bid + df.ask) / 2.0
    df = df.set_index("time")
    print(f"  {len(df):,} ticks  {df.index[0]} -> {df.index[-1]}", flush=True)

    # raw ticks (mid/bid/ask) for exact intrabar fill simulation
    df[["bid", "ask", "mid"]].to_parquet(os.path.join(OUT_DIR, "XAUUSD_ticks.parquet"))

    for label, rule in (("M1", "1min"), ("M5", "5min"), ("M15", "15min")):
        bars = df["mid"].resample(rule).ohlc().dropna()
        bars["spread"] = (df.ask - df.bid).resample(rule).mean().reindex(bars.index)
        bars["ticks"] = df["mid"].resample(rule).count().reindex(bars.index)
        out = os.path.join(OUT_DIR, f"XAUUSD_{label}.csv")
        bars.to_csv(out, index_label="time")
        print(f"  {label}: {len(bars):,} bars -> {out}", flush=True)


if __name__ == "__main__":
    main()
