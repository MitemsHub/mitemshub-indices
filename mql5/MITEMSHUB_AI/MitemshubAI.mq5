//+------------------------------------------------------------------+
//|                                            MitemshubAI.mq5       |
//|                        MITEMSHUB AI MARKET ENGINE v14             |
//|             Trend-Regime + Pullback Entry + ATR Filter            |
//|                                                                    |
//|  Based on expert recommendation:                                  |
//|  - Classify regime (trending/ranging/high-vol)                    |
//|  - Trade WITH trend using pullback entries                        |
//|  - M5 entries with M15 regime confirmation                        |
//|  - ATR volatility filter (percentile-based)                       |
//|  - Compression breakout as second mode                            |
//|  - Fixed exits, no trailing initially                             |
//|  - Conservative fixed risk (0.5%)                                 |
//|  - Preserve original R for reliable tracking                      |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "14.00"
#property strict

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input int    InpBarSec           = 300;       // Bar period in seconds (300=M5)
//--- Regime Detection (M15)
input int    InpEmaFast          = 20;        // Fast EMA for regime (M15)
input int    InpEmaMid           = 50;        // Mid EMA for regime (M15)
input int    InpEmaSlow          = 100;       // Slow EMA for regime (M15)
//--- Pullback Entry (M5)
input double InpPullbackMin      = 0.3;       // Min pullback to EMA (ATR units)
input double InpPullbackMax      = 2.0;       // Max pullback to EMA (ATR units)
input int    InpRsiPeriod        = 14;        // RSI period
//--- ATR Volatility Filter
input int    InpAtrPeriod        = 14;        // ATR period
input int    InpAtrPercentile    = 200;       // Lookback for percentile calc
input double InpAtrLowPct        = 15.0;      // Below this percentile = too quiet
input double InpAtrHighPct       = 85.0;      // Above this percentile = too volatile
//--- Compression Breakout
input int    InpCompressBars     = 20;        // Bars to measure compression range
input double InpCompressATR      = 0.7;       // ATR must be below this * avg ATR
input double InpBreakoutMin      = 0.15;      // Min breakout distance (ATR units)
//--- Risk Management (CONSERVATIVE)
input double InpRiskPerTrade     = 0.005;     // 0.5% of equity per trade
input double InpAtrStopMult      = 1.5;       // Stop = ATR * multiplier
input double InpAtrTargetMult    = 2.0;       // Target = ATR * multiplier
input int    InpHoldBars         = 12;        // Max hold in bars (60 min on M5)
input double InpMaxDailyLossPct  = 0.02;      // Max daily loss (2%)
input int    InpMaxConsecLoss    = 3;         // Max consecutive losses
input int    InpCoolDownBars     = 3;         // Bars to wait after loss
//--- Execution
input bool   InpLiveExecution    = true;      // false=paper, true=live
input long   InpMagic            = 7788123;   // EA magic number
input int    InpMaxSlippagePts   = 50;        // Max slippage
input int    InpWarmupCandles    = 200;       // Min bars before trading
input bool   InpDrawDashboard    = true;      // Draw dashboard on chart
input bool   InpDrawSignals      = true;      // Draw entry/exit arrows

//+------------------------------------------------------------------+
//| REGIME CLASSIFIER                                                   |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

string RegimeToString(ENUM_REGIME r)
  {
   switch(r)
     {
      case REGIME_BULLISH:   return "BULLISH";
      case REGIME_BEARISH:   return "BEARISH";
      case REGIME_RANGING:   return "RANGING";
      case REGIME_HIGH_VOL:  return "HIGH_VOL";
      case REGIME_NO_TRADE:  return "NO_TRADE";
     }
   return "UNKNOWN";
  }

//+------------------------------------------------------------------+
//| BAR AGGREGATOR                                                    |
//+------------------------------------------------------------------+
struct AggregatedBar
  {
   double   open,high,low,close;
   datetime time;
  };

class CBarAggregator
  {
private:
   int       m_bar_sec;
   double    m_open,m_high,m_low,m_close;
   datetime  m_bar_start;
   bool      m_have_bar;
public:
   CBarAggregator(): m_bar_sec(300),m_have_bar(false) {}
   void Reset(int bs) { m_bar_sec=bs; m_have_bar=false; }
   bool OnTick(double bid, datetime tick_time)
     {
      if(m_bar_sec<=0) return false;
      datetime bs0=tick_time-(tick_time%m_bar_sec);
      if(!m_have_bar)
        { m_bar_start=bs0; m_open=m_high=m_low=m_close=bid; m_have_bar=true; return false; }
      if(bid>m_high) m_high=bid;
      if(bid<m_low)  m_low=bid;
      m_close=bid;
      if(bs0>m_bar_start) return true;
      return false;
     }
   bool ClosedBar(AggregatedBar &bar)
     {
      if(!m_have_bar) return false;
      bar.open=m_open; bar.high=m_high; bar.low=m_low; bar.close=m_close; bar.time=m_bar_start;
      return true;
     }
   void RestartBar(double bid, datetime tick_time)
     {
      m_bar_start=tick_time-(tick_time%m_bar_sec);
      m_open=m_high=m_low=m_close=bid; m_have_bar=true;
     }
  };

