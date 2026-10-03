> ## ⚠️ SECOND CORRECTION — v2 only worked in 2025-26
>
> Everything below was validated on **one year** (2025-10 → 2026-10). Tested on
> the full **2019 → 2026** bid/ask history, v2 returns **PF 0.98, t −0.34**, and
> before October 2025 it **loses** (n=1,286, WR 45.3%, PF 0.90, t −1.36).
> By-year PF: 2019 1.05 · 2020 0.96 · 2021 0.54 · 2022 0.85 · 2023 0.93 ·
> 2024 0.67 · **2025 1.44 · 2026 1.79**. 2025 was gold's strongest momentum year
> (+65%), and a long-only RSI-momentum rule simply rode it. A single year cannot
> distinguish an edge from a regime — that is the lesson. The current research is
> in **GOLD_BOT_README.md**.

# Gold Momentum Sniper — XAUUSD M5

A non-repainting TradingView strategy for gold, plus the tick-accurate research
harness behind it. Validated on **93.0 million real Dukascopy ticks covering a
full year** (2025-10-03 → 2026-10-02).

| File | What it is |
|---|---|
| `gold_sniper_scalper.pine` | The TradingView strategy. Apply to **XAUUSD, 5-minute**. |
| `fetch_xauusd_ticks.py` | Downloads real XAUUSD ticks from Dukascopy, builds M1/M5/M15 bars. |
| `gold_scalper_backtest.py` | Tick-accurate backtest engine. |
| `search_momentum.py` | Parameter search ranked by the *worse* of two halves. |
| `confirm_momentum.py` | Confirms a shortlist on the full year. |
| `results/` | Trade-by-trade output and stats behind every number here. |
| `results/bars/` | The gzipped year of OHLC, committed so the research is reproducible. |

---

## Result

| Metric | Value |
|---|---|
| Trades | 215 (one year) |
| **Win rate** | **53.0%** |
| **Profit factor** | **1.52** |
| Max drawdown | **3.35R** |
| Avg win / avg loss | +0.289R / −0.214R |
| t-statistic | **+2.19** |
| Bootstrap P(not profitable) | **1.3%** |
| 95% CI on mean R/trade | [+0.006, +0.100] — excludes zero |
| Months profitable | 8 of 13 |
| Average hold | 1h 29m |

Spread paid on entry **and** exit; stop-vs-exit resolved on the real tick
sequence, never on bar OHLC.

### Versus the previous version

| | v1 (90-day fit) | **v2 (year-validated)** |
|---|---|---|
| Win rate | 38.7% | **53.0%** |
| Profit factor | 0.92 | **1.52** |
| Total | −28.1R | **+11.3R** |
| Max drawdown | 64.7R | **3.35R** |
| Significance | t **−0.99** | **t +2.19** |

Win rate up 14 points, profit factor from losing to 1.52, drawdown 19× smaller.

---

## What changed, and why it worked

**v1 failed.** It was fitted on 90 days (showing 49.2% WR / PF 1.42) and then
measured against a full year: **PF 0.92, −28R, 64.8R drawdown**, and PF 0.80
across the 9 months it had never seen. Its best-looking parameters were all
regime artifacts — the 12:00-20:00 session window helped on 90 days and hurt
over the year, and its long/short split inverted between samples.

Three changes fixed it, each driven by a measurement rather than a hunch.

### 1. Stop chasing a high win rate. Find a signal that is actually real.

Measuring forward returns over the full year, then checking each signal holds
in **both halves**, separates signal from regime luck:

| Signal (12-bar forward return, ATR units) | Full year | 1st half | 2nd half | Stable |
|---|---|---|---|---|
| **RSI(14) > 75** | +0.479 (t +5.9) | +0.695 | +0.244 | **yes** |
| **RSI(14) > 70** | +0.424 (t +8.7) | +0.567 | +0.261 | **yes** |
| **Break of 20-bar high** | +0.165 (t +3.8) | +0.217 | +0.098 | **yes** |
| Above EMA200 | +0.092 (t +6.6) | +0.157 | +0.010 | decays |
| EMA50 > EMA200 | +0.072 (t +5.2) | +0.175 | −0.056 | **sign flips** |
| Below EMA200 (short bias) | −0.033 (t −2.3) | +0.027 | −0.080 | **sign flips** |
| RSI < 30 (buy the dip) | −0.037 | +0.031 | −0.089 | **sign flips** |

