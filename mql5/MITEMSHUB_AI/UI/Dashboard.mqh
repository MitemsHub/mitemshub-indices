//+------------------------------------------------------------------+
//|                                       UI/Dashboard.mqh           |
//|  MITEMSHUB AI MARKET ENGINE — Phase 9 Dashboard.                 |
//|                                                                  |
//|  The plan §34 chart dashboard: one fixed-format block on the     |
//|  chart showing SYMBOL / MODE / REGIME / CONFIDENCE / HTF BIAS /  |
//|  STRUCTURE / VOLATILITY / ACTIVE STRATEGY / SETUP SCORE /        |
//|  EXPECTED RR / DECISION / RISK / SL / TP / OPEN POSITIONS /      |
//|  TODAY / DRAWDOWN plus a REASON line and an EMERGENCY_STOP       |
//|  banner when a hard safety limit is breached.                    |
//|                                                                  |
//|  Layout is a fixed table of OBJ_LABEL rows over a rectangle      |
//|  background — object count is CONSTANT (CDashboard::Create()     |
//|  creates exactly ExpectedObjects() objects once; Update() only   |
//|  rewrites text), so the object-count gate is trivially stable.   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_UI_DASHBOARD_MQH
#define MITEMSHUB_UI_DASHBOARD_MQH

#include "../Core/Constants.mqh"
#include "../Core/StateManager.mqh"
#include "Panel.mqh"

//--- §34 row order (each row is one label: "LABEL: value") ---------------
//--- ROW0..ROW16: SYMBOL, MODE, REGIME, HTF BIAS, STRUCTURE, VOLATILITY,
//--- STRATEGY, SETUP SCORE, EXPECTED RR, DECISION, RISK, SL, TP,          
//--- OPEN POSITIONS, TODAY, DRAWDOWN, REASON.                             
#define DASH_ROWS 17
//--- panel geometry (MQL5 forbids in-class static const members → #define) ---
#define DASH_X       12
#define DASH_Y       24
#define DASH_ROW_H   15
#define DASH_W       250
#define DASH_H       (DASH_Y + DASH_ROWS * DASH_ROW_H + 12)

struct DashboardState
  {
   string             symbol;
   ENUM_ENGINE_MODE   mode;
   ENUM_REGIME        regime;
   double             regime_conf;       // 0..1
   ENUM_STRUCTURE_BIAS htf_bias;
   ENUM_STRUCTURE_BIAS structure_bias;
   string             volatility;        // "NORMAL" / "HIGH" / "LOW" / "EXPANDING"
   ENUM_STRATEGY      strategy;
   double             setup_score;       // 0..100
   double             expected_rr;
   ENUM_DECISION      decision;
   double             risk_pct;          // % of equity at risk
   double             sl;
   double             tp;
   int                open_positions;
   double             today_r;           // today's P/L in R
   double             drawdown_pct;      // % drawdown
   string             reason;            // decision reason trail
   bool               hard_halt;         // EMERGENCY_STOP banner

   void Reset()
     {
      symbol        = "R_75";
      mode          = ENGINE_MODE_BACKTEST;
      regime        = REGIME_UNKNOWN;
      regime_conf   = 0.0;
      htf_bias      = STRUCT_BIAS_NEUTRAL;
      structure_bias= STRUCT_BIAS_NEUTRAL;
      volatility    = "NORMAL";
      strategy      = STRATEGY_NONE;
      setup_score   = 0.0;
      expected_rr   = 0.0;
      decision      = DECISION_WAIT;
      risk_pct      = 0.0;
      sl            = 0.0;
      tp            = 0.0;
      open_positions= 0;
      today_r       = 0.0;
      drawdown_pct  = 0.0;
      reason        = "";
      hard_halt     = false;
     }
  };

