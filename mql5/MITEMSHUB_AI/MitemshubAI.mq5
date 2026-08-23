//+------------------------------------------------------------------+
//|                                         MitemshubAI_v17_3.mq5    |
//|                     MITEMSHUB AI MARKET ENGINE v17.3              |
//|   H1 + H4 • Session Filter • Session SL • Early Time Exit         |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "17.30"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Session Filter (UTC Server Time) ==="
input bool   InpUseSessionFilter = false;
input int    InpSessionStartHour = 0;         // 0-23 UTC
input int    InpSessionEndHour   = 24;        // 24 = full day

input group "=== Session-Specific Stop Loss (UTC) ==="
input bool   InpUseSessionSL     = true;      // Enable different SL by hour
input double InpSL_Quiet         = 1.40;      // SL multiplier during quiet hours
input double InpSL_Active        = 1.60;      // SL multiplier during active hours
input int    InpQuietStartHour   = 0;         // Quiet hours start (UTC)
input int    InpQuietEndHour     = 7;         // Quiet hours end (UTC)

input group "=== Time-Based Exit Logic ==="
input int    InpHoldBars         = 18;        // Maximum hold (hours on H1)
input int    InpEarlyExitHours   = 6;         // Close early if not profitable after X hours
input double InpEarlyExitMinR    = 0.15;      // Minimum R to keep the trade alive
input bool   InpUseHardClose     = false;     // Force close all trades at specific hour
input int    InpHardCloseHour    = 21;        // Hour to force close (UTC)

input group "=== Regime (Higher TF) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input bool   InpTrendOnly        = true;
input double InpMinEmaSeparation = 0.25;

input group "=== Pullback Entry ==="
input double InpPullbackMin      = 0.40;
input double InpPullbackMax      = 2.20;
input int    InpRsiPeriod        = 14;
input double InpRsiBuyMax        = 62.0;
input double InpRsiSellMin       = 38.0;

input group "=== Momentum ==="
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

input group "=== Risk & Trailing ==="
input double InpRiskPerTrade     = 0.004;
input double InpAtrTargetMult    = 2.5;       // Target = multiplier × Stop distance
input double InpMaxDailyLossPct  = 0.025;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 3;
input bool   InpUseTrailing      = true;
input double InpTrailStartATR    = 0.9;
input double InpTrailDistATR     = 0.9;
input bool   InpUseBreakeven     = true;
input double InpBETriggerATR     = 1.1;

input group "=== Execution ==="
input long   InpMagic            = 7788131;
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

ENUM_TIMEFRAMES g_tf_entry, g_tf_regime;

int hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;
int hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E;

double g_eq=0, g_peak_eq=0, g_daily_pnl=0;
datetime g_day_start=0;
int g_cooldown=0, g_consec_loss=0;
bool g_paused=false;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

int g_trades=0, g_wins=0, g_losses=0;
int g_target_exits=0, g_time_exits=0, g_stop_exits=0, g_early_exits=0;
double g_total_r=0;

ulong g_ticket=0;
int g_dir=0;
double g_entry=0, g_sl=0, g_tp=0, g_orig_risk=0, g_position_volume=0;
datetime g_entry_time=0;
int g_bars_held=0;

double atr_hist[];
int atr_hist_count=0;
string dash_names[26];

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES entry_tf)
{
   if(entry_tf == PERIOD_H1) return PERIOD_H4;
   if(entry_tf == PERIOD_H4) return PERIOD_D1;
   if(entry_tf == PERIOD_M15) return PERIOD_H1;
   return PERIOD_H4;
}

//+------------------------------------------------------------------+
//| Session helpers                                                    |
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

bool IsQuietHour()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int h = dt.hour;
   if(InpQuietStartHour < InpQuietEndHour)
      return (h >= InpQuietStartHour && h < InpQuietEndHour);
   return (h >= InpQuietStartHour || h < InpQuietEndHour);
}

