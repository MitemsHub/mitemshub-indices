//+------------------------------------------------------------------+
//|                                            MitemshubAI_v15.mq5   |
//|                        MITEMSHUB AI MARKET ENGINE v15             |
//|   Regime (M15) + Pullback / Compression Breakout (M5) + ATR       |
//|   Native indicators • Proper risk lots • Trailing option          |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "15.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Regime (M15) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;

input group "=== Pullback Entry (M5) ==="
input double InpPullbackMin      = 0.25;      // Min pullback (ATR)
input double InpPullbackMax      = 1.8;       // Max pullback (ATR)
input int    InpRsiPeriod        = 14;
input double InpRsiBuyMax        = 58.0;      // BUY RSI max
input double InpRsiSellMin       = 42.0;      // SELL RSI min

input group "=== ATR Volatility Filter ==="
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 200;       // Percentile lookback
input double InpAtrLowPct        = 12.0;
input double InpAtrHighPct       = 88.0;

input group "=== Compression Breakout ==="
input int    InpCompressBars     = 18;
input double InpCompressATRMult  = 0.65;
input double InpBreakoutMin      = 0.12;

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.005;     // 0.5% equity risk
input double InpAtrStopMult      = 2.0;
input double InpAtrTargetMult    = 2.8;
input int    InpHoldBars         = 14;        // Max bars held (~70 min)
input double InpMaxDailyLossPct  = 0.025;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 4;
input bool   InpUseTrailing      = true;
input double InpTrailStartATR    = 0.8;       // Start trail after this profit (ATR)
input double InpTrailDistATR     = 0.7;       // Trail distance (ATR)
input bool   InpUseBreakeven     = true;
input double InpBETriggerATR     = 1.0;

input group "=== Execution ==="
input long   InpMagic            = 7788125;
input int    InpMaxSlippagePts   = 40;
input int    InpWarmupBars       = 250;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;      // false = paper simulation only

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

int      hEMA_Fast_M15, hEMA_Mid_M15, hEMA_Slow_M15;
int      hEMA_Fast_M5, hRSI_M5, hATR_M5;
double   g_equity, g_peak_equity, g_daily_pnl;
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

