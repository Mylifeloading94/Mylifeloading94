# Automated TradeLocker Forex & Gold Bot — v3 Report (SMC + trailing stop)

**Data:** real bars from the TradeLocker **live PULSE feed** (account L#808776), 24 instruments,
~80,000 M15 bars each (**2023-06-01 → 2026-08-21**) plus ~978,000 **M1** bars each
(**2024-01-01 → 2026-08-21**) for sniper entries and intrabar trail resolution.
No synthetic prices anywhere.

**Headline validation:** anchored walk-forward, 2025-04-01 → 2026-08-22, $10,000.

---

## 1. Result

Requested changes: **SMC method across H4/H1/M15→M1 for sniper entries**, and
**trail the stop into profit every 20 pips**. Both were built and measured. One
helped, one did not — details in §2 and §3.

Headline is the anchored walk-forward, $10,000, 2025-04-01 → 2026-08-22, with the
trailing stop active and resolved on **M1 bars**.

| | **All pairs** (default) | **Filtered watchlist** | Brief's target |
|---|---|---|---|
| Ending balance | **$10,493.68** | $10,516.88 | — |
| Net profit | **+$493.68 (+4.94%)** | +$516.88 (+5.17%) | positive |
| Trades | 91 | 34 | — |
| **Win rate** | **72.53%** | **82.35%** | 60% min, **70–90% goal** |
| **Profit factor** | **1.385** | 2.642 | > 1 |
| Expectancy | +$5.43 (+0.120R) | +$15.20 (+0.326R) | positive |
| **Max drawdown** | **2.93%** | 1.50% | low |
| Sharpe | 0.899 | 1.836 | — |
| Longest losing streak | 4 | 3 | — |
| Trades per day | 0.146 | 0.055 | 2–3 |

**The 70–90% win-rate target is now met** (72.5% on the unbiased full universe),
with a profit factor of 1.385 and under 3% drawdown. The trailing stop is what
delivered it.

Against the previous build (no trail): win rate rose 59.1% → 72.5% and profit
factor 1.364 → 1.385, while net profit fell 7.13% → 4.94% and drawdown rose
2.11% → 2.93%. Trailing converts some large winners into small ones — that is the
trade you are making, and it is the trade the brief asks for.

Still unmet: **reward-to-risk 0.884** (below 1) and **0.15 trades/day** rather than
2–3. §11 explains why those two are arithmetically unreachable alongside a 70%+
win rate rather than merely untuned.

---

## 2. The 20-pip trailing stop — implemented, but not literally

A fixed 20-pip step is **not instrument-neutral on this book.** Median H4 stop
distances measured across the universe:

| | median stop | what 20 pips means |
|---|---|---|
| EURGBP | 20.9 pips | ~1.0R — would cut nearly every trade |
| EURUSD | 51.2 pips | 0.39R |
| USDJPY | 91.1 pips | 0.22R |
| **XAUUSD** | **219.0 pips** | **0.09R — that is $2.00 against a $21.90 stop** |

Tested literally, in-sample, the fixed-pip trail helped 7 instruments and **hurt
11**. The aggregate profit-factor gain was not broad-based; it came from a handful
of pairs.

So the rule is implemented **proportionally**: every **0.5R** of progress the stop
moves to **0.25R behind** the best price reached. On the median 43-pip H4 stop
that is *"trail roughly every 20 pips, keeping about 10 behind"* — your rule, on a
typical pair — while scaling correctly for gold and the JPY crosses.

Measured out of sample (anchored walk-forward, M1-resolved):

| trail rule | trades | win rate | profit factor | expectancy |
|---|---|---|---|---|
| no trail | 106 | 59.43% | 1.401 | +0.1665R |
| literal 20 pips, 20 gap | 104 | 50.00% | 1.301 | +0.0909R |
| literal 20 pips, 10 gap | 114 | 69.30% | 1.323 | +0.1013R |
| **proportional 0.5R / 0.25R** | 101 | **76.24%** | **1.705** | **+0.1692R** |

The proportional rule is the only variant that raises the win rate into the target
band **without** giving up expectancy. `trail_pips` is still in the code if you
want the literal version — set `p.trail_pips = 20` and `p.trail_r = 0`.

How it behaves on a trade: at +0.5R the stop locks **+0.25R** (already in profit,
not breakeven); at +1.0R it locks +0.75R; at +2.0R, +1.75R.

Exit mix under trailing: 30 targets (+0.979R), 36 trailed stops (+0.207R),
25 full stops (−1.037R). **The trailed exits are what convert would-be losses into
small wins** — that is the whole win-rate gain.

---

## 3. The SMC H4→H1→M15→M1 build — tested, and it underperforms

Fully implemented in `smc.py` / `smc_sim.py`: H4 structure bias via BOS/CHoCH,
H4 dealing-range premium/discount, H1 unmitigated **order blocks and fair-value
gaps** as points of interest, a required **liquidity sweep**, M15 **change of
character** confirmation, and an M1 **micro order-block limit** for the sniper
entry. ~978,000 M1 bars per instrument were downloaded for all 24 instruments.

It loses money in every configuration tested:

| variant | trades | win rate | profit factor | median stop |
|---|---|---|---|---|
| M15 entry, M15 stop | 235 | 30.6% | 0.75 | 24.6 pips |
| **M1 sniper, M1 micro stop** | 96 | **16.7%** | **0.48** | **8.2 pips** |
| M1 sniper, M15 structural stop | 95 | 28.4% | 0.76 | 21.1 pips |

**The sniper entry actively hurts.** It does exactly what it promises — the stop
shrinks from ~25 pips to ~8 pips — but an 8-pip stop on FX is *inside the noise*,
and the win rate collapses to 16.7%. Anchoring the stop to M15 structure instead
(sniper entry, survivable stop) recovers it to 0.76, which is still losing and no
better than simply entering on M15.

Two genuine bugs were found and fixed in the SMC chain along the way — the M15
confirmation was allowed to occur *before* price reached the point of interest,
and the sniper was entering at the M1 close rather than at the micro order block.
Adding the required liquidity sweep cut over-trading ~25× (PF 0.68 → 1.02 on a
4-symbol sample). None of it was enough.

**Recommendation: keep the validated H4 sweep + market-structure-shift engine**
(PF 1.385 with trailing) rather than the full SMC drill-down (PF ≤ 0.76). The SMC
code ships and is reproducible so you can re-test it, but it is not the default.

Why the drill-down fails here is the same arithmetic as v1: tighter stops mean
transaction costs and noise consume a larger share of R. An 8-pip stop with a
~1-pip spread is ~13% cost drag before slippage — the exact problem that sank the
M15 build.

---
## 4. Complete $10,000 walk-forward — all pairs, trailing active

| Block | Threshold | Trades | Win rate | P/L | Start | End |
|---|---|---|---|---|---|---|
| 2025-04..06 | 50 | 22 | 81.8% | +$329.48 | $10,000.00 | $10,329.48 |
| 2025-07..09 | 65 | 19 | 57.9% | −$181.82 | $10,329.48 | $10,147.66 |
| 2025-10..12 | 65 | 20 | 80.0% | +$376.92 | $10,147.66 | $10,524.58 |
| 2026-01..03 | 70 | 16 | 56.2% | −$239.05 | $10,524.58 | $10,285.53 |
| 2026-04..06 | 70 | 7 | 85.7% | +$121.76 | $10,285.53 | $10,407.29 |
| 2026-07..08 | 70 | 7 | 85.7% | +$86.39 | $10,407.29 | **$10,493.68** |

| Metric | Value |
|---|---|
| Starting / ending balance | $10,000.00 → **$10,493.68** |
| Net profit | **+$493.68 (+4.94%)** |
| Total / winning / losing trades | 91 / 66 / 25 |
| **Win rate** | **72.53%** |
| Average win / loss | $26.89 / −$51.25 |
| **Profit factor** | **1.385** |
| Expectancy | +$5.43 (+0.120R) |
| Avg planned R:R / realized | 0.884 / 0.525 |
| Max drawdown | $309.15 (**2.93%**) |
| Recovery factor | 1.597 |
| Sharpe / Sortino | 0.899 / 0.459 |
| Largest win / loss | $50.10 / −$55.16 |
| Longest win / loss streak | **18** / 4 |
| Avg trade duration | 16.9 hours |
| Trades per day | 0.146 |

**Exit breakdown — this is where the win rate comes from:**

| exit | trades | avg R | total |
|---|---|---|---|
| target | 30 | +0.979R | +$1,411.90 |
| **trailed stop** | **36** | **+0.207R** | **+$363.09** |
| full stop | 25 | −1.037R | −$1,281.28 |

Without trailing those 36 trades would mostly have been full stops. That is the
entire mechanism: the trail converts marginal losers into small winners, which
lifts the win rate and slightly lifts the profit factor, while shrinking the
average win from $48.52 to $26.89.

### Monthly

| Month | Trades | Win rate | P/L | PF | Max DD | Ending balance |
|---|---|---|---|---|---|---|
| 2025-04 | 7 | 42.9% | −$84.62 | 0.54 | 1.40% | $9,915.38 |
| 2025-05 | 8 | 100.0% | +$228.77 | ∞ | 0.00% | $10,144.14 |
| 2025-06 | 7 | 100.0% | +$185.33 | ∞ | 0.00% | $10,329.48 |
| 2025-07 | 4 | 50.0% | −$83.57 | 0.19 | 0.49% | $10,245.90 |
| 2025-08 | 7 | 57.1% | −$67.24 | 0.56 | 0.51% | $10,178.66 |
| 2025-09 | 8 | 62.5% | −$31.00 | 0.80 | 1.00% | $10,147.66 |
| 2025-10 | 7 | 71.4% | +$135.47 | 2.26 | 1.04% | $10,283.13 |
| 2025-11 | 5 | 80.0% | +$67.12 | 2.35 | 0.48% | $10,350.25 |
| 2025-12 | 8 | 87.5% | +$174.33 | 4.35 | 0.00% | $10,524.58 |
| **2026-01** | 6 | 33.3% | −$193.01 | 0.10 | 2.02% | $10,331.57 |
| **2026-02** | 3 | 100.0% | +$31.40 | ∞ | 0.00% | $10,362.98 |
| **2026-03** | 7 | 57.1% | −$77.45 | 0.51 | 1.42% | $10,285.53 |
| **2026-04** | 0 | — | $0.00 | — | — | $10,285.53 |
| **2026-05** | 4 | 75.0% | +$14.79 | 1.28 | 0.52% | $10,300.32 |
| **2026-06** | 3 | 100.0% | +$106.97 | ∞ | 0.00% | $10,407.29 |
| **2026-07** | 3 | 66.7% | +$7.80 | 1.15 | 0.00% | $10,415.09 |
| **2026-08** (to 21st) | 4 | 100.0% | +$78.59 | ∞ | 0.00% | **$10,493.68** |

10 of 16 active months profitable. **The Jan–Aug 2026 stretch is −$30.90 on its
own** ($10,524.58 → $10,493.68), so the specific window the brief asked about is
still roughly flat; the profit is earned across the longer walk-forward.
April 2026 produced no qualifying setup and the bot stood down.

---

## 5. Pair-by-pair (walk-forward, 91 trades, 23 instruments)

| Pair | Trades | Win rate | Net | Avg R | PF |
|---|---|---|---|---|---|
| EURGBP | 7 | 100.0% | +$223.97 | +0.638 | ∞ |
| AUDUSD | 8 | 87.5% | +$212.52 | +0.532 | 5.48 |
| EURCAD | 6 | 100.0% | +$209.82 | +0.723 | ∞ |
| GBPAUD | 3 | 100.0% | +$102.08 | +0.736 | ∞ |
| EURAUD | 2 | 100.0% | +$59.20 | +0.598 | ∞ |
| CHFJPY | 1 | 100.0% | +$47.45 | +0.989 | ∞ |
| GBPUSD | 1 | 100.0% | +$44.57 | +0.989 | ∞ |
| XAUUSD | 2 | 100.0% | +$26.17 | +0.620 | ∞ |
| AUDCAD | 5 | 80.0% | +$24.39 | +0.105 | 1.45 |
| EURJPY | 2 | 100.0% | +$22.33 | +0.228 | ∞ |
| EURUSD | 4 | 75.0% | +$16.47 | +0.090 | 1.31 |
| CADJPY | 1 | 100.0% | +$10.91 | +0.228 | ∞ |
| USDSGD | 1 | 100.0% | +$8.76 | +0.175 | ∞ |
| GBPCHF | 5 | 60.0% | +$7.53 | +0.022 | 1.07 |
| AUDNZD | 3 | 66.7% | +$6.44 | +0.041 | 1.12 |
| GBPJPY | 6 | 66.7% | −$12.57 | −0.064 | 0.87 |
| USDCAD | 4 | 75.0% | −$23.34 | −0.113 | 0.56 |
| NZDJPY | 3 | 66.7% | −$30.65 | −0.211 | 0.40 |
| USDCHF | 6 | 50.0% | −$51.73 | −0.154 | 0.67 |
| NZDUSD | 6 | 50.0% | −$81.60 | −0.292 | 0.46 |
| EURCHF | 7 | 57.1% | −$82.90 | −0.233 | 0.48 |
| AUDJPY | 4 | 25.0% | −$108.16 | −0.532 | 0.31 |
| GBPCAD | 4 | 25.0% | −$137.95 | −0.716 | 0.07 |

**15 of 23 pairs profitable.** No pair earns A+ — every per-pair sample is 1–8
trades, far too small to grade. Treat this table as descriptive only; §6 shows why
acting on it is a mistake.

---

## 6. Automatic pair filtering — now genuinely ambiguous

With trailing active the filtered watchlist finally beats the full universe on
risk-adjusted terms, which reverses the previous build's finding:

| | Trades | Win rate | PF | Net | Max DD | Sharpe |
|---|---|---|---|---|---|---|
| All 24 pairs (default) | 91 | 72.53% | 1.385 | +$493.68 (+4.94%) | 2.93% | 0.899 |
| Filtered watchlist | 34 | 82.35% | 2.642 | +$516.88 (+5.17%) | 1.50% | 1.836 |

**I am still defaulting to all pairs**, for one reason: 34 trades is too few to
trust, and the previous build showed per-pair persistence is essentially noise
(the training-selected watchlist and the test-selected watchlist overlapped by
**zero pairs**). One walk-forward where filtering wins does not overturn that.
Run `--filtered` if you disagree; both are implemented and both are profitable
here.

---

## 7. Risk analysis

| Metric | Value |
|---|---|
| Active trading days | 76 |
| Losing days | 19 of 76 (**25%**) |
| Worst day | −$185.49 (−1.8%) |
| Best day | +$58.87 |
| Days breaching the 2% daily cap | **0** |
| Longest losing streak | 4 trades |
| Longest winning streak | 18 trades |
| Max drawdown | $309.15 (2.93%) |
| Long trades | 54, 77.8% WR, +$580.91 |
| Short trades | 37, 64.9% WR, −$87.20 |

Only 25% of active days lose money, against 38% before trailing. Risk controls
held throughout: no daily-cap breach, position size fixed at 0.5% of equity
(0.35% gold), no martingale.

**Shorts still carry no edge** (−$87.20 across 37 trades) while longs carry all of
it. I have deliberately **not** made the bot long-only — that would be fitting to
a sample that may simply reflect a dollar-weakness regime.

---

## 8. The quality score still does not rank trades

Out-of-sample correlation between score and outcome remains near zero (+0.024 in
the previous run). The score works as a **gate** — every band above the floor is
profitable — but it does not rank. **Do not size positions by score.** It is
reported as measured rather than rebuilt, because rebuilding it against the same
data is how it would become overfitted.

---

## 9. Trade examples

**Winner — EURGBP, 7 of 7, +$223.97.** H4 structure bullish, price swept the prior
20-bar low and reclaimed it, H4 closed back through the pre-sweep high with a body
over 0.45×ATR, limit filled at 62% back into the leg. Small sample, but every
trade followed this identical shape.

**Winner via the trail — 36 trades exiting at +0.207R average.** These are the
trades that never reached the 1R target. Without trailing most would have been
−1R. This is the single mechanism behind the 72.5% win rate.

**Loser — GBPCAD, 1 of 4, −$137.95 (−0.716R avg).** All four passed every gate.
This is what an ordinary losing streak looks like in a system with a real but
modest edge, and why the 4-consecutive-loss lockout exists.

**Loser — AUDJPY, 1 of 4, −$108.16.** Losses slightly exceed 1R because spread and
commission are charged on top of the stop.

**Rejected setups.** The bot stands down on ~99.7% of bars, and April 2026
produced no qualifying setup at all.

---

## 10. Final bot rules

**Markets:** all 24 FX pairs + XAUUSD. **Signal timeframe:** H4. **Context:** D1 + W1.

**Pre-conditions (all must hold):**
1. ATR(14)/price between 0.025% and 1.25%
2. Spread ≤ 45% of ATR(14)
3. Daily bias non-neutral (close vs EMA50 vs EMA200 agree)
4. Weekly/H4 bias does not contradict the daily bias

**Entry trigger (all must hold, direction = higher-timeframe bias):**
5. **Liquidity sweep** — within the last 6 bars, a bar wicked beyond the prior
   20-bar extreme and closed back inside it
6. **Structure shift** — the current bar closes beyond the 3-bar extreme preceding
   the sweep
7. **Displacement** — body ≥ 0.45 × ATR, closing in the trade direction
8. **Location** — the sweep extreme sat in the lower 45% (longs) / upper 45%
   (shorts) of the 40-bar range
9. **Extension** — price within 1.6 × ATR of EMA20
10. **Quality score ≥ 60/100**

**Order:** limit at 62% retracement of the displacement leg, GTC, expires after
6 bars, cancelled if the stop level trades first.

**Stop:** sweep extreme ± 0.5 × ATR(14).
**Target:** 1.0R (balanced) or 0.6R (high win rate).

**Trailing stop:** every **0.5R** of progress, move the stop to **0.25R behind**
the best price reached; never backwards. (+0.5R → lock +0.25R, +1.0R → +0.75R,
+2.0R → +1.75R.) On the median 43-pip H4 stop this is ≈ "every 20 pips, holding 10
behind". Set `p.trail_pips = 20; p.trail_r = 0` for the literal fixed-pip version.

**Risk:** 0.5% equity per trade (0.35% gold) · max 3 concurrent · max 2 positions
sharing a currency · max 3 trades/day · 2% daily loss cap · 4-consecutive-loss
lockout. Never increase size after a loss.

---

## 11. Honest limitations — read before risking money

1. **The sample is small.** 91 walk-forward trades over 17 months. A 72.5% win rate
   on 91 trades spans roughly 62–81% at 95% confidence.
2. **Frequency is far below the brief.** 0.15 trades/day, not 2–3. H4 systems are
   selective by nature; forcing more trades is what failed in v1.
3. **Reward-to-risk is 0.884, below 1.** The measured trade-off is one-for-one: you
   buy win rate with R:R. A 70%+ win rate and a "strong R:R" cannot coexist here.
   That is arithmetic, not a tuning failure.
4. **Trailing cuts net profit.** +7.13% without it, +4.94% with it, and drawdown
   rises 2.11% → 2.93%. You are buying win rate with profit. If you would rather
   have the money than the win rate, set `p.trail_r = 0`.
5. **The SMC drill-down is in the repo but is NOT the default**, because it loses
   (PF ≤ 0.76). Do not switch to it on the strength of the method's reputation.
6. **Shorts carry no edge in this sample.** Possibly regime, possibly noise.
7. **Live results will be worse.** Real spreads widen around news and rollover;
   these are modelled as constants. Broker stop-modification latency will also
   make the trail slightly worse than simulated.
8. **Rotate the account password.** It was shared in plaintext in the task.

**Suggested path:** run `--demo` for 2–3 months (~10–20 trades), compare the
realized profit factor against 1.385, and only then consider live with the
smallest size your broker allows.

---

## Appendix — reproducing this

```bash
export TL_EMAIL=... TL_PASSWORD=... TL_SERVER=PULSE TL_ENV=live
python3 tl_data.py               # real M15 back to 2023-06 (data/, gitignored)
python3 test_no_lookahead.py     # look-ahead verification
python3 tl_data.py --m1          # M1 bars for sniper entries + trail resolution
python3 improve.py               # in-sample timeframe / structure search
python3 walkforward_full.py      # fully uncontaminated walk-forward
python3 trail_walkforward.py     # trailing-stop variants, out of sample
python3 smc_study.py             # the SMC H4/H1/M15/M1 build
python3 final_backtest.py        # the $10,000 headline result
python3 live_bot.py --dry-run
```

Outputs: `final_results.json`, `trades_walkforward.csv`, `walkforward_full.csv`,
`improve_insample.csv`, `smc_insample.csv`, `pair_selection_insample.csv`.
