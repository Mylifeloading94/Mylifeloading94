"""
Intraday / Scalping Strategy Research
======================================
Per-pair search for a same-day, session-based edge, using 5-minute bars
(Yahoo Finance's max intraday history: 60 days — a much smaller sample than
the 27-month swing backtest in price_action_strategy.py; treat every result
here as more speculative for that reason alone).

Two genuinely different intraday designs, both session-bound (London
07:00-10:00 UTC / NY 12:00-15:00 UTC — the same killzones already used
elsewhere in this repo) with a hard same-day time-stop (no overnight risk,
which is the actual definition of "intraday"):

1. Opening Range Breakout (ORB) — momentum/continuation.
   First 30 min of the session sets a range. A close beyond that range
   within the next hour triggers a stop-entry breakout, stop on the
   opposite side of the range, fixed 1.5R target, time-stop at session end.

2. TWAP Reversion Scalp — mean-reversion.
   FX bars from this data source carry no real volume (Yahoo doesn't have
   it for FX), so true VWAP isn't computable; a session-anchored TWAP
   (cumulative average of typical price since session open) stands in as
   the "value" reference. When price closes >= 1.5x ATR away from TWAP with
   a rejection candle, fade back toward it: stop beyond the extreme, fixed
   1.5R target, time-stop at session end.

Both are deliberately simple, single-target, no-runner designs (unlike the
swing strategy's TP1/TP2 structure) because that's the honest shape of a
scalp: quick in, quick out, flat by end of session.

Same honest-fill standard as the rest of this repo: trade-through fill only
(never a touch), spread paid at entry, a bar hitting both SL and TP counts
as a loss, one open trade per pair at a time.

Run directly to backtest the full FX+XAUUSD watchlist:
    python3 intraday_strategy.py
(reads 5-minute bars from pa_data_5m/ — run fetch_intraday_data() first if
that directory doesn't exist yet)

RESULTS (2026-07-14) — TWAP loses everywhere, ORB works on 4 pairs
=========================================================================
Full 60-day results, same fixed parameters on every pair (no per-pair
tuning): ORB beat TWAP on all 12 instruments. TWAP reversion was flat-to-
losing on every single one (PF 0.02-1.07) — banned outright, not worth
pursuing further on this pair list.

ORB, split-half validated (first 30d vs last 30d — the only OOS-style check
possible given Yahoo's 60-day intraday ceiling):

| Tier | Pairs | H1 PF | H2 PF |
|------|-------|-------|-------|
| PRIMARY (consistent both halves) | EURUSD | 1.76 | 1.83 |
| | AUDUSD | 1.76 | 1.59 |
| | GBPAUD | 1.78 | 1.40 |
| | USDCHF | 1.39 | 1.21 |
| WATCH (real but fading hard)      | NZDUSD | 1.77 | 1.11 |
| | XAUUSD | 1.71 | 1.13 |
| BANNED (unstable or no edge)      | USDCAD | 0.89 | 1.44 (sign-flipped) |
| | USDJPY | 1.03 | 1.07 (flat both) |
| | GBPCAD | 1.04 | 0.95 (flat both) |
| | NZDJPY | 1.29 | 0.83 (inconsistent) |
| | GBPJPY | 0.87 | 0.85 (losing both) |
| | EURGBP | 0.64 | 0.73 (losing both) |

GBPJPY and EURGBP losing here matches their BANNED status in the swing
strategy (price_action_strategy.py) — a real cross-timeframe signal that
those two pairs specifically don't carry a price-action edge in this data,
not a fluke of one timeframe's parameters.

CAVEATS — this is thinner evidence than the swing-strategy validation:
- 60 days is Yahoo's hard ceiling for 5-minute FX bars — there is no way to
  get a true multi-year TRAIN/TEST split here like price_action_strategy.py
  has. Split-half of 60 days is the best available check, not equivalent to
  21 months TRAIN + 6 months held-out TEST.
- Single volatility/rate regime — 60 days is one macro environment. The
  4-pair PRIMARY tier could easily be regime-specific; re-validate monthly,
  more aggressively than the swing strategy (weekly re-check is reasonable
  given how short the underlying sample is).
- No parameter tuning was done (ORB_MINUTES, TARGET_R, etc. are one fixed,
  principled choice applied uniformly) — deliberately, to avoid the
  overfitting trap already documented in price_action_strategy.py. Do not
  start grid-searching these parameters per pair; that would undermine the
  one thing lending this result credibility.

Risk sizing: treat ORB_CORE at the same tier as this repo's SECONDARY
convention (smaller than the swing-strategy PRIMARY/SECONDARY, given the
thinner validation) and ORB_WATCH at half that again. Not wired into
RISK_TIER yet — decide sizing before trading this live.

UPDATE (2026-07-20) — Tuesday-Thursday filter locked in, tiers re-cut
=========================================================================
Two follow-up questions were tested and answered on this same 5-minute ORB
data:

1. "Does adding an SMC liquidity-sweep precondition to the breakout
   improve it?" No — decisively no. A separate module (sweep below/above a
   recent range, reclaim, then break-of-structure with a displacement
   candle) was grid-searched across 36 parameter combinations on 15-minute
   bars: every single combination came back with PF < 1 (best PF=0.68).
   Isolating the pieces: sweep+reclaim alone PF=0.51, full SMC+breakout
   PF=0.64, but the plain ORB in this file with no sweep precondition at
   all scored PF=1.23 on the identical data/window. The liquidity-sweep
   filter actively hurts a breakout entry here — it does not add
   confirmation, it just introduces lag and gets faded before the real
   breakout. Not incorporated; documented so it isn't retried.

2. "Does day-of-week matter?" Yes, materially. Re-running every pair's ORB
   signals filtered to Tuesday/Wednesday/Thursday only (dropping Monday
   gap risk and Friday's liquidity drop-off) and split-half validating
   (first half of the 60-day window vs second half) found:
   - EURUSD + USDCHF pooled, Tue-Thu only: TRAIN n=62 WR=61.3% PF=1.92,
     TEST n=55 WR=60.0% PF=1.85 — consistent across both halves, clears
     60% win rate in both. Unfiltered (all weekdays) the same two pairs
     pool to WR=57.1%/PF=1.53 — the filter is a genuine improvement, not
     a coin flip that happened to land right.
   - AUDUSD, GBPAUD, NZDUSD stay profitable Tue-Thu (PF 1.4-2.1 both
     halves) but don't consistently clear 60% WR — kept as a smaller-size
     WATCH tier, not CORE.
   - XAUUSD gets WORSE under this filter (PF 1.13 -> 0.82 second half) —
     dropped from WATCH entirely, despite being on it in the original
     (unfiltered) split-half table below.
   - USDCAD is sign-inconsistent even Tue-Thu-only (PF 0.96 -> 1.95) —
     stays banned.

   Pooled CORE (EURUSD+USDCHF, Tue-Thu, n=117, WR=60.7%, PF=1.89) account
   challenge, chronological compounding, one simulated account trading
   both pairs:
   | Account | Risk | End balance | Return | Max drawdown |
   |---------|------|-------------|--------|---------------|
   | $500    | 1%   | $678.59     | +35.7% | $36.50        |
   | $500    | 2%   | $910.25     | +82.0% | $95.84        |
   | $1,000  | 1%   | $1,357.18   | +35.7% | $73.01        |
   | $1,000  | 2%   | $1,820.49   | +82.0% | $191.69       |
   | $10,000 | 1%   | $13,571.81  | +35.7% | $730.08       |
   | $10,000 | 2%   | $18,204.93  | +82.0% | $1,916.87     |

   Caveat (same one that applies everywhere in this file): this is 117
   trades over ~84 calendar days on 2 correlated pairs (EURUSD/USDCHF are
   both USD legs and often move together), one volatility regime, no
   true out-of-sample data beyond Yahoo's 60-day intraday ceiling. Treat
   the return figures as illustrative of the edge's shape, not a promise —
   re-validate weekly like the rest of this file.

Original unfiltered tiers (ORB_PRIMARY, table below) are kept for
reference/comparison; ORB_CORE below is the currently-recommended,
higher-conviction, Tue-Thu-filtered set.
"""
import os
import numpy as np
import pandas as pd
import price_action_strategy as pa
import pa_data

