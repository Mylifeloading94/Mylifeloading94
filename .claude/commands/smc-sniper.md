# SMC Sniper AI Forex Trading Bot

A Smart Money Concepts sniper system: multi-timeframe bias, liquidity sweeps,
market-structure shifts, order blocks / fair value gaps, and a hard scoring
gate. Built to the owner's spec, backtested on real broker data, and reported
honestly.

---

## STATUS — read this first  ·  **v5**

**Do not trade any of this live.**

v5 was asked to hunt for defects, reach three trades a day at 1:2–1:5, and
deliver a 90-day workbook at 1% and 2% risk. The bug hunt is where the value
was: **eight real defects, two of them lookahead**. The frequency target is
measured to a definite answer and the answer is **no**.

| | **v2** | **v3 scalper** | **v5 (adopted)** |
|---|---|---|---|
| Setup timeframe | 1H | 15m (5m fills) | **1H** |
| Target | liquidity ladder | ladder | **flat 4R, no management** |
| Full window (~1200d) | 153 tr, 54.90%, PF 1.260, +0.114R | 1888 tr, 43.64%, PF 0.749, −0.131R | **144 tr, 32.64%, PF 1.341, +0.2438R** |
| Break-even win rate | — | — | **20.0% — cleared by 12.6 points** |
| Walk-forward OOS | 132 tr, 55.30%, +0.107R | 362 tr, 39.78%, −0.204R | **125 tr, 32.80%, PF 1.345, +0.2466R** |
| Expectancy 95% CI | −0.061 to +0.286 | entirely below zero | **−0.071 to +0.560** |
| CI clear of zero? | NO | yes — WRONG side | **NO** |
| Max drawdown | 3.98% | 124% | **7.06%** |
| Longest losing streak | 5 | 12 | **15** |
| Trades/day | 0.17 | 3.78 | **0.12** |
| **3 trades/day reached?** | NO | YES (losing) | **NO** |

**The audit is the headline.** Two lookaheads (an order-block quality rank
reading two bars into the future on 11.16% of 88,299 blocks; the risk engine
booking P/L at signal time), a commission ~190× too small on every JPY cross
(36% of v2's trades were effectively commission-free), a fill-window off-by-one,
a take-profit that filled on a touch while the entry required trade-through,
break-even exits scored as wins, a matched-R control that was never
entry-matched, and a risk cap that silently turned a requested 2% into 1%. All
eight are fixed, each behind a flag defaulting to the old behaviour, so
`run_backtest.py --stack swing` still returns **exactly** v2's 153 / 54.90% /
1.260 / +0.114R.

**Fixing them moved the honest v2 number from +0.114R to +0.126R and its
out-of-sample half from +0.083R to +0.032R — the lookahead was flattering the
part that matters most.**

**Three trades a day is not reachable with a positive expectancy, and the whole
frontier is now measured.** 1H tops out at 0.62 trades/day and is negative
there; a new 30m rung tops out at 1.25/day and is negative at every score gate
on TRAIN and TEST independently; only 15m reaches 3.78/day, and that is the one
configuration in this repo whose confidence interval is clear of zero — below
it. **The achievable frequency on a working engine is about 0.12 trades a day.**

**The 90-day $100k deliverable is five trades**, −3.83% at 1% risk and −7.56% at
2%. Five trades cannot evaluate anything; the ~1200-day number is the one that
means something, and its interval still contains zero.

**Forward results: still PENDING DEMO RUN.** Nothing in this repo has ever
placed an order.

---

## STATUS — v3 (superseded, kept for continuity)

v3 was asked for a scalping system with a 70%+ win rate at 3+ trades a day. It
built one, measured it properly, and the answer is negative: **the SMC entry
model does not survive the move to a scalping timeframe.** On 15m setups with
5m fills, over 700 days and 29 pairs, it loses money at every score gate, every
cost gate, every target width and every pair subset tested — 40 configurations,
not one positive on both splits.

v3 also produced this repo's best measured configuration, by accident and on
the *swing* stack: v2's flagged flat-4R lead **replicated** and is now
`profiles.swing_4r` (+0.263R, PF 1.375 — at a 32.89% win rate).

| | **v1** | **v2** | **v3 scalper** | **v3 `swing_4r`** |
|---|---|---|---|---|
| Setup timeframe | 1H | 1H | **15m (5m fills)** | 1H |
| Window | ~1200d | ~1200d | **~700d** | ~1200d |
| Full window | 151 tr, 53.64%, PF 1.113, +0.052R | 153 tr, 54.90%, PF 1.260, +0.114R | **1888 tr, 43.64%, PF 0.749, −0.131R** | **149 tr, 32.89%, PF 1.375, +0.263R** |
| Expectancy 95% CI | −0.119 to +0.221 | −0.061 to +0.286 | **entirely below zero** | **−0.042 to +0.574** |
| CI clear of zero? | NO | NO | **yes — on the WRONG side** | NO (narrowest yet) |
| Trades/day | 0.17 | 0.17 | **3.78** | 0.17 |
| **70% WR reached?** | NO | NO | **only at a 0.5R target, where it loses money** | NO — 32.9% |
| **3 trades/day reached?** | NO | NO | **YES** | NO |

**The two owner targets pull against each other and the frontier is measured,
not argued.** A flat 0.5R target gives 71.57% WR on TRAIN and 68.33% on TEST —
essentially the 70% — at 2.13 trades a day and **−0.086R per trade**. Loosening
the score gate to 55 gives 3.78 trades a day at **−0.131R**. Both targets are
individually reachable. Neither is reachable profitably, and they are not
reachable together.

**The scalper's failure is not a cost problem, and that took ruling out three
ways.** Gross expectancy before commission is −0.119R against a commission drag
of 0.033R; the broker's real live spreads (~3× narrower than the backtester's
deliberately conservative ones) still lose; and restricting to the five pairs
where the spread is under 10% of R makes the out-of-sample result *worse*
(−0.230R). The entries do not work at this timeframe.

**Forward results: still PENDING DEMO RUN.** Nothing in this repo has ever
placed an order.

---

## v5 — the audit, and the frequency frontier measured to its end

The owner asked for four things: find and fix whatever is suppressing
performance, reach at least three trades a day at 1:2–1:5 reward-to-risk, run
the result at 1% and 2% risk, and deliver a clean 90-day workbook. The first
one is where the value was, and it produced **seven real defects**. The second
one is measured to a definite answer and the answer is **no**.

### The seven defects, with what each one cost

Each fix ships behind a flag that defaults to the OLD behaviour, so
`python3 run_backtest.py --stack swing` still returns exactly 153 trades /
54.90% WR / PF 1.260 / +0.114R. The `v5` profile turns them all on.

| # | Defect | Where | Measured impact |
|---|---|---|---|
| 1 | **Lookahead in the order-block quality rank.** The structure-event association window ran two bars PAST the bar the zone becomes knowable on, and it feeds `_rank_ob`, whose output gates admission through `order_blocks.min_quality`. | `zones.py::find_order_blocks` | **11.16% of 88,299 order blocks** had their quality decided by an event the market had not printed yet. Removing it: 153→149 trades, full expectancy +0.114R→+0.139R, **but TEST +0.083R→+0.045R** — the lookahead was flattering the out-of-sample half. |
| 2 | **Commission ~190× too small on every JPY cross.** `contract_value` returned a flat 100,000 for all non-metal pairs, which is only right when the QUOTE currency is USD. A 1.0-unit move on 1 lot of USDJPY is 100,000 *JPY*, ≈$666. | `risk.py::contract_value` | Commission drag by quote currency: USD **0.0359R**, CHF 0.0320R, CAD 0.0259R, NZD 0.0130R, AUD 0.0150R, **JPY 0.00019R**. 36% of v2's trades were effectively commission-free. Fixing it costs **−0.0123R** (+0.114 → +0.102). |
| 3 | **Lookahead in the risk layer.** `register` booked realised P/L, the consecutive-loss counter and the running balance at *signal* time, so the daily/weekly loss gates and the loss cooldown were evaluated against the outcome of positions that were still open. | `risk.py::register` | +1 trade, +0.0033R. Small on a stack that trades 0.13 times a day; structural on anything faster. |
| 4 | **Asymmetric fill rule.** The entry limit required trade-through; the take profit — also a resting limit — filled on a touch. | `backtest.py` | **Zero measurable change** on 1H float prices. Fixed anyway: the rule should be symmetric, and it will bite on a tick-quantised feed or around round numbers. |
| 5 | **Off-by-one in the fill window.** `end` is the first entry bar the limit is *already cancelled* for, and the scan ran `range(start, end + 1)`. `entry.valid_bars: 8` was really a 9-bar window, in the strategy's favour. | `backtest.py::simulate_trade` | (see round M) |
| 6 | **Break-even exits are scored as wins.** A stop moved to entry + 0.05R exits a hair above zero, so `r > 0` books it as a win. 7 of 153 v2 trades exit at **+0.010R to +0.045R having banked no partial at all** — price tagged +1R intrabar, which triggers the break-even move but does not reach a TP1 sitting further out. | `metrics.py` | With a ±0.10R scratch band: 10 scratches, win rate **54.90% → 53.85%**. About one point, not the ~15 the same defect class was worth in the uploaded bot, because here the partial P/L is genuinely realised rather than assumed. `win_rate` is left alone; `win_rate_ex_scratch` is reported beside it. |
| 7 | **The matched-R control is not entry-matched.** `min_rr` is applied to `rr_tp2`, which in `fixed_rr` mode is the flat multiple the config just asserted — so the reward-to-risk gate is inert for any flat target ≥ `min_rr` and lethal for any below it. `matched_r_control` papers over the second half by setting `min_rr = min(rr, 2.0)`, which means **every row of the matched-R table runs with the reward-to-risk filter switched off while the ladder baseline it is compared against runs with it on.** | `signal_engine.py`, `walkforward.py` | This is the check this repo leans on hardest — it is how `swing_4r` was adopted. (see round R) |

### What audited CLEAN — this is the valuable half

* **No wrong-side stops.** The defect that broke the uploaded bot — nothing
  verifying the stop is on the *losing* side of the entry — is structurally
  impossible here: the long stop anchor is
  `min(sweep.extreme, zone.bottom, recent lows) − buffer×ATR`, and `zone.bottom`
  is in that `min`, so the stop is always below the entry, which lies inside the
  zone. **Verified on all 153 v2 trades: zero wrong-side stops.**
