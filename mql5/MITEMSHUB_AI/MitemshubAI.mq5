//+------------------------------------------------------------------+
//|                                            MitemshubAI.mq5       |
//|  MITEMSHUB AI MARKET ENGINE — the integrated EA (Phase 10).      |
//|                                                                  |
//|  OnTick -> BarAggregator -> CandleEngine -> Garch -> Volatility  |
//|  -> Regime -> Structure -> State -> BAND gate -> Decision ->     |
//|  Risk -> Execute -> Journal -> Dashboard -> Signals -> Manage.   |
//|                                                                  |
//|  Closed-candle discipline: every engine consumes CLOSED bars      |
//|  only; signals fire once per closed execution bar.  The band leg  |
//|  is the P10-A aligned cross-validation target: with the alignment |
//|  inputs below it reproduces the Python reference (phase8/CLI      |
//|  backtest-vol --mode band) trade-for-trade on the same window.   |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "MITEMSHUB Phase 10 integration EA - band leg"

#include "Core/Constants.mqh"
#include "Core/StateManager.mqh"
#include "Market/CandleEngine.mqh"
#include "Market/BarAggregator.mqh"
#include "Market/GarchForecaster.mqh"
#include "Market/VolatilityEngine.mqh"
#include "Market/SymbolAdapter.mqh"
#include "Regime/RegimeEngine.mqh"
#include "Structure/StructureEngine.mqh"
#include "Strategies/StrategyEngine.mqh"
#include "Decision/ScoringEngine.mqh"
#include "Decision/ConfidenceEngine.mqh"
#include "Decision/TradeQualityEngine.mqh"
#include "Risk/RiskEngine.mqh"
#include "Execution/ExecutionEngine.mqh"
#include "Journal/TradeJournal.mqh"
#include "Journal/DecisionLogger.mqh"
#include "Journal/PerformanceLogger.mqh"
#include "UI/Dashboard.mqh"
#include "UI/VisualSignals.mqh"

//--- stage-3 gate state (same constants as BandBackTests) ---------------------
#define GATE_STILL_LEARNING 0
#define GATE_PROVEN         1
#define GATE_SUPPRESSED     2

//--- execution timeframe ------------------------------------------------------
input int    InpBarSec           = 300;      // 300 = M5 (P10-A), 60 = M1 (P10-B)

//--- band geometry (optimized via backtest: R_100 z=2.2 stop=0.12 tgt=1.0, no trail) ----
input double InpZEntry           = 2.2;      // optimized: |z_dev| to trigger fade entry (was 1.0)
input double InpVolGateRatio     = 1.3;
input double InpMinRevertSignal  = 0.02;     // EGARCH mean-revert confirmation (Python gate)
input int    InpEmaPeriod        = 20;
input int    InpSigmaEmaPeriod   = 30;
input int    InpWarmupCandles    = 60;
input double InpStopSigmaMult    = 0.12;     // optimized: stop = 0.12 x sigma_h (was 0.20)
input double InpTargetSigmaMult  = 1.0;      // optimized: target = 1.0 x sigma_h (was 0.80)
input int    InpHoldSec          = 3600;
input double InpMinTargetRR      = 2.0;
input double InpMaxStopPct       = 0.015;

//--- GARCH estimator (P10-A aligned = mode 0 seeded with calibrated params) ----
input int    InpGarchMode        = 0;        // 0 = online-SGD from calibrated priors (Python path), 1 = calibrated fixed
input double InpGarchOmega       = -1.884103; // calibrated R_75 (r_75.json, anchored 6-start fit on the frozen snapshot)
input double InpGarchAlpha       = 0.142169;
input double InpGarchGamma       = -0.073285;
input double InpGarchBeta        = 0.852741;

//--- management (P10-A aligned = wick exits + breakeven trail, Python parity) --
input bool   InpTrailOn          = false;    // R_100 optimized: trail HURTS performance
input double InpTrailFrac        = 0.3;
input bool   InpPartialClose     = false;
input bool   InpClosedCandleGrace= false;    // false = wick trade-throughs (Python _maybe_close)
input bool   InpDriftGate        = false;    // P10-A: verified no-op on the corpus (Python ADWIN drift_events=0)

