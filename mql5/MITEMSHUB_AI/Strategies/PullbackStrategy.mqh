//+------------------------------------------------------------------+
//|                                    Strategies/PullbackStrategy.mqh|
//|  MITEMSHUB AI MARKET ENGINE — pullback / re-entry (RESEARCH).    |
//|                                                                  |
//|  STATUS: DISABLED — research only.  Compiles but returns WAIT    |
//|  until it passes the walk-forward gates of the band leg.         |
//|                                                                  |
//|  ── HYPOTHESIS BLOCK ──────────────────────────────────────────── |
//|  H1 hypothesis:  In an established directional regime (4H        |
//|    TREND_UP/DOWN + Phase 3 bias aligned), an impulse (Phase 3    |
//|    displacement) followed by a *controlled* retracement that     |
//|    preserves the swing structure (no CHOCH against the trend,    |
//|    retrace depth < 61.8% of the impulse) then breaks the last    |
//|    swing in the trend direction (BOS) re-enters the trend with   |
//|    positive expectancy at a better price than the impulse entry. |
//|  H2 why it might work:  the retracement drains weak holders and  |
//|    resets entry crowding; the BOS after the retrace is the       |
//|    second leg, which is where most of a trend's move lives; the  |
//|    stop behind the preserved swing is structurally cheap.        |
//|  H3 measurable variables:  regime + bias; impulse displacement   |
//|    (body/range in ATR); retrace depth as % of impulse and in     |
//|    ATR; structure preserved (no adverse CHOCH); BOS event with   |
//|    strength; RR of the resulting geometry.                      |
//|  H4 expected regime:  TREND_UP / TREND_DOWN only.                |
//|  H5 invalidation:  retrace beyond 61.8% of the impulse (structure |
//|    damage) or close back through the broken swing.               |
//|  H6 expected reward/risk:  ≥ 2.0R; target at external liquidity  |
//|    or the band edge.                                             |
//|  H7 data required:  ≥ 14 days clean M5 per symbol; per-trade     |
//|    outcome with retrace-depth bucket.                            |
//|  H8 how it could fail:  the retrace is the whole move on a       |
//|    CSPRNG-driven index (impulse + fade, no second leg); retrace  |
//|    depth buckets are regime-dependent and drift; costs on the    |
//|    BOS re-entry eat a thin edge.                                 |
//|  H9 OOS test:  walk-forward; impulse + retrace + BOS all on      |
//|    closed bars; no re-entry after a failed second leg for N      |
//|    bars.                                                         |
//|  H10 overfit detection:  robustness across ±5% retrace depth,    |
//|    ±1 ATR period, ±1 swing guard; reject if expectancy flips     |
//|    sign in any neighborhood cell.                                |
//|  ──────────────────────────────────────────────────────────────── |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_PULLBACKSTRATEGY_MQH
#define MITEMSHUB_STRATEGIES_PULLBACKSTRATEGY_MQH

#include "../Core/Constants.mqh"

class CPullbackStrategy
  {
public:
   static StrategyCandidate Evaluate(const double &closes[], const int count,
                                     StrategyCandidate &out)
     {
      out.strategy        = STRATEGY_PULLBACK;
      out.decision        = DECISION_WAIT;
      out.entry           = 0.0;
      out.stop_loss       = 0.0;
      out.take_profit     = 0.0;
      out.setup_quality   = 0.0;
      out.confidence      = 0.0;
      out.reason_codes    = "research: hypothesis not validated OOS - disabled by matrix";
      out.required_regime = REGIME_TREND_UP;
      return(out);
     }
  };

#endif // MITEMSHUB_STRATEGIES_PULLBACKSTRATEGY_MQH
