//+------------------------------------------------------------------+
//|                                       XAU_ScalpIntraday_EA.mq5   |
//|                                                  Mylifeloading94 |
//|                                                                  |
//| Dual-engine XAUUSD Expert Advisor                                |
//|   SCALP    : bias M5  -> entry M1                                |
//|   INTRADAY : bias H4  -> entry H1                                |
//|                                                                  |
//| Setup  : higher-TF trend (EMA50/200 + ADX) -> pullback into the  |
//|          entry-TF EMA zone -> momentum break candle (optional    |
//|          liquidity sweep).                                       |
//| Exits  : 3 legs per setup                                        |
//|          leg 1 -> TP1 (1R)                                       |
//|          leg 2 -> TP2 (nearest liquidity pool, or 2R)            |
//|          leg 3 -> runner (trailed, optional far TP)              |
//|          SL -> breakeven+lock after 1R, then ATR-adaptive        |
//|          trailing stop clamped between 25 and 60 pips.           |
//| Safety : % risk sizing, spread filter, session filter, USD news  |
//|          blackout, daily loss limit, max trades/day, consecutive |
//|          loss stop, Friday close.                                |
//|                                                                  |
//| 1 pip on gold = 0.10 (10 cents). 25 pips = $2.50 price move.     |
//+------------------------------------------------------------------+
#property copyright "Mylifeloading94"
#property version   "1.00"
#property description "XAUUSD scalping (M5/M1) + intraday (H4/H1) EA."
#property description "Multi-target entries, breakeven after TP1, ATR trailing stop 25-60 pips."

#include <Trade/Trade.mqh>

//==================================================================== inputs
input group "=== General ==="
input double InpPipSize         = 0.10;  // Pip size in price (gold: 0.10)
input double InpMaxSpreadPips   = 5.0;   // Max spread to open a trade (pips)
input int    InpSlippagePoints  = 30;    // Max slippage (points)
input bool   InpShowDashboard   = true;  // Show on-chart dashboard

input group "=== Account protection ==="
input double InpMaxDailyLossPct  = 3.0;  // Stop for the day after this % loss (0 = off)
input bool   InpCloseOnDailyLoss = true; // Close this EA's trades when daily loss is hit
input int    InpFridayNoNewHour  = 18;   // Friday: no new trades from this server hour (0 = off)
input int    InpFridayCloseHour  = 21;   // Friday: close all trades at this server hour (0 = off)

input group "=== News filter (live/demo only, not in tester) ==="
input bool   InpUseNews       = true;    // Block entries around high-impact USD news
input int    InpNewsBeforeMin = 30;      // Minutes before news
input int    InpNewsAfterMin  = 30;      // Minutes after news

input group "=== Signal settings (both engines) ==="
input int    InpBiasFastEMA     = 50;    // Bias TF fast EMA
input int    InpBiasSlowEMA     = 200;   // Bias TF slow EMA
input int    InpADXPeriod       = 14;    // Bias TF ADX period
input double InpMinADX          = 20.0;  // Min ADX on bias TF (trend strength)
input int    InpEntryFastEMA    = 21;    // Entry TF fast EMA (pullback zone)
input int    InpEntrySlowEMA    = 50;    // Entry TF slow EMA
input int    InpATRPeriod       = 14;    // Entry TF ATR period
input int    InpRSIPeriod       = 14;    // Entry TF RSI period
input double InpRSIMaxLong      = 75.0;  // Long only if RSI below (short uses 100 - this)
input double InpMinBodyRatio    = 0.5;   // Trigger candle body / range minimum
input int    InpPullbackBars    = 6;     // Bars to look back for the pullback
input bool   InpRequireSweep    = false; // Require liquidity sweep (fewer, cleaner trades)
input int    InpSweepLookback   = 10;    // Bars defining the liquidity that must be swept
input int    InpSLStructureBars = 5;     // SL beyond swing of last N bars
input double InpSLBufferATR     = 0.3;   // Extra SL buffer (x ATR)
input double InpSLMinATR        = 1.0;   // SL at least this many ATR away
input int    InpTargetLookback  = 50;    // Bars to search for TP2 liquidity

input group "=== Trade management ==="
input double InpBETriggerR    = 1.0;     // Move SL to breakeven at this R profit
input double InpBELockPips    = 3.0;     // Pips locked in at breakeven
input double InpTrailStartR   = 1.0;     // Start trailing at this R profit
input double InpTrailStepPips = 5.0;     // Min SL improvement per modification (pips)

