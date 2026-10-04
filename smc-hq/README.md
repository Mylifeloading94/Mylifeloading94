# SMC TRADING HQ — 3D AGENT WORLD

> **FOUR AI AGENTS. ONE MARKET INTELLIGENCE SYSTEM.**
> An interactive, comic-book-styled 3D city where four cooperating analysis agents live in their own buildings,
> hand structured JSON to one another, and — only after every validation passes — publish a signal to Telegram.

**Educational analysis — not financial advice.** The system never places trades. A *confidence score* measures how
many rule-based conditions are satisfied right now; it is **not** a probability of winning and no win rate is promised
anywhere in the app.

The visual style is an original, comic-book/video-game-inspired look (bold outlines, halftone, speech bubbles,
POW-style effects). It uses no characters, logos or artwork from any existing franchise.

---

## Quick start

```bash
cd smc-hq
npm install
npm run dev          # http://localhost:3000
```

No API keys, no database server: the app starts in **DEMO MODE** with simulated data (clearly labelled everywhere)
and a JSON-file database in `.data/`. Click **▶ RUN DEMO SIGNAL** (bottom-left) to watch a simulated XAUUSD setup travel
through all four agents; a Telegram *preview* appears (it is never sent).

Other scripts: `npm test` · `npm run typecheck` · `npm run build && npm start` · `npx tsx scripts/demo-cli.ts`
(runs the demo pipeline in the terminal and prints the Telegram preview).

## The world

| Building | Agent | What you see |
|---|---|---|
| **MARKET ANALYST** | multi-timeframe price action | operator in front of a giant holographic chart of **real** (provider) candles with entry zone / SL / TP overlays, orbiting candlesticks, buy/sell arrow; panel: pair, timeframes, bias, structure, liquidity, FVG |
| **NEWS INTELLIGENCE** | headlines, social, scheduled events | three floating news screens with scrolling headlines, currency glyphs, BREAKING banner + siren on high-impact news; panel: latest news, impact, currency, next event, countdown, sentiment |
| **SETUP HUNTER** | scoring & validation | rotating radar on the roof whose blips turn yellow (scanning) / red (rejected) / green (approved), a tall confidence meter; panel: pair scanning, setups found, rejected, current score, best setup |
| **SIGNAL COMMAND** | final validation & delivery | alert beacons, signal "burst", packet that flies Hunter → Command → the Telegram relay in the sky; panel: signals today, last signal, Telegram status, system status |

Orbit (drag), pan (right-drag), zoom (wheel). **Click a building** to fly into its control room (status, decision
summary, activity log, the exact JSON it hands to the next agent). Top navigation: WORLD · MARKET · NEWS · SETUPS ·
SIGNALS · PERFORMANCE · SETTINGS. The status bar shows MARKET DATA / NEWS / AGENTS / TELEGRAM honestly
(`DEMO`, `ONLINE`, `UNAVAILABLE`, `NOT CONFIGURED`, `CONNECTED`). A **2D MODE** button (and automatic fallback when
WebGL is unavailable or the screen is narrow) shows the same agents as plain cards.

## Going live

Copy `.env.example` to `.env` and fill what you have. **Secrets are read only in server code** (API routes /
`lib/*`); the browser receives booleans and labels, never keys (covered by a test).

