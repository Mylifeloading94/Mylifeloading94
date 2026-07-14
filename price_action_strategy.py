"""
Trend-Pullback Price Action Strategy
=====================================
A pure price-action system — no indicators beyond a moving average used as a
dynamic value zone. No SMC/ICT liquidity concepts; the edge (if any) is
candlestick rejection + momentum confirmation traded with the higher-timeframe
trend, honestly filled and costed like every other backtest in this repo.

Timeframes
  4H  -> trend regime  (EMA50 vs EMA200, price vs EMA50)
  1H  -> entry trigger (pullback to EMA20 + reversal candle + momentum break)

Setup (long; short is the mirror)
  1. 4H trend up:  EMA50 > EMA200  AND  4H close > EMA50.
  2. 1H pullback:  signal bar's low comes within 0.25*ATR of (or below) the
     1H EMA20 — price returned to value instead of running away from it.
  3. Reversal candle at the pullback, either:
       - Bull pin bar   — lower wick >= 60% of range, body <= 35% of range,
         close in the top 40% of the bar.
       - Bull engulfing — bullish body fully engulfs the prior bearish body.
  4. Not extended: close within 1.5*ATR of EMA20 (no chasing).
  5. Entry = stop order at the signal bar's high + spread, valid 3 bars
     (trade-through fill only, never a touch).
  6. Stop = min(signal bar low, prior bar low) - 0.1*ATR.
  7. Exit = TP1 at +2R (close 50%, stop to breakeven) -> TP2 at +4R runner,
     40-bar (~1 week) time-stop on the runner.

Honest-fill rules (same standard as sniper_smc.py / honest_edge.py)
  - Limit/stop fill only on trade-through, never a touch.
  - A bar that hits both SL and TP in the same bar = loss.
  - Entry price pays the spread; no lookahead — only closed bars are used,
    and the 4H trend used at bar i is the last 4H bar that CLOSED before i.
  - One open trade per instrument at a time.

Run directly to backtest the full watchlist over the last 6 months:
    python3 price_action_strategy.py

STATUS: NOT VALIDATED — do not go live on this alone.
=========================================================
6-month backtest (Jan-Jul 2026, Yahoo hourly bars, honest fills, spread paid):

| Instrument | n  | WR    | PF   | E[R]  | totalR |
|-----------|----|-------|------|-------|--------|
| SPX500    | 15 | 46.7% | 2.25 | +0.59 | +8.8   |
| US30      | 21 | 47.6% | 1.93 | +0.44 | +9.3   |
| NAS100    | 15 | 40.0% | 1.30 | +0.18 | +2.7   |
| all 14 FX pairs + XAUUSD | 52-79 each | 21-34% | 0.44-0.93 | negative | negative |

Only the three equity indices show positive expectancy; every FX pair and
XAUUSD LOSES money with this exact setup over the period (spread + a low
~25-30% hit rate against 2R/4R targets is a losing combination). This mirrors
the honest_edge.py finding: naive trend-continuation price action is not a
free edge on FX.

Split-half check (first 3mo vs last 3mo) on the three positive indices:
| Instrument | H1 (Jan-Apr)      | H2 (Apr-Jul)      |
|-----------|--------------------|--------------------|
| SPX500    | n=5  PF=3.50 +1.00R | n=4  PF=0.00 -0.76R |
| US30      | n=5  PF=3.08 +0.83R | n=7  PF=0.23 -0.44R |
| NAS100    | n=5  PF=8.00 +1.40R | n=6  PF=0.00 -1.00R |

The index edge is entirely front-loaded in H1 and INVERTS in H2 — it does not
hold out-of-sample. Parameter perturbation (+-25% on touch/extension/stop
tolerances) leaves all three indices PF > 1.2 in-sample, so the in-sample
signal isn't a fluke of exact parameters, but the failed split-half means
it's regime-dependent, not a standing edge.

A London/NY-killzone session filter (07:00-10:30 / 12:00-15:30 UTC, applied
to FX + XAUUSD only) was also tested: it nudges USDCAD, EURAUD and XAUUSD to
barely positive (PF 1.09-1.24, E[R] +0.09 to +0.15, n=31-43) but nowhere near
this repo's go-live gate (PF > 1.2 over 40+ trades, out-of-sample).

Verdict: nothing here clears the repo's go-live bar yet. Indices are the only
instruments worth watching further; re-run monthly as more data accumulates
before considering real size. Do not trade this on FX/XAUUSD as configured.
"""
import glob
import os
import numpy as np
import pandas as pd

DATA_DIR = os.environ.get(
    "PA_DATA_DIR",
    "/tmp/claude-0/-home-user-Mylifeloading94/684a5836-4d64-52de-bc1e-5f71b18c7741/scratchpad/data",
)

