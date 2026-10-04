"""
Brad Gold's XAUUSD liquidity-scalping framework (strategy_specs/brad_gold_liquidity_scalping.md),
turned into mechanical, causal rules. Nothing here looks past the bar being judged.

Step 1  Trend: per timeframe, bullish = last two CONFIRMED swing highs AND lows both rising
        (bearish = both falling, else neutral). Swings (2 bars each side) are only known 2 bars
        after they form. Trade only when 1H and 15M agree.
Step 2  POIs (15M): displacement candle (range >= 1 ATR, body >= 50%) that breaks the last
        confirmed swing = break of structure. Its order block (last opposite candle within 3 bars)
        and the fair-value gap it leaves become demand (bull) / supply (bear) zones. A zone expires
        after 24h or when price closes through it, and triggers at most one trade.
Step 3  Price must trade into an unused zone (without closing through it).
Step 4  A bar that sweeps the latest confirmed swing low (shorts: high) AND closes back beyond it,
        while tapping the zone. Entry models:
          E1 aggressive   enter at market right after that sweep bar
          E2 Brad         ...after ONE extra confirming candle (body >= 60%, closes beyond the sweep bar)
          E3 conservative wait (<= 8 bars) for a 15M market shift (close through the swing that preceded the
                          sweep, on a displacement candle), then a limit into that leg's order block
Step 5  Stop just beyond the sweep extreme (+0.1 ATR). Target = nearest confirmed 15M swing
        high/low beyond entry ['swing15'] or 1H swing ['swing1h']; optional minimum reward:risk.
        Sanity: stop distance 0.5-4 ATR. Max hold is set by the executor (6h).
"""
import numpy as np
import pandas as pd
import xau_strategies as S

K = 2            # swing fractal width, both timeframes
ZONE_LIFE = 96   # 15M bars = 24h


def swings(h, l, k=K):
    """Confirmed swing points. Returns dict with swing bar idx, confirmation idx (= idx + k) and value."""
    sh, sl = pd.Series(h), pd.Series(l)
    left_h = sh.rolling(k).max().shift(1).to_numpy(); right_h = sh[::-1].rolling(k).max().shift(1)[::-1].to_numpy()
    left_l = sl.rolling(k).min().shift(1).to_numpy(); right_l = sl[::-1].rolling(k).min().shift(1)[::-1].to_numpy()
    with np.errstate(invalid="ignore"):
        is_h = (h > left_h) & (h >= right_h); is_l = (l < left_l) & (l <= right_l)
    ih = np.flatnonzero(is_h); il = np.flatnonzero(is_l)
    return dict(hi_idx=ih, hi_conf=ih + k, hi_val=h[ih], lo_idx=il, lo_conf=il + k, lo_val=l[il])


def last_two(conf, val, n):
    """For every bar t: values of the last two swings CONFIRMED by t (nan if fewer than two)."""
    p = np.searchsorted(conf, np.arange(n), side="right") - 1
    v1 = np.where(p >= 0, val[np.clip(p, 0, None)], np.nan)
    v2 = np.where(p >= 1, val[np.clip(p - 1, 0, None)], np.nan)
    return v1, v2, p


def trend_arrays(b):
    h, l = b.high.to_numpy(), b.low.to_numpy(); n = len(b)
    sw = swings(h, l)
    h1, h2, ph = last_two(sw["hi_conf"], sw["hi_val"], n)
    l1, l2, pl = last_two(sw["lo_conf"], sw["lo_val"], n)
    with np.errstate(invalid="ignore"):
        tr = np.where((h1 > h2) & (l1 > l2), 1, np.where((h1 < h2) & (l1 < l2), -1, 0))
    return tr, sw, (h1, l1, ph, pl)


def nearest_beyond(sw, key, upto_conf_idx, price, direction, n_back=12):
    """Nearest confirmed swing high ABOVE price (direction +1) / swing low BELOW price (-1), among the last n_back."""
    conf = sw[key + "_conf"]; val = sw[key + "_val"]
    p = np.searchsorted(conf, upto_conf_idx, side="right")
    cand = val[max(0, p - n_back):p]
    if direction == 1:
        c = cand[cand > price]; return c.min() if len(c) else np.nan
    c = cand[cand < price]; return c.max() if len(c) else np.nan


