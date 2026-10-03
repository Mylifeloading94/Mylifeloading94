"""
Smart-Money-Concepts + kill-zone signal generator (causal, no repainting).

Setup (long; short is the exact mirror):
  1. KILL ZONE   the signal bar closes inside London (02:00-05:00 ET) or NY AM (07:00-10:00 ET).
                 Times are converted with America/New_York, so daylight saving is handled.
  2. LIQUIDITY SWEEP   a bar trades BELOW a resting pool of sell-side liquidity and closes back
                 above it (a grab with reclaim). Pools: Asian range low (20:00-00:00 ET), London
                 low (02:00-07:00 ET, only once complete), previous trading-day low ['session'],
                 or the rolling 3-hour swing low ['swing'].
  3. MARKET-STRUCTURE SHIFT   within `m` bars a displacement candle (range >= 1 ATR, body >= 50%)
                 CLOSES above the structure high that stood before the sweep.
  4. FAIR VALUE GAP   the three candles around the displacement leave an imbalance
                 (low[t] > high[t-2]). Entry = limit at the gap midpoint ['mid'] or its near edge ['edge'].
  5. STOP beyond the sweep extreme (+0.2 ATR); TARGET = rr x planned risk; the setup is skipped if
     the planned risk is outside 0.5-4 ATR.
  Optional HTF bias: longs only above the 20-day EMA, shorts only below.

Everything is evaluated on CLOSED bars; the order is placed at the close of the bar that completes
the gap and can only fill afterwards. A level is only used once it is complete.
"""
import numpy as np
import pandas as pd
import xau_strategies as S

ET = "America/New_York"
KZ = {"london": (2 * 60, 5 * 60), "ny": (7 * 60, 10 * 60)}      # minutes after ET midnight
ASIAN_HOD, LONDON_HOD = (3, 7), (9, 14)        # hour-of-trading-day (ET + 7h): Asian 20-24 ET, London 02-07 ET


def session_levels(b):
    """Asian / London / previous-day highs and lows, available only once each window is complete."""
    et = b.index.tz_convert(ET)
    shifted = et + pd.Timedelta(hours=7)                 # trading day rolls at 17:00 ET
    tday = shifted.floor("D")
    hod = shifted.hour
    hi, lo = b.high.to_numpy(), b.low.to_numpy()
    df = pd.DataFrame({"hi": hi, "lo": lo, "tday": tday, "hod": hod}, index=b.index)
    n = len(b)
    out = {k: np.full(n, np.nan) for k in ("asia_hi", "asia_lo", "lon_hi", "lon_lo", "pd_hi", "pd_lo")}
    for name, (a0, a1), ready, kh, kl in (("asia", ASIAN_HOD, ASIAN_HOD[1], "asia_hi", "asia_lo"),
                                         ("lon", LONDON_HOD, LONDON_HOD[1], "lon_hi", "lon_lo")):
        w = df[(df.hod >= a0) & (df.hod < a1)]
        g = w.groupby("tday").agg(h=("hi", "max"), l=("lo", "min"))
        mh = df.tday.map(g.h).to_numpy(); ml = df.tday.map(g.l).to_numpy()
        ok = (df.hod.to_numpy() >= ready)
        out[kh] = np.where(ok, mh, np.nan); out[kl] = np.where(ok, ml, np.nan)
    day = df.groupby("tday").agg(h=("hi", "max"), l=("lo", "min"))
    prev = day.shift(1)
    out["pd_hi"] = df.tday.map(prev.h).to_numpy(); out["pd_lo"] = df.tday.map(prev.l).to_numpy()
    return out


def kill_zone_mask(b, tf_min):
    """True where the bar's CLOSE falls inside a kill zone (ET). Returns (mask, zone-name array)."""
    et = (b.index + pd.Timedelta(minutes=tf_min)).tz_convert(ET)
    m = et.hour * 60 + et.minute
    zone = np.full(len(b), "", dtype=object)
    ok = np.zeros(len(b), bool)
    for name, (a, z) in KZ.items():
        inside = (m > a) & (m <= z)
        zone[inside] = name; ok |= inside
    return ok, zone


