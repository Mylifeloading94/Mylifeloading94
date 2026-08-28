# XAUUSD SMC Sniper Engine

A high-selectivity Smart Money Concepts analysis and signal engine for gold.
Real-time data, multi-timeframe SMC analysis, objective grading, measured
probabilities, and automatic 60-second re-validation.

**It is an analysis tool. It places no orders, and it is not investment advice.**

```
python3 xau_bot.py scan        # one full scan, printed to the terminal
python3 xau_bot.py run         # the 60-second live scanner loop
python3 xau_bot.py serve       # web dashboard: TradingView chart + SMC chart
python3 xau_bot.py backtest    # rebuild the validated win-rate statistics
python3 xau_bot.py selftest    # 235 internal consistency checks, offline
```

No third-party packages. Python 3.10+ and the standard library only.

---

## The three rules this engine will not break

Everything below follows from these. They are enforced in code and covered by
`selftest`.

1. **A price is never invented.** Every quote and bar comes from a named
   upstream. If nothing fresh arrives, the dashboard says
   `LIVE DATA UNAVAILABLE` and no setup is produced. There is no "last known
   price" fallback anywhere.
2. **Live and historical data are never mixed.** Live panels are badged `LIVE`,
   backtest panels are badged `HISTORICAL / BACKTEST DATA`, and the live-tracked
   performance table stays empty rather than borrowing the backtest's numbers.
3. **A win rate is a measurement or it is absent.** The percentage next to a
   setup is the observed win rate of *that exact configuration* in the backtest,
   printed with its sample size. Below the sample threshold the engine prints
   `INSUFFICIENT SAMPLE (n=…)`. It never rounds up to a nicer number.

---

## 1. Data — where the prices come from

Providers are tried in priority order; the first that can serve every requested
timeframe wins, and the choice is sticky for the session.

| # | Provider | Instrument | What it actually is | Real-time |
|---|----------|-----------|---------------------|-----------|
| 1 | `tradelocker` | `XAUUSD` | **True broker XAUUSD spot** | yes |
| 2 | `binance` | `PAXGUSDT` | PAX Gold token — spot-gold proxy, trades 24/7 | yes |
| 3 | `yahoo` | `GC=F` | COMEX gold futures — proxy, carries basis | **no, ~10-15 min delayed** |

Only provider 1 is true XAUUSD. Providers 2 and 3 are flagged
`is_true_xauusd = False`, and the dashboards print a proxy warning on every
render. A provider with a publisher-imposed lag is flagged `delayed` and
labelled `[DELAYED ~N MIN]`. Neither fact is ever hidden, and both are stamped
onto each setup as `data_quality` (`LIVE_XAUUSD_SPOT`, `LIVE_PROXY_REALTIME`,
`LIVE_PROXY_DELAYED`).

To use true XAUUSD spot:

```bash
export TL_EMAIL=you@example.com
export TL_PASSWORD=...
export TL_SERVER=GenFX            # your TradeLocker server
export TL_ACCOUNT_ID=...          # optional
python3 xau_bot.py scan
```

**Staleness.** Each timeframe has an age budget (`feed.MAX_AGE_SEC`). The
fastest timeframe is re-fetched on every scan with the cache bypassed, so a new
setup is never graded against a price the previous scan already used. If the
newest bar exceeds its budget the feed reports `STALE` during market hours, or
`MARKET_CLOSED` outside them — never `LIVE`.

**TradingView.** The dashboard embeds TradingView's own free Advanced Chart
widget (`OANDA:XAUUSD` by default). That is the supported way to show
TradingView's chart. The bot does **not** scrape TradingView and reads no
prices from it — the widget is there to look at, the analysis comes from the
feed above.

---

## 2. Multi-timeframe modes

Each mode is a complete timeframe stack: two timeframes for bias, one for
execution structure, one for entry refinement.

| Mode | Bias (HTF) | Confirm (MTF) | Execution (LTF) | Trigger (TTF) | Min R:R | Stop band |
|------|-----------|---------------|-----------------|---------------|---------|-----------|
| `SCALP` | H1 | M15 | M5 | M1 | 1.8 | 25–150 pips |
| `INTRADAY` | H4 | H1 | M15 | M5 | 2.0 | 45–350 pips |
| `SWING` | H4 | H4 | H1 | M15 | 2.2 | 120–900 pips |

A pip on gold is a `0.10` move; a point is `1.00`. All three modes are scanned
every pass, and every setup is labelled with its mode.

---

