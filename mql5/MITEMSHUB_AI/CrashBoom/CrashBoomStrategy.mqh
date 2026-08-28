//+------------------------------------------------------------------+
//|                                 CrashBoom/CrashBoomStrategy.mqh  |
//|  MITEMSHUB AI — CRASH/Boom STRATEGY ENGINE                      |
//|                                                                  |
//|  Entry strategies for Crash/Boom indices:                        |
//|  1. POST-SPIKE FADE: After a spike, fade the overshoot          |
//|  2. GRIND CONTINUATION: Enter with the grind (tight stops)      |
//|  3. SPIKE-AVOID: Don't enter when spike probability is high     |
//|                                                                  |
//|  Exit strategies:                                                |
//|  1. QUICK TRAIL: Tighter trailing stops than Volatility mode    |
//|  2. SPIKE EXIT: Exit immediately if spike probability spikes    |
//|  3. PROFIT LOCK: Lock profit at lower thresholds               |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CRASHBOOM_STRATEGY_MQH
#define MITEMSHUB_CRASHBOOM_STRATEGY_MQH

#include "SpikeDetector.mqh"

//--- Crash/Boom signal types
enum ENUM_CB_SIGNAL
{
   CB_NONE = 0,
   CB_POST_SPIKE_FADE = 1,    // Fade after spike
   CB_GRIND_CONTINUATION = 2, // Enter with grind direction
   CB_SPIKE_AVOID = 3         // Block entry (spike imminent)
};

class CCrashBoomStrategy
{
private:
   CSpikeDetector* m_spike_detector;
   
   //--- Symbol type detection
   bool m_is_crash;  // true = Crash index, false = Boom index
   bool m_is_enabled;
   
   //--- Indicator handles (created ONCE in Init, reused everywhere)
   int      m_bb_handle;
   int      m_atr_handle;
   double   m_bb_upper, m_bb_middle, m_bb_lower;
   double   m_bb_deviation;
   
   //--- Strategy parameters
   double   m_spike_threshold;      // body ratio to count as spike (default 3.0)
   int      m_spike_cooldown_bars;  // bars to wait after spike before entering
   double   m_fade_r_entry;         // R level to enter fade after spike
   double   m_fade_sl_atr_mult;     // stop loss = this x ATR
   double   m_fade_tp_atr_mult;     // take profit = this x ATR
   double   m_grind_sl_mult;        // stop for grind continuation = this x avg body
   double   m_max_spike_prob;       // block entries above this probability
   int      m_post_spike_window;   // bars after spike that fade is valid
   
   //--- Current state
   ENUM_CB_SIGNAL m_last_signal;
   int      m_last_signal_dir;
   double   m_last_signal_entry;
   double   m_last_signal_sl;
   double   m_last_signal_tp;
   string   m_last_signal_reason;

public:
   CCrashBoomStrategy()
   {
      m_spike_detector = NULL;
      m_is_crash = false;
      m_is_enabled = false;
      m_bb_handle = INVALID_HANDLE;
      m_atr_handle = INVALID_HANDLE;
      m_bb_upper = 0;
      m_bb_middle = 0;
      m_bb_lower = 0;
      m_bb_deviation = 2.0;
      
      // Default parameters
      m_spike_threshold = 3.0;
      m_spike_cooldown_bars = 2;
      m_fade_r_entry = 0.3;        // enter at 0.3R into the fade
      m_fade_sl_atr_mult = 0.5;
      m_fade_tp_atr_mult = 1.5;
      m_grind_sl_mult = 2.0;
      m_max_spike_prob = 0.65;
      m_post_spike_window = 5;
      
      m_last_signal = CB_NONE;
      m_last_signal_dir = 0;
      m_last_signal_entry = 0;
      m_last_signal_sl = 0;
      m_last_signal_tp = 0;
      m_last_signal_reason = "";
   }
   
   ~CCrashBoomStrategy()
   {
      // Don't delete m_spike_detector — caller owns it
   }

   //--- Initialize
   void Init(CSpikeDetector* detector, bool is_crash_index, bool enabled)
   {
      m_spike_detector = detector;
      m_is_crash = is_crash_index;
      m_is_enabled = enabled;
      
      if(enabled)
      {
         // Create indicator handles ONCE — reuse on every bar
         m_bb_handle = iBands(_Symbol, PERIOD_M5, 20, 0, m_bb_deviation, PRICE_CLOSE);
         m_atr_handle = iATR(_Symbol, PERIOD_M5, 14);
         
         if(m_bb_handle == INVALID_HANDLE)
            Print("[CB] WARNING: Failed to create BB handle");
         if(m_atr_handle == INVALID_HANDLE)
            Print("[CB] WARNING: Failed to create ATR handle");
         
         PrintFormat("[CB] Initialized: %s mode, spike_threshold=%.1f, max_spike_prob=%.2f",
                     is_crash_index ? "CRASH" : "BOOM",
                     m_spike_threshold, m_max_spike_prob);
      }
   }

