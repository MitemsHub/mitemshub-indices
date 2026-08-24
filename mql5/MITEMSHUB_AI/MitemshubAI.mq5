//+------------------------------------------------------------------+
//|                                         MitemshubAI_v20.mq5      |
//|                     MITEMSHUB AI MARKET ENGINE v20               |
//|   H4 Regime + M5 Structure Entries • V100 Optimized             |
//|   Smart SL/TP • Risk-Based Sizing • Trade Journal               |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "20.00"
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Regime Detection (H4) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input double InpMinEmaSep        = 0.15;      // min EMA separation in ATR for trend
input bool   InpTradeRanging     = true;      // allow trades in ranging regime

input group "=== Structure Detection (M5) ==="
input int    InpSwingLookback    = 5;          // bars to confirm swing point
input int    InpStructureBars    = 30;         // bars to look back for structure
input double InpBosBuffer        = 0.10;       // buffer above/below structure level (ATR)
input bool   InpRequireBos       = false;      // require BOS for entry (stricter)

input group "=== Entry Filters ==="
input double InpMinBodyRatio     = 0.55;       // min candle body/range ratio
input double InpMinRangeAtr      = 0.6;        // min bar range as fraction of ATR
input double InpRsiBuyLo         = 40.0;       // RSI floor for buys
input double InpRsiBuyHi         = 70.0;       // RSI ceiling for buys
input double InpRsiSellLo        = 30.0;       // RSI floor for sells
input double InpRsiSellHi        = 60.0;       // RSI ceiling for sells
input int    InpMomLookback      = 5;          // velocity lookback bars
input double InpMomThreshold     = 0.20;       // min price velocity (ATR units)

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.01;       // 1% equity risk per trade
input double InpTpMult           = 2.0;        // TP = multiplier × SL distance
input int    InpMaxHoldBars      = 16;         // max hold on M5 (80 min)
input double InpMaxDailyLossPct  = 0.05;       // 5% daily loss cap
input int    InpMaxConsecLoss    = 4;          // pause after N consecutive losses
input int    InpCoolDownBars     = 3;          // cooldown after loss (M5 bars)

input group "=== Trade Management ==="
input bool   InpUseTrailing      = true;
input double InpTrailTriggerR    = 1.0;        // trailing starts after 1R profit
input double InpTrailDistR       = 0.8;        // trailing distance in R
input bool   InpUseBreakeven     = true;
input double InpBeTriggerR       = 0.8;        // BE trigger after 0.8R
input double InpBeOffsetPts      = 0.10;       // BE offset above entry (price units)

input group "=== Execution ==="
input long   InpMagic            = 7788200;
input int    InpMaxSlippagePts   = 30;
input int    InpWarmupBars       = 200;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = false;      // PAPER by default
input bool   InpDebugLog         = false;
input int    InpMaxTradesPerDay  = 3;

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_NO_TRADE };

ENUM_TIMEFRAMES g_tf_entry, g_tf_regime;

// Regime indicators (H4)
int hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;

// Entry indicators (M5)
int hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E;

double   g_eq = 0, g_peak_eq = 0, g_daily_pnl = 0;
datetime g_day_start = 0;
int      g_cooldown = 0, g_consec_loss = 0;
bool     g_paused = false;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

int      g_trades = 0, g_wins = 0, g_losses = 0;
int      g_target_exits = 0, g_time_exits = 0, g_stop_exits = 0, g_be_exits = 0;
double   g_total_r = 0;

ulong    g_ticket = 0;
int      g_dir = 0;
double   g_entry = 0, g_sl = 0, g_tp = 0, g_orig_risk = 0;
double   g_position_volume = 0;
datetime g_entry_time = 0;
int      g_bars_held = 0;

// Structure tracking
double   g_swing_highs[];
double   g_swing_lows[];
int      g_swing_count = 0;
double   g_last_bos_level = 0;
int      g_last_bos_dir = 0;

int      g_trades_today = 0;

string   dash_names[28];