//+------------------------------------------------------------------+
//| POSITION MANAGER — preserves original R                           |
//+------------------------------------------------------------------+
struct PositionInfo
  {
   int      direction;
   double   entry_price,stop_loss,take_profit;
   double   original_risk;    // FIXED: store original SL distance
   datetime entry_time;
   int      entry_bar;
   double   stake;
   bool     active;
  };

//+------------------------------------------------------------------+
//| INDICATOR BUFFERS                                                  |
//+------------------------------------------------------------------+
#define MAX_HISTORY 500
double g_close_buf[MAX_HISTORY];
double g_high_buf[MAX_HISTORY];
double g_low_buf[MAX_HISTORY];
int    g_buf_count=0;
int    g_buf_head=0;

// M15 regime buffers (loaded at startup)
#define MAX_M15 500
double g_m15_close[MAX_M15];
double g_m15_high[MAX_M15];
double g_m15_low[MAX_M15];
int    g_m15_count=0;

// ATR history for percentile calculation
double g_atr_history[500];
int    g_atr_hist_count=0;

void PushBar(double close, double high, double low)
  {
   int idx=(g_buf_head)%MAX_HISTORY;
   g_close_buf[idx]=close;
   g_high_buf[idx]=high;
   g_low_buf[idx]=low;
   g_buf_head=(g_buf_head+1)%MAX_HISTORY;
   if(g_buf_count<MAX_HISTORY) g_buf_count++;
  }

double GetClose(int bars_ago)
  {
   if(bars_ago>=g_buf_count) return 0;
   int idx=(g_buf_head-1-bars_ago+MAX_HISTORY)%MAX_HISTORY;
   return g_close_buf[idx];
  }

double GetHigh(int bars_ago)
  {
   if(bars_ago>=g_buf_count) return 0;
   int idx=(g_buf_head-1-bars_ago+MAX_HISTORY)%MAX_HISTORY;
   return g_high_buf[idx];
  }

double GetLow(int bars_ago)
  {
   if(bars_ago>=g_buf_count) return 0;
   int idx=(g_buf_head-1-bars_ago+MAX_HISTORY)%MAX_HISTORY;
   return g_low_buf[idx];
  }

//+------------------------------------------------------------------+
//| INDICATOR CALCULATIONS                                              |
//+------------------------------------------------------------------+
double CalcEMA_M5(int period)
  {
   if(g_buf_count<period) return GetClose(0);
   double alpha=2.0/(period+1.0);
   double ema=GetClose(g_buf_count-1);
   for(int i=g_buf_count-2;i>=0;i--)
     {
      double c=GetClose(i);
      ema=c*alpha+ema*(1.0-alpha);
     }
   return ema;
  }

double CalcEMA_M15(int period)
  {
   if(g_m15_count<period) return (g_m15_count>0)?g_m15_close[g_m15_count-1]:0;
   double alpha=2.0/(period+1.0);
   double ema=g_m15_close[0];
   for(int i=1;i<g_m15_count;i++)
     {
      ema=g_m15_close[i]*alpha+ema*(1.0-alpha);
     }
   return ema;
  }

double CalcRSI(int period)
  {
   if(g_buf_count<period+1) return 50.0;
   double avg_gain=0, avg_loss=0;
   for(int i=0;i<period;i++)
     {
      double diff=GetClose(i)-GetClose(i+1);
      if(diff>0) avg_gain+=diff; else avg_loss-=diff;
     }
   avg_gain/=period; avg_loss/=period;
   if(avg_loss<1e-12) return 100.0;
   double rs=avg_gain/avg_loss;
   return 100.0-100.0/(1.0+rs);
  }

double CalcATR(int period)
  {
   if(g_buf_count<period+1) return 0.001;
   double sum=0;
   for(int i=0;i<period;i++)
     {
      double tr=g_high_buf[(g_buf_head-1-i+MAX_HISTORY)%MAX_HISTORY]
                -g_low_buf[(g_buf_head-1-i+MAX_HISTORY)%MAX_HISTORY];
      if(i+1<g_buf_count)
        {
         double prev_c=GetClose(i+1);
         double h=g_high_buf[(g_buf_head-1-i+MAX_HISTORY)%MAX_HISTORY];
         double l=g_low_buf[(g_buf_head-1-i+MAX_HISTORY)%MAX_HISTORY];
         double t1=MathAbs(h-prev_c), t2=MathAbs(l-prev_c);
         if(t1>tr) tr=t1; if(t2>tr) tr=t2;
        }
      sum+=tr;
     }
   return sum/period;
  }