* **No lookahead anywhere else.** Swings confirm at `index + lookback`;
  structure events read `closes[i]` with `active_high.index < i`; the bias array
  advances on `events[ev].index <= i`; `MTFView` maps every higher timeframe by
  `close_time <= setup_bar.close_time`; liquidity pools are indexed by the bar
  they become knowable (PDH from the first bar of the next day, session levels
  from the bar after the session's last); `detect_sweeps` breaks on
  `pool.index >= i`; zone invalidation is compared against the current bar; the
  volatility-regime rank is `.rolling(...).shift(1)`. The only remaining
  backfill is `atr()`'s `.bfill()` over the first ~6 bars of a frame, and signal
  generation starts at bar 30.
* **No double-counting of a liquidity event.** Across 153 trades: **one** pair of
  same-symbol/same-direction entries within 24 hours, **zero** overlapping
  positions on the same pair, maximum **3** simultaneous positions portfolio-wide.
* **Contract specs and pip sizes are right.** XAUUSD `pip: 0.1` with a 100 oz
  contract quoted in USD; JPY crosses `pip: 0.01`; everything else `0.0001`.
  The gold spread of 25 pips is $2.50. R-multiples and dollar P/L were never
  affected by defect 2 — `pnl` is `R × risk_amount` — only `size_lots` and the
  per-lot commission were.
* **The entry mechanics are already at their optimum.** Twenty variants, selected
  on TRAIN, scored on an untouched TEST. **Not one beats the baseline on both.**

### Round E — entry mechanics, stop calibration, sequencing

| Change | TRAIN E | TEST E | Verdict |
|---|---|---|---|
| baseline (all fixes on) | **+0.106R** | **+0.032R** | reference |
| fill depth 0.0 (zone edge) | −0.003 | +0.171 | REJECTED — TRAIN collapses |
| fill depth 0.25 | +0.036 | +0.061 | REJECTED |
| **fill depth 0.5 (default)** | **+0.106** | **+0.032** | the TRAIN peak |
| fill depth 0.75 | −0.028 | +0.047 | REJECTED |
| fill depth 1.0 (far edge) | −0.035 | +0.120 | REJECTED |
| fill window 4 bars | +0.062 | +0.058 | REJECTED |
| fill window 6 | +0.081 | +0.032 | REJECTED |
| **fill window 8 (default)** | **+0.106** | **+0.032** | the TRAIN peak |
| fill window 12 | +0.068 | +0.087 | REJECTED |
| fill window 16 | −0.014 | +0.133 | REJECTED |
| **zone-must-form-after-sweep OFF** | +0.088 | **−0.012** | REJECTED — the sequencing rule earns its place on BOTH splits |
| sweep recency 3 bars | **+0.136** | −0.041 | REJECTED — inverts |
| sweep recency 4 | −0.010 | +0.026 | REJECTED |
| sweep recency 8 | +0.060 | +0.074 | REJECTED |
| sweep recency 10 | +0.080 | −0.075 | REJECTED |
| stop buffer 0.15×ATR | +0.091 | −0.043 | REJECTED |
| **stop buffer 0.35×ATR** | **+0.191** | **−0.051** | REJECTED — the loudest TRAIN result in the round, and it inverts |
| stop buffer 0.50×ATR | +0.135 | −0.044 | REJECTED |
| min stop 0.50×ATR | +0.112 | −0.005 | REJECTED |
| min stop 1.00×ATR | +0.086 | +0.032 | REJECTED |
| min stop 1.30×ATR | +0.088 | −0.025 | REJECTED |
| PD hard veto 0.65 | +0.073 | +0.076 | REJECTED — hurts TRAIN |
| PD hard veto 0.75 | +0.085 | +0.032 | REJECTED |
| PD hard veto 0.95 | −0.002 | +0.052 | REJECTED |

**The answer to "is the zone midpoint the best fill reference" is yes, and it is
not close.** Both edges cost TRAIN expectancy, and the far edge costs 10% of the
trades as well. The answer to "is the fill window sensible" is also yes: 8 setup
bars is the TRAIN peak in both directions. The answer to "must the zone form
after the sweep" is yes and it is the only rule in the round that is better on
*both* splits.

### Round F — is there a rung between the 1H model that works and the 15m one that does not?

v3 established that the SMC entry model loses money on a 15m setup. v5 built the
missing rung: a **30m setup timeframe**, resampled from the native 15m cache,
under the swing stack's own higher-timeframe context (1D bias / 4H structure,
15m fills), ~700 days, 29 pairs, all audit fixes on, concurrency caps raised so
the risk engine is not the binding constraint.

| Score gate | Trades | Trades/day | Win rate | PF | Full E | TRAIN E | TEST E |
|---|---|---|---|---|---|---|---|
| 80 | 138 | 0.20 | 39.86% | 0.676 | −0.184R | −0.158 | −0.086 |
| 75 | 292 | 0.42 | 41.44% | 0.679 | −0.183R | −0.182 | −0.021 |
| 70 | 387 | 0.56 | 42.89% | 0.673 | −0.186R | −0.138 | −0.045 |
| 65 | 609 | 0.88 | 43.35% | 0.739 | −0.143R | −0.076 | −0.111 |
| 60 | 808 | **1.16** | 45.17% | 0.784 | −0.114R | −0.074 | −0.066 |
| 55 | 872 | **1.25** | 43.23% | 0.734 | −0.146R | −0.100 | −0.108 |

**Negative at every gate, on TRAIN and TEST independently — and it tops out at
1.25 trades a day.** The 30m rung fails twice: it does not work, and even
wide open it cannot deliver the frequency. The break is between 1H and 30m, not
between 30m and 15m.

### The win rate / reward-to-risk trade-off, stated plainly

This is the single most important thing in the report, so it is stated in
words before the table.

**A win rate on its own is not information.** A trade that risks 1 to make 0.5
needs to win 67% of the time just to break even. A trade that risks 1 to make 4
needs to win 20%. So a 70% win rate at a 0.5R target and a 35% win rate at a 4R
target are not "70 versus 35" — they are "70 against a 67 break-even line" and
"35 against a 20 break-even line". The first clears its bar by 3 points. The
second clears its bar by 15.

That is why **35% at 4R beats 70% at 0.5R**, and it is not a close call. This
repo has already measured the 0.5R case directly: the v3 scalper hit **70.18%**
win rate at a flat 0.5R target and still lost **0.086R per trade**, because the
round-trip cost is a double-digit percentage of R at that target width. The win
rate was real. The money was not.

Every configuration below is reported with its break-even line beside it, so
the comparison is never win rate against win rate.

### Is three trades a day reachable? No.

Plainly: **no.** Here is the whole frontier this repo has now measured, on one
axis, so the answer is checkable rather than asserted.

| Stack | Setup TF | Best honest expectancy | Trades/day at that setting | Trades/day wide open | Expectancy wide open |
|---|---|---|---|---|---|
| swing (v5) | **1H** | **positive** | ~0.13 | (see round R gates) | |
| mid30_swing (v5) | 30m | −0.114R | 1.16 | 1.25 | −0.146R |
| scalp15 (v3) | 15m | −0.131R | 3.78 | 3.78 | −0.131R |
| scalp5 (v3) | 5m | rejected on cost arithmetic before any backtest | 0.02 | — | — |

**The only stack in this repo that reaches three trades a day is the 15m one,
and it is the one configuration here whose confidence interval is clear of zero
— on the wrong side.** It loses 0.131R per trade over 1,888 trades, with TRAIN
and TEST agreeing. The 30m rung built specifically to bridge the gap tops out at
1.25 trades a day and is negative at every score gate. The 1H stack that works
trades roughly once a week.

Every lever the brief named was tried:

* **Wider pair universe** — already 29 pairs, and the 16 added in v2 are
  frequency rather than edge (negative on TRAIN on their own).
* **A lower score gate** — measured on both the 1H and 30m stacks. On 30m the
  win rate barely moves across a 25-point gate range, which says the score card
  carries no marginal information below 1H.
* **Concurrent positions** — `max_open_positions` and `max_exposure_per_currency`
  were inert until v3 fixed them, and v5 measured what they actually bind at:
  the natural maximum on the 1H stack is **exactly 3 simultaneous positions**,
  the configured cap. Raising it buys nothing because the constraint is setup
  supply.
* **`risk.max_trades_per_day: 3`** — this one WOULD bind at the target
  frequency and never binds today, so it was raised to 30 in every frequency
  experiment to make sure the risk engine was not the thing being measured.
* **An intermediate timeframe** — built, measured, negative.

**The achievable frequency on a working engine is about 0.13 trades a day**
(roughly one a week across 29 pairs), rising to the values in the gate table
below at a cost in expectancy that is stated there. Manufacturing 3/day means
moving to a timeframe this repo has now measured as loss-making twice, at two
different resolutions. That is not a trade worth making, and the brief said so:
*if 3/day is not honestly reachable without destroying expectancy, say so.*

### Round R — the reward-to-risk frontier, on an entry-matched control

