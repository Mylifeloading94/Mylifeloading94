# XAUUSD TradeLocker Automated Scalping System

An event-driven, regime-gated XAUUSD intraday system with three strategies, a
full risk engine, a realistic backtester, and a TradeLocker execution layer.

**Status: the deployment gate PASSES. Demo forward testing may begin. Not live.**

Validated on 4,070,991 real XAUUSD M1 bars, 2015-01-01 → 2026-08-21.

---

## Results — shipped configuration, held identical throughout

$500 account, 0.50% risk per trade, 0.001 (micro) minimum lot.

| Year | Trades | Win% | PF | Return | Max DD |
|---|---|---|---|---|---|
| 2015 | 14 | 28.6% | 0.17 | −0.95% | 0.95% |
| 2016 | 35 | 51.4% | 1.09 | +0.25% | 0.84% |
| 2017 | 1 | — | — | +0.09% | 0.00% |
| 2018 | 2 | 0.0% | 0.00 | −0.10% | 0.10% |
| 2019 | 19 | 36.8% | 0.52 | −1.02% | 1.40% |
| 2020 | 88 | 51.1% | 1.12 | +1.08% | 1.84% |
| 2021 | 61 | 34.4% | 0.57 | −3.04% | 3.77% |
| 2022 | 83 | 41.0% | 0.73 | −3.00% | 3.00% |
| 2023 | 49 | 53.1% | 1.51 | +2.29% | 1.59% |
| 2024 | 105 | 53.3% | 1.38 | +4.10% | 1.45% |
| 2025 | 220 | 60.0% | 1.64 | +15.44% | 2.81% |
| **2026 (holdout)** | **91** | **52.7%** | **1.21** | **+3.31%** | **3.76%** |

**Pooled 2015–2026: 768 trades, 51.0% win rate, PF 1.19, expectancy +0.056R.**

Walk-forward, config fixed, rolling 6-month blocks 2019–2026:
**10 of 14 blocks profitable (71%)**, median block PF 1.12, median block win
rate 49.4%, worst block −3.25%.

Monte Carlo, 5,000 resamples with reshuffling, 10% missed trades, cost shocks
and R noise: **76.1% probability of profit**, median max drawdown 7.2%, p95
11.1%, worst 21.4%, probability of 50% ruin 0.0%.

Full detail: `reports/FINAL_REPORT_V3.txt`.

### On the win rate

**51% pooled, 52.7% on the 2026 holdout. That is not a high win rate, and
60%+ was not achievable.** This is a cost constraint, not a tuning failure:

| Win rate | 0.5R payoff | 1.0R | 1.5R | 2.0R |
|---|---|---|---|---|
| 50% | PF 0.50 | 1.00 | 1.50 | 2.00 |
| 60% | 0.75 | 1.50 | 2.25 | **3.00** |
| 70% | 1.17 | 2.33 | 3.50 | 4.67 |

A 60% win rate at PF 3.0 needs a 2.0R average payoff *at 60% accuracy*. High
win rates come from small targets — and small targets are where the spread
eats you. Measured round-trip cost as a share of a 1×M5-ATR move:

| Year | Gold | M5 ATR | Cost as % of a 1-ATR target | Break-even win rate on a 1:1 |
|---|---|---|---|---|
| 2016 | $1,250 | $0.81 | 47.2% | 73.6% |
| 2019 | $1,394 | $0.63 | 60.3% | 80.2% |
| 2022 | $1,801 | $1.16 | 31.7% | 65.8% |
| 2024 | $2,389 | $1.48 | 25.5% | 62.7% |
| 2026 | $4,575 | $5.42 | 7.0% | 53.5% |

Configurations that *did* show 57–60% win rates in testing (0.5R targets) all
had profit factors of 0.47–0.65. They lose money. A high win rate is easy to
manufacture and worthless on its own; this system optimises expectancy and
accepts the win rate that comes with it.

### What the search actually found

Four things, in the order they were established, each on the full 11.6 years:

