"""
Backtest of XAU_ScalpIntraday_EA.mq5 logic on Dukascopy XAUUSD M1 data.

Faithful Python port of the EA rules:
  SCALP    : M5 bias (EMA50/200 + ADX) + H1 agreement, M1 pullback/trigger entry
  INTRADAY : H4 bias (EMA50/200 + ADX), H1 pullback/trigger entry
  3 legs (TP1 / liquidity TP2 / runner), BE+lock at 1R, ATR trail clamped in pips,
  sessions, max setups/day, losing-streak stop, daily loss limit, Friday close.

Simulation on M1 bars (BID data, constant spread added for ASK):
  - entries at the open of the first M1 bar of a new entry-TF candle
  - SL checked before TP inside a bar (conservative)
  - stops are trailed using the bar's favourable extreme; if the bar then
    closes through the new stop it is treated as hit at that stop
Not modelled: news filter (EA disables it in the tester too), swaps, slippage.

Usage: python3 xau_ea_backtest.py [start_date] [end_date] [balance]
"""
import copy
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_UTC_OFFSET_H = 3        # typical gold broker server time in summer (GMT+3)
CONTRACT = 100.0               # oz per 1.00 lot
LOT_STEP = 0.01
LOT_MIN = 0.01

BASE = dict(
    pip=0.10, spread=0.30, max_spread_pips=5.0,
    max_daily_loss_pct=3.0, close_on_daily_loss=True,
    friday_no_new_hour=18, friday_close_hour=21,
    bias_fast=50, bias_slow=200, adx_period=14, min_adx=20.0,
    entry_fast=21, entry_slow=50, atr_period=14, rsi_period=14, rsi_max_long=75.0,
    min_body_ratio=0.5, pullback_bars=6, require_sweep=False, sweep_lookback=10,
    sl_structure_bars=5, sl_buffer_atr=0.3, sl_min_atr=1.0, target_lookback=50,
    be_trigger_r=1.0, be_lock_pips=3.0, trail_start_r=1.0, trail_step_pips=5.0,
    # sizing policy: 'ea' = exactly the EA (skip if below min lot);
    # 'min_lot' = fall back to the minimum lot if that risk <= min_lot_max_risk_pct
    sizing="ea", min_lot_max_risk_pct=0.0,
    engines=[
        dict(name="SCALP", on=True, bias_tf="5min", entry_tf="1min", h1_filter=True,
             risk_pct=0.5, sl_min=30, sl_max=120, tp1_r=1.0, tp2_r=2.0, runner_r=4.0,
             split=(50, 30, 20), trail_min=25, trail_max=40, trail_atr=1.5,
             start_hour=9, end_hour=20, max_per_day=6, max_consec_loss=3),
        dict(name="INTRADAY", on=True, bias_tf="4h", entry_tf="1h", h1_filter=False,
             risk_pct=1.0, sl_min=100, sl_max=500, tp1_r=1.0, tp2_r=2.0, runner_r=4.0,
             split=(40, 30, 30), trail_min=40, trail_max=60, trail_atr=1.0,
             start_hour=3, end_hour=21, max_per_day=2, max_consec_loss=2),
    ],
)


# --------------------------------------------------------------------------- data
def load_csv(name):
    df = pd.read_csv(os.path.join(HERE, "data", name))
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    # work in broker server time (naive) so sessions / H4 candles line up like MT5
    df.index = (df.index + pd.Timedelta(hours=SERVER_UTC_OFFSET_H)).tz_localize(None)
    return df


def load_m1():
    return load_csv("XAUUSD_M1.csv")


def load_h1():
    """Dukascopy monthly H1 candles: long history for the H1/H4 EMA200 warm-up."""
    p = os.path.join(HERE, "data", "XAUUSD_H1.csv")
    return load_csv("XAUUSD_H1.csv") if os.path.exists(p) else None