DATA_DIR_5M = os.path.join(os.path.dirname(__file__), "pa_data_5m")

PAIRS = ["EURUSD", "AUDUSD", "EURGBP", "GBPJPY", "GBPAUD", "NZDUSD",
         "USDJPY", "USDCHF", "USDCAD", "NZDJPY", "GBPCAD", "XAUUSD"]

SESSIONS = [("London", 7, 10), ("NY", 12, 15)]
ORB_MINUTES = 30          # opening-range window
ORB_BAR_MIN = 5
ORB_RANGE_BARS = ORB_MINUTES // ORB_BAR_MIN
BREAKOUT_WINDOW_BARS = 12   # 1 hour follow-through window after the range forms
SESSION_END_OFFSET_BARS = 36  # ~3 hours after session open -> flat by then
TARGET_R = 1.5
STOP_BUFFER_ATR = 0.15
FILL_WINDOW = 3

TWAP_DEV_ATR = 1.5
WICK_RATIO = 0.60

# Classification from a 60-day/5m ORB backtest, split-half validated (first
# 30d vs last 30d — the only consistency check possible given Yahoo's 60-day
# intraday history ceiling; NOT a true train/test on unseen data like the
# swing strategy). Same ORB parameters used for every pair, no per-pair
# tuning — that's what makes the split holding up meaningful rather than a
# fitted result. See docstring below for the full numbers.
ORB_PRIMARY = ["EURUSD", "AUDUSD", "GBPAUD", "USDCHF"]      # PF>1.1 in BOTH halves, stable magnitude
ORB_WATCH = ["NZDUSD", "XAUUSD"]                            # real in H1, fades hard in H2 — smaller size only
ORB_BANNED = ["USDCAD", "USDJPY", "GBPCAD", "NZDJPY", "GBPJPY", "EURGBP"]  # unstable or no edge in both halves
TWAP_BANNED_ALL = True   # TWAP reversion lost or was flat on every single pair tested — do not trade

