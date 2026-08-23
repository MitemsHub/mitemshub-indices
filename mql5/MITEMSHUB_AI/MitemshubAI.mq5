//+------------------------------------------------------------------+
//|                                         MitemshubAI_v16_7.mq5    |
//|                     MITEMSHUB AI MARKET ENGINE v16.7              |
//|   Auto-TF • Wide Pullback • Momentum • Regime + Trailing         |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "16.71"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Regime (3x chart TF) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;

input group "=== Pullback Entry ==="
input double InpPullbackMin      = 0.10;      // v16.7: min pullback distance (ATR)
input double InpPullbackMax      = 3.5;       // v16.7: max pullback (was 2.2 — too tight)
input int    InpRsiPeriod        = 14;
input double InpRsiBuyMax        = 62.0;      // v16.7: slightly wider RSI band
input double InpRsiSellMin       = 38.0;

input group "=== Momentum Entry ==="
input bool   InpUseMomentum      = true;      // v16.7: NEW — catch strong moves
input int    InpMomLookback      = 20;        // bars to check for session high/low
input double InpMomMinMove       = 1.5;       // min move in ATR to trigger
input double InpMomRsiThresh     = 40.0;      // RSI threshold for momentum buy
input double InpMomRsiThreshSell = 60.0;      // RSI threshold for momentum sell

input group "=== ATR Volatility Filter ==="
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 200;
input double InpAtrLowPct        = 2.0;       // v16.73: lower filter (was 8%, blocked trending markets)
input double InpAtrHighPct       = 92.0;      // v16.7: wider range (was 88%)

input group "=== Compression Breakout ==="
input int    InpCompressBars     = 18;
input double InpCompressATRMult  = 0.70;      // v16.7: slightly easier (was 0.65)
input double InpBreakoutMin      = 0.10;      // v16.7: tighter breakout trigger

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.004;     // 0.4% per trade
input double InpAtrStopMult      = 1.6;       // optimized for V100
input double InpAtrTargetMult    = 1.4;       // v16.73: R-multiple of SL (was 2.8×ATR)
input int    InpHoldBars         = 14;
input double InpMaxDailyLossPct  = 0.025;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 3;
input bool   InpUseTrailing      = true;
input double InpTrailStartATR    = 0.6;
input double InpTrailDistATR     = 0.7;
input bool   InpUseBreakeven     = true;
input double InpBETriggerATR     = 1.0;

input group "=== Execution ==="
input long   InpMagic            = 7788127;
input int    InpMaxSlippagePts   = 40;
input int    InpWarmupBars       = 250;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;
input bool   InpDebugLog         = true;      // v16.7: signal rejection logging

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

// Auto-detect timeframes
ENUM_TIMEFRAMES g_tf_entry;     // chart timeframe (e.g. M5)
ENUM_TIMEFRAMES g_tf_regime;    // 3x chart (e.g. M15)

int      hEMA_Fast_Regime, hEMA_Mid_Regime, hEMA_Slow_Regime;
int      hEMA_Fast_Entry, hRSI_Entry, hATR_Entry;
double   g_peak_equity, g_daily_pnl;
datetime g_day_start = 0;
int      g_cooldown = 0, g_consec_loss = 0;
bool     g_paused = false;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

ulong    g_ticket = 0;
int      g_dir = 0;
double   g_entry = 0, g_sl = 0, g_tp = 0, g_orig_risk = 0, g_stake = 0;
datetime g_entry_time = 0;
int      g_bars_held = 0;

double   atr_hist[];
int      atr_hist_count = 0;

string   dash_names[24];

//+------------------------------------------------------------------+
//| Helper: get timeframe 3x higher than input                        |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES entry_tf)
{
   // M1->M5, M5->M15, M15->H1, H1->H4, H4->D1
   switch(entry_tf)
   {
      case PERIOD_M1:  return PERIOD_M5;
      case PERIOD_M2:  return PERIOD_M15;
      case PERIOD_M3:  return PERIOD_M15;
      case PERIOD_M4:  return PERIOD_M15;
      case PERIOD_M5:  return PERIOD_M15;
      case PERIOD_M6:  return PERIOD_M15;
      case PERIOD_M10: return PERIOD_M30;
      case PERIOD_M12: return PERIOD_M30;
      case PERIOD_M15: return PERIOD_H1;
      case PERIOD_M20: return PERIOD_H1;
      case PERIOD_M30: return PERIOD_H1;
      case PERIOD_H1:  return PERIOD_H4;
      case PERIOD_H2:  return PERIOD_H4;
      case PERIOD_H3:  return PERIOD_H4;
      case PERIOD_H4:  return PERIOD_D1;
      case PERIOD_H6:  return PERIOD_D1;
      case PERIOD_H8:  return PERIOD_D1;
      case PERIOD_H12: return PERIOD_D1;
      case PERIOD_D1:  return PERIOD_W1;
      default:         return PERIOD_M15;
   }
}

