//+------------------------------------------------------------------+
//|                                        Execution/StopManager.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 7 StopManager.               |
//|                                                                  |
//|  Stop-loss geometry — NO arbitrary fixed-point stops (plan §13). |
//|  Every stop derives from a measurable quantity (ATR, structure,  |
//|  volatility fraction) and every stop is validated against the    |
//|  broker's stops-level before it may be sent.  Pure static math,  |
//|  testable headlessly (same pattern as Phase-6 PositionSizer).    |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_EXECUTION_STOPMANAGER_MQH
#define MITEMSHUB_EXECUTION_STOPMANAGER_MQH

#include "../Core/Constants.mqh"

class CStopManager
  {
public:
   //--- ATR-multiple stop: entry ∓ mult × atr (direction +1 long, -1 short) --
   // Degenerate inputs (atr/mult <= 0) return 0.0 — the caller must reject.
   static double AtmStop(const double entry, const int direction,
                         const double atr, const double mult)
     {
      if(entry <= 0.0 || atr <= 0.0 || mult <= 0.0)
         return(0.0);
      return(direction > 0 ? entry - mult * atr : entry + mult * atr);
     }

   //--- Structure stop: a swing/liquidity level plus an ATR tolerance -------
   // Place the stop just BEYOND the level so a wick to it does not stop out
   // the structure thesis (the level is the trigger, not the stop).
   static double StructureStop(const double level, const int direction,
                               const double atr, const double tol_atr)
     {
      if(level <= 0.0)
         return(0.0);
      double tol = MathMax(atr, 0.0) * MathMax(tol_atr, 0.0);
      return(direction > 0 ? level - tol : level + tol);
     }

   //--- Volatility stop: a fixed fraction of price (max-stop guard) ---------
   static double VolatilityStop(const double entry, const int direction,
                                const double frac)
     {
      if(entry <= 0.0 || frac <= 0.0)
         return(0.0);
      return(direction > 0 ? entry * (1.0 - frac) : entry * (1.0 + frac));
     }

   //--- Distance between entry and stop, in points ---------------------------
   static double DistancePoints(const double entry, const double stop,
                                const double point)
     {
      return(point > 0.0 ? MathAbs(entry - stop) / point : 0.0);
     }

   //--- Broker min-distance check (SYMBOL_TRADE_STOPS_LEVEL) -----------------
   // stops_level <= 0 means the broker has no minimum — always allowed.
   static bool MeetsStopsLevel(const double entry, const double stop,
                               const double point, const long stops_level)
     {
      if(stops_level <= 0 || point <= 0.0)
         return(true);
      return(DistancePoints(entry, stop, point) >= (double)stops_level);
     }

   //--- Effective stop after a breakeven trail arms: entry, else the original
   static double EffectiveStop(const bool trail_armed, const double entry,
                               const double stop)
     {
      return(trail_armed ? entry : stop);
     }
  };

#endif // MITEMSHUB_EXECUTION_STOPMANAGER_MQH