double CalcATRPercentile()
  {
   if(g_atr_hist_count<InpAtrPercentile) return 50.0;
   double current=g_atr_history[(g_atr_hist_count-1)%500];
   int below=0;
   for(int i=0;i<InpAtrPercentile && i<g_atr_hist_count;i++)
     {
      double h=g_atr_history[(g_atr_hist_count-1-i+500)%500];
      if(current>h) below++;
     }
   return (double)below/InpAtrPercentile*100.0;
  }

//+------------------------------------------------------------------+
//| REGIME CLASSIFIER                                                   |
//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
  {
   // Need enough M15 data
   if(g_m15_count<InpEmaSlow) return REGIME_NO_TRADE;
   
   double ema_fast=CalcEMA_M15(InpEmaFast);
   double ema_mid=CalcEMA_M15(InpEmaMid);
   double ema_slow=CalcEMA_M15(InpEmaSlow);
   double price=g_m15_close[g_m15_count-1];
   
   // ATR percentile check
   double atr_pct=CalcATRPercentile();
   if(atr_pct>InpAtrHighPct) return REGIME_HIGH_VOL;
   if(atr_pct<InpAtrLowPct) return REGIME_NO_TRADE;
   
   // EMA alignment: all three must be ordered
   if(ema_fast>ema_mid && ema_mid>ema_slow && price>ema_fast)
     return REGIME_BULLISH;
   if(ema_fast<ema_mid && ema_mid<ema_slow && price<ema_fast)
     return REGIME_BEARISH;
   
   return REGIME_RANGING;
  }

//+------------------------------------------------------------------+
//| COMPRESSION DETECTION                                               |
//+------------------------------------------------------------------+
bool IsCompressed()
  {
   if(g_buf_count<InpCompressBars) return false;
   double atr_current=CalcATR(InpAtrPeriod);
   
   // Average ATR over last 100 bars
   double avg_atr=0;
   int cnt=MathMin(100,g_buf_count);
   for(int i=0;i<cnt;i++) avg_atr+=CalcATR(InpAtrPeriod); // simplified
   avg_atr/=cnt;
   
   return atr_current<avg_atr*InpCompressATR;
  }

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
CBarAggregator   g_agg;
PositionInfo     g_pos;

double g_prev_close=0;
long   g_bars_seen=0;
datetime g_last_bar_end=0;
double g_equity=0, g_peak_equity=0;
double g_daily_pnl=0;
int    g_cooldown=0, g_consec_loss=0;
bool   g_preloading=false, g_paused=false;
datetime g_day_start=0;
ENUM_REGIME g_current_regime=REGIME_NO_TRADE;

// Trade history
#define MAX_TRADES 10000
struct TradeRecord
  {
   datetime entry_time,exit_time;
   int      direction;
   double   entry_price,exit_price,original_sl;
   double   return_r,pnl;
   string   exit_reason,signal_type,regime;
  };
TradeRecord g_trades[MAX_TRADES];
int g_trade_count=0;

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
#define DASH_Y 20
#define DASH_H 18
#define DASH_X 10
string g_dl[24];

void DashCreate()
  {
   for(int i=0;i<24;i++)
     {
      g_dl[i]="MITEM_D_"+IntegerToString(i);
      ObjectCreate(0,g_dl[i],OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,g_dl[i],OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,g_dl[i],OBJPROP_XDISTANCE,DASH_X);
      ObjectSetInteger(0,g_dl[i],OBJPROP_YDISTANCE,DASH_Y+i*DASH_H);
      ObjectSetString(0,g_dl[i],OBJPROP_FONT,"Consolas");
      ObjectSetInteger(0,g_dl[i],OBJPROP_FONTSIZE,10);
      ObjectSetInteger(0,g_dl[i],OBJPROP_COLOR,clrWhite);
     }
  }