## 3. The SMC engine

`xausmc/smc.py` is pure: closed bars in, structure out. No clock, no network,
no state — which is why the live scanner and the backtest can run the identical
code path, and why the published statistics describe *this* engine.

- **Swings** — fractal pivots, confirmed `strength` bars late, never earlier.
- **Structure** — walks bars forward maintaining live reference levels, emitting
  **BOS** (continuation break) and **CHoCH/MSS** (the first break against the
  prevailing trend).
- **Liquidity** — swing pools, equal highs/lows clustered by ATR tolerance,
  prior-day high/low, and the Asia-session range. Pools already traded through
  are marked spent.
- **Sweep** — a bar whose *wick* takes a pool and whose *body* closes back
  inside. A clean break is not a sweep.
- **Displacement** — an impulse bar with body ≥ `displacement_atr` × ATR and a
  body ratio above `displacement_body_ratio`.
- **FVG** — 3-bar imbalance, annotated with how much has since been filled.
- **Order block** — the last opposing candle before a *qualifying displacement*.
  A random red candle is not an order block.
- **Premium / discount** — dealing range from the most recent opposing swing
  extremes, with equilibrium and the 0.618–0.79 OTE band.

### The four setup families (spec §5)

| Pattern | Sequence |
|---------|----------|
| `LIQUIDITY_SWEEP_REVERSAL` | liquidity → sweep → MSS → displacement → FVG → entry |
| `TREND_CONTINUATION` | HTF bias → liquidity → BOS → pullback → OB/FVG → entry |
| `BREAKOUT` | consolidation → liquidity build → displacement → BOS → retest |
| `PREMIUM_DISCOUNT_REVERSAL` | HTF range → premium/discount → sweep → MSS → FVG/OB |

Detection is sequence-driven, not indicator-driven: a setup exists only once the
whole institutional sequence has already printed. Nothing predicts; it confirms.
Where a sequence satisfies several families it is classified into the one with
the most specific structural precondition, so each statistical bucket means one
thing.

### Entry, stop, targets

- **Entry** is the point of interest: the FVG (preferred) or the order block. If
  price is already inside, the entry is `MARKET` and `ARMED`; if it has yet to
  retrace, it is a `LIMIT` at the zone midpoint and `PENDING`. If price has
  traded clean through the zone, the sequence is spent and nothing is emitted.
- **Stop** sits beyond the sweep extreme *and* the far edge of the zone, plus an
  ATR buffer, then must land inside the mode's stop band or the setup is dropped.
- **Targets** are draw-on-liquidity first, R floors second: aim just short of the
  opposing pool price is actually reaching for. A draw beyond `REACH_CAP` (2×)
  the R floor is out of reach and the floor is used instead — that is what stops
  a distant range extreme from flattering the published R:R. **TP3 is only
  published when a genuine draw sits in its band**, never as a padded multiple.

---

## 4. Grading (spec §8)

Ten weighted **market** components, totalling exactly 100:

| Component | Weight | | Component | Weight |
|---|---|---|---|---|
| HTF bias alignment | 15 | | FVG quality | 11 |
| Liquidity quality | 13 | | Premium/discount + OTE | 11 |
| MSS / BOS confirmation | 13 | | Order block | 8 |
| Execution structure | 10 | | Session / killzone | 6 |
| Displacement | 10 | | Volatility regime | 3 |

`A+ 90–100 · A 80–89 · B 70–79 · C 60–69 · INVALID below 60`

Every grade is published with the engine's own read of it — *sniper*, *strong*,
*tradeable, size down*, *weak, skip it* — so a C never appears as a bare
"VALID". C setups stay visible rather than being suppressed, because hiding them
would hide why the engine passed on a session; set `min_publish_grade` to `B` if
you only want the top two bands on screen.

**Hard gates** run first and produce `INVALID` whatever the score: R:R under the
mode minimum, unsuitable volatility, conflicted HTF bias on a non-reversal
pattern, entry in the wrong half of the range, or fewer than
`min_confluences` components scoring ≥ 0.60.

### Why history is not one of the ten

If measured performance fed the score, the score would set the grade, the grade
would select the historical bucket, and that bucket would feed the score — a
loop that quietly manufactures an edge, and one that makes the backtest's grade
buckets incomparable to live grades.

So history is applied **afterwards, as a one-way veto**
(`grading.apply_history_veto`): a configuration whose own sample is large enough
*and* loses money is struck out with `VALIDATED_NEGATIVE`, whatever its
confluence score. History can remove a setup here. It can never promote one.

