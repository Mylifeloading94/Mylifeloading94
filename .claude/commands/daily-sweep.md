# The Daily Sweep System — Skill

Multi-asset two-timeframe liquidity-sweep strategy (Forex • Gold • SPX500 •
NAS100 • US30). **Daily sets the bias, the 1H delivers the trap, the FVG
delivers the entry.** One setup, one session (NY open), every instrument.

Implemented in `daily_sweep.py`. Source: user's "Daily Sweep System" PDF.

---

## Core logic
At the NY open the market runs stops before the real move. Retail chases the
break; smart money uses that liquidity to fill in the direction of the higher-
timeframe trend. Three conditions must stack **in order** — no stack, no trade:
1. **Daily bias** — who's in control
2. **The sweep** — a fakeout against that bias at NY open
3. **The FVG** — displacement confirming the trap is complete

## Step 1 — Daily bias (before the session)
- **BULLISH (longs only):** Daily printing higher highs AND higher lows.
  Target = previous day's high (PDH). Trap area = sweeps below intraday lows.
- **BEARISH (shorts only):** Daily printing lower highs AND lower lows.
  Target = previous day's low (PDL). Trap area = sweeps above intraday highs.
- **NO BIAS = no trade:** Daily ranging / inside prior day's range. Sit out.
  *This filter alone removes most losing days.*
- Mark **PDH, PDL, and the Asian-session high/low** every morning. The whole
  system trades between PDH and PDL.

## Step 2 — The trap (1H, NY open)
- **Kill zone: 09:30–11:00 ET** (13:30–15:00 UTC in summer / EDT).
  Forex & gold may extend from **08:30 ET** (12:30 UTC — news often triggers the
  sweep). Indices: nothing before the 09:30 cash open; pre-market is noise.
- Wait for price to break a short-term 1H level **against** the daily bias:
  - Bullish bias → sweep **below** a recent 1H low (looks like a breakdown).
  - Bearish bias → sweep **above** a recent 1H high (looks like a breakout).
- Best trap locations: **Asian session high/low**, **PDL/PDH**, obvious
  **equal highs/lows**.

## Step 3 — Confirmation: the FVG
- A **Fair Value Gap** must form immediately after the sweep, in the bias
  direction, created by a **displacement candle** (strong full body — weak
  drift back does not count). Check the FVG on the **15M** for precision.
- Bullish FVG: gap between candle-1 high and candle-3 low. Bearish: mirror.

## Step 4 — Entry, stop, target
- **Entry:** limit inside the FVG. Default = **50% (consequent encroachment)**.
  Aggressive = top of gap (longs) / bottom (shorts). NAS100: top/bottom third.
- **Stop:** beyond the sweep extreme + buffer:
  | Instrument | Buffer |
  |---|---|
  | EURUSD/GBPUSD majors | 3–5 pips |
  | USDJPY / crosses | 5–8 pips |
  | XAUUSD | $1.50–3.00 |
  | SPX500 | 3–5 pts |
  | NAS100 | 15–25 pts |
  | US30 | 30–50 pts |
- **Target:** PDH (longs) / PDL (shorts). **Non-negotiable.**
  **Minimum 2R or skip** — if PDH/PDL is too close, the setup doesn't pay.
- **Management:** stop to breakeven at 1.5R; optional 50% off at 2R, run the
  rest to the daily level.

## Step 5 — Risk rules (what makes it a system)
- **1% risk per trade**, fixed.
- **Max 1 trade per instrument per day** — the Daily Sweep happens once.
- **Max 2 trades total per day** across all instruments.
- **Daily loss limit −2%** → close the platform.
- No trades **Friday after 12:00 ET**.
- **No entries within 15 min of red-folder news** (FOMC/CPI/NFP) — let the
  sweep happen on the news, enter after the FVG.

## Instrument playbook
- **Forex majors:** cleanest Asian-range sweeps at NY open; check DXY inverse
  confirmation; best Tue–Thu.
- **Gold:** most violent sweeper, deep wicks, wider stop; 08:30 data often IS
  the sweep (A+ after the spike); avoid widened-spread transitions.
- **NAS100:** fastest displacement, largest FVGs (often partial fills → enter
  top/bottom third); signature = 09:30 sweep of pre-market/overnight extreme.
- **SPX500:** cleaner/slower; 50% FVG fills reliably; Globex high/low at 09:30.
- **US30:** widest swings, fewest clean FVGs — be pickier; dead if no sweep by
  10:30 ET.

## Invalidation — no trade if
- Daily is ranging (no structure).
- The NY break is WITH the daily trend (breakout, not a trap).
- No FVG forms after the sweep.
- FVG R:R to PDH/PDL is under 2:1.
- Within 15 min of red-folder news.
- You already took your trade for the day.

*One setup. One session. Five instruments. Let the trap come to you.*

---

## Honest backtest note (this repo's standard)
A **mechanical** version of this system (`daily_sweep.py`, honest fills) was
run on 90 days of GenFX data across all instruments. It was **net-negative
across every parameter combination** (−3.4R to −7.6R; only 9–26 trades).

That is **not** a verdict that the system is bad — it's a caveat about
mechanization. The PDF describes a **discretionary manual method** whose edge
lives in judgement a scanner can't reproduce: visual daily bias, choosing the
*best* trap location (Asian range / PDH-PDL / equal H-L rather than any recent
low), DXY inverse confirmation, news timing, and FVG-quality discretion.

**Use this as a manual playbook and an alert aid** (`daily_sweep.scan_live()`
flags NY-killzone sweeps against the daily bias for you to confirm by hand).
For a **mechanically-validated auto-trading edge**, use the Sniper-SMC skill
(`sniper_smc.py` — 70% WR / PF 2.17, holds out-of-sample and under ±25%
parameter perturbation).
