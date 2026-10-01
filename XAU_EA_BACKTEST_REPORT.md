# XAU Scalp + Intraday EA — backtest report

**Test:** 3 Jul 2026 → 1 Oct 2026 (90 days), XAUUSD, $500 start
**Data:** Dukascopy M1 (BID) + Dukascopy H1 history for indicator warm-up
**Costs:** 3-pip ($0.30) spread on every trade, no commission, no swap, no slippage
**Engine:** `xau_ea_backtest.py` — Python port of `XAU_ScalpIntraday_EA.mq5` rules
(server time GMT+3, SL checked before TP inside a bar, news filter off as in MT5 tester)

## 1. $500 account, 90 days

| Run | Trades | Win rate | Net | Return | Max DD |
|---|---|---|---|---|---|
| EA defaults (0.5% / 1% risk) | **0** | – | $0 | 0% | 0% |
| $500 mode (0.01 min lot if risk ≤ 5%) | 191 | 45% | +$21.97 | +4.4% | **19.2%** |

$500 mode by engine:

| Engine | Trades | Win rate | Net | Profit factor | Avg R |
|---|---|---|---|---|---|
| Scalp (M5/M1) | 185 | 44.3% | −$37.57 | 0.93 | −0.07R |
| Intraday (H4/H1) | 6 | 66.7% | +$59.54 | 2.72 | +0.47R |

Why defaults took 0 trades: 0.5% of $500 = $2.50 risk. Gold's minimum 0.01 lot loses $1 per
$1 move, and the smallest scalp SL is 30 pips ($3) → the size rounds to 0. Intraday SLs are
$10–$50, so 0.01 lot = 2–10% of the account. In $500 mode every trade was a **single 0.01
lot**, so the 3-target system never actually ran (it needs ≥ 0.03 lots).

## 2. Is there an edge? (size-independent, in R)

Scalp, 90 days:

| Variant | Trades | Win % | Total R | Jul–Aug | Sep |
|---|---|---|---|---|---|
| Base | 187 | 46.0 | −9.4R | −7.3R | −2.1R |
| Base with zero spread | 190 | 51.6 | +9.3R | +1.7R | +7.6R |
| Require liquidity sweep | 85 | 43.5 | −8.4R | −4.1R | −4.4R |
| SL min 60 pips | 185 | 50.8 | +8.7R | −4.7R | +13.5R |
| London/NY 10–18 only | 175 | 48.0 | −1.0R | +2.5R | −3.5R |
| TP1/BE at 1.5R | 182 | 39.6 | +3.1R | −0.7R | +3.8R |
| ADX ≥ 25 | 171 | 43.9 | −19.8R | −18.4R | −1.5R |

Intraday, Feb → Sep 2026 on H1 bars (longer sample):

| Variant | Trades | Win % | Total R | Feb–May | Jun–Sep |
|---|---|---|---|---|---|
| Base | 39 | 43.6 | −1.7R | +3.7R | −5.4R |
| Trail 150–400 pips | 39 | 41.0 | −5.7R | +0.4R | −6.1R |
| Trail 150–400 from 2R | 37 | 45.9 | −1.8R | +2.8R | −4.6R |

## 3. Verdict

- **Scalp engine: no edge.** Gross it is about break-even (+0.05R/trade); the spread
  turns it negative. No variant was positive in *both* halves of the test.
- **Intraday engine: no proven edge.** The 6-trade 90-day result was luck; over 8 months
  it is −1.7R. Winners almost all close near +1R because the 40–60 pip trail is tiny versus
  a 250–450 pip SL, so the "multi-target" structure behaves like a fixed 1:1.
- **Not ready for a live or funded account.**

## 4. What to change before trading it

1. Trailing in pips doesn't scale with a $4,000+ gold price. Trail in R or ATR instead.
2. With $500, use **one position with partial closes** (or a broker allowing 0.001 lots)
   or the multi-target logic never runs.
3. The entry (EMA pullback + break candle) needs a better filter — candidates: SMC
   structure (BOS + FVG retest, as in `sniper_smc.py`), London/NY session liquidity sweeps,
   or higher-TF key levels.
4. Re-test on 12+ months, accept only a variant that is positive in every quarter.
