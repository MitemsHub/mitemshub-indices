//+------------------------------------------------------------------+
//| Decision/TradeQualityEngine.mqh                                  |
//|  MITEMSHUB AI MARKET ENGINE — Phase 5 TradeQualityEngine.        |
//|                                                                  |
//|  Tracks the R-multiple anatomy of every trade the plan requires: |
//|  entry/stop/target, MAE and MFE (in R), +1R/+2R/+3R reached,     |
//|  time to target / time to stop, hold duration, exit reason, and  |
//|  the regime/strategy that produced the setup.  Statistics answer |
//|  "is this setup historically favorable relative to its           |
//|  invalidation?" — per strategy: n, hit rate, avg R, expectancy,  |
//|  avg planned RR, and the empirical break-even hit-rate floor     |
//|  (the exact stage3_gate.break_even_floor math: 1/(1+rr)+margin,  |
//|  clamped [0.10, 0.60], fallback 0.50 when RR unknown).           |
//|                                                                  |
//|  Realized-R math is the Python PaperBroker's (_close_at_price):  |
//|    risk_distance = |entry - stop|  (fallback entry*0.001 if 0)   |
//|    long:  return_r = (exit - entry) / risk_distance              |
//|    short: return_r = (entry - exit) / risk_distance              |
//|    won   = return_r > 0                                          |
//|  MAE/MFE use intrabar extremes between open and close.           |
//|                                                                  |
//|  No order-filling logic here — the engine only observes.  It is  |
//|  fed by StartPosition()/UpdatePosition()/ClosePosition() from    |
//|  the execution layer (Phase 7) or the backtest loop.             |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_DECISION_TRADE_QUALITY_ENGINE_MQH
#define MITEMSHUB_DECISION_TRADE_QUALITY_ENGINE_MQH

#include "../Core/Constants.mqh"

//--- stage3_gate.py defaults (locked by the parity gate) ----------------------
#define GATE_HIT_RATE_FLOOR_DEFAULT  0.50
#define BREAK_EVEN_MARGIN_DEFAULT    0.05
#define BREAK_EVEN_FLOOR_MIN_DEFAULT 0.10
#define BREAK_EVEN_FLOOR_MAX_DEFAULT 0.60

#define MAX_OUTCOME_RECORDS 2000

