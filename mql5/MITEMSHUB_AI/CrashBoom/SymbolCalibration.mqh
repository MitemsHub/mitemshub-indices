//+------------------------------------------------------------------+
//|                                  CrashBoom/SymbolCalibration.mqh |
//|  MITEMSHUB AI — SYMBOL-SPECIFIC CALIBRATION                     |
//|                                                                  |
//|  Each Boom/Crash index has different spike characteristics:      |
//|  - Boom 1000: frequent small spikes, avg ~50-100 points         |
//|  - Boom 500: medium spikes, avg ~100-200 points                 |
//|  - Boom 300: rare but huge spikes, avg ~200-500 points          |
//|  - Crash 1000: mirrors Boom 1000 but downward                   |
//|  - Crash 500: mirrors Boom 500                                  |
//|  - Crash 300: mirrors Boom 300                                  |
//|                                                                  |
//|  Auto-calibrates:                                                |
//|  1. Spike threshold per symbol                                  |
//|  2. Fade depth per symbol                                       |
//|  3. Risk scaling per symbol                                     |
//|  4. Optimal hold time per symbol                                |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_SYMBOL_CALIBRATION_MQH
#define MITEMSHUB_SYMBOL_CALIBRATION_MQH

//--- Symbol profiles
struct SymbolProfile
{
   string   name;              // "Boom 1000", "Crash 500", etc.
   bool     is_crash;          // true = Crash, false = Boom
   double   spike_threshold;   // body ratio to count as spike
   double   avg_spike_size;    // average spike size in points
   double   fade_depth;        // typical retrace % after spike
   double   fade_sl_mult;      // SL multiplier for fade
   double   fade_tp_mult;      // TP multiplier for fade
   int      optimal_hold;      // optimal hold time in bars
   double   risk_mult;         // risk multiplier (smaller for volatile)
   int      cooldown_bars;     // bars to wait after spike
   double   max_spike_prob;    // max spike probability before blocking
};

class CSymbolCalibration
{
private:
   SymbolProfile m_profiles[6];   // Boom 300, 500, 1000 + Crash 300, 500, 1000
   int           m_profile_count;
   
   SymbolProfile m_current;       // active profile
   bool          m_is_active;
   
   //--- Live calibration data
   double   m_live_avg_body;       // average body size on this symbol
   double   m_live_avg_spike;      // average spike size on this symbol
   int      m_live_spike_count;    // spikes observed
   double   m_live_retrace_avg;    // average retrace after spike
   int      m_live_retrace_count;  // retraces observed

public:
   CSymbolCalibration()
   {
      m_profile_count = 0;
      m_is_active = false;
      m_live_avg_body = 0;
      m_live_avg_spike = 0;
      m_live_spike_count = 0;
      m_live_retrace_avg = 0;
      m_live_retrace_count = 0;
      
      InitDefaultProfiles();
   }

   //--- Initialize default profiles for all Boom/Crash indices
   void InitDefaultProfiles()
   {
      // Boom 1000 — frequent small spikes
      m_profiles[0].name = "Boom 1000";
      m_profiles[0].is_crash = false;
      m_profiles[0].spike_threshold = 3.0;
      m_profiles[0].avg_spike_size = 75;
      m_profiles[0].fade_depth = 0.40;
      m_profiles[0].fade_sl_mult = 0.5;
      m_profiles[0].fade_tp_mult = 1.5;
      m_profiles[0].optimal_hold = 5;
      m_profiles[0].risk_mult = 1.0;
      m_profiles[0].cooldown_bars = 2;
      m_profiles[0].max_spike_prob = 0.65;
      
      // Boom 500 — medium spikes
      m_profiles[1].name = "Boom 500";
      m_profiles[1].is_crash = false;
      m_profiles[1].spike_threshold = 3.5;
      m_profiles[1].avg_spike_size = 150;
      m_profiles[1].fade_depth = 0.35;
      m_profiles[1].fade_sl_mult = 0.6;
      m_profiles[1].fade_tp_mult = 1.8;
      m_profiles[1].optimal_hold = 4;
      m_profiles[1].risk_mult = 0.8;
      m_profiles[1].cooldown_bars = 3;
      m_profiles[1].max_spike_prob = 0.60;
      
      // Boom 300 — rare huge spikes
      m_profiles[2].name = "Boom 300";
      m_profiles[2].is_crash = false;
      m_profiles[2].spike_threshold = 4.0;
      m_profiles[2].avg_spike_size = 300;
      m_profiles[2].fade_depth = 0.30;
      m_profiles[2].fade_sl_mult = 0.7;
      m_profiles[2].fade_tp_mult = 2.0;
      m_profiles[2].optimal_hold = 3;
      m_profiles[2].risk_mult = 0.6;
      m_profiles[2].cooldown_bars = 4;
      m_profiles[2].max_spike_prob = 0.55;
      
      // Crash 1000 — mirrors Boom 1000
      m_profiles[3].name = "Crash 1000";
      m_profiles[3].is_crash = true;
      m_profiles[3].spike_threshold = 3.0;
      m_profiles[3].avg_spike_size = 75;
      m_profiles[3].fade_depth = 0.40;
      m_profiles[3].fade_sl_mult = 0.5;
      m_profiles[3].fade_tp_mult = 1.5;
      m_profiles[3].optimal_hold = 5;
      m_profiles[3].risk_mult = 1.0;
      m_profiles[3].cooldown_bars = 2;
      m_profiles[3].max_spike_prob = 0.65;
      
      // Crash 500
      m_profiles[4].name = "Crash 500";
      m_profiles[4].is_crash = true;
      m_profiles[4].spike_threshold = 3.5;
      m_profiles[4].avg_spike_size = 150;
      m_profiles[4].fade_depth = 0.35;
      m_profiles[4].fade_sl_mult = 0.6;
      m_profiles[4].fade_tp_mult = 1.8;
      m_profiles[4].optimal_hold = 4;
      m_profiles[4].risk_mult = 0.8;
      m_profiles[4].cooldown_bars = 3;
      m_profiles[4].max_spike_prob = 0.60;
      
      // Crash 300
      m_profiles[5].name = "Crash 300";
      m_profiles[5].is_crash = true;
      m_profiles[5].spike_threshold = 4.0;
      m_profiles[5].avg_spike_size = 300;
      m_profiles[5].fade_depth = 0.30;
      m_profiles[5].fade_sl_mult = 0.7;
      m_profiles[5].fade_tp_mult = 2.0;
      m_profiles[5].optimal_hold = 3;
      m_profiles[5].risk_mult = 0.6;
      m_profiles[5].cooldown_bars = 4;
      m_profiles[5].max_spike_prob = 0.55;
      
      m_profile_count = 6;
   }

