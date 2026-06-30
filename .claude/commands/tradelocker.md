# TradeLocker API Skill

You are an expert at using the TradeLocker Public API. When invoked, help the user interact with TradeLocker's trading platform programmatically. Use the knowledge below to construct correct API calls, explain endpoints, write integration code, or execute trading workflows.

## Reference Documentation
Full API docs: https://public-api.tradelocker.com/docs/getting-started
AI-formatted index: https://public-api.tradelocker.com/llms.txt

---

## Base URLs

| Environment | Base URL |
|-------------|----------|
| Demo | `https://demo.tradelocker.com/backend-api` |
| Live | `https://live.tradelocker.com/backend-api` |

Always default to the **demo** environment unless the user explicitly confirms live trading.

---

## Authentication

TradeLocker uses JWT Bearer token authentication. Every request (except token generation) must include:

```
Authorization: Bearer {accessToken}
```

### Step 1 — Get Access Token

```http
POST /auth/jwt/token
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "yourpassword",
  "server": "OSP-DEMO"
}
```

**Response:**
```json
{
  "accessToken": "eyJ...",
  "refreshToken": "eyJ...",
  "expireDate": 1700000000000
}
```

### Step 2 — Refresh Token

```http
POST /auth/jwt/refresh
Content-Type: application/json

{
  "refreshToken": "eyJ..."
}
```

Returns a new `accessToken` without requiring credentials again.

### Step 3 — Get All Accounts

Retrieve account numbers (`accNum`) required for trade endpoints:

```http
GET /auth/jwt/all-accounts
Authorization: Bearer {accessToken}
```

**Response:**
```json
{
  "accounts": [
    {
      "id": 12345,
      "accNum": 1,
      "currency": "USD",
      "accountBalance": 10000.00
    }
  ]
}
```

---

## Key Identifiers

| Parameter | Description | Where to get it |
|-----------|-------------|-----------------|
| `accountId` | Unique account identifier per environment | `/auth/jwt/all-accounts` → `id` field |
| `accNum` | Sequential account number, required in headers for all `/trade/*` calls | `/auth/jwt/all-accounts` → `accNum` field |
| `routeId` | Either `TRADE` (orders/positions) or `INFO` (quotes/history) | `/trade/accounts/{accountId}/instruments` |
| `tradableInstrumentId` | Instrument identifier for placing orders | `/trade/accounts/{accountId}/instruments` |

### Required Header for All `/trade/*` Endpoints

```
accNum: {accNum}
```

---

## Market Data Endpoints

### Get Instruments

```http
GET /trade/accounts/{accountId}/instruments
Authorization: Bearer {accessToken}
accNum: {accNum}
```

Returns list of tradable instruments with their `tradableInstrumentId` and `routeId`.

### Get Quotes (Current Price)

```http
GET /trade/quotes
Authorization: Bearer {accessToken}
accNum: {accNum}

Query params:
  - tradableInstrumentId: number
  - routeId: "INFO"
```

### Get Historical Bars

```http
GET /trade/history
Authorization: Bearer {accessToken}
accNum: {accNum}

Query params:
  - tradableInstrumentId: number
  - routeId: "INFO"
  - startTime: ISO timestamp
  - endTime: ISO timestamp
  - resolution: "1" | "5" | "15" | "60" | "D" | "W"
```

### Get Daily Bar

```http
GET /trade/dailyBar
Authorization: Bearer {accessToken}
accNum: {accNum}

Query params:
  - tradableInstrumentId: number
  - routeId: "INFO"
```

---

## Account State

```http
GET /trade/accounts/{accountId}
Authorization: Bearer {accessToken}
accNum: {accNum}
```

Returns account balance, equity, margin, P&L, and open positions count.

---

## Order Management

### Place an Order

```http
POST /trade/accounts/{accountId}/orders
Authorization: Bearer {accessToken}
accNum: {accNum}
Content-Type: application/json

{
  "tradableInstrumentId": 1,
  "routeId": "TRADE",
  "type": "market",
  "side": "buy",
  "qty": 1.0,
  "stopLoss": 1.0800,
  "takeProfit": 1.1200,
  "validity": "GTC"
}
```

**Order types:** `market`, `limit`, `stop`, `stopLimit`
**Sides:** `buy`, `sell`
**Validity:** `GTC` (Good Till Cancel), `GTD` (Good Till Date), `IOC`, `FOK`

**Response includes `orderId`** — this becomes a `positionId` once filled (different value).

### Get Open Orders

```http
GET /trade/accounts/{accountId}/orders
Authorization: Bearer {accessToken}
accNum: {accNum}
```

### Modify an Order

```http
PATCH /trade/accounts/{accountId}/orders/{orderId}
Authorization: Bearer {accessToken}
accNum: {accNum}
Content-Type: application/json

{
  "qty": 2.0,
  "stopLoss": 1.0750,
  "takeProfit": 1.1300
}
```

