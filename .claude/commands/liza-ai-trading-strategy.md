# LIZA AI Trading Strategy — MintyTraders Multi-Bot ES Futures System

> Source: @LaythBanks | Platform: MintyTraders (app.mintytraders.com)
> Instruments: ES (E-mini S&P 500) primary | NQ, YM also supported
> Execution Layer: Tradecopia copy-trading across multiple prop-firm accounts

---

## System Overview

LIZA AI is an institutional-grade automated trading signal platform that runs **three
specialized bots simultaneously** on ES futures. Each bot uses a different edge — order flow
absorption, dark pool institutional prints, and Databento delta — so they are uncorrelated
and complement each other. All bots are **bidirectional** (long and short) and operate on
the ES (E-mini S&P 500 futures, ticker ES1!).

The bots execute on the **MintyTraders** platform and are copy-traded via **Tradecopia** to
multiple prop-firm funded accounts across providers like **Apex Trader Funding**, **Apex**,
and **Lucid Trading**.

---

## The Three Bots

### Bot 1: ES Iceberg Bot

**Edge:** Order-flow ABSORPTION + CONFLUENCE engine (v2)

**How it works:**
- Detects large iceberg (hidden) orders being absorbed in the ES order book
- Confirms the absorption anchor using **CVD (Cumulative Volume Delta) divergence** or
  **VWAP location** as confluence
- Bidirectional — takes both long and short trades depending on where absorption is
  detected relative to VWAP and CVD

**Trade Parameters:**
- Stop Loss: **4 points**
- Profit Target: **9 points** (2.25 R:R)
- Time Stop: **45 minutes** (auto-closes trade if neither stop nor target is hit)
- Max Trades Per Day: **4**
- Active Trading Window: **08:30 – 14:30 CT** (Central Time)

**Performance Stats:**
- Win Rate: **49%**
- Profit Factor: **1.36×**
- Estimated Monthly P&L: **~$850 per contract**
- Backtest Profit Factor: 1.36 | Out-of-Sample PF: 1.60

**Key Insight:** This bot wins less than half the time but is profitable because the
target (9 pts) is more than double the stop (4 pts). The edge comes from identifying
institutional absorption at key VWAP levels where large hidden orders are being filled.

---

### Bot 2: DarkPrint Bot

**Edge:** SPY dark-pool institutional prints → ES momentum

**How it works:**
- Monitors **SPY dark pool** prints in real-time via QD (Quant Data) equity_prints feed
- Filters for **$5M+ prints** that are **ASK/BID aggressed only** (not mid-price prints)
- When a large institutional dark pool print hits on the ASK side (aggressive buying) or
  BID side (aggressive selling) in SPY, it translates that directional pressure into an
  ES futures trade
- The logic: massive institutional dark pool orders in SPY signal directional conviction
  that will flow into ES futures

**Trade Parameters:**
- Stop Loss: **4 points**
- Profit Target: **6 points** (1.5 R:R)
- Time Stop: **30 minutes**
- Version: **DARK-LINK v1**

**Performance Stats:**
- Win Rate: **50%**
- Profit Factor: **1.38×**
- Estimated Monthly P&L: **~$1,500 per contract**

**Key Insight:** This bot uses an information edge — it reads institutional dark pool
activity in SPY (where the real size trades happen off-exchange) and front-runs the
resulting momentum in ES futures. The 1.5:1 reward-to-risk with 50% win rate creates a
positive expectancy.

---

### Bot 3: Apex Bot

**Edge:** Prop-pass strategy (Variant A) — Databento delta + VWAP bias

**How it works:**
- Uses **Databento** real-time market data feed for institutional-level order flow
- Trades based on **sign-only delta** (net aggressive buying vs selling pressure) combined
  with **VWAP bias** (whether price is above or below VWAP)
- Bidirectional with **2 ES contracts** per trade
- Specifically designed for **passing prop firm evaluations** with its conservative risk
  parameters and high win rate

**Trade Parameters:**
- Stop Loss: **8 points**
- Profit Target: **8 points** (1:1 R:R)
- Max Trades Per Day: **4**
- Daily P&L Caps: **±$900** (hard stop on both profit and loss per day)
- Contracts: **2 ES**

**Performance Stats:**
- Win Rate: **91%** (90.9% across 17 ESM6 backtest sessions)
- Profit Factor: **3.12×**
- Estimated Monthly P&L: **~$2,400 per contract**
- Status: Building live track record

**Key Insight:** This bot is the prop-firm account passer. The 91% win rate with ±$900
daily caps means it's designed to steadily grow accounts without triggering prop firm
drawdown limits. The 1:1 R:R with a 91% win rate is an exceptional edge driven by reading
Databento institutional delta at VWAP levels.

---

## Combined System Performance

When all three bots run simultaneously on a single contract each:

| Metric | Value |
|---|---|
| Combined Est. Monthly P&L | ~$4,750 per contract |
| Daily Trades | Up to 12 (4 per bot) |
| Composite Win Rate | ~53% (last 30 days live) |
| 30-Day Total P&L (live) | +$30,910 |
| Sample Daily P&L | +$1,112.50 (13 trades, 8W/5L, 62% WR) |
| Avg Win | +$277 |
| Avg Loss | -$220 |

---

## Execution & Infrastructure Stack

### Signal Platform
- **MintyTraders** (app.mintytraders.com)
- Strategies tab → toggle each bot Active with contract count
- Dashboard shows: Today's P&L, Open Trades, Win Rate (30-day), Active Accounts, Total P&L (30D)
- Navigation: Dashboard | Accounts | Trades | Strategies | Live Bots | Settings | Support | Admin

