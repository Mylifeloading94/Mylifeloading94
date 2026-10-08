# 90-Day SMC + TDI + Divergence Backtest (TradingView data)

**Data:** TradingView OHLCV, OANDA feed, pulled through the Tradingview_Ai connector on 2026-10-08. 30 symbols (28 FX pairs, XAUUSD, SPX500USD).
**Window:** the last 90 completed trading days, **2026-06-04 → 2026-10-07**.
**Everything below is a historical backtest.** The live GBPJPY order posted to Telegram today is not part of it.

---

## 1. Executive summary

- **The only setup that made money and passed the hold-out test is H4 bias → M30 entry, score 70 or higher.**
  - 83 trades over 90 days, 68.7% win rate, profit factor 1.52, average +0.19R per trade, worst drawdown 4.8R.
  - "Win" includes trades that hit Target 1 and then stopped at breakeven (+0.5R). Only 30% reached Target 2.
  - The selection period (first 60% of the window) made PF 1.32. The hold-out period (last 40%), which I didn't use to choose anything, made PF 1.81.
- **M15 scalping lost money in every version tested** (PF 0.35–0.67). On the same dates, M30 made PF 1.71.
  - Stops on M15 are small, so the spread eats too much of each trade.
- **TDI adds almost nothing as a confirmation.** The breakout candle itself pushes TDI into "strong" on 92% of trades, so it doesn't filter anything.
  - One TDI condition did help: **skipping setups where TDI was already overbought or oversold (below 32 or above 68) at the sweep.** That raised selection-period PF from 1.32 to 1.80 and hold-out PF from 1.81 to 2.18.
  - I found that pattern by looking at the full results, so it still needs live testing.
- **Regular divergence helped a little** (PF 1.69 vs 1.23 without it, 22 trades). Hidden divergence did worse.
- **Accounts (compounding, H4→M30, score 70+):**
  - $500 → $581 at 1% risk, or $669 at 2%
  - $1,000 → $1,162 at 1%, or $1,338 at 2%
  - Worst drawdown: 4.7% at 1% risk, 9.3% at 2%.
- **Per-pair results can't be trusted.** No pair had more than 5 trades, so any pair ranking is mostly luck. Rank the strategy, not the pairs.

## 2. Strategy rules (fixed before testing)

1. **Direction from the bias timeframe:** last break of structure, using swing points confirmed 3 bars after they print.
   - It only uses bias candles that have already closed.
   - **No higher-timeframe direction = no trade.**
2. **Liquidity sweep** on the entry timeframe:
   - **What counts as liquidity:** a swing high or low from the last 60 bars, or the previous day's high or low.
   - **The sweep:** a wick goes 1.5×ATR or less through that level and the candle closes back inside.
3. **Market structure shift within 12 bars of the sweep:** a candle closes through the most recent small swing point.
   - Its body must be at least 1.0×ATR, so a real displacement.
   - It's tagged BOS (with the existing entry-timeframe trend) or CHoCH (against it).
4. **Fair value gap inside the sweep-to-shift move**, at least 0.15×ATR in size.
5. **Entry:** limit order at the middle of the FVG, live for 16 bars.
   - **Fill:** only counts if price trades 1 pip past the entry.
   - **Cancel:** only if a candle closes beyond the stop (rule A, same as the live bot).
6. **Stop:** sweep extreme ± max(0.3×ATR, 1.5×spread). The stop must be at least 3× the spread.
7. **Room to the target:** the opposite end of the bias timeframe's range must be at least 1.2R away.
8. **Targets:**
   - **Target 1:** 1R, close half, move the stop to entry.
   - **Target 2:** the smaller of 2.5R and the range extreme.
9. **Honest fills:**
   - A candle that touches both the stop and a target counts as the stop.
   - If the fill candle also touches the stop, that's a loss.
   - The full estimated spread is charged on every trade.
10. **Portfolio limits:** one open trade per symbol, at most 4 new fills per UTC day, risk sized on current equity.

**Score (0–100):**

| Component | Points |
|---|---:|
| Core model (rules 1–8) | 40 |
| Entry in discount (longs) or premium (shorts) | +10 |
| Deep discount or premium (beyond 40%) | +5 |
| London or NY killzone | +10 |
| TDI confirmation | +10 |
| Strong TDI | +5 |
| Regular divergence (or hidden, +7) | +10 |
| Room to target at least 1.6R | +10 |

