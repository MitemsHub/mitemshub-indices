//+------------------------------------------------------------------+
//|                                         MitemshubAI_v17_2.mq5    |
//|                     MITEMSHUB AI MARKET ENGINE v17.2              |
//|   H1 Entry + H4 Regime • Strengthened Trend Logic • V10 Tuned     |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "17.20"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Regime (Higher TF) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input bool   InpTrendOnly        = true;      // Recommended true for cleaner multi-hour trades
input double InpMinEmaSeparation = 0.25;      // Min EMA distance in ATR (trend strength)

input group "=== Pullback Entry (Entry TF) ==="
input double InpPullbackMin      = 0.40;      // Strengthened from 0.10
input double InpPullbackMax      = 2.20;
input int    InpRsiPeriod        = 14;
input double InpRsiBuyMax        = 62.0;
input double InpRsiSellMin       = 38.0;

input group "=== Momentum (Ranging only) ==="
input bool   InpUseMomentum      = true;
input int    InpMomLookback      = 10;
input double InpMomMinMove       = 1.0;
input double InpMomRsiBuy        = 52.0;
input double InpMomRsiSell       = 48.0;
input double InpSlopeThresh      = 0.35;

input group "=== ATR Volatility Filter ==="
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 150;
input double InpAtrLowPct        = 8.0;
input double InpAtrHighPct       = 90.0;

input group "=== Risk & Exits (V10 / Multi-hour) ==="
input double InpRiskPerTrade     = 0.004;
input double InpAtrStopMult      = 1.6;
input double InpAtrTargetMult    = 2.5;       // Target = 2.5 × Stop distance
input int    InpHoldBars         = 18;        // ~18 hours on H1
input double InpMaxDailyLossPct  = 0.025;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 3;
input bool   InpUseTrailing      = true;
input double InpTrailStartATR    = 0.9;
input double InpTrailDistATR     = 0.9;
input bool   InpUseBreakeven     = true;
input double InpBETriggerATR     = 1.1;

input group "=== Execution ==="
input long   InpMagic            = 7788130;
input int    InpMaxSlippagePts   = 50;
input int    InpWarmupBars       = 300;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;
input bool   InpDebugLog         = false;

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

ENUM_TIMEFRAMES g_tf_entry;
ENUM_TIMEFRAMES g_tf_regime;

int      hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;
int      hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E;

double   g_eq = 0, g_peak_eq = 0, g_daily_pnl = 0;
datetime g_day_start = 0;
int      g_cooldown = 0, g_consec_loss = 0;
bool     g_paused = false;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

int      g_trades = 0, g_wins = 0, g_losses = 0;
int      g_target_exits = 0, g_time_exits = 0, g_stop_exits = 0;
double   g_total_r = 0;

ulong    g_ticket = 0;
int      g_dir = 0;
double   g_entry = 0, g_sl = 0, g_tp = 0, g_orig_risk = 0;
datetime g_entry_time = 0;
int      g_bars_held = 0;
double   g_position_volume = 0;

double   atr_hist[];
int      atr_hist_count = 0;

string   dash_names[24];