def pick_target(sw, key, upto, entry_px, d, risk, min_r):
    """Nearest confirmed swing beyond entry whose reward:risk is at least min_r (0 = simply the nearest)."""
    conf = sw[key + "_conf"]; val = sw[key + "_val"]
    p = np.searchsorted(conf, upto, side="right")
    cand = val[max(0, p - 12):p]
    ok = cand[d * (cand - entry_px) / risk >= max(min_r, 1e-9)]
    if not len(ok):
        return np.nan
    return ok.min() if d == 1 else ok.max()


def generate(b15, b1h, entry="E1", aligned=True, tp_mode="swing15", min_rr=0.0,
             stop_buf=0.1, min_risk_atr=0.5, max_risk_atr=4.0, tp_min_r=0.0, kz=False, e2_mode="strict", need_target=True):
    n = len(b15)
    o, h, l, c = (b15[x].to_numpy() for x in ("open", "high", "low", "close"))
    atr = S.atr(b15).to_numpy()
    tr15, sw15, (hi1, lo1, _, _) = trend_arrays(b15)
    tr1h_bar, sw1h, _ = trend_arrays(b1h)
    close15 = (b15.index + pd.Timedelta(minutes=15)).asi8
    close1h = (b1h.index + pd.Timedelta(minutes=60)).asi8
    j = np.searchsorted(close1h, close15, side="right") - 1          # last 1H bar fully closed at this 15M close
    tr1h = np.where(j >= 0, tr1h_bar[np.clip(j, 0, None)], 0)
    rng = h - l; body = c - o
    ap = np.concatenate([[np.nan], atr[:-1]])                          # ATR as of the previous bar
    with np.errstate(invalid="ignore"):
        bull_disp = (body > 0) & (rng >= ap) & (body >= 0.5 * rng) & (c > np.concatenate([[np.nan], hi1[:-1]]))
        bear_disp = (body < 0) & (rng >= ap) & (-body >= 0.5 * rng) & (c < np.concatenate([[np.nan], lo1[:-1]]))
    zl, zs = [], []                                                    # active zones: [bottom, top, created, kind, used]
    pend2, pend3 = [], []
    rows = []
    for t in range(60, n):
        a = atr[t]
        if not np.isfinite(a) or a <= 0 or not np.isfinite(ap[t]):
            continue
        # ----- zone upkeep (strictly causal) -----
        zl = [z for z in zl if t - z[2] <= ZONE_LIFE and c[t] >= z[0] and not z[4]]
        zs = [z for z in zs if t - z[2] <= ZONE_LIFE and c[t] <= z[1] and not z[4]]
        # ----- create zones from displacement that breaks structure -----
        if bull_disp[t]:
            for jj in range(t - 1, max(t - 4, 0), -1):
                if c[jj] < o[jj]:
                    zl.append([l[jj], h[jj], t, "OB", False]); break
        if bear_disp[t]:
            for jj in range(t - 1, max(t - 4, 0), -1):
                if c[jj] > o[jj]:
                    zs.append([l[jj], h[jj], t, "OB", False]); break
        if bull_disp[t - 1] and l[t] > h[t - 2]:
            zl.append([h[t - 2], l[t], t, "FVG", False])
        if bear_disp[t - 1] and h[t] < l[t - 2]:
            zs.append([h[t], l[t - 2], t, "FVG", False])
        # ----- trend gate (as of this bar's close) -----
        for d in (1, -1):
            if tr15[t] != d or (aligned and tr1h[t] != d):
                continue
            zones = zl if d == 1 else zs
            L1 = lo1[t - 1] if d == 1 else hi1[t - 1]                  # latest swing liquidity, known BEFORE bar t
            if not np.isfinite(L1):
                continue
            # ---- sweep + tap on bar t ----
            swept = (l[t] < L1 and c[t] > L1) if d == 1 else (h[t] > L1 and c[t] < L1)
            if swept:
                for z in zones:
                    if z[2] >= t or z[4]:
                        continue
                    tapped = (l[t] <= z[1] + 0.25 * a and c[t] > z[0]) if d == 1 else (h[t] >= z[0] - 0.25 * a and c[t] < z[1])
                    if not tapped:
                        continue
                    ext = l[t] if d == 1 else h[t]
                    if entry == "E1":
                        rows.append(("E1", t, d, c[t], ext, z, t)); z[4] = True; break
                    if entry == "E2":
                        pend2.append((t, d, ext, z, t)); z[4] = True; break
                    if entry == "E3":
                        sh_prior = hi1[t - 1] if d == 1 else lo1[t - 1]
                        pend3.append([t, d, ext, sh_prior, z]); z[4] = True; break
        # ----- E2: one confirming candle right after the sweep bar -----
        if entry == "E2":
            keep = []
            for (s, d, ext, z, _) in pend2:
                if t == s + 1:
                    if e2_mode == "strict":
                        ok = (d == 1 and body[t] > 0 and body[t] >= 0.6 * rng[t] and c[t] > h[s]) or \
                             (d == -1 and body[t] < 0 and -body[t] >= 0.6 * rng[t] and c[t] < l[s])
                    else:       # loose: a clearly directional candle that closes past the middle of the sweep bar
                        ok = (d == 1 and body[t] > 0 and body[t] >= 0.4 * rng[t] and c[t] > (h[s] + l[s]) / 2) or \
                             (d == -1 and body[t] < 0 and -body[t] >= 0.4 * rng[t] and c[t] < (h[s] + l[s]) / 2)
                    if ok and ((d == 1 and tr15[t] == 1) or (d == -1 and tr15[t] == -1)):
                        e2 = min(ext, l[t]) if d == 1 else max(ext, h[t])
                        rows.append(("E2", t, d, c[t], e2, z, s))
                elif t <= s + 1:
                    keep.append((s, d, ext, z, _))
            pend2 = keep
        # ----- E3: market shift after the sweep, then limit into the shifting leg's order block -----
        if entry == "E3":
            keep = []
            for item in pend3:
                s, d, ext, shp, z = item
                if t <= s or t - s > 8:
                    if t <= s: keep.append(item)
                    continue
                shifted = (d == 1 and c[t] > shp and body[t] > 0 and rng[t] >= ap[t] and body[t] >= 0.5 * rng[t]) or \
                          (d == -1 and c[t] < shp and body[t] < 0 and rng[t] >= ap[t] and -body[t] >= 0.5 * rng[t])
                if not shifted:
                    keep.append(item); continue
                ob = None
                for jj in range(t - 1, max(t - 4, 0), -1):
                    if (d == 1 and c[jj] < o[jj]) or (d == -1 and c[jj] > o[jj]):
                        ob = (l[jj], h[jj]); break
                if ob is not None:
                    lim = (ob[0] + ob[1]) / 2
                    if (d == 1 and lim < c[t]) or (d == -1 and lim > c[t]):
                        rows.append(("E3", t, d, lim, ext, z, s))
        # (zones consumed above are dropped by the upkeep filter on the next bar)
    out = []
    if kz:
        import smc
        kzm, _ = smc.kill_zone_mask(b15, 15)
    for kind, t, d, entry_px, ext, z, s in rows:
        if kz and not kzm[t]:
            continue
        a = atr[t]; stop = ext - stop_buf * a if d == 1 else ext + stop_buf * a
        risk = d * (entry_px - stop)
        if not (min_risk_atr * a <= risk <= max_risk_atr * a):
            continue
        ref = c[t]
        if tp_min_r > 0:
            tgt = pick_target(sw15, "hi" if d == 1 else "lo", t, entry_px, d, risk, tp_min_r)
        elif tp_mode == "swing15":
            tgt = nearest_beyond(sw15, "hi" if d == 1 else "lo", t, entry_px, d)
        else:
            jh = int(j[t]); tgt = nearest_beyond(sw1h, "hi" if d == 1 else "lo", jh, entry_px, d) if jh >= 0 else np.nan
        if need_target:
            if not np.isfinite(tgt):
                continue
            rr = d * (tgt - entry_px) / risk
            if rr <= 0 or rr < min_rr:
                continue
        else:
            rr = d * (tgt - entry_px) / risk if np.isfinite(tgt) else np.nan
        out.append((t, d, kind, entry_px, stop, tgt, risk, rr, z[3], int(tr1h[t] == d)))
    return pd.DataFrame(out, columns=["t", "dir", "model", "entry", "stop", "target", "risk", "rr", "poi", "h1_aligned"])
