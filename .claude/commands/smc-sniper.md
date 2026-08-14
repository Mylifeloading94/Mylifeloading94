# SMC Sniper AI Forex Trading Bot

A Smart Money Concepts sniper system: multi-timeframe bias, liquidity sweeps,
market-structure shifts, order blocks / fair value gaps, and a hard scoring
gate. Built to the owner's spec, backtested on real broker data, and reported
honestly.

---

## STATUS — read this first

<!--STATUS_BLOCK-->

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

<!--RESULTS_BLOCK-->

---

## Caveats

<!--CAVEATS_BLOCK-->

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