Grade bands: 90+ A+ · 80–89 A · 70–79 B · 60–69 C · below 60 no trade.

## 3. TDI and divergence rules

- **TDI:**
  - RSI(13) on the entry timeframe.
  - Price line = SMA2 of RSI, signal line = SMA7, middle band = SMA34.
- **Confirmation for a long:** price line above signal line and rising at the shift candle. Shorts mirror this.
- **Strong:** confirmation, plus the price line just crossed 50 or sits above the middle band.
- **Overbought/oversold at the sweep:** price line below 32 for a long, or above 68 for a short. This is the condition worth avoiding.
- **Regular divergence:** the sweep makes a new price extreme, but RSI does not.
- **Hidden divergence:** across the last two swing points, price makes a higher low but RSI makes a lower low (mirror for shorts).

## 4. Best scalping timeframe

Same dates (2026-07-24 → 10-07), score 70+:

| Combo | Trades | Win rate | PF | Avg R | Net R | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| H4 bias → M15 entry | 81 | 51% | 0.67 | −0.19 | −15.7 | 19.2R |
| H1 bias → M15 entry | 55 | 44% | 0.35 | −0.44 | −24.4 | 24.8R |
| *(compare)* H4 bias → M30 entry | 53 | 70% | 1.71 | +0.24 | +12.7 | 4.8R |

**No profitable scalping combination was found.**
- **M15:** TradingView limits each request to 5,000 bars, so M15 only reaches back about 52 trading days.
- **M5 and M1:** at the same limit they only cover about 17 and 3.5 days, so they weren't tested and are reported as no data.
- **Recommendation:** use M30 as the fastest entry timeframe.

## 5. Best intraday timeframe

Full 90 days, score 70+:

| Combo | Trades | Win rate | PF | Avg R | Net R | Max DD | Selection PF | Hold-out PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **H4 bias → M30 entry** | **83** | **69%** | **1.52** | **+0.19** | **+15.5** | **4.8R** | **1.32** | **1.81** |
| D1 bias → H1 entry | 38 | 58% | 0.99 | −0.01 | −0.2 | 5.0R | 0.71 | 1.35 |
| H1 bias → M30 entry | 28 | 57% | 0.93 | −0.03 | −0.9 | 4.7R | 0.75 | 1.30 |
| H4 bias → H1 entry | 32 | 53% | 0.71 | −0.15 | −4.9 | 7.4R | 0.83 | 0.63 |

- **How the winner was chosen:** I picked the combo and score threshold with the highest selection-period net R, out of 30 configurations, requiring at least 15 trades and PF above 1. Only then did I look at the hold-out period.
- **Score threshold for H4→M30:**

| Threshold | Trades | PF | Net R |
|---|---:|---:|---:|
| 50+ | 106 | 1.27 | +11.5 |
| 60+ | 99 | 1.41 | +15.5 |
| **70+** | **83** | **1.52** | **+15.5** |
| 80+ | 56 | 1.12 | +2.6 |
| 90+ | 24 | 1.10 | +1.0 |

  Raising the bar above 70 didn't help: an A+ score did not mean a better trade.

## 6. 90-day pair ranking (H4→M30, score 70+)

**Grading rule:** a pair needs at least 10 trades to grade above C. No pair reached 10.

