//+------------------------------------------------------------------+
//|                                CrashBoom/TimeOfDayAwareness.mqh  |
//|  MITEMSHUB AI — TIME-OF-DAY SPIKE CLUSTERING                    |
//|                                                                  |
//|  Tracks when spikes happen by hour of day:                      |
//|  - Spikes cluster at certain hours (e.g., London open, NY close)|
//|  - Avoids entering during high-spike hours                      |
//|  - Increases caution during historically dangerous hours         |
//|                                                                  |
//|  Learns from live data — no hardcoded assumptions.              |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_TIME_OF_DAY_MQH
#define MITEMSHUB_TIME_OF_DAY_MQH

#define TOD_HISTORY_SIZE 500

class CTimeOfDayAwareness
{
private:
   //--- Spike tracking by hour (0-23)
   int      m_spike_count_by_hour[24];     // total spikes per hour
   int      m_total_spikes;                 // total spikes observed
   double   m_spike_rate_by_hour[24];       // spikes per bar at each hour
   int      m_bars_by_hour[24];             // bars observed per hour
   
   //--- Recent spike history
   datetime m_spike_times[TOD_HISTORY_SIZE];
   int      m_spike_count_buf;
   int      m_spike_head;
   
   //--- Current hour analysis
   int      m_current_hour;
   double   m_current_hour_risk;            // risk level for current hour (0-1)
   double   m_avg_hour_risk;                // average risk across all hours
   
   //--- Session awareness
   bool     m_is_high_risk_hour;           // current hour is dangerous
   bool     m_is_low_risk_hour;            // current hour is safe
   double   m_hour_risk_multiplier;        // multiply risk by this
   
   //--- Spike clustering detection
   int      m_spikes_in_last_hour;         // spikes in last 60 minutes
   int      m_spikes_in_last_4h;           // spikes in last 4 hours
   bool     m_cluster_detected;            // spike cluster active
   
   //--- Learning parameters
   double   m_high_risk_threshold;         // hourly rate above this = high risk
   double   m_low_risk_threshold;          // hourly rate below this = low risk
   int      m_min_samples;                 // minimum observations before acting

public:
   CTimeOfDayAwareness()
   {
      ArrayInitialize(m_spike_count_by_hour, 0);
      ArrayInitialize(m_spike_rate_by_hour, 0);
      ArrayInitialize(m_bars_by_hour, 0);
      ArrayInitialize(m_spike_times, 0);
      
      m_total_spikes = 0;
      m_spike_count_buf = 0;
      m_spike_head = 0;
      m_current_hour = 0;
      m_current_hour_risk = 0;
      m_avg_hour_risk = 0;
      m_is_high_risk_hour = false;
      m_is_low_risk_hour = false;
      m_hour_risk_multiplier = 1.0;
      m_spikes_in_last_hour = 0;
      m_spikes_in_last_4h = 0;
      m_cluster_detected = false;
      m_high_risk_threshold = 0.15;   // >15% of bars have spikes = high risk
      m_low_risk_threshold = 0.02;    // <2% of bars have spikes = low risk
      m_min_samples = 50;             // need 50+ bars before acting
   }

   //--- Call on every bar close
   void OnBar(ENUM_TIMEFRAMES tf)
   {
      datetime now = TimeCurrent();
      MqlDateTime dt;
      TimeToStruct(now, dt);
      m_current_hour = dt.hour;
      
      // Update bar count for current hour
      m_bars_by_hour[m_current_hour]++;
      
      // Check if a spike just happened (body > 3x average)
      if(IsSpikeBar(tf, 1))
      {
         RecordSpike(now, m_current_hour);
      }
      
      // Update hourly rates
      UpdateHourlyRates();
      
      // Update current hour risk
      UpdateCurrentHourRisk();
      
      // Check for spike clusters
      UpdateClusterDetection(now);
   }

   //--- Check if a bar is a spike
   bool IsSpikeBar(ENUM_TIMEFRAMES tf, int bar_index) const
   {
      double body = MathAbs(iClose(_Symbol, tf, bar_index) - iOpen(_Symbol, tf, bar_index));
      double avg_body = 0;
      int n = 20;
      for(int i = 2; i <= n + 1; i++)
         avg_body += MathAbs(iClose(_Symbol, tf, i) - iOpen(_Symbol, tf, i));
      avg_body /= n;
      return (avg_body > 0 && body >= avg_body * 3.0);
   }

   //--- Record a spike event
   void RecordSpike(datetime time, int hour)
   {
      m_spike_count_by_hour[hour]++;
      m_total_spikes++;
      
      // Store in ring buffer
      m_spike_times[m_spike_head] = time;
      m_spike_head = (m_spike_head + 1) % TOD_HISTORY_SIZE;
      if(m_spike_count_buf < TOD_HISTORY_SIZE) m_spike_count_buf++;
   }