def resample(m1, rule):
    if rule == "1min":
        return m1.copy()
    r = m1.resample(rule, label="left", closed="left")
    out = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                        "low": r["low"].min(), "close": r["close"].last()}).dropna()
    return out


# --------------------------------------------------------------------- indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr_sma(df, n):  # MT5 iATR = simple average of true range
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi_wilder(s, n):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def adx_mt5(df, n):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    size = len(df)
    pdi_raw = np.zeros(size)
    mdi_raw = np.zeros(size)
    for i in range(1, size):
        p = max(h[i] - h[i - 1], 0.0)
        m = max(l[i - 1] - l[i], 0.0)
        if p > m:
            m = 0.0
        elif m > p:
            p = 0.0
        else:
            p = m = 0.0
        tr = max(h[i], c[i - 1]) - min(l[i], c[i - 1])
        if tr > 0:
            pdi_raw[i] = 100 * p / tr
            mdi_raw[i] = 100 * m / tr
    pdi = pd.Series(pdi_raw).ewm(span=n, adjust=False).mean()
    mdi = pd.Series(mdi_raw).ewm(span=n, adjust=False).mean()
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0)
    return pd.Series(dx.ewm(span=n, adjust=False).mean().values, index=df.index)


def tf_delta(rule):
    return pd.Timedelta(rule)


class TF:
    """One timeframe with indicators and close-time lookup."""

    def __init__(self, m1, rule, cfg, kind):
        df = resample(m1, rule)
        self.open_t = df.index.values
        self.close_t = (df.index + tf_delta(rule)).values
        self.o, self.h = df["open"].values, df["high"].values
        self.l, self.c = df["low"].values, df["close"].values
        if kind == "bias":
            self.fast = ema(df["close"], cfg["bias_fast"]).values
            self.slow = ema(df["close"], cfg["bias_slow"]).values
            self.adx = adx_mt5(df, cfg["adx_period"]).values
        else:
            self.fast = ema(df["close"], cfg["entry_fast"]).values
            self.slow = ema(df["close"], cfg["entry_slow"]).values
            self.atr = atr_sma(df, cfg["atr_period"]).values
            self.rsi = rsi_wilder(df["close"], cfg["rsi_period"]).values

    def last_closed(self, t):
        """index of the last candle fully closed at time t (MT5 shift 1)."""
        return int(np.searchsorted(self.close_t, t, side="right")) - 1

    def current(self, t):
        """index of the candle forming at time t (MT5 shift 0)."""
        return int(np.searchsorted(self.open_t, t, side="right")) - 1


