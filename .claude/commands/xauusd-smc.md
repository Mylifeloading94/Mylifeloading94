# XAUUSD SMC Sniper Engine — Skill

High-selectivity Smart Money Concepts analysis and signal engine for gold.
Real-time data, multi-timeframe SMC, objective grading, measured probabilities,
60-second re-validation.

Package: `xausmc/` · CLI: `xau_bot.py` · Full docs: `XAUUSD_SMC_BOT.md`

```bash
python3 xau_bot.py scan       # one full scan, printed
python3 xau_bot.py run        # 60-second live loop
python3 xau_bot.py serve      # web dashboard (TradingView + SMC chart)
python3 xau_bot.py backtest   # rebuild the validated win rates
python3 xau_bot.py selftest   # offline consistency checks
```

Stdlib only. No pandas, no numpy, no requests.

---

## The rules that make the numbers mean something

**Never work around these — they are the product, not a constraint on it.**

1. **No invented prices.** Every bar comes from a named upstream. Nothing fresh
   → `LIVE DATA UNAVAILABLE`, and no setup at all. There is no last-known-price
   fallback and there must never be one.
2. **Live and historical never mix.** Live panels badge `LIVE`, backtest panels
   badge `HISTORICAL / BACKTEST DATA`. The live-performance table stays empty
   rather than borrowing backtest numbers.
3. **A win rate is measured or absent.** The percentage is the observed win rate
   of that exact `pattern|mode|grade|direction` bucket, always printed with its
   sample size. Under 30 observations it prints `INSUFFICIENT SAMPLE (n=…)`.
4. **Grading never reads its own statistics.** History is a one-way *veto*
   (`grading.apply_history_veto`), never a score input. If history fed the score,
   the score would set the grade, the grade would pick the bucket, and the bucket
   would feed the score — a loop that invents an edge. History can only remove a
   setup, never promote one.
5. **The live scanner and the backtest run the same `detect` + `grade` code.**
   That is the whole reason the published statistics describe this engine.
   Any change to detection or grading invalidates `state/stats.json`
   — re-run `backtest` in the same commit.

## Feed priority

| # | Provider | Instrument | Reality |
|---|----------|-----------|---------|
| 1 | `tradelocker` | XAUUSD | true broker spot — set `TL_EMAIL`/`TL_PASSWORD`/`TL_SERVER` |
| 2 | `binance` | PAXGUSDT | PAX Gold, real-time spot proxy, trades 24/7 |
| 3 | `yahoo` | GC=F | COMEX futures — proxy **and ~10-15 min delayed** |

Only #1 is true XAUUSD. Proxy and delay flags are stamped on every setup as
`data_quality` and printed on every render.

## Fill honesty (the lesson this repo already paid for)

`sniper_smc.py` once showed 66-82% win rates that were a **touch-fill
artifact** — with honest fills the strategy was a loser (PF 0.91). The backtest
here enforces, and must keep enforcing:

- limit fills only on **trade-through** (`low ≤ entry − 1 pip` for a buy)
- entry **pays the spread**
- a bar hitting **both** TP and SL is a **loss**; the fill bar breaching SL is a loss
- unfilled orders expire; open trades hit a time stop
- fixed management: 50% at TP1 → stop to breakeven → runner to TP2

## Grade bands

`A+ 90-100 · A 80-89 · B 70-79 · C 60-69 · INVALID <60`, from ten market
components totalling 100 (HTF bias 15, liquidity 13, MSS/BOS 13, FVG 11,
premium/discount 11, structure 10, displacement 10, order block 8, session 6,
volatility 3). Hard gates override the score entirely.

## Selectivity

Target 2-3 quality setups per day; `max_setups_per_day` is a **ceiling, not a
quota**. `NO VALID SETUP` is the correct output most of the time. Do not tune
thresholds to raise signal count.

## Colour system

🔵 Entry · 🔴 Stop loss · 🟢 Targets · ⚪ Invalid (watermarked `INVALID`)

## Before changing anything

Run `python3 xau_bot.py selftest` (235 offline checks). It asserts the invariants above: no
fabricated prices, no probability without a sample, honest fills, coherent trade
geometry, causal `Series.before`, weights summing to 100.
