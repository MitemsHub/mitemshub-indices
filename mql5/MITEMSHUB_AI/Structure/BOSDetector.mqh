//+------------------------------------------------------------------+
//|                                      Structure/BOSDetector.mqh   |
//|  MITEMSHUB AI MARKET ENGINE — break of structure.                |
//|                                                                  |
//|  Bullish BOS: price CLOSES above the most recent confirmed       |
//|  swing high (buyers broke the last high).  Bearish BOS: close    |
//|  below the most recent confirmed swing low.  Only closed bars,   |
//|  and a swing is only usable after its right guard has confirmed  |
//|  it (bar + right <= current bar) — no lookahead.                 |
//|                                                                  |
//|  One event per level crossing: re-arming requires price to       |
//|  return through the level first, so a sustained move emits       |
//|  exactly one BOS, not one per bar.                               |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_BOSDETECTOR_MQH
#define MITEMSHUB_STRUCTURE_BOSDETECTOR_MQH

#include "../Core/Constants.mqh"
#include "SwingDetector.mqh"

struct BOSEvent
  {
   datetime time;      // bar time of the break
   double   price;     // close that broke the level
   double   level;     // the broken swing extreme
   int      direction; // +1 bullish BOS, -1 bearish BOS
   double   strength;  // |price - level| / atr, clamped 0..1
  };

class CBOSDetector
  {
public:
   static int Detect(const double &highs[], const double &lows[], const double &closes[],
                     const datetime &times[], const int count, const int left, const int right,
                     const double atr, BOSEvent &out[], const int max_out)
     {
      ArrayResize(out, 0);
      if(count < left + right + 3 || atr <= 0.0)
         return(0);

      SwingPoint swings[];
      int ns = CSwingDetector::FindSwing(highs, lows, times, count, left, right, atr, swings, 128);

      int    next_swing = 0;
      double last_sh_price = 0.0;   // 0 = none yet
      double last_sl_price = 0.0;
      for(int i = 0; i < count; i++)
        {
         // Activate swings whose right guard has confirmed (closed bars only).
         while(next_swing < ns && swings[next_swing].bar + right <= i)
           {
            if(swings[next_swing].direction > 0)
               last_sh_price = swings[next_swing].price;
            else
               last_sl_price = swings[next_swing].price;
            next_swing++;
           }

         if(last_sh_price > 0.0 &&
            closes[i] > last_sh_price &&
            (i == 0 || closes[i - 1] <= last_sh_price))
           {
            BOSEvent e;
            e.time      = times[i];
            e.price     = closes[i];
            e.level     = last_sh_price;
            e.direction = 1;
            e.strength  = Strength(closes[i] - last_sh_price, atr);
            Append(out, e, max_out);
           }
         else if(last_sl_price > 0.0 &&
                 closes[i] < last_sl_price &&
                 (i == 0 || closes[i - 1] >= last_sl_price))
           {
            BOSEvent e;
            e.time      = times[i];
            e.price     = closes[i];
            e.level     = last_sl_price;
            e.direction = -1;
            e.strength  = Strength(last_sl_price - closes[i], atr);
            Append(out, e, max_out);
           }
        }
      return(ArraySize(out));
     }

private:
   static double Strength(const double dist, const double atr)
     {
      double s = dist / atr;
      if(s > 1.0)
         return(1.0);
      if(s < 0.0)
         return(0.0);
      return(s);
     }

   static void Append(BOSEvent &out[], const BOSEvent &e, const int max_out)
     {
      if(ArraySize(out) >= max_out)
         return;
      int n = ArraySize(out);
      ArrayResize(out, n + 1);
      out[n] = e;
     }
  };

#endif // MITEMSHUB_STRUCTURE_BOSDETECTOR_MQH