def generate(b, tf_min, liq="session", entry="mid", bias=False, m=8, r_back=10, expiry_bars=8):
    """Return a DataFrame of signals: one row per setup, indexed by signal-bar position."""
    n = len(b)
    hi, lo, op, cl = (b[c].to_numpy() for c in ("high", "low", "open", "close"))
    atr = S.atr(b).to_numpy()
    kz_ok, zone = kill_zone_mask(b, tf_min)
    L = session_levels(b) if liq == "session" else None
    nsw = max(4, int(180 / tf_min))
    sw_lo = b.low.rolling(nsw).min().shift(1).to_numpy(); sw_hi = b.high.rolling(nsw).max().shift(1).to_numpy()
    if liq == "session":
        lows = [L["asia_lo"], L["lon_lo"], L["pd_lo"]]; highs = [L["asia_hi"], L["lon_hi"], L["pd_hi"]]
    else:
        lows, highs = [sw_lo], [sw_hi]
    sweep_l = np.zeros(n, bool); sweep_h = np.zeros(n, bool)
    for lv in lows:
        with np.errstate(invalid="ignore"):
            sweep_l |= (lo < lv) & (cl > lv)
    for lv in highs:
        with np.errstate(invalid="ignore"):
            sweep_h |= (hi > lv) & (cl < lv)
    idx = np.arange(n)
    last_l = np.maximum.accumulate(np.where(sweep_l, idx, -1)); last_h = np.maximum.accumulate(np.where(sweep_h, idx, -1))
    es = S.ema(b.close, int(20 * 1440 / tf_min)).to_numpy() if bias else None
    rows, used_l, used_h = [], -1, -1
    for t in range(max(r_back + 3, 2), n):
        if not kz_ok[t] or not np.isfinite(atr[t - 1]) or atr[t - 1] <= 0:
            continue
        a = atr[t - 1]; rng1 = hi[t - 1] - lo[t - 1]
        if rng1 < a or abs(cl[t - 1] - op[t - 1]) < 0.5 * rng1:
            continue                                            # no displacement on candle t-1
        # ---------- long ----------
        s = last_l[t - 2]
        if s >= 0 and 2 <= t - s <= m + 2 and s != used_l and lo[t] > hi[t - 2] and cl[t - 1] > op[t - 1]:
            sh = hi[max(0, s - r_back):s].max() if s > 0 else np.nan
            if np.isfinite(sh) and cl[t - 1] > sh and (not bias or cl[t] > es[t]):
                ext = lo[s:t + 1].min()
                e_px = (hi[t - 2] + lo[t]) / 2 if entry == "mid" else lo[t]
                stop = ext - 0.2 * a; risk = e_px - stop
                if 0.5 * a <= risk <= 4.0 * a:
                    rows.append((t, 1, e_px, stop, risk, zone[t])); used_l = s
        # ---------- short ----------
        s = last_h[t - 2]
        if s >= 0 and 2 <= t - s <= m + 2 and s != used_h and hi[t] < lo[t - 2] and cl[t - 1] < op[t - 1]:
            sl_ = lo[max(0, s - r_back):s].min() if s > 0 else np.nan
            if np.isfinite(sl_) and cl[t - 1] < sl_ and (not bias or cl[t] < es[t]):
                ext = hi[s:t + 1].max()
                e_px = (lo[t - 2] + hi[t]) / 2 if entry == "mid" else hi[t]
                stop = ext + 0.2 * a; risk = stop - e_px
                if 0.5 * a <= risk <= 4.0 * a:
                    rows.append((t, -1, e_px, stop, risk, zone[t])); used_h = s
    return pd.DataFrame(rows, columns=["t", "dir", "limit", "stop", "risk", "zone"])