v1's RSI band of **50-80 excluded the strongest signal in the data.** Raising
the floor and removing the cap improves everything monotonically. All rows
below use the *same* shipped exit, so they are directly comparable:

| Signal | Trades | Win rate | Profit factor | Max DD | t | 1st half / 2nd half PF |
|---|---|---|---|---|---|---|
| RSI>50 (≈ v1's band) | 778 | 49.6% | 0.96 | 13.1R | −0.42 | 1.08 / 0.83 |
| RSI>60 | 744 | 49.7% | 0.97 | 11.9R | −0.33 | 1.09 / 0.83 |
| RSI>65 | 596 | 49.5% | 1.01 | 9.7R | +0.09 | 1.12 / 0.90 |
| RSI>70 | 389 | 50.9% | 1.20 | 4.2R | +1.28 | 1.28 / 1.11 |
| **RSI>75 (shipped)** | **215** | **53.0%** | **1.52** | **3.35R** | **+2.19** | **1.51 / 1.54** |
| RSI>80 | 102 | 55.9% | 1.87 | 1.17R | +2.26 | 2.12 / 1.65 |

Six thresholds improving in order is a coherent pattern, not a cherry-picked
cell — which is the main reason to believe the signal is real.

**RSI>80 scores better on every metric** (55.9% WR, PF 1.87) and if you want
the highest win rate and profit factor in this file, set `Minimum RSI` to 80.
It ships at 75 only because 215 trades give a tighter estimate than 102; at
~2 trades a week, RSI>80 will take years to confirm. Both halves of the year
were strongly profitable at either setting.

Every bearish signal flips sign between halves, so the strategy is **long
only** — not an oversight, a finding.

### 2. The tight stop was the problem, not the entry

This is the key insight. The signal is strongly significant (t +5.9) but v1's
*trade* was not (t −0.99). The gap: the signal predicts a drift of about
**+0.48 ATR**, while v1's stop sat **1.8 ATR** away. Noise around that drift
crosses a stop well inside it long before the edge appears, so a strong
conditional mean became a coin flip.

Fixing it meant inverting the usual advice — **remove the tight stop and exit
on the clock**:

All four rows below use the *same* shipped signal (RSI>75), so only the exit
differs:

| Exit | Trades | Win rate | Profit factor | Max DD | t |
|---|---|---|---|---|---|
| 0.5R target, 1.8×ATR stop | 277 | **63.2%** | **0.87** | 22.7R | −1.06 |
| 1.5R target, 1.8×ATR stop (v1's model) | 241 | 41.1% | 1.02 | 17.3R | +0.14 |
| 2.0×ATR trailing stop (bar-synced) | 221 | 42.5% | 1.12 | 14.0R | +0.66 |
| **18-bar hold, 10×ATR disaster stop** | **215** | **53.0%** | **1.52** | **3.35R** | **+2.19** |

Note the first row: the tight-stop/small-target version wins 63.2% of the time
and **still loses money.**

The 10×ATR stop fired **once in 215 trades**. It is a disaster stop; the real
exit is time. Tightening it is exactly what made v1 lose money.

### 3. Rank by the worse half, not the best number

Every config is scored on both halves of the year and ranked by the *worse*
one. Ranking on full-period profit factor is what let v1 through.

---

## Honest limits — read before risking money

- **Marginal significance.** t = +2.19 is just past the usual bar, and this
  config was chosen from ~24 tested. What makes it credible is not the single
  cell but the plateau: the entire RSI>75 family scored PF 1.45-1.57 (t
  1.86-2.28) across every horizon (18-36 bars) and stop width (6-10×ATR)
  tried. A broad flat optimum is far more trustworthy than a sharp peak. It is
  still not proof.
- **Concentrated.** January 2026 alone produced +5.2R of the +11.3R total.
  5 of 13 months lost money. Expect flat and negative stretches.
- **Bull-market tailwind.** Gold trended up over this year. A long-only
  momentum strategy flatters itself in that regime, and this has **not** been
  shown to work in a gold downtrend.
- **Position sizing.** With a 10×ATR stop (~$45 on gold) 1R is large. Risk a
  fixed % of equity across that distance; do not size it like a scalp stop.
- **Sample.** One year, one instrument, 215 trades. Forward-test on demo.
- **Costs decide it.** A broker whose gold spread is much worse than ~0.40
  will erase this edge. Check your own spread.

### On "high win rate AND high profit factor"

Both improved here, but only because the *signal* and the *exit* improved — not
by tuning the target. Tuning the target trades one for the other:

| Exit (same RSI>75 signal) | Win rate | Profit factor | Verdict |
|---|---|---|---|
| 0.5R target | **63.2%** | **0.87** | loses money |
| 1.5R target | 41.1% | 1.02 | breaks even |
| 18-bar time exit | 53.0% | 1.52 | the shipped version |
| 18-bar time exit, RSI>80 | 55.9% | 1.87 | highest of both, fewer trades |

A 63.2% win rate that loses money is the trap. Anything advertising a high win
rate *and* a high profit factor on gold is usually not paying the spread,
resolving stop-vs-target on bar OHLC instead of ticks, or quoting an in-sample
fit. This harness does none of those.

### Measured and rejected

| Idea | Result | Why |
|---|---|---|
| Enter on a retest of the broken level | PF 1.42 → **0.97** | Adverse selection — breakouts that return to the level are the *failing* ones; good ones never fill you. |
| Move stop to breakeven at 1R | WR 49% → **31%** | Stops out trades that recover. |
| Anti-chase filter (cap distance from EMA) | 122 → **18** trades | A breakout is extended by definition; the filter deletes the setup. |
| 12:00-20:00 UTC session window | helps on 90d, **hurts** on 1y | Regime artifact. |
| Short side | every bearish signal flips sign | No demonstrated edge on gold. |
| Tighter trailing stop (1.5×ATR) | PF **0.96** | Inside the noise. |

---

## Why it does not repaint

- `calc_on_every_tick = false` — evaluated only at **bar close**.
- The broken range is `ta.highest(high, 20)[1]` — bars *before* the signal bar.
  That `[1]` is what stops a level being redrawn by the bar being judged.
- `process_orders_on_close = false` — fills at the **next bar's open**.
- Entry / Stop / Time-exit are drawn only after the signal bar closes, pinned
  to fixed prices and a fixed bar, and frozen on exit.
- No `request.security()`, no lookahead, no future-referencing functions.

The backtest enforces the same discipline, and critically resolves exits on the
**real tick stream** — when one bar holds both the stop and the exit, the ticks
decide. The engine also offers `exit_mode='trail_bar'`, which ratchets once per
bar close rather than per tick, because that is the only trail a non-repainting
Pine strategy can honestly reproduce.

---

## Setup

1. Open **XAUUSD** on the **5-minute** chart.
2. Pine Editor → paste `gold_sniper_scalper.pine` → Add to chart.
3. **Set your costs.** Strategy Tester → Properties → **Slippage** ≈ half your
   broker's gold spread in ticks (spread ~0.40, mintick 0.01 → ~20). Charged
   per side. At zero slippage the tester will flatter these numbers.

## Reproducing

```bash
pip install pandas numpy requests pyarrow
python3 fetch_xauusd_ticks.py 365   # ~7500 files, ~1GB of ticks, cached in data/
python3 confirm_momentum.py         # shortlist on the full year, split by halves
python3 search_momentum.py          # wider search, ranked by worse half
```

`results/bars/` already holds the gzipped year of OHLC, so signal research can
be rerun without the download. Note Dukascopy URLs use **zero-indexed months**
(January = `00`) — that trips up most scrapers.
