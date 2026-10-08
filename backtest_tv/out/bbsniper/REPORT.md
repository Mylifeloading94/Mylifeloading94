# BB SNIPER — backtest report

Generated 2026-10-08 21:30 UTC. TradingView OANDA bars, 17 instruments. Engine: `bbsniper/` (15 modules), honest fills, no lookahead, confirmed higher-timeframe bars only.

## 0. Read this first — what the data allows

The TradingView connector returns at most **5,000 bars per request (newest only)** and has no 3-minute interval. A 90-day test on 1M/3M/5M/15M is therefore **not possible** with this feed. Each timeframe is tested on the full window that exists:

| Exec TF | Setup TF / Bias TF | Window (UTC) | ≈ Trading days | Candidate setups (any score) |
|---|---|---|---:|---:|
| 1M | 5M / 15M | 2026-10-05 13:42 → 2026-10-08 21:00 | 2.4 | 1019 |
| 3M | 5M / 15M | 2026-10-05 22:06 → 2026-10-08 20:57 | 2.1 | 288 |
| 5M | 5M / 15M | 2026-09-16 09:25 → 2026-10-08 21:00 | 16.1 | 919 |
| 15M | 15M / 1H | 2026-07-31 05:15 → 2026-10-08 21:00 | 49.8 | 939 |