class CTradeQualityEngine
  {
private:
   OutcomeRecord g_records[MAX_OUTCOME_RECORDS];
   int           g_count;

   //--- open-position observation state
   bool       g_in_pos;
   int        g_dir;
   double     g_entry;
   double     g_stop;
   double     g_target;
   double     g_risk_distance;
   double     g_mfe_r;
   double     g_mae_r;
   int        g_hold_bars;
   datetime   g_opened_at;
   ENUM_STRATEGY g_strategy;
   ENUM_REGIME   g_regime;

public:
   CTradeQualityEngine()
     {
      g_count = 0;
      g_in_pos = false;
     }

   void Reset()
     {
      g_count = 0;
      g_in_pos = false;
     }

   int Count() const { return g_count; }

   //--- read-only access to a journaled outcome (for tests / analytics)
   bool GetRecord(const int i, OutcomeRecord &out) const
     {
      if(i < 0 || i >= g_count)
         return false;
      out = g_records[i];
      return true;
     }

   //--- Exact port of stage3_gate.break_even_floor(rr, margin). ---------------
   static double BreakEvenFloor(const double reward_risk, const double margin)
     {
      if(reward_risk <= 0.0)
         return GATE_HIT_RATE_FLOOR_DEFAULT;
      double m = (margin >= 0.0) ? margin : BREAK_EVEN_MARGIN_DEFAULT;
      double raw = 1.0 / (1.0 + reward_risk) + m;
      return MathMax(BREAK_EVEN_FLOOR_MIN_DEFAULT,
                     MathMin(raw, BREAK_EVEN_FLOOR_MAX_DEFAULT));
     }

   //--- Open a new position observation.  cand: the StrategyCandidate that
   //--- produced the setup; entry: the fill price (signal close).
   void StartPosition(const StrategyCandidate &cand, const double entry,
                      const datetime opened_at)
     {
      g_in_pos = true;
      g_dir = (cand.decision == DECISION_BUY) ? 1 : -1;
      g_entry = (entry > 0.0) ? entry : cand.entry;
      g_stop = cand.stop_loss;
      g_target = cand.take_profit;
      g_risk_distance = MathAbs(g_entry - g_stop);
      if(g_risk_distance <= 0.0)
         g_risk_distance = g_entry * 0.001;
      g_mfe_r = 0.0;
      g_mae_r = 0.0;
      g_hold_bars = 0;
      g_opened_at = opened_at;
      g_strategy = cand.strategy;
      g_regime = cand.required_regime;
     }

   //--- Feed each subsequent bar's extreme prices; tracks MAE/MFE in R.
   void UpdatePosition(const double bar_high, const double bar_low)
     {
      if(!g_in_pos)
         return;
      g_hold_bars++;
      if(g_dir > 0)
        {
         double mfe = (bar_high - g_entry) / g_risk_distance;
         double mae = (g_entry - bar_low) / g_risk_distance;
         if(mfe > g_mfe_r) g_mfe_r = mfe;
         if(mae > g_mae_r) g_mae_r = mae;
        }
      else
        {
         double mfe = (g_entry - bar_low) / g_risk_distance;
         double mae = (bar_high - g_entry) / g_risk_distance;
         if(mfe > g_mfe_r) g_mfe_r = mfe;
         if(mae > g_mae_r) g_mae_r = mae;
        }
     }

   //--- Close the observation and journal the OutcomeRecord.  Returns the
   //--- realized R (Python PaperBroker math).
   double ClosePosition(const double exit_price, const ENUM_EXIT_REASON reason,
                        const datetime closed_at)
     {
      if(!g_in_pos)
         return 0.0;
      double return_r = 0.0;
      if(g_dir > 0)
         return_r = (exit_price - g_entry) / g_risk_distance;
      else
         return_r = (g_entry - exit_price) / g_risk_distance;

      if(g_count < MAX_OUTCOME_RECORDS)
        {
         OutcomeRecord r;
         r.strategy      = g_strategy;
         r.regime        = g_regime;
         r.direction     = g_dir;
         r.entry         = g_entry;
         r.stop_loss     = g_stop;
         r.take_profit   = g_target;
         r.exit_price    = exit_price;
         r.risk_distance = g_risk_distance;
         r.reward_risk   = (g_risk_distance > 0.0)
                           ? MathAbs(g_target - g_entry) / g_risk_distance : 0.0;
         r.return_r      = return_r;
         r.mae_r         = g_mae_r;
         r.mfe_r         = g_mfe_r;
         r.r1_reached    = g_mfe_r >= 1.0;
         r.r2_reached    = g_mfe_r >= 2.0;
         r.r3_reached    = g_mfe_r >= 3.0;
         r.opened_at     = g_opened_at;
         r.closed_at     = closed_at;
         r.hold_bars     = g_hold_bars;
         r.exit_reason   = reason;
         r.won           = return_r > 0.0;
         g_records[g_count++] = r;
        }
      g_in_pos = false;
      return return_r;
     }

   //--- Per-strategy statistics: n, hit rate, avg R, expectancy, avg planned
   //--- RR, break-even floor.  strategy STRATEGY_NONE = all strategies.
   //--- Returns false when there are no closed outcomes to aggregate.
   bool Statistics(const ENUM_STRATEGY strategy,
                   int &n, double &hit_rate, double &avg_r,
                   double &expectancy, double &avg_rr, double &break_even) const
     {
      n = 0;
      double sum_r = 0.0, sum_rr = 0.0;
      int wins = 0;
      for(int i = 0; i < g_count; i++)
        {
         if(strategy != STRATEGY_NONE && g_records[i].strategy != strategy)
            continue;
         n++;
         sum_r += g_records[i].return_r;
         sum_rr += g_records[i].reward_risk;
         if(g_records[i].won)
            wins++;
        }
      if(n == 0)
        {
         hit_rate = 0.0; avg_r = 0.0; expectancy = 0.0; avg_rr = 0.0;
         break_even = GATE_HIT_RATE_FLOOR_DEFAULT;
         return false;
        }
      hit_rate = (double)wins / (double)n;
      avg_r = sum_r / (double)n;
      expectancy = avg_r;                       // R per trade (gross)
      avg_rr = sum_rr / (double)n;
      break_even = BreakEvenFloor(avg_rr, BREAK_EVEN_MARGIN_DEFAULT);
      return true;
     }
  };

#endif // MITEMSHUB_DECISION_TRADE_QUALITY_ENGINE_MQH
