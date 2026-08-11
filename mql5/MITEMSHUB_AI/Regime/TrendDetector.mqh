//+------------------------------------------------------------------+
//|                                      Regime/TrendDetector.mqh    |
//|  MITEMSHUB AI MARKET ENGINE — trend detection.                   |
//|                                                                  |
//|  Two independent measurements are combined:                      |
//|    1. price efficiency (net move / gross path) — 1.0 = perfect   |
//|       directional, 0.0 = chop.                                   |
//|    2. SMA slope, normalized by mean price (vol-independent).     |
//|  Direction uses the SMA slope with a small dead-band.            |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_TRENDDETECTOR_MQH
#define MITEMSHUB_REGIME_TRENDDETECTOR_MQH

#include "../Core/Constants.mqh"
#include "../Market/NormalizationEngine.mqh"

class CTrendDetector
  {
public:
   //--- 0..1 trend strength.
   static double TrendStrength(const double &closes[], const int count,
                               const int ma_period = 20)
     {
      if(count < 2 * ma_period + 2)
         return(0.0);
      double er = CNormalizationEngine::EfficiencyRatio(closes, count);

      double ma_now  = SMA(closes, count - ma_period, ma_period);
      double ma_prev = SMA(closes, count - 2 * ma_period, ma_period);
      double mean    = MeanAbs(closes, count);
      double slope   = (mean > 0.0) ? (ma_now - ma_prev) / mean : 0.0;

      // A 2% net MA move over ma_period bars maps to slope_score 1.0.
      double slope_score = MathMin(1.0, MathAbs(slope) * 50.0);
      double strength = 0.5 * er + 0.5 * slope_score;
      if(strength > 1.0)
         strength = 1.0;
      return(strength);
     }

   //--- +1 / -1 / 0 (dead-band avoids noise around a flat MA).
   static int Direction(const double &closes[], const int count,
                        const int ma_period = 20)
     {
      if(count < 2 * ma_period + 2)
         return(0);
      double ma_now  = SMA(closes, count - ma_period, ma_period);
      double ma_prev = SMA(closes, count - 2 * ma_period, ma_period);
      double mean    = MeanAbs(closes, count);
      double diff    = ma_now - ma_prev;
      if(mean > 0.0 && MathAbs(diff) < mean * 0.0005)
         return(0);                                   // 0.05% dead-band
      return(diff > 0.0 ? 1 : -1);
     }

private:
   static double SMA(const double &closes[], const int start, const int period)
     {
      double sum = 0.0;
      for(int i = start; i < start + period; i++)
         sum += closes[i];
      return(period > 0 ? sum / period : 0.0);
     }

   static double MeanAbs(const double &closes[], const int count)
     {
      double sum = 0.0;
      for(int i = 0; i < count; i++)
         sum += MathAbs(closes[i]);
      return(count > 0 ? sum / count : 0.0);
     }
  };

#endif // MITEMSHUB_REGIME_TRENDDETECTOR_MQH