   //--- Release indicator handles on shutdown
   void Deinit()
   {
      if(m_bb_handle != INVALID_HANDLE) IndicatorRelease(m_bb_handle);
      if(m_atr_handle != INVALID_HANDLE) IndicatorRelease(m_atr_handle);
      m_bb_handle = INVALID_HANDLE;
      m_atr_handle = INVALID_HANDLE;
   }

   //--- Set parameters
   void SetSpikeThreshold(double threshold)     { m_spike_threshold = threshold; }
   void SetFadeR(double r)                       { m_fade_r_entry = r; }
   void SetFadeSL(double atr_mult)               { m_fade_sl_atr_mult = atr_mult; }
   void SetFadeTP(double atr_mult)               { m_fade_tp_atr_mult = atr_mult; }
   void SetMaxSpikeProb(double prob)             { m_max_spike_prob = prob; }
   void SetPostSpikeWindow(int bars)             { m_post_spike_window = bars; }
   void SetSpikeCooldown(int bars)               { m_spike_cooldown_bars = bars; }

   //--- Main signal generation (call on each bar close)
   //    Returns direction (1=BUY, -1=SELL, 0=no signal)
   //    and fills in entry/SL/TP
   int GenerateSignal(double &entry, double &sl, double &tp, string &reason)
   {
      if(!m_is_enabled || m_spike_detector == NULL) return 0;
      
      m_last_signal = CB_NONE;
      m_last_signal_dir = 0;
      reason = "";
      
      //--- Step 1: Check if spike probability is too high → BLOCK
      double spike_prob = m_spike_detector->GetSpikeProbability();
      if(spike_prob > m_max_spike_prob)
      {
         reason = StringFormat("SPIKE-AVOID prob=%.2f > %.2f", spike_prob, m_max_spike_prob);
         m_last_signal = CB_SPIKE_AVOID;
         TelemLog(reason);
         return 0;
      }
      
      //--- Step 2: Check for POST-SPIKE FADE opportunity
      int fade_dir = CheckPostSpikeFade(entry, sl, tp, reason);
      if(fade_dir != 0)
      {
         m_last_signal = CB_POST_SPIKE_FADE;
         m_last_signal_dir = fade_dir;
         m_last_signal_entry = entry;
         m_last_signal_sl = sl;
         m_last_signal_tp = tp;
         m_last_signal_reason = reason;
         return fade_dir;
      }
      
      //--- Step 3: Check for GRIND CONTINUATION entry
      int grind_dir = CheckGrindContinuation(entry, sl, tp, reason);
      if(grind_dir != 0)
      {
         m_last_signal = CB_GRIND_CONTINUATION;
         m_last_signal_dir = grind_dir;
         m_last_signal_entry = entry;
         m_last_signal_sl = sl;
         m_last_signal_tp = tp;
         m_last_signal_reason = reason;
         return grind_dir;
      }
      
      return 0;
   }

