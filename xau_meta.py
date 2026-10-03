"""
Meta-labelling for XAUUSD: score EVERY possible trade with a model, take only the
highest-confidence ones. Strict walk-forward, real bid/ask costs.

Pipeline
  1. At every signal-timeframe bar close, simulate a LONG and a SHORT trade with a
     triple barrier (stop = sl_atr*ATR, target = tp*R, or time exit) on the real
     M1 bid/ask -- the exact fills xau_engine uses. That gives each bar two labels.
  2. Features describe the market state at that bar's close and nothing later.
  3. Walk-forward: to trade year Y, fit on data entered strictly before Y minus a
     purge window (the trade horizon), so no label overlaps the test period.
  4. Trade the top-q fraction of the test year's bars by predicted expected R
     (ranked on predictions only -- no labels are used to pick the threshold).
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import xau_engine as E
import xau_strategies as S


def entry_index(m1, b, rule):
    """First M1 bar at/after each TF bar's close; -1 where the market was shut."""
    tmin = E._min(m1.index)
    close_min = E._min(b.index) + E.tf_minutes(rule)
    ent = np.searchsorted(tmin, close_min, side="left")
    ok = ent < len(tmin)
    ok[ok] = (tmin[ent[ok]] - close_min[ok]) <= 15
    return np.where(ok, ent, -1).astype(np.int64)


def build_features(b, m1, rule):
    c, a = b.close, S.atr(b)
    per_day = int(1440 / E.tf_minutes(rule))
    X = pd.DataFrame(index=b.index)
    for k in (1, 2, 4, 8, 16, 32, 64):
        X[f"ret{k}"] = (c - c.shift(k)) / a
    X["ret1d"] = (c - c.shift(per_day)) / a
    X["ret5d"] = (c - c.shift(5 * per_day)) / a
    for n in (3, 7, 14):
        X[f"rsi{n}"] = S.rsi(c, n)
    m, sd = c.rolling(20).mean(), c.rolling(20).std()
    X["bbz"] = (c - m) / sd
    for n in (20, 50, 200):
        X[f"ema{n}"] = (c - S.ema(c, n)) / a
    e50, e200 = S.ema(c, 50), S.ema(c, 200)
    X["slope50"] = (e50 - e50.shift(8)) / a
    X["slope200"] = (e200 - e200.shift(32)) / a
    X["volratio"] = a / a.rolling(500).median()
    X["adx"] = S.adx(b)
    rng = (b.high - b.low).replace(0, np.nan)
    X["bar_rng"] = rng / a
    X["bar_pos"] = (c - b.low) / rng
    X["bar_body"] = (c - b.open) / a
    for n in (20, 60):
        X[f"dhi{n}"] = (b.high.rolling(n).max().shift(1) - c) / a
        X[f"dlo{n}"] = (c - b.low.rolling(n).min().shift(1)) / a
    hr = b.index.hour + b.index.minute / 60.0
    X["hsin"], X["hcos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    X["dow"] = b.index.dayofweek.astype(float)
    sp = (m1.ac - m1.bc).resample(rule, label="left", closed="left").mean().reindex(b.index)
    X["spr"] = sp / a
    X["spr_abs"] = sp
    X["atr_abs"] = a
    return X.astype("float32")


def label_all(m1, b, ent, sl_atr, tp, hold):
    """Independent triple-barrier outcome (R, exit M1 index) for a long and a short at every bar."""
    a = S.atr(b).to_numpy()
    valid = (ent >= 0) & np.isfinite(a) & (a > 0)
    idx = np.flatnonzero(valid)
    tmin = E._min(m1.index)
    arr = [np.ascontiguousarray(m1[c_].to_numpy("float64")) for c_ in ("bo", "bh", "bl", "bc", "ao", "ah", "al", "ac")]
    out = {}
    for d in (1, -1):
        r = np.empty(len(idx)); xi = np.empty(len(idx), np.int64); w = np.empty(len(idx), np.int64)
        E._sim(ent[idx].astype(np.int64), np.full(len(idx), d, np.int64), (sl_atr * a[idx]).astype("float64"),
               float(tp), int(hold), 0.0, tmin, *arr, r, xi, w)
        full_r = np.full(len(b), np.nan); full_x = np.full(len(b), -1, np.int64)
        full_r[idx], full_x[idx] = r, xi
        out[d] = (full_r, full_x)
    return out


def make_model():
    return HistGradientBoostingRegressor(max_iter=150, learning_rate=0.05, max_leaf_nodes=15,
                                         min_samples_leaf=500, l2_regularization=1.0, random_state=0)


def walk_forward_preds(X, lab, ent_time, hold, test_years):
    """Out-of-sample predicted expected R for long/short at every bar of each test year."""
    pred = {1: np.full(len(X), np.nan), -1: np.full(len(X), np.nan)}
    Xv = X.to_numpy()
    for Y in test_years:
        start = pd.Timestamp(f"{Y}-01-01", tz="UTC"); end = pd.Timestamp(f"{Y + 1}-01-01", tz="UTC")
        purge = start - pd.Timedelta(minutes=hold + 60)
        tr = (X.index < purge) & np.isfinite(Xv).all(1)
        te = (X.index >= start) & (X.index < end) & np.isfinite(Xv).all(1)
        for d in (1, -1):
            y = lab[d][0]
            m = tr & np.isfinite(y)
            if m.sum() < 5000 or te.sum() == 0:
                continue
            mdl = make_model().fit(Xv[m], y[m])
            pred[d][te] = mdl.predict(Xv[te])
    return pred


def pick_trades(pred, lab, ent, X_index, q, years, hold_cd=1):
    """Top-q fraction of each year's bars by best predicted R; one position at a time."""
    pl, ps = pred[1], pred[-1]
    best = np.where(np.nan_to_num(pl, nan=-9) >= np.nan_to_num(ps, nan=-9), pl, ps)
    side = np.where(np.nan_to_num(pl, nan=-9) >= np.nan_to_num(ps, nan=-9), 1, -1)
    rows = []
    for Y in years:
        m = (X_index.year == Y) & np.isfinite(best)
        if m.sum() == 0:
            continue
        thr = np.quantile(best[m], 1 - q)
        sel = np.flatnonzero(m & (best >= thr))
        busy = -1
        for i in sel:
            if ent[i] <= busy:
                continue
            d = side[i]
            r, xi = lab[d][0][i], lab[d][1][i]
            if not np.isfinite(r):
                continue
            rows.append((X_index[i], int(d), float(r), int(xi)))
            busy = xi + hold_cd
    t = pd.DataFrame(rows, columns=["entry_time", "dir", "r", "xi"])
    t["risk"] = np.nan
    return t
