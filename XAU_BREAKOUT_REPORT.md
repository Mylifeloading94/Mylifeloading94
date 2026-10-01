# XAU Breakout Pro v2 — backtest results

**Strategy:** `XAU_BreakoutPro_EA.mq5` (MT5) / `xau_breakout_backtest.py` (Python test)
**Data:** Dukascopy XAUUSD M1. Jul–Sep 2026 complete; Apr–Jun ~2/3 of days downloaded.
**Costs:** 3-pip spread on every trade, honest fills (stop checked before target inside a candle).

## How it trades
| Engine | Level | Entry | Filter | SL | Exits |
|---|---|---|---|---|---|
| Scalp (M5) | Asian range 00–06 UTC | First M5 close beyond it, 06–10 UTC | Daily trend (D1 EMA20/50) must agree | 1.5 × ATR(M5) | ½ at 1R → BE, rest 2R, 10h time stop |
| Intraday (H1) | Previous day high/low | First H1 close beyond it, 06–16 UTC | Daily trend must agree | 1.5 × ATR(H1) | ½ at 1R → BE, rest 3R, 24h time stop |

If the first break of the day goes against the daily trend, that engine sits out the day.

## $500 account, 90 days (3 Jul → 1 Oct 2026)

| Risk per trade | Trades | Win rate | Net profit | ROI | Max drawdown | Profit factor |
|---|---|---|---|---|---|---|
| 1% | 14 | 64.3% | **+$52.02** | **+10.4%** | 3.8% | 2.38 |
| **2%** | 14 | 64.3% | **+$62.35** | **+12.5%** | **3.7%** | **2.66** |

At 2% risk: 9 winners (6 full winners at +1.5R to +2R, 3 closed at breakeven +$0.30),
5 losers (−$5.56 to −$14.37). Best trade +$21.47, worst −$14.37.
Most trades are 0.01 lot, so 1% vs 2% risk changes little at $500.

| Engine (2% risk) | Trades | Win rate | Net |
|---|---|---|---|
| Scalp (Asia break) | 13 | 69.2% | +$76.70 |
| Intraday (PDH/PDL) | 1 | 0% | −$14.37 |

The intraday engine was skipped on most signals: its stop is ~$15–40, so even 0.01 lot is
3–8% of a $500 account. It needs roughly **$1,500+** to trade properly.

## Edge check — longer sample, size-independent (Apr → Sep, R units)

| | Trades | Win rate | Profit factor | Avg per trade |
|---|---|---|---|---|
| Scalp | 26 | 61.5% | 1.81 | +0.31R |
| Intraday | 31 | 64.5% | 1.88 | +0.31R |
| **Both** | **57** | **63.2%** | **1.85** | **+0.31R** |

By month: Apr −0.5R (2 trades) · May +6.6R · Jun +3.0R · Jul +3.7R · Aug +2.0R · Sep +2.9R

Intraday engine on 8 months of H1 data (Feb–Sep): 41 trades, 66% win rate, PF 2.0,
positive in both halves.

$500 at 2% over Apr–Sep (6 months): **+$75.45 (+15.1%)**, max drawdown 5.0%, 27 trades, 59% win rate.

## Compared to v1
| | v1 (EMA pullback) | v2 (session breakout) |
|---|---|---|
| 90-day $500 | +4.4%, DD 19% (191 trades) | **+12.5%, DD 3.7%** (14 trades) |
| Edge per trade | −0.05R (losing) | **+0.31R** |
| Profit factor | 0.93 | **1.85** |

## Honest caveats
- **Small sample.** 14 trades in 90 days, 57 over ~6 months. The edge is consistent across
  months and settings, but it needs demo forward-testing before real money.
- Selective by design: about 1 trade a week on $500.
- Backtest ≠ live: real spreads widen at the London open, and fills can slip.
- Trend filter means it sits out when the daily trend is flat (e.g. only 3 trades in Sep).

## Addendum — can it scalp 4–10 times a day at 1% risk?

Constraint: 1% of $500 = $5, and 0.01 lot loses $1 per $1 move → every stop must be ≤ 50 pips.

Tested on Jul–Sep (in-sample) and Apr–Jun (out-of-sample), all with the daily trend filter,
SL 20–50 pips, simulator checked neutral (random entries at zero spread ≈ 0R):

| Setup | Trades/day | Win rate | Avg per trade (3-pip spread) | Avg (1.5-pip spread) |
|---|---|---|---|---|
| M1 EMA pullback | 9–17 | 43% | −0.14R | −0.07R |
| M1 previous-hour break | 7.6 | 45% | −0.11R | −0.06R |
| M1 20–30 bar breakout | 14–23 | 43% | −0.14R | −0.09R |
| M1 dip-buy in daily trend (best) | 7–9 | 49–52% | −0.02R to 0R | +0.02R to +0.05R |
| M5 versions | 1–2.5 | 42–50% | −0.17R to 0R | −0.14R to +0.01R |

**No high-frequency setup has a real edge after costs.** The best (M1 dip-buy) is break-even
out-of-sample. v2 at a strict 1% takes 0 trades on $500 (its stops are 50–110 pips);
allowing 0.01 lot up to 1.5% risk gives 10 trades / 90 days, +4.7%, DD 3.3%.
