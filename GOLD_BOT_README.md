# Gold (XAUUSD) bot — scalp and intraday versions, tested 2019 → today

**Short version: the targets you set (win rate 55–90%, profit factor ≥ 3, drawdown < 10%)
could not be met, and I am not going to tell you otherwise.** I built both versions,
tested 4,500 configurations on 7.75 years of real bid/ask data, and report below what
they actually do. One option has a thin real edge. The other has none.

## The two options

| | **Intraday** (1–4 h) | **Scalp** (1–15 min) |
|---|---|---|
| Config | `configs/gold_intraday.json` | `configs/gold_scalp.json` |
| Pine | `gold_intraday_fade.pine` (M15) | — (nothing worth porting) |
| Status | **thin edge, paper-trade first** | **no edge found — bot refuses `--live`** |
| Strategy | Buy a 3σ Bollinger washout with RSI(7)<20; stop 6×ATR, target 2R, close after 4 h | least-bad of 1,890 configs |
| Trades 2019→today | 546 | 639 |
| Win rate | **53.1%** | 55.1% |
| Profit factor | **1.11** | **0.75** |
| Avg trade | +0.023R | **−0.078R** (t = −3.21) |
| Total | +12.5R | **−49.7R** |
| Max drawdown | 10.2R (≈5% at 0.5% risk, 9.9% at 1% risk) | 57.6R |
| Significance | t = +0.93 (**not significant**) | significantly **negative** |

## Against your targets

| Target | Intraday | Scalp |
|---|---|---|
| Win rate 55–90% | 53.1% — **just misses** | 55.1% — met, but loses money |
| Profit factor ≥ 3 | **1.11 — not met** | **0.75 — not met** |
| Max drawdown < 10% | met (5% at 0.5% risk) | not met |
| Average trade profitable | +0.023R — barely | **negative** |
| Highly profitable | **+12% over 7.75 years at 1% risk** | loses money |

Across **both** grids (4,500 configs), **zero** reached WR ≥ 55% and PF ≥ 3 on the
training period *or* the validation period. Scalp: zero of 1,890 were even profitable on
both.

## How it was tested

- **Data:** 2.75M real Dukascopy M1 bars, **bid and ask OHLC**, 2019-01-01 → 2026-10-02.
  Longs enter at the ask and exit at the bid, so the real, time-varying spread is paid on
  every trade (mean $0.29 in 2019 → $0.73 in 2026).
  *Not TradeLocker data:* your demo login authenticates but the broker returns 403 on the
  instruments endpoint ("API usage not allowed"), so Dukascopy was the only full-history
  source reachable. Re-run on GenFX's own feed if they enable API access.
- **Pessimistic fills:** if one bar touches both stop and target, the **stop** is assumed to
  hit first; bars that gap through a stop fill at the open; nothing is held through a
  market closure.
- **Split discipline:** configs chosen on **2019–2022** only; **2023–2024** shown as
  validation; **2025 → today** scored once, on finalists.
- **No lookahead:** `check_replay.py` rebuilds exactly what the live bot would see (a
  trailing 900-bar window) at hundreds of bars per strategy and requires the same signal
  as the full-history backtest. 0 mismatches.

## Why the targets are out of reach

**Scalping gold is a spread problem.** A 1–15 minute gold move is a few dollars; the round-
trip spread is $0.29–0.73. That cost alone eats the edge — not one of 1,890 scalp configs
was profitable on both train and validation, and the best was PF 0.79.

**High win rate and high profit factor pull against each other.** A small target with a
wide stop wins often and loses big. The scalp "best" wins 55.1% and still loses because its
average loss (−0.68R) is bigger than its average win (+0.42R).

