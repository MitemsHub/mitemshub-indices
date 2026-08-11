//+------------------------------------------------------------------+
//|                                    Strategies/LiquiditySweep.mqh |
//|  MITEMSHUB AI MARKET ENGINE — liquidity sweep reversal (RESEARCH).|
//|                                                                  |
//|  STATUS: DISABLED — research only.  Compiles but returns WAIT    |
//|  until it passes the walk-forward gates of the band leg.         |
//|                                                                  |
//|  ── HYPOTHESIS BLOCK ──────────────────────────────────────────── |
//|  H1 hypothesis:  A sweep of a recent swing level (Phase 3        |
//|    LiquidityEngine: wick beyond the level ≥ 0.1×ATR, close back  |
//|    inside) followed by a displacement bar against the sweep and  |
//|    a structure shift (Phase 3 CHOCH or BOS against the sweep     |
//|    direction) reverses with positive expectancy.                 |
//|  H2 why it might work:  a sweep hunts resting stop-losses above  |
//|    a swing high / below a swing low; once the stops are filled   |
//|    the fuel is gone and the displacement away shows real         |
//|    institutional intent — the reversal leg is where the trapped  |
//|    liquidity becomes the fuel.                                   |
//|  H3 measurable variables:  sweep event {level, extreme, close,   |
//|    direction}; displacement after the sweep (body/range in ATR,  |
//|    close-location); CHOCH/BOS event timing vs sweep timing;      |
//|    bars between sweep and confirmation (staleness gate).         |
//|  H4 expected regime:  RANGE (sweep of the range boundary) or     |
//|    COMPRESSION (sweep of the spring level).  Never EXPANSION.    |
//|  H5 invalidation:  price closes beyond the swept level (the      |
//|    sweep was a real break), or the ATR-based stop.               |
//|  H6 expected reward/risk:  ≥ 2.0R; target at the opposite        |
//|    liquidity or the band edge.                                   |
//|  H7 data required:  ≥ 14 days clean M5 per symbol; sweep log     |
//|    with outcome per reversal.                                    |
//|  H8 how it could fail:  synthetic indices are CSPRNG-driven —    |
//|    sweeps may be pure noise with no trapped-liquidity dynamics;  |
//|    the displacement leg may already be spent by the time the     |
//|    confirmation bar closes; costs are highest right at sweeps.   |
//|  H9 OOS test:  walk-forward; sweep + confirmation must both be   |
//|    on closed bars; no re-entry after a failed reversal for N     |
//|    bars.                                                         |
//|  H10 overfit detection:  robustness across ±0.1×ATR sweep        |
//|    exceed, ±1 displacement multiple, ±1 swing guard; reject if   |
//|    any neighborhood cell flips expectancy sign.                  |
//|  ──────────────────────────────────────────────────────────────── |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_LIQUIDITYSWEEP_MQH
#define MITEMSHUB_STRATEGIES_LIQUIDITYSWEEP_MQH

#include "../Core/Constants.mqh"

class CLiquiditySweep
  {
public:
   static StrategyCandidate Evaluate(const double &closes[], const int count,
                                     StrategyCandidate &out)
     {
      out.strategy        = STRATEGY_LIQUIDITY_SWEEP;
      out.decision        = DECISION_WAIT;
      out.entry           = 0.0;
      out.stop_loss       = 0.0;
      out.take_profit     = 0.0;
      out.setup_quality   = 0.0;
      out.confidence      = 0.0;
      out.reason_codes    = "research: hypothesis not validated OOS - disabled by matrix";
      out.required_regime = REGIME_RANGE;
      return(out);
     }
  };

#endif // MITEMSHUB_STRATEGIES_LIQUIDITYSWEEP_MQH
