# XAUUSD SMC Bot — setup & operation

Automated Smart Money Concepts bot for Gold. It scans **every 60 seconds**,
places the trade on **TradeLocker**, and posts the trade to your **Telegram
channel immediately after the broker confirms the fill**.

Strategy reference: `.claude/commands/xauusd-smc.md` (the `/xauusd-smc` skill).

---

## What it does each cycle

1. Refresh equity; roll the daily / weekly counters.
2. Manage open trades — at **TP1 close 50% and move the stop to breakeven**;
   report any position the broker has closed.
3. Run the gates: session, news blackout, spread, volatility, risk limits.
4. Top-down analysis: **H4 bias → H1 structure → M15 sweep + CHoCH + OB/FVG in
   discount/premium → M5 confirmation**.
5. Grade the setup (A+ / A / B / C) and size it from the real stop distance.
6. Send a market order with SL and TP attached, then fire the Telegram alert
   (with a chart when `matplotlib` is installed).

Only **closed** candles are used — the forming bar is dropped on every
timeframe, so signals never repaint.

---

## Install

```bash
pip3 install requests          # required
pip3 install matplotlib        # optional — enables chart images in Telegram
```

## Configure

```bash
cp .env.example .env
$EDITOR .env      # .env is gitignored — never commit it
```

| Variable | Meaning |
|----------|---------|
| `TL_ENV` | `demo` (default) or `live` |
| `TL_EMAIL` / `TL_PASSWORD` | TradeLocker login |
| `TL_SERVER` | the server name on your TradeLocker login screen (e.g. `OSP-DEMO`) |
| `TL_ACCOUNT_ID` | optional — blank uses the first account |
| `TL_CONFIRM_LIVE` | must be `I_UNDERSTAND` before the bot will trade live |
| `TG_BOT_TOKEN` | from [@BotFather](https://t.me/BotFather) |
| `TG_CHAT_ID` | your channel id (add the bot as a channel **admin**) |

Everything else has a working default — see `.env.example` for the full list
(`MIN_GRADE`, `MAX_TRADES_PER_DAY`, `SL_ATR_MULT`, `MAX_SPREAD_USD`, …).

## Run

```bash
python3 xauusd_smc_bot.py --check      # credentials, instrument, quote, bars, Telegram
python3 xauusd_smc_bot.py --dry-run    # full pipeline + alerts, no orders sent
python3 xauusd_smc_bot.py --once       # one scan, then exit
python3 xauusd_smc_bot.py              # the real loop, every 60s
python3 -m unittest discover -s tests  # 41 offline tests, no network needed
```

### Keep it running

```bash
nohup python3 xauusd_smc_bot.py >> xauusd_smc_bot.log 2>&1 &
```

or as a service (`/etc/systemd/system/xauusd-smc.service`):

```ini
[Unit]
Description=XAUUSD SMC bot
After=network-online.target

[Service]
WorkingDirectory=/path/to/Mylifeloading94
ExecStart=/usr/bin/python3 /path/to/Mylifeloading94/xauusd_smc_bot.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now xauusd-smc
journalctl -u xauusd-smc -f
```

---

## Risk controls (all enforced in code)

| Control | Default |
|---------|---------|
| Risk per trade | A+ 3% • A 2.5% • B 1.5% |
| Minimum grade traded | `A` (B setups are logged and skipped) |
| Open positions | 1 |
| Trades per day | 3 |
| Daily stop | 2 consecutive losses, or −6% |
| Weekly stop | −10% |
| Spread filter | skip above $0.50 |
| News blackout | ±15 min (see below) |
| Sessions | London 07:00–16:00, NY 12:00–21:00 UTC, weekdays |
| Lot cap | 10.0, plus a check that the rounded size cannot overshoot the budget |

State lives in `xauusd_smc_state.json`; every open, TP1 and close is appended to
`xauusd_smc_journal.jsonl` (your trade journal). Both survive restarts, so a
daily stop stays in force if you bounce the process.

### News calendar

Drop a `news_calendar.json` next to the bot and it is re-read every 5 minutes:

```json
[
  {"time": "2026-09-04T12:30:00Z", "title": "NFP",  "impact": "high"},
  {"time": "2026-09-10T12:30:00Z", "title": "CPI",  "impact": "high"},
  {"time": "2026-09-16T18:00:00Z", "title": "FOMC", "impact": "high"}
]
```

Without one, the bot conservatively blocks the classic US release slots
(12:30, 14:00, 18:00 UTC on weekdays). Set `NEWS_FALLBACK_BLACKOUT=false` to
turn that off, or point `NEWS_JSON_URL` at a feed in the same shape.

---

## Deliberate deviations from the strategy document

Two places where the code does something the document does not say literally.
Both are one environment variable away from the document's exact wording:

1. **Stop buffer** — the doc says 2–3 pips beyond the OB. The bot uses
   `max(2.5 pips, 0.25 × ATR(M15))`. This repo's own measured work
   (`honest_edge.py`) found tight swing stops were the single biggest leak, and
   that widening the stop beyond the sweep roughly doubled the win rate. Set
   `SL_ATR_MULT=0` for the literal version.
2. **`MIN_GRADE=A`** — the doc allows B setups at 1.5%. Since the request was
   for a high win rate, B (the "no HTF alignment / no fresh sweep" bucket) is
   off by default. Set `MIN_GRADE=B` to enable it.

Sizing follows the document exactly: for gold **1 pip = $1.00 of price** and one
lot pays **$10/pip**, so a 30-pip stop on $1,500 of risk gives 5.00 lots — the
doc's own worked example, asserted in the test-suite.

---

## Honest expectations

The strategy document's own backtest shows a **~44% win rate** — it makes money
from large winners, not from being right often. With TP1 at 2R that is the
expected shape, and losing streaks are normal. This repo's earlier honest-fill
work measured gold as the *weakest* instrument it tested (`honest_edge.py`:
45–50% WR, PF < 0.5, banned; `sniper_smc.py`: 43%). Those used different rules
on the same broker data, so treat this bot as an untested hypothesis until your
own forward test says otherwise:

**`--dry-run` → demo → live**, and gate live size on **profit factor > 1.2 over
40+ trades**. 3% risk at a 44% win rate implies ~20% drawdowns.

*Not financial advice. Trading involves substantial risk of loss.*
