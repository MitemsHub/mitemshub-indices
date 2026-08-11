//+------------------------------------------------------------------+
//|                                    Structure/SwingDetector.mqh   |
//|  MITEMSHUB AI MARKET ENGINE — objective swing detection.         |
//|                                                                  |
//|  A swing high is a fractal: high[i] strictly greater than the    |
//|  highs of `left` bars before and `right` bars after it.  Only    |
//|  CLOSED bars are ever analyzed — the right guard is what         |
//|  removes repainting, so a swing can only be *confirmed* once     |
//|  `right` bars have closed after it.                              |
//|                                                                  |
//|  Strength is the prominence of the swing in ATR multiples        |
//|  (clearance above the immediate neighbors), clamped 0..1 —       |
//|  vol-normalized so swings are comparable across symbols.         |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_SWINGDETECTOR_MQH
#define MITEMSHUB_STRUCTURE_SWINGDETECTOR_MQH

#include "../Core/Constants.mqh"

struct SwingPoint
  {
   datetime time;      // bar time of the swing extreme
   double   price;     // high (swing high) or low (swing low)
   int      bar;       // bar index within the analyzed window
   int      direction; // +1 swing high, -1 swing low
   double   strength;  // 0..1 prominence in ATR multiples
  };

class CSwingDetector
  {
public:
   //--- Fractal guard on CLOSED bars: strictly the max of its neighborhood.
   static bool IsSwingHigh(const double &highs[], const int i, const int left, const int right)
     {
      if(i - left < 0 || i + right >= ArraySize(highs))
         return(false);
      for(int j = i - left; j <= i + right; j++)
        {
         if(j == i)
            continue;
         if(highs[i] <= highs[j])
            return(false);
        }
      return(true);
     }

   static bool IsSwingLow(const double &lows[], const int i, const int left, const int right)
     {
      if(i - left < 0 || i + right >= ArraySize(lows))
         return(false);
      for(int j = i - left; j <= i + right; j++)
        {
         if(j == i)
            continue;
         if(lows[i] >= lows[j])
            return(false);
        }
      return(true);
     }

   //--- Prominence: clearance above the two immediate neighbors, in ATR.
   static double Strength(const double &highs[], const double &lows[], const int i,
                          const int direction, const double atr)
     {
      if(atr <= 0.0 || i < 1 || i >= ArraySize(highs) - 1)
         return(0.0);
      double clear;
      if(direction > 0)
         clear = MathMin(highs[i] - highs[i - 1], highs[i] - highs[i + 1]);
      else
         clear = MathMin(lows[i - 1] - lows[i], lows[i + 1] - lows[i]);
      if(clear <= 0.0)
         return(0.0);
      double s = clear / atr;
      return(s > 1.0 ? 1.0 : s);
     }

   //--- All fractal swings in a window, oldest-first.  Returns the count.
   //--- Every returned swing is already confirmed (its right guard bars are
   //--- inside the window); consumers walking forward must additionally gate
   //--- on `bar + right <= current_bar` to avoid lookahead.
   //--- Python-parity window-edge convention: the CURRENT (last) bar is never
   //--- a right guard — swings are confirmed only by bars strictly before it
   //--- (i + right < count - 1), matching Python detect_swings(candles[:-1]).
   //--- This is what aligns the engine's recent-swing levels with Python's
   //--- recent_high/recent_low in the real-corpus cross-validation.
   static int FindSwing(const double &highs[], const double &lows[], const datetime &times[],
                        const int count, const int left, const int right, const double atr,
                        SwingPoint &out[], const int max_out)
     {
      ArrayResize(out, 0);
      for(int i = left; i + right < count - 1; i++)
        {
         if(ArraySize(out) >= max_out)
            break;
         if(IsSwingHigh(highs, i, left, right))
           {
            SwingPoint s;
            s.time      = times[i];
            s.price     = highs[i];
            s.bar       = i;
            s.direction = 1;
            s.strength  = Strength(highs, lows, i, 1, atr);
            int n = ArraySize(out);
            ArrayResize(out, n + 1);
            out[n] = s;
           }
         else if(IsSwingLow(lows, i, left, right))
           {
            SwingPoint s;
            s.time      = times[i];
            s.price     = lows[i];
            s.bar       = i;
            s.direction = -1;
            s.strength  = Strength(highs, lows, i, -1, atr);
            int n = ArraySize(out);
            ArrayResize(out, n + 1);
            out[n] = s;
           }
        }
      return(ArraySize(out));
     }
  };

#endif // MITEMSHUB_STRUCTURE_SWINGDETECTOR_MQH
