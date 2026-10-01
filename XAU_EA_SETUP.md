# XAU Scalp + Intraday EA — setup (MacBook)

File: `XAU_ScalpIntraday_EA.mq5` (MetaTrader 5 source code)

## Install
1. MetaTrader 5 → **File → Open Data Folder** → `MQL5` → `Experts`.
2. Drag `XAU_ScalpIntraday_EA.mq5` into that folder.
3. In MT5 press **F4** (or Tools → MetaQuotes Language Editor) to open MetaEditor.
4. In MetaEditor, open the file in the Navigator (Experts) and press **Compile** (F7).
   It should say `0 errors`. If there are errors, screenshot the bottom "Errors" tab.
5. Back in MT5, Navigator → Expert Advisors → right-click → **Refresh**.
6. Open **one XAUUSD chart** (any timeframe — the EA reads M1/M5/H1/H4 itself).
7. Drag the EA onto the chart → Common tab → tick **Allow Algo Trading** → OK.
8. Toolbar **Algo Trading** button must be green. Blue hat top-right = running.

## How it trades
| Engine | Trend (bias) | Entry | SL | Trail |
|---|---|---|---|---|
| Scalp | M5 EMA50/200 + ADX, and H1 agrees | M1 pullback to EMA21 + break candle | 30–120 pips | 25–40 pips |
| Intraday | H4 EMA50/200 + ADX | H1 pullback to EMA21 + break candle | 100–500 pips | 40–60 pips |

Each setup opens 3 positions:
- **Leg 1** closes at TP1 (1R)
- **Leg 2** closes at TP2 (nearest liquidity high/low, or 2R)
- **Leg 3** is the runner (trailed, hard TP at 4R)

At 1R profit the SL on the remaining legs moves to breakeven + 3 pips. Then it trails
at ATR × multiplier, clamped to the min/max pips above, moving at least 5 pips at a time.

## Safety built in
- Risk-based lot size (default 0.5% scalp / 1% intraday per setup, split across the legs)
- Max spread 5 pips, session hours, high-impact USD news blackout (±30 min)
- Daily loss limit 3% → closes trades and stops for the day
- Max setups per day and stop after a losing streak
- No new trades Friday after 18:00, closes everything Friday 21:00 (server time)

## Before going live
1. **Strategy Tester** (Cmd/Ctrl+R): XAUUSD, model "Every tick based on real ticks",
   at least 6–12 months. Test each engine on its own (turn the other off in Inputs).
2. Run on **demo for 2–4 weeks**.
3. Session hours are **broker server time** — check your broker's time zone (often GMT+2/+3).
4. If your broker quotes gold with 3 decimals, `InpPipSize` stays 0.10.
