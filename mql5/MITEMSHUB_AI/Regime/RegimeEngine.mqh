//+------------------------------------------------------------------+
//|                                        Regime/RegimeEngine.mqh   |
//|  MITEMSHUB AI MARKET ENGINE — regime classification orchestrator.|
//|                                                                  |
//|  Combines the detectors into ONE regime + confidence.  Rules:    |
//|   - TRANSITION wins only when its probability clears a threshold |
//|     (it overrides a stale regime when the character is changing).|
//|   - Confidence = the winning score, PENALIZED when independent   |
//|     models disagree (e.g. trend AND range both high) — per the   |
//|     architecture: "if different regime models disagree, reduce   |
//|     confidence."                                                 |
//|   - Hurst is an input to the trend/range split, never decisive.  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_REGIME_REGIMEENGINE_MQH
#define MITEMSHUB_REGIME_REGIMEENGINE_MQH

#include "../Core/Constants.mqh"
#include "TrendDetector.mqh"
#include "RangeDetector.mqh"
#include "CompressionDetector.mqh"
#include "ExpansionDetector.mqh"
#include "TransitionDetector.mqh"
#include "HurstAnalyzer.mqh"

#define REGIME_TRANSITION_THRESHOLD 0.70   // only a CLEAR transition overrides
                                       // (raised from 0.55 after real-corpus
                                       // calibration: 0.55 over-fired ~7x the
                                       // structural-break rate of the Python
                                       // CUSUM detector)

class CRegimeEngine
  {
private:
   ENUM_REGIME m_regime;
   double      m_confidence;          // 0..1
   int         m_trend_direction;     // +1 / -1 / 0
   double      m_trend_strength;      // 0..1
   double      m_mean_reversion_score;// 0..1
   double      m_transition_prob;     // 0..1
   double      m_volatility_state;    // 0..1 (ATR percentile)
   double      m_hurst;               // 0..1 or -1
   string      m_reason;

public:
   CRegimeEngine()
     {
      Reset();
     }

   void Reset()
     {
      m_regime              = REGIME_UNKNOWN;
      m_confidence          = 0.0;
      m_trend_direction     = 0;
      m_trend_strength      = 0.0;
      m_mean_reversion_score= 0.0;
      m_transition_prob     = 0.0;
      m_volatility_state    = 0.0;
      m_hurst               = -1.0;
      m_reason              = "";
     }

   //--- Main classification entry.  closes: oldest→newest (index count-1 =
   //--- newest closed).  atr_percentile/atr_ratio come from the
   //--- VolatilityEngine (0..1 and current/baseline respectively).
   void Classify(const double &closes[], const int count,
                 const double atr_percentile, const double atr_ratio)
     {
      Reset();

      m_trend_strength       = CTrendDetector::TrendStrength(closes, count);
      m_trend_direction      = CTrendDetector::Direction(closes, count);
      m_mean_reversion_score = CRangeDetector::RangeScore(closes, count);
      m_volatility_state     = MathMax(0.0, MathMin(1.0, atr_percentile));
      m_transition_prob      = CTransitionDetector::TransitionScore(closes, count);
      m_hurst                = CHurstAnalyzer::HurstOnCloses(closes, count);

      double compression = CCompressionDetector::CompressionScore(atr_percentile, atr_ratio);
      double expansion   = CExpansionDetector::ExpansionScore(atr_percentile, atr_ratio);

      //--- candidate scores
      double s_trend_up   = (m_trend_direction > 0 ? m_trend_strength : 0.0);
      double s_trend_down = (m_trend_direction < 0 ? m_trend_strength : 0.0);
      double s_range      = m_mean_reversion_score;
      double s_compress   = compression * (1.0 - m_trend_strength); // squeeze
                                                                     // fades when a
                                                                     // trend exists
      // EXPANSION must be a REAL ATR lift, not a high relative percentile
      // alone — on R_75 the ATR percentile can sit near 1.0 during a merely
      // volatile-but-stable stretch (ratio ~1.0), which is not an expansion.
      double s_expand     = (atr_ratio > 1.15 ? expansion : expansion * 0.4);
      double s_transition = (m_transition_prob >= REGIME_TRANSITION_THRESHOLD)
                            ? m_transition_prob : 0.0;

      //--- pick the winner
      double top = s_trend_up;
      ENUM_REGIME regime = REGIME_TREND_UP;
      if(s_trend_down > top) { top = s_trend_down; regime = REGIME_TREND_DOWN; }
      if(s_range      > top) { top = s_range;      regime = REGIME_RANGE; }
      if(s_compress   > top) { top = s_compress;   regime = REGIME_COMPRESSION; }
      if(s_expand     > top) { top = s_expand;     regime = REGIME_EXPANSION; }
      if(s_transition > top) { top = s_transition; regime = REGIME_TRANSITION; }

      m_regime = regime;

      //--- confidence with disagreement penalty
      double disagreement = MathAbs(m_trend_strength - m_mean_reversion_score);
      double conf = top * (1.0 - 0.5 * disagreement);
      if(conf > 1.0)
         conf = 1.0;
      if(conf < 0.0)
         conf = 0.0;
      m_confidence = conf;

      m_reason = StringFormat("%s (%.2f) conf=%.2f trend=%.2f dir=%d range=%.2f "
                              "trans=%.2f hurst=%.2f vol=%.2f",
                              RegimeToString(m_regime), top, m_confidence,
                              m_trend_strength, m_trend_direction,
                              m_mean_reversion_score, m_transition_prob,
                              m_hurst, m_volatility_state);
     }

   //--- Accessors ------------------------------------------------------------
   ENUM_REGIME Regime() const          { return(m_regime); }
   double      Confidence() const      { return(m_confidence); }
   int         TrendDirection() const  { return(m_trend_direction); }
   double      TrendStrength() const   { return(m_trend_strength); }
   double      MeanReversionScore() const { return(m_mean_reversion_score); }
   double      TransitionProb() const  { return(m_transition_prob); }
   double      VolatilityState() const { return(m_volatility_state); }
   double      Hurst() const           { return(m_hurst); }
   string      Reason() const          { return(m_reason); }
  };

#endif // MITEMSHUB_REGIME_REGIMEENGINE_MQH