1. **Exit geometry cannot rescue a bad entry.** A forward-excursion study over
   4,795 signals in 2015–2021 evaluated 42 stop/target combinations on an
   identical entry set. Every one had negative expectancy; the best was
   −0.044R. The "highest win rate with positive expectancy" list was empty.

2. **Cost is the dominant variable** (table above). Short-horizon gold trading
   was structurally impossible for most of the last decade.

3. **Directional information exists but is small.** Triple-barrier labelling
   over 4.04M bars: baseline P(up first) = 49.85%. The strongest single
   conditions reach ~52% — real (z up to 20) but barely above the cost hurdle.
   The sign also flips between eras: mean reversion paid 2015–2023, momentum
   pays 2024–2026.

4. **Gross vs net separates the two explanations.** With costs zeroed, the same
   entries are positive in the high-volatility era (PF 1.22) and negative in
   the cheap-gold era. The entries do carry signal; costs were eating it.

The fix follows directly: widen the stop and target so the round trip is a
small fraction of the target, and refuse setups where it is not.

---

## The configuration

```
stop        = 3.0x the structural invalidation distance
target      = 1.0R          (no partials, no breakeven, no trailing)
entry gate  = retest AND M15 alignment required
cost filter = round trip must be <= 3% of the target
max hold    = 480 min, flat by 21:00 UTC, no overnight positions
risk        = 0.50% per trade, one position at a time
```

Partials, breakeven moves and trailing stops are **off**. Each was an
unvalidated free parameter that flattered the backtest without earning its
keep, so each was removed.

The cost filter is what makes the system volatility-aware, and it is why the
bot barely trades in 2015–2019 (1–35 trades a year): it correctly refuses a
market where the spread is half the move it is trying to catch.

### Chosen on a plateau, not a peak

Every neighbouring geometry was scored on the full span. The differences are
small — the signature of a plateau rather than a fitted point:

| Configuration | n | Win% | PF | Blocks profitable |
|---|---|---|---|---|
| stop 2.5× / 1.00R / cost ≤3% | 572 | 52.4% | 1.19 | 6/11 |
| stop 2.5× / 1.25R / cost ≤3% | 810 | 49.8% | 1.20 | 8/14 |
| **stop 3.0× / 1.00R / cost ≤3%** | **691** | **51.1%** | **1.19** | **10/14** |
| stop 3.0× / 1.25R / cost ≤3% | 954 | 46.8% | 1.08 | 9/14 |
| stop 2.5× / 1.50R / cost ≤3% | 1033 | 46.4% | 1.11 | 7/14 |

The shipped point was chosen for **block stability (10/14)**, not for the best
headline number.

---

## Account size — read this before funding anything

The validated stop is roughly **$21 wide on 2026 gold**. What that costs:

| Min lot | Loss at a $21 stop | % of $500 | Equity needed for 0.5% risk |
|---|---|---|---|
| 0.001 (micro) | $2.10 | 0.42% | $420 — **works** |
| 0.01 (standard) | $21.00 | 4.20% | **~$4,200** |

Forced onto 0.01 lots at $500, the 2026 holdout **loses 40% with a 53%
drawdown**. All results above use 0.001 lots. Confirm your broker offers micro
lots on gold before anything else; if it does not, this account is too small
for this system and no amount of strategy work changes that.

---

## Honest limitations

- **The edge is thin.** Expectancy +0.056R per trade. It is real across 768
  trades and 12 years, but it is not a money printer, and a bad six months is
  well within normal (worst block −3.25%).
- **It is regime-dependent.** Losing years 2015, 2019, 2021, 2022. The cost
  filter suppresses trading in cheap-gold eras but does not make them
  profitable. If gold's volatility collapses back toward 2019 levels, expect
  this to stop trading — that is the design working, not a bug.
- **Some of it is a bull market.** 2024–25 longs materially outperformed
  shorts. On the 2026 holdout the asymmetry disappeared (longs 49% win, shorts
  56%), which is mildly reassuring, but the system has never seen a sustained
  gold bear market at high volatility.
- **The news filter is inactive.** No calendar file is supplied, so no
  CPI/NFP/FOMC blackouts were applied. The filter prints `INACTIVE` rather than
  silently passing everything. Real event risk would likely make these results
  worse.