double GetCurrentStopMult()
{
   if(!InpUseSessionSL) return 1.60;
   return IsQuietHour() ? InpSL_Quiet : InpSL_Active;
}

string GetSessionStr()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return StringFormat("%02d:00 UTC %s", dt.hour, IsQuietHour() ? "(Quiet)" : "(Active)");
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
   hRSI_E      = iRSI(_Symbol, g_tf_entry, InpRsiPeriod, PRICE_CLOSE);
   hATR_E      = iATR(_Symbol, g_tf_entry, InpAtrPeriod);

   if(hEMA_Fast_R==INVALID_HANDLE || hEMA_Mid_R==INVALID_HANDLE || hEMA_Slow_R==INVALID_HANDLE ||
      hEMA_Fast_E==INVALID_HANDLE || hEMA_Mid_E==INVALID_HANDLE || hEMA_Slow_E==INVALID_HANDLE ||
      hRSI_E==INVALID_HANDLE || hATR_E==INVALID_HANDLE)
   {
      Print("v17.3: Handle creation failed");
      return INIT_FAILED;
   }

   ArrayResize(atr_hist, InpAtrLookback+50);
   ArrayInitialize(atr_hist, 0.0);

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);

   RecoverPosition();
   if(InpDrawDashboard) CreateDashboard();

   Print("MITEMSHUB AI v17.3 started | Session SL + Early Exit active | All times = Server/UTC");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_R); IndicatorRelease(hEMA_Mid_R); IndicatorRelease(hEMA_Slow_R);
   IndicatorRelease(hEMA_Fast_E); IndicatorRelease(hEMA_Mid_E); IndicatorRelease(hEMA_Slow_E);
   IndicatorRelease(hRSI_E); IndicatorRelease(hATR_E);

   for(int i=0; i<26; i++) ObjectDelete(0, dash_names[i]);

   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   Print("========================================");
   PrintFormat("v17.3 Summary | Trades:%d WR:%.1f%% TotalR:%+.2f", g_trades, wr, g_total_r);
   PrintFormat("Exits → Target:%d Time:%d Early:%d Stop:%d", g_target_exits, g_time_exits, g_early_exits, g_stop_exits);
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
   if(ds != g_day_start) { g_day_start = ds; g_daily_pnl = 0; }

   if(g_cooldown > 0) g_cooldown--;

   // Hard close at specific hour
   if(InpUseHardClose && g_ticket > 0)
   {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      if(dt.hour == InpHardCloseHour && dt.min < 5)
         ClosePosition("HARD_CLOSE");
   }

   if(g_ticket > 0)
   {
      if(PositionSelectByTicket(g_ticket))
         ManagePosition();
      else
         g_ticket = 0;
   }

   if(g_ticket == 0 && !g_paused && g_cooldown == 0 &&
      Bars(_Symbol, g_tf_entry) >= InpWarmupBars && IsInSession())
   {
      string sig = "";
      int dir = GenerateSignal(sig);
      if(dir != 0) OpenTrade(dir, sig);
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
void RecoverPosition()
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t==0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;

      g_ticket = t;
      g_dir = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1;
      g_entry = PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl = PositionGetDouble(POSITION_SL);
      g_tp = PositionGetDouble(POSITION_TP);
      g_orig_risk = MathAbs(g_entry - g_sl);
      g_position_volume = PositionGetDouble(POSITION_VOLUME);
      g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held = 0;
      Print("v17.3: Recovered position #", t);
      break;
   }
}

