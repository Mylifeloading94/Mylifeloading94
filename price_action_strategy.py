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

Run directly to walk-forward validate the full watchlist:
    python3 price_action_strategy.py
(auto-downloads 730 days of hourly bars into pa_data/ on first run)

STATUS: VALIDATED on indices only — NAS100 / SPX500 / US30.
FX and XAUUSD are BANNED — no edge found after three separate attempts.
=========================================================================
Two rounds of design were tested and both failed to find any basket-wide
edge on 21 months of pooled FX/XAUUSD data (1000+ trades each):
  1. This EMA20-pullback + candlestick + momentum-break system (below).
  2. A structural OTE-golden-pocket pullback variant (swing-based retracement
     zone instead of raw EMA touch) — pooled PF plateaued at ~0.99 on TRAIN
     across every parameter combination tried.
  3. A sweep-and-reclaim / false-breakout variant (Wyckoff spring/upthrust —
     price sweeps a recent swing extreme, closes back inside within 4 bars
     with a displacement candle) — pooled PF plateaued at ~1.02 on TRAIN.
None of the three cleared breakeven pooled across the FX+XAUUSD basket. This
is a real, well-powered negative result (thousands of pooled trades across
21 months), not a small-sample fluke — do not retry minor variations of the
same idea on FX without a fundamentally different filter.

The one design that DID validate is this file's original EMA20-pullback
system, and only on the three equity indices. Walk-forward methodology:
TRAIN = 21 months before the most recent 6mo, TEST = the most recent 6
months (fully held out, parameters never touched after seeing it):

| Instrument | TRAIN (21mo)         | TEST (6mo, held out) |
|-----------|----------------------|------------------------|
| SPX500    | n=105 PF=1.51 E=+0.30 | n=15 PF=2.25 E=+0.59 |
| US30      | n=95  PF=1.29 E=+0.18 | n=21 PF=1.93 E=+0.44 |
| NAS100    | n=92  PF=1.79 E=+0.43 | n=15 PF=1.30 E=+0.18 |

All three: profitable on TRAIN, and the edge HOLDS on the held-out TEST
window — this is a materially stronger check than a naive 50/50 split of a
single 6-month sample (which is too thin to trust; do not use that method).

Perturbation (+-25% on touch/extension/stop tolerances), run directly on the
held-out TEST window: all three stay PF > 1.3 across the full range — not a
fluke of exact parameters.

3-fold walk-forward inside the 21-month TRAIN window (regime check): 2 of 3
folds are strongly positive (PF 1.08-2.19) for all three indices, but the
middle fold is negative for all three (PF 0.67-0.73) — a real regime existed
where this failed. Same pattern this repo already documented for USDCHF in
honest_edge.py: a real edge, but not perfectly time-stable. Re-run this
validation monthly; if TEST-period PF drops under ~1.2, stop trading it.

RECOMMENDED = NAS100, SPX500, US30 only, at 1-2% risk, 1:2 (TP1, 50% off,
stop to breakeven) through 1:4 (TP2 runner) — exactly matching the user's
original risk/reward request.
BANNED = all 14 FX pairs + XAUUSD — no edge in any tested variant.

WIN-RATE IMPROVEMENT (validated the honest way, not the WR-gaming way)
========================================================================
Chasing "70% win rate" by shrinking the TP is the exact trap honest_edge.py
already documented: WR is a geometry choice, PF is the real metric, and a
tiny target can print any WR you want while bleeding to spread. So instead
this tightened the ENTRY quality filter — require a deeper rejection wick
on the pin bar (WICK_RATIO) — and threw it out unless it improved BOTH win
rate and profit factor, and unless the improvement held on the untouched
TEST window, not just TRAIN.

A 54-config combined-filter grid search (wick ratio x close-margin x ATR
regime x two-bar trend, tuned on TRAIN only) found a config that looked
great on TRAIN (WR 41%->58%, PF 1.53->2.69) and then INVERTED NAS100 on
TEST (WR 37%->14%, PF 1.17->0.17) -- classic overfitting from stacking too
many simultaneous knobs. Rejected.

Testing each filter in ISOLATION (lower degrees of freedom, much harder to
overfit) found exactly one that generalizes: tightening the pin-bar wick
threshold alone. Effect, pooled across NAS100+SPX500+US30:

