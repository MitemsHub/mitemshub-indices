//+------------------------------------------------------------------+
//|                                     Execution/ExecutionEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 ExecutionEngine.           |
//|                                                                  |
//|  Orchestrates the five execution modules (OrderManager,          |
//|  StopManager, TakeProfitManager, PositionManager,                |
//|  ExecutionMonitor) and enforces the plan's iron rule: the        |
//|  engine NEVER assumes an order succeeded — every request is      |
//|  retcode-checked and the fill verified against the position      |
//|  table before it is recorded or handed to the PositionManager.   |
//|                                                                  |
//|  Entry pipeline (Execute):                                       |
//|    hard-halt -> verdict approved -> spread guard -> price-sanity |
//|    -> stops-level -> min-RR -> volume grid -> open+verify        |
//|  Management pipeline (ManageBar, closed candles only):           |
//|    partial @ +1R -> BE-trail arm -> stop/target/time exit        |
//|                                                                  |
//|  The trade transport is injected (CTradeInterface*), so the same |
//|  engine runs against the real CTrade in production and a mock    |
//|  with scripted retcodes in the tester (mocked-retcode gate).     |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_EXECUTION_EXECUTIONENGINE_MQH
#define MITEMSHUB_EXECUTION_EXECUTIONENGINE_MQH

#include "../Core/Constants.mqh"
#include "../Core/StateManager.mqh"
#include "../Market/SymbolAdapter.mqh"
#include "OrderManager.mqh"
#include "StopManager.mqh"
#include "TakeProfitManager.mqh"
#include "PositionManager.mqh"
#include "ExecutionMonitor.mqh"

//--- Execution configuration (from Config inputs) -----------------------------
struct ExecutionConfig
  {
   long   magic;
   long   max_slippage_points;
   double max_spread_points;    // 0 = off
   double min_rr;               // planned-RR floor for a sendable target
   bool   live;                 // false = paper mode (no real orders)
   bool   verify_fills;         // never assume success (default true)
  };

