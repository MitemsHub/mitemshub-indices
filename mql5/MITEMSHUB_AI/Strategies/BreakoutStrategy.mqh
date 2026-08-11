//+------------------------------------------------------------------+
//|                                    Strategies/BreakoutStrategy.mqh|
//|  MITEMSHUB AI MARKET ENGINE — breakout (RESEARCH).               |
//|                                                                  |
//|  STATUS: DISABLED — research only.  Compiles but returns WAIT    |
//|  until it passes the walk-forward gates of the band leg.         |
//|                                                                  |
//|  ── HYPOTHESIS BLOCK ──────────────────────────────────────────── |
//|  H1 hypothesis:  A COMPRESSION regime (ATR percentile < 0.1)     |
//|    resolved by a displacement bar (Phase 3 DisplacementDetector  |
//|    ≥ 2×ATR body, close ≥ 0.7 location) through a tested range    |
//|    boundary (Phase 3 SupportResistance, ≥ 2 touches) continues   |
//|    in the breakout direction with positive expectancy.           |
//|  H2 why it might work:  compression stores directional energy;    |
//|    the first displacement through a high-touch level is where    |
//|    resting orders cluster, so follow-through is more likely      |
//|    than a random move — and the stop behind the boundary is      |
//|    cheap when the level was genuinely tested.                    |
//|  H3 measurable variables:  regime = COMPRESSION + confidence;    |
//|    ATR percentile; range boundary touch count; displacement      |
//|    body/range in ATR; close-location; bars since compression     |
//|    started (spring length).                                      |
//|  H4 expected regime:  COMPRESSION → EXPANSION transition only.   |
//|  H5 invalidation:  close back inside the broken boundary within  |
//|    N bars (failed breakout), or the ATR-based stop.              |
//|  H6 expected reward/risk:  ≥ 2.0R, target at external liquidity  |
//|    or the expansion band edge.                                   |
//|  H7 data required:  ≥ 14 days clean M5 per symbol; compression   |
//|    episode log with outcome per breakout.                        |
//|  H8 how it could fail:  synthetic indices breakout-and-revert    |
//|    (the classic false break on a CSPRNG-driven market); most     |
//|    breakouts during quiet regimes are range resumption; costs    |
//|    spike exactly at displacement bars.                           |
//|  H9 OOS test:  walk-forward; only closed-bar confirmations; no   |
//|    same-day re-entry after a failed breakout (independence).     |
//|  H10 overfit detection:  robustness across ±1 compression        |
//|    threshold, ±1 displacement multiple, ±1 touch requirement;    |
//|    reject if any neighborhood cell flips expectancy sign.        |
//|  ──────────────────────────────────────────────────────────────── |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_BREAKOUTSTRATEGY_MQH
#define MITEMSHUB_STRATEGIES_BREAKOUTSTRATEGY_MQH

#include "../Core/Constants.mqh"

class CBreakoutStrategy
  {
public:
   static StrategyCandidate Evaluate(const double &closes[], const int count,
                                     StrategyCandidate &out)
     {
      out.strategy        = STRATEGY_BREAKOUT;
      out.decision        = DECISION_WAIT;
      out.entry           = 0.0;
      out.stop_loss       = 0.0;
      out.take_profit     = 0.0;
      out.setup_quality   = 0.0;
      out.confidence      = 0.0;
      out.reason_codes    = "research: hypothesis not validated OOS - disabled by matrix";
      out.required_regime = REGIME_COMPRESSION;
      return(out);
     }
  };

#endif // MITEMSHUB_STRATEGIES_BREAKOUTSTRATEGY_MQH