# ---------------------------------------------------------------------- strategy
def get_signal(cfg, eng, bias_tf, entry_tf, h1_tf, t):
    k = bias_tf.last_closed(t)
    if k < max(cfg["bias_slow"], 10):
        return 0, None, None
    bF, bF4, bS, adx, bC = bias_tf.fast[k], bias_tf.fast[k - 3], bias_tf.slow[k], bias_tf.adx[k], bias_tf.c[k]
    bias = 1 if (bC > bS and bF > bS and bF > bF4) else (-1 if (bC < bS and bF < bS and bF < bF4) else 0)
    if bias == 0 or adx < cfg["min_adx"]:
        return 0, None, None
    if eng["h1_filter"]:
        j = h1_tf.last_closed(t)
        if j < cfg["bias_slow"]:
            return 0, None, None
        hb = 1 if (h1_tf.c[j] > h1_tf.slow[j] and h1_tf.fast[j] > h1_tf.slow[j]) else \
            (-1 if (h1_tf.c[j] < h1_tf.slow[j] and h1_tf.fast[j] < h1_tf.slow[j]) else 0)
        if hb != bias:
            return 0, None, None

    i = entry_tf.current(t)          # forming bar; r[1] = i-1
    need = max(cfg["target_lookback"] + 2, 4 + cfg["sweep_lookback"],
               max(cfg["pullback_bars"], cfg["sl_structure_bars"]) + 2)
    if i - need < cfg["entry_slow"]:
        return 0, None, None
    e = entry_tf
    f1, s1, atr, rsi = e.fast[i - 1], e.slow[i - 1], e.atr[i - 1], e.rsi[i - 1]
    if not np.isfinite(atr) or atr <= 0:
        return 0, None, None
    o1, h1, l1, c1 = e.o[i - 1], e.h[i - 1], e.l[i - 1], e.c[i - 1]
    rng = h1 - l1
    if rng <= 0:
        return 0, None, None
    strong = abs(c1 - o1) / rng >= cfg["min_body_ratio"]

    def lowest(frm, cnt):
        return e.l[i - frm - cnt + 1:i - frm + 1].min()

    def highest(frm, cnt):
        return e.h[i - frm - cnt + 1:i - frm + 1].max()

    if bias > 0:
        pb = lowest(1, cfg["pullback_bars"])
        ok = (f1 > s1 and pb <= f1 + 0.25 * atr and pb >= s1 - 0.5 * atr and c1 > o1 and strong
              and c1 > e.h[i - 2] and c1 > f1 and 50 < rsi < cfg["rsi_max_long"])
        if ok and cfg["require_sweep"]:
            ok = lowest(1, 3) < lowest(4, cfg["sweep_lookback"])
        if not ok:
            return 0, None, None
        sl = min(lowest(1, cfg["sl_structure_bars"]) - cfg["sl_buffer_atr"] * atr, c1 - cfg["sl_min_atr"] * atr)
        return 1, sl, highest(2, cfg["target_lookback"])
    pb = highest(1, cfg["pullback_bars"])
    ok = (f1 < s1 and pb >= f1 - 0.25 * atr and pb <= s1 + 0.5 * atr and c1 < o1 and strong
          and c1 < e.l[i - 2] and c1 < f1 and 100 - cfg["rsi_max_long"] < rsi < 50)
    if ok and cfg["require_sweep"]:
        ok = highest(1, 3) > highest(4, cfg["sweep_lookback"])
    if not ok:
        return 0, None, None
    sl = max(highest(1, cfg["sl_structure_bars"]) + cfg["sl_buffer_atr"] * atr, c1 + cfg["sl_min_atr"] * atr)
    return -1, sl, lowest(2, cfg["target_lookback"])


def norm_lot(v):
    v = np.floor(v / LOT_STEP + 1e-9) * LOT_STEP
    return round(v, 2) if v >= LOT_MIN else 0.0


