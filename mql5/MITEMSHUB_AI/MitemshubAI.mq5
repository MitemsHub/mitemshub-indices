//+------------------------------------------------------------------+
//|                                    MitemshubAI_v21.mq5           |
//|                     MITEMSHUB AI MULTI-STRATEGY ENGINE v21       |
//|   Any Instrument • Any Timeframe • Auto-Strategy Selection       |
//|   8 Strategies • Scoring • Regime-Based • Combinable             |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "21.00"
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| STRATEGY ENUMS                                                     |
//+------------------------------------------------------------------+
enum ENUM_STRATEGY
{
   STRAT_BREAKOUT       = 0,   // Breakout (N-bar range)
   STRAT_BOS            = 1,   // Break of Structure
   STRAT_MOMENTUM       = 2,   // Momentum (bar body + velocity)
   STRAT_MEAN_REVERT    = 3,   // Mean Reversion (RSI + BB)
   STRAT_EMA_PULLBACK   = 4,   // EMA Pullback in Trend
   STRAT_LIQ_GRAB       = 5,   // Liquidity Grab (sweep & reverse)
   STRAT_ORDER_BLOCK    = 6,   // Order Block
   STRAT_CONFLUENCE     = 7,   // Multi-Indicator Confluence
   STRAT_COUNT          = 8
};

enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_NO_TRADE };

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Strategy Selection ==="
input bool   InpUseBreakout      = true;       // Enable Breakout strategy
input bool   InpUseBos           = true;       // Enable Break of Structure
input bool   InpUseMomentum      = true;       // Enable Momentum strategy
input bool   InpUseMeanRevert    = true;       // Enable Mean Reversion
input bool   InpUseEmaPullback   = true;       // Enable EMA Pullback
input bool   InpUseLiqGrab       = true;       // Enable Liquidity Grab
input bool   InpUseOrderBlock    = true;       // Enable Order Block
input bool   InpUseConfluence    = true;       // Enable Multi-Indicator Confluence
input int    InpMinScore         = 4;          // Min combined score to enter (0-10)
input bool   InpRequire2Strats   = true;       // Require 2+ strategies to agree

input group "=== Regime Detection ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input bool   InpTradeRanging     = true;       // Allow ranging trades

input group "=== Breakout Settings ==="
input int    InpBreakoutBars     = 20;         // N-bar breakout lookback
input double InpBreakoutBuffer   = 0.08;       // Buffer above/below range (ATR)

input group "=== Structure Settings ==="
input int    InpSwingLookback    = 5;          // Swing point lookback
input int    InpStructureBars    = 30;         // Structure analysis window

input group "=== Momentum Settings ==="
input double InpMomBodyThresh    = 0.4;        // Min body/range ratio
input int    InpMomVelocity      = 5;          // Velocity lookback bars
input double InpMomVelocityThresh = 0.20;      // Min velocity (ATR units)

input group "=== Mean Reversion Settings ==="
input double InpRsiOversold      = 30.0;       // RSI oversold level
input double InpRsiOverbought    = 70.0;       // RSI overbought level
input double InpBBWidthThresh    = 0.04;       // BB width for squeeze detection

input group "=== EMA Pullback Settings ==="
input double InpPullbackMaxAtr   = 0.5;        // Max pullback distance (ATR)

input group "=== Order Block Settings ==="
input int    InpObLookback       = 5;          // Order block lookback
input double InpObStrengthAtr    = 1.0;        // Min candle size for OB (ATR)

input group "=== Confluence Settings ==="
input int    InpConfMinAgree     = 4;          // Min indicators to agree (out of 6)

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.01;       // 1% equity risk
input double InpTpMult           = 2.0;        // TP = multiplier × SL
input int    InpMaxHoldBars      = 16;         // Max hold (M5 bars)
input double InpMaxDailyLossPct  = 0.05;       // 5% daily loss cap
input int    InpMaxConsecLoss    = 4;          // Pause after N losses
input int    InpCoolDownBars     = 3;          // Cooldown after loss

input group "=== Trade Management ==="
input bool   InpUseTrailing      = true;
input double InpTrailTriggerR    = 1.0;
input double InpTrailDistR       = 0.8;
input bool   InpUseBreakeven     = true;
input double InpBeTriggerR       = 0.8;
input double InpBeOffsetPts      = 0.10;

input group "=== Execution ==="
input long   InpMagic            = 7788210;
input int    InpMaxSlippagePts   = 30;
input int    InpWarmupBars       = 200;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = false;
input bool   InpDebugLog         = false;
input int    InpMaxTradesPerDay  = 3;

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES g_tf_entry, g_tf_regime;
int hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;
int hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E;
int hBB_E;

double g_eq = 0, g_peak_eq = 0, g_daily_pnl = 0;
datetime g_day_start = 0;
int g_cooldown = 0, g_consec_loss = 0;
bool g_paused = false;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

