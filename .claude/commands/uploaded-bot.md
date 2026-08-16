# Uploaded SMC Sniper bot — 90-day verdict

**STATUS: NOT FIT TO TRADE. Do not deploy it, and do not let it replace the v2/swing_4r
configuration.** On the only sample large enough to measure anything, the honest-fill
result is a profit factor of **0.59**, an expectancy of **−0.239R per trade**, and a
**−30.05% ROI** over 90 days, with a bootstrap 95% CI of **[−0.454R, −0.015R]** —
entirely below zero. That is not "unproven". That is measurably losing.

The package's headline claim of **70.0% WR / PF 2.17** is a fill artifact. It does not
survive honest fills on the broker's own bars.

- Workbook: `Uploaded_Bot_Backtest.xlsx`
- Pristine upload: `uploaded_bot/sniper_backtest.py`, `uploaded_bot/sniper_smc.py`, `uploaded_bot/smc_sniper/`
- Fixed copy: `uploaded_bot/sniper_backtest_honest.py` (diff it against the pristine file)
- Rebuild: `python3 uploaded_bot/build_data.py && python3 uploaded_bot/run_uploaded_backtest.py && python3 build_uploaded_bot_workbook.py`

## Test setup

| | |
|---|---|
| Data | Real TradeLocker broker history, read-only (`GET /trade/history`) |
| Window | 2026-05-18 → 2026-08-16 UTC, 90 days (+35 days warm-up, excluded from results) |
| Pairs | The package's own `SNIPER_PAIRS`: NAS100, USDJPY, GBPJPY, GBPUSD, AUDJPY, USDCAD |
| Unavailable pairs | **None.** All six resolved. |
| Account basis | $100,000, compounding trade by trade |
| Risk | **2.0% per trade** — `smc_sniper/config.py :: SniperConfig.RISK_PER_TRADE`, sized by `smc_sniper/risk.py::position_size` (lots floored to 0.01) |
| No order was ever placed | `live_runner.py` was never imported or called; `dry_run=False` appears nowhere |

**A note on NAS100.** The uploaded `trading_agent.py` hard-codes `INFO_ROUTE = 674`, and
this account answers that route with an empty payload. Taken at face value it looks like
NAS100 has no history. The real INFO route is **452**, resolved per instrument from
`/trade/accounts/<id>/instruments`. All six pairs are present and were tested. Worth
knowing: as shipped, the bot's own data layer silently returns nothing for every symbol.

**The package ships two different parameter sets, and they disagree.** Both are reported
because picking one silently would be the same trick the original numbers played.

- **Config 1** — what the docstrings and `config.py` call the validated config:
  OTE band 0.62–0.90, prime killzones only, displacement 1.1×ATR, TP2 2.5R.
  Produces **7–8 trades in 90 days**. Too few to conclude anything.
- **Config 2** — what `python3 sniper_backtest.py` actually executes: displacement
  0.6×ATR, TP2 2.0R, no OTE gate, wider sessions. Produces **70–72 trades**. This is the
  sample that decides the question.

## Results — Config 2 (70–72 trades, the usable sample)

| Metric | Run A — as uploaded | **Run B — honest fills** |
|---|---|---|
| Trades | 70 | **72** |
| Trades / day | 0.78 | **0.80** |
| Win rate | 55.7% | **40.3%** |
| Profit factor | 1.03 | **0.59** |
| Expectancy | +0.011R | **−0.239R** |
| Bootstrap 95% CI | [−0.206R, +0.238R] | **[−0.454R, −0.015R]** |
| Start balance | $100,000.00 | $100,000.00 |
| End balance | $100,289 | **$69,946** |
| **Profit $** | +$289 | **−$30,054** |
| **ROI %** | +0.29% | **−30.05%** |
| **Total pips** | −409.0 | **−826.1** |
| Max drawdown | 12.92% | **30.05%** |

Even *with* every bug left in, Config 2 makes $289 in 90 days — a rounding error on a
$100k account. Corrected, it loses nearly a third of the account.

## Results — Config 1 (7–8 trades, decides nothing)

| Metric | Run A — as uploaded | **Run B — honest fills** |
|---|---|---|
| Trades | 7 | **8** |
| Trades / day | 0.08 | **0.09** |
| Win rate | 85.7% | **62.5%** |
| Profit factor | 4.25 | **1.15** |
| Expectancy | +0.464R | **+0.058R** |
| Bootstrap 95% CI | [−0.143R, +1.036R] | **[−0.625R, +0.674R]** |
| Start balance | $100,000.00 | $100,000.00 |
| End balance | $106,603 | **$100,805** |
| **Profit $** | +$6,603 | **+$805** |
| **ROI %** | +6.60% | **+0.80%** |
| **Total pips** | +130.3 | **+109.8** |
| Max drawdown | 2.00% | **4.94%** |

Run B is nominally positive here, and it means nothing: the CI runs from −0.625R to
+0.674R on eight trades. Two of those eight are the structurally broken trades described
below; remove them and the sign flips again. **Nobody should read +0.80% as an edge.**
Neither run reproduces the claimed 70.0% WR / PF 2.17.

*On pips:* pips are position-weighted (R × risk_pips), so partial closes count correctly.
Pips and dollars can disagree in sign here because NAS100 risk is measured in index points
at $1.00/point while FX pips are worth $6.70–$12.50 — NAS100 dominates the pip total while
position sizing normalises its dollar impact. **Dollars and ROI are the figures to read.**

