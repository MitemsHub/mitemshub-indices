//+------------------------------------------------------------------+
//|                                    MitemshubAI_v22_1.mq5         |
//|                     MITEMSHUB AI MULTI-STRATEGY ENGINE v22.1     |
//|   Cleaned • Regime-Aware • 5 Core Strategies • Active & Safer    |
//|                                                                  |
//| v22.0 FIXES (2026-08-25):                                        |
//|  1. Consecutive-loss PAUSE now auto-resets on session-day        |
//|     rollover (was a permanent latch — the #1 opportunity killer).|
//|  2. Daily-loss halt actually wired (input existed, never used).  |
//|  3. Effective-risk guardrail: refuse entries whose min-lot risk  |
//|     breaches InpMaxEffectiveRiskPct of equity.                   |
//|  4. Band-fade leg added — the walk-forward VALIDATED edge        |
//|     (fade |z|>=2 sigma extensions during vol expansion;          |
//|     stop=0.10xsigma_h, target=0.80xsigma_h on R_100).            |
//|  5. Momentum demoted to confluence vote — a lone big candle no   |
//|     longer triggers an entry (fixed chase-top/bottom bleed).     |
//|  6. Entry/regime timeframe overrides (run M15 exec off an H1 chart)|
//|  7. TELEMETRY journal: per-bar z_dev + sigma-expansion ratio +     |
//|     fired-legs, written as JSONL to MQL5\Files\                    |
//|     MitemshubAI_v22_telemetry.jsonl (+ live dashboard row) —       |
//|     future Python replays read REAL EA values, no feature proxies. |
//|  8. ACCOUNT-WIDE EXPOSURE GUARD: sums open risk across ALL fleet   |
//|     magics and blocks new entries above InpMaxTotalRiskPct of      |
//|     equity — multi-chart safety on small accounts.                 |
//+------------------------------------------------------------------+
#property copyright "MITEMSHUB AI"
#property version   "22.10"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

#define TELEM_FILE "MitemshubAI_v22_telemetry.jsonl"   // JSONL journal, lands in MQL5\Files (Tester: tester Files dir)

//+------------------------------------------------------------------+
//| ENUMS                                                              |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Strategy Selection ==="
input bool   InpUsePullback      = true;     // EMA Pullback (Trend)
input bool   InpUseBreakout      = true;     // Breakout
input bool   InpUseMomentum      = true;     // Momentum
input bool   InpUseMeanRevert    = true;     // Mean Reversion (Ranging only)
input bool   InpUseBandFade      = true;     // Band Fade (VALIDATED: fade |z|>=2 sigma extensions)
input int    InpMinScore         = 3;        // Minimum score to enter
input bool   InpRequire2Strats   = false;    // Require at least 2 strategies agree
input bool   InpMomentumStandalone = false;  // Allow a momentum candle ALONE to trigger entry

input group "=== Regime & Volatility ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input double InpMinEmaSep        = 0.22;
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 120;
input double InpAtrLowPct        = 8.0;
input double InpAtrHighPct       = 90.0;

input group "=== Strategy Parameters ==="
input double InpPullbackMin      = 0.30;
input double InpPullbackMax      = 2.20;
input double InpBreakoutBuffer   = 0.10;
input int    InpBreakoutBars     = 12;
input double InpMomBodyMin       = 0.45;
input double InpRsiOversold      = 32.0;
input double InpRsiOverbought    = 68.0;

input group "=== Band Fade (validated edge) ==="
input double InpBandZEntry       = 2.0;      // |z_dev| fade trigger (R_75/R_100 optimized)
input double InpBandVolExtRatio  = 1.25;     // sigma must exceed this x sigma EMA baseline
input int    InpBandSigmaEmaLen  = 30;       // sigma baseline EMA length (bars)
input double InpBandStopSigmaMult  = 0.10;   // stop   = 0.10 x sigma_h (validated)
input double InpBandTargetSigmaMult= 0.80;   // target = 0.80 x sigma_h (R_100; R_75 use 1.20)
input int    InpBandHoldSec      = 3600;     // band hold horizon (seconds)
input double InpBandMinRR        = 2.5;      // min reward:risk for band plans
input double InpBandMaxStopPct   = 0.015;    // reject band plan if stop > 1.5% of price

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.005;    // TARGET risk fraction (min-lot floor may force more)
input double InpMaxEffectiveRiskPct = 30.0;  // HARD CAP: skip entry if real min-lot risk > this % of equity
input double InpMaxTotalRiskPct  = 15.0;     // ACCOUNT GUARD: max SUMMED open risk (all fleet magics) as % of equity
input string InpFleetMagicsCSV   = "7788010,7788025,7788050,7788075,7788100"; // Fleet magics for the account-wide guard (no spaces)
input double InpTpMult           = 2.4;
input int    InpMaxHoldBars      = 14;
input double InpMaxDailyLossPct  = 0.03;
input int    InpMaxConsecLoss    = 3;
input int    InpCoolDownBars     = 3;
input bool   InpUseTrailing      = true;
input double InpTrailStartR      = 1.0;
input double InpTrailDistR       = 0.9;
input bool   InpUseBreakeven     = true;
input double InpBeTriggerR       = 1.0;

input group "=== Execution ==="
input string InpEntryTFOverride  = "CURRENT"; // Entry timeframe: CURRENT,M1,M5,M15,M30,H1,H4,D1
input string InpRegimeTFOverride = "CURRENT"; // Regime timeframe (default = one step above entry)
input long   InpMagic            = 7788211;
input int    InpMaxSlippagePts   = 50;
input int    InpWarmupBars       = 250;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;
input int    InpMaxTradesPerDay  = 9999; // No daily trade cap

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES g_tf_entry, g_tf_regime;
int hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;
int hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E, hBB_E;

double g_eq=0, g_peak_eq=0, g_daily_pnl=0;
datetime g_day_start=0;
double g_day_start_eq=0;              // session-day equity baseline (daily-loss halt)
int g_cooldown=0, g_consec_loss=0, g_trades_today=0;
bool g_paused=false;                  // consecutive-loss pause — AUTO-RESETS next session day
ENUM_REGIME g_regime = REGIME_NO_TRADE;

