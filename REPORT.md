# Automated TradeLocker Forex & Gold Bot — v2 Report

**Data:** real bars from the TradeLocker **live PULSE feed** (account L#808776), 24 instruments,
~80,000 M15 bars each, **2023-06-01 → 2026-08-21**. No synthetic prices anywhere.

**Headline validation:** anchored walk-forward, 2025-04-01 → 2026-08-22, $10,000.

---

## 1. Result

Two validated configurations. Both trade the same signal and differ only in target placement.

| | **Balanced** (default) | **High win rate** | Brief's target |
|---|---|---|---|
| Ending balance | **$10,712.81** | $10,435.44 | — |
| Net profit | **+$712.81 (+7.13%)** | +$435.44 (+4.35%) | positive |
| Trades | 93 | 89 | — |
| **Win rate** | **59.14%** | **70.79%** | 60% min, 70–90% goal |
| **Profit factor** | **1.364** | 1.330 | > 1 |
| Expectancy | +$7.66 (+0.155R) | +$4.89 (+0.106R) | positive |
| **Max drawdown** | **$220.31 (2.11%)** | $212.00 (2.04%) | low |
| Recovery factor | 3.235 | 2.054 | — |
| Sharpe / Sortino | 1.053 / 0.707 | 0.829 / 0.409 | — |
| Avg reward-to-risk | 0.886 | 0.509 | "strong" |
| Longest losing streak | 4 | 4 | — |
| Trades per day | 0.15 | 0.14 | 2–3 |

**Scorecard against the brief:** win rate ✅ (high-win-rate mode hits the 70–90% band; balanced
mode is 59.1%, a hair under the 60% floor) · profit factor ✅ · positive expectancy ✅ ·
low drawdown ✅ (2%) · consistency ✅ (4 of 6 blocks positive) · controlled risk ✅ ·
**reward-to-risk ❌** (below 1) · **trade frequency ❌** (0.15/day, not 2–3).

This is a genuine turnaround from v1, which lost 19.26% at profit factor 0.36. Two of the
brief's targets are still not met, and §6 explains why they are arithmetically unreachable
together rather than merely untuned.

---

## 2. What was wrong with v1 — two real bugs

### Bug 1 — the in-sample window was crippled (this was the big one)

The daily EMA200 trend filter needs 200 daily bars of warm-up. v1's data only reached back to
Feb 2025, so:

| window | bars with a usable daily bias |
|---|---|
| v1 in-sample (2025-03 → 2025-12) | **32.2%** |
| v1 out-of-sample (2026) | **100%** |

Selection and evaluation were effectively running **different strategies**. Almost every
in-sample bar was rejected before the trend filter could contribute, so the ~10-month training
window was really about 3 months of usable data. That is why nothing transferred.

Fixed by pulling history back to 2023-06. Both windows are now at 100% coverage.

### Bug 2 — the signal was on the wrong timeframe for its cost structure

Round-trip cost (spread + slippage + commission) as a share of the stop:

| timeframe | cost / stop | in-sample **median** profit factor |
|---|---|---|
| M15 | ~14% | 0.735 |
| H1 | ~4% | 0.785 |
| **H4** | **~2%** | **1.413** |

At H4, **100% of 240 tested configurations beat profit factor 1.0**. That is a plateau, not a
peak — the opposite of what M15 showed. The edge was always being eaten by transaction costs.

Confirming this independently: in the full walk-forward, where the training data re-chooses the
timeframe from scratch every cycle, it selected **H4 in all six cycles**.

### Two smaller code faults, also fixed
- `UsdConverter` cached currency-conversion series keyed on `id(index)`. A freed pandas Index
  can be reallocated at the same address, silently returning another symbol's rates.
- `_find_sweep` scanned newest-bar-first, so it could latch onto a bar part-way through a
  reversal rather than the liquidity event that started it. Now scans from the origin.

---

## 3. Validation method

### No look-ahead — mechanically verified
`test_no_lookahead.py` evaluates each bar twice: once with full history, once with the price
feed physically **truncated at that bar's close**. Any difference proves the strategy reads the
future.

> **96 signals compared, 0 mismatches. PASS.**

Structurally: higher-timeframe bars become visible only once closed (`htf_index`); a signal on
bar *i* is never filled on bar *i*; every ambiguity resolves against the account (bar touching
both stop and target → stop; gap through stop → filled at the gapped open; a limit filling
mid-bar may resolve the stop but never the target).

### Costs
Spread 0.9–3.0 pips (set at or above typical retail quotes), $7/lot round-turn commission,
0.3 pip entry slippage, 0.6 pip extra on stops. P&L converted to USD at the live cross-rate for
each timestamp.

### The headline test: anchored walk-forward
Nothing is fixed in advance. Inside each training window the procedure re-selects **from
scratch** — signal timeframe, target, stop buffer, score threshold, and watchlist — then trades
the next 3 months with that frozen choice.

| test block | tf chosen | target | threshold | train PF | trades | win rate | PF |
|---|---|---|---|---|---|---|---|
| 2025-04..06 | H4 | 2.0R | 70 | 1.413 | 17 | 41.2% | 1.351 |
| 2025-07..09 | H4 | 1.0R | 60 | 1.546 | 23 | 43.5% | 0.727 |
| 2025-10..12 | H4 | 1.0R | 60 | 1.292 | 27 | 70.4% | 2.200 |
| 2026-01..03 | H4 | 1.0R | 70 | 1.482 | 16 | 62.5% | 1.560 |
| 2026-04..06 | H4 | 1.0R | 70 | 1.494 | 10 | 70.0% | 2.216 |
| 2026-07..08 | H4 | 1.0R | 70 | 1.547 | 8 | 37.5% | 0.633 |

Pooled: **101 trades, 55.5% win rate, PF 1.339, +0.155R expectancy.** No window is ever used for
both selection and evaluation, so this cannot be contaminated by re-examining a test set.

### The win-rate / profit-factor trade-off, measured out of sample
Same walk-forward, target forced to each value:

| target | win rate | profit factor | expectancy |
|---|---|---|---|
| 0.6R | **67.74%** | 1.184 | +0.061R |
| **1.0R** | **60.55%** | **1.467** | **+0.188R** |
| 1.5R | 51.65% | 1.524 | +0.260R |
| 2.0R | 41.38% | 1.314 | +0.183R |

1.0R is the best joint point — and, importantly, it is what the **unconstrained** walk-forward
picked on training data alone in 5 of 6 cycles, before this table was produced. It was not
chosen from this table.

---

## 4. Complete $10,000 walk-forward — balanced mode

| Block | Threshold | Trades | Win rate | P/L | Start | End |
|---|---|---|---|---|---|---|
| 2025-04..06 | 50 | 21 | 71.4% | +$429.37 | $10,000.00 | $10,429.37 |
| 2025-07..09 | 65 | 19 | 47.4% | −$79.25 | $10,429.37 | $10,350.12 |
| 2025-10..12 | 65 | 20 | 70.0% | +$363.68 | $10,350.12 | $10,713.80 |
| 2026-01..03 | 65 | 19 | 47.4% | −$80.09 | $10,713.80 | $10,633.71 |
| 2026-04..06 | 70 | 7 | 71.4% | +$144.45 | $10,633.71 | $10,778.16 |
| 2026-07..08 | 70 | 7 | 42.9% | −$65.35 | $10,778.16 | **$10,712.81** |

| Metric | Value |
|---|---|
| Starting / ending balance | $10,000.00 → **$10,712.81** |
| Net profit | **+$712.81 (+7.13%)** |
| Total / winning / losing trades | 93 / 55 / 38 |
| Win rate | 59.14% |
| Average win / loss | $48.52 / −$51.47 |
| Profit factor | 1.364 |
| Expectancy | +$7.66 (+0.155R) |
| Avg planned R:R / realized | 0.886 / 0.943 |
| Max drawdown | $220.31 (2.11%) |
| Recovery factor | 3.235 |
| Sharpe / Sortino | 1.053 / 0.707 |
| Largest win / loss | $52.37 / −$56.07 |
| Longest win / loss streak | 8 / 4 |
| Avg trade duration | 32.8 hours |
| Trades per day | 0.149 |

Exit breakdown: 55 targets (+0.979R avg, +$2,668.53), 37 stops (−1.038R, −$1,899.95),
1 stop-gap (−1.055R, −$55.79). **No time-stop exits at all.**

### Monthly (balanced)

| Month | Trades | Win rate | P/L | PF | Max DD | Ending balance |
|---|---|---|---|---|---|---|
| 2025-04 | 7 | 42.9% | −$48.35 | 0.74 | 1.40% | $9,951.65 |
| 2025-05 | 7 | 71.4% | +$131.90 | 2.30 | 0.51% | $10,083.55 |
| 2025-06 | 7 | 100.0% | +$345.81 | ∞ | 0.00% | $10,429.37 |
| 2025-07 | 4 | 25.0% | −$111.58 | 0.30 | 0.57% | $10,317.79 |
| 2025-08 | 6 | 33.3% | −$104.85 | 0.40 | 0.53% | $10,212.93 |
| 2025-09 | 9 | 66.7% | +$137.18 | 1.89 | 0.99% | $10,350.12 |
| 2025-10 | 7 | 71.4% | +$135.47 | 2.26 | 1.02% | $10,485.59 |
| 2025-11 | 5 | 60.0% | +$38.81 | 1.36 | 1.02% | $10,524.40 |
| 2025-12 | 8 | 75.0% | +$189.40 | 2.75 | 0.51% | $10,713.80 |
| **2026-01** | 6 | 33.3% | −$115.53 | 0.47 | 1.50% | $10,598.27 |
| **2026-02** | 3 | 100.0% | +$152.32 | ∞ | 0.00% | $10,750.59 |
| **2026-03** | 10 | 40.0% | −$116.88 | 0.63 | 1.95% | $10,633.71 |
| **2026-04** | 0 | — | $0.00 | — | — | $10,633.71 |
| **2026-05** | 4 | 75.0% | +$97.98 | 2.82 | 0.50% | $10,731.69 |
| **2026-06** | 3 | 66.7% | +$46.47 | 1.83 | 0.51% | $10,778.16 |
| **2026-07** | 3 | 33.3% | −$55.99 | 0.48 | 0.47% | $10,722.16 |
| **2026-08** (to 21st) | 4 | 50.0% | −$9.36 | 0.92 | 0.51% | **$10,712.81** |

9 of 16 active months profitable. **The requested Jan–Aug 2026 stretch is almost exactly flat
on its own: $10,713.80 → $10,712.81, a loss of $0.99 (−0.009%).** All of the profit was earned
in 2025. That matters — the specific window the brief asked about is break-even, and the
positive headline comes from the longer walk-forward. **April 2026 produced no qualifying setup
at all** and the bot stood down rather than forcing trades.

---

## 5. Pair-by-pair (walk-forward, 93 trades over 23 instruments)

| Pair | Trades | Win rate | Net | PF | Avg R | W/L streak | Grade |
|---|---|---|---|---|---|---|---|
| EURGBP | 7 | 100.0% | +$351.44 | ∞ | +0.975 | 7 / 0 | A |
| EURCAD | 6 | 100.0% | +$288.02 | ∞ | +0.979 | 6 / 0 | A |
| GBPAUD | 3 | 100.0% | +$138.24 | ∞ | +0.988 | 3 / 0 | B |
| AUDUSD | 9 | 66.7% | +$137.50 | 1.90 | +0.306 | 6 / 2 | A |
| EURAUD | 2 | 100.0% | +$100.36 | ∞ | +0.980 | 2 / 0 | C |
| EURJPY | 2 | 100.0% | +$97.20 | ∞ | +0.993 | 2 / 0 | C |
| AUDCAD | 4 | 75.0% | +$91.89 | 2.71 | +0.466 | 2 / 1 | B |
| GBPUSD | 1 | 100.0% | +$50.94 | ∞ | +0.989 | 1 / 0 | C |
| NZDJPY | 3 | 66.7% | +$47.80 | 1.94 | +0.303 | 2 / 1 | C |
| USDCHF | 5 | 60.0% | +$47.67 | 1.46 | +0.174 | 2 / 1 | B |
| CHFJPY | 1 | 100.0% | +$47.45 | ∞ | +0.989 | 1 / 0 | C |
| CADJPY | 1 | 100.0% | +$47.44 | ∞ | +0.992 | 1 / 0 | C |
| XAUUSD | 2 | 50.0% | −$1.21 | 0.95 | −0.005 | 1 / 1 | D |
| USDCAD | 4 | 50.0% | −$6.36 | 0.94 | −0.041 | 2 / 1 | D |
| EURUSD | 4 | 50.0% | −$8.43 | 0.92 | −0.031 | 2 / 2 | D |
| GBPCHF | 6 | 50.0% | −$9.56 | 0.94 | −0.022 | 2 / 2 | D |
| AUDNZD | 3 | 33.3% | −$54.86 | 0.48 | −0.374 | 1 / 2 | F |
| AUDJPY | 5 | 40.0% | −$61.66 | 0.61 | −0.229 | 2 / 3 | F |
| EURCHF | 7 | 42.9% | −$72.50 | 0.67 | −0.188 | 3 / 4 | F |
| GBPJPY | 6 | 33.3% | −$102.45 | 0.48 | −0.358 | 2 / 3 | F |
| NZDUSD | 6 | 33.3% | −$106.55 | 0.49 | −0.372 | 1 / 3 | F |
| USDSGD | 2 | 0.0% | −$106.65 | 0.00 | −1.044 | 0 / 2 | F |
| GBPCAD | 4 | 0.0% | −$202.93 | 0.00 | −1.028 | 0 / 4 | F |

12 of 23 pairs profitable. **No pair earns A+** — every per-pair sample is 1–9 trades, which is
far too small to grade reliably, and the grades above should be read as descriptive only.

---

## 6. Automatic pair filtering — the brief's §7 rule measurably HURTS

The brief asks for pairs failing the minimums to be removed automatically. That filter is
implemented (`select_pairs.py`) and applied inside every walk-forward cycle. **It costs money:**

| | Trades | Win rate | PF | Net |
|---|---|---|---|---|
| Filtered watchlist | 42 | 57.14% | 1.255 | **+$230.36 (+2.30%)** |
| **All 24 pairs** | 93 | 59.14% | 1.364 | **+$712.81 (+7.13%)** |

Why: pair-level performance does not persist. In v1 the overlap between the watchlist chosen on
training data and the one the test period would have chosen was **zero pairs**. Per-pair samples
are 1–9 trades — pure noise — so filtering on them discards good pairs as often as bad ones and
mainly just shrinks the sample.

**Recommendation: trade the full universe and let the per-setup quality gates do the filtering.**
This directly contradicts §7 of the brief, and the table above is why. Both variants are
implemented; `--filtered` is available if you want the brief's behaviour.

The filter's verdicts on in-sample data, for the record:

| Approved (7) | Rejected — reason |
|---|---|
| EURCAD, AUDNZD, EURGBP, CHFJPY, EURCHF, XAUUSD, AUDUSD | USDSGD, AUDCAD, USDCAD (win rate 50% < 60%) · GBPCHF, USDCHF (57.1% < 60%) · EURAUD, GBPJPY (40% < 60%) · GBPAUD (42.9%) · GBPCAD, NZDUSD (28.6%) · AUDJPY (25%) · EURUSD, GBPUSD, EURJPY, CADJPY, USDJPY, NZDJPY (insufficient setups) |

Note AUDNZD and EURCHF were **approved** and then lost money, while EURGBP-style performers were
mostly rejected — the filter got it backwards, as expected from noise.

---

## 7. Risk analysis

| Metric | Value |
|---|---|
| Active trading days | 79 |
| Losing days | 30 of 79 (38.0%) |
| Worst day | −$185.49 (−1.7%) |
| Best day | +$101.02 |
| Days breaching the 2% daily cap | **0** |
| Max trades in one day | 4 |
| Mean trades per active day | 1.18 |
| Longest losing streak | 4 trades |
| Max drawdown | $220.31 (2.11%) |
| Long trades | 56, 64.3% WR, +$721.45 |
| Short trades | 37, 51.4% WR, −$8.66 |

Drawdown of 2.1% against a 7.1% return is the strongest single number here (recovery factor
3.24). Risk controls held throughout: no daily-cap breach, no martingale, position size fixed at
0.5% of equity (0.35% on gold).

**Shorts are near-worthless** (51.4% win rate, −0.006R expectancy) while longs carry the entire
edge. Over 2024–2026 this may simply reflect a persistent dollar-weakness regime. I have **not**
made the bot long-only — that would be fitting to the sample, and the regime can flip.

---

## 8. The quality score still does not discriminate out of sample

In-sample at H4 the score looked genuinely predictive — median PF rose monotonically with the
threshold (1.202 → 1.365 → 1.687 for thresholds 0/60/70). **Out of sample it flattens:**

| score band | trades | win rate | expectancy |
|---|---|---|---|
| ≤65 | 8 | 62.5% | +0.232R |
| 65–70 | 16 | 50.0% | −0.028R |
| 70–75 | 29 | 62.1% | +0.212R |
| 75–100 | 40 | 60.0% | +0.171R |

Correlation with outcome: **+0.024**. The score works as a *gate* (it removes the weakest
setups and every band above the floor is profitable), but it does **not** rank trades. Do not
size positions by score. This is reported rather than rebuilt, because rebuilding it against
the same data is how it would become overfitted.

---

## 9. Trade examples

**Winner — EURGBP, target hit, +0.975R.** Daily and weekly bias both up; price wicked below the
prior 20-bar low, closed back inside, then an H4 bar closed above the pre-sweep 3-bar high with
a body over 0.45×ATR. Limit rested at 62% back into that leg and filled. EURGBP went 7-for-7 in
the walk-forward — small sample, but every trade followed this identical shape.

**Winner — AUDUSD, 9 trades, 66.7%, +$137.50, PF 1.90.** The most *credible* winner because the
sample is largest and the win rate is realistic rather than perfect.

**Loser — GBPCAD, 0 for 4, −$202.93.** Every trade a full −1R stop, the worst losing streak in
the run. All four passed every gate. This is what an ordinary losing streak looks like in a
system with a real but modest edge — and it is why the 4-consecutive-loss lockout exists.

**Loser — USDSGD, 0 for 2, −$106.65 (−1.044R avg).** Losses slightly exceed 1R because spread
and commission are charged on top of the stop.

**Rejected setups.** The bot stands down on **99.7%** of bars. On EURUSD across 2026, of 15,932
bars examined: 66.7% outside session, 14.6% no liquidity sweep, 6.7% no clear daily trend, 5.8%
sweep never reclaimed, 5.2% H4/D1 conflict, 0.3% weak confirmation candle — **0.32% accepted**.
Selectivity is real and deliberate; April 2026 produced zero trades.

---

## 10. Final bot rules

**Markets:** all 24 FX pairs + XAUUSD. **Signal timeframe:** H4. **Context:** D1 + W1.

**Pre-conditions (all must hold):**
1. ATR(14)/price between 0.025% and 1.25%
2. Spread ≤ 45% of ATR(14)
3. Daily bias non-neutral (close vs EMA50 vs EMA200 agree)
4. Weekly/H4 bias does not contradict the daily bias

**Entry trigger (all must hold, direction = higher-timeframe bias):**
5. **Liquidity sweep** — within the last 6 bars, a bar wicked beyond the prior 20-bar extreme
   and closed back inside it
6. **Structure shift** — the current bar closes beyond the 3-bar extreme preceding the sweep
7. **Displacement** — body ≥ 0.45 × ATR, closing in the trade direction
8. **Location** — the sweep extreme sat in the lower 45% (longs) / upper 45% (shorts) of the
   40-bar range
9. **Extension** — price within 1.6 × ATR of EMA20
10. **Quality score ≥ 60/100**

**Order:** limit at 62% retracement of the displacement leg, GTC, expires after 6 bars,
cancelled if the stop level trades first.

**Stop:** sweep extreme ± 0.5 × ATR(14).
**Target:** 1.0R (balanced) or 0.6R (high win rate). No partials, no breakeven stop — both
measurably reduced expectancy. Time stop 40 bars (effectively inert; chosen as a plateau).

**Risk:** 0.5% equity per trade (0.35% gold) · max 3 concurrent · max 2 positions sharing a
currency · max 3 trades/day · 2% daily loss cap · 4-consecutive-loss lockout. Never increase
size after a loss.

---

## 11. Honest limitations — read before risking money

1. **The sample is small.** 93 walk-forward trades over 17 months. At 95% confidence a 59.1%
   win rate on 93 trades spans roughly 49–69%. The edge is real in this data but not tightly
   bounded.
2. **Frequency is far below the brief.** 0.15 trades/day, not 2–3. H4 systems are simply
   selective; forcing more trades means loosening gates, which is what failed in v1. April 2026
   had none at all.
3. **Reward-to-risk is below 1** (0.886 balanced, 0.509 high-win-rate). The brief asks for both
   a 60–90% win rate *and* a strong R:R. The measured trade-off table in §3 shows those are
   mutually exclusive here — you buy win rate with R:R, one for one. This is arithmetic, not a
   tuning failure.
4. **One disclosure.** The time-stop parameter was re-examined after the 2026 split had been run
   once, because time-exits were visibly carrying the loss there. The re-examination used
   in-sample data only, but that split has now been looked at twice, which is exactly why the
   **walk-forward** — where no window is ever reused — is the headline number rather than the
   single split.
5. **Shorts carry no edge in this sample.** Possibly regime, possibly noise.
6. **Live results will be worse than backtest.** Real spreads widen around news and rollover;
   these are modelled as constants.
7. **Rotate the account password.** It was shared in plaintext in the task.

**Suggested path:** run `--demo --mode balanced` for 2–3 months (~10–20 trades), compare the
realized profit factor against 1.36, and only then consider live with the smallest size your
broker allows.

---

## Appendix — reproducing this

```bash
export TL_EMAIL=... TL_PASSWORD=... TL_SERVER=PULSE TL_ENV=live
python3 tl_data.py               # real M15 back to 2023-06 (data/, gitignored)
python3 test_no_lookahead.py     # look-ahead verification
python3 improve.py               # in-sample timeframe / structure search
python3 walkforward_full.py      # fully uncontaminated walk-forward
python3 final_backtest.py        # the $10,000 headline result
python3 live_bot.py --dry-run
```

Outputs: `final_results.json`, `trades_walkforward.csv`, `walkforward_full.csv`,
`improve_insample.csv`, `pair_selection_insample.csv`.
