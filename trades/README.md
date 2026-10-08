# Trade log rules

`trades.json` is the single source of truth for every signal (demo and live).

**Lifecycle:** `pending` (limit not filled) -> `open` (filled) -> `tp1` (TP1 hit, stop moved to entry) -> `closed`.
A pending setup becomes `expired` if price reaches TP1 before the entry fills, or the stop level is hit before the entry fills.

**Honest-fill rules (same as sniper-smc):**
- A limit fills only on trade-through (1 pip beyond the entry), never on a touch.
- If one bar touches both the stop and a target, it counts as the STOP.
- After TP1, half the position is closed and the stop moves to entry (breakeven).

**Result pips (`result_pips`)** are blended: 50% of the position at TP1 + 50% at TP2 (or at breakeven = 0).
Stop before TP1 = full loss (-risk pips). Pip size: 0.0001 default, 0.01 for JPY pairs, 0.1 for XAUUSD.

**Events** are `{ "type": "fill|tp1|tp2|sl|be|expired", "time_utc": ..., "price": ... }`.