int g_trades = 0, g_wins = 0, g_losses = 0;
int g_target_exits = 0, g_time_exits = 0, g_stop_exits = 0;
double g_total_r = 0;

ulong g_ticket = 0;
int g_dir = 0;
double g_entry = 0, g_sl = 0, g_tp = 0, g_orig_risk = 0;
double g_position_volume = 0;
datetime g_entry_time = 0;
int g_bars_held = 0;
int g_trades_today = 0;

// Strategy performance tracking
int g_strat_trades[STRAT_COUNT];
int g_strat_wins[STRAT_COUNT];
double g_strat_pnl[STRAT_COUNT];
double g_strat_scores[STRAT_COUNT];   // rolling score

// Structure data
double g_swing_highs[];
double g_swing_lows[];
int g_swing_count = 0;

string dash_names[30];

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M5)  return PERIOD_H1;
   if(tf == PERIOD_M15) return PERIOD_H4;
   if(tf == PERIOD_H1)  return PERIOD_D1;
   return PERIOD_H4;
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_tf_entry  = (ENUM_TIMEFRAMES)Period();
   g_tf_regime = GetRegimeTF(g_tf_entry);

   hEMA_Fast_R = iMA(_Symbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_R  = iMA(_Symbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_R = iMA(_Symbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Fast_E = iMA(_Symbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_E  = iMA(_Symbol, g_tf_entry, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_E = iMA(_Symbol, g_tf_entry, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_E      = iRSI(_Symbol, g_tf_entry, 14, PRICE_CLOSE);
   hATR_E      = iATR(_Symbol, g_tf_entry, 14);
   hBB_E       = iBands(_Symbol, g_tf_entry, 20, 0, 2, PRICE_CLOSE);

   if(hEMA_Fast_R == INVALID_HANDLE || hEMA_Mid_R == INVALID_HANDLE || hEMA_Slow_R == INVALID_HANDLE ||
      hEMA_Fast_E == INVALID_HANDLE || hEMA_Mid_E == INVALID_HANDLE || hEMA_Slow_E == INVALID_HANDLE ||
      hRSI_E == INVALID_HANDLE || hATR_E == INVALID_HANDLE || hBB_E == INVALID_HANDLE)
   {
      Print("[v21] Handle creation failed");
      return INIT_FAILED;
   }

   ArrayResize(g_swing_highs, 100);
   ArrayResize(g_swing_lows, 100);

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   // Init strategy stats
   ArrayInitialize(g_strat_trades, 0);
   ArrayInitialize(g_strat_wins, 0);
   ArrayInitialize(g_strat_pnl, 0.0);

   RecoverPosition();
   if(InpDrawDashboard) CreateDashboard();

   PrintFormat("[MITEM v21] Multi-Strategy Engine | Entry=%s Regime=%s | Strategies: %s%s%s%s%s%s%s%s",
               EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpUseBreakout?"BKO ":"", InpUseBos?"BOS ":"", InpUseMomentum?"MOM ":"",
               InpUseMeanRevert?"MRV ":"", InpUseEmaPullback?"EMA ":"", InpUseLiqGrab?"LIQ ":"",
               InpUseOrderBlock?"OBK ":"", InpUseConfluence?"CNF ":"");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_R); IndicatorRelease(hEMA_Mid_R); IndicatorRelease(hEMA_Slow_R);
   IndicatorRelease(hEMA_Fast_E); IndicatorRelease(hEMA_Mid_E); IndicatorRelease(hEMA_Slow_E);
   IndicatorRelease(hRSI_E); IndicatorRelease(hATR_E); IndicatorRelease(hBB_E);
   for(int i = 0; i < 30; i++) ObjectDelete(0, dash_names[i]);

   Print("========================================");
   Print("[v21] STRATEGY PERFORMANCE:");
   string names[] = {"BREAKOUT","BOS","MOMENTUM","MEAN_REV","EMA_PULL","LIQ_GRAB","ORDER_BLK","CONFLUENCE"};
   for(int i = 0; i < STRAT_COUNT; i++)
   {
      if(g_strat_trades[i] > 0)
      {
         double wr = 100.0 * g_strat_wins[i] / g_strat_trades[i];
         PrintFormat("  %s: %d trades, WR=%.1f%%, P&L=$%.2f", names[i], g_strat_trades[i], wr, g_strat_pnl[i]);
      }
   }
   PrintFormat("TOTAL: %d trades, WR=%.1f%%, R=%+.2f", g_trades, g_trades>0?100.0*g_wins/g_trades:0, g_total_r);
   Print("========================================");
}

//+------------------------------------------------------------------+
void OnTick()
{
   static datetime last_bar = 0;
   datetime cur_bar = iTime(_Symbol, g_tf_entry, 0);
   if(cur_bar == last_bar)
   {
      if(InpDrawDashboard) UpdateDashboard();
      return;
   }
   last_bar = cur_bar;

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_eq > g_peak_eq) g_peak_eq = g_eq;

   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start)
   {
      g_day_start = ds;
      g_daily_pnl = 0;
      g_trades_today = 0;
      g_paused = false;
   }

   if(g_cooldown > 0) g_cooldown--;

   if(g_ticket > 0)
   {
      if(PositionSelectByTicket(g_ticket))
         ManagePosition();
      else
         g_ticket = 0;
   }

   if(g_ticket == 0 && !g_paused && g_cooldown == 0 &&
      g_trades_today < InpMaxTradesPerDay &&
      Bars(_Symbol, g_tf_entry) >= InpWarmupBars)
   {
      string sig_type = "";
      int direction = GenerateSignal(sig_type);
      if(direction != 0)
         OpenTrade(direction, sig_type);
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
void RecoverPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      g_ticket = t;
      g_dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      g_entry = PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl = PositionGetDouble(POSITION_SL);
      g_tp = PositionGetDouble(POSITION_TP);
      g_orig_risk = MathAbs(g_entry - g_sl);
      g_position_volume = PositionGetDouble(POSITION_VOLUME);
      g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held = 0;
      break;
   }
}

//+------------------------------------------------------------------+
//| REGIME CLASSIFICATION                                              |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hEMA_Fast_R,0,1,1,emaF)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_R,0,1,1,emaM)<1)  return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_R,0,1,1,emaS)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)        return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);
   double sep = MathAbs(emaF[0] - emaM[0]) / atr[0];

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0] && sep >= 0.10)
      return REGIME_BULLISH;
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0] && sep >= 0.10)
      return REGIME_BEARISH;
   return REGIME_RANGING;
}

