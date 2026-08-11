//+------------------------------------------------------------------+
//|                                   Structure/SupportResistance.mqh|
//|  MITEMSHUB AI MARKET ENGINE — support/resistance level clusters. |
//|                                                                  |
//|  Raw extremes (swing prices) are clustered: anything within      |
//|  tol_atr × ATR of an existing level is a TOUCH of that level     |
//|  rather than a new one.  A level only survives the cluster       |
//|  filter once it has enough touches, so a single random extreme   |
//|  never becomes a "level".                                        |
//|                                                                  |
//|  kind: +1 resistance (formed by swing highs), -1 support (swing  |
//|  lows), 0 = both (a level that acted as both a ceiling and a    |
//|  floor is the strongest kind).                                   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_SUPPORTRESISTANCE_MQH
#define MITEMSHUB_STRUCTURE_SUPPORTRESISTANCE_MQH

#include "../Core/Constants.mqh"

struct SRLevel
  {
   double   level;
   int      touches;
   int      kind;        // +1 resistance, -1 support, 0 both
   datetime first_time;
   datetime last_time;
  };

class CSupportResistance
  {
public:
   //--- Cluster raw extremes into levels; returns the count after filtering.
   static int Cluster(const double &prices[], const int &kinds[], const datetime &times[],
                      const int count, const double atr, const double tol_atr,
                      SRLevel &out[], const int max_out, const int min_touches)
     {
      ArrayResize(out, 0);
      if(atr <= 0.0 || count <= 0)
         return(0);

      for(int i = 0; i < count; i++)
        {
         int found = -1;
         for(int j = 0; j < ArraySize(out); j++)
           {
            if(MathAbs(out[j].level - prices[i]) <= tol_atr * atr)
              {
               found = j;
               break;
              }
           }
         if(found >= 0)
           {
            out[found].touches++;
            out[found].kind     |= kinds[i];
            out[found].last_time = times[i];
           }
         else
           {
            if(ArraySize(out) >= max_out)
               continue;
            SRLevel l;
            l.level      = prices[i];
            l.touches    = 1;
            l.kind       = kinds[i];
            l.first_time = times[i];
            l.last_time  = times[i];
            int n = ArraySize(out);
            ArrayResize(out, n + 1);
            out[n] = l;
           }
        }

      // Filter: only levels with enough touches survive.
      int keep = 0;
      for(int j = 0; j < ArraySize(out); j++)
        {
         if(out[j].touches >= min_touches)
            out[keep++] = out[j];
        }
      ArrayResize(out, keep);
      return(keep);
     }

   //--- Nearest level within tol_atr × ATR of `price`; false if none.
   static bool QueryNear(const SRLevel &levels[], const int n, const double price,
                         const double atr, const double tol_atr, double &out_level, int &out_touches)
     {
      int    best = -1;
      double best_dist = 0.0;
      for(int i = 0; i < n; i++)
        {
         double d = MathAbs(levels[i].level - price);
         if(best < 0 || d < best_dist)
           {
            best = i;
            best_dist = d;
           }
        }
      if(best < 0 || best_dist > tol_atr * atr)
         return(false);
      out_level  = levels[best].level;
      out_touches = levels[best].touches;
      return(true);
     }
  };

#endif // MITEMSHUB_STRUCTURE_SUPPORTRESISTANCE_MQH
