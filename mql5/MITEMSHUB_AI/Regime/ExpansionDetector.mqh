//+------------------------------------------------------------------+
//|                                    Regime/ExpansionDetector.mqh  |
//|  MITEMSHUB AI MARKET ENGINE — expansion (volatility burst)       |
//|  detection.                                                      |
//|                                                                  |
//|  Expansion = volatility expanding: high ATR percentile rank AND  |
//|  ATR growing relative to its baseline.  Complements the          |
//|  compression detector (squeeze → burst).                        |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_EXPANSIONDETECTOR_MQH
#define MITEMSHUB_REGIME_EXPANSIONDETECTOR_MQH

#include "../Core/Constants.mqh"

class CExpansionDetector
  {
public:
   //--- atr_percentile: 0..1 (1 = current ATR is the largest in its window).
   //--- atr_ratio: current ATR / baseline ATR (1 = unchanged).
   static double ExpansionScore(const double atr_percentile, const double atr_ratio)
     {
      if(atr_percentile < 0.0 || atr_percentile > 1.0)
         return(0.0);
      double p = atr_percentile;                     // high rank → expansion
      double r = MathMax(0.0, atr_ratio - 1.0);      // growing → expansion
      double score = 0.6 * p + 0.4 * MathMin(1.0, r);
      if(score > 1.0)
         score = 1.0;
      return(score);
     }
  };

#endif // MITEMSHUB_REGIME_EXPANSIONDETECTOR_MQH