//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1], atr[1];
   if(CopyBuffer(hEMA_Fast_R,0,1,1,emaF)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_R,0,1,1,emaM)<1)  return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_R,0,1,1,emaS)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)       return REGIME_NO_TRADE;

   if(atr_hist_count < ArraySize(atr_hist))
      atr_hist[atr_hist_count++] = atr[0];
   else
   {
      for(int i=0;i<ArraySize(atr_hist)-1;i++) atr_hist[i]=atr_hist[i+1];
      atr_hist[ArraySize(atr_hist)-1] = atr[0];
   }

   double pct = CalcATRPercentile(atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);
   double sep = MathAbs(emaF[0]-emaM[0])/atr[0];

   if(emaF[0]>emaM[0] && emaM[0]>emaS[0] && price>emaF[0] && sep>=InpMinEmaSeparation)
      return REGIME_BULLISH;
   if(emaF[0]<emaM[0] && emaM[0]<emaS[0] && price<emaF[0] && sep>=InpMinEmaSeparation)
      return REGIME_BEARISH;

   return REGIME_RANGING;
}

double CalcATRPercentile(double current)
{
   if(atr_hist_count < 40) return 50.0;
   int below=0, look=MathMin(InpAtrLookback, atr_hist_count);
   for(int i=atr_hist_count-look; i<atr_hist_count; i++)
      if(current > atr_hist[i]) below++;
   return (double)below/look*100.0;
}

//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime==REGIME_NO_TRADE || g_regime==REGIME_HIGH_VOL) return 0;
   if(InpTrendOnly && g_regime==REGIME_RANGING) return 0;

   double emaF[1],emaM[1],emaS[1],rsi[1],atr[1];
   if(CopyBuffer(hEMA_Fast_E,0,1,1,emaF)<1) return 0;
   if(CopyBuffer(hEMA_Mid_E,0,1,1,emaM)<1)  return 0;
   if(CopyBuffer(hEMA_Slow_E,0,1,1,emaS)<1) return 0;
   if(CopyBuffer(hRSI_E,0,1,1,rsi)<1)       return 0;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)       return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   double body  = price - iClose(_Symbol,g_tf_entry,2);

   if(g_regime==REGIME_BULLISH || g_regime==REGIME_BEARISH)
   {
      int dir = (g_regime==REGIME_BULLISH) ? 1 : -1;
      double pb = MathAbs(price - emaF[0]);

      if(pb < InpPullbackMin*atr[0] || pb > InpPullbackMax*atr[0]) return 0;
      if(dir>0 && price > emaF[0]+0.7*atr[0]) return 0;
      if(dir<0 && price < emaF[0]-0.7*atr[0]) return 0;
      if(dir>0 && rsi[0] > InpRsiBuyMax) return 0;
      if(dir<0 && rsi[0] < InpRsiSellMin) return 0;
      if(dir>0 && !(emaF[0]>emaM[0] && emaM[0]>emaS[0])) return 0;
      if(dir<0 && !(emaF[0]<emaM[0] && emaM[0]<emaS[0])) return 0;
      if(dir>0 && body < -0.15*atr[0]) return 0;
      if(dir<0 && body >  0.15*atr[0]) return 0;

      sig_type = dir>0 ? "PULLBACK_LONG" : "PULLBACK_SHORT";
      return dir;
   }

   if(InpUseMomentum && g_regime==REGIME_RANGING)
   {
      double ema_now[1], ema_prev[1];
      CopyBuffer(hEMA_Fast_E,0,1,1,ema_now);
      CopyBuffer(hEMA_Fast_E,0,6,1,ema_prev);

      int dir=0;
      if(ema_now[0] > ema_prev[0] + InpSlopeThresh*atr[0]) dir=1;
      else if(ema_now[0] < ema_prev[0] - InpSlopeThresh*atr[0]) dir=-1;
      if(dir==0) return 0;

      double hh=iHigh(_Symbol,g_tf_entry,1), ll=iLow(_Symbol,g_tf_entry,1);
      for(int i=2;i<=InpMomLookback;i++)
      {
         hh = MathMax(hh, iHigh(_Symbol,g_tf_entry,i));
         ll = MathMin(ll, iLow(_Symbol,g_tf_entry,i));
      }

      if(dir>0 && (price-ll)>InpMomMinMove*atr[0] && rsi[0]>InpMomRsiBuy && body>0)
      { sig_type="MOMENTUM_LONG"; return 1; }
      if(dir<0 && (hh-price)>InpMomMinMove*atr[0] && rsi[0]<InpMomRsiSell && body<0)
      { sig_type="MOMENTUM_SHORT"; return -1; }
   }
   return 0;
}