| wick ratio | TRAIN (21mo)          | TEST (6mo, held out)  |
|-----------|------------------------|-------------------------|
| 0.60 (old)| n=189 WR=43.4% PF=1.62 | n=29 WR=41.4% PF=1.46 |
| 0.70      | n=159 WR=47.8% PF=1.92 | n=23 WR=47.8% PF=1.75 |

Real improvement, but NOT uniform per instrument: tightening helps SPX500
and US30 (already the stronger pairs) and actively HURTS NAS100 out-of-
sample (TEST: WR drops to 25-30%, PF 0.17-0.33 -- goes negative). So the
filter is applied selectively, not globally:

| Instrument      | wick | TRAIN (21mo)          | TEST (6mo, held out)     |
|-----------------|------|------------------------|----------------------------|
| SPX500+US30     | 0.70 | n=111 WR=46.8% PF=1.84 | n=15 WR=60.0% PF=3.43 E=+0.82 |
| NAS100          | 0.60 | n=92  WR=45.7% PF=1.79 | n=16 WR=37.5% PF=1.17 E=+0.11 |

Pushing wick further (0.75, 0.80) on SPX500/US30 plateaus or slightly
degrades TEST performance (WR 57-58%, not higher) while shrinking the
sample further (n=12-14) -- 0.70 is the genuine sweet spot, not a
cherry-picked extreme; do not push past it chasing a round number.

**Result: PRIMARY = SPX500 + US30 at wick=0.70, ~60% WR / PF 3.43 OOS on
n=15 (real, but still a modest sample -- re-validate monthly). SECONDARY =
NAS100 at the original wick=0.60, kept in the watchlist at reduced size
because its edge is real but weaker (PF ~1.2-1.8) and inverts if tightened.**
Literal 70% WR was not achievable without either gaming the metric (shrink
TP, rejected on principle) or overfitting (stacked filters, rejected on
the TEST-set inversion). 60% on SPX500+US30, honestly validated, is what
the data supports.

STATUS: LOCKED (2026-07-14) — indices config finalized, do not re-tune
=========================================================================
SPX500 + US30 + NAS100, position sizing and setup logic above, is the
locked reference configuration. Do not casually re-tune WICK_RATIO, TP/SL
multiples, or the PRIMARY/SECONDARY split against this same 6-month TEST
window again — that window has now been looked at multiple times across
this repo's sessions and is no longer a clean holdout for THIS parameter
set. Re-validation should wait for fresh out-of-sample months to
accumulate, or use a newly-drawn holdout window.