//+------------------------------------------------------------------+
//| HELPER: Get regime TF from entry TF                              |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M5)  return PERIOD_H4;
   if(tf == PERIOD_M15) return PERIOD_H1;
   if(tf == PERIOD_H1)  return PERIOD_H4;
   return PERIOD_H4;
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   g_tf_entry  = (ENUM_TIMEFRAMES)Period();
   g_tf_regime = GetRegimeTF(g_tf_entry);

   // Regime indicators (H4)
   hEMA_Fast_R = iMA(_Symbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_R  = iMA(_Symbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_R = iMA(_Symbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   // Entry indicators (M5)
   hEMA_Fast_E = iMA(_Symbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_E  = iMA(_Symbol, g_tf_entry, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_E = iMA(_Symbol, g_tf_entry, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_E      = iRSI(_Symbol, g_tf_entry, 14, PRICE_CLOSE);
   hATR_E      = iATR(_Symbol, g_tf_entry, 14);

   if(hEMA_Fast_R == INVALID_HANDLE || hEMA_Mid_R == INVALID_HANDLE || hEMA_Slow_R == INVALID_HANDLE ||
      hEMA_Fast_E == INVALID_HANDLE || hEMA_Mid_E == INVALID_HANDLE || hEMA_Slow_E == INVALID_HANDLE ||
      hRSI_E == INVALID_HANDLE || hATR_E == INVALID_HANDLE)
   {
      Print("v20: Indicator handle failed");
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

   RecoverPosition();
   if(InpDrawDashboard) CreateDashboard();

   PrintFormat("[MITEM v20] Started | Entry=%s Regime=%s | Risk=%.2f%% | TP=%.1fxSL",
               EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpRiskPerTrade * 100, InpTpMult);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_R); IndicatorRelease(hEMA_Mid_R); IndicatorRelease(hEMA_Slow_R);
   IndicatorRelease(hEMA_Fast_E); IndicatorRelease(hEMA_Mid_E); IndicatorRelease(hEMA_Slow_E);
   IndicatorRelease(hRSI_E); IndicatorRelease(hATR_E);

   for(int i = 0; i < 28; i++) ObjectDelete(0, dash_names[i]);

   double wr = g_trades > 0 ? 100.0 * g_wins / g_trades : 0;
   double dd = g_peak_eq > 0 ? (g_peak_eq - g_eq) / g_peak_eq * 100 : 0;

   Print("========================================");
   PrintFormat("[v20] SESSION SUMMARY");
   PrintFormat("Symbol: %s | Entry: %s | Regime: %s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   PrintFormat("Trades: %d | Wins: %d | Losses: %d | WR: %.1f%%", g_trades, g_wins, g_losses, wr);
   PrintFormat("Total R: %+.3f", g_total_r);
   PrintFormat("Exits -> Target: %d | Time: %d | Stop: %d | BE: %d", g_target_exits, g_time_exits, g_stop_exits, g_be_exits);
   PrintFormat("Equity: $%.2f | Peak: $%.2f | MaxDD: %.2f%%", g_eq, g_peak_eq, dd);
   Print("========================================");
}

//+------------------------------------------------------------------+
//| OnTick                                                             |
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

   // Daily reset
   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start)
   {
      g_day_start = ds;
      g_daily_pnl = 0;
      g_trades_today = 0;
      g_paused = false;
   }

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
//| RECOVER POSITION                                                   |
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
      PrintFormat("[v20] Recovered position #%d", t);
      break;
   }
}

//+------------------------------------------------------------------+
//| REGIME CLASSIFICATION (H4)                                         |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hEMA_Fast_R, 0, 1, 1, emaF) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_R,  0, 1, 1, emaM) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_R, 0, 1, 1, emaS) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_E, 0, 1, 1, atr) < 1) return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);
   double sep = MathAbs(emaF[0] - emaM[0]) / atr[0];

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0] && sep >= InpMinEmaSep)
      return REGIME_BULLISH;
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0] && sep >= InpMinEmaSep)
      return REGIME_BEARISH;

   return REGIME_RANGING;
}

//+------------------------------------------------------------------+
//| STRUCTURE DETECTION (M5)                                           |
//+------------------------------------------------------------------+
void DetectSwingPoints()
{
   g_swing_count = 0;
   int lb = InpSwingLookback;
   int look = InpStructureBars;

   for(int i = lb; i < look && i < Bars(_Symbol, g_tf_entry) - 1; i++)
   {
      double high_i = iHigh(_Symbol, g_tf_entry, i);
      double low_i  = iLow(_Symbol, g_tf_entry, i);

      // Swing high: highest high in window
      bool is_swing_high = true;
      for(int j = 1; j <= lb; j++)
      {
         if(iHigh(_Symbol, g_tf_entry, i - j) >= high_i) { is_swing_high = false; break; }
         if(iHigh(_Symbol, g_tf_entry, i + j) >= high_i) { is_swing_high = false; break; }
      }

      // Swing low: lowest low in window
      bool is_swing_low = true;
      for(int j = 1; j <= lb; j++)
      {
         if(iLow(_Symbol, g_tf_entry, i - j) <= low_i) { is_swing_low = false; break; }
         if(iLow(_Symbol, g_tf_entry, i + j) <= low_i) { is_swing_low = false; break; }
      }

      if(is_swing_high && g_swing_count < 100)
      {
         g_swing_highs[g_swing_count] = high_i;
         g_swing_count++;
      }
      if(is_swing_low && g_swing_count < 100)
      {
         g_swing_lows[g_swing_count] = low_i;
         g_swing_count++;
      }
   }
}