input group "=== SCALP engine (bias M5 -> entry M1) ==="
input bool            InpScalpOn          = true;      // Enable scalp engine
input ENUM_TIMEFRAMES InpScalpBiasTF      = PERIOD_M5; // Bias timeframe
input ENUM_TIMEFRAMES InpScalpEntryTF     = PERIOD_M1; // Entry timeframe
input bool            InpScalpH1Filter    = true;      // Also require H1 trend agreement
input double          InpScalpRiskPct     = 0.5;       // Risk per setup (% equity, all legs)
input double          InpScalpSLMinPips   = 30;        // Min SL (pips)
input double          InpScalpSLMaxPips   = 120;       // Max SL (pips) - wider setups skipped
input double          InpScalpTP1R        = 1.0;       // TP1 (R)
input double          InpScalpTP2R        = 2.0;       // TP2 fallback (R)
input double          InpScalpRunnerR     = 4.0;       // Runner hard TP (R, 0 = none)
input double          InpScalpSplit1      = 50;        // Volume % leg 1
input double          InpScalpSplit2      = 30;        // Volume % leg 2
input double          InpScalpSplit3      = 20;        // Volume % leg 3 (runner)
input double          InpScalpTrailMin    = 25;        // Trail distance min (pips)
input double          InpScalpTrailMax    = 40;        // Trail distance max (pips)
input double          InpScalpTrailATR    = 1.5;       // Trail distance = ATR x this (clamped)
input int             InpScalpStartHour   = 9;         // Session start (server hour)
input int             InpScalpEndHour     = 20;        // Session end (server hour)
input int             InpScalpMaxPerDay   = 6;         // Max setups per day
input int             InpScalpMaxConsecL  = 3;         // Stop after N losing setups in a row
input ulong           InpScalpMagic       = 26100;     // Magic number

input group "=== INTRADAY engine (bias H4 -> entry H1) ==="
input bool            InpDayOn            = true;      // Enable intraday engine
input ENUM_TIMEFRAMES InpDayBiasTF        = PERIOD_H4; // Bias timeframe
input ENUM_TIMEFRAMES InpDayEntryTF       = PERIOD_H1; // Entry timeframe
input double          InpDayRiskPct       = 1.0;       // Risk per setup (% equity, all legs)
input double          InpDaySLMinPips     = 100;       // Min SL (pips)
input double          InpDaySLMaxPips     = 500;       // Max SL (pips) - wider setups skipped
input double          InpDayTP1R          = 1.0;       // TP1 (R)
input double          InpDayTP2R          = 2.0;       // TP2 fallback (R)
input double          InpDayRunnerR       = 4.0;       // Runner hard TP (R, 0 = none)
input double          InpDaySplit1        = 40;        // Volume % leg 1
input double          InpDaySplit2        = 30;        // Volume % leg 2
input double          InpDaySplit3        = 30;        // Volume % leg 3 (runner)
input double          InpDayTrailMin      = 40;        // Trail distance min (pips)
input double          InpDayTrailMax      = 60;        // Trail distance max (pips)
input double          InpDayTrailATR      = 1.0;       // Trail distance = ATR x this (clamped)
input int             InpDayStartHour     = 3;         // Session start (server hour)
input int             InpDayEndHour       = 21;        // Session end (server hour)
input int             InpDayMaxPerDay     = 2;         // Max setups per day
input int             InpDayMaxConsecL    = 2;         // Stop after N losing setups in a row
input ulong           InpDayMagic         = 26200;     // Magic number

//==================================================================== types
struct Engine
  {
   string            name;
   string            tag;
   bool              enabled;
   ulong             magic;
   ENUM_TIMEFRAMES   biasTF;
   ENUM_TIMEFRAMES   entryTF;
   bool              useH1Filter;
   double            riskPct;
   double            slMinPips;
   double            slMaxPips;
   double            tp1R;
   double            tp2R;
   double            runnerR;
   double            split[3];
   double            trailMinPips;
   double            trailMaxPips;
   double            trailATR;
   int               startHour;
   int               endHour;
   int               maxPerDay;
   int               maxConsecLoss;
   // handles
   int               hBiasFast;
   int               hBiasSlow;
   int               hADX;
   int               hFast;
   int               hSlow;
   int               hATR;
   int               hRSI;
   // state
   datetime          lastBar;
   int               bias;
   int               setupsToday;
   int               consecLoss;
   string            status;
  };

CTrade   trade;
Engine   E[2];
int      g_hH1Fast = INVALID_HANDLE;
int      g_hH1Slow = INVALID_HANDLE;
datetime g_newsCheckedAt = 0;
bool     g_newsBlock = false;

const string GV_PREFIX = "XAUB_";

//==================================================================== helpers
double Pip(double pips) { return pips * InpPipSize; }

double Buf(int handle, int buffer, int shift)
  {
   double a[1];
   if(handle == INVALID_HANDLE || CopyBuffer(handle, buffer, shift, 1, a) != 1)
      return EMPTY_VALUE;
   return a[0];
  }

