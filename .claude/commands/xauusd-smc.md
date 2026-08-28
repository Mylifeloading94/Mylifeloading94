# XAUUSD SMC Trading Strategy — Skill

High-probability Smart Money Concepts strategy for Gold, with the live bot that
trades it on TradeLocker and posts every trade to Telegram.

**Version:** 1.0 • **Asset:** XAUUSD • **Account:** $50,000 • **Risk:** up to 3%
**Code:** `xauusd_smc/` package, entry point `xauusd_smc_bot.py`, tests in
`tests/test_xauusd_smc.py`.

---

## 1. Core principles
- **Market structure:** BOS (break of structure) and CHoCH (change of character)
  define the trend. A break is a **close** through the last confirmed swing —
  with the trend it is a BOS, against it a CHoCH.
- **Liquidity:** price sweeps equal highs/lows (stop hunts) before reversing. A
  sweep must **close back inside** the level; a close beyond it is a real break,
  not a raid.
- **Order blocks (OB):** the last opposite-colour candle before the displacement
  that broke structure. Price returns to mitigate it.
- **Fair value gaps (FVG):** three-candle imbalance (`high[i-1] < low[i+1]` for
  a bullish gap). Price tends to fill it.
- **Premium / discount:** fib the dealing range — buy below 0.5, sell above 0.5.

## 2. Timeframes (top-down, in order)
| TF | Job |
|----|-----|
| **H4** | Overall bias. Trade with it — unless a fresh **H1 CHoCH** flips the picture (and that trade can never grade above B). |
| **H1** | Key liquidity pools and structure shifts (BOS / CHoCH). |
| **M15** | The setup: liquidity sweep → CHoCH → return to OB / FVG. |
| **M5** | Precision entry: rejection candle (engulfing / hammer) or a 5M BOS. |

## 3. Trade setup — long (short is the exact mirror)
Every condition must hold:
1. Price swept a previous low within the last 2–3 M15 candles (a wider 6-bar
   fallback is allowed and grades no higher than A).
2. H1 or M15 prints a CHoCH — the shift must come **after** the sweep.
3. Price retraces into a bullish **OB or FVG** sitting in **discount (<50%)** of
   the swing.
4. **M5 confirms**: bullish engulfing, hammer rejection, or a 5M BOS after price
   touches the zone.
5. **R:R ≥ 1:2 to TP1**, and there is a liquidity pool ≥ 2R away to pay for it
   ("draw on liquidity" — minor pullback highs in between are not blockers).

**Entry** — buy limit at the top of the OB, or (what the bot does) market entry
on the close of the confirming M5 candle. The bot re-prices against the real
ask/bid and **refuses to chase** more than 0.5R past the zone.

**Stop loss** — below the OB bottom *and* below the sweep low, plus a buffer of
`max(2.5 pips, 0.25 × ATR(M15))`. Typical distance $10–30 on gold.

**Take profit** — TP1 = **2R**, TP2 = **3R** (extended to a real liquidity pool
when one sits between 3R and 4R). At TP1: **close 50% and move the stop to
breakeven**, let the runner go.

## 4. Risk management
- Risk by grade: **A+ 3%**, **A 2.5%**, **B 1.5%**, C = no trade.
- `Lot = risk$ / (SL_pips × $10)` — for gold **1 pip = $1.00 of price** and one
  lot pays **$10 per pip** (SL 30 pips on $1,500 risk → 5.00 lots).
- **Daily stop:** 2 consecutive losses, or −6% ($3,000 on $50k).
- **Weekly stop:** −10% ($5,000).
- **No trades** ±15 min around high-impact news (NFP, CPI, FOMC).
- Skip if **spread > $0.50**, or the M15 range is too tight (ATR < $1.50).
- London 07:00–16:00 and New York 12:00–21:00 UTC, weekdays only.

## 5. Trade grading
| Grade | Requirements | Risk |
|-------|--------------|------|
| **A+** | H4 trend + H1 CHoCH + major liquidity sweep (equal highs/lows before the raid) + retrace ≥ 0.705 + M5 confirmation | 3% |
| **A**  | H4 trend + M15/H1 CHoCH + sweep + OB/FVG + M5 confirmation | 2.5% |
| **B**  | M15 structure only (no H4 alignment) or no fresh sweep | 1.5%, skip if R:R < 1:2 |
| **C**  | Anything missing | **do not trade** |

The bot's default `MIN_GRADE=A` — B setups are detected, logged and skipped
until you deliberately switch it on.

## 6. Running the bot
```bash
python3 xauusd_smc_bot.py --check      # verify credentials + data + Telegram
python3 xauusd_smc_bot.py --dry-run    # full analysis, alerts, no orders
python3 xauusd_smc_bot.py              # live loop, scans every 60 seconds
python3 -m unittest discover -s tests  # 41 offline tests
```
Credentials live in `.env` (gitignored): `TL_ENV, TL_EMAIL, TL_PASSWORD,
TL_SERVER, TL_ACCOUNT_ID, TG_BOT_TOKEN, TG_CHAT_ID`. `TL_ENV=live` additionally
requires `TL_CONFIRM_LIVE=I_UNDERSTAND`. Full setup: `XAUUSD_SMC_BOT.md`.

## 7. Implementation rules the code must keep
- **Closed bars only.** The forming candle is dropped from every timeframe; a
  fractal at index *i* is only visible at *i+strength*. No repainting.
- **Sweep before shift.** A CHoCH that predates the sweep is not the setup.
- **Honest fills.** Entry is re-priced at the ask (buy) / bid (sell) and R:R is
  recomputed from that fill before sizing — never from the idealised zone price.
- **Risk is money, not lots.** Size from the real stop distance; refuse the
  trade when the rounded lot size would overshoot the budget.
- **One fingerprint, one trade.** A zone that has been traded is never re-entered.

## 8. Expectations — read this before scaling size
The strategy document quotes a backtest of +797% with a **~44% win rate**
(the profit comes from large winners, not from being right often). Be careful
mixing that with the phrase "high win rate" — with TP1 at 2R, a 44% win rate is
the *expected* shape of this system, and it will produce losing streaks.

This repository's own honest-fill work is a warning worth keeping in view:
`honest_edge.py` measured **XAUUSD at 45–50% WR with profit factor < 0.5** and
banned it, and `sniper_smc.py` found gold the weakest pair in the basket (43%).
Neither used *these* rules — but both used the same broker data, so:

- Run **`--dry-run` first**, then **demo**, and gate live money on
  **profit factor > 1.2 over 40+ trades**, not on a win-rate number.
- 3% risk with a 44% win rate implies drawdowns near 20%. Start lower
  (`MIN_GRADE=A+`, or edit `GRADE_RISK`) until the live sample says otherwise.
- Re-check monthly. The regime that suits a strategy always shifts eventually.

*Not financial advice. Past performance does not guarantee future results.*
