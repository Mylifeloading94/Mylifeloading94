# Price Action Strategy Skill

Trend-pullback price-action system — pure candlestick/EMA logic, no SMC/ICT
liquidity concepts. Implemented in `price_action_strategy.py` (data fetch/
cache in `pa_data.py`).

---

## STATUS: VALIDATED on indices only — NAS100 / SPX500 / US30

FX and XAUUSD are **banned** — no edge survived after three independently
designed attempts. Run `python3 price_action_strategy.py` to reproduce (it
auto-downloads 730 days of hourly bars into `pa_data/` on first run).

### The validation that held up
Walk-forward, not a naive split: **TRAIN = 21 months, TEST = the most recent
6 months, held out and never touched while designing the setup.**

| Instrument | TRAIN (21mo)          | TEST (6mo, held out)  |
|-----------|------------------------|-------------------------|
| SPX500    | n=105  PF=1.51  E=+0.30 | n=15  PF=2.25  E=+0.59 |
| US30      | n=95   PF=1.29  E=+0.18 | n=21  PF=1.93  E=+0.44 |
| NAS100    | n=92   PF=1.79  E=+0.43 | n=15  PF=1.30  E=+0.18 |

All three are profitable on TRAIN **and** the edge holds on the fully
held-out TEST window — that's the actual bar for "solid," not a 50/50 split
of one thin 6-month sample (an earlier pass here did exactly that and got
fooled: n=5 vs n=6 per half is noise, not evidence, and it's why the first
version of this doc said "not validated"). More data fixed that, it didn't
change the strategy.

**Caveats, so this doesn't get oversold:**
- Perturbation (±25% touch/extension/stop tolerances) run directly on the
  held-out TEST window stays PF > 1.3 across the whole range — not a fluke
  of exact parameters.
- A 3-fold split of the 21-month TRAIN window shows 2 of 3 folds strongly
  positive (PF 1.08-2.19) but the **middle fold is negative** for all three
  indices (PF 0.67-0.73). A real bad regime happened in there. Same shape as
  honest_edge.py's USDCHF finding (1st-half PF 0.60, 2nd-half PF 3.73) — a
  real edge, not a time-stable one. **Re-run this validation monthly; if the
  most-recent-6-month PF drops under ~1.2, stop trading it.**
- n is still modest (92-105 train, 15-21 test per instrument). Treat as a
  live-demo hypothesis before real size, same gate as every other strategy
  in this repo: **PF > 1.2 over 40+ trades, out-of-sample.**

### Setup logic (long; short mirrors)
1. **4H trend** — EMA50 > EMA200 and 4H close > EMA50.
2. **1H pullback** — signal bar's low comes within 0.25×ATR of the 1H EMA20.
3. **Reversal candle** — bull pin bar (lower wick ≥ 60% of range) or bull
   engulfing at the pullback.
4. **Not extended** — close within 1.5×ATR of EMA20 (no chasing).
5. **Entry** — stop order at the signal bar's high + spread, 3-bar fill
   window, trade-through only (never a touch).
6. **Stop** — min(signal low, prior low) − 0.1×ATR.
7. **Exit** — TP1 at +2R (close 50%, stop to breakeven), TP2 at +4R runner,
   40-bar time-stop on the runner. Matches the user's requested 1:2-1:4 RR.
8. **Risk** — size for 1-2% account risk per trade (R-multiple metrics above
   are risk-size-invariant; scale directly).

---

## Why FX and XAUUSD are banned — three attempts, all failed pooled

Tuning honestly means checking the whole basket pooled on TRAIN before ever
touching TEST, not cherry-picking whichever pair looks best after the fact.
All three attempts below were grid-tuned that way (basket-pooled TRAIN,
min-trade-count filters) and none cleared breakeven:

1. **This EMA20-pullback system**, run on FX+XAUUSD pooled: no config beat
   PF ≈ 0.99 on 21 months / 1000+ pooled trades.
2. **OTE golden-pocket variant** (swing-detected impulsive leg, 62-90%
   Fibonacci retracement entry zone instead of a raw EMA touch, structural
   stop at the leg's origin — the same filter family that made sniper_smc
   work) — pooled PF plateaued at ~0.99 across a 12-point parameter grid.
3. **Sweep-and-reclaim** (Wyckoff spring/upthrust: price sweeps a recent
   20-40 bar swing extreme, closes back inside within 2-4 bars on a
   displacement candle ≥0.5×ATR) — pooled PF plateaued at ~1.02-1.03 across
   a 54-point parameter grid, i.e. statistically indistinguishable from
   costs-neutral.

Individual FX pairs occasionally *looked* good in only one of TRAIN or TEST
(e.g. XAUUSD/AUDUSD under variant 2, USDJPY under variant 3) but none held
up in **both** windows for the same pair — classic multiple-comparisons
noise from scanning 18 instruments × 3 strategy families. Don't re-promote
any of them without a genuinely different idea and the same TRAIN/TEST
discipline used above.

This mirrors honest_edge.py's finding almost exactly: naive price-action
trend/reversal patterns are not a free edge on FX. Whatever edge exists on
FX in this repo lives in honest_edge.py's sweep-and-reclaim (USDCHF primary)
and sniper_smc.py's OTE+MSS system — both use tighter, more specific
liquidity/structure filters than anything tried here.

## Data source
Yahoo Finance hourly chart API (`query2.finance.yahoo.com`), fetched and
cached by `pa_data.py` via direct `requests` calls through the environment's
HTTPS proxy — TradeLocker/GenFX credentials were not available when this was
built, so this is a Yahoo-data backtest, not a broker-tick backtest.
Re-validate against TradeLocker history before trusting fills precisely
(Yahoo FX/index bars are mid-price, no real bid/ask depth).
