//+------------------------------------------------------------------+
//|                                         MitemshubAI_v19_0.mq5    |
//|                     MITEMSHUB AI MARKET ENGINE v19.0              |
//|   Multi-Layer Decision Engine • Step Index • Structure + Scoring  |
//|   Risk-Based Sizing • M5 Confirmation • Trade Journal             |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "19.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| ENUMS                                                              |
//+------------------------------------------------------------------+
enum ENUM_REGIME {
   REGIME_TREND_UP,
   REGIME_TREND_DOWN,
   REGIME_RANGE,
   REGIME_COMPRESSION,
   REGIME_EXPANSION,
   REGIME_NO_TRADE
};

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Instrument ==="
input string InpSymbol = "Step Index";

input group "=== Session Filter (UTC) ==="
input bool   InpUseSessionFilter = false;
input int    InpSessionStartHour = 0;
input int    InpSessionEndHour   = 24;

input group "=== Multi-Timeframe Regime ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input int    InpSwingLookback    = 5;         // Bars to confirm swing points

input group "=== Structure Detection ==="
input int    InpStructureBars    = 20;        // Bars to look back for structure
input double InpBosMinATR        = 0.5;       // Min ATR move for Break of Structure

input group "=== Scoring Thresholds ==="
input int    InpMinScore         = 70;        // Minimum 0-100 score to trade
input int    InpMinTrend         = 15;        // Min trend score (of 25)
input int    InpMinStructure     = 10;        // Min structure score (of 25)

input group "=== Risk Engine ==="
input double InpRiskPerTrade     = 0.01;      // 1% risk per trade
input double InpMaxDailyLossPct  = 0.03;      // 3% max daily loss
input int    InpMaxConsecLoss    = 3;         // Pause after N consecutive losses
input int    InpMaxTradesPerDay  = 5;         // Max trades per day
input int    InpCoolDownBars     = 2;         // Bars cooldown after loss
input double InpMaxDDPct         = 0.10;      // 10% max drawdown to pause

input group "=== SL/TP (Volatility Aware) ==="
input double InpSL_AtrMult       = 1.5;       // SL = max(structure, ATR x mult)
input double InpTP_RewardMult    = 2.0;       // TP = SL distance x reward multiplier
input double InpMinSL_Pts        = 2.0;       // Minimum SL in points
input double InpMaxSL_Pts        = 15.0;      // Maximum SL in points

input group "=== Trade Management ==="
input double InpBE_RTrigger      = 0.8;       // Move to BE after 0.8R profit
input double InpBE_Offset        = 0.2;       // BE offset above entry (points)
input double InpTrail_RTrigger   = 1.0;       // Start trailing after 1.0R
input double InpTrailDist_ATR    = 0.8;       // Trail distance = ATR x mult
input double InpLock_RTrigger    = 1.5;       // Lock profit after 1.5R
input double InpLockMin_Pts      = 1.0;       // Minimum lock profit (points)
input int    InpMaxHoldBars      = 16;        // Max hold (M15 bars = 4 hours)

input group "=== M5 Confirmation ==="
input bool   InpUseM5Confirm     = true;      // Require M5 alignment
input int    InpM5EmaFast        = 8;         // M5 fast EMA
input int    InpM5EmaSlow        = 21;        // M5 slow EMA

input group "=== Execution ==="
input long   InpMagic            = 7788190;
input int    InpMaxSlippagePts   = 20;
input int    InpWarmupBars       = 300;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = false;     // Default: PAPER until verified
input bool   InpDebugLog         = true;
input bool   InpWriteJournal     = true;      // Write trade journal to CSV

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES g_tf_entry  = PERIOD_M15;
ENUM_TIMEFRAMES g_tf_regime = PERIOD_H1;
ENUM_TIMEFRAMES g_tf_m5     = PERIOD_M5;

// Indicator handles
int hR_EmaF_R, hR_EmaM_R, hR_EmaS_R;      // Regime (H1)
int hE_EmaF, hE_EmaM, hE_RSI, hE_ATR;     // Entry (M15)
int hE_EmaS;                                // M15 slow EMA for structure
int hM5_EmaF, hM5_EmaM;                     // M5 confirmation

// State
double   g_eq = 0, g_peak_eq = 0, g_daily_pnl = 0;
datetime g_day_start = 0;
int      g_daily_trades = 0, g_consec_loss = 0;
bool     g_paused = false;
int      g_cooldown = 0;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

// Score components
int      g_score_trend = 0, g_score_structure = 0, g_score_momentum = 0;
int      g_score_volatility = 0, g_score_location = 0, g_score_confirm = 0;
int      g_total_score = 0;

// Position state
ulong    g_ticket = 0;
int      g_dir = 0;
double   g_entry = 0, g_sl = 0, g_tp = 0;
double   g_orig_sl_dist = 0;          // Original SL distance in points
double   g_position_volume = 0;
datetime g_entry_time = 0;
int      g_bars_held = 0;
int      g_entry_score = 0;           // Score at entry
string   g_entry_regime = "";

// Structure detection
double   g_swing_highs[];
double   g_swing_lows[];
int      g_swing_count = 0;
bool     g_is_bullish_structure = false;
bool     g_is_bearish_structure = false;
bool     g_bos_detected = false;

// Session stats
int      g_trades = 0, g_wins = 0, g_losses = 0;
int      g_target_exits = 0, g_trail_exits = 0, g_be_exits = 0;
int      g_time_exits = 0, g_stop_exits = 0, g_lock_exits = 0;
double   g_total_r = 0;
double   g_best_trade = 0, g_worst_trade = 0;