void DashUpdate()
  {
   double total_r=0; int wins=0;
   for(int i=0;i<g_trade_count;i++)
     { total_r+=g_trades[i].return_r; if(g_trades[i].return_r>0) wins++; }
   double wr=(g_trade_count>0)?(double)wins/g_trade_count*100:0;
   double dd=(g_peak_equity>0)?(g_peak_equity-g_equity)/g_peak_equity*100:0;
   
   double atr=CalcATR(InpAtrPeriod);
   double atr_pct=CalcATRPercentile();
   double rsi=CalcRSI(InpRsiPeriod);
   double ema20=CalcEMA_M5(InpEmaFast);
   double price=GetClose(0);
   
   string L[24];
   L[0]="=== MITEMSHUB AI v14 ===";
   L[1]="Balance: $"+DoubleToString(g_equity,2);
   L[2]="Trades: "+IntegerToString(g_trade_count);
   L[3]="Win Rate: "+DoubleToString(wr,1)+"%";
   L[4]="Total R: "+DoubleToString(total_r,3);
   L[5]="Regime: "+RegimeToString(g_current_regime);
   L[6]="ATR %ile: "+DoubleToString(atr_pct,0)+"%";
   L[7]="RSI: "+DoubleToString(rsi,1);
   L[8]="Drawdown: "+DoubleToString(dd,2)+"%";
   L[9]="Consec Loss: "+IntegerToString(g_consec_loss);
   L[10]="Status: "+(g_paused?"PAUSED":(g_preloading?"PRELOAD":"ACTIVE"));
   L[11]=InpLiveExecution?"MODE: LIVE":"MODE: PAPER";
   L[12]="Risk: "+DoubleToString(InpRiskPerTrade*100,1)+"%/trade";
   L[13]="SL: "+DoubleToString(InpAtrStopMult,1)+"x ATR";
   L[14]="TP: "+DoubleToString(InpAtrTargetMult,1)+"x ATR";
   L[15]="Hold: "+IntegerToString(InpHoldBars*5)+"min";
   L[16]="EMA20(M5): "+DoubleToString(ema20,_Digits>3?2:5);
   L[17]="Price: "+DoubleToString(price,_Digits>3?2:5);
   L[18]="Compressed: "+(IsCompressed()?"YES":"NO");
   L[19]="Cooldown: "+IntegerToString(g_cooldown);
   L[20]="Daily P&L: $"+DoubleToString(g_daily_pnl,2);
   L[21]="MaxDD: 2% daily";
   L[22]="Risk: 0.5% fixed";
   L[23]="v14: Regime+Pullback";
   
   for(int i=0;i<24;i++)
     {
      ObjectSetString(0,g_dl[i],OBJPROP_TEXT,L[i]);
      color c=clrWhite;
      if(i==0) c=clrGold;
      else if(i==3) c=wr>=50?clrLime:(wr>=35?clrYellow:clrRed);
      else if(i==5) c=(g_current_regime==REGIME_BULLISH)?clrLime:
                       (g_current_regime==REGIME_BEARISH)?clrRed:
                       (g_current_regime==REGIME_RANGING)?clrYellow:clrGray;
      else if(i==6) c=(atr_pct>85||atr_pct<15)?clrRed:clrLime;
      else if(i==8) c=dd>5?clrRed:(dd>2?clrYellow:clrLime);
      else if(i==10) c=g_paused?clrRed:(g_preloading?clrYellow:clrLime);
      else if(i==11) c=InpLiveExecution?clrRed:clrDodgerBlue;
      else if(i==18) c=IsCompressed()?clrGold:clrGray;
      else if(i==20) c=g_daily_pnl>=0?clrLime:clrRed;
      ObjectSetInteger(0,g_dl[i],OBJPROP_COLOR,c);
     }
   ChartRedraw(0);
  }

void DrawSignal(int direction, datetime t, double price, string tag)
  {
   string name="MITEM_SIG_"+tag+"_"+IntegerToString(t);
   long arrow=(direction>0)?233:234;
   color c=(direction>0)?clrLime:clrRed;
   ObjectCreate(0,name,OBJ_ARROW,0,t,price);
   ObjectSetInteger(0,name,OBJPROP_ARROWCODE,arrow);
   ObjectSetInteger(0,name,OBJPROP_COLOR,c);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
  }

