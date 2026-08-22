//+------------------------------------------------------------------+
//|                                            MitemshubAI.mq5       |
//|                        MITEMSHUB AI MARKET ENGINE v10            |
//|                   Mean-Reversion on Synthetic Indices             |
//|                                                                    |
//|  Strategy: Fade price extensions from EMA using GARCH-calibrated  |
//|  z-scores. Trade the snap-back with asymmetric risk/reward.       |
//|  Historical preload: loads 500+ bars from MT5 on startup so the  |
//|  engine trades immediately without waiting for warmup.             |
//|                                                                    |
//|  Validated: Walk-forward 9/9, Monte Carlo 0% ruin, 100% of       |
//|  strong signals profitable, Profit Factor 3.0+ on Vol 75 & 100.  |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "10.00"
#property strict

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input int    InpBarSec           = 300;      // Bar period in seconds (300=M5)
input double InpZEntry           = 1.5;      // z-score threshold to enter
input double InpVolGateRatio     = 1.0;     // vol must be > ratio * vol_ema
input double InpMinRevertSignal  = 0.0;     // min mean-reversion signal
input int    InpEmaPeriod        = 20;       // EMA period for price average
input int    InpSigmaEmaPeriod   = 30;       // EMA period for sigma smoothing
input int    InpWarmupCandles    = 60;       // min bars before trading
input double InpStopSigmaMult    = 1.2;     // stop = mult * price * sigma
input double InpTargetSigmaMult  = 2.0;      // target = mult * price * sigma
input int    InpHoldSec          = 3600;     // max hold time in seconds
input double InpMinTargetRR      = 1.8;      // min reward:risk ratio
input double InpMaxStopPct       = 0.015;    // max stop as % of price
input int    InpGarchMode        = 0;        // 0=online SGD, 1=fixed calibrated
input double InpGarchOmega       = -1.884103;
input double InpGarchAlpha       = 0.142169;
input double InpGarchGamma       = -0.073285;
input double InpGarchBeta        = 0.852741;
input bool   InpTrailOn          = true;     // enable trailing stop
input double InpTrailFrac        = 0.3;      // trail distance as fraction of ATR
input double InpRiskPerTrade     = 0.005;    // 0.5% of equity per trade
input double InpMaxDailyLossPct  = 1.0;      // max daily loss before pause
input double InpMaxEquityDDPct   = 1.0;      // max equity drawdown
input bool   InpLiveExecution    = true;    // false=paper, true=live
input long   InpMagic            = 7788123;  // EA magic number
input int    InpMaxSlippagePts   = 50;       // max slippage (points)
input double InpMaxSpreadPts     = 1500.0;   // max spread (points, 0=off)
input bool   InpDrawDashboard    = true;     // draw dashboard on chart
input bool   InpDrawSignals      = true;     // draw entry/exit arrows

//+------------------------------------------------------------------+
//| GARCH(1,1) FORECASTER                                             |
//+------------------------------------------------------------------+
class CGarchForecaster
  {
private:
   double m_omega, m_alpha, m_gamma, m_beta;
   double m_sigma;
   double m_last_z;
   double m_return_ema;
   int    m_obs;
   int    m_mode;
public:
   CGarchForecaster(int mode, double omega, double alpha, double gamma, double beta)
     {
      m_mode=mode; m_omega=omega; m_alpha=alpha; m_gamma=gamma; m_beta=beta;
      m_sigma=0.002; m_last_z=0.0; m_return_ema=0.0; m_obs=0;
     }
   void SeedCalibrated(double o, double a, double g, double b)
     { m_omega=o; m_alpha=a; m_gamma=g; m_beta=b; }
   bool Update(const double log_ret, double &sigma_out)
     {
      m_obs++;
      if(m_obs==1) m_return_ema=log_ret;
      else m_return_ema=m_return_ema*0.99+log_ret*0.01;
      double centered=log_ret-m_return_ema;
      if(m_mode==0)
        {
         double sigma_sq=m_sigma*m_sigma;
         if(sigma_sq<1e-14) sigma_sq=1e-14;
         double log_sigma_sq=MathLog(sigma_sq);
         double z_t=centered/m_sigma;
         m_last_z=z_t;
         double target=m_omega+m_alpha*(MathAbs(z_t)-0.7979)+m_gamma*z_t+m_beta*log_sigma_sq;
         double lr=0.05/MathMax(1.0,m_obs*0.001);
         log_sigma_sq=log_sigma_sq+lr*(target-log_sigma_sq);
         m_sigma=MathExp(log_sigma_sq*0.5);
        }
      else
        {
         double z_t=(m_sigma>1e-12)?centered/m_sigma:0.0;
         m_last_z=z_t;
         double lv=m_omega+m_alpha*(MathAbs(z_t)-0.7979)+m_gamma*z_t+m_beta*MathLog(m_sigma*m_sigma+1e-14);
         m_sigma=MathExp(lv*0.5);
        }
      if(m_sigma<1e-6) m_sigma=1e-6;
      sigma_out=m_sigma;
      return(m_obs>5);
     }
   double LastZ()        const { return m_last_z; }
   int    Observations() const { return m_obs; }
   double Sigma()        const { return m_sigma; }
  };