// Dashboard labels
string   dash_names[22];

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   g_equity = AccountInfoDouble(ACCOUNT_BALANCE);
   g_peak_equity = g_equity;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);

   // M15 regime
   hEMA_Fast_M15 = iMA(_Symbol, PERIOD_M15, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_M15  = iMA(_Symbol, PERIOD_M15, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_M15 = iMA(_Symbol, PERIOD_M15, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   // M5 entry
   hEMA_Fast_M5  = iMA(_Symbol, PERIOD_M5, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_M5       = iRSI(_Symbol, PERIOD_M5, InpRsiPeriod, PRICE_CLOSE);
   hATR_M5       = iATR(_Symbol, PERIOD_M5, InpAtrPeriod);

   if(hEMA_Fast_M15==INVALID_HANDLE || hEMA_Mid_M15==INVALID_HANDLE || hEMA_Slow_M15==INVALID_HANDLE ||
      hEMA_Fast_M5==INVALID_HANDLE || hRSI_M5==INVALID_HANDLE || hATR_M5==INVALID_HANDLE)
   {
      Print("Indicator handle creation failed");
      return INIT_FAILED;
   }

   ArrayResize(atr_hist, InpAtrLookback + 50);
   ArrayInitialize(atr_hist, 0);

   if(InpDrawDashboard) CreateDashboard();

   Print("MITEMSHUB AI v15 started | Risk=", InpRiskPerTrade*100, "% | Symbol=", _Symbol);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_M15);
   IndicatorRelease(hEMA_Mid_M15);
   IndicatorRelease(hEMA_Slow_M15);
   IndicatorRelease(hEMA_Fast_M5);
   IndicatorRelease(hRSI_M5);
   IndicatorRelease(hATR_M5);

   for(int i=0; i<22; i++) ObjectDelete(0, dash_names[i]);
   Print("MITEMSHUB AI v15 stopped. Final equity: ", g_equity);
}

//+------------------------------------------------------------------+
//| OnTick                                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   static datetime last_bar = 0;
   datetime cur_bar = iTime(_Symbol, PERIOD_M5, 0);
   if(cur_bar == last_bar) 
   {
      if(InpDrawDashboard) UpdateDashboard();
      return; // only process on new M5 bar
   }
   last_bar = cur_bar;

   // Update equity
   g_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_equity > g_peak_equity) g_peak_equity = g_equity;

   // Daily reset
   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start) { g_day_start = ds; g_daily_pnl = 0; }

   if(g_cooldown > 0) g_cooldown--;

   // Manage open position
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      ManagePosition();
   }
   else
   {
      g_ticket = 0; // cleaned
   }

   // Entry logic only if flat
   if(g_ticket == 0 && !g_paused && Bars(_Symbol, PERIOD_M5) >= InpWarmupBars && g_cooldown == 0)
   {
      string sig_type = "";
      int direction = GenerateSignal(sig_type);
      if(direction != 0) OpenTrade(direction, sig_type);
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| REGIME CLASSIFIER                                                  |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hEMA_Fast_M15, 0, 1, 1, emaF) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_M15,  0, 1, 1, emaM) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_M15, 0, 1, 1, emaS) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_M5,       0, 1, 1, atr)  < 1) return REGIME_NO_TRADE;

   // Update ATR history for percentile
   if(atr_hist_count < ArraySize(atr_hist))
   {
      atr_hist[atr_hist_count++] = atr[0];
   }
   else
   {
      for(int i=0; i<ArraySize(atr_hist)-1; i++) atr_hist[i] = atr_hist[i+1];
      atr_hist[ArraySize(atr_hist)-1] = atr[0];
   }

   double pct = CalcATRPercentile(atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(_Symbol, PERIOD_M15, 1);

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
//| SIGNAL GENERATION                                                  |
//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE || g_regime == REGIME_HIGH_VOL) return 0;

   double ema20[1], rsi[1], atr[1];
   if(CopyBuffer(hEMA_Fast_M5, 0, 1, 1, ema20) < 1) return 0;
   if(CopyBuffer(hRSI_M5,      0, 1, 1, rsi)   < 1) return 0;
   if(CopyBuffer(hATR_M5,      0, 1, 1, atr)   < 1) return 0;

   double price = iClose(_Symbol, PERIOD_M5, 1);
   double prev  = iClose(_Symbol, PERIOD_M5, 2);
   double body  = price - prev;

   // MODE 1: TREND PULLBACK
   if(g_regime == REGIME_BULLISH || g_regime == REGIME_BEARISH)
   {
      int dir = (g_regime == REGIME_BULLISH) ? 1 : -1;
      double pb = MathAbs(price - ema20[0]);

      if(pb < InpPullbackMin * atr[0] || pb > InpPullbackMax * atr[0]) return 0;

      // Correct side of EMA
      if(dir > 0 && price > ema20[0] + 0.6*atr[0]) return 0;
      if(dir < 0 && price < ema20[0] - 0.6*atr[0]) return 0;

      // RSI
      if(dir > 0 && rsi[0] > InpRsiBuyMax) return 0;
      if(dir < 0 && rsi[0] < InpRsiSellMin) return 0;

      // Confirmation candle
      if(dir > 0 && body <= 0) return 0;
      if(dir < 0 && body >= 0) return 0;

      // Gap filter
      if(MathAbs(body) > atr[0] * 0.7) return 0;

      sig_type = (dir > 0) ? "PULLBACK_LONG" : "PULLBACK_SHORT";
      return dir;
   }

   // MODE 2: COMPRESSION BREAKOUT
   if(g_regime == REGIME_RANGING)
   {
      double atr_now = atr[0];
      double sum = 0;
      int cnt = 0;
      for(int i=1; i<=100 && i < Bars(_Symbol, PERIOD_M5); i++)
      {
         double a[1];
         if(CopyBuffer(hATR_M5, 0, i, 1, a) == 1) { sum += a[0]; cnt++; }
      }
      if(cnt < 20) return 0;
      double avg_atr = sum / cnt;
      if(atr_now > avg_atr * InpCompressATRMult) return 0; // not compressed

      double rh = iHigh(_Symbol, PERIOD_M5, 1);
      double rl = iLow(_Symbol, PERIOD_M5, 1);
      for(int i=2; i<=InpCompressBars; i++)
      {
         rh = MathMax(rh, iHigh(_Symbol, PERIOD_M5, i));
         rl = MathMin(rl, iLow(_Symbol, PERIOD_M5, i));
      }
      double range = rh - rl;
      if(range < atr_now * 0.4) return 0;

      double close = iClose(_Symbol, PERIOD_M5, 1);
      int dir = 0;
      if(close > rh + InpBreakoutMin * atr_now) dir = 1;
      else if(close < rl - InpBreakoutMin * atr_now) dir = -1;
      if(dir == 0) return 0;

      // Exhaustion filter
      double candle = iHigh(_Symbol, PERIOD_M5, 1) - iLow(_Symbol, PERIOD_M5, 1);
      if(candle > atr_now * 2.2) return 0;

      // RSI
      if(dir > 0 && rsi[0] < 52) return 0;
      if(dir < 0 && rsi[0] > 48) return 0;

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
   if(CopyBuffer(hATR_M5, 0, 1, 1, atr) < 1) return;

   double entry = (direction > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                  : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double stop_dist = InpAtrStopMult * atr[0];
   double tp_dist   = InpAtrTargetMult * atr[0];

   // Sanity clamps
   double max_stop = entry * 0.025;
   if(stop_dist > max_stop) stop_dist = max_stop;
   if(stop_dist < atr[0] * 0.5) stop_dist = atr[0] * 0.5;

   double sl = (direction > 0) ? entry - stop_dist : entry + stop_dist;
   double tp = (direction > 0) ? entry + tp_dist   : entry - tp_dist;

   // Risk-based volume
   double risk_money = g_equity * InpRiskPerTrade;
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
         ok = trade.Buy(vol, _Symbol, entry, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v15");
      else
         ok = trade.Sell(vol, _Symbol, entry, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v15");

      if(ok)
      {
         g_ticket = trade.ResultOrder();
         // Wait a moment and get real ticket from position
         Sleep(100);
         for(int i=PositionsTotal()-1; i>=0; i--)
         {
            if(PositionGetTicket(i) > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic &&
               PositionGetString(POSITION_SYMBOL) == _Symbol)
            {
               g_ticket = PositionGetInteger(POSITION_TICKET);
               break;
            }
         }
      }
      else
      {
         Print("Order failed: ", trade.ResultRetcode(), " ", trade.ResultComment());
         g_cooldown = InpCoolDownBars;
         return;
      }
   }
   else
   {
      // Paper mode
      g_ticket = (ulong)TimeCurrent(); // fake
      ok = true;
   }

   if(ok)
   {
      g_dir = direction;
      g_entry = entry;
      g_sl = sl;
      g_tp = tp;
      g_orig_risk = stop_dist;
      g_stake = risk_money;
      g_entry_time = TimeCurrent();
      g_bars_held = 0;

      if(InpDrawSignals)
         DrawArrow(direction, TimeCurrent(), entry, sig_type);

      PrintFormat("[MITEM v15] %s %s @%.5f SL=%.5f TP=%.5f Vol=%.2f ATR=%.5f Regime=%s",
                  sig_type, direction>0?"BUY":"SELL", entry, sl, tp, vol, atr[0], RegimeToStr(g_regime));
   }
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
   CopyBuffer(hATR_M5, 0, 0, 1, atr);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double price = (g_dir > 0) ? bid : ask;

   // Time exit
   if(g_bars_held >= InpHoldBars)
   {
      ClosePosition("TIME");
      return;
   }

   // SL / TP check (broker may already close, but we track)
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
      double be_trigger = InpBETriggerATR * atr[0];
      if(g_dir > 0 && bid >= g_entry + be_trigger && g_sl < g_entry)
      {
         double new_sl = g_entry + 2 * _Point;
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
            g_sl = new_sl;
      }
      if(g_dir < 0 && ask <= g_entry - be_trigger && g_sl > g_entry)
      {
         double new_sl = g_entry - 2 * _Point;
         if(trade.PositionModify(g_ticket, new_sl, g_tp))
            g_sl = new_sl;
      }
   }

   // Trailing
   if(InpUseTrailing)
   {
      double trail_start = InpTrailStartATR * atr[0];
      double trail_dist  = InpTrailDistATR * atr[0];

      if(g_dir > 0 && bid >= g_entry + trail_start)
      {
         double new_sl = bid - trail_dist;
         if(new_sl > g_sl && new_sl > g_entry)
         {
            if(trade.PositionModify(g_ticket, new_sl, g_tp))
               g_sl = new_sl;
         }
      }
      if(g_dir < 0 && ask <= g_entry - trail_start)
      {
         double new_sl = ask + trail_dist;
         if(new_sl < g_sl && new_sl < g_entry)
         {
            if(trade.PositionModify(g_ticket, new_sl, g_tp))
               g_sl = new_sl;
         }
      }
   }
}

void ClosePosition(string reason)
{
   double exit_price = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                                   : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double r_mult = (g_dir > 0) ? (exit_price - g_entry) / g_orig_risk
                               : (g_entry - exit_price) / g_orig_risk;
   double pnl = g_stake * r_mult;

   if(InpLiveExecution && g_ticket > 0)
      trade.PositionClose(g_ticket);

   g_equity += pnl;
   g_daily_pnl += pnl;
   if(g_equity > g_peak_equity) g_peak_equity = g_equity;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
   }
   else g_consec_loss = 0;

   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -g_equity * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_equity - g_equity) > g_peak_equity * 0.12) g_paused = true;

   PrintFormat("[MITEM v15] CLOSE %s R=%.3f PnL=$%.2f Equity=$%.2f", reason, r_mult, pnl, g_equity);

   g_ticket = 0;
   g_dir = 0;
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i=0; i<22; i++)
   {
      dash_names[i] = "MITEM15_" + IntegerToString(i);
      ObjectCreate(0, dash_names[i], OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, dash_names[i], OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, dash_names[i], OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, dash_names[i], OBJPROP_YDISTANCE, 20 + i*17);
      ObjectSetString(0, dash_names[i], OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, dash_names[i], OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, clrWhite);
   }
}