---

## 5. Probability (spec §9)

`stats.py` holds buckets built from resolved backtest trades, keyed by
`pattern | mode | grade | direction`. A lookup walks from the most specific
bucket outward — `pattern+mode+grade+dir` → `pattern+mode+grade` →
`pattern+grade` → `mode+grade` → `grade` → `all` — and stops at the first with
at least `min_probability_sample` (default 30) observations. The level it
settled on is disclosed alongside the number.

If nothing qualifies, the setup shows `INSUFFICIENT SAMPLE (n=…)` and the
`probability` field is `None`. There is no default, no prior, and no borrowed
figure from a neighbouring bucket presented as if it were this one.

Tracked per bucket: sample size, wins, losses, breakeven, win rate, average R:R,
profit factor, expectancy, average win, average loss, and maximum drawdown in R.
Descriptive breakdowns by session, mode, pattern, direction, grade and timeframe
sit alongside.

---

## 6. Backtest (spec §9 / §18)

```bash
python3 xau_bot.py backtest                       # default plan, all three modes
python3 xau_bot.py backtest --provider yahoo --base-tf M15 --bars 40000
python3 xau_bot.py backtest --min-grade B --spread 0.30
```

Walk-forward, with a strict anti-lookahead gate: at simulated time *T* the
engine may only see bars that had **closed** by *T* (`Series.before`). It runs
the same `detect` + `grade` path the live scanner runs.

**The fill model is deliberately pessimistic**, because optimistic fills are how
backtests lie — this repository has been burned by exactly that before (see
`sniper_smc.py`, where a 66–82% win rate turned out to be a touch-fill artifact
of a strategy that was actually losing money):

- a `LIMIT` fills only on **trade-through** (a buy needs `low ≤ entry − 1 pip`);
  a touch is not a fill
- the fill **pays the spread**
- a bar that touches **both** target and stop is booked as a **loss**
- a bar that fills the order and breaches the stop is booked as a **loss**
- unfilled orders expire; open trades hit a time stop

**Management is fixed and identical for every trade**, so the R multiples are
comparable: 50% off at TP1 with the stop to breakeven, the remainder runs to TP2.

Outputs `state/stats.json` (the buckets the live bot reads) and
`state/backtest_trades.json` (every simulated trade, for audit). Deep history
pages are cached under `state/cache/`.

The default plan uses two base timeframes because `SCALP` triggers on M1 and
cannot be derived from an M5 base:

| Base | Bars | Span | Modes |
|------|------|------|-------|
| M5 | 150,000 | ~520 days | `INTRADAY`, `SWING` |
| M1 | 120,000 | ~83 days | `SCALP` |

---

## 7. Invalidation (spec §12)

Every scan re-checks every open setup. The first failing condition wins, and the
reason is displayed verbatim:

1. stop loss hit
2. TP1 reached before a pending entry filled (opportunity missed)
3. price traded clean through the entry zone
4. HTF bias reversed against the trade
5. the confirming MSS/BOS failed — an opposing BOS printed
6. liquidity reclaimed — price closed back through the swept pool
7. the FVG that justified the entry was fully invalidated
8. R:R decayed below the mode minimum
9. volatility regime became unsuitable
10. the sequence aged out without a fill

An old signal is never left standing as valid.

---

## 8. Risk management (spec §17)

Configurable in `xausmc.config.RiskConfig`, all enforced in `engine.Guard`:

| Setting | Default |
|---|---|
| `risk_per_trade_pct` | 0.5% |
| `max_daily_loss_pct` | 2% (→ a −4R daily stop at 0.5% risk) |
| `max_open_trades` | 2 |
| `max_consecutive_losses` | 3, then stand down for the day |
| `max_setups_per_day` | 3 — a **ceiling**, never a quota |
| `target_setups_per_day` | 2 |
| `allowed_sessions` | London, London/NY overlap, New York |
| `news_filter` | on, but only applied when a calendar exists |

When the guard blocks, setups are still *shown* — with the reason — but are not
recorded. Risk is never increased to recover losses; there is no such code path.

**News filter.** There is no free, reliable, redistributable economic calendar
this bot can depend on, so it does not pretend to have one. Supply
`state/news.json` and the blackout is enforced; supply nothing and the dashboard
says `NEWS FILTER: no calendar configured — filter NOT applied` rather than
implying it checked and found nothing.

```json
[{"time": "2026-08-28T12:30:00Z", "impact": "high", "title": "US CPI"}]
```

