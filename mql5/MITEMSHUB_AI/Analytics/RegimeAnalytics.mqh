//+------------------------------------------------------------------+
//|                                     Analytics/RegimeAnalytics.mqh |
//|  MITEMSHUB AI MARKET ENGINE — Phase 8 RegimeAnalytics.          |
//|                                                                  |
//|  Plan §18: performance broken down by the regime recorded at     |
//|  entry, so the engine can answer "does this strategy actually    |
//|  make money in the regime it claims to trade, and where does it  |
//|  bleed?"  Regime is the Phase-2 RegimeEngine output the strategy |
//|  consumed when it opened the trade (OutcomeRecord.regime).       |
//|                                                                  |
//|  Provides: per-regime bucket stats, the best/worst regime by     |
//|  expectancy, and a regime-purity check: how much of the edge     |
//|  concentrates in a single regime (the regime-concentration       |
//|  metric) — a strategy whose profit lives in ONE regime is more   |
//|  fragile than one spread across several.                         |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_ANALYTICS_REGIMEANALYTICS_MQH
#define MITEMSHUB_ANALYTICS_REGIMEANALYTICS_MQH

#include "../Core/Constants.mqh"
#include "PerformanceAnalytics.mqh"

class CRegimeAnalytics
  {
public:
   //--- which regimes actually produced closed trades -----------------------------
   static int ActiveRegimes(const BucketStats &by_regime[])
     {
      int active = 0;
      for(int r = 0; r < ANALYTICS_MAX_REGIMES; r++)
         if(by_regime[r].n > 0)
            active++;
      return(active);
     }

   //--- regime concentration: share of all trades in the regime with the most -----
   static double Concentration(const BucketStats &by_regime[], const int total_trades)
     {
      if(total_trades <= 0)
         return(0.0);
      int top = 0;
      for(int r = 0; r < ANALYTICS_MAX_REGIMES; r++)
         if(by_regime[r].n > top)
            top = by_regime[r].n;
      return((double)top / (double)total_trades);
     }

   //--- best regime by expectancy (returns the enum; -1 when no trades) -----------
   static int BestRegime(const BucketStats &by_regime[])
     {
      int best = -1;
      double best_exp = -1e9;
      for(int r = 0; r < ANALYTICS_MAX_REGIMES; r++)
        {
         if(by_regime[r].n == 0)
            continue;
         double e = by_regime[r].AvgR();
         if(e > best_exp)
           {
            best_exp = e;
            best = r;
           }
        }
      return(best);
     }

   //--- worst regime by expectancy -------------------------------------------------
   static int WorstRegime(const BucketStats &by_regime[])
     {
      int worst = -1;
      double worst_exp = 1e9;
      for(int r = 0; r < ANALYTICS_MAX_REGIMES; r++)
        {
         if(by_regime[r].n == 0)
            continue;
         double e = by_regime[r].AvgR();
         if(e < worst_exp)
           {
            worst_exp = e;
            worst = r;
           }
        }
      return(worst);
     }

   //--- do the strategy's trades align with the regime it requires?  ---------------- 
   // OutcomeRecord only carries the regime AT ENTRY, so "alignment" is measured as:
   // the share of trades whose regime is the one the strategy's hypothesis names.
   // Returns the share of trades in that regime (0..1).
   static double AlignmentShare(const OutcomeRecord &rows[], const int n,
                                const ENUM_REGIME required)
     {
      if(n <= 0)
         return(0.0);
      int aligned = 0;
      for(int i = 0; i < n; i++)
         if(rows[i].regime == required)
            aligned++;
      return((double)aligned / (double)n);
     }

   //--- plan §24 print ----------------------------------------------------------------
   static void PrintRegimeTable(const BucketStats &by_regime[])
     {
      Print("[ANALYTICS] regime split:");
      for(int r = 0; r < ANALYTICS_MAX_REGIMES; r++)
        {
         BucketStats b = by_regime[r];   // MQL5: no local reference variables
         if(b.n == 0)
            continue;
         Print(StringFormat("[ANALYTICS]   %-18s n=%4d hit=%5.1f%% exp=%+.3fR sumR=%+.2fR",
                            RegimeToString((ENUM_REGIME)r), b.n,
                            100.0 * b.HitRate(), b.AvgR(), b.sum_r));
        }
     }
  };

#endif // MITEMSHUB_ANALYTICS_REGIMEANALYTICS_MQH
