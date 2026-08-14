# SMC Sniper AI Forex Trading Bot

A Smart Money Concepts sniper system: multi-timeframe bias, liquidity sweeps,
market-structure shifts, order blocks / fair value gaps, and a hard scoring
gate. Built to the owner's spec, backtested on real broker data, and reported
honestly.

---

## STATUS — read this first  ·  **v2**

**It does not hit 68%. Its edge is still not statistically established. Do not
trade it live.** v2 is a real improvement on v1 and still does not clear the
bar that matters.

| | **v1 baseline** | **v2 (current)** |
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

**The 90-day $100,000 deliverable lost money:** 6 trades, 33.3% WR, end
balance **$98,378.77 (−1.62%)**, max DD 1.86%. Six trades cannot distinguish a
broken system from a working one having a quiet quarter — see the deliverable
section below for why that number is reported rather than defended.

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
tests/               44 unit + integration tests
run_backtest.py      Full validation protocol -> reports + Excel
run_paper.py         Offline dry-run scanner (no orders, ever)
```

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