//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1];
   if(CopyBuffer(hATR_E,0,1,1,atr)<1) return;

   double entry = direction>0 ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double stop_mult = GetCurrentStopMult();
   double stop_dist = stop_mult * atr[0];
   double tp_dist   = InpAtrTargetMult * stop_dist;

   double max_stop = entry * 0.03;
   if(stop_dist > max_stop) stop_dist = max_stop;
   if(stop_dist < atr[0]*0.4) stop_dist = atr[0]*0.4;

   double sl = direction>0 ? entry-stop_dist : entry+stop_dist;
   double tp = direction>0 ? entry+tp_dist   : entry-tp_dist;

   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPerTrade;
   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tick_size<=0 || tick_value<=0) return;

   double vol = risk_money / ((stop_dist/tick_size)*tick_value);
   vol = NormalizeVolume(vol);
   if(vol<=0) return;

   bool ok=false;
   if(InpLiveExecution)
   {
      if(direction>0)
         ok = trade.Buy(vol,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"MITEM_v17.3");
      else
         ok = trade.Sell(vol,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"MITEM_v17.3");
   }
   else { g_ticket=(ulong)TimeCurrent(); ok=true; }

   if(!ok)
   {
      Print("Order failed: ",trade.ResultRetcode());
      g_cooldown = InpCoolDownBars;
      return;
   }

   // Ticket recovery
   g_ticket=0;
   for(int a=0;a<8;a++)
   {
      Sleep(80);
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong t=PositionGetTicket(i);
         if(t==0) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
         if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
         if(TimeCurrent()-(datetime)PositionGetInteger(POSITION_TIME)>15) continue;
         g_ticket=t; break;
      }
      if(g_ticket>0) break;
   }
   if(g_ticket==0) g_ticket=trade.ResultOrder();

   g_dir=direction; g_entry=entry; g_sl=sl; g_tp=tp;
   g_orig_risk=stop_dist; g_position_volume=vol;
   g_entry_time=TimeCurrent(); g_bars_held=0;

   if(InpDrawSignals) DrawArrow(direction,TimeCurrent(),entry,sig_type);

   PrintFormat("[v17.3] %s %s @%.5f SL=%.5f (mult=%.2f) TP=%.5f",
               sig_type, direction>0?"BUY":"SELL", entry, sl, stop_mult, tp);
}

double NormalizeVolume(double vol)
{
   double minv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=0.01;
   vol=MathFloor(vol/step)*step;
   if(vol<minv) vol=minv;
   if(vol>maxv) vol=maxv;
   return NormalizeDouble(vol,2);
}