//--- execution costs (Python PaperExecutionConfig backtest-vol defaults) -------
input double InpExitSlippage     = 0.05;     // flat adverse price units per exit

//--- risk (P10-A aligned: reference approved every signal — limits permissive) -
input double InpRiskPerTrade     = 0.005;
input double InpMinConfidence    = 0.0;      // reference risk_config zeroed these
input double InpMinRewardRisk    = 0.0;
input double InpMaxDailyLossPct  = 1.0;      // never trips in the aligned run
input int    InpMaxConsecLosses  = 9999;
input double InpMaxEquityDDPct   = 1.0;

//--- stage-3 floor gate (report-only in P10-A; production enables the veto) ---
input int    InpFloorMinSamples  = 10;
input double InpFloorMargin      = 0.05;
input bool   InpFloorGate        = false;

//--- depth cap (aligned: off) ---------------------------------------------------
input double InpMaxEdgeDepth     = 0.0;

//--- execution mode ---------------------------------------------------------------
input bool   InpLiveExecution    = false;    // false = paper (tester), true = live (real CTrade)
input long   InpMagic            = 7788123;  // EA magic number (separates EA trades)
input int    InpMaxSlippagePts   = 50;       // max deviation for market orders (points)
input double InpMaxSpreadPts     = 1500.0;   // skip entry if spread above (points; 0=off)
                                              // NOTE: SYN75 NORMAL spread ~1000-1100 pts

//--- UI --------------------------------------------------------------------------
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;

//+------------------------------------------------------------------+
//| PaperTrade — tester transport (accepts every order, verify=true) |
//+------------------------------------------------------------------+
class PaperTrade : public CTradeInterface
  {
private:
   struct PP
     {
      ulong  ticket;
      long   type;          // POSITION_TYPE_BUY / SELL
      string symbol;
     };
   PP     m_pos[16];
   int    m_npos;
   ulong  m_rc;
   ulong  m_last_order;
   ulong  m_last_deal;

public:
   PaperTrade()
     {
      Reset();
     }

   void Reset()
     {
      m_npos = 0;
      m_rc   = (ulong)TRADE_RETCODE_DONE;
      m_last_order = 0;
      m_last_deal  = 0;
     }

   virtual bool Buy(const double volume, const string symbol,
                    const double price, const double sl, const double tp,
                    const string comment)
     {
      return(Open(1, symbol));
     }

   virtual bool Sell(const double volume, const string symbol,
                     const double price, const double sl, const double tp,
                     const string comment)
     {
      return(Open(-1, symbol));
     }

   virtual bool PositionModify(const ulong ticket, const double sl, const double tp)
     {
      m_rc = (ulong)TRADE_RETCODE_DONE;
      return(true);
     }

   virtual bool PositionClose(const ulong ticket, const double volume)
     {
      m_rc = (ulong)TRADE_RETCODE_DONE;
      for(int i = 0; i < m_npos; i++)
        {
         if(m_pos[i].ticket == ticket)
           {
            m_pos[i] = m_pos[m_npos - 1];
            m_npos--;
            break;
           }
        }
      return(true);
     }

   virtual bool   LastResult()                 { return(m_rc == (ulong)TRADE_RETCODE_DONE); }
   virtual ulong  ResultOrder()                { return(m_last_order); }
   virtual ulong  ResultDeal()                 { return(m_last_deal); }
   virtual ulong  ResultRetcode()              { return(m_rc); }
   virtual string ResultRetcodeDescription()   { return("done"); }
   virtual bool   PositionExists(const ulong ticket)
     {
      for(int i = 0; i < m_npos; i++)
         if(m_pos[i].ticket == ticket)
            return(true);
      return(false);
     }
   virtual bool   PositionSelect(const ulong ticket)
     {
      return(PositionExists(ticket));
     }
   virtual double PositionPriceOpen()          { return(0.0); }
   virtual double PositionPriceCurrent()       { return(0.0); }
   virtual long   PositionType()               { return(0); }
   virtual double PositionVolume()             { return(0.0); }
   virtual void   SetExpertMagicNumber(const long magic) { }
   virtual void   SetDeviationInPoints(const long deviation) { }
   virtual void   SetTypeFillingBySymbol(const string symbol) { }

private:
   bool Open(const int dir, const string symbol)
     {
      if(m_npos >= 16)
        {
         m_rc = (ulong)TRADE_RETCODE_REJECT;
         return(false);
        }
      m_last_order = m_next_ticket();
      m_last_deal  = m_last_order;
      m_pos[m_npos].ticket = m_last_order;
      m_pos[m_npos].type   = (dir > 0) ? (long)POSITION_TYPE_BUY : (long)POSITION_TYPE_SELL;
      m_pos[m_npos].symbol = symbol;
      m_npos++;
      m_rc = (ulong)TRADE_RETCODE_DONE;
      return(true);
     }

   ulong m_next_ticket()
     {
      static ulong s_next = 1000;
      return(s_next++);
     }
  };

