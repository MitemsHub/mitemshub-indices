//+------------------------------------------------------------------+
//|                                CrashBoom/DynamicRiskSizing.mqh   |
//|  MITEMSHUB AI — DYNAMIC RISK SIZING for Crash/Boom              |
//|                                                                  |
//|  Adjusts lot size based on spike probability:                    |
//|  - High spike probability → smaller lot (protect capital)       |
//|  - Just had a spike → normal lot (lower risk now)               |
//|  - Normal conditions → standard risk                            |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_DYNAMIC_RISK_MQH
#define MITEMSHUB_DYNAMIC_RISK_MQH

#include "SpikeDetector.mqh"

class CDynamicRiskSizing
{
private:
   bool     m_is_enabled;
   
   //--- Risk parameters
   double   m_base_risk_pct;        // base risk as % of equity
   double   m_min_risk_pct;         // minimum risk during high spike prob
   double   m_max_risk_pct;         // maximum risk after spike (lower risk)
   double   m_spike_prob_threshold; // above this prob, reduce risk
   
   //--- Post-spike adjustment
   double   m_post_spike_risk_mult; // multiply risk by this after spike
   int      m_post_spike_bars;      // bars after spike that this applies

   //--- v25.3: micro-fade tier
   bool     m_micro_fade;           // reduce risk for small (micro) spikes
   double   m_micro_min_mult;       // risk multiplier floor for micro spikes
   double   m_micro_full_ratio;     // spike body ratio at/above which full risk
   double   m_micro_anchor;         // spike threshold (ratio where mult = floor)

public:
   CDynamicRiskSizing()
   {
      m_is_enabled = false;
      m_base_risk_pct = 0.5;        // 0.5% of equity per trade
      m_min_risk_pct = 0.15;        // minimum 0.15% during high risk
      m_max_risk_pct = 0.75;        // max 0.75% after spike
      m_spike_prob_threshold = 0.5; // 50% spike prob = start reducing
      m_post_spike_risk_mult = 1.2; // 20% more risk after spike (safer)
      m_post_spike_bars = 5;
      m_micro_fade = false;
      m_micro_min_mult = 0.5;       // micro spike trades at half risk
      m_micro_full_ratio = 3.0;     // ratio >= 3.0x EMA = full risk
      m_micro_anchor = 2.5;         // default anchor (synced to spike threshold)
   }

   void Init(bool enabled)
   {
      m_is_enabled = enabled;
      if(enabled)
         Print("[CB-RISK] Dynamic risk sizing enabled");
   }

   //--- Set parameters
   void SetBaseRisk(double pct)          { m_base_risk_pct = pct; }
   void SetMinRisk(double pct)           { m_min_risk_pct = pct; }
   void SetMaxRisk(double pct)           { m_max_risk_pct = pct; }
   void SetSpikeThreshold(double prob)   { m_spike_prob_threshold = prob; }
   void SetPostSpikeMult(double mult)    { m_post_spike_risk_mult = mult; }
   void SetPostSpikeBars(int bars)       { m_post_spike_bars = bars; }
   
   //--- v25.3: micro-fade tier controls
   void SetMicroFade(bool on)            { m_micro_fade = on; }
   void SetMicroAnchor(double thr)       { m_micro_anchor = MathMax(1.0, thr); }
   void SetMicroFullRatio(double r)      { m_micro_full_ratio = MathMax(m_micro_anchor + 0.1, r); }

   //--- Calculate adjusted risk % for this trade
   //    spike_prob: current spike probability (0-1)
   //    spike_just_happened: true if spike occurred recently
   double CalculateRiskPct(double spike_prob, bool spike_just_happened, double body_ratio = 0.0) const
   {
      if(!m_is_enabled) return m_base_risk_pct;
      
      double risk = m_base_risk_pct;
      
      //--- Adjust based on spike probability
      if(spike_prob > m_spike_prob_threshold)
      {
         // Linear interpolation: at threshold = base, at 1.0 = min
         double factor = (spike_prob - m_spike_prob_threshold) 
                       / (1.0 - m_spike_prob_threshold);
         risk = m_base_risk_pct - factor * (m_base_risk_pct - m_min_risk_pct);
      }
      
      //--- Post-spike adjustment (increase risk slightly — spike just cleared)
      if(spike_just_happened)
      {
         risk *= m_post_spike_risk_mult;
         risk = MathMin(risk, m_max_risk_pct);  // cap at max
      }
      
      //--- v25.3: micro-fade tier — small spikes carry proportionally less risk
      if(m_micro_fade && body_ratio > 0 && body_ratio < m_micro_full_ratio)
      {
         double span = MathMax(m_micro_full_ratio - m_micro_anchor, 0.1);
         double t = MathMax(0.0, MathMin(1.0, (body_ratio - m_micro_anchor) / span));
         risk *= (m_micro_min_mult + t * (1.0 - m_micro_min_mult));
      }
      
      return MathMax(m_min_risk_pct, MathMin(m_max_risk_pct, risk));
   }

   //--- Calculate volume for a trade
   //    equity: current account equity
   //    stop_dist: stop loss distance in price
   //    tick_size: symbol tick size
   //    tick_value: symbol tick value
   double CalculateVolume(double equity, double stop_dist, double tick_size, 
                          double tick_value, double spike_prob, bool spike_just_happened,
                          double min_lot, double max_lot, double lot_step,
                          double body_ratio = 0.0) const
   {
      if(!m_is_enabled || equity <= 0 || stop_dist <= 0 || tick_size <= 0 || tick_value <= 0)
         return 0;
      
      double risk_pct = CalculateRiskPct(spike_prob, spike_just_happened, body_ratio);
      double risk_money = equity * risk_pct / 100.0;
      
      double risk_per_lot = (stop_dist / tick_size) * tick_value;
      if(risk_per_lot <= 0) return min_lot;
      
      double vol = risk_money / risk_per_lot;
      
      // Normalize to lot step
      if(lot_step > 0)
         vol = MathFloor(vol / lot_step) * lot_step;
      
      // Clamp
      vol = MathMax(min_lot, MathMin(max_lot, vol));
      
      return NormalizeDouble(vol, 2);
   }

   //--- Get current risk description for dashboard
   string GetRiskDescription(double spike_prob, bool spike_just_happened, double body_ratio = 0.0) const
   {
      if(!m_is_enabled) return "OFF";
      
      double risk = CalculateRiskPct(spike_prob, spike_just_happened, body_ratio);
      string desc = StringFormat("%.2f%%", risk);
      
      if(spike_prob > m_spike_prob_threshold)
         desc += StringFormat(" (spike %.0f%%)", spike_prob * 100);
      if(spike_just_happened)
         desc += " [POST-SPIKE]";
      if(m_micro_fade && body_ratio > 0 && body_ratio < m_micro_full_ratio)
         desc += StringFormat(" [MICRO x%.2f]", MicroMult(body_ratio));
      
      return desc;
   }
   
   //--- v25.3: expose the micro multiplier (for logging/dashboard)
   double MicroMult(double body_ratio) const
   {
      if(!m_micro_fade || body_ratio <= 0 || body_ratio >= m_micro_full_ratio) return 1.0;
      double span = MathMax(m_micro_full_ratio - m_micro_anchor, 0.1);
      double t = MathMax(0.0, MathMin(1.0, (body_ratio - m_micro_anchor) / span));
      return (m_micro_min_mult + t * (1.0 - m_micro_min_mult));
   }
};

#endif