double NP(double price)
  {
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0)
      ts = _Point;
   return NormalizeDouble(MathRound(price / ts) * ts, _Digits);
  }

double NormLot(double v)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0)
      step = 0.01;
   v = MathFloor(v / step + 1e-9) * step;
   if(v < mn)
      return 0.0;
   return NormalizeDouble(MathMin(v, mx), 2);
  }

double LowestLow(const MqlRates &r[], int from, int count)
  {
   double v = DBL_MAX;
   for(int i = from; i < from + count && i < ArraySize(r); i++)
      v = MathMin(v, r[i].low);
   return v;
  }

double HighestHigh(const MqlRates &r[], int from, int count)
  {
   double v = -DBL_MAX;
   for(int i = from; i < from + count && i < ArraySize(r); i++)
      v = MathMax(v, r[i].high);
   return v;
  }

bool InSession(int startHour, int endHour, int hour)
  {
   if(startHour == endHour)
      return true;
   if(startHour < endHour)
      return hour >= startHour && hour < endHour;
   return hour >= startHour || hour < endHour;   // wraps midnight
  }

// a is a better stop than b for direction dir
bool BetterSL(int dir, double a, double b)
  {
   if(b == 0.0)
      return true;
   return dir * (a - b) > 0;
  }

string GVR(ulong magic, long sid)
  {
   return GV_PREFIX + "R_" + IntegerToString((long)magic) + "_" + IntegerToString(sid);
  }

// comment format: TAG|setupId|leg
bool ParseComment(string c, long &sid, int &leg)
  {
   string parts[];
   if(StringSplit(c, StringGetCharacter("|", 0), parts) != 3)
      return false;
   sid = StringToInteger(parts[1]);
   leg = (int)StringToInteger(parts[2]);
   return sid > 0 && leg >= 1 && leg <= 3;
  }

int EngineByMagic(ulong magic)
  {
   for(int i = 0; i < 2; i++)
      if(E[i].magic == magic)
         return i;
   return -1;
  }

bool SetupOpen(ulong magic, long sid)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      long s;
      int leg;
      if(ParseComment(PositionGetString(POSITION_COMMENT), s, leg) && s == sid)
         return true;
     }
   return false;
  }

int OpenPositions(ulong magic)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == magic)
         n++;
     }
   return n;
  }

void CloseAll(ulong magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || (ulong)PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      if(!trade.PositionClose(t))
         Print("Close failed #", t, " ", trade.ResultRetcodeDescription());
     }
  }

void CloseAllOurs()
  {
   for(int i = 0; i < 2; i++)
      CloseAll(E[i].magic);
  }

//==================================================================== day stats
long DayKey() { return (long)(TimeCurrent() / 86400); }

double DayStartBalance()
  {
   string n = GV_PREFIX + "DAY_" + IntegerToString(DayKey());
   if(!GlobalVariableCheck(n))
      GlobalVariableSet(n, AccountInfoDouble(ACCOUNT_BALANCE));
   return GlobalVariableGet(n);
  }

double DayPnLPct()
  {
   double start = DayStartBalance();
   if(start <= 0)
      return 0.0;
   return (AccountInfoDouble(ACCOUNT_EQUITY) - start) / start * 100.0;
  }

bool DailyLossHit()
  {
   if(InpMaxDailyLossPct <= 0)
      return false;
   string blk = GV_PREFIX + "BLK_" + IntegerToString(DayKey());
   if(GlobalVariableCheck(blk))
      return true;
   if(DayPnLPct() <= -InpMaxDailyLossPct)
     {
      GlobalVariableSet(blk, 1);
      Print("Daily loss limit hit (", DoubleToString(DayPnLPct(), 2), "%). No more trades today.");
      if(InpCloseOnDailyLoss)
         CloseAllOurs();
      return true;
     }
   return false;
  }