//+------------------------------------------------------------------+
//| Engine instances                                                  |
//+------------------------------------------------------------------+
CStateManager       g_state;
CCandleEngine       g_ce;
CBarAggregator      g_agg;
CGarchForecaster   *g_garch = NULL;
CVolatilityEngine   g_vol;
CRegimeEngine       g_regime;
CStructureEngine    g_structure;
CRiskEngine         g_risk;
CTradeQualityEngine g_tqe;
CTradeJournal       g_journal;
CDecisionLogger     g_decisions;
CPerformanceLogger  g_perf;
CDashboard          g_dash;
CVisualSignals      g_signals;
PaperTrade          g_paper;
CTradeAdapter       g_live;
CExecutionEngine   *g_exec = NULL;
CSymbolAdapter      g_adapter;

//--- band stream state -----------------------------------------------------------
double g_prev_close = 0.0;
double g_ema        = 0.0;
double g_sigma      = 0.0;
double g_sigma_ema  = 0.0;
double g_prev_sigma = 0.0;
long   g_bars_seen  = 0;
datetime g_last_bar_end = 0;
double g_atr_ema    = 0.0;
int    g_z_head     = 0;
int    g_z_cnt      = 0;
double g_z_ring[50];
int    g_risk_vetoes = 0;
int    g_exec_rejects = 0;
int    g_floor_verdict = GATE_STILL_LEARNING;
int    g_pos_dir    = 0;      // direction of the open paper position (+1/-1)
double g_pos_stake  = 0.0;    // risk-engine stake of the open position (for outcome pnl)
double g_equity     = 0.0;    // running account equity (Python RiskState.equity parity)
int    g_drift_n    = 0;
double g_drift_win[20];
int    g_cooldown   = 9999;

//+------------------------------------------------------------------+
//| Helpers                                                            |
//+------------------------------------------------------------------+
double SafeDiv(const double a, const double b, const double def = 0.0)
  {
   return(MathAbs(b) < 1e-12 ? def : a / b);
  }

bool InPos()
  {
   return(g_exec != NULL && g_exec.InPosition());
  }

ENUM_TIMEFRAMES TfFromBarSec(const int bar_sec)
  {
   if(bar_sec <= 60)
      return(PERIOD_M1);
   if(bar_sec <= 300)
      return(PERIOD_M5);
   if(bar_sec <= 900)
      return(PERIOD_M15);
   if(bar_sec <= 3600)
      return(PERIOD_H1);
   return(PERIOD_H4);
  }

//--- Python _compute_mean_revert_signal: needs the z-history ring ----------------
void PushZ(const double z_t)
  {
   g_z_ring[g_z_head] = z_t;
   g_z_head = (g_z_head + 1) % 50;
   if(g_z_cnt < 50)
      g_z_cnt++;
  }

double MeanRevertSignal(const double z_t)
  {
   if(g_z_cnt < 5)
      return(0.0);
   int recent = 0;
   int take = MathMin(10, g_z_cnt);
   for(int k = 0; k < take; k++)
     {
      int idx = (g_z_head - 1 - k + 50) % 50;
      if(MathAbs(g_z_ring[idx]) > 2.0)
         recent++;
     }
   double az = MathAbs(z_t);
   if(az < 1.0)
      return(0.0);
   if(az < 2.0)
      return(MathMin(0.3, recent * 0.05));
   if(az < 3.0)
      return(MathMin(0.6, 0.3 + recent * 0.05));
   return(MathMin(0.9, 0.5 + recent * 0.07));
  }