string TFStr(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      default:         return "AUTO";
   }
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   // Auto-detect timeframes
   g_tf_entry  = (ENUM_TIMEFRAMES)_Period;
   g_tf_regime = GetRegimeTF(g_tf_entry);

   g_peak_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_daily_pnl = 0;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);

   // Regime indicators (higher TF)
   hEMA_Fast_Regime = iMA(_Symbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_Regime  = iMA(_Symbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_Regime = iMA(_Symbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   // Entry indicators (chart TF)
   hEMA_Fast_Entry = iMA(_Symbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_Entry      = iRSI(_Symbol, g_tf_entry, InpRsiPeriod, PRICE_CLOSE);
   hATR_Entry      = iATR(_Symbol, g_tf_entry, InpAtrPeriod);

   if(hEMA_Fast_Regime==INVALID_HANDLE || hEMA_Mid_Regime==INVALID_HANDLE || hEMA_Slow_Regime==INVALID_HANDLE ||
      hEMA_Fast_Entry==INVALID_HANDLE || hRSI_Entry==INVALID_HANDLE || hATR_Entry==INVALID_HANDLE)
   {
      Print("[MITEM v16.71] ERROR: Indicator handle creation failed");
      return INIT_FAILED;
   }

   ArrayResize(atr_hist, InpAtrLookback + 50);
   ArrayInitialize(atr_hist, 0);

   RecoverPositions();

   if(InpDrawDashboard) CreateDashboard();

   PrintFormat("[MITEM v16.71] Started | Entry=%s Regime=%s | Risk=%.2f%% | Magic=%d | Mode=%s",
               TFStr(g_tf_entry), TFStr(g_tf_regime), InpRiskPerTrade*100, InpMagic, InpLiveExecution?"LIVE":"PAPER");
   PrintFormat("[MITEM v16.71] Pullback=%.1f-%.1f ATR | Momentum=%s | SL=%.1f TP=%.1f Trail=%.1f/%.1f",
               InpPullbackMin, InpPullbackMax, InpUseMomentum?"ON":"OFF",
               InpAtrStopMult, InpAtrTargetMult, InpTrailStartATR, InpTrailDistATR);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_Regime);
   IndicatorRelease(hEMA_Mid_Regime);
   IndicatorRelease(hEMA_Slow_Regime);
   IndicatorRelease(hEMA_Fast_Entry);
   IndicatorRelease(hRSI_Entry);
   IndicatorRelease(hATR_Entry);

   for(int i=0; i<24; i++) ObjectDelete(0, dash_names[i]);
   Print("[MITEM v16.71] stopped. Reason=", reason);
}

//+------------------------------------------------------------------+
//| RECOVER POSITIONS                                                  |
//+------------------------------------------------------------------+
void RecoverPositions()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      g_ticket = ticket;
      g_dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      g_entry = PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl = PositionGetDouble(POSITION_SL);
      g_tp = PositionGetDouble(POSITION_TP);
      g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held = 0;
      g_orig_risk = MathAbs(g_entry - g_sl);
      g_stake = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPerTrade;

      PrintFormat("[MITEM v16.71] RECOVERED %s ticket=%d", _Symbol, ticket);
   }
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

   g_peak_equity = MathMax(g_peak_equity, AccountInfoDouble(ACCOUNT_EQUITY));

   // Daily reset — v16.7: resets pause state
   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start)
   {
      g_day_start = ds;
      g_daily_pnl = 0;
      g_paused = false;
      g_consec_loss = 0;
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

   // Entry logic
   if(g_ticket == 0 && !g_paused && Bars(_Symbol, g_tf_entry) >= InpWarmupBars && g_cooldown == 0)
   {
      string sig_type = "";
      int direction = GenerateSignal(sig_type);
      if(direction != 0)
         OpenTrade(direction, sig_type);
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| REGIME CLASSIFIER                                                  |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hEMA_Fast_Regime, 0, 1, 1, emaF) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_Regime,  0, 1, 1, emaM) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_Regime, 0, 1, 1, emaS) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_Entry,       0, 1, 1, atr)  < 1) return REGIME_NO_TRADE;

   // ATR history for percentile
   if(atr_hist_count < ArraySize(atr_hist))
      atr_hist[atr_hist_count++] = atr[0];
   else
   {
      for(int i=0; i<ArraySize(atr_hist)-1; i++) atr_hist[i] = atr_hist[i+1];
      atr_hist[ArraySize(atr_hist)-1] = atr[0];
   }

   double pct = CalcATRPercentile(atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0])
      return REGIME_BULLISH;

   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0])
      return REGIME_BEARISH;

   return REGIME_RANGING;
}

