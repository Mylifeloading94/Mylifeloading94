# SMC Sniper AI Forex Trading Bot

A Smart Money Concepts sniper system: multi-timeframe bias, liquidity sweeps,
market-structure shifts, order blocks / fair value gaps, and a hard scoring
gate. Built to the owner's spec, backtested on real broker data, and reported
honestly.

---

## STATUS — read this first

**It does not hit 68%. It does not clearly have an edge. Do not trade it live.**

| | Long-window stack (1H setup, ~1200d) |
|---|---|
| Full window | **151 trades, 53.6% WR, PF 1.11, expectancy +0.052R** |
| Win-rate 95% CI | **45.7% – 61.6%** (a 16-point span) |
| Expectancy 95% CI | **−0.119R to +0.221R — spans zero** |
| Walk-forward (out-of-sample) | **129 trades, 55.8% WR, PF 1.21, +0.092R** |
| Max drawdown | 3.74% · longest losing streak 7 |
| **68% target reached?** | **NO — 53.6% full window, 55.8% walk-forward** |

The honest summary: this is a *correctly built* SMC system whose measured edge
is **statistically indistinguishable from zero**. The expectancy confidence
interval contains zero, which means the data cannot rule out that this system
makes no money. Profit factor above 1.0 and a positive walk-forward are
encouraging, not conclusive.

What it is **not**: it is not overfit to a win rate, it is not shrinking targets
to buy a win rate (the matched-R control proves the opposite), and it is not
hiding costs. The number is low because the accounting is honest.

Per the spec's own instruction — *"do not claim a 68% win rate unless the actual
test data demonstrates it"* — the target is reported **against**, not toward.
The spec also says *"a lower win rate with substantially better expectancy is
preferable to an overfit strategy."* This is the lower win rate. The better
expectancy has not been demonstrated yet.

**Next step is a forward demo run, not capital.** Paper/demo results:
**PENDING DEMO RUN.**

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

All figures from TradeLocker broker bars (BID), 13 pairs, risk 0.5%/trade,
score gate 80/95. **In-sample, out-of-sample and walk-forward are kept
separate.** Do not quote any single row on its own.

### Long-window stack — 1D bias / 4H structure / 1H setup, ~1200 days

| Split | Window | Trades | Win rate | 95% CI | PF | Expectancy |
|---|---|---|---|---|---|---|
| **IN-SAMPLE (train)** | 2023-05 → 2024-12 | 73 | 50.68% | — | 1.022 | +0.011R |
| **VALIDATION** | 2024-12 → 2025-08 | 40 | 60.00% | — | 1.457 | +0.176R |
| **OUT-OF-SAMPLE (test)** | 2025-08 → 2026-08 | 38 | 52.63% | — | 0.996 | +0.002R |
| **FULL WINDOW** | 2023-05 → 2026-08 | 151 | 53.64% | 45.7–61.6% | 1.113 | +0.052R |
| **WALK-FORWARD (OOS only)** | 5 rolling folds | **129** | **55.81%** | 47.3–63.6% | **1.210** | **+0.092R** |

Walk-forward folds (fit → immediately following unseen window):

| Fold | Fit trades | Fit WR | Fit E | OOS trades | OOS WR | OOS E |
|---|---|---|---|---|---|---|
| 1 | 22 | 40.91% | −0.180R | 27 | 59.26% | +0.158R |
| 2 | 27 | 59.26% | +0.158R | 24 | 50.00% | +0.020R |
| 3 | 24 | 50.00% | +0.020R | 36 | 58.33% | +0.080R |
| 4 | 36 | 58.33% | +0.080R | 23 | 56.52% | +0.248R |
| 5 | 23 | 56.52% | +0.248R | 19 | 52.63% | −0.078R |

The TRAIN→TEST gap is small (50.7% → 52.6%), which argues *against* overfitting.
But TEST profit factor is 0.996 — flat. Validation's 60% / PF 1.46 is the best
window and should be read as the luckiest one, not the true rate.

### Matched-R control — the anti-TP-shrinking check

Same entries, management stripped off, one flat target at each R:

| Fixed R | Trades | Win rate | Break-even WR needed | PF | Expectancy |
|---|---|---|---|---|---|
| 1.0R | 150 | 56.67% | 50.0% | 1.109 | +0.049R |
| 1.5R | 128 | 41.41% | 40.0% | 0.924 | −0.046R |
| 2.0R | 149 | 38.93% | 33.3% | 1.118 | +0.078R |
| 2.5R | 144 | 32.64% | 28.6% | 1.038 | +0.027R |
| 3.0R | 146 | 30.14% | 25.0% | 1.075 | +0.059R |
| 4.0R | 147 | 27.21% | 20.0% | **1.166** | **+0.131R** |

Win rate falls monotonically as the target widens — that is the expected
mechanical relationship. The important part: **expectancy is best at the
*widest* target (4R), not the narrowest.** A win rate bought by shrinking
targets shows the opposite. This system is not doing that.

### Pair selection — a cautionary result

Selecting pairs on TRAIN only (the correct protocol) picked a single pair,
which then returned **5 trades at 40% WR and PF 0.019** on TEST. Per-pair
samples here are far too small to select on; doing it destroyed performance.
The walk-forward therefore keeps all pairs and says so, rather than
manufacturing a selection the data cannot support.

### Spec-native stack — 4H bias / 1H structure / 15m setup, ~400 days

Reported separately because the sample is much smaller and cannot carry a
conclusion on its own: **47 trades, 51.1% WR, PF 1.02, expectancy +0.010R**
(95% CI on win rate 36.2–63.8%). At the conservative 85 gate this stack
produces **3 trades in 400 days** — correct sniper behaviour, statistically
useless. This is the honest cost of the spec's selectivity at 15m.

---

## Caveats

Read these before quoting any number above.

1. **The edge is not statistically established.** The expectancy CI spans zero
   (−0.119R to +0.221R). 151 trades is a small sample for a 53% win rate; the
   win-rate CI is 16 points wide. Anyone quoting "53.6%" to one decimal is
   over-claiming.

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

7. **Session structure is a hypothesis, not a validated filter.** Session
   filters have inverted between train and test in this repo before. London and
   NY are used per the spec, and per-session results are reported so an
   inversion is visible.

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