// ATR percentile
double   g_atr_hist[];
int      g_atr_hist_count = 0;

string   g_journal_file = "";

// Dashboard
string   g_dash_names[26];

//+------------------------------------------------------------------+
//| INIT                                                               |
//+------------------------------------------------------------------+
int OnInit()
{
   if(!SymbolSelect(InpSymbol, true))
   {
      PrintFormat("v19.0: Cannot select %s", InpSymbol);
      return INIT_FAILED;
   }

   g_tf_entry  = (ENUM_TIMEFRAMES)Period();
   g_tf_regime = GetRegimeTF(g_tf_entry);
   g_tf_m5     = PERIOD_M5;

   // Regime indicators (H1)
   hR_EmaF_R = iMA(InpSymbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hR_EmaM_R = iMA(InpSymbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hR_EmaS_R = iMA(InpSymbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   // Entry indicators (M15)
   hE_EmaF = iMA(InpSymbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hE_EmaM = iMA(InpSymbol, g_tf_entry, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hE_EmaS = iMA(InpSymbol, g_tf_entry, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hE_RSI  = iRSI(InpSymbol, g_tf_entry, 14, PRICE_CLOSE);
   hE_ATR  = iATR(InpSymbol, g_tf_entry, 14);

   // M5 confirmation
   hM5_EmaF = iMA(InpSymbol, g_tf_m5, InpM5EmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hM5_EmaM = iMA(InpSymbol, g_tf_m5, InpM5EmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   if(hR_EmaF_R==INVALID_HANDLE || hR_EmaM_R==INVALID_HANDLE || hR_EmaS_R==INVALID_HANDLE ||
      hE_EmaF==INVALID_HANDLE || hE_EmaM==INVALID_HANDLE || hE_EmaS==INVALID_HANDLE ||
      hE_RSI==INVALID_HANDLE || hE_ATR==INVALID_HANDLE ||
      hM5_EmaF==INVALID_HANDLE || hM5_EmaM==INVALID_HANDLE)
   {
      Print("v19.0: Handle creation failed");
      return INIT_FAILED;
   }

   ArrayResize(g_atr_hist, 200);
   ArrayInitialize(g_atr_hist, 0.0);

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(InpSymbol);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   RecoverPosition();
   if(InpDrawDashboard) CreateDashboard();

   // Initialize journal
   if(InpWriteJournal) InitJournal();

   PrintFormat("MITEMSHUB AI v19.0 | %s %s→%s | Risk=%.1f%% | MinScore=%d",
               InpSymbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpRiskPerTrade*100, InpMinScore);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M1)  return PERIOD_M5;
   if(tf == PERIOD_M5)  return PERIOD_M15;
   if(tf == PERIOD_M15) return PERIOD_H1;
   if(tf == PERIOD_H1)  return PERIOD_H4;
   if(tf == PERIOD_H4)  return PERIOD_D1;
   return PERIOD_H4;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hR_EmaF_R); IndicatorRelease(hR_EmaM_R); IndicatorRelease(hR_EmaS_R);
   IndicatorRelease(hE_EmaF); IndicatorRelease(hE_EmaM); IndicatorRelease(hE_EmaS);
   IndicatorRelease(hE_RSI); IndicatorRelease(hE_ATR);
   IndicatorRelease(hM5_EmaF); IndicatorRelease(hM5_EmaM);

   for(int i=0; i<26; i++) ObjectDelete(0, g_dash_names[i]);

   double wr = g_trades > 0 ? 100.0 * g_wins / g_trades : 0;
   double dd = g_peak_eq > 0 ? (g_peak_eq - g_eq) / g_peak_eq * 100 : 0;

   Print("========================================");
   PrintFormat("v19.0 SESSION | Trades:%d WR:%.1f%% TotalR:%+.2f", g_trades, wr, g_total_r);
   PrintFormat("Exits → T:%d Tr:%d Be:%d Lk:%d Tm:%d St:%d",
               g_target_exits, g_trail_exits, g_be_exits, g_lock_exits, g_time_exits, g_stop_exits);
   PrintFormat("Best:%+.2fR Worst:%+.2fR MaxDD:%.1f%%", g_best_trade, g_worst_trade, dd);
   Print("========================================");
}

//+------------------------------------------------------------------+
//| ONTICK                                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   static datetime last_bar = 0;
   datetime cur_bar = iTime(InpSymbol, g_tf_entry, 0);
   if(cur_bar == last_bar)
   {
      if(InpDrawDashboard) UpdateDashboard();
      return;
   }
   last_bar = cur_bar;

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_eq > g_peak_eq) g_peak_eq = g_eq;

   // Daily reset
   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start)
   {
      g_day_start = ds;
      g_daily_trades = 0;
      g_daily_pnl = 0;
      g_paused = false;
   }

   // Check pause conditions
   if(g_eq < g_peak_eq * (1.0 - InpMaxDDPct)) g_paused = true;
   if(g_daily_pnl < -AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxDailyLossPct) g_paused = true;

   // Cooldown
   if(g_cooldown > 0) g_cooldown--;

   // Manage open position
   if(g_ticket > 0)
   {
      if(PositionSelectByTicket(g_ticket))
         ManagePosition();
      else
         g_ticket = 0;
   }

   // Entry
   if(g_ticket == 0 && !g_paused && g_daily_trades < InpMaxTradesPerDay &&
      g_cooldown == 0 &&
      Bars(InpSymbol, g_tf_entry) >= InpWarmupBars && IsInSession())
   {
      // Run the full scoring engine
      int score = CalculateSetupScore();

      if(score >= InpMinScore)
      {
         string sig = StringFormat("SCORE_%d", score);
         int dir = GetScoredDirection();
         if(dir != 0)
            OpenTrade(dir, sig, score);
      }
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| SESSION                                                            |
//+------------------------------------------------------------------+
bool IsInSession()
{
   if(!InpUseSessionFilter) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int h = dt.hour;
   if(InpSessionStartHour < InpSessionEndHour)
      return (h >= InpSessionStartHour && h < InpSessionEndHour);
   return (h >= InpSessionStartHour || h < InpSessionEndHour);
}

//+------------------------------------------------------------------+
//| RECOVER POSITION                                                   |
//+------------------------------------------------------------------+
void RecoverPosition()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != InpSymbol) continue;

      g_ticket = t;
      g_dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      g_entry = PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl = PositionGetDouble(POSITION_SL);
      g_tp = PositionGetDouble(POSITION_TP);
      g_position_volume = PositionGetDouble(POSITION_VOLUME);
      g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held = 0;

      double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
      if(point > 0)
         g_orig_sl_dist = MathAbs(g_entry - g_sl) / point;

      PrintFormat("v19.0: Recovered #%d %s @%.5f SL=%.5f TP=%.5f", t, g_dir>0?"BUY":"SELL", g_entry, g_sl, g_tp);
      break;
   }
}

//+------------------------------------------------------------------+
//| LAYER 1: REGIME DETECTION                                         |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hR_EmaF_R,0,1,1,emaF)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hR_EmaM_R,0,1,1,emaM)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hR_EmaS_R,0,1,1,emaS)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hE_ATR,0,1,1,atr)<1) return REGIME_NO_TRADE;

   double price = iClose(InpSymbol, g_tf_regime, 1);

   // ATR percentile for compression/expansion
   UpdateATRHistory(atr[0]);
   double pct = CalcATRPercentile(atr[0]);

   // Compression: ATR below 15th percentile
   if(pct < 15.0) return REGIME_COMPRESSION;

   // Expansion: ATR above 85th percentile
   if(pct > 85.0) return REGIME_EXPANSION;

   // Trend detection with EMA alignment + separation
   double sep = MathAbs(emaF[0] - emaM[0]) / atr[0];

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0] && sep >= 0.2)
      return REGIME_TREND_UP;
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0] && sep >= 0.2)
      return REGIME_TREND_DOWN;

   return REGIME_RANGE;
}

