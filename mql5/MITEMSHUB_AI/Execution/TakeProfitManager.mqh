//+------------------------------------------------------------------+
//|                                    Execution/TakeProfitManager.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 TakeProfitManager.         |
//|                                                                  |
//|  Target geometry (plan §13): fixed-R / ATR / structure-liquidity.|
//|  Every target is validated against the planned minimum RR before |
//|  it may be sent — a target that cannot reach the break-even      |
//|  floor for its geometry is rejected at the gate, not at the      |
//|  broker.  Pure static math, testable headlessly.                 |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_EXECUTION_TAKEPROFITMANAGER_MQH
#define MITEMSHUB_EXECUTION_TAKEPROFITMANAGER_MQH

#include "../Core/Constants.mqh"

class CTakeProfitManager
  {
public:
   //--- Fixed-R target: entry ± rr × |entry-stop| ----------------------------
   static double FixedR(const double entry, const double stop, const double rr)
     {
      double risk = MathAbs(entry - stop);
      if(entry <= 0.0 || risk <= 0.0 || rr <= 0.0)
         return(0.0);
      return(entry > stop ? entry + rr * risk : entry - rr * risk);
     }

   //--- ATR target: entry ± mult × atr ---------------------------------------
   static double AtrTarget(const double entry, const int direction,
                           const double atr, const double mult)
     {
      if(entry <= 0.0 || atr <= 0.0 || mult <= 0.0)
         return(0.0);
      return(direction > 0 ? entry + mult * atr : entry - mult * atr);
     }

   //--- Structure / liquidity target: an explicit level ----------------------
   static double LevelTarget(const double level)
     {
      return(level > 0.0 ? level : 0.0);
     }

   //--- Planned-RR guard -----------------------------------------------------
   // Returns false when the geometry cannot reach the minimum RR — the setup
   // is not tradeable regardless of what the broker would accept.
   static bool MeetsMinRR(const double entry, const double stop,
                          const double target, const double min_rr)
     {
      double risk   = MathAbs(entry - stop);
      double reward = MathAbs(target - entry);
      if(risk <= 0.0 || reward <= 0.0)
         return(false);                  // degenerate geometry — never send
      if(min_rr <= 0.0)
         return(true);                   // no gate configured
      return(reward / risk >= min_rr);
     }

  };

#endif // MITEMSHUB_EXECUTION_TAKEPROFITMANAGER_MQH