| Rank | Pair | Grade | Win rate | Trades | PF | Avg R | Max DD | Best TF (≥3 trades) | Note |
|---:|---|---|---:|---:|---:|---:|---:|---|---|
| 1 | NZDUSD | C | 100% | 5 | ∞ | +1.38 | 0.0R | H4→M30 | small sample |
| 2 | EURNZD | C | 100% | 2 | ∞ | +1.28 | 0.0R | H4→M15 (neg) | small sample |
| 3 | NZDCAD | C | 100% | 5 | ∞ | +0.51 | 0.0R | H4→M30 | small sample |
| 4 | GBPJPY | C | 75% | 4 | 3.03 | +0.55 | 1.1R | H4→M30 | small sample |
| 5 | EURJPY | C | 75% | 4 | 2.90 | +0.53 | 1.1R | H4→M30 | small sample |
| 6 | NZDJPY | C | 100% | 2 | ∞ | +0.97 | 0.0R | D1→H1 | small sample |
| 7 | EURCAD | C | 67% | 3 | 2.47 | +0.57 | 1.2R | H4→M30 | small sample |
| 8 | GBPCHF | C | 100% | 2 | ∞ | +0.74 | 0.0R | — | small sample |
| 9 | USDJPY | C | 60% | 5 | 1.68 | +0.30 | 1.9R | H4→M30 | small sample |
| 10 | GBPNZD | C | 100% | 4 | ∞ | +0.33 | 0.0R | D1→H1 | small sample |
| 11 | EURGBP | C | 100% | 1 | ∞ | +1.12 | 0.0R | — | small sample |
| 12 | AUDJPY | C | 100% | 3 | ∞ | +0.37 | 0.0R | H4→M30 | small sample |
| 13 | AUDNZD | C | 67% | 3 | 1.55 | +0.21 | 1.2R | H4→M30 | small sample |
| 14 | AUDUSD | C | 67% | 3 | 1.37 | +0.15 | 1.2R | H4→M30 | small sample |
| 15 | GBPAUD | C | 100% | 1 | ∞ | +0.36 | 0.0R | H4→M15 | small sample |
| 16 | CADJPY | C | 100% | 1 | ∞ | +0.28 | 0.0R | H4→M15 | small sample |
| 17 | USDCAD | D | 50% | 2 | 1.18 | +0.10 | 1.1R | H4→M15 | flat |
| 18 | GBPUSD | D | 60% | 5 | 1.08 | +0.04 | 1.3R | H4→H1 | flat |
| 19 | EURAUD | D | 60% | 5 | 0.87 | −0.06 | 2.0R | — | flat |
| 20 | EURCHF | D | 75% | 4 | 0.68 | −0.10 | 1.3R | — | flat |
| 21 | EURUSD | F | 50% | 2 | 0.37 | −0.36 | 1.1R | — | negative |
| 22 | CHFJPY | F | 50% | 2 | 0.26 | −0.40 | 1.1R | — | negative |
| 23 | GBPCAD | F | 0% | 1 | 0.00 | −1.16 | 1.2R | — | negative |
| 24 | SPX500USD | F | 50% | 4 | 0.42 | −0.30 | 1.6R | — | negative |
| 25 | AUDCAD | F | 60% | 5 | 0.36 | −0.30 | 1.8R | D1→H1 | negative |
| 26 | USDCHF | F | 33% | 3 | 0.16 | −0.63 | 2.3R | — | negative |
| 27 | XAUUSD | F | 0% | 2 | 0.00 | −1.02 | 2.0R | — | negative |
| 28 | CADCHF | F | 0% | 2 | 0.00 | −1.26 | 2.5R | — | negative |
| — | AUDCHF, NZDCHF | — | — | 0 | — | — | — | — | no qualifying trades |

## 7. Detailed backtest statistics (H4→M30, score 70+)

**Outcome counts:** 83 trades, 43 sells and 40 buys.

| Outcome | Trades |
|---|---:|
| Target 2 hit | 25 |
| Target 1, then breakeven | 32 |
| Stop loss | 23 |
| Stop loss on the fill candle | 3 |

**Per-trade numbers:**

| Measure | Value |
|---|---|
| Win rate / loss rate | 68.7% / 31.3% |
| Profit factor | 1.52 |
| Expectancy | +0.187R per trade |
| Average win / average loss | +0.79R / −1.14R (spread included) |
| Best / worst trade | +1.69R / −1.27R |
| Longest winning / losing streak | 6 / 3 |
| Worst drawdown | 4.82R |
| Average MFE / MAE | 1.53R / 0.64R |
| Median stop | 15.1 pips |

**Setup mix:** 50 liquidity reversals (CHoCH), 33 trend continuations (BOS). Regular divergence on 22 trades, hidden on 8.

**Confluence breakdown, all 106 trades scoring 50+:**