def run(m1, cfg, start, end, balance, h1=None):
    eng_cfgs = [e for e in cfg["engines"] if e["on"]]

    def src(rule):  # hourly-and-up candles come from the long H1 history when available
        return h1 if (h1 is not None and pd.Timedelta(rule) >= pd.Timedelta("1h")) else m1

    tfs = {}
    for e in eng_cfgs:
        tfs[(e["name"], "bias")] = TF(src(e["bias_tf"]), e["bias_tf"], cfg, "bias")
        tfs[(e["name"], "entry")] = TF(src(e["entry_tf"]), e["entry_tf"], cfg, "entry")
    h1_tf = TF(src("1h"), "1h", cfg, "bias")

    sim = m1[(m1.index >= start) & (m1.index < end)]
    T = sim.index.values
    O, H, L, C = sim["open"].values, sim["high"].values, sim["low"].values, sim["close"].values
    pip, spread = cfg["pip"], cfg["spread"]

    equity_closed = balance
    positions = []           # open legs
    setups = []              # all setups
    last_entry_bar = {e["name"]: -1 for e in eng_cfgs}
    day_start_bal, day_key, day_blocked = balance, None, False
    curve = []
    stats = {e["name"]: dict(signals=0, skipped_size=0, skipped_wide=0) for e in eng_cfgs}

    def close_leg(p, price, t, why):
        nonlocal equity_closed
        pnl = p["dir"] * (price - p["open"]) * p["lots"] * CONTRACT
        equity_closed += pnl
        p.update(exit=price, exit_t=t, pnl=pnl, why=why)
        s = p["setup"]
        s["pnl"] += pnl
        s["open_legs"] -= 1
        s["r_mult"] += p["dir"] * (price - p["open"]) / s["R"] * p["lots"] / s["lots"]
        if s["open_legs"] == 0:
            s["exit_t"] = t

    for j in range(len(T)):
        t = T[j]
        ts = pd.Timestamp(t)
        dkey = ts.date()
        if dkey != day_key:
            day_key = dkey
            day_start_bal, day_blocked = equity_closed, False
        dow, hour = ts.weekday(), ts.hour   # Mon=0 .. Fri=4

        # Friday close
        if cfg["friday_close_hour"] and dow == 4 and hour >= cfg["friday_close_hour"] and positions:
            for p in positions:
                close_leg(p, O[j] + (spread if p["dir"] < 0 else 0.0), t, "friday")
            positions = []

        # ---- entries (new entry-TF candle)
        for e in eng_cfgs:
            etf = tfs[(e["name"], "entry")]
            bi = etf.current(t)
            if bi == last_entry_bar[e["name"]]:
                continue
            last_entry_bar[e["name"]] = bi
            if day_blocked:
                continue
            if dow >= 5 or (cfg["friday_no_new_hour"] and dow == 4 and hour >= cfg["friday_no_new_hour"]):
                continue
            sh, eh = e["start_hour"], e["end_hour"]
            if not (sh == eh or (sh < eh and sh <= hour < eh) or (sh > eh and (hour >= sh or hour < eh))):
                continue
            if any(p["setup"]["engine"] == e["name"] for p in positions):
                continue
            today = [s for s in setups if s["engine"] == e["name"] and pd.Timestamp(s["t"]).date() == dkey]
            if e["max_per_day"] and len(today) >= e["max_per_day"]:
                continue
            streak = 0
            for s in today:
                if s["open_legs"] == 0:
                    streak = streak + 1 if s["pnl"] < 0 else 0
            if e["max_consec_loss"] and streak >= e["max_consec_loss"]:
                continue
            if spread / pip > cfg["max_spread_pips"]:
                continue
            d, sl_level, liq = get_signal(cfg, e, tfs[(e["name"], "bias")], etf, h1_tf, t)
            if d == 0:
                continue
            stats[e["name"]]["signals"] += 1
            entry = O[j] + (spread if d > 0 else 0.0)
            R = d * (entry - sl_level)
            R = max(R, e["sl_min"] * pip)
            if R > e["sl_max"] * pip:
                stats[e["name"]]["skipped_wide"] += 1
                continue
            sl = entry - d * R
            tp1 = entry + d * e["tp1_r"] * R
            tp2 = entry + d * e["tp2_r"] * R
            liq_d = d * (liq - entry)
            cap = (e["runner_r"] if e["runner_r"] > 0 else 6.0) * R
            if 1.5 * R <= liq_d <= cap:
                tp2 = liq - d * 2 * pip
            if d * (tp2 - tp1) < 0.3 * R:
                tp2 = entry + d * e["tp2_r"] * R
            tp3 = entry + d * e["runner_r"] * R if e["runner_r"] > 0 else 0.0

            eq = equity_closed + sum(p["dir"] * (O[j] - p["open"]) * p["lots"] * CONTRACT for p in positions)
            total = eq * e["risk_pct"] / 100 / (R * CONTRACT)
            ssum = sum(e["split"]) or 100
            lots = [norm_lot(total * x / ssum) for x in e["split"]]
            if lots[0] <= 0:
                lots = [norm_lot(total), 0.0, 0.0]
            if lots[0] <= 0 and cfg["sizing"] == "min_lot":
                if LOT_MIN * R * CONTRACT <= eq * cfg["min_lot_max_risk_pct"] / 100:
                    lots = [LOT_MIN, 0.0, 0.0]
            if lots[0] <= 0:
                stats[e["name"]]["skipped_size"] += 1
                continue
            tps = [tp1, tp2, tp3]
            if lots[1] <= 0 and lots[2] <= 0:
                tps[0] = tp2
            s = dict(engine=e["name"], t=t, dir=d, entry=entry, R=R, sl=sl, tps=tps, lots=sum(lots),
                     legs=[l for l in lots if l > 0], risk_usd=sum(lots) * R * CONTRACT,
                     pnl=0.0, r_mult=0.0, open_legs=0, exit_t=None)
            setups.append(s)
            for k in range(3):
                if lots[k] <= 0:
                    continue
                positions.append(dict(setup=s, eng=e, dir=d, open=entry, sl=sl, tp=tps[k], lots=lots[k], leg=k + 1))
                s["open_legs"] += 1

        # ---- manage open legs on this bar
        still = []
        for p in positions:
            d = p["dir"]
            e = p["eng"]
            # prices as seen by the position: buys exit on BID, sells on ASK
            lo, hi, cl, op = (L[j], H[j], C[j], O[j]) if d > 0 else (L[j] + spread, H[j] + spread, C[j] + spread, O[j] + spread)
            hit = None
            if d > 0:
                if lo <= p["sl"]:
                    hit = (min(op, p["sl"]), "sl")
                elif p["tp"] and hi >= p["tp"]:
                    hit = (max(op, p["tp"]), "tp")
            else:
                if hi >= p["sl"]:
                    hit = (max(op, p["sl"]), "sl")
                elif p["tp"] and lo <= p["tp"]:
                    hit = (min(op, p["tp"]), "tp")
            if hit:
                close_leg(p, hit[0], t, hit[1])
                continue
            # trailing using the favourable extreme
            fav = hi if d > 0 else lo
            R = p["setup"]["R"]
            prof = d * (fav - p["open"])
            new_sl = p["sl"]
            if prof >= cfg["be_trigger_r"] * R:
                be = p["open"] + d * cfg["be_lock_pips"] * pip
                if d * (be - new_sl) > 0:
                    new_sl = be
            if prof >= cfg["trail_start_r"] * R:
                etf = tfs[(e["name"], "entry")]
                ai = etf.current(t) - 1
                a = etf.atr[ai] if ai >= 0 else np.nan
                dist = e["trail_max"] * pip
                if np.isfinite(a) and a > 0:
                    dist = max(e["trail_min"] * pip, min(e["trail_max"] * pip, a * e["trail_atr"]))
                cand = fav - d * dist
                if d * (cand - new_sl) > 0:
                    new_sl = cand
            first_lock = d * (p["sl"] - p["open"]) < 0
            if d * (new_sl - p["sl"]) > 0 and (first_lock or d * (new_sl - p["sl"]) >= cfg["trail_step_pips"] * pip):
                p["sl"] = new_sl
                if d * (cl - new_sl) <= 0:      # closed back through the new stop
                    close_leg(p, new_sl, t, "trail")
                    continue
            still.append(p)
        positions = still

        # ---- daily loss limit
        eq = equity_closed + sum(p["dir"] * ((C[j] if p["dir"] > 0 else C[j] + spread) - p["open"]) * p["lots"] * CONTRACT
                                 for p in positions)
        if cfg["max_daily_loss_pct"] > 0 and not day_blocked and (eq - day_start_bal) / day_start_bal * 100 <= -cfg["max_daily_loss_pct"]:
            day_blocked = True
            if cfg["close_on_daily_loss"]:
                for p in positions:
                    close_leg(p, C[j] if p["dir"] > 0 else C[j] + spread, t, "daily_limit")
                positions = []
        if j % 60 == 0:
            curve.append((t, eq))

    for p in positions:   # close anything left at the end
        close_leg(p, C[-1] if p["dir"] > 0 else C[-1] + spread, T[-1], "end")
    return setups, curve, stats, equity_closed


