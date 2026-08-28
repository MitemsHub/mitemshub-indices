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

   //--- Calculate adjusted risk % for this trade
   //    spike_prob: current spike probability (0-1)
   //    spike_just_happened: true if spike occurred recently
   double CalculateRiskPct(double spike_prob, bool spike_just_happened) const
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
      
      return MathMax(m_min_risk_pct, MathMin(m_max_risk_pct, risk));
   }

   //--- Calculate volume for a trade
   //    equity: current account equity
   //    stop_dist: stop loss distance in price
   //    tick_size: symbol tick size
   //    tick_value: symbol tick value
   double CalculateVolume(double equity, double stop_dist, double tick_size, 
                          double tick_value, double spike_prob, bool spike_just_happened,
                          double min_lot, double max_lot, double lot_step) const
   {
      if(!m_is_enabled || equity <= 0 || stop_dist <= 0 || tick_size <= 0 || tick_value <= 0)
         return 0;
      
      double risk_pct = CalculateRiskPct(spike_prob, spike_just_happened);
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
   string GetRiskDescription(double spike_prob, bool spike_just_happened) const
   {
      if(!m_is_enabled) return "OFF";
      
      double risk = CalculateRiskPct(spike_prob, spike_just_happened);
      string desc = StringFormat("%.2f%%", risk);
      
      if(spike_prob > m_spike_prob_threshold)
         desc += StringFormat(" (spike %.0f%%)", spike_prob * 100);
      if(spike_just_happened)
         desc += " [POST-SPIKE]";
      
      return desc;
   }
};

#endif