//+------------------------------------------------------------------+
//| Check Break of Structure                                           |
//+------------------------------------------------------------------+
int CheckBOS(double price, double atr_val)
{
   double buffer = InpBosBuffer * atr_val;

   // Find most recent swing high and swing low
   double last_sh = 0, last_sl = 0;
   for(int i = 0; i < g_swing_count; i++)
   {
      if(g_swing_highs[i] > 0) last_sh = g_swing_highs[i];
      if(g_swing_lows[i] > 0) last_sl = g_swing_lows[i];
   }

   if(last_sh > 0 && price > last_sh + buffer)
      return 1;   // BOS bullish
   if(last_sl > 0 && price < last_sl - buffer)
      return -1;  // BOS bearish

   return 0;
}

//+------------------------------------------------------------------+
//| Check Higher Highs / Higher Lows                                   |
//+------------------------------------------------------------------+
int CheckMarketStructure()
{
   if(g_swing_count < 4) return 0;

   // Find 2 most recent swing highs and lows
   double sh1 = 0, sh2 = 0, sl1 = 0, sl2 = 0;
   int sh_count = 0, sl_count = 0;

   for(int i = g_swing_count - 1; i >= 0 && (sh_count < 2 || sl_count < 2); i--)
   {
      if(g_swing_highs[i] > 0 && sh_count < 2)
      {
         if(sh_count == 0) sh1 = g_swing_highs[i];
         else sh2 = g_swing_highs[i];
         sh_count++;
      }
      if(g_swing_lows[i] > 0 && sl_count < 2)
      {
         if(sl_count == 0) sl1 = g_swing_lows[i];
         else sl2 = g_swing_lows[i];
         sl_count++;
      }
   }

   if(sh_count >= 2 && sl_count >= 2)
   {
      // Higher Highs + Higher Lows = Bullish structure
      if(sh1 > sh2 && sl1 > sl2) return 1;
      // Lower Highs + Lower Lows = Bearish structure
      if(sh1 < sh2 && sl1 < sl2) return -1;
   }

   return 0;
}