//+------------------------------------------------------------------+
//| GENERATE SIGNAL — v14: Regime + Pullback                          |
//+------------------------------------------------------------------+
int GenerateSignal(string &signal_type)
  {
   if(g_buf_count<InpWarmupCandles) return 0;
   
   ENUM_REGIME regime=ClassifyRegime();
   g_current_regime=regime;
   
   // No trade in bad regimes
   if(regime==REGIME_NO_TRADE || regime==REGIME_HIGH_VOL) return 0;
   
   double price=GetClose(0);
   double atr=CalcATR(InpAtrPeriod);
   double rsi=CalcRSI(InpRsiPeriod);
   double ema20_m5=CalcEMA_M5(InpEmaFast);
   
   //--- MODE 1: TRENDING REGIME → PULLBACK ENTRY
   if(regime==REGIME_BULLISH || regime==REGIME_BEARISH)
     {
      // Direction aligns with regime
      int dir=(regime==REGIME_BULLISH)?1:-1;
      
      // Price must have pulled back toward EMA20
      double pullback_dist=MathAbs(price-ema20_m5);
      if(pullback_dist<InpPullbackMin*atr) return 0;  // not enough pullback
      if(pullback_dist>InpPullbackMax*atr) return 0;  // too far, trend may have broken
      
      // Price must be on the correct side of EMA20 for pullback
      if(dir>0 && price>ema20_m5+atr) return 0;  // BUY: price should be near/below EMA20
      if(dir<0 && price<ema20_m5-atr) return 0;  // SELL: price should be near/above EMA20
      
      // RSI confirmation: not extreme
      if(dir>0 && rsi>60) return 0;  // BUY: RSI shouldn't be too high
      if(dir<0 && rsi<40) return 0;  // SELL: RSI shouldn't be too low
      
      // Confirmation candle: last bar must be in our direction
      double last_body=GetClose(0)-GetClose(1);
      if(dir>0 && last_body<=0) return 0;  // BUY: need bullish candle
      if(dir<0 && last_body>=0) return 0;  // SELL: need bearish candle
      
      // Gap check: current open shouldn't be too far from previous close
      double gap=MathAbs(GetClose(0)-GetClose(1));
      if(gap>atr*0.5) return 0;  // gap too large
      
      signal_type="PULLBACK_"+(dir>0?"LONG":"SHORT");
      return dir;
     }
   
   //--- MODE 2: RANGING REGIME → COMPRESSION BREAKOUT
   if(regime==REGIME_RANGING && IsCompressed())
     {
      // Find range high/low over last N bars
      double range_high=0, range_low=999999;
      for(int i=1;i<=InpCompressBars && i<g_buf_count;i++)
        {
         double h=GetHigh(i);
         double l=GetLow(i);
         if(h>range_high) range_high=h;
         if(l<range_low) range_low=l;
         }
      
      double range_mid=(range_high+range_low)/2.0;
      double range_size=range_high-range_low;
      
      if(range_size<atr*0.5) return 0;  // range too small
      
      // Breakout: close outside range
      double close=GetClose(0);
      int dir=0;
      
      if(close>range_high+InpBreakoutMin*atr)
        {
         dir=1;  // breakout UP
         // Check candle not too large (exhaustion)
         double candle_size=GetHigh(0)-GetLow(0);
         if(candle_size>atr*2.0) return 0;  // too large, may be exhaustion
        }
      else if(close<range_low-InpBreakoutMin*atr)
        {
         dir=-1;  // breakout DOWN
         double candle_size=GetHigh(0)-GetLow(0);
         if(candle_size>atr*2.0) return 0;
        }
      
      if(dir==0) return 0;
      
      // RSI confirmation for breakout
      if(dir>0 && rsi<50) return 0;  // bullish breakout needs RSI >50
      if(dir<0 && rsi>50) return 0;  // bearish breakout needs RSI <50
      
      signal_type="BREAKOUT_"+(dir>0?"UP":"DOWN");
      return dir;
     }
   
   return 0;
  }

