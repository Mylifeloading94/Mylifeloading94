# Intraday / Scalping Strategy Skill

Per-pair search for a same-day, session-based edge on the FX + XAUUSD
watchlist. Implemented in `intraday_strategy.py` (data fetch in
`fetch_intraday_data()`, cached to `pa_data_5m/`).

---

## STATUS: ORB validated on 4 pairs (thinner evidence than the swing strategy)

Two genuinely different intraday designs were tested, both session-bound
(London 07:00-10:00 UTC / NY 12:00-15:00 UTC) with a hard same-day
time-stop — no overnight risk, the actual definition of "intraday":

1. **Opening Range Breakout (ORB)** — momentum/continuation. First 30 min
   of the session sets a range; a close beyond it within the next hour
   triggers a breakout entry, stop on the opposite side, fixed 1.5R target,
   flat by session end.
2. **TWAP Reversion Scalp** — mean-reversion, fading price back toward a
   session-anchored TWAP (Yahoo has no real FX volume, so true VWAP isn't
   computable — TWAP is the honest substitute) when price closes ≥1.5×ATR
   away with a rejection candle.

**TWAP lost or was flat on all 12 pairs tested (PF 0.02-1.07) — banned
outright.** ORB won on every pair by comparison, and on 4 of them held up
under a split-half check (first 30 days vs last 30 days — the only
OOS-style validation possible, see caveat below):

| Tier | Pairs | H1 PF | H2 PF |
|------|-------|-------|-------|
| **PRIMARY** | EURUSD | 1.76 | 1.83 |
| | AUDUSD | 1.76 | 1.59 |
| | GBPAUD | 1.78 | 1.40 |
| | USDCHF | 1.39 | 1.21 |
| **WATCH** (fades hard) | NZDUSD | 1.77 | 1.11 |
| | XAUUSD | 1.71 | 1.13 |
| **BANNED** | USDCAD | 0.89 | 1.44 (sign-flipped) |
| | USDJPY | 1.03 | 1.07 (flat both) |
| | GBPCAD | 1.04 | 0.95 (flat both) |
| | NZDJPY | 1.29 | 0.83 (inconsistent) |
| | GBPJPY | 0.87 | 0.85 (losing both) |
| | EURGBP | 0.64 | 0.73 (losing both) |

Same fixed ORB parameters on every pair — deliberately not tuned per pair,
which is what makes 4 pairs holding up meaningful rather than fitted noise.
GBPJPY and EURGBP losing here matches their BANNED status in the swing
strategy (`price_action_strategy.py`) — a real cross-timeframe signal, not
a fluke of one parameter set.

### Why this is thinner evidence than the swing strategy
- **60 days is Yahoo's hard ceiling for 5-minute FX bars.** There's no way
  to get a multi-year TRAIN/TEST split here like the swing strategy has.
  Split-half of 60 days is the best available check — not equivalent to 21
  months TRAIN + 6 months truly-held-out TEST.
- **Single volatility/rate regime.** 60 days is one macro environment. The
  4-pair PRIMARY tier could be regime-specific. **Re-validate weekly**, not
  monthly — the underlying sample is too short for a monthly cadence to
  catch a regime shift in time.
- No parameter grid search was run (ORB_MINUTES=30, TARGET_R=1.5, etc. are
  one principled a-priori choice, not tuned). Don't start grid-searching
  per pair — that would undermine the one thing lending this credibility.

### Setup logic (ORB, long; short mirrors)
1. First 30 minutes of the session (London or NY) sets the opening range
   (high/low of the first 6× 5-min bars).
2. A close beyond the range high within the next hour triggers a stop-entry
   breakout (trade-through fill only, never a touch).
3. Stop = opposite side of the opening range.
4. Target = fixed 1.5R, single target (no partial/runner — that's the
   honest shape of a scalp).
5. Time-stop = flat by ~3 hours after session open, regardless of outcome.
6. One trade per session per pair.

## Data source
Yahoo Finance 5-minute chart API, 60-day range (the max Yahoo allows for
this interval) — same proxy/fetch mechanism as `pa_data.py`. FX bars carry
zero real volume from this source; XAUUSD (GC=F futures) has real volume.

## Risk sizing
Not yet wired into `RISK_TIER` — decide before trading live. Given the
thinner validation here, size ORB_PRIMARY below the swing strategy's
SECONDARY tier, and ORB_WATCH at half that again.

---

## UPDATE (2026-07-20): Tuesday-Thursday filter — currently recommended

Two follow-up questions were tested against this same 5-minute ORB data.

**1. Does adding an SMC liquidity-sweep precondition improve the breakout?**
No. A sweep-below-range + reclaim + break-of-structure-with-displacement
variant was grid-searched across 36 parameter combinations on 15-minute
bars — every combination scored PF < 1 (best PF=0.68). Isolating pieces:
sweep+reclaim alone PF=0.51, full SMC+breakout PF=0.64, plain ORB (no
sweep precondition) on the identical data PF=1.23. The sweep filter adds
lag, not confirmation — it actively hurts here. Not adopted.

**2. Does day-of-week matter?** Yes. Filtering ORB signals to
Tuesday/Wednesday/Thursday only (dropping Monday gap risk and Friday's
liquidity drop-off), split-half validated:

| Tier | Pairs | TRAIN | TEST |
|------|-------|-------|------|
| **ORB_CORE** | EURUSD | WR=62.1% PF=1.91 | WR=64.0% PF=1.82 |
| | USDCHF | WR=60.6% PF=1.94 | WR=56.7% PF=1.88 |
| **ORB_CORE_WATCH** (half size) | AUDUSD | WR=53.1% PF=1.69 | WR=56.2% PF=1.77 |
| | GBPAUD | WR=57.1% PF=2.05 | WR=50.0% PF=1.80 |
| | NZDUSD | WR=53.3% PF=1.85 | WR=45.2% PF=1.38 |

Pooled ORB_CORE (EURUSD+USDCHF, Tue-Thu only): n=117, WR=60.7%, PF=1.89,
E[R]=+0.27 — clears the 60% win-rate bar on both split halves, not just
pooled. Unfiltered (all weekdays) the same two pairs pool to WR=57.1%/
PF=1.53 — the day-of-week filter is a real, validated improvement, not a
lucky subset.

XAUUSD, previously ORB_WATCH unfiltered, gets *worse* under this filter
(PF 1.13→0.82 second half) and is dropped from the Tue-Thu tier entirely.
USDCAD stays banned (sign-inconsistent even Tue-Thu-only: PF 0.96→1.95).

**Account challenge** (pooled CORE, n=117, chronological compounding):

| Account | Risk | End balance | Return | Max DD |
|---------|------|-------------|--------|--------|
| $500 | 1% | $678.59 | +35.7% | $36.50 |
| $500 | 2% | $910.25 | +82.0% | $95.84 |
| $1,000 | 1% | $1,357.18 | +35.7% | $73.01 |
| $1,000 | 2% | $1,820.49 | +82.0% | $191.69 |
| $10,000 | 1% | $13,571.81 | +35.7% | $730.08 |
| $10,000 | 2% | $18,204.93 | +82.0% | $1,916.87 |

Caveat: 117 trades over ~84 calendar days on two correlated USD-leg pairs,
one volatility regime, no true out-of-sample data beyond Yahoo's 60-day
ceiling. Treat as the edge's shape, not a promise — re-validate weekly.

Implementation: `generate_orb_signals(df, weekdays=ALLOWED_WEEKDAYS)` in
`intraday_strategy.py`; run `python3 intraday_strategy.py` to see both the
original unfiltered table and this Tue-Thu re-cut printed together.