double CalcATRPercentile(double current)
{
   if(atr_hist_count < 50) return 50.0;
   int below = 0;
   int look = MathMin(InpAtrLookback, atr_hist_count);
   for(int i = atr_hist_count - look; i < atr_hist_count; i++)
      if(current > atr_hist[i]) below++;
   return (double)below / look * 100.0;
}

//+------------------------------------------------------------------+
//| SIGNAL GENERATION — v16.7: 3 entry modes                          |
//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE || g_regime == REGIME_HIGH_VOL) return 0;

   double ema20[1], rsi[1], atr[1];
   if(CopyBuffer(hEMA_Fast_Entry, 0, 1, 1, ema20) < 1) return 0;
   if(CopyBuffer(hRSI_Entry,      0, 1, 1, rsi)   < 1) return 0;
   if(CopyBuffer(hATR_Entry,      0, 1, 1, atr)   < 1) return 0;

   double price = iClose(_Symbol, g_tf_entry, 1);
   double prev  = iClose(_Symbol, g_tf_entry, 2);
   double body  = price - prev;

   // ─── MODE 1: TREND PULLBACK ───
   if(g_regime == REGIME_BULLISH || g_regime == REGIME_BEARISH)
   {
      int dir = (g_regime == REGIME_BULLISH) ? 1 : -1;
      double pb = MathAbs(price - ema20[0]);

      // v16.7: wider pullback range (0.10-3.5 ATR)
      if(pb < InpPullbackMin * atr[0])
      {
         if(InpDebugLog) PrintFormat("[v16.7 SKIP] %s Pullback too close: %.2f < %.2f ATR", _Symbol, pb/atr[0], InpPullbackMin);
         return 0;
      }
      if(pb > InpPullbackMax * atr[0])
      {
         if(InpDebugLog) PrintFormat("[v16.7 SKIP] %s Pullback too deep: %.2f > %.2f ATR", _Symbol, pb/atr[0], InpPullbackMax);
         return 0;
      }
      // v16.7: removed the 0.6 ATR cap — allow deeper pullbacks
      if(dir > 0 && rsi[0] > InpRsiBuyMax)
      {
         if(InpDebugLog) PrintFormat("[v16.7 SKIP] %s RSI too high for BUY: %.1f > %.1f", _Symbol, rsi[0], InpRsiBuyMax);
         return 0;
      }
      if(dir < 0 && rsi[0] < InpRsiSellMin)
      {
         if(InpDebugLog) PrintFormat("[v16.7 SKIP] %s RSI too low for SELL: %.1f < %.1f", _Symbol, rsi[0], InpRsiSellMin);
         return 0;
      }
      // v16.7: removed body direction filter — let price action decide
      // v16.7: removed body size filter — large candles are momentum

      sig_type = (dir > 0) ? "PULLBACK_LONG" : "PULLBACK_SHORT";
      return dir;
   }

   // ─── MODE 2: MOMENTUM (v16.71: works in ALL regimes) ───
   if(InpUseMomentum)
   {
      int dir = 0;
      if(g_regime == REGIME_BULLISH) dir = 1;
      else if(g_regime == REGIME_BEARISH) dir = -1;
      // v16.71: RANGING — detect direction from momentum itself
      else if(g_regime == REGIME_RANGING)
      {
         // Use EMA slope to determine direction even in ranging
         double emaF_now[1], emaF_prev[1];
         if(CopyBuffer(hEMA_Fast_Entry, 0, 1, 1, emaF_now) >= 1 &&
            CopyBuffer(hEMA_Fast_Entry, 0, 5, 1, emaF_prev) >= 1)
         {
            if(emaF_now[0] > emaF_prev[0] + 0.1 * atr[0]) dir = 1;   // EMA rising
            else if(emaF_now[0] < emaF_prev[0] - 0.1 * atr[0]) dir = -1; // EMA falling
         }
      }

      // Find session high/low over lookback period
      double session_high = iHigh(_Symbol, g_tf_entry, 1);
      double session_low  = iLow(_Symbol, g_tf_entry, 1);
      for(int i = 2; i <= InpMomLookback && i < Bars(_Symbol, g_tf_entry); i++)
      {
         session_high = MathMax(session_high, iHigh(_Symbol, g_tf_entry, i));
         session_low  = MathMin(session_low,  iLow(_Symbol, g_tf_entry, i));
      }

      double move_up   = price - session_low;
      double move_down = session_high - price;

      // Bullish momentum: price near session high, RSI not overbought
      if(dir > 0 && move_up > InpMomMinMove * atr[0] && rsi[0] > InpMomRsiThresh && rsi[0] < 68)
      {
         // Confirm: current candle is bullish
         if(body > 0)
         {
            sig_type = "MOMENTUM_LONG";
            return 1;
         }
      }

      // Bearish momentum: price near session low, RSI not oversold
      if(dir < 0 && move_down > InpMomMinMove * atr[0] && rsi[0] < InpMomRsiThreshSell && rsi[0] > 32)
      {
         if(body < 0)
         {
            sig_type = "MOMENTUM_SHORT";
            return -1;
         }
      }
   }

   // ─── MODE 3: COMPRESSION BREAKOUT ───
   if(g_regime == REGIME_RANGING)
   {
      double atr_now = atr[0];
      double sum = 0;
      int cnt = 0;
      for(int i=1; i<=100 && i < Bars(_Symbol, g_tf_entry); i++)
      {
         double a[1];
         if(CopyBuffer(hATR_Entry, 0, i, 1, a) == 1) { sum += a[0]; cnt++; }
      }
      if(cnt < 20) return 0;
      double avg_atr = sum / cnt;

      // v16.7: easier compression (0.70x vs 0.65x)
      if(atr_now > avg_atr * InpCompressATRMult) return 0;

      double rh = iHigh(_Symbol, g_tf_entry, 1);
      double rl = iLow(_Symbol, g_tf_entry, 1);
      for(int i=2; i<=InpCompressBars; i++)
      {
         rh = MathMax(rh, iHigh(_Symbol, g_tf_entry, i));
         rl = MathMin(rl, iLow(_Symbol, g_tf_entry, i));
      }
      double range = rh - rl;
      if(range < atr_now * 0.3) return 0;  // v16.7: easier range filter

      double close = iClose(_Symbol, g_tf_entry, 1);
      int dir = 0;
      if(close > rh + InpBreakoutMin * atr_now) dir = 1;
      else if(close < rl - InpBreakoutMin * atr_now) dir = -1;
      if(dir == 0) return 0;

      // v16.7: removed candle size filter
      // v16.7: easier RSI filter
      if(dir > 0 && rsi[0] < 48) return 0;
      if(dir < 0 && rsi[0] > 52) return 0;

      sig_type = (dir > 0) ? "BREAKOUT_UP" : "BREAKOUT_DOWN";
      return dir;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| OPEN TRADE                                                         |
//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1];
   if(CopyBuffer(hATR_Entry, 0, 1, 1, atr) < 1) return;

   double entry = (direction > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                  : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double stop_dist = InpAtrStopMult * atr[0];
   double tp_dist   = InpAtrTargetMult * stop_dist;  // v16.73: R-multiple of SL distance

   double max_stop = entry * 0.025;
   if(stop_dist > max_stop) stop_dist = max_stop;
   if(stop_dist < atr[0] * 0.5) stop_dist = atr[0] * 0.5;

   double sl = (direction > 0) ? entry - stop_dist : entry + stop_dist;
   double tp = (direction > 0) ? entry + tp_dist   : entry - tp_dist;

   // Risk-based volume
   double equity_now = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = equity_now * InpRiskPerTrade;
   double tick_val   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double point      = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(tick_size <= 0 || tick_val <= 0) return;

   double risk_points = stop_dist / point;
   double vol = risk_money / (risk_points * (tick_val / (tick_size / point)));
   vol = NormalizeVolume(vol);
   if(vol <= 0) return;

   bool ok = false;
   if(InpLiveExecution)
   {
      if(direction > 0)
         ok = trade.Buy(vol, _Symbol, entry, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v16.7");
      else
         ok = trade.Sell(vol, _Symbol, entry, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v16.7");
   }
   else
   {
      g_ticket = (ulong)TimeCurrent();
      ok = true;
   }

   if(!ok)
   {
      PrintFormat("[MITEM v16.71] Order FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      g_cooldown = InpCoolDownBars;
      return;
   }

   // Robust ticket recovery
   ulong order_ticket = trade.ResultOrder();
   g_ticket = 0;
   for(int attempt = 0; attempt < 5; attempt++)
   {
      Sleep(50 + attempt * 100);
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         ulong pos = PositionGetTicket(i);
         if(pos == 0) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY && direction < 0) continue;
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL && direction > 0) continue;
         datetime pos_time = (datetime)PositionGetInteger(POSITION_TIME);
         if((int)(TimeCurrent() - pos_time) > 5) continue;
         g_ticket = pos;
         break;
      }
      if(g_ticket > 0) break;
   }
   if(g_ticket == 0) g_ticket = order_ticket;

   g_dir = direction;
   g_entry = entry;
   g_sl = sl;
   g_tp = tp;
   g_orig_risk = stop_dist;
   g_stake = risk_money;
   g_entry_time = TimeCurrent();
   g_bars_held = 0;

   if(InpDrawSignals) DrawArrow(direction, TimeCurrent(), entry, sig_type);

   PrintFormat("[MITEM v16.71] %s %s @%.5f SL=%.5f TP=%.5f Vol=%.2f Regime=%s ATR=%.5f",
               sig_type, direction>0?"BUY":"SELL", entry, sl, tp, vol, RegimeToStr(g_regime), atr[0]);
}

double NormalizeVolume(double vol)
{
   double minv = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxv = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
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
   g_bars_held++;

   double atr[1];
   CopyBuffer(hATR_Entry, 0, 0, 1, atr);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // Time exit
   if(g_bars_held >= InpHoldBars)
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

   // Breakeven
   if(InpUseBreakeven)
   {
      double be_trigger = InpBETriggerATR * (atr[0] > 0 ? atr[0] : 1);
      if(g_dir > 0 && bid >= g_entry + be_trigger && g_sl < g_entry)
      {
         double new_sl = NormalizeDouble(g_entry + 2 * _Point, _Digits);
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
            g_sl = new_sl;
      }
      if(g_dir < 0 && ask <= g_entry - be_trigger && g_sl > g_entry)
      {
         double new_sl = NormalizeDouble(g_entry - 2 * _Point, _Digits);
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
            g_sl = new_sl;
      }
   }

   // Trailing
   if(InpUseTrailing && atr[0] > 0)
   {
      double trail_start = InpTrailStartATR * atr[0];
      double trail_dist  = InpTrailDistATR * atr[0];

      if(g_dir > 0 && bid >= g_entry + trail_start)
      {
         double new_sl = NormalizeDouble(bid - trail_dist, _Digits);
         if(new_sl > g_sl && new_sl > g_entry)
            if(trade.PositionModify(g_ticket, new_sl, g_tp))
               g_sl = new_sl;
      }
      if(g_dir < 0 && ask <= g_entry - trail_start)
      {
         double new_sl = NormalizeDouble(ask + trail_dist, _Digits);
         if(new_sl < g_sl && new_sl > g_entry)
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

   bool ok = trade.PositionClose(g_ticket);
   if(!ok)
   {
      PrintFormat("[MITEM v16.71] Close FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      return;
   }

   Sleep(50);
   double equity_now = AccountInfoDouble(ACCOUNT_EQUITY);

   double realized_pnl = 0;
   if(HistorySelect(g_entry_time - 10, TimeCurrent() + 10))
   {
      for(int i = HistoryDealsTotal()-1; i >= 0; i--)
      {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0) continue;
         if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic) continue;
         if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
         if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
         realized_pnl = HistoryDealGetDouble(deal, DEAL_PROFIT)
                      + HistoryDealGetDouble(deal, DEAL_COMMISSION)
                      + HistoryDealGetDouble(deal, DEAL_SWAP);
         break;
      }
   }

   double exit_price = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                                   : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double r_mult = (g_orig_risk > 0) ?
      ((g_dir > 0) ? (exit_price - g_entry) / g_orig_risk
                   : (g_entry - exit_price) / g_orig_risk) : 0;

   if(equity_now > g_peak_equity) g_peak_equity = equity_now;
   g_daily_pnl += realized_pnl;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
   }
   else g_consec_loss = 0;

   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -equity_now * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_equity - equity_now) > g_peak_equity * 0.12) g_paused = true;

   PrintFormat("[MITEM v16.71] CLOSE %s R=%.3f PnL=$%.2f Equity=$%.2f",
               reason, r_mult, realized_pnl, equity_now);

   g_ticket = 0;
   g_dir = 0;
   g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i=0; i<24; i++)
   {
      dash_names[i] = "MITEM167_" + IntegerToString(i);
      ObjectCreate(0, dash_names[i], OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, dash_names[i], OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, dash_names[i], OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, dash_names[i], OBJPROP_YDISTANCE, 20 + i*16);
      ObjectSetString(0, dash_names[i], OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, dash_names[i], OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, clrWhite);
   }
}