## The four bugs, measured

Each fix toggled alone on the as-uploaded engine, everything else held identical.
Deltas below are against Run A on **Config 2** (the meaningful sample). All four are
isolated; only the combined row is not additive, because the fill and spread fixes change
which setups clear the minimum-risk gate and that shifts the non-overlap sequencing.

| Bug | WR Δ | PF Δ | Expectancy Δ | ROI Δ | Isolated? |
|---|---|---|---|---|---|
| 1. Touch-fill, not trade-through | +0.0 pp | +0.00 | +0.000R | +0.00 pp | ISOLATED |
| 2. Spread computed then discarded | −8.5 pp | −0.29 | −0.145R | −18.96 pp | ISOLATED |
| 3. TP1 booked before same-bar stop | −11.4 pp | −0.32 | −0.171R | −21.49 pp | ISOLATED |
| 4. Scratches dropped from WR denominator | +0.0 pp | +0.00 | +0.000R | +0.00 pp | ISOLATED |
| **All four combined (= Run B)** | **−15.4 pp** | **−0.44** | **−0.249R** | **−30.34 pp** | COMBINED |

**1. Touch-fill** (`sniper_backtest.py` ~L114): `if swept=="bull" and ck["l"]<=zone_mid:
entry=zone_mid`. A resting limit needs price to trade *through* the level. Measured cost
on this data: **zero** — over 90 days no retrace bar's extreme landed exactly on the zone
midpoint to float precision. The bug is real and would bite on tick-quantised or
round-number levels, but here it cost nothing. Reporting it as zero rather than guessing.

**2. Spread computed then discarded** (~L124): `entry_eff = entry + sign*sp  # pay spread
on entry`. `entry_eff` appears **exactly once in the whole file**. `tp1`, `tp2`, the stop
comparison and the final realised R all use raw `entry`. The cost is calculated and thrown
away, so every trade is booked at mid. **−0.145R per trade.**

**3. TP1 booked before the same-bar stop check** (~L129–132): the partial-close branch
runs before the stop branch inside the same bar, so a bar that traded through both the
target and the stop scores +0.5R instead of −1R. **−0.171R per trade — the single most
expensive bug.**

**4. Scratches dropped from the win-rate denominator** (~L148): `dec=wins+losses;
wr=wins/dec*100` excludes `be_ct`. Measured cost: **zero**, and the reason matters more
than the number. `be_ct` was 0 in every run because the engine books a break-even stop as
**+0.5R** (the TP1 partial was already taken), not 0.0R — so a BE exit is counted as a
*win*. That is the same line, and it is why a 55.7% win rate can sit on a profit factor of
1.03. The reported win rate was never measuring what it claimed to.

### A fifth defect — found in the ledger, disclosed, deliberately not fixed

The engine never checks that the stop is on the **losing** side of the entry. SL is placed
at `sweep_ext ∓ sl_buf*ATR` while entry is the FVG midpoint, and risk is taken as
`abs(entry-sl)`, which hides the sign. When a deep retrace puts the zone midpoint beyond
the sweep extreme, a long is opened with its stop *above* the entry and its targets above
that — stopped out on its own fill bar, a structurally guaranteed −1R at full size.

- Config 1 (honest): **2 of 8 trades (25%)**, contributing −2.00R of a +0.46R total. Those
  two trades are the entire difference between Run B reading positive and negative.
- Config 2 (honest): 2 of 72 trades (2.8%), −2.00R of −17.19R. A small part of the damage
  there; Config 2 loses on its own merits.

Left in on purpose. The brief was to correct four fill bugs and change nothing else;
adding an entry-validity gate is a strategy change and would break the A/B comparison.

## Recommendation

**No. It should not replace the current v2/swing_4r configuration, and it should not run
on the live account in any form.**

1. **It loses money once fills are honest.** −0.239R per trade over 72 trades with a CI
   entirely below zero is a measured negative edge, not an unlucky sample.
2. **The positive-looking configuration is unmeasurable.** 8 trades in 90 days at 0.09
   trades/day cannot be validated in any reasonable timeframe, and a quarter of them are
   structurally broken entries.
3. **The claimed validation cannot be reproduced.** 70.0% WR / PF 2.17 appears in neither
   run on either parameter set. The package's own `config.py` warns that changing these
   knobs "invalidates that result until re-backtested" — the result was not there to
   invalidate.
4. **The incumbent is better and better-evidenced.** The repo's v2 swing stack returns
   153 trades / 54.90% WR / PF 1.260 / +0.114R. It is positive, it is built on ~10× the
   sample, and it has already been walk-forward tested. Swapping a +0.114R stack for a
   −0.239R one is strictly worse on every axis.
5. **Its data layer is broken as shipped** (`INFO_ROUTE = 674` returns nothing), so it
   would trade on empty bar arrays if run unmodified.

**Worth keeping:** the modular scaffolding in `uploaded_bot/smc_sniper/` — `risk.py`'s
sizing invariants, `correlation.py`, `daily_guardrails.py`, `news_filter.py`, `journal.py`
— is sound, well-factored work that is independent of the broken entry engine. If any of
it is wanted, port those modules on top of the existing v2 signal engine. **The entry
logic is the part that does not work; keep the plumbing, discard the signal.**
