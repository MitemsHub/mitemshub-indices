//+------------------------------------------------------------------+
//|                                    Structure/StructureEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — structure aggregation.             |
//|                                                                  |
//|  Consumes the Phase-2 CandleEngine (closed-bar ring buffers),    |
//|  pulls the latest window of bars for one timeframe, and runs     |
//|  every Structure detector over it: swings, BOS, CHOCH, liquidity |
//|  sweeps, support/resistance clusters, and displacement.          |
//|                                                                  |
//|  Outputs a single structure state: BIAS (bullish / bearish /     |
//|  neutral) plus the most recent structure event with its          |
//|  direction/price/time.  CHOCH outranks BOS for the bias (a       |
//|  character change is a stronger statement than a continuation    |
//|  break); the swing sequence is the fallback when no event fired. |
//|                                                                  |
//|  Per the architecture decision, structure is a RESEARCH input    |
//|  only: it feeds the research strategies, never the active band   |
//|  leg by default.                                                 |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRUCTURE_STRUCTUREENGINE_MQH
#define MITEMSHUB_STRUCTURE_STRUCTUREENGINE_MQH

#include "../Core/Constants.mqh"
#include "../Market/CandleEngine.mqh"
#include "SwingDetector.mqh"
#include "BOSDetector.mqh"
#include "CHOCHDetector.mqh"
#include "LiquidityEngine.mqh"
#include "SupportResistance.mqh"
#include "DisplacementDetector.mqh"

