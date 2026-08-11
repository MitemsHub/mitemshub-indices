//+------------------------------------------------------------------+
//|                                     Structure/CHOCHDetector.mqh  |
//|  MITEMSHUB AI MARKET ENGINE — change of character.               |
//|                                                                  |
//|  CHOCH is the first sign of a reversal: in an uptrend defined by |
//|  higher highs AND higher lows (HH + HL), a CLOSE below the last  |
//|  higher low is a character change to the downside.  Symmetrically|
//|  in a downtrend (LH + LL), a close above the last lower high is  |
//|  a character change to the upside.                               |
//|                                                                  |
//|  The trend definition is recomputed bar-by-bar from the last two |
//|  confirmed swings of each polarity, so it is stateless and       |
//|  cannot drift.  Only closed bars; swings usable only after their |
//|  right guard confirms them.                                      |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_CHOCHDETECTOR_MQH
#define MITEMSHUB_STRUCTURE_CHOCHDETECTOR_MQH

#include "../Core/Constants.mqh"
#include "SwingDetector.mqh"

struct CHOCH
  {
   datetime time;      // bar time of the character change
   double   price;     // close that broke the level
   double   level;     // broken higher-low (down) or lower-high (up)
   int      direction; // +1 bullish CHOCH, -1 bearish CHOCH
   double   strength;  // |price - level| / atr, clamped 0..1
  };

class CCHOCHDetector
  {
public:
   static int Detect(const double &highs[], const double &lows[], const double &closes[],
                     const datetime &times[], const int count, const int left, const int right,
                     const double atr, CHOCH &out[], const int max_out)
     {
      ArrayResize(out, 0);
      if(count < left + right + 5 || atr <= 0.0)
         return(0);

      SwingPoint swings[];
      int ns = CSwingDetector::FindSwing(highs, lows, times, count, left, right, atr, swings, 128);

      int    next_swing = 0;
      double sh1 = 0.0, sh0 = 0.0;   // last two confirmed swing highs (0 = none)
      double sl1 = 0.0, sl0 = 0.0;   // last two confirmed swing lows
      for(int i = 0; i < count; i++)
        {
         while(next_swing < ns && swings[next_swing].bar + right <= i)
           {
            if(swings[next_swing].direction > 0)
              {
               sh1 = sh0;
               sh0 = swings[next_swing].price;
              }
            else
              {
               sl1 = sl0;
               sl0 = swings[next_swing].price;
              }
            next_swing++;
           }

         bool uptrend   = (sh0 > 0.0 && sh1 > 0.0 && sl0 > 0.0 && sl1 > 0.0) &&
                          sh0 > sh1 && sl0 > sl1;
         bool downtrend = (sh0 > 0.0 && sh1 > 0.0 && sl0 > 0.0 && sl1 > 0.0) &&
                          sh0 < sh1 && sl0 < sl1;

         if(uptrend && closes[i] < sl0 && (i == 0 || closes[i - 1] >= sl0))
           {
            // close below the last higher low = character change to down
            CHOCH c;
            c.time      = times[i];
            c.price     = closes[i];
            c.level     = sl0;
            c.direction = -1;
            c.strength  = Strength(sl0 - closes[i], atr);
            Append(out, c, max_out);
           }
         else if(downtrend && closes[i] > sh0 && (i == 0 || closes[i - 1] <= sh0))
           {
            // close above the last lower high = character change to up
            CHOCH c;
            c.time      = times[i];
            c.price     = closes[i];
            c.level     = sh0;
            c.direction = 1;
            c.strength  = Strength(closes[i] - sh0, atr);
            Append(out, c, max_out);
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

   static void Append(CHOCH &out[], const CHOCH &c, const int max_out)
     {
      if(ArraySize(out) >= max_out)
         return;
      int n = ArraySize(out);
      ArrayResize(out, n + 1);
      out[n] = c;
     }
  };

#endif // MITEMSHUB_STRUCTURE_CHOCHDETECTOR_MQH