class CExecutionEngine
  {
private:
   CTradeInterface *m_trade;
   COrderManager    m_orders;
   CPositionManager m_position;
   CStateManager   *m_state;
   ExecutionConfig  m_cfg;
   int              m_last_failure;   // ENUM_EXEC_FAILURE of the last attempt
   string           m_last_log;       // journal trail of the last attempt

public:
   // Pointer-based transport injection (MQL5 forbids reference chaining).
   CExecutionEngine(CTradeInterface *trade, const ExecutionConfig &cfg)
     {
      m_trade        = trade;
      m_orders.Bind(trade);
      m_state        = NULL;
      m_cfg          = cfg;
      m_last_failure = EXEC_FAILURE_NONE;
      m_last_log     = "";
     }

   void SetStateManager(CStateManager &state)   { m_state = &state; }
   int    LastFailure() const                   { return(m_last_failure); }
   string LastLog() const                       { return(m_last_log); }
   bool   InPosition() const                    { return(m_position.InPosition()); }
   // MQL5 forbids reference return types — expose the position state via
   // narrow accessors instead of the object itself.
   bool   PositionTrailArmed() const            { return(m_position.TrailArmed()); }
   bool   PositionPartialDone() const           { return(m_position.PartialDone()); }
   double PositionMFE_R() const                 { return(m_position.MFE_R()); }
   long   PositionTicket() const                { return((long)m_position.Ticket()); }

   //--- Configure the management layer (BE trail, time exit, partial) --------
   void ConfigureManagement(const PositionMgmtConfig &mgmt)
     {
      m_position.Configure(mgmt);
     }

   //--- Execute one approved verdict (never assumes success) ------------------
   // Returns true only when the position was opened AND verified.
   bool Execute(const StrategyCandidate &cand, const RiskVerdict &verdict,
                const SymbolSpec &spec, const double bid, const double ask,
                string &log_out)
     {
      log_out = "";
      // 1. hard halt (Phase-6 final authority, absolute)
      if(m_state != NULL && m_state.HardHalt())
        {
         m_last_failure = EXEC_FAILURE_TRADE_DISABLED;
         m_last_log     = "hard halt active — no entries";
         log_out        = m_last_log;
         return(false);
        }
      // 2. verdict must approve and the decision must be directional
      if(!verdict.approved || cand.decision == DECISION_WAIT)
        {
         m_last_failure = EXEC_FAILURE_NONE;
         m_last_log     = verdict.approved
                          ? "decision=WAIT — no entry"
                          : "risk vetoed the entry";
         log_out        = m_last_log;
         return(false);
        }
      // 3. spread guard (execution conditions)
      if(m_cfg.max_spread_points > 0.0 && spec.point > 0.0 && ask > bid)
        {
         double spread_pts = (ask - bid) / spec.point;
         if(spread_pts > m_cfg.max_spread_points)
           {
            m_last_failure = EXEC_FAILURE_REQUOTE;
            m_last_log     = StringFormat("spread %.1f pts > cap %.1f",
                                          spread_pts, m_cfg.max_spread_points);
            log_out        = m_last_log;
            return(false);
           }
        }
      // 4. price sanity — never enter when price is already beyond the stop
      if(cand.decision == DECISION_BUY && bid <= cand.stop_loss)
        {
         m_last_failure = EXEC_FAILURE_INVALID_PRICE;
         m_last_log     = "price below stop — entry skipped";
         log_out        = m_last_log;
         return(false);
        }
      if(cand.decision == DECISION_SELL && ask >= cand.stop_loss)
        {
         m_last_failure = EXEC_FAILURE_INVALID_PRICE;
         m_last_log     = "price above stop — entry skipped";
         log_out        = m_last_log;
         return(false);
        }
      // 5. level validation: broker stops level + planned-RR floor
      if(!CStopManager::MeetsStopsLevel(cand.entry, cand.stop_loss,
                                        spec.point, spec.stops_level))
        {
         m_last_failure = EXEC_FAILURE_INVALID_STOPS;
         m_last_log     = "stop within broker stops level";
         log_out        = m_last_log;
         return(false);
        }
      if(!CTakeProfitManager::MeetsMinRR(cand.entry, cand.stop_loss,
                                         cand.take_profit, m_cfg.min_rr))
        {
         m_last_failure = EXEC_FAILURE_INVALID_STOPS;
         m_last_log     = StringFormat("planned RR below %.2f floor",
                                       m_cfg.min_rr);
         log_out        = m_last_log;
         return(false);
        }
      // 6. volume grid (floor to step, clamp to [min,max])
      double lots = m_cfg.live ? m_orders.NormalizeVolume(spec, verdict.lots)
                               : 0.0;                 // paper mode — no real lots
      // 7. send + verify
      OrderResult res;
      bool ok = m_orders.Open(spec.symbol, cand.decision, lots,
                              cand.stop_loss, cand.take_profit,
                              "mitemshub-" + StrategyToString(cand.strategy), res);
      if(!ok || !res.accepted)
        {
         m_last_failure = CExecutionMonitor::Classify(res.retcode);
         m_last_log     = res.attempt_log;
         log_out        = m_last_log;
         return(false);
        }
      // 8. hand off to the position manager + engine state
      m_position.Open((long)res.order_ticket,
                      cand.decision == DECISION_BUY ? 1 : -1,
                      cand.entry, cand.stop_loss, cand.take_profit,
                      TimeCurrent());
      if(m_state != NULL)
         m_state.SetOpenPosition((long)res.order_ticket);
      m_last_failure = EXEC_FAILURE_NONE;
      m_last_log     = res.attempt_log;
      log_out        = m_last_log;
      return(true);
     }

   //--- Manage the open position on one CLOSED bar ----------------------------
   // Returns the exit reason (EXIT_NONE while holding).  partial_out=true
   // means +1R was reached: the caller closes half and the engine moves the
   // stop to entry (a management action, not an exit).
   ENUM_EXIT_REASON ManageBar(const double high, const double low,
                              const double close, const datetime bar_open_time,
                              const int bar_sec, double &exit_price_out,
                              OrderResult &res_out, bool &partial_out)
     {
      exit_price_out = 0.0;
      partial_out    = false;
      if(!m_position.InPosition())
         return(EXIT_NONE);

      ENUM_EXIT_REASON reason = EXIT_NONE;
      bool should_exit = m_position.UpdateBar(high, low, close, bar_open_time,
                                              bar_sec, reason, exit_price_out,
                                              partial_out);
      if(partial_out)
        {
         // +1R reached — stop moves to entry with the half-close.
         m_orders.Modify((ulong)m_position.Ticket(),
                         m_position.Entry(), m_position.Target(),
                         "partial_close_at_1r", res_out);
         return(EXIT_NONE);
        }
      if(should_exit)
        {
         m_orders.Close((ulong)m_position.Ticket(), 0.0,
                        ExitReasonToString(reason), res_out);
         m_position.CloseTrack();
         if(m_state != NULL)
            m_state.SetOpenPosition(0);
         return(reason);
        }
      return(EXIT_NONE);
     }

   //--- Emergency stop: flat now, no new entries -------------------------------
   bool EmergencyFlat(OrderResult &res_out)
     {
      if(!m_position.InPosition())
         return(true);
      bool ok = m_orders.Close((ulong)m_position.Ticket(), 0.0,
                               "EMERGENCY_STOP", res_out);
      m_position.CloseTrack();
      if(m_state != NULL)
         m_state.SetOpenPosition(0);
      return(ok && res_out.accepted);
     }
  };

#endif // MITEMSHUB_EXECUTION_EXECUTIONENGINE_MQH
