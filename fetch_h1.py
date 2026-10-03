"""
Tier-1 data: H1 BID/ASK candles for the whole watchlist, 2019 -> today.

One file per (instrument, month, side). Resumable: every month is cached under
data/h1_raw/<SYM>/YYYYMM_<SIDE>.parquet. Zero-volume filler hours (market closed)
are dropped. Final per-symbol frame columns match the M1 engine: bo,bh,bl,bc,ao,ah,al,ac,n.

Dukascopy rate-limits bursts (HTTP 429 -> multi-minute ban), so this is paced.
Usage: python3 fetch_h1.py [workers=3] [pause_seconds=0.4]
"""
import datetime as dt, lzma, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests
import fetch_candles as F

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "h1_raw")
_TL = threading.local(); _LOCK = threading.Lock(); STAT = {"ok": 0, "429": 0, "empty": 0}
_RATE = {"next": 0.0, "gap": 2.5, "ban_until": 0.0}   # GLOBAL pacing: ~0.4 requests/second across all workers


def _pace():
    with _LOCK:
        now = time.time(); wait = max(0.0, _RATE["next"] - now, _RATE["ban_until"] - now)
        _RATE["next"] = max(now, _RATE["next"]) + _RATE["gap"]
    if wait:
        time.sleep(wait)


def get(url):
    for attempt in range(12):
        if not hasattr(_TL, "s"):
            _TL.s = requests.Session()
        _pace()
        try:
            r = _TL.s.get(url, timeout=40)
        except Exception:
            _TL.s = requests.Session(); time.sleep(5); continue
        if r.status_code == 200:
            return r.content
        if r.status_code == 404:
            return b""
        with _LOCK:
            STAT["429"] += 1
            # one 429 means EVERY worker must stop: requests sent inside a ban only prolong it
            _RATE["ban_until"] = max(_RATE["ban_until"], time.time() + 300)
            _RATE["next"] = max(_RATE["next"], _RATE["ban_until"])
    raise RuntimeError("gave up " + url)


def month_file(sym, y, m, side, pause):
    path = os.path.join(RAW, sym, f"{y}{m:02d}_{side}.parquet")
    if os.path.exists(path):
        return
    div = F.scale(sym)
    blob = get(f"{F.BASE}/{F.ALIASES[sym]}/{y}/{m-1:02d}/{side}_candles_hour_1.bi5")
    time.sleep(pause)
    if blob:
        raw = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(blob); n = len(raw) // 24
        a = np.frombuffer(raw[:n * 24], dtype=F.REC)
        ts = pd.Timestamp(year=y, month=m, day=1, tz="UTC") + pd.to_timedelta(a["t"].astype("int64"), unit="s")
        df = pd.DataFrame({"o": a["o"] / div, "h": a["h"] / div, "l": a["l"] / div, "c": a["c"] / div, "v": a["v"].astype("float32")}, index=ts)
        df = df[df.v > 0]
    else:
        df = pd.DataFrame(columns=["o", "h", "l", "c", "v"])
    now = dt.datetime.now(dt.timezone.utc)
    if (y, m) < (now.year, now.month):                      # never cache the running month
        os.makedirs(os.path.dirname(path), exist_ok=True); df.to_parquet(path)
    with _LOCK:
        STAT["ok" if len(df) else "empty"] += 1


SAMPLE_MONTH = 6          # ASK is fetched for June of each year only; the rest is modelled


def assemble(sym):
    """BID everywhere; ASK = real where sampled, else BID + per-(year, UTC-hour) median spread."""
    raw = os.path.join(RAW, sym)
    bid = pd.concat([pd.read_parquet(os.path.join(raw, f)) for f in sorted(os.listdir(raw)) if f.endswith("_BID.parquet")]).sort_index()
    bid = bid[~bid.index.duplicated()]
    ask_files = sorted(f for f in os.listdir(raw) if f.endswith("_ASK.parquet"))
    ask = pd.concat([pd.read_parquet(os.path.join(raw, f)) for f in ask_files]).sort_index() if ask_files else None
    out = pd.DataFrame({"bo": bid.o, "bh": bid.h, "bl": bid.l, "bc": bid.c, "n": bid.v})
    sp = {c: np.nan for c in ("o", "h", "l", "c")}
    if ask is not None and len(ask):
        j = bid.index.intersection(ask.index)
        d = (ask.loc[j] - bid.loc[j])[["o", "h", "l", "c"]]
        d["year"], d["hour"] = d.index.year, d.index.hour
        prof = d.groupby(["year", "hour"]).median()
        yrs = sorted(d.year.unique())
        for c in ("o", "h", "l", "c"):
            near = np.array([min(yrs, key=lambda y: abs(y - yy)) for yy in out.index.year])
            key = pd.MultiIndex.from_arrays([near, out.index.hour])
            est = prof[c].reindex(key).to_numpy()
            out["a" + c] = out["b" + c].to_numpy() + np.where(np.isnan(est), np.nanmedian(prof[c]), est)
        real = ask.loc[ask.index.intersection(out.index)]
        for c in ("o", "h", "l", "c"):
            out.loc[real.index, "a" + c] = real[c]          # real ask wherever we have it
    else:
        raise RuntimeError(f"{sym}: no ASK sample to model spread from")
    out["ask_real"] = out.index.isin(ask.index) if ask is not None else False
    return out[["bo", "bh", "bl", "bc", "ao", "ah", "al", "ac", "n", "ask_real"]].astype("float32")


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    syms = list(F.INDICES) + F.FOREX + ["XAUUSD"]          # indices first: they matter most to the user
    now = dt.datetime.now(dt.timezone.utc)
    months = [(y, m) for y in range(2019, now.year + 1) for m in range(1, 13) if (y, m) <= (now.year, now.month)]
    jobs = []
    for s_ in syms:                                          # symbol-major: each instrument finishes early
        for (y, m) in months:
            jobs.append((s_, y, m, "BID"))
            if m == SAMPLE_MONTH:
                jobs.append((s_, y, m, "ASK"))
    todo = [j for j in jobs if not os.path.exists(os.path.join(RAW, j[0], f"{j[1]}{j[2]:02d}_{j[3]}.parquet"))]
    print(f"{len(syms)} instruments -> {len(todo)} requests ({len(jobs)} total), {workers} workers, ~{1/_RATE['gap']:.1f} req/s", flush=True)
    os.makedirs(os.path.join(HERE, "data", "h1"), exist_ok=True)
    t0 = time.time(); done_syms = set()
    remaining = {s_: sum(1 for j in todo if j[0] == s_) for s_ in syms}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(j, ex.submit(month_file, *j, 0.0)) for j in todo]
        for i, (j, f) in enumerate(futs, 1):
            try:
                f.result()
            except Exception as e:
                print("  FAILED", j, e, flush=True)
            remaining[j[0]] -= 1
            if remaining[j[0]] == 0:                         # instrument complete -> write its frame now
                try:
                    assemble(j[0]).to_parquet(os.path.join(HERE, "data", "h1", f"{j[0]}.parquet"))
                    print(f"  [{time.time()-t0:5.0f}s] {j[0]} complete ({i}/{len(todo)}) stats {STAT}", flush=True)
                except Exception as e:
                    print("  assemble failed", j[0], e, flush=True)
    for s_ in syms:                                          # symbols that were already fully cached
        pth = os.path.join(HERE, "data", "h1", f"{s_}.parquet")
        if not os.path.exists(pth):
            try: assemble(s_).to_parquet(pth)
            except Exception as e: print("assemble failed", s_, e)
    print("done", STAT, flush=True)


if __name__ == "__main__":
    main()
