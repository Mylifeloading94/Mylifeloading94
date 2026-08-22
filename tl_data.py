"""
TradeLocker historical data layer.

Fetches REAL M15 bars from the broker's own INFO feed and caches them to
./data/<SYMBOL>_M15.csv. Every price used anywhere in this project comes from
here — nothing is ever synthesised.

Credentials are read from the environment only:
    TL_EMAIL, TL_PASSWORD, TL_SERVER, TL_ENV (live|demo)

Usage:
    python3 tl_data.py                      # fetch all symbols
    python3 tl_data.py EURUSD XAUUSD        # fetch a subset
"""
import os
import sys
import time
import json
import datetime as dt

import pandas as pd
import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Broker resolution vocabulary (probed against /trade/history):
#   1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W, 1M
RES_M15 = "15m"

# tradableInstrumentId map for the PULSE live feed. Regenerate with
# `python3 tl_data.py --instruments` if the broker renumbers.
INSTRUMENTS = {
    "EURUSD": 16187, "GBPUSD": 16203, "USDJPY": 16162, "AUDUSD": 16184,
    "USDCAD": 16174, "USDCHF": 16177, "NZDUSD": 16156, "EURJPY": 16159,
    "GBPJPY": 16143, "AUDJPY": 16158, "EURGBP": 16194, "EURAUD": 16137,
    "GBPAUD": 16201, "CHFJPY": 16186, "CADJPY": 16202, "NZDJPY": 16149,
    "EURCAD": 16173, "EURCHF": 16170, "GBPCAD": 16172, "GBPCHF": 16175,
    "AUDCAD": 16141, "AUDNZD": 16154, "USDSGD": 16171, "XAUUSD": 15063,
}

SYMBOLS = list(INSTRUMENTS)
INFO_ROUTE = 765338
TRADE_ROUTE = 775154


def _base():
    env = os.environ.get("TL_ENV", "demo").lower()
    host = "live" if env == "live" else "demo"
    return f"https://{host}.tradelocker.com/backend-api"


class TLClient:
    def __init__(self):
        self.base = _base()
        self.session = requests.Session()
        self.access = None
        self.account_id = None
        self.acc_num = None
        self.login()

    def login(self):
        r = self.session.post(
            f"{self.base}/auth/jwt/token",
            json={
                "email": os.environ["TL_EMAIL"],
                "password": os.environ["TL_PASSWORD"],
                "server": os.environ["TL_SERVER"],
            },
            timeout=30,
        )
        r.raise_for_status()
        self.access = r.json()["accessToken"]
        a = self.session.get(
            f"{self.base}/auth/jwt/all-accounts",
            headers={"Authorization": f"Bearer {self.access}"},
            timeout=30,
        )
        a.raise_for_status()
        acct = a.json()["accounts"][0]
        self.account_id = acct["id"]
        self.acc_num = str(acct["accNum"])
        return acct

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.access}", "accNum": self.acc_num}

    def bars(self, symbol, resolution, start, end, retries=4):
        """Fetch OHLCV bars. `start`/`end` are naive-UTC datetimes."""
        iid = INSTRUMENTS[symbol]
        params = {
            "tradableInstrumentId": iid,
            "routeId": INFO_ROUTE,
            "resolution": resolution,
            "from": int(start.replace(tzinfo=dt.timezone.utc).timestamp() * 1000),
            "to": int(end.replace(tzinfo=dt.timezone.utc).timestamp() * 1000),
        }
        delay = 2
        for attempt in range(retries):
            try:
                r = self.session.get(f"{self.base}/trade/history",
                                     headers=self.headers, params=params, timeout=120)
                if r.status_code == 401:
                    self.login()
                    continue
                if r.status_code == 429:
                    time.sleep(delay); delay *= 2; continue
                r.raise_for_status()
                j = r.json()
                if j.get("s") == "error":
                    raise RuntimeError(j.get("errmsg"))
                return j.get("d", {}).get("barDetails", [])
            except (requests.RequestException, RuntimeError):
                if attempt == retries - 1:
                    raise
                time.sleep(delay); delay *= 2
        return []


def bars_to_frame(bars):
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                            "c": "close", "v": "volume"})
    df = df.set_index("time")[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df.astype(float)


def fetch_m15(client, symbol, start, end, chunk_days=60):
    """Chunked M15 fetch so we never hit a server-side bar cap silently."""
    frames = []
    cur = start
    while cur < end:
        stop = min(cur + dt.timedelta(days=chunk_days), end)
        bars = client.bars(symbol, RES_M15, cur, stop)
        if bars:
            frames.append(bars_to_frame(bars))
        cur = stop
        time.sleep(0.25)          # be polite to the INFO route
    if not frames:
        return bars_to_frame([])
    df = pd.concat(frames)
    return df[~df.index.duplicated(keep="first")].sort_index()


def csv_path(symbol):
    return os.path.join(DATA_DIR, f"{symbol}_M15.csv")


def load(symbol):
    """Load cached M15 for a symbol, or None."""
    p = csv_path(symbol)
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, parse_dates=["time"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def resample(df, rule):
    """Aggregate M15 up to H1/H4/D1. Right-labelled bars, closed-left, so a
    bar's timestamp is its OPEN time and it is only complete once the next
    one begins — this is what keeps the backtest free of look-ahead."""
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    symbols = args or SYMBOLS
    # warm-up reach-back: the D1 200-EMA bias needs ~200 daily bars before
    # 2026-01-01, so start the pull in early 2025.
    start = dt.datetime(2025, 2, 1)
    end = dt.datetime(2026, 8, 22, 23, 59)

    os.makedirs(DATA_DIR, exist_ok=True)
    client = TLClient()
    print(f"connected: account={client.account_id} accNum={client.acc_num} "
          f"env={os.environ.get('TL_ENV')}")

    for sym in symbols:
        try:
            df = fetch_m15(client, sym, start, end)
        except Exception as exc:                       # noqa: BLE001
            print(f"{sym:8s} FAILED: {exc}")
            continue
        if df.empty:
            print(f"{sym:8s} no data returned")
            continue
        df.to_csv(csv_path(sym), index_label="time")
        print(f"{sym:8s} {len(df):6d} bars  {df.index[0]}  ..  {df.index[-1]}")


if __name__ == "__main__":
    main()
