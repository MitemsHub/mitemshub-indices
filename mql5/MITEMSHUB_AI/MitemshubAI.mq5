//+------------------------------------------------------------------+
//|                                         MitemshubAI_v17_1.mq5    |
//|                     MITEMSHUB AI MARKET ENGINE v17.1              |
//|   H1 Entry + H4 Regime • Trend-Only • V10 Optimized              |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "17.10"
#property strict

#include <Trade/Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Regime (H4 timeframes) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input bool   InpTrendOnly        = false;     // v17.0: trade in all regimes (pullback + momentum)

input group "=== Pullback Entry (H1) ==="
input double InpPullbackMin      = 0.10;      // min pullback distance (ATR)
input double InpPullbackMax      = 2.5;       // max pullback (ATR)
input int    InpRsiPeriod        = 14;
input double InpRsiBuyMax        = 68.0;      // v17.0: H1 RSI band
input double InpRsiSellMin       = 32.0;

input group "=== Momentum Entry ==="
input bool   InpUseMomentum      = true;      // v17.0: momentum in all regimes
input int    InpMomLookback      = 12;        // bars to check for session high/low
input double InpMomMinMove       = 0.8;       // min move in ATR to trigger
input double InpMomRsiThresh     = 38.0;      // RSI threshold for momentum buy
input double InpMomRsiThreshSell = 62.0;      // RSI threshold for momentum sell
input double InpSlopeThresh      = 0.3;       // v17.1: EMA slope for ranging direction (validated)

input group "=== ATR Volatility Filter ==="
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 200;
input double InpAtrLowPct        = 2.0;
input double InpAtrHighPct       = 92.0;

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.004;     // 0.4% per trade
input double InpAtrStopMult      = 1.5;       // v17.0: SL = 1.5 x ATR
input double InpAtrTargetMult    = 2.0;       // v17.0: TP = 2.0 x SL (2.0R target)
input int    InpHoldBars         = 24;        // v17.0: hold up to 24 hours (1 day)
input double InpMaxDailyLossPct  = 0.025;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 2;         // v17.0: 2 hours cooldown
input bool   InpUseTrailing      = true;
input double InpTrailStartATR    = 1.0;       // v17.0: trail starts after 1.0 x ATR profit
input double InpTrailDistATR     = 1.2;       // v17.0: trail distance 1.2 x ATR
input bool   InpUseBreakeven     = true;
input double InpBETriggerATR     = 2.0;       // v17.0: BE after 2.0 x ATR profit

input group "=== Execution ==="
input long   InpMagic            = 7788127;
input int    InpMaxSlippagePts   = 40;
input int    InpWarmupBars       = 250;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;
input bool   InpDebugLog         = true;

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

ENUM_TIMEFRAMES g_tf_entry;
ENUM_TIMEFRAMES g_tf_regime;

int      hEMA_Fast_Regime, hEMA_Mid_Regime, hEMA_Slow_Regime;
int      hEMA_Fast_Entry, hEMA_Mid_Entry, hEMA_Slow_Entry, hRSI_Entry, hATR_Entry;
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
double   g_entry = 0, g_sl = 0, g_tp = 0, g_orig_risk = 0, g_stake = 0;
datetime g_entry_time = 0;
int      g_bars_held = 0;

double   atr_hist[];
int      atr_hist_count = 0;

string   dash_names[24];

