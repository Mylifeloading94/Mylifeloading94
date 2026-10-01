"""Download XAUUSD M1 candles from Dukascopy's public datafeed and cache to data/XAUUSD_M1.csv."""
import datetime as dt
import lzma
import os
import struct
import sys
import time

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_DIR = os.path.join(DATA_DIR, "duka_xau")
URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
POINT = 1000.0  # XAUUSD prices are stored as int / 1000


def fetch_day(day):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, day.strftime("%Y%m%d") + ".bi5")
    if os.path.exists(path):
        return open(path, "rb").read()
    url = URL.format(y=day.year, m=day.month - 1, d=day.day)  # month is 0-based
    for attempt in range(8):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            if r.status_code == 200:
                open(path, "wb").write(r.content)
                return r.content
            if r.status_code == 404:
                open(path, "wb").write(b"")
                return b""
        except requests.RequestException:
            pass
        time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"failed to download {day}")


def parse(day, raw):
    if not raw:
        return []
    data = lzma.decompress(raw)
    base = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    rows = []
    for i in range(0, len(data), 24):
        t, o, c, l, h, v = struct.unpack(">5if", data[i:i + 24])
        if v <= 0:
            continue  # flat filler minute (market closed)
        rows.append((base + dt.timedelta(seconds=t), o / POINT, h / POINT, l / POINT, c / POINT))
    return rows


def main(start, end):
    out = []
    day = start
    while day <= end:
        if day.weekday() != 5:  # gold doesn't trade Saturday
            out.extend(parse(day, fetch_day(day)))
            print(day, len(out), flush=True)
        day += dt.timedelta(days=1)
    with open(os.path.join(DATA_DIR, "XAUUSD_M1.csv"), "w") as f:
        f.write("time,open,high,low,close\n")
        for r in out:
            f.write(f"{r[0].isoformat()},{r[1]},{r[2]},{r[3]},{r[4]}\n")


HOUR_URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/BID_candles_hour_1.bi5"


def fetch_hours(year, month):
    """Monthly H1 candle file -> list of rows (one request per month)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"H1_{year}{month:02d}.bi5")
    raw = open(path, "rb").read() if os.path.exists(path) else None
    if raw is None:
        url = HOUR_URL.format(y=year, m=month - 1)
        for attempt in range(10):
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
                if r.status_code == 200:
                    raw = r.content
                    open(path, "wb").write(raw)
                    break
            except requests.RequestException:
                pass
            time.sleep(min(2 ** attempt, 30))
        if raw is None:
            raise RuntimeError(f"failed hourly {year}-{month}")
    base = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    data = lzma.decompress(raw) if raw else b""
    rows = []
    for i in range(0, len(data), 24):
        t, o, c, l, h, v = struct.unpack(">5if", data[i:i + 24])
        if v > 0:
            rows.append((base + dt.timedelta(seconds=t), o / POINT, h / POINT, l / POINT, c / POINT))
    return rows


def save_hours(months):
    out = []
    for y, m in months:
        out.extend(fetch_hours(y, m))
        print("H1", y, m, len(out), flush=True)
    with open(os.path.join(DATA_DIR, "XAUUSD_H1.csv"), "w") as f:
        f.write("time,open,high,low,close\n")
        for r in out:
            f.write(f"{r[0].isoformat()},{r[1]},{r[2]},{r[3]},{r[4]}\n")


if __name__ == "__main__":
    if sys.argv[1] == "hours":
        save_hours([(2026, m) for m in range(1, 10)])
        sys.exit()
    s = dt.date.fromisoformat(sys.argv[1])
    e = dt.date.fromisoformat(sys.argv[2])
    main(s, e)