// band-fade state
double g_sigma_ema=0;                 // EMA baseline of per-bar close-to-close sigma
bool   g_sigma_init=false;

// v22 TELEMETRY (refreshed once per closed entry-TF bar; journaled per decision)
double g_sigma_now=0;                 // last closed-bar per-bar sigma (log-return stdev)
double g_z_dev=0;                     // z-deviation of close vs its 20-bar SMA (in sigmas)
double g_exp_ratio=0;                 // g_sigma_now / g_sigma_ema (>1 = vol expanding)
string g_fired_legs="";               // fired legs of last evaluation, e.g. "MOM-|MR-|BF+"
string g_last_skip="";                // why the last evaluated signal did not trade

// per-signal exit geometry (set by the winning strategy leg)
bool   g_sig_is_band=false;
int    g_last_band_dir=0;             // direction band-fade actually fired (guards geometry)
double g_sig_sl_atr=0, g_sig_tp_atr=0; // stop/target distances in ATR units (band leg)
double g_risk_money=0;                // effective $ risk at entry (daily P&L accounting)
int    g_max_hold=14;                 // per-trade hold limit (band trades use their own horizon)

int g_trades=0, g_wins=0, g_losses=0;
int g_target_exits=0, g_time_exits=0, g_stop_exits=0;
double g_total_r=0;

ulong g_ticket=0;
int g_dir=0;
double g_entry=0, g_sl=0, g_tp=0, g_orig_risk=0, g_position_volume=0;
datetime g_entry_time=0;
int g_bars_held=0;

double atr_hist[];
int atr_hist_count=0;
string dash_names[24];