//+------------------------------------------------------------------+
//| Helper: Regime TF                                                  |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES entry_tf)
{
   switch(entry_tf)
   {
      case PERIOD_M15: return PERIOD_H1;
      case PERIOD_H1:  return PERIOD_H4;
      case PERIOD_H4:  return PERIOD_D1;
      default:         return PERIOD_H4;
   }
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
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
   hRSI_E      = iRSI(_Symbol, g_tf_entry, InpRsiPeriod, PRICE_CLOSE);
   hATR_E      = iATR(_Symbol, g_tf_entry, InpAtrPeriod);

   if(hEMA_Fast_R == INVALID_HANDLE || hEMA_Mid_R == INVALID_HANDLE || hEMA_Slow_R == INVALID_HANDLE ||
      hEMA_Fast_E == INVALID_HANDLE || hEMA_Mid_E == INVALID_HANDLE || hEMA_Slow_E == INVALID_HANDLE ||
      hRSI_E == INVALID_HANDLE || hATR_E == INVALID_HANDLE)
   {
      Print("v17.2: Indicator handles failed");
      return INIT_FAILED;
   }

   ArrayResize(atr_hist, InpAtrLookback + 50);
   ArrayInitialize(atr_hist, 0.0);
   atr_hist_count = 0;

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   RecoverPosition();

   if(InpDrawDashboard) CreateDashboard();

   PrintFormat("MITEMSHUB AI v17.2 started | Entry=%s Regime=%s | TrendOnly=%s | Risk=%.2f%%",
               EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpTrendOnly ? "ON" : "OFF", InpRiskPerTrade*100);
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

   for(int i = 0; i < 24; i++) ObjectDelete(0, dash_names[i]);

   double wr = (g_trades > 0) ? 100.0 * g_wins / g_trades : 0.0;
   double dd = (g_peak_eq > 0) ? (g_peak_eq - g_eq) / g_peak_eq * 100.0 : 0.0;

   Print("========================================");
   Print("MITEMSHUB AI v17.2 — SESSION SUMMARY");
   PrintFormat("Symbol: %s | TF: %s / %s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   PrintFormat("Trades: %d | WR: %.1f%% | Total R: %+.3f", g_trades, wr, g_total_r);
   PrintFormat("Exits → Target: %d | Time: %d | Stop: %d", g_target_exits, g_time_exits, g_stop_exits);
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

   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start)
   {
      g_day_start = ds;
      g_daily_pnl = 0;
      // Optional: reset pause daily
      // g_paused = false;
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
//| Recover                                                            |
//+------------------------------------------------------------------+
void RecoverPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      g_ticket = ticket;
      g_dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      g_entry = PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl = PositionGetDouble(POSITION_SL);
      g_tp = PositionGetDouble(POSITION_TP);
      g_orig_risk = MathAbs(g_entry - g_sl);
      g_position_volume = PositionGetDouble(POSITION_VOLUME);
      g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held = 0;
      PrintFormat("v17.2: Recovered position #%d", ticket);
      break;
   }
}

//+------------------------------------------------------------------+
//| Regime Classification (with ATR filter)                            |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hEMA_Fast_R, 0, 1, 1, emaF) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_R,  0, 1, 1, emaM) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_R, 0, 1, 1, emaS) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_E,      0, 1, 1, atr)  < 1) return REGIME_NO_TRADE;

   // Update ATR history
   if(atr_hist_count < ArraySize(atr_hist))
      atr_hist[atr_hist_count++] = atr[0];
   else
   {
      for(int i = 0; i < ArraySize(atr_hist)-1; i++) atr_hist[i] = atr_hist[i+1];
      atr_hist[ArraySize(atr_hist)-1] = atr[0];
   }

   double pct = CalcATRPercentile(atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);
   double sep = MathAbs(emaF[0] - emaM[0]) / atr[0];

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0] && sep >= InpMinEmaSeparation)
      return REGIME_BULLISH;
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0] && sep >= InpMinEmaSeparation)
      return REGIME_BEARISH;

   return REGIME_RANGING;
}

double CalcATRPercentile(double current)
{
   if(atr_hist_count < 40) return 50.0;
   int below = 0;
   int look = MathMin(InpAtrLookback, atr_hist_count);
   for(int i = atr_hist_count - look; i < atr_hist_count; i++)
      if(current > atr_hist[i]) below++;
   return (double)below / look * 100.0;
}

