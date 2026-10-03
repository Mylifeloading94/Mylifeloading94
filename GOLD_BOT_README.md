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
