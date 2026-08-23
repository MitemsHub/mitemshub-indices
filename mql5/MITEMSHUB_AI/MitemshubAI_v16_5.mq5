//+------------------------------------------------------------------+
//|                                         MitemshubAI_v16_5.mq5    |
//|                     MITEMSHUB AI MARKET ENGINE v16.5              |
//|   Multi-Symbol • Session Filter • Regime + Pullback + Trailing    |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "16.50"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Symbols (comma separated) ==="
input string InpSymbols          = "Volatility 100 Index,Volatility 75 Index";

input group "=== Session Filter (UTC) ==="
input bool   InpUseSessionFilter = false;     // Enable session filter
input int    InpSessionStartHour = 0;         // Start hour (0-23 UTC)
input int    InpSessionEndHour   = 24;        // End hour (0-24 UTC, 24 = midnight)

input group "=== Regime (M15) ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;

input group "=== Pullback Entry (M5) ==="
input double InpPullbackMin      = 0.25;
input double InpPullbackMax      = 1.8;
input int    InpRsiPeriod        = 14;
input double InpRsiBuyMax        = 58.0;
input double InpRsiSellMin       = 42.0;

input group "=== ATR Volatility Filter ==="
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 200;
input double InpAtrLowPct        = 12.0;
input double InpAtrHighPct       = 88.0;
input double InpMinAtrPoints     = 0.0;

input group "=== Compression Breakout ==="
input int    InpCompressBars     = 18;
input double InpCompressATRMult  = 0.65;
input double InpBreakoutMin      = 0.12;

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.004;     // 0.4% per trade (shared)
input double InpAtrStopMult      = 1.6;       // Optimized for Vol 100
input double InpAtrTargetMult    = 2.8;
input int    InpHoldBars         = 14;
input double InpMaxDailyLossPct  = 0.025;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 4;
input bool   InpUseTrailing      = true;
input double InpTrailStartATR    = 0.6;       // Optimized: faster profit lock
input double InpTrailDistATR     = 0.7;       // Optimized: tighter trail
input bool   InpUseBreakeven     = true;
input double InpBETriggerATR     = 1.0;

input group "=== Filters & Execution ==="
input int    InpMaxSpreadPoints  = 80;
input long   InpMagic            = 7788127;
input int    InpMaxSlippagePts   = 40;
input int    InpWarmupBars       = 250;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;

//+------------------------------------------------------------------+
//| STRUCTURES                                                         |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

struct SymbolState
{
   string   symbol;
   int      hEMA_Fast_M15, hEMA_Mid_M15, hEMA_Slow_M15;
   int      hEMA_Fast_M5, hRSI_M5, hATR_M5;
   ulong    ticket;
   int      dir;
   double   entry, sl, tp, orig_risk;
   datetime entry_time;
   int      bars_held;
   ENUM_REGIME regime;
   double   atr_hist[300];
   int      atr_hist_count;
   bool     valid;
};

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
SymbolState g_states[];
int         g_symbol_count = 0;

double      g_equity, g_peak_equity, g_daily_pnl;
datetime    g_day_start = 0;
int         g_cooldown = 0, g_consec_loss = 0;
bool        g_paused = false;

// Performance
int         g_trades = 0, g_wins = 0, g_losses = 0;
int         g_target_exits = 0, g_time_exits = 0, g_stop_exits = 0;
double      g_total_r = 0;