//+------------------------------------------------------------------+
//| Signal Generation                                                  |
//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE || g_regime == REGIME_HIGH_VOL) return 0;

   if(InpTrendOnly && g_regime == REGIME_RANGING) return 0;

   double emaF[1], emaM[1], emaS[1], rsi[1], atr[1];
   if(CopyBuffer(hEMA_Fast_E, 0, 1, 1, emaF) < 1) return 0;
   if(CopyBuffer(hEMA_Mid_E,  0, 1, 1, emaM) < 1) return 0;
   if(CopyBuffer(hEMA_Slow_E, 0, 1, 1, emaS) < 1) return 0;
   if(CopyBuffer(hRSI_E,      0, 1, 1, rsi)  < 1) return 0;
   if(CopyBuffer(hATR_E,      0, 1, 1, atr)  < 1) return 0;

   double price = iClose(_Symbol, g_tf_entry, 1);
   double prev_close = iClose(_Symbol, g_tf_entry, 2);
   double body = price - prev_close;

   // ========== MODE 1: High-quality Pullback ==========
   if(g_regime == REGIME_BULLISH || g_regime == REGIME_BEARISH)
   {
      int dir = (g_regime == REGIME_BULLISH) ? 1 : -1;
      double pb = MathAbs(price - emaF[0]);

      if(pb < InpPullbackMin * atr[0] || pb > InpPullbackMax * atr[0]) return 0;

      // Must be on the correct side / near the EMA
      if(dir > 0 && price > emaF[0] + 0.7 * atr[0]) return 0;
      if(dir < 0 && price < emaF[0] - 0.7 * atr[0]) return 0;

      // RSI
      if(dir > 0 && rsi[0] > InpRsiBuyMax) return 0;
      if(dir < 0 && rsi[0] < InpRsiSellMin) return 0;

      // Entry TF must also be aligned
      if(dir > 0 && !(emaF[0] > emaM[0] && emaM[0] > emaS[0])) return 0;
      if(dir < 0 && !(emaF[0] < emaM[0] && emaM[0] < emaS[0])) return 0;

      // Prefer a candle in the trade direction (mild confirmation)
      if(dir > 0 && body < -0.15 * atr[0]) return 0;
      if(dir < 0 && body >  0.15 * atr[0]) return 0;

      sig_type = (dir > 0) ? "PULLBACK_LONG" : "PULLBACK_SHORT";
      return dir;
   }

   // ========== MODE 2: Momentum in Ranging ==========
   if(InpUseMomentum && g_regime == REGIME_RANGING)
   {
      double ema_now[1], ema_prev[1];
      if(CopyBuffer(hEMA_Fast_E, 0, 1, 1, ema_now) < 1) return 0;
      if(CopyBuffer(hEMA_Fast_E, 0, 6, 1, ema_prev) < 1) return 0;

      int dir = 0;
      if(ema_now[0] > ema_prev[0] + InpSlopeThresh * atr[0]) dir = 1;
      else if(ema_now[0] < ema_prev[0] - InpSlopeThresh * atr[0]) dir = -1;
      if(dir == 0) return 0;

      double hh = iHigh(_Symbol, g_tf_entry, 1);
      double ll = iLow(_Symbol, g_tf_entry, 1);
      for(int i = 2; i <= InpMomLookback; i++)
      {
         hh = MathMax(hh, iHigh(_Symbol, g_tf_entry, i));
         ll = MathMin(ll, iLow(_Symbol, g_tf_entry, i));
      }

      double move_up = price - ll;
      double move_dn = hh - price;

      if(dir > 0 && move_up > InpMomMinMove * atr[0] && rsi[0] > InpMomRsiBuy && body > 0)
      {
         sig_type = "MOMENTUM_LONG";
         return 1;
      }
      if(dir < 0 && move_dn > InpMomMinMove * atr[0] && rsi[0] < InpMomRsiSell && body < 0)
      {
         sig_type = "MOMENTUM_SHORT";
         return -1;
      }
   }

   return 0;
}

