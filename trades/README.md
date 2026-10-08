# Trade log rules

`trades.json` is the single source of truth for every signal (demo and live).

**Lifecycle:** `pending` (limit not filled) -> `open` (filled) -> `tp1` (TP1 hit, stop moved to entry) -> `closed`.
A pending limit order stays live like a real broker order. It is cancelled (`expired`) only on STRUCTURE invalidation: (a) an M15 candle closes beyond the stop level, or (b) the M15 structure flips against the idea (e.g. a sell setup whose M15 turns bullish). Touching the TP1 level before the entry fills does NOT cancel it by itself.

**Honest-fill rules (same as sniper-smc):**
- A limit fills only on trade-through (1 pip beyond the entry), never on a touch.
- If one bar touches both the stop and a target, it counts as the STOP.
- After TP1, half the position is closed and the stop moves to entry (breakeven).

**Result pips (`result_pips`)** are blended: 50% of the position at TP1 + 50% at TP2 (or at breakeven = 0).
Stop before TP1 = full loss (-risk pips). Pip size: 0.0001 default, 0.01 for JPY pairs, 0.1 for XAUUSD, 1.0 (index point) for SPX500USD.

**Events** are `{ "type": "fill|tp1|tp2|sl|be|expired", "time_utc": ..., "price": ... }`.

**Order types (`order_type`):**
- `market` — ENTER NOW execution trade. Allowed only inside a killzone (07:00–10:30 / 12:00–15:30 UTC) when sweep + MSS has just confirmed and price is still within 0.3R of the ideal entry (origin FVG/OB). Logged with status `open` and an immediate `fill` event at the live M1 close (+ spread for buys). DOL room ≥ 1.6R is measured from the actual market price.
- `limit` — pending WAIT order at the zone; lifecycle above.

**Watchlist:** all 28 OANDA FX majors/crosses + `OANDA:XAUUSD` (gold) + `OANDA:SPX500USD` (S&P 500). Priority list: XAUUSD, GBPJPY, GBPUSD, USDCAD, USDJPY, CHFJPY, SPX500USD, GBPAUD, NZDUSD, NZDJPY.