### Cancel an Order

```http
DELETE /trade/accounts/{accountId}/orders/{orderId}
Authorization: Bearer {accessToken}
accNum: {accNum}
```

### Cancel All Orders

```http
DELETE /trade/accounts/{accountId}/orders
Authorization: Bearer {accessToken}
accNum: {accNum}
```

### Order History

```http
GET /trade/accounts/{accountId}/ordersHistory
Authorization: Bearer {accessToken}
accNum: {accNum}
```

Use this to find the `positionId` for a filled order — match on `orderId` and read `positionId`.

---

## Position Management

### Get Open Positions

```http
GET /trade/accounts/{accountId}/positions
Authorization: Bearer {accessToken}
accNum: {accNum}
```

### Close a Position

```http
DELETE /trade/accounts/{accountId}/positions/{positionId}
Authorization: Bearer {accessToken}
accNum: {accNum}
Content-Type: application/json

{
  "qty": 1.0
}
```

Omit `qty` to close the entire position.

### Modify a Position (SL/TP)

```http
PATCH /trade/accounts/{accountId}/positions/{positionId}
Authorization: Bearer {accessToken}
accNum: {accNum}
Content-Type: application/json

{
  "stopLoss": 1.0800,
  "takeProfit": 1.1200
}
```

### Close All Positions

```http
DELETE /trade/accounts/{accountId}/positions
Authorization: Bearer {accessToken}
accNum: {accNum}
```

---

## orderId vs positionId

These are **different values** despite representing related concepts:

1. `POST /orders` → broker accepts → returns `orderId`
2. Order is pending (limit/stop orders wait for price conditions; market orders fill immediately)
3. Order fills → status becomes `FILLED` → a **new** `positionId` is created (different number)
4. Filled order moves to `/ordersHistory`; new position appears in `/positions`

To map orderId → positionId: query `/ordersHistory` and find the matching record.

---

## Configuration

### Get Rate Limits & Field Specs

```http
GET /trade/config
Authorization: Bearer {accessToken}
accNum: {accNum}
```

Returns max request rates per route, allowed order operations per instrument, and field constraints.

### Trade Session Status

```http
GET /trade/session
Authorization: Bearer {accessToken}
accNum: {accNum}

Query params:
  - tradableInstrumentId: number
  - routeId: "TRADE"
```

---

## Bot & Subscription Management

### List Bots

```http
GET /trade/accounts/{accountId}/bots
Authorization: Bearer {accessToken}
accNum: {accNum}
```

### Create Subscription

```http
POST /trade/accounts/{accountId}/subscriptions
Authorization: Bearer {accessToken}
accNum: {accNum}
Content-Type: application/json

{
  "botId": "...",
  "tradableInstrumentId": 1,
  "routeId": "TRADE"
}
```

---

## Common Workflows

### Workflow: Open a Market Buy Position

```python
import requests

BASE = "https://demo.tradelocker.com/backend-api"

# 1. Authenticate
r = requests.post(f"{BASE}/auth/jwt/token", json={
    "email": "you@example.com",
    "password": "password",
    "server": "OSP-DEMO"
})
tokens = r.json()
access_token = tokens["accessToken"]
headers = {"Authorization": f"Bearer {access_token}"}

# 2. Get accounts
accounts = requests.get(f"{BASE}/auth/jwt/all-accounts", headers=headers).json()
account = accounts["accounts"][0]
account_id = account["id"]
acc_num = account["accNum"]
trade_headers = {**headers, "accNum": str(acc_num)}

# 3. Find instrument (e.g. EURUSD)
instruments = requests.get(
    f"{BASE}/trade/accounts/{account_id}/instruments",
    headers=trade_headers
).json()
eurusd = next(i for i in instruments["d"]["instruments"] if i["name"] == "EURUSD")
instrument_id = eurusd["tradableInstrumentId"]
route_id = next(r["id"] for r in eurusd["routes"] if r["type"] == "TRADE")

# 4. Place market order
order = requests.post(
    f"{BASE}/trade/accounts/{account_id}/orders",
    headers=trade_headers,
    json={
        "tradableInstrumentId": instrument_id,
        "routeId": route_id,
        "type": "market",
        "side": "buy",
        "qty": 0.01,
        "validity": "GTC"
    }
).json()
order_id = order["orderId"]

# 5. Find the resulting positionId
history = requests.get(
    f"{BASE}/trade/accounts/{account_id}/ordersHistory",
    headers=trade_headers
).json()
filled = next(o for o in history["d"]["ordersHistory"] if o["id"] == order_id)
position_id = filled["positionId"]
```

### Workflow: Close a Position

```python
requests.delete(
    f"{BASE}/trade/accounts/{account_id}/positions/{position_id}",
    headers=trade_headers
)
```

---

## Rate Limiting