//--- ADWIN-lite drift detector (BandBackTests port; signed returns, so a vol
//--- burst never trips it — only a sustained one-sided move).  OFF for P10-A:
//--- the Python reference's ADWIN fired 0 times on the corpus (measured), so
//--- the reference gate is a no-op and disabling it matches the entry set.
void ObserveDrift(const double log_ret)
  {
   double v = log_ret * 100.0;
   if(g_drift_n < 20)
      g_drift_win[g_drift_n++] = v;
   else
     {
      for(int i = 0; i < 19; i++)
         g_drift_win[i] = g_drift_win[i + 1];
      g_drift_win[19] = v;
     }
   if(g_drift_n < 20)
      return;
   double m0 = 0.0, m1 = 0.0;
   for(int i = 0; i < 10; i++)
      m0 += g_drift_win[i];
   for(int i = 10; i < 20; i++)
      m1 += g_drift_win[i];
   m0 /= 10.0;
   m1 /= 10.0;
   double sd = 0.0;
   for(int i = 0; i < 20; i++)
     {
      double m = (i < 10) ? m0 : m1;
      sd += (g_drift_win[i] - m) * (g_drift_win[i] - m);
     }
   sd = MathSqrt(sd / 20.0);
   double cut = MathSqrt(2.0 * MathLog(2.0 / 0.002) / 20.0) * MathMax(sd, 1e-9);
   if(MathAbs(m1 - m0) > cut)
      g_cooldown = 0;   // drift detected: cooldown resets
  }

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[MITEMSHUB] === integration EA starting ===");
   g_agg.Reset(InpBarSec);
   g_garch = new CGarchForecaster((InpGarchMode == 0) ? 0 : 1,
                                  InpGarchOmega, InpGarchAlpha, InpGarchGamma, InpGarchBeta);
   if(InpGarchMode == 0)
      g_garch.SeedCalibrated(InpGarchOmega, InpGarchAlpha, InpGarchGamma, InpGarchBeta);
   g_vol.SetPeriod(14);
   g_ce.RegisterTimeframe(TfFromBarSec(InpBarSec));
   g_structure.SetParams(2, 2, 60);
   g_adapter.Init(_Symbol);

   //--- risk: mode-aware config ------------------------------------------------
   // Paper (tester) = permissive aligned limits; Live = production safety.
   g_risk.SetRiskPerTrade(InpRiskPerTrade);
   g_risk.SetMinConfidence(InpMinConfidence);
   g_risk.SetMinRewardRisk(InpMinRewardRisk);
   g_risk.SetVetoWeakSignals(InpLiveExecution);   // live: only STRONG signals trade
   g_risk.SetVolatilityZ(0.0);
   g_risk.limits.SetMaxDailyLossPct(InpMaxDailyLossPct);
   g_risk.limits.SetMaxDailyDrawdownPct(InpMaxDailyLossPct);
   g_risk.limits.SetMaxEquityDrawdownPct(InpMaxEquityDDPct);
   g_risk.limits.SetMaxConsecutiveLosses(InpMaxConsecLosses);
   g_risk.limits.SetMaxOpenPositions(1);
   g_risk.limits.SetMaxTradesPerHour(InpLiveExecution ? 3 : 9999);
   g_risk.limits.SetMaxTradesPerDay(InpLiveExecution ? 10 : 9999);
   g_risk.dd.SetLimits(InpMaxEquityDDPct, InpMaxDailyLossPct, 1.0);

   //--- execution transport: paper (tester) or live (real CTrade) ----------------
   CTradeInterface *transport;
   ExecutionConfig ecfg;
   if(InpLiveExecution)
     {
      //--- live: configure the real CTrade adapter ---------------------------
      g_live.SetExpertMagicNumber(InpMagic);
      g_live.SetDeviationInPoints(InpMaxSlippagePts);
      g_live.SetTypeFillingBySymbol(_Symbol);
      transport = &g_live;
      ecfg.live            = true;
      ecfg.verify_fills    = true;       // NEVER assume success
      ecfg.min_rr          = InpMinTargetRR;
      ecfg.max_spread_points = InpMaxSpreadPts;
      Print("[MITEMSHUB] LIVE EXECUTION enabled — magic=" + IntegerToString(InpMagic));
     }
   else
     {
      //--- paper (strategy tester) -------------------------------------------
      transport = &g_paper;
      ecfg.live            = false;
      ecfg.verify_fills    = true;
      ecfg.min_rr          = InpMinTargetRR;
      ecfg.max_spread_points = 0.0;      // no spread guard in the reference
     }
   g_exec = new CExecutionEngine(transport, ecfg);
   g_exec.SetStateManager(g_state);
   PositionMgmtConfig mgmt;
   mgmt.breakeven_trail   = InpTrailOn;
   mgmt.trail_frac        = InpTrailFrac;
   mgmt.hold_sec          = InpHoldSec;
   mgmt.partial_close     = InpPartialClose;
   mgmt.closed_candle_grace = InpClosedCandleGrace;
   g_exec.ConfigureManagement(mgmt);

   //--- journal (tester sandbox CSV; the P10-A contract reads machine lines) ---
   g_journal.Init("MitemshubAI_trades.csv");
   g_perf.Reset();

   //--- dashboard / signals -----------------------------------------------------
   if(InpDrawDashboard)
      g_dash.Create();
   if(InpDrawSignals)
      g_signals.Init(0, "MITEMSHUB_SIG_");

   Print(StringFormat("[MITEMSHUB] bar_sec=%d garch_mode=%d omega=%.4f alpha=%.4f gamma=%.4f beta=%.4f "
                      "revert=%.2f drift=%s trail=%.2f grace=%s live=%s magic=%d",
                      InpBarSec, InpGarchMode, InpGarchOmega, InpGarchAlpha, InpGarchGamma, InpGarchBeta,
                      InpMinRevertSignal, InpDriftGate ? "ON" : "OFF", InpTrailFrac,
                      InpClosedCandleGrace ? "ON" : "OFF",
                      InpLiveExecution ? "LIVE" : "PAPER", InpMagic));
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| ProcessOneBar — the closed-bar pipeline (runs once per bar)       |
//+------------------------------------------------------------------+
void ProcessOneBar(const AggregatedBar &bar)
  {
   ENUM_TIMEFRAMES tf = TfFromBarSec(InpBarSec);
   g_ce.PushBar(tf, bar.open, bar.high, bar.low, bar.close, bar.time);
   g_bars_seen++;

   //--- gap re-anchor (Python _gap_reanchor: a feed outage is not one giant bar)
   if(g_last_bar_end > 0 && bar.time > g_last_bar_end + (datetime)MathMax(3 * InpBarSec, 600))
     {
      g_prev_close = bar.close;
      g_ema        = bar.close;
      g_last_bar_end = bar.time + InpBarSec;
      return;
     }
   g_last_bar_end = bar.time + InpBarSec;

   //--- first bar: seed baselines, no signal -------------------------------------
   if(g_prev_close <= 0.0)
     {
      g_prev_close = bar.close;
      g_ema        = bar.close;
      return;
     }

   double prev_close = g_prev_close;
   double log_ret = MathLog(bar.close / prev_close);
   g_prev_close = bar.close;

   //--- GARCH (Python VolBandStrategy order: prev_sigma = last bar's sigma, then
   //--- forecaster update, then the EMAs) ---------------------------------------
   g_prev_sigma = g_sigma;
   bool ready = g_garch.Update(log_ret, g_sigma);
   if(ready)
      PushZ(g_garch.LastZ());
   double sigma_alpha = 2.0 / (InpSigmaEmaPeriod + 1.0);
   g_sigma_ema = (g_sigma_ema <= 0.0) ? g_sigma : g_sigma_ema * (1.0 - sigma_alpha) + g_sigma * sigma_alpha;
   double alpha = 2.0 / (InpEmaPeriod + 1.0);
   g_ema = g_ema * (1.0 - alpha) + bar.close * alpha;
   ObserveDrift(log_ret);
   if(g_cooldown < 9999)
      g_cooldown++;

   //--- volatility / regime / structure (StateManager feed) -----------------------
   g_vol.OnBarWithPrevClose(prev_close, bar.high, bar.low, bar.close);
   double atr = g_vol.ATR();
   g_atr_ema = (g_atr_ema <= 0.0) ? atr : g_atr_ema * 0.98 + atr * 0.02;
   double atr_pct = g_vol.ATRPercentile(50);
   double atr_ratio = SafeDiv(atr, g_atr_ema, 1.0);
   double closes[];
   int nc = g_ce.GetCloses(tf, closes, 120);
   if(nc >= 30)
     {
      g_regime.Classify(closes, nc, atr_pct, atr_ratio);
      g_structure.Update(g_ce, tf, atr);
     }
   g_state.SetRegime(g_regime.Regime(), g_regime.Confidence());

   //--- manage the OPEN position FIRST (Python order: broker closes the old
   //--- position on the entry bar before the strategy opens the new one) --------
   if(InPos())
     {
      g_tqe.UpdatePosition(bar.high, bar.low);
      double exit_price = 0.0;
      OrderResult res;
      bool partial = false;
      ENUM_EXIT_REASON reason = g_exec.ManageBar(bar.high, bar.low, bar.close,
                                                 bar.time, InpBarSec, exit_price,
                                                 res, partial);
      if(reason != EXIT_NONE)
        {
         // Python _apply_exit_slippage: flat adverse 0.05 price units
         double slipped = (g_pos_dir > 0) ? exit_price - InpExitSlippage
                                          : exit_price + InpExitSlippage;
         double rr = g_tqe.ClosePosition(slipped, reason, bar.time + InpBarSec);
         g_perf.AddOutcome(rr, rr, 0);
         // Python RiskEngine.register_outcome: pnl = stake * return_r (penalty 0
         // in the aligned run); only material losses (rr < -0.10) extend the
         // consecutive-loss streak, so breakeven scratches never trip the
         // breaker.  Registering outcomes is what makes the consecutive-loss /
         // daily-loss / equity-drawdown limits ACTUALLY fire in the EA.
         double outcome_pnl = g_pos_stake * rr;
         g_equity += outcome_pnl;
         // Python parity: register_outcome itself decrements open_positions and
         // updates equity/streak — no separate close registration in the Python
         // runner.  The EA's Evaluate ALSO consults the MQL5-only exposure
         // manager, so RegisterClose must run here too (its limits decrement is
         // guarded at 0, so it never double-decrements; exposure is otherwise
         // never cleared and CanOpen vetoes every later entry).
         g_risk.RegisterOutcome(outcome_pnl, rr);
         g_risk.RegisterClose(g_pos_dir);
         g_pos_stake = 0.0;
         OutcomeRecord rec;
         if(g_tqe.GetRecord(g_tqe.Count() - 1, rec))
            g_journal.Append(rec, _Symbol, 0.0, 0.0,
                             g_state.LastConfidence(), g_state.LastScore());
         g_state.SetOpenPosition(0);
         g_pos_dir = 0;
         if(InpDrawSignals)
            g_signals.Add(MARKER_EXIT, bar.time + InpBarSec, slipped,
                          ExitReasonToString(reason));
         Print(StringFormat("[MITEMSHUB] exit %s @%.5f R=%.3f (bar %I64d)",
                            ExitReasonToString(reason), slipped, rr, g_bars_seen));
        }
     }

   //--- band entry gate (P10-A aligned, matches the Python strategy) --------------
   if(InPos())
      return;
   if(g_bars_seen < InpWarmupCandles)
      return;
   if(g_garch.Observations() < 30)
      return;
   if(InpDriftGate && g_cooldown < 10)
      return;
   if(g_sigma_ema <= 0.0 || g_prev_sigma <= 0.0)
      return;
   if(!(g_prev_sigma > InpVolGateRatio * g_sigma_ema))
      return;
   if(InpMinRevertSignal > 0.0)
     {
      double revert = MeanRevertSignal(g_garch.LastZ());
      if(revert < InpMinRevertSignal)
         return;
     }
   double z_dev = MathLog(bar.close / g_ema) / g_prev_sigma;
   if(MathAbs(z_dev) < InpZEntry)
      return;
   int direction = (z_dev > 0.0) ? -1 : 1;   // Python: z>0 -> SHORT (fade the extension)
   double depth = MathAbs(z_dev) / InpZEntry;
   if(InpMaxEdgeDepth > 0.0 && depth > InpMaxEdgeDepth)
      return;

   //--- candidate -> decision -> risk -> execute -----------------------------------
   CStrategyEngine::BandContext ctx;
   ctx.entry           = bar.close;
   ctx.direction       = direction;
   ctx.sigma_per_bar   = g_prev_sigma;
   ctx.bar_sec         = InpBarSec;
   ctx.hold_sec        = InpHoldSec;
   ctx.stop_sigma_mult = InpStopSigmaMult;
   ctx.target_sigma_mult = InpTargetSigmaMult;
   ctx.min_target_rr   = InpMinTargetRR;
   ctx.max_stop_pct    = InpMaxStopPct;
   StrategyCandidate cand = CStrategyEngine::Evaluate(STRATEGY_BAND, ctx);
   if(cand.decision == DECISION_WAIT)
      return;
   double risk_dist = MathAbs(cand.entry - cand.stop_loss);
   double rr = (risk_dist > 0.0) ? MathAbs(cand.take_profit - cand.entry) / risk_dist : 0.0;

   //--- decision layer (recorded; does not veto the aligned run) --------------------
   ScoreBreakdown sb;
   double composite = CScoringEngine::Evaluate(cand, g_regime.Regime(), -1, -1, sb);
   double out_min_conf = 0.0;
   ENUM_SIGNAL_STRENGTH verdict = CConfidenceEngine::Gate(
       composite, cand.confidence, true, direction > 0, -1, 0, 5000, out_min_conf);
   double blended = CConfidenceEngine::BlendConfidence(composite, cand.confidence);
   g_state.SetDecision(cand.decision, cand.reason_codes, composite, blended,
                       rr, STRATEGY_BAND);

   //--- stage-3 floor verdict (walk-forward; report-only in P10-A) -------------------
   int n = 0;
   double hit_rate = 0.0, avg_r = 0.0, expectancy = 0.0, avg_rr = 0.0, floor = 0.0;
   g_tqe.Statistics(STRATEGY_BAND, n, hit_rate, avg_r, expectancy, avg_rr, floor);
   g_floor_verdict = GATE_STILL_LEARNING;
   if(n >= InpFloorMinSamples)
      g_floor_verdict = (hit_rate >= floor) ? GATE_PROVEN : GATE_SUPPRESSED;
   if(InpFloorGate && g_floor_verdict == GATE_SUPPRESSED)
      return;

   //--- risk ---------------------------------------------------------------------------
   // Track equity through outcomes (Python RiskState.equity parity): the risk
   // engine's daily-loss / equity-drawdown fractions must see realized PnL, not
   // a flat 10000 pinned on every bar.
   if(g_equity <= 0.0)
      g_equity = 10000.0;
   g_risk.SyncState(g_equity, 0.0, 0.0, bar.time);
   SymbolSpec spec = g_adapter.Spec();
   if(!spec.valid)
      return;
   RiskVerdict verdict2 = g_risk.Evaluate(cand, 1.0, spec.volume_min, spec.volume_max,
                                          spec.volume_step, spec.tick_value, spec.tick_size);
   if(!verdict2.approved)
     {
      g_risk_vetoes++;
      return;
     }

   //--- execute (paper; never assume success) --------------------------------------------
   string exlog = "";
   double bid = bar.close, ask = bar.close;
   if(!g_exec.Execute(cand, verdict2, spec, bid, ask, exlog))
     {
      g_exec_rejects++;
      return;
     }
   g_tqe.StartPosition(cand, cand.entry, bar.time + InpBarSec);
   g_state.SetOpenPosition(g_exec.PositionTicket());
   g_pos_dir = direction;
   g_pos_stake = verdict2.stake;   // Python: register_open after a successful submit
   g_risk.RegisterOpen(direction);

   //--- decision journal + dashboard + signals --------------------------------------------
   g_decisions.Log(bar.time, cand.decision, STRATEGY_BAND, g_regime.Regime(),
                   verdict, blended, composite, cand.setup_quality,
                   cand.entry, cand.stop_loss, cand.take_profit, cand.reason_codes);
   if(InpDrawSignals)
      g_signals.DrawTrade(direction, bar.time + InpBarSec, cand.entry,
                          cand.stop_loss, cand.take_profit, cand.entry);
   Print(StringFormat("[MITEMSHUB] entry %s @%.5f SL=%.5f TP=%.5f RR=%.2f z=%.2f depth=%.2f (bar %I64d)",
                      direction > 0 ? "BUY" : "SELL", cand.entry, cand.stop_loss,
                      cand.take_profit, rr, z_dev, depth, g_bars_seen));

   //--- dashboard --------------------------------------------------------------------------
   if(InpDrawDashboard)
     {
      DashboardState dst;
      CDashboard::FromStateManager(g_state, _Symbol, dst);
      dst.mode       = InpLiveExecution ? ENGINE_MODE_LIVE : ENGINE_MODE_BACKTEST;
      dst.htf_bias   = (ENUM_STRUCTURE_BIAS)g_structure.Bias();
      dst.volatility = "HIGH";
      g_dash.Update(dst);
     }
  }

