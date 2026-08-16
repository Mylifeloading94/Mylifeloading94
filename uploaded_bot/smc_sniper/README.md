# SMC Sniper — modular architecture

This package turns the validated sniper entry engine (`sniper_smc.py` +
`sniper_backtest.py`, one directory up) into the full module set described
in the SMC Sniper spec, without touching the entry/SL/TP logic that already
passed an honest-fill 90-day backtest. See those two files' docstrings for
the current validated numbers and caveats before changing anything here.

## Module map (spec §26)

| # | Spec module | File | Status |
|---|---|---|---|
| 1 | Market Data | `../trading_agent.py` (TradeLocker) | existing |
| 2 | Market Structure Engine | `../trading_agent.py::market_structure`, `../sniper_backtest.py::structure` | existing |
| 3 | Liquidity Detection | `../sniper_smc.py` (sweep of prior 20-bar extreme / session range) | existing |
| 4 | Order Block Detection | `../sniper_smc.py` (pre-displacement candle range) | existing |
| 5 | Fair Value Gap Detection | `../sniper_smc.py` (gap left by the MSS candle) | existing |
| 6 | Premium/Discount Engine | `scoring.py::_premium_discount` (OTE golden-pocket depth) | new |
| 7 | HTF Bias Engine | `../trading_agent.py::market_structure` on 4H | existing |
| 8 | Setup Scanner | `scanner.py::run_pipeline` | new |
| 9 | Setup Scoring Engine | `scoring.py` | new |
| 10 | Risk Management | `risk.py` | new |
| 11 | Position Sizing | `risk.py::position_size` | new |
| 12 | News Filter | `news_filter.py` | new (needs a live calendar feed wired in — see below) |
| 13 | Correlation Manager | `correlation.py` | new |
| 14 | Trade Execution | `live_runner.py` (scanner-pipeline wired to TradeLocker orders) | new |
| 15 | Position Management | `risk.py::assert_sl_not_widened`, `config.py::PARTIAL_TARGETS` | new (partial config only) |
| 16 | Trade Journal | `journal.py` | new |
| 17 | Backtesting Engine | `../sniper_backtest.py` + `backtest_report.py` | existing + new |
| 18 | Walk-Forward Testing | `walk_forward.py` | new |
| 19 | Monte Carlo Analysis | `monte_carlo.py` | new |
| 20 | Performance Dashboard | `backtest_report.py::print_report` | new |
| 21 | Alerts / Logging | `../autopilot.py` (Telegram) | existing |

## Live execution (`live_runner.py`)

`live_runner.run_once()` is the full SCAN -> FILTER -> SCORE -> CONFIRM ->
SIZE -> EXECUTE cycle, wired to real TradeLocker orders. Two things about
it are non-negotiable:

- **`dry_run=True` is the default everywhere** — the function signature,
  and the `__main__` block. It prints the full signal explanation for
  every setup that clears every gate and places *no order* until you pass
  `dry_run=False` explicitly. Review dry-run output before ever flipping
  that flag, especially on an account with prior drawdown.
- **No "take everything" mode exists.** Every order placed by
  `execute_plan` has already passed `scanner.run_pipeline` — instrument
  spec, spread, news, score >= `MIN_SETUP_SCORE`, R:R, position sizing,
  correlation, and daily guardrails. There is no parameter that bypasses
  the score gate; removing the discipline isn't a config change, it's a
  different, unvalidated bot.
- **Credentials**: `live_runner` imports `trading_agent.py`, which reads
  `TL_EMAIL` / `TL_PASSWORD` / `TL_SERVER` from the environment at import
  time — set those through your environment's secrets config, never in
  chat or in a file that could be committed. Because of this,
  `live_runner` is deliberately **not** imported by `smc_sniper/__init__.py`
  — every other module in this package works standalone, without live
  credentials, for backtesting/scoring/journaling. Import it explicitly
  (`from smc_sniper import live_runner`) only when you actually want live
  execution.

`config.py` centralizes every configurable threshold (spec §28) that the
other modules read from — nothing above should hard-code a number that
changes trading behaviour.

## Design choice: layered on top, not rewritten

`sniper_smc.analyze_sniper` already enforces the full institutional
sequence (HTF bias -> liquidity sweep -> MSS/displacement -> FVG/OB return)
before it ever returns a setup — that enforcement is what the 90-day
backtest validated. `scoring.py` re-verifies those same components
independently from the setup's own metadata (added to `sniper_smc.py`'s
return dict additively, see the `meta` field) rather than trusting a black
box, and grades the two genuinely continuous components (displacement
strength, R:R quality) the spec calls out as gradable. Everything in this
package composes around that engine; none of it changes its entry, stop,
or target logic.