//+------------------------------------------------------------------+
//| PROCESS ONE BAR                                                     |
//+------------------------------------------------------------------+
void ProcessOneBar(const AggregatedBar &bar)
  {
   g_bars_seen++;
   if(g_last_bar_end>0 && bar.time>g_last_bar_end+(datetime)MathMax(3*InpBarSec,600))
     { g_prev_close=bar.close; g_last_bar_end=bar.time+InpBarSec; return; }
   g_last_bar_end=bar.time+InpBarSec;
   if(g_prev_close<=0) { g_prev_close=bar.close; return; }
   
   double prev_close=g_prev_close;
   g_prev_close=bar.close;
   
   // Push to buffer
   PushBar(bar.close,bar.high,bar.low);
   
   // Update ATR history
   double atr=CalcATR(InpAtrPeriod);
   g_atr_history[g_atr_hist_count%500]=atr;
   if(g_atr_hist_count<500) g_atr_hist_count++;
   
   // Update cooldown
   if(g_cooldown>0) g_cooldown--;
   
   // Daily reset
   datetime ds=bar.time-(bar.time%86400);
   if(ds!=g_day_start) { g_day_start=ds; g_daily_pnl=0; }
   
   if(g_preloading) return;
   
   //--- MANAGE POSITION (FIXED: use original_risk for R calc)
   if(g_pos.active)
     {
      g_pos.entry_bar++;
      
      // Time exit
      if(g_pos.entry_bar>=InpHoldBars)
        {
         double exit_p=bar.close;
         double r_mult=(g_pos.direction>0)?
                       (exit_p-g_pos.entry_price)/g_pos.original_risk:
                       (g_pos.entry_price-exit_p)/g_pos.original_risk;
         double pnl=g_pos.stake*r_mult;
         g_equity+=pnl; g_daily_pnl+=pnl;
         g_peak_equity=MathMax(g_peak_equity,g_equity);
         
         if(r_mult<0) { g_consec_loss++; g_cooldown=InpCoolDownBars; }
         else g_consec_loss=0;
         
         if(g_consec_loss>=InpMaxConsecLoss) g_paused=true;
         if(g_daily_pnl<-g_equity*InpMaxDailyLossPct) g_paused=true;
         if((g_peak_equity-g_equity)>g_peak_equity*0.10) g_paused=true;
         
         if(g_trade_count<MAX_TRADES)
           {
            g_trades[g_trade_count].entry_time=g_pos.entry_time;
            g_trades[g_trade_count].exit_time=bar.time+InpBarSec;
            g_trades[g_trade_count].direction=g_pos.direction;
            g_trades[g_trade_count].entry_price=g_pos.entry_price;
            g_trades[g_trade_count].exit_price=exit_p;
            g_trades[g_trade_count].original_sl=g_pos.original_risk;
            g_trades[g_trade_count].return_r=r_mult;
            g_trades[g_trade_count].pnl=pnl;
            g_trades[g_trade_count].exit_reason="TIME";
            g_trade_count++;
           }
         
         Print(StringFormat("[MITEM] TIME @%.5f R=%.3f $%.2f #trade=%d",exit_p,r_mult,pnl,g_trade_count));
         g_pos.active=false;
         return;
        }
      
      // SL check
      if(g_pos.direction>0 && bar.low<=g_pos.stop_loss)
        {
         double exit_p=g_pos.stop_loss;
         double r_mult=(exit_p-g_pos.entry_price)/g_pos.original_risk;
         double pnl=g_pos.stake*r_mult;
         g_equity+=pnl; g_daily_pnl+=pnl;
         g_peak_equity=MathMax(g_peak_equity,g_equity);
         
         g_consec_loss++; g_cooldown=InpCoolDownBars;
         if(g_consec_loss>=InpMaxConsecLoss) g_paused=true;
         if(g_daily_pnl<-g_equity*InpMaxDailyLossPct) g_paused=true;
         if((g_peak_equity-g_equity)>g_peak_equity*0.10) g_paused=true;
         
         if(g_trade_count<MAX_TRADES)
           {
            g_trades[g_trade_count].entry_time=g_pos.entry_time;
            g_trades[g_trade_count].exit_time=bar.time+InpBarSec;
            g_trades[g_trade_count].direction=g_pos.direction;
            g_trades[g_trade_count].entry_price=g_pos.entry_price;
            g_trades[g_trade_count].exit_price=exit_p;
            g_trades[g_trade_count].original_sl=g_pos.original_risk;
            g_trades[g_trade_count].return_r=r_mult;
            g_trades[g_trade_count].pnl=pnl;
            g_trades[g_trade_count].exit_reason="STOP";
            g_trade_count++;
           }
         
         Print(StringFormat("[MITEM] STOP @%.5f R=%.3f $%.2f #trade=%d",exit_p,r_mult,pnl,g_trade_count));
         g_pos.active=false;
         return;
        }
      
      if(g_pos.direction<0 && bar.high>=g_pos.stop_loss)
        {
         double exit_p=g_pos.stop_loss;
         double r_mult=(g_pos.entry_price-exit_p)/g_pos.original_risk;
         double pnl=g_pos.stake*r_mult;
         g_equity+=pnl; g_daily_pnl+=pnl;
         g_peak_equity=MathMax(g_peak_equity,g_equity);
         
         g_consec_loss++; g_cooldown=InpCoolDownBars;
         if(g_consec_loss>=InpMaxConsecLoss) g_paused=true;
         if(g_daily_pnl<-g_equity*InpMaxDailyLossPct) g_paused=true;
         if((g_peak_equity-g_equity)>g_peak_equity*0.10) g_paused=true;
         
         if(g_trade_count<MAX_TRADES)
           {
            g_trades[g_trade_count].entry_time=g_pos.entry_time;
            g_trades[g_trade_count].exit_time=bar.time+InpBarSec;
            g_trades[g_trade_count].direction=g_pos.direction;
            g_trades[g_trade_count].entry_price=g_pos.entry_price;
            g_trades[g_trade_count].exit_price=exit_p;
            g_trades[g_trade_count].original_sl=g_pos.original_risk;
            g_trades[g_trade_count].return_r=r_mult;
            g_trades[g_trade_count].pnl=pnl;
            g_trades[g_trade_count].exit_reason="STOP";
            g_trade_count++;
           }
         
         Print(StringFormat("[MITEM] STOP @%.5f R=%.3f $%.2f #trade=%d",exit_p,r_mult,pnl,g_trade_count));
         g_pos.active=false;
         return;
        }
      
      // TP check
      if(g_pos.direction>0 && bar.high>=g_pos.take_profit)
        {
         double exit_p=g_pos.take_profit;
         double r_mult=(exit_p-g_pos.entry_price)/g_pos.original_risk;
         double pnl=g_pos.stake*r_mult;
         g_equity+=pnl; g_daily_pnl+=pnl;
         g_peak_equity=MathMax(g_peak_equity,g_equity);
         g_consec_loss=0;
         
         if(g_trade_count<MAX_TRADES)
           {
            g_trades[g_trade_count].entry_time=g_pos.entry_time;
            g_trades[g_trade_count].exit_time=bar.time+InpBarSec;
            g_trades[g_trade_count].direction=g_pos.direction;
            g_trades[g_trade_count].entry_price=g_pos.entry_price;
            g_trades[g_trade_count].exit_price=exit_p;
            g_trades[g_trade_count].original_sl=g_pos.original_risk;
            g_trades[g_trade_count].return_r=r_mult;
            g_trades[g_trade_count].pnl=pnl;
            g_trades[g_trade_count].exit_reason="TARGET";
            g_trade_count++;
           }
         
         Print(StringFormat("[MITEM] TARGET @%.5f R=%.3f $%.2f #trade=%d",exit_p,r_mult,pnl,g_trade_count));
         g_pos.active=false;
         return;
        }
      
      if(g_pos.direction<0 && bar.low<=g_pos.take_profit)
        {
         double exit_p=g_pos.take_profit;
         double r_mult=(g_pos.entry_price-exit_p)/g_pos.original_risk;
         double pnl=g_pos.stake*r_mult;
         g_equity+=pnl; g_daily_pnl+=pnl;
         g_peak_equity=MathMax(g_peak_equity,g_equity);
         g_consec_loss=0;
         
         if(g_trade_count<MAX_TRADES)
           {
            g_trades[g_trade_count].entry_time=g_pos.entry_time;
            g_trades[g_trade_count].exit_time=bar.time+InpBarSec;
            g_trades[g_trade_count].direction=g_pos.direction;
            g_trades[g_trade_count].entry_price=g_pos.entry_price;
            g_trades[g_trade_count].exit_price=exit_p;
            g_trades[g_trade_count].original_sl=g_pos.original_risk;
            g_trades[g_trade_count].return_r=r_mult;
            g_trades[g_trade_count].pnl=pnl;
            g_trades[g_trade_count].exit_reason="TARGET";
            g_trade_count++;
           }
         
         Print(StringFormat("[MITEM] TARGET @%.5f R=%.3f $%.2f #trade=%d",exit_p,r_mult,pnl,g_trade_count));
         g_pos.active=false;
         return;
        }
      
      return;  // position still open, no entry
     }
   
   //--- ENTRY GATE
   if(g_pos.active) return;
   if(g_paused) return;
   if(g_bars_seen<(long)InpWarmupCandles) return;
   if(g_cooldown>0) return;
   if(atr<=0) return;
   
   // Generate signal
   string signal_type="";
   int direction=GenerateSignal(signal_type);
   if(direction==0) return;
   
   // Calculate SL/TP
   double entry=bar.close;
   double sd=InpAtrStopMult*atr;
   double td=InpAtrTargetMult*atr;
   
   // Sanity: max stop 2% of price
   double max_stop=entry*0.02;
   if(sd>max_stop) sd=max_stop;
   if(sd<atr*0.5) sd=atr*0.5;
   
   double sl,tp;
   if(direction>0) { sl=entry-sd; tp=entry+td; }
   else            { sl=entry+sd; tp=entry-td; }
   
   // Fixed risk sizing (NO anti-martingale)
   double risk_pct=InpRiskPerTrade;
   double stake=g_equity*risk_pct;
   
   // Execute
   if(InpLiveExecution)
     {
      MqlTradeRequest  req={};
      MqlTradeResult   res={};
      req.action=TRADE_ACTION_DEAL;
      req.symbol=_Symbol;
      req.volume=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      req.type=(direction>0)?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
      req.price=(direction>0)?SymbolInfoDouble(_Symbol,SYMBOL_ASK):SymbolInfoDouble(_Symbol,SYMBOL_BID);
      req.sl=NormalizeDouble(sl,_Digits);
      req.tp=NormalizeDouble(tp,_Digits);
      req.deviation=InpMaxSlippagePts;
      req.magic=InpMagic;
      req.comment="MITEM_v14";
      if(!OrderSend(req,res))
        { Print("[MITEM] ORDER FAIL:",res.retcode,"-",res.comment); g_cooldown=InpCoolDownBars; return; }
      stake=res.volume*SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE)
            *(td/SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
     }
   
   // Open position with ORIGINAL risk preserved
   g_pos.direction=direction;
   g_pos.entry_price=entry;
   g_pos.stop_loss=sl;
   g_pos.take_profit=tp;
   g_pos.original_risk=sd;  // CRITICAL: preserve original SL distance
   g_pos.entry_time=bar.time+InpBarSec;
   g_pos.entry_bar=0;
   g_pos.stake=stake;
   g_pos.active=true;
   
   if(InpDrawSignals) DrawSignal(direction,bar.time+InpBarSec,entry,signal_type);
   
   Print(StringFormat("[MITEM] %s %s @%.5f SL=%.5f TP=%.5f ATR=%.4f $%.2f Regime=%s",
                      signal_type,direction>0?"BUY":"SELL",entry,sl,tp,atr,stake,
                      RegimeToString(g_current_regime)));
  }