3M bars are built from 1M. Walk-forward split per timeframe: first 4/6 = training (the spec's 60/90), next 1/6 = validation, last 1/6 = out-of-sample. Spreads are static estimates (no historical spread feed); the news filter is **disabled** in the backtest because no historical economic-calendar data is available (it is not simulated with invented data).

## 1. Timeframe comparison (default rules: score ≥ 8, BB 20/2.0, SL buffer 0.2 ATR, min RR 1.5, London+NY)

Pair-level trades pooled across all 17 instruments (one position per pair, 3 trades / 3 losses per pair per day).

| TF | Trades | Win rate | PF | Avg R | Net R | Max DD (R) | t-stat | Trades/day (all pairs) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1M | 6 | 16.7% | 0.08 | -0.62 | -3.7 | 3.7 | -2.76 | 2.54 |
| 3M | 10 | 30.0% | 0.14 | -0.60 | -6.0 | 6.3 | -3.10 | 4.74 |
| 5M | 36 | 36.1% | 0.62 | -0.25 | -8.8 | 9.4 | -1.37 | 2.24 |
| 15M | 57 | 40.4% | 0.76 | -0.15 | -8.3 | 13.9 | -0.98 | 1.15 |

**By setup type**

| TF | Setup | Trades | Win rate | PF | Avg R |
|---|---|---:|---:|---:|---:|
| 1M | BB Liquidity Reversal | 2 | 0.0% | 0.00 | -0.53 |
| 1M | BB Trend Continuation | 3 | 33.3% | 0.17 | -0.55 |
| 1M | BB Squeeze Breakout | 1 | 0.0% | 0.00 | -1.00 |
| 3M | BB Liquidity Reversal | 2 | 0.0% | 0.00 | -1.00 |
| 3M | BB Trend Continuation | 2 | 0.0% | 0.00 | -1.00 |
| 3M | BB Squeeze Breakout | 6 | 50.0% | 0.34 | -0.33 |
| 5M | BB Liquidity Reversal | 5 | 20.0% | 0.38 | -0.50 |
| 5M | BB Trend Continuation | 6 | 66.7% | 1.88 | +0.29 |
| 5M | BB Squeeze Breakout | 25 | 32.0% | 0.52 | -0.32 |
| 15M | BB Liquidity Reversal | 7 | 85.7% | 6.86 | +0.84 |
| 15M | BB Trend Continuation | 12 | 58.3% | 1.06 | +0.02 |
| 15M | BB Squeeze Breakout | 38 | 26.3% | 0.49 | -0.38 |

**By session**

| TF | Session | Trades | Win rate | PF | Avg R |
|---|---|---:|---:|---:|---:|
| 1M | London | 3 | 33.3% | 0.32 | -0.24 |
| 1M | Overlap | 3 | 0.0% | 0.00 | -1.00 |
| 3M | London | 4 | 50.0% | 0.34 | -0.33 |
| 3M | Overlap | 5 | 20.0% | 0.08 | -0.73 |
| 3M | NY | 1 | 0.0% | 0.00 | -1.00 |
| 5M | London | 13 | 61.5% | 1.57 | +0.22 |
| 5M | Overlap | 19 | 26.3% | 0.45 | -0.40 |
| 5M | NY | 4 | 0.0% | 0.00 | -1.00 |
| 15M | London | 29 | 37.9% | 0.79 | -0.13 |
| 15M | Overlap | 16 | 31.2% | 0.53 | -0.32 |
| 15M | NY | 12 | 58.3% | 1.14 | +0.06 |

## 2. Walk-forward optimisation (24 configs, chosen on training only)

Grid: min_score ∈ [7, 8, 9], bb_dev ∈ [2.0, 2.2], sl_buf_atr ∈ [0.15, 0.3], min_rr ∈ [1.5, 2.0]. Selection = best training expectancy with ≥ 20 trades.

| TF | Chosen params | Train n / WR / PF / avgR | Validation n / WR / PF / avgR | Out-of-sample n / WR / PF / avgR | Default rules OOS |
|---|---|---|---|---|---|
| 1M | min_score=7, bb_dev=2.2, sl_buf_atr=0.15, min_rr=1.5 ⚠ <20 train trades | 8 / 12.5% / 0.05 / -0.83 | 0 trades | 3 / 0.0% / 0.00 / -0.69 | 3 / 0.0% / 0.00 / -0.68 |
| 3M | min_score=7, bb_dev=2.0, sl_buf_atr=0.15, min_rr=1.5 ⚠ <20 train trades | 9 / 44.4% / 0.56 / -0.24 | 0 trades | 3 / 0.0% / 0.00 / -1.00 | 3 / 0.0% / 0.00 / -1.00 |
| 5M | min_score=7, bb_dev=2.0, sl_buf_atr=0.3, min_rr=2.0 | 20 / 45.0% / 0.93 / -0.04 | 4 / 75.0% / 3.54 / +0.64 | 5 / 20.0% / 0.10 / -0.57 | 7 / 28.6% / 0.40 / -0.43 |
| 15M | min_score=7, bb_dev=2.2, sl_buf_atr=0.3, min_rr=1.5 | 34 / 52.9% / 1.49 / +0.23 | 18 / 44.4% / 0.86 / -0.08 | 10 / 40.0% / 0.78 / -0.13 | 11 / 36.4% / 0.68 / -0.20 |

## 3. BEST OVERALL CONFIGURATION

No pair/timeframe produced at least 10 trades under the default rules — no configuration qualifies.

## 4. TOP 10 PAIRS (each pair at its best timeframe)

| Rank | Pair | TF | Grade | Trades | Win Rate | PF | ROI ($1k@1%) | Max DD | Avg R | Sample |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | AUDJPY | 5M | C | 4 | 75.0% | 3.25 | 2.2% | 1.0R | +0.56 | ⚠ n<10 |
| 2 | CADJPY | 15M | C | 3 | 66.7% | 2.99 | 1.9% | 1.0R | +0.66 | ⚠ n<10 |
| 3 | XAUUSD | 15M | C | 7 | 57.1% | 1.59 | 1.9% | 2.0R | +0.25 | ⚠ n<10 |
| 4 | EURUSD | 15M | C | 4 | 75.0% | 2.72 | 1.6% | 1.0R | +0.43 | ⚠ n<10 |
| 5 | EURAUD | 5M | C | 1 | 100.0% | 99.00 | 1.5% | 0.0R | +1.71 | ⚠ n<10 |
| 6 | EURCAD | 5M | C | 1 | 100.0% | 99.00 | 1.4% | 0.0R | +1.54 | ⚠ n<10 |
| 7 | GBPUSD | 15M | C | 5 | 40.0% | 1.20 | 0.6% | 2.0R | +0.12 | ⚠ n<10 |
| 8 | EURJPY | 15M | C | 4 | 50.0% | 1.19 | 0.4% | 2.0R | +0.10 | ⚠ n<10 |
| 9 | USDCHF | 5M | F | 1 | 0.0% | 0.00 | -1.0% | 1.0R | -1.00 | ⚠ n<10 |
| 10 | USDCAD | 5M | F | 1 | 0.0% | 0.00 | -1.0% | 1.0R | -1.00 | ⚠ n<10 |

> ⚠ No pair reached 10 trades on any timeframe, so this order is provisional (small samples are ordered by net R, not win rate). None of these rows is evidence of an edge.

Ranking = weighted rank-sum of PF (6), win rate (5), expectancy (4), drawdown (3), net R (2), % positive weeks (1); rows with < 10 trades rank last. Grades need ≥ 30 trades to exceed C.

**All pairs — best timeframe, setup, session, score threshold, risk model**

| Pair | Best TF | Grade | Trades | WR | PF | Avg R | Best setup | Best session | Best score ≥ | Risk |
|---|---|---|---:|---:|---:|---:|---|---|---|---|
| EURUSD | 15M | C | 4 | 75.0% | 2.72 | +0.43 | BB Squeeze Breakout (n=3) | London (n=3) | 7 | 1% |
| GBPUSD | 15M | C | 5 | 40.0% | 1.20 | +0.12 | BB Squeeze Breakout (n=3) | London (n=3) | 7 | 1% |
| USDJPY | 15M | F | 8 | 37.5% | 0.65 | -0.22 | BB Squeeze Breakout (n=5) | London (n=3) | 7 | 1% |
| USDCHF | 5M | F | 1 | 0.0% | 0.00 | -1.00 | n<3 | n<3 | n<5 | 1% |
| AUDUSD | — | F | 0 | — | — | — | — | — | — | — |
| NZDUSD | 15M | F | 4 | 0.0% | 0.00 | -1.00 | BB Squeeze Breakout (n=3) | n<3 | n<5 | 1% |
| USDCAD | 5M | F | 1 | 0.0% | 0.00 | -1.00 | n<3 | n<3 | n<5 | 1% |
| EURJPY | 15M | C | 4 | 50.0% | 1.19 | +0.10 | n<3 | n<3 | 7 | 1% |
| GBPJPY | 15M | F | 1 | 0.0% | 0.00 | -1.00 | n<3 | n<3 | n<5 | 1% |
| EURGBP | — | F | 0 | — | — | — | — | — | — | — |
| EURAUD | 5M | C | 1 | 100.0% | 99.00 | +1.71 | n<3 | n<3 | n<5 | 1% |
| EURCAD | 5M | C | 1 | 100.0% | 99.00 | +1.54 | n<3 | n<3 | n<5 | 1% |
| GBPCAD | 15M | F | 1 | 0.0% | 0.00 | -1.00 | n<3 | n<3 | n<5 | 1% |
| GBPAUD | 15M | F | 3 | 33.3% | 0.17 | -0.55 | n<3 | London (n=3) | n<5 | 1% |
| AUDJPY | 5M | C | 4 | 75.0% | 3.25 | +0.56 | n<3 | London (n=3) | 7 | 1% |
| CADJPY | 15M | C | 3 | 66.7% | 2.99 | +0.66 | BB Squeeze Breakout (n=3) | n<3 | 7 | 1% |
| XAUUSD | 15M | C | 7 | 57.1% | 1.59 | +0.25 | BB Squeeze Breakout (n=5) | London (n=4) | 7 | 1% |

## 5. TOP 10 SETUPS (pair + TF + setup + session, ≥ 5 trades to rank)

| Rank | Pair | TF | Setup | Session | Trades | WR | PF | Avg R |
|---:|---|---|---|---|---:|---:|---:|---:|
| — | No pair + TF + setup + session combination reached 5 trades. | | | | | | | |

## 6. $500 RESULTS (portfolio of all 17 pairs, compounding, real lot sizing)

| TF | Risk | Trades | Win rate | Net profit | ROI | Max DD | PF | Avg/day $ | Best day | Worst day | Skipped (lot < 0.01) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1M | 1% | 6 | 16.7% | $-13.18 | -2.6% | 2.6% | 0.08 | $-3.29 | $1.11 | $-7.03 | 1 |
| 1M | 2% | 6 | 16.7% | $-29.53 | -5.9% | 5.9% | 0.07 | $-7.38 | $2.22 | $-14.20 | 0 |
| 3M | 1% | 8 | 37.5% | $-15.90 | -3.2% | 3.5% | 0.23 | $-5.30 | $-0.64 | $-12.21 | 1 |
| 3M | 2% | 7 | 42.9% | $-24.63 | -4.9% | 5.6% | 0.28 | $-8.21 | $0.87 | $-18.82 | 0 |
| 5M | 1% | 30 | 36.7% | $-23.36 | -4.7% | 6.3% | 0.72 | $-1.67 | $20.15 | $-8.81 | 5 |
| 5M | 2% | 32 | 37.5% | $-57.44 | -11.5% | 13.5% | 0.69 | $-3.83 | $41.39 | $-17.90 | 2 |
| 15M | 1% | 46 | 39.1% | $-37.55 | -7.5% | 11.4% | 0.69 | $-1.34 | $10.31 | $-13.66 | 7 |
| 15M | 2% | 44 | 38.6% | $-69.71 | -13.9% | 21.1% | 0.72 | $-2.49 | $20.61 | $-21.14 | 6 |

## 7. $1,000 RESULTS (portfolio of all 17 pairs, compounding, real lot sizing)

| TF | Risk | Trades | Win rate | Net profit | ROI | Max DD | PF | Avg/day $ | Best day | Worst day | Skipped (lot < 0.01) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1M | 1% | 6 | 16.7% | $-29.53 | -3.0% | 3.0% | 0.07 | $-7.38 | $2.22 | $-14.20 | 0 |
| 1M | 2% | 6 | 16.7% | $-63.29 | -6.3% | 6.3% | 0.08 | $-15.82 | $5.55 | $-33.72 | 0 |
| 3M | 1% | 8 | 37.5% | $-33.07 | -3.3% | 3.6% | 0.22 | $-11.02 | $0.87 | $-27.26 | 0 |
| 3M | 2% | 7 | 42.9% | $-54.20 | -5.4% | 6.0% | 0.26 | $-18.07 | $-3.21 | $-37.63 | 0 |
| 5M | 1% | 33 | 36.4% | $-66.87 | -6.7% | 7.7% | 0.65 | $-4.46 | $41.39 | $-26.38 | 2 |
| 5M | 2% | 32 | 40.6% | $-95.98 | -9.6% | 13.7% | 0.73 | $-6.40 | $86.19 | $-40.35 | 1 |
| 15M | 1% | 46 | 39.1% | $-66.51 | -6.7% | 10.7% | 0.75 | $-2.38 | $20.61 | $-29.40 | 6 |
| 15M | 2% | 47 | 40.4% | $-144.82 | -14.5% | 22.8% | 0.72 | $-4.83 | $42.70 | $-43.31 | 1 |

## 8. Weekly and monthly breakdown ($1,000 @ 1%)

**1M** — weekly: 2026-W41: 6 tr, $-29.53 (-3.0%), WR 16.7%

**1M** — monthly: 2026-10: 6 tr, $-29.53 (-3.0%), WR 16.7%

**3M** — weekly: 2026-W41: 8 tr, $-33.07 (-3.3%), WR 37.5%

**3M** — monthly: 2026-10: 8 tr, $-33.07 (-3.3%), WR 37.5%

**5M** — weekly: 2026-W38: 2 tr, $-18.86 (-1.9%), WR 0.0%; 2026-W39: 12 tr, $+29.91 (3.0%), WR 58.3%; 2026-W40: 12 tr, $-50.03 (-5.0%), WR 25.0%; 2026-W41: 7 tr, $-27.89 (-2.8%), WR 28.6%

**5M** — monthly: 2026-09: 20 tr, $-31.73 (-3.2%), WR 40.0%; 2026-10: 13 tr, $-35.14 (-3.5%), WR 30.8%

**15M** — weekly: 2026-W32: 3 tr, $+7.77 (0.8%), WR 66.7%; 2026-W33: 4 tr, $+37.71 (3.8%), WR 75.0%; 2026-W34: 7 tr, $-42.73 (-4.3%), WR 14.3%; 2026-W35: 3 tr, $-16.55 (-1.7%), WR 33.3%; 2026-W36: 2 tr, $-18.02 (-1.8%), WR 0.0%; 2026-W37: 4 tr, $+13.63 (1.4%), WR 75.0%; 2026-W38: 8 tr, $+18.01 (1.8%), WR 50.0%; 2026-W39: 7 tr, $-29.39 (-2.9%), WR 28.6%; 2026-W40: 6 tr, $-19.87 (-2.0%), WR 33.3%; 2026-W41: 2 tr, $-17.07 (-1.7%), WR 0.0%

**15M** — monthly: 2026-08: 18 tr, $-23.31 (-2.3%), WR 38.9%; 2026-09: 22 tr, $-12.95 (-1.3%), WR 45.5%; 2026-10: 6 tr, $-30.25 (-3.0%), WR 16.7%

Per-day results for every account are in `results.json` (`accounts → day`) and the ledgers `ledger_<tf>_<balance>_<risk>pct.csv`.

## 9. Filter sensitivity and cost diagnostic (informational — not used to choose anything)

Do the strict filters hide an edge? Relaxing them gives bigger samples; zero-spread runs show the edge before costs.

| TF | Variant | Trades | Win rate | PF | Avg R | t-stat | OOS trades | OOS avg R |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 15M | Default rules | 57 | 40.4% | 0.76 | -0.15 | -0.98 | 11 | -0.20 |
| 15M | No 1.5R room filter | 150 | 44.0% | 0.84 | -0.09 | -0.97 | 26 | -0.09 |
| 15M | No max-stop filter | 87 | 37.9% | 0.68 | -0.18 | -1.62 | 15 | -0.21 |
| 15M | Spread filter 100% ATR | 66 | 39.4% | 0.70 | -0.19 | -1.36 | 13 | -0.38 |
| 15M | All three relaxed | 329 | 40.7% | 0.70 | -0.17 | -2.91 | 55 | -0.09 |
| 15M | All relaxed + all sessions | 519 | 40.3% | 0.70 | -0.17 | -3.66 | 86 | -0.06 |
| 15M | Default, ZERO spread | 74 | 54.1% | 1.17 | +0.08 | +0.61 | 14 | -0.19 |
| 15M | All relaxed, ZERO spread | 333 | 48.3% | 0.90 | -0.05 | -0.84 | 55 | -0.03 |
| 5M | Default rules | 36 | 36.1% | 0.62 | -0.25 | -1.37 | 7 | -0.43 |
| 5M | No 1.5R room filter | 94 | 33.0% | 0.61 | -0.25 | -2.21 | 14 | -0.49 |
| 5M | No max-stop filter | 51 | 41.2% | 0.57 | -0.25 | -1.84 | 10 | -0.44 |
| 5M | Spread filter 100% ATR | 72 | 37.5% | 0.50 | -0.33 | -2.66 | 17 | -0.47 |
| 5M | All three relaxed | 292 | 38.0% | 0.57 | -0.26 | -4.38 | 60 | -0.42 |
| 5M | All relaxed + all sessions | 423 | 38.3% | 0.59 | -0.25 | -4.88 | 78 | -0.32 |
| 5M | Default, ZERO spread | 91 | 49.5% | 0.97 | -0.02 | -0.12 | 19 | -0.12 |
| 5M | All relaxed, ZERO spread | 306 | 43.1% | 0.73 | -0.15 | -2.46 | 63 | -0.37 |

## 10. Honest conclusion

- Across all four execution timeframes the strict rule set produced **109 trades** in the available history. Most candidate setups are removed by the spread, stop-size and 1.5R-room filters — the system is very selective by design.
- **1M:** 6 trades, win rate 16.7%, PF 0.08, -0.62R/trade → negative and not statistically meaningful (t = -2.76).
- **3M:** 10 trades, win rate 30.0%, PF 0.14, -0.60R/trade → negative and not statistically meaningful (t = -3.10).
- **5M:** 36 trades, win rate 36.1%, PF 0.62, -0.25R/trade → negative and not statistically meaningful (t = -1.37).
- **15M:** 57 trades, win rate 40.4%, PF 0.76, -0.15R/trade → negative and not statistically meaningful (t = -0.98).
- Least-bad timeframe on this data: **15M**.
- **The filters are not hiding an edge.** With the room/stop/spread filters removed, 15M gives 329 trades at -0.17R (t = -2.91): a larger sample that is more clearly negative.
- **Before costs the edge is roughly zero:** default rules with zero spread give +0.08R/trade (t = +0.61, n = 74). Spread turns that into a loss, which is why 1M–5M are worst.
- **Verdict: on this data BB SNIPER, as specified, is a NO-TRADE system.** It should not be traded live or sent as signals until a longer test (90+ days per timeframe) shows positive out-of-sample expectancy.
- **1M/3M:** the 3.5-day window and spreads that are a large fraction of a 1-minute ATR make these timeframes unsuitable to judge, and mostly untradeable at retail spreads.
- No configuration here should be called proven. Before risking money: run `python3 -m bbsniper.live` on demo, log 50+ trades, and load longer history (TradingView CSV exports) into `backtest_tv/data/` to repeat this test on 90+ days.

## 11. Rules actually implemented (defaults in `bbsniper/config.py`)

- **Bias (15M, 1H for 15M exec):** close > EMA200 and EMA20 > EMA200 (bull) / mirror (bear); counter-bias trades are never taken; neutral bias trades only if every non-bias point scores.
- **Regime (setup TF):** ADX < 20 ranging, 20–25 transitional, > 25 + EMA alignment trending; BandWidth percentile (100 bars) < 20 = squeeze, > 80 and rising = expansion.
- **Mean reversion (ranging/transitional):** low at/near lower band → sweep of an unswept swing low (pivot 3/3, last 60 bars) → close back above it → bullish MSS (close through the last micro swing high, pivot 2/2) → enter on the MSS close. Stop = sweep low − 0.2 ATR.
- **Trend continuation (trending + aligned bias):** after %B > 0.8, pullback into EMA20/middle band → MSS → enter; stop below the pullback low − 0.2 ATR.
- **Squeeze breakout:** BandWidth squeeze in the last 10 bars → close outside the band and above the 20-bar range with ADX rising → retest of the breakout level that holds → bullish confirmation candle → enter; stop below the retest low − 0.2 ATR.
- **Score 0–10:** +2 HTF bias, +1 setup-TF trend, +2 liquidity sweep, +1 Bollinger extreme, +1 MSS, +1 RSI (zone or divergence), +1 %B (reclaim or divergence), +1 ADX. Trade ≥ 8 (Standard).
- **Filters:** London+NY sessions, spread ≤ 50% of ATR, stop ≤ 3 ATR, nearest opposing major swing ≥ 1.5R away, max 3 trades/day, stop after 3 losses/day, 3% daily loss limit.
- **Management:** 30% at 1R, 35% at 2R, rest at 3R; stop to entry + 0.05R after TP1; ATR(1.5) trailing after 2R; 120-bar time stop.
- **Fills:** longs pay the spread on entry, shorts on exit; stop assumed before target when both are touched in one bar; targets need 0.2 pip trade-through; gaps fill at the open.
