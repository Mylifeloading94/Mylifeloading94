//+------------------------------------------------------------------+
//|                                          XAU_BreakoutPro_EA.mq5  |
//|                                                  Mylifeloading94 |
//|                                                                  |
//| XAUUSD session-breakout EA (v2 - replaces XAU_ScalpIntraday_EA)  |
//|                                                                  |
//| SCALP    (M5): Asian range 00:00-06:00 UTC. First M5 close beyond|
//|                it between 06:00-10:00 UTC, in daily-trend        |
//|                direction. SL 1.5 x ATR(M5).                      |
//| INTRADAY (H1): previous-day high/low. First H1 close beyond it   |
//|                between 06:00-16:00 UTC, in daily-trend direction.|
//|                SL 1.5 x ATR(H1).                                 |
//| Daily trend  : D1 close and EMA20 on the same side of EMA50.     |
//|                A first break AGAINST the trend ends that engine's|
//|                day (no trade).                                   |
//| Exits        : two halves. TP1 = 1R closes half, SL of the rest  |
//|                -> breakeven + lock; runner to TP2; time stop.    |
//|                                                                  |
//| Backtest (Dukascopy M1, Apr-Sep 2026, 3-pip spread, honest fills)|
//| see XAU_BREAKOUT_REPORT.md                                       |
//+------------------------------------------------------------------+
#property copyright "Mylifeloading94"
#property version   "2.00"
#property description "XAUUSD session breakout: Asian-range (M5) + previous-day high/low (H1)."
#property description "Daily trend filter, 2-target exits, breakeven after TP1, time stop."

#include <Trade/Trade.mqh>

input group "=== General ==="
input double InpPipSize          = 0.10;   // Pip size in price (gold: 0.10)
input int    InpServerGMTOffset  = -99;    // Broker server GMT offset in hours (-99 = auto)
input double InpMaxSpreadPips    = 5.0;    // Max spread to open (pips)
input int    InpSlippagePoints   = 30;     // Max slippage (points)
input bool   InpShowDashboard    = true;   // On-chart dashboard

input group "=== Risk ==="
input double InpRiskPct          = 2.0;    // Risk per trade (% equity, both halves)
input double InpMinLotMaxRiskPct = 3.0;    // Allow 0.01 lot if its risk <= this % (small accounts)
input double InpMaxDailyLossPct  = 4.0;    // Stop new trades after this daily loss % (0 = off)
input int    InpFridayCloseHourUTC = 19;   // Close all trades Friday at this UTC hour (0 = off)

input group "=== News filter (live/demo only) ==="
input bool   InpUseNews          = true;   // Skip entries near high-impact USD news
input int    InpNewsBeforeMin    = 30;
input int    InpNewsAfterMin     = 30;

input group "=== Daily trend filter ==="
input int    InpTrendFastEMA     = 20;     // D1 fast EMA
input int    InpTrendSlowEMA     = 50;     // D1 slow EMA

input group "=== SCALP engine: Asian range breakout (M5) ==="
input bool   InpScalpOn          = true;
input int    InpAsiaStartUTC     = 0;      // Asian range start (UTC hour)
input int    InpAsiaEndUTC       = 6;      // Asian range end (UTC hour)
input int    InpScalpWinEndUTC   = 10;     // Last UTC hour to enter (window = AsiaEnd..this)
input double InpScalpSLATR       = 1.5;    // SL = ATR(M5) x this
input double InpScalpSLMinPips   = 25;
input double InpScalpSLMaxPips   = 200;
input double InpScalpTP1R        = 1.0;
input double InpScalpTP2R        = 2.0;
input int    InpScalpTimeStopMin = 600;    // Close after N minutes
input ulong  InpScalpMagic       = 27100;

input group "=== INTRADAY engine: previous-day high/low breakout (H1) ==="
input bool   InpDayOn            = true;
input int    InpDayWinStartUTC   = 6;
input int    InpDayWinEndUTC     = 16;
input double InpDaySLATR         = 1.5;    // SL = ATR(H1) x this
input double InpDaySLMinPips     = 80;
input double InpDaySLMaxPips     = 600;
input double InpDayTP1R          = 1.0;
input double InpDayTP2R          = 3.0;
input int    InpDayTimeStopMin   = 1440;
input ulong  InpDayMagic         = 27200;

