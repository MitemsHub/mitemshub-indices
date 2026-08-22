//+------------------------------------------------------------------+
//|                                            MitemshubAI.mq5       |
//|                        MITEMSHUB AI MARKETING ENGINE v13         |
//|                   Multi-Indicator Mean-Reversion Engine           |
//|                                                                    |
//|  Strategy (v13 - rebuilt from autopsy of v11 losses):             |
//|  - Vol 75: SMA50 distance fade + RSI confirmation                 |
//|  - Vol 100: Momentum exhaustion (5+ bars) + RSI confirmation     |
//|  - ATR-based adaptive stops and targets                           |
//|  - Cool-down after losses, max daily loss cap                     |
//|                                                                    |
//|  Root cause of v11 failure: single-bar z-score was noise (15% WR) |
//|  v13 uses MULTI-BAR indicators that actually have statistical edge |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "13.00"
#property strict

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input int    InpBarSec           = 300;       // Bar period in seconds (300=M5)
//--- Strategy Selection
input int    InpStrategy         = 0;         // 0=auto (symbol-based), 1=SMA50 fade, 2=momentum exhaust
//--- SMA50 Distance Strategy (Vol 75 primary)
input int    InpSmaPeriod        = 50;        // SMA period for distance calculation
input double InpSmaDistPct       = 1.5;       // min % distance from SMA to trigger signal
//--- Momentum Exhaustion Strategy (Vol 100 primary)
input int    InpConsecBars       = 5;         // consecutive bars required for exhaustion
input int    InpConsecLookback   = 7;         // lookback window for counting
//--- RSI Confirmation
input int    InpRsiPeriod        = 14;        // RSI period
input double InpRsiOversold      = 35.0;      // RSI oversold threshold (buy below this)
input double InpRsiOverbought    = 65.0;      // RSI overbought threshold (sell above this)
input bool   InpUseRsiConfirm    = true;      // require RSI confirmation
//--- Bollinger Band Filter
input int    InpBbPeriod         = 20;        // BB period
input double InpBbDev            = 2.0;       // BB standard deviation multiplier
input bool   InpUseBbFilter      = true;      // require price near BB extreme
//--- Risk Management
input double InpRiskPerTrade     = 0.05;      // 5% of equity per trade (conservative after losses)
input double InpAtrStopMult      = 1.5;       // stop loss = ATR * multiplier
input double InpAtrTargetMult    = 2.5;       // take profit = ATR * multiplier
input int    InpHoldSec          = 3600;      // max hold time in seconds (60 min)
input double InpMaxDailyLossPct  = 0.08;      // max daily loss (8% of equity)
input int    InpMaxConsecLoss    = 3;         // max consecutive losses before pause
input int    InpCoolDownBars     = 3;         // bars to wait after a loss
input double InpMinTargetRR      = 1.2;       // minimum reward:risk ratio
//--- Trailing Stop
input bool   InpTrailOn          = true;      // enable trailing stop
input double InpTrailATRMult     = 1.0;       // trail distance as ATR multiple
//--- Trend Filter
input bool   InpUseTrendFilter   = true;      // filter trades against the trend
input int    InpTrendSmaFast     = 20;        // fast SMA for trend detection
input int    InpTrendSmaSlow     = 50;        // slow SMA for trend detection
//--- Execution
input bool   InpLiveExecution    = true;      // false=paper, true=live
input long   InpMagic            = 7788123;   // EA magic number
input int    InpMaxSlippagePts   = 50;        // max slippage (points)
input int    InpWarmupCandles    = 100;       // min bars before trading
input bool   InpDrawDashboard    = true;      // draw dashboard on chart
input bool   InpDrawSignals      = true;      // draw entry/exit arrows