   //--- Update hourly spike rates
   void UpdateHourlyRates()
   {
      double total_bars = 0;
      for(int h = 0; h < 24; h++)
         total_bars += m_bars_by_hour[h];
      
      if(total_bars < m_min_samples) return;
      
      double sum_rates = 0;
      for(int h = 0; h < 24; h++)
      {
         if(m_bars_by_hour[h] > 0)
            m_spike_rate_by_hour[h] = (double)m_spike_count_by_hour[h] / m_bars_by_hour[h];
         sum_rates += m_spike_rate_by_hour[h];
      }
      m_avg_hour_risk = sum_rates / 24.0;
   }

   //--- Update current hour risk assessment
   void UpdateCurrentHourRisk()
   {
      m_current_hour_risk = m_spike_rate_by_hour[m_current_hour];
      m_is_high_risk_hour = (m_current_hour_risk > m_high_risk_threshold);
      m_is_low_risk_hour = (m_current_hour_risk < m_low_risk_threshold && m_total_spikes > m_min_samples);
      
      // Risk multiplier: high risk = 0.5x (trade less), low risk = 1.3x (trade more)
      if(m_is_high_risk_hour)
         m_hour_risk_multiplier = 0.5;
      else if(m_is_low_risk_hour)
         m_hour_risk_multiplier = 1.3;
      else
         m_hour_risk_multiplier = 1.0;
   }

   //--- Detect spike clusters (multiple spikes in short time)
   void UpdateClusterDetection(datetime now)
   {
      m_spikes_in_last_hour = 0;
      m_spikes_in_last_4h = 0;
      
      for(int i = 0; i < m_spike_count_buf; i++)
      {
         int idx = (m_spike_head - 1 - i + TOD_HISTORY_SIZE) % TOD_HISTORY_SIZE;
         if(m_spike_times[idx] == 0) continue;
         
         int secs_ago = (int)(now - m_spike_times[idx]);
         
         if(secs_ago <= 3600)      m_spikes_in_last_hour++;
         if(secs_ago <= 14400)     m_spikes_in_last_4h++;
      }
      
      m_cluster_detected = (m_spikes_in_last_hour >= 2);  // 2+ spikes in 1 hour = cluster
   }

   //--- Get risk multiplier for current conditions
   double GetRiskMultiplier() const
   {
      double mult = m_hour_risk_multiplier;
      
      // Reduce further if cluster detected
      if(m_cluster_detected)
         mult *= 0.6;  // 40% reduction during clusters
      
      return mult;
   }

   //--- Should we avoid trading right now?
   bool ShouldAvoid() const
   {
      // Avoid during high-risk hours if we have enough data
      if(m_total_spikes >= m_min_samples && m_is_high_risk_hour)
         return true;
      
      // Avoid during active spike clusters
      if(m_cluster_detected && m_spikes_in_last_hour >= 3)
         return true;
      
      return false;
   }

   //--- Get analysis for a specific hour
   double GetHourRate(int hour) const { return m_spike_rate_by_hour[hour]; }
   int    GetHourSpikeCount(int hour) const { return m_spike_count_by_hour[hour]; }
   int    GetHourBarCount(int hour) const { return m_bars_by_hour[hour]; }

   //--- Get dashboard string
   string GetDashboard() const
   {
      string risk_level = m_is_high_risk_hour ? "HIGH" : (m_is_low_risk_hour ? "LOW" : "MED");
      string cluster = m_cluster_detected ? "CLUSTER" : "";
      
      return StringFormat("TOD: %02d:00 risk=%s mult=%.1f spikes/h=%d cluster=%s",
                          m_current_hour, risk_level, m_hour_risk_multiplier,
                          m_spikes_in_last_hour, cluster);
   }

   //--- Get risk description for current hour
   string GetRiskDescription() const
   {
      if(m_total_spikes < m_min_samples)
         return StringFormat("Learning... (%d spikes, need %d)", m_total_spikes, m_min_samples);
      
      return StringFormat("Hour %02d: %.1f%% spike rate [%s] mult=%.1f",
                          m_current_hour, m_current_hour_risk * 100,
                          m_is_high_risk_hour ? "DANGER" : (m_is_low_risk_hour ? "SAFE" : "NORMAL"),
                          m_hour_risk_multiplier);
   }

   //--- Reset
   void Reset()
   {
      ArrayInitialize(m_spike_count_by_hour, 0);
      ArrayInitialize(m_spike_rate_by_hour, 0);
      ArrayInitialize(m_bars_by_hour, 0);
      ArrayInitialize(m_spike_times, 0);
      m_total_spikes = 0;
      m_spike_count_buf = 0;
      m_spike_head = 0;
      m_spikes_in_last_hour = 0;
      m_spikes_in_last_4h = 0;
      m_cluster_detected = false;
   }
};

#endif