   //--- Auto-detect and load profile for current symbol
   void AutoCalibrate()
   {
      string sym = _Symbol;
      StringToUpper(sym);
      
      m_is_active = false;
      
      for(int i = 0; i < m_profile_count; i++)
      {
         string profile_name = m_profiles[i].name;
         StringToUpper(profile_name);
         
         if(StringFind(sym, profile_name) >= 0)
         {
            m_current = m_profiles[i];
            m_is_active = true;
            PrintFormat("[CB-CAL] Auto-detected: %s | spike_thresh=%.1f | fade_depth=%.0f%% | risk_mult=%.1f",
                        m_current.name, m_current.spike_threshold,
                        m_current.fade_depth * 100, m_current.risk_mult);
            return;
         }
      }
      
      // Fallback: try partial matching
      if(StringFind(sym, "BOOM") >= 0 || StringFind(sym, "CRASH") >= 0)
      {
         // Default to Boom/Crash 1000
         bool is_crash = (StringFind(sym, "CRASH") >= 0);
         m_current = is_crash ? m_profiles[3] : m_profiles[0];
         m_is_active = true;
         PrintFormat("[CB-CAL] Default profile: %s (partial match)", m_current.name);
      }
      else
      {
         PrintFormat("[CB-CAL] WARNING: No profile found for %s — using defaults", _Symbol);
         m_current = m_profiles[0];  // Boom 1000 defaults
         m_is_active = true;
      }
   }

   //--- Update calibration with live data
   void UpdateLive(ENUM_TIMEFRAMES tf, bool is_spike, double body_size, double retrace_pct)
   {
      if(is_spike)
      {
         m_live_spike_count++;
         m_live_avg_spike = (m_live_avg_spike * (m_live_spike_count - 1) + body_size) / m_live_spike_count;
      }
      
      if(retrace_pct >= 0)
      {
         m_live_retrace_count++;
         m_live_retrace_avg = (m_live_retrace_avg * (m_live_retrace_count - 1) + retrace_pct) / m_live_retrace_count;
      }
      
      // Update average body
      if(m_live_avg_body <= 0)
         m_live_avg_body = body_size;
      else
         m_live_avg_body = 0.1 * body_size + 0.9 * m_live_avg_body;
      
      // Adapt parameters based on live data (after enough samples)
      if(m_live_spike_count >= 10)
      {
         // Adjust fade depth based on actual retrace behavior
         if(m_live_retrace_count >= 5)
         {
            m_current.fade_depth = MathMax(0.20, MathMin(0.60, m_live_retrace_avg));
            m_current.fade_tp_mult = m_current.fade_depth * 4.0;  // TP = 4x fade depth
         }
         
         // Adjust spike threshold based on actual spike sizes
         if(m_live_avg_body > 0)
         {
            double expected_spike_body = m_live_avg_spike;
            m_current.spike_threshold = MathMax(2.5, MathMin(5.0, expected_spike_body / m_live_avg_body));
         }
      }
   }

   //--- Get active profile
   SymbolProfile GetProfile() const { return m_current; }
   bool IsActive() const { return m_is_active; }
   
   //--- Get live calibration stats
   double GetLiveAvgBody() const    { return m_live_avg_body; }
   double GetLiveAvgSpike() const   { return m_live_avg_spike; }
   int    GetLiveSpikeCount() const { return m_live_spike_count; }
   double GetLiveRetraceAvg() const { return m_live_retrace_avg; }

   //--- Get dashboard string
   string GetDashboard() const
   {
      if(!m_is_active) return "CAL: OFF";
      
      return StringFormat("CAL: %s | thresh=%.1f fade=%.0f%% risk=%.1f live_spikes=%d",
                          m_current.name, m_current.spike_threshold,
                          m_current.fade_depth * 100, m_current.risk_mult,
                          m_live_spike_count);
   }

   //--- Reset live data (new session)
   void ResetLiveData()
   {
      m_live_avg_body = 0;
      m_live_avg_spike = 0;
      m_live_spike_count = 0;
      m_live_retrace_avg = 0;
      m_live_retrace_count = 0;
   }
};

#endif
