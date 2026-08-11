//+------------------------------------------------------------------+
//|                                      Core/StateManager.mqh       |
//|  MITEMSHUB AI MARKET ENGINE — single source of truth for engine  |
//|  state.                                                          |
//|                                                                  |
//|  One instance, owned by the Engine.  Every pipeline stage reads   |
//|  and writes state here; nothing else keeps mutable engine state.  |
//|  This prevents the classic EA bug of two modules disagreeing     |
//|  about the current regime/position because each cached its own.  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CORE_STATEMANAGER_MQH
#define MITEMSHUB_CORE_STATEMANAGER_MQH

#include "Constants.mqh"

//--- Daily statistics (reset on session day change) --------------------------
struct DailyStats
  {
   int      session_day;          // day index (TimeCurrent()/86400) when seeded
   int      trades_today;
   int      consecutive_losses;
   double   day_start_balance;
   double   day_start_equity;
   double   realized_pnl_today;
   double   peak_equity_today;
   double   max_daily_drawdown_pct;

   void Init()
     {
      session_day          = 0;
      trades_today         = 0;
      consecutive_losses   = 0;
      day_start_balance    = 0.0;
      day_start_equity     = 0.0;
      realized_pnl_today   = 0.0;
      peak_equity_today    = 0.0;
      max_daily_drawdown_pct = 0.0;
     }
  };

//--- The engine state --------------------------------------------------------
class CStateManager
  {
private:
   ENUM_REGIME          m_regime;
   double               m_regime_confidence;
   ENUM_DECISION        m_last_decision;
   string               m_last_decision_reason;
   ENUM_STRATEGY        m_active_strategy;
   double               m_last_score;         // 0..100
   double               m_last_confidence;    // 0..1
   double               m_last_expected_rr;
   long                 m_open_position_ticket;
   DailyStats           m_daily;
   bool                 m_hard_halt;          // any hard limit breached

public:
   CStateManager()
     {
      Reset();
     }

   void Reset()
     {
      m_regime             = REGIME_UNKNOWN;
      m_regime_confidence  = 0.0;
      m_last_decision      = DECISION_WAIT;
      m_last_decision_reason = "";
      m_active_strategy    = STRATEGY_NONE;
      m_last_score         = 0.0;
      m_last_confidence    = 0.0;
      m_last_expected_rr   = 0.0;
      m_open_position_ticket = 0;
      m_hard_halt          = false;
      m_daily.Init();
     }

   //--- regime ---
   void        SetRegime(const ENUM_REGIME regime, const double confidence)
     {
      m_regime = regime;
      m_regime_confidence = confidence;
     }
   ENUM_REGIME Regime() const              { return(m_regime); }
   double      RegimeConfidence() const    { return(m_regime_confidence); }

   //--- decision ---
   void SetDecision(const ENUM_DECISION decision, const string reason,
                    const double score, const double confidence,
                    const double expected_rr, const ENUM_STRATEGY strategy)
     {
      m_last_decision        = decision;
      m_last_decision_reason = reason;
      m_last_score           = score;
      m_last_confidence      = confidence;
      m_last_expected_rr     = expected_rr;
      m_active_strategy      = strategy;
     }
   ENUM_DECISION LastDecision() const          { return(m_last_decision); }
   string        LastDecisionReason() const    { return(m_last_decision_reason); }
   double        LastScore() const             { return(m_last_score); }
   double        LastConfidence() const        { return(m_last_confidence); }
   double        LastExpectedRR() const        { return(m_last_expected_rr); }
   ENUM_STRATEGY ActiveStrategy() const        { return(m_active_strategy); }

   //--- position ---
   void SetOpenPosition(const long ticket)     { m_open_position_ticket = ticket; }
   long OpenPositionTicket() const             { return(m_open_position_ticket); }
   bool HasOpenPosition() const                { return(m_open_position_ticket != 0); }

   //--- hard halt ---
   void SetHardHalt(const bool halted)         { m_hard_halt = halted; }
   bool HardHalt() const                       { return(m_hard_halt); }

   //--- daily stats ---
   // Note: MQL5 forbids pointer/reference return types — return a copy.
   DailyStats Daily()                          { return(m_daily); }
   bool SessionDayChanged()
     {
      int today = (int)(TimeCurrent() / 86400);
      return(today != m_daily.session_day);
     }
   void SeedDay(const double balance, const double equity)
     {
      m_daily.session_day        = (int)(TimeCurrent() / 86400);
      m_daily.day_start_balance  = balance;
      m_daily.day_start_equity   = equity;
      m_daily.peak_equity_today  = equity;
      m_daily.realized_pnl_today = 0.0;
      m_daily.trades_today       = 0;
      m_daily.consecutive_losses = 0;
      m_daily.max_daily_drawdown_pct = 0.0;
     }
  };

#endif // MITEMSHUB_CORE_STATEMANAGER_MQH
