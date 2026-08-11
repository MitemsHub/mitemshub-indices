//+------------------------------------------------------------------+
//|                                      Regime/RangeDetector.mqh    |
//|  MITEMSHUB AI MARKET ENGINE — range / chop detection.            |
//|                                                                  |
//|  High range score = low efficiency (price goes nowhere) AND      |
//|  frequent direction flips (oscillation) around a bounded mean.   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_RANGEDETECTOR_MQH
#define MITEMSHUB_REGIME_RANGEDETECTOR_MQH

#include "../Core/Constants.mqh"
#include "../Market/NormalizationEngine.mqh"

class CRangeDetector
  {
public:
   //--- 0..1 range score.
   static double RangeScore(const double &closes[], const int count)
     {
      if(count < 8)
         return(0.0);
      double er = CNormalizationEngine::EfficiencyRatio(closes, count);

      // direction-flip frequency (d1*d2 < 0 → the market changed course)
      double flips = 0.0;
      int    n = 0;
      for(int i = 2; i < count; i++)
        {
         double d1 = closes[i - 1] - closes[i - 2];
         double d2 = closes[i]     - closes[i - 1];
         if((d1 > 0.0 && d2 < 0.0) || (d1 < 0.0 && d2 > 0.0))
            flips += 1.0;
         n++;
        }
      double flip_ratio = (n > 0) ? flips / n : 0.0;

      double er_score   = 1.0 - MathMin(1.0, er * 4.0);   // low ER → range
      double flip_score = MathMin(1.0, flip_ratio * 2.0); // many flips → range
      double score = 0.6 * er_score + 0.4 * flip_score;
      if(score > 1.0)
         score = 1.0;
      return(score);
     }
  };

#endif // MITEMSHUB_REGIME_RANGEDETECTOR_MQH