//+------------------------------------------------------------------+
//| LAYER 2: STRUCTURE DETECTION                                      |
//+------------------------------------------------------------------+
void DetectStructure()
{
   g_swing_count = 0;
   g_is_bullish_structure = false;
   g_is_bearish_structure = false;
   g_bos_detected = false;

   int lookback = InpStructureBars + 5;
   if(Bars(InpSymbol, g_tf_entry) < lookback) return;

   double highs[], lows[];
   ArrayResize(highs, lookback);
   ArrayResize(lows, lookback);

   for(int i = 1; i < lookback; i++)
   {
      highs[i-1] = iHigh(InpSymbol, g_tf_entry, i);
      lows[i-1]  = iLow(InpSymbol, g_tf_entry, i);
   }

   // Find swing highs and lows
   int swing_high_bars[];
   int swing_low_bars[];
   ArrayResize(swing_high_bars, 0);
   ArrayResize(swing_low_bars, 0);

   for(int i = InpSwingLookback; i < lookback - InpSwingLookback; i++)
   {
      // Swing high: bar high is highest in lookback window
      bool is_swing_high = true;
      for(int j = i - InpSwingLookback; j <= i + InpSwingLookback; j++)
      {
         if(j != i && highs[j] >= highs[i]) { is_swing_high = false; break; }
      }
      if(is_swing_high)
      {
         int sz = ArraySize(swing_high_bars);
         ArrayResize(swing_high_bars, sz+1);
         swing_high_bars[sz] = i;
      }

      // Swing low: bar low is lowest in lookback window
      bool is_swing_low = true;
      for(int j = i - InpSwingLookback; j <= i + InpSwingLookback; j++)
      {
         if(j != i && lows[j] <= lows[i]) { is_swing_low = false; break; }
      }
      if(is_swing_low)
      {
         int sz = ArraySize(swing_low_bars);
         ArrayResize(swing_low_bars, sz+1);
         swing_low_bars[sz] = i;
      }
   }

   // Analyze structure: HH/HL = bullish, LH/LL = bearish
   double atr[1];
   CopyBuffer(hE_ATR, 0, 1, 1, atr);
   double bos_threshold = InpBosMinATR * atr[0];

   if(ArraySize(swing_high_bars) >= 2 && ArraySize(swing_low_bars) >= 2)
   {
      double sh1 = highs[swing_high_bars[0]];  // Most recent swing high
      double sh2 = highs[swing_high_bars[1]];  // Previous swing high
      double sl1 = lows[swing_low_bars[0]];    // Most recent swing low
      double sl2 = lows[swing_low_bars[1]];    // Previous swing low

      // Bullish structure: Higher High + Higher Low
      if(sh1 > sh2 && sl1 > sl2)
      {
         g_is_bullish_structure = true;
         g_bos_detected = (sh1 - sh2) > bos_threshold;
      }
      // Bearish structure: Lower High + Lower Low
      else if(sh1 < sh2 && sl1 < sl2)
      {
         g_is_bearish_structure = true;
         g_bos_detected = (sh2 - sh1) > bos_threshold;
      }
   }
}