// setups opened today and current losing streak (closed setups only)
void TodayStats(Engine &e)
  {
   e.setupsToday = 0;
   e.consecLoss  = 0;
   datetime now = TimeCurrent();
   datetime dayStart = now - (now % 86400);
   if(!HistorySelect(dayStart, now + 60))
      return;

   long   posIds[], posSid[], sids[];
   double nets[];
   int total = HistoryDealsTotal();

   for(int i = 0; i < total; i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0 || HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol)
         continue;
      if((ulong)HistoryDealGetInteger(d, DEAL_MAGIC) != e.magic)
         continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;
      long sid;
      int leg;
      if(!ParseComment(HistoryDealGetString(d, DEAL_COMMENT), sid, leg))
         continue;
      int np = ArraySize(posIds);
      ArrayResize(posIds, np + 1);
      ArrayResize(posSid, np + 1);
      posIds[np] = HistoryDealGetInteger(d, DEAL_POSITION_ID);
      posSid[np] = sid;
      bool known = false;
      for(int k = 0; k < ArraySize(sids); k++)
         if(sids[k] == sid)
            known = true;
      if(!known)
        {
         int ns = ArraySize(sids);
         ArrayResize(sids, ns + 1);
         ArrayResize(nets, ns + 1);
         sids[ns] = sid;
         nets[ns] = HistoryDealGetDouble(d, DEAL_COMMISSION);
        }
     }
   e.setupsToday = ArraySize(sids);

   for(int i = 0; i < total; i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0)
         continue;
      long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;
      long pid = HistoryDealGetInteger(d, DEAL_POSITION_ID);
      for(int p = 0; p < ArraySize(posIds); p++)
        {
         if(posIds[p] != pid)
            continue;
         for(int k = 0; k < ArraySize(sids); k++)
            if(sids[k] == posSid[p])
               nets[k] += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP)
                          + HistoryDealGetDouble(d, DEAL_COMMISSION);
         break;
        }
     }

   for(int k = 0; k < ArraySize(sids); k++)
     {
      if(SetupOpen(e.magic, sids[k]))
         continue;
      if(nets[k] < 0)
         e.consecLoss++;
      else
         e.consecLoss = 0;
     }
  }

//==================================================================== news
bool NewsBlackout()
  {
   if(!InpUseNews || MQLInfoInteger(MQL_TESTER))
      return false;
   datetime now = TimeTradeServer();
   if(now - g_newsCheckedAt < 60)
      return g_newsBlock;
   g_newsCheckedAt = now;
   g_newsBlock = false;

   MqlCalendarValue values[];
   if(CalendarValueHistory(values, now - InpNewsAfterMin * 60, now + InpNewsBeforeMin * 60, NULL, "USD") <= 0)
      return false;
   for(int i = 0; i < ArraySize(values); i++)
     {
      MqlCalendarEvent ev;
      if(CalendarEventById(values[i].event_id, ev) && ev.importance == CALENDAR_IMPORTANCE_HIGH)
        {
         g_newsBlock = true;
         break;
        }
     }
   return g_newsBlock;
  }

//==================================================================== signal
int H1Bias()
  {
   double f = Buf(g_hH1Fast, 0, 1), s = Buf(g_hH1Slow, 0, 1);
   double c = iClose(_Symbol, PERIOD_H1, 1);
   if(f == EMPTY_VALUE || s == EMPTY_VALUE || c == 0)
      return 0;
   if(c > s && f > s)
      return 1;
   if(c < s && f < s)
      return -1;
   return 0;
  }