input group "=== Management ==="
input double InpBELockPips       = 3.0;    // Pips locked when SL moves to breakeven
input int    InpATRPeriod        = 14;

//==================================================================== state
struct Engine
  {
   string            name;
   string            tag;
   bool              on;
   ulong             magic;
   ENUM_TIMEFRAMES   tf;
   int               hATR;
   double            slATR, slMin, slMax, tp1R, tp2R;
   int               timeStopMin;
   datetime          lastBar;
   int               doneDay;      // UTC day index on which this engine is finished
   string            status;
  };

CTrade   trade;
Engine   E[2];
int      g_hFast = INVALID_HANDLE, g_hSlow = INVALID_HANDLE;
datetime g_newsAt = 0;
bool     g_news = false;
const string GV = "XAUBP_";

//==================================================================== utils
double Pip(double p) { return p * InpPipSize; }

double Buf(int h, int b, int shift)
  {
   double a[1];
   if(h == INVALID_HANDLE || CopyBuffer(h, b, shift, 1, a) != 1)
      return EMPTY_VALUE;
   return a[0];
  }

double NP(double p)
  {
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0)
      ts = _Point;
   return NormalizeDouble(MathRound(p / ts) * ts, _Digits);
  }

int GMTOffsetSec()
  {
   if(InpServerGMTOffset != -99)
      return InpServerGMTOffset * 3600;
   if(MQLInfoInteger(MQL_TESTER))
      return 3 * 3600;     // tester has no real GMT clock: assume GMT+3 (set input to override)
   long diff = (long)(TimeTradeServer() - TimeGMT());
   return (int)(MathRound(diff / 1800.0) * 1800);
  }

datetime ToUTC(datetime server) { return server - GMTOffsetSec(); }
datetime ToServer(datetime utc) { return utc + GMTOffsetSec(); }
int      DayIdx(datetime t)     { return (int)(t / 86400); }
int      UTCHour(datetime server) { MqlDateTime d; TimeToStruct(ToUTC(server), d); return d.hour; }

string GVR(ulong magic, long sid) { return GV + "R_" + IntegerToString((long)magic) + "_" + IntegerToString(sid); }

bool ParseComment(string c, long &sid, int &leg)
  {
   string p[];
   if(StringSplit(c, StringGetCharacter("|", 0), p) != 3)
      return false;
   sid = StringToInteger(p[1]);
   leg = (int)StringToInteger(p[2]);
   return sid > 0;
  }

int EngineByMagic(ulong magic)
  {
   for(int i = 0; i < 2; i++)
      if(E[i].magic == magic)
         return i;
   return -1;
  }

int OpenCount(ulong magic)
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

void CloseMagic(ulong magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == magic)
         if(!trade.PositionClose(t))
            Print("Close failed #", t, " ", trade.ResultRetcodeDescription());
     }
  }

//==================================================================== filters
int DailyTrend()
  {
   double f = Buf(g_hFast, 0, 1), s = Buf(g_hSlow, 0, 1);
   double c = iClose(_Symbol, PERIOD_D1, 1);
   if(f == EMPTY_VALUE || s == EMPTY_VALUE || c == 0)
      return 0;
   if(c > s && f > s)
      return 1;
   if(c < s && f < s)
      return -1;
   return 0;
  }

double DayStartBalance()
  {
   string n = GV + "DAY_" + IntegerToString(DayIdx(TimeCurrent()));
   if(!GlobalVariableCheck(n))
      GlobalVariableSet(n, AccountInfoDouble(ACCOUNT_BALANCE));
   return GlobalVariableGet(n);
  }

double DayPnLPct()
  {
   double s = DayStartBalance();
   return s > 0 ? (AccountInfoDouble(ACCOUNT_EQUITY) - s) / s * 100.0 : 0.0;
  }

bool NewsBlackout()
  {
   if(!InpUseNews || MQLInfoInteger(MQL_TESTER))
      return false;
   datetime now = TimeTradeServer();
   if(now - g_newsAt < 60)
      return g_news;
   g_newsAt = now;
   g_news = false;
   MqlCalendarValue v[];
   if(CalendarValueHistory(v, now - InpNewsAfterMin * 60, now + InpNewsBeforeMin * 60, NULL, "USD") <= 0)
      return false;
   for(int i = 0; i < ArraySize(v); i++)
     {
      MqlCalendarEvent ev;
      if(CalendarEventById(v[i].event_id, ev) && ev.importance == CALENDAR_IMPORTANCE_HIGH)
        {
         g_news = true;
         break;
        }
     }
   return g_news;
  }