## What's still a stub

- **News filter** (`news_filter.py`): the interface and blackout-window
  logic are real and tested, but no live economic-calendar feed is wired
  in — no such credential exists anywhere in this repo. `FileNewsCalendar`
  reads a JSON export you provide; `EmptyNewsCalendar` (no filtering at
  all) exists only for backtests that intentionally ignore news. Wire a
  live feed before trading news-sensitive size live.
- **Position management** (BE-move, partials, trailing): `config.py` holds
  the parameters (`BREAK_EVEN_R`, `PARTIAL_TARGETS`, `TRAILING_STOP_ENABLED`)
  and `risk.py::assert_sl_not_widened` is the safety guard, but the
  order-modification calls themselves belong in `trading_agent.py` /
  `autopilot.py`'s execution loop, which already implements TP1/BE logic
  for the live sniper flow — this package doesn't duplicate broker calls.

## Phased development status (spec §29)

| Phase | Scope | Status |
|---|---|---|
| 1 | Market data + market structure | done (`trading_agent.py`) |
| 2 | Liquidity detection | done (`sniper_smc.py`) |
| 3 | Order blocks + FVG | done (`sniper_smc.py`) |
| 4 | Multi-timeframe bias | done (`trading_agent.py`) |
| 5 | Setup scoring | done (`scoring.py`) |
| 6 | Backtesting engine | done, honest-fill validated (`sniper_backtest.py`) |
| 7 | Risk management | done (`risk.py`, `correlation.py`, `daily_guardrails.py`) |
| 8 | Paper trading | not started — `run_pipeline` is ready to drive a demo-account loop, no demo runner exists yet |
| 9 | Forward testing | not started — `journal.py` + `backtest_report.py` can score it once it runs |
| 10 | Live trading | **not started, and not recommended** until phases 8-9 produce real PF/WR numbers |

## Honest performance statement (spec §30)

The validated backtest (`sniper_smc.py` docstring) shows 70.0% WR / PF 2.17
over a 90-day honest-fill sample, holding up out-of-sample and under
parameter perturbation. That is one 90-day window on live-fetched data,
not a guarantee: n=20 pooled trades is small, the edge concentrates in a
handful of pairs, and a regime shift can erase it. The go-live gate stated
in `sniper_smc.py` is **PF > 1.3 on 25+ live demo trades**, not the 70%
number — treat that gate as this package's actual finish line before
phase 10. `walk_forward.py` and `monte_carlo.py` exist specifically so
that gate can be checked objectively instead of asserted.

## Safety invariants (spec §27)

Enforced in code, not just documented:

- `risk.position_size` raises `RiskViolation` on: no stop loss, zero risk
  distance, non-positive equity, requested risk above
  `MAX_RISK_PER_TRADE`, or an instrument with no verified broker spec.
  Position size is always rounded **down**, never up, so realized risk
  never exceeds the target.
- `risk.assert_sl_not_widened` raises if a proposed SL change would
  increase planned loss on an open position.
- `correlation.check_correlation` and `daily_guardrails.can_trade` are
  hard gates in `scanner.run_pipeline` — a setup that fails either is
  rejected with a logged reason, never silently allowed through.
- Nothing in this package places a live order. `scanner.run_pipeline`
  produces `ExecutionPlan`s; wiring those into `trading_agent.py`'s order
  calls is a deliberate, separate step so a bug here can't fire a trade by
  itself.

## Quick usage sketch

```python
from smc_sniper import CONFIG, run_pipeline
from smc_sniper.daily_guardrails import load_state
from smc_sniper.news_filter import FileNewsCalendar
import sniper_smc as sn
import trading_agent as ta

headers, account_id, equity = ta.auth()
raw_setups = sn.scan_sniper(headers)          # existing validated scanner
daily_state = load_state(equity)
calendar = FileNewsCalendar("news_calendar.json")   # populate from your provider

approved, rejected = run_pipeline(
    raw_setups, equity=equity, open_positions=[...],  # from ta.get_positions
    current_spreads={...}, news_calendar=calendar,
    daily_state=daily_state, cfg=CONFIG,
)
for plan in approved:
    print(plan.explanation["reason"])   # never trade without a legible reason
```
