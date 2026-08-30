//+------------------------------------------------------------------+
//|                                   CrashBoom/CrashBoomEngine.mqh  |
//|  MITEMSHUB AI — CRASH/BOOM ENGINE (master coordinator)          |
//|                                                                  |
//|  Coordinates:                                                    |
//|  - SpikeDetector: monitors tick speed, candle patterns           |
//|  - CrashBoomStrategy: entry/exit logic                          |
//|  - DynamicRiskSizing: adjusts lot size for spike risk           |
//|                                                                  |
//|  Usage in main EA:                                               |
//|  1. Set InpCrashBoomMode = true                                 |
//|  2. Set InpIsCrashIndex = true/false                            |
//|  3. In OnTick: call g_cb.OnTick()                              |
//|  4. In OnBar:  call g_cb.OnBar() → get signal                  |
//|  5. Use g_cb.CalculateVolume() for lot sizing                  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CRASHBOOM_ENGINE_MQH
#define MITEMSHUB_CRASHBOOM_ENGINE_MQH

#include "SpikeDetector.mqh"
#include "TickPatternAnalyzer.mqh"
#include "MultiTimeframeConfirm.mqh"
#include "TimeOfDayAwareness.mqh"
#include "SymbolCalibration.mqh"
#include "CrashBoomStrategy.mqh"
#include "DynamicRiskSizing.mqh"

class CCrashBoomEngine
{
private:
   CSpikeDetector          m_spike_detector;
   CTickPatternAnalyzer    m_tick_analyzer;
   CMultiTimeframeConfirm  m_mtf_confirm;
   CTimeOfDayAwareness     m_tod_awareness;
   CSymbolCalibration      m_calibration;
   CCrashBoomStrategy      m_strategy;
   CDynamicRiskSizing      m_risk_sizer;
   
   bool m_is_enabled;
   bool m_is_crash;
   
   //--- State tracking
   int      m_last_spike_bar;        // bar index of last detected spike
   int      m_spike_cooldown;        // bars to wait after spike
   datetime m_last_bar_time;          // prevents duplicate bar processing
   int      m_total_spikes;          // spikes detected this session
   int      m_fade_trades;           // fade trades taken
   int      m_grind_trades;          // grind trades taken
   
   //--- Last signal output
   int      m_sig_dir;
   double   m_sig_entry;
   double   m_sig_sl;
   double   m_sig_tp;
   string   m_sig_reason;
   string   m_sig_type;              // "CB-FADE" or "CB-GRIND"
   
   //--- v25.4: tick-triggered fast-fade state machine
   bool     m_tick_fade_enabled;     // fire fades on the tick spike itself
   double   m_tick_spike_pts;        // min tick jump (points) that counts as a spike
   int      m_tick_fade_timeout;     // pending spike expiry (seconds)
   int      m_tf_state;              // 0=idle, 1=spike pending retrace
   double   m_tf_prev;               // previous tick price
   double   m_tf_pre;                // pre-spike price (= spike low for Boom)
   double   m_tf_peak;               // post-spike extreme price
   double   m_tf_jump;               // spike jump size (abs, price units)
   datetime m_tf_t0;                 // spike time
   double   m_tick_fade_ratio;       // spike/body-EMA ratio for risk sizing (consume-once)

public:
   CCrashBoomEngine()
   {
      m_is_enabled = false;
      m_is_crash = false;
      m_last_spike_bar = 0;
      m_spike_cooldown = 0;
      m_last_bar_time = 0;
      m_total_spikes = 0;
      m_fade_trades = 0;
      m_grind_trades = 0;
      m_sig_dir = 0;
      m_sig_entry = 0;
      m_sig_sl = 0;
      m_sig_tp = 0;
      m_sig_reason = "";
      m_sig_type = "";
      m_tick_fade_enabled = false;
      m_tick_spike_pts = 3.0;
      m_tick_fade_timeout = 600;
      m_tf_state = 0;
      m_tf_prev = 0;
      m_tf_pre = 0;
      m_tf_peak = 0;
      m_tf_jump = 0;
      m_tf_t0 = 0;
      m_tick_fade_ratio = 0;
   }