//==================================================================== levels
// high/low of `tf` candles whose UTC open time is in [fromUTC, toUTC)
bool RangeHL(ENUM_TIMEFRAMES tf, datetime fromUTC, datetime toUTC, double &hi, double &lo)
  {
   MqlRates r[];
   int n = CopyRates(_Symbol, tf, ToServer(fromUTC), ToServer(toUTC) - 1, r);
   if(n < 3)
      return false;
   hi = -DBL_MAX;
   lo = DBL_MAX;
   for(int i = 0; i < n; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
     }
   return true;
  }

// previous UTC trading day's high/low (skips days without data, e.g. weekend)
bool PrevDayHL(datetime nowUTC, double &hi, double &lo)
  {
   datetime today = (datetime)(DayIdx(nowUTC) * 86400);
   for(int back = 1; back <= 5; back++)
      if(RangeHL(PERIOD_H1, today - back * 86400, today - (back - 1) * 86400, hi, lo))
         return true;
   return false;
  }

//==================================================================== orders
double LossPerLot(int dir, double entry, double sl)
  {
   double pl = 0;
   if(OrderCalcProfit(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, _Symbol, 1.0, entry, sl, pl) && pl < 0)
      return -pl;
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   return (tv > 0 && ts > 0) ? MathAbs(entry - sl) / ts * tv : 0.0;
  }

double FloorLot(double v)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0)
      step = 0.01;
   v = MathFloor(v / step + 1e-9) * step;
   return NormalizeDouble(MathMin(v, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX)), 2);
  }

void Open(Engine &e, int dir, double slLevel)
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double entry = dir > 0 ? tk.ask : tk.bid;
   double R = dir * (entry - slLevel);
   if(R < Pip(e.slMin))
      R = Pip(e.slMin);
   if(R > Pip(e.slMax))
     {
      e.status = "skipped: SL too wide";
      return;
     }
   double sl  = NP(entry - dir * R);
   double tp1 = NP(entry + dir * e.tp1R * R);
   double tp2 = NP(entry + dir * e.tp2R * R);

   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double lpl = LossPerLot(dir, entry, sl);
   if(lpl <= 0)
      return;
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double total = FloorLot(eq * InpRiskPct / 100.0 / lpl);
   if(total < minLot)
     {
      if(minLot * lpl <= eq * InpMinLotMaxRiskPct / 100.0)
         total = minLot;
      else
        {
         e.status = "skipped: account too small for this SL";
         return;
        }
     }
   double leg1 = FloorLot(total / 2.0);
   double leg2 = FloorLot(total - leg1);
   if(leg1 < minLot || leg2 < minLot)
     {
      leg1 = 0;          // one position only: BE at TP1, target TP2
      leg2 = total;
     }

   long sid = (long)TimeCurrent();
   GlobalVariableSet(GVR(e.magic, sid), R);
   trade.SetExpertMagicNumber(e.magic);
   int ok = 0;
   if(leg1 > 0)
     {
      string c1 = e.tag + "|" + IntegerToString(sid) + "|1";
      if(dir > 0 ? trade.Buy(leg1, _Symbol, 0, sl, tp1, c1) : trade.Sell(leg1, _Symbol, 0, sl, tp1, c1))
         ok++;
      else
         Print(e.name, " leg1 failed ", trade.ResultRetcodeDescription());
     }
   string c2 = e.tag + "|" + IntegerToString(sid) + "|2";
   if(dir > 0 ? trade.Buy(leg2, _Symbol, 0, sl, tp2, c2) : trade.Sell(leg2, _Symbol, 0, sl, tp2, c2))
      ok++;
   else
      Print(e.name, " leg2 failed ", trade.ResultRetcodeDescription());

   if(ok > 0)
     {
      e.status = StringFormat("%s %.2f lots, SL %.0f pips", dir > 0 ? "BUY" : "SELL", leg1 + leg2, R / InpPipSize);
      PrintFormat("%s %s @%.2f SL %.2f TP1 %.2f TP2 %.2f lots %.2f+%.2f", e.name, dir > 0 ? "BUY" : "SELL",
                  entry, sl, tp1, tp2, leg1, leg2);
     }
   else
      GlobalVariableDel(GVR(e.magic, sid));
  }

