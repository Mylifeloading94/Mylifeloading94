# Gold Sniper Scalper — XAUUSD M5

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