//+------------------------------------------------------------------+
//| SIGNAL GENERATION                                                  |
//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   // Step 1: Regime (H4)
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE) return 0;

   if(!InpTradeRanging && g_regime == REGIME_RANGING)
   {
      if(InpDebugLog) Print("[v20] SKIP: RANGING regime");
      return 0;
   }

   double atr[1];
   if(CopyBuffer(hATR_E, 0, 1, 1, atr) < 1) return 0;
   if(atr[0] <= 0) return 0;

   double price = iClose(_Symbol, g_tf_entry, 1);
   double body  = price - iOpen(_Symbol, g_tf_entry, 1);
   double range = iHigh(_Symbol, g_tf_entry, 1) - iLow(_Symbol, g_tf_entry, 1);

   if(range <= 0) return 0;

   // Step 2: Basic candle filters
   double body_ratio = MathAbs(body) / range;
   if(body_ratio < InpMinBodyRatio) return 0;
   if(range < InpMinRangeAtr * atr[0]) return 0;

   // Step 3: Structure detection
   DetectSwingPoints();
   int structure_dir = CheckMarketStructure();
   int bos = CheckBOS(price, atr[0]);

   // Step 4: Momentum filter
   double velocity = 0;
   if(Bars(_Symbol, g_tf_entry) > InpMomLookback + 1)
      velocity = (price - iClose(_Symbol, g_tf_entry, InpMomLookback + 1)) / InpMomLookback;

   // Step 5: RSI filter
   double rsi[1];
   if(CopyBuffer(hRSI_E, 0, 1, 1, rsi) < 1) return 0;

   // Step 6: EMA alignment for trend confirmation
   double emaF[1], emaM[1], emaS[1];
   if(CopyBuffer(hEMA_Fast_E, 0, 1, 1, emaF) < 1) return 0;
   if(CopyBuffer(hEMA_Mid_E,  0, 1, 1, emaM) < 1) return 0;
   if(CopyBuffer(hEMA_Slow_E, 0, 1, 1, emaS) < 1) return 0;

   // === SCORING ENGINE ===
   // Each component contributes to a directional score
   double buy_score = 0;
   double sell_score = 0;

   // --- Regime (H4) ---
   if(g_regime == REGIME_BULLISH)      buy_score += 2.0;
   else if(g_regime == REGIME_BEARISH) sell_score += 2.0;
   else // RANGING — use momentum for direction
   {
      if(velocity > 0) buy_score += 0.5;
      else             sell_score += 0.5;
   }

   // --- Market Structure (M5) ---
   if(structure_dir == 1)      buy_score += 2.0;
   else if(structure_dir == -1) sell_score += 2.0;

   // --- Break of Structure ---
   if(bos == 1)      buy_score += 1.5;
   else if(bos == -1) sell_score += 1.5;
   else if(InpRequireBos) return 0;

   // --- Candle Direction ---
   if(body > 0) buy_score += 1.0;
   else         sell_score += 1.0;

   // --- Body Quality ---
   double quality = body_ratio;  // 0.55 to 1.0
   if(body > 0) buy_score += quality;
   else         sell_score += quality;

   // --- EMA Alignment (M5) ---
   if(emaF[0] > emaM[0] && emaM[0] > emaS[0]) buy_score += 1.0;
   else if(emaF[0] < emaM[0] && emaM[0] < emaS[0]) sell_score += 1.0;

   // --- RSI ---
   if(rsi[0] > InpRsiBuyLo && rsi[0] < InpRsiBuyHi && body > 0)
      buy_score += 0.5;
   else if(rsi[0] > InpRsiSellLo && rsi[0] < InpRsiSellHi && body < 0)
      sell_score += 0.5;

   // --- Velocity ---
   if(velocity > InpMomThreshold * atr[0])      buy_score += 1.0;
   else if(velocity < -InpMomThreshold * atr[0]) sell_score += 1.0;

   // === DECISION ===
   // Need buy_score or sell_score >= threshold
   double threshold = 4.0;  // need strong confluence

   if(buy_score >= threshold && buy_score > sell_score + 1.0)
   {
      // Verify we're not buying into overbought
      if(rsi[0] >= InpRsiBuyHi) return 0;
      sig_type = StringFormat("BUY_S%.0f", buy_score);
      return 1;
   }

   if(sell_score >= threshold && sell_score > buy_score + 1.0)
   {
      if(rsi[0] <= InpRsiSellLo) return 0;
      sig_type = StringFormat("SELL_S%.0f", sell_score);
      return -1;
   }

   return 0;
}