//+------------------------------------------------------------------+
//| STRUCTURE DETECTION                                                |
//+------------------------------------------------------------------+
void DetectSwingPoints()
{
   g_swing_count = 0;
   int lb = InpSwingLookback;
   for(int i = lb; i < InpStructureBars && i < Bars(_Symbol, g_tf_entry) - 1; i++)
   {
      double hi = iHigh(_Symbol, g_tf_entry, i);
      double lo = iLow(_Symbol, g_tf_entry, i);
      bool is_sh = true, is_sl = true;
      for(int j = 1; j <= lb; j++)
      {
         if(iHigh(_Symbol, g_tf_entry, i-j) >= hi || iHigh(_Symbol, g_tf_entry, i+j) >= hi) { is_sh = false; break; }
      }
      if(is_sh && g_swing_count < 100) { g_swing_highs[g_swing_count] = hi; g_swing_count++; }
      for(int j = 1; j <= lb; j++)
      {
         if(iLow(_Symbol, g_tf_entry, i-j) <= lo || iLow(_Symbol, g_tf_entry, i+j) <= lo) { is_sl = false; break; }
      }
      if(is_sl && g_swing_count < 100) { g_swing_lows[g_swing_count] = lo; g_swing_count++; }
   }
}

int CheckMarketStructure()
{
   if(g_swing_count < 4) return 0;
   double sh1=0, sh2=0, sl1=0, sl2=0; int shc=0, slc=0;
   for(int i = g_swing_count-1; i >= 0 && (shc < 2 || slc < 2); i--)
   {
      if(g_swing_highs[i] > 0 && shc < 2) { if(shc==0) sh1=g_swing_highs[i]; else sh2=g_swing_highs[i]; shc++; }
      if(g_swing_lows[i] > 0 && slc < 2)  { if(slc==0) sl1=g_swing_lows[i]; else sl2=g_swing_lows[i]; slc++; }
   }
   if(shc >= 2 && slc >= 2)
   {
      if(sh1 > sh2 && sl1 > sl2) return 1;   // HH + HL = Bullish
      if(sh1 < sh2 && sl1 < sl2) return -1;  // LH + LL = Bearish
   }
   return 0;
}

//+------------------------------------------------------------------+
//| INDIVIDUAL STRATEGY SIGNALS                                       |
//+------------------------------------------------------------------+
// Each returns: 1=buy, -1=sell, 0=no signal
// score: confidence 0-5

int StratBreakout(double &score)
{
   score = 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double price = iClose(_Symbol, g_tf_entry, 1);
   int bars = InpBreakoutBars;
   if(Bars(_Symbol, g_tf_entry) <= bars + 2) return 0;

   double hh = iHigh(_Symbol, g_tf_entry, 1);
   double ll = iLow(_Symbol, g_tf_entry, 1);
   for(int i = 2; i <= bars; i++)
   {
      hh = MathMax(hh, iHigh(_Symbol, g_tf_entry, i));
      ll = MathMin(ll, iLow(_Symbol, g_tf_entry, i));
   }
   double buf = InpBreakoutBuffer * atr[0];

   if(price > hh + buf) { score = 3.0; return 1; }
   if(price < ll - buf) { score = 3.0; return -1; }
   return 0;
}