//+------------------------------------------------------------------+
//| LAYER 3: MOMENTUM ANALYSIS                                        |
//+------------------------------------------------------------------+
double CalcMomentumScore(int direction)
{
   double emaF[1], emaM[1], rsi[1], atr[1];
   CopyBuffer(hE_EmaF, 0, 1, 1, emaF);
   CopyBuffer(hE_EmaM, 0, 1, 1, emaM);
   CopyBuffer(hE_RSI, 0, 1, 1, rsi);
   CopyBuffer(hE_ATR, 0, 1, 1, atr);

   double price = iClose(InpSymbol, g_tf_entry, 1);
   double prev  = iClose(InpSymbol, g_tf_entry, 2);
   double body  = price - prev;
   double body_pct = (atr[0] > 0) ? MathAbs(body) / atr[0] : 0;

   double score = 0;

   // EMA alignment on entry TF (0-5)
   if(direction > 0 && emaF[0] > emaM[0]) score += 3;
   if(direction < 0 && emaF[0] < emaM[0]) score += 3;
   if(body_pct > 0.3) score += 2; // Strong body

   // RSI position (0-5)
   if(direction > 0 && rsi[0] > 45 && rsi[0] < 68) score += 3;
   if(direction < 0 && rsi[0] < 55 && rsi[0] > 32) score += 3;
   if(body_pct > 0.5) score += 2; // Very strong body

   // Consecutive candles (0-5)
   int consec = 0;
   for(int i = 1; i <= 5; i++)
   {
      double b = iClose(InpSymbol, g_tf_entry, i) - iClose(InpSymbol, g_tf_entry, i+1);
      if((direction > 0 && b > 0) || (direction < 0 && b < 0))
         consec++;
      else break;
   }
   score += MathMin(consec, 5);

   return MathMin(score, 15); // Max 15
}

//+------------------------------------------------------------------+
//| LAYER 4: VOLATILITY ANALYSIS                                      |
//+------------------------------------------------------------------+
double CalcVolatilityScore()
{
   double atr[1];
   CopyBuffer(hE_ATR, 0, 1, 1, atr);
   double pct = CalcATRPercentile(atr[0]);
   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);

   double score = 0;

   // ATR percentile sweet spot: 20-70 (0-10)
   if(pct >= 20 && pct <= 70) score += 8;
   else if(pct >= 10 && pct <= 85) score += 4;
   // Too low (<10) or too high (>85): penalty
   else score += 0;

   // ATR absolute check: must be above minimum
   double atr_pts = atr[0] / point;
   if(atr_pts >= InpMinSL_Pts) score += 4;
   else score += 1;

   // ATR not extreme
   if(pct > 15 && pct < 90) score += 3;

   return MathMin(score, 15); // Max 15
}

//+------------------------------------------------------------------+
//| LAYER 5: LOCATION ANALYSIS                                        |
//+------------------------------------------------------------------+
double CalcLocationScore(int direction)
{
   double atr[1];
   CopyBuffer(hE_ATR, 0, 1, 1, atr);

   // Get recent range
   int lookback = 20;
   double hh = iHigh(InpSymbol, g_tf_entry, 1);
   double ll = iLow(InpSymbol, g_tf_entry, 1);
   for(int i = 2; i <= lookback; i++)
   {
      hh = MathMax(hh, iHigh(InpSymbol, g_tf_entry, i));
      ll = MathMin(ll, iLow(InpSymbol, g_tf_entry, i));
   }

   double price = iClose(InpSymbol, g_tf_entry, 1);
   double range = hh - ll;
   if(range <= 0) return 0;

   double position_in_range = (price - ll) / range; // 0=bottom, 1=top

   double score = 0;

   // For BUY: prefer entry in discount zone (bottom 40%)
   if(direction > 0)
   {
      if(position_in_range < 0.4) score += 8;      // Discount zone
      else if(position_in_range < 0.6) score += 5;  // Middle
      else score += 2;                                // Premium - less ideal
   }
   // For SELL: prefer entry in premium zone (top 40%)
   else
   {
      if(position_in_range > 0.6) score += 8;
      else if(position_in_range > 0.4) score += 5;
      else score += 2;
   }

   // Distance from structure
   double dist_from_mid = MathAbs(position_in_range - 0.5);
   if(dist_from_mid > 0.2) score += 2; // Near extremes

   return MathMin(score, 10); // Max 10
}

//+------------------------------------------------------------------+
//| LAYER 6: M5 CONFIRMATION                                          |
//+------------------------------------------------------------------+
double CalcConfirmationScore(int direction)
{
   if(!InpUseM5Confirm) return 5; // Full score if disabled

   double emaF5[1], emaM5[1];
   if(CopyBuffer(hM5_EmaF, 0, 1, 1, emaF5) < 1) return 3;
   if(CopyBuffer(hM5_EmaM, 0, 1, 1, emaM5) < 1) return 3;

   double score = 0;

   // M5 EMA alignment (0-5)
   if(direction > 0 && emaF5[0] > emaM5[0]) score += 5;
   else if(direction < 0 && emaF5[0] < emaM5[0]) score += 5;
   else score += 0;

   // M5 price above/below EMAs (0-3)
   double price5 = iClose(InpSymbol, g_tf_m5, 1);
   if(direction > 0 && price5 > emaF5[0]) score += 3;
   else if(direction < 0 && price5 < emaF5[0]) score += 3;
   else score += 0;

   // M5 candle direction (0-2)
   double body5 = iClose(InpSymbol, g_tf_m5, 1) - iOpen(InpSymbol, g_tf_m5, 1);
   if(direction > 0 && body5 > 0) score += 2;
   else if(direction < 0 && body5 < 0) score += 2;

   return MathMin(score, 10); // Max 10
}