   //--- Initialize
   void Init(bool enabled, bool is_crash_index)
   {
      m_is_enabled = enabled;
      m_is_crash = is_crash_index;
      
      if(!enabled) return;
      
      // Initialize sub-modules
      m_spike_detector.Reset();
      m_tick_analyzer.Reset();
      m_tod_awareness.Reset();
      m_calibration.AutoCalibrate();
      m_strategy.Init(m_spike_detector, is_crash_index, true);
      m_risk_sizer.Init(true);
      m_mtf_confirm.Init(true);
      
      // Apply calibrated parameters
      SymbolProfile prof = m_calibration.GetProfile();
      m_spike_detector.SetSpikeThreshold(prof.spike_threshold);
      m_strategy.SetSpikeThreshold(prof.spike_threshold);
      m_strategy.SetMaxSpikeProb(prof.max_spike_prob);
      m_strategy.SetPostSpikeWindow(prof.optimal_hold);
      m_strategy.SetSpikeCooldown(prof.cooldown_bars);
      m_spike_cooldown = 0;
      m_strategy.SetFadeSL(prof.fade_sl_mult);
      m_strategy.SetFadeTP(prof.fade_tp_mult);
      m_strategy.SetMinRR(2.0);
      
      m_risk_sizer.SetBaseRisk(0.5 * prof.risk_mult);
      m_risk_sizer.SetMinRisk(0.15);
      m_risk_sizer.SetMaxRisk(0.75 * prof.risk_mult);
      m_risk_sizer.SetSpikeThreshold(0.5);
      
      PrintFormat("[CB] Engine initialized: %s | %s | thresh=%.1f | fade=%.0f%% | risk_mult=%.1f | grind=%s",
                  is_crash_index ? "CRASH" : "BOOM",
                  prof.name, prof.spike_threshold, prof.fade_depth*100, prof.risk_mult,
                  m_strategy.IsGrindEnabled() ? "ON" : "OFF");
   }

   //--- Release all indicator handles on shutdown
   void Deinit()
   {
      m_strategy.Deinit();
      m_mtf_confirm.Deinit();
      Print("[CB] Engine deinitialized — handles released");
   }

   //--- Call on every tick
   void OnTick(double bid, double ask)
   {
      if(!m_is_enabled) return;
      m_spike_detector.OnTick();
      m_tick_analyzer.OnTick(bid, ask);  // v24.1: tick pattern analysis
   }
   
