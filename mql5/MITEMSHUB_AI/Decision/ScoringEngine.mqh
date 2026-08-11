//+------------------------------------------------------------------+
//| Decision/ScoringEngine.mqh                                       |
//|  MITEMSHUB AI MARKET ENGINE — Phase 5 ScoringEngine.             |
//|                                                                  |
//|  Turns a StrategyCandidate + market context into the plan's      |
//|  per-axis scores (setup / regime / structure / risk / execution) |
//|  and a weighted composite, plus the human-readable explanation   |
//|  the DecisionEngine must journal ("REGIME=RANGE SETUP_QUALITY=54 |
//|  RISK/REWARD=INSUFFICIENT ...").                                 |
//|                                                                  |
//|  All weights are configurable (defaults sum to 1.0).  Every      |
//|  method is a pure function of its inputs — no state — so the     |
//|  engine is unit-testable and the mirror locks the math.          |
//|                                                                  |
//|  Sub-score semantics:                                            |
//|    setup      = candidate.setup_quality (0..1) from the strategy |
//|    regime     = alignment of the CURRENT regime with the setup's |
//|                 required regime (exact 1.0; family-compatible    |
//|                 0.7; transition/unknown 0.4; conflicting 0.2).   |
//|                 The regime matrix still BLOCKS strategies in     |
//|                 wrong regimes — this scores the quality when     |
//|                 allowed.                                         |
//|    structure  = caller-provided structure-bias agreement (0..1), |
//|                 default 0.5 (neutral) when the caller has no     |
//|                 structure opinion (the band leg, for instance).  |
//|    risk       = RR adequacy vs the minimum RR (0..1) combined    |
//|                 with max-stop fit; a setup that can't express    |
//|                 its planned stop inside the price cap scores 0.  |
//|    execution  = caller-provided execution-condition quality      |
//|                 (0..1, default 1.0 when unknown); a live caller  |
//|                 feeds spread/vol conditions here.                |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_DECISION_SCORING_ENGINE_MQH
#define MITEMSHUB_DECISION_SCORING_ENGINE_MQH

#include "../Core/Constants.mqh"

//--- Default weights (sum = 1.0) — configurable per the plan. ------
#define DEFAULT_SCORE_W_SETUP       0.30
#define DEFAULT_SCORE_W_REGIME      0.25
#define DEFAULT_SCORE_W_STRUCTURE   0.10
#define DEFAULT_SCORE_W_RISK        0.25
#define DEFAULT_SCORE_W_EXECUTION   0.10

