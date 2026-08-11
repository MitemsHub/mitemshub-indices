//+------------------------------------------------------------------+
//|                                      Regime/HurstAnalyzer.mqh    |
//|  MITEMSHUB AI MARKET ENGINE — Hurst exponent via R/S analysis.   |
//|                                                                  |
//|  H > 0.5  → persistent (trending) process                       |
//|  H ~ 0.5  → random walk                                          |
//|  H < 0.5  → anti-persistent (mean-reverting) process            |
//|                                                                  |
//|  IMPORTANT (per architecture): Hurst is ONE input to the regime  |
//|  engine, never the sole classifier — it is noisy on small        |
//|  samples and biased by outliers.                                 |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_HURSTANALYZER_MQH
#define MITEMSHUB_REGIME_HURSTANALYZER_MQH

#include "../Core/Constants.mqh"

class CHurstAnalyzer
  {
public:
   //--- R/S Hurst over `count` log returns.  Returns 0..1, or -1 if the
   //--- sample is too small / degenerate to estimate.
   static double Hurst(const double &returns[], const int count)
     {
      if(count < 32)
         return(-1.0);

      int      npts = 0;
      double   xs[16], ys[16];
      int      maxL = count / 2;

      for(int L = 8; L <= maxL; L = (L * 3) / 2)
        {
         if(L < 8)
            L = 8;            // guard first iteration after the seed
         if(L + 1 > count || L >= count)
            break;

         int      ns = count / L;          // number of sub-series
         double   rs_sum = 0.0;
         int      rs_n = 0;

         for(int s = 0; s < ns; s++)
           {
            int base = s * L;
            double sub[];
            ArrayResize(sub, L);
            double mean = 0.0;
            for(int i = 0; i < L; i++)
              {
               sub[i] = returns[base + i];
               mean += sub[i];
              }
            mean /= L;

            // sample std of the sub-series
            double var = 0.0;
            for(int i = 0; i < L; i++)
              {
               double d = sub[i] - mean;
               var += d * d;
              }
            if(L < 2)
               continue;
            var /= (L - 1);
            double sdev = MathSqrt(var);
            if(sdev <= 0.0)
               continue;

            // rescaled range of cumulative deviations
            double cum = 0.0;
            double mn = 0.0;
            double mx = 0.0;
            for(int i = 0; i < L; i++)
              {
               cum += (sub[i] - mean);
               if(i == 0)
                 {
                  mn = cum;
                  mx = cum;
                 }
               else
                 {
                  if(cum < mn)
                     mn = cum;
                  if(cum > mx)
                     mx = cum;
                 }
              }
            double rng = mx - mn;
            if(rng > 0.0)
              {
               rs_sum += rng / sdev;
               rs_n++;
              }
           }

         if(rs_n > 0 && npts < 16)
           {
            xs[npts] = MathLog((double)L);
            ys[npts] = MathLog(rs_sum / rs_n);
            npts++;
           }
        }

      if(npts < 3)
         return(-1.0);

      // least-squares slope of log(RS) vs log(L)
      double sx = 0.0, sy = 0.0, sxx = 0.0, sxy = 0.0;
      for(int i = 0; i < npts; i++)
        {
         sx  += xs[i];
         sy  += ys[i];
         sxx += xs[i] * xs[i];
         sxy += xs[i] * ys[i];
        }
      double denom = npts * sxx - sx * sx;
      if(denom == 0.0)
         return(-1.0);
      double h = (npts * sxy - sx * sy) / denom;
      if(h < 0.0)
         h = 0.0;
      if(h > 1.0)
         h = 1.0;
      return(h);
     }

   //--- Convenience: compute on closes by taking log returns internally.
   static double HurstOnCloses(const double &closes[], const int count)
     {
      if(count < 33)
         return(-1.0);
      double rets[];
      ArrayResize(rets, count - 1);
      for(int i = 0; i < count - 1; i++)
        {
         double p = closes[i];
         rets[i] = (p > 0.0 && closes[i + 1] > 0.0)
                   ? MathLog(closes[i + 1] / p) : 0.0;
        }
      return(Hurst(rets, count - 1));
     }
  };

#endif // MITEMSHUB_REGIME_HURSTANALYZER_MQH
