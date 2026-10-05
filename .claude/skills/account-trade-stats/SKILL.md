---
name: account-trade-stats
description: Track and report statistics for trades taken on the trading account (TradeLocker / Aquafunded $25k evaluation) - win rate, profit factor, expectancy, drawdown, streaks, daily P&L, and the live evaluation headroom (3% target, 5% trailing drawdown, -1% per-trade floating limit). Use when the user asks for account stats, trade stats, how the account is doing, how close it is to the target or drawdown limit, or wants to log/import trades.
---

# Account trade stats

Reports how the trades taken on the account are performing and how much room is left in the Aquafunded evaluation.

## Run

```bash
# closed trades from a TradeLocker/TradingView history export (CSV) or the local log
python3 .claude/skills/account-trade-stats/trade_stats.py --csv path/to/history.csv
python3 .claude/skills/account-trade-stats/trade_stats.py            # uses data/trade_log.csv if present

# add a live snapshot (open positions + balance/equity) - needs TL_USERNAME, TL_PASSWORD, TL_SERVER
# (+ TL_ACCOUNT_ID, TL_ACC_NUM, TL_ENV) in the environment. NEVER write credentials to a file.
python3 .claude/skills/account-trade-stats/trade_stats.py --csv history.csv --live
```

Options: `--start 25000` (starting balance), `--target-pct 3`, `--dd-pct 5`, `--float-pct 1`, `--daily-pct 3`, `--json`.

The CSV needs a profit column (any of `profit`, `pnl`, `net p&l`, `realized pnl`, `closed p/l`) and ideally a close-time column (`close time`, `closed`, `time`, `date`) and `symbol`. Rows are sorted by close time; each CSV import is also appended (de-duplicated) to `data/trade_log.csv` (git-ignored) so history survives broker session limits - the TradeLocker API only exposes executions for the current session.

## What it reports

- Closed-trade stats: trades, win rate, profit factor, average win/loss, payoff ratio, expectancy, net P&L, max realized drawdown, longest losing streak, best/worst trade, per-symbol and per-day P&L, trading days.
- Evaluation status (Aquafunded Pay After Pass rules): progress to +3% target, trailing floor (peak equity - 5% of start; peak uses realized balance, plus live equity when `--live`), headroom to the floor, the daily-loss headroom, and the worst open floating loss versus the -1% (-$250) per-trade kill.
- A plain verdict line: `OK`, `CAUTION` (<40% of drawdown headroom left or open loss >60% of the per-trade limit) or `STOP` (limit hit).

## Reading the numbers honestly

- Small samples mean nothing: below ~30 trades the win rate and profit factor are noise; say so.
- The trailing floor from closed trades alone understates risk if floating profit was given back; `--live` improves this only from the moment it is run.
- Rules not stated on the help page (time limit, evaluation daily limit, news/bot rules) are not enforced here.

## Pre-trade filter (from the imported tvremix dashboard)

`reference/gold_go_nogo_dashboard.json` is the user's TradingView dashboard for gold (FOREXCOM:XAUUSD): GO only when the 1D, 4h and 1h reads agree AND price sits at >= 2 confluences (structure level, volume POC/value area, SMC zone, moving average), with a stated entry/stop/target and reward-to-risk; otherwise WAIT/NO-GO and name what is missing. Bull and bear scenarios each need an invalidation level. This is an analysis layout, not a backtested edge - none of my backtests validated a gold setup, so treat a GO as a discretionary checklist, not a probability.
