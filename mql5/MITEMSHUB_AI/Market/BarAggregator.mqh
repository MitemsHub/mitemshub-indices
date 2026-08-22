//+------------------------------------------------------------------+
//|                                  Market/BarAggregator.mqh        |
//|  MITEMSHUB AI MARKET ENGINE — tick → closed-bar bucketter.       |
//|                                                                  |
//|  Buckets ticks into closed OHLC bars of a fixed wall-clock       |
//|  timeframe using the SAME convention as the Python CandleBuilder |
//|  (src/synthetic_trader/data/candles.py):                         |
//|    bucket = floor(epoch / bar_sec) * bar_sec                     |
//|    - same-bucket tick   → update high/low/close in place         |
//|    - next-bucket tick   → close the current bar, start a new one |
//|    - multi-bucket jump  → skipped buckets have no ticks, so no   |
//|      empty bars are fabricated (matches Python exactly)          |
//|  OnTick returns TRUE exactly once when a bar closes, so the EA   |
//|  runs its per-bar pipeline (signal/decide/risk/manage) ONCE per  |
//|  closed execution bar — closed-candle discipline, no lookahead,  |
//|  no repainting.  The closed bar is consumed via ClosedBar()      |
//|  (exactly-once; a second read returns false).                    |
//|                                                                  |
//|  NOTE: the Python builder's price-outlier guard (the Deriv→      |
//|  Deriv venue-leak hygiene) is deliberately NOT ported: this  |
//|  aggregator consumes a single MT5 feed, so there is no venue     |
//|  mixing to guard against here.                                   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_BARAGGREGATOR_MQH
#define MITEMSHUB_MARKET_BARAGGREGATOR_MQH

#include "../Core/Constants.mqh"

struct AggregatedBar
  {
   datetime time;         // bucket start (floor(time/bar_sec)*bar_sec)
   double   open;
   double   high;
   double   low;
   double   close;
   int      tick_count;
  };

class CBarAggregator
  {
private:
   int      m_bar_sec;
   bool     m_has_bar;     // a forming bar exists
   datetime m_bucket;      // open_time of the forming bar
   AggregatedBar m_bar;    // forming bar
   AggregatedBar m_closed; // last closed bar (until consumed)
   bool     m_has_closed;

public:
   CBarAggregator(const int bar_sec = 300)
     {
      Reset(bar_sec);
     }

   void Reset(const int bar_sec = 300)
     {
      m_bar_sec    = (bar_sec > 0) ? bar_sec : 300;
      m_has_bar    = false;
      m_bucket     = 0;
      m_has_closed = false;
      ZeroMemory(m_bar);
      ZeroMemory(m_closed);
     }

   int BarSec() const { return(m_bar_sec); }

   //--- Feed one tick.  Returns TRUE iff this tick CLOSED a bar; the
   //--- finished OHLC is then available via ClosedBar().  For a monotonic
   //--- tick stream this fires exactly once per closed bar.  A stale tick
   //--- (time earlier than the forming bar) is ignored — it can never close
   //--- a bar, so a reordered/duplicated tick cannot fabricate a signal.
   bool OnTick(const double price, const datetime time)
     {
      if(time < m_bar.time && m_has_bar)
         return(false);                     // stale tick — ignore

      datetime bucket = (datetime)(((long)time / (long)m_bar_sec) * (long)m_bar_sec);
      if(!m_has_bar)
        {
         m_has_bar = true;
         m_bucket  = bucket;
         m_bar.time = bucket;
         m_bar.open = price;
         m_bar.high = price;
         m_bar.low  = price;
         m_bar.close = price;
         m_bar.tick_count = 1;
         return(false);
        }

      if(bucket == m_bucket)
        {
         if(price > m_bar.high) m_bar.high = price;
         if(price < m_bar.low)  m_bar.low  = price;
         m_bar.close = price;
         m_bar.tick_count++;
         return(false);
        }

      // Bucket boundary crossed: the forming bar is closed; the new bar
      // starts at the new bucket with this tick (multi-bucket jumps skip
      // the empty buckets — same as Python).
      m_closed    = m_bar;
      m_has_closed = true;
      m_bucket    = bucket;
      m_bar.time  = bucket;
      m_bar.open  = price;
      m_bar.high  = price;
      m_bar.low   = price;
      m_bar.close = price;
      m_bar.tick_count = 1;
      return(true);
     }

   //--- Consume the last closed bar (exactly-once: a second call returns
   //--- false until the next bar closes).
   bool ClosedBar(AggregatedBar &out)
     {
      if(!m_has_closed)
         return(false);
      out         = m_closed;
      m_has_closed = false;
      return(true);
     }

   //--- The currently-forming bar (read-only peek; never used for signals).
   bool FormingBar(AggregatedBar &out) const
     {
      if(!m_has_bar)
         return(false);
      out = m_bar;
      return(true);
     }
  };
#endif
