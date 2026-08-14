# SMC Sniper AI Forex Trading Bot

A Smart Money Concepts sniper system: multi-timeframe bias, liquidity sweeps,
market-structure shifts, order blocks / fair value gaps, and a hard scoring
gate. Built to the owner's spec, backtested on real broker data, and reported
honestly.

---

## STATUS — read this first  ·  **v3**

**Do not trade any of this live.**

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

**Dial 2 — target width (win rate).** Management stripped, one flat target.

| Target | Win rate | Break-even WR needed | Trades/day | TRAIN E | TEST E |
|---|---|---|---|---|---|
| 0.5R | **69.24%** | 66.67% | 2.13 | −0.053R | −0.101R |
| 1.0R | 48.68% | 50.00% | 2.35 | −0.118R | −0.159R |
| 1.5R | 39.56% | 40.00% | 2.28 | −0.125R | −0.178R |
| 2.0R | 35.63% | 33.33% | 2.27 | −0.091R | −0.194R |
| 3.0R | 32.59% | 25.00% | 2.24 | −0.092R | −0.186R |
| 4.0R | 31.87% | 20.00% | 2.23 | −0.084R | −0.147R |

**So: is 70% reachable? Very nearly — 71.57% on TRAIN and 68.33% on TEST at a
flat 0.5R target — and it loses 0.086R per trade.** That is the entire lesson
of the target-shrinking trap in one row. The win rate clears its break-even
line by 2.6 points and the position still bleeds, because at 15m the round-trip
cost is a double-digit percentage of R and eats the margin.

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

6. **Everything else from the v2 caveats still applies** — no news filter, BID
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
```

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

# Offline dry-run scan: current qualifying setups, no orders
python3 run_paper.py

# Tests
python3 -m pytest tests/ -q
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