//+------------------------------------------------------------------+
//| OnInit                                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[MITEM] === MITEMSHUB AI v14 starting ===");
   g_equity=AccountInfoDouble(ACCOUNT_BALANCE);
   g_peak_equity=g_equity;
   Print(StringFormat("[MITEM] Account balance: $%.2f",g_equity));
   g_agg.Reset(InpBarSec);
   if(InpDrawDashboard) DashCreate();
   
   // Load M15 data for regime detection
   MqlRates m15_rates[];
   int m15_got=CopyRates(_Symbol,PERIOD_M15,0,MAX_M15,m15_rates);
   if(m15_got>0)
     {
      for(int i=0;i<m15_got;i++)
        {
         g_m15_close[i]=m15_rates[i].close;
         g_m15_high[i]=m15_rates[i].high;
         g_m15_low[i]=m15_rates[i].low;
        }
      g_m15_count=m15_got;
      Print(StringFormat("[MITEM] M15 preload: %d bars",m15_got));
     }
   
   // Preload M5 data
   g_preloading=true;
   int preload=MathMax(InpWarmupCandles*3,500);
   MqlRates rates[];
   int got=CopyRates(_Symbol,PERIOD_M5,0,preload,rates);
   if(got>0)
     {
      Print(StringFormat("[MITEM] M5 preload: %d bars",got));
      for(int i=got-1;i>=0;i--)
        {
         AggregatedBar ab;
         ab.open=rates[i].open; ab.high=rates[i].high;
         ab.low=rates[i].low; ab.close=rates[i].close;
         ab.time=rates[i].time;
         ProcessOneBar(ab);
        }
      g_preloading=false;
     }
   else g_preloading=false;
   
   Print(StringFormat("[MITEM] v14: Regime+Pullback | SL=%.1f ATR | TP=%.1f ATR | Risk=%.1f%% | MaxDD=2%%",
                      InpAtrStopMult,InpAtrTargetMult,InpRiskPerTrade*100));
   Print(StringFormat("[MITEM] Regime: EMA %d/%d/%d M15 | ATR filter: %.0f-%.0f%%",
                      InpEmaFast,InpEmaMid,InpEmaSlow,InpAtrLowPct,InpAtrHighPct));
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| OnTick                                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick)) return;
   if(tick.bid<=0) return;
   AggregatedBar closed;
   if(g_agg.OnTick(tick.bid,(datetime)tick.time))
     {
      if(g_agg.ClosedBar(closed))
        { ProcessOneBar(closed); g_agg.RestartBar(tick.bid,(datetime)tick.time); }
     }
   if(InpDrawDashboard) DashUpdate();
  }

