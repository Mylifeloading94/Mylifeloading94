# BB SNIPER

Bollinger Band + liquidity sweep + market-structure strategy for forex and gold, built as a
mechanical, no-lookahead quantitative system. Full results: `backtest_tv/out/bbsniper/REPORT.md`.

## Verdict on the data available today

On TradingView/OANDA history (1M ≈ 3.5 days, 5M ≈ 17 days, 15M ≈ 50 days; 3M built from 1M)
the specified rules lose money on every execution timeframe. With the filters relaxed, the samples
get larger and the result is significantly negative (t-stats −2.5 to −4.9). Before trading costs
the edge is roughly zero. **Treat it as NO TRADE until a 90+ day test with longer history shows
positive out-of-sample expectancy.**

## Commands

```bash
python3 -m bbsniper.run                      # full backtest -> backtest_tv/out/bbsniper/*
python3 -m bbsniper.live --tf 5m             # live scan of the watchlist on the latest stored bars
python3 -m bbsniper.live --tf 15m --json     # machine-readable (for bots)
python3 -m bbsniper.data EURUSD 5m file.csv  # import a TradingView CSV export (longer history)
```

TradingView Pine Script v5 version: `bbsniper/pine/bb_sniper.pine`. Paste it into the Pine
editor, then "Add to chart". Set the setup and bias timeframes to suit your chart. This file has
**not been compiled in TradingView from here**, so fix any editor warning before relying on it.

## Modules (spec section 39)

| # | Module | File |
|---|---|---|
| 1 | Indicators (BB, %B, BandWidth, EMA, RSI, ADX, ATR) | `indicators.py` |
| 2 | Market regime | `regime.py` |
| 3 | Higher-timeframe bias | `bias.py` |
| 4 | Liquidity detection | `liquidity.py` |
| 5 | Market structure | `structure.py` |
| 6 | RSI / %B divergence | `divergence.py` |
| 7 | Bollinger logic | `bands.py` |
| 8 | Entry engine (MR / TC / SB state machines + score) | `entries.py` |
| 9 | Risk management (filters, daily guard) | `risk.py` |
| 10 | Position sizing (lots from equity, risk %, stop, pip value) | `risk.py` |
| 11 | Trade management (TP1/2/3, BE, trailing, honest fills) | `manage.py` |
| 12 | Backtesting (pair-level + account portfolio) | `backtest.py` |
| 13 | Optimisation + walk-forward | `optimize.py` |
| 14 | Reporting / grading / ranking | `report.py`, `run.py` |
| 15 | Live signals and alerts | `live.py` |

All inputs are in `config.py`. Data: `data.py` (higher-timeframe values come only from bars
already closed, and stale or missing data gives no signal).

## Known limits

- The data feed caps history at 5,000 bars per timeframe and has no historical spreads, so spreads
  are static estimates. There is also no historical economic calendar, so the news filter is
  disabled in backtests.
- Small samples. No pair reached 10 trades on any timeframe under the default rules.