//+------------------------------------------------------------------+
//| Auto-detect timeframes                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES entry_tf)
{
   // H1 -> H4, H4 -> D1
   switch(entry_tf)
   {
      case PERIOD_M1:  return PERIOD_M5;
      case PERIOD_M5:  return PERIOD_M15;
      case PERIOD_M15: return PERIOD_H1;
      case PERIOD_H1:  return PERIOD_H4;
      case PERIOD_H4:  return PERIOD_D1;
      default:         return (ENUM_TIMEFRAMES)((int)entry_tf * 3);
   }
}

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   g_tf_entry = (ENUM_TIMEFRAMES)Period();
   g_tf_regime = GetRegimeTF(g_tf_entry);

   // Regime indicators (on H4 or higher)
   hEMA_Fast_Regime = iMA(_Symbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_Regime  = iMA(_Symbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_Regime = iMA(_Symbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);

   // Entry indicators (on H1)
   hEMA_Fast_Entry = iMA(_Symbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_Entry  = iMA(_Symbol, g_tf_entry, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_Entry = iMA(_Symbol, g_tf_entry, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_Entry      = iRSI(_Symbol, g_tf_entry, InpRsiPeriod, PRICE_CLOSE);
   hATR_Entry      = iATR(_Symbol, g_tf_entry, InpAtrPeriod);

   if(hEMA_Fast_Regime == INVALID_HANDLE || hEMA_Mid_Regime == INVALID_HANDLE ||
      hEMA_Slow_Regime == INVALID_HANDLE || hEMA_Fast_Entry == INVALID_HANDLE ||
      hEMA_Mid_Entry == INVALID_HANDLE || hEMA_Slow_Entry == INVALID_HANDLE ||
      hRSI_Entry == INVALID_HANDLE || hATR_Entry == INVALID_HANDLE)
   {
      Print("v17.0: Handle creation failed");
      return INIT_FAILED;
   }

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;
   g_daily_pnl = 0;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   RecoverPosition();

   PrintFormat("[MITEM v17.0] Started | Entry=%s Regime=%s | Risk=%.2f%% | Mode=%s",
               EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpRiskPerTrade*100, InpLiveExecution?"LIVE":"PAPER");
   PrintFormat("[MITEM v17.0] Pullback=%.2f-%.2f ATR | TP=%.1fxSL | SL=%.1fxATR | Hold=%d bars",
               InpPullbackMin, InpPullbackMax, InpAtrTargetMult, InpAtrStopMult, InpHoldBars);
   PrintFormat("[MITEM v17.0] Trail: start=%.1f dist=%.1f | BE: trigger=%.1f | TrendOnly=%s",
               InpTrailStartATR, InpTrailDistATR, InpBETriggerATR, InpTrendOnly?"ON":"OFF");

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
   IndicatorRelease(hEMA_Mid_Entry);
   IndicatorRelease(hEMA_Slow_Entry);
   IndicatorRelease(hRSI_Entry);
   IndicatorRelease(hATR_Entry);

   for(int i = 0; i < 24; i++) ObjectDelete(0, dash_names[i]);

   double wr = (g_trades > 0) ? (double)g_wins / g_trades * 100.0 : 0.0;
   double dd = (g_peak_eq > 0) ? (g_peak_eq - g_eq) / g_peak_eq * 100.0 : 0.0;

   Print("========================================");
   Print("MITEMSHUB AI v17.0 — SESSION SUMMARY");
   PrintFormat("Symbol: %s | Entry: %s | Regime: %s", _Symbol, EnumToString(g_tf_entry), EnumToString(g_tf_regime));
   PrintFormat("Trades: %d | Wins: %d | Losses: %d | WR: %.1f%%", g_trades, g_wins, g_losses, wr);
   PrintFormat("Total R: %+.3f", g_total_r);
   PrintFormat("Exits -> Target: %d | Time: %d | Stop: %d", g_target_exits, g_time_exits, g_stop_exits);
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

   // Entry
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
//| RECOVER POSITION                                                   |
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
      g_entry_time = (datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held = 0;
      PrintFormat("[v17.0] Recovered position ticket=%d", ticket);
      break;
   }
}

//+------------------------------------------------------------------+
//| REGIME CLASSIFICATION                                              |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1], emaM[1], emaS[1];
   if(CopyBuffer(hEMA_Fast_Regime, 0, 1, 1, emaF) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_Regime,  0, 1, 1, emaM) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_Regime, 0, 1, 1, emaS) < 1) return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0]) return REGIME_BULLISH;
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0]) return REGIME_BEARISH;

   return REGIME_RANGING;
}