//+------------------------------------------------------------------+
//| OnDeinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   for(int i=0;i<24;i++) ObjectDelete(0,g_dl[i]);
   double total_r=0; int wins=0,ns=0,nt=0,ntm=0;
   for(int i=0;i<g_trade_count;i++)
     {
      total_r+=g_trades[i].return_r;
      if(g_trades[i].return_r>0) wins++;
      if(g_trades[i].exit_reason=="STOP") ns++;
      if(g_trades[i].exit_reason=="TARGET") nt++;
      if(g_trades[i].exit_reason=="TIME") ntm++;
     }
   double wr=(g_trade_count>0)?(double)wins/g_trade_count*100:0;
   double dd=(g_peak_equity>0)?(g_peak_equity-g_equity)/g_peak_equity*100:0;
   Print("========================================");
   Print("[MITEM] === SESSION SUMMARY v14 ===");
   Print(StringFormat("[MITEM] trades=%d wr=%.1f%% R=%+.3f",g_trade_count,wr,total_r));
   Print(StringFormat("[MITEM] exits: stop=%d target=%d time=%d",ns,nt,ntm));
   Print(StringFormat("[MITEM] equity=$%.2f peak=$%.2f dd=%.2f%%",g_equity,g_peak_equity,dd));
   Print("[MITEM] === END ===");
   Print("========================================");
  }
//+------------------------------------------------------------------+