# ----------------------------------------------------------------------- report
def summarize(setups, curve, stats, final, balance, label):
    out = {"label": label, "start_balance": balance, "final_balance": round(final, 2),
           "return_pct": round((final / balance - 1) * 100, 2)}
    eq = np.array([c[1] for c in curve]) if curve else np.array([balance])
    peak = np.maximum.accumulate(eq)
    out["max_drawdown_pct"] = round(float(((eq - peak) / peak).min() * -100), 2)
    for name in sorted(set([s["engine"] for s in setups]) | set(stats)):
        ss = [s for s in setups if s["engine"] == name]
        wins = [s for s in ss if s["pnl"] > 0]
        losses = [s for s in ss if s["pnl"] <= 0]
        gp = sum(s["pnl"] for s in wins)
        gl = -sum(s["pnl"] for s in losses)
        out[name] = dict(
            setups=len(ss), wins=len(wins), losses=len(losses),
            win_rate_pct=round(100 * len(wins) / len(ss), 1) if ss else 0.0,
            net_usd=round(sum(s["pnl"] for s in ss), 2),
            profit_factor=round(gp / gl, 2) if gl > 0 else None,
            avg_win_usd=round(gp / len(wins), 2) if wins else 0.0,
            avg_loss_usd=round(-gl / len(losses), 2) if losses else 0.0,
            avg_r=round(float(np.mean([s["r_mult"] for s in ss])), 2) if ss else 0.0,
            total_r=round(float(np.sum([s["r_mult"] for s in ss])), 2) if ss else 0.0,
            avg_risk_usd=round(float(np.mean([s["risk_usd"] for s in ss])), 2) if ss else 0.0,
            **stats.get(name, {}),
        )
    return out