class CDashboard : public CUiPanel
  {
protected:
   int   RowY(const int row) const  { return(DASH_Y + row * DASH_ROW_H); }
   color DecisionColor(const ENUM_DECISION decision) const
     {
      if(decision == DECISION_BUY)
         return(clrLime);
      if(decision == DECISION_SELL)
         return(clrTomato);
      return(clrSilver);
     }
   color RegimeColor(const ENUM_REGIME regime) const
     {
      if(regime == REGIME_TREND_UP)
         return(clrLime);
      if(regime == REGIME_TREND_DOWN)
         return(clrTomato);
      if(regime == REGIME_COMPRESSION)
         return(clrYellow);
      if(regime == REGIME_EXPANSION || regime == REGIME_HIGH_VOLATILITY)
         return(clrOrange);
      if(regime == REGIME_TRANSITION)
         return(clrMagenta);
      return(clrSilver);
     }

public:
   //--- object-name constants (created once in Create()) --------------------
   static string ObjBG()     { return("BG"); }
   static string ObjTitle()  { return("TITLE"); }
   static string ObjHalt()   { return("HALT"); }
   static string ObjRow(const int i)
     {
      return("ROW" + IntegerToString(i));
     }

   static int ExpectedObjects()
     {
      // BG + TITLE + HALT banner + DASH_ROWS data rows
      return(3 + DASH_ROWS);
     }

   //--- create the fixed table (idempotent, bounded, one-time) --------------
   void Create()
     {
      if(Count() > 0)
         return;
      // Background rectangle behind everything.
      CreateObject(ObjBG(), OBJ_RECTANGLE_LABEL);
      SetInt(ObjBG(), OBJPROP_XDISTANCE, DASH_X - 6);
      SetInt(ObjBG(), OBJPROP_YDISTANCE, DASH_Y - 20);
      SetInt(ObjBG(), OBJPROP_XSIZE, DASH_W);
      SetInt(ObjBG(), OBJPROP_YSIZE, DASH_H - DASH_Y + 22);
      SetInt(ObjBG(), OBJPROP_BGCOLOR, clrBlack);
      SetInt(ObjBG(), OBJPROP_BORDER_COLOR, clrDimGray);
      SetInt(ObjBG(), OBJPROP_BACK, true);

      // Title banner.
      CreateObject(ObjTitle(), OBJ_LABEL);
      MoveTo(ObjTitle(), DASH_X, DASH_Y - 16);
      SetText(ObjTitle(), "MITEMSHUB AI MARKET ENGINE", clrWhite, 10, true);

      // Hard-halt banner (text toggled by Update).
      CreateObject(ObjHalt(), OBJ_LABEL);
      MoveTo(ObjHalt(), DASH_X, DASH_H - 2);
      SetText(ObjHalt(), "", clrRed, 9, true);

      // Data rows.
      for(int i = 0; i < DASH_ROWS; i++)
        {
         CreateObject(ObjRow(i), OBJ_LABEL);
         MoveTo(ObjRow(i), DASH_X, RowY(i));
         SetText(ObjRow(i), "", clrSilver, 9);
        }
     }

   //--- render one state snapshot (text-only updates; no new objects) -------
   void Update(const DashboardState &st)
     {
      if(Count() == 0)
         Create();

      // The REGIME row is color-coded by the regime itself.
      string regime_text = StringFormat("%s  (%.0f%%)",
                                        RegimeToString(st.regime),
                                        100.0 * st.regime_conf);
      SetText(ObjRow(2), "REGIME: " + regime_text, RegimeColor(st.regime), 9);

      // The DECISION row is color-coded BUY green / SELL red / WAIT gray.
      string decision_text = DecisionToString(st.decision);
      SetText(ObjRow(9), "DECISION: " + decision_text, DecisionColor(st.decision), 9, true);

      // All remaining rows are neutral silver.
      SetText(ObjRow(0), "SYMBOL: " + UITruncate(st.symbol, 24), clrSilver, 9);
      SetText(ObjRow(1), "MODE: " + EngineModeToString(st.mode), clrSilver, 9);
      SetText(ObjRow(3), "HTF BIAS: " + StructureBiasToString(st.htf_bias), clrSilver, 9);
      SetText(ObjRow(4), "STRUCTURE: " + StructureBiasToString(st.structure_bias), clrSilver, 9);
      SetText(ObjRow(5), "VOLATILITY: " + UITruncate(st.volatility, 24), clrSilver, 9);
      SetText(ObjRow(6), "STRATEGY: " + StrategyToString(st.strategy), clrSilver, 9);
      SetText(ObjRow(7), StringFormat("SETUP SCORE: %.0f/100", st.setup_score), clrSilver, 9);
      SetText(ObjRow(8), StringFormat("EXPECTED RR: %.1f", st.expected_rr), clrSilver, 9);
      SetText(ObjRow(10), StringFormat("RISK: %.2f%%", st.risk_pct), clrSilver, 9);
      SetText(ObjRow(11), StringFormat("SL: %.2f", st.sl), clrSilver, 9);
      SetText(ObjRow(12), StringFormat("TP: %.2f", st.tp), clrSilver, 9);
      SetText(ObjRow(13), StringFormat("OPEN POSITIONS: %d", st.open_positions), clrSilver, 9);
      SetText(ObjRow(14), StringFormat("TODAY: %+.2f R", st.today_r), clrSilver, 9);
      SetText(ObjRow(15), StringFormat("DRAWDOWN: %.1f%%", st.drawdown_pct), clrSilver, 9);
      SetText(ObjRow(16), "REASON: " + UITruncate(st.reason), clrSilver, 8);

      // Emergency banner (empty text = hidden).
      if(st.hard_halt)
         SetText(ObjHalt(), "EMERGENCY_STOP - TRADING DISABLED", clrRed, 9, true);
      else
         SetText(ObjHalt(), "", clrRed, 9, true);

      if(m_created > 0)
         ChartRedraw(m_chart);
     }

   //--- convenience: pull whatever CStateManager already holds ---------------
   // Note: CStateManager::Daily() is non-const, so st cannot be const here.
   static void FromStateManager(CStateManager &st, const string symbol,
                                DashboardState &out)
     {
      out.Reset();
      out.symbol          = symbol;
      out.regime          = st.Regime();
      out.regime_conf     = st.RegimeConfidence();
      out.strategy        = st.ActiveStrategy();
      out.setup_score     = st.LastScore();
      out.expected_rr     = st.LastExpectedRR();
      out.decision        = st.LastDecision();
      out.reason          = st.LastDecisionReason();
      out.open_positions  = st.HasOpenPosition() ? 1 : 0;
      out.hard_halt       = st.HardHalt();
      DailyStats d        = st.Daily();
      out.today_r         = d.realized_pnl_today;
      out.drawdown_pct    = d.max_daily_drawdown_pct;
      out.risk_pct        = (d.day_start_equity > 0.0)
                            ? 100.0 * MathAbs(d.realized_pnl_today) / d.day_start_equity
                            : 0.0;
     }
  };

#endif // MITEMSHUB_UI_DASHBOARD_MQH
