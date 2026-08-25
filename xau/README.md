# XAUUSD scalper research — INCOMPLETE, AND ITS HEADLINE RESULT WAS WRONG

Status: superseded. Kept for the record and for the bug documented below.

## Read this before reusing anything here

`profile_edge.py` was used to scan XAUUSD for a scalping edge. Its first run
reported a large momentum-continuation edge:

| setup | direction | win % | expectancy |
|---|---|---|---|
| RSI >= 75 | LONG | 74.99% | +0.216R |
| RSI <= 25 | SHORT | 72.33% | +0.174R |
| thrust + RSI + range edge | LONG | 76.69% | +0.243R |

**Those numbers are invalid.** They came from a LOOK-AHEAD BUG.

`barrier_outcomes()` was called with entry positions derived from
`np.searchsorted(m1_index, m5.index)` — the M1 position of each M5 bar's
**OPEN** — and then filled at `entry_pos + 1`. That is one minute into the M5
bar, i.e. **four minutes before that bar closed**. But every feature
(`ret5`, `rsi`, `range_pos`) is computed from the M5 bar's **CLOSE**. So the
scan was entering trades four minutes early using knowledge of how the bar
would finish.

Re-run with correct alignment (entry at the M5 close, `close_pos`), every
conditional edge collapses to the unconditional baseline:

| setup | direction | win % | expectancy |
|---|---|---|---|
| baseline (all bars) | long | 59.60% | -0.031R |
| thrust + RSI + range edge | long | 59.51% | -0.033R |
| baseline (all bars) | short | 56.82% | -0.074R |
| thrust + RSI + range edge | short | 54.66% | -0.111R |

`scalper.py` — which always used correct M5-close timing — independently agreed:
1,693 sequential trades on the training window gave **58.89% win rate, profit
factor 0.825, $10,000 -> $2,991**. That was the honest number the whole time,
and the gap between it and the scan is what exposed the bug.

## The lesson

Two things nearly let this through:

1. A high win rate on a scan is not evidence. The corrected baseline shows you
   can reach ~70% win rate on gold with nothing but a wide stop
   (25-pip target / 60-pip stop = 70.03% win rate, expectancy **-0.0074R**).
   Win rate without expectancy is meaningless.
2. Gold rose from ~$2,000 to ~$4,600 across the training window. Any long-biased
   result has to be checked against that drift — which is why long/short
   symmetry was used as the sanity test.

## If you continue this work

- Always resolve barriers from the signal bar's CLOSE, never its open.
- Cross-check any scan result against a sequential backtest before believing it.
- `first_touch` / `barrier_outcomes` resolve a bar spanning both barriers as a
  LOSS, which is the correct conservative choice — keep it.

## Files

| file | purpose |
|---|---|
| `barrier.py` | scalar first-touch barrier walk (reference implementation) |
| `profile_edge.py` | vectorised barrier scan — **see the alignment warning above** |
| `features.py` | M5/M15 feature construction (ATR, RSI, VWAP, sweeps, range position) |
| `scalper.py` | sequential momentum scalper — correct timing, and it loses |

Conventions used throughout: 1 pip = $0.10, contract 100 oz ($1.00 = $100/lot),
spread 3.0 pips ($0.30), 0.5 pip entry slippage, 1.0 pip extra on stops,
$7/lot round-turn commission.