//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)) { g_ticket=0; return; }

   g_bars_held++;

   double atr[1];
   CopyBuffer(hATR_E,0,0,1,atr);

   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double current = g_dir>0 ? bid : ask;

   // === Early Exit: not profitable after X hours ===
   double hours_open = (double)(TimeCurrent() - g_entry_time) / 3600.0;
   if(hours_open >= InpEarlyExitHours)
   {
      double r_now = g_orig_risk>0 ? (g_dir>0 ? (current-g_entry) : (g_entry-current)) / g_orig_risk : 0;
      if(r_now < InpEarlyExitMinR)
      {
         ClosePosition("EARLY");
         return;
      }
   }

   // Max hold
   if(g_bars_held >= InpHoldBars)
   {
      ClosePosition("TIME");
      return;
   }

   // SL / TP
   if(g_dir>0)
   {
      if(bid<=g_sl){ClosePosition("STOP"); return;}
      if(bid>=g_tp){ClosePosition("TARGET"); return;}
   }
   else
   {
      if(ask>=g_sl){ClosePosition("STOP"); return;}
      if(ask<=g_tp){ClosePosition("TARGET"); return;}
   }

   // Breakeven
   if(InpUseBreakeven)
   {
      double trigger = InpBETriggerATR * atr[0];
      if(g_dir>0 && bid>=g_entry+trigger && g_sl<g_entry)
      {
         double newsl = NormalizeDouble(g_entry+3*_Point,_Digits);
         if(trade.PositionModify(g_ticket,newsl,g_tp)) g_sl=newsl;
      }
      if(g_dir<0 && ask<=g_entry-trigger && g_sl>g_entry)
      {
         double newsl = NormalizeDouble(g_entry-3*_Point,_Digits);
         if(trade.PositionModify(g_ticket,newsl,g_tp)) g_sl=newsl;
      }
   }

   // Trailing
   if(InpUseTrailing)
   {
      double start=InpTrailStartATR*atr[0];
      double dist =InpTrailDistATR*atr[0];
      if(g_dir>0 && bid>=g_entry+start)
      {
         double newsl=NormalizeDouble(bid-dist,_Digits);
         if(newsl>g_sl && newsl>g_entry)
            if(trade.PositionModify(g_ticket,newsl,g_tp)) g_sl=newsl;
      }
      if(g_dir<0 && ask<=g_entry-start)
      {
         double newsl=NormalizeDouble(ask+dist,_Digits);
         if(newsl<g_sl && newsl>g_entry)
            if(trade.PositionModify(g_ticket,newsl,g_tp)) g_sl=newsl;
      }
   }
}

//+------------------------------------------------------------------+
void ClosePosition(string reason)
{
   if(g_ticket==0) return;

   double exit_price = g_dir>0 ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   if(!trade.PositionClose(g_ticket))
   {
      Print("Close failed: ",trade.ResultRetcode());
      return;
   }

   double r_mult = g_orig_risk>0 ? (g_dir>0?(exit_price-g_entry):(g_entry-exit_price))/g_orig_risk : 0;

   g_trades++;
   g_total_r += r_mult;
   if(r_mult>0) g_wins++; else g_losses++;

   if(reason=="TARGET")     g_target_exits++;
   else if(reason=="TIME")  g_time_exits++;
   else if(reason=="EARLY") g_early_exits++;
   else if(reason=="STOP")  g_stop_exits++;

   if(r_mult<0){ g_consec_loss++; g_cooldown=InpCoolDownBars; }
   else g_consec_loss=0;

   if(g_consec_loss>=InpMaxConsecLoss) g_paused=true;
   if(g_daily_pnl < -AccountInfoDouble(ACCOUNT_EQUITY)*InpMaxDailyLossPct) g_paused=true;

   PrintFormat("[v17.3] CLOSE %s R=%+.3f", reason, r_mult);

   g_ticket=0; g_dir=0; g_bars_held=0;
}

//+------------------------------------------------------------------+
//| Dashboard                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i=0;i<26;i++)
   {
      dash_names[i]="M173_"+IntegerToString(i);
      ObjectCreate(0,dash_names[i],OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,dash_names[i],OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,dash_names[i],OBJPROP_XDISTANCE,10);
      ObjectSetInteger(0,dash_names[i],OBJPROP_YDISTANCE,16+i*15);
      ObjectSetString(0,dash_names[i],OBJPROP_FONT,"Consolas");
      ObjectSetInteger(0,dash_names[i],OBJPROP_FONTSIZE,9);
      ObjectSetInteger(0,dash_names[i],OBJPROP_COLOR,clrWhite);
   }
}