**One good year proves nothing.** Last turn's "v2" strategy looked excellent on
2025-10 → 2026-10 (PF 1.52, t +2.19). On the full history it returns **PF 0.98**, and loses
before October 2025. 2025 was gold's strongest momentum year (+65%). Any single-regime
backtest — including the 90-day one before it — will find something. This is corrected in
`GOLD_SNIPER_README.md` and `gold_sniper_scalper.pine`.

## The intraday option in detail

By year (0.5% risk/trade):

| Year | n | WR | PF | R | Gold buy-and-hold |
|---|---|---|---|---|---|
| 2019 | 66 | 53.0% | 1.01 | +0.2 | +18% |
| 2020 | 68 | 51.5% | 1.01 | +0.1 | +25% |
| 2021 | 73 | 52.1% | **0.79** | −4.0 | −4% |
| 2022 | 55 | 58.2% | 1.62 | +7.2 | 0% |
| 2023 | 76 | 50.0% | 1.05 | +0.9 | +13% |
| 2024 | 67 | 53.7% | 1.32 | +3.8 | +27% |
| 2025 | 71 | 56.3% | 1.32 | +3.7 | +65% |
| 2026 | 70 | 51.4% | 1.05 | +0.6 | −4% |

What counts **for** it:
- It survived all three stages: train PF 1.06 → validation PF 1.16 → test PF 1.18.
- Profitable in 7 of 8 years, including 2022 when gold was flat.
- **It beats 98% of random long entries** with the same stop and hold. Buying gold every
  4 hours instead loses badly (PF 0.90, −112R over 6,192 trades), so its timing carries
  real information, not just bull-market drift.

What counts **against** it:
- **t = +0.93.** Not statistically significant. It was one of 6 survivors out of 2,610
  configs, and some survivors are expected by chance.
- **Fragile to costs.** Extra cost of $0.25/oz → PF 1.03; $0.50/oz → PF 0.95. Check your
  broker's real gold spread before anything else.
- **Long only**, in a market that rose 4.4× over the period. Not shown to work in a
  downtrend; the short side was tested and rejected.
- **Tiny.** +0.023R per trade. +12% total over 7.75 years at 1% risk is roughly 1.5% a year.

## Using the bot

```bash
# credentials ONLY via environment variables - never a file, never argv
export TL_USERNAME=... TL_PASSWORD=... TL_SERVER=GenFX TL_ACCOUNT_ID=... TL_ACC_NUM=...

python3 bot_gold.py --config configs/gold_intraday.json          # DRY RUN (default)
python3 bot_gold.py --config configs/gold_intraday.json --live   # sends orders
```

- **Dry run is the default.** It logs the exact order it would send.
- The stop is attached to the order itself, so a crash cannot leave a naked position.
- `--live` on `gold_scalp.json` is refused unless you add `--force-unvalidated`. Don't.
- **Not tested against a live TradeLocker session.** The signal logic is verified; the
  broker glue (history parsing, order calls) is written against the SDK's documented
  signatures but was never run with real credentials. Run it dry on demo and read the log.
- **Rotate the password you pasted into the chat.**

## Reproducing

```bash
pip install pandas numpy requests pyarrow numba tradelocker
python3 fetch_xauusd_m1.py 2019-01-01 32   # ~70 min; or use results/bars_m1/ (committed)
python3 research_gold.py intraday 4        # 2,610 configs
python3 research_gold.py scalp 4           # 1,890 configs
python3 select_gold.py intraday            # rank on train, show validation, score test once
python3 finalize_gold.py                   # the numbers above
python3 check_replay.py                    # live signal path == backtest signal path
```

`results/bars_m1/` holds the full M1 bid/ask history (69 MB, zstd parquet by year).
`results/research_*.jsonl` holds every one of the 4,500 configs' train/validation stats.

## What I'd do next

1. Get GenFX to enable API access (or export gold bars from TradeLocker) and re-run on
   **your broker's own feed and spread** — for the intraday option that is the whole question.
2. Paper-trade the intraday option for a few months before risking anything.
3. If you want profit factor near 3, the honest route is a different kind of edge than these
   price-pattern families: it would need information outside the price series, not a better
   threshold.

