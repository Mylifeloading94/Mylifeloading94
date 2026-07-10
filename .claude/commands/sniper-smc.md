# Sniper-SMC Strategy Skill

High-intelligence Smart Money Concepts strategy with institutional "sniper"
entries, plus the backtest framework that keeps it honest.

Files: `sniper_smc.py` (live scanner), `sniper_backtest.py` (engine),
Fable-5 v5 design spec (below).

---

## STATUS: EXPERIMENTAL — not cleared for live trading

A first backtest printed 66–82% win rates. **Those were a fill artifact.**
Re-running with honest fills (trade-through required, spread paid, same-bar
TP+SL = loss) collapsed the edge. This is the single most important lesson in
this repo: **a backtest that fills limit orders on touch and resolves intrabar
optimistically will manufacture a fake 80% win rate.** Always require:
- Limit fill only on **trade-through** (`low ≤ E − 1 pip` for a buy), never touch.
- Entry price = zone + **spread** (you pay the ask).
- A bar that hits **both TP and SL** counts as a **loss**.
- The **fill bar** breaching SL counts as a loss.
- **≥ 25 trades per pair** before ranking it (9–18 is noise).

Honest-fill results (the real numbers): only **AUDJPY (55.6% WR, PF 1.58)** and
USDCAD (53.8%, PF 1.04) survived; GBPCAD/XAUUSD/EURUSD flipped to losing.
Go-live gate = **PF > 1.3 on 25+ honest-fill trades**, validated on a held-out
window. Until then this runs on demo only.

---

## The sniper sequence (sound ICT logic, entry is real — edge is unproven)

*You are buying the exact spot where retail stops were just harvested, but only
when the 1H book is already long, price is in 4H discount, the reversal printed
an imbalance, and there is a paid trip of ≥ 1.6R to the next liquidity pool.*

1. **HTF bias** — 1H BOS/CHoCH state machine (LONG/SHORT/NONE); no trades in NONE.
2. **4H premium/discount** — longs only ≤ 40% of the 4H dealing range, shorts ≥ 60%.
3. **Draw-on-liquidity gate** — require ≥ 1.6R of clear room to the nearest
   opposing unmitigated pool, else skip. (Fable: this filter matters more than
   any trigger refinement.)
4. **Sweep** of *named* liquidity (PDH/PDL, Asian/London range, equal highs/lows)
   with penetration 0.05–1.5×ATR and a close back inside.
5. **MSS** — displacement candle (body ≥ 1.1×ATR) closing past the correct ICT
   pivot, and the leg must contain a fresh FVG (≥ 0.15×ATR).
6. **Return-to-origin** — limit entry at the origin-FVG midpoint (CE), retrace
   depth 0.50–0.79 (OTE), first mitigation only, fill window 16 bars.
7. **Stop** = sweep extreme − max(0.4×ATR, 3×spread, 2 pips).
   **TP1** = 1.0R close 50% → breakeven; **TP2** = min(2.5R, DOL − 0.1×ATR).
8. **Filters** — killzones 07:00–10:30 / 12:00–15:30 UTC; ATR 30–90th percentile;
   skip if day range ≥ 1.3×ADR20; news ±30 min; 1 trade per currency; ≤4/day.

## Realistic expectation (Fable, honest)
~55–62% TP1-based win rate, PF 1.25–1.6, +0.15–0.35R/trade **if** it works out
of sample. Anything above 65% WR / PF 2 across the basket = a backtest bug.

## Failure modes to keep testing
Lookahead (fractal lag, forming bar, ATR incl. current bar); fill fantasy;
in-sample pair cherry-picking; regime dependence (90d ≈ one regime — split
60/30 train/test); over-tuning (~20 params — freeze all, tune ≤ 3).