//+------------------------------------------------------------------+
//| OPEN TRADE — Structure-based SL                                    |
//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1];
   if(CopyBuffer(hATR_E, 0, 1, 1, atr) < 1) return;

   double entry = (direction > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                  : SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // === STRUCTURE-BASED SL ===
   double structure_sl = 0;
   if(direction > 0)
   {
      // Find nearest swing low below entry
      double best_sl = 0;
      for(int i = 0; i < g_swing_count; i++)
      {
         if(g_swing_lows[i] > 0 && g_swing_lows[i] < entry)
         {
            if(g_swing_lows[i] > best_sl)  // highest swing low = nearest support
               best_sl = g_swing_lows[i];
         }
      }
      structure_sl = (best_sl > 0) ? best_sl - InpBosBuffer * atr[0] : entry - 1.5 * atr[0];
   }
   else
   {
      double best_sl = 999999;
      for(int i = 0; i < g_swing_count; i++)
      {
         if(g_swing_highs[i] > 0 && g_swing_highs[i] > entry)
         {
            if(g_swing_highs[i] < best_sl)  // lowest swing high = nearest resistance
               best_sl = g_swing_highs[i];
         }
      }
      structure_sl = (best_sl < 999999) ? best_sl + InpBosBuffer * atr[0] : entry + 1.5 * atr[0];
   }

   double stop_dist = MathAbs(entry - structure_sl);

   // Safety limits
   double min_stop = 0.5 * atr[0];    // minimum SL = 0.5 ATR
   double max_stop = 3.0 * atr[0];    // maximum SL = 3 ATR
   if(stop_dist < min_stop) stop_dist = min_stop;
   if(stop_dist > max_stop) stop_dist = max_stop;

   double sl = (direction > 0) ? entry - stop_dist : entry + stop_dist;
   double tp = (direction > 0) ? entry + InpTpMult * stop_dist
                               : entry - InpTpMult * stop_dist;

   // === RISK-BASED VOLUME ===
   double equity_now = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = equity_now * InpRiskPerTrade;
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);

   if(tick_size <= 0 || tick_value <= 0) return;

   double ticks_to_sl = stop_dist / tick_size;
   double loss_per_lot = ticks_to_sl * tick_value;
   if(loss_per_lot <= 0) return;

   double vol = risk_money / loss_per_lot;
   vol = NormalizeVolume(vol);
   if(vol <= 0) return;

   // === EXECUTE ===
   bool ok = false;
   if(InpLiveExecution)
   {
      if(direction > 0)
         ok = trade.Buy(vol, _Symbol, 0, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v20");
      else
         ok = trade.Sell(vol, _Symbol, 0, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v20");
   }
   else
   {
      g_ticket = (ulong)TimeCurrent();
      ok = true;
   }

   if(!ok)
   {
      PrintFormat("[v20] Order FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      g_cooldown = InpCoolDownBars;
      return;
   }

   // Ticket recovery
   g_ticket = 0;
   for(int attempt = 0; attempt < 8; attempt++)
   {
      Sleep(70);
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         if(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME) > 12) continue;
         g_ticket = t;
         break;
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

   PrintFormat("[v20] %s %s @%.5f SL=%.5f TP=%.5f Vol=%.2f Risk=$%.2f Score=%s",
               sig_type, direction > 0 ? "BUY" : "SELL", entry, sl, tp, vol,
               risk_money, StringSubstr(sig_type, StringFind(sig_type, "_S") + 2));
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
//| MANAGE POSITION                                                    |
//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)) { g_ticket = 0; return; }

   g_bars_held++;

   double atr[1];
   if(CopyBuffer(hATR_E, 0, 0, 1, atr) < 1) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // Time exit
   if(g_bars_held >= InpMaxHoldBars)
   {
      ClosePosition("TIME");
      return;
   }

   // SL / TP
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

   // Current R
   double r_now = (g_orig_risk > 0) ? (g_dir > 0 ? (bid - g_entry) : (g_entry - ask)) / g_orig_risk : 0;

   // Breakeven
   if(InpUseBreakeven && r_now >= InpBeTriggerR)
   {
      double be_level = (g_dir > 0) ? g_entry + InpBeOffsetPts : g_entry - InpBeOffsetPts;
      if(g_dir > 0 && g_sl < be_level)
      {
         double new_sl = NormalizeDouble(be_level, _Digits);
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
            g_sl = new_sl;
      }
      if(g_dir < 0 && g_sl > be_level)
      {
         double new_sl = NormalizeDouble(be_level, _Digits);
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
            g_sl = new_sl;
      }
   }

   // Trailing
   if(InpUseTrailing && r_now >= InpTrailTriggerR)
   {
      double trail_dist = InpTrailDistR * g_orig_risk;

      if(g_dir > 0)
      {
         double new_sl = NormalizeDouble(bid - trail_dist, _Digits);
         if(new_sl > g_sl && new_sl > g_entry)
            if(trade.PositionModify(g_ticket, new_sl, g_tp))
               g_sl = new_sl;
      }
      else
      {
         double new_sl = NormalizeDouble(ask + trail_dist, _Digits);
         if(new_sl < g_sl && new_sl < g_entry)
            if(trade.PositionModify(g_ticket, new_sl, g_tp))
               g_sl = new_sl;
      }
   }
}

//+------------------------------------------------------------------+
//| CLOSE POSITION                                                     |
//+------------------------------------------------------------------+
void ClosePosition(string reason)
{
   if(g_ticket == 0) return;

   double exit_price = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                                   : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   if(!trade.PositionClose(g_ticket))
   {
      Print("[v20] Close failed: ", trade.ResultRetcode());
      return;
   }

   double r_mult = (g_orig_risk > 0) ? (g_dir > 0 ? (exit_price - g_entry) : (g_entry - exit_price)) / g_orig_risk : 0;

   g_trades++;
   g_total_r += r_mult;
   if(r_mult > 0) g_wins++; else g_losses++;

   if(reason == "TARGET")     g_target_exits++;
   else if(reason == "TIME")  g_time_exits++;
   else if(reason == "STOP")  g_stop_exits++;

   // Approximate dollar P&L
   double pnl_dollars = r_mult * g_orig_risk * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) /
                        SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE) * g_position_volume;
   g_daily_pnl += pnl_dollars;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
   }
   else
      g_consec_loss = 0;

   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_eq - g_eq) > g_peak_eq * 0.15) g_paused = true;

   PrintFormat("[v20] CLOSE %s R=%+.3f | TotalR=%+.2f | Daily=$%.2f", reason, r_mult, g_total_r, g_daily_pnl);

   g_ticket = 0;
   g_dir = 0;
   g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i = 0; i < 28; i++)
   {
      dash_names[i] = "M20_" + IntegerToString(i);
      ObjectCreate(0, dash_names[i], OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, dash_names[i], OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, dash_names[i], OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, dash_names[i], OBJPROP_YDISTANCE, 16 + i * 15);
      ObjectSetString(0, dash_names[i], OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, dash_names[i], OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, clrWhite);
   }
}