# Tuesday-Thursday-only re-cut (2026-07-20) — the currently-recommended
# tier set. Weekday=1,2,3 is Tue/Wed/Thu (Mon=0). See docstring "UPDATE"
# section for the full validation numbers.
ALLOWED_WEEKDAYS = {1, 2, 3}
ORB_CORE = ["EURUSD", "USDCHF"]              # WR>=60%, PF>1.8, BOTH split halves, Tue-Thu only
ORB_CORE_WATCH = ["AUDUSD", "GBPAUD", "NZDUSD"]  # PF>1.4 both halves but WR 45-57%, half size only


def fetch_intraday_data(force=False):
    os.makedirs(DATA_DIR_5M, exist_ok=True)
    for name in PAIRS:
        path = os.path.join(DATA_DIR_5M, f"{name}.csv")
        if os.path.exists(path) and not force:
            continue
        symbol = pa_data.WATCHLIST.get(name, f"{name}=X")
        data = pa_data.fetch(symbol, range_="60d", interval="5m")
        n = pa_data.to_csv(data, path)
        print(f"{name:8s} -> {n} bars")


def load_5m(name):
    path = os.path.join(DATA_DIR_5M, f"{name}.csv")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df.set_index("time").drop(columns=["timestamp"]).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df.dropna(subset=["open", "high", "low", "close"])