int StratBOS(double &score)
{
   score = 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double price = iClose(_Symbol, g_tf_entry, 1);
   double buf = InpBreakoutBuffer * atr[0];

   double last_sh = 0, last_sl = 0;
   for(int i = 0; i < g_swing_count; i++)
   {
      if(g_swing_highs[i] > 0) last_sh = g_swing_highs[i];
      if(g_swing_lows[i] > 0)  last_sl = g_swing_lows[i];
   }

   if(last_sh > 0 && price > last_sh + buf) { score = 4.0; return 1; }
   if(last_sl > 0 && price < last_sl - buf) { score = 4.0; return -1; }
   return 0;
}

int StratMomentum(double &score)
{
   score = 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double body = iClose(_Symbol,g_tf_entry,1) - iOpen(_Symbol,g_tf_entry,1);
   double range = iHigh(_Symbol,g_tf_entry,1) - iLow(_Symbol,g_tf_entry,1);
   if(range <= 0 || atr[0] <= 0) return 0;

   double body_ratio = MathAbs(body) / range;
   if(body_ratio < InpMomBodyThresh) return 0;
   if(range < 0.5 * atr[0]) return 0;

   // Velocity
   double velocity = 0;
   if(Bars(_Symbol,g_tf_entry) > InpMomVelocity + 1)
      velocity = (iClose(_Symbol,g_tf_entry,1) - iClose(_Symbol,g_tf_entry,InpMomVelocity+1)) / InpMomVelocity;

   if(body > 0 && velocity > InpMomVelocityThresh * atr[0]) { score = 3.0 + body_ratio; return 1; }
   if(body < 0 && velocity < -InpMomVelocityThresh * atr[0]) { score = 3.0 + body_ratio; return -1; }
   return 0;
}

int StratMeanRevert(double &score)
{
   score = 0;
   double rsi[1]; if(CopyBuffer(hRSI_E,0,1,1,rsi)<1) return 0;
   double bb[1]; if(CopyBuffer(hBB_E,0,1,1,bb)<1) return 0;
   double bb_upper[1]; if(CopyBuffer(hBB_E,1,1,1,bb_upper)<1) return 0;
   double bb_lower[1]; if(CopyBuffer(hBB_E,2,1,1,bb_lower)<1) return 0;

   double price = iClose(_Symbol, g_tf_entry, 1);
   double prev_price = iClose(_Symbol, g_tf_entry, 2);

   // Bounce off BB + RSI confirmation
   if(prev_price <= bb_lower[1] && price > bb_lower[0] && rsi[0] < InpRsiOversold)
   { score = 3.5; return 1; }
   if(prev_price >= bb_upper[1] && price < bb_upper[0] && rsi[0] > InpRsiOverbought)
   { score = 3.5; return -1; }
   return 0;
}

int StratEmaPullback(double &score)
{
   score = 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double emaF[1], emaM[1], emaS[1];
   if(CopyBuffer(hEMA_Fast_E,0,1,1,emaF)<1) return 0;
   if(CopyBuffer(hEMA_Mid_E,0,1,1,emaM)<1)  return 0;
   if(CopyBuffer(hEMA_Slow_E,0,1,1,emaS)<1) return 0;
   double rsi[1]; if(CopyBuffer(hRSI_E,0,1,1,rsi)<1) return 0;
   double price = iClose(_Symbol, g_tf_entry, 1);
   double body = price - iOpen(_Symbol, g_tf_entry, 1);

   // Bullish: EMAs aligned, price pulled back to fast EMA
   if(emaF[0] > emaM[0] && emaM[0] > emaS[0])
   {
      double pb = MathAbs(price - emaF[0]);
      if(pb < InpPullbackMaxAtr * atr[0] && body > 0 && rsi[0] > 35 && rsi[0] < 70)
      { score = 3.0; return 1; }
   }
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0])
   {
      double pb = MathAbs(price - emaF[0]);
      if(pb < InpPullbackMaxAtr * atr[0] && body < 0 && rsi[0] < 65 && rsi[0] > 30)
      { score = 3.0; return -1; }
   }
   return 0;
}

int StratLiqGrab(double &score)
{
   score = 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   int bars = 20;
   if(Bars(_Symbol, g_tf_entry) <= bars + 2) return 0;

   double hh = iHigh(_Symbol, g_tf_entry, 1);
   double ll = iLow(_Symbol, g_tf_entry, 1);
   for(int i = 2; i <= bars; i++)
   {
      hh = MathMax(hh, iHigh(_Symbol, g_tf_entry, i));
      ll = MathMin(ll, iLow(_Symbol, g_tf_entry, i));
   }

   double hi_now = iHigh(_Symbol, g_tf_entry, 1);
   double lo_now = iLow(_Symbol, g_tf_entry, 1);
   double close_now = iClose(_Symbol, g_tf_entry, 1);
   double open_now = iOpen(_Symbol, g_tf_entry, 1);

   // Grabbed high then closed bearish
   if(hi_now > hh && close_now < open_now && close_now < hh)
   { score = 3.5; return -1; }
   // Grabbed low then closed bullish
   if(lo_now < ll && close_now > open_now && close_now > ll)
   { score = 3.5; return 1; }
   return 0;
}