   //--- Update Bollinger Bands (call on each bar)
   void UpdateBands()
   {
      if(m_bb_handle == INVALID_HANDLE) return;
      
      double upper[], middle[], lower[];
      ArraySetAsSeries(upper, true);
      ArraySetAsSeries(middle, true);
      ArraySetAsSeries(lower, true);
      
      if(CopyBuffer(m_bb_handle, 1, 1, 1, upper) < 1) return;
      if(CopyBuffer(m_bb_handle, 0, 1, 1, middle) < 1) return;
      if(CopyBuffer(m_bb_handle, 2, 1, 1, lower) < 1) return;
      
      m_bb_upper = upper[0];
      m_bb_middle = middle[0];
      m_bb_lower = lower[0];
   }

private:
   //--- Check for post-spike fade opportunity
   int CheckPostSpikeFade(double &entry, double &sl, double &tp, string &reason)
   {
      if(!m_spike_detector->SpikeJustHappened(m_post_spike_window)) return 0;
      
      // Get ATR using pre-created handle (no leak)
      double atr[];
      ArraySetAsSeries(atr, true);
      if(m_atr_handle == INVALID_HANDLE) return 0;
      if(CopyBuffer(m_atr_handle, 0, 1, 1, atr) < 1) return 0;
      
      double current_price = iClose(_Symbol, PERIOD_M5, 0);
      int bars_since_spike = m_spike_detector->GetGrindDuration();  // approximate
      
      //--- CRASH index: spikes go DOWN → fade by BUYING
      if(m_is_crash)
      {
         // Check if price has retraced enough from spike low
         double spike_low = iLow(_Symbol, PERIOD_M5, 1);
         double spike_body = MathAbs(iClose(_Symbol, PERIOD_M5, 1) - iOpen(_Symbol, PERIOD_M5, 1));
         
         if(spike_body > 0 && current_price > spike_low)
         {
            double retrace = (current_price - spike_low) / spike_body;
            
            // Enter if retracted 30-70% of spike
            if(retrace >= m_fade_r_entry && retrace <= 0.70)
            {
               entry = current_price;
               sl = entry - m_fade_sl_atr_mult * atr[0];
               tp = entry + m_fade_tp_atr_mult * atr[0];
               
               // Ensure TP is above spike high
               double spike_high = iHigh(_Symbol, PERIOD_M5, 1);
               if(tp < spike_high) tp = spike_high + atr[0] * 0.2;
               
               reason = StringFormat("CB-FADE-BUY retrace=%.0f%% bars=%d", retrace*100, bars_since_spike);
               return 1;  // BUY
            }
         }
      }
      //--- BOOM index: spikes go UP → fade by SELLING
      else
      {
         double spike_high = iHigh(_Symbol, PERIOD_M5, 1);
         double spike_body = MathAbs(iClose(_Symbol, PERIOD_M5, 1) - iOpen(_Symbol, PERIOD_M5, 1));
         
         if(spike_body > 0 && current_price < spike_high)
         {
            double retrace = (spike_high - current_price) / spike_body;
            
            if(retrace >= m_fade_r_entry && retrace <= 0.70)
            {
               entry = current_price;
               sl = entry + m_fade_sl_atr_mult * atr[0];
               tp = entry - m_fade_tp_atr_mult * atr[0];
               
               double spike_low = iLow(_Symbol, PERIOD_M5, 1);
               if(tp > spike_low) tp = spike_low - atr[0] * 0.2;
               
               reason = StringFormat("CB-FADE-SELL retrace=%.0f%% bars=%d", retrace*100, bars_since_spike);
               return -1;  // SELL
            }
         }
      }
      
      return 0;
   }

   //--- Check for grind continuation entry
   int CheckGrindContinuation(double &entry, double &sl, double &tp, string &reason)
   {
      int grind_dir = m_spike_detector->GetGrindDirection();
      int grind_dur = m_spike_detector->GetGrindDuration();
      
      // Need at least 5 bars of grind
      if(grind_dir == 0 || grind_dur < 5) return 0;
      
      // Don't enter if grind is too long (spike imminent)
      if(grind_dur > 15)
      {
         reason = StringFormat("CB-GRIND-TOO-LONG dur=%d", grind_dur);
         return 0;
      }
      
      // Get ATR using pre-created handle (no leak)
      double atr[];
      ArraySetAsSeries(atr, true);
      if(m_atr_handle == INVALID_HANDLE) return 0;
      if(CopyBuffer(m_atr_handle, 0, 1, 1, atr) < 1) return 0;
      
      double body_avg = m_spike_detector->GetGrindBodyAvg();
      double current_price = iClose(_Symbol, PERIOD_M5, 0);
      
      //--- Grind UP → BUY with the trend
      if(grind_dir > 0 && !m_is_crash)  // Boom grind up = buy
      {
         entry = current_price;
         sl = entry - m_grind_sl_mult * body_avg;
         tp = entry + m_grind_sl_mult * body_avg * 2.0;  // 2:1 R:R
         
         reason = StringFormat("CB-GRIND-BUY dur=%d body_avg=%.5f", grind_dur, body_avg);
         return 1;
      }
      else if(grind_dir > 0 && m_is_crash)  // Crash grind up = sell (spike will be down)
      {
         entry = current_price;
         sl = entry + m_grind_sl_mult * body_avg;
         tp = entry - m_grind_sl_mult * body_avg * 2.0;
         
         reason = StringFormat("CB-GRIND-SELL dur=%d body_avg=%.5f", grind_dur, body_avg);
         return -1;
      }
      else if(grind_dir < 0 && m_is_crash)  // Crash grind down = buy (spike will be up)
      {
         entry = current_price;
         sl = entry - m_grind_sl_mult * body_avg;
         tp = entry + m_grind_sl_mult * body_avg * 2.0;
         
         reason = StringFormat("CB-GRIND-BUY dur=%d body_avg=%.5f", grind_dur, body_avg);
         return 1;
      }
      else if(grind_dir < 0 && !m_is_crash)  // Boom grind down = sell
      {
         entry = current_price;
         sl = entry + m_grind_sl_mult * body_avg;
         tp = entry - m_grind_sl_mult * body_avg * 2.0;
         
         reason = StringFormat("CB-GRIND-SELL dur=%d body_avg=%.5f", grind_dur, body_avg);
         return -1;
      }
      
      return 0;
   }

   //--- Log telemetry
   void TelemLog(string msg)
   {
      PrintFormat("[CB] %s", msg);
   }
};

#endif