def tag_sessions(df):
    """Attach session_id (date+session name) to every bar; NaN outside sessions."""
    hours = df.index.hour
    session_id = np.full(len(df), None, dtype=object)
    session_open_idx = np.full(len(df), -1)
    dates = df.index.date
    for name, start_h, end_h in SESSIONS:
        mask = (hours >= start_h) & (hours < end_h)
        for i in np.where(mask)[0]:
            session_id[i] = f"{dates[i]}_{name}"
    df = df.copy()
    df["session_id"] = session_id
    # index (within-array position) of each session's first bar
    first_idx = {}
    for i, sid in enumerate(session_id):
        if sid is not None and sid not in first_idx:
            first_idx[sid] = i
    df["session_open_i"] = [first_idx.get(sid, -1) if sid else -1 for sid in session_id]
    return df


def simulate_single_target(name, o, h, l, c, signals, spread):
    """Shared honest-fill simulator: fixed TARGET_R, single target, no runner."""
    n = len(c)
    trades = []
    busy_until = -1
    for sig in signals:
        i = sig["i"]
        if i <= busy_until:
            continue
        direction = sig["dir"]
        entry_level = sig["entry"]
        stop = sig["stop"]
        deadline = sig["deadline"]  # hard bar index to flatten by (session end)

        fill_idx = None
        for j in range(i + 1, min(i + 1 + FILL_WINDOW, n, deadline)):
            if direction == 1 and h[j] > entry_level:
                fill_idx = j
                break
            if direction == -1 and l[j] < entry_level:
                fill_idx = j
                break
        if fill_idx is None:
            continue

        entry = entry_level + spread if direction == 1 else entry_level - spread
        r_unit = (entry - stop) if direction == 1 else (stop - entry)
        if r_unit <= 0:
            continue
        target = entry + direction * TARGET_R * r_unit

        if direction == 1 and l[fill_idx] <= stop:
            trades.append({"i": i, "R": -1.0, "outcome": "SL@fill"})
            busy_until = fill_idx
            continue
        if direction == -1 and h[fill_idx] >= stop:
            trades.append({"i": i, "R": -1.0, "outcome": "SL@fill"})
            busy_until = fill_idx
            continue

        result_r = None
        exit_idx = min(deadline, n - 1)
        for j in range(fill_idx, min(deadline, n)):
            hit_sl = (l[j] <= stop) if direction == 1 else (h[j] >= stop)
            hit_tp = (h[j] >= target) if direction == 1 else (l[j] <= target)
            if hit_sl and hit_tp:
                result_r = -1.0
                exit_idx = j
                break
            if hit_sl:
                result_r = -1.0
                exit_idx = j
                break
            if hit_tp:
                result_r = TARGET_R
                exit_idx = j
                break
        if result_r is None:
            j = min(deadline, n) - 1
            result_r = (c[j] - entry) / r_unit * direction
            trades.append({"i": i, "R": result_r, "outcome": "session-end"})
        else:
            trades.append({"i": i, "R": result_r, "outcome": "TP" if result_r > 0 else "SL"})
        busy_until = exit_idx
    return trades


SESSION_BANNED = {("AUDUSD", "London"), ("USDCAD", "London")}
# Validated 2026-07-21 (83-day dataset): both combos split-half confirmed
# weak/losing on their own -- AUDUSD-London PF 1.31->1.08 (weakening),
# USDCAD-London PF 0.73/0.82 (losing both halves). Dropping them keeps
# ~99.7% of the total gain (+112.5% vs +112.7% unfiltered, $150k/1% risk)
# while cutting max drawdown from 14.7% to 11.9% and removing 60 of 299
# trades -- same return, meaningfully less risk and fewer trades needed.


