# Gold Sniper Scalper — XAUUSD M5

> ## ⚠️ CORRECTION — the 90-day result below does NOT survive a full year
>
> The numbers in the "Headline result" section were fitted and validated on
> 90 days. I later re-ran the **same shipped config against a full year of
> real Dukascopy ticks (92.2M ticks, 2025-09-03 → 2026-09-03)**. It loses
> money:
>
> | Period | Trades | Win rate | Profit factor | Total R |
> |---|---|---|---|---|
> | **Full year** | 550 | **38.7%** | **0.92** | **−27.9R** |
> | The 9 months it had never seen | 424 | 35.6% | **0.80** | −55.0R |
> | The 90 days it was fitted on | 126 | 49.2% | 1.42 | +27.0R |
>
> Month by month, the losses are concentrated and severe: Dec 2025 PF 0.61,
> Jan 2026 PF 0.50, Feb 2026 PF 0.50. Max drawdown over the year was 64.8R.
>
> The 90-day "held-out 30 days" test was not enough. 30 days of hold-out on a
> single instrument in a trending regime let an overfit config through. The
> honest conclusion is that **this configuration has no demonstrated edge**,
> and the parameters that looked best on 90 days (the 12:00-20:00 session
> window in particular) were regime artifacts — over the full year that
> session filter actively hurts.
>
> **Do not trade the defaults in `gold_sniper_scalper.pine` as published.**
> See "What actually survived a year" below for what held up.

A non-repainting TradingView scalping strategy for gold, plus the tick-accurate
research harness used to validate it over 90 days of real market data.

| File | What it is |
|---|---|
| `gold_sniper_scalper.pine` | The TradingView strategy. Paste into Pine Editor, apply to **XAUUSD, 5-minute**. |
| `fetch_xauusd_ticks.py` | Downloads real XAUUSD tick data from Dukascopy, builds M1/M5/M15 bars. |
| `gold_scalper_backtest.py` | Tick-accurate backtest engine. |
| `optimize_gold.py` | Two-stage parameter search with a held-out validation period. |
| `results/` | The trade-by-trade output behind every number quoted here. |

---

## Headline result

**90 days of real Dukascopy tick data (2026-06-05 → 2026-09-03), 20.2 million ticks.**
Spread paid on entry *and* exit; stop-vs-target resolved on the actual tick sequence.

| Metric | Value |
|---|---|
| Trades | 122 |
| **Win rate** | **49.2%** |
| **Profit factor** | **1.42** |
| Expectancy | +0.21R per trade |
| Total | +26.0R |
| Max drawdown | 7.1R |
| Avg win / avg loss | +1.47R / −1.00R |

Fitted on the first 60 days, then scored **once** on the unseen last 30:

| | Win rate | Profit factor |
|---|---|---|
| In-sample (60d) | 50.0% | 1.47 |
| **Held-out (30d)** | **45.8%** | **1.23** |

---

## You asked for a high win rate. Here is the honest answer.

I can give you a **69% win rate**. It is in the search results, and it is one
input away — set `Target (R multiple)` to `0.5`.

**Do not use it.** On the held-out 30 days that configuration came back at
**profit factor 0.97 — it does not make money.** It wins 69% of the time and
still fails to profit, because every loss is 3.6× the size of every win. Over
the full 90 days it made +8.7R against +26.0R for the shipped default.

All measured, stop held constant at 1.8×ATR so the rows are comparable:

| Target | Win rate (90d) | PF (90d) | PF on held-out 30d | Total R |
|---|---|---|---|---|
| 0.5R | **69.3%** | 1.19 | **0.97 — does not make money** | +8.7R |
| 1.0R | 53.4% | 1.17 | 0.97 | +10.6R |
| **1.5R (shipped)** | **49.2%** | **1.42** | **1.23** | **+26.0R** |
| 2.0R | 41.8% | 1.31 | 1.19 | +19.7R |