class CScoringEngine
  {
public:
   //--- Regime alignment: how well the CURRENT regime matches the setup's
   //--- required regime.  Exact match 1.0; same-family 0.7 (trend legs want
   //--- any trend/expansion state, range legs want range/compression/low);
   //--- transition/unknown 0.4; conflicting 0.2.
   static double RegimeAlignment(const ENUM_REGIME current, const ENUM_REGIME required)
     {
      if(current == required)
         return 1.0;
      bool trend_family = (required == REGIME_TREND_UP || required == REGIME_TREND_DOWN);
      bool range_family = (required == REGIME_RANGE || required == REGIME_COMPRESSION
                           || required == REGIME_LOW_VOLATILITY);
      if(trend_family &&
         (current == REGIME_TREND_UP || current == REGIME_TREND_DOWN
          || current == REGIME_EXPANSION || current == REGIME_HIGH_VOLATILITY))
         return 0.7;
      if(range_family &&
         (current == REGIME_RANGE || current == REGIME_COMPRESSION
          || current == REGIME_LOW_VOLATILITY))
         return 0.7;
      if(current == REGIME_TRANSITION || current == REGIME_UNKNOWN)
         return 0.4;
      return 0.2;
     }

   //--- Risk score: RR adequacy (0..1) weighted 0.7 + max-stop fit 0.3.
   //--- reward_risk <= 0 -> risk score 0 (a setup with no edge geometry).
   //--- max_stop_pct <= 0 means "no stop cap in force" (fit = 1.0).
   static double RiskScore(const double reward_risk, const double min_rr,
                           const double stop_pct, const double max_stop_pct)
     {
      if(reward_risk <= 0.0)
         return 0.0;
      double rr_ratio = (min_rr > 0.0) ? MathMin(1.0, reward_risk / min_rr) : 1.0;
      double fit = 1.0;
      if(max_stop_pct > 0.0 && stop_pct > 0.0)
         fit = (stop_pct <= max_stop_pct) ? 1.0 : MathMax(0.0, max_stop_pct / stop_pct);
      return 0.7 * rr_ratio + 0.3 * fit;
     }

   //--- Composite: weighted sum of the five sub-scores (all 0..1).
   static double Composite(const double setup_score, const double regime_score,
                           const double structure_score, const double risk_score,
                           const double execution_score,
                           const double w_setup = DEFAULT_SCORE_W_SETUP,
                           const double w_regime = DEFAULT_SCORE_W_REGIME,
                           const double w_structure = DEFAULT_SCORE_W_STRUCTURE,
                           const double w_risk = DEFAULT_SCORE_W_RISK,
                           const double w_execution = DEFAULT_SCORE_W_EXECUTION)
     {
      double s = w_setup * setup_score + w_regime * regime_score
                 + w_structure * structure_score + w_risk * risk_score
                 + w_execution * execution_score;
      return MathMax(0.0, MathMin(1.0, s));
     }

   //--- One-shot: full breakdown from a candidate + context.  Returns the
   //--- composite; fills the breakdown struct.  structure_score and
   //--- execution_score are caller inputs (0..1); pass -1 to use the
   //--- neutral defaults (0.5 / 1.0).
   static double Evaluate(const StrategyCandidate &cand,
                          const ENUM_REGIME current_regime,
                          const double structure_score,
                          const double execution_score,
                          ScoreBreakdown &out)
     {
      out.setup_score     = MathMax(0.0, MathMin(1.0, cand.setup_quality));
      out.regime_score    = RegimeAlignment(current_regime, cand.required_regime);
      out.structure_score = (structure_score >= 0.0 && structure_score <= 1.0)
                            ? structure_score : 0.5;
      out.execution_score = (execution_score >= 0.0 && execution_score <= 1.0)
                            ? execution_score : 1.0;

      double risk_dist = MathAbs(cand.entry - cand.stop_loss);
      double stop_pct = (cand.entry > 0.0 && risk_dist > 0.0)
                        ? risk_dist / cand.entry : 0.0;
      double rr = (risk_dist > 0.0)
                  ? MathAbs(cand.take_profit - cand.entry) / risk_dist : 0.0;
      out.risk_score = RiskScore(rr, DEFAULT_BAND_MIN_TARGET_RR, stop_pct,
                                 DEFAULT_BAND_MAX_STOP_PCT);
      out.composite = Composite(out.setup_score, out.regime_score,
                                out.structure_score, out.risk_score,
                                out.execution_score);
      return out.composite;
     }

   //--- Human-readable explanation (the plan's journal format).
   //--- Example: "REGIME=RANGE TREND_ALIGNMENT=LOW SETUP_QUALITY=54
   //---          RISK/REWARD=INSUFFICIENT EXECUTION_QUALITY=GOOD"
   static string Explain(const ScoreBreakdown &b, const string regime_label)
     {
      string trend = b.regime_score >= 0.7 ? "HIGH" : (b.regime_score >= 0.4 ? "MEDIUM" : "LOW");
      string rr = b.risk_score >= 0.7 ? "ADEQUATE" : "INSUFFICIENT";
      string ex = b.execution_score >= 0.8 ? "GOOD" : (b.execution_score >= 0.5 ? "FAIR" : "POOR");
      return StringFormat("REGIME=%s TREND_ALIGNMENT=%s SETUP_QUALITY=%.0f "
                          "STRUCTURE=%.0f RISK/REWARD=%s EXECUTION_QUALITY=%s "
                          "COMPOSITE=%.0f",
                          regime_label, trend, b.setup_score * 100.0,
                          b.structure_score * 100.0, rr, ex, b.composite * 100.0);
     }
  };

#endif // MITEMSHUB_DECISION_SCORING_ENGINE_MQH