// account-wide exposure guard
long g_fleet_magics[];
int    g_fleet_n=0;

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES tf)
{
   // Regime timeframe = roughly one structural step above the entry TF
   switch(tf)
   {
      case PERIOD_M1:  return PERIOD_M5;
      case PERIOD_M5:  return PERIOD_M30;
      case PERIOD_M15: return PERIOD_H1;
      case PERIOD_M30: return PERIOD_H4;
      case PERIOD_H1:  return PERIOD_H4;
      case PERIOD_H4:  return PERIOD_D1;
      default:         return PERIOD_D1;
   }
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_tf_entry  = ParseTF(InpEntryTFOverride, (ENUM_TIMEFRAMES)Period());
   ENUM_TIMEFRAMES regParsed = ParseTF(InpRegimeTFOverride, PERIOD_CURRENT);
   g_tf_regime = (regParsed == PERIOD_CURRENT) ? GetRegimeTF(g_tf_entry) : regParsed;

   hEMA_Fast_R = iMA(_Symbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_R  = iMA(_Symbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_R = iMA(_Symbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Fast_E = iMA(_Symbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_E  = iMA(_Symbol, g_tf_entry, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_E = iMA(_Symbol, g_tf_entry, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_E      = iRSI(_Symbol, g_tf_entry, 14, PRICE_CLOSE);
   hATR_E      = iATR(_Symbol, g_tf_entry, InpAtrPeriod);
   hBB_E       = iBands(_Symbol, g_tf_entry, 20, 0, 2.0, PRICE_CLOSE);

   if(hEMA_Fast_R==INVALID_HANDLE || hEMA_Mid_R==INVALID_HANDLE || hEMA_Slow_R==INVALID_HANDLE ||
      hEMA_Fast_E==INVALID_HANDLE || hEMA_Mid_E==INVALID_HANDLE || hEMA_Slow_E==INVALID_HANDLE ||
      hRSI_E==INVALID_HANDLE || hATR_E==INVALID_HANDLE || hBB_E==INVALID_HANDLE)
   {
      Print("v22: Handle failed");
      return INIT_FAILED;
   }

   ArrayResize(atr_hist, InpAtrLookback+30);
   ArrayInitialize(atr_hist, 0);

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;
   g_day_start_eq = g_eq;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);

   // parse fleet magics for the account-wide exposure guard
   {
      string parts[];
      g_fleet_n = StringSplit(InpFleetMagicsCSV, ',', parts);
      ArrayResize(g_fleet_magics, MathMax(1, g_fleet_n));
      int k=0;
      for(int i=0;i<g_fleet_n;i++)
         if(parts[i] != "")
            g_fleet_magics[k++] = (long)StringToInteger(parts[i]);
      g_fleet_n = k;
   }

   RecoverPosition();
   if(InpDrawDashboard) CreateDashboard();

   Print("[v22.1] MITEMSHUB AI v22.1 started | 5 Core Strategies (band-fade primary) | Regime-Aware");
   PrintFormat("[v22.1] Entry TF=%s | Regime TF=%s | Band=%s | MomStandalone=%s | MinScore=%d | RiskCap=%.0f%% | AcctGuard=%.0f%%",
               EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpUseBandFade ? "ON" : "OFF", InpMomentumStandalone ? "YES" : "NO",
               InpMinScore, InpMaxEffectiveRiskPct, InpMaxTotalRiskPct);
   if(InpMaxEffectiveRiskPct > 10.0)
      Print("[v22] WARNING: risk cap > 10% of equity per trade — tiny-account mode. Fund the account or drop to a lower-vol symbol ASAP.");
   Print("[v22.1] Telemetry journal -> MQL5\\Files\\", TELEM_FILE);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_R); IndicatorRelease(hEMA_Mid_R); IndicatorRelease(hEMA_Slow_R);
   IndicatorRelease(hEMA_Fast_E); IndicatorRelease(hEMA_Mid_E); IndicatorRelease(hEMA_Slow_E);
   IndicatorRelease(hRSI_E); IndicatorRelease(hATR_E); IndicatorRelease(hBB_E);
   for(int i=0;i<24;i++) ObjectDelete(0, dash_names[i]);

   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   PrintFormat("v22 Summary | Trades:%d WR:%.1f%% TotalR:%+.2f", g_trades, wr, g_total_r);
}

//+------------------------------------------------------------------+
void OnTick()
{
   static datetime last_bar=0;
   datetime cur = iTime(_Symbol, g_tf_entry, 0);
   if(cur == last_bar) { if(InpDrawDashboard) UpdateDashboard(); return; }
   last_bar = cur;

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_eq > g_peak_eq) g_peak_eq = g_eq;

   datetime ds = TimeCurrent() - (TimeCurrent()%86400);
   if(ds != g_day_start)
   {
      g_day_start=ds; g_daily_pnl=0; g_trades_today=0;
      g_day_start_eq = g_eq;
      if(g_paused)
      {
         g_paused=false; g_consec_loss=0;
         Print("[v22] New session day — consecutive-loss PAUSE lifted (counters reset)");
      }
   }

   if(g_cooldown>0) g_cooldown--;

   if(g_ticket>0)
   {
      if(PositionSelectByTicket(g_ticket)) ManagePosition();
      else g_ticket=0;
   }

   UpdateSigmaBaseline();
   UpdateBandTelemetry();   // measure z_dev / expansion ratio BEFORE evaluating signals

   if(g_ticket==0 && !g_paused && g_cooldown==0 && !DailyLossHalted() &&
      Bars(_Symbol,g_tf_entry) >= InpWarmupBars)
   {
      string sig="";
      int dir = GenerateSignal(sig);
      if(dir != 0) OpenTrade(dir, sig);
   }
   else if(g_ticket==0 && (g_paused || g_cooldown>0 || DailyLossHalted()))
   {
      // Log why we're not trading (once per bar)
      if(g_paused) Print("[v22] PAUSED — consecutive-loss breaker; auto-resets next session day");
      if(g_cooldown>0) PrintFormat("[v22] COOLDOWN %d bars left", g_cooldown);
      if(DailyLossHalted()) Print("[v22] DAILY-HALT — daily loss limit; resets next session day");
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
void RecoverPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      g_ticket=t;
      g_dir = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1;
      g_entry=PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl=PositionGetDouble(POSITION_SL);
      g_tp=PositionGetDouble(POSITION_TP);
      g_orig_risk=MathAbs(g_entry-g_sl);
      g_position_volume=PositionGetDouble(POSITION_VOLUME);
      g_entry_time=(datetime)PositionGetInteger(POSITION_TIME);
      g_bars_held=0;
      break;
   }
}

//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Parse a timeframe override string ("CURRENT" -> fallback).       |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES ParseTF(const string s, const ENUM_TIMEFRAMES fallback)
{
   string t = s;
   StringToUpper(t);
   if(t=="CURRENT" || t=="") return fallback;
   if(t=="M1")  return PERIOD_M1;
   if(t=="M5")  return PERIOD_M5;
   if(t=="M15") return PERIOD_M15;
   if(t=="M30") return PERIOD_M30;
   if(t=="H1")  return PERIOD_H1;
   if(t=="H4")  return PERIOD_H4;
   if(t=="D1")  return PERIOD_D1;
   Print("[v22] Unknown TF override '", s, "' — using fallback");
   return fallback;
}

//+------------------------------------------------------------------+
//| Per-bar close-to-close sigma (sample stdev of log returns over   |
//| `lookback` closed bars of the ENTRY timeframe).                  |
//+------------------------------------------------------------------+
double PerBarSigma(const int lookback)
{
   int n = MathMax(3, lookback);
   if(Bars(_Symbol, g_tf_entry) < n+2) return 0.0;
   double sum=0, sum2=0;
   for(int i=1; i<=n; i++)
   {
      double c0 = iClose(_Symbol, g_tf_entry, i);
      double c1 = iClose(_Symbol, g_tf_entry, i+1);
      if(c0<=0 || c1<=0) return 0.0;
      double r = MathLog(c0/c1);
      sum += r; sum2 += r*r;
   }
   double mean = sum/n;
   double sq = sum2 - n*mean*mean;
   if(sq <= 0) return 0.0;
   return MathSqrt(sq/(n-1));
}

//+------------------------------------------------------------------+
//| Update the sigma EMA baseline once per new bar (band-fade gate). |
//+------------------------------------------------------------------+
void UpdateSigmaBaseline()
{
   double sig = PerBarSigma(20);
   if(sig <= 0) return;
   if(!g_sigma_init){ g_sigma_ema=sig; g_sigma_init=true; return; }
   double a = 2.0/(InpBandSigmaEmaLen+1.0);
   g_sigma_ema = a*sig + (1.0-a)*g_sigma_ema;
}

//+------------------------------------------------------------------+
//| Per-closed-bar band TELEMETRY: z-deviation & expansion ratio.    |
//| Runs once per new entry-TF bar BEFORE strategy evaluation so     |
//| every decision (and the dashboard) carries real measured values  |
//| — future replays read these exact numbers, no proxies needed.    |
//+------------------------------------------------------------------+
void UpdateBandTelemetry()
{
   g_sigma_now=PerBarSigma(20);
   g_z_dev=0.0; g_exp_ratio=0.0;
   if(g_sigma_now<=0) return;

   double sma=0.0;
   for(int i=1;i<=20;i++) sma += iClose(_Symbol,g_tf_entry,i);
   sma /= 20.0;
   double price=iClose(_Symbol,g_tf_entry,1);
   if(sma<=0 || price<=0) return;

   g_z_dev = MathLog(price/sma)/g_sigma_now;
   if(g_sigma_init && g_sigma_ema>0) g_exp_ratio = g_sigma_now/g_sigma_ema;
}

//+------------------------------------------------------------------+
//| Append one JSON line to the telemetry journal. The file is       |
//| opened/appended/closed per event — safe across restarts and lets |
//| external tools tail it live.                                     |
//+------------------------------------------------------------------+
void Telem(const string type, const string kv)
{
   int h=FileOpen(TELEM_FILE, FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h==INVALID_HANDLE)
   { Print("[v22] telem write failed err=",GetLastError()); return; }
   FileSeek(h,0,SEEK_END);
   FileWriteString(h, StringFormat("{\"ts\":\"%s\",\"epoch\":%I64d,\"type\":\"%s\",%s}\n",
                   TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
                   (long)TimeCurrent(), type, kv));
   FileClose(h);
}

//+------------------------------------------------------------------+
//| ACCOUNT-WIDE EXPOSURE GUARD                                       |
//| Sums current open risk (entry->SL distance valued at tick specs)  |
//| over EVERY position whose magic belongs to the fleet, regardless  |
//| of which chart/EA instance holds it. Positions with no SL are     |
//| skipped (our EAs always carry an SL) but counted separately.      |
//+------------------------------------------------------------------+
bool IsFleetMagic(const long m)
{
   for(int i=0;i<g_fleet_n;i++)
      if(g_fleet_magics[i]==m) return true;
   return false;
}

double FleetOpenRisk(int &no_sl_count)
{
   no_sl_count=0;
   double total=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0 || !PositionSelectByTicket(t)) continue;
      if(!IsFleetMagic((long)PositionGetInteger(POSITION_MAGIC))) continue;
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      string sym   = PositionGetString(POSITION_SYMBOL);
      if(sl<=0){ no_sl_count++; continue; }
      double ts = SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE);
      double tv = SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE);
      if(ts<=0 || tv<=0) continue;
      total += MathAbs(entry-sl)/ts*tv*vol;
   }
   return total;
}