class CStructureEngine
  {
private:
   ENUM_TIMEFRAMES m_tf;
   int      m_swing_left;
   int      m_swing_right;
   int      m_window;
   double   m_atr;
   // latest window of closed bars (oldest-first)
   double   m_opens[], m_highs[], m_lows[], m_closes[];
   datetime m_times[];
   // detector outputs
   SwingPoint   m_swings[];
   BOSEvent     m_bos[];
   CHOCH        m_choch[];
   Sweep        m_sweeps[];
   SRLevel      m_sr[];
   Displacement m_disp[];
   // derived state
   int      m_bias;          // ENUM_STRUCTURE_BIAS
   int      m_last_event;    // ENUM_STRUCTURE_EVENT
   int      m_last_direction;
   double   m_last_event_price;
   datetime m_last_event_time;

   void ComputeLastEvent()
     {
      m_last_event      = STRUCT_EVENT_NONE;
      m_last_direction  = 0;
      m_last_event_price = 0.0;
      m_last_event_time = 0;
      // Every list is emitted in bar order, so the newest is the last element.
      // Strict `>` comparisons make CHOCH win ties over BOS, BOS over SWEEP,
      // SWEEP over DISPLACEMENT (higher-priority type = earlier in code).
      datetime t = 0;
      int      type = STRUCT_EVENT_NONE, dir = 0;
      double   price = 0.0;
      if(ArraySize(m_choch) > 0)
        {
         CHOCH c = m_choch[ArraySize(m_choch) - 1];
         t = c.time; type = STRUCT_EVENT_CHOCH; dir = c.direction; price = c.price;
        }
      if(ArraySize(m_bos) > 0)
        {
         BOSEvent b = m_bos[ArraySize(m_bos) - 1];
         if(b.time > t)
           {
            t = b.time; type = STRUCT_EVENT_BOS; dir = b.direction; price = b.price;
           }
        }
      if(ArraySize(m_sweeps) > 0)
        {
         Sweep s = m_sweeps[ArraySize(m_sweeps) - 1];
         if(s.time > t)
           {
            t = s.time; type = STRUCT_EVENT_SWEEP; dir = s.direction; price = s.level;
           }
        }
      if(ArraySize(m_disp) > 0)
        {
         Displacement d = m_disp[ArraySize(m_disp) - 1];
         if(d.bar >= 0 && d.bar < ArraySize(m_times) && m_times[d.bar] > t)
           {
            t = m_times[d.bar]; type = STRUCT_EVENT_DISPLACEMENT; dir = d.direction; price = m_closes[d.bar];
           }
        }
      m_last_event      = type;
      m_last_direction  = dir;
      m_last_event_price = price;
      m_last_event_time = t;
     }

   void ComputeBias()
     {
      ComputeLastEvent();
      // A structure change (CHOCH) or a continuation break (BOS) sets the bias.
      if(m_last_event == STRUCT_EVENT_CHOCH || m_last_event == STRUCT_EVENT_BOS)
        {
         m_bias = m_last_direction > 0 ? STRUCT_BIAS_BULLISH : STRUCT_BIAS_BEARISH;
         return;
        }
      // Fallback: the swing sequence itself (HH+HL vs LH+LL).
      m_bias = STRUCT_BIAS_NEUTRAL;
      double sh1 = 0.0, sh0 = 0.0, sl1 = 0.0, sl0 = 0.0;
      for(int i = 0; i < ArraySize(m_swings); i++)
        {
         if(m_swings[i].direction > 0)
           {
            sh1 = sh0;
            sh0 = m_swings[i].price;
           }
         else
           {
            sl1 = sl0;
            sl0 = m_swings[i].price;
           }
        }
      if(sh0 > 0.0 && sh1 > 0.0 && sl0 > 0.0 && sl1 > 0.0)
        {
         if(sh0 > sh1 && sl0 > sl1)
            m_bias = STRUCT_BIAS_BULLISH;
         else if(sh0 < sh1 && sl0 < sl1)
            m_bias = STRUCT_BIAS_BEARISH;
        }
     }

public:
   CStructureEngine()
     {
      m_tf            = PERIOD_CURRENT;
      m_swing_left    = DEFAULT_SWING_LEFT;
      m_swing_right   = DEFAULT_SWING_RIGHT;
      m_window        = DEFAULT_STRUCTURE_LOOKBACK;
      m_atr           = 0.0;
      m_bias          = STRUCT_BIAS_NEUTRAL;
      m_last_event    = STRUCT_EVENT_NONE;
      m_last_direction = 0;
      m_last_event_price = 0.0;
      m_last_event_time  = 0;
     }

   void SetParams(const int swing_left, const int swing_right, const int window)
     {
      m_swing_left  = swing_left;
      m_swing_right = swing_right;
      m_window      = window;
     }

   //--- Pull the latest closed bars from the CandleEngine and recompute.
   //--- Returns false when not enough bars are buffered.
   bool Update(const CCandleEngine &ce, const ENUM_TIMEFRAMES tf, const double atr)
     {
      m_tf  = tf;
      m_atr = atr;
      int have = ce.Count(tf);
      int take = have < m_window ? have : m_window;
      if(take < m_swing_left + m_swing_right + 3)
         return(false);

      ArrayResize(m_opens,  take);
      ArrayResize(m_highs,  take);
      ArrayResize(m_lows,   take);
      ArrayResize(m_closes, take);
      ArrayResize(m_times,  take);
      MqlRates r;
      for(int i = 0; i < take; i++)
        {
         // CandleEngine shift 0 = newest; we want oldest-first in the window.
         int shift = take - 1 - i;
         if(!ce.GetBar(tf, shift, r))
            return(false);
         m_opens[i]  = r.open;
         m_highs[i]  = r.high;
         m_lows[i]   = r.low;
         m_closes[i] = r.close;
         m_times[i]  = r.time;
        }

      CSwingDetector::FindSwing(m_highs, m_lows, m_times, take, m_swing_left, m_swing_right,
                                atr, m_swings, 64);
      CBOSDetector::Detect(m_highs, m_lows, m_closes, m_times, take, m_swing_left, m_swing_right,
                           atr, m_bos, 16);
      CCHOCHDetector::Detect(m_highs, m_lows, m_closes, m_times, take, m_swing_left, m_swing_right,
                             atr, m_choch, 16);
      CLiquidityEngine::DetectSweeps(m_highs, m_lows, m_closes, m_times, take,
                                     m_swing_left, m_swing_right, atr, m_sweeps, 16,
                                     DEFAULT_SWEEP_EXCEED_ATR);
      CDisplacementDetector::Detect(m_opens, m_highs, m_lows, m_closes, m_times, take,
                                    atr, m_disp, 16, DEFAULT_DISPLACEMENT_BODY_MULT,
                                    DEFAULT_DISPLACEMENT_RANGE_MULT);

      // S/R clusters from swing prices (kinds carry polarity).
      int nsw = ArraySize(m_swings);
      double   srt_prices[];
      int      srt_kinds[];
      datetime srt_times[];
      ArrayResize(srt_prices, nsw);
      ArrayResize(srt_kinds,  nsw);
      ArrayResize(srt_times,  nsw);
      for(int i = 0; i < nsw; i++)
        {
         srt_prices[i] = m_swings[i].price;
         srt_kinds[i]  = m_swings[i].direction;
         srt_times[i]  = m_swings[i].time;
        }
      CSupportResistance::Cluster(srt_prices, srt_kinds, srt_times, nsw, atr,
                                  DEFAULT_SR_TOL_ATR, m_sr, 32, DEFAULT_MIN_SR_TOUCHES);

      ComputeBias();
      return(true);
     }

   //--- Accessors ------------------------------------------------------------
   int      Bias()                 const { return(m_bias); }
   int      LastEvent()            const { return(m_last_event); }
   int      LastEventDirection()   const { return(m_last_direction); }
   double   LastEventPrice()       const { return(m_last_event_price); }
   datetime LastEventTime()        const { return(m_last_event_time); }
   int      SwingCount()           const { return(ArraySize(m_swings)); }
   int      BOSCount()             const { return(ArraySize(m_bos)); }
   int      CHOCHCount()           const { return(ArraySize(m_choch)); }
   int      SweepCount()           const { return(ArraySize(m_sweeps)); }
   int      SRCount()              const { return(ArraySize(m_sr)); }
   int      DisplacementCount()    const { return(ArraySize(m_disp)); }
   double   ATR()                  const { return(m_atr); }
  };

#endif // MITEMSHUB_STRUCTURE_STRUCTUREENGINE_MQH