### Copy-Trading Layer
- **Tradecopia** — mirrors all MintyTraders bot signals across connected brokerage accounts
- Supports grouping multiple prop firm accounts under one copy profile
- Daily P&L aggregated across all accounts in Tradecopia dashboard

### Prop Firm Accounts
- **Apex Trader Funding** — primary prop firm provider
- **Apex** — secondary accounts
- **Lucid Trading** — additional funded accounts
- Example setup: **9 accounts**, **$455,095 total balance** across all prop firms
- Sample daily P&L across all accounts: **+$4,242.18**

### Discord Notifications (LIZA AI Bot)
The system posts daily recaps to Discord via the LIZA AI bot with this format:

```
🔥 Daily Recap — [Day], [Date]

📈 Performance
Total P&L: $+[amount]
Win Rate: [%] ([W]W / [L]L)
Avg Win: $+[amount] | Avg Loss: $-[amount]

🕐 Trades ([count])
🟢 [time] [bot_name] [LONG/SHORT] ES1! → $+[amount]
🔴 [time] [bot_name] [LONG/SHORT] ES1! → $-[amount]
...

LIZA AI Trading • MintyTraders • [recap_time]
```

---

## Strategy Logic Summary

### Why Three Bots?

Each bot captures a **different edge** in the ES futures market:

1. **Iceberg Bot** — Reads the visible order book for hidden (iceberg) institutional
   absorption at key technical levels (VWAP, CVD divergence zones). This is a
   **microstructure** edge.

2. **DarkPrint Bot** — Reads the invisible order book (dark pools) for massive
   institutional prints in SPY and translates that into ES momentum trades. This is an
   **information asymmetry** edge.

3. **Apex Bot** — Reads real-time institutional delta via Databento at VWAP levels for
   high-probability directional plays. This is a **statistical** edge designed for
   consistent account growth.

Because these edges are **uncorrelated** (order book microstructure vs dark pool prints
vs Databento delta), the system diversifies risk across signal types. When one bot has
a losing streak, the others can compensate.

### Core Concepts Used

- **Order Flow Absorption** — Large hidden orders absorbing aggressive market orders
  at a price level, signaling institutional accumulation/distribution
- **CVD (Cumulative Volume Delta)** — Running total of aggressive buys minus aggressive
  sells; divergence from price signals hidden institutional activity
- **VWAP (Volume Weighted Average Price)** — Institutional benchmark price; bots use
  position relative to VWAP as directional bias
- **Dark Pool Prints** — Large institutional trades ($5M+) executed off-exchange in dark
  pools; direction (ASK vs BID aggressed) signals institutional intent
- **Databento Delta** — Real-time institutional-level order flow data; sign-only delta
  shows net aggressive buying vs selling
- **Time Stops** — Automatic exit after a set time (30-45 min) to avoid holding through
  low-conviction drift
- **Daily P&L Caps (±$900)** — Hard daily limits to protect prop-firm accounts from
  drawdown violations

### Risk Management Principles

1. **Fixed point stops** on every trade (4-8 pts depending on bot)
2. **Time-based exits** prevent holding losers through dead zones
3. **Daily trade caps** (max 4 per bot) prevent overtrading
4. **Daily P&L caps** (Apex Bot ±$900) prevent blowing funded accounts
5. **Session-only trading** — Iceberg Bot only trades 08:30-14:30 CT (high-liquidity
   US session hours)
6. **Multi-account diversification** — spread across 9+ prop firm accounts so a single
   account issue doesn't affect the whole operation

---

## How to Replicate This Setup

### Step 1: Get Prop Firm Accounts
- Sign up for funded accounts at Apex Trader Funding, Apex, and/or Lucid Trading
- Start with evaluation accounts; use the Apex Bot's high win rate to pass evaluations

### Step 2: Set Up MintyTraders
- Go to mintytraders.com → Get Started
- Connect your prop firm accounts
- Navigate to the **Strategies** tab
- Activate all three bots: ES Iceberg Bot, DarkPrint Bot, Apex Bot
- Set contract count (start with 1 per bot)

### Step 3: Configure Tradecopia Copy-Trading
- Set up Tradecopia to mirror MintyTraders signals across all your prop firm accounts
- Link each prop firm brokerage account to your Tradecopia profile
- Verify copy-trading is active and signals are being replicated

### Step 4: Monitor via Discord
- Join the LIZA AI Discord for daily recaps
- Monitor the daily P&L summaries and individual trade breakdowns
- Review the MintyTraders dashboard for real-time performance metrics

### Step 5: Scale
- Once accounts are funded and profitable, add more prop firm accounts
- Increase contract count per bot as your funded balance grows
- The system scales linearly — more accounts × more contracts = more profit potential

---

## Key Metrics to Track

- **Win Rate per bot** (target: Iceberg ~49%, DarkPrint ~50%, Apex ~91%)
- **Profit Factor per bot** (target: Iceberg 1.36×, DarkPrint 1.38×, Apex 3.12×)
- **Daily P&L** across all accounts (Tradecopia dashboard)
- **30-day rolling P&L** (MintyTraders dashboard)
- **Number of active accounts** and total funded balance
- **Drawdown per account** — critical for maintaining prop firm compliance

---

## Platform Links

- MintyTraders: https://mintytraders.com / https://app.mintytraders.com
- Tradecopia: https://tradecopia.com
- Content by: @LaythBanks (Instagram)
- Instruments: ES (E-mini S&P 500), NQ (E-mini Nasdaq), YM (E-mini Dow)
- Status: LIVE — Active since March 2026, 14+ active client accounts