   //--- v25.4: tick-triggered fast fade — runs on EVERY tick.
   //    Tracks tick-level spikes and their retrace; fires the fade as soon as
   //    the retrace enters the window, instead of waiting for the M5 close.
   //    can_trade: caller's entry gates (position/session/cooldown) — the spike
   //    is always tracked, but only fired when gates are open.
   //    Returns 1=BUY, -1=SELL, 0=nothing; fills entry/sl/tp/reason on fire.
   int OnTickFade(double bid, double &entry, double &sl, double &tp, string &reason, bool can_trade)
   {
      if(!m_is_enabled) { m_tf_prev = bid; return 0; }
      
      double prev = (m_tf_prev > 0) ? m_tf_prev : bid;
      m_tf_prev = bid;
      double jump = bid - prev;
      datetime now = TimeCurrent();
      
      //--- 1) detect / extend a tick spike (Boom spikes UP, Crash spikes DOWN)
      bool is_spike = m_is_crash ? (jump <= -m_tick_spike_pts) : (jump >= m_tick_spike_pts);
      if(is_spike)
      {
         if(m_tf_state == 1)
         {
            // same spike extended to a new extreme — move the peak, restart clock
            if(m_is_crash ? (bid < m_tf_peak) : (bid > m_tf_peak))
            {
               m_tf_peak = bid;
               m_tf_jump = MathAbs(m_tf_peak - m_tf_pre);
               m_tf_t0   = now;
            }
         }
         else
         {
            m_tf_state = 1;
            m_tf_pre   = prev;
            m_tf_peak  = bid;
            m_tf_jump  = MathAbs(jump);
            m_tf_t0    = now;
            PrintFormat("[CB-TICKSPIKE] %s jump=%+.1fpts", m_is_crash ? "DN" : "UP", jump);
         }
      }
      
      if(m_tf_state != 1) return 0;
      
      //--- 2) pending: measure retrace, fire or expire
      double retrace = m_is_crash ? (bid - m_tf_peak) / m_tf_jump
                                  : (m_tf_peak - bid) / m_tf_jump;
      int age = (int)(now - m_tf_t0);
      
      // full retrace back through the pre-spike price — fade window gone
      if(m_is_crash ? (bid >= m_tf_pre) : (bid <= m_tf_pre))
      {
         PrintFormat("[CB-TICKFADE-EXPIRE] full retrace after %ds", age);
         m_tf_state = 0;
         return 0;
      }
      if(age > m_tick_fade_timeout)
      {
         m_tf_state = 0;
         return 0;   // silent timeout
      }
      
      double r_entry = m_strategy.ScaledFadeEntry(m_tf_jump);   // v25.7 size-scaled
      double r_max   = m_strategy.GetFadeRetraceMax();
      if(retrace < r_entry) return 0;             // not deep enough yet (silent)
      if(retrace > r_max)
      {
         PrintFormat("[CB-TICKFADE-EXPIRE] retrace %.0f%% > %.0f%% max after %ds", retrace*100, r_max*100, age);
         m_tf_state = 0;
         return 0;
      }
      
      if(!can_trade) return 0;                    // gates closed — keep tracking
      if(m_tod_awareness.ShouldAvoid())
      {
         reason = StringFormat("CB-TICKFADE blocked %s", m_tod_awareness.GetRiskDescription());
         return 0;
      }
      
      double atr = m_strategy.GetATR();
      if(atr <= 0) return 0;
      
      //--- geometry mirrors the M5 fade (SL/TP in ATR units, R:R gate)
      entry = bid;
      if(m_is_crash)
      {
         sl = entry - m_strategy.GetFadeSL() * atr;
         tp = entry + m_strategy.GetFadeTP() * atr;
         if(tp < m_tf_pre) tp = m_tf_pre + atr * 0.2;   // keep TP above spike high
         double rr = (tp - entry) / MathMax(entry - sl, _Point);
         if(rr < m_strategy.GetMinRR())
         {
            PrintFormat("[CB-TICKFADE-SKIP] RR %.1f < %.1f (TP clamped @pre-spike)", rr, m_strategy.GetMinRR());
            m_tf_state = 0;
            return 0;
         }
         reason = StringFormat("CB-TICK-FADE-BUY jump=%.1fpts retrace=%.0f%% t=%ds", m_tf_jump, retrace*100, age);
         PrintFormat("[CB-TICKFADE] BUY jump=%.1fpts retrace=%.0f%% t=%ds prob=%.2f",
                     m_tf_jump, retrace*100, age, m_spike_detector.GetSpikeProbability());
      }
      else
      {
         sl = entry + m_strategy.GetFadeSL() * atr;
         tp = entry - m_strategy.GetFadeTP() * atr;
         if(tp > m_tf_pre) tp = m_tf_pre - atr * 0.2;   // keep TP below pre-spike level
         double rr = (entry - tp) / MathMax(sl - entry, _Point);
         if(rr < m_strategy.GetMinRR())
         {
            PrintFormat("[CB-TICKFADE-SKIP] RR %.1f < %.1f (TP clamped @pre-spike)", rr, m_strategy.GetMinRR());
            m_tf_state = 0;
            return 0;
         }
         reason = StringFormat("CB-TICK-FADE-SELL jump=%.1fpts retrace=%.0f%% t=%ds", m_tf_jump, retrace*100, age);
         PrintFormat("[CB-TICKFADE] SELL jump=%.1fpts retrace=%.0f%% t=%ds prob=%.2f",
                     m_tf_jump, retrace*100, age, m_spike_detector.GetSpikeProbability());
      }
      
      //--- consume the spike: block the M5 fade path for it, size risk by
      //    tick-jump/body-EMA (same scale as the M5 micro-fade multiplier)
      m_tf_state = 0;
      m_spike_cooldown = m_calibration.GetProfile().cooldown_bars;
      m_tick_fade_ratio = m_tf_jump / MathMax(m_spike_detector.GetBodyEma(), _Point);
      return m_is_crash ? 1 : -1;
   }