//==================================================================== signals
void CheckEngine(Engine &e, bool blocked, bool news, double spreadPips)
  {
   datetime bar = iTime(_Symbol, e.tf, 0);
   if(bar == 0 || bar == e.lastBar)
      return;
   e.lastBar = bar;

   datetime nowUTC = ToUTC(TimeCurrent());
   int day = DayIdx(nowUTC);
   int hour = UTCHour(TimeCurrent());
   MqlDateTime dt;
   TimeToStruct(nowUTC, dt);

   if(e.doneDay == day)
      return;
   if(dt.day_of_week == 0 || dt.day_of_week == 6)
     {
      e.status = "weekend";
      return;
     }
   int winStart = (e.tag == "BS") ? InpAsiaEndUTC : InpDayWinStartUTC;
   int winEnd   = (e.tag == "BS") ? InpScalpWinEndUTC : InpDayWinEndUTC;
   if(hour < winStart || hour >= winEnd)
     {
      e.status = StringFormat("waiting for window %02d-%02d UTC", winStart, winEnd);
      return;
     }
   if(OpenCount(e.magic) > 0)
     {
      e.status = "managing trade";
      return;
     }

   double hi, lo;
   datetime today = (datetime)(day * 86400);
   bool okLvl = (e.tag == "BS")
                ? RangeHL(PERIOD_M5, today + InpAsiaStartUTC * 3600, today + InpAsiaEndUTC * 3600, hi, lo)
                : PrevDayHL(nowUTC, hi, lo);
   if(!okLvl)
     {
      e.status = "no level data";
      return;
     }
   double c = iClose(_Symbol, e.tf, 1);
   int dir = c > hi ? 1 : (c < lo ? -1 : 0);
   if(dir == 0)
     {
      e.status = StringFormat("inside %.2f - %.2f", lo, hi);
      return;
     }
   // the first break of the day decides: with trend -> trade, against -> done
   e.doneDay = day;
   int trend = DailyTrend();
   if(trend != dir)
     {
      e.status = "first break against daily trend - no trade today";
      return;
     }
   if(blocked)
     {
      e.status = "daily loss limit - no trade";
      return;
     }
   if(spreadPips > InpMaxSpreadPips)
     {
      e.status = "spread too high - no trade";
      return;
     }
   if(news)
     {
      e.status = "news blackout - no trade";
      return;
     }
   double atr = Buf(e.hATR, 0, 1);
   if(atr == EMPTY_VALUE || atr <= 0)
      return;
   Open(e, dir, c - dir * e.slATR * atr);
  }

//==================================================================== management
void Manage()
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double minDist = MathMax((double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                            (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * _Point;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      ulong magic = (ulong)PositionGetInteger(POSITION_MAGIC);
      int ei = EngineByMagic(magic);
      if(ei < 0)
         continue;
      int dir = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);

      // time stop
      if(TimeCurrent() - opened >= E[ei].timeStopMin * 60)
        {
         if(!trade.PositionClose(t))
            Print("Time-stop close failed #", t);
         continue;
        }
      // breakeven once price reaches TP1 distance
      long sid;
      int leg;
      double R = 0;
      if(ParseComment(PositionGetString(POSITION_COMMENT), sid, leg) && GlobalVariableCheck(GVR(magic, sid)))
         R = GlobalVariableGet(GVR(magic, sid));
      if(R <= 0)
         R = (sl > 0 && dir * (open - sl) > 0) ? dir * (open - sl) : Pip(E[ei].slMin);
      double price = dir > 0 ? tk.bid : tk.ask;
      if(dir * (price - open) >= E[ei].tp1R * R)
        {
         double be = NP(open + dir * Pip(InpBELockPips));
         if((sl == 0 || dir * (be - sl) > 0) && dir * (price - be) > minDist)
            if(!trade.PositionModify(t, be, tp))
               Print("BE modify failed #", t, " ", trade.ResultRetcodeDescription());
        }
     }
  }

void Cleanup()
  {
   int today = DayIdx(TimeCurrent());
   for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
     {
      string nm = GlobalVariableName(i);
      if(StringFind(nm, GV) != 0)
         continue;
      string p[];
      int n = StringSplit(nm, StringGetCharacter("_", 0), p);
      if(n == 4 && p[1] == "R")
        {
         ulong magic = (ulong)StringToInteger(p[2]);
         if(EngineByMagic(magic) >= 0 && OpenCount(magic) == 0)
            GlobalVariableDel(nm);
        }
      else
         if(n == 3 && p[1] == "DAY" && StringToInteger(p[2]) < today - 3)
            GlobalVariableDel(nm);
     }
  }