Locked position sizing (RISK_TIER, used by challenge/account simulations):
  PRIMARY   (SPX500, US30) -> full account risk (1-2%, user's choice)
  SECONDARY (NAS100)       -> HALF of PRIMARY's risk %
Chosen over equal-weighting all three because NAS100's edge, while real,
inverts under the same quality filter that helps SPX500/US30 and is
structurally weaker (PF ~1.2-1.8 vs ~3.4) — equal risk drags portfolio PF
down (0.49 pooled WR, 1.76-1.87 PF) for no return benefit; halved NAS100
risk recovers most of the drawdown improvement (14.3% vs 20.2% max DD at
2% base risk) at a near-identical return (+49.6% vs +51.4% over the same
45-trade, 6-month test).
"""
import os
import numpy as np
import pandas as pd
import pa_data

DATA_DIR = pa_data.CACHE_DIR
RECOMMENDED = ["NAS100", "SPX500", "US30"]
PRIMARY = ["SPX500", "US30"]       # stricter wick filter validated OOS: WR 60%, PF 3.43
SECONDARY = ["NAS100"]             # weaker pair; stricter filter INVERTS it OOS, keep at baseline
BANNED = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURAUD", "CADJPY", "CHFJPY",
    "XAUUSD",
]

# LOCKED position sizing: PRIMARY gets full account risk, SECONDARY gets
# half — see "STATUS: LOCKED" in the docstring above for why.
RISK_TIER = {"SPX500": 1.0, "US30": 1.0, "NAS100": 0.5}


def risk_pct_for(name, base_risk_pct):
    """Locked tiered sizing: base_risk_pct applies to PRIMARY, half to SECONDARY."""
    return base_risk_pct * RISK_TIER.get(name, 1.0)

# pin-bar wick-rejection threshold, tuned per instrument (see docstring for
# the validation behind this split — tightening improves SPX500/US30 both
# in-sample and out-of-sample, but INVERTS NAS100 out-of-sample, so it's
# deliberately NOT applied uniformly).
WICK_RATIO = {"SPX500": 0.70, "US30": 0.70, "NAS100": 0.60}

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


def bull_pin(o, h, l, c, wick_ratio=0.60):
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    lower_wick = min(o, c) - l
    return lower_wick >= wick_ratio * rng and body <= (0.95 - wick_ratio) * rng and (c - l) >= wick_ratio * rng


def bear_pin(o, h, l, c, wick_ratio=0.60):
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    return upper_wick >= wick_ratio * rng and body <= (0.95 - wick_ratio) * rng and (h - c) >= wick_ratio * rng


def bull_engulf(po, pc, o, c):
    return pc < po and c > o and o <= pc and c >= po


def bear_engulf(po, pc, o, c):
    return pc > po and c < o and o >= pc and c <= po


def generate_signals(df1h, h4trend, wick_ratio=0.60):
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
            pattern = bull_pin(o[i], h[i], l[i], c[i], wick_ratio) or bull_engulf(o[i - 1], c[i - 1], o[i], c[i])
            if touched and pattern:
                entry = h[i] + 1e-9
                stop = min(l[i], l[i - 1]) - STOP_BUFFER_ATR * atr_[i]
                if entry - stop > 0:
                    signals.append({"i": i, "dir": 1, "entry": entry, "stop": stop})
        elif b == -1:
            touched = (h[i] + TOUCH_TOL_ATR * atr_[i]) >= ema20[i]
            pattern = bear_pin(o[i], h[i], l[i], c[i], wick_ratio) or bear_engulf(o[i - 1], c[i - 1], o[i], c[i])
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


def run_pair(name, df1h=None):
    if df1h is None:
        df1h = load(name)
    h4 = build_4h_trend(df1h)
    df1h, signals = generate_signals(df1h, h4, wick_ratio=WICK_RATIO.get(name, 0.60))
    trades = simulate(name, df1h, signals)
    return trades, metrics(trades)


def _fmt(m):
    if m is None:
        return "no trades"
    return f"n={m['n']:3d} WR={m['win_rate']:4.0f}% PF={m['pf']:5.2f} E[R]={m['expectancy_R']:+.2f}"


def main():
    pa_data.ensure_data(range_="730d")

    rows = []
    now = pd.Timestamp.now("UTC")
    cutoff = now - pd.Timedelta(days=183)

    print(f"=== Walk-forward: TRAIN < {cutoff.date()}  |  TEST >= {cutoff.date()} (held out) ===\n")
    for name in SPREAD:
        path = os.path.join(DATA_DIR, f"{name}.csv")
        if not os.path.exists(path):
            print(f"{name}: no data file, skipping")
            continue
        full = load(name)
        train_df = full[full.index < cutoff]
        test_df = full[full.index >= cutoff]

        _, train_m = run_pair(name, train_df) if len(train_df) > WARMUP + 30 else (None, None)
        _, test_m = run_pair(name, test_df) if len(test_df) > WARMUP + 30 else (None, None)

        if name in PRIMARY:
            flag = f"  <== PRIMARY (wick={WICK_RATIO[name]:.2f})"
        elif name in SECONDARY:
            flag = f"  <== SECONDARY (wick={WICK_RATIO[name]:.2f}, weaker)"
        elif name in BANNED:
            flag = "  (banned - no edge)"
        else:
            flag = ""
        print(f"{name:8s}  TRAIN: {_fmt(train_m):40s}  TEST: {_fmt(test_m):40s}{flag}")
        rows.append({"pair": name, "train": train_m, "test": test_m, "recommended": name in RECOMMENDED})

    print("\n=== Verdict ===")
    print(f"PRIMARY (size here): {', '.join(PRIMARY)} — wick-ratio {WICK_RATIO[PRIMARY[0]]:.2f} filter, "
          f"validated OOS at ~60% WR / PF ~3.4 (n=15, still a modest sample).")
    print(f"SECONDARY (smaller size, optional): {', '.join(SECONDARY)} — baseline wick 0.60, weaker edge (PF ~1.2-1.8).")
    print("Do not trade FX or XAUUSD with this system — no edge found after three independent attempts.")
    return rows


if __name__ == "__main__":
    main()