//+------------------------------------------------------------------+
//| Daily-loss halt: freeze NEW entries for the rest of the session  |
//| day once drawdown from the day-start equity baseline breaches    |
//| InpMaxDailyLossPct. Resets automatically at rollover.            |
//+------------------------------------------------------------------+
bool DailyLossHalted()
{
   if(InpMaxDailyLossPct<=0 || g_day_start_eq<=0) return false;
   return ((g_day_start_eq-g_eq)/g_day_start_eq >= InpMaxDailyLossPct);
}

//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1],emaM[1],emaS[1],atr[1];
   if(CopyBuffer(hEMA_Fast_R,0,1,1,emaF)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_R,0,1,1,emaM)<1)  return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_R,0,1,1,emaS)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)       return REGIME_NO_TRADE;

   if(atr_hist_count < ArraySize(atr_hist))
      atr_hist[atr_hist_count++] = atr[0];
   else
   {
      for(int i=0;i<ArraySize(atr_hist)-1;i++) atr_hist[i]=atr_hist[i+1];
      atr_hist[ArraySize(atr_hist)-1]=atr[0];
   }

   double pct = CalcATRPercentile(atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);
   double sep = MathAbs(emaF[0]-emaM[0])/atr[0];

   if(emaF[0]>emaM[0] && emaM[0]>emaS[0] && price>emaF[0] && sep>=InpMinEmaSep)
      return REGIME_BULLISH;
   if(emaF[0]<emaM[0] && emaM[0]<emaS[0] && price<emaF[0] && sep>=InpMinEmaSep)
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
//| 4 CORE STRATEGIES                                                  |
//+------------------------------------------------------------------+
int StratPullback(double &score)
{
   score=0;
   if(g_regime != REGIME_BULLISH && g_regime != REGIME_BEARISH) return 0;

   double emaF[1], emaM[1], emaS[1], rsi[1], atr[1];
   if(CopyBuffer(hEMA_Fast_E,0,1,1,emaF)<1) return 0;
   if(CopyBuffer(hEMA_Mid_E,0,1,1,emaM)<1)  return 0;
   if(CopyBuffer(hEMA_Slow_E,0,1,1,emaS)<1) return 0;
   if(CopyBuffer(hRSI_E,0,1,1,rsi)<1)       return 0;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)       return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   double body  = price - iOpen(_Symbol,g_tf_entry,1);
   int dir = (g_regime==REGIME_BULLISH) ? 1 : -1;

   double pb = MathAbs(price - emaF[0]);
   if(pb < InpPullbackMin*atr[0] || pb > InpPullbackMax*atr[0]) return 0;

   if(dir>0 && (rsi[0]>65 || body<-0.1*atr[0])) return 0;
   if(dir<0 && (rsi[0]<35 || body>0.1*atr[0])) return 0;

   if(dir>0 && !(emaF[0]>emaM[0])) return 0;
   if(dir<0 && !(emaF[0]<emaM[0])) return 0;

   score = 4.0;
   return dir;
}

int StratBreakout(double &score)
{
   score=0;
   if(g_regime == REGIME_NO_TRADE || g_regime == REGIME_HIGH_VOL) return 0;

   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double price = iClose(_Symbol,g_tf_entry,1);
   double body  = price - iOpen(_Symbol,g_tf_entry,1);

   double hh=iHigh(_Symbol,g_tf_entry,1), ll=iLow(_Symbol,g_tf_entry,1);
   for(int i=2;i<=InpBreakoutBars;i++)
   {
      hh=MathMax(hh,iHigh(_Symbol,g_tf_entry,i));
      ll=MathMin(ll,iLow(_Symbol,g_tf_entry,i));
   }
   double buf = InpBreakoutBuffer * atr[0];

   int dir=0;
   if(g_regime==REGIME_BULLISH || g_regime==REGIME_RANGING) dir=1;
   if(g_regime==REGIME_BEARISH) dir=-1;

   if(dir>0 && price>hh+buf && body>0){ score=3.5; return 1; }
   if(dir<0 && price<ll-buf && body<0){ score=3.5; return -1; }
   return 0;
}

int StratMomentum(double &score)
{
   score=0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double body = iClose(_Symbol,g_tf_entry,1) - iOpen(_Symbol,g_tf_entry,1);
   double range = iHigh(_Symbol,g_tf_entry,1) - iLow(_Symbol,g_tf_entry,1);
   if(range<=0) return 0;

   double ratio = MathAbs(body)/range;
   if(ratio < InpMomBodyMin) return 0;

   if(body>0 && ratio>0.55){ score=3.0; return 1; }
   if(body<0 && ratio>0.55){ score=3.0; return -1; }
   return 0;
}

