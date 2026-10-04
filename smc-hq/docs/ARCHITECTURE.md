# Architecture

```
 MARKET DATA ─► MARKET ANALYST ─► (market.analysis JSON)
                                      │
 NEWS / SOCIAL ─► NEWS INTELLIGENCE ─►│ (news.intel JSON)
                                      ▼
                               SETUP HUNTER ── score + 10 validations ──► (setup.approved JSON)
                                                                              │
                                                                              ▼
                                                                      SIGNAL COMMAND ─► DB ─► TELEGRAM
                                                                              │
                              SSE (/api/events) ◄──── in-process event bus ◄──┘ → 3D world animations
```

## Layers

| Path | Responsibility |
|---|---|
| `types/` | zod schemas = the *contracts* between agents (snake_case JSON), settings, signal model |
| `lib/analysis/` | pure functions: indicators, resampling, swings/structure, FVG/OB/breaker, liquidity & sweeps, sessions, the multi-timeframe `buildMarketAnalysis` |
| `lib/market/` | `MarketDataProvider` interface; `TwelveDataProvider` (live), `DemoMarketProvider` (scripted + seeded random walks) |
| `lib/news/`, `lib/social/` | `NewsProvider` / `SocialFeedProvider` interfaces; NewsAPI, X API v2, demo and "unavailable" implementations; headline classification and per-pair blackout logic |
| `lib/scoring/` | the transparent 100-point rubric and the ten validations |
| `lib/risk/` | settings persistence/validation, daily/simultaneous limits, duplicate detection |
| `lib/agents/` | `BaseAgent` + the four agents |
| `lib/telegram/` | `TelegramProvider`, message formatter, `sendTelegramSignal()`, bot commands |
| `lib/database/` | `Store` interface; `PrismaStore` (PostgreSQL) and `FileStore` (zero-setup fallback) |
| `lib/pipeline.ts` | orchestration (`runScan`, `runDemoSignal`) |
| `lib/events/bus.ts`, `lib/state.ts` | typed pub/sub + runtime snapshot (agent status, latest outputs, pause flag) |
| `app/api/*` | route handlers — the only place server config is touched besides `lib/*` |
| `components/` | `3d/` (React Three Fiber scene), `dashboard/` views, `agents/` control room, `charts/`, `telegram/`, `ui/` |

## Agent contract (`lib/agents/base.ts`)

Every agent has an `inputSchema`, an `outputSchema`, a status (`idle|working|error|paused|offline`), timestamps,
per-agent log (also persisted), retry with exponential backoff (default 3 attempts; schema failures are not retried) and
a one-line **reasoning summary made of decision factors only** — no chain-of-thought is stored or shown.
Agents never touch each other's state: they receive validated JSON and return validated JSON, and the pipeline publishes
those payloads on the bus.

## Data modes

`config.mode` is `LIVE` only when `MARKET_DATA_API_KEY` is set and `DEMO_MODE` is not `true`; every analysis, news
report, evaluation and signal carries `data_mode`. Demo and live records are stored in the same tables but are always
filtered by mode (statistics, limits, duplicates, Telegram). Backtest data is not mixed in anywhere.

The demo market is deterministic: EURUSD…AUDJPY are seeded regime-switching random walks (the engine usually rejects
them — that is intentional), while XAUUSD follows a scripted *sweep → MSS → FVG* path rendered into M5 candles and
resampled to M15/H1/H4/D1. **Nothing in the report is hard-coded** — the analysis engine has to detect every element
in those candles. `RUN DEMO SIGNAL` shifts the simulated clock a little each time so signals are distinct.

## Real-time

`GET /api/events` is a Server-Sent-Events stream of bus events (`agent.status`, `market.analysis`, `news.intel`,
`hunter.progress`, `setup.evaluated`, `setup.approved`, `signal.created`, `telegram.preview|sent|failed`, …). The browser
reduces them into ephemeral animation state (`components/useWorld.ts`) and also polls `/api/state` every 6 s as the
source of truth. The bus is in-process: run a single server instance (or put a broker behind `emit/subscribe`).

## Security notes

* Secrets only in `lib/config.ts` (server). A test fails if client code imports config, env or the database layer.
* Mutating endpoints (`/api/settings`, `/api/pipeline/scan`, `/api/signals/*`, `/api/demo/*`) have **no authentication** —
  this is a local tool. Put it behind your own auth/reverse proxy before exposing it.
* The Telegram webhook verifies `X-Telegram-Bot-Api-Secret-Token` (when configured) and the sender's chat id.
* Provider errors are sanitised so URLs containing the bot token are never logged or returned.
