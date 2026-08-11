//+------------------------------------------------------------------+
//| Decision/ConfidenceEngine.mqh                                    |
//|  MITEMSHUB AI MARKET ENGINE — Phase 5 ConfidenceEngine.          |
//|                                                                  |
//|  Maps the composite score + model confidence + setup confirmation|
//|  into the final confidence and the four signal states            |
//|  (strong/weak buy/sell + wait).  A faithful port of the Python   |
//|  decision engine's confidence math (decision_engine.py):         |
//|    - _classify_signal_strength  -> Classify()                    |
//|    - _dynamic_min_confidence    -> DynamicMinConfidence()        |
//|    - _drift_confidence_penalty  -> DriftPenalty()                |
//|  Parity is locked by mql5/phase5_logic_check.py against the REAL |
//|  Python methods, and by Tests/Phase5Tests.mq5 against the mirror.|
//|                                                                  |
//|  Constants are the Python values (BASE_MIN_CONFIDENCE=0.48,      |
//|  STRONG_WITH_SETUP=0.52, STRONG_WITHOUT_SETUP=0.65, Brier        |
//|  floor/ceil 0.25/0.10, MIN_RAISE_SAMPLES=30, max raise 0.55,     |
//|  drift penalty 0.02 decaying over 500 steps).  If the strategy   |
//|  reports its own candidate.confidence (0..1), the engine blends  |
//|  it with the composite score before classification; otherwise the|
//|  composite alone is used.  No state beyond the inputs — every    |
//|  method is a pure function, so the engine is unit-testable.      |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_DECISION_CONFIDENCE_ENGINE_MQH
#define MITEMSHUB_DECISION_CONFIDENCE_ENGINE_MQH

#include "../Core/Constants.mqh"

//--- Python decision_engine constants (locked by the parity gate) ------------
#define PY_BASE_MIN_CONFIDENCE       0.48
#define PY_MAX_RAISED_CONFIDENCE     0.55
#define PY_BRIER_FLOOR               0.25   // coin-flip quality -> no raise
#define PY_BRIER_CEIL                0.10   // excellent -> full raise
#define PY_MIN_RAISE_SAMPLES         30
#define PY_DRIFT_MAX_PENALTY         0.02
#define PY_DRIFT_PENALTY_DECAY_STEPS 500
#define PY_STRONG_WITH_SETUP         0.52
#define PY_STRONG_WITHOUT_SETUP      0.65

class CConfidenceEngine
  {
public:
   //--- Port of _drift_confidence_penalty: penalty decays linearly from
   //--- DRIFT_MAX_PENALTY to 0 over DRIFT_PENALTY_DECAY_STEPS updates.
   static double DriftPenalty(const int steps_since_drift)
     {
      if(steps_since_drift < 0 || steps_since_drift >= PY_DRIFT_PENALTY_DECAY_STEPS)
         return 0.0;
      double decay = 1.0 - (double)steps_since_drift / (double)PY_DRIFT_PENALTY_DECAY_STEPS;
      return PY_DRIFT_MAX_PENALTY * decay;
     }

   //--- Port of _dynamic_min_confidence.
   //--- brier: the calibration Brier score (any value; the Python has NO
   //--- negative guard — it simply clamps to [BRIER_CEIL, BRIER_FLOOR]; the
   //--- parity gate locks that behavior).
   //--- samples: number of calibration predictions collected.
   //--- drift_penalty: output of DriftPenalty() (0.0 when no drift).
   static double DynamicMinConfidence(const double brier, const int samples,
                                      const double drift_penalty)
     {
      if(samples < PY_MIN_RAISE_SAMPLES)
         return PY_BASE_MIN_CONFIDENCE;
      // Clamp brier to [BRIER_CEIL, BRIER_FLOOR] for interpolation
      double brier_clamped = MathMax(PY_BRIER_CEIL, MathMin(PY_BRIER_FLOOR, brier));
      // progress 0.0 (poor) -> 1.0 (excellent)
      double progress = (PY_BRIER_FLOOR - brier_clamped) / (PY_BRIER_FLOOR - PY_BRIER_CEIL);
      double dynamic_min = PY_BASE_MIN_CONFIDENCE
                           + progress * (PY_MAX_RAISED_CONFIDENCE - PY_BASE_MIN_CONFIDENCE);
      dynamic_min += drift_penalty;
      return MathMax(PY_BASE_MIN_CONFIDENCE,
                     MathMin(dynamic_min, PY_MAX_RAISED_CONFIDENCE + PY_DRIFT_MAX_PENALTY));
     }

   //--- Blend the strategy's own confidence with the composite score.
   //--- Python's DecisionEngine uses the model confidence as the signal's
   //--- confidence; here the strategy may report its own (candidate.confidence)
   //--- and the ScoringEngine produces a composite.  Blend keeps both visible:
   //--- composite weight w (default 0.5) against candidate confidence.
   static double BlendConfidence(const double composite, const double candidate_confidence,
                                 const double w = 0.5)
     {
      double c = (candidate_confidence >= 0.0 && candidate_confidence <= 1.0)
                 ? candidate_confidence : composite;
      double b = MathMax(0.0, MathMin(1.0, w * composite + (1.0 - w) * c));
      return b;
     }

   //--- Port of _classify_signal_strength: strong/weak/wait classification.
   //--- is_long: direction is LONG (buy) — FALSE means SELL.  Returned as the
   //--- ENUM_SIGNAL_STRENGTH; callers may also use SignalStrengthToString().
   static ENUM_SIGNAL_STRENGTH Classify(const double confidence,
                                        const double min_confidence,
                                        const bool has_formal_setup,
                                        const bool is_long)
     {
      double threshold = has_formal_setup ? PY_STRONG_WITH_SETUP : PY_STRONG_WITHOUT_SETUP;
      bool strong = (confidence >= threshold) && has_formal_setup;
      if(strong)
         return is_long ? SIGNAL_STRONG_BUY : SIGNAL_STRONG_SELL;
      if(confidence >= min_confidence)
         return is_long ? SIGNAL_WEAK_BUY : SIGNAL_WEAK_SELL;
      return SIGNAL_WAIT;
     }

   //--- Convenience: full gate in one call.  Returns the classification and
   //--- exposes the effective min_confidence via out param.
   static ENUM_SIGNAL_STRENGTH Gate(const double composite,
                                    const double candidate_confidence,
                                    const bool has_formal_setup,
                                    const bool is_long,
                                    const double brier,
                                    const int calibration_samples,
                                    const int steps_since_drift,
                                    double &out_min_confidence)
     {
      double drift = DriftPenalty(steps_since_drift);
      out_min_confidence = DynamicMinConfidence(brier, calibration_samples, drift);
      double conf = BlendConfidence(composite, candidate_confidence);
      return Classify(conf, out_min_confidence, has_formal_setup, is_long);
     }
  };

#endif // MITEMSHUB_DECISION_CONFIDENCE_ENGINE_MQH
