# HTTP API

All routes are Node-runtime route handlers under `/api`. JSON in, JSON out. No auth (local tool — see ARCHITECTURE).

| Method & path | Description |
|---|---|
| `GET /api/health` | mode, active database (`postgres`/`file`) + row counts, which integrations are configured (booleans only) |
| `GET /api/state` | full snapshot: mode, system status, agent snapshots (status, summary, logs), latest analyses/news/hunter report, signals, settings, recent bus events |
| `GET /api/events` | **SSE** stream of bus events `{id, ts, type, from, to, payload}` |
| `POST /api/pipeline/scan` | run one full scan of the watchlist (LIVE if configured, else DEMO). Responds `{mode, skipped, scanned, failures, approved, signals[], best, tracking}` |
| `POST /api/demo/run-signal` | body `{blackout?: boolean}`. Simulated XAUUSD run (~5 s, staged). Returns analysis, evaluation (score breakdown + checks), signal and `telegram_preview`; `telegram_sent` is always `false` |
| `GET/PUT /api/settings` | risk settings: `risk_per_trade` (0.25/0.5/1/2), `max_daily_signals`, `max_simultaneous_signals`, `min_rr`, `min_confidence` (70–100), `news_blackout_minutes` (15/30/60), `watchlist` (6-letter symbols), `manual_events[]`. `422` with a message on invalid input |
| `GET /api/signals?mode=LIVE\|DEMO&limit=` | stored signals (newest first) |
| `PATCH /api/signals/{signalId}` | `{status}` ∈ PENDING, ACTIVE, TP1, TP2, TP3, STOPPED, EXPIRED, CANCELLED — records an outcome; `result_r` is derived from the stored levels |
| `POST /api/signals/track` | evaluates open LIVE signals against provider candles (LIVE provider required) |
| `GET /api/performance?mode=LIVE\|DEMO` | statistics from recorded signals only (nulls when there is no data) |
| `GET /api/market/{pair}?tf=D1\|H4\|H1\|M15\|M5&count=` | candles from the active provider with `data_mode`; `503 MARKET DATA UNAVAILABLE` on provider failure |
| `GET /api/news` | latest News Intelligence report |
| `GET /api/telegram/status` | `CONNECTED \| NOT_CONFIGURED \| ERROR` (calls `getMe`, cached 60 s) |
| `POST /api/telegram/test` | sends a labelled test message (not a signal) |
| `POST /api/telegram/webhook` | Telegram → app. Header `X-Telegram-Bot-Api-Secret-Token` checked if `TELEGRAM_WEBHOOK_SECRET` is set |

## Inter-agent JSON (zod schemas in `types/index.ts`)

`MarketAnalysis` → `NewsIntel` → `HunterReport { evaluations[], approved: ApprovedSetup[] }` → `SignalCommandOutput`.

```jsonc
// ApprovedSetup (Setup Hunter → Signal Command)
{ "pair": "XAUUSD", "timestamp": "…", "data_mode": "DEMO", "direction": "long", "bias": "bullish",
  "market_structure": "bullish", "liquidity_event": "sell_side_sweep", "fvg": true,
  "setup_type": "Sell-side Liquidity Sweep + MSS + FVG + Order Block",
  "entry_zone": {"low": 3340.37, "high": 3344.59}, "stop_loss": 3336.54, "take_profits": [3345.77, 3367.64, 3394.79],
  "risk_reward": 4.24, "news_risk": "low", "confidence_score": 97, "grade": "PREMIUM",
  "score_breakdown": {"market_structure": 20, "liquidity": 14, "fvg_ob": 13, "htf_alignment": 15, "entry_confirmation": 10,
                      "risk_reward": 10, "session": 5, "news": 5, "volatility": 5},
  "confirmations": ["H4 bullish structure", "…"], "technical_reasoning": "…", "news_reasoning": "…", "fingerprint": "XAUUSD|long|…" }
```
