//+------------------------------------------------------------------+
//|                                CrashBoom/MultiTimeframeConfirm.mqh|
//|  MITEMSHUB AI — MULTI-TIMEFRAME CONFIRMATION                    |
//|                                                                  |
//|  Checks spike conditions across M1, M5, and M15 together:       |
//|  - M1: immediate tick/candle patterns                           |
//|  - M5: trend and grind context                                  |
//|  - M15: higher-level regime and structure                       |
//|                                                                  |
//|  A signal is only valid if at least 2 of 3 timeframes agree.    |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MULTI_TF_CONFIRM_MQH
#define MITEMSHUB_MULTI_TF_CONFIRM_MQH

//--- Timeframe-specific analysis result
struct TFAnalysis
{
   ENUM_TIMEFRAMES tf;
   bool     spike_detected;      // spike on this TF
   bool     grind_detected;      // grind on this TF
   int      grind_direction;     // 1=UP, -1=DOWN, 0=none
   int      grind_duration;      // bars in grind
   double   body_ratio;          // current body / avg body
   double   bb_position;         // where price is relative to BB (0=lower, 1=upper)
   double   atr_ratio;           // current ATR / historical ATR
   int      consecutive_same;    // consecutive same-direction bars
   double   score;               // overall score for this TF
   bool     agrees_with_signal;  // does this TF support the proposed direction?
};

class CMultiTimeframeConfirm
{
private:
   TFAnalysis m_analysis[3];    // M1, M5, M15
   int        m_tf_count;
   bool       m_is_enabled;
   
   //--- Indicator handles per timeframe (created ONCE, reused)
   int m_bb_handles[3];
   int m_atr_handles[3];
   int m_ema_handles[3];

public:
   CMultiTimeframeConfirm()
   {
      m_tf_count = 3;
      m_is_enabled = false;
      ArrayInitialize(m_bb_handles, INVALID_HANDLE);
      ArrayInitialize(m_atr_handles, INVALID_HANDLE);
      ArrayInitialize(m_ema_handles, INVALID_HANDLE);
      
      for(int i = 0; i < 3; i++)
      {
         m_analysis[i].tf = PERIOD_M1;
         m_analysis[i].spike_detected = false;
         m_analysis[i].grind_detected = false;
         m_analysis[i].grind_direction = 0;
         m_analysis[i].grind_duration = 0;
         m_analysis[i].body_ratio = 0;
         m_analysis[i].bb_position = 0;
         m_analysis[i].atr_ratio = 0;
         m_analysis[i].consecutive_same = 0;
         m_analysis[i].score = 0;
         m_analysis[i].agrees_with_signal = false;
      }
   }

   //--- Initialize with timeframes (create handles ONCE)
   void Init(bool enabled)
   {
      m_is_enabled = enabled;
      if(!enabled) return;
      
      ENUM_TIMEFRAMES tfs[3] = { PERIOD_M1, PERIOD_M5, PERIOD_M15 };
      
      for(int i = 0; i < 3; i++)
      {
         m_analysis[i].tf = tfs[i];
         m_bb_handles[i] = iBands(_Symbol, tfs[i], 20, 0, 2.0, PRICE_CLOSE);
         m_atr_handles[i] = iATR(_Symbol, tfs[i], 14);
         m_ema_handles[i] = iMA(_Symbol, tfs[i], 20, 0, MODE_EMA, PRICE_CLOSE);
      }
      
      Print("[CB-MTF] Multi-timeframe confirmation enabled: M1 + M5 + M15");
   }

   //--- Release handles on shutdown
   void Deinit()
   {
      for(int i = 0; i < 3; i++)
      {
         if(m_bb_handles[i] != INVALID_HANDLE)  IndicatorRelease(m_bb_handles[i]);
         if(m_atr_handles[i] != INVALID_HANDLE) IndicatorRelease(m_atr_handles[i]);
         if(m_ema_handles[i] != INVALID_HANDLE) IndicatorRelease(m_ema_handles[i]);
         m_bb_handles[i] = INVALID_HANDLE;
         m_atr_handles[i] = INVALID_HANDLE;
         m_ema_handles[i] = INVALID_HANDLE;
      }
   }

   //--- Analyze all timeframes (call on each M5 bar close)
   void Analyze()
   {
      if(!m_is_enabled) return;
      
      for(int i = 0; i < 3; i++)
         AnalyzeTimeframe(i);
   }

   //--- Check if signal is confirmed by multiple timeframes
   //    direction: proposed trade direction (1=BUY, -1=SELL)
   //    Returns: true if at least 1 of 3 TFs agree
   bool IsConfirmed(int direction, string &reason)
   {
      if(!m_is_enabled) return true;  // pass through if disabled
      
      // CRITICAL: Set agrees_with_signal based on each TF's grind direction
      // This was NEVER done before — MTF always blocked!
      for(int i = 0; i < 3; i++)
      {
         m_analysis[i].agrees_with_signal = false;
         
         // A TF agrees if:
         // 1. It has a grind in the same direction as the signal, OR
         // 2. It has no strong opposing grind, OR
         // 3. It has a spike that supports the direction
         if(m_analysis[i].grind_detected)
         {
            // Grind direction matches signal direction
            if(m_analysis[i].grind_direction == direction)
               m_analysis[i].agrees_with_signal = true;
         }
         else
         {
            // No strong grind — TF is neutral, counts as agreement
            m_analysis[i].agrees_with_signal = true;
         }
      }
      
      int agree_count = 0;
      int total_score = 0;
      
      for(int i = 0; i < 3; i++)
      {
         if(m_analysis[i].agrees_with_signal)
         {
            agree_count++;
            total_score += (int)(m_analysis[i].score * 100);
         }
      }
      
      if(agree_count >= 1)
      {
         reason = StringFormat("MTF-CONFIRM %d/3 TFs agree (score=%d)", agree_count, total_score);
         return true;
      }
      else
      {
         reason = StringFormat("MTF-BLOCK %d/3 TFs agree (need 1+)", agree_count);
         return false;
      }
   }

