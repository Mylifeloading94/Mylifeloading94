# Sniper-SMC Strategy Skill

High-intelligence Smart Money Concepts strategy with institutional "sniper"
entries, plus the backtest framework that keeps it honest.

Files: `sniper_smc.py` (live scanner), `sniper_backtest.py` (engine),
Fable-5 v5 design spec (below).

---

## STATUS: VALIDATED on 90d honest fills — demo-forward before scaling

**Final config: OTE 0.62–0.90 + prime killzones + displacement 1.1×ATR + TP 2.5R.**

| Test | WR | PF | note |
|------|----|----|------|
| Full 90d | **70.0%** | **2.17** | +0.35R/trade, n=20 pooled |
| Held-out test (40%) | 71.4% | 2.40 | ✅ holds out-of-sample |
| Split halves | 75% / 62.5% | 2.75 / 1.60 | ✅ positive in both |
| Perturbation ±25% | 65–71% | 1.69–2.45 | ✅ degrades gracefully = real edge |

### How we got here (the lesson)
A first backtest printed 66–82% — a **fill artifact**. With honest fills the
naive version was a loser (PF 0.91). An ablation of Fable's v5 filters found the
**OTE golden pocket** as the single carrier of edge: enter only when price
retraces to 62–90% of the displacement leg, in prime killzones. Everything
else (FVG-in-leg, DOL room, ATR regime) either hurt or didn't move the needle.

### Honest-fill rules the backtest MUST enforce (never relax)
- Limit fill only on **trade-through** (`low ≤ E − 1 pip` for a buy), never touch.
- Entry price = zone + **spread** (pay the ask).
- Bar hitting **both TP and SL** = **loss**; **fill bar** breaching SL = loss.
- Validate **out-of-sample** (60/40) AND **perturb ±25%** — anything that
  collapses under perturbation is overfit, not an edge.

### Caveats (do not ignore)
- Sniper = selective: **~1.5 trades/week across all 15 pairs**. n=20 is small.
- Edge concentrates in **NAS100, USDJPY, GBPJPY, GBPUSD**. XAUUSD dragged (43%).
- Go-live gate = confirm **PF > 1.3 on 25+ live demo trades** before real size.
- Re-run monthly; the regime that favours this will eventually shift.

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