def main():
    end = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp("2026-10-01")
    start = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else end - pd.Timedelta(days=90)
    balance = float(sys.argv[3]) if len(sys.argv) > 3 else 500.0
    m1 = load_m1()
    h1 = load_h1()
    print(f"data {m1.index[0]} -> {m1.index[-1]} ({len(m1)} M1 bars), test {start.date()} -> {end.date()}")

    runs = []
    ea = copy.deepcopy(BASE)
    runs.append(("EA defaults (0.5% scalp / 1% intraday risk)", ea))
    small = copy.deepcopy(BASE)
    small["sizing"] = "min_lot"
    small["min_lot_max_risk_pct"] = 5.0
    runs.append(("$500 mode: min lot 0.01 allowed if risk <= 5%", small))

    results = []
    all_setups = {}
    for label, cfg in runs:
        setups, curve, stats, final = run(m1, cfg, start, end, balance, h1)
        res = summarize(setups, curve, stats, final, balance, label)
        results.append(res)
        all_setups[label] = setups
        print(json.dumps(res, indent=2, default=str))

    with open(os.path.join(HERE, "xau_ea_backtest_results.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    rows = []
    for label, ss in all_setups.items():
        for s in ss:
            rows.append(dict(run=label, engine=s["engine"], time_server=pd.Timestamp(s["t"]),
                             side="BUY" if s["dir"] > 0 else "SELL", entry=round(s["entry"], 2),
                             sl_pips=round(s["R"] / 0.10, 1), lots="/".join(f"{l:.2f}" for l in s["legs"]),
                             risk_usd=round(s["risk_usd"], 2), r_mult=round(s["r_mult"], 2),
                             pnl_usd=round(s["pnl"], 2),
                             exit_server=pd.Timestamp(s["exit_t"]) if s["exit_t"] is not None else None))
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "xau_ea_backtest_trades.csv"), index=False)


if __name__ == "__main__":
    main()