void UpdateDashboard()
{
   double atr[1], rsi[1];
   CopyBuffer(hATR_M5, 0, 0, 1, atr);
   CopyBuffer(hRSI_M5, 0, 0, 1, rsi);
   double pct = CalcATRPercentile(atr[0]);

   string lines[22];
   lines[0]  = "=== MITEMSHUB AI v15 ===";
   lines[1]  = "Equity: $" + DoubleToString(g_equity, 2);
   lines[2]  = "Regime: " + RegimeToStr(g_regime);
   lines[3]  = "ATR %ile: " + DoubleToString(pct, 0) + "%";
   lines[4]  = "RSI: " + DoubleToString(rsi[0], 1);
   lines[5]  = "Daily PnL: $" + DoubleToString(g_daily_pnl, 2);
   lines[6]  = "Consec Loss: " + IntegerToString(g_consec_loss);
   lines[7]  = "Cooldown: " + IntegerToString(g_cooldown);
   lines[8]  = "Status: " + (g_paused ? "PAUSED" : "ACTIVE");
   lines[9]  = InpLiveExecution ? "MODE: LIVE" : "MODE: PAPER";
   lines[10] = "Risk: " + DoubleToString(InpRiskPerTrade*100, 2) + "%";
   lines[11] = "SL: " + DoubleToString(InpAtrStopMult, 1) + "x ATR";
   lines[12] = "TP: " + DoubleToString(InpAtrTargetMult, 1) + "x ATR";
   lines[13] = "Trail: " + (InpUseTrailing ? "ON" : "OFF");
   lines[14] = "Open: " + (g_ticket > 0 ? "YES" : "NO");
   lines[15] = "Bars Held: " + IntegerToString(g_bars_held);
   lines[16] = "Peak: $" + DoubleToString(g_peak_equity, 2);
   lines[17] = "DD: " + DoubleToString((g_peak_equity-g_equity)/g_peak_equity*100, 2) + "%";
   lines[18] = "Symbol: " + _Symbol;
   lines[19] = "Magic: " + IntegerToString(InpMagic);
   lines[20] = "v15: Native + Risk Lots";
   lines[21] = "Best on: Volatility 75";

   for(int i=0; i<22; i++)
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
      if(i==5) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i==8) c = g_paused ? clrRed : clrLime;
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
   string name = "M15SIG_" + tag + "_" + IntegerToString((int)t);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir>0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir>0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}

//+------------------------------------------------------------------+