| Factor | Group | Trades | PF | Net R |
|---|---|---:|---:|---:|
| Session | London KZ | 21 | 2.15 | +7.6 |
| | Asia | 26 | 1.92 | +7.7 |
| | Off-killzone | 37 | 0.96 | −0.6 |
| | NY KZ | 22 | 0.70 | −3.1 |
| TDI | Strong | 98 | 1.32 | +12.5 |
| | Overbought/oversold at sweep | 27 | 0.72 | −4.3 |
| | Not overbought/oversold | 79 | 1.57 | +15.9 |
| Divergence | Regular | 22 | 1.69 | +4.7 |
| | None | 74 | 1.23 | +7.4 |
| | Hidden | 10 | 0.89 | −0.5 |
| Setup | Reversal (CHoCH) | 63 | 1.27 | +6.4 |
| | Continuation (BOS) | 43 | 1.27 | +5.2 |

These are observations from the full sample, not validated filters.

Full trade list: `backtest_tv/out/trades_selected.csv`, one row per trade with date, symbol, session, side, entry, stop, targets, R:R, setup, MSS, liquidity pool, TDI, divergence, score, exit, R, MFE and MAE.

## 8. $500 account results

| Risk | Trades | Win rate | Net profit | ROI | Max DD | Ending balance |
|---|---:|---:|---:|---:|---:|---:|
| 1% | 83 | 68.7% | +$81.13 | +16.2% | 4.7% | **$581.13** |
| 2% | 83 | 68.7% | +$169.19 | +33.8% | 9.3% | **$669.19** |

## 9. $1,000 account results

| Risk | Trades | Win rate | Net profit | ROI | Max DD | Ending balance |
|---|---:|---:|---:|---:|---:|---:|
| 1% | 83 | 68.7% | +$162.26 | +16.2% | 4.7% | **$1,162.26** |
| 2% | 83 | 68.7% | +$338.37 | +33.8% | 9.3% | **$1,338.37** |

Risk is a percentage of current equity at each fill, so the account size doesn't change the percentages.

## 10. 1% vs 2% risk

| | 1% | 2% |
|---|---:|---:|
| ROI over 90 days | +16.2% | +33.8% |
| Max drawdown | 4.7% | 9.3% |
| Worst day ($1,000 account) | −$14.07 | −$31.34 |
| Worst week ($1,000 account) | −$28.52 | −$64.81 |
| Chance of a 50% drawdown within 250 trades* | 0% | 0% |

\*Estimated by reshuffling the 83 backtest results 5,000 times.

**Is 2% sustainable?** On these numbers, yes: the longest losing streak was 3 and the worst drawdown under 10%.
- **The catch:** 83 trades from a single 4-month period can't show how bad a different market would be.
- **Recommendation:** use 1% until 25 or more live demo trades confirm PF above 1.3, then consider 2%.

## 11. Daily, weekly and monthly performance ($1,000 account)

**Daily** (56 days with a closed trade):

| | 1% | 2% |
|---|---:|---:|
| Trades per active day | 1.48 | 1.48 |
| Wins / losses per day | 1.02 / 0.46 | 1.02 / 0.46 |
| Average daily P/L | +$2.90 | +$6.04 |
| Average daily ROI | +0.28% | +0.55% |
| Best day | +$58.10 | +$122.37 |
| Worst day | −$14.07 | −$31.34 |

Over the full 90 trading days that works out to about 0.92 trades per day.

**Weekly:** 13 of 18 weeks were profitable (72%).
- **Best week:** 2026-W35, +$53.70 at 1% or +$113.02 at 2%.
- **Worst week:** 2026-W38, −$28.52 at 1% or −$64.81 at 2%.

**Monthly** (results in R, plus ROI for the $1,000 account):

| Month | Trades | Win rate | PF | Net R | Max DD | ROI 1% | ROI 2% |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-06 (from 4th) | 9 | 67% | 1.01 | +0.04 | 1.99R | +0.0% | −0.0% |
| 2026-07 | 29 | 66% | 1.39 | +4.56 | 3.49R | +4.4% | +8.5% |
| 2026-08 | 16 | 81% | 2.79 | +5.95 | 1.25R | +6.0% | +12.1% |
| 2026-09 | 24 | 62% | 1.21 | +2.13 | 4.82R | +2.1% | +4.1% |
| 2026-10 (to 7th) | 5 | 80% | 3.51 | +2.83 | 1.13R | +2.8% | +5.7% |

