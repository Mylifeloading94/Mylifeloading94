# Price Action Strategy Skill

Trend-pullback price-action system — pure candlestick/EMA logic, no SMC/ICT
liquidity concepts. Implemented in `price_action_strategy.py`.

---

## STATUS: NOT VALIDATED — do not go live on this alone

A 6-month backtest (Jan-Jul 2026, hourly bars, honest fills, spread paid,
one trade at a time per instrument) across the full watchlist — 14 FX pairs,
XAUUSD, NAS100, SPX500, US30 — found a real edge only in the three equity
indices, and even that fails out-of-sample. See the full write-up in the
`price_action_strategy.py` docstring.

| Instrument | n  | WR    | PF   | E[R]  |
|-----------|----|-------|------|-------|
| SPX500    | 15 | 46.7% | 2.25 | +0.59 |
| US30      | 21 | 47.6% | 1.93 | +0.44 |
| NAS100    | 15 | 40.0% | 1.30 | +0.18 |
| all 14 FX pairs + XAUUSD | — | 21-34% | 0.44-0.93 | negative |

Split-half (H1 Jan-Apr vs H2 Apr-Jul) shows the index edge is entirely
front-loaded and **inverts** in H2 — not time-stable. Parameter perturbation
(+-25%) holds up in-sample, ruling out a pure parameter fluke, but the failed
out-of-sample half means this is regime-dependent, not a standing edge.

**Do not risk real capital on this system as configured.** Treat it as a
watchlist/research tool: re-run monthly, and only promote an instrument to
live-demo once it clears this repo's standard gate — **PF > 1.2 over 40+
trades, out-of-sample** — same bar used for sniper_smc and honest_edge.

## Setup logic (long; short mirrors)
1. **4H trend** — EMA50 > EMA200 and 4H close > EMA50.
2. **1H pullback** — signal bar's low comes within 0.25×ATR of the 1H EMA20.
3. **Reversal candle** — bull pin bar (lower wick ≥ 60% of range) or bull
   engulfing at the pullback.
4. **Not extended** — close within 1.5×ATR of EMA20 (no chasing).
5. **Entry** — stop order at the signal bar's high + spread, 3-bar fill
   window, trade-through only (never a touch).
6. **Stop** — min(signal low, prior low) − 0.1×ATR.
7. **Exit** — TP1 at +2R (close 50%, stop to breakeven), TP2 at +4R runner,
   40-bar time-stop on the runner.
8. **Risk** — size for 1-2% account risk per trade (R-multiple metrics above
   are risk-size-invariant; scale directly).

## Data source
Yahoo Finance hourly chart API (`query2.finance.yahoo.com`) via direct
`requests` calls through the environment's HTTPS proxy — TradeLocker/GenFX
credentials were not available in this environment, so this is a Yahoo-data
backtest, not a broker-tick backtest. Re-validate against TradeLocker history
before trusting fills precisely (Yahoo FX/index bars are mid-price, no
real bid/ask depth).

## Session-filter experiment (tested, not adopted)
Restricting FX + XAUUSD signals to London/NY killzones (07:00-10:30 /
12:00-15:30 UTC) nudges USDCAD, EURAUD and XAUUSD to barely positive
(PF 1.09-1.24, n=31-43) but not enough to trade. Logic lives in the
`robustness.py` scratch script used to produce these numbers (not committed —
rerun ad hoc if needed).

## Next steps to actually find an edge here
- The reversal-pullback-breakout pattern has a genuinely low hit rate
  (~25-30%) against 2R/4R targets on FX — either the pattern needs a much
  higher-quality filter (structure/liquidity context, like sniper_smc's OTE
  filter) or FX intraday price action alone isn't enough carrier of edge on
  this data, matching the honest_edge.py finding for naive trend-continuation.
- Indices are the one lead worth following: get more history (12mo+) before
  trusting a 15-21 trade sample either way.