// returns +1 buy, -1 sell, 0 none; fills structural SL level and liquidity target
int GetSignal(Engine &e, double &slLevel, double &liqTarget)
  {
   // ---- higher timeframe bias
   double bF  = Buf(e.hBiasFast, 0, 1);
   double bF4 = Buf(e.hBiasFast, 0, 4);
   double bS  = Buf(e.hBiasSlow, 0, 1);
   double adx = Buf(e.hADX, 0, 1);
   double bC  = iClose(_Symbol, e.biasTF, 1);
   if(bF == EMPTY_VALUE || bF4 == EMPTY_VALUE || bS == EMPTY_VALUE || adx == EMPTY_VALUE || bC == 0)
     {
      e.status = "waiting for data";
      return 0;
     }
   e.bias = 0;
   if(bC > bS && bF > bS && bF > bF4)
      e.bias = 1;
   else
      if(bC < bS && bF < bS && bF < bF4)
         e.bias = -1;
   if(e.bias == 0)
     {
      e.status = "no clear HTF trend";
      return 0;
     }
   if(adx < InpMinADX)
     {
      e.status = "HTF trend too weak (ADX " + DoubleToString(adx, 1) + ")";
      return 0;
     }
   if(e.useH1Filter && H1Bias() != e.bias)
     {
      e.status = "H1 trend disagrees";
      return 0;
     }

   // ---- entry timeframe
   int need = MathMax(InpTargetLookback + 2, 4 + InpSweepLookback);
   need = MathMax(need, MathMax(InpPullbackBars, InpSLStructureBars) + 2);
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, e.entryTF, 0, need, r) < need)
     {
      e.status = "waiting for data";
      return 0;
     }
   double f1  = Buf(e.hFast, 0, 1);
   double s1  = Buf(e.hSlow, 0, 1);
   double atr = Buf(e.hATR, 0, 1);
   double rsi = Buf(e.hRSI, 0, 1);
   if(f1 == EMPTY_VALUE || s1 == EMPTY_VALUE || atr == EMPTY_VALUE || rsi == EMPTY_VALUE || atr <= 0)
     {
      e.status = "waiting for data";
      return 0;
     }
   double range = r[1].high - r[1].low;
   if(range <= 0)
      return 0;
   bool strongBody = MathAbs(r[1].close - r[1].open) / range >= InpMinBodyRatio;

   if(e.bias > 0)
     {
      double pbLow  = LowestLow(r, 1, InpPullbackBars);
      bool aligned  = f1 > s1;
      bool pulled   = pbLow <= f1 + 0.25 * atr && pbLow >= s1 - 0.5 * atr;
      bool trigger  = r[1].close > r[1].open && strongBody && r[1].close > r[2].high
                      && r[1].close > f1 && rsi > 50 && rsi < InpRSIMaxLong;
      bool sweep    = !InpRequireSweep || LowestLow(r, 1, 3) < LowestLow(r, 4, InpSweepLookback);
      if(!(aligned && pulled && trigger && sweep))
        {
         e.status = "uptrend - waiting for pullback + trigger";
         return 0;
        }
      slLevel = MathMin(LowestLow(r, 1, InpSLStructureBars) - InpSLBufferATR * atr,
                        r[1].close - InpSLMinATR * atr);
      liqTarget = HighestHigh(r, 2, InpTargetLookback);
      return 1;
     }

   double pbHigh = HighestHigh(r, 1, InpPullbackBars);
   bool aligned  = f1 < s1;
   bool pulled   = pbHigh >= f1 - 0.25 * atr && pbHigh <= s1 + 0.5 * atr;
   bool trigger  = r[1].close < r[1].open && strongBody && r[1].close < r[2].low
                   && r[1].close < f1 && rsi < 50 && rsi > 100.0 - InpRSIMaxLong;
   bool sweep    = !InpRequireSweep || HighestHigh(r, 1, 3) > HighestHigh(r, 4, InpSweepLookback);
   if(!(aligned && pulled && trigger && sweep))
     {
      e.status = "downtrend - waiting for pullback + trigger";
      return 0;
     }
   slLevel = MathMax(HighestHigh(r, 1, InpSLStructureBars) + InpSLBufferATR * atr,
                     r[1].close + InpSLMinATR * atr);
   liqTarget = LowestLow(r, 2, InpTargetLookback);
   return -1;
  }

//==================================================================== orders
double LotsForRisk(int dir, double entry, double sl, double riskPct)
  {
   double riskMoney = AccountInfoDouble(ACCOUNT_EQUITY) * riskPct / 100.0;
   double pl = 0.0;
   ENUM_ORDER_TYPE otype = dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcProfit(otype, _Symbol, 1.0, entry, sl, pl) || pl >= 0)
     {
      double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tv <= 0 || ts <= 0)
         return 0.0;
      pl = -MathAbs(entry - sl) / ts * tv;
     }
   if(pl == 0)
      return 0.0;
   return riskMoney / MathAbs(pl);
  }