# per-instrument cost model: round-trip spread in PRICE UNITS (not pips),
# applied once at entry (pay the ask), matching sniper_smc's convention.
SPREAD = {
    "EURUSD": 0.00012, "GBPUSD": 0.00016, "USDJPY": 0.015, "USDCHF": 0.00018,
    "USDCAD": 0.00018, "AUDUSD": 0.00015, "NZDUSD": 0.00022, "EURJPY": 0.020,
    "GBPJPY": 0.030, "EURGBP": 0.00016, "AUDJPY": 0.025, "EURAUD": 0.00022,
    "CADJPY": 0.020, "CHFJPY": 0.025, "XAUUSD": 0.35, "NAS100": 2.0,
    "SPX500": 0.6, "US30": 3.0,
}

RISK_PCT_LOW, RISK_PCT_HIGH = 0.01, 0.02
TP1_R, TP2_R = 2.0, 4.0
TP1_CLOSE_FRAC = 0.5
FILL_WINDOW = 3
STOP_BUFFER_ATR = 0.10
TOUCH_TOL_ATR = 0.25
EXT_TOL_ATR = 1.5
TIME_STOP_BARS = 40
WARMUP = 250


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def load(name):
    path = os.path.join(DATA_DIR, f"{name}.csv")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("time").drop(columns=["timestamp"]).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df.dropna()