int StratOrderBlock(double &score)
{
   score = 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   int lb = InpObLookback;

   for(int i = 1; i <= lb; i++)
   {
      double body_i = iClose(_Symbol,g_tf_entry,i) - iOpen(_Symbol,g_tf_entry,i);
      double range_i = iHigh(_Symbol,g_tf_entry,i) - iLow(_Symbol,g_tf_entry,i);
      if(range_i <= 0) continue;

      // Bullish OB: bearish candle followed by strong bullish move
      if(body_i < 0 && MathAbs(body_i) > InpObStrengthAtr * atr[0])
      {
         // Check if next candle was strongly bullish
         double next_body = iClose(_Symbol,g_tf_entry,i-1) - iOpen(_Symbol,g_tf_entry,i-1);
         if(i-1 >= 0 && next_body > InpObStrengthAtr * atr[0])
         {
            double price = iClose(_Symbol, g_tf_entry, 1);
            double ob_top = MathMax(iOpen(_Symbol,g_tf_entry,i), iClose(_Symbol,g_tf_entry,i));
            if(price <= ob_top + 0.2 * atr[0] && price >= ob_top - 0.3 * atr[0])
            { score = 3.0; return 1; }
         }
      }
      // Bearish OB: bullish candle followed by strong bearish move
      if(body_i > 0 && body_i > InpObStrengthAtr * atr[0])
      {
         double next_body = iClose(_Symbol,g_tf_entry,i-1) - iOpen(_Symbol,g_tf_entry,i-1);
         if(i-1 >= 0 && next_body < -InpObStrengthAtr * atr[0])
         {
            double price = iClose(_Symbol, g_tf_entry, 1);
            double ob_bot = MathMin(iOpen(_Symbol,g_tf_entry,i), iClose(_Symbol,g_tf_entry,i));
            if(price >= ob_bot - 0.2 * atr[0] && price <= ob_bot + 0.3 * atr[0])
            { score = 3.0; return -1; }
         }
      }
   }
   return 0;
}

int StratConfluence(double &score)
{
   score = 0;
   double emaF[1], emaM[1], emaS[1];
   if(CopyBuffer(hEMA_Fast_E,0,1,1,emaF)<1) return 0;
   if(CopyBuffer(hEMA_Mid_E,0,1,1,emaM)<1)  return 0;
   if(CopyBuffer(hEMA_Slow_E,0,1,1,emaS)<1) return 0;
   double rsi[1]; if(CopyBuffer(hRSI_E,0,1,1,rsi)<1) return 0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double price = iClose(_Symbol, g_tf_entry, 1);
   double body = price - iOpen(_Symbol, g_tf_entry, 1);

   int buy_agree = 0, sell_agree = 0;

   // 1. EMA alignment
   if(emaF[0] > emaM[0]) buy_agree++; else sell_agree++;
   // 2. Price vs EMA
   if(price > emaF[0]) buy_agree++; else sell_agree++;
   // 3. RSI
   if(rsi[0] > 50 && rsi[0] < 75) buy_agree++;
   else if(rsi[0] < 50 && rsi[0] > 25) sell_agree++;
   // 4. MACD-like: momentum
   double vel = 0;
   if(Bars(_Symbol,g_tf_entry) > 6)
      vel = (price - iClose(_Symbol,g_tf_entry,6)) / 5;
   if(vel > 0.1 * atr[0]) buy_agree++;
   else if(vel < -0.1 * atr[0]) sell_agree++;
   // 5. Candle direction
   if(body > 0) buy_agree++; else sell_agree++;
   // 6. Range quality
   double range = iHigh(_Symbol,g_tf_entry,1) - iLow(_Symbol,g_tf_entry,1);
   if(range > 0 && MathAbs(body)/range > 0.5)
   {
      if(body > 0) buy_agree++; else sell_agree++;
   }

   if(buy_agree >= InpConfMinAgree) { score = 2.0 + buy_agree * 0.5; return 1; }
   if(sell_agree >= InpConfMinAgree) { score = 2.0 + sell_agree * 0.5; return -1; }
   return 0;
}