void UpdateDashboard()
{
   double atr[1], rsi[1];
   CopyBuffer(hATR_Entry, 0, 0, 1, atr);
   CopyBuffer(hRSI_Entry, 0, 0, 1, rsi);
   double pct = CalcATRPercentile(atr[0]);
   double equity_now = AccountInfoDouble(ACCOUNT_EQUITY);

   string lines[24];
   lines[0]  = "=== MITEMSHUB AI v16.71 ===";
   lines[1]  = "Equity: $" + DoubleToString(equity_now, 2);
   lines[2]  = "Regime: " + RegimeToStr(g_regime);
   lines[3]  = "ATR %ile: " + DoubleToString(pct, 0) + "%";
   lines[4]  = "RSI: " + DoubleToString(rsi[0], 1);
   lines[5]  = "Entry TF: " + TFStr(g_tf_entry) + " | Regime TF: " + TFStr(g_tf_regime);
   lines[6]  = "Daily PnL: $" + DoubleToString(g_daily_pnl, 2);
   lines[7]  = "Consec Loss: " + IntegerToString(g_consec_loss);
   lines[8]  = "Cooldown: " + IntegerToString(g_cooldown);
   lines[9]  = "Status: " + (g_paused ? "PAUSED" : "ACTIVE");
   lines[10] = InpLiveExecution ? "MODE: LIVE" : "MODE: PAPER";
   lines[11] = "Risk: " + DoubleToString(InpRiskPerTrade*100, 2) + "%";
   lines[12] = "SL: " + DoubleToString(InpAtrStopMult, 1) + "x | TP: " + DoubleToString(InpAtrTargetMult, 1) + "x";
   lines[13] = "Trail: " + (InpUseTrailing ? DoubleToString(InpTrailStartATR,1)+"/"+DoubleToString(InpTrailDistATR,1) : "OFF");
   lines[14] = "Momentum: " + (InpUseMomentum ? "ON" : "OFF");
   bool has_pos = g_ticket > 0;
   lines[15] = "Open: " + (has_pos ? "YES" : "NO");
   lines[16] = "Bars Held: " + IntegerToString(g_bars_held);
   lines[17] = "Peak: $" + DoubleToString(g_peak_equity, 2);
   lines[18] = "DD: " + DoubleToString((g_peak_equity>0) ? (g_peak_equity-equity_now)/g_peak_equity*100 : 0, 2) + "%";
   lines[19] = "Pullback: " + DoubleToString(InpPullbackMin,2) + "-" + DoubleToString(InpPullbackMax,1) + " ATR";
   lines[20] = "Symbol: " + _Symbol;
   lines[21] = "Magic: " + IntegerToString(InpMagic);
   lines[22] = "v16.71: Auto-TF + Momentum + All Regimes";
   lines[23] = "Debug: " + (InpDebugLog ? "ON" : "OFF");

   for(int i=0; i<24; i++)
   {
      ObjectSetString(0, dash_names[i], OBJPROP_TEXT, lines[i]);
      color c = clrWhite;
      if(i==0) c = clrGold;
      if(i==2)
      {
         if(g_regime == REGIME_BULLISH) c = clrLime;
         else if(g_regime == REGIME_BEARISH) c = clrRed;
         else if(g_regime == REGIME_RANGING) c = clrYellow;
         else c = clrGray;
      }
      if(i==6) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i==9) c = g_paused ? clrRed : clrLime;
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
      case REGIME_HIGH_VOL: return "HIGH_VOL";
      default:              return "NO_TRADE";
   }
}

void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name = "M167_" + tag + "_" + IntegerToString((int)t);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir>0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir>0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}
//+------------------------------------------------------------------+