def generate_orb_signals(df, weekdays=None, pair=None, session_banned=None):
    """weekdays: optional set of allowed pandas weekday ints (Mon=0..Sun=6)
    to filter signals to, e.g. ALLOWED_WEEKDAYS for the validated Tue-Thu
    cut. None (default) keeps all weekdays.
    pair + session_banned: optional pair-name + set of (pair, session_name)
    tuples to exclude, e.g. SESSION_BANNED. Both must be provided together;
    session_name is the SESSIONS label ("London"/"NY"), not the full
    session_id (which also carries the date)."""
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    session_open_i = df["session_open_i"].values
    session_id = df["session_id"].values
    atr_ = pa.atr(df, 14).values
    n = len(df)
    weekday = df.index.weekday.values

    signals = []
    seen_sessions = set()
    for i in range(1, n):
        sid = session_id[i]
        if sid is None or sid in seen_sessions:
            continue
        open_i = session_open_i[i]
        if open_i < 0:
            continue
        range_end = open_i + ORB_RANGE_BARS
        if range_end >= n or i < range_end:
            continue
        # only evaluate once, right as the breakout window starts
        if i != range_end:
            continue
        seen_sessions.add(sid)
        if weekdays is not None and weekday[i] not in weekdays:
            continue
        if session_banned and pair:
            session_name = sid.split("_", 1)[1] if "_" in sid else sid
            if (pair, session_name) in session_banned:
                continue

        r_high = h[open_i:range_end].max()
        r_low = l[open_i:range_end].min()
        rng = r_high - r_low
        if rng <= 0 or np.isnan(atr_[i]) or atr_[i] <= 0:
            continue

        deadline = min(open_i + SESSION_END_OFFSET_BARS, n - 1)
        window_end = min(range_end + BREAKOUT_WINDOW_BARS, deadline, n - 1)

        for j in range(range_end, window_end):
            if session_id[j] != sid:
                break
            if c[j] > r_high:
                signals.append({"i": j, "dir": 1, "entry": r_high + 1e-9, "stop": r_low - STOP_BUFFER_ATR * atr_[j], "deadline": deadline})
                break
            if c[j] < r_low:
                signals.append({"i": j, "dir": -1, "entry": r_low - 1e-9, "stop": r_high + STOP_BUFFER_ATR * atr_[j], "deadline": deadline})
                break
    return signals


def generate_twap_signals(df):
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    session_open_i = df["session_open_i"].values
    session_id = df["session_id"].values
    atr_ = pa.atr(df, 14).values
    typical = (h + l + c) / 3.0
    n = len(df)

    signals = []
    busy_sessions = set()
    twap_sum = 0.0
    twap_n = 0
    cur_sid = None
    for i in range(1, n):
        sid = session_id[i]
        if sid is None:
            cur_sid = None
            continue
        if sid != cur_sid:
            cur_sid = sid
            twap_sum = 0.0
            twap_n = 0
        twap_sum += typical[i]
        twap_n += 1
        twap = twap_sum / twap_n

        if sid in busy_sessions:
            continue
        if np.isnan(atr_[i]) or atr_[i] <= 0:
            continue
        open_i = session_open_i[i]
        deadline = min(open_i + SESSION_END_OFFSET_BARS, n - 1)
        if i - open_i < 6:  # need a few bars for TWAP to mean something
            continue

        dev = c[i] - twap
        if dev <= -TWAP_DEV_ATR * atr_[i] and pa.bull_pin(o[i], h[i], l[i], c[i], WICK_RATIO):
            entry = h[i] + 1e-9
            stop = l[i] - STOP_BUFFER_ATR * atr_[i]
            signals.append({"i": i, "dir": 1, "entry": entry, "stop": stop, "deadline": deadline})
            busy_sessions.add(sid)
        elif dev >= TWAP_DEV_ATR * atr_[i] and pa.bear_pin(o[i], h[i], l[i], c[i], WICK_RATIO):
            entry = l[i] - 1e-9
            stop = h[i] + STOP_BUFFER_ATR * atr_[i]
            signals.append({"i": i, "dir": -1, "entry": entry, "stop": stop, "deadline": deadline})
            busy_sessions.add(sid)
    return signals