//+------------------------------------------------------------------+
//| MASTER SIGNAL GENERATOR                                           |
//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE) return 0;
   if(!InpTradeRanging && g_regime == REGIME_RANGING) return 0;

   DetectSwingPoints();

   // Collect signals from all enabled strategies
   int directions[STRAT_COUNT];
   double scores[STRAT_COUNT];
   ArrayInitialize(directions, 0);
   ArrayInitialize(scores, 0);

   int total_buy_score = 0, total_sell_score = 0;
   int buy_count = 0, sell_count = 0;

   if(InpUseBreakout)     { directions[0] = StratBreakout(scores[0]);     if(directions[0]>0) { total_buy_score += (int)scores[0]; buy_count++; } else if(directions[0]<0) { total_sell_score += (int)scores[0]; sell_count++; } }
   if(InpUseBos)          { directions[1] = StratBOS(scores[1]);          if(directions[1]>0) { total_buy_score += (int)scores[1]; buy_count++; } else if(directions[1]<0) { total_sell_score += (int)scores[1]; sell_count++; } }
   if(InpUseMomentum)     { directions[2] = StratMomentum(scores[2]);     if(directions[2]>0) { total_buy_score += (int)scores[2]; buy_count++; } else if(directions[2]<0) { total_sell_score += (int)scores[2]; sell_count++; } }
   if(InpUseMeanRevert)   { directions[3] = StratMeanRevert(scores[3]);   if(directions[3]>0) { total_buy_score += (int)scores[3]; buy_count++; } else if(directions[3]<0) { total_sell_score += (int)scores[3]; sell_count++; } }
   if(InpUseEmaPullback)  { directions[4] = StratEmaPullback(scores[4]);  if(directions[4]>0) { total_buy_score += (int)scores[4]; buy_count++; } else if(directions[4]<0) { total_sell_score += (int)scores[4]; sell_count++; } }
   if(InpUseLiqGrab)      { directions[5] = StratLiqGrab(scores[5]);      if(directions[5]>0) { total_buy_score += (int)scores[5]; buy_count++; } else if(directions[5]<0) { total_sell_score += (int)scores[5]; sell_count++; } }
   if(InpUseOrderBlock)   { directions[6] = StratOrderBlock(scores[6]);   if(directions[6]>0) { total_buy_score += (int)scores[6]; buy_count++; } else if(directions[6]<0) { total_sell_score += (int)scores[6]; sell_count++; } }
   if(InpUseConfluence)   { directions[7] = StratConfluence(scores[7]);   if(directions[7]>0) { total_buy_score += (int)scores[7]; buy_count++; } else if(directions[7]<0) { total_sell_score += (int)scores[7]; sell_count++; } }

   // Apply regime bonus
   if(g_regime == REGIME_BULLISH)  total_buy_score += 2;
   else if(g_regime == REGIME_BEARISH) total_sell_score += 2;

   // Find winning strategy names
   string winners = "";
   for(int i = 0; i < STRAT_COUNT; i++)
   {
      if(directions[i] != 0)
      {
         string names[] = {"BKO","BOS","MOM","MRV","EMA","LIQ","OBK","CNF"};
         winners += names[i] + "+";
      }
   }

   // DECISION
   int final_dir = 0;
   double final_score = 0;

   if(total_buy_score >= InpMinScore && total_buy_score > total_sell_score)
   {
      if(InpRequire2Strats && buy_count < 2) return 0;
      final_dir = 1;
      final_score = total_buy_score;
   }
   else if(total_sell_score >= InpMinScore && total_sell_score > total_buy_score)
   {
      if(InpRequire2Strats && sell_count < 2) return 0;
      final_dir = -1;
      final_score = total_sell_score;
   }

   if(final_dir != 0)
   {
      sig_type = StringFormat("SC%.0f_%s", final_score, winners);
      if(InpDebugLog) PrintFormat("[v21] SIGNAL: %s Dir=%d Strategies: %s", sig_type, final_dir, winners);
   }

   return final_dir;
}