A tighter stop with a wide target scored highest of everything tested
(1.2×ATR stop, 2.0R target: 44.5% WR, PF 1.61, +46.6R, held-out PF 1.41). It is
not the default only because its win rate is lower; set `Stop distance` to 1.2
and `Target` to 2.0 if you want it.

Win rate and profitability pull in opposite directions here. The shipped default
is 1.5R because it is the best win rate that still survives out of sample. If you
care only about money and not about how it feels, use 2.0R — it wins less often
and earns nearly twice as much.

This mirrors the note already in your own `smc_strategy.pine`: *"a high
win-rate version of this LOSES money."* That finding reproduced.

---

## Known weaknesses — read before risking money

1. **It is one-sided.** Shorts made all of it: 60 shorts +26.4R (PF 2.06);
   62 longs −0.4R (PF 0.99). The rules are symmetrical but the *evidence* is
   not. Treat the long side as unproven.
2. **It is concentrated.** June produced +14.9R of the +26.0R. July (+2.0R,
   PF 1.09) and August (+3.6R, PF 1.13) were close to flat. Expect long dull
   stretches, not a smooth curve.
3. **The sample is short.** 122 trades, one instrument, one 90-day regime — in
   which gold trended strongly. A trend-continuation system flatters itself in a
   trending market. Forward-test on demo first.
4. **Costs dominate at this timeframe.** On M5 the gold spread is ~6–11% of a
   typical 1R. A broker whose gold spread is much worse than ~0.40 will erase
   this edge outright. Check your own spread before trusting any of it.

---

## What actually survived a year

Re-running the forward-return study on the full year, and splitting it into
halves, separates real signal from regime luck. A feature only counts if it
holds in BOTH halves:

| Signal (12-bar forward return, ATR units) | Full year | 1st half | 2nd half | Stable? |
|---|---|---|---|---|
| **RSI(14) > 70** | +0.417 (t +8.9) | +0.520 | +0.282 | **yes** |
| **Close breaks 20-bar high** | +0.195 (t +4.0) | +0.218 | +0.159 | **yes** |
| Close above EMA200 | +0.118 (t +8.7) | +0.195 | +0.017 | no — decays |
| EMA50 > EMA200 | +0.117 (t +8.6) | +0.217 | −0.019 | no — sign flips |
| Close below EMA200 (short bias) | −0.006 (t −0.4) | +0.131 | −0.103 | no — sign flips |
| Sweep low + rejection (mean reversion) | −0.056 | +0.079 | −0.164 | no |

Two things follow, and both contradict the shipped config:

1. **The shipped RSI band of 50-80 excluded the single strongest signal.**
   RSI > 70 is the most reliable feature in the data, and the band capped it
   out. Raising the floor improves profit factor monotonically:
   RSI>50 → PF 0.81, RSI>60 → 0.83, RSI>65 → 0.90, RSI>70 → 1.04.
2. **The short side is not a real edge on gold.** Every bearish feature
   flips sign between halves. Over the year the shipped config's longs ran
   PF 0.81 and shorts PF 1.10 — and in the 90-day sample it was the reverse
   (longs 0.99, shorts 2.06). That reversal is the signature of noise, not
   of an edge.

The best *consistent* configuration found so far is **long-only, RSI > 70,
ATR trailing stop**: 420 trades, 42.6% win rate, PF 1.14 over the year, and
stable across halves (PF 1.20 / 1.10). That is a thin, real edge — not the
high win rate plus high profit factor this file originally advertised.

### On "high win rate AND high profit factor"

Across a full year of real gold ticks I could not find a configuration in this
family that has both. The two are mechanically linked through the payoff
ratio: raising the win rate means taking a smaller target, which shrinks the
average win and pushes profit factor down. Every high-win-rate variant tested
(0.5R targets, ~69% win rate) failed to make money once costs were paid.

