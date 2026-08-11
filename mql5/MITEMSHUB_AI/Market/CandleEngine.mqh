//+------------------------------------------------------------------+
//|                                     Market/CandleEngine.mqh      |
//|  MITEMSHUB AI MARKET ENGINE — per-timeframe candle ring buffers. |
//|                                                                  |
//|  Stores the last CAP closed bars per registered timeframe.       |
//|  Push model (live path feeds closed bars; the tester path can    |
//|  bulk-load from CopyRates).  Only CLOSED bars are ever stored —  |
//|  the forming bar is never part of a decision input (no look-     |
//|  ahead, no repainting).                                         |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_CANDLEENGINE_MQH
#define MITEMSHUB_MARKET_CANDLEENGINE_MQH

#include "../Core/Constants.mqh"

#define CANDLE_ENGINE_CAPACITY 500
#define CANDLE_ENGINE_MAX_TFS  8

class CCandleEngine
  {
private:
   ENUM_TIMEFRAMES m_tfs[CANDLE_ENGINE_MAX_TFS];
   MqlRates        m_bars[CANDLE_ENGINE_MAX_TFS][CANDLE_ENGINE_CAPACITY];
   int             m_head[CANDLE_ENGINE_MAX_TFS];   // next write slot
   int             m_count[CANDLE_ENGINE_MAX_TFS];
   int             m_ntfs;

   int TfIndex(const ENUM_TIMEFRAMES tf) const
     {
      for(int i = 0; i < m_ntfs; i++)
         if(m_tfs[i] == tf)
            return(i);
      return(-1);
     }

public:
   CCandleEngine()
     {
      m_ntfs = 0;
      ArrayInitialize(m_head, 0);
      ArrayInitialize(m_count, 0);
     }

   //--- Register a timeframe this engine should track (idempotent).
   void RegisterTimeframe(const ENUM_TIMEFRAMES tf)
     {
      if(m_ntfs >= CANDLE_ENGINE_MAX_TFS || TfIndex(tf) >= 0)
         return;
      m_tfs[m_ntfs++] = tf;
     }

   //--- Push one CLOSED bar.
   void PushBar(const ENUM_TIMEFRAMES tf, const double open, const double high,
                const double low, const double close, const datetime time)
     {
      int idx = TfIndex(tf);
      if(idx < 0)
         return;
      MqlRates r;
      r.time        = time;
      r.open        = open;
      r.high        = high;
      r.low         = low;
      r.close       = close;
      r.tick_volume = 0;
      r.spread      = 0;
      r.real_volume = 0;
      m_bars[idx][m_head[idx]] = r;
      m_head[idx] = (m_head[idx] + 1) % CANDLE_ENGINE_CAPACITY;
      if(m_count[idx] < CANDLE_ENGINE_CAPACITY)
         m_count[idx]++;
     }

   //--- Bars stored for a timeframe (0 if not registered).
   int Count(const ENUM_TIMEFRAMES tf) const
     {
      int i = TfIndex(tf);
      return(i < 0 ? 0 : m_count[i]);
     }

   //--- Latest bar: shift 0 = newest closed, 1 = previous, ...
   bool GetBar(const ENUM_TIMEFRAMES tf, const int shift, MqlRates &out) const
     {
      int i = TfIndex(tf);
      if(i < 0 || shift < 0 || shift >= m_count[i])
         return(false);
      int idx = (m_head[i] - 1 - shift + CANDLE_ENGINE_CAPACITY) % CANDLE_ENGINE_CAPACITY;
      out = m_bars[i][idx];
      return(true);
     }

   //--- Latest close (shift 0 = newest closed).
   bool GetClose(const ENUM_TIMEFRAMES tf, const int shift, double &close) const
     {
      MqlRates r;
      if(!GetBar(tf, shift, r))
         return(false);
      close = r.close;
      return(true);
     }

   //--- Copy the last `count` closes, oldest-first (index 0 = oldest).
   //--- Returns false if fewer than `count` bars are buffered.
   bool GetCloses(const ENUM_TIMEFRAMES tf, double &closes[], const int count) const
     {
      int i = TfIndex(tf);
      if(i < 0 || count <= 0 || count > m_count[i])
         return(false);
      ArrayResize(closes, count);
      for(int k = 0; k < count; k++)
        {
         int idx = (m_head[i] - 1 - k + CANDLE_ENGINE_CAPACITY) % CANDLE_ENGINE_CAPACITY;
         closes[count - 1 - k] = m_bars[i][idx].close;
        }
      return(true);
     }

   //--- Highest / lowest of the last `count` bars.
   bool GetHighLow(const ENUM_TIMEFRAMES tf, const int count,
                   double &high, double &low) const
     {
      int i = TfIndex(tf);
      if(i < 0 || count <= 0 || count > m_count[i])
         return(false);
      high = 0.0;
      low  = 0.0;
      for(int k = 0; k < count; k++)
        {
         int idx = (m_head[i] - 1 - k + CANDLE_ENGINE_CAPACITY) % CANDLE_ENGINE_CAPACITY;
         double h = m_bars[i][idx].high;
         double l = m_bars[i][idx].low;
         if(k == 0 || h > high)
            high = h;
         if(k == 0 || l < low)
            low = l;
        }
      return(true);
     }
  };

#endif // MITEMSHUB_MARKET_CANDLEENGINE_MQH