---

## 9. Output

**Terminal** (`scan` / `run`) — feed banner and provenance warnings, the
multi-timeframe structure table, the active setup, an ASCII chart with the
levels drawn in, the full confluence breakdown, everything rejected this scan
*with the reason*, tracked setups, and the risk guard.

**Web** (`serve`, default <http://127.0.0.1:8787>) — the same content plus the
engine's own SVG chart (candles, FVG and OB boxes, unswept liquidity pools,
BOS/MSS labels, premium/discount shading, entry/stop/target lines) and the
embedded TradingView widget. It refreshes every 60 seconds in step with the
scanner. JSON at `/api/scan`, `/api/stats`, `/api/performance`.

**Colour system**, identical in both:

| | |
|---|---|
| 🔵 **Blue** | Entry and entry zone |
| 🔴 **Red** | Stop loss |
| 🟢 **Green** | Take profit / targets |
| ⚪ **Grey** | Invalid setup, watermarked `INVALID` |

---

## 10. Signal history and live performance (spec §14 / §15)

Every published setup is written to `state/signals.jsonl` and then tracked to a
result — fill, MFE, MAE, R multiple, outcome — using the same management rules
the backtest uses, so live and historical R multiples are comparable. This is a
**paper** record; the bot places no orders.

`python3 xau_bot.py perf` reports today / this week / this month with setups,
wins, losses, win rate, profit factor, expectancy and maximum drawdown, broken
down by mode, setup type, direction, session, grade and timeframe.

Until signals have resolved, this panel stays **empty**. It does not fall back
to the backtest's numbers.

---

## 11. Configuration

```bash
python3 xau_bot.py config --out xausmc.config.json   # write a file you can edit
python3 xau_bot.py --config xausmc.config.json scan

# or override per run
python3 xau_bot.py --provider binance --modes INTRADAY,SWING \
                   --balance 25000 --risk 0.5 scan
```

`XAUSMC_STATE_DIR` relocates `state/`; `XAUSMC_CONFIG` points at a config file.

---

## 12. Layout

```
xau_bot.py            CLI entry point
xausmc/
  candles.py          bars, series, resampling, ATR — no pandas/numpy
  feed.py             providers, failover, staleness, LIVE DATA UNAVAILABLE
  smc.py              swings, BOS/CHoCH, liquidity, sweeps, FVG, OB, premium/discount
  sessions.py         sessions and killzones (UTC)
  regime.py           trending / ranging / volatile + volatility suitability
  config.py           modes, strategy params, grade weights, risk limits
  setups.py           the four setup families; entry / stop / target construction
  grading.py          the ten-component score, hard gates, the history veto
  stats.py            validated-performance buckets and probability lookup
  invalidation.py     the ten invalidation conditions
  journal.py          signal history and paper result tracking
  performance.py      today / week / month + breakdowns
  news.py             high-impact news blackout (only when a calendar exists)
  engine.py           the 60-second scan orchestration and risk guard
  render.py           terminal dashboard and ASCII chart
  chart.py            SVG SMC chart and the TradingView widget
  web.py              HTML dashboard and the built-in server
  backtest.py         walk-forward validation with honest fills
  selftest.py         offline consistency checks
state/
  stats.json          validated statistics (committed — the bot ships with them)
  backtest_trades.json  every simulated trade, for audit
  signals.jsonl       live signal history (not committed)
  news.json           your calendar, if you supply one (not committed)
```

---

## 13. Honest limits

- **The shipped statistics were measured on PAX Gold**, not on broker XAUUSD.
  PAXG tracks spot closely but trades 24/7, so weekend bars exist that XAUUSD
  does not have, and its microstructure is not a broker's. Re-run
  `backtest --provider tradelocker` once you have credentials to get numbers
  measured on the instrument you actually trade.
- **Sample sizes are small in the specific buckets.** A `pattern+mode+grade+dir`
  bucket needs 30 observations before a number is published, and the engine will
  often fall back a level or print `INSUFFICIENT SAMPLE`. That is the honest
  reading, not a defect.
- **A backtest is not a forward test.** Validate on demo before risking money.
  The go-live gate this repository already uses elsewhere is a good one: profit
  factor above 1.3 over 25+ demo trades, not a win-rate headline.
- **Two to three quality setups a day is a target, not a quota.** `NO VALID
  SETUP` is the correct output most of the time, and the engine will print it
  rather than lower its standards to fill a slot.
- Past performance is not a prediction and not a guarantee of future results.