//+------------------------------------------------------------------+
//| SIGNAL GENERATION                                                  |
//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime == REGIME_NO_TRADE || g_regime == REGIME_HIGH_VOL) return 0;

   // v17.0: Skip RANGING if trend-only mode
   if(InpTrendOnly && g_regime == REGIME_RANGING)
   {
      if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s RANGING regime", _Symbol);
      return 0;
   }

   double emaF[1], emaM[1], emaS[1], rsi[1], atr[1];
   if(CopyBuffer(hEMA_Fast_Entry, 0, 1, 1, emaF) < 1) return 0;
   if(CopyBuffer(hEMA_Mid_Entry,  0, 1, 1, emaM) < 1) return 0;
   if(CopyBuffer(hEMA_Slow_Entry, 0, 1, 1, emaS) < 1) return 0;
   if(CopyBuffer(hRSI_Entry,      0, 1, 1, rsi)  < 1) return 0;
   if(CopyBuffer(hATR_Entry,      0, 1, 1, atr)  < 1) return 0;

   double price = iClose(_Symbol, g_tf_entry, 1);

   // ─── MODE 1: PULLBACK (primary signal) ───
   if(g_regime == REGIME_BULLISH || g_regime == REGIME_BEARISH)
   {
      int dir = (g_regime == REGIME_BULLISH) ? 1 : -1;
      double pb = MathAbs(price - emaF[0]);

      if(pb < InpPullbackMin * atr[0])
      {
         if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s Pullback too close: %.2f < %.2f ATR", _Symbol, pb/atr[0], InpPullbackMin);
         return 0;
      }
      if(pb > InpPullbackMax * atr[0])
      {
         if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s Pullback too deep: %.2f > %.2f ATR", _Symbol, pb/atr[0], InpPullbackMax);
         return 0;
      }

      // v17.0: Wider RSI band for H1
      if(dir > 0 && rsi[0] > InpRsiBuyMax)
      {
         if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s RSI too high for BUY: %.1f > %.1f", _Symbol, rsi[0], InpRsiBuyMax);
         return 0;
      }
      if(dir < 0 && rsi[0] < InpRsiSellMin)
      {
         if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s RSI too low for SELL: %.1f < %.1f", _Symbol, rsi[0], InpRsiSellMin);
         return 0;
      }

      // v17.0: H1 EMA alignment must confirm direction
      if(dir > 0 && !(emaF[0] > emaM[0] && emaM[0] > emaS[0]))
      {
         if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s H1 EMAs not aligned bullish", _Symbol);
         return 0;
      }
      if(dir < 0 && !(emaF[0] < emaM[0] && emaM[0] < emaS[0]))
      {
         if(InpDebugLog) PrintFormat("[v17.0 SKIP] %s H1 EMAs not aligned bearish", _Symbol);
         return 0;
      }

      sig_type = (dir > 0) ? "PULLBACK_LONG" : "PULLBACK_SHORT";
      return dir;
   }

   // ─── MODE 2: MOMENTUM (all regimes) ───
   if(InpUseMomentum)
   {
      int dir = 0;
      if(g_regime == REGIME_BULLISH) dir = 1;
      else if(g_regime == REGIME_BEARISH) dir = -1;
      else if(g_regime == REGIME_RANGING)
      {
         // EMA slope determines direction in ranging
         double emaF_now[1], emaF_prev[1];
         if(CopyBuffer(hEMA_Fast_Entry, 0, 1, 1, emaF_now) < 1) return 0;
         if(CopyBuffer(hEMA_Fast_Entry, 0, 5, 1, emaF_prev) < 1) return 0;

         if(emaF_now[0] > emaF_prev[0] + InpSlopeThresh * atr[0]) dir = 1;
         else if(emaF_now[0] < emaF_prev[0] - InpSlopeThresh * atr[0]) dir = -1;
      }
      if(dir == 0) return 0;

      double session_high = iHigh(_Symbol, g_tf_entry, 1);
      double session_low  = iLow(_Symbol, g_tf_entry, 1);
      for(int i = 2; i <= InpMomLookback && i < Bars(_Symbol, g_tf_entry); i++)
      {
         session_high = MathMax(session_high, iHigh(_Symbol, g_tf_entry, i));
         session_low  = MathMin(session_low,  iLow(_Symbol, g_tf_entry, i));
      }

      double move_up   = price - session_low;
      double move_down = session_high - price;
      double body = price - iClose(_Symbol, g_tf_entry, 2);

      if(dir > 0 && move_up > InpMomMinMove * atr[0] && rsi[0] > InpMomRsiThresh && rsi[0] < 70 && body > 0)
      {
         sig_type = "MOMENTUM_LONG";
         return 1;
      }
      if(dir < 0 && move_down > InpMomMinMove * atr[0] && rsi[0] < InpMomRsiThreshSell && rsi[0] > 30 && body < 0)
      {
         sig_type = "MOMENTUM_SHORT";
         return -1;
      }
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
   double tp_dist   = InpAtrTargetMult * stop_dist;  // v17.0: 2.0R target

   double max_stop = entry * 0.025;
   if(stop_dist > max_stop) stop_dist = max_stop;
   if(stop_dist < atr[0] * 0.3) stop_dist = atr[0] * 0.3;

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
         ok = trade.Buy(vol, _Symbol, entry, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v17.0");
      else
         ok = trade.Sell(vol, _Symbol, entry, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits), "MITEM_v17.0");
   }
   else
   {
      g_ticket = (ulong)TimeCurrent();
      ok = true;
   }

   if(!ok)
   {
      PrintFormat("[v17.0] Order FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      g_cooldown = InpCoolDownBars;
      return;
   }

   // Ticket recovery
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

   PrintFormat("[v17.0] %s %s @%.2f SL=%.2f TP=%.2f Vol=%.2f Regime=%s ATR=%.2f",
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
   if(InpUseBreakeven && atr[0] > 0)
   {
      double be_trigger = InpBETriggerATR * atr[0];
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

   bool ok = trade.PositionClose(g_ticket);
   if(!ok)
   {
      PrintFormat("[v17.0] Close FAILED: %d %s", trade.ResultRetcode(), trade.ResultComment());
      return;
   }

   Sleep(50);
   double equity_now = AccountInfoDouble(ACCOUNT_EQUITY);

   double realized_pnl = 0;
   if(HistorySelect(g_entry_time - 10, TimeCurrent() + 10))
   {
      int deals = HistoryDealsTotal();
      for(int i = deals - 1; i >= 0; i--)
      {
         ulong ticket = HistoryDealGetTicket(i);
         if(ticket == 0) continue;
         if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic) continue;
         if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
         if(HistoryDealGetInteger(ticket, DEAL_ENTRY) == DEAL_ENTRY_OUT)
         {
            realized_pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT);
            break;
         }
      }
   }

   double r_mult = (g_orig_risk > 0) ? realized_pnl / (g_orig_risk * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)) : 0;
   if(r_mult > 0) g_wins++; else g_losses++;
   g_trades++;
   g_total_r += r_mult;

   if(reason == "TARGET") g_target_exits++;
   else if(reason == "TIME") g_time_exits++;
   else if(reason == "STOP") g_stop_exits++;

   g_daily_pnl += realized_pnl;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
   }
   else g_consec_loss = 0;

   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_eq - equity_now) > g_peak_eq * 0.12) g_paused = true;

   PrintFormat("[v17.0] CLOSE %s %s R=%+.3f PnL=$%.2f", _Symbol, reason, r_mult, realized_pnl);

   g_ticket = 0;
   g_dir = 0;
   g_bars_held = 0;
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i = 0; i < 24; i++)
   {
      dash_names[i] = "MITEM170_" + IntegerToString(i);
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
   double wr = (g_trades > 0) ? 100.0 * g_wins / g_trades : 0;
   double dd = (g_peak_eq > 0) ? (g_peak_eq - g_eq) / g_peak_eq * 100.0 : 0;

   string L[24];
   L[0]  = "=== MITEMSHUB AI v17.0 ===";
   L[1]  = StringFormat("Symbol: %s | Entry: %s", _Symbol, EnumToString(g_tf_entry));
   L[2]  = StringFormat("Regime TF: %s | TrendOnly: %s", EnumToString(g_tf_regime), InpTrendOnly?"ON":"OFF");
   L[3]  = StringFormat("Equity: $%.2f | Peak: $%.2f", g_eq, g_peak_eq);
   L[4]  = StringFormat("Regime: %s", RegimeToStr(g_regime));
   L[5]  = StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f", g_trades, wr, g_total_r);
   L[6]  = StringFormat("Daily PnL: $%.2f", g_daily_pnl);
   L[7]  = StringFormat("Consec Loss: %d | Cooldown: %d", g_consec_loss, g_cooldown);
   L[8]  = StringFormat("Status: %s", g_paused ? "PAUSED" : "ACTIVE");
   L[9]  = StringFormat("Mode: %s", InpLiveExecution ? "LIVE" : "PAPER");
   L[10] = StringFormat("Risk: %.2f%% | SL: %.1fxATR | TP: %.1fxSL",
                         InpRiskPerTrade*100, InpAtrStopMult, InpAtrTargetMult);
   L[11] = StringFormat("Trail: %.1f/%.1f | BE: %.1f",
                         InpTrailStartATR, InpTrailDistATR, InpBETriggerATR);
   L[12] = StringFormat("Pullback: %.2f-%.2f ATR | Hold: %d bars",
                         InpPullbackMin, InpPullbackMax, InpHoldBars);
   L[13] = StringFormat("MaxDD: %.2f%% | T/T/S: %d/%d/%d",
                         dd, g_target_exits, g_time_exits, g_stop_exits);

   // Position info
   int line = 14;
   if(g_ticket > 0 && PositionSelectByTicket(g_ticket))
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      L[line] = StringFormat("OPEN: %s @ %.2f | SL: %.2f | TP: %.2f",
                             g_dir > 0 ? "BUY" : "SELL", g_entry, g_sl, g_tp);
      line++;
      double current = (g_dir > 0) ? bid : ask;
      double pnl_pts = (g_dir > 0) ? (current - g_entry) : (g_entry - current);
      L[line] = StringFormat("Current: %.2f | P/L: %.2f pts | Held: %d bars",
                             current, pnl_pts, g_bars_held);
      line++;
   }

   while(line < 24) { L[line] = ""; line++; }

   for(int i = 0; i < 24; i++)
   {
      ObjectSetString(0, dash_names[i], OBJPROP_TEXT, L[i]);
      color c = clrWhite;
      if(i == 0) c = clrGold;
      if(i == 4) c = (g_regime == REGIME_BULLISH) ? clrLime : (g_regime == REGIME_BEARISH) ? clrRed : clrGray;
      if(i == 6) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i == 8) c = g_paused ? clrRed : clrLime;
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
      default:              return "NONE";
   }
}

void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name = "M170_" + tag + "_" + IntegerToString((int)t);
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir > 0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir > 0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}
//+------------------------------------------------------------------+