//+------------------------------------------------------------------+
//| MASTER SCORING ENGINE                                              |
//+------------------------------------------------------------------+
int CalculateSetupScore()
{
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE) return 0;

   // Detect structure
   DetectStructure();

   int direction = 0;

   // Determine direction from structure + regime
   if(g_regime == REGIME_TREND_UP || (g_regime == REGIME_RANGE && g_is_bullish_structure))
      direction = 1;
   else if(g_regime == REGIME_TREND_DOWN || (g_regime == REGIME_RANGE && g_is_bearish_structure))
      direction = -1;
   else
      return 0; // No clear direction

   // Disqualify if structure contradicts
   if(direction > 0 && g_is_bearish_structure) return 0;
   if(direction < 0 && g_is_bullish_structure) return 0;

   // ── SCORE EACH LAYER ──

   // TREND (25 points)
   g_score_trend = 0;
   if(g_regime == REGIME_TREND_UP || g_regime == REGIME_TREND_DOWN) g_score_trend += 15;
   else if(g_regime == REGIME_RANGE) g_score_trend += 5;
   else if(g_regime == REGIME_EXPANSION) g_score_trend += 10;

   // EMA alignment on entry TF
   double emaF[1], emaM[1], emaS[1];
   CopyBuffer(hE_EmaF, 0, 1, 1, emaF);
   CopyBuffer(hE_EmaM, 0, 1, 1, emaM);
   CopyBuffer(hE_EmaS, 0, 1, 1, emaS);

   if(direction > 0 && emaF[0] > emaM[0] && emaM[0] > emaS[0]) g_score_trend += 10;
   else if(direction < 0 && emaF[0] < emaM[0] && emaM[0] < emaS[0]) g_score_trend += 10;
   else g_score_trend += 3;

   g_score_trend = MathMin(g_score_trend, 25);

   // STRUCTURE (25 points)
   g_score_structure = 0;
   if(direction > 0 && g_is_bullish_structure) g_score_structure += 15;
   else if(direction < 0 && g_is_bearish_structure) g_score_structure += 15;
   else g_score_structure += 5;

   if(g_bos_detected) g_score_structure += 10;
   else g_score_structure += 3;

   g_score_structure = MathMin(g_score_structure, 25);

   // MOMENTUM (15 points)
   g_score_momentum = (int)MathRound(CalcMomentumScore(direction));

   // VOLATILITY (15 points)
   g_score_volatility = (int)MathRound(CalcVolatilityScore());

   // LOCATION (10 points)
   g_score_location = (int)MathRound(CalcLocationScore(direction));

   // CONFIRMATION (10 points)
   g_score_confirm = (int)MathRound(CalcConfirmationScore(direction));

   // TOTAL
   g_total_score = g_score_trend + g_score_structure + g_score_momentum +
                   g_score_volatility + g_score_location + g_score_confirm;

   return g_total_score;
}