//+------------------------------------------------------------------+
//| OnTick — feed the aggregator; run the pipeline on bar close       |
//+------------------------------------------------------------------+
void OnTick()
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;
   if(tick.bid <= 0.0)
      return;
   AggregatedBar closed;
   if(g_agg.OnTick(tick.bid, (datetime)tick.time))
     {
      if(g_agg.ClosedBar(closed))
         ProcessOneBar(closed);
     }
  }

//+------------------------------------------------------------------+
//| OnDeinit — summary machine lines + journal close                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   int n = 0;
   double hit_rate = 0.0, avg_r = 0.0, expectancy = 0.0, avg_rr = 0.0, floor = 0.0;
   g_tqe.Statistics(STRATEGY_BAND, n, hit_rate, avg_r, expectancy, avg_rr, floor);
   int n_stop = 0, n_trail = 0, n_target = 0, n_time = 0;
   double sum_r = 0.0;
   OutcomeRecord rec;
   for(int i = 0; i < g_tqe.Count(); i++)
     {
      if(!g_tqe.GetRecord(i, rec))
         continue;
      if(rec.strategy != STRATEGY_BAND)
         continue;
      switch(rec.exit_reason)
        {
         case EXIT_STOP_HIT:         n_stop++;   break;
         case EXIT_BREAKEVEN_TRAIL:  n_trail++;  break;
         case EXIT_TARGET_HIT:       n_target++; break;
         case EXIT_TIME:             n_time++;   break;
         default: break;
        }
      sum_r += rec.return_r;
     }

   Print(StringFormat("[PHASE10] bar_sec=%d garch_mode=%d drift=%s revert=%.2f trail=%.2f grace=%s",
                      InpBarSec, InpGarchMode, InpDriftGate ? "ON" : "OFF",
                      InpMinRevertSignal, InpTrailFrac, InpClosedCandleGrace ? "ON" : "OFF"));
   Print(StringFormat("[PHASE10] trades=%d exits=stop:%d,trail:%d,target:%d,time:%d "
                      "sumR=%+.3f hit=%.2f%% avg_rr=%.2f floor=%.1f%% floor_verdict=%s "
                      "risk_vetoes=%d exec_rejects=%d",
                      n, n_stop, n_trail, n_target, n_time, sum_r, hit_rate * 100.0,
                      avg_rr, floor * 100.0,
                      g_floor_verdict == GATE_PROVEN ? "BEAT" : "NOT_BEAT",
                      g_risk_vetoes, g_exec_rejects));

   Print("[PHASE10] SUITE PASSED - P10-A integration run complete (machine lines above are the cross-validation contract)");

   g_journal.Close();
   if(g_exec != NULL)
     {
      delete g_exec;
      g_exec = NULL;
     }
   if(g_garch != NULL)
     {
      delete g_garch;
      g_garch = NULL;
     }
  }
