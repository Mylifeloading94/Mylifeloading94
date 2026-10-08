"""Bar loading, resampling and no-lookahead higher-timeframe alignment."""
import json, os, bisect, functools
import numpy as np
from .config import TF_SEC

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest_tv", "data")


def _read(sym, tf):
    p = os.path.join(DATA, f"{sym}_{tf}.json")
    if not os.path.exists(p): return None
    b = json.load(open(p))
    return [(x["t"], x["o"], x["h"], x["l"], x["c"]) for x in b] if isinstance(b[0], dict) else [tuple(x[:5]) for x in b]


def resample(rows, sec):
    out = []
    for t, o, h, l, c in rows:
        k = t - t % sec
        if out and out[-1][0] == k:
            r = out[-1]; out[-1] = (k, r[1], max(r[2], h), min(r[3], l), c)
        else:
            out.append((k, o, h, l, c))
    return out


@functools.lru_cache(maxsize=None)
def rows(sym, tf):
    """Native rows if present; 3m is built from 1m. A native series that ends early is extended
    with bars resampled from the next lower timeframe (the unfinished last bucket is dropped)."""
    if tf == "3m":
        r = _read(sym, "1m")
        return tuple(resample(r, 180)[:-1]) if r else None
    rs = _read(sym, tf)
    lower = {"15m": "5m", "1h": "15m"}.get(tf)
    if lower:
        src = rows(sym, lower)
        if src:
            ext = resample(list(src), TF_SEC[tf])[:-1]
            rs = ext if rs is None else rs + [r for r in ext if r[0] > rs[-1][0]]
    return tuple(rs) if rs else None


@functools.lru_cache(maxsize=None)
def load(sym, tf):
    r = rows(sym, tf)
    if not r: return None
    a = np.array(r, dtype=float)
    return dict(t=a[:, 0].astype(np.int64), o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4])


class HTF:
    """Index of the last higher-timeframe bar CLOSED at time T (no lookahead, no forming bar).
    Returns -1 if that bar is older than `stale` HTF bars (missing data -> no signal, never a stale read)."""
    def __init__(self, bars, tf, stale=3):
        self.close_t = bars["t"] + TF_SEC[tf]; self.max_age = stale * TF_SEC[tf]

    def idx(self, T):
        k = bisect.bisect_right(self.close_t, T) - 1
        return k if k >= 0 and T - self.close_t[k] <= self.max_age else -1


def import_csv(path, sym, tf):
    """Import a TradingView chart export (time,open,high,low,close[,...]) into backtest_tv/data/{sym}_{tf}.json.
    Merges with any bars already stored (CSV wins on overlap). Usage:
        python3 -m bbsniper.data EURUSD 5m ~/Downloads/OANDA_EURUSD,_5.csv"""
    import csv, datetime as _dt
    rows = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            k = {c.lower().strip(): v for c, v in r.items()}
            t = k["time"]
            ts = int(float(t)) if t.replace(".", "").isdigit() else int(_dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
            rows[ts] = dict(t=ts, o=float(k["open"]), h=float(k["high"]), l=float(k["low"]), c=float(k["close"]))
    old = _read(sym, tf) or []
    for t, o, h, l, c in old: rows.setdefault(t, dict(t=t, o=o, h=h, l=l, c=c))
    out = [rows[t] for t in sorted(rows)]
    json.dump(out, open(os.path.join(DATA, f"{sym}_{tf}.json"), "w"))
    return len(out)


if __name__ == "__main__":
    import sys
    print(import_csv(sys.argv[3], sys.argv[1], sys.argv[2]), "bars stored")