string      dash_names[26];

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   g_equity      = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_equity = g_equity;
   g_daily_pnl   = 0;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.LogLevel(LOG_LEVEL_ERRORS);

   // Parse symbols
   string parts[];
   int n = StringSplit(InpSymbols, ',', parts);
   if(n <= 0)
   {
      Print("v16.5: No symbols specified");
      return INIT_FAILED;
   }

   ArrayResize(g_states, n);
   g_symbol_count = 0;

   for(int i = 0; i < n; i++)
   {
      string sym = parts[i];
      StringTrimLeft(sym);
      StringTrimRight(sym);
      if(StringLen(sym) < 3) continue;

      if(!SymbolSelect(sym, true))
      {
         PrintFormat("v16.5: Cannot select symbol %s", sym);
         continue;
      }

      SymbolState s;
      s.symbol = sym;
      s.ticket = 0;
      s.dir = 0;
      s.entry = s.sl = s.tp = s.orig_risk = 0;
      s.entry_time = 0;
      s.bars_held = 0;
      s.regime = REGIME_NO_TRADE;
      s.atr_hist_count = 0;
      ArrayInitialize(s.atr_hist, 0.0);
      s.valid = false;

      // Create handles
      s.hEMA_Fast_M15 = iMA(sym, PERIOD_M15, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
      s.hEMA_Mid_M15  = iMA(sym, PERIOD_M15, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
      s.hEMA_Slow_M15 = iMA(sym, PERIOD_M15, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
      s.hEMA_Fast_M5  = iMA(sym, PERIOD_M5,  InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
      s.hRSI_M5       = iRSI(sym, PERIOD_M5,  InpRsiPeriod, PRICE_CLOSE);
      s.hATR_M5       = iATR(sym, PERIOD_M5,  InpAtrPeriod);

      if(s.hEMA_Fast_M15 == INVALID_HANDLE || s.hEMA_Mid_M15 == INVALID_HANDLE ||
         s.hEMA_Slow_M15 == INVALID_HANDLE || s.hEMA_Fast_M5 == INVALID_HANDLE ||
         s.hRSI_M5 == INVALID_HANDLE || s.hATR_M5 == INVALID_HANDLE)
      {
         PrintFormat("v16.5: Handle failed for %s", sym);
         continue;
      }

      s.valid = true;
      g_states[g_symbol_count++] = s;
      PrintFormat("v16.5: Loaded symbol %s", sym);
   }

   if(g_symbol_count == 0)
   {
      Print("v16.5: No valid symbols loaded");
      return INIT_FAILED;
   }

   // Recover existing positions
   RecoverAllPositions();

   if(InpDrawDashboard) CreateDashboard();

   PrintFormat("MITEMSHUB AI v16.5 started | Symbols=%d | Risk=%.2f%% | Magic=%d",
               g_symbol_count, InpRiskPerTrade*100, InpMagic);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   for(int i = 0; i < g_symbol_count; i++)
   {
      if(!g_states[i].valid) continue;
      IndicatorRelease(g_states[i].hEMA_Fast_M15);
      IndicatorRelease(g_states[i].hEMA_Mid_M15);
      IndicatorRelease(g_states[i].hEMA_Slow_M15);
      IndicatorRelease(g_states[i].hEMA_Fast_M5);
      IndicatorRelease(g_states[i].hRSI_M5);
      IndicatorRelease(g_states[i].hATR_M5);
   }

   for(int i = 0; i < 26; i++) ObjectDelete(0, dash_names[i]);

   double wr = (g_trades > 0) ? (double)g_wins / g_trades * 100.0 : 0.0;
   double dd = (g_peak_equity > 0) ? (g_peak_equity - g_equity) / g_peak_equity * 100.0 : 0.0;

   Print("========================================");
   Print("MITEMSHUB AI v16.5 — SESSION SUMMARY");
   PrintFormat("Symbols traded: %d", g_symbol_count);
   PrintFormat("Trades: %d | Wins: %d | Losses: %d | WR: %.1f%%", g_trades, g_wins, g_losses, wr);
   PrintFormat("Total R: %+.3f", g_total_r);
   PrintFormat("Exits → Target: %d | Time: %d | Stop: %d", g_target_exits, g_time_exits, g_stop_exits);
   PrintFormat("Equity: $%.2f | Peak: $%.2f | MaxDD: %.2f%%", g_equity, g_peak_equity, dd);
   Print("========================================");
}

//+------------------------------------------------------------------+
//| OnTick                                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   static datetime last_bar = 0;
   datetime cur_bar = iTime(_Symbol, PERIOD_M5, 0);   // use host chart bar
   if(cur_bar == last_bar)
   {
      if(InpDrawDashboard) UpdateDashboard();
      return;
   }
   last_bar = cur_bar;

   g_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_equity > g_peak_equity) g_peak_equity = g_equity;

   datetime ds = TimeCurrent() - (TimeCurrent() % 86400);
   if(ds != g_day_start)
   {
      g_day_start = ds;
      g_daily_pnl = 0;
   }

   if(g_cooldown > 0) g_cooldown--;

   bool in_session = IsInSession();

   // Process every symbol
   for(int i = 0; i < g_symbol_count; i++)
   {
      if(!g_states[i].valid) continue;

      // Manage open position
      if(g_states[i].ticket > 0)
      {
         if(PositionSelectByTicket(g_states[i].ticket))
            ManagePosition(i);
         else
            g_states[i].ticket = 0;
      }

      // Entry
      if(g_states[i].ticket == 0 && !g_paused && in_session &&
         Bars(g_states[i].symbol, PERIOD_M5) >= InpWarmupBars && g_cooldown == 0)
      {
         if(IsSpreadOK(g_states[i].symbol) && IsMinAtrOK(i))
         {
            string sig_type = "";
            int direction = GenerateSignal(i, sig_type);
            if(direction != 0)
               OpenTrade(i, direction, sig_type);
         }
      }
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| SESSION & FILTERS                                                  |
//+------------------------------------------------------------------+
bool IsInSession()
{
   if(!InpUseSessionFilter) return true;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int hour = dt.hour;

   if(InpSessionStartHour < InpSessionEndHour)
      return (hour >= InpSessionStartHour && hour < InpSessionEndHour);
   else
      return (hour >= InpSessionStartHour || hour < InpSessionEndHour); // overnight
}

bool IsSpreadOK(string sym)
{
   long spread = SymbolInfoInteger(sym, SYMBOL_SPREAD);
   return (spread <= InpMaxSpreadPoints);
}

bool IsMinAtrOK(int idx)
{
   if(InpMinAtrPoints <= 0) return true;
   double atr[1];
   if(CopyBuffer(g_states[idx].hATR_M5, 0, 1, 1, atr) < 1) return false;
   double point = SymbolInfoDouble(g_states[idx].symbol, SYMBOL_POINT);
   if(point <= 0) return false;
   return ((atr[0] / point) >= InpMinAtrPoints);
}

//+------------------------------------------------------------------+
//| RECOVER POSITIONS                                                  |
//+------------------------------------------------------------------+
void RecoverAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      string sym = PositionGetString(POSITION_SYMBOL);

      for(int s = 0; s < g_symbol_count; s++)
      {
         if(g_states[s].symbol == sym && g_states[s].ticket == 0)
         {
            g_states[s].ticket     = ticket;
            g_states[s].dir        = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
            g_states[s].entry      = PositionGetDouble(POSITION_PRICE_OPEN);
            g_states[s].sl         = PositionGetDouble(POSITION_SL);
            g_states[s].tp         = PositionGetDouble(POSITION_TP);
            g_states[s].orig_risk  = MathAbs(g_states[s].entry - g_states[s].sl);
            g_states[s].entry_time = (datetime)PositionGetInteger(POSITION_TIME);
            g_states[s].bars_held  = 0;
            PrintFormat("v16.5: Recovered %s ticket=%d", sym, ticket);
            break;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| REGIME                                                             |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime(int idx)
{
   SymbolState &st = g_states[idx];
   double emaF[1], emaM[1], emaS[1], atr[1];

   if(CopyBuffer(st.hEMA_Fast_M15, 0, 1, 1, emaF) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(st.hEMA_Mid_M15,  0, 1, 1, emaM) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(st.hEMA_Slow_M15, 0, 1, 1, emaS) < 1) return REGIME_NO_TRADE;
   if(CopyBuffer(st.hATR_M5,       0, 1, 1, atr)  < 1) return REGIME_NO_TRADE;

   // ATR history
   if(st.atr_hist_count < 300)
      st.atr_hist[st.atr_hist_count++] = atr[0];
   else
   {
      for(int i = 0; i < 299; i++) st.atr_hist[i] = st.atr_hist[i+1];
      st.atr_hist[299] = atr[0];
   }

   double pct = CalcATRPercentile(idx, atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(st.symbol, PERIOD_M15, 1);

   if(emaF[0] > emaM[0] && emaM[0] > emaS[0] && price > emaF[0]) return REGIME_BULLISH;
   if(emaF[0] < emaM[0] && emaM[0] < emaS[0] && price < emaF[0]) return REGIME_BEARISH;

   return REGIME_RANGING;
}

double CalcATRPercentile(int idx, double current)
{
   SymbolState &st = g_states[idx];
   if(st.atr_hist_count < 50) return 50.0;
   int below = 0;
   int look = MathMin(InpAtrLookback, st.atr_hist_count);
   for(int i = st.atr_hist_count - look; i < st.atr_hist_count; i++)
      if(current > st.atr_hist[i]) below++;
   return (double)below / look * 100.0;
}

//+------------------------------------------------------------------+
//| SIGNAL                                                             |
//+------------------------------------------------------------------+
int GenerateSignal(int idx, string &sig_type)
{
   SymbolState &st = g_states[idx];
   st.regime = ClassifyRegime(idx);
   if(st.regime == REGIME_NO_TRADE || st.regime == REGIME_HIGH_VOL) return 0;

   double ema20[1], rsi[1], atr[1];
   if(CopyBuffer(st.hEMA_Fast_M5, 0, 1, 1, ema20) < 1) return 0;
   if(CopyBuffer(st.hRSI_M5,      0, 1, 1, rsi)   < 1) return 0;
   if(CopyBuffer(st.hATR_M5,      0, 1, 1, atr)   < 1) return 0;

   double price = iClose(st.symbol, PERIOD_M5, 1);
   double prev  = iClose(st.symbol, PERIOD_M5, 2);
   double body  = price - prev;

   // Pullback
   if(st.regime == REGIME_BULLISH || st.regime == REGIME_BEARISH)
   {
      int dir = (st.regime == REGIME_BULLISH) ? 1 : -1;
      double pb = MathAbs(price - ema20[0]);

      if(pb < InpPullbackMin * atr[0] || pb > InpPullbackMax * atr[0]) return 0;
      if(dir > 0 && price > ema20[0] + 0.6*atr[0]) return 0;
      if(dir < 0 && price < ema20[0] - 0.6*atr[0]) return 0;
      if(dir > 0 && rsi[0] > InpRsiBuyMax) return 0;
      if(dir < 0 && rsi[0] < InpRsiSellMin) return 0;
      if(dir > 0 && body <= 0) return 0;
      if(dir < 0 && body >= 0) return 0;
      if(MathAbs(body) > atr[0] * 0.7) return 0;

      sig_type = (dir > 0) ? "PULLBACK_LONG" : "PULLBACK_SHORT";
      return dir;
   }

   // Compression Breakout
   if(st.regime == REGIME_RANGING)
   {
      double atr_now = atr[0];
      double sum = 0; int cnt = 0;
      for(int i = 1; i <= 100 && i < Bars(st.symbol, PERIOD_M5); i++)
      {
         double a[1];
         if(CopyBuffer(st.hATR_M5, 0, i, 1, a) == 1) { sum += a[0]; cnt++; }
      }
      if(cnt < 20) return 0;
      if(atr_now > (sum/cnt) * InpCompressATRMult) return 0;

      double rh = iHigh(st.symbol, PERIOD_M5, 1);
      double rl = iLow(st.symbol, PERIOD_M5, 1);
      for(int i = 2; i <= InpCompressBars; i++)
      {
         rh = MathMax(rh, iHigh(st.symbol, PERIOD_M5, i));
         rl = MathMin(rl, iLow(st.symbol, PERIOD_M5, i));
      }
      if((rh - rl) < atr_now * 0.4) return 0;

      double close = iClose(st.symbol, PERIOD_M5, 1);
      int dir = 0;
      if(close > rh + InpBreakoutMin * atr_now) dir = 1;
      else if(close < rl - InpBreakoutMin * atr_now) dir = -1;
      if(dir == 0) return 0;

      double candle = iHigh(st.symbol, PERIOD_M5, 1) - iLow(st.symbol, PERIOD_M5, 1);
      if(candle > atr_now * 2.2) return 0;
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
void OpenTrade(int idx, int direction, string sig_type)
{
   SymbolState &st = g_states[idx];
   string sym = st.symbol;

   double atr[1];
   if(CopyBuffer(st.hATR_M5, 0, 1, 1, atr) < 1) return;

   double entry = (direction > 0) ? SymbolInfoDouble(sym, SYMBOL_ASK)
                                  : SymbolInfoDouble(sym, SYMBOL_BID);

   double stop_dist = InpAtrStopMult * atr[0];
   double tp_dist   = InpAtrTargetMult * atr[0];

   double max_stop = entry * 0.025;
   if(stop_dist > max_stop) stop_dist = max_stop;
   if(stop_dist < atr[0] * 0.5) stop_dist = atr[0] * 0.5;

   double sl = (direction > 0) ? entry - stop_dist : entry + stop_dist;
   double tp = (direction > 0) ? entry + tp_dist   : entry - tp_dist;

   // Volume
   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPerTrade;
   double tick_val   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tick_val <= 0 || tick_size <= 0) return;

   double loss_1lot = (stop_dist / tick_size) * tick_val;
   if(loss_1lot <= 0) return;

   double vol = risk_money / loss_1lot;
   vol = NormalizeVolume(sym, vol);
   if(vol <= 0) return;

   trade.SetTypeFillingBySymbol(sym);

   bool ok = false;
   if(InpLiveExecution)
   {
      if(direction > 0)
         ok = trade.Buy(vol, sym, 0, NormalizeDouble(sl, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                        NormalizeDouble(tp, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)), "MITEM_v16.5");
      else
         ok = trade.Sell(vol, sym, 0, NormalizeDouble(sl, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
                         NormalizeDouble(tp, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)), "MITEM_v16.5");

      if(ok)
      {
         st.ticket = trade.ResultOrder();
         // Confirm
         if(!PositionSelectByTicket(st.ticket))
         {
            for(int p = PositionsTotal()-1; p >= 0; p--)
            {
               ulong t = PositionGetTicket(p);
               if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic &&
                  PositionGetString(POSITION_SYMBOL) == sym)
               {
                  st.ticket = t;
                  break;
               }
            }
         }
      }
      else
      {
         PrintFormat("v16.5 Order fail %s: %d %s", sym, trade.ResultRetcode(), trade.ResultComment());
         g_cooldown = InpCoolDownBars;
         return;
      }
   }
   else
   {
      st.ticket = (ulong)TimeCurrent() + idx;
      ok = true;
   }

   if(ok && st.ticket > 0)
   {
      st.dir        = direction;
      st.entry      = entry;
      st.sl         = sl;
      st.tp         = tp;
      st.orig_risk  = stop_dist;
      st.entry_time = TimeCurrent();
      st.bars_held  = 0;

      if(InpDrawSignals) DrawArrow(sym, direction, TimeCurrent(), entry, sig_type);

      PrintFormat("[v16.5] %s %s %s @%.5f SL=%.5f TP=%.5f Vol=%.2f Regime=%s",
                  sym, sig_type, direction>0?"BUY":"SELL", entry, sl, tp, vol, RegimeToStr(st.regime));
   }
}

double NormalizeVolume(string sym, double vol)
{
   double minv = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxv = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(step <= 0) step = 0.01;

   vol = MathFloor(vol / step) * step;
   if(vol < minv) vol = minv;
   if(vol > maxv) vol = maxv;
   return NormalizeDouble(vol, 2);
}

//+------------------------------------------------------------------+
//| MANAGE POSITION                                                    |
//+------------------------------------------------------------------+
void ManagePosition(int idx)
{
   SymbolState &st = g_states[idx];
   if(!PositionSelectByTicket(st.ticket)) { st.ticket = 0; return; }

   st.bars_held++;

   double atr[1];
   if(CopyBuffer(st.hATR_M5, 0, 0, 1, atr) < 1) return;

   double bid = SymbolInfoDouble(st.symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(st.symbol, SYMBOL_ASK);
   int digits = (int)SymbolInfoInteger(st.symbol, SYMBOL_DIGITS);

   // Time exit
   if(st.bars_held >= InpHoldBars)
   {
      ClosePosition(idx, "TIME");
      return;
   }

   // SL / TP safety
   if(st.dir > 0)
   {
      if(bid <= st.sl) { ClosePosition(idx, "STOP"); return; }
      if(bid >= st.tp) { ClosePosition(idx, "TARGET"); return; }
   }
   else
   {
      if(ask >= st.sl) { ClosePosition(idx, "STOP"); return; }
      if(ask <= st.tp) { ClosePosition(idx, "TARGET"); return; }
   }

   // Breakeven
   if(InpUseBreakeven)
   {
      double trigger = InpBETriggerATR * atr[0];
      if(st.dir > 0 && bid >= st.entry + trigger && st.sl < st.entry)
      {
         double new_sl = NormalizeDouble(st.entry + 2 * SymbolInfoDouble(st.symbol, SYMBOL_POINT), digits);
         if(trade.PositionModify(st.ticket, new_sl, st.tp)) st.sl = new_sl;
      }
      if(st.dir < 0 && ask <= st.entry - trigger && st.sl > st.entry)
      {
         double new_sl = NormalizeDouble(st.entry - 2 * SymbolInfoDouble(st.symbol, SYMBOL_POINT), digits);
         if(trade.PositionModify(st.ticket, new_sl, st.tp)) st.sl = new_sl;
      }
   }

   // Trailing
   if(InpUseTrailing)
   {
      double start = InpTrailStartATR * atr[0];
      double dist  = InpTrailDistATR  * atr[0];

      if(st.dir > 0 && bid >= st.entry + start)
      {
         double new_sl = NormalizeDouble(bid - dist, digits);
         if(new_sl > st.sl && new_sl > st.entry)
            if(trade.PositionModify(st.ticket, new_sl, st.tp)) st.sl = new_sl;
      }
      if(st.dir < 0 && ask <= st.entry - start)
      {
         double new_sl = NormalizeDouble(ask + dist, digits);
         if(new_sl < st.sl && new_sl > st.entry)
            if(trade.PositionModify(st.ticket, new_sl, st.tp)) st.sl = new_sl;
      }
   }
}

void ClosePosition(int idx, string reason)
{
   SymbolState &st = g_states[idx];
   if(st.ticket == 0) return;

   double exit_price = (st.dir > 0) ? SymbolInfoDouble(st.symbol, SYMBOL_BID)
                                    : SymbolInfoDouble(st.symbol, SYMBOL_ASK);

   double r_mult = 0;
   if(st.orig_risk > 0)
      r_mult = (st.dir > 0) ? (exit_price - st.entry) / st.orig_risk
                            : (st.entry - exit_price) / st.orig_risk;

   if(InpLiveExecution)
      trade.PositionClose(st.ticket);

   g_trades++;
   g_total_r += r_mult;
   if(r_mult > 0) g_wins++; else g_losses++;

   if(reason == "TARGET") g_target_exits++;
   else if(reason == "TIME") g_time_exits++;
   else if(reason == "STOP") g_stop_exits++;

   double pnl_approx = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPerTrade * r_mult;
   g_daily_pnl += pnl_approx;

   if(r_mult < 0)
   {
      g_consec_loss++;
      g_cooldown = InpCoolDownBars;
   }
   else g_consec_loss = 0;

   if(g_consec_loss >= InpMaxConsecLoss) g_paused = true;
   if(g_daily_pnl < -AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxDailyLossPct) g_paused = true;
   if((g_peak_equity - g_equity) > g_peak_equity * 0.12) g_paused = true;

   PrintFormat("[v16.5] CLOSE %s %s R=%+.3f", st.symbol, reason, r_mult);

   st.ticket = 0;
   st.dir = 0;
   st.bars_held = 0;
}

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i = 0; i < 26; i++)
   {
      dash_names[i] = "MITEM165_" + IntegerToString(i);
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
   double dd = (g_peak_equity > 0) ? (g_peak_equity - g_equity) / g_peak_equity * 100.0 : 0;

   string L[26];
   L[0]  = "=== MITEMSHUB AI v16.5 Multi ===";
   L[1]  = "Equity: $" + DoubleToString(g_equity, 2);
   L[2]  = "Symbols: " + IntegerToString(g_symbol_count);
   L[3]  = "Session: " + (IsInSession() ? "OPEN" : "CLOSED");
   L[4]  = "Trades: " + IntegerToString(g_trades) + "  WR: " + DoubleToString(wr, 1) + "%";
   L[5]  = "Total R: " + DoubleToString(g_total_r, 2);
   L[6]  = "Daily PnL: $" + DoubleToString(g_daily_pnl, 2);
   L[7]  = "Consec Loss: " + IntegerToString(g_consec_loss);
   L[8]  = "Cooldown: " + IntegerToString(g_cooldown);
   L[9]  = "Status: " + (g_paused ? "PAUSED" : "ACTIVE");
   L[10] = InpLiveExecution ? "MODE: LIVE" : "MODE: PAPER";
   L[11] = "Risk/Trade: " + DoubleToString(InpRiskPerTrade*100, 2) + "%";
   L[12] = "SL/TP: " + DoubleToString(InpAtrStopMult,1) + "/" + DoubleToString(InpAtrTargetMult,1);
   L[13] = "Trail: " + (InpUseTrailing ? "ON" : "OFF");
   L[14] = "MaxDD: " + DoubleToString(dd, 2) + "%";
   L[15] = "T/T/S: " + IntegerToString(g_target_exits) + "/" + IntegerToString(g_time_exits) + "/" + IntegerToString(g_stop_exits);

   // Per-symbol status (first few)
   int line = 16;
   for(int i = 0; i < g_symbol_count && line < 25; i++)
   {
      string shortname = g_states[i].symbol;
      if(StringLen(shortname) > 18) shortname = StringSubstr(shortname, 0, 18);
      string pos = (g_states[i].ticket > 0) ? "OPEN" : "flat";
      L[line] = shortname + ": " + RegimeToStr(g_states[i].regime) + " " + pos;
      line++;
   }
   while(line < 26) { L[line] = ""; line++; }

   for(int i = 0; i < 26; i++)
   {
      ObjectSetString(0, dash_names[i], OBJPROP_TEXT, L[i]);
      color c = clrWhite;
      if(i == 0) c = clrGold;
      if(i == 3) c = IsInSession() ? clrLime : clrGray;
      if(i == 6) c = (g_daily_pnl >= 0) ? clrLime : clrRed;
      if(i == 9) c = g_paused ? clrRed : clrLime;
      ObjectSetInteger(0, dash_names[i], OBJPROP_COLOR, c);
   }
   ChartRedraw();
}

string RegimeToStr(ENUM_REGIME r)
{
   switch(r)
   {
      case REGIME_BULLISH:  return "BULL";
      case REGIME_BEARISH:  return "BEAR";
      case REGIME_RANGING:  return "RANGE";
      case REGIME_HIGH_VOL: return "HVOL";
      default:              return "NONE";
   }
}

void DrawArrow(string sym, int dir, datetime t, double price, string tag)
{
   // Only draw if the host chart is this symbol
   if(sym != _Symbol) return;
   string name = "M165_" + tag + "_" + IntegerToString((int)t);
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, dir > 0 ? 233 : 234);
   ObjectSetInteger(0, name, OBJPROP_COLOR, dir > 0 ? clrLime : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 2);
}
//+------------------------------------------------------------------+