## 12. Drawdown and risk

- Worst drawdown was 4.82R: 4.7% at 1% risk, 9.3% at 2%. It happened in September.
- Longest losing streak was 3, longest winning streak 6.
- **Average loss is bigger than 1R (−1.14R):** spread costs, plus 3 trades where the fill candle also hit the stop.
- **Estimated spreads:** I used typical OANDA spreads because historical spreads aren't in the TradingView feed. Wider real spreads would lower all results.
- **News:** no news filter was applied, because I had no historical economic calendar.

## 13. Best performing pair

**NZDUSD:** 5 trades, all winners, +6.9R. That's too few trades to call it an edge.
- **Next best:** NZDCAD and GBPJPY.
- **Worst:** CADCHF, XAUUSD, USDCHF and AUDCAD, all negative.
- **SPX500 and gold:** both were negative with this model.

## 14. Best performing strategy

| | |
|---|---|
| **Best pair** | NZDUSD (small sample; trade the basket, not one pair) |
| **Best timeframe** | H4 bias → M30 entry |
| **Best session** | London killzone (07:00–10:30 UTC), then Asia; avoid the NY killzone |
| **Best entry model** | Sweep → market structure shift with displacement → limit at the FVG midpoint, cancel only if a candle closes past the stop |
| **Best TDI confirmation** | Skip setups where TDI was already overbought/oversold at the sweep (<32 / >68). "TDI strong" itself doesn't filter anything. |
| **Best divergence** | Regular divergence at the sweep |
| **Win rate** | 68.7% (Target 2 reached 30%) |
| **Profit factor** | 1.52 (selection period 1.32, hold-out 1.81) |
| **Average R** | +0.19R |
| **Max drawdown** | 4.8R |
| **Trades per day** | about 0.9 across all 30 symbols |

**Rules to take the trade:** rules 1–10 in section 2, with a score of 70 or higher.

**Optional refinement (still needs live testing):** also skip setups with TDI overbought/oversold at the sweep. In this backtest it gave:

| Period | Trades | PF |
|---|---:|---:|
| Selection | 36 | 1.80 |
| Hold-out | 27 | 2.18 |

## 15. A+ sniper entry checklist

- [ ] H4 structure points the same way as the trade (last break up for longs, down for shorts)
- [ ] Price is inside the H4 range, ideally in discount for longs or premium for shorts
- [ ] M30 wick sweeps a swing high/low or the previous day's high/low, and the candle closes back inside
- [ ] Within 12 M30 candles, a displacement candle (body ≥ 1×ATR) closes through the last small swing point
- [ ] That move left a fair value gap (≥ 0.15×ATR); place the limit at its midpoint
- [ ] Stop goes past the sweep extreme (buffer: 0.3×ATR or 1.5× spread, whichever is bigger)
- [ ] The H4 range extreme is at least 1.2R away (1.6R or more scores higher)
- [ ] TDI was **not** already below 32 / above 68 at the sweep
- [ ] Regular divergence at the sweep: bonus, not required
- [ ] Ideally London killzone or Asia session
- [ ] Score of 70 or higher, then go
- [ ] Manage the trade: half off at 1R, stop to entry, rest at the smaller of 2.5R and the H4 range extreme

## 16. Final recommended watchlist

- **Core** (positive with 3+ trades on H4→M30): NZDUSD, NZDCAD, GBPJPY, EURJPY, EURCAD, USDJPY, AUDJPY, AUDNZD, AUDUSD
- **Keep scanning, not enough data yet:** EURNZD, NZDJPY, GBPCHF, GBPNZD, GBPAUD, CADJPY, EURGBP, GBPUSD, USDCAD
- **Drop for now** (negative in this window): CADCHF, XAUUSD, USDCHF, AUDCAD, SPX500USD, GBPCAD, CHFJPY, EURUSD

**Re-check:** re-run this study monthly. With only 2–5 trades per pair, the pair list will shift as more data comes in.

---

## Method notes and limitations

- **No look-ahead:**
  - Swing points only count once they're confirmed, 3 bars after they print.
  - Bias candles only count after they close.
  - Indicators at a candle use data up to that candle only.
  - Every entry is a limit order filled on a later candle.