def build_4h_trend(df1h):
    h4 = df1h.resample("4h", label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    h4["ema50"] = ema(h4["close"], 50)
    h4["ema200"] = ema(h4["close"], 200)
    h4["bias"] = 0
    up = (h4["ema50"] > h4["ema200"]) & (h4["close"] > h4["ema50"])
    dn = (h4["ema50"] < h4["ema200"]) & (h4["close"] < h4["ema50"])
    h4.loc[up, "bias"] = 1
    h4.loc[dn, "bias"] = -1
    return h4[["bias"]]


def bull_pin(o, h, l, c):
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lower_wick = min(o, c) - l
    return lower_wick >= 0.6 * rng and body <= 0.35 * rng and (c - l) >= 0.6 * rng


def bear_pin(o, h, l, c):
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    return upper_wick >= 0.6 * rng and body <= 0.35 * rng and (h - c) >= 0.6 * rng


def bull_engulf(po, pc, o, c):
    return pc < po and c > o and o <= pc and c >= po


def bear_engulf(po, pc, o, c):
    return pc > po and c < o and o >= pc and c <= po


def generate_signals(df1h, h4trend):
    df = df1h.copy()
    df["ema20"] = ema(df["close"], 20)
    df["atr"] = atr(df, 14)
    trend = h4trend.reindex(df.index, method="ffill")
    # last 4H bar that CLOSED before this 1H bar's timestamp -> avoid lookahead
    bias_asof = pd.merge_asof(
        df.reset_index()[["time"]], h4trend.reset_index().rename(columns={"time": "h4time"}),
        left_on="time", right_on="h4time", direction="backward",
    )
    df["bias"] = bias_asof["bias"].values

    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    ema20, atr_ = df["ema20"].values, df["atr"].values
    bias = df["bias"].values

    signals = []
    for i in range(WARMUP, len(df) - 1):
        if atr_[i] <= 0 or np.isnan(atr_[i]) or np.isnan(ema20[i]):
            continue
        b = bias[i]
        if b == 0 or np.isnan(b):
            continue
        not_extended = abs(c[i] - ema20[i]) <= EXT_TOL_ATR * atr_[i]
        if not not_extended:
            continue

        if b == 1:
            touched = (l[i] - TOUCH_TOL_ATR * atr_[i]) <= ema20[i]
            pattern = bull_pin(o[i], h[i], l[i], c[i]) or bull_engulf(o[i - 1], c[i - 1], o[i], c[i])
            if touched and pattern:
                entry = h[i] + 1e-9
                stop = min(l[i], l[i - 1]) - STOP_BUFFER_ATR * atr_[i]
                if entry - stop > 0:
                    signals.append({"i": i, "dir": 1, "entry": entry, "stop": stop})
        elif b == -1:
            touched = (h[i] + TOUCH_TOL_ATR * atr_[i]) >= ema20[i]
            pattern = bear_pin(o[i], h[i], l[i], c[i]) or bear_engulf(o[i - 1], c[i - 1], o[i], c[i])
            if touched and pattern:
                entry = l[i] - 1e-9
                stop = max(h[i], h[i - 1]) + STOP_BUFFER_ATR * atr_[i]
                if stop - entry > 0:
                    signals.append({"i": i, "dir": -1, "entry": entry, "stop": stop})
    return df, signals


def simulate(name, df, signals):
    spread = SPREAD[name]
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    n = len(df)
    trades = []
    busy_until = -1  # index up to which we have an open/pending trade

    for sig in signals:
        i = sig["i"]
        if i <= busy_until:
            continue
        direction = sig["dir"]
        entry_level = sig["entry"]
        stop = sig["stop"]

        # --- fill window: trade-through only, never a touch ---
        fill_idx = None
        for j in range(i + 1, min(i + 1 + FILL_WINDOW, n)):
            if direction == 1 and h[j] > entry_level:
                fill_idx = j
                break
            if direction == -1 and l[j] < entry_level:
                fill_idx = j
                break
        if fill_idx is None:
            continue  # signal expired unfilled

        entry = entry_level + spread if direction == 1 else entry_level - spread
        r_unit = (entry - stop) if direction == 1 else (stop - entry)
        if r_unit <= 0:
            continue
        tp1 = entry + direction * TP1_R * r_unit
        tp2 = entry + direction * TP2_R * r_unit

        # fill bar itself: SL breach on the fill bar = loss (honest-fill rule)
        if direction == 1 and l[fill_idx] <= stop:
            trades.append({"i": i, "dir": direction, "entry": entry, "R": -1.0, "outcome": "SL@fill"})
            busy_until = fill_idx
            continue
        if direction == -1 and h[fill_idx] >= stop:
            trades.append({"i": i, "dir": direction, "entry": entry, "R": -1.0, "outcome": "SL@fill"})
            busy_until = fill_idx
            continue

        # --- phase 1: run to TP1 or SL ---
        tp1_hit = False
        exit_idx = n - 1
        result_r = None
        for j in range(fill_idx, min(fill_idx + TIME_STOP_BARS, n)):
            hit_sl = (l[j] <= stop) if direction == 1 else (h[j] >= stop)
            hit_tp1 = (h[j] >= tp1) if direction == 1 else (l[j] <= tp1)
            if hit_sl and hit_tp1:
                result_r = -1.0
                exit_idx = j
                break
            if hit_sl:
                result_r = -1.0
                exit_idx = j
                break
            if hit_tp1:
                tp1_hit = True
                exit_idx = j
                break
        if result_r is not None:
            trades.append({"i": i, "dir": direction, "entry": entry, "R": result_r, "outcome": "SL"})
            busy_until = exit_idx
            continue
        if not tp1_hit:
            # time-stop before TP1 reached
            j = min(fill_idx + TIME_STOP_BARS, n) - 1
            r = (c[j] - entry) / r_unit * direction
            trades.append({"i": i, "dir": direction, "entry": entry, "R": r, "outcome": "time-stop"})
            busy_until = j
            continue

        # --- phase 2: TP1 banked (50%), stop to BE, runner to TP2 ---
        be = entry
        runner_r = None
        runner_exit = min(fill_idx + TIME_STOP_BARS, n) - 1
        for j in range(exit_idx + 1, min(fill_idx + TIME_STOP_BARS, n)):
            hit_be = (l[j] <= be) if direction == 1 else (h[j] >= be)
            hit_tp2 = (h[j] >= tp2) if direction == 1 else (l[j] <= tp2)
            if hit_be and hit_tp2:
                runner_r = 0.0
                runner_exit = j
                break
            if hit_be:
                runner_r = 0.0
                runner_exit = j
                break
            if hit_tp2:
                runner_r = TP2_R
                runner_exit = j
                break
        if runner_r is None:
            j = runner_exit
            runner_r = (c[j] - entry) / r_unit * direction

        blended = TP1_CLOSE_FRAC * TP1_R + (1 - TP1_CLOSE_FRAC) * runner_r
        trades.append({"i": i, "dir": direction, "entry": entry, "R": blended, "outcome": f"TP1+{runner_r:.1f}R"})
        busy_until = runner_exit

    return trades


def metrics(trades):
    if not trades:
        return None
    rs = np.array([t["R"] for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    win_rate = len(wins) / len(rs) * 100
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    expectancy = rs.mean()
    equity = np.cumsum(rs)
    peak = np.maximum.accumulate(equity)
    max_dd = (peak - equity).max() if len(equity) else 0.0
    return {
        "n": len(rs), "win_rate": win_rate, "pf": pf,
        "expectancy_R": expectancy, "total_R": rs.sum(), "max_dd_R": max_dd,
    }


def run_pair(name):
    df1h = load(name)
    h4 = build_4h_trend(df1h)
    df1h, signals = generate_signals(df1h, h4)
    trades = simulate(name, df1h, signals)
    return trades, metrics(trades)


def main():
    rows = []
    for name in SPREAD:
        path = os.path.join(DATA_DIR, f"{name}.csv")
        if not os.path.exists(path):
            print(f"{name}: no data file, skipping")
            continue
        trades, m = run_pair(name)
        if m is None:
            print(f"{name:8s}  0 trades")
            continue
        rows.append({"pair": name, **m})
        print(
            f"{name:8s}  n={m['n']:3d}  WR={m['win_rate']:5.1f}%  "
            f"PF={m['pf']:5.2f}  E[R]={m['expectancy_R']:+.2f}  "
            f"totalR={m['total_R']:+6.1f}  maxDD={m['max_dd_R']:5.1f}R"
        )

    print("\n=== Ranked by expectancy (R per trade), min 5 trades ===")
    ranked = sorted(
        [r for r in rows if r["n"] >= 5],
        key=lambda r: r["expectancy_R"], reverse=True,
    )
    for r in ranked:
        print(
            f"{r['pair']:8s}  n={r['n']:3d}  WR={r['win_rate']:5.1f}%  "
            f"PF={r['pf']:5.2f}  E[R]={r['expectancy_R']:+.2f}  totalR={r['total_R']:+6.1f}"
        )
    return rows


if __name__ == "__main__":
    main()