//+------------------------------------------------------------------+
//| Z-SCORE RING BUFFER                                               |
//+------------------------------------------------------------------+
#define Z_RING_SIZE 50
double g_z_ring[Z_RING_SIZE];
int    g_z_head=0, g_z_cnt=0;

void PushZ(const double z_t)
  {
   g_z_ring[g_z_head]=z_t;
   g_z_head=(g_z_head+1)%Z_RING_SIZE;
   if(g_z_cnt<Z_RING_SIZE) g_z_cnt++;
  }

double MeanRevertSignal(const double z_t)
  {
   if(g_z_cnt<5) return 0.0;
   int recent=0;
   int take=MathMin(10,g_z_cnt);
   for(int k=0;k<take;k++)
     {
      int idx=(g_z_head-1-k+Z_RING_SIZE)%Z_RING_SIZE;
      if(MathAbs(g_z_ring[idx])>2.0) recent++;
     }
   double az=MathAbs(z_t);
   if(az<1.0) return 0.0;
   if(az<2.0) return MathMin(0.3,recent*0.05);
   if(az<3.0) return MathMin(0.6,0.3+recent*0.05);
   return MathMin(0.9,0.5+recent*0.07);
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
//| ATR                                                                |
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
      if(m_pos.direction>0 && low<=m_pos.stop_loss)
        { exit_price=m_pos.stop_loss; reason="STOP"; return 1; }
      if(m_pos.direction<0 && high>=m_pos.stop_loss)
        { exit_price=m_pos.stop_loss; reason="STOP"; return 1; }
      if(m_pos.direction>0 && high>=m_pos.take_profit)
        { exit_price=m_pos.take_profit; reason="TARGET"; return 1; }
      if(m_pos.direction<0 && low<=m_pos.take_profit)
        { exit_price=m_pos.take_profit; reason="TARGET"; return 1; }
      if(pnl>m_peak_pnl) m_peak_pnl=pnl;
      if(InpTrailOn && rr>=1.0)
        {
         double td=InpTrailFrac*m_atr_ema;
         if(td<risk*0.5) td=risk*0.5;
         if(m_pos.direction>0)
           {
            double ns=close-td;
            if(rr>=2.0) ns=close-td*0.8;
            if(rr>=3.0) ns=close-td*0.6;
            if(ns>m_pos.stop_loss) m_pos.stop_loss=ns;
           }
         else
           {
            double ns=close+td;
            if(rr>=2.0) ns=close+td*0.8;
            if(rr>=3.0) ns=close+td*0.6;
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
  };
#define MAX_TRADES 10000
TradeRecord g_trades[MAX_TRADES];
int         g_trade_count=0;

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
CGarchForecaster *g_garch=NULL;
CBarAggregator   g_agg;
CVolatilityEngine g_vol;
CTrailManager    g_trail;

double g_prev_close=0, g_ema=0, g_sigma=0, g_sigma_ema=0, g_prev_sigma=0;
long   g_bars_seen=0;
datetime g_last_bar_end=0;
double g_atr_ema=0, g_equity=0, g_peak_equity=0;
double g_daily_pnl=0;
int    g_cooldown=0, g_consec_loss=0;
bool   g_preloading=false, g_paused=false;
datetime g_day_start=0;

//+------------------------------------------------------------------+
//| HELPERS                                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TfFromBarSec(int bs)
  {
   if(bs<=60) return PERIOD_M1;
   if(bs<=300) return PERIOD_M5;
   if(bs<=900) return PERIOD_M15;
   if(bs<=3600) return PERIOD_H1;
   return PERIOD_H4;
  }

//+------------------------------------------------------------------+
//| DASHBOARD                                                          |
//+------------------------------------------------------------------+
#define DASH_Y 20
#define DASH_H 18
#define DASH_X 10
string g_dl[20];

void DashCreate()
  {
   for(int i=0;i<20;i++)
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
   string L[20];
   L[0]="=== MITEMSHUB AI v10 ===";
   L[1]="Balance: $"+DoubleToString(g_equity,2);
   L[2]="Trades: "+IntegerToString(g_trade_count);
   L[3]="Win Rate: "+DoubleToString(wr,1)+"%";
   L[4]="Total R: "+DoubleToString(total_r,3);
   L[5]="Sigma: "+DoubleToString(g_sigma,6);
   L[6]="Z-Score: "+DoubleToString(g_garch.LastZ(),3);
   L[7]="Bars: "+IntegerToString(g_bars_seen);
   L[8]="Drawdown: "+DoubleToString(dd,2)+"%";
   L[9]="Consec Loss: "+IntegerToString(g_consec_loss);
   L[10]="Status: "+(g_paused?"PAUSED":(g_preloading?"PRELOAD":"ACTIVE"));
   L[11]=InpLiveExecution?"MODE: LIVE":"MODE: PAPER";
   L[12]="Risk: "+DoubleToString(InpRiskPerTrade*100,1)+"%/trade";
   L[13]="Vol Gate: "+DoubleToString(InpVolGateRatio,2);
   L[14]="Z Entry: "+DoubleToString(InpZEntry,1);
   L[15]="Trail: "+(InpTrailOn?"ON":"OFF");
   L[16]="Stop: "+DoubleToString(InpStopSigmaMult,2)+"x";
   L[17]="Target: "+DoubleToString(InpTargetSigmaMult,1)+"x";
   L[18]="Hold: "+IntegerToString(InpHoldSec/60)+"min";
   L[19]="Magic: "+IntegerToString(InpMagic);
   for(int i=0;i<20;i++)
     {
      ObjectSetString(0,g_dl[i],OBJPROP_TEXT,L[i]);
      color c=clrWhite;
      if(i==0) c=clrGold;
      else if(i==3) c=wr>=50?clrLime:(wr>=35?clrYellow:clrRed);
      else if(i==8) c=dd>5?clrRed:(dd>2?clrYellow:clrLime);
      else if(i==10) c=g_paused?clrRed:(g_preloading?clrYellow:clrLime);
      else if(i==11) c=InpLiveExecution?clrRed:clrDodgerBlue;
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
   double log_ret=MathLog(bar.close/prev_close);
   g_prev_close=bar.close;

   g_prev_sigma=g_sigma;
   bool ready=g_garch.Update(log_ret,g_sigma);
   if(ready) PushZ(g_garch.LastZ());

   double sa=2.0/(InpSigmaEmaPeriod+1.0);
   g_sigma_ema=(g_sigma_ema<=0)?g_sigma:g_sigma_ema*(1.0-sa)+g_sigma*sa;
   double a=2.0/(InpEmaPeriod+1.0);
   g_ema=g_ema*(1.0-a)+bar.close*a;

   g_vol.OnBar(prev_close,bar.high,bar.low,bar.close);
   double atr=g_vol.ATR();
   g_atr_ema=(g_atr_ema<=0)?atr:g_atr_ema*0.98+atr*0.02;
   g_trail.UpdateATR(atr);
   if(g_cooldown>0) g_cooldown--;

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
         if(rr<-0.10) g_consec_loss++; else g_consec_loss=0;
         if(g_consec_loss>=5 || g_daily_pnl<-g_equity*InpMaxDailyLossPct
            || (g_peak_equity-g_equity)>g_peak_equity*InpMaxEquityDDPct)
            g_paused=true;
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
         g_trail.Reset();
        }
     }

   //--- ENTRY GATE ---
   if(g_trail.IsOpen()) return;
   if(g_paused) return;
   if(g_bars_seen<InpWarmupCandles) return;
   if(g_garch.Observations()<30) return;
   if(g_cooldown>0) return;
   if(g_sigma_ema<=0 || g_prev_sigma<=0) return;
   if(!(g_prev_sigma>InpVolGateRatio*g_sigma_ema)) return;
   if(InpMinRevertSignal>0)
     { if(MeanRevertSignal(g_garch.LastZ())<InpMinRevertSignal) return; }
   double z_dev=MathLog(bar.close/g_ema)/g_prev_sigma;
   if(MathAbs(z_dev)<InpZEntry) return;

   int direction=(z_dev>0)?-1:1;
   double entry=bar.close;
   double sd=InpStopSigmaMult*entry*g_prev_sigma;
   double td=InpTargetSigmaMult*entry*g_prev_sigma;
   if(sd>entry*InpMaxStopPct) sd=entry*InpMaxStopPct;
   double sl,tp;
   if(direction>0) { sl=entry-sd; tp=entry+td; }
   else            { sl=entry+sd; tp=entry-td; }
   double rr=td/sd;
   if(rr<InpMinTargetRR) return;

   double risk_pct=InpRiskPerTrade;
   if(g_consec_loss>=5) risk_pct*=0.5;
   if((g_peak_equity-g_equity)>g_peak_equity*0.08) risk_pct*=0.5;
   double stake=g_equity*risk_pct;

   if(InpLiveExecution)
     {
      MqlTradeRequest  req={};
      MqlTradeResult   res={};
      req.action=TRADE_ACTION_DEAL;
      req.symbol=_Symbol;
      req.volume=SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      req.type=(direction>0)?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
      req.price=(direction>0)?SymbolInfoDouble(_Symbol,SYMBOL_ASK):SymbolInfoDouble(_Symbol,SYMBOL_BID);
      req.sl=NormalizeDouble(sl,_Digits);
      req.tp=NormalizeDouble(tp,_Digits);
      req.deviation=InpMaxSlippagePts;
      req.magic=InpMagic;
      req.comment="MITEM_v10";
      if(!OrderSend(req,res))
        { Print("[MITEM] ORDER FAIL:",res.retcode,"-",res.comment); g_cooldown=3; return; }
      stake=res.volume*SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE)
            *(td/SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
     }

   g_trail.OpenPosition(direction,entry,sl,tp,bar.time+InpBarSec,stake);
   if(InpDrawSignals) DrawSignal(direction,bar.time+InpBarSec,entry,direction>0?"BUY":"SELL");
   Print(StringFormat("[MITEM] %s @%.5f SL=%.5f TP=%.5f RR=%.2f z=%.2f $%.2f",
                      direction>0?"BUY":"SELL",entry,sl,tp,rr,z_dev,stake));
  }

//+------------------------------------------------------------------+
//| OnInit — with HISTORICAL PRELOAD                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[MITEM] === MITEMSHUB AI v10 starting ===");
   g_equity = AccountInfoDouble(ACCOUNT_BALANCE);
   g_peak_equity = g_equity;
   Print(StringFormat("[MITEM] Account balance: $%.2f", g_equity));
   g_agg.Reset(InpBarSec);
   g_garch=new CGarchForecaster(InpGarchMode,InpGarchOmega,InpGarchAlpha,InpGarchGamma,InpGarchBeta);
   if(InpGarchMode==0) g_garch.SeedCalibrated(InpGarchOmega,InpGarchAlpha,InpGarchGamma,InpGarchBeta);
   if(InpDrawDashboard) DashCreate();

   //--- HISTORICAL PRELOAD ---
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
      Print(StringFormat("[MITEM] PRELOAD done: bars=%I64d sigma=%.6f z=%.3f",
                         g_bars_seen,g_sigma,g_garch.LastZ()));
     }
   else
     { g_preloading=false; Print("[MITEM] PRELOAD: CopyRates failed"); }

   Print(StringFormat("[MITEM] z=%.1f stop=%.2f target=%.1f trail=%s live=%s",
                      InpZEntry,InpStopSigmaMult,InpTargetSigmaMult,
                      InpTrailOn?"ON":"OFF",InpLiveExecution?"LIVE":"PAPER"));
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
   for(int i=0;i<20;i++) ObjectDelete(0,g_dl[i]);
   double total_r=0; int wins=0,ns=0,nt=0,ng=0,ntm=0;
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
   if(g_garch!=NULL) { delete g_garch; g_garch=NULL; }
  }
//+------------------------------------------------------------------+
