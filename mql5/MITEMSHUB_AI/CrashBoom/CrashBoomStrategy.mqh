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
   CSpikeDetector  m_spike_detector_obj;  // owned copy, not a pointer
   
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
   double   m_min_rr;               // minimum planned reward:risk
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
   
   //--- v24.11: Post-trade trend-reversal guard
   int      m_last_trade_dir;       // direction of last closed trade (+1/-1)
   double   m_last_trade_entry;     // entry price of last trade
   int      m_bars_since_last_trade; // bars elapsed since last trade closed
   bool     m_needs_reversal;       // if true, must see trend reversal before re-entry

   //--- v25: Grind leg control
   bool     m_enable_grind;         // false = fade-only mode

   //--- v25: Fade-only optimized parameters
   double   m_fade_retrace_max;     // max retrace % for entry (quality filter)
   double   m_breakeven_r;          // lock SL at entry after this R
   bool     m_use_trail;            // use trailing stop in CB mode
   bool     m_require_spike_direction; // require spike candle to match index direction
   double   m_min_atr_points;       // reject untradeably small ATR values

public:
   CCrashBoomStrategy()
   {
      // m_spike_detector_obj initialized by default constructor
      m_is_crash = false;
      m_is_enabled = false;
      m_bb_handle = INVALID_HANDLE;
      m_atr_handle = INVALID_HANDLE;
      m_bb_upper = 0;
      m_bb_middle = 0;
      m_bb_lower = 0;
      m_bb_deviation = 2.0;
      
      // Default parameters (v25: optimized from 60-day Boom 1000 data)
      m_spike_threshold = 2.8;       // optimized: 2.8x avg body
      m_spike_cooldown_bars = 1;     // optimized: 1 bar cooldown
      m_fade_r_entry = 0.40;         // optimized: enter at 40% retrace (deeper = cleaner)
      m_fade_sl_atr_mult = 0.4;     // optimized: tighter stop = 0.4x ATR
      m_fade_tp_atr_mult = 3.5;     // optimized: wider target = 3.5x ATR (PF 10.33)
      m_min_rr = 2.0;               // reject plans whose geometry is not asymmetric
      m_fade_retrace_max = 0.50;    // optimized: max 50% retrace (quality filter)
      m_grind_sl_mult = 2.0;
      m_max_spike_prob = 0.70;      // optimized: 70% spike prob threshold
      m_post_spike_window = 5;
      m_breakeven_r = 0.5;          // optimized: lock at 0.5R
      m_use_trail = false;           // optimized: trailing KILLS expectancy on CB fade
      m_require_spike_direction = true;
      m_min_atr_points = 0.0;
      
      m_last_signal = CB_NONE;
      m_last_signal_dir = 0;
      m_last_signal_entry = 0;
      m_last_signal_sl = 0;
      m_last_signal_tp = 0;
      m_last_signal_reason = "";
      
      // v24.11: post-trade trend-reversal guard
      m_last_trade_dir = 0;
      m_last_trade_entry = 0;
      m_bars_since_last_trade = 999;
      m_needs_reversal = false;

      // v25: default to fade-only
      m_enable_grind = false;
   }
   
   ~CCrashBoomStrategy()
   {
      // Object member — no manual delete needed
   }

   //--- Initialize
   void Init(CSpikeDetector &detector, bool is_crash_index, bool enabled)
   {
      // Copy the detector state from the engine's instance
      m_spike_detector_obj = detector;
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

   //--- Update spike detector state from engine (call on every bar)
   //    CRITICAL: Without this, strategy uses stale copy from init time
   void UpdateSpikeDetector(const CSpikeDetector &detector)
   {
      m_spike_detector_obj = detector;
   }

   //--- Set parameters
   void SetSpikeThreshold(double threshold)     { m_spike_threshold = threshold; }
   void SetFadeR(double r)                       { m_fade_r_entry = r; }
   void SetFadeSL(double atr_mult)               { m_fade_sl_atr_mult = atr_mult; }
   void SetFadeTP(double atr_mult)               { m_fade_tp_atr_mult = atr_mult; }
   void SetMinRR(double rr)                       { m_min_rr = MathMax(0.0, rr); }
   void SetMaxSpikeProb(double prob)             { m_max_spike_prob = prob; }
   double GetMaxSpikeProb() const                { return m_max_spike_prob; }
   void SetPostSpikeWindow(int bars)             { m_post_spike_window = bars; }
   int  GetPostSpikeWindow() const               { return m_post_spike_window; }
   void SetSpikeCooldown(int bars)               { m_spike_cooldown_bars = bars; }
   void SetEnableGrind(bool val)                 { m_enable_grind = val; }
   bool IsGrindEnabled() const                   { return m_enable_grind; }
   void SetFadeRetraceMax(double val)            { m_fade_retrace_max = val; }
   void SetBreakevenR(double val)                { m_breakeven_r = val; }
   void SetUseTrail(bool val)                    { m_use_trail = val; }
   void SetRequireSpikeDirection(bool val)        { m_require_spike_direction = val; }
   void SetMinATRPoints(double val)               { m_min_atr_points = MathMax(0.0, val); }
   double GetFadeRetraceMax() const              { return m_fade_retrace_max; }
   double GetBreakevenR() const                  { return m_breakeven_r; }
   bool   GetUseTrail() const                    { return m_use_trail; }
   
   //--- v24.11: Track when a trade closes (call from main EA's ClosePosition)
   void OnTradeClosed(int dir, double entry_price)
   {
      m_last_trade_dir = dir;
      m_last_trade_entry = entry_price;
      m_bars_since_last_trade = 0;
      m_needs_reversal = true;  // must see trend reversal before re-entry
   }
   
   //--- v24.11: Update bar counter (call from OnBar)
   void UpdateBarCounter()
   {
      if(m_bars_since_last_trade < 999)
         m_bars_since_last_trade++;
      
      // After 6 bars (30 min on M5), allow re-entry without reversal check
      if(m_bars_since_last_trade >= 6)
         m_needs_reversal = false;
   }

   //--- Main signal generation (call on each bar close)
   //    Returns direction (1=BUY, -1=SELL, 0=no signal)
   //    and fills in entry/SL/TP
   int GenerateSignal(double &entry, double &sl, double &tp, string &reason)
   {
      if(!m_is_enabled) return 0;
      
      m_last_signal = CB_NONE;
      m_last_signal_dir = 0;
      reason = "";
      
      //--- Step 1: Check if spike probability is too high → BLOCK
      double spike_prob = m_spike_detector_obj.GetSpikeProbability();
      if(spike_prob > m_max_spike_prob)
      {
         reason = StringFormat("SPIKE-AVOID prob=%.2f > %.2f", spike_prob, m_max_spike_prob);
         m_last_signal = CB_SPIKE_AVOID;
         TelemLog(reason);
         return 0;
      }
      
      //--- v24.11: Update bar counter since last trade
      UpdateBarCounter();
      
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
         TelemLog(reason);
         return fade_dir;
      }
      
      //--- Step 3: Check for GRIND CONTINUATION entry (only if enabled)
      if(m_enable_grind)
      {
         int grind_dir = CheckGrindContinuation(entry, sl, tp, reason);
         if(grind_dir != 0)
         {
            m_last_signal = CB_GRIND_CONTINUATION;
            m_last_signal_dir = grind_dir;
            m_last_signal_entry = entry;
            m_last_signal_sl = sl;
            m_last_signal_tp = tp;
            m_last_signal_reason = reason;
            TelemLog(reason);
            return grind_dir;
         }
      }
      
      //--- No signal
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
      if(!m_spike_detector_obj.SpikeJustHappened(m_post_spike_window)) return 0;
      
      // Get ATR using pre-created handle (no leak)
      double atr[];
      ArraySetAsSeries(atr, true);
      if(m_atr_handle == INVALID_HANDLE) return 0;
      if(CopyBuffer(m_atr_handle, 0, 1, 1, atr) < 1) return 0;
      if(atr[0] <= 0 || (m_min_atr_points > 0 && atr[0] / _Point < m_min_atr_points)) return 0;
      
      double current_price = iClose(_Symbol, PERIOD_M5, 0);
      int bars_since_spike = m_spike_detector_obj.GetGrindDuration();  // approximate
      
      //--- CRASH index: spikes go DOWN → fade by BUYING
      if(m_is_crash)
      {
         // Check if price has retraced enough from spike low
         double spike_low = iLow(_Symbol, PERIOD_M5, 1);
         double spike_body_signed = iClose(_Symbol, PERIOD_M5, 1) - iOpen(_Symbol, PERIOD_M5, 1);
         double spike_body = MathAbs(spike_body_signed);
         if(m_require_spike_direction && spike_body_signed >= 0) return 0;
         
         if(spike_body > 0 && current_price > spike_low)
         {
            double retrace = (current_price - spike_low) / spike_body;
            
            // Enter if retracted in optimized window
            if(retrace >= m_fade_r_entry && retrace <= m_fade_retrace_max)
            {
               entry = current_price;
               sl = entry - m_fade_sl_atr_mult * atr[0];
               tp = entry + m_fade_tp_atr_mult * atr[0];
               
               // Ensure TP is above spike high and preserves minimum R:R.
               double spike_high = iHigh(_Symbol, PERIOD_M5, 1);
               if(tp < spike_high) tp = spike_high + atr[0] * 0.2;
               if((tp-entry) / MathMax(entry-sl, _Point) < m_min_rr) return 0;
               
               reason = StringFormat("CB-FADE-BUY retrace=%.0f%% bars=%d", retrace*100, bars_since_spike);
               return 1;  // BUY
            }
         }
      }
      //--- BOOM index: spikes go UP → fade by SELLING
      else
      {
         double spike_high = iHigh(_Symbol, PERIOD_M5, 1);
         double spike_body_signed = iClose(_Symbol, PERIOD_M5, 1) - iOpen(_Symbol, PERIOD_M5, 1);
         double spike_body = MathAbs(spike_body_signed);
         if(m_require_spike_direction && spike_body_signed <= 0) return 0;
         
         if(spike_body > 0 && current_price < spike_high)
         {
            double retrace = (spike_high - current_price) / spike_body;
            
            if(retrace >= m_fade_r_entry && retrace <= m_fade_retrace_max)
            {
               entry = current_price;
               sl = entry + m_fade_sl_atr_mult * atr[0];
               tp = entry - m_fade_tp_atr_mult * atr[0];
               
               double spike_low = iLow(_Symbol, PERIOD_M5, 1);
               if(tp > spike_low) tp = spike_low - atr[0] * 0.2;
               if((entry-tp) / MathMax(sl-entry, _Point) < m_min_rr) return 0;
               
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
      int grind_dir = m_spike_detector_obj.GetGrindDirection();
      int grind_dur = m_spike_detector_obj.GetGrindDuration();
      
      // Need at least 2 bars of grind (lowered from 5 → 3 → 2 for Boom 1000 speed)
      if(grind_dir == 0 || grind_dur < 2) return 0;
      
      // Don't enter if grind is too long (spike imminent)
      if(grind_dur > 20)
      {
         reason = StringFormat("CB-GRIND-TOO-LONG dur=%d", grind_dur);
         return 0;
      }
      
      //--- v24.11: Post-trade trend-reversal guard
      // If we just closed a trade, don't re-enter same direction unless trend reversed
      if(m_needs_reversal && m_last_trade_dir != 0)
      {
         double current_price = iClose(_Symbol, PERIOD_M5, 0);
         double price_vs_entry = current_price - m_last_trade_entry;
         
         // Determine the proposed direction for this grind
         int proposed_dir = 0;
         if(grind_dir > 0 && !m_is_crash) proposed_dir = 1;   // Boom grind up = BUY
         else if(grind_dir > 0 && m_is_crash) proposed_dir = -1; // Crash grind up = SELL
         else if(grind_dir < 0 && m_is_crash) proposed_dir = 1;  // Crash grind down = BUY
         else if(grind_dir < 0 && !m_is_crash) proposed_dir = -1; // Boom grind down = SELL
         
         // If same direction as last trade, check if trend has reversed
         if(proposed_dir == m_last_trade_dir)
         {
            // For SELL trades: trend reversed if price dropped below entry
            // For BUY trades: trend reversed if price rose above entry
            bool reversed = false;
            if(m_last_trade_dir < 0)
               reversed = (price_vs_entry < -5.0);  // price dropped 5+ points below our entry
            else
               reversed = (price_vs_entry > 5.0);   // price rose 5+ points above our entry
            
            if(!reversed)
            {
               reason = StringFormat("CB-GRIND-REVERSAL-GUARD last_dir=%s bars=%d gap=%.1f",
                                    m_last_trade_dir>0?"BUY":"SELL",
                                    m_bars_since_last_trade, price_vs_entry);
               return 0;  // Block: trend hasn't reversed yet
            }
         }
      }
      
      // Get ATR using pre-created handle (no leak)
      double atr[];
      ArraySetAsSeries(atr, true);
      if(m_atr_handle == INVALID_HANDLE) return 0;
      if(CopyBuffer(m_atr_handle, 0, 1, 1, atr) < 1) return 0;
      
      double body_avg = m_spike_detector_obj.GetGrindBodyAvg();
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
