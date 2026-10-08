# Strategy improvement search: can $500 → $3,000 or $1,000 → $10,000 be reached?

**Data:** TradingView OANDA bars, 30 symbols, the 90 trading days from 2026-06-04 to 2026-10-07.

**Method:**
- **Engine:** the corrected one. A target touched on the fill candle never counts, and the M15 data (last 52 days) is used to see what happened inside each 30-minute candle.
- **Selection and hold-out:** I picked versions using only the first 60% of the window (to 2026-08-21), then checked them on the last 40%, which played no part in the choice.

## What was tested (292 configurations)

| Family | Idea | Versions | Hold-out PF > 1 (of those with ≥ 30 selection-period trades) |
|---|---|---:|---:|
| A | SMC sniper (sweep → MSS → FVG), H4 or H1 bias, M30 entry | 256 | 40 / 60 |
| B | Trend pullback to EMA20 + TDI cross, H4 EMA50 trend | 24 | 2 / 24 |
| C | London breakout of the Asian range, H4 trend | 12 | 2 / 12 |

**Family A settings varied:**
- Entry: middle of the gap or its near edge
- Exits: half off at Target 1 plus breakeven, or one full target
- Targets: 2R or 3R
- Breakout candle size: 1.0 or 1.5 ATR
- Stop buffer: 0.3 or 0.6 ATR
- Minimum score: 50 or 70
- With or without the TDI overbought/oversold filter

## Results

- **The best selection-period version failed the hold-out test.** Entry at the gap edge with a 3R target scored PF 1.43 at first, then 0.77 on the hold-out.
- **Only 2 of 292 versions beat PF 1.15 in both periods.** Both are SMC versions with the same entry rules:

**Most consistent version:** H4 bias → M30 entry, limit at the middle of the gap, half off at 1R then breakeven, Target 2 = the smaller of 2R and the H4 range extreme, score 70 or higher, skipping setups with TDI overbought/oversold at the sweep.

| Period | Trades | Win rate | PF | Avg R | Net R | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| Selection | 36 | 64% | 1.20 | +0.09 | +3.1 | 4.0R |
| Hold-out | 27 | 63% | 1.21 | +0.09 | +2.4 | 4.7R |
| Full 90 days | 63 | 63% | 1.21 | +0.09 | +5.5 | 4.9R |

- **That edge is not statistically significant.** The t-score is about 0.6; you'd want 2 or more before trusting it.
- **Trend pullback (B) and Asian breakout (C) lost money** in nearly every version.
- **M15 scalping** had already lost money in the first study.

## Growth odds (resampling the 63 results above, compounded at fixed % risk)

| Goal | Horizon | Risk | Chance of reaching goal | Chance of losing 50% | Chance of a ≥ 30% drawdown | Median ending balance |
|---|---|---:|---:|---:|---:|---:|
| $500 → $3,000 | 90 days | 2% | 0% | 0% | 2% | $550 |
| | 365 days | 2% | 0% | 0% | 18% | $740 |
| | 365 days | 5% | 15% | 14% | 96% | $1,077 |
| $1,000 → $10,000 | 90 days | 2% | 0% | 0% | 2% | $1,101 |
| | 365 days | 3% | 0% | 2% | 55% | $1,725 |
| | 365 days | 5% | 4% | 14% | 96% | $2,154 |

Even these figures assume the +0.09R per trade continues, which this data can't confirm.

## Conclusion

**None of the tested strategies can realistically turn $500 into $3,000 or $1,000 into $10,000.** That would take a 6–10× return.
- **Best case found:** about +0.09R per trade and 0.7 trades a day, roughly +6R per quarter.
- **Why not push risk:** at 5% risk the odds of reaching the goal stay low (15% for $500, 4% for $1,000) and a 30%+ drawdown becomes nearly certain.
- **Why not keep searching:** I stopped at 292 versions. Searching until a backtest *looks* very profitable would only find luck that disappears live. The best selection-period version proved that: PF 1.43, then 0.77 on the hold-out.

## What would actually move the odds

1. **More history.** TradingView chart exports (CSV) of 1–3 years of M30/H1 per pair would allow proper walk-forward testing. 90 days is one market regime.
2. **Forward demo.** Run the most consistent version live on demo, logged in `trades/trades.json`, until 50+ trades. Only raise risk if PF stays above 1.3.
3. **Keep risk at 1–2%.** On these numbers, 2% risk gives about a 2% chance of a 30% drawdown in 90 days. 5% risk gives about 50%.

Reproduce: `python3 backtest_tv/research.py` (full grid), then `python3 backtest_tv/growth.py backtest_tv/out/chosen_rs.json`.
