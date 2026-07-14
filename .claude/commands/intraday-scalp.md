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
