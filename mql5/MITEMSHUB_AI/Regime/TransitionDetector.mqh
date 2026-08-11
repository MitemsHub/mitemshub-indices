//+------------------------------------------------------------------+
//|                                    Regime/TransitionDetector.mqh |
//|  MITEMSHUB AI MARKET ENGINE — regime-transition probability.     |
//|                                                                  |
//|  A transition is a structural change, not a bar move: volatility |
//|  of the recent half vs the prior half (vol-of-vol), plus the     |
//|  change in price efficiency between halves.  High values mean    |
//|  "the character of the market is changing" — reduce conviction   |
//|  in whatever regime was detected a moment ago.                  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_TRANSITIONDETECTOR_MQH
#define MITEMSHUB_REGIME_TRANSITIONDETECTOR_MQH

#include "../Core/Constants.mqh"
#include "../Market/NormalizationEngine.mqh"

class CTransitionDetector
  {
public:
   //--- 0..1 transition probability over the last 2*window closes.
   static double TransitionScore(const double &closes[], const int count,
                                 const int window = 10)
     {
      if(count < 2 * window + 4)
         return(0.0);
      int start1 = count - 2 * window;
      int start2 = count - window;

      double v1 = SliceRealizedVol(closes, start1, window);
      double v2 = SliceRealizedVol(closes, start2, window);
      double vv = (v1 + v2) > 0.0 ? MathAbs(v2 - v1) / (v1 + v2) : 0.0;

      double e1 = SliceER(closes, start1, window);
      double e2 = SliceER(closes, start2, window);
      double ed = MathAbs(e2 - e1);

      double score = 0.6 * MathMin(1.0, vv * 3.0) + 0.4 * MathMin(1.0, ed * 3.0);
      if(score > 1.0)
         score = 1.0;
      return(score);
     }

private:
   static double SliceER(const double &closes[], const int start, const int n)
     {
      if(n < 2)
         return(0.0);
      double net = MathAbs(closes[start + n - 1] - closes[start]);
      double gross = 0.0;
      for(int i = 1; i < n; i++)
         gross += MathAbs(closes[start + i] - closes[start + i - 1]);
      return(gross <= 0.0 ? 0.0 : net / gross);
     }

   static double SliceRealizedVol(const double &closes[], const int start, const int n)
     {
      if(n < 3)
         return(0.0);
      double rets[];
      ArrayResize(rets, n - 1);
      for(int i = 0; i < n - 1; i++)
        {
         double p = closes[start + i];
         rets[i] = (p > 0.0) ? MathLog(closes[start + i + 1] / p) : 0.0;
        }
      int    m = n - 1;
      double mean = 0.0;
      for(int i = 0; i < m; i++)
         mean += rets[i];
      mean /= m;
      double var = 0.0;
      for(int i = 0; i < m; i++)
        {
         double d = rets[i] - mean;
         var += d * d;
        }
      var /= (m - 1);
      return(MathSqrt(var));
     }
  };

#endif // MITEMSHUB_REGIME_TRANSITIONDETECTOR_MQH
