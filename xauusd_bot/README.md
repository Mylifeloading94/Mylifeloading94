# XAUUSD TradeLocker Automated Scalping System

An event-driven, regime-gated XAUUSD intraday system with three independent
strategies, a full risk engine, a realistic backtester, and a TradeLocker
execution layer.

**Status: BUILT AND VALIDATED — DEPLOYMENT REFUSED.**
The system works; the *strategies* do not have a demonstrable edge on the data
tested. The deployment gate fails and `bot.py` will not place an order.
See [Results](#results) — the numbers are real and not flattered.

---

## Results

Real XAUUSD M1 bars from HistData.com, **2026-01-01 → 2026-08-21**
(226,604 bars, 194 trading days), $500 starting equity.

### 0.01 standard lot (default contract)

At 0.01 lots gold is **$1 of P&L per $1 of price movement**, so risk per trade
is decided by the stop distance, not by a risk percentage. The 0.50% target is
unreachable; the min-lot rejection must be overridden and a hard risk cap
decides which setups are still refused.

| Hard cap | Trades | Win% | Net PF | Return | Max DD | Median risk/trade |
|---|---|---|---|---|---|---|
| 1.0% | 2 | 50.0% | — | +1.00% | 0.01% | 0.88% |
| **2.0%** | **74** | **41.9%** | **1.00** | **−0.18%** | **21.01%** | **1.67%** |
| 3.0% | 84 | 40.5% | 0.89 | −11.66% | 21.09% | 2.20% |
| uncapped | 79 | 35.4% | 0.68 | **−46.02%** | **57.09%** | 4.15% |

A 1% cap leaves 2 trades in eight months — not a system. The 2% cap is the
only variant that both trades and survives, and it is dead flat (PF 1.00) with
a **21% drawdown**. Uncapped, the account loses nearly half its value.

Splits at 0.01 lot / 2% cap:

| Window | Trades | Win% | Net PF | Return | Max DD |
|---|---|---|---|---|---|
| In-sample Jan–May | 37 | 56.8% | 1.81 | +22.13% | 4.83% |
| Validation Jun–Jul (unseen) | 12 | 41.7% | **0.67** | −3.41% | 5.37% |
| Holdout Jul–Aug (opened once) | 16 | 18.8% | **0.30** | **−13.02%** | 13.02% |

Walk-forward: 3 of 6 windows profitable, **median** OOS PF 1.25 (mean 2.08,
inflated by one 5-trade window), 28 out-of-sample trades total.
Monte Carlo: probability of profit **9.2%**, median max drawdown 19.9%, p95
29.9%, worst 43.8%.

### 0.001 micro lot (0.50% risk honoured)

| Window | Trades | Win% | Net PF | Return | Max DD |
|---|---|---|---|---|---|
| Full sample (untuned) | 160 | 40.0% | **0.86** | −4.91% | 7.56% |
| In-sample (Jan–May, tuned on) | 36 | 52.8% | 1.27 | +1.71% | 1.20% |
| Validation (Jun–Jul, unseen) | 12 | 33.3% | **0.50** | −1.38% | 2.03% |
| Holdout (Jul–Aug, opened once) | 11 | 27.3% | **0.63** | −0.86% | 2.33% |

Walk-forward: 2 of 6 windows profitable, median OOS PF 0.58, mean expectancy
−0.172R. Monte Carlo: probability of profit **0.0%**.

### Lot size does not change the edge

Expectancy per trade is essentially zero at both sizes (−0.013R at 0.01/2% cap,
−0.082R at 0.001). Lot size only scales the swings: the same non-edge produces
a 7.6% drawdown at 0.001 lots and a 21%–57% drawdown at 0.01. The small
apparent improvement at 0.01 lots comes from the 2% cap **filtering out
wide-stop setups**, which is a trade filter, not a sizing effect — and it does
not survive the holdout (PF 0.30).

**Against the stated targets** (60%+ win rate, PF 3.0+): not met at either lot
size, and the gap is not a tuning problem — every configuration that looked
good in-sample degraded out-of-sample.

Full detail: `reports/PERFORMANCE_REPORT.txt` and
`reports/PERFORMANCE_REPORT_001LOT.txt`.

### Two findings that matter more than the P&L

**1. A $500 account cannot trade standard-contract XAUUSD within the stated
risk limits.** One standard lot is 100 oz, so the 0.01 minimum lot is $1 per
$1 of gold movement. Gold's M5 ATR in 2026 ran $3–6, giving structural stops
of $3–15. At the 0.01 minimum that is **0.6%–3.0% risk per trade** on $500 —
above the 0.25–0.50% target. With the risk limits enforced the sizer rejects
every setup and the backtest takes **zero trades**; with the override enabled
the account carries 1.7%–4.2% median risk per trade and 21%–57% drawdowns.
The daily 1.5% loss lock then fires on almost every losing trade (50 of 74
trades at the 2% cap risk more than the entire daily allowance), so the risk
framework spends most of its time locked out. Confirm your broker's minimum
lot before anything else — on a standard contract this account size is not
viable.

**2. The in-sample optimum was worse out-of-sample than not optimising at
all.** IS-tuned PF 1.27 → validation PF 0.50, versus untuned PF 0.99 on the
same validation block. The in-sample winner also failed its own profit
concentration test: the top 5 trades produced 204% of net profit, i.e.
everything else lost money.

---

## Why the system still refuses to trade

`deployment_gate.py` runs before any order can be placed, in demo *and* live:

```
0.001 micro lot                                   0.01 standard lot / 2% cap
[FAIL] walk-forward stability >= 60%   — 33.3%    [FAIL] stability >= 60%   — 50.0%
[FAIL] median OOS PF > 1.0             — 0.58     [PASS] median OOS PF      — 1.25
[FAIL] OOS sample size >= 100 trades   — 49       [FAIL] OOS sample size    — 28
[FAIL] mean OOS expectancy > 0         — -0.172R  [PASS] mean OOS expectancy— +0.125R
[FAIL] Monte Carlo P(profit) >= 60%    — 0.0%     [FAIL] MC P(profit)       — 9.2%
VERDICT: DO NOT DEPLOY                            VERDICT: DO NOT DEPLOY
```

The gate judges walk-forward robustness on the **median** window, not the
mean — six windows are far too few for a mean to mean anything, and the
0.01-lot mean of 2.08 is one 5-trade window.

`bot.py` exits with code 2 when the gate fails. This is deliberate: the point
of the gate is that it is allowed to say no.

---

## Architecture

```
REAL-TIME DATA -> VALIDATION -> REGIME ENGINE -> STRATEGY SELECTOR
  -> STRATEGY SIGNAL -> SETUP SCORE -> RISK ENGINE -> EXECUTION
  -> TRADE MONITOR -> JOURNAL -> ANALYTICS
```

```
xauusd_bot/
├── bot.py                  entry point; blocked by the deployment gate
├── config.py               every tunable number, in one place
├── pipeline.py             shared bars -> result path (no divergence between
│                           backtest, walk-forward and live)
├── deployment_gate.py      the go/no-go checklist
├── data/
│   ├── histdata_provider.py   real M1 download + cache
│   ├── data_engine.py         multi-TF features, anti-lookahead alignment
│   ├── indicators.py          causal indicators only
│   ├── structure.py           confirmation-stamped swings, BOS/CHoCH
│   ├── sessions.py            UTC session map, 21:00 trading-day boundary
│   └── validators.py          data quality report (never silently repairs)
├── strategy/
│   ├── regime_engine.py       12 regimes + confidence score
│   ├── trend_continuation.py  pullback-in-trend
│   ├── liquidity_reversal.py  sweep -> rejection -> CHoCH -> displacement
│   ├── breakout.py            compression -> confirmed break -> momentum
│   ├── setup_scorer.py        0-100 quality score
│   └── selector.py            one strategy owns each decision
├── risk/                   risk_manager, position_sizer, kill_switch
├── execution/              tradelocker_client, execution_guard,
│                           order_manager, position_manager
├── backtesting/            engine, simulator (costs/fills), metrics, reports
├── optimization/           splits, objective, optimizer, walk_forward,
│                           sensitivity, monte_carlo
├── news/                   news_filter
├── monitoring/             dashboard, alerts, forward_monitor
├── journal/                trade_journal (SQLite + CSV)
├── tests/                  56 tests
└── reports/                generated output
```

### Anti-lookahead
Higher-timeframe frames carry an explicit `close_time`; alignment to the M1
clock uses `merge_asof(direction="backward")` on that column, so an M15 bar
labelled 09:00 is invisible until 09:15. Swings are stamped at the bar where
they became confirmable, not at the swing itself. `tests/test_lookahead.py`
truncates the data, recomputes, and asserts every past value is bit-identical
— on synthetic *and* real data. Two genuine lookahead bugs were found and
fixed this way (the completed Asian range being visible during the Asian
session; the previous-day level mapping).

### Fill realism
Signals compute at bar close and fill at the **next** bar's open, plus half
spread plus slippage. When a bar contains both the stop and the target, the
**stop** is assumed to fill first. Gaps through a stop fill at the bar open.
Limit fills receive no positive slippage. Spread is session-based and widens
with realised volatility.

---

## Running it

```bash
pip install -r xauusd_bot/requirements.txt

python3 -m pytest xauusd_bot/tests/ -q     # 56 tests
python3 run_backtest.py                    # 0.01 vs 0.001 contract modes
python3 run_001lot.py                      # 0.01 lot across four risk caps
python3 validate_001lot.py                 # 0.01 lot splits + walk-forward + MC
python3 validate_all.py                    # walk-forward + sensitivity + MC + holdout
python3 generate_report.py                 # reports/PERFORMANCE_REPORT.txt
python3 report_001lot.py                   # reports/PERFORMANCE_REPORT_001LOT.txt

cp xauusd_bot/.env.example .env            # then fill it in
python3 xauusd_bot/bot.py --mode demo
python3 xauusd_bot/bot.py --mode live --confirm-live   # also needs LIVE_TRADING=true
```

Live mode requires `--confirm-live` **and** `LIVE_TRADING=true` **and** a
passing deployment gate. All three.

---

## Honest limitations

- **7.7 months is too short.** The spec asks for 6-month train / 2-month
  validate walk-forward blocks; the requested window supports one training
  block and a handful of forward blocks with 6–13 trades each. Nothing here
  has the statistical power to confirm an edge, only to reject one.
- **~160 trades total.** At that sample size a 60% win rate has a 95% CI of
  roughly ±8 points. Small differences between configurations are noise.
- **One market regime.** Gold ran from $4,323 to ~$5,300 in this window. The
  system has not been tested through a gold bear market or a low-volatility
  regime.
- **The news filter is inactive.** No calendar file is supplied, so no
  CPI/NFP/FOMC blackouts were applied in these backtests. The filter prints
  `INACTIVE` rather than silently passing everything. Real high-impact events
  would likely make these results *worse*, not better.
- **Bar data, not tick data.** Intrabar path is unknown, which is why the
  fill model always resolves ambiguity against the strategy.
- **No live TradeLocker verification.** No credentials were available in this
  environment, so the client, guard and managers are covered by a fake-broker
  test suite (transport failure, unknown fills, missing stops, duplicate-order
  prevention, reconciliation) but have not been run against the real API.

## What would need to happen before this is worth deploying

1. Get 3–5 years of XAUUSD M1 data and re-run the whole validation suite.
2. Confirm a broker offering 0.001 lots on gold, or fund the account to a size
   where 0.01 lots is 0.5% risk. At a $3–15 stop that means roughly
   **$600–$3,000 per 0.01 lot of intended risk** — realistically $2,000+.
3. Find an edge that survives walk-forward — the current strategies do not.
   The one stable signal across all six windows was that the London/NY
   **overlap and New York sessions** outperform the London morning; that is a
   filter, not an edge.
4. Only then: demo forward test until the forward monitor agrees with the
   backtest, then a tiny live allocation.