| Variable | Purpose |
|---|---|
| `MARKET_DATA_API_KEY` | [Twelve Data](https://twelvedata.com) key → switches the whole app to **LIVE** mode |
| `NEWS_API_KEY` | [NewsAPI.org](https://newsapi.org) headlines |
| `X_API_KEY` | X (Twitter) API v2 **bearer token** for recent-search of central-bank/agency accounts (official API only, no scraping) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | signal delivery |
| `DATABASE_URL` | PostgreSQL; empty ⇒ JSON-file fallback in `DATA_DIR` |
| `DEMO_MODE=true` | force demo even if a market key exists |
| `TELEGRAM_WEBHOOK_SECRET`, `PUBLIC_APP_URL` | webhook for bot commands |
| `SCAN_INTERVAL_SECONDS` | optional server-side auto-scan (≥ 30) |

Mode rules (so data is never mixed): no market key ⇒ everything is DEMO. With a market key everything is LIVE; if the
news key is missing the news feed reports **UNAVAILABLE** and news risk becomes **UNKNOWN** (never demo headlines). If market
data cannot be fetched the UI says **MARKET DATA UNAVAILABLE** and no signal is generated.

### Database (PostgreSQL)

```bash
# 1. put DATABASE_URL=postgresql://user:pass@localhost:5432/smc in .env
npm run db:generate
npm run db:push        # creates the tables
npm run db:seed        # default settings + one DEMO pipeline pass (never fabricates results)
```
Tables: `signals`, `market_analyses`, `news_events`, `agent_activity`, `setup_scores`, `telegram_messages`, `settings`
(see `prisma/schema.prisma`). Without `DATABASE_URL` the same interface is served by a JSON file; `/api/health`
and Settings show which one is active. If `DATABASE_URL` is set but unreachable, the app logs the error and falls back
to the file store rather than crashing.

### Telegram

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to your bot (or add it to a group/channel as admin), then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` into `TELEGRAM_CHAT_ID`.
3. Restart `npm run dev`; Settings → **SEND TEST MESSAGE** (a clearly-labelled non-signal) verifies the link.
4. Optional bot commands (`/status /signals /lastsignal /pairs /pause /resume`) need a public HTTPS URL:
   set `PUBLIC_APP_URL` (e.g. a cloudflared/ngrok tunnel) and `TELEGRAM_WEBHOOK_SECRET`, then `npm run telegram:webhook`
   (`-- --delete` removes it). Only the configured chat id may issue commands.

Signals are sent **only** by Signal Command, **only** for LIVE signals, **after** the signal is stored. If Telegram is
down the signal is kept with `telegram_state = FAILED`. Demo signals are refused by `sendTelegramSignal()`.

## How a setup is judged

1. **Market Analyst** (D1/H4/H1/M15/M5): swings, BOS vs CHoCH/MSS (close-based — a wick is a sweep, not a break), equal
   highs/lows, liquidity sweeps (swing, EQH/EQL, PDH/PDL, PWH/PWL, Asian/London/NY ranges), FVG, order blocks, breaker
   blocks, premium/discount, fib of the post-sweep impulse, ATR regime, S/R. RSI and EMAs are *reported but not scored* —
   indicator agreement is not an independent confirmation.
2. **HTF bias** needs agreement (H4 counts double; a lone H4 trend stays *neutral*).
3. **Entry model**: sweep of the *opposing* liquidity → structure shift after it → unmitigated FVG/OB zone. Stop goes
   beyond the full manipulation wick; targets are real liquidity levels (R-multiples are used only when none exist and are
   flagged *projected*).
4. **Setup Hunter** scores 100 points (structure 20 · liquidity 15 · FVG/OB 15 · HTF alignment 15 · entry
   confirmation 10 · R:R 10 · session 5 · news 5 · volatility 5) and runs ten validations plus an
   *independent-confirmation* gate (≥ 4 of 5 groups). ≥ 90 PREMIUM, ≥ 85 VERY HIGH, ≥ 80 HIGH; below your minimum
   confidence (default 80) ⇒ rejected. R:R is measured zone-midpoint → TP2 (default minimum 1:2).
5. **Signal Command** re-checks the arithmetic itself, enforces daily/simultaneous limits (LIVE only), blocks
   duplicates, assigns `SMC-YYYY-NNNN` (`DEMO-…` for demo), stores, then sends.

News: HIGH/EXTREME releases inside your blackout window (15/30/60 min before, 15 min after; doubled for EXTREME) reject
the setup; HIGH within 4 h downgrades it. NewsAPI has no economic calendar, so add scheduled releases in
**Settings → Manual news events** to get blackouts in LIVE mode; without any calendar news risk is reported **UNKNOWN**.

## Performance & honesty

The Performance tab is computed from signals and outcomes actually recorded in the database — LIVE and DEMO are
separate tabs and never blended; with no closed signals every ratio shows “—”. Outcomes come from the tracker
(`TRACK OPEN SIGNALS` / auto-scan; conservative: stop wins a same-candle tie) or from manual entry in the Signals tab. R is derived from the
recorded levels and assumes exit at the highest target reached.

## Verified vs. not verified

Tested here (`npm test`, 53 tests + 3 Postgres tests): analysis engine, scoring/validation, limits, duplicate
prevention, the full demo pipeline (including 12 consecutive runs), statistics, tracker, Telegram formatting/commands/
send path against a **mocked** Bot API, provider request/response handling against **mocked** HTTP, secrets-not-exposed
checks, and the PostgreSQL store against a real PostgreSQL 16 (`TEST_DATABASE_URL=… npm test`).
**Not** verified: real Twelve Data / NewsAPI / X / Telegram accounts (no credentials were available) — the request
shapes follow their public docs, but expect to adjust for plan limits (Twelve Data’s free tier allows ~8 requests/min; a
12-pair × 5-timeframe scan needs 60 — use a paid plan, a smaller watchlist, or rely on the built-in caching).
The sessions are an approximation (UTC windows), and the structure/SMC rules are one explicit, heuristic reading of the
concepts — they are not backtested here and carry no performance claim.

## Docs

* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — modules, agent contract, message flow, data modes
* [`docs/API.md`](docs/API.md) — HTTP endpoints and event stream