- Each route has individual rate limits; query `/trade/config` to get current limits.
- Apply for the [TradeLocker Developer Program](https://tradelocker.typeform.com/devprogram) for elevated limits when building multi-user solutions.
- Use exponential backoff and respect `Retry-After` headers on 429 responses.

---

## Error Handling

| HTTP Status | Meaning |
|-------------|---------|
| 200/201 | Success |
| 400 | Bad request — check request body against `/trade/config` field specs |
| 401 | Unauthorized — token expired, refresh it |
| 403 | Forbidden — insufficient permissions or wrong environment |
| 404 | Resource not found |
| 429 | Rate limit hit — back off and retry |
| 500 | Server error — retry with backoff |

---

## Security Reminders

- Never commit credentials or tokens to source control.
- Store secrets in environment variables: `TRADELOCKER_EMAIL`, `TRADELOCKER_PASSWORD`, `TRADELOCKER_SERVER`.
- Always test on the **demo** environment before switching to live.
- Refresh tokens before expiry rather than re-authenticating from scratch.

---

## Chart Style — CONFIRMED LOCKED IN

All trade alert charts generated by `generate_chart()` in `trading_agent.py` must use this exact style. Do NOT change it without user instruction.

### Candles
| Element | Value |
|---------|-------|
| Background | `white` |
| Bull candle body | `#90bff9` (light blue) |
| Bear candle body | `#f48fb1` (light pink) |
| Wick | `black` |
| Body border | `black`, linewidth 0.5 |

### Scale & Lines
| Element | Value |
|---------|-------|
| Y-axis scale text | `#0000ff` (blue) |
| Level lines (Entry/SL/TP) | `black` |
| Entry line style | solid |
| SL / TP line style | dashed |
| TP1 line style | dotted |
| Grid | subtle grey `#e0e0e0`, y-axis only |

### TradingView Position Box (vertical rectangle, right side of chart)
The box sits just after the last candle (`box_x = n - 0.5`, width `n * 0.13`).  
Colors are the same regardless of direction — **blue = profit zone, red = loss zone**.

| Trade Direction | Top zone | Bottom zone |
|----------------|----------|-------------|
| **BUY / Long** | `#2962ff` blue (entry → TP2) | `#f23645` red (SL → entry) |
| **SELL / Short** | `#f23645` red (entry → SL) | `#2962ff` blue (TP2 → entry) |

- Opacity: `alpha=0.25` on both rectangles  
- Box edge color matches fill color  
- TP1 tick line drawn inside the profit zone at `alpha=0.7`  
- Labels placed to the right of the box (no background box)

### Header
- Top-left: pair + timeframe label, black, bold, size 13
- Top-right: `▲  LONG` in `#2962ff` or `▼  SHORT` in `#f23645`, bold, size 11

### No trend lines.  
Trend lines were removed. Do not re-add them.

---

## Entry Discipline — POST-MORTEM & RULES (learned from losing trades)

### What went wrong (2026-06-29/30)
Two trades sent to the channel lost because the agent **entered at market on the
1H close without a 15M trigger**:

| Trade | Entered at | 15M range pos | Outcome |
|-------|-----------|----------------|---------|
| EURUSD BUY 1.14258 | 1H close | **93%** (top of range) | SL hit −16.8p / −$55 |
| GBPUSD BUY 1.32468 | 1H close | 56% (mid) | went −$40 underwater |

Root causes:
1. **`entry = price`** — bought wherever price was, even at the top of the local range.
2. **15M was decorative** — only a +1 score, never gated the actual entry.
3. **Premium/Discount too loose** — passed at exactly 50% (no real edge).
4. **Correlation blind spot** — EURUSD + GBPUSD are both "short USD"; when the
   dollar bounced overnight they fell together. The old filter put them in
   different groups and allowed both.

### The fix — every entry must now clear `fifteen_min_entry()`
A trade is REJECTED unless ALL hold on the 15M timeframe:
1. **Location** — buys only in 15M discount (**≤40%** of last-40-bar range);
   sells only in premium (**≥60%**). Never chase the extreme.
2. **Not extended** — price within **2.0×ATR(15M)** of the 15M EMA20.
3. **Confirmation** — last closed 15M candle reacts in-direction
   (rejection wick ≥50% of body, or close through a fresh 15M FVG).
4. **SL anchored to the 15M swing** extreme + 2-pip buffer (tighter, better R:R).

### Other guards added
- **Premium/Discount** now needs a real edge: buy ≤45%, sell ≥55% (was bare 50%).
- **USD-exposure cap** (`usd_exposure_ok`): max **1** open same-direction-USD trade.
  Blocks stacking EURUSD+GBPUSD+AUDUSD all-long-EUR/short-USD at once.

### Standing rule
4H/1H confluence sets the **bias**; the **15M sets the entry**. High score is
necessary but NOT sufficient — no clean 15M trigger means no trade, no alert,
however good the higher-timeframe story looks.