//+------------------------------------------------------------------+
//| OPEN TRADE                                                        |
//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1];
   if(CopyBuffer(hATR_E,0,1,1,atr)<1) return;

   double entry = (direction > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                  : SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // Structure-based SL
   double structure_sl = 0;
   if(direction > 0)
   {
      double best = 0;
      for(int i = 0; i < g_swing_count; i++)
         if(g_swing_lows[i] > 0 && g_swing_lows[i] < entry && g_swing_lows[i] > best)
            best = g_swing_lows[i];
      structure_sl = (best > 0) ? best - 0.10 * atr[0] : entry - 1.5 * atr[0];
   }
   else
   {
      double best = 999999;
      for(int i = 0; i < g_swing_count; i++)
         if(g_swing_highs[i] > 0 && g_swing_highs[i] > entry && g_swing_highs[i] < best)
            best = g_swing_highs[i];
      structure_sl = (best < 999999) ? best + 0.10 * atr[0] : entry + 1.5 * atr[0];
   }

   double stop_dist = MathAbs(entry - structure_sl);
   double min_stop = 0.5 * atr[0];
   double max_stop = 3.0 * atr[0];
   if(stop_dist < min_stop) stop_dist = min_stop;
   if(stop_dist > max_stop) stop_dist = max_stop;

   double sl = (direction > 0) ? entry - stop_dist : entry + stop_dist;
   double tp = (direction > 0) ? entry + InpTpMult * stop_dist
                               : entry - InpTpMult * stop_dist;

   // Risk-based volume
   double risk_money = g_eq * InpRiskPerTrade;
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tick_size <= 0 || tick_value <= 0) return;
   double loss_per_lot = (stop_dist / tick_size) * tick_value;
   if(loss_per_lot <= 0) return;
   double vol = NormalizeVolume(risk_money / loss_per_lot);

   bool ok = false;
   if(InpLiveExecution)
   {
      if(direction > 0) ok = trade.Buy(vol, _Symbol, 0, NormalizeDouble(sl,_Digits), NormalizeDouble(tp,_Digits), "MITEM_v21");
      else              ok = trade.Sell(vol, _Symbol, 0, NormalizeDouble(sl,_Digits), NormalizeDouble(tp,_Digits), "MITEM_v21");
   }
   else { g_ticket = (ulong)TimeCurrent(); ok = true; }

   if(!ok)
   {
      PrintFormat("[v21] Order FAILED: %d", trade.ResultRetcode());
      g_cooldown = InpCoolDownBars;
      return;
   }

   g_ticket = 0;
   for(int a = 0; a < 8; a++)
   {
      Sleep(70);
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         if(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME) > 12) continue;
         g_ticket = t; break;
      }
      if(g_ticket > 0) break;
   }
   if(g_ticket == 0) g_ticket = trade.ResultOrder();

   g_dir = direction;
   g_entry = entry;
   g_sl = sl;
   g_tp = tp;
   g_orig_risk = stop_dist;
   g_position_volume = vol;
   g_entry_time = TimeCurrent();
   g_bars_held = 0;
   g_trades_today++;

   if(InpDrawSignals) DrawArrow(direction, TimeCurrent(), entry, sig_type);

   PrintFormat("[v21] %s %s @%.5f SL=%.5f TP=%.5f Vol=%.2f Regime=%s",
               sig_type, direction>0?"BUY":"SELL", entry, sl, tp, vol, RegimeToStr(g_regime));
}

double NormalizeVolume(double vol)
{
   double minv = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxv = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0) step = 0.01;
   vol = MathFloor(vol / step) * step;
   if(vol < minv) vol = minv;
   if(vol > maxv) vol = maxv;
   return NormalizeDouble(vol, 2);
}

//+------------------------------------------------------------------+
//| MANAGE POSITION                                                   |
//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)) { g_ticket = 0; return; }
   g_bars_held++;

   double atr[1]; CopyBuffer(hATR_E,0,0,1,atr);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   if(g_bars_held >= InpMaxHoldBars) { ClosePosition("TIME"); return; }

   if(g_dir > 0)
   {
      if(bid <= g_sl) { ClosePosition("STOP"); return; }
      if(bid >= g_tp) { ClosePosition("TARGET"); return; }
   }
   else
   {
      if(ask >= g_sl) { ClosePosition("STOP"); return; }
      if(ask <= g_tp) { ClosePosition("TARGET"); return; }
   }

   double r_now = (g_orig_risk > 0) ? (g_dir > 0 ? (bid-g_entry) : (g_entry-ask)) / g_orig_risk : 0;

   if(InpUseBreakeven && r_now >= InpBeTriggerR)
   {
      double be = (g_dir > 0) ? g_entry + InpBeOffsetPts : g_entry - InpBeOffsetPts;
      if(g_dir > 0 && g_sl < be) { double ns = NormalizeDouble(be,_Digits); if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl = ns; }
      if(g_dir < 0 && g_sl > be) { double ns = NormalizeDouble(be,_Digits); if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl = ns; }
   }

   if(InpUseTrailing && r_now >= InpTrailTriggerR)
   {
      double td = InpTrailDistR * g_orig_risk;
      if(g_dir > 0) { double ns = NormalizeDouble(bid-td,_Digits); if(ns > g_sl && ns > g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl = ns; }
      else          { double ns = NormalizeDouble(ask+td,_Digits); if(ns < g_sl && ns < g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl = ns; }
   }
}

void ClosePosition(string reason)
{
   if(g_ticket == 0) return;
   double exit_p = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(!trade.PositionClose(g_ticket)) return;

   double r = (g_orig_risk > 0) ? (g_dir > 0 ? (exit_p-g_entry) : (g_entry-exit_p)) / g_orig_risk : 0;

   g_trades++; g_total_r += r;
   if(r > 0) g_wins++; else g_losses++;

   if(reason == "TARGET") g_target_exits++;
   else if(reason == "TIME") g_time_exits++;
   else if(reason == "STOP") g_stop_exits++;

   g_daily_pnl += r * g_orig_risk * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) /
                  SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE) * g_position_volume;

   if(r < 0) { g_consec_loss++; g_cooldown = InpCoolDownBars; } else g_consec_loss = 0;
   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -g_eq * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_eq - g_eq) > g_peak_eq * 0.15) g_paused = true;

   PrintFormat("[v21] CLOSE %s R=%+.3f | TotalR=%+.2f", reason, r, g_total_r);
   g_ticket = 0; g_dir = 0; g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                         |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i = 0; i < 30; i++)
   {
      dash_names[i] = "M21_" + IntegerToString(i);
      ObjectCreate(0, dash_names[i], OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, dash_names[i], OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, dash_names[i], OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, dash_names[i], OBJPROP_YDISTANCE, 14 + i * 14);
      ObjectSetString(0, dash_names[i], OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, dash_names[i], OBJPROP_FONTSIZE, 8);
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, clrWhite);
   }
}