- **Bar data, not tick data.** Intrabar path is unknown, so the fill model
  always resolves ambiguity against the strategy.
- **No live TradeLocker verification.** No credentials were available, so the
  client, guard and managers are covered by a fake-broker test suite
  (transport failure, unknown fills, missing stops, duplicate-order
  prevention, reconciliation) but have not been run against the real API.
- **The holdout is not pristine.** 2026 was never used to fit the geometry,
  gate or filters, but it was included in the aggregate era study that
  motivated the cost filter. Treat the 2026 numbers as good, not immaculate.

---

## Architecture

```
REAL-TIME DATA -> VALIDATION -> REGIME ENGINE -> STRATEGY SELECTOR
  -> STRATEGY SIGNAL -> SETUP SCORE -> RISK ENGINE -> EXECUTION
  -> TRADE MONITOR -> JOURNAL -> ANALYTICS
```

```
xauusd_bot/
├── bot.py                  entry point; blocked unless the gate passes
├── config.py               every tunable number, in one place
├── pipeline.py             shared bars -> result path
├── deployment_gate.py      the go/no-go checklist
├── data/                   histdata_provider, data_engine, indicators,
│                           structure, sessions, validators
├── strategy/               regime_engine, trend_continuation,
│                           liquidity_reversal, breakout, setup_scorer, selector
├── research/               excursion (forward-path study), loader
├── risk/                   risk_manager, position_sizer, kill_switch
├── execution/              tradelocker_client, execution_guard,
│                           order_manager, position_manager
├── backtesting/            engine, simulator, metrics, reports
├── optimization/           splits, objective, optimizer, walk_forward,
│                           sensitivity, monte_carlo
├── news/ monitoring/ journal/ tests/ reports/
```

### Anti-lookahead
HTF frames carry an explicit `close_time`; alignment uses
`merge_asof(direction="backward")` on it, so an M15 bar labelled 09:00 is
invisible until 09:15. Swings are stamped at the bar where they became
confirmable. `tests/test_lookahead.py` truncates the data, recomputes, and
asserts every past value is bit-identical — on synthetic *and* real data. Two
genuine lookahead bugs were found and fixed this way.

### Fill realism
Signals compute at bar close and fill at the **next** bar's open, plus half
spread plus slippage. When a bar contains both the stop and the target, the
**stop** fills first. Gaps through a stop fill at the bar open. Limit fills get
no positive slippage. Spread is session-based and widens with realised
volatility.

---

## Running it

```bash
pip install -r xauusd_bot/requirements.txt

python3 -m pytest xauusd_bot/tests/ -q     # 56 tests

python3 fetch_history.py                   # 2015-2026 M1 (~4M bars)
python3 build_features.py                  # yearly feature chunks
python3 final_report.py                    # reports/FINAL_REPORT_V3.txt
python3 validate_v3.py                     # walk-forward + Monte Carlo + gate

# research that produced the configuration
python3 cost_analysis.py                   # cost vs volatility by year
python3 barrier_scan.py                    # directional edge, 4M bars
python3 era_study.py                       # gross vs net by era
python3 fit_cheap_era.py                   # geometry + filters on 2024-25
python3 plateau_sweep.py                   # neighbours over the full span

cp xauusd_bot/.env.example .env            # then fill it in
python3 xauusd_bot/bot.py --mode demo
python3 xauusd_bot/bot.py --mode live --confirm-live   # + LIVE_TRADING=true
```

Live mode requires `--confirm-live` **and** `LIVE_TRADING=true` **and** a
passing gate. All three.

## Next steps before real money

1. Demo forward test until the forward monitor's rolling expectancy agrees
   with +0.056R. At ~1.3 trades/day that is roughly two months for 50 trades.
2. Confirm the broker's real minimum lot and spread — the whole edge lives
   inside a 3%-of-target cost budget, so a 0.45 spread instead of 0.29
   materially changes these numbers.
3. Supply a real news calendar and re-run; expect the results to get worse.
4. Then a small live allocation, with the forward monitor's PAUSE authority
   respected.