//==================================================================== events
int OnInit()
  {
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("Warning: built for XAUUSD / GOLD, attached to ", _Symbol);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   E[0].name = "SCALP (Asia break M5)";
   E[0].tag = "BS";
   E[0].on = InpScalpOn;
   E[0].magic = InpScalpMagic;
   E[0].tf = PERIOD_M5;
   E[0].slATR = InpScalpSLATR;
   E[0].slMin = InpScalpSLMinPips;
   E[0].slMax = InpScalpSLMaxPips;
   E[0].tp1R = InpScalpTP1R;
   E[0].tp2R = InpScalpTP2R;
   E[0].timeStopMin = InpScalpTimeStopMin;

   E[1].name = "INTRADAY (PDH/PDL break H1)";
   E[1].tag = "BD";
   E[1].on = InpDayOn;
   E[1].magic = InpDayMagic;
   E[1].tf = PERIOD_H1;
   E[1].slATR = InpDaySLATR;
   E[1].slMin = InpDaySLMinPips;
   E[1].slMax = InpDaySLMaxPips;
   E[1].tp1R = InpDayTP1R;
   E[1].tp2R = InpDayTP2R;
   E[1].timeStopMin = InpDayTimeStopMin;

   if(InpScalpMagic == InpDayMagic)
      return INIT_PARAMETERS_INCORRECT;
   for(int i = 0; i < 2; i++)
     {
      E[i].hATR = iATR(_Symbol, E[i].tf, InpATRPeriod);
      if(E[i].hATR == INVALID_HANDLE)
         return INIT_FAILED;
      E[i].lastBar = iTime(_Symbol, E[i].tf, 0);
      E[i].doneDay = -1;
      E[i].status = E[i].on ? "starting" : "disabled";
     }
   g_hFast = iMA(_Symbol, PERIOD_D1, InpTrendFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   g_hSlow = iMA(_Symbol, PERIOD_D1, InpTrendSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(g_hFast == INVALID_HANDLE || g_hSlow == INVALID_HANDLE)
      return INIT_FAILED;
   DayStartBalance();
   EventSetTimer(60);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   for(int i = 0; i < 2; i++)
      if(E[i].hATR != INVALID_HANDLE)
         IndicatorRelease(E[i].hATR);
   if(g_hFast != INVALID_HANDLE)
      IndicatorRelease(g_hFast);
   if(g_hSlow != INVALID_HANDLE)
      IndicatorRelease(g_hSlow);
   Comment("");
  }

void OnTimer() { Cleanup(); }

void OnTick()
  {
   Manage();

   MqlDateTime u;
   TimeToStruct(ToUTC(TimeCurrent()), u);
   if(InpFridayCloseHourUTC > 0 && u.day_of_week == 5 && u.hour >= InpFridayCloseHourUTC)
      for(int i = 0; i < 2; i++)
         CloseMagic(E[i].magic);

   bool blocked = InpMaxDailyLossPct > 0 && DayPnLPct() <= -InpMaxDailyLossPct;
   bool news = NewsBlackout();
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double spreadPips = (tk.ask - tk.bid) / InpPipSize;
   for(int i = 0; i < 2; i++)
      if(E[i].on)
         CheckEngine(E[i], blocked, news, spreadPips);

   if(InpShowDashboard)
     {
      int tr = DailyTrend();
      string s = StringFormat("XAU Breakout Pro v2 | UTC %02d:%02d | daily trend: %s | spread %.1f pips | day P/L %.2f%%%s\n",
                              u.hour, u.min, tr > 0 ? "UP" : (tr < 0 ? "DOWN" : "FLAT (no trades)"),
                              spreadPips, DayPnLPct(), news ? " | NEWS" : "");
      for(int i = 0; i < 2; i++)
         s += StringFormat("\n[%s] %s  open: %d\n  %s\n", E[i].name, E[i].on ? "ON" : "OFF",
                           OpenCount(E[i].magic), E[i].status);
      Comment(s);
     }
  }
//+------------------------------------------------------------------+