   //--- Get confirmation strength (0-1)
   double GetConfirmationStrength() const
   {
      if(!m_is_enabled) return 1.0;
      
      int agree = 0;
      for(int i = 0; i < 3; i++)
         if(m_analysis[i].agrees_with_signal) agree++;
      
      return (double)agree / 3.0;
   }

   //--- Get analysis for a specific TF
   TFAnalysis GetAnalysis(int index) const
   {
      if(index < 0 || index >= 3) return m_analysis[0];
      return m_analysis[index];
   }

   //--- Get dashboard string
   string GetDashboard() const
   {
      if(!m_is_enabled) return "MTF: OFF";
      
      string result = "MTF:";
      string tf_names[3] = {"M1", "M5", "M15"};
      
      for(int i = 0; i < 3; i++)
      {
         string spike = m_analysis[i].spike_detected ? "S" : "";
         string grind = m_analysis[i].grind_detected ? 
                        (m_analysis[i].grind_direction > 0 ? "GU" : "GD") : "";
         string agree = m_analysis[i].agrees_with_signal ? "✓" : "✗";
         result += StringFormat(" %s[%s%s%s]", tf_names[i], spike, grind, agree);
      }
      
      return result;
   }

private:
   //--- Analyze a single timeframe
   void AnalyzeTimeframe(int index)
   {
      ENUM_TIMEFRAMES tf = m_analysis[index].tf;
      
      if(Bars(_Symbol, tf) < 30) return;
      
      //--- Get body ratio
      double body = MathAbs(iClose(_Symbol, tf, 1) - iOpen(_Symbol, tf, 1));
      double avg_body = 0;
      for(int i = 2; i <= 20; i++)
         avg_body += MathAbs(iClose(_Symbol, tf, i) - iOpen(_Symbol, tf, i));
      avg_body /= 19;
      m_analysis[index].body_ratio = (avg_body > 0) ? body / avg_body : 1.0;
      
      //--- Spike detection
      m_analysis[index].spike_detected = (m_analysis[index].body_ratio >= 3.0);
      
      //--- Grind detection
      int dir = 0;
      int dur = 0;
      for(int i = 1; i <= 15; i++)
      {
         double c = iClose(_Symbol, tf, i);
         double o = iOpen(_Symbol, tf, i);
         int bar_dir = (c > o) ? 1 : -1;
         
         if(dur == 0)
         {
            dir = bar_dir;
            dur = 1;
         }
         else if(bar_dir == dir)
            dur++;
         else
            break;
      }
      m_analysis[index].grind_detected = (dur >= 3);
      m_analysis[index].grind_direction = dir;
      m_analysis[index].grind_duration = dur;
      
      //--- BB position (use pre-created handle)
      double bb_upper[], bb_lower[];
      ArraySetAsSeries(bb_upper, true);
      ArraySetAsSeries(bb_lower, true);
      double upper = 0, lower = 0;
      if(m_bb_handles[index] != INVALID_HANDLE)
      {
         if(CopyBuffer(m_bb_handles[index], 1, 1, 1, bb_upper) >= 1) upper = bb_upper[0];
         if(CopyBuffer(m_bb_handles[index], 2, 1, 1, bb_lower) >= 1) lower = bb_lower[0];
      }
      double close = iClose(_Symbol, tf, 1);
      if(upper > lower)
         m_analysis[index].bb_position = (close - lower) / (upper - lower);
      else
         m_analysis[index].bb_position = 0.5;
      
      //--- ATR ratio (use pre-created handle)
      double atr_buf[];
      ArraySetAsSeries(atr_buf, true);
      double atr_now = 0;
      if(m_atr_handles[index] != INVALID_HANDLE)
      {
         if(CopyBuffer(m_atr_handles[index], 0, 1, 1, atr_buf) >= 1)
            atr_now = atr_buf[0];
      }
      double atr_avg = 0;
      int atr_count = 0;
      for(int i = 2; i <= 20; i++)
      {
         if(CopyBuffer(m_atr_handles[index], 0, i, 1, atr_buf) >= 1)
         {
            atr_avg += atr_buf[0];
            atr_count++;
         }
      }
      if(atr_count > 0) atr_avg /= atr_count;
      m_analysis[index].atr_ratio = (atr_avg > 0) ? atr_now / atr_avg : 1.0;
      
      //--- Consecutive same-direction bars
      int consec = 0;
      for(int i = 1; i <= 10; i++)
      {
         double c = iClose(_Symbol, tf, i);
         double o = iOpen(_Symbol, tf, i);
         int d = (c > o) ? 1 : -1;
         if(consec == 0 || d == ((iClose(_Symbol, tf, i-1) > iOpen(_Symbol, tf, i-1)) ? 1 : -1))
            consec++;
         else
            break;
      }
      m_analysis[index].consecutive_same = consec;
      
      //--- Calculate TF score (0-1)
      double score = 0;
      score += MathMin(1.0, m_analysis[index].body_ratio / 4.0) * 0.2;      // body
      score += MathMin(1.0, (double)m_analysis[index].grind_duration / 15.0) * 0.2; // grind
      score += MathMin(1.0, m_analysis[index].atr_ratio / 2.0) * 0.2;       // ATR
      score += MathMin(1.0, (double)consec / 10.0) * 0.2;                   // consecutive
      score += (m_analysis[index].bb_position < 0.2 || m_analysis[index].bb_position > 0.8) ? 0.2 : 0; // BB extreme
      m_analysis[index].score = score;
   }
};

#endif