Management stripped off, one flat target at each R, and — for the first time in
this repo — the reward-to-risk gate evaluated against the liquidity that is
actually there, so **every row selects the same entries** (144–146 trades
against the ladder's 149; audit defect 7). ~1200 days, 29 pairs, all fixes on.

| Target | Trades | Win rate | Break-even WR | Clears by | PF | Full E | TRAIN E | TEST E | Max DD |
|---|---|---|---|---|---|---|---|---|---|
| ladder (liquidity TP1/TP2/TP3 + BE + trail) | 149 | **55.70%** | — | — | 1.289 | +0.126R | +0.106 | +0.032 | 2.31% |
| flat 1.0R | 150 | **59.33%** | 50.0% | +9.3 | 1.198 | +0.085R | +0.022 | −0.034 | 2.62% |
| flat 1.5R | 146 | 47.95% | 40.0% | +8.0 | 1.133 | +0.075R | +0.069 | +0.023 | 3.65% |
| **flat 2.0R** | 146 | 43.15% | 33.3% | +9.8 | 1.233 | +0.141R | +0.104 | +0.157 | 3.62% |
| flat 2.5R | 146 | 37.67% | 28.6% | +9.1 | 1.177 | +0.119R | +0.080 | +0.134 | 4.32% |
| **flat 3.0R** | 144 | 36.11% | 25.0% | +11.1 | 1.271 | +0.186R | +0.188 | +0.142 | 4.56% |
| **flat 3.5R** | 144 | 34.03% | 22.2% | +11.8 | 1.307 | +0.215R | +0.187 | +0.267 | 4.85% |
| **flat 4.0R — ADOPTED** | 145 | **33.10%** | 20.0% | **+13.1** | **1.378** | **+0.267R** | **+0.185** | **+0.381** | 6.94% |
| flat 4.5R | 145 | 31.72% | 18.2% | +13.5 | 1.342 | +0.248R | +0.177 | +0.221 | 6.75% |
| **flat 5.0R** | 145 | 31.03% | 16.7% | +14.3 | 1.318 | +0.233R | **+0.234** | +0.087 | 6.49% |
| flat 6.0R (outside the brief) | 145 | 31.03% | 14.3% | +16.7 | 1.457 | +0.332R | +0.377 | +0.200 | 6.23% |

**Read the "clears by" column, not the win rate column.** Win rate falls
monotonically from 59% to 31% as the target widens — the correct mechanical
relationship — but the *margin over break-even* rises the whole way, from +9.3
points at 1R to +13.1 at 4R. A win rate bought by shrinking the target shows
the exact opposite shape. This system is not doing that.

**Why 4.0R and not 5.0R, which is the TRAIN argmax.** Three reasons, none of
them TEST:

1. **4R is pre-registered.** v2's matched-R sweep flagged it, v3 gave it a
   TRAIN/TEST cycle and it replicated, and v5 re-ran it on an audited engine
   with a control that is genuinely entry-matched. Confirming a stated
   hypothesis is a stronger position than picking an argmax.
2. **4R sits inside a plateau; 5R is a spike.** TRAIN runs +0.188 / +0.187 /
   +0.185 / +0.177 across 3.0–4.5R and then jumps to +0.234 at 5.0R with 4.5R
   *lower* on either side of it. A parameter with one convenient best value is
   the exact shape of v2's rejected lead (a).
3. **5R is at the edge of the owner's 1:2–1:5 band**, and 5R and 6R return the
   *identical* 31.03% win rate — the same 45 winners — which means everything
   past 5R rides on how far a handful of trends run rather than on the entry.

For the record and not as a justification: had the strict TRAIN argmax been
taken, TEST would have come back +0.087R instead of +0.381R.

### What the management ladder is actually doing

The brief asked whether partial-close and break-even mechanics interact badly
with anything. They do, and the direction is worth stating:

| Ladder variant | Trades | Win rate | Full E | TRAIN E | TEST E |
|---|---|---|---|---|---|
| ladder (all management on) | 149 | 55.70% | +0.126R | +0.106 | +0.032 |
| ladder, **break-even off** | 148 | **44.59%** | **+0.154R** | +0.095 | +0.145 |
| ladder, trailing off | 149 | 55.70% | +0.149R | +0.162 | −0.046 |
| ladder, partials off | 149 | 57.05% | +0.105R | +0.096 | −0.081 |

**Switching the break-even stop off costs 11 points of win rate and makes
money.** That is the whole win-rate/expectancy tension in one row: the
break-even mechanic converts trades that would have run into scratches booked
as wins (audit defect 6) and clips the runners that pay for the losers. It is
not adopted as a ladder change — TRAIN goes +0.106 → +0.095, and selection is
made on TRAIN — but it is the same force that makes the flat-4R configuration,
which has break-even off by construction, the better one.

None of the three management variants improves TRAIN, so the ladder is left
exactly as it was. The adopted configuration simply does not use it.

### The frequency frontier on the 1H stack, for completeness

| Score gate | Trades | Trades/day | Win rate | PF | Full E | TRAIN E | TEST E | Max DD |
|---|---|---|---|---|---|---|---|---|
| **80 (default)** | 149 | **0.13** | 55.70% | 1.289 | **+0.126R** | +0.106 | +0.032 | 2.31% |
| 75 | 332 | 0.28 | 53.01% | 1.042 | +0.022R | −0.008 | +0.020 | 6.74% |
| 70 | 425 | 0.36 | 54.35% | 1.082 | +0.037R | +0.022 | −0.032 | 6.06% |
| 65 | 728 | 0.62 | 50.14% | 0.890 | −0.053R | −0.108 | −0.067 | 23.69% |

**Even wide open, the 1H stack does not reach one trade a day** — and it stops
making money long before it gets there. Doubling the frequency to 0.28/day costs
82% of the expectancy; quintupling it to 0.62/day turns the system negative and
takes max drawdown from 2.3% to 23.7%.

Stack the three timeframes side by side and the frontier is complete:

| Achievable trades/day | 1H | 30m | 15m |
|---|---|---|---|
| 0.13 | **+0.126R** | — | — |
| 0.28–0.62 | +0.022 to −0.053R | — | — |
| 1.16–1.25 | — | −0.114 to −0.146R | — |
| 3.78 | — | — | −0.131R (CI clear of zero, below it) |

**There is no point on this surface with three trades a day and a positive
expectancy.** The owner's frequency target and the owner's profitability target
are on opposite sides of it.

### One more thing the flat target buys: an honest win rate

Every flat-R row above has **zero scratches**. The ladder has 10, and the ladder
with break-even removed has 20. A configuration with break-even and trailing
switched off cannot book a scratch as a win, because every trade ends at exactly
+4R or exactly −1R. When the number being quoted is a win rate, that matters
more than a tenth of an R.

### The adopted v5 configuration, fully validated

`profiles.v5` — 1D bias / 4H structure / 1H setup / 1H entry, 29 pairs, score
gate 80/95, session-extreme sweeps excluded, **flat 4R target with all
management stripped off**, all seven audit fixes on, ~1200 days of TradeLocker
1H bars.

| Split | Window | Trades | Win rate | PF | Expectancy |
|---|---|---|---|---|---|
| **IN-SAMPLE (train)** | 2023-05 → 2024-12 | 65 | 29.23% | 1.182 | +0.1318R |
| **VALIDATION** | 2024-12 → 2025-08 | 38 | 31.58% | 1.405 | +0.2871R |
| **OUT-OF-SAMPLE (test)** | 2025-08 → 2026-08 | 41 | 39.02% | 1.562 | +0.3814R |
| **FULL WINDOW** | 2023-05 → 2026-08 | **144** | **32.64%** | **1.341** | **+0.2438R** |
| **WALK-FORWARD (OOS only)** | 5 rolling folds | **125** | **32.80%** | **1.345** | **+0.2466R** |

* Win-rate 95% CI **25.00 – 40.28%**, against a **20.0%** break-even line at 4R.
* **Expectancy 95% CI [−0.0710R, +0.5597R] — IT STILL SPANS ZERO.**
* Walk-forward OOS CI [−0.0851R, +0.6010R] — also spans zero.
* Max drawdown **7.06%**. **Longest losing streak: 15.**
* **0.123 trades a day.** Average winner +2.874R, average loser −1.031R.

Walk-forward folds:

| Fold | Fit → OOS | Fit trades | Fit E | OOS trades | OOS WR | OOS E |
|---|---|---|---|---|---|---|
| 1 | 2023-05 → 2024-06 | 19 | +0.226R | 23 | 34.78% | **+0.270R** |
| 2 | 2023-11 → 2024-12 | 23 | +0.270R | 23 | 21.74% | −0.084R |
| 3 | 2024-06 → 2025-07 | 23 | −0.084R | 33 | 36.36% | **+0.489R** |
| 4 | 2024-12 → 2026-01 | 33 | +0.489R | 28 | 32.14% | −0.007R |
| 5 | 2025-07 → 2026-08 | 28 | −0.007R | 18 | 38.89% | **+0.589R** |

The walk-forward number (+0.2466R over 125 unseen trades) landing on top of the
full-window number (+0.2438R over 144) is the most reassuring line in this
document. Three of five folds are clearly positive, one is flat and one is
negative, on 18–33 trade folds — the spread the confidence interval is
describing.

Pair selection still refuses to select: no pair reaches 12 fit-window trades
(max 5 across 29 pairs), so every fold keeps everything and says so.

**This is a better configuration than v2 by every measure that matters — nearly
double the expectancy, a profit factor of 1.34, and a walk-forward that agrees
with the full window. It is still not an established edge.** The interval
contains zero. 144 trades cannot pin down a 33% win rate against a 20%
break-even line, and the difference between the two is the whole result.

### An eighth defect, found while building the deliverable

`Config.risk_per_trade_pct` **clamps** to `risk.risk_per_trade_max_pct`, which
the spec sets to 1.0. Asking the engine for 2% therefore returns a 1% run,
silently: the first draft of the 1% and 2% tables came back **bit-for-bit
identical** — same end balance to the cent — which reads as a copy-paste error
rather than as a clamp. `run_scalp_100k.py` raises the cap explicitly (so v3's
2% deliverable really was at 2%), but nothing warns a caller that does not.
`run_v5_100k.py` now raises it deliberately and says so.

The same block hides a second trap. The daily and weekly loss gates are
percentages of the account, so at 2% risk an untouched `max_daily_loss_pct: 2.0`
is tripped by **one** losing trade and `max_weekly_loss_pct: 5.0` by two and a
half. A 2% run against unscaled gates measures the circuit breaker, not the
strategy. Both are scaled with the risk step-up so that they bind at the same
*number of losing trades* at every risk level and the two runs stay comparable.

**2% is outside this system's own stated risk band** (`risk_per_trade_max_pct:
1.0`). It is produced because the owner asked for it, with the loss-streak
arithmetic printed beside it.

### Round H — the time stop against a wide target, matched-R

The adopted 4R configuration has an average winner of **+2.874R**, not the ~3.5R
a clean 4R fill nets after cost. That says trades are being closed by
`targets.max_hold_bars` before the target arrives, so the time budget was swept
with the target held fixed — and repeated at 2R so a time-stop effect could not
be mistaken for a target-width effect.

| Budget | 4R: % time-stopped | avg winner | Win rate | TRAIN E | TEST E | | 2R: TRAIN E |
|---|---|---|---|---|---|---|---|
| 48h | 24.8% | +2.381R | 34.04% | +0.101 | +0.250 | | +0.029 |
| **96h (default)** | 11.8% | **+2.874R** | 32.64% | **+0.132** | +0.381 | | **+0.079** |
| 192h | 2.1% | +3.497R | 27.97% | +0.039 | +0.355 | | +0.011 |
| 384h | 1.4% | +3.520R | 27.27% | −0.002 | +0.330 | | +0.011 |
| 720h | 0.7% | +3.583R | 26.57% | −0.002 | +0.276 | | +0.011 |

**The truncation is not a defect — it is doing real work.** Extending the budget
lets more trades reach the full 4R (average winner climbs to +3.58R) and the
win rate *falls* from 32.6% to 26.6%, because the positions the time stop used
to harvest in profit go on to hit their stop instead. 96 bars is the TRAIN
optimum in both directions, and the 2R control shows the identical shape, so it
is a property of the time stop rather than of the target. **Audited clean.**

### The $100,000 / 90-day deliverable, at 1% AND 2%

`profiles.v5`, most recent 90 days of broker data (2026-05-16 → 2026-08-14),
$100,000, compounding trade by trade, two independent runs.

| | **1% risk** | **2% risk** |
|---|---|---|
| Start balance | $100,000.00 | $100,000.00 |
| **End balance** | **$96,166.57** | **$92,436.37** |
| **Total profit** | **−$3,833.43** | **−$7,563.63** |
| **Total ROI** | **−3.83%** | **−7.56%** |
| Trades | **5** | **5** |
| Win rate | 20.00% (1 of 5) | 20.00% |
| Profit factor | 0.082 | 0.080 |
| Max drawdown | 4.18% | 8.22% |
| Longest losing streak | 4 | 4 |
| Trades per weekday | 0.078 | 0.078 |
| Active days | 5 of 91 | 5 of 91 |
| Expectancy CI | n=5 — refused | n=5 — refused |

Monthly: May 0.00%, June 0.00%, July −2.11% / −4.19%, August −1.76% / −3.52%.

**Five trades is not a result and this document will not pretend otherwise.** A
four-loss run is completely ordinary at a 33% win rate — it is the modal outcome
of five trades — and it is most of what this window contains. The same
configuration returns **+0.2438R over 144 trades** and **+0.2466R over 125
walk-forward trades**. Ninety days at 0.12 trades a day cannot distinguish a
working system from a broken one, and the bootstrap interval is **refused**
rather than reported below 30 trades, because an interval on five trades is not
evidence in either direction.

This is the third time this repo has produced a thin 90-day deliverable, and the
reason is structural rather than unlucky: the configurations with an edge do not
trade often enough for a quarter to detect it, and the configuration that trades
often enough has no edge. That sentence is the whole session.

### What 2% actually implies here

2% is **outside this system's own stated risk band** (`risk_per_trade_max_pct:
1.0`). It is produced because it was asked for, with the arithmetic beside it.

| | |
|---|---|
| Longest losing streak in the 90-day window | 4 |
| **Longest losing streak over the full ~1200 days** | **15** |
| Drawdown from that 15-loss streak at **1%** | **14.0%** |
| Drawdown from that 15-loss streak at **2%** | **26.1%** |
| Consecutive losses needed to lose 20% at 2% | 11 |
| Probability of a single loss | **0.67** |

A 15-loss streak sounds extreme and is not: at a 67% loss rate over 144 trades
the *expected* longest run is about 12, so 15 is ordinary. **At 2% that ordinary
run is a 26% drawdown, and the expectancy interval still contains zero** — which
means the system is not yet known to make the money back. On a configuration
with a demonstrated edge 2% would be aggressive. On this one it is a bet that
the edge is real, sized as though it already were.

At 1% the same streak costs 14%. That is not an argument that 1% is safe; it is
the same bet at half the stake.

### v5 caveats

1. **The expectancy CI still spans zero.** [−0.0710R, +0.5597R] on the full
   window, [−0.0851R, +0.6010R] walk-forward. This is the best configuration
   this repo has measured and it is still not an established edge. Getting this
   interval clear of zero remains the most valuable available outcome and **v5
   did not achieve it either.**
2. **Two of the eight defects were flattering the out-of-sample half.** Honest
   v2 TEST expectancy is +0.032R, not +0.083R. Every historical number in this
   document that predates v5 carries that correction.
3. **The 15-trade losing streak is a property of a 33% win rate, not a warning
   sign.** It is also the number that decides what risk setting is survivable.
4. **144 trades cannot pin a 33% win rate against a 20% break-even line.** The
   win-rate CI is 25.00–40.28%; the bottom of it is *above* break-even, which is
   the most encouraging single fact here, and it is still a 15-point interval.
5. **Pair selection still refuses to select** — no pair reaches 12 fit-window
   trades (max 5 across 29 pairs) in any walk-forward fold.
6. **A window-median FX rate is used for the quote-currency conversion.** It
   touches only the commission, which is 2–4% of R, so a ±20% rate error moves
   the result by well under a hundredth of an R. Documented rather than hidden.
7. **No news filter, BID bars with modelled spread, XAUUSD is the broker's own
   contract, and nothing has ever traded live or on demo.** Unchanged from v2.

### How to run v5

```bash
# The audited configuration (all eight fixes on, flat 4R)
python3 run_backtest.py --stack swing --profile v5

# The 30m rung, to reproduce the frequency answer
python3 run_backtest.py --stack mid30_swing

# The deliverable: $100k, 90 days, 1% AND 2%, + the clean workbook
python3 run_v5_100k.py --days 90 --profile v5
python3 build_v5_workbook.py            # -> Bot_Performance_90d.xlsx

# v2 is untouched and still reproduces EXACTLY 153 / 54.90% / 1.260 / +0.114R
python3 run_backtest.py --stack swing
```

---

## v2 — the reference configuration (unchanged, still reproducible)

`python3 run_backtest.py --stack swing` still returns exactly 153 trades /
54.90% WR / PF 1.260 / +0.114R / 3.98% max DD. Every v3 addition is opt-in
behind a config profile precisely so that stays true.

| | **v1 baseline** | **v2** |
|---|---|---|
| Universe | 13 pairs | **29 pairs** |
| Full window | 151 trades, 53.64% WR, PF 1.113, +0.052R | **153 trades, 54.90% WR, PF 1.260, +0.114R** |
| Win-rate 95% CI | 45.7 – 61.6% | 47.1 – 62.8% |
| **Expectancy 95% CI** | −0.119R to +0.221R — **spans zero** | **−0.061R to +0.286R — still spans zero** |
| In-sample (TRAIN) | 73 trades, 50.68% WR, PF 1.022, +0.011R | **72 trades, 52.78% WR, PF 1.237, +0.109R** |
| Out-of-sample (TEST) | 38 trades, 52.63% WR, PF 0.996, +0.002R | **44 trades, 52.27% WR, PF 1.169, +0.083R** |
| Walk-forward (OOS) | 129 trades, 55.81% WR, PF 1.210, +0.092R | **132 trades, 55.30% WR, PF 1.243, +0.107R** |
| Max drawdown | 3.74% · longest losing streak 7 | 3.98% · longest losing streak **5** |
| **68% reached?** | **NO** | **NO — 54.9% full, 55.3% walk-forward** |

**What v2 actually bought.** Expectancy roughly doubled (+0.052R → +0.114R),
profit factor went 1.11 → 1.26, TEST profit factor went from 0.996 (flat) to
1.169, and the trade count held. The negative tail of the expectancy CI
halved: −0.119R → −0.061R.

**What v2 did not buy.** *The expectancy confidence interval still contains
zero.* That was the single most valuable thing to fix and it is not fixed. The
data still cannot rule out that this system makes no money. The interval got
narrower and moved right; it did not clear.

The honest summary is unchanged in kind: this is a *correctly built* SMC system
whose measured edge is **not yet distinguishable from zero**. Profit factor
above 1.0, a positive walk-forward and a TRAIN/TEST result that agree are
encouraging, not conclusive.

What it is **not**: it is not overfit to a win rate, it is not shrinking targets
to buy a win rate (the matched-R control proves the opposite), and it is not
hiding costs. The number is low because the accounting is honest.

Per the spec's own instruction — *"do not claim a 68% win rate unless the actual
test data demonstrates it"* — the target is reported **against**, not toward.
The spec also says *"a lower win rate with substantially better expectancy is
preferable to an overfit strategy."* This is the lower win rate. The better
expectancy has not been demonstrated yet.

**The v2 90-day $100,000 deliverable lost money:** 6 trades, 33.3% WR, end
balance **$98,378.77 (−1.62%)**, max DD 1.86%, at 0.5% risk. Six trades cannot
distinguish a broken system from a working one having a quiet quarter — see the
deliverable section below for why that number is reported rather than defended.
The v3 deliverable at 2% risk on the scalper is in the v3 section, and it is
much worse.

**Next step is a forward demo run, not capital.** Paper/demo results:
**PENDING DEMO RUN.**

---

## v2 — what changed, and what was tried and thrown away

Protocol, no exceptions: every change was written down as a hypothesis first,
measured on **TRAIN** (first 50% of the window) and **TEST** (last 30%)
**independently**, and adopted only if it helped TRAIN *and* survived TEST.
Nothing was selected on the full window. Nothing was selected on TEST. The full
table with every number is the **Improvements v2** sheet of the workbook and
`reports/tuning/improvements.csv`; `tune.py` is the harness that produced it.

### Adopted

**1. Sweeps of session extremes are no longer traded.** (`filters.liquidity_exclude`)

v1's adaptive layer flagged session-high sweeps as decisively negative (n=34,
PF 0.456, −0.331R, CI entirely below zero). v2 treated that as a
*pre-registered hypothesis* and confirmed it on TRAIN before adopting: session
highs n=21, PF 0.368, −0.377R, CI [−0.719, −0.023]. It is removed as a **class**
(highs and lows), not one convenient side — a one-sided cut of a symmetric pool
type is a fit, not a filter.

| 13-pair universe | TRAIN | TEST |
|---|---|---|
| before | 50.68% WR, PF 1.022, +0.011R | 52.63% WR, PF 0.996, +0.002R |
| after | **52.50% WR, PF 1.405, +0.179R** | **55.17% WR, PF 1.330, +0.145R** |

This is the only v2 change that improved both splits on its own.

**2. The universe went from 13 pairs to 29.** Sixteen further liquid crosses
the broker genuinely offers (checked against `/instruments`), with live-sampled
spreads widened ~3× for the backtester.

⚠️ **Read this before quoting the trade count.** Those 16 pairs *on their own*
are **negative on TRAIN** (−0.029R, n=31) and weakly positive on TEST
(+0.051R, n=16). **They are frequency, not edge.** They were adopted because
the portfolio still improves against the v1 baseline on both splits while
holding trade count — not because they were shown to be good. The cost is
visible: on 13 pairs the filter alone gives +0.174R on 93 trades; on 29 pairs
it gives +0.114R on 153. **That is the trade the owner asked for — more
opportunities — priced honestly.**

### Rejected (with the numbers, not just the names)

| Change | TRAIN | TEST | Why rejected |
|---|---|---|---|
| Early structural-invalidation exits | +0.011 → **−0.064R** | +0.002 → −0.003R | Worse on both; max DD 3.74% → 5.98%. It cuts trades that were going to recover. |
| Loss-streak throttle (3 / 2) | −0.025R / −0.026R | −0.049R / +0.026R | Skips the recovery trades along with the bad ones. |
| Score gate 75 | +0.179 → **−0.113R** | +0.145 → +0.120R | Collapses TRAIN, max DD 9.09%. Matches the v1 perturbation. |
| Score gate 85 | n=4 on TRAIN | n=7 | Starves the sample to nothing. |
| Longs only | +0.309R | +0.141R | Better on both, but halves trade count **and** direction had already inverted train↔test at baseline. |
| **London only** | 13 pairs: +0.269R | 13 pairs: +0.274R | Superb on 13 pairs, **reversed on 29** (TRAIN +0.070R, worse than +0.109R). A filter that depends on the universe is a fit. |
| Equal-levels whitelist | +0.179 → +0.132R | +0.145 → +0.142R | Hurts TRAIN. Selection is made on TRAIN. |
| `min_rr` 2.5 | +0.338R | +0.188R | Better, but touches exits (needs matched-R) and costs 62% of trades. |
| Dedupe 4 / wider caps / all volume levers | ±0.00R | ±0.00R | **No-ops.** `max_open_positions`, `max_trades_per_day` and per-currency exposure were never binding. The system is limited by *setup scarcity*, not by its risk limits. |

### The v1 "68.57%" claim, tested properly — it did not replicate

v1 reported a post-hoc subgroup: sweeps of **equal lows**, n=35, 68.57% WR,
+0.345R, and flagged it as a hypothesis rather than a result. v2 tested it on
the splits it was not derived from:

| | TRAIN | TEST |
|---|---|---|
| Equal-lows sweeps only | n=17, 64.71% WR, **+0.446R** | n=8, 62.50% WR, **+0.057R** |

**An 87% out-of-sample shrink.** That is the expected fate of a subgroup found
by scanning seven liquidity types, and it is exactly why v1 refused to call it
a result. The 68.57% figure should not be quoted by anyone, ever.

### The $100,000 / 90-day deliverable

`python3 run_100k.py` runs the adopted v2 config over the most recent 90 days
of broker data on a $100,000 account with **trade-by-trade compounding**, and
writes continuous Daily / Weekly / Monthly tables (start balance, end balance,
$ gain, period ROI%, cumulative ROI%) to `reports/100k/` and to the
**100k Daily / 100k Weekly / 100k Monthly** sheets of the workbook.

⚠️ **Read the flat rows.** At roughly one to three trades a week, most calendar
days in a 90-day window are flat and weekends are closed. Those rows are not
missing data — they are the product. **90 days is far too short to be a
performance claim**; it is a shape check, and it is presented as one. The
1200-day validation above is the number that means something, and even that
one has a confidence interval containing zero.

**The result, stated plainly: the last 90 days lost money.**

| | 2026-05-16 → 2026-08-14 |
|---|---|
| Start balance | $100,000.00 |
| **End balance** | **$98,378.77** |
| **Net P/L** | **−$1,621.23 (−1.62%)** |
| Trades | **6** (0.47/week) |
| Win rate | 33.33% (2 of 6) |
| Profit factor | 0.217 |
| Max drawdown | 1.86% (daily equity path) |
| Active days | 6 of 91 — **93% of the window is flat** |

Monthly: May 0.00%, June 0.00%, July −1.05%, August −0.58%.

**Six trades is not a result.** It cannot distinguish a broken system from a
working one having a bad quarter — the same config returns +0.114R per trade
over 153 trades and +0.107R over 132 walk-forward trades, and a six-trade
sample sits comfortably inside the noise of either. It is reported here
because the owner asked for a 90-day $100k run and this is what a 90-day $100k
run actually produced. It is **not** evidence the system works, and it is
**not** evidence it does not.

Two months of the window produced **zero trades**. That is the honest shape of
a sniper system on 29 pairs at a 80/95 score gate, and no volume lever tested
in v2 changed it without destroying the expectancy (see the rejected table).

### Where the losses actually were

The diagnostic that drove round A: at baseline, **every** losing trade exits at
−1.01R (they are all full stop-outs — there is no fat tail to trim), while
winners exit through break-even/trailing at ~+0.95R. So "minimise losses" could
only mean *taking fewer bad setups*, not *losing less per bad setup*. Trying to
lose less per trade (the structural-invalidation exit) made it worse. Removing
the worst-identified setup class is what worked.

---

## v3 — the scalping attempt, and what it found

The owner asked for four things: scalping setups, a 70%+ win rate, a minimum of
three trades a day, and a $100k / 2% / 90-day backtest with a clean
profit-and-ROI workbook. Three of the four were built and measured. The
second — 70% — turns out to be the wrong thing to want, and this section shows
why with numbers rather than with an opinion.

**Headline: the SMC entry model does not survive the move to a scalping
timeframe.** On 15m setups with 5m fills, over 700 days and 29 pairs, it loses
money at every score gate, every cost gate, every target width and every pair
subset tested. That is not a tuning failure; it is a measurement, and it is
consistent between TRAIN and TEST.

---

### What was unlocked first: the data was never the limit

Both previous versions of this repo recorded that the broker only serves
~120 days of 5m history, and shelved the idea of a validated scalping stack on
that basis. **That was wrong.**

A single `/trade/history` call returns at most ~20–27k bars, and it answers an
over-long range with an **empty payload** rather than a truncated one. The
empty payload was being read as "history ends here". Chunk the request and the
same endpoint serves:

| Interval | Old belief | Actually available |
|---|---|---|
| 5m | ~120 days | **≥700 days** (142,867 bars/pair) |
| 1m | not testable | **≥200 days** |
| 15m | ~400 days | **≥700 days** (47,647 bars/pair) |

`fetch_deep.py` does the chunking. All 29 pairs now hold ~700 days of 5m and
15m. That is a 75% increase in usable 15m history and a 6x increase in 5m, and
it is the only reason anything below is a validation rather than an anecdote.

---

### Cost viability — which pairs can be scalped at all

On a swing trade the spread is a rounding error. On a scalp it is a large
fraction of the risk, so this was computed **before** any backtest, from median
London/NY ATR against the configured round-trip cost. A 1.5×ATR structural stop
is the typical scalp stop.

| | 5m setup | 15m setup |
|---|---|---|
| Best pair (USDJPY) | cost = **9.1%** of R | cost = **5.2%** of R |
| Median pair | cost = **30.3%** of R | cost = **17.6%** of R |
| Worst pair (AUDNZD) | cost = **62.4%** of R | cost = **36.7%** of R |
| Pairs where the stop clears 10× cost | **1 of 29** | **5 of 29** |

**The 5m setup timeframe is rejected on this arithmetic, before any performance
number is consulted.** The median pair pays 30% of its risk to the spread on
every 5m scalp, and only one pair in twenty-nine has a typical stop that clears
ten times its round-trip cost. That is a property of the broker's book, not of
the strategy, and it is the honest ground on which to exclude a timeframe. The
15m stack is the viable scalping timeframe here, and everything below uses it.

(The 5m stack was also run, and independently confirms the arithmetic: at the
v2 score gate it produced **13 signals per pair in 700 days** — 0.02 a day —
and no setup on the 5m stack ever scored above 75 out of 95.)

---

### The frontier the owner actually asked about

Two independent dials move win rate and frequency, and they are reported
together because quoting either alone is how this repo used to publish a 70%
that was really 45%.

**Dial 1 — the score gate (frequency).** 700 days, 29 pairs, cost gate 6×.

| Gate | Trades | Trades/day | Win rate | TRAIN E | TEST E |
|---|---|---|---|---|---|
| 55 | 1888 | **3.78** | 43.64% | −0.105R | −0.127R |
| 60 | 1673 | 3.35 | 43.10% | −0.112R | −0.153R |
| 65 | 1179 | 2.36 | 43.17% | −0.123R | −0.144R |
| 70 | 748 | 1.50 | 43.05% | −0.139R | −0.106R |
| 75 | 551 | 1.10 | 42.65% | −0.145R | −0.075R |
| 80 | 191 | 0.38 | 41.36% | −0.271R | −0.142R |

Note what this says about the scoring model itself: **win rate barely moves
across a 25-point gate range (41–44%), and TRAIN expectancy gets *worse* as the
gate tightens.** On a 15m setup the score card carries no positive marginal
information. That is a direct answer to "test the scoring components for
marginal contribution": at this timeframe they do not discriminate.

**Dial 2 — target width (win rate).** Management stripped, one flat target, and
a 48-hour time budget so a wide target is not truncated by the time stop before
it can arrive. (The first version of this control left the 8-hour stop in place,
which quietly penalised exactly the wide-target rows it exists to test. Both
versions are in `reports/scalp/`; they agree.)

| Target | Win rate | Break-even WR needed | Clears by | TRAIN E | TEST E |
|---|---|---|---|---|---|
| **0.5R** | **70.18%** | 66.67% | +3.5 pts | **−0.053R** | **−0.090R** |
| 1.0R | 49.49% | 50.00% | −0.5 pts | −0.119R | −0.145R |
| 2.0R | 32.97% | 33.33% | −0.4 pts | −0.090R | −0.185R |
| 3.0R | 25.10% | 25.00% | +0.1 pts | −0.139R | −0.138R |
| 4.0R | 22.05% | 20.00% | +2.1 pts | −0.140R | −0.035R |

**So: is 70% reachable? Yes — 70.18%, almost exactly the number asked for, at a
flat 0.5R target. And it loses 0.053R per trade on TRAIN and 0.090R on TEST.**

That single row is the entire lesson of the target-shrinking trap. The win rate
clears its break-even line by three and a half points and the account still
bleeds, because "break-even win rate" is computed on gross R and at 15m the
round-trip cost is a double-digit percentage of R. A win rate can be bought at
any level by moving the target closer. It buys nothing.

Win rate falls monotonically from 70% to 22% as the target widens — the correct
mechanical relationship, and the same shape the v2 swing stack shows. The
difference is that on the swing stack expectancy *rises* with target width and
turns positive; here it stays negative at every single width.

**Is 3 trades a day reachable? Yes — 3.78/day at gate 55.** It loses 0.131R per
trade.

**Both at once? No. And neither one profitably.**

---

### It is not a cost problem, and that took ruling out three ways

The obvious explanation for a losing scalper is the toll. It was tested
directly and it is not the answer.

| Test | TRAIN | TEST | Reading |
|---|---|---|---|
| Base (gate 65, cost 6×) | −0.123R | −0.144R | reference |
| Commission set to **zero** | −0.093R | −0.114R | commission is worth only 0.03R |
| Broker's **live** spreads (~3× narrower) | −0.139R | −0.120R | still negative, more trades |
| Only the 5 pairs where cost < 10% of R | −0.092R | −0.230R | **worse**, not better |
| Only the 12 pairs where cost < 15% of R | −0.107R | −0.240R | **worse** |
| Cost gate 12× | −0.081R | −0.096R | better, still negative |
| Cost gate 20× | −0.011R | −0.205R | TRAIN-only; TEST collapses |

Gross expectancy *before commission* is **−0.119R** against a commission drag
of **0.033R**. Restricting to the cheapest pairs on the book makes the result
*worse* out of sample. Running the broker's real quotes instead of the
deliberately-conservative ones still loses. Whatever is wrong here, a cheaper
broker does not fix it.

The cost gate looks like it helps — TRAIN improves monotonically from −0.240R
at 0× to −0.011R at 20× — but TEST does not follow, and at 20× it falls to
−0.205R on 119 trades. That is the signature of a filter shrinking a sample
until TRAIN noise looks like signal, and it is the same shape as v2 lead (a).

---

### The v2 leads, finally tested — one replicated, one did not

Both were flagged in v2 and neither had a TRAIN/TEST cycle, because both were
scored on the **full window**, which is the one selection this repo forbids.
`tune_v2_leads.py` gave them one, on the swing stack where they were found.

### Lead (a) `min_stop_over_cost = 15` — NOT REPLICATED

| Config | Trades | Full E | TRAIN E | TEST E |
|---|---|---|---|---|
| baseline (ladder, 10×) | 153 | +0.114R | +0.109R | +0.083R |
| cost 12× | 126 | +0.070R | +0.151R | **−0.084R** |
| **cost 15×** | 94 | **+0.245R** | **+0.391R** | +0.078R |
| cost 20× | 49 | +0.239R | +0.514R | **−0.119R** |

The headline +0.245R is a TRAIN artifact. Out of sample 15× lands on +0.078R
against the baseline's +0.083R — **no improvement, for 39% fewer trades** — and
the values either side of it are negative on TEST. Its full-window CI
[+0.028, +0.465] does clear zero, which is exactly the trap: the full window is
what suggested the parameter. **Rejected.**

### Lead (b) flat 4R target — REPLICATED, and adopted as a profile

| Config | Trades | Win rate | PF | Full E | TRAIN E | TEST E | Max DD |
|---|---|---|---|---|---|---|---|
| ladder | 153 | 54.90% | 1.260 | +0.114R | +0.109R | +0.083R | 3.98% |
| flat 3R | 150 | 36.00% | 1.284 | +0.192R | +0.145R | +0.253R | 4.85% |
| **flat 4R** | 149 | 32.89% | **1.375** | **+0.263R** | **+0.158R** | **+0.503R** | 7.31% |

It helps TRAIN, it improves TEST, and — the part that distinguishes it from
lead (a) — the effect is **monotonic in target width** rather than appearing at
one convenient value. Shipped as `profiles.swing_4r`.

Three caveats stated at the profile itself so it cannot be selected blind:
win rate falls **54.90% → 32.89%** (it wins bigger, not more often), max
drawdown nearly doubles, and the expectancy CI is **[−0.042, +0.574] — still
spanning zero**, though with a negative tail a third narrower than the ladder's
−0.061. A better configuration; not an established edge.

---

### Engineering fixes that came out of this session

**1. The intraday history limit was a misread empty payload.** Documented
above. `fetch_deep.py`, and 6× more 5m history for every pair.

**2. `max_open_positions` and `max_exposure_per_currency` were inert.**
`RiskEngine.can_trade` read `state.open_positions` and
`state.currency_exposure`; nothing in the backtest path ever wrote either. Both
caps have therefore never bound in any backtest this repo has published.

This rewrites one of v2's conclusions. v2 recorded "raising
`max_open_positions` / `max_trades_per_day` / per-currency exposure changed the
result by exactly zero trades" and read it as evidence that the system is
limited by setup scarcity rather than by its risk limits. Two of those three
levers were simply not connected. (`max_trades_per_day` *is* enforced, so that
third of the finding stands.) Fixed behind `risk.enforce_concurrency`, default
off so v2 stays reproducible, on in the scalp profile.

**3. A 10× speedup, and one "optimisation" that was a slowdown.** The engine
was profiled on 20k-bar 1H frames; a 143k-bar 5m frame is a different machine.
Three indexed-lookup fixes took a PairContext from 74s to 7.8s. One earlier
attempt cached bar arrays on `frame.attrs` — which pandas **deep-copies** on
every derived frame — and made the build *slower* than the pandas access it
replaced. Another sorted the zone list and silently changed which of two
equal-keyed zones won a strict-`>` tie-break, moving the swing stack from 153
trades to 155. Both were caught by re-running the v2 regression, which is why
that check exists.

**Every speedup is verified, not asserted.** The swing stack still returns
exactly 153 trades / 54.90% WR / PF 1.260 / +0.114R / 3.98% max DD, and
`detect_sweeps` was run side by side with the original implementation over
432,000 sweeps across 8 pair/timeframe combinations with every field matching.

**4. The context cache is version-stamped.** The tuning harnesses pickle 850MB
of PairContexts and reuse them across rounds. A cache written before a change to
`LiquidityMap` or `ZoneMap` unpickles into objects missing the attributes the
new code reads — an AttributeError an hour into a run, or worse, a silently
different result. `signal_engine.CONTEXT_CACHE_VERSION` now travels with the
pickle and a mismatch forces a rebuild.

**5. A display bug in the deliverable ledger.** With partial take-profits,
`exit_price` is only where the *remainder* closed, so computing pips as
`exit_price − entry` measured the last leg while `profit_usd` measured the whole
trade. Six of 185 rows showed a pip loss beside a dollar profit. Pips are now
derived from realised R. Headline money numbers were never affected — they come
from `pnl` — but the pip column is one the owner asked for by name.

---

### v3 caveats

1. **The scalper's expectancy CI is clear of zero on the wrong side.** v1 and
   v2 could not rule out that they made no money. v3's scalper can: it is
   reliably negative, and the TRAIN and TEST splits agree on that. This is the
   one place in this repo where a result *is* statistically established, and it
   establishes a loss.

2. **`swing_4r` is better, not proven.** Its CI [−0.042, +0.574] still spans
   zero. 149 trades is not enough to establish a 32.89% win rate against a 20%
   break-even line, and the TEST half of that result (+0.503R on 43 trades)
   leans on a handful of 4R winners. Treat the +0.263R as the best available
   estimate, not as a number to size positions from.

3. **The score card does not discriminate at 15m.** Across a 25-point gate
   range the win rate moves 41–44% and TRAIN expectancy gets *worse* as the
   gate tightens. Whatever the components measure on a 1H chart, they do not
   measure it on a 15m one. Nothing was reweighted on that basis, because
   reweighting to fit one timeframe's negative result is a fit.

4. **The 5m stack was rejected on cost arithmetic, not on a backtest.** Its
   median pair pays 38% of its risk to the spread. That is a property of the
   broker's book, computed before any signal was generated, and it is the
   honest ground on which to exclude a timeframe.

5. **2% risk on a negative-expectancy system is not a risk setting, it is a
   countdown.** The deliverable is produced at 2% because the owner asked for
   2%, and the risk-of-ruin block is printed next to it for the same reason.

6. **The intraday flat is counted in bars, and three trades escaped it.**
   `targets.max_hold_bars` counts *entry-timeframe bars*, and the session-flat
   deadline resolves to the first bar at or after it. A Friday-evening fill
   therefore has no bar to exit on until the Sunday open, so 3 of the 185
   deliverable trades were held over a weekend — 182 of 185 closed same-day, as
   intended. It is immaterial to a −48.94% result and it is disclosed rather
   than fixed, because fixing it would mean re-running the deliverable to
   change nothing. A live scalper would need a hard Friday cutoff.

7. **`exit_price` on a scaled-out position is the last leg only.** The ledger
   reports `final_exit_price` and derives pips from realised R, so the pip,
   dollar and R columns agree. Anyone recomputing pips from the price columns
   will get the last portion's result, not the trade's.

8. **Everything else from the v2 caveats still applies** — no news filter, BID
   bars with modelled spread, XAUUSD is the broker's own contract, and nothing
   has ever traded live or on demo.

---

### How to run v3

```bash
# Deepen the intraday cache (chunked; this is what makes 5m/15m testable)
python3 fetch_deep.py --interval 5m  --days 700
python3 fetch_deep.py --interval 15m --days 700

# The scalping improvement loop (TRAIN/TEST scored, nothing on the full window)
python3 tune_scalp.py --round viability   # cost per pair, 5m vs 15m
python3 tune_scalp.py --round diag        # matched-R: does the entry model work?
python3 tune_scalp.py --round s1          # score gate + cost gate frontier
python3 tune_scalp.py --round s2          # follow the cost
python3 tune_scalp.py --round s3          # the hypotheses still standing
python3 tune_scalp.py --round frontier    # win rate vs frequency, both ends
python3 tune_scalp.py --round final       # walk-forward + controls

# The two v2 leads, on the stack they were found on
python3 tune_v2_leads.py

# The $100k / 2% / 90-day deliverable + the clean workbook
python3 run_scalp_100k.py
python3 build_scalper_workbook.py

# v2 is untouched and still selectable
python3 run_backtest.py --stack swing                  # 153 tr, 54.90%, PF 1.260
python3 run_backtest.py --stack swing --profile swing_4r
```

---

### The adopted scalping config, fully validated

`profiles.scalp` — scalp15 stack (4H bias / 1H structure / 15m setup / 5m
entry), score gate 55, cost gate 6×, intraday flat at 21:00 UTC, concurrency
caps enforced, 29 pairs, 0.5% risk, ~700 days.

The gate was chosen on TRAIN subject to the owner's stated floor of three
trades a day, which the score gate is the only lever that reaches. TEST was not
consulted until the choice was frozen.

| Split | Trades | Trades/day | Win rate | PF | Expectancy |
|---|---|---|---|---|---|
| **IN-SAMPLE (train)** | 1052 | 4.21 | 45.44% | 0.794 | **−0.105R** |
| **VALIDATION** | 312 | 3.12 | 38.46% | 0.590 | −0.226R |
| **OUT-OF-SAMPLE (test)** | 524 | 3.49 | 43.13% | 0.760 | **−0.127R** |
| **FULL WINDOW** | **1888** | **3.78** | **43.64%** | **0.749** | **−0.131R** |

**Expectancy 95% CI: [−0.175R, −0.086R].** Win-rate 95% CI: 41.37–45.92%.

**The confidence interval is clear of zero.** For the first time in this repo a
result is statistically established rather than merely suggestive — and what it
establishes is that the system loses 0.13R per trade. v1 and v2 could not rule
out that they made no money; v3's scalper rules out that it does.

Total −247.92R over the window. Max drawdown 124% (the account is destroyed
partway through and the figure keeps counting against the starting balance).
**Longest losing streak: 12.**

### Walk-forward — and pair selection failing again, this time on a real sample

Five rolling folds, each fitting on its own window and scoring the immediately
following unseen window. Pair selection runs on the fit window only.

| Fold | Fit → OOS | Pairs kept | Fit trades | Fit E | OOS trades | OOS WR | OOS E |
|---|---|---|---|---|---|---|---|
| 1 | 2024-09 → 2025-05 | 6 of 28 | 322 | −0.095R | 134 | 41.79% | −0.152R |
| 2 | 2025-01 → 2025-08 | 6 of 29 | 415 | −0.084R | 97 | 37.11% | −0.275R |
| 3 | 2025-05 → 2025-12 | 3 of 29 | 316 | −0.148R | 36 | 27.78% | −0.449R |
| 4 | 2025-08 → 2026-04 | 1 of 26 | 258 | −0.236R | **12** | 83.33% | **+0.646R** |
| 5 | 2025-12 → 2026-08 | 6 of 29 | 354 | −0.089R | 83 | 38.55% | −0.223R |

**Walk-forward OOS: 362 trades, 39.78% WR (CI 34.81–44.75%), PF 0.639,
−0.204R (CI [−0.302, −0.105]).** Also clear of zero, also below it.

Two things worth reading here.

**The one positive fold has twelve trades.** Fold 4's +0.646R comes from a
single-pair selection producing twelve trades. It is the loudest number in the
table and the least informative one, and it is exactly the kind of row that
gets quoted out of a walk-forward.

**Pair selection made things worse, on a sample large enough to know better.**
v2 could never test this properly — no pair reached even 12 TRAIN trades across
29 pairs, so the protocol kept everything and said so. Here the sample is large
enough that selection genuinely engages, picking 1–6 pairs per fold. The result:
walk-forward OOS is **−0.204R against the all-pairs full-window −0.131R**.
Choosing the pairs that worked on the fit window made the next window
*measurably worse*, on 1888 trades rather than 153. v1's cautionary result about
pair selection now has a proper sample behind it.

### The $100,000 / 2% / 90-day deliverable

The adopted scalping config (scalp15, score gate 55, cost gate 6×, intraday
flat, concurrency enforced), most recent 90 days of broker data, $100,000,
**2% risk per trade**, compounding trade by trade.

| | 2026-05-16 → 2026-08-14 |
|---|---|
| Start balance | $100,000.00 |
| **End balance** | **$51,059.00** |
| **Net P/L** | **−$48,941.00 (−48.94%)** |
| Trades | **185** — **2.88 per weekday** |
| Win rate | **40.00%** (74 of 185), 95% CI 32.97–47.03% |
| Profit factor | 0.615 |
| Expectancy | **−0.183R**, 95% CI [−0.319, −0.041] — **clear of zero, below it** |
| Max drawdown | **50.76%** (daily equity path) |
| Longest losing streak | **7** |
| Active days | **60 of 91** |

Monthly: May −17.41%, June −29.41%, July −7.64%, August −5.18%.

**Read the frequency number carefully.** 2.88 trades per weekday over this
particular 90 days, against 3.78 over the full 700-day window. The 3/day target
is met on the long window and *missed* on the quarter the owner asked about.
Both numbers are reported because quoting only the one that clears the bar is
the thing this repo exists not to do.

**60 of 91 days traded**, against v2's 6. The frequency problem is genuinely
solved. The problem it exposed is that frequency was never what was wrong.

### What 2% risk implies — asked for, delivered, and costed

The owner asked for 2%. 2% is what the deliverable uses. Here is what it means
on the streak this system actually produced:

| | |
|---|---|
| Longest losing streak in the 90-day window | **7** |
| Longest losing streak over the full 700 days | **12** |
| Drawdown from a 7-loss streak alone, at 2% | **11.72%** |
| Drawdown from a 12-loss streak, at 2% | **21.5%** |
| Consecutive losses needed to lose 20% | 13 |
| Probability of a single loss | 0.60 |

A 7-loss streak at 2% is an 11.7% drawdown. The full window contains a
**12-loss streak**, which at 2% is a 21.5% drawdown from a single bad run, and
at a loss rate of 0.60 streaks of that length are ordinary rather than
exceptional. **On a system
with positive expectancy, 2% is aggressive. On this one it is not a risk
setting, it is a rate of descent** — the account is down 48.94% in a quarter,
and the drawdown figure of 50.76% is not a bad patch, it is the trend.

At 0.5% risk the same 185 trades lose roughly 16% instead of 49%. That is not
an argument for trading it at 0.5%; a negative edge does not become positive
when it is sized smaller, it just takes longer.

### The `swing_4r` 90-day comparison — and why 90 days cannot settle anything

The same $100k / 2% / 90-day treatment applied to the validated `swing_4r`
profile, for contrast:

| | 2026-05-16 → 2026-08-14 |
|---|---|
| Start / end balance | $100,000.00 → **$92,492.15** |
| Net P/L | **−$7,507.85 (−7.51%)** |
| Trades | **5** (0.08/weekday) |
| Win rate | 20.00% (1 of 5) |
| Max drawdown | 8.18% |

**Five trades.** A configuration measured at +0.263R over 149 trades returned
−0.77R per trade over five. That is not a contradiction, it is what a
five-trade sample does — and it is the clearest possible demonstration that
**a 90-day window cannot evaluate a system that trades 0.17 times a day.**

It also shows the other half of the frequency problem, and the shape of the
whole session: the scalper trades often enough for 90 days to mean something
and has no edge; the swing configurations have the edge and do not trade often
enough for 90 days to detect it.

### The deliverable workbook

`SMC_Scalper_Results.xlsx` — deliberately five sheets and no analytics clutter:

| Sheet | Contents |
|---|---|
| **Summary** | Starting balance, ending balance, total profit $, total ROI%, win rate, profit factor, max drawdown, trades, trades/day. Nothing else. |
| **Trade Results** | 185 rows. Time in/out, pair, direction, lots, entry / stop / target / exit price, **pips**, **profit $**, R multiple, win-loss flag, exit reason, session, hold minutes, running balance. |
| **Daily ROI** | All 91 days. Weekend rows shaded, not deleted. |
| **Weekly ROI** | 14 weeks. |
| **Monthly ROI** | 4 months. |

Each period sheet carries start balance, end balance, $ gain, period ROI% and
cumulative ROI%. `SMC_Sniper_Backtest.xlsx` (the v2 validation workbook) is
untouched; all validation detail stays there and in this document.

### Everything that was tried, and its number

Rounds S1–S3 ran 40 configurations of the scalping stack. **Not one is
positive on TRAIN and TEST.** Not one is positive on TRAIN alone at a sample
size worth quoting. The full log with every split is
`reports/scalp/improvements.csv`.

| Change | TRAIN | TEST | Verdict |
|---|---|---|---|
| base (gate 65, cost 6×) | −0.123R | −0.144R | reference |
| score gate 55 (3.78 trades/day) | −0.105R | −0.127R | best frequency, still loses |
| score gate 80 (v2's gate) | −0.271R | −0.142R | worst; the gate does not transfer |
| cost gate 12× | −0.081R | −0.096R | REJECTED |
| cost gate 20× | −0.011R | −0.205R | REJECTED — sample shrinkage |
| 5 cheapest pairs only | −0.092R | −0.230R | REJECTED — worse |
| 12 cheapest pairs only | −0.107R | −0.240R | REJECTED — worse |
| zero commission | −0.093R | −0.114R | diagnostic: not the cause |
| broker's live spreads | −0.139R | −0.120R | diagnostic: not the cause |
| no session-flat exit | −0.126R | −0.158R | REJECTED — flat exit helps |
| no break-even management | −0.114R | −0.157R | REJECTED — WR falls to 38.2% |
| `min_rr` 1.0 | −0.123R | −0.144R | no-op — TP2 already exceeds 2R |
| flat 4R (the v2 lead) | −0.092R | −0.121R | REJECTED — works on 1H, not 15m |
| require structure-TF alignment | −0.136R | −0.093R | REJECTED — hurts TRAIN |
| require 5m entry confirmation | −0.135R | −0.137R | REJECTED |
| NY session only | −0.084R | −0.131R | REJECTED |
| skip early London (08–09 UTC) | −0.078R | −0.177R | REJECTED — TEST worsens |
| time stop 24h (was 8h) | −0.124R | −0.138R | REJECTED — no effect |
| time stop 48h, no session flat | −0.133R | −0.152R | REJECTED — worse |
| high-volatility regime only | −0.089R | −0.214R | REJECTED |
| mid-volatility band | −0.135R | −0.151R | REJECTED |
| **PD/PW pools only** | **+0.216R** | **−0.436R** | REJECTED — n=48 |
| **no equal-level pools** | **+0.123R** | **−0.218R** | REJECTED — n=104 |

The last two rows are the only configurations in forty that are **positive on
TRAIN**, and both invert on TEST at samples of 48 and 104 trades. They are what
a post-hoc subgroup looks like before it is tested, and they are the reason the
protocol scores TEST separately instead of stopping at the encouraging number.

The time-stop rows deserve a note because they killed the most plausible
remaining hypothesis. `targets.max_hold_bars` is counted on the *entry*
timeframe, so the swing stack's 96 bars is four days while the scalper's same
96 is eight hours — a third of the setup-bar budget, against ATR-scaled targets
the same distance away. That asymmetry looked like it could explain everything.
Extending the budget to 24h changes the result by 0.001R, and to 48h makes it
worse. It is not the cause.

The pattern in the right-hand column is the whole story. Filters that shrink
the sample improve TRAIN and leave TEST alone or make it worse. That is what
overfitting looks like from the inside, and it is why selection is made on
TRAIN and scored on TEST rather than eyeballed on the full window.

---

## Architecture map

```
smc_sniper/
  config.py          Dotted-path config access + per-instrument overrides
  config.yaml        EVERY tunable. Nothing is hard-coded in strategy code.
  providers.py       TradeLocker (primary, read-only) + Yahoo (fallback)
  data.py            Cache, resample, ATR, and MTFView (no-lookahead alignment)
  structure.py       Swings, HH/HL/LH/LL, BOS / CHoCH / MSS, displacement
  liquidity.py       Equal highs/lows, PDH/PDL, PWH/PWL, session levels, sweeps
  zones.py           Order blocks, breakers, mitigation blocks, FVGs
  premium_discount.py  Equilibrium of the structural leg (soft rule + hard veto)
  scoring.py         The component score card
  signal_engine.py   The 12-step A+ sequence; emits Signals and Rejections
  risk.py            Sizing + every hard limit (anti-martingale by construction)
  backtest.py        Event-driven fills, costs, partials, management
  position_manager.py  The same management logic for live/paper, bar by bar
  execution.py       Abstract broker interface; Paper + TradeLocker adapters
  metrics.py         WR/PF/expectancy/Sharpe/Sortino/DD + bootstrap CIs
  walkforward.py     Splits, pair selection, walk-forward, controls
  adaptive.py        Which pair/session/setup combos carry expectancy
  news.py            Blackout filter (needs a calendar file to activate)
  telegram.py        Message formatting, dry-run only
  dashboard.py       Self-contained themed HTML report
  report_xlsx.py     The Excel workbook
  logging_engine.py  JSONL decision log, including every rejection
tests/               59 unit + integration tests
run_backtest.py      Full validation protocol -> reports + Excel
run_paper.py         Offline dry-run scanner (no orders, ever)

  --- v3 additions -------------------------------------------------------
fetch_deep.py        Chunked history fetch. The broker caps a single
                     /trade/history call at ~20-27k bars and answers an
                     over-long range with an EMPTY payload, which v1 and v2
                     both read as "history ends here". Chunking gets 5m back
                     700+ days and 1m back 200+.
tune_scalp.py        The scalping improvement loop (same TRAIN/TEST protocol
                     as tune.py) + the win-rate-vs-frequency frontier.
tune_v2_leads.py     v2's two flagged leads, on a real TRAIN/TEST cycle.
run_scalp_100k.py    The $100k / 2% / 90-day deliverable + risk-of-ruin.
build_scalper_workbook.py   SMC_Scalper_Results.xlsx (5 clean sheets).

  --- v5 additions -------------------------------------------------------
run_v5_100k.py       The $100k / 90-day deliverable at 1% AND 2% risk. Raises
                     `risk_per_trade_max_pct` explicitly (asking for 2% without
                     it silently returns a 1% run) and scales the daily/weekly
                     loss gates with the risk step-up so a 2% run is not
                     measuring its own circuit breaker.
build_v5_workbook.py Bot_Performance_90d.xlsx -- Date/Pair/Trades/Profit/ROI,
                     five sheets, both risk levels behind a Risk % column.
```

**v5 flags.** Eight defects, eight config flags, every one defaulting to the OLD
behaviour so v2 stays bit-for-bit reproducible:
`order_blocks.causal_structure_association`, `risk.quote_ccy_conversion`,
`risk.book_on_exit`, `execution.tp_trade_through`, `entry.exact_expiry`,
`targets.min_rr_on_liquidity`, plus the reporting-only `scratches` /
`win_rate_ex_scratch` in `metrics.py` and the explicit risk-cap raise in
`run_v5_100k.py`. `profiles.v5` turns them all on.

**Config profiles.** `Config.apply_profile(name)` overlays a flat map of dotted
paths from `profiles.<name>` in `config.yaml`. This is how v3 variants are
selected *without touching a single default*, so
`run_backtest.py --stack swing` keeps reproducing v2's published 153 trades /
54.90% / PF 1.260 forever. Two profiles ship: `scalp` and `swing_4r`.

**Data flow:** `providers -> data (cache/resample) -> MTFView -> PairContext
(structure + liquidity + zones per pair) -> signal_engine (score + gate) ->
risk -> backtest fills -> metrics -> walkforward -> reports`.

---

## Entry model — the 12-step A+ sequence

A long is only taken when every one of these holds (short is the mirror):

| # | Step | Rule |
|---|------|------|
| 1 | HTF bias | Bias timeframe must be bullish. **Hard gate** — never trade against it |
| 2 | Location | Entry inside the leg's discount half (soft, worth +5); hard veto past 85% of the leg |
| 3 | Approach | Price approaches a liquidity pool |
| 4 | Sweep | Wick pierces the pool **and closes back** — a touch is not a sweep, a close beyond is a break |
| 5 | Displacement | A large directional body (ATR-scaled) away from the sweep |
| 6 | Structure | MSS / CHoCH / BOS in the trade direction, after the sweep |
| 7 | Zone | An OB and/or FVG that formed **at or after the sweep** (it must belong to the reversal leg) |
| 8 | Retrace | A resting **limit** order inside that zone — no chasing, no market entries |
| 9 | LTF confirm | Displacement confirmation on the entry timeframe (+5) |
| 10 | R:R | TP2 must be ≥ `targets.min_rr` (default 1:2), else skip |
| 11 | Spread | Within the per-instrument cap, and risk ≥ 10× round-trip cost |
| 12 | Score | Total ≥ threshold (default 80) |

**Scoring — note the real ceiling.** The spec describes a 0–100 scale, but its
own component weights sum to **95**. They are kept verbatim rather than
rescaled (rescaling would silently shift every threshold), so a flawless setup
scores 95 and nothing can reach 100. The default 80 gate is 84% of maximum.

| Component | Points | | Component | Points |
|---|---|---|---|---|
| HTF aligned (bias **and** structure TF) | 15 | | Valid FVG | 10 |
| Major liquidity sweep | 15 | | Premium/discount location | 5 |
| MSS / CHoCH | 10 | | Displacement | 5 |
| BOS | 10 | | LTF confirmation | 5 |
| Valid order block | 10 | | Favourable spread | 5 |
| PD/PW liquidity | 5 | | **Maximum** | **95** |

**Stops** are structural — beyond the sweep extreme plus an ATR buffer, floored
at `min_stop_atr` and at 10× round-trip cost, capped at `max_stop_atr`. Never
widened. **Targets** are liquidity-based (TP1 internal, TP2 previous swing, TP3
external PDH/PDL/PWH/PWL), each required to sit a minimum R away so "nearest
liquidity" cannot collapse into a trivial micro-scalp.

---

## How costs are modelled

These rules are why the numbers below are lower than a naive backtest, and they
are not configurable into dishonesty:

- **Trade-through fills only.** A limit fills only if price trades strictly
  beyond it. A touch is not a fill.
- **Spread is always paid at entry**, on top of broker BID bars.
- **Slippage** is applied against the trade on entry and on stop exits.
- **Same-bar TP and SL resolves as a LOSS.** Intrabar order is unknowable from
  OHLC, so ambiguity always resolves against the strategy.
- **A fill bar that also reaches the stop is a loss.**
- **Commission** per round turn.

---

## Validated results

All figures from TradeLocker broker bars (BID), **29 pairs**, risk 0.5%/trade,
score gate 80/95, session-extreme sweeps filtered out. **In-sample,
out-of-sample and walk-forward are kept separate.** Do not quote any single row
on its own.

### Long-window stack — 1D bias / 4H structure / 1H setup, ~1200 days (v2)

| Split | Window | Trades | Win rate | 95% CI | PF | Expectancy |
|---|---|---|---|---|---|---|
| **IN-SAMPLE (train)** | 2023-05 → 2024-12 | 72 | 52.78% | — | 1.237 | +0.109R |
| **VALIDATION** | 2024-12 → 2025-08 | 37 | 62.16% | — | 1.453 | +0.163R |
| **OUT-OF-SAMPLE (test)** | 2025-08 → 2026-08 | 44 | 52.27% | — | 1.169 | +0.083R |
| **FULL WINDOW** | 2023-05 → 2026-08 | 153 | 54.90% | 47.1–62.8% | 1.260 | +0.114R |
| **WALK-FORWARD (OOS only)** | 5 rolling folds | **132** | **55.30%** | 47.0–63.6% | **1.243** | **+0.107R** |

Walk-forward folds (fit → immediately following unseen window):

| Fold | Fit trades | Fit WR | Fit E | OOS trades | OOS WR | OOS E |
|---|---|---|---|---|---|---|
| 1 | 21 | 52.38% | +0.163R | 24 | 66.67% | +0.383R |
| 2 | 24 | 66.67% | +0.383R | 27 | 40.74% | **−0.176R** |
| 3 | 27 | 40.74% | −0.176R | 32 | 65.62% | +0.196R |
| 4 | 32 | 65.62% | +0.196R | 29 | 48.28% | +0.024R |
| 5 | 29 | 48.28% | +0.024R | 20 | 55.00% | +0.134R |

Four of five OOS folds are positive and one is clearly negative — that spread
across 20–32 trade folds is the same thing the CI is saying: the sample cannot
pin the number down. The TRAIN→TEST gap is half a point (52.78% → 52.27%),
which argues *against* overfitting. TEST profit factor is 1.169, up from the
flat 0.996 of v1, and that is the single most meaningful line in this table.
Validation's 62% is the luckiest window, not the true rate.

Pair selection still refuses to select: no pair reaches 12 TRAIN trades (max 7
across 29 pairs). The per-pair sample is smaller than ever now that the
universe is wider, and the protocol says so rather than manufacturing a pick.

### Matched-R control — the anti-TP-shrinking check

Same entries, management stripped off, one flat target at each R (v2 config):

| Fixed R | Trades | Win rate | Break-even WR needed | PF | Expectancy |
|---|---|---|---|---|---|
| 1.0R | 153 | 58.17% | 50.0% | 1.177 | +0.076R |
| 1.5R | 131 | 47.33% | 40.0% | 1.142 | +0.077R |
| 2.0R | 152 | 42.76% | 33.3% | 1.239 | +0.144R |
| 2.5R | 152 | 37.50% | 28.6% | 1.188 | +0.125R |
| 3.0R | 150 | 36.00% | 25.0% | 1.284 | +0.192R |
| 4.0R | 149 | 32.89% | 20.0% | **1.375** | **+0.263R** |

Win rate falls monotonically as the target widens — the expected mechanical
relationship. The important part is unchanged in v2, and stronger: **expectancy
is best at the *widest* target (4R), not the narrowest**, and the win rate
clears the break-even line at *every* R. A win rate bought by shrinking targets
shows the exact opposite. This system is not doing that.

Note what this also says: the live liquidity-based ladder (+0.114R) delivers
*less* than a flat 4R target would (+0.263R). That is a real, unexploited lead
for a future version — and it is not adopted here, because changing exits needs
its own TRAIN/TEST cycle and this session ran out of runway before it could be
done properly.

✅ **v3 did the cycle and it REPLICATED.** Flat 4R: TRAIN +0.158R (vs the
ladder's +0.109R) and TEST +0.503R (vs +0.083R), with flat 3R landing in
between on both splits — monotonic in target width rather than appearing at one
convenient value. Shipped as `profiles.swing_4r`. It costs 22 points of win
rate (54.90% → 32.89%) and nearly doubles max drawdown (3.98% → 7.31%), and its
expectancy CI [−0.042, +0.574] still spans zero. See the v3 section.

### Pair selection — a cautionary result (v1, still the reason it is off)

Selecting pairs on TRAIN only (the correct protocol) once picked a single pair,
which then returned **5 trades at 40% WR and PF 0.019** on TEST. Per-pair
samples here are far too small to select on; doing it destroyed performance.
The walk-forward therefore keeps all pairs and says so, rather than
manufacturing a selection the data cannot support. On v2's 29 pairs the
sample per pair is thinner still (max 7 TRAIN trades), so the refusal stands.

### Robustness — parameter perturbation

Each parameter nudged with everything else held. Context-shaping parameters
(FVG sizing, swing lookback) trigger a full context rebuild.

v2 config, 29 pairs (profit factor at each value):

| Parameter | Values → profit factor | Reading |
|---|---|---|
| `scoring.threshold` | 75 → **0.974** (351 trades), 80 → **1.260**, 85 → 0.992 (20 trades) | Loosening destroys it; tightening starves it. 80 is a genuine optimum here, not a plateau. |
| `stops.min_stop_over_cost` | 0 → 1.022, 6 → 1.039, 10 → **1.260**, 15 → **1.644** (94 trades) | Still monotonic, and now *keeps rising* past 10×. See below. |
| `stops.buffer_atr` | 0.20 → 1.213, 0.25 → **1.260**, 0.35 → 1.222 | Shallow, no knife-edge. |
| `fvg.min_size_atr` | 0.14 → 1.232, 0.18 → **1.260**, 0.25 → 1.191 | Flat. |
| `structure.swing_lookback` | 2 → 1.260, 3 → 1.258 | Flat. |
| `targets.min_rr` | 1.5 → 1.260, 2.0 → 1.260, 2.5 → 1.431 (69 trades) | Flat until it starves the sample. |

Most parameters are flat, which is the main thing a perturbation check is for.
Two are not, and both matter:

* **The score gate is now a peak, not a plateau.** In v1, PF rose monotonically
  with selectivity (75 → 0.87, 85 → 1.26). In v2 it falls off on *both* sides.
  80 is the right gate on this data, but a parameter that has a single best
  value deserves more suspicion than one that does not.
* **`min_stop_over_cost` = 15 looks better than the configured 10** (PF 1.644,
  +0.245R) at the cost of 40% of the trades. It was **not** adopted: it was
  never put through a TRAIN/TEST cycle, and a perturbation sweep is scored on
  the full window, which is exactly the selection this repo forbids. It is a
  **candidate for the next round**, recorded here so it is not lost.

  ✅ **v3 tested it and it did not replicate.** TRAIN +0.391R against a TEST of
  +0.078R — no better than the baseline's +0.083R for 39% fewer trades — and the
  gate values either side of it (12× and 20×) are *negative* on TEST. Its
  full-window CI [+0.028, +0.465] does clear zero, which is precisely why a
  full-window number cannot be trusted to select a parameter: the full window is
  what suggested it. See the v3 section. **Rejected.**

### Adaptive analysis — what actually carries the expectancy

v1 found, across ~7 dimensions, only two groups with a 95% CI clear of zero:

| Group | n | Win rate | PF | Expectancy | 95% CI |
|---|---|---|---|---|---|
| Sweeps of **equal lows** | 35 | **68.57%** | 2.266 | **+0.345R** | +0.027 to +0.651 |
| Sweeps of **session highs** | 34 | 41.18% | 0.456 | −0.331R | −0.624 to −0.022 |

**v2 acted on both, and only one of them held up.**

The negative one *replicated*: session-high sweeps were still bad on TRAIN
(n=21, PF 0.368, −0.377R, CI clear of zero), and removing that pool class is
now the adopted filter — the single change that improved both splits.

The positive one *did not*: equal-lows-only was +0.446R on TRAIN and **+0.057R
on TEST**, an 87% shrink. ⚠️ **The 68.57% is dead. Do not quote it.** It was a
post-hoc subgroup from seven comparisons, v1 said so, and the out-of-sample
test confirmed it.

Directional and session tendencies were re-tested too and both failed:
longs-only and London-only each looked strong on one universe and reversed on
another. Neither is in the config. No individual pair reaches n=30 on 29 pairs;
the per-pair sample got *thinner*, not thicker.

### Spec-native stack — 4H bias / 1H structure / 15m setup, ~400 days

⚠️ **NOT RE-VALIDATED UNDER v2.** The numbers below are the **v1** 13-pair
results and are kept only for continuity. The v2 filter and the 29-pair
universe were validated on the long-window stack; this session ended before the
15m stack could be re-run, so its v1 bundle was moved aside
(`reports/sniper_v1_stale/`) rather than being silently mixed into a v2
workbook.

| Split (v1) | Trades | Win rate | PF | Expectancy |
|---|---|---|---|---|
| IN-SAMPLE (train) | 22 | 54.55% | 1.055 | +0.026R |
| VALIDATION | 12 | 41.67% | 0.834 | −0.087R |
| OUT-OF-SAMPLE (test) | 13 | 53.85% | 1.147 | +0.072R |
| **FULL WINDOW** | **47** | **51.06%** | **1.020** | **+0.010R** |

Win-rate 95% CI 36.2–66.0%; expectancy CI −0.291R to +0.313R. Max drawdown
2.87%. These splits hold 12–22 trades each and **cannot support any
conclusion**. To refresh them under v2: `python3 run_backtest.py --stack sniper`
(the 15m bars for all 29 pairs are already cached).

---

## Caveats

Read these before quoting any number above.

1. **The edge is still not statistically established.** The v2 expectancy CI is
   **−0.061R to +0.286R — it still spans zero.** 153 trades is a small sample
   for a 55% win rate; the win-rate CI is 15.7 points wide. Anyone quoting
   "54.9%" to one decimal is over-claiming. Getting this CI clear of zero was
   the most valuable available outcome and **v2 did not achieve it.**

1b. **The 16 pairs added in v2 are frequency, not edge.** On their own they are
   negative on TRAIN (−0.029R). They were adopted because the *portfolio*
   improves on both splits, not because they were shown to be good. If you want
   the highest-expectancy configuration rather than the highest trade count, set
   `markets` back to the original 13 and expect +0.174R on ~93 trades instead of
   +0.114R on 153.

2. **No news filtering.** No historical economic calendar is available here, so
   every backtest ran with the news filter inactive. The engine is built and
   config-driven — supply `news.calendar_file` as
   `utc_timestamp,impact,event` to activate it. Expect results to change.

3. **Thin sample on the spec-native 15m stack.** ~400 days of 15m bars yields
   47 trades at the default gate and 3 at the conservative gate. The 1H stack
   exists purely to get a sample large enough to walk-forward.

4. **5m precision layer is barely testable.** Only ~120 days of 5m history
   exists. The `sniper_5m` stack is a fill-model robustness check, not an
   independent result. **1M backtesting is out of scope** — the hook exists,
   the data does not.

5. **Bars are BID (TradeLocker) or mid (Yahoo).** There is no real bid/ask
   depth, so spread is modelled rather than observed. The configured spreads
   are deliberately **wider** than the broker's live quotes (EURUSD 0.6 vs
   ~0.1 observed) — overestimating cost is the safe direction.

6. **Costs dominate at small stop sizes.** Before the 10× cost gate, spread
   plus slippage inflated the median trade's true risk by 17.5%, and on gold
   the spread reached 30% of the stop. That single effect accounted for the
   whole of an earlier −0.23R expectancy. Any change that shrinks stops will
   re-open it.

7. **Session structure is a hypothesis, not a validated filter — confirmed
   again in v2.** London-only measured +0.269R TRAIN / +0.274R TEST on 13 pairs
   and then *reversed* on 29 pairs (TRAIN +0.070R, worse than the +0.109R it was
   compared against). London and NY are both still traded per the spec, and
   per-session results are reported so an inversion stays visible.

7b. **The risk caps are not what limits this system.** Raising
   `max_open_positions`, `max_trades_per_day` and per-currency exposure changed
   the result by exactly zero trades. The binding constraint is *setup
   scarcity*. Anyone hoping to raise frequency by loosening risk limits will
   get nothing but risk.

8. **XAUUSD on the Yahoo fallback is `GC=F`**, the COMEX future — close but not
   identical to spot gold. On TradeLocker it is the broker's own contract.

9. **Nothing has traded live or on demo.** Forward results: **PENDING DEMO
   RUN.**

---

## How to run

```bash
pip install pandas numpy requests pyyaml openpyxl pytest

# Full validation protocol -> reports/ + Excel workbook
python3 run_backtest.py --stack swing      # 1H setup, ~1200 days (largest n)
python3 run_backtest.py --stack sniper     # 15m setup, ~400 days (spec-native)
python3 run_backtest.py --refresh-data     # re-pull bars from TradeLocker first
python3 run_backtest.py --source yahoo     # credential-free fallback
python3 run_backtest.py --quick            # skip perturbation + matched-R

# The $100k deliverable: 90 days, compounding, daily/weekly/monthly tables
python3 run_100k.py                        # -> reports/100k/
python3 run_100k.py --days 180 --risk 0.75

# The v2 improvement loop (TRAIN/TEST scored, nothing selected on the full window)
python3 tune.py --round diagnostics        # where the losses live
python3 tune.py --round a                  # loss minimisation
python3 tune.py --round b                  # win rate / quality
python3 tune.py --round c                  # opportunity / volume
python3 tune.py --round log                # -> reports/tuning/improvements.csv

# Assemble the workbook from saved bundles (+ the 100k and Improvements sheets)
python3 build_final_report.py

# --- v3 ------------------------------------------------------------------
# Deepen the intraday cache. This is the step that makes 5m/15m testable at
# all: a single /trade/history call caps at ~25k bars and returns EMPTY for a
# longer range, which v1 and v2 both read as the end of history.
python3 fetch_deep.py --interval 5m  --days 700
python3 fetch_deep.py --interval 15m --days 700

# The scalping improvement loop
python3 tune_scalp.py --round viability   # cost per pair, 5m vs 15m
python3 tune_scalp.py --round diag        # matched-R: do the entries work?
python3 tune_scalp.py --round s1          # score gate + cost gate frontier
python3 tune_scalp.py --round s2          # follow the cost
python3 tune_scalp.py --round s3          # the hypotheses still standing
python3 tune_scalp.py --round final       # walk-forward + controls
python3 tune_scalp.py --round log         # -> reports/scalp/improvements.csv

# v2's two flagged leads, on the stack they were found on
python3 tune_v2_leads.py

# The $100k / 2% / 90-day scalping deliverable + the clean workbook
python3 run_scalp_100k.py
python3 build_scalper_workbook.py         # -> SMC_Scalper_Results.xlsx

# --- v5 ------------------------------------------------------------------
python3 run_backtest.py --stack swing --profile v5   # the audited config
python3 run_backtest.py --stack mid30_swing          # the 30m rung
python3 run_v5_100k.py --days 90 --profile v5        # 1% AND 2%
python3 build_v5_workbook.py                         # -> Bot_Performance_90d.xlsx

# Any stack with any profile overlaid
python3 run_backtest.py --stack swing --profile swing_4r
python3 run_backtest.py --stack scalp15 --profile scalp

# Offline dry-run scan: current qualifying setups, no orders
python3 run_paper.py

# Tests
python3 -m pytest tests/ -q               # 59 tests
```

**Credentials.** `.env` holds `TL_EMAIL / TL_PASSWORD / TL_SERVER /
TL_ACCOUNT_ID / TL_ACC_NUM`. It is gitignored and must never be committed. Only
read-only TradeLocker endpoints (`/instruments`, `/quotes`, `/history`) are ever
called.

**Live orders are structurally blocked.** `TradeLockerExecution.place_order`
raises unless *both* `execution.tradelocker.allow_live_orders: true` and
`SMC_SNIPER_ALLOW_LIVE_ORDERS=1` are set. Nothing in this repo sets either. This
system has never placed an order.

## Tuning safely

All parameters live in `config.yaml`. Gold has its own block and never shares
EURUSD's parameters. If you change targets, **re-run the matched-R control** —
it is the check that catches a win rate bought by shrinking the target, which
has been caught three times before in this repo:

```bash
python3 run_backtest.py --stack swing   # prints the matched-R table
```

Win rate should fall as R rises (that is mechanical). What matters is whether
it clears the break-even line at each R, and whether expectancy holds up
without depending on one convenient target.