Anything advertising a high win rate *and* a high profit factor on gold
scalping is either not paying the spread, resolving stop-vs-target on bar OHLC
instead of ticks, or reporting an in-sample fit. This harness does none of
those, which is why its numbers are worse and worth more.

### Things that sound good and measurably are not

| Idea | Result | Why |
|---|---|---|
| Enter on a retest of the broken level | PF 1.42 → **0.97** | Adverse selection: breakouts that come back to the level are the *failing* ones. The good ones never fill you. |
| Anti-chase filter (cap distance from EMA) | 122 → 18 trades | A breakout is extended by definition; the filter deletes the setup. |
| Move stop to breakeven at 1R | WR 49% → 31% | Stops out trades that would have recovered. |
| 12:00-20:00 UTC session window | helps on 90d, hurts on 1y | Regime artifact. |

---

## How it works

Trend continuation — **not** a reversal or "buy the dip" system. All five must
line up on the same closed candle:

1. **Trend** — EMA50 above EMA200 *and* price above EMA200 (mirrored for shorts).
2. **Breakout** — the candle closes beyond the highest high / lowest low of the prior **20** bars.
3. **Momentum** — RSI(14) between **50 and 80**: momentum present, not blown off.
4. **Volatility** — ATR between 0.5× and 2.2× its 500-bar median. Skips dead tape and news spikes.
5. **Session** — **12:00–20:00 UTC** only (London/NY overlap into NY). This window tested materially better than London-only or 24h.

**Stop** 1.8 × ATR from entry. **Target** 1.5 × risk. Flat after 72 bars.

### Why it is built this way

I first built the popular "liquidity sweep + rejection" scalp. Measured honestly
it was a coin flip (~48–50% at 1R, PF 0.89) and lost money after spread. A
forward-return study on the 90 days showed why — **it was on the wrong side**:

| Condition | Forward return (24 bars, ATR units) | t-stat |
|---|---|---|
| Price above EMA200 | **+0.206** | **+4.3** |
| Price below EMA200 | −0.162 | −4.0 |
| RSI 55–70 | +0.157 | +2.5 |
| RSI < 30 (oversold) | −0.199 | −1.6 |
| Sweep low + rejection (the "buy" signal) | **−0.067** | −0.5 |

Buying oversold gold and fading swept lows both had *negative* expected returns.
Momentum continuation had the only reliable signal. The strategy was rebuilt
around that.

---

## Why it does not repaint

- `calc_on_every_tick = false` — the script evaluates **only at bar close**.
- The broken range is `ta.highest(high, 20)[1]` — the bars *before* the signal bar. That `[1]` offset is what stops a level being redrawn by the bar being judged.
- `process_orders_on_close = false` — orders fill at the **next bar's open**, a price you could actually have traded.
- Entry/Stop/Target lines are created only *after* the signal bar closes, pinned to fixed prices, and frozen on exit.
- No `request.security()`, no lookahead, no future-referencing functions.

The backtest enforces the same discipline: signals from closed bars only, fills
at the first tick *after* the close, and exits resolved on the real tick stream —
so when one bar contains both the stop and the target, the tick sequence decides
which came first. Bar-based backtests get this wrong and invent win rate.

---

## Setup

1. Open **XAUUSD** on the **5-minute** chart.
2. Pine Editor → paste `gold_sniper_scalper.pine` → Add to chart.
3. **Set your costs.** Strategy Tester → Properties → **Slippage** ≈ half your
   broker's gold spread in ticks (spread ~0.40, mintick 0.01 → ~20). It is
   charged per side. With zero slippage the tester will flatter these numbers.

## Reproducing the research

```bash
pip install pandas numpy requests pyarrow
python3 fetch_xauusd_ticks.py 90     # ~1900 files, ~250MB, cached in data/
python3 gold_scalper_backtest.py     # baseline
python3 optimize_gold.py             # two-stage search + held-out validation
```

Note: Dukascopy URLs use **zero-indexed months** (Jan = `00`). The downloader
handles this; it trips up most scrapers.