//+------------------------------------------------------------------+
//| ATR CALCULATOR                                                     |
//+------------------------------------------------------------------+
class CVolatilityEngine
  {
private:
   double m_atr;
   double m_tr[14];
   int    m_tr_idx,m_tr_cnt;
public:
   CVolatilityEngine(): m_atr(0),m_tr_idx(0),m_tr_cnt(0) {}
   void OnBar(double prev_close, double high, double low, double close)
     {
      double tv=high-low;
      if(prev_close>0)
        {
         double t1=MathAbs(high-prev_close), t2=MathAbs(low-prev_close);
         if(t1>tv) tv=t1; if(t2>tv) tv=t2;
        }
      m_tr[m_tr_idx]=tv; m_tr_idx=(m_tr_idx+1)%14;
      if(m_tr_cnt<14) m_tr_cnt++;
      double s=0; for(int i=0;i<m_tr_cnt;i++) s+=m_tr[i];
      m_atr=s/m_tr_cnt;
     }
   double ATR() const { return m_atr; }
  };

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
//| TRAILING STOP MANAGER                                              |
//+------------------------------------------------------------------+
struct PositionInfo
  {
   int      direction;
   double   entry_price,stop_loss,take_profit;
   datetime entry_time;
   double   stake;
   bool     active;
  };

class CTrailManager
  {
private:
   PositionInfo m_pos;
   double       m_atr_ema;
   double       m_peak_pnl;
public:
   CTrailManager(): m_atr_ema(0),m_peak_pnl(0) { m_pos.active=false; }
   void Reset() { m_pos.active=false; m_peak_pnl=0; }
   void OpenPosition(int dir,double entry,double sl,double tp,datetime t,double stake)
     {
      m_pos.direction=dir; m_pos.entry_price=entry; m_pos.stop_loss=sl;
      m_pos.take_profit=tp; m_pos.entry_time=t; m_pos.stake=stake;
      m_pos.active=true; m_peak_pnl=0;
     }
   void UpdateATR(double atr)
     { if(m_atr_ema<=0) m_atr_ema=atr; else m_atr_ema=m_atr_ema*0.98+atr*0.02; }
   int Manage(double high,double low,double close,datetime bar_time,
              int bar_sec,double &exit_price,string &reason)
     {
      if(!m_pos.active) return 0;
      if((int)(bar_time-m_pos.entry_time)>=InpHoldSec)
        { exit_price=close; reason="TIME"; return 1; }
      double risk=MathAbs(m_pos.entry_price-m_pos.stop_loss);
      if(risk<1e-12) risk=1e-12;
      double pnl=(m_pos.direction>0)?close-m_pos.entry_price:m_pos.entry_price-close;
      double rr=pnl/risk;
      //--- Check SL and TP
      if(m_pos.direction>0 && low<=m_pos.stop_loss)
        { exit_price=m_pos.stop_loss; reason="STOP"; return 1; }
      if(m_pos.direction<0 && high>=m_pos.stop_loss)
        { exit_price=m_pos.stop_loss; reason="STOP"; return 1; }
      if(m_pos.direction>0 && high>=m_pos.take_profit)
        { exit_price=m_pos.take_profit; reason="TARGET"; return 1; }
      if(m_pos.direction<0 && low<=m_pos.take_profit)
        { exit_price=m_pos.take_profit; reason="TARGET"; return 1; }
      if(pnl>m_peak_pnl) m_peak_pnl=pnl;
      //--- Break-even at 0.5R
      if(InpTrailOn && rr>=0.5)
        {
         if(m_pos.direction>0)
           { double be=m_pos.entry_price+risk*0.1; if(be>m_pos.stop_loss) m_pos.stop_loss=be; }
         else
           { double be=m_pos.entry_price-risk*0.1; if(be<m_pos.stop_loss) m_pos.stop_loss=be; }
        }
      //--- Trailing stop: tighter as profit grows
      if(InpTrailOn && rr>=1.0 && m_atr_ema>0)
        {
         double td=InpTrailATRMult*m_atr_ema;
         double trail_frac=0.6;
         if(rr>=2.0) trail_frac=0.45;
         if(rr>=3.0) trail_frac=0.3;
         if(m_pos.direction>0)
           {
            double ns=close-td*trail_frac;
            if(ns>m_pos.stop_loss) m_pos.stop_loss=ns;
           }
         else
           {
            double ns=close+td*trail_frac;
            if(ns<m_pos.stop_loss) m_pos.stop_loss=ns;
           }
        }
      return 0;
     }
   bool IsOpen() const { return m_pos.active; }
   PositionInfo GetPosition() const { return m_pos; }
  };