---

## Round 2 — pushing for win rate > 60% and profit factor > 4

**Result: not reachable. I could not get there, and the evidence below shows why, not just that I failed.**

### What the target requires

PF = (WR × avg win) ÷ ((1 − WR) × avg loss). So WR > 60% with PF > 4 needs
winners **≥ 2.7× the size of losers** while hitting 60% of the time. Equivalent
requirements: WR 70% → winners ≥ 1.7× losers; WR 80% → ≥ 1.0×. That is a trader who is
right most of the time *and* wins big — i.e. very strong predictability of gold's next
move from public price data. The strongest edge found anywhere in this project is about
0.05R per trade; this target needs about 0.5R.

### What I tried (all walk-forward or train/validation/test, real bid/ask costs)

| Approach | Best honest result | Verdict |
|---|---|---|
| Hand-written families: momentum, pullback, Bollinger fade, session breakout (4,500 configs) | WR 53%, PF 1.11–1.18 | no config reaches WR>60 **and** PF>4 even **in-sample**, at any sample size |
| Meta-labelling: gradient-boosted model on 33 features scoring every bar, M15, take top 0.5–10% | selection PF **0.94**, OOS rank-IC 0.00–0.05 | no predictive power |
| Meta-labelling, M5 (scalp holds ≤ 15 min) | all 24 settings PF **< 1** | spread beats the signal |
| Meta-labelling, H1 with 4–24 h holds | best selection PF 1.23, then 0.76 on 2025–26 | still ≈ 1 |
| Win-rate-first search: configs with WR > 60% on both train and validation | **0 found** (so none to test for profit) | high WR only appears with PF < 1 |
| Cost-aware gating (skip trades where spread is a large share of the stop) | PF 1.11 → 0.97–1.11, no consistent gain | rejected |

### Why — the diagnosis

1. **The directional edge is tiny; the cost is the same size.** Top-1% model signals earn
   about +0.0 to +0.12R gross, against a spread cost of 0.05–0.11R per trade (2021–24).
   Net ≈ 0. The M5 model's high rank-IC (0.10–0.18) is mostly it *predicting trade cost*
   (spread/ATR is a feature), not direction; add the spread back and the edge collapses.
2. **Costs have fallen, which is why 2025–26 looks good everywhere.** Spread cost per trade
   dropped from 0.11R (2021) to 0.03R (2026) because gold's dollar volatility grew far
   faster than its spread. Every strategy improves in that regime. That is a feature of the
   market, not a property of any strategy, and it may not persist.
3. **The intraday fade is a time-exit strategy in disguise.** Its 2R target sits 12 ATR
   away and fired 4 times in 546 trades; 84% of trades exit on the clock. Its reported
   win rate and PF depend on the (arbitrary) 6-ATR stop width.
4. **No hidden pocket exists.** If the target were reachable with a high-conviction, low-
   frequency setup, an in-sample search would at least find overfit candidates. It found
   none, at any minimum trade count.

### What this means for you

- Treat **WR 53%, PF ≈ 1.1** (the intraday option) as the realistic ceiling for rule-based
  gold trading from price data on these horizons, before costs that depend on your broker.
- A published backtest showing WR > 60% **and** PF > 4 on gold would normally be explained
  by one of: unpaid or fixed-low spread, stop-vs-target resolved on bar OHLC, in-sample
  fitting, a single bullish regime, or survivorship in which configs were reported.
  This harness removes all of those, which is why its numbers are smaller.
- To change the answer you would need information that is **not** in the price series
  (order flow / depth, positioning, scheduled-news reaction data), or a different
  execution setup (lower-cost venue, limit-order entries with real queue modelling).
  Neither can be tested with the data available here.

