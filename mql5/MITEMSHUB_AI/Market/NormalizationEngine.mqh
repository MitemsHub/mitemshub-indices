//+------------------------------------------------------------------+
//|                                      Market/NormalizationEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — broker-independent measurement.    |
//|                                                                  |
//|  Raw prices are NOT the basis of strategy logic.  Every         |
//|  measurement is expressed relative to something: ATR multiples,  |
//|  percentage returns, z-scores, volatility-adjusted distance.    |
//|  This is what makes the engine portable between brokers and     |
//|  symbols (V75 at ~1,668 vs V100 at ~354 are both "2.4 ATR from  |
//|  the mean" — the raw numbers are meaningless by themselves).    |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_NORMALIZATIONENGINE_MQH
#define MITEMSHUB_MARKET_NORMALIZATIONENGINE_MQH

#include "../Core/Constants.mqh"

class CNormalizationEngine
  {
public:
   // Candle range (high-low) as a multiple of ATR.  ATR<=0 → 0.
   static double RangeToATR(const double high, const double low, const double atr)
     {
      if(atr <= 0.0 || high <= low || high <= 0.0)
         return(0.0);
      return((high - low) / atr);
     }

   // Body size as a multiple of ATR.
   static double BodyToATR(const double open, const double close, const double atr)
     {
      if(atr <= 0.0)
         return(0.0);
      return(MathAbs(close - open) / atr);
     }

   // Log return of a move.
   static double LogReturn(const double from, const double to)
     {
      if(from <= 0.0 || to <= 0.0)
         return(0.0);
      return(MathLog(to / from));
     }

   // Percentage return of a move.
   static double PctReturn(const double from, const double to)
     {
      if(from == 0.0)
         return(0.0);
      return((to - from) / from);
     }

   // Z-score of a value against a mean/std (std<=0 → 0).
   static double ZScore(const double value, const double mean, const double std)
     {
      if(std <= 0.0)
         return(0.0);
      return((value - mean) / std);
     }

   // Distance of `price` from `level`, normalized by ATR (vol-adjusted).
   // Positive = price above the level.
   static double RelativeDistance(const double price, const double level, const double atr)
     {
      if(atr <= 0.0)
         return(0.0);
      return((price - level) / atr);
     }

   // Close position inside the bar (0=low, 1=high) — "close location".
   static double CloseLocation(const double high, const double low, const double close)
     {
      double rng = high - low;
      if(rng <= 0.0)
         return(0.5);
      double loc = (close - low) / rng;
      if(loc < 0.0)
         loc = 0.0;
      if(loc > 1.0)
         loc = 1.0;
      return(loc);
     }

   // Directional efficiency ratio: net move / gross path over a window.
   // 1.0 = perfectly directional, 0.0 = pure chop.
   static double EfficiencyRatio(const double &closes[], const int count)
     {
      if(count < 2)
         return(0.0);
      double net = MathAbs(closes[count - 1] - closes[0]);
      double gross = 0.0;
      for(int i = 1; i < count; i++)
         gross += MathAbs(closes[i] - closes[i - 1]);
      if(gross <= 0.0)
         return(0.0);
      return(net / gross);
     }
  };

#endif // MITEMSHUB_MARKET_NORMALIZATIONENGINE_MQH