//+------------------------------------------------------------------+
//| TRADE RECORD                                                       |
//+------------------------------------------------------------------+
struct TradeRecord
  {
   datetime entry_time,exit_time;
   int      direction;
   double   entry_price,exit_price,stop_loss,take_profit,return_r,pnl;
   string   exit_reason;
   string   signal_type;
  };
#define MAX_TRADES 10000
TradeRecord g_trades[MAX_TRADES];
int         g_trade_count=0;

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
CBarAggregator   g_agg;
CVolatilityEngine g_vol;
CTrailManager    g_trail;

double g_prev_close=0, g_ema=0;
long   g_bars_seen=0;
datetime g_last_bar_end=0;
double g_atr_ema=0, g_equity=0, g_peak_equity=0;
double g_daily_pnl=0;
int    g_cooldown=0, g_consec_loss=0, g_consec_win=0;
bool   g_preloading=false, g_paused=false;
datetime g_day_start=0;
bool   g_last_trade_won=false;

//--- History buffers for indicator calculation
#define MAX_HISTORY 500
double g_close_buf[MAX_HISTORY];
double g_high_buf[MAX_HISTORY];
double g_low_buf[MAX_HISTORY];
int    g_buf_count=0;
int    g_buf_head=0;

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
double CalcSMA(int period)
  {
   if(g_buf_count<period) return GetClose(0);
   double s=0;
   for(int i=0;i<period;i++) s+=GetClose(i);
   return s/period;
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

double CalcBollingerUpper(int period, double dev)
  {
   double sma=CalcSMA(period);
   if(g_buf_count<period) return sma+dev*g_vol.ATR();
   double var=0;
   for(int i=0;i<period;i++)
     { double d=GetClose(i)-sma; var+=d*d; }
   return sma+dev*MathSqrt(var/period);
  }

double CalcBollingerLower(int period, double dev)
  {
   double sma=CalcSMA(period);
   if(g_buf_count<period) return sma-dev*g_vol.ATR();
   double var=0;
   for(int i=0;i<period;i++)
     { double d=GetClose(i)-sma; var+=d*d; }
   return sma-dev*MathSqrt(var/period);
  }

int CountConsecutiveBars(int lookback)
  {
   int up=0, down=0;
   for(int i=1;i<=lookback && i<g_buf_count;i++)
     {
      if(GetClose(i-1)>GetClose(i)) up++;
      else if(GetClose(i-1)<GetClose(i)) down++;
     }
   return (up>=down)?up:(-down);
  }

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
#define DASH_Y 20
#define DASH_H 18
#define DASH_X 10
string g_dl[22];

void DashCreate()
  {
   for(int i=0;i<22;i++)
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
   
   double sma50=CalcSMA(InpSmaPeriod);
   double rsi=CalcRSI(InpRsiPeriod);
   int consec=CountConsecutiveBars(InpConsecLookback);
   double atr=g_vol.ATR();
   double price=GetClose(0);
   double sma_dist=(price>0&&sma50>0)?(price-sma50)/sma50*100:0;
   
   string L[22];
   L[0]="=== MITEMSHUB AI v13 ===";
   L[1]="Balance: $"+DoubleToString(g_equity,2);
   L[2]="Trades: "+IntegerToString(g_trade_count);
   L[3]="Win Rate: "+DoubleToString(wr,1)+"%";
   L[4]="Total R: "+DoubleToString(total_r,3);
   L[5]="ATR: "+DoubleToString(atr,4);
   L[6]="RSI(14): "+DoubleToString(rsi,1);
   L[7]="Bars: "+IntegerToString(g_bars_seen);
   L[8]="Drawdown: "+DoubleToString(dd,2)+"%";
   L[9]="Consec Loss: "+IntegerToString(g_consec_loss);
   L[10]="Status: "+(g_paused?"PAUSED":(g_preloading?"PRELOAD":"ACTIVE"));
   L[11]=InpLiveExecution?"MODE: LIVE":"MODE: PAPER";
   L[12]="Risk: "+DoubleToString(InpRiskPerTrade*100,1)+"%/trade";
   L[13]="SMA50 Dist: "+DoubleToString(sma_dist,3)+"%";
   L[14]="SMA Dist Thresh: "+DoubleToString(InpSmaDistPct,1)+"%";
   L[15]="Consec Bars: "+IntegerToString(consec);
   L[16]="SL: "+DoubleToString(InpAtrStopMult,1)+"x ATR";
   L[17]="TP: "+DoubleToString(InpAtrTargetMult,1)+"x ATR";
   L[18]="Hold: "+IntegerToString(InpHoldSec/60)+"min";
   L[19]="Strategy: "+(IsVol75()?"SMA50 Fade":"Mom Exhaust");
   L[20]="Cooldown: "+IntegerToString(g_cooldown);
   L[21]="Daily P&L: $"+DoubleToString(g_daily_pnl,2);
   
   for(int i=0;i<22;i++)
     {
      ObjectSetString(0,g_dl[i],OBJPROP_TEXT,L[i]);
      color c=clrWhite;
      if(i==0) c=clrGold;
      else if(i==3) c=wr>=50?clrLime:(wr>=35?clrYellow:clrRed);
      else if(i==6) c=rsi<30?clrLime:(rsi>70?clrRed:clrWhite);
      else if(i==8) c=dd>5?clrRed:(dd>2?clrYellow:clrLime);
      else if(i==10) c=g_paused?clrRed:(g_preloading?clrYellow:clrLime);
      else if(i==11) c=InpLiveExecution?clrRed:clrDodgerBlue;
      else if(i==13) c=MathAbs(sma_dist)>InpSmaDistPct?clrGold:clrGray;
      else if(i==19) c=clrDodgerBlue;
      else if(i==21) c=g_daily_pnl>=0?clrLime:clrRed;
      ObjectSetInteger(0,g_dl[i],OBJPROP_COLOR,c);
     }
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| SIGNAL ARROW                                                       |
//+------------------------------------------------------------------+
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
//| SYMBOL HELPERS                                                      |
//+------------------------------------------------------------------+
bool IsVol75()
  { return StringFind(_Symbol,"75")>=0; }

bool IsVol100()
  { return StringFind(_Symbol,"100")>=0; }

int GetStrategy()
  {
   if(InpStrategy>0) return InpStrategy;
   return IsVol75()?1:2;  // Vol75=SMA50 fade, Vol100=momentum exhaust
  }

//+------------------------------------------------------------------+
//| GENERATE SIGNAL — THE NEW BRAIN                                     |
//+------------------------------------------------------------------+
// Returns: 1=BUY, -1=SELL, 0=no signal
// Also outputs signal_type for logging
int GenerateSignal(string &signal_type)
  {
   if(g_buf_count<InpWarmupCandles) return 0;
   
   double price=GetClose(0);
   double rsi=CalcRSI(InpRsiPeriod);
   int strategy=GetStrategy();
   
   //--- STRATEGY 1: SMA50 Distance Fade (Vol 75 primary)
   if(strategy==1)
     {
      double sma=CalcSMA(InpSmaPeriod);
      if(sma<=0) return 0;
      double dist_pct=(price-sma)/sma*100.0;
      
      // Need price to be far from SMA
      if(MathAbs(dist_pct)<InpSmaDistPct) return 0;
      
      // RSI confirmation
      if(InpUseRsiConfirm)
        {
         if(dist_pct>0 && rsi<InpRsiOversold) return 0;  // don't sell if RSI already oversold
         if(dist_pct<0 && rsi>InpRsiOverbought) return 0;  // don't buy if RSI already overbought
         // Confirm: sell when price above SMA AND RSI elevated, buy when below AND RSI depressed
         if(dist_pct>0 && rsi<50) return 0;  // need RSI to confirm overbought
         if(dist_pct<0 && rsi>50) return 0;  // need RSI to confirm oversold
        }
      
      // BB filter: price should be near outer band
      if(InpUseBbFilter)
        {
         double upper=CalcBollingerUpper(InpBbPeriod,InpBbDev);
         double lower=CalcBollingerLower(InpBbPeriod,InpBbDev);
         if(dist_pct>0 && price<upper*0.998) return 0;  // must be near upper band
         if(dist_pct>0 && price>(upper+(upper-lower)*0.1)) return 0;  // skip if WAY above band
         if(dist_pct<0 && price>lower*1.002) return 0;  // must be near lower band
         if(dist_pct<0 && price<(lower-(upper-lower)*0.1)) return 0;  // skip if WAY below band
        }
      
      // Trend filter: don't fade strong trends
      if(InpUseTrendFilter)
        {
         double sma_fast=CalcSMA(InpTrendSmaFast);
         double sma_slow=CalcSMA(InpTrendSmaSlow);
         // Don't sell if fast > slow (uptrend)
         if(dist_pct>0 && sma_fast>sma_slow*1.001) return 0;
         // Don't buy if fast < slow (downtrend)
         if(dist_pct<0 && sma_fast<sma_slow*0.999) return 0;
        }
      
      signal_type="SMA50_FADE";
      return (dist_pct>0)?-1:1;  // above SMA=SELL, below=BUY
     }
   
   //--- STRATEGY 2: Momentum Exhaustion (Vol 100 primary)
   if(strategy==2)
     {
      int consec=CountConsecutiveBars(InpConsecLookback);
      int abs_consec=MathAbs(consec);
      
      if(abs_consec<InpConsecBars) return 0;
      
      // RSI confirmation
      if(InpUseRsiConfirm)
        {
         if(consec>0 && rsi<55) return 0;   // need RSI >55 for sell exhaustion
         if(consec<0 && rsi>45) return 0;   // need RSI <45 for buy exhaustion
         // Stronger confirmation: require RSI to be in extreme zone
         if(consec>0 && rsi<InpRsiOverbought) return 0;
         if(consec<0 && rsi>InpRsiOversold) return 0;
        }
      
      // BB filter: price should be extended
      if(InpUseBbFilter)
        {
         double upper=CalcBollingerUpper(InpBbPeriod,InpBbDev);
         double lower=CalcBollingerLower(InpBbPeriod,InpBbDev);
         if(consec>0 && price<upper*0.995) return 0;  // sell only near upper band
         if(consec<0 && price>lower*1.005) return 0;  // buy only near lower band
        }
      
      // Trend filter
      if(InpUseTrendFilter)
        {
         double sma_fast=CalcSMA(InpTrendSmaFast);
         double sma_slow=CalcSMA(InpTrendSmaSlow);
         if(consec>0 && sma_fast>sma_slow*1.002) return 0;  // don't fade uptrend
         if(consec<0 && sma_fast<sma_slow*0.998) return 0;  // don't fade downtrend
        }
      
      signal_type="MOM_EXHAUST";
      return (consec>0)?-1:1;  // up exhaustion=SELL, down=BUY
     }
   
   return 0;
  }

//+------------------------------------------------------------------+
//| PROCESS ONE CLOSED BAR                                             |
//+------------------------------------------------------------------+
void ProcessOneBar(const AggregatedBar &bar)
  {
   g_bars_seen++;
   if(g_last_bar_end>0 && bar.time>g_last_bar_end+(datetime)MathMax(3*InpBarSec,600))
     { g_prev_close=bar.close; g_ema=bar.close; g_last_bar_end=bar.time+InpBarSec; return; }
   g_last_bar_end=bar.time+InpBarSec;
   if(g_prev_close<=0) { g_prev_close=bar.close; g_ema=bar.close; return; }
   
   double prev_close=g_prev_close;
   g_prev_close=bar.close;
   
   //--- Update ATR
   g_vol.OnBar(prev_close,bar.high,bar.low,bar.close);
   double atr=g_vol.ATR();
   g_atr_ema=(g_atr_ema<=0)?atr:g_atr_ema*0.98+atr*0.02;
   g_trail.UpdateATR(atr);
   
   //--- Push to history buffer
   PushBar(bar.close,bar.high,bar.low);
   
   //--- Update cooldown
   if(g_cooldown>0) g_cooldown--;
   
   //--- Daily reset
   datetime ds=bar.time-(bar.time%86400);
   if(ds!=g_day_start) { g_day_start=ds; g_daily_pnl=0; }
   
   if(g_preloading) return;
   
   //--- MANAGE POSITION ---
   if(g_trail.IsOpen())
     {
      double ep=0; string reason="";
      if(g_trail.Manage(bar.high,bar.low,bar.close,bar.time,InpBarSec,ep,reason)==1)
        {
         PositionInfo pos=g_trail.GetPosition();
         double slipped=(pos.direction>0)?ep-0.05:ep+0.05;
         double risk=MathAbs(pos.entry_price-pos.stop_loss);
         if(risk<1e-12) risk=1e-12;
         double rr=(pos.direction>0)?(slipped-pos.entry_price)/risk:(pos.entry_price-slipped)/risk;
         double pnl=pos.stake*rr;
         g_equity+=pnl; g_daily_pnl+=pnl;
         g_peak_equity=MathMax(g_peak_equity,g_equity);
         
         //--- Track consecutive losses and wins
         if(rr<0)
           {
            g_consec_loss++;
            g_consec_win=0;
            g_cooldown=InpCoolDownBars;  // cool down after loss
           }
         else
           {
            g_consec_win++;
            g_consec_loss=0;
           }
         
         //--- Pause conditions
         if(g_consec_loss>=InpMaxConsecLoss)
           {
            g_paused=true;
            Print("[MITEM] PAUSED: "+IntegerToString(g_consec_loss)+" consecutive losses");
           }
         if(g_daily_pnl<-g_equity*InpMaxDailyLossPct)
           {
            g_paused=true;
            Print("[MITEM] PAUSED: daily loss limit hit ($"+DoubleToString(g_daily_pnl,2)+")");
           }
         if((g_peak_equity-g_equity)>g_peak_equity*0.15)
           {
            g_paused=true;
            Print("[MITEM] PAUSED: max drawdown 15% reached");
           }
         
         //--- Record trade
         if(g_trade_count<MAX_TRADES)
           {
            g_trades[g_trade_count].entry_time=pos.entry_time;
            g_trades[g_trade_count].exit_time=bar.time+InpBarSec;
            g_trades[g_trade_count].direction=pos.direction;
            g_trades[g_trade_count].entry_price=pos.entry_price;
            g_trades[g_trade_count].exit_price=slipped;
            g_trades[g_trade_count].stop_loss=pos.stop_loss;
            g_trades[g_trade_count].take_profit=pos.take_profit;
            g_trades[g_trade_count].return_r=rr;
            g_trades[g_trade_count].pnl=pnl;
            g_trades[g_trade_count].exit_reason=reason;
            g_trade_count++;
           }
         
         Print(StringFormat("[MITEM] %s @%.5f R=%.3f $%.2f #trade=%d",reason,slipped,rr,pnl,g_trade_count));
         g_last_trade_won=(rr>0);
         g_trail.Reset();
        }
     }
   
   //--- ENTRY GATE ---
   if(g_trail.IsOpen()) return;
   if(g_paused) return;
   if(g_bars_seen<(long)InpWarmupCandles) return;
   if(g_cooldown>0) return;
   if(g_vol.ATR()<=0) return;
   
   //--- Generate signal
   string signal_type="";
   int direction=GenerateSignal(signal_type);
   if(direction==0) return;
   
   //--- Calculate entry, SL, TP using ATR
   double entry=bar.close;
   double atr_val=g_vol.ATR();
   double sd=InpAtrStopMult*atr_val;
   double td=InpAtrTargetMult*atr_val;
   
   //--- Sanity check: stop must be reasonable
   double max_stop=entry*0.02;  // max 2% of price
   if(sd>max_stop) sd=max_stop;
   if(sd<atr_val*0.5) sd=atr_val*0.5;  // min 0.5 ATR
   
   double sl,tp;
   if(direction>0) { sl=entry-sd; tp=entry+td; }
   else            { sl=entry+sd; tp=entry-td; }
   
   double rr=td/sd;
   if(rr<InpMinTargetRR) return;
   
   //--- Risk sizing
   double risk_pct=InpRiskPerTrade;
   if(g_consec_loss>=2) risk_pct*=0.7;  // reduce after losses
   if(g_consec_win>=3) risk_pct*=1.2;   // increase after wins (but cap)
   risk_pct=MathMin(risk_pct,0.10);     // max 10% per trade
   risk_pct=MathMax(risk_pct,0.01);     // min 1% per trade
   
   double stake=g_equity*risk_pct;
   
   //--- Execute trade
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
      req.comment="MITEM_v13";
      if(!OrderSend(req,res))
        { Print("[MITEM] ORDER FAIL:",res.retcode,"-",res.comment); g_cooldown=InpCoolDownBars; return; }
      stake=res.volume*SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE)
            *(td/SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
     }
   
   g_trail.OpenPosition(direction,entry,sl,tp,bar.time+InpBarSec,stake);
   if(InpDrawSignals) DrawSignal(direction,bar.time+InpBarSec,entry,direction>0?"BUY":"SELL");
   
   Print(StringFormat("[MITEM] %s %s @%.5f SL=%.5f TP=%.5f RR=%.2f ATR=%.4f $%.2f",
                      signal_type,direction>0?"BUY":"SELL",entry,sl,tp,rr,atr_val,stake));
  }

//+------------------------------------------------------------------+
//| OnInit — with HISTORICAL PRELOAD                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[MITEM] === MITEMSHUB AI v13 starting ===");
   g_equity = AccountInfoDouble(ACCOUNT_BALANCE);
   g_peak_equity = g_equity;
   Print(StringFormat("[MITEM] Account balance: $%.2f", g_equity));
   g_agg.Reset(InpBarSec);
   if(InpDrawDashboard) DashCreate();
   
   //--- HISTORICAL PRELOAD
   g_preloading=true;
   int preload=MathMax(InpWarmupCandles*3,500);
   ENUM_TIMEFRAMES tf=TfFromBarSec(InpBarSec);
   MqlRates rates[];
   int got=CopyRates(_Symbol,tf,0,preload,rates);
   if(got>0)
     {
      Print(StringFormat("[MITEM] PRELOAD: %d historical %s bars",got,EnumToString(tf)));
      for(int i=got-1;i>=0;i--)
        {
         AggregatedBar ab;
         ab.open=rates[i].open; ab.high=rates[i].high;
         ab.low=rates[i].low; ab.close=rates[i].close;
         ab.time=rates[i].time;
         ProcessOneBar(ab);
        }
      g_preloading=false;
      Print(StringFormat("[MITEM] PRELOAD done: bars=%I64d ATR=%.6f",g_bars_seen,g_vol.ATR()));
     }
   else
     { g_preloading=false; Print("[MITEM] PRELOAD: CopyRates failed"); }
   
   int strat=GetStrategy();
   Print(StringFormat("[MITEM] Strategy: %s | SL=%.1f ATR | TP=%.1f ATR | Risk=%.0f%% | Trail=%s | Live=%s",
                      strat==1?"SMA50 Fade":"Mom Exhaust",
                      InpAtrStopMult,InpAtrTargetMult,InpRiskPerTrade*100,
                      InpTrailOn?"ON":"OFF",InpLiveExecution?"LIVE":"PAPER"));
   if(strat==1)
     Print(StringFormat("[MITEM] SMA50: dist_thresh=%.1f%% RSI_confirm=%s BB=%s Trend=%s",
                        InpSmaDistPct,InpUseRsiConfirm?"ON":"OFF",
                        InpUseBbFilter?"ON":"OFF",InpUseTrendFilter?"ON":"OFF"));
   if(strat==2)
     Print(StringFormat("[MITEM] MOM: consec=%d RSI_confirm=%s BB=%s Trend=%s",
                        InpConsecBars,InpUseRsiConfirm?"ON":"OFF",
                        InpUseBbFilter?"ON":"OFF",InpUseTrendFilter?"ON":"OFF"));
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
   for(int i=0;i<22;i++) ObjectDelete(0,g_dl[i]);
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
   Print("[MITEM] === SESSION SUMMARY ===");
   Print(StringFormat("[MITEM] trades=%d wr=%.1f%% R=%+.3f",g_trade_count,wr,total_r));
   Print(StringFormat("[MITEM] exits: stop=%d target=%d time=%d",ns,nt,ntm));
   Print(StringFormat("[MITEM] equity=$%.2f peak=$%.2f dd=%.2f%%",g_equity,g_peak_equity,dd));
   Print("[MITEM] === END ===");
   Print("========================================");
  }

ENUM_TIMEFRAMES TfFromBarSec(int bs)
  {
   if(bs<=60) return PERIOD_M1;
   if(bs<=300) return PERIOD_M5;
   if(bs<=900) return PERIOD_M15;
   if(bs<=3600) return PERIOD_H1;
   return PERIOD_H4;
  }
//+------------------------------------------------------------------+