int StratMeanRevert(double &score)
{
   score=0;
   if(g_regime != REGIME_RANGING) return 0;   // Only in ranging

   double rsi[1], bb_mid[1], bb_up[1], bb_lo[1];
   if(CopyBuffer(hRSI_E,0,1,1,rsi)<1) return 0;
   if(CopyBuffer(hBB_E,0,1,1,bb_mid)<1) return 0;
   if(CopyBuffer(hBB_E,1,1,1,bb_up)<1) return 0;
   if(CopyBuffer(hBB_E,2,1,1,bb_lo)<1) return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   double prev  = iClose(_Symbol,g_tf_entry,2);

   if(prev <= bb_lo[0] && price > bb_lo[0] && rsi[0] < InpRsiOversold)
   { score=3.8; return 1; }
   if(prev >= bb_up[0] && price < bb_up[0] && rsi[0] > InpRsiOverbought)
   { score=3.8; return -1; }
   return 0;
}

//+------------------------------------------------------------------+
//| BAND FADE — the walk-forward VALIDATED edge (port of Python      |
//| band_geometry.py + vol_band.py entry gates).                     |
//|                                                                  |
//| Fires when volatility just EXPANDED (sigma > ratio x sigma EMA)  |
//| AND price is statistically extended (|z_dev| >= ZEntry): fade    |
//| back toward the mean with sigma-derived levels:                  |
//|   stop   = 0.10 x sigma_h     (being wrong is cheap)             |
//|   target = 0.80 x sigma_h     (inside the reachable band)        |
//| Allowed regimes: RANGING and HIGH_VOL — expansion IS its edge.   |
//+------------------------------------------------------------------+
int StratBandFade(double &score)
{
   score=0;
   if(g_regime != REGIME_RANGING && g_regime != REGIME_HIGH_VOL) return 0;
   if(!g_sigma_init || g_sigma_ema<=0) return 0;

   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   if(atr[0]<=0) return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   if(g_sigma_now<=0 || price<=0) return 0;

   // Vol-extension gate: market must have JUST expanded vs baseline
   if(!(g_sigma_init && g_exp_ratio > InpBandVolExtRatio)) return 0;

   double z_dev   = g_z_dev;      // measured this bar by UpdateBandTelemetry()
   double sig_now = g_sigma_now;

   int dir=0;
   if(z_dev >=  InpBandZEntry) dir=-1;   // faded extension above -> SELL
   if(z_dev <= -InpBandZEntry) dir= 1;   // faded extension below -> BUY
   if(dir==0) return 0;

   // Validated geometry: sigma scaled to the hold horizon (fractional)
   int bar_sec = PeriodSeconds(g_tf_entry);
   if(bar_sec<=0) bar_sec=300;
   int bars = (int)MathMax(1, MathRound((double)InpBandHoldSec/bar_sec));
   double sigma_h  = sig_now*MathSqrt((double)bars);
   double stop_f   = InpBandStopSigmaMult*sigma_h;
   double target_f = InpBandTargetSigmaMult*sigma_h;
   if(stop_f<=0 || target_f<=0) return 0;
   if(target_f/stop_f < InpBandMinRR) return 0;
   if(stop_f > InpBandMaxStopPct) return 0;

   // Express in ATR units so OpenTrade keeps one execution path
   g_sig_is_band = true;
   g_sig_sl_atr  = stop_f*price/atr[0];
   g_sig_tp_atr  = target_f*price/atr[0];

   score = 4.2;   // highest-quality validated leg
   g_last_band_dir = dir;
   return dir;
}