void UpdateDashboard()
{
   double wr = g_trades > 0 ? 100.0 * g_wins / g_trades : 0;
   double dd = g_peak_eq > 0 ? (g_peak_eq - g_eq) / g_peak_eq * 100 : 0;
   double atr[1]; CopyBuffer(hATR_E, 0, 0, 1, atr);

   string L[28];
   L[0]  = "=== MITEMSHUB AI v20.0 ===";
   L[1]  = StringFormat("%s | Entry=%s Regime=%s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   L[2]  = StringFormat("Equity: $%.2f | Peak: $%.2f", g_eq, g_peak_eq);
   L[3]  = StringFormat("Regime: %s | ATR: %.4f", RegimeToStr(g_regime), atr[0]);
   L[4]  = StringFormat("Structure: BOS=%d | HH/HL=%d", g_last_bos_dir, CheckMarketStructure());
   L[5]  = StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f", g_trades, wr, g_total_r);
   L[6]  = StringFormat("Daily: $%.2f | Trades today: %d/%d", g_daily_pnl, g_trades_today, InpMaxTradesPerDay);
   L[7]  = StringFormat("Status: %s | CD: %d | ConsecL: %d", g_paused ? "PAUSED" : "ACTIVE", g_cooldown, g_consec_loss);
   L[8]  = StringFormat("Risk: %.2f%% | TP: %.1fxSL | Hold: %d bars", InpRiskPerTrade * 100, InpTpMult, InpMaxHoldBars);
   L[9]  = StringFormat("Trail: %.1fR/%.1fR | BE: %.1fR", InpTrailTriggerR, InpTrailDistR, InpBeTriggerR);
   L[10] = StringFormat("T/T/S: %d/%d/%d | Mode: %s", g_target_exits, g_time_exits, g_stop_exits, InpLiveExecution ? "LIVE" : "PAPER");
   L[11] = StringFormat("MaxDD: %.2f%% | Trades: %d", dd, g_trades);

   int line = 12;
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      double cur = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double r_now = g_orig_risk > 0 ? (g_dir > 0 ? (cur - g_entry) : (g_entry - cur)) / g_orig_risk : 0;
      double hrs = (double)(TimeCurrent() - g_entry_time) / 3600.0;
      L[line++] = StringFormat("OPEN %s @%.5f", g_dir > 0 ? "BUY" : "SELL", g_entry);
      L[line++] = StringFormat("SL: %.5f | TP: %.5f", g_sl, g_tp);
      L[line++] = StringFormat("R: %+.2f | Held: %.1fh | Vol: %.2f", r_now, hrs, g_position_volume);
   }
   while(line < 28) L[line++] = "";

   for(int i = 0; i < 28; i++)
   {
      ObjectSetString(0, dash_names[i], OBJPROP_TEXT, L[i]);
      color c = clrWhite;
      if(i == 0) c = clrGold;
      if(i == 3)
      {
         if(g_regime == REGIME_BULLISH) c = clrLime;
         else if(g_regime == REGIME_BEARISH) c = clrRed;
         else if(g_regime == REGIME_RANGING) c = clrYellow;
         else c = clrGray;
      }
      if(i == 6) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i == 7) c = g_paused ? clrRed : clrLime;
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, c);
   }
   ChartRedraw();
}

string RegimeToStr(ENUM_REGIME r)
{
   switch(r)
   {
      case REGIME_BULLISH:  return "BULLISH";
      case REGIME_BEARISH:  return "BEARISH";
      case REGIME_RANGING:  return "RANGING";
      default:              return "NO_TRADE";
   }
}

void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name = "M20_" + tag + "_" + IntegerToString((int)t);
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir > 0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir > 0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}
//+------------------------------------------------------------------+