//+------------------------------------------------------------------+
//| Open Trade                                                         |
//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1];
   if(CopyBuffer(hATR_E, 0, 1, 1, atr) < 1) return;

   double entry = (direction > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                  : SymbolInfoDouble(_Symbol, SYMBOL_BID);

   double stop_dist = InpAtrStopMult * atr[0];
   double tp_dist   = InpAtrTargetMult * stop_dist;

   double max_stop = entry * 0.03;
   if(stop_dist > max_stop) stop_dist = max_stop;
   if(stop_dist < atr[0] * 0.4) stop_dist = atr[0] * 0.4;

   double sl = (direction > 0) ? entry - stop_dist : entry + stop_dist;
   double tp = (direction > 0) ? entry + tp_dist   : entry - tp_dist;

   // Proper risk volume
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = equity * InpRiskPerTrade;
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tick_size <= 0 || tick_value <= 0) return;

   double ticks_in_stop = stop_dist / tick_size;
   double loss_per_lot = ticks_in_stop * tick_value;
   if(loss_per_lot <= 0) return;

   double vol = risk_money / loss_per_lot;
   vol = NormalizeVolume(vol);
   if(vol <= 0) return;

   bool ok = false;
   if(InpLiveExecution)
   {
      if(direction > 0)
         ok = trade.Buy(vol, _Symbol, 0, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v17.2");
      else
         ok = trade.Sell(vol, _Symbol, 0, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v17.2");
   }
   else
   {
      g_ticket = (ulong)TimeCurrent();
      ok = true;
   }

   if(!ok)
   {
      PrintFormat("v17.2 Order failed: %d %s", trade.ResultRetcode(), trade.ResultComment());
      g_cooldown = InpCoolDownBars;
      return;
   }

   // Robust ticket capture
   g_ticket = 0;
   for(int attempt = 0; attempt < 8; attempt++)
   {
      Sleep(80);
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         if((TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME)) > 15) continue;
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

   if(InpDrawSignals) DrawArrow(direction, TimeCurrent(), entry, sig_type);

   PrintFormat("[v17.2] %s %s @%.5f SL=%.5f TP=%.5f Vol=%.2f Regime=%s",
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
//| Manage Position                                                    |
//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)) { g_ticket = 0; return; }

   g_bars_held++;

   double atr[1];
   if(CopyBuffer(hATR_E, 0, 0, 1, atr) < 1) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   if(g_bars_held >= InpHoldBars)
   {
      ClosePosition("TIME");
      return;
   }

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
      double trigger = InpBETriggerATR * atr[0];
      if(g_dir > 0 && bid >= g_entry + trigger && g_sl < g_entry)
      {
         double new_sl = NormalizeDouble(g_entry + 3*_Point, _Digits);
         if(trade.PositionModify(g_ticket, new_sl, g_tp)) g_sl = new_sl;
      }
      if(g_dir < 0 && ask <= g_entry - trigger && g_sl > g_entry)
      {
         double new_sl = NormalizeDouble(g_entry - 3*_Point, _Digits);
         if(trade.PositionModify(g_ticket, new_sl, g_tp)) g_sl = new_sl;
      }
   }

   // Trailing
   if(InpUseTrailing)
   {
      double start = InpTrailStartATR * atr[0];
      double dist  = InpTrailDistATR * atr[0];

      if(g_dir > 0 && bid >= g_entry + start)
      {
         double new_sl = NormalizeDouble(bid - dist, _Digits);
         if(new_sl > g_sl && new_sl > g_entry)
            if(trade.PositionModify(g_ticket, new_sl, g_tp)) g_sl = new_sl;
      }
      if(g_dir < 0 && ask <= g_entry - start)
      {
         double new_sl = NormalizeDouble(ask + dist, _Digits);
         if(new_sl < g_sl && new_sl > g_entry)
            if(trade.PositionModify(g_ticket, new_sl, g_tp)) g_sl = new_sl;
      }
   }
}

//+------------------------------------------------------------------+
//| Close Position (accurate R)                                        |
//+------------------------------------------------------------------+
void ClosePosition(string reason)
{
   if(g_ticket == 0) return;

   double exit_price = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                                   : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   bool closed = trade.PositionClose(g_ticket);
   if(!closed)
   {
      PrintFormat("v17.2 Close failed: %d", trade.ResultRetcode());
      return;
   }

   // Calculate R from price distance (most reliable)
   double r_mult = 0;
   if(g_orig_risk > 0)
      r_mult = (g_dir > 0) ? (exit_price - g_entry) / g_orig_risk
                           : (g_entry - exit_price) / g_orig_risk;

   g_trades++;
   g_total_r += r_mult;
   if(r_mult > 0) g_wins++; else g_losses++;

   if(reason == "TARGET") g_target_exits++;
   else if(reason == "TIME") g_time_exits++;
   else if(reason == "STOP") g_stop_exits++;

   // Approximate money PnL for daily tracking
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double pnl_money = 0;
   if(tick_size > 0)
      pnl_money = ((exit_price - g_entry) * g_dir / tick_size) * tick_value * g_position_volume;

   g_daily_pnl += pnl_money;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
   }
   else g_consec_loss = 0;

   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_eq - g_eq) > g_peak_eq * 0.12) g_paused = true;

   PrintFormat("[v17.2] CLOSE %s R=%+.3f | TotalR=%+.2f", reason, r_mult, g_total_r);

   g_ticket = 0;
   g_dir = 0;
   g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| Dashboard                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i = 0; i < 24; i++)
   {
      dash_names[i] = "MITEM172_" + IntegerToString(i);
      ObjectCreate(0, dash_names[i], OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, dash_names[i], OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, dash_names[i], OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, dash_names[i], OBJPROP_YDISTANCE, 16 + i*15);
      ObjectSetString(0, dash_names[i], OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, dash_names[i], OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, clrWhite);
   }
}

