//+------------------------------------------------------------------+
//|                                      Market/VolatilityEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — volatility measurement.            |
//|                                                                  |
//|  Provides: Wilder ATR, realized volatility (std of log returns), |
//|  ATR percentile rank over a rolling window, and an expansion     |
//|  detector.  All values are broker-independent (they are relative |
//|  measurements over the symbol's own price geometry).            |
//|                                                                  |
//|  The regime engine consumes these — it never computes vol itself.|
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_VOLATILITYENGINE_MQH
#define MITEMSHUB_MARKET_VOLATILITYENGINE_MQH

#include "../Core/Constants.mqh"

#define VOL_ENGINE_MAX_BARS 500

class CVolatilityEngine
  {
private:
   int      m_period;
   double   m_atr;                 // current Wilder ATR
   bool     m_has_atr;
   //--- realized-vol ring buffer ---
   double   m_log_returns[VOL_ENGINE_MAX_BARS];
   double   m_atr_series[VOL_ENGINE_MAX_BARS];
   int      m_head;                // next write index
   int      m_count;               // items buffered

   void   Reset()
     {
      m_atr = 0.0;
      m_has_atr = false;
      m_head = 0;
      m_count = 0;
      ArrayInitialize(m_log_returns, 0.0);
      ArrayInitialize(m_atr_series, 0.0);
     }

public:
   CVolatilityEngine()
     {
      m_period = DEFAULT_ATR_PERIOD;
      Reset();
     }

   //--- lifecycle ------------------------------------------------------------
   void SetPeriod(const int period)
     {
      if(period < 2)
         m_period = 2;
      else
         m_period = period;
      Reset();
     }

   // Wilder ATR with explicit previous close (proper true-range).
   // Feed one closed bar: (prev_close, high, low, close).
   void OnBarWithPrevClose(const double prev_close, const double high,
                           const double low, const double close)
     {
      double tr = (high - low);
      if(prev_close > 0.0)
        {
         double up_gap  = MathAbs(high - prev_close);
         double dn_gap  = MathAbs(low  - prev_close);
         if(up_gap > tr)
            tr = up_gap;
         if(dn_gap > tr)
            tr = dn_gap;
        }
      if(!m_has_atr)
        {
         m_atr = tr;
         m_has_atr = true;
        }
      else
         m_atr = (m_atr * (m_period - 1) + tr) / m_period;

      if(prev_close > 0.0 && close > 0.0)
         BufferPush(MathLog(close / prev_close), m_atr);
     }

   //--- accessors ------------------------------------------------------------
   bool   HasATR() const       { return(m_has_atr); }
   double ATR() const          { return(m_atr); }

   // Realized vol = std of log returns over the last N entries (annualized
   // factor optional — for intraday compare, plain std is used).
   double RealizedVol(const int lookback) const
     {
      int n = MathMin(lookback, m_count);
      if(n < 2)
         return(0.0);
      double sum = 0.0;
      int start = (m_head - n + VOL_ENGINE_MAX_BARS) % VOL_ENGINE_MAX_BARS;
      for(int i = 0; i < n; i++)
        {
         int idx = (start + i) % VOL_ENGINE_MAX_BARS;
         sum += m_log_returns[idx];
        }
      double mean = sum / n;
      double var = 0.0;
      for(int i = 0; i < n; i++)
        {
         int idx = (start + i) % VOL_ENGINE_MAX_BARS;
         double d = m_log_returns[idx] - mean;
         var += d * d;
        }
      var /= (n - 1);
      return(MathSqrt(var));
     }

   // Percentile rank of the current ATR within the last `window` ATR values.
   // 0.0..1.0 — 1.0 means today's ATR is the largest in the window.
   double ATRPercentile(const int window) const
     {
      if(!m_has_atr || window <= 0 || m_count < 2)
         return(0.5);
      int n = MathMin(window, m_count);
      int below = 0;
      int start = (m_head - n + VOL_ENGINE_MAX_BARS) % VOL_ENGINE_MAX_BARS;
      for(int i = 0; i < n; i++)
        {
         int idx = (start + i) % VOL_ENGINE_MAX_BARS;
         if(m_atr_series[idx] < m_atr)
            below++;
        }
      return((double)below / n);
     }

   // Simple expansion flag: current ATR is above mean+1σ of the window.
   bool IsExpanding(const int window) const
     {
      if(!m_has_atr || window <= 0 || m_count < 2)
         return(false);
      int n = MathMin(window, m_count);
      double sum = 0.0;
      int start = (m_head - n + VOL_ENGINE_MAX_BARS) % VOL_ENGINE_MAX_BARS;
      for(int i = 0; i < n; i++)
        {
         int idx = (start + i) % VOL_ENGINE_MAX_BARS;
         sum += m_atr_series[idx];
        }
      double mean = sum / n;
      double var = 0.0;
      for(int i = 0; i < n; i++)
        {
         int idx = (start + i) % VOL_ENGINE_MAX_BARS;
         double d = m_atr_series[idx] - mean;
         var += d * d;
        }
      var /= MathMax(1, n - 1);
      double std = MathSqrt(var);
      return(std > 0.0 && m_atr > mean + std);
     }

   // Current ATR in points (for spread-relative decisions).
   double ATRPoints() const
     {
      double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
      return(point > 0.0 ? m_atr / point : 0.0);
     }

private:
   void BufferPush(const double log_return, const double atr)
     {
      m_log_returns[m_head] = log_return;
      m_atr_series[m_head]  = atr;
      m_head = (m_head + 1) % VOL_ENGINE_MAX_BARS;
      if(m_count < VOL_ENGINE_MAX_BARS)
         m_count++;
     }
  };

#endif // MITEMSHUB_MARKET_VOLATILITYENGINE_MQH
