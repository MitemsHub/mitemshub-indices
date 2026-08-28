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
#include "CrashBoomStrategy.mqh"
#include "DynamicRiskSizing.mqh"

class CCrashBoomEngine
{
private:
   CSpikeDetector     m_spike_detector;
   CCrashBoomStrategy m_strategy;
   CDynamicRiskSizing m_risk_sizer;
   
   bool m_is_enabled;
   bool m_is_crash;
   
   //--- State tracking
   int      m_last_spike_bar;        // bar index of last detected spike
   int      m_spike_cooldown;        // bars to wait after spike
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

public:
   CCrashBoomEngine()
   {
      m_is_enabled = false;
      m_is_crash = false;
      m_last_spike_bar = 0;
      m_spike_cooldown = 0;
      m_total_spikes = 0;
      m_fade_trades = 0;
      m_grind_trades = 0;
      m_sig_dir = 0;
      m_sig_entry = 0;
      m_sig_sl = 0;
      m_sig_tp = 0;
      m_sig_reason = "";
      m_sig_type = "";
   }

   //--- Initialize
   void Init(bool enabled, bool is_crash_index)
   {
      m_is_enabled = enabled;
      m_is_crash = is_crash_index;
      
      if(!enabled) return;
      
      // Initialize sub-modules
      m_spike_detector.Reset();
      m_strategy.Init(&m_spike_detector, is_crash_index, true);
      m_risk_sizer.Init(true);
      
      // Set default parameters (can be overridden)
      m_spike_detector.SetSpikeThreshold(3.0);
      m_strategy.SetSpikeThreshold(3.0);
      m_strategy.SetMaxSpikeProb(0.65);
      m_strategy.SetPostSpikeWindow(5);
      m_strategy.SetSpikeCooldown(2);
      
      m_risk_sizer.SetBaseRisk(0.5);
      m_risk_sizer.SetMinRisk(0.15);
      m_risk_sizer.SetMaxRisk(0.75);
      m_risk_sizer.SetSpikeThreshold(0.5);
      
      PrintFormat("[CB] Engine initialized: %s mode | spike_thresh=%.1f | max_spike_prob=%.2f | risk=%.2f%%",
                  is_crash_index ? "CRASH" : "BOOM",
                  3.0, 0.65, 0.5);
   }

   //--- Call on every tick
   void OnTick()
   {
      if(!m_is_enabled) return;
      m_spike_detector.OnTick();
   }

   //--- Call on every bar close
   //    Returns direction (1=BUY, -1=SELL, 0=no signal)
   //    Fills in entry, sl, tp, reason, signal_type
   int OnBar(double &entry, double &sl, double &tp, string &reason, string &signal_type)
   {
      if(!m_is_enabled) return 0;
      
      // Update spike detector
      m_spike_detector.OnBar(PERIOD_M5, 20, 3.0);
      
      // Update Bollinger Bands
      m_strategy.UpdateBands();
      
      // Decrement cooldown
      if(m_spike_cooldown > 0) m_spike_cooldown--;
      
      // Check for new spike
      if(m_spike_detector.SpikeJustHappened(1))
      {
         m_total_spikes++;
         m_spike_cooldown = 2;  // wait 2 bars after spike
         PrintFormat("[CB] Spike #%d detected! prob=%.2f grind_dur=%d",
                     m_total_spikes, m_spike_detector.GetSpikeProbability(),
                     m_spike_detector.GetGrindDuration());
      }
      
      // Skip if in cooldown
      if(m_spike_cooldown > 0)
      {
         reason = StringFormat("CB-COOLDOWN %d bars", m_spike_cooldown);
         return 0;
      }
      
      // Generate signal from strategy
      m_sig_dir = m_strategy.GenerateSignal(entry, sl, tp, reason);
      
      if(m_sig_dir != 0)
      {
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
      if(!m_is_enabled) return 0;
      
      double spike_prob = m_spike_detector.GetSpikeProbability();
      bool spike_just = m_spike_detector.SpikeJustHappened(m_strategy.GetPostSpikeWindow());
      
      return m_risk_sizer.CalculateVolume(equity, stop_dist, tick_size, tick_value,
                                          spike_prob, spike_just,
                                          min_lot, max_lot, lot_step);
   }

   //--- Check if we should block entry (spike probability too high)
   bool ShouldBlockEntry() const
   {
      if(!m_is_enabled) return false;
      return (m_spike_detector.GetSpikeProbability() > m_strategy.GetMaxSpikeProb());
   }

   //--- Get dashboard info
   string GetDashboardInfo() const
   {
      if(!m_is_enabled) return "CB: OFF";
      
      double prob = m_spike_detector.GetSpikeProbability();
      int grind = m_spike_detector.GetGrindDuration();
      int grind_dir = m_spike_detector.GetGrindDirection();
      string risk_desc = m_risk_sizer.GetRiskDescription(prob, m_spike_detector.SpikeJustHappened(5));
      
      return StringFormat("CB: %s | Spike:%.0f%% | Grind:%s%d | Risk:%s | Spikes:%d Fades:%d Grinds:%d",
                          m_is_crash ? "CRASH" : "BOOM",
                          prob * 100,
                          grind_dir > 0 ? "UP" : (grind_dir < 0 ? "DN" : "--"),
                          grind,
                          risk_desc,
                          m_total_spikes, m_fade_trades, m_grind_trades);
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
   
   //--- Access individual modules
   CSpikeDetector*     GetSpikeDetector()  { return &m_spike_detector; }
   CCrashBoomStrategy* GetStrategy()       { return &m_strategy; }
   CDynamicRiskSizing* GetRiskSizer()      { return &m_risk_sizer; }
};

#endif