   //--- Call on every bar close
   //    Returns direction (1=BUY, -1=SELL, 0=no signal)
   //    Fills in entry, sl, tp, reason, signal_type
   int OnBar(double &entry, double &sl, double &tp, string &reason, string &signal_type)
   {
      if(!m_is_enabled) return 0;
      
      // OnBar is normally called once per EA bar, but guard against duplicate
      // calls so cooldowns and spike ages cannot be consumed twice.
      datetime bar_time = iTime(_Symbol, PERIOD_M5, 0);
      if(bar_time <= 0 || bar_time == m_last_bar_time) return 0;
      m_last_bar_time = bar_time;

      // Update all analyzers
      m_spike_detector.OnBar(PERIOD_M5, 20, m_spike_detector.GetSpikeThreshold());
      m_mtf_confirm.Analyze();           // v24.1: multi-timeframe confirmation
      m_tod_awareness.OnBar(PERIOD_M5);  // v24.1: time-of-day awareness
      m_strategy.UpdateBands();
      m_strategy.UpdateSpikeDetector(m_spike_detector);  // CRITICAL: sync detector state
      
      // Decrement cooldown
      if(m_spike_cooldown > 0) m_spike_cooldown--;
      
      // Check for new spike
      if(m_spike_detector.SpikeJustHappened(1))
      {
         m_total_spikes++;
         m_spike_cooldown = m_calibration.GetProfile().cooldown_bars;
         
         // v24.1: Update calibration with live spike data
         double spike_body = MathAbs(iClose(_Symbol, PERIOD_M5, 1) - iOpen(_Symbol, PERIOD_M5, 1));
         m_calibration.UpdateLive(PERIOD_M5, true, spike_body, -1);
         
         PrintFormat("[CB] Spike #%d detected! prob=%.2f grind=%d precursor=%.2f TOD=%s",
                     m_total_spikes, m_spike_detector.GetSpikeProbability(),
                     m_spike_detector.GetGrindDuration(),
                     m_tick_analyzer.GetPrecursorScore(),
                     m_tod_awareness.GetDashboard());
      }
      
      // Update calibration with current body size (non-spike)
      double cur_body = MathAbs(iClose(_Symbol, PERIOD_M5, 1) - iOpen(_Symbol, PERIOD_M5, 1));
      m_calibration.UpdateLive(PERIOD_M5, false, cur_body, -1);
      
      // Skip if in cooldown
      if(m_spike_cooldown > 0)
      {
         reason = StringFormat("CB-COOLDOWN %d bars", m_spike_cooldown);
         return 0;
      }
      
      // v24.1: Check tick precursor score — block if spike imminent
      double precursor = m_tick_analyzer.GetPrecursorScore();
      if(precursor > 0.7)
      {
         reason = StringFormat("CB-TICK-BLOCK precursor=%.2f > 0.70", precursor);
         return 0;
      }
      
      // v24.1: Check time-of-day risk — block during dangerous hours
      if(m_tod_awareness.ShouldAvoid())
      {
         reason = StringFormat("CB-TOD-AVOID %s", m_tod_awareness.GetRiskDescription());
         return 0;
      }
      
      // Generate signal from strategy
      m_sig_dir = m_strategy.GenerateSignal(entry, sl, tp, reason);
      
      if(m_sig_dir != 0)
      {
         // v24.1: Multi-timeframe confirmation check
         string mtf_reason = "";
         if(!m_mtf_confirm.IsConfirmed(m_sig_dir, mtf_reason))
         {
            reason = mtf_reason;
            return 0;
         }
         
         // Determine signal type
         if(reason.Find("FADE") >= 0)
         {
            signal_type = "CB-FADE";
            m_fade_trades++;
         }
         else if(reason.Find("GRIND") >= 0)
         {
            signal_type = "CB-GRIND";
            m_grind_trades++;
         }
         else
         {
            signal_type = "CB-UNKNOWN";
         }
         
         // v24.1: Apply time-of-day risk multiplier to entry
         double tod_mult = m_tod_awareness.GetRiskMultiplier();
         if(tod_mult != 1.0)
            reason += StringFormat(" TOD Mult=%.1f", tod_mult);
         
         m_sig_entry = entry;
         m_sig_sl = sl;
         m_sig_tp = tp;
         m_sig_reason = reason;
         m_sig_type = signal_type;
      }
      
      return m_sig_dir;
   }

   //--- Calculate volume with dynamic risk sizing
   double CalculateVolume(double equity, double stop_dist, 
                          double tick_size, double tick_value,
                          double min_lot, double max_lot, double lot_step)
   {
      if(!m_is_enabled) return 0;       double spike_prob = m_spike_detector.GetSpikeProbability();
       bool spike_just = m_spike_detector.SpikeJustHappened(m_strategy.GetPostSpikeWindow());
       // v25.4: tick-fired fades carry their own ratio; M5 fades use detector ratio
       double body_ratio = (m_tick_fade_ratio > 0) ? m_tick_fade_ratio
                                                   : m_spike_detector.GetLastSpikeBodyRatio();
       m_tick_fade_ratio = 0;   // consume-once
       
       return m_risk_sizer.CalculateVolume(equity, stop_dist, tick_size, tick_value,
                                           spike_prob, spike_just,
                                           min_lot, max_lot, lot_step, body_ratio);
   }

   //--- v24.11: Notify engine when a trade closes (for trend-reversal guard)
   void OnTradeClosed(int dir, double entry_price)
   {
      if(!m_is_enabled) return;
      m_strategy.OnTradeClosed(dir, entry_price);
   }
   