void OpenSetup(Engine &e, int dir, double slLevel, double liqTarget)
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double entry = dir > 0 ? tk.ask : tk.bid;

   // ---- stop loss from structure, clamped
   double R = dir * (entry - slLevel);
   if(R < Pip(e.slMinPips))
      R = Pip(e.slMinPips);
   if(R > Pip(e.slMaxPips))
     {
      e.status = "setup skipped - SL too wide (" + DoubleToString(R / InpPipSize, 0) + " pips)";
      return;
     }
   double stopLvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(R <= stopLvl || R * e.tp1R <= stopLvl)
     {
      e.status = "setup skipped - broker stop level";
      return;
     }

   // ---- targets based on the setup
   double sl  = NP(entry - dir * R);
   double tp1 = NP(entry + dir * e.tp1R * R);
   double tp2 = entry + dir * e.tp2R * R;
   double liqDist = dir * (liqTarget - entry);
   double cap = (e.runnerR > 0 ? e.runnerR : 6.0) * R;
   if(liqDist >= 1.5 * R && liqDist <= cap)
      tp2 = liqTarget - dir * Pip(2.0);   // front-run the liquidity pool
   if(dir * (tp2 - tp1) < 0.3 * R)
      tp2 = entry + dir * e.tp2R * R;
   tp2 = NP(tp2);
   double tp3 = e.runnerR > 0 ? NP(entry + dir * e.runnerR * R) : 0.0;

   // ---- position sizing split across legs
   double total = LotsForRisk(dir, entry, sl, e.riskPct);
   double splitSum = e.split[0] + e.split[1] + e.split[2];
   if(splitSum <= 0)
      splitSum = 100;
   double lots[3];
   for(int k = 0; k < 3; k++)
      lots[k] = NormLot(total * e.split[k] / splitSum);
   if(lots[0] <= 0)
     {
      lots[0] = NormLot(total);
      lots[1] = 0;
      lots[2] = 0;
     }
   if(lots[0] <= 0)
     {
      e.status = "setup skipped - risk too small for minimum lot";
      return;
     }
   double tps[3];
   tps[0] = tp1;
   tps[1] = tp2;
   tps[2] = tp3;
   if(lots[1] <= 0 && lots[2] <= 0)
      tps[0] = tp2;   // single leg: aim for TP2, BE + trail protect it

   long sid = (long)TimeCurrent();
   GlobalVariableSet(GVR(e.magic, sid), R);
   trade.SetExpertMagicNumber(e.magic);

   int opened = 0;
   for(int k = 0; k < 3; k++)
     {
      if(lots[k] <= 0)
         continue;
      string c = e.tag + "|" + IntegerToString(sid) + "|" + IntegerToString(k + 1);
      bool ok = dir > 0 ? trade.Buy(lots[k], _Symbol, 0.0, sl, tps[k], c)
                : trade.Sell(lots[k], _Symbol, 0.0, sl, tps[k], c);
      uint rc = trade.ResultRetcode();
      if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
         opened++;
      else
         Print(e.name, " leg ", k + 1, " failed: ", rc, " ", trade.ResultRetcodeDescription());
     }

   if(opened > 0)
     {
      e.status = StringFormat("%s opened %d legs | SL %.0f pips", dir > 0 ? "BUY" : "SELL", opened, R / InpPipSize);
      PrintFormat("%s %s @%.2f SL %.2f TP1 %.2f TP2 %.2f TP3 %.2f lots %.2f/%.2f/%.2f",
                  e.name, dir > 0 ? "BUY" : "SELL", entry, sl, tps[0], tp2, tp3, lots[0], lots[1], lots[2]);
     }
   else
      GlobalVariableDel(GVR(e.magic, sid));
  }

//==================================================================== management
void ManagePositions()
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double minDist = MathMax((double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                            (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * _Point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      ulong magic = (ulong)PositionGetInteger(POSITION_MAGIC);
      int ei = EngineByMagic(magic);
      if(ei < 0)
         continue;

      int    dir   = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
      double open  = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double price = dir > 0 ? tk.bid : tk.ask;

      // initial risk distance (R) of this setup
      double R = 0;
      long sid;
      int leg;
      if(ParseComment(PositionGetString(POSITION_COMMENT), sid, leg) && GlobalVariableCheck(GVR(magic, sid)))
         R = GlobalVariableGet(GVR(magic, sid));
      if(R <= 0)
         R = (sl > 0 && dir * (open - sl) > 0) ? dir * (open - sl) : Pip(E[ei].slMinPips);

      double profit = dir * (price - open);
      double newSL  = sl;

      // 1) breakeven + lock after TP1 distance
      if(profit >= InpBETriggerR * R)
        {
         double be = open + dir * Pip(InpBELockPips);
         if(BetterSL(dir, be, newSL))
            newSL = be;
        }

      // 2) ATR-adaptive trailing stop, clamped to [trailMin, trailMax] pips
      if(profit >= InpTrailStartR * R)
        {
         double d   = Pip(E[ei].trailMaxPips);
         double atr = Buf(E[ei].hATR, 0, 1);
         if(atr != EMPTY_VALUE && atr > 0)
            d = MathMax(Pip(E[ei].trailMinPips), MathMin(Pip(E[ei].trailMaxPips), atr * E[ei].trailATR));
         double cand = price - dir * d;
         if(BetterSL(dir, cand, newSL))
            newSL = cand;
        }

      newSL = NP(newSL);
      if(newSL == sl || !BetterSL(dir, newSL, sl))
         continue;
      bool firstLock = (sl == 0.0) || dir * (sl - open) < 0;   // SL still on the losing side
      if(!firstLock && dir * (newSL - sl) < Pip(InpTrailStepPips))
         continue;
      if(dir * (price - newSL) <= minDist)
         continue;
      if(!trade.PositionModify(ticket, newSL, tp))
         Print("Modify failed #", ticket, " ", trade.ResultRetcodeDescription());
     }
  }

void CleanupGlobals()
  {
   long today = DayKey();
   for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
     {
      string nm = GlobalVariableName(i);
      if(StringFind(nm, GV_PREFIX) != 0)
         continue;
      string parts[];
      int n = StringSplit(nm, StringGetCharacter("_", 0), parts);
      if(n == 4 && parts[1] == "R")
        {
         ulong magic = (ulong)StringToInteger(parts[2]);
         if(EngineByMagic(magic) >= 0 && !SetupOpen(magic, StringToInteger(parts[3])))
            GlobalVariableDel(nm);
        }
      else
         if(n == 3 && (parts[1] == "DAY" || parts[1] == "BLK") && StringToInteger(parts[2]) < today - 3)
            GlobalVariableDel(nm);
     }
  }

//==================================================================== gating
bool CanOpen(Engine &e, bool dayBlocked, bool news, double spreadPips)
  {
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);

   if(dayBlocked)
     {
      e.status = "daily loss limit hit - done for today";
      return false;
     }
   if(t.day_of_week == 5 && InpFridayNoNewHour > 0 && t.hour >= InpFridayNoNewHour)
     {
      e.status = "Friday - no new trades";
      return false;
     }
   if(t.day_of_week == 0 || t.day_of_week == 6)
     {
      e.status = "weekend";
      return false;
     }
   if(!InSession(e.startHour, e.endHour, t.hour))
     {
      e.status = "outside session";
      return false;
     }
   if(OpenPositions(e.magic) > 0)
     {
      e.status = "managing open setup";
      return false;
     }
   TodayStats(e);
   if(e.maxPerDay > 0 && e.setupsToday >= e.maxPerDay)
     {
      e.status = "max setups for today reached";
      return false;
     }
   if(e.maxConsecLoss > 0 && e.consecLoss >= e.maxConsecLoss)
     {
      e.status = "losing streak stop - done for today";
      return false;
     }
   if(spreadPips > InpMaxSpreadPips)
     {
      e.status = "spread too high (" + DoubleToString(spreadPips, 1) + " pips)";
      return false;
     }
   if(news)
     {
      e.status = "high-impact USD news blackout";
      return false;
     }
   return true;
  }