//+------------------------------------------------------------------+
int GetScoredDirection()
{
   if(g_regime == REGIME_TREND_UP || (g_regime == REGIME_RANGE && g_is_bullish_structure))
      return 1;
   if(g_regime == REGIME_TREND_DOWN || (g_regime == REGIME_RANGE && g_is_bearish_structure))
      return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| OPEN TRADE (Risk-Based Sizing)                                     |
//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type, int score)
{
   double atr[1];
   if(CopyBuffer(hE_ATR, 0, 1, 1, atr) < 1) return;

   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);

   double entry = (direction > 0) ? SymbolInfoDouble(InpSymbol, SYMBOL_ASK)
                                  : SymbolInfoDouble(InpSymbol, SYMBOL_BID);

   // ── VOLATILITY-AWARE SL ──
   // Structure-based SL: nearest swing against trade direction
   double structure_sl_dist = 0;
   if(direction > 0)
   {
      double swing = iLow(InpSymbol, g_tf_entry, 1);
      for(int k = 2; k <= 6; k++) swing = MathMin(swing, iLow(InpSymbol, g_tf_entry, k));
      structure_sl_dist = (entry - swing) / point;
   }
   else
   {
      double swing = iHigh(InpSymbol, g_tf_entry, 1);
      for(int k = 2; k <= 6; k++) swing = MathMax(swing, iHigh(InpSymbol, g_tf_entry, k));
      structure_sl_dist = (swing - entry) / point;
   }

   double atr_sl_dist = InpSL_AtrMult * atr[0] / point;

   // Use the larger of structure or ATR-based SL
   double sl_pts = MathMax(structure_sl_dist, atr_sl_dist);

   // Apply bounds
   if(sl_pts < InpMinSL_Pts) sl_pts = InpMinSL_Pts;
   if(sl_pts > InpMaxSL_Pts) sl_pts = InpMaxSL_Pts;

   // ── RISK-BASED POSITION SIZING ──
   double sl_dist = sl_pts * point;
   double tp_dist = sl_pts * InpTP_RewardMult * point;

   double sl = (direction > 0) ? entry - sl_dist : entry + sl_dist;
   double tp = (direction > 0) ? entry + tp_dist : entry - tp_dist;

   // Calculate volume from risk, NOT margin
   double risk_money = g_eq * InpRiskPerTrade;
   double tick_val = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size <= 0 || tick_val <= 0) return;

   double ticks_to_sl = sl_dist / tick_size;
   double loss_per_lot = ticks_to_sl * tick_val;
   if(loss_per_lot <= 0) return;

   double vol = risk_money / loss_per_lot;

   // Normalize volume
   double minv = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
   double maxv = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP);
   if(step <= 0) step = 0.01;
   vol = MathFloor(vol / step) * step;
   if(vol < minv) vol = minv;
   if(vol > maxv) vol = maxv;

   // Verify margin is sufficient
   double margin_needed = 0;
   if(!OrderCalcMargin(ORDER_TYPE_BUY, InpSymbol, vol, entry, margin_needed))
   {
      if(InpDebugLog) Print("v19.0: OrderCalcMargin failed — no trade");
      return;
   }
   if(margin_needed > g_eq * 0.90)
   {
      // Reduce volume to fit within 90% margin
      vol = vol * (g_eq * 0.90 / margin_needed);
      vol = MathFloor(vol / step) * step;
      if(vol < minv) vol = minv;
   }

   // Check margin one final time
   double final_margin = 0;
   if(!OrderCalcMargin(ORDER_TYPE_BUY, InpSymbol, vol, entry, final_margin))
   {
      if(InpDebugLog) Print("v19.0: Final margin check failed");
      return;
   }

   bool ok = false;
   if(InpLiveExecution)
   {
      if(direction > 0)
         ok = trade.Buy(vol, InpSymbol, 0, NormalizeDouble(sl, digits), NormalizeDouble(tp, digits),
                        StringFormat("V19_S%d", score));
      else
         ok = trade.Sell(vol, InpSymbol, 0, NormalizeDouble(sl, digits), NormalizeDouble(tp, digits),
                         StringFormat("V19_S%d", score));
   }
   else
   {
      // Paper mode: simulate
      g_ticket = (ulong)TimeCurrent();
      ok = true;
   }

   if(!ok)
   {
      PrintFormat("v19.0 Order FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      g_consec_loss++;
      if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
      return;
   }

   // Ticket recovery
   g_ticket = 0;
   for(int attempt = 0; attempt < 8; attempt++)
   {
      Sleep(70);
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if(PositionGetString(POSITION_SYMBOL) != InpSymbol) continue;
         if(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME) > 15) continue;
         g_ticket = t; break;
      }
      if(g_ticket > 0) break;
   }
   if(g_ticket == 0) g_ticket = trade.ResultOrder();

   g_dir = direction;
   g_entry = entry;
   g_sl = sl;
   g_tp = tp;
   g_orig_sl_dist = sl_pts;
   g_position_volume = vol;
   g_entry_time = TimeCurrent();
   g_bars_held = 0;
   g_entry_score = score;
   g_entry_regime = RegimeToStr(g_regime);

   if(InpDrawSignals) DrawArrow(direction, TimeCurrent(), entry, sig_type);

   double risk_dollar = vol * loss_per_lot;
   double reward_dollar = risk_dollar * InpTP_RewardMult;

   PrintFormat("[v19.0] %s %s @%.5f SL=%.5f (%.1fpts) TP=%.5f Vol=%.2f Risk=$%.2f Reward=$%.2f Score=%d Regime=%s",
               sig_type, direction>0?"BUY":"SELL", entry, sl, sl_pts, tp, vol,
               risk_dollar, reward_dollar, score, RegimeToStr(g_regime));
}