Code: `xau_meta.py`, `run_meta.py` (`results/meta_{5min,15min,1h}.jsonl`). Run
`OMP_NUM_THREADS=1 python3 run_meta.py 15min` — set the thread count, or the workers
thrash and a one-minute job takes twenty.

---

## Round 3 — candle-by-candle replay and a "better bot" attempt

**Result: the replay engine is a real upgrade and it proves the backtest is honest. The strategy
itself did not get better — no tweak survived — and the account-level numbers are modest.**

### 1. The replay engine (`replay_engine.py`)

Walks M1 candles one at a time and does only what a live bot can: builds signal bars as candles
arrive, calls `bot_gold.latest_signal()` (the live function) on a trailing 900-bar window, fills at
the next candle's open (ask/bid), manages stop / target / time-exit per candle (stop wins a tie,
gaps fill at the open, flat before any market closure), sizes in **real 0.01-lot steps from
compounding equity**, charges commission and slippage, and marks equity to market every candle.

```bash
python3 replay_engine.py --config configs/gold_intraday.json --start 2025-01-01 --end 2025-07-01 \
    --risk 1.0 --out results/replay/h1_2025        # -> trades csv + equity/drawdown chart
```

**Integrity check — does it reproduce the vectorised backtest trade for trade?**
544 of 546 trades identical (entry time, direction); worst R difference 5e-5; **0 trades the
vectorised engine lacks.** Every year 2020–2026 matches perfectly. The 2 exceptions are the first
two trades in the dataset (Jan 2019), which fire before 800 bars of history exist; the replay
refuses to trade without a full window, as the live bot does. (A first run showed 7 misses: the
replay's lead-in was measured in wall-clock time and weekends have no bars. Fixed.)

### 2. Improvement study (`improve_gold.py`)

21 single-change variants, each motivated by the diagnosis: trend alignment (3 lengths), confirmation
bar, panic-volatility floor, hold length, stop width, band width, RSI threshold, and a trend-gated
short side. A change was accepted only if it improved PF on **both** train (2019-22) and validation
(2023-24) with a usable sample. **0 of 21 were accepted.** Variants that looked good in one period
flipped in the other (`trend_ema=1000`: train PF 0.88 → validation 1.61); the ones that improved both
did so on 30–69 trades. The base configuration is a local optimum within noise, so it is unchanged.
Full table: `results/improve_gold_output.txt`.

### 3. Win rate vs profit factor — the frontier on the same signal

| Exit | Win rate | PF (all years) | avg win / avg loss |
|---|---|---|---|
| target 0.1R | **83.0%** | 0.82 | +0.10 / −0.59 |
| target 0.2R | 72.7% | 1.03 | +0.20 / −0.51 |
| target 0.3R | 64.2% | 1.05 | +0.27 / −0.46 |
| 1R / time exit (shipped) | 53.1% | **1.11** | +0.43 / −0.44 |

Raising the win rate only converts big winners into small ones. This is why "win rate above 60%"
and "profit factor above 4" cannot both be bought with exit tweaks.

### 4. Account-level replay, 2019 → 2026-10-02 ($10,000, real lots, compounding, MTM drawdown)

| Scenario | Trades | PF ($) | Net | CAGR | Max DD | Sharpe |
|---|---|---|---|---|---|---|
| **0.5% risk** | 469 | 1.11 | +$494 | 0.62% | **4.3%** | 0.28 |
| **1.0% risk** | 533 | 1.10 | +$1,063 | 1.31% | **9.3%** | 0.28 |
| 1.0% + drawdown brake + daily-loss cap | 530 | 1.04 | +$362 | 0.46% | 8.5% | 0.12 |
| 1.0% + commission $7/lot + $0.10 slippage | 531 | 1.02 | +$227 | 0.29% | 11.0% | 0.08 |

- **The risk controls hurt.** A drawdown brake on a small mean-reverting edge cuts size right as the
  bounce arrives. They are implemented (`risk_controls()`, shared by bot and replay, unit-tested) and
  **off by default**.
- **Costs decide it.** Ordinary commission plus a little slippage takes PF from 1.10 to 1.02.
- **Lot granularity matters at $10k.** At 0.5% risk, 87 signals were too small for the 0.01-lot
  minimum and were skipped. Use ≥ $20k or 1% risk.
- **Real return is small:** about +1.3% a year at ~9% drawdown, Sharpe 0.28. A quarter can lose
  (Q1 2025: PF 0.84).

### Bottom line

What improved is **trustworthiness and realism**: a verified candle-by-candle replay, real account
sizing, shared risk code, and a quantified answer to "what happens with real lots, costs and
drawdown". What did **not** improve is the edge. I would not trade this for income; it is a research
baseline that is probably, but not provably, slightly positive before your broker's costs.

---

## Round 4 — the forex / NAS100 / SPX500 watchlist

**Coverage, stated first: this screen is incomplete.** 9 FX pairs plus gold (as a reference) were
screened. **The 2 indices (SPX500, NAS100) and 19 FX crosses were NOT**, because Dukascopy rate-limits
this server's IP (HTTP 429, an effectively multi-hour ban after the first ~1,200 requests) and no other
source reachable from here carries intraday indices. Nothing below says anything about NAS100 or
SPX500. Screened: EURUSD GBPUSD USDJPY USDCHF USDCAD AUDUSD NZDUSD EURGBP EURJPY (+ XAUUSD).

**To finish it from a normal connection** (about 1.5 h, resumable; indices are fetched first):
```bash
python3 fetch_h1.py 3                 # ~3,000 paced requests; caches per month under data/h1_raw/
python3 screen_watchlist.py           # pre-registered screen + null control
python3 deep_watchlist.py             # deep dive + permutation test on qualifiers
python3 sensitivity_watchlist.py      # plateau test + cross-section
```
Everything reads `data/h1/` or falls back to the committed `results/h1/` (10 instruments, 21 MB).

### How it was run (rules fixed before looking at results)
- H1 bid/ask bars 2019 → 2026-09. Bid is real for every month; ask is real for June of each year and
  **modelled** elsewhere as bid + the median spread for that (year, UTC hour). Spreads are Dukascopy's
  feed (EURUSD 0.3–0.7 pips) and tighter than most retail brokers.
- **10 fixed configs applied identically to every instrument — no per-instrument tuning**: fade (3.0σ/RSI20
  and 2.5σ/RSI25, 4h and 8h holds), the same four long-only, and momentum (20-bar break + EMA stack,
  RSI>70 / RSI>75, 8h). Stop 3 ATR, time exit.
- Per instrument, the config best on **train (2019-22)** is chosen; it *qualifies* only if PF > 1.05 on
  train **and** validation (2023-24). Test (2025+) is reported last.
- **Null control:** the same procedure on randomly time-shifted signals (same frequency, no information).
- Fidelity: on gold, the H1-bar engine matches the M1 engine at R-correlation 0.999–1.000 on matched trades
  with PF within ~0.05 (trade counts differ by up to 9% around gaps). Fine for ranking, not for final numbers.
  A true M1 pass was infeasible for the same rate-limit reason.

### Result 1 — the screen is at chance level
2 of 10 instruments qualified (USDJPY, USDCHF). **The null control qualifies a mean of 2.0 of 10
(runs: 0, 5, 2, 1, 2).** The qualification rule is loose enough that ~20% of instruments pass by luck, so
"qualified" is not evidence. No fade config qualified on any FX pair; gold did not qualify on this H1 screen.

### Result 2 — USDJPY momentum is the one candidate worth a second look
| | pre-registered (RSI>75, 8h) | neighbouring setting (RSI>80, 8h) — chosen *after* the plateau test |
|---|---|---|
| Trades / win rate | 426 / 49.8% | 168 / 56.5% |
| Profit factor / t-stat | **1.35** / +2.27 | **1.84** / +2.82 |
| train / valid / test PF | 1.29 / 1.69 / 1.16 | 1.60 / 2.27 / 2.06 (test n = 29, WR 69%) |
| Long / short PF | 1.54 / 1.06 | **1.86 / 1.79** — profitable on both sides |
| Max DD (risk 0.5%/trade) | 4.7% (+18.4% over 7.75y) | 2.0% (+15.4% over 7.75y) |
| Cost ×2 (double spread) | PF 1.29 | PF 1.76 |
| Permutation p (time-shift null) | 0.007 | 0.002–0.010 (two runs) |

Why it is credible: it is a **plateau, not a spike** — all 48 neighbouring configs (RSI 65–80 × 4–24h ×
2–4 ATR stops) are profitable, median PF 1.30, and PF rises *monotonically* with the RSI threshold
(1.12 → 1.84), the same dose-response gold showed; 33 of 48 are profitable in train, validation **and**
test at once; and it is robust to doubled spread, because a 3-ATR stop dwarfs FX spread.

Why it is not proven:
- **It fails the multiple-testing bar.** Bonferroni for 31 instruments needs p ≤ 0.0016; for the 10
  actually screened, 0.005. The RSI>75 p of 0.007 misses both, and the RSI>80 p was chosen post hoc.
- **It is the only one.** The same RSI>80 rule loses on EURGBP (PF 0.59), EURUSD (0.71) and NZDUSD (0.71)
  and is flat on AUDUSD, EURJPY, USDCAD and gold (0.92–1.05). GBPUSD (1.34, p 0.055) and USDCHF (1.22,
  p 0.075) are suggestive only. One instrument at p ≈ 0.01 out of ten is not unusual by chance.
- **Small samples:** 168 trades (~22 a year); the test period is 29 trades.
- **Regime:** 2019 PF 0.79, 2021 1.08 — weak before the 2022 yen move; USDJPY went 109 → 160.
- USDCHF (median neighbour PF 1.04) and EURJPY (0.98) show no plateau.

### What this means
Nothing here approaches the earlier win-rate/profit-factor targets, and nothing is proven. The honest
reading is: *USDJPY H1 momentum after an RSI>80 break is a plausible, cost-robust, two-sided effect with
a p-value around 0.002–0.01 that would not survive a strict correction for how many things were
tried.* It deserves an out-of-sample test on the rest of the watchlist and, above all, on **new data**
(forward-test it on demo; it fires ~2 times a month). It is **not wired into `bot_gold.py`**: that bot is
gold-specific (contract size, sizing). Say the word and I will generalise it per instrument.

Files: `fetch_candles.py`, `fetch_h1.py`, `screen_watchlist.py`, `deep_watchlist.py`,
`sensitivity_watchlist.py`; outputs `results/screen_watchlist.json`, `results/deep_watchlist_output.txt`,
`results/watchlist_sensitivity.txt`, data `results/h1/`.

---

## 90-day backtest (2026-07-02 → 2026-09-30; gold bot to 2026-10-02)

Run with `python3 backtest_90d.py`; full output in `results/backtest_90d.txt`. Covers the 9 FX pairs
and gold only — **SPX500, NAS100 and 19 crosses are still unavailable** (data source throttled).
Indicators use full history; only trades *entered* in the window count.

**Read this first:** 90 days is 5–40 trades per strategy. These numbers cannot confirm or refute
anything; the lesson of the very first 90-day result in this project (PF 1.42 that collapsed to 0.92
over a year) still applies. Intervals are shown for that reason.

| Strategy | Trades | Win rate | PF | Total | Verdict |
|---|---|---|---|---|---|
| **USDJPY momentum RSI>75, 8h** (pre-registered) | **8** | 62.5% | **4.90** | +4.1R | looks great, means little: 95% CI on mean R [−0.07, +1.15], time-shift null p = 0.10. Full-history PF is 1.35. |
| USDJPY momentum RSI>80, 8h (post-hoc) | 5 | 80.0% | 4.21 | +3.2R | 5 trades. p = 0.05. |
| Momentum RSI>75, all 10 instruments pooled | 107 | 48.6% | 1.25 | +6.3R | the only config positive in aggregate; CI [−0.08, +0.21] spans zero |
| Fade configs, pooled | 50–336 each | 34–50% | 0.39–0.95 | negative | **fade 3.0σ long-only 8h is significantly negative** (CI [−0.45, −0.08]). Gold's M15 fade edge does not transfer to FX hourly bars. |
| **Gold bot** (M15 fade, long-only, vectorised, M1 fills) | 18 | 50.0% | 1.49 | +1.6R | CI [−0.19, +0.36] |
| Gold bot, candle-by-candle replay, $10k, risk 1.0% | 18 | 50.0% | 1.48 | **+$135 (+1.35%)**, maxDD 1.40% | |
| Gold bot, candle-by-candle replay, $10k, risk 0.5% | 6 | 50.0% | 2.13 | +$78 (+0.78%), maxDD 0.67% | 13 signals skipped: too small for the 0.01-lot minimum at $10k |

Single-instrument cells such as EURJPY momentum "PF 7.81" are 6 trades and are noise; the permutation
null on USDJPY shows even its 8-trade PF 4.90 has p = 0.10.

---

## Best strategy / highest profit

`python3 best_strategy.py` → `results/best_strategy.txt`. "Highest profit" depends on risk taken, so the
comparison was set up to avoid rewarding a bigger bet or a lucky pick: only strategies already
identified in earlier rounds, included only if **PF > 1.05 on both train (2019-22) and validation
(2023-24)**, risk sized on the **2019-24 design period only** to a drawdown budget, and **2025+ held out
and scored once**. Post-hoc variants are shown but ineligible.

| Strategy | Train / valid / test PF | Included? |
|---|---|---|
| Gold M15 fade (long-only) | 1.06 / 1.16 / 1.18 | yes |
| USDJPY H1 momentum RSI>75 | 1.29 / 1.69 / 1.16 | yes |
| USDCHF H1 momentum RSI>75 | 1.11 / 1.09 / 1.24 | yes |
| USDJPY RSI>80 | 1.60 / 2.27 / 2.06 | **no — chosen after seeing results** |
| Gold M5 momentum RSI>75 ("v2") | 0.85 / 0.79 / 1.57 | no — loses in 6 of 8 years |

**The three included edges are uncorrelated** (daily-R correlation −0.06 to +0.08), which is the one
legitimate way to raise profit without raising drawdown.

Equal-risk portfolio, event-driven shared equity (drawdown on realised equity; bootstrap = same trades
reshuffled, since one historical path understates drawdown risk):

| Risk budget | Full 2019-26 | Max DD (hist / bootstrap 95th) | **Held-out 2025+** | CAGR | Sharpe |
|---|---|---|---|---|---|
| 1.0% | +21.3% | 4.6% / 7.9% | **+4.3%** (DD 3.9%) | 2.5% | 0.72 |
| 2.0% | +46.3% | 9.1% / 15.4% | **+8.6%** (DD 7.6%) | 5.0% | 0.72 |
| 3.0% | +75.2% | 13.5% / 22.4% | +12.9% (DD 11.2%) | 7.5% | 0.72 |

Sharpe is the same at every size — profit scales with risk and so does drawdown; sizing does not create edge.

Strategy by strategy at a 5% design-DD budget: gold fade +5.0%, USDJPY +18.4% (held-out only +1.7%: most
of it was earned in 2022-24), USDCHF +8.4%, **portfolio +21.3% (held-out +4.3%, best of the group out of
sample)**. The hindsight pick, USDJPY RSI>80, shows +40.5% (Sharpe 0.81) — the biggest number available,
and exactly the kind you should not trust: it was selected after the data was seen.

**Honest answer:** the best strategy is the *portfolio*, not any single rule; realistic expectation is
**roughly 2-5% a year at a 5-9% drawdown**, with a plausible worst case of ~15% at the 2% budget. It is
a thin edge, not a high-profit one, and only the gold leg is wired into `bot_gold.py`
(`configs/best_portfolio.json`).

---

## SMC + kill zones (gold) — a fresh start, no earlier strategy reused

**Result: no edge. 0 of 48 configurations qualify, and the pattern shows no directional information.**
Win rate 35–46%, median profit factor ~0.8. I would not trade it, and I have not written a Pine/bot for it.

**What was built** (`smc.py`, `smc_exec.py`, all causal — nothing repaints): kill zones in New York time
(London 02:00–05:00 ET, NY AM 07:00–10:00 ET, so daylight saving is right); liquidity pools (Asian range,
London range, previous-day high/low, or rolling swing points); a **sweep with reclaim**, then a
**displacement candle that breaks structure (MSS)** leaving a **fair value gap**; limit entry at the gap
midpoint or near edge; stop beyond the sweep extreme; optional higher-timeframe bias. Fills are
pessimistic: a limit fills only if ask/bid trades through it, a bar that also reaches the stop is a loss,
the fill bar's target is not credited, gaps fill at the open.

**Pre-registered grid, real M1 bid/ask, 2019 → 2026-10:** TF {M5, M15} × liquidity {session, swing} ×
entry {FVG mid, edge} × HTF bias {off, on} × reward:risk {1, 2, 3} = 48. Ranked on train (2019-22);
qualify only if PF > 1.05 on train **and** validation (2023-24).

| | Result |
|---|---|
| Qualifiers | **0 of 48** |
| Best train PF | 1.02 (then 0.84 on validation) |
| Median PF, train / validation | 0.78–0.82 / 0.69 |
| Win rate by reward:risk 1 / 2 / 3 | 44.0% / 36.7% / 35.1% — the usual trade-off: a higher win rate costs payoff, and neither pays |
| London KZ vs NY AM KZ | PF 0.75 vs 0.79 — both lose |
| Long vs short | PF 0.80 vs 0.78 — both lose |

**Is it my fill model?** No. (1) Entering **at market** instead of with a limit: 24 configs, 0 qualify,
median PF 0.82 / 0.76 (limit entries suffer adverse selection, but that is not the cause).
(2) Trading the **mirror** of every signal also loses (PF 0.86–0.90): the pattern is not anti-predictive
either, costs eat both sides. (3) With **no exits or fills at all**, the signed move after the signal is
inside the random band on M15 at every horizon (1h/3h/6h, t between −0.75 and +0.87).

**What kill zones do have is movement, not direction:** mean bar range is 1.21 ATR (London) and 1.47 (NY)
versus 0.90 outside. That is why traders like them; it does not tell you which way price goes.

**One loose thread (exploratory, post-hoc, contaminated):** on **M5** the signed move after a setup is
*negative* (t −2 to −3 pooled): price tends to reverse the setup — a mean-reversion effect, consistent with
the gold fade found earlier, not an SMC edge. Trading the inverse gives PF 1.20–1.52 on train/validation for
the swing variant but **0.90–0.93 on the 2025+ test**; the session variant is 0.98 / 1.05 / 1.16. It does
not hold across all three periods and the effect is the same size as the spread (~0.044R/trade).
`smc_inverse.py` reproduces it.

Files: `smc.py`, `smc_exec.py`, `run_smc.py`, `smc_market_diag.py`, `smc_info_test.py`, `smc_inverse.py`;
outputs `results/smc_grid.json`, `results/smc_market_diag.json`, `results/smc_info_test.txt`,
`results/smc_inverse.txt`.