//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime==REGIME_NO_TRADE) return 0;
   // HIGH_VOL is no longer a global block: the band-fade leg TRADES expansion.
   // Pullback/Breakout/MeanRevert self-gate away from it below.

   // fresh per-signal exit geometry (defaults = classic ATR legs)
   g_sig_is_band=false; g_last_band_dir=0; g_sig_sl_atr=0; g_sig_tp_atr=0;

   double scores[5];
   int dirs[5];
   ArrayInitialize(scores,0);
   ArrayInitialize(dirs,0);

   int buy_score=0, sell_score=0, buy_cnt=0, sell_cnt=0;

   if(InpUsePullback)   { dirs[0]=StratPullback(scores[0]); }
   if(InpUseBreakout)   { dirs[1]=StratBreakout(scores[1]); }
   if(InpUseMomentum)   { dirs[2]=StratMomentum(scores[2]); }
   if(InpUseMeanRevert) { dirs[3]=StratMeanRevert(scores[3]); }
   if(InpUseBandFade)   { dirs[4]=StratBandFade(scores[4]); }

   // TELEMETRY: compact fired-leg string, e.g. "MOM-|MR-|BF-"
   const string LEGNAMES[5]={"PB","BO","MOM","MR","BF"};
   g_fired_legs="";
   for(int i=0;i<5;i++)
      if(dirs[i]!=0)
      {
         string sep=(g_fired_legs=="") ? "" : "|";
         g_fired_legs += sep+LEGNAMES[i]+(dirs[i]>0?"+":"-");
      }

   for(int i=0;i<5;i++)
   {
      if(dirs[i]>0){ buy_score += (int)scores[i]; buy_cnt++; }
      if(dirs[i]<0){ sell_score += (int)scores[i]; sell_cnt++; }
   }

   // Regime bonus (band fade already thrives on expansion — no bonus for it)
   if(g_regime==REGIME_BULLISH) buy_score += 2;
   if(g_regime==REGIME_BEARISH) sell_score += 2;

   // MOMENTUM DEMOTION: a lone momentum candle must never be an entry by
   // itself — chasing extended bars on a mean-reverting synthetic index is
   // exactly what produced the Aug-17 losing spree (see journals).
   bool mom_demoted=false;
   if(!InpMomentumStandalone)
   {
      if(buy_cnt==1  && dirs[2]>0){ buy_score=0;  buy_cnt=0; mom_demoted=true; }
      if(sell_cnt==1 && dirs[2]<0){ sell_score=0; sell_cnt=0; mom_demoted=true; }
   }

   int final_dir=0;
   string skip_reason="";
   if(buy_score >= InpMinScore && buy_score > sell_score)
   {
      if(InpRequire2Strats && buy_cnt<2) skip_reason="need-2-strats-BUY";
      else final_dir=1;
   }
   else if(sell_score >= InpMinScore && sell_score > buy_score)
   {
      if(InpRequire2Strats && sell_cnt<2) skip_reason="need-2-strats-SELL";
      else final_dir=-1;
   }
   if(final_dir==0 && skip_reason=="")
      skip_reason=(buy_cnt==0 && sell_cnt==0)
                ? (mom_demoted ? "mom-demoted-lone-candle" : "no-legs")
                : StringFormat("score B%d/S%d < min %d", buy_score, sell_score, InpMinScore);

   // Guard: sigma-derived exit levels are only valid for a trade in the SAME
   // direction band-fade fired. If another leg won the opposite side, fall
   // back to the classic ATR geometry.
   if(g_sig_is_band && (final_dir==0 || g_last_band_dir!=final_dir))
   { g_sig_is_band=false; g_sig_sl_atr=0; g_sig_tp_atr=0; }

   if(final_dir!=0)
   {
      sig_type = StringFormat("SC%d%s", MathMax(buy_score,sell_score),
                              g_sig_is_band ? "B" : "");
      g_last_skip="";
   }
   else g_last_skip=skip_reason;

   // TELEMETRY: one structured line per evaluated bar that had any fired leg.
   // Bars where entries are externally blocked (pause/cooldown/halt/warmup)
   // never reach here — those blockers are logged separately in Experts log.
   if(g_fired_legs!="")
      Telem("sig", StringFormat(
         "\"sym\":\"%s\",\"action\":\"%s\",\"dir\":%d,\"reason\":\"%s\",\"legs\":\"%s\"," +
         "\"score_b\":%.1f,\"score_s\":%.1f,\"regime\":\"%s\",\"z\":%.3f,\"exp\":%.3f," +
         "\"sigma\":%.6f,\"sigma_base\":%.6f,\"band_geom\":%s",
         _Symbol, (final_dir!=0?"TAKE":"SKIP"), final_dir,
         (final_dir!=0?"-":skip_reason), g_fired_legs,
         buy_score, sell_score, RegimeToStr(g_regime),
         g_z_dev, g_exp_ratio, g_sigma_now, g_sigma_ema,
         g_sig_is_band?"true":"false"));

   return final_dir;
}