void UpdateDashboard()
{
   double wr = g_trades > 0 ? 100.0 * g_wins / g_trades : 0;
   double dd = g_peak_eq > 0 ? (g_peak_eq - g_eq) / g_peak_eq * 100 : 0;
   double atr[1]; CopyBuffer(hATR_E, 0, 0, 1, atr);

   string L[30];
   L[0]  = "=== MITEMSHUB AI v21 MULTI-STRAT ===";
   L[1]  = StringFormat("%s | %s -> %s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   L[2]  = StringFormat("Equity: $%.2f | Peak: $%.2f", g_eq, g_peak_eq);
   L[3]  = StringFormat("Regime: %s | ATR: %.4f", RegimeToStr(g_regime), atr[0]);
   L[4]  = StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f", g_trades, wr, g_total_r);
   L[5]  = StringFormat("Daily: $%.2f | T/d: %d/%d", g_daily_pnl, g_trades_today, InpMaxTradesPerDay);
   L[6]  = StringFormat("Status: %s | CD: %d | ConsecL: %d", g_paused?"PAUSED":"ACTIVE", g_cooldown, g_consec_loss);

   // Strategy stats
   string strats_enabled = "";
   if(InpUseBreakout) strats_enabled += "BKO ";
   if(InpUseBos) strats_enabled += "BOS ";
   if(InpUseMomentum) strats_enabled += "MOM ";
   if(InpUseMeanRevert) strats_enabled += "MRV ";
   if(InpUseEmaPullback) strats_enabled += "EMA ";
   if(InpUseLiqGrab) strats_enabled += "LIQ ";
   if(InpUseOrderBlock) strats_enabled += "OBK ";
   if(InpUseConfluence) strats_enabled += "CNF ";
   L[7]  = StringFormat("Strategies: %s", strats_enabled);
   L[8]  = StringFormat("MinScore: %d | 2+Strat: %s", InpMinScore, InpRequire2Strats?"ON":"OFF");
   L[9]  = StringFormat("Risk: %.2f%% | TP: %.1fxSL | Hold: %d", InpRiskPerTrade*100, InpTpMult, InpMaxHoldBars);
   L[10] = StringFormat("Trail: %.1fR/%.1fR | BE: %.1fR | T/T/S: %d/%d/%d",
                         InpTrailTriggerR, InpTrailDistR, InpBeTriggerR, g_target_exits, g_time_exits, g_stop_exits);

   int line = 11;
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      double cur = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double r_now = g_orig_risk > 0 ? (g_dir>0?(cur-g_entry):(g_entry-cur))/g_orig_risk : 0;
      double hrs = (double)(TimeCurrent() - g_entry_time) / 3600.0;
      L[line++] = StringFormat("OPEN %s @%.5f", g_dir>0?"BUY":"SELL", g_entry);
      L[line++] = StringFormat("SL: %.5f | TP: %.5f", g_sl, g_tp);
      L[line++] = StringFormat("R: %+.2f | Held: %.1fh", r_now, hrs);
   }
   while(line < 30) L[line++] = "";

   for(int i = 0; i < 30; i++)
   {
      ObjectSetString(0, dash_names[i], OBJPROP_TEXT, L[i]);
      color c = clrWhite;
      if(i == 0) c = clrGold;
      if(i == 3)
      {
         if(g_regime==REGIME_BULLISH) c = clrLime;
         else if(g_regime==REGIME_BEARISH) c = clrRed;
         else if(g_regime==REGIME_RANGING) c = clrYellow;
         else c = clrGray;
      }
      if(i == 5) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i == 6) c = g_paused ? clrRed : clrLime;
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, c);
   }
   ChartRedraw();
}

string RegimeToStr(ENUM_REGIME r)
{
   if(r==REGIME_BULLISH) return "BULLISH";
   if(r==REGIME_BEARISH) return "BEARISH";
   if(r==REGIME_RANGING) return "RANGING";
   return "NO_TRADE";
}

void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name = "M21_" + tag + "_" + IntegerToString((int)t);
   if(ObjectFind(0,name)>=0) ObjectDelete(0,name);
   ObjectCreate(0,name,OBJ_ARROW,0,t,price);
   ObjectSetInteger(0,name,OBJPROP_ARROWCODE, dir>0?233:234);
   ObjectSetInteger(0,name,OBJPROP_COLOR, dir>0?clrLime:clrRed);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
}
//+------------------------------------------------------------------+
