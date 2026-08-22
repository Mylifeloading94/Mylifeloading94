# Automated TradeLocker Forex & Gold Bot — Build and Backtest Report

**Period tested:** 2026-01-01 → 2026-08-22 (broker data ends Fri 2026-08-21 20:45 UTC)
**Starting balance:** $10,000
**Data:** real M15 bars pulled from the TradeLocker **live PULSE feed** (account L#808776),
24 instruments, ~38,700 bars each, Feb 2025 → Aug 2026. No synthetic prices anywhere.

---

## Headline result — please read this first

The strategy **did not meet the performance targets. It lost money.**

| | Target in brief | Actual (out of sample) |
|---|---|---|
| Win rate | 60% min, 70–90% goal | **42.7%** |
| Profit factor | > 1 | **0.36** |
| Net profit | positive | **−$1,925.82 (−19.26%)** |
| Max drawdown | low | **$2,032.70 (20.11%)** |
| Expectancy | positive | **−$17.51 per trade (−0.400R)** |

Ending balance: **$8,074.18**.

Per the brief's Most Important Rule, these are the real numbers. I did not tune the
strategy against the 2026 window to make them look better, and section 3 below documents
the specific points where doing so was possible and was deliberately declined.

**Recommendation: do not trade this live.** The live bot is wired and working, but it
refuses to run against a live account without an explicit acknowledgement flag.

---

## 1. What was built

| File | Purpose |
|---|---|
| `tl_data.py` | TradeLocker auth + historical M15 fetch, caches to `data/` |
| `strategy.py` | Signal logic + 0–100 trade-quality score. No broker dependency |
| `backtest.py` | Portfolio backtester: sizing, daily loss cap, concurrency, currency caps |
| `signal_sim.py` | Independent signal-level simulator, used for parameter selection |
| `config.py` | The **locked** parameter set and the in-sample/out-of-sample windows |
| `metrics.py` | Performance statistics |
| `run_backtest.py` | The final out-of-sample run that produced this report |
| `walkforward.py` | Rolling train/test validation |
| `live_bot.py` | TradeLocker execution bot |

Two independent engines (`backtest.py` and `signal_sim.py`) were built and cross-checked
against each other. They initially disagreed (88.2% vs 75.0% win rate) — that disagreement
was a **bug**, not noise, and finding it changed the conclusions materially. See §3.

---

## 2. Method — how look-ahead and overfitting were kept out

**Timeframe alignment.** Higher-timeframe bars become visible only once closed. An H4 bar
stamped 08:00 is invisible until 12:00 (`strategy.htf_index`). Without this the daily and
4-hour bias would silently leak the future.

**Fills.** A signal computed on the close of bar *i* is never filled on bar *i*. It rests
as a limit order from bar *i+1*.

**Every ambiguity resolves against the account:**
- bar touches both stop and target → stop
- gap through the stop → filled at the gapped open, not the stop price
- limit fills mid-bar → that bar may resolve the **stop** but never the target, because
  intrabar order is unknowable from OHLC

**Costs.** Spread (0.9–3.0 pips, set at or above typical retail quotes), $7/lot round-turn
commission, 0.3 pip entry slippage, 0.6 pip extra on stops. Measured drag: **round-trip
cost is ~13.9% of the median stop** (median stop 15.7 pips).

**Train/test split.** Parameters and the pair watchlist were chosen on **2025 data only**
(2025-03-01 → 2025-12-31) and frozen in `config.py` **before** the 2026 window was
evaluated. The 2026 result above is a genuine out-of-sample result.

---

## 3. Where the results could have been faked, and were not

These are the three places this backtest could have been made to look excellent. Each is
documented in code.

**(a) The R:R gate.** `min_rr_after_costs` is savagely sensitive in-sample:

| gate | trades | win rate | profit factor |
|---|---|---|---|
| 0.30 | 116 | 75.9% | 1.54 |
| 0.36 | 85 | 78.8% | 1.86 |
| 0.40 | 57 | 82.5% | 2.39 |
| 0.45 | 26 | 84.6% | 2.86 |
| 0.50 | **8** | **100.0%** | **∞** |

Tightening one number produces a 100% win rate — purely by shrinking the sample to 8
trades. **The loosest value (0.30) was taken**, which is the only choice that cannot be
accused of chasing the metric.

**(b) Pair selection.** The watchlist was chosen on 2025. Had it instead been chosen on the
2026 test data, it would have contained **GBPAUD, GBPCAD, AUDCAD, EURCAD** — and GBPAUD
alone shows 93.75% win rate at profit factor 7.82 in 2026. Fitting the watchlist to the test
window would have let me report a spectacular result.

> **Overlap between the honestly-chosen watchlist and the fitted one: zero pairs.**

That zero is the single most important number in this report. Pair-level performance carries
**no information** from one period to the next; it is noise.

**(c) The fill-bar bug.** The first cross-check showed 88.2% win rate / PF 3.65 in-sample.
That was a bug: the signal simulator was awarding targets on the same bar the limit filled.
Fixing it dropped in-sample to 73.1% / PF 1.34, and re-running selection on the corrected
engine showed that **essentially no configuration achieves both a 60%+ win rate and a
profit factor above 1** (2 of 27, best PF 1.042). The pre-fix numbers would have looked
like a success.

---

## 4. Why it fails — the diagnosis

**The signal has no predictive edge, before costs are even considered.** Re-running
in-sample with **all costs set to zero**:

| target | trades | win rate | break-even win rate needed | profit factor |
|---|---|---|---|---|
| 0.6R | 196 | 63.8% | 62.5% | 1.06 |
| 1.0R | 195 | 52.3% | 50.0% | 1.10 |
| 1.5R | 193 | 38.9% | 40.0% | 0.94 |
| 2.0R | 193 | 34.7% | 33.3% | 1.02 |

Win rates land within ~1.5 points of the break-even line at every target size. The setup is
close to a coin flip. Costs (13.9% of the stop) then convert "no edge" into "reliably
losing".

**The win-rate/RR trade-off is arithmetic, not a tuning problem.** You can have a high win
rate *or* a strong risk-to-reward ratio, never both:

| target | win rate | profit factor |
|---|---|---|
| 0.6R | 63.1% | 0.885 |
| 1.0R | 50.6% | 0.907 |
| 1.5R | 43.6% | 0.998 |
| 2.0R | 39.9% | **1.031** |
| 2.5R | 36.9% | 0.974 |

The brief asks for a 60–90% win rate **and** a strong R:R. On this data those requirements
are mutually exclusive — the 60%+ win rate configurations all have R:R below 1.

**Walk-forward confirms it is not a one-split accident.** Rolling 3-month train → 1-month
test, re-selecting target size and watchlist each cycle:

- months where test profit factor > 1: **4 of 10**
- mean out-of-sample expectancy: **−0.1497R**
- **correlation between train PF and test PF: −0.111**

A negative correlation means selecting on recent performance is, if anything, mildly
counterproductive.

**The quality score does not work.** Out of sample its correlation with outcome is
**−0.037**, and the highest-scoring trades performed **worst**:

| score band | trades | win rate | expectancy |
|---|---|---|---|
| ≤65 | 17 | 35.3% | −0.553R |
| 65–70 | 21 | 61.9% | −0.097R |
| 70–75 | 32 | 50.0% | −0.279R |
| **75–100** | **59** | **40.7%** | **−0.423R** |

The two largest losing trades scored **96/100** and **88/100**. A scoring system that ranks
its worst trades highest is not a filter — it is decoration. This is reported rather than
quietly rebuilt, because rebuilding it against this same data is exactly how it would become
overfitted.

**Alternative strategy families were tested and also failed** (in-sample 2025, pooled):

| family | timeframe | best PF | verdict |
|---|---|---|---|
| Donchian breakout | H1 / H4 | 0.85 | clearly negative |
| EMA pullback continuation | H1 / H4 | < 0.85 | clearly negative |
| Bollinger mean reversion | H4 | 1.18 (n=143) | not robust — neighbours collapse to 1.02 |
| Sweep + MSS (primary) | M15 | 1.03 | not robust |

Only 6 of 72 alternative configurations beat PF 1.0 in-sample, and none survived a
robustness check.

---

## 5. Complete $10,000 backtest — overall performance

| Metric | Value |
|---|---|
| Starting balance | $10,000.00 |
| Ending balance | **$8,074.18** |
| Net profit | **−$1,925.82** |
| Net profit % | **−19.26%** |
| Total trades | 110 |
| Winning trades | 47 |
| Losing trades | 63 |
| Win rate | **42.73%** |
| Average win | $23.19 |
| Average loss | −$47.87 |
| Profit factor | **0.361** |
| Expectancy per trade | −$17.51 (−0.400R) |
| Average planned R:R | 0.427 |
| Realized R:R (avg win / avg loss) | 0.484 |
| Max drawdown ($) | $2,032.70 |
| Max drawdown (%) | 20.11% |
| Recovery factor | −0.947 |
| Sharpe ratio | −5.587 |
| Sortino ratio | −6.326 |
| Largest winning trade | $27.40 |
| Largest losing trade | −$57.68 |
| Average trades per day | 0.66 |
| Longest winning streak | 4 |
| Longest losing streak | **8** |
| Average trade duration | 0.86 hours |

Exit breakdown: 47 targets (avg +0.543R, +$1,089.93), 63 stops (avg −1.104R, −$3,015.78).

---

## 6. Monthly results

| Month | Trades | Win rate | P/L | Profit factor | Max DD | Ending balance |
|---|---|---|---|---|---|---|
| Jan 2026 | 19 | 57.89% | −$160.60 | 0.62 | $267.48 (2.65%) | $9,839.40 |
| Feb 2026 | 18 | 50.00% | −$222.00 | 0.51 | $275.04 (2.79%) | $9,617.40 |
| Mar 2026 | 16 | 31.25% | −$441.54 | 0.22 | $518.48 (5.35%) | $9,175.86 |
| Apr 2026 | 14 | 35.71% | −$333.77 | 0.26 | $334.97 (3.65%) | $8,842.09 |
| May 2026 | 7 | 57.14% | −$55.25 | 0.63 | $125.71 (1.41%) | $8,786.84 |
| Jun 2026 | 14 | 50.00% | −$143.43 | 0.46 | $119.00 (1.36%) | $8,643.42 |
| Jul 2026 | 13 | 30.77% | −$315.27 | 0.22 | $287.85 (3.34%) | $8,328.15 |
| Aug 2026 (to 21st) | 9 | 22.22% | −$253.97 | 0.14 | $275.35 (3.30%) | $8,074.18 |

**Every month lost money.** Not one month reached profit factor 1.0. There is no
"good regime" hiding in here — the equity curve declines monotonically.

---

## 7. Pair-by-pair analysis (all 24 tested, 2026, $10,000 each, single-pair)

| # | Pair | Trades | Win rate | Net | ROI | PF | Max DD % | Avg trade | Avg R:R | W/L streak | Trades/day | Grade |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GBPAUD | 16 | 93.75% | +$359.89 | +3.60% | 7.82 | 0.53% | +$22.49 | 0.376 | 8 / 1 | 0.10 | A |
| 2 | GBPCAD | 13 | 92.31% | +$276.16 | +2.76% | 6.18 | 0.54% | +$21.24 | 0.370 | 9 / 1 | 0.08 | A |
| 3 | AUDCAD | 5 | 80.00% | +$48.43 | +0.48% | 1.86 | 0.58% | +$9.69 | 0.339 | 3 / 1 | 0.03 | C |
| 4 | EURCAD | 11 | 72.73% | +$40.49 | +0.40% | 1.24 | 1.19% | +$3.68 | 0.339 | 5 / 1 | 0.07 | C |
| 5 | EURAUD | 18 | 66.67% | −$4.80 | −0.05% | 0.99 | 1.12% | −$0.27 | 0.390 | 6 / 2 | 0.11 | D |
| 6 | NZDUSD | 10 | 60.00% | −$60.84 | −0.61% | 0.72 | 1.10% | −$6.08 | 0.354 | 4 / 2 | 0.06 | D |
| 7 | NZDJPY | 5 | 60.00% | −$34.38 | −0.34% | 0.69 | 1.14% | −$6.88 | 0.336 | 2 / 2 | 0.03 | F |
| 8 | GBPCHF | 4 | 50.00% | −$51.06 | −0.51% | 0.52 | 1.06% | −$12.77 | 0.305 | 2 / 2 | 0.02 | F |
| 9 | USDSGD | 2 | 50.00% | −$26.06 | −0.26% | 0.50 | 0.52% | −$13.03 | 0.361 | 1 / 1 | 0.01 | F |
| 10 | GBPUSD | 20 | 50.00% | −$279.38 | −2.79% | 0.49 | 2.80% | −$13.97 | 0.418 | 3 / 2 | 0.12 | F |
| 11 | AUDJPY | 10 | 50.00% | −$142.87 | −1.43% | 0.48 | 1.69% | −$14.29 | 0.405 | 4 / 3 | 0.06 | F |
| 12 | EURGBP | 6 | 50.00% | −$88.75 | −0.89% | 0.48 | 1.42% | −$14.79 | 0.308 | 2 / 2 | 0.04 | F |
| 13 | EURJPY | 6 | 50.00% | −$89.11 | −0.89% | 0.46 | 1.16% | −$14.85 | 0.407 | 2 / 2 | 0.04 | F |
| 14 | XAUUSD | 14 | 42.86% | −$142.97 | −1.43% | 0.38 | 1.85% | −$10.21 | 0.559 | 3 / 5 | 0.08 | F |
| 15 | CHFJPY | 14 | 42.86% | −$259.03 | −2.59% | 0.38 | 2.86% | −$18.50 | 0.413 | 2 / 2 | 0.08 | F |
| 16 | CADJPY | 9 | 44.44% | −$173.06 | −1.73% | 0.37 | 2.24% | −$19.23 | 0.363 | 2 / 2 | 0.05 | F |
| 17 | USDCHF | 7 | 42.86% | −$135.78 | −1.36% | 0.37 | 1.90% | −$19.40 | 0.386 | 2 / 3 | 0.04 | F |
| 18 | USDJPY | 9 | 44.44% | −$180.32 | −1.80% | 0.36 | 2.07% | −$20.04 | 0.446 | 2 / 3 | 0.05 | F |
| 19 | USDCAD | 15 | 40.00% | −$338.22 | −3.38% | 0.32 | 3.64% | −$22.55 | 0.414 | 2 / 4 | 0.09 | F |
| 20 | EURUSD | 13 | 38.46% | −$318.09 | −3.18% | 0.29 | 3.45% | −$24.47 | 0.405 | 2 / 4 | 0.08 | F |
| 21 | GBPJPY | 11 | 36.36% | −$265.95 | −2.66% | 0.29 | 2.92% | −$24.18 | 0.415 | 2 / 3 | 0.07 | F |
| 22 | AUDUSD | 10 | 30.00% | −$305.25 | −3.05% | 0.20 | 3.05% | −$30.53 | 0.402 | 1 / 3 | 0.06 | F |
| 23 | EURCHF | 1 | 0.00% | −$9.14 | −0.09% | 0.00 | 0.09% | −$9.14 | 0.455 | 0 / 1 | 0.01 | F |
| 24 | AUDNZD | 1 | 0.00% | −$55.70 | −0.56% | 0.00 | 0.56% | −$55.70 | 0.340 | 0 / 1 | 0.01 | F |

**Grading (§6 of brief):** grades combine win rate, profit factor, ROI, drawdown, trade
frequency, consistency and R:R. **No pair earns A+.** GBPAUD and GBPCAD grade A on 2026
numbers alone, but both were **rejected** on 2025 data (55.6% win rate, PF 0.62) — their
2026 performance is a 13–16 trade sample with no prior support, which is why they are not
in the approved watchlist and must not be treated as an edge.

---

## 8. Approved and rejected pairs

### Approved trading watchlist (chosen on 2025, frozen before testing)
`EURUSD, USDJPY, CADJPY, XAUUSD, GBPUSD, GBPJPY, USDCAD, EURJPY, CHFJPY, AUDJPY`

**All ten subsequently lost money in 2026.** Their in-sample credentials (win rates
71–100%, PF 1.25–∞) did not transfer at all.

### Rejected pairs and the exact reason

| Pair | In-sample stats | Reason rejected |
|---|---|---|
| AUDUSD | n=2, 100% WR | insufficient setups (2 < 5) |
| EURCHF | n=1, 100% WR | insufficient setups (1 < 5) |
| AUDCAD | n=1, 100% WR | insufficient setups (1 < 5) |
| EURCAD | n=3, 66.7% WR | insufficient setups (3 < 5) |
| GBPCHF | n=2, 50.0% WR | insufficient setups (2 < 5) |
| EURGBP | n=3, 33.3% WR | insufficient setups (3 < 5) |
| NZDUSD | n=1, 0% WR | insufficient setups (1 < 5) |
| AUDNZD | n=0 | insufficient setups (0 < 5) |
| USDSGD | n=0 | insufficient setups (0 < 5) |
| USDCHF | n=6, 66.7% WR, PF 0.97 | profit factor 0.97 < 1.15 |
| NZDJPY | n=5, 60.0% WR, PF 0.76 | profit factor 0.76 < 1.15 |
| GBPAUD | n=9, 55.6% WR, PF 0.62 | win rate 55.6% < 60% |
| GBPCAD | n=9, 55.6% WR, PF 0.62 | win rate 55.6% < 60% |
| EURAUD | n=6, 50.0% WR, PF 0.48 | win rate 50.0% < 60% |

The automatic filter worked exactly as specified in §7 of the brief. It simply had nothing
real to select on.

### Performance ranking of qualifying pairs
Ranking the approved watchlist by 2026 result gives: AUDJPY (−1.43%), EURJPY (−0.89%),
XAUUSD (−1.43%), CHFJPY (−2.59%), USDJPY (−1.80%), CADJPY (−1.73%), GBPUSD (−2.79%),
GBPJPY (−2.66%), EURUSD (−3.18%), USDCAD (−3.38%). **Every entry is a loss, so this
ranking orders degrees of failure, not degrees of merit.**

---

## 9. Risk analysis

The risk layer is the one part of the system that performed exactly as designed.

| Metric | Value |
|---|---|
| Active trading days | 82 |
| Losing days | 52 of 82 (63.4%) |
| Worst single day | −$154.01 (−1.6%) |
| Best single day | +$51.10 |
| Days breaching the 2% daily loss cap | **0** |
| Max trades in one day | 3 (cap respected) |
| Mean trades per active day | 1.34 |
| Longest losing streak | **8 trades, −$410.47** (13–23 Mar 2026) |
| Max drawdown | $2,032.70 / 20.11% |
| Losers that were ≥ +0.5R in profit first | 1 of 63 |
| Winners: mean MFE / MAE | +0.88R / −0.34R |
| Losers: mean MFE / MAE | +0.10R / −1.28R |
| Long trades | 78, 47.4% WR, −$1,130.05 |
| Short trades | 32, 31.3% WR, −$795.80 |

No single day lost more than 1.6% against a 2% cap; position sizing held risk at ~0.5% of
equity throughout; no martingale, no averaging down. The 20% drawdown was **not** produced
by a risk failure — it is 110 small, correctly-sized losses accumulating. Good risk
management cannot rescue a negative-expectancy signal; it only controls the rate of loss.

Note also that losers show a mean MFE of just +0.10R — they go wrong almost immediately.
This is not a "give it more room" problem.

---

## 10. Trade examples

### Winner — XAUUSD LONG, 26 Jan 2026, score 92/100
Entry 5070.96, stop 5048.54 (224 pips), target 5084.42. Daily and H4 both bullish; price
swept the 20-bar low, reclaimed it, then a displacement candle closed above the pre-sweep
high. Limit rested at 62% back into the leg and filled 90 minutes later.
**Result: target, +0.597R.** MFE +1.48R — it went more than twice as far as the target.

### Winner — USDCAD LONG, 22 Jun 2026, score 87/100
Entry 1.41576, stop 1.41409 (16.7 pips), target 1.41676. **Result: target, +0.541R**, held
6 bars. MFE only +0.84R — the 0.6R target was the right size here.

### Loser — XAUUSD LONG, 18 Aug 2026, **score 96/100** (the highest-scored trade in the set)
Entry 4388.06, stop 4372.21, target 4397.58. Every condition aligned: daily trend 15/15,
H4 12/12, clean sweep, strong displacement, prime session. **Result: stopped, −1.008R after
2 bars.** MFE +0.53R, MAE −1.53R. Price reclaimed the sweep, failed instantly, and ran
straight through the stop.

### Loser — XAUUSD LONG, 26 Feb 2026, score 88/100
Entry 5166.55, stop 5153.43. **Result: stopped, −1.010R.** MAE −2.02R — it went twice the
stop distance against us.

### Loser — GBPUSD LONG, 31 Jul 2026, score 87/100
Entry 1.34194, stop 1.34049 (14.5 pips). **Result: stopped, −1.090R after a single bar.**
Note the cost drag: the loss is 1.09R, not 1.00R, because spread + slippage + commission on
a 14.5-pip stop is ~9% of R.

**What these examples show:** the winners and losers are indistinguishable at entry. Both
sets satisfy every rule, and the losers score *higher*. That is the signature of a
non-predictive signal.

### Setups the bot rejected (EURUSD, 2026 — 15,932 bars examined)

| Reason | Count | Share |
|---|---|---|
| Outside the two trading sessions | 10,620 | 66.66% |
| No liquidity sweep to trade | 2,319 | 14.56% |
| No clear daily trend | 1,072 | 6.73% |
| Sweep never reclaimed (no structure shift) | 928 | 5.82% |
| H4 disagrees with the daily bias | 831 | 5.22% |
| Confirmation candle too weak | 49 | 0.31% |
| Failed location / extension / score gate | 42 | 0.26% |
| Volatility outside tradable band | 20 | 0.13% |
| **Accepted** | **51** | **0.32%** |

The bot is genuinely selective — it stands down on 99.7% of bars. Selectivity was never the
problem.

---

## 11. Final bot rules (as implemented)

These are the exact rules in `config.py` / `strategy.py`, stated precisely enough to be
executed automatically. They are documented for completeness — **they are not a
recommendation to trade.**

**Markets:** the 10-pair approved watchlist. **Timeframe:** M15 signal, H1/H4/D1 context.

**Sessions (UTC):** 07:00–11:00 and 12:00–16:00 only.

**Pre-conditions (all must hold):**
1. ATR(14)/price between 0.025% and 1.25% — not dead, not blown out
2. Spread ≤ 45% of ATR(14)
3. Daily bias non-neutral: close vs EMA50 vs EMA200 agree on direction
4. H4 bias (close vs EMA20 vs EMA50) does not contradict the daily bias

**Entry trigger (all must hold, direction = daily bias):**
5. **Liquidity sweep:** within the last 6 bars, a bar wicked beyond the prior 20-bar
   extreme and closed back inside it
6. **Structure shift:** the current bar closes beyond the 3-bar extreme preceding the sweep
7. **Displacement:** body ≥ 0.45 × ATR, closing in the trade direction
8. **Location:** the sweep extreme sat in the lower 45% (longs) / upper 45% (shorts) of the
   40-bar range
9. **Extension:** price within 1.6 × ATR of EMA20
10. **Quality score ≥ 60/100**

**Order:** limit at 62% retracement of the displacement leg, GTC, expires after 6 bars,
cancelled if the stop level trades first.

**Stop:** sweep extreme ± 0.5 × ATR(14). **Target:** 0.6R. No partials, no breakeven stop
(both measurably reduced expectancy). **Time stop:** 64 bars.

**Risk:** 0.5% equity per trade (0.35% gold); max 3 concurrent; max 2 positions sharing a
currency; max 3 trades/day; 2% daily loss cap; 4-consecutive-loss lockout. Never increase
size after a loss.

---

## 12. What I would do next

The evidence says the problem is the **signal**, not the parameters, so more tuning of this
family is not worth doing.

1. **Do not trade this.** Nothing here justifies risking capital.
2. **Test the premise on cleaner ground.** M15 costs are ~14% of the stop. H4/D1 systems put
   costs near 2–3%, so a genuine edge has room to survive.
3. **Look for edges with a documented economic cause** — carry, session/time-of-day effects,
   post-news volatility, cross-asset lead-lag — rather than pure chart geometry, which is
   what the 24 pairs above all failed to provide.
4. **Set the go-live gate on profit factor, not win rate:** PF > 1.2 across 100+ trades in
   a period never used for tuning. This build never came close.
5. **Rotate the account password.** It was shared in the task text; treat it as compromised.

---

## Appendix — reproducing this

```bash
export TL_EMAIL=... TL_PASSWORD=... TL_SERVER=PULSE TL_ENV=live
python3 tl_data.py          # fetch real M15 (writes data/, gitignored)
python3 select_pairs.py     # in-sample 2025 watchlist selection
python3 run_backtest.py     # the out-of-sample 2026 run in this report
python3 walkforward.py      # rolling train/test validation
python3 live_bot.py --dry-run
```

Outputs: `backtest_results.json`, `trades_oos_2026.csv`, `pair_selection_insample.csv`,
`walkforward.csv`, `sweep_insample.csv`, `winrate_probe.csv`, `alt_strategies_insample.csv`.
