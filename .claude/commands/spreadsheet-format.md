# Spreadsheet format — the house standard for every backtest deliverable

**Every backtest spreadsheet in this repo uses this format. No exceptions, no
per-deliverable reinvention.** The owner supplied the reference workbook
(`mylifeloading_portfolio_gold_fx_100k_backtest.xlsx`) and asked that all
spreadsheets follow it.

Implemented once in **`report_format.py`**. A deliverable is a call to
`build_workbook()`, not a fresh layout. `build_house_report.py` is a working
end-to-end example that rebuilds the current adopted config from its ledger.

```python
import report_format as rf
rf.build_workbook(
    "Some_Strategy_100k_backtest.xlsx",
    title="Strategy name -- instruments covered",
    subtitle="<start> to <end>  ·  $100,000 account  ·  1% risk/trade  ·  <target>  ·  <tf> execution",
    methodology="<the prose block -- see below, this is mandatory>",
    headline={...},            # the 8 metric columns
    trades=trades_df,          # TRADE_LOG_COLUMNS names
    starting_balance=100_000.0,
    concurrency={...},         # optional but expected
    per_instrument=per_pair_df # optional but expected
)
```

---

## Three sheets, always, in this order

### 1. `Summary`

| Row | Content |
|---|---|
| 1 | **Title** — strategy name + instruments covered |
| 2 | **Subtitle** — window dates, account size, risk/trade, target, execution timeframe, data source |
| 4 | **Methodology / caveat prose block** (merged, wrapped) |
| ~7 | **Headline metric row** (header + one value row) |
| then | **Concurrency** section |
| then | **Per-Instrument Breakdown** table |

**Headline columns, in this order:**
`Signals` · `Trades Taken` · `Skipped (Daily Cap)` · `Win Rate` · `Profit Factor` ·
`Ending Balance` · `ROI` · `Max Drawdown`

**Concurrency** — how many instruments compete for the same account:
trading days, days with 2+ instruments signalling, max instruments same day,
window length, trades/day, longest losing streak.

**Per-Instrument Breakdown** — `Pair` · `Trades` · `Win Rate` · `PF` ·
`Total P&L ($)` · `Strategy Params`.

### 2. `Trade Log`

Title in row 1, headers in row 3, data from row 4. Eighteen fixed columns:

`Date` · `Entry Time (UTC)` · `Pair` · `Direction` · `Entry` · `Stop` ·
`Target` · `Exit` · `Outcome` · `Stop (pips)` · `Result (pips)` · `Result R` ·
`Win` · `Lots` · `P&L ($)` · `Balance ($)` · `Week` · `Month`

`Balance ($)` is the running account balance after that trade — the reader can
trace the equity curve down the column. Win/loss rows are tinted; the sheet is
frozen below the header and auto-filtered.

### 3. `Periods`

Three stacked blocks — **Daily Gains**, **Weekly Gains**, **Monthly Gains** —
each with the same three columns:

`Period` · `P&L ($)` · `% of Starting Balance`

Percentages are **of the starting balance**, not of each period's own opening
balance, so all three tables share one scale and sum to the total return.

---

## The prose block is mandatory, and it goes above the numbers

The reference workbook put its overfitting caveat, its concurrency risk and its
lot-rounding disclosure in a prose block *above* the ROI. That placement is the
point: **the reader meets the caveats before the headline.** Reproduce that.

Cover, in roughly this order:

1. **What this is** — config, window, account size, risk, and the fill model
   (trade-through only, spread paid at entry, same-bar TP+SL counted a loss).
2. **How the configuration was chosen** — TRAIN-only selection, untouched TEST,
   walk-forward; and any defects fixed that changed the numbers.
3. **Read this before trusting the ROI** — the honest warning. Win-rate shape,
   streak risk, what a bad run does to the account at the stated risk.
4. **What is not established** — confidence intervals, especially where the
   walk-forward interval still spans zero, and forward/demo status.
5. **Concurrency** — several fixed-%-risk positions sharing one account is not
   full diversification; ROI is an upper bound.

Write it plainly. If a number is weak, the prose block is where it gets said,
not a footnote nobody reads.

---

## Rules

- **Never rename or reorder the columns.** Downstream reading (and the owner's
  eye) depends on the fixed shape.
- **No metric without its denominator.** A win rate next to a 4R target needs
  the break-even win rate stated somewhere; a small sample needs its `n`.
- **A pair with no losing trade has no finite profit factor** — print
  `n/a (no losses)`, never divide by a fabricated 1.0. (This bug shipped once:
  it printed the gross win total in a column the reader reads as a ratio.)
- **Percentages are stored as fractions** with a `0.00%` number format, not as
  pre-multiplied numbers.
- **Continuous timelines** in the Periods sheet — do not silently drop flat
  periods; their absence would overstate how often the system trades.
- **Extra sheets are allowed only when they add something the three cannot
  carry** (e.g. a risk table, a walk-forward split). The three core sheets keep
  their names, order and shape regardless.