//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return;

   double entry = direction>0 ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID);

   // Exit geometry: the band leg carries sigma-derived distances; ATR legs
   // keep the classic swing-adjusted stop.
   double stop_dist;
   if(g_sig_is_band && g_sig_sl_atr>0)
      stop_dist = g_sig_sl_atr*atr[0];
   else
   {
      stop_dist = 1.7 * atr[0];
      // Simple structure adjustment
      if(direction>0)
      {
         double lo = iLow(_Symbol,g_tf_entry,1);
         for(int k=2;k<=5;k++) lo=MathMin(lo,iLow(_Symbol,g_tf_entry,k));
         stop_dist = MathMax(stop_dist, entry - (lo - 0.15*atr[0]));
      }
      else
      {
         double hi = iHigh(_Symbol,g_tf_entry,1);
         for(int k=2;k<=5;k++) hi=MathMax(hi,iHigh(_Symbol,g_tf_entry,k));
         stop_dist = MathMax(stop_dist, (hi + 0.15*atr[0]) - entry);
      }
      if(stop_dist < atr[0]*0.5) stop_dist = atr[0]*0.5;
   }

   // Broker minimum stop distance + absolute sanity cap
   double min_stop = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   if(min_stop>0 && stop_dist<min_stop) stop_dist=min_stop;
   if(stop_dist > entry*0.03) stop_dist = entry*0.03;

   double tp_dist = (g_sig_is_band && g_sig_tp_atr>0) ? g_sig_tp_atr*atr[0]
                                                      : InpTpMult*stop_dist;
   double sl = direction>0 ? entry-stop_dist : entry+stop_dist;
   double tp = direction>0 ? entry+tp_dist : entry-tp_dist;

   // Risk volume
   double risk_money = g_eq * InpRiskPerTrade;
   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tick_size<=0 || tick_value<=0) return;
   double vol = risk_money / ((stop_dist/tick_size)*tick_value);
   vol = NormalizeVolume(vol);
   if(vol<=0) return;

   // EFFECTIVE-RISK GUARDRAIL: on tiny accounts the broker's min-lot floor
   // can force far more risk than InpRiskPerTrade asked for. Refuse entries
   // whose REAL risk breaches the hard cap instead of silently over-risking.
   double eff_risk   = vol*((stop_dist/tick_size)*tick_value);
   double cap_money  = g_eq*InpMaxEffectiveRiskPct/100.0;
   if(eff_risk > cap_money)
   {
      PrintFormat("[v22] SKIP %s — min-lot effective risk $%.2f exceeds cap $%.2f (%.0f%% equity). Add capital or trade a lower-vol symbol.",
                  direction>0?"BUY":"SELL", eff_risk, cap_money, InpMaxEffectiveRiskPct);
      g_cooldown=1;
      return;
   }
   g_risk_money = eff_risk;
   if(eff_risk > g_eq*0.05)
      PrintFormat("[v22] WARNING: effective risk $%.2f = %.1f%% of equity (min-lot floor on small account).",
                  eff_risk, eff_risk/g_eq*100.0);

   // ACCOUNT-WIDE EXPOSURE GUARD: existing open risk across ALL fleet
   // magics + this new trade must stay under InpMaxTotalRiskPct of equity.
   int no_sl=0;
   double fleet_risk = FleetOpenRisk(no_sl);
   double acct_eq    = AccountInfoDouble(ACCOUNT_EQUITY);
   double total_cap  = acct_eq*InpMaxTotalRiskPct/100.0;
   if(fleet_risk + eff_risk > total_cap)
   {
      PrintFormat("[v22] SKIP %s — ACCOUNT GUARD: open fleet risk $%.2f + new $%.2f "
                  "> ceiling $%.2f (%.0f%% equity)%s",
                  direction>0?"BUY":"SELL", fleet_risk, eff_risk, total_cap,
                  InpMaxTotalRiskPct,
                  no_sl>0 ? StringFormat(" [%d fleet pos without SL!]",no_sl) : "");
      Telem("risk_block", StringFormat(
         "\"sym\":\"%s\",\"fleet_risk\":%.2f,\"new_risk\":%.2f,\"ceiling\":%.2f,\"eq\":%.2f",
         _Symbol, fleet_risk, eff_risk, total_cap, acct_eq));
      g_cooldown=1;
      return;
   }
   if(no_sl>0)
      PrintFormat("[v22] WARNING: %d fleet position(s) carry no SL — not counted in exposure guard.", no_sl);

   bool ok=false;
   if(InpLiveExecution)
   {
      PrintFormat("[v22] Executing %s vol=%.2f SL=%.5f TP=%.5f", direction>0?"BUY":"SELL", vol, sl, tp);
      if(direction>0) ok=trade.Buy(vol,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"MITEM_v22.1");
      else            ok=trade.Sell(vol,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"MITEM_v22.1");
      if(!ok)
      {
         uint retcode = trade.ResultRetcode();
         string desc   = trade.ResultRetcodeDescription();
         PrintFormat("[v22] ORDER FAILED retcode=%d desc=%s", retcode, desc);
      }
   }
   else { g_ticket=(ulong)TimeCurrent(); ok=true; Print("[v22] PAPER MODE - no order sent"); }

   if(!ok){ g_cooldown=InpCoolDownBars; return; }

   g_ticket=0;
   for(int a=0;a<6;a++)
   {
      Sleep(60);
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong t=PositionGetTicket(i);
         if(t>0 && PositionGetInteger(POSITION_MAGIC)==InpMagic && PositionGetString(POSITION_SYMBOL)==_Symbol)
         { g_ticket=t; break; }
      }
      if(g_ticket>0) break;
   }
   if(g_ticket==0) g_ticket=trade.ResultOrder();

   g_dir=direction; g_entry=entry; g_sl=sl; g_tp=tp;
   g_orig_risk=stop_dist; g_position_volume=vol;
   g_entry_time=TimeCurrent(); g_bars_held=0;
   g_max_hold = (g_sig_is_band && g_sig_sl_atr>0)
      ? (int)MathMax(4, (int)MathRound((double)InpBandHoldSec/MathMax(60,PeriodSeconds(g_tf_entry)))+2)
      : InpMaxHoldBars;   // band trades honor their own horizon (+2 bar grace)
   g_trades_today++;

   if(InpDrawSignals) DrawArrow(direction,TimeCurrent(),entry,sig_type);
   PrintFormat("[v22] %s %s @%.5f SL=%.5f TP=%.5f", sig_type, direction>0?"BUY":"SELL", entry,sl,tp);

   // TELEMETRY: full entry context so replays never need feature proxies
   Telem("open", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"dir\":%d,\"entry\":%.5f,\"sl\":%.5f,\"tp\":%.5f," +
      "\"vol\":%.2f,\"eff_risk\":%.2f,\"band\":%s,\"legs\":\"%s\",\"regime\":\"%s\"," +
      "\"tf\":\"%s\",\"z\":%.3f,\"exp\":%.3f",
      _Symbol, g_ticket, direction, entry, sl, tp, vol, g_risk_money,
      (g_sig_is_band?"true":"false"), g_fired_legs, RegimeToStr(g_regime),
      EnumToString(g_tf_entry), g_z_dev, g_exp_ratio));
}

double NormalizeVolume(double vol)
{
   double minv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=0.01;
   vol=MathFloor(vol/step)*step;
   if(vol<minv) vol=minv; if(vol>maxv) vol=maxv;
   return NormalizeDouble(vol,2);
}

//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)){ g_ticket=0; return; }
   g_bars_held++;

   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);

   if(g_bars_held >= g_max_hold){ ClosePosition("TIME"); return; }

   if(g_dir>0){ if(bid<=g_sl){ClosePosition("STOP");return;} if(bid>=g_tp){ClosePosition("TARGET");return;} }
   else       { if(ask>=g_sl){ClosePosition("STOP");return;} if(ask<=g_tp){ClosePosition("TARGET");return;} }

   double r_now = g_orig_risk>0 ? (g_dir>0?(bid-g_entry):(g_entry-ask))/g_orig_risk : 0;

   if(InpUseBreakeven && r_now >= InpBeTriggerR)
   {
      double be = g_dir>0 ? g_entry+2*_Point : g_entry-2*_Point;
      if((g_dir>0 && g_sl<be) || (g_dir<0 && g_sl>be))
         if(trade.PositionModify(g_ticket,NormalizeDouble(be,_Digits),g_tp)) g_sl=be;
   }

   if(InpUseTrailing && r_now >= InpTrailStartR)
   {
      double dist = InpTrailDistR * g_orig_risk;
      if(g_dir>0){ double ns=NormalizeDouble(bid-dist,_Digits); if(ns>g_sl && ns>g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl=ns; }
      else       { double ns=NormalizeDouble(ask+dist,_Digits); if(ns<g_sl && ns<g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl=ns; }
   }
}

void ClosePosition(string reason)
{
   if(g_ticket==0) return;
   ulong closed_ticket=g_ticket;
   double exit_p = g_dir>0 ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   if(!trade.PositionClose(g_ticket)) return;

   double r = g_orig_risk>0 ? (g_dir>0?(exit_p-g_entry):(g_entry-exit_p))/g_orig_risk : 0;
   g_trades++; g_total_r += r;
   if(r>0) g_wins++; else g_losses++;

   if(reason=="TARGET") g_target_exits++;
   else if(reason=="TIME") g_time_exits++;
   else if(reason=="STOP") g_stop_exits++;

   if(r<0){ g_consec_loss++; g_cooldown=InpCoolDownBars; } else g_consec_loss=0;
   if(g_consec_loss>=InpMaxConsecLoss)
   {
      g_paused=true;
      PrintFormat("[v22] %d consecutive losses — PAUSED (auto-resets next session day).", g_consec_loss);
   }
   g_daily_pnl += r*g_risk_money;   // signed money P&L approximation for reporting

   PrintFormat("[v22] CLOSE %s R=%+.3f | dailyPnL=$%+.2f", reason, r, g_daily_pnl);

   // TELEMETRY: outcome + post-trade breaker state
   Telem("close", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"dir\":%d,\"reason\":\"%s\",\"exit\":%.5f," +
      "\"r\":%.3f,\"pnl\":%.2f,\"consec_loss\":%d,\"paused\":%s,\"daily_halt\":%s",
      _Symbol, closed_ticket, g_dir, reason, exit_p, r, r*g_risk_money,
      g_consec_loss, (g_paused?"true":"false"), (DailyLossHalted()?"true":"false")));
   g_ticket=0; g_dir=0; g_bars_held=0;
}