- **Design fixes made before looking at any profit or loss:** two fixes, made after the first runs gave almost no trades.
  - **Target:** changed from the nearest small swing to the H4 range extreme.
  - **Cancel rule:** pending orders now cancel only on a close past the stop (your rule A).
- **Chosen after seeing results:** the timeframe combo and score threshold were picked on the selection period only.
  - The TDI and session breakdowns in section 7 were found on the full sample, so treat them as ideas to test, not proven edges.
- **Data gaps:**
  - **D1 and H4 candles:** built from H1 using UTC days.
  - **M15:** about 52 days.
  - **M5 and M1:** not tested, because the 5,000-bar limit gives too little history.
- **Reproduce:** run `python3 backtest_tv/run.py`. Raw TradingView bars go in `backtest_tv/data/` (not committed; re-pull them with `get_ohlcv`, 1h×2300, 30m×4700, 15m×5000 per symbol).

---

## Addendum: fixed 0.20 lots per trade (same 83 trades)

**Assumptions:**
- **FX pairs:** 0.20 lots = 20,000 units, so 1 pip ≈ $2 on USD-quoted pairs. Cross and JPY pip values are converted to USD at the TradingView H1 close at fill time.
- **Gold:** 1 pip (0.1) = $2.
- **SPX500:** $0.20 per point. This depends on the broker and is assumed.
- **P/L per trade** = net R × stop in pips × pip value. There's no compounding.

| Account | Set | Trades | Win rate | Net profit | ROI | Max DD | Ending balance | PF ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| $500 | all symbols | 83 | 68.7% | **−$215.79** | −43.2% | **95.7%** (effectively blown) | $284.21 | 0.85 |
| $1,000 | all symbols | 83 | 68.7% | **−$215.79** | −21.6% | 59.4% | $784.21 | 0.85 |
| $500 | without XAUUSD | 81 | 70.4% | +$523.77 | +104.8% | 17.0% | $1,023.77 | 1.78 |
| $1,000 | without XAUUSD | 81 | 70.4% | +$523.77 | +52.4% | 11.1% | $1,523.77 | 1.78 |

**Why gold flips the result:**
- **The size problem:** a fixed lot ignores stop size. The two gold trades had M30 stops of $14.19 and $22.08, which at 0.20 lots risked **$284 and $442**. The larger one was 88% of a $500 account on one trade.
- **The damage:** those two losses cost **−$739.56**, more than all 81 other trades made together (+$523.77).
- **Without gold:** 0.20 lots risks a median **$21 per trade**, which is 4.3% of $500 or 2.1% of $1,000. The largest single risk is $66 (13% of $500).

**More numbers, without gold:**
- **Per trade:** average win +$20.96, average loss −$27.96. Best trade +$106.22, worst −$54.99.
- **Days:** average +$9.35 per active day. Best day +$120.61, worst day −$54.99.
- **Weeks:** 13 of 18 profitable. Best week 2026-W41 (+$148.01), worst 2026-W38 (−$83.73).

**Monthly, without gold:**

| Month | Trades | Win rate | PF | Net profit | ROI on $500 | ROI on $1,000 |
|---|---:|---:|---:|---:|---:|---:|
| 2026-06 | 9 | 67% | 2.17 | +$72.30 | +14.5% | +7.2% |
| 2026-07 | 29 | 66% | 1.26 | +$73.61 | +14.7% | +7.4% |
| 2026-08 | 16 | 81% | 4.02 | +$156.89 | +31.4% | +15.7% |
| 2026-09 | 22 | 68% | 1.31 | +$72.95 | +14.6% | +7.3% |
| 2026-10 | 5 | 80% | 4.84 | +$148.01 | +29.6% | +14.8% |

**Margin:** up to 2 trades were open at once, with about $50k notional (gold excluded).
- On $500, that's 100:1 leverage, and many brokers will refuse the second position.
- On $1,000 it's 50:1.

**Verdict:** at 0.20 lots, $500 is over-leveraged; one wide-stop trade can wipe it out.
- **If you want a fixed lot:** exclude gold and indices, and skip any trade whose stop would risk more than 3% of the account (about 0.20 lots × 37 pips on $1,000).
- **Otherwise:** use percent-risk sizing (sections 8–10).