void UpdateDashboard()
{
   double wr = (g_trades > 0) ? 100.0 * g_wins / g_trades : 0;
   double dd = (g_peak_eq > 0) ? (g_peak_eq - g_eq) / g_peak_eq * 100.0 : 0;
   double atr[1]; CopyBuffer(hATR_E, 0, 0, 1, atr);
   double pct = CalcATRPercentile(atr[0]);

   string L[24];
   L[0]  = "=== MITEMSHUB AI v17.2 ===";
   L[1]  = StringFormat("%s | %s → %s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   L[2]  = StringFormat("Equity: $%.2f | Peak: $%.2f", g_eq, g_peak_eq);
   L[3]  = StringFormat("Regime: %s | ATR%%: %.0f", RegimeToStr(g_regime), pct);
   L[4]  = StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f", g_trades, wr, g_total_r);
   L[5]  = StringFormat("Daily: $%.2f | ConsecL: %d", g_daily_pnl, g_consec_loss);
   L[6]  = StringFormat("Status: %s | CD: %d", g_paused ? "PAUSED" : "ACTIVE", g_cooldown);
   L[7]  = StringFormat("Risk: %.2f%% | SL: %.1fx | TP: %.1fxSL", InpRiskPerTrade*100, InpAtrStopMult, InpAtrTargetMult);
   L[8]  = StringFormat("Trail: %.1f/%.1f | BE: %.1f", InpTrailStartATR, InpTrailDistATR, InpBETriggerATR);
   L[9]  = StringFormat("Hold: %d bars | TrendOnly: %s", InpHoldBars, InpTrendOnly?"ON":"OFF");
   L[10] = StringFormat("MaxDD: %.2f%% | T/T/S: %d/%d/%d", dd, g_target_exits, g_time_exits, g_stop_exits);
   L[11] = InpLiveExecution ? "MODE: LIVE" : "MODE: PAPER";

   int line = 12;
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      double cur = (g_dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      L[line++] = StringFormat("OPEN %s @%.5f", g_dir>0?"BUY":"SELL", g_entry);
      L[line++] = StringFormat("SL: %.5f | TP: %.5f", g_sl, g_tp);
      L[line++] = StringFormat("Held: %d bars | Cur: %.5f", g_bars_held, cur);
   }
   while(line < 24) L[line++] = "";

   for(int i = 0; i < 24; i++)
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
      if(i == 5) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i == 6) c = g_paused ? clrRed : clrLime;
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
   string name = "M172_" + tag + "_" + IntegerToString((int)t);
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir > 0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir > 0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}
//+------------------------------------------------------------------+
