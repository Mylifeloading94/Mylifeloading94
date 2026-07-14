"""
Yahoo Finance hourly OHLC fetcher/cache for price_action_strategy.py.

TradeLocker/GenFX credentials (TL_EMAIL/TL_PASSWORD/TL_SERVER, used by every
other backtest in this repo) were not available when this strategy was
built, so it sources bars from Yahoo Finance's chart API directly instead.
Re-validate against TradeLocker history before trusting fills precisely —
Yahoo FX/index bars are mid-price with no real bid/ask depth.
"""
import os
import time
import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "pa_data")
os.makedirs(CACHE_DIR, exist_ok=True)

CA_BUNDLE = "/root/.ccr/ca-bundle.crt"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
VERIFY = CA_BUNDLE if os.path.exists(CA_BUNDLE) else True

WATCHLIST = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "USDCAD": "USDCAD=X", "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X", "EURJPY": "EURJPY=X", "GBPJPY": "GBPJPY=X",
    "EURGBP": "EURGBP=X", "AUDJPY": "AUDJPY=X", "EURAUD": "EURAUD=X",
    "CADJPY": "CADJPY=X", "CHFJPY": "CHFJPY=X", "XAUUSD": "GC=F",
    "GBPAUD": "GBPAUD=X", "NZDJPY": "NZDJPY=X", "GBPCAD": "GBPCAD=X",
    "NAS100": "^NDX", "SPX500": "^GSPC", "US30": "^DJI",
}


def fetch(symbol, range_="730d", interval="60m", retries=5):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_, "interval": interval}
    r = None
    for attempt in range(retries):
        r = requests.get(url, params=params, headers=HEADERS, verify=VERIFY, timeout=20)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(3 + attempt * 3)
            continue
        r.raise_for_status()
    raise RuntimeError(f"failed to fetch {symbol}: {r.status_code} {r.text[:200]}")


def to_csv(data, path):
    result = data["chart"]["result"]
    if not result:
        return 0
    r = result[0]
    ts = r["timestamp"]
    q = r["indicators"]["quote"][0]
    o, h, l, c, v = q["open"], q["high"], q["low"], q["close"], q.get("volume")
    n = 0
    with open(path, "w") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        for i in range(len(ts)):
            if o[i] is None or h[i] is None or l[i] is None or c[i] is None:
                continue
            vol = v[i] if v and v[i] is not None else 0
            f.write(f"{ts[i]},{o[i]},{h[i]},{l[i]},{c[i]},{vol}\n")
            n += 1
    return n


def ensure_data(range_="730d", force=False):
    """Download (or refresh) hourly bars for the full watchlist into pa_data/*.csv."""
    for name, symbol in WATCHLIST.items():
        path = os.path.join(CACHE_DIR, f"{name}.csv")
        if os.path.exists(path) and not force:
            continue
        data = fetch(symbol, range_=range_)
        n = to_csv(data, path)
        print(f"{name:10s} ({symbol:10s}) -> {n} bars")
        time.sleep(1.2)


if __name__ == "__main__":
    ensure_data(force=True)