//+------------------------------------------------------------------+
void CreateDashboard()
{
   for(int i=0;i<24;i++)
   {
      dash_names[i]="M211_"+IntegerToString(i);
      ObjectCreate(0,dash_names[i],OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,dash_names[i],OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,dash_names[i],OBJPROP_XDISTANCE,10);
      ObjectSetInteger(0,dash_names[i],OBJPROP_YDISTANCE,15+i*15);
      ObjectSetString(0,dash_names[i],OBJPROP_FONT,"Consolas");
      ObjectSetInteger(0,dash_names[i],OBJPROP_FONTSIZE,9);
   }
}

void UpdateDashboard()
{
   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   double atr[1]; CopyBuffer(hATR_E,0,0,1,atr);
   double pct = CalcATRPercentile(atr[0]);

   string L[24];
   L[0]="=== MITEMSHUB AI v22.1 ===";
   L[1]=StringFormat("%s | %s -> %s",_Symbol,EnumToString(g_tf_entry),EnumToString(g_tf_regime));
   L[2]=StringFormat("Equity: $%.2f",g_eq);
   L[3]=StringFormat("Regime: %s | ATR%%: %.0f",RegimeToStr(g_regime),pct);
   L[4]=StringFormat("Trades: %d | WR: %.1f%% | R: %+.2f",g_trades,wr,g_total_r);
   L[5]=StringFormat("Today: %d | Status: %s",g_trades_today,
        g_paused?"PAUSED(next-day reset)":(DailyLossHalted()?"DAILY-HALT":"ACTIVE"));
   L[6]=StringFormat("Strategies: Pull+%s Break+%s Mom+%s MR+%s",
        InpUsePullback?"ON":"OFF", InpUseBreakout?"ON":"OFF",
        InpUseMomentum?"ON":"OFF", InpUseMeanRevert?"ON":"OFF");
   L[7]=StringFormat("MinScore: %d | 2+ Agree: %s",InpMinScore,InpRequire2Strats?"YES":"NO");
   L[8]=StringFormat("Risk: %.2f%% (cap %.0f%%) | TP: %.1fx | Hold: %d",
        InpRiskPerTrade*100,InpMaxEffectiveRiskPct,InpTpMult,InpMaxHoldBars);
   L[9]=StringFormat("Band: %s z>=%.1f tgt=%.2fsig | MomAlone: %s",
        InpUseBandFade?"ON":"OFF",InpBandZEntry,InpBandTargetSigmaMult,
        InpMomentumStandalone?"YES":"NO");
   L[10]=(g_sigma_init && g_sigma_now>0)
        ? StringFormat("Telem: z=%+.2f exp=%.2fx sig=%.5f base=%.5f",
                       g_z_dev,g_exp_ratio,g_sigma_now,g_sigma_ema)
        : "Telem: warming up...";
   {
      int nsl=0;
      double fr=FleetOpenRisk(nsl);
      double cap=AccountInfoDouble(ACCOUNT_EQUITY)*InpMaxTotalRiskPct/100.0;
      L[11]=StringFormat("Guard: fleet risk $%.2f / $%.2f cap (%.0f%% eq)%s",
                         fr,cap,InpMaxTotalRiskPct,
                         nsl>0?StringFormat(" [%d no-SL!]",nsl):"");
   }

   int line=12;
   if(g_ticket>0 && PositionSelectByTicket(g_ticket))
   {
      double cur = g_dir>0?SymbolInfoDouble(_Symbol,SYMBOL_BID):SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double rnow = g_orig_risk>0?(g_dir>0?(cur-g_entry):(g_entry-cur))/g_orig_risk:0;
      L[line++]=StringFormat("OPEN %s @%.5f  R:%+.2f",g_dir>0?"BUY":"SELL",g_entry,rnow);
   }
   while(line<24) L[line++]=" ";

   for(int i=0;i<24;i++)
   {
      ObjectSetString(0,dash_names[i],OBJPROP_TEXT,L[i]);
      color c=clrWhite;
      if(i==0) c=clrGold;
      if(i==3){
         if(g_regime==REGIME_BULLISH) c=clrLime;
         else if(g_regime==REGIME_BEARISH) c=clrRed;
         else if(g_regime==REGIME_RANGING) c=clrYellow;
         else c=clrGray;
      }
      if(i==5) c=g_paused?clrRed:clrLime;
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
   string name="M211_"+tag+"_"+IntegerToString((int)t);
   ObjectCreate(0,name,OBJ_ARROW,0,t,price);
   ObjectSetInteger(0,name,OBJPROP_ARROWCODE,dir>0?233:234);
   ObjectSetInteger(0,name,OBJPROP_COLOR,dir>0?clrLime:clrRed);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
}
//+------------------------------------------------------------------+