//+------------------------------------------------------------------+
//| MANAGE POSITION (R-Multiple Based)                                 |
//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)) { g_ticket = 0; return; }
   g_bars_held++;

   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   double atr[1];
   CopyBuffer(hE_ATR, 0, 0, 1, atr);

   double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   double current = (g_dir > 0) ? bid : ask;

   // Current R
   double current_r = (g_orig_sl_dist > 0) ?
      ((g_dir > 0) ? (current - g_entry) : (g_entry - current)) / (g_orig_sl_dist * point) : 0;

   // ── TIME EXIT ──
   if(g_bars_held >= InpMaxHoldBars)
   {
      ClosePosition("TIME");
      return;
   }

   // ── HARD SL/TP CHECK ──
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

   // ── BREAKEVEN (R-multiple based) ──
   if(current_r >= InpBE_RTrigger && g_sl != NormalizeDouble(g_entry + InpBE_Offset * point * g_dir, digits))
   {
      double new_sl = NormalizeDouble(g_entry + InpBE_Offset * point * g_dir, digits);
      bool valid = false;
      if(g_dir > 0) valid = (new_sl > g_sl);
      else valid = (new_sl < g_sl);

      if(valid)
      {
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
         {
            // Verify modification actually took effect
            if(PositionSelectByTicket(g_ticket))
            {
               double actual_sl = PositionGetDouble(POSITION_SL);
               if(MathAbs(actual_sl - new_sl) < point * 2)
                  g_sl = new_sl;
            }
         }
         else
         {
            if(InpDebugLog) PrintFormat("v19.0 BE modify failed: %d", trade.ResultRetcode());
         }
      }
   }

   // ── TRAILING (R-multiple based, ATR distance) ──
   if(current_r >= InpTrail_RTrigger && atr[0] > 0)
   {
      double trail_dist = InpTrailDist_ATR * atr[0];
      double new_sl = 0;
      bool valid = false;

      if(g_dir > 0)
      {
         new_sl = NormalizeDouble(bid - trail_dist, digits);
         valid = (new_sl > g_sl && new_sl > g_entry);
      }
      else
      {
         new_sl = NormalizeDouble(ask + trail_dist, digits);
         valid = (new_sl < g_sl && new_sl < g_entry);
      }

      if(valid)
      {
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
         {
            if(PositionSelectByTicket(g_ticket))
            {
               double actual_sl = PositionGetDouble(POSITION_SL);
               if(MathAbs(actual_sl - new_sl) < point * 2)
                  g_sl = new_sl;
            }
         }
      }
   }

   // ── PROFIT LOCK (R-multiple based) ──
   if(current_r >= InpLock_RTrigger)
   {
      double lock_level = InpLockMin_Pts * point;
      double new_sl = 0;
      bool valid = false;

      if(g_dir > 0)
      {
         new_sl = NormalizeDouble(g_entry + lock_level, digits);
         valid = (new_sl > g_sl);
      }
      else
      {
         new_sl = NormalizeDouble(g_entry - lock_level, digits);
         valid = (new_sl < g_sl);
      }

      if(valid)
      {
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
         {
            if(PositionSelectByTicket(g_ticket))
            {
               double actual_sl = PositionGetDouble(POSITION_SL);
               if(MathAbs(actual_sl - new_sl) < point * 2)
                  g_sl = new_sl;
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| CLOSE POSITION                                                     |
//+------------------------------------------------------------------+
void ClosePosition(string reason)
{
   if(g_ticket == 0) return;

   double exit_price = (g_dir > 0) ? SymbolInfoDouble(InpSymbol, SYMBOL_BID)
                                   : SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);

   if(!trade.PositionClose(g_ticket))
   {
      PrintFormat("v19.0 Close FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      return;
   }

   // Calculate R
   double exit_pts = (g_dir > 0) ? (exit_price - g_entry) : (g_entry - exit_price);
   exit_pts /= point;
   double r_mult = (g_orig_sl_dist > 0) ? exit_pts / g_orig_sl_dist : 0;

   // Dollar PnL
   double tick_val = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE);
   double pnl = 0;
   if(tick_size > 0)
      pnl = (exit_pts * point / tick_size) * tick_val * g_position_volume;

   g_trades++;
   g_total_r += r_mult;
   if(r_mult > 0) g_wins++; else g_losses++;

   if(r_mult > g_best_trade) g_best_trade = r_mult;
   if(r_mult < g_worst_trade) g_worst_trade = r_mult;

   if(reason == "TARGET") g_target_exits++;
   else if(reason == "STOP") g_stop_exits++;
   else if(reason == "TIME") g_time_exits++;
   else if(reason == "TRAIL") g_trail_exits++;
   else if(reason == "LOCK") g_lock_exits++;

   g_daily_pnl += pnl;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
      if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   }
   else
      g_consec_loss = 0;

   PrintFormat("[v19.0] CLOSE %s R=%+.2f PnL=$%.2f | Day=$%.2f | Score=%d | %d/%d today",
               reason, r_mult, pnl, g_daily_pnl, g_entry_score, g_daily_trades, InpMaxTradesPerDay);

   // Write journal
   if(InpWriteJournal) WriteJournalEntry(reason, r_mult, pnl);

   g_ticket = 0;
   g_dir = 0;
   g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| ATR PERCENTILE                                                     |
//+------------------------------------------------------------------+
void UpdateATRHistory(double atr_val)
{
   if(g_atr_hist_count < ArraySize(g_atr_hist))
      g_atr_hist[g_atr_hist_count++] = atr_val;
   else
   {
      for(int i = 0; i < ArraySize(g_atr_hist)-1; i++)
         g_atr_hist[i] = g_atr_hist[i+1];
      g_atr_hist[ArraySize(g_atr_hist)-1] = atr_val;
   }
}

double CalcATRPercentile(double current)
{
   if(g_atr_hist_count < 40) return 50.0;
   int below = 0;
   for(int i = 0; i < g_atr_hist_count; i++)
      if(current > g_atr_hist[i]) below++;
   return (double)below / g_atr_hist_count * 100.0;
}

//+------------------------------------------------------------------+
//| TRADE JOURNAL                                                      |
//+------------------------------------------------------------------+
void InitJournal()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   g_journal_file = StringFormat("Mitemshub_v19_journal_%04d%02d%02d.csv",
                                  dt.year, dt.mon, dt.day);

   // Write header if file doesn't exist
   int handle = FileOpen(g_journal_file, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(handle != INVALID_HANDLE)
   {
      if(FileSize(handle) == 0)
      {
         FileWriteString(handle,
            "Time,Symbol,Direction,Entry,Exit,SL,TP,Volume,Score,Regime," +
            "TrendScore,StructureScore,MomentumScore,VolatilityScore,LocationScore,ConfirmScore," +
            "Reason,R,PnL_Dollar,HoldBars,DailyTrades,Equity\n");
      }
      FileClose(handle);
   }
}

void WriteJournalEntry(string reason, double r_mult, double pnl)
{
   if(!InpWriteJournal || g_journal_file == "") return;

   int handle = FileOpen(g_journal_file, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(handle == INVALID_HANDLE) return;

   MqlDateTime dt;
   TimeToStruct(g_entry_time, dt);
   string time_str = StringFormat("%04d-%02d-%02d %02d:%02d", dt.year, dt.mon, dt.day, dt.hour, dt.min);

   FileWriteString(handle,
      StringFormat("%s,%s,%s,%.5f,%.5f,%.5f,%.5f,%.2f,%d,%s,%d,%d,%d,%d,%d,%d,%s,%+.3f,%.2f,%d,%d,%.2f\n",
         time_str, InpSymbol, g_dir>0?"BUY":"SELL",
         g_entry, (g_dir>0)?SymbolInfoDouble(InpSymbol,SYMBOL_BID):SymbolInfoDouble(InpSymbol,SYMBOL_ASK),
         g_sl, g_tp, g_position_volume, g_entry_score, g_entry_regime,
         g_score_trend, g_score_structure, g_score_momentum, g_score_volatility,
         g_score_location, g_score_confirm,
         reason, r_mult, pnl, g_bars_held, g_daily_trades, g_eq));

   FileClose(handle);
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i = 0; i < 26; i++)
   {
      g_dash_names[i] = "M190_" + IntegerToString(i);
      ObjectCreate(0, g_dash_names[i], OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, g_dash_names[i], OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, g_dash_names[i], OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, g_dash_names[i], OBJPROP_YDISTANCE, 16 + i*14);
      ObjectSetString(0, g_dash_names[i], OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, g_dash_names[i], OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, g_dash_names[i], OBJPROP_COLOR, clrWhite);
   }
}

void UpdateDashboard()
{
   double wr = g_trades > 0 ? 100.0 * g_wins / g_trades : 0;
   double dd = g_peak_eq > 0 ? (g_peak_eq - g_eq) / g_peak_eq * 100 : 0;

   string L[26];
   L[0]  = "=== MITEMSHUB AI v19.0 ===";
   L[1]  = StringFormat("%s | %s→%s", InpSymbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   L[2]  = StringFormat("Equity: $%.2f | Peak: $%.2f", g_eq, g_peak_eq);
   L[3]  = StringFormat("Regime: %s | Struct: %s", RegimeToStr(g_regime),
                         g_is_bullish_structure?"BULL":(g_is_bearish_structure?"BEAR":"FLAT"));
   L[4]  = StringFormat("Score: %d/100 (min:%d)", g_total_score, InpMinScore);
   L[5]  = StringFormat("T:%d S:%d M:%d V:%d L:%d C:%d",
                         g_score_trend, g_score_structure, g_score_momentum,
                         g_score_volatility, g_score_location, g_score_confirm);
   L[6]  = StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f", g_trades, wr, g_total_r);
   L[7]  = StringFormat("Day: $%.2f | %d/%d today", g_daily_pnl, g_daily_trades, InpMaxTradesPerDay);
   L[8]  = StringFormat("Risk: %.1f%% | TP: %.1fxSL | SL: %.1fxATR",
                         InpRiskPerTrade*100, InpTP_RewardMult, InpSL_AtrMult);
   L[9]  = StringFormat("BE:%.1fR Trail:%.1fR Lock:%.1fR | MaxHold:%d",
                         InpBE_RTrigger, InpTrail_RTrigger, InpLock_RTrigger, InpMaxHoldBars);
   L[10] = StringFormat("DD: %.1f%% | ConsecL: %d | BOS: %s",
                         dd, g_consec_loss, g_bos_detected?"YES":"NO");
   L[11] = InpLiveExecution ? "MODE: LIVE" : "MODE: PAPER";

   int line = 12;
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      double cur = g_dir > 0 ? SymbolInfoDouble(InpSymbol, SYMBOL_BID) : SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
      double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
      double r_now = (g_orig_sl_dist > 0 && point > 0) ?
         ((g_dir > 0 ? (cur - g_entry) : (g_entry - cur)) / point / g_orig_sl_dist) : 0;
      double hrs = (double)(TimeCurrent() - g_entry_time) / 3600.0;
      L[line++] = StringFormat("OPEN %s @%.5f (Score:%d)", g_dir>0?"BUY":"SELL", g_entry, g_entry_score);
      L[line++] = StringFormat("SL: %.5f | TP: %.5f", g_sl, g_tp);
      L[line++] = StringFormat("R: %+.2f | Held: %.1fh | %s", r_now, hrs, g_entry_regime);
   }
   while(line < 26) L[line++] = "";

   for(int i = 0; i < 26; i++)
   {
      ObjectSetString(0, g_dash_names[i], OBJPROP_TEXT, L[i]);
      color c = clrWhite;
      if(i == 0) c = clrGold;
      if(i == 3)
      {
         if(g_regime == REGIME_TREND_UP) c = clrLime;
         else if(g_regime == REGIME_TREND_DOWN) c = clrRed;
         else if(g_regime == REGIME_RANGE) c = clrYellow;
         else if(g_regime == REGIME_COMPRESSION) c = clrGray;
         else if(g_regime == REGIME_EXPANSION) c = clrAqua;
      }
      if(i == 4)
      {
         if(g_total_score >= 85) c = clrGold;
         else if(g_total_score >= InpMinScore) c = clrLime;
         else c = clrRed;
      }
      if(i == 6) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i == 7) c = g_paused ? clrRed : clrLime;
      ObjectSetInteger(0, g_dash_names[i], OBJPROP_COLOR, c);
   }
   ChartRedraw();
}

string RegimeToStr(ENUM_REGIME r)
{
   switch(r)
   {
      case REGIME_TREND_UP:     return "TREND_UP";
      case REGIME_TREND_DOWN:   return "TREND_DOWN";
      case REGIME_RANGE:        return "RANGE";
      case REGIME_COMPRESSION:  return "COMPRESSION";
      case REGIME_EXPANSION:    return "EXPANSION";
      default:                  return "NO_TRADE";
   }
}

void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name = "M190_" + tag + "_" + IntegerToString((int)t);
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir > 0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir > 0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}
//+------------------------------------------------------------------+