void UpdateDashboard()
{
   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   double dd = g_peak_eq>0 ? (g_peak_eq-g_eq)/g_peak_eq*100 : 0;
   double atr[1]; CopyBuffer(hATR_E,0,0,1,atr);
   double pct = CalcATRPercentile(atr[0]);

   string L[26];
   L[0]  = "=== MITEMSHUB AI v17.3 ===";
   L[1]  = StringFormat("%s | %s > %s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   L[2]  = StringFormat("Equity: $%.2f | Peak: $%.2f", g_eq, g_peak_eq);
   L[3]  = StringFormat("Regime: %s | ATR%%: %.0f", RegimeToStr(g_regime), pct);
   L[4]  = StringFormat("Session: %s", GetSessionStr());
   L[5]  = StringFormat("SL Mode: %s (%.2f×ATR)", IsQuietHour()?"Quiet":"Active", GetCurrentStopMult());
   L[6]  = StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f", g_trades, wr, g_total_r);
   L[7]  = StringFormat("Daily: $%.2f | ConsecL: %d", g_daily_pnl, g_consec_loss);
   L[8]  = StringFormat("Status: %s | CD: %d", g_paused?"PAUSED":"ACTIVE", g_cooldown);
   L[9]  = StringFormat("Risk: %.2f%% | TP: %.1fxSL", InpRiskPerTrade*100, InpAtrTargetMult);
   L[10] = StringFormat("Trail: %.1f/%.1f | BE: %.1f", InpTrailStartATR, InpTrailDistATR, InpBETriggerATR);
   L[11] = StringFormat("Hold: %d bars | Early: %dh @>%.2fR", InpHoldBars, InpEarlyExitHours, InpEarlyExitMinR);
   L[12] = StringFormat("MaxDD: %.2f%% | T/T/E/S: %d/%d/%d/%d", dd, g_target_exits, g_time_exits, g_early_exits, g_stop_exits);
   L[13] = InpLiveExecution ? "MODE: LIVE" : "MODE: PAPER";

   int line = 14;
   if(g_ticket>0 && PositionSelectByTicket(g_ticket))
   {
      double cur = g_dir>0 ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double r_now = g_orig_risk>0 ? (g_dir>0?(cur-g_entry):(g_entry-cur))/g_orig_risk : 0;
      double hrs = (double)(TimeCurrent()-g_entry_time)/3600.0;
      L[line++] = StringFormat("OPEN %s @%.5f", g_dir>0?"BUY":"SELL", g_entry);
      L[line++] = StringFormat("SL: %.5f | TP: %.5f", g_sl, g_tp);
      L[line++] = StringFormat("R: %+.2f | Held: %.1fh", r_now, hrs);
   }
   while(line < 26) L[line++] = "";

   for(int i=0;i<26;i++)
   {
      ObjectSetString(0,dash_names[i],OBJPROP_TEXT,L[i]);
      color c=clrWhite;
      if(i==0) c=clrGold;
      if(i==3)
      {
         if(g_regime==REGIME_BULLISH) c=clrLime;
         else if(g_regime==REGIME_BEARISH) c=clrRed;
         else if(g_regime==REGIME_RANGING) c=clrYellow;
         else c=clrGray;
      }
      if(i==5) c = IsQuietHour() ? clrGray : clrLime;
      if(i==7) c = (g_daily_pnl>=0) ? clrLime : clrRed;
      if(i==8) c = g_paused ? clrRed : clrLime;
      ObjectSetInteger(0,dash_names[i],OBJPROP_COLOR,c);
   }
   ChartRedraw();
}

string RegimeToStr(ENUM_REGIME r)
{
   if(r==REGIME_BULLISH) return "BULLISH";
   if(r==REGIME_BEARISH) return "BEARISH";
   if(r==REGIME_RANGING) return "RANGING";
   if(r==REGIME_HIGH_VOL) return "HIGH_VOL";
   return "NO_TRADE";
}

void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name="M173_"+tag+"_"+IntegerToString((int)t);
   if(ObjectFind(0,name)>=0) ObjectDelete(0,name);
   ObjectCreate(0,name,OBJ_ARROW,0,t,price);
   ObjectSetInteger(0,name,OBJPROP_ARROWCODE,dir>0?233:234);
   ObjectSetInteger(0,name,OBJPROP_COLOR,dir>0?clrLime:clrRed);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
}
//+------------------------------------------------------------------+