   //--- Check if we should block entry (spike probability too high)
   bool ShouldBlockEntry() const
   {
      if(!m_is_enabled) return false;
      return (m_spike_detector.GetSpikeProbability() > m_strategy.GetMaxSpikeProb());
   }

   //--- Get dashboard info (multi-line)
   string GetDashboardInfo() const
   {
      if(!m_is_enabled) return "CB: OFF";
      
      double prob = m_spike_detector.GetSpikeProbability();
      int grind = m_spike_detector.GetGrindDuration();
      int grind_dir = m_spike_detector.GetGrindDirection();
      string risk_desc = m_risk_sizer.GetRiskDescription(prob, m_spike_detector.SpikeJustHappened(5));
      double precursor = m_tick_analyzer.GetPrecursorScore();
      
      string info = StringFormat("CB: %s | Spike:%.0f%% Precursor:%.0f%% | Mode:%s",
                          m_is_crash ? "CRASH" : "BOOM",
                          prob * 100, precursor * 100,
                          m_strategy.IsGrindEnabled() ? "FADE+GRIND" : "FADE-ONLY");
      info += StringFormat(" | Risk:%s | Spikes:%d Fades:%d",
                          risk_desc, m_total_spikes, m_fade_trades);
      return info;
   }

   //--- Get detailed info for Experts journal
   string GetDetailedInfo() const
   {
      string info = "";
      info += m_calibration.GetDashboard() + "\n";
      info += m_mtf_confirm.GetDashboard() + "\n";
      info += m_tod_awareness.GetDashboard() + "\n";
      info += StringFormat("Tick: speed=%.1f/s cluster=%d anomaly=%.1f entropy=%.2f precursor=%.2f",
                          m_tick_analyzer.GetCurrentSpeed(),
                          m_tick_analyzer.GetDirectionCluster(),
                          m_tick_analyzer.GetAnomalyRatio(),
                          m_tick_analyzer.GetEntropy(),
                          m_tick_analyzer.GetPrecursorScore());
      return info;
   }

   //--- Get spike probability
   double GetSpikeProbability() const { return m_spike_detector.GetSpikeProbability(); }
   
   //--- Get risk description
   string GetRiskDescription() const
   {
      return m_risk_sizer.GetRiskDescription(m_spike_detector.GetSpikeProbability(),
                                             m_spike_detector.SpikeJustHappened(5));
   }
   
   //--- Check if spike just happened
   bool SpikeJustHappened() const { return m_spike_detector.SpikeJustHappened(5); }
   
   //--- Is engine enabled?
   bool IsEnabled() const { return m_is_enabled; }
   bool IsCrash() const   { return m_is_crash; }
   
   //--- Parameter setters (wrappers — avoid pointer access from main EA)
   void SetSpikeThreshold(double val)  { m_spike_detector.SetSpikeThreshold(val); m_strategy.SetSpikeThreshold(val); m_risk_sizer.SetMicroAnchor(val); }
   void SetMicroFade(bool on)          { m_risk_sizer.SetMicroFade(on); }   // v25.3 micro-fade tier
   void SetMaxSpikeProb(double val)    { m_strategy.SetMaxSpikeProb(val); }
   void SetFadeR(double val)           { m_strategy.SetFadeR(val); }
   void SetFadeSL(double val)          { m_strategy.SetFadeSL(val); }
   void SetFadeTP(double val)          { m_strategy.SetFadeTP(val); }
   void SetMinRR(double val)            { m_strategy.SetMinRR(val); }
   void SetBaseRisk(double val)        { m_risk_sizer.SetBaseRisk(val); }
   void SetMinRisk(double val)         { m_risk_sizer.SetMinRisk(val); }
   void SetEnableGrind(bool val)       { m_strategy.SetEnableGrind(val); }
   void SetRequireSpikeDirection(bool val) { m_strategy.SetRequireSpikeDirection(val); }
   void SetMinATRPoints(double val)        { m_strategy.SetMinATRPoints(val); }
   
   //--- v25.4: tick fast-fade configuration
   void SetTickFade(bool on, double spike_pts, int timeout_sec)
   {
      m_tick_fade_enabled = on;
      m_tick_spike_pts    = MathMax(0.5, spike_pts);
      m_tick_fade_timeout = MathMax(60, timeout_sec);
      if(on) PrintFormat("[CB-TICKFADE] armed: spike>=%.1fpts timeout=%ds", m_tick_spike_pts, m_tick_fade_timeout);
   }
   
   //--- Get spike detector (for diagnostic access)
   CSpikeDetector *GetSpikeDetectorPtr() { return &m_spike_detector; }
};

#endif
