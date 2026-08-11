//+------------------------------------------------------------------+
//|                                    Structure/LiquidityEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — liquidity sweep detection.         |
//|                                                                  |
//|  Swing highs hold buy-side liquidity (resting stop-buys above),  |
//|  swing lows hold sell-side liquidity.  A SWEEP is a wick that    |
//|  takes the level out (by at least min_exceed_atr × ATR, so a     |
//|  one-tick spike can't trigger it) and then CLOSES back inside —  |
//|  the price rejected the level instead of breaking it.  Sweeps    |
//|  above a swing high are bearish intent (direction -1); sweeps    |
//|  below a swing low are bullish intent (+1).                      |
//|                                                                  |
//|  Only the MOST RECENT swing of each polarity is swept (the same  |
//|  reference the Python market_structure features use:             |
//|  recent_high / recent_low).  Sweeping a stale level from the     |
//|  middle of the window is not a meaningful event — on the real    |
//|  R_75 corpus, scanning every historical level fired a sweep in   |
//|  every 100-bar window (448/448), which carries no information.   |
//|  This restriction is the Phase-3 real-corpus reconciliation      |
//|  (see README "Phase 3 — Structure").                            |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_LIQUIDITYENGINE_MQH
#define MITEMSHUB_STRUCTURE_LIQUIDITYENGINE_MQH

#include "../Core/Constants.mqh"
#include "SwingDetector.mqh"

struct Sweep
  {
   datetime time;      // bar time of the sweep
   double   level;     // the liquidity level (swing extreme)
   double   extreme;   // the wick extreme that took the level out
   double   close;     // close back inside the level
   int      direction; // -1 buy-side sweep (above swing high), +1 sell-side (below swing low)
   bool     confirmed; // closed back inside the level
  };

class CLiquidityEngine
  {
public:
   //--- above=true: sweeping a swing high (buy-side liquidity).
   static bool IsSweep(const double bar_high, const double bar_low, const double close,
                       const double level, const double atr, const double min_exceed_atr,
                       const bool above)
     {
      if(atr <= 0.0)
         return(false);
      if(above)
         return(bar_high > level + min_exceed_atr * atr && close < level);
      return(bar_low < level - min_exceed_atr * atr && close > level);
     }

   //--- One sweep per level (first crossing in the window), oldest-first.
   static int DetectSweeps(const double &highs[], const double &lows[], const double &closes[],
                           const datetime &times[], const int count, const int left, const int right,
                           const double atr, Sweep &out[], const int max_out,
                           const double min_exceed_atr)
     {
      ArrayResize(out, 0);
      if(count < left + right + 3 || atr <= 0.0)
         return(0);

      SwingPoint swings[];
      int ns = CSwingDetector::FindSwing(highs, lows, times, count, left, right, atr, swings, 128);

      // Only the most recent swing of each polarity is the live liquidity
      // reference — matching Python's recent_high / recent_low semantics.
      double last_high = 0.0;
      double last_low  = 0.0;
      int    last_high_bar = -1;
      int    last_low_bar  = -1;
      for(int s = 0; s < ns; s++)
        {
         if(swings[s].direction > 0)
           {
            last_high = swings[s].price;
            last_high_bar = swings[s].bar;
           }
         else
           {
            last_low = swings[s].price;
            last_low_bar = swings[s].bar;
           }
        }

      if(last_high_bar >= 0)
         DetectLevel(highs, lows, closes, times, count, right, atr, min_exceed_atr,
                     last_high, last_high_bar, true, out, max_out);
      if(last_low_bar >= 0)
         DetectLevel(highs, lows, closes, times, count, right, atr, min_exceed_atr,
                     last_low, last_low_bar, false, out, max_out);
      return(ArraySize(out));
     }

private:
   static void DetectLevel(const double &highs[], const double &lows[], const double &closes[],
                           const datetime &times[], const int count, const int right,
                           const double atr, const double min_exceed_atr, const double level,
                           const int level_bar, const bool above, Sweep &out[], const int max_out)
     {
      // Only bars AFTER the level's right guard confirmed it (closed bars).
      for(int i = level_bar + right + 1; i < count; i++)
        {
         if(ArraySize(out) >= max_out)
            return;
         if(!IsSweep(highs[i], lows[i], closes[i], level, atr, min_exceed_atr, above))
            continue;
         Sweep sw;
         sw.time      = times[i];
         sw.level     = level;
         sw.extreme   = above ? highs[i] : lows[i];
         sw.close     = closes[i];
         sw.direction = above ? -1 : 1;
         sw.confirmed = true;
         int n = ArraySize(out);
         ArrayResize(out, n + 1);
         out[n] = sw;
         return;   // one sweep per level (first crossing)
        }
     }
  };

#endif // MITEMSHUB_STRUCTURE_LIQUIDITYENGINE_MQH
