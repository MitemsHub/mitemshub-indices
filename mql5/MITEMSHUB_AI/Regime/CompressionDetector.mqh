//+------------------------------------------------------------------+
//|                                   Regime/CompressionDetector.mqh |
//|  MITEMSHUB AI MARKET ENGINE — compression (squeeze) detection.   |
//|                                                                  |
//|  Compression = volatility contracting: low ATR percentile rank   |
//|  AND ATR shrinking relative to its baseline.  High compression   |
//|  often precedes a breakout — the engine should pair this with    |
//|  the expansion detector rather than trade the squeeze blindly.   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_COMPRESSIONDETECTOR_MQH
#define MITEMSHUB_REGIME_COMPRESSIONDETECTOR_MQH

#include "../Core/Constants.mqh"

class CCompressionDetector
  {
public:
   //--- atr_percentile: 0..1 (1 = current ATR is the largest in its window).
   //--- atr_ratio: current ATR / baseline ATR (1 = unchanged).
   static double CompressionScore(const double atr_percentile, const double atr_ratio)
     {
      if(atr_percentile < 0.0 || atr_percentile > 1.0)
         return(0.0);
      double p = 1.0 - atr_percentile;              // low rank → compression
      double r = MathMax(0.0, 1.0 - atr_ratio);     // shrinking → compression
      double score = 0.6 * p + 0.4 * MathMin(1.0, r);
      if(score > 1.0)
         score = 1.0;
      return(score);
     }
  };

#endif // MITEMSHUB_REGIME_COMPRESSIONDETECTOR_MQH
