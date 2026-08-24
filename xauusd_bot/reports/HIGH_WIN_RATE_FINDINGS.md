# Can a high-win-rate XAUUSD scalper be built? — the evidence

## Short answer

A high win rate is trivially available and worthless on its own. A **76.7%
win rate on held-out data loses money** (PF 0.85). The binding constraint is
directional accuracy, and a gradient-boosted model trained on 554,516 samples
across eight years reaches **AUC 0.51** — a coin flip — at every geometry and
horizon tested.

## The mechanical constraint

Break-even win rate = `(S + c) / (T + S)` where T = target, S = stop,
c = round-trip cost (~$0.39: spread $0.29 + 2 x $0.05 slippage).

| Geometry | T=$3 | T=$5 | T=$8 | T=$12 |
|---|---|---|---|---|
| T = S (1:1) | 56.5% | 53.9% | 52.4% | 51.6% |
| S = 1.5T | 65.2% | 63.1% | 62.0% | 61.3% |
| S = 2T | 71.0% | 69.3% | 68.3% | 67.8% |
| S = 3T | 78.2% | 77.0% | 76.2% | 75.8% |

Wanting a higher win rate means moving down this table, and every row down
*raises* the accuracy you need. High win rate and low accuracy requirement are
in direct opposition.

## What was built and tested

**Feature set.** 106 strictly scale-free features across M1/M3/M5/M15/H1:
multi-horizon returns normalised by ATR, volatility ratios and ranks, ADX/DI,
RSI, structure bias, BOS/CHoCH, displacement, distances to PDH/PDL/session
extremes/swings in ATR units, day-range position, cyclical time-of-day, session
dummies, and the cost-to-volatility ratio.

No absolute prices, no raw ATR, no price levels — gold ran $1,180 to $4,600
across this dataset, and any level-carrying feature lets the model learn
"gold above $3,000 => buy", which is era-fitting rather than an edge.

**Labels.** Triple-barrier, with the pessimistic tie-break used by the
backtester (stop first when both are touched in the same minute).

**Split.** Strictly chronological with an embargo of one full label horizon at
each boundary, so no test outcome shares bars with training data.
Train 2015-2022 (554,516), validate 2023-2024 (130,083), test 2025-2026
(114,301).

## Result: AUC ~0.505 everywhere

| Geometry | Side | Base win% | AUC valid | AUC test |
|---|---|---|---|---|
| T=0.5 S=1.5 H=60 | long | 74.2 | 0.5091 | 0.5063 |
| T=0.5 S=1.5 H=60 | short | 74.6 | 0.5092 | 0.5030 |
| T=0.8 S=1.2 H=120 | long | 59.7 | 0.5076 | 0.5096 |
| T=0.8 S=1.2 H=120 | short | 59.8 | 0.5058 | 0.5057 |
| T=1.0 S=1.0 H=240 | long | 50.0 | 0.5052 | 0.5057 |
| T=1.0 S=1.0 H=240 | short | 49.9 | 0.5044 | 0.5044 |
| T=1.5 S=1.5 H=480 | long | 49.9 | 0.5061 | 0.5059 |
| T=1.5 S=1.5 H=480 | short | 50.1 | 0.5069 | 0.5040 |
| T=2.0 S=1.0 H=480 | long | 33.7 | 0.5066 | 0.4994 |
| T=2.0 S=1.0 H=480 | short | 33.5 | 0.5050 | 0.5115 |

Ten independent model fits, five geometries, two horizons each, 114,301
held-out samples. Every AUC lands in 0.499-0.512.

## The high-win-rate trap, measured

Threshold chosen on validation, reported on the 2025-2026 test set:

| Geometry | Win rate | Trades/day | Avg $ | PF |
|---|---|---|---|---|
| T=0.5 S=1.5 (long) | **76.7%** | 2.48 | **−0.328** | **0.85** |
| T=0.5 S=1.5 (short) | **74.0%** | 0.94 | **−0.755** | **0.62** |
| T=0.8 S=1.2 (long) | 68.3% | 0.51 | +0.055 | 1.03 |
| T=0.8 S=1.2 (short) | 57.4% | 0.70 | −0.958 | 0.65 |

The 76.7% configuration is exactly the bot that "looks" excellent and drains
an account. The one positive cell (PF 1.03, one trade every two days) sits on
a model with AUC 0.5096 — it is noise, and its own short side is PF 0.65.

Raising the confidence threshold barely moves accuracy: on the test set the
long model goes from 59.7% at threshold 0.50 to 62.0% at 0.75, while trade
count collapses from 262/day to 0.28/day. There is no confident subset to
harvest, which is what AUC 0.51 means in practice.

## Conclusion

The information needed for a high-win-rate gold scalper is not present in OHLC
price structure at 1-240 minute horizons. This is consistent with the earlier
triple-barrier scan over 4.04M bars, where the strongest single conditions
reached ~52% against a ~50% baseline.

The shipped V3 system remains the best available configuration precisely
because it does *not* chase win rate: it sits at T=S, where the accuracy
requirement is lowest, and accepts ~51% accuracy for PF 1.19.

## What would actually be required

Not better modelling — better information. In rough order of expected value:

1. **Order-flow data** (tick volume, bid/ask imbalance, depth). Every result
   here uses OHLC bars only, which discard the microstructure that short-horizon
   edges live in.
2. **A lower cost base.** The whole edge lives inside a ~3%-of-target budget.
   Halving the spread from $0.29 to $0.15 moves the 1:1 break-even at T=$5 from
   53.9% to 51.5% — a larger gain than any modelling change achieved here.
3. **Cross-asset inputs** — DXY, real yields, SPX. Gold is a macro instrument
   and none of its drivers appear in its own candles.
4. **Longer horizons.** The cost hurdle falls as the target grows; the edge
   found in V3 lives at multi-hour holds, not scalps.