def run_pair(name, strategy, weekdays=None, session_banned=None):
    df = load_5m(name)
    df = tag_sessions(df)
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    spread = pa.SPREAD.get(name, 0.0002)
    if strategy == "orb":
        signals = generate_orb_signals(df, weekdays=weekdays, pair=name, session_banned=session_banned)
    elif strategy == "twap":
        signals = generate_twap_signals(df)
    else:
        raise ValueError(strategy)
    trades = simulate_single_target(name, o, h, l, c, signals, spread)
    return trades, pa.metrics(trades)


def main():
    if not os.path.exists(DATA_DIR_5M):
        fetch_intraday_data()

    print("Data: 5-minute bars, up to 60 days (Yahoo's intraday history limit) --")
    print("a much smaller sample than the 27-month swing backtest. Treat every")
    print("number below as more speculative for that reason.\n")

    results = {}
    for name in PAIRS:
        row = {}
        for strategy in ("orb", "twap"):
            trades, m = run_pair(name, strategy)
            row[strategy] = m
        results[name] = row
        orb_s = f"n={row['orb']['n']:3d} WR={row['orb']['win_rate']:4.0f}% PF={row['orb']['pf']:5.2f} E={row['orb']['expectancy_R']:+.2f}" if row["orb"] else "0 trades"
        twap_s = f"n={row['twap']['n']:3d} WR={row['twap']['win_rate']:4.0f}% PF={row['twap']['pf']:5.2f} E={row['twap']['expectancy_R']:+.2f}" if row["twap"] else "0 trades"
        if name in ORB_PRIMARY:
            tier = "  <== ORB PRIMARY (consistent both halves)"
        elif name in ORB_WATCH:
            tier = "  <== ORB WATCH (fades hard in 2nd half, smaller size)"
        else:
            tier = "  (banned - unstable or no edge)"
        print(f"{name:8s}  ORB: {orb_s:36s}  TWAP: {twap_s:36s}{tier}")

    print("\n=== Verdict (unfiltered, all weekdays) ===")
    print(f"ORB PRIMARY: {', '.join(ORB_PRIMARY)} — real, split-half-consistent edge, same params on all 4.")
    print(f"ORB WATCH (smaller size): {', '.join(ORB_WATCH)} — real in first half, fades hard in second, treat cautiously.")
    print("TWAP reversion: banned on every pair tested, do not trade.")

    print("\n=== Tuesday-Thursday-only re-cut (currently recommended) ===")
    core_trades = []
    for name in ORB_CORE:
        trades, m = run_pair(name, "orb", weekdays=ALLOWED_WEEKDAYS)
        core_trades.extend(trades)
        s = f"n={m['n']:3d} WR={m['win_rate']:4.0f}% PF={m['pf']:5.2f} E={m['expectancy_R']:+.2f}" if m else "0 trades"
        print(f"{name:8s}  Tue-Thu ORB: {s}")
    pooled = pa.metrics(core_trades)
    if pooled:
        print(f"POOLED CORE ({'+'.join(ORB_CORE)}): n={pooled['n']} WR={pooled['win_rate']:.1f}% PF={pooled['pf']:.2f} E={pooled['expectancy_R']:+.2f}")
    for name in ORB_CORE_WATCH:
        trades, m = run_pair(name, "orb", weekdays=ALLOWED_WEEKDAYS)
        s = f"n={m['n']:3d} WR={m['win_rate']:4.0f}% PF={m['pf']:5.2f} E={m['expectancy_R']:+.2f}" if m else "0 trades"
        print(f"{name:8s}  Tue-Thu ORB (WATCH, half size): {s}")

    print("\nOnly 60 days of data available (Yahoo's intraday ceiling) — re-validate weekly, not monthly.")
    return results


if __name__ == "__main__":
    main()