void FridayClose()
  {
   if(InpFridayCloseHour <= 0)
      return;
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   if(t.day_of_week == 5 && t.hour >= InpFridayCloseHour)
      CloseAllOurs();
  }

void Dashboard(double spreadPips, bool news, bool dayBlocked)
  {
   string s = "XAU Scalp + Intraday EA\n";
   s += StringFormat("Spread %.1f pips | Day P/L %.2f%% | News block: %s%s\n",
                     spreadPips, DayPnLPct(), news ? "YES" : "no", dayBlocked ? " | DAILY LIMIT HIT" : "");
   for(int i = 0; i < 2; i++)
     {
      string b = E[i].bias > 0 ? "UP" : (E[i].bias < 0 ? "DOWN" : "-");
      s += StringFormat("\n[%s] %s  bias: %s  setups today: %d  open legs: %d\n  %s\n",
                        E[i].name, E[i].enabled ? "ON" : "OFF", b, E[i].setupsToday,
                        OpenPositions(E[i].magic), E[i].status);
     }
   Comment(s);
  }

//==================================================================== engine setup
bool CreateHandles(Engine &e)
  {
   e.hBiasFast = iMA(_Symbol, e.biasTF, InpBiasFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   e.hBiasSlow = iMA(_Symbol, e.biasTF, InpBiasSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   e.hADX      = iADX(_Symbol, e.biasTF, InpADXPeriod);
   e.hFast     = iMA(_Symbol, e.entryTF, InpEntryFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   e.hSlow     = iMA(_Symbol, e.entryTF, InpEntrySlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   e.hATR      = iATR(_Symbol, e.entryTF, InpATRPeriod);
   e.hRSI      = iRSI(_Symbol, e.entryTF, InpRSIPeriod, PRICE_CLOSE);
   return e.hBiasFast != INVALID_HANDLE && e.hBiasSlow != INVALID_HANDLE && e.hADX != INVALID_HANDLE
          && e.hFast != INVALID_HANDLE && e.hSlow != INVALID_HANDLE && e.hATR != INVALID_HANDLE
          && e.hRSI != INVALID_HANDLE;
  }

void ReleaseHandles(Engine &e)
  {
   int h[7];
   h[0] = e.hBiasFast;
   h[1] = e.hBiasSlow;
   h[2] = e.hADX;
   h[3] = e.hFast;
   h[4] = e.hSlow;
   h[5] = e.hATR;
   h[6] = e.hRSI;
   for(int i = 0; i < 7; i++)
      if(h[i] != INVALID_HANDLE)
         IndicatorRelease(h[i]);
  }

//==================================================================== events
int OnInit()
  {
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("Warning: this EA is built for XAUUSD / GOLD. Current symbol: ", _Symbol);

   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   // ---- scalp engine
   E[0].name = "SCALP";
   E[0].tag = "SC";
   E[0].enabled = InpScalpOn;
   E[0].magic = InpScalpMagic;
   E[0].biasTF = InpScalpBiasTF;
   E[0].entryTF = InpScalpEntryTF;
   E[0].useH1Filter = InpScalpH1Filter;
   E[0].riskPct = InpScalpRiskPct;
   E[0].slMinPips = InpScalpSLMinPips;
   E[0].slMaxPips = InpScalpSLMaxPips;
   E[0].tp1R = InpScalpTP1R;
   E[0].tp2R = InpScalpTP2R;
   E[0].runnerR = InpScalpRunnerR;
   E[0].split[0] = InpScalpSplit1;
   E[0].split[1] = InpScalpSplit2;
   E[0].split[2] = InpScalpSplit3;
   E[0].trailMinPips = InpScalpTrailMin;
   E[0].trailMaxPips = InpScalpTrailMax;
   E[0].trailATR = InpScalpTrailATR;
   E[0].startHour = InpScalpStartHour;
   E[0].endHour = InpScalpEndHour;
   E[0].maxPerDay = InpScalpMaxPerDay;
   E[0].maxConsecLoss = InpScalpMaxConsecL;

   // ---- intraday engine
   E[1].name = "INTRADAY";
   E[1].tag = "ID";
   E[1].enabled = InpDayOn;
   E[1].magic = InpDayMagic;
   E[1].biasTF = InpDayBiasTF;
   E[1].entryTF = InpDayEntryTF;
   E[1].useH1Filter = false;
   E[1].riskPct = InpDayRiskPct;
   E[1].slMinPips = InpDaySLMinPips;
   E[1].slMaxPips = InpDaySLMaxPips;
   E[1].tp1R = InpDayTP1R;
   E[1].tp2R = InpDayTP2R;
   E[1].runnerR = InpDayRunnerR;
   E[1].split[0] = InpDaySplit1;
   E[1].split[1] = InpDaySplit2;
   E[1].split[2] = InpDaySplit3;
   E[1].trailMinPips = InpDayTrailMin;
   E[1].trailMaxPips = InpDayTrailMax;
   E[1].trailATR = InpDayTrailATR;
   E[1].startHour = InpDayStartHour;
   E[1].endHour = InpDayEndHour;
   E[1].maxPerDay = InpDayMaxPerDay;
   E[1].maxConsecLoss = InpDayMaxConsecL;

   if(InpScalpMagic == InpDayMagic)
     {
      Print("Scalp and intraday magic numbers must differ.");
      return INIT_PARAMETERS_INCORRECT;
     }

   for(int i = 0; i < 2; i++)
     {
      if(!CreateHandles(E[i]))
        {
         Print("Failed to create indicators for ", E[i].name);
         return INIT_FAILED;
        }
      E[i].lastBar = iTime(_Symbol, E[i].entryTF, 0);   // don't act on a stale bar at start-up
      E[i].bias = 0;
      E[i].setupsToday = 0;
      E[i].consecLoss = 0;
      E[i].status = E[i].enabled ? "waiting for next candle" : "disabled";
     }

   g_hH1Fast = iMA(_Symbol, PERIOD_H1, InpBiasFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   g_hH1Slow = iMA(_Symbol, PERIOD_H1, InpBiasSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(g_hH1Fast == INVALID_HANDLE || g_hH1Slow == INVALID_HANDLE)
      return INIT_FAILED;

   DayStartBalance();
   EventSetTimer(60);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   for(int i = 0; i < 2; i++)
      ReleaseHandles(E[i]);
   if(g_hH1Fast != INVALID_HANDLE)
      IndicatorRelease(g_hH1Fast);
   if(g_hH1Slow != INVALID_HANDLE)
      IndicatorRelease(g_hH1Slow);
   Comment("");
  }

void OnTimer()
  {
   CleanupGlobals();
   for(int i = 0; i < 2; i++)
      if(E[i].enabled)
         TodayStats(E[i]);
  }

void OnTick()
  {
   ManagePositions();
   FridayClose();

   bool dayBlocked = DailyLossHit();
   bool news = NewsBlackout();
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double spreadPips = (tk.ask - tk.bid) / InpPipSize;

   for(int i = 0; i < 2; i++)
     {
      if(!E[i].enabled)
         continue;
      datetime bar = iTime(_Symbol, E[i].entryTF, 0);
      if(bar == 0 || bar == E[i].lastBar)
         continue;
      E[i].lastBar = bar;

      if(!CanOpen(E[i], dayBlocked, news, spreadPips))
         continue;
      double slLevel = 0, liqTarget = 0;
      int dir = GetSignal(E[i], slLevel, liqTarget);
      if(dir != 0)
         OpenSetup(E[i], dir, slLevel, liqTarget);
     }

   if(InpShowDashboard)
      Dashboard(spreadPips, news, dayBlocked);
  }
//+------------------------------------------------------------------+
