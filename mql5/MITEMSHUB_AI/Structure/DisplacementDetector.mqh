//+------------------------------------------------------------------+
//|                                  Structure/DisplacementDetector.mqh|
//|  MITEMSHUB AI MARKET ENGINE — normalized displacement.           |
//|                                                                  |
//|  Displacement is an impulse bar: a body and range that are       |
//|  multiples of ATR (broker/price-scale independent) AND a close   |
//|  near the extreme of the bar (the close rejected the body, not   |
//|  a wick-and-fade).  It answers \"who is in control\" with one     |
//|  normalized number instead of raw point sizes.                   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_DISPLACEMENTDETECTOR_MQH
#define MITEMSHUB_STRUCTURE_DISPLACEMENTDETECTOR_MQH

#include "../Core/Constants.mqh"

struct Displacement
  {
   int      bar;        // bar index within the analyzed window
   int      direction;  // +1 up, -1 down
   double   body_atr;   // |close - open| / atr
   double   range_atr;  // (high - low) / atr
   double   close_loc;  // close position in the bar (0=low, 1=high)
   double   score;      // 0..1 weighted displacement score
  };

class CDisplacementDetector
  {
public:
   //--- 0..1 score: 70% body (primary) + 30% range, each vs its multiple.
   static double Score(const double open, const double high, const double low, const double close,
                       const double atr, const double body_mult, const double range_mult)
     {
      if(atr <= 0.0)
         return(0.0);
      double rng = high - low;
      if(rng <= 0.0)
         return(0.0);
      double body_part  = MathMin(1.0, MathAbs(close - open) / atr / body_mult);
      double range_part = MathMin(1.0, rng / atr / range_mult);
      return(0.7 * body_part + 0.3 * range_part);
     }

   //--- True when body AND range clear their multiples AND the close is
   //--- committed to the direction (close-location >= 0.7 up / <= 0.3 down).
   static bool IsDisplacement(const double open, const double high, const double low,
                              const double close, const double atr,
                              const double body_mult, const double range_mult)
     {
      if(atr <= 0.0)
         return(false);
      double rng = high - low;
      if(rng <= 0.0)
         return(false);
      double body = MathAbs(close - open);
      if(body / atr < body_mult || rng / atr < range_mult)
         return(false);
      double loc = (close - low) / rng;
      if(body > 0.0 && close > open)
         return(loc >= 0.7);
      if(body > 0.0 && close < open)
         return(loc <= 0.3);
      return(false);
     }

   //--- All displacement bars in a window, oldest-first.
   static int Detect(const double &opens[], const double &highs[], const double &lows[],
                     const double &closes[], const datetime &times[], const int count,
                     const double atr, Displacement &out[], const int max_out,
                     const double body_mult, const double range_mult)
     {
      ArrayResize(out, 0);
      if(atr <= 0.0)
         return(0);
      for(int i = 0; i < count; i++)
        {
         if(ArraySize(out) >= max_out)
            break;
         if(!IsDisplacement(opens[i], highs[i], lows[i], closes[i], atr, body_mult, range_mult))
            continue;
         Displacement d;
         d.bar       = i;
         d.direction = closes[i] > opens[i] ? 1 : -1;
         double rng  = highs[i] - lows[i];
         d.body_atr  = rng > 0.0 ? MathAbs(closes[i] - opens[i]) / atr : 0.0;
         d.range_atr = rng > 0.0 ? rng / atr : 0.0;
         d.close_loc = rng > 0.0 ? (closes[i] - lows[i]) / rng : 0.5;
         d.score     = Score(opens[i], highs[i], lows[i], closes[i], atr, body_mult, range_mult);
         int n = ArraySize(out);
         ArrayResize(out, n + 1);
         out[n] = d;
        }
      return(ArraySize(out));
     }
  };

#endif // MITEMSHUB_STRUCTURE_DISPLACEMENTDETECTOR_MQH
