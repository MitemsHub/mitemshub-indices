//+------------------------------------------------------------------+
//|                                 Strategies/TrendContinuation.mqh |
//|  MITEMSHUB AI MARKET ENGINE — trend continuation (RESEARCH).     |
//|                                                                  |
//|  STATUS: DISABLED — research only.  This module compiles but     |
//|  returns WAIT until it passes the same walk-forward gates as the |
//|  band leg (§: train → validate → OOS → walk forward on the real  |
//|  corpus with realistic costs).  The StrategyEngine hard-disables |
//|  it via the regime-allowance matrix.                             |
//|                                                                  |
//|  ── HYPOTHESIS BLOCK ──────────────────────────────────────────── |
//|  H1 hypothesis:  In a confirmed HTF trend (4H regime TREND_UP/   |
//|    DOWN, structure HH+HL / LH+LL), a pullback that preserves the |
//|    swing structure and then breaks the last swing in the trend   |
//|    direction (BOS) continues with positive expectancy.           |
//|  H2 why it might work:  Trend persistence is real on synthetic   |
//|    indices during regime windows (Hurst > 0.6 measured on R_75   |
//|    in Phase 2); entry after a *controlled* retrace buys a better |
//|    price than a chase entry and the stop sits behind a real      |
//|    swing, so the invalidation is structural, not noise.          |
//|  H3 measurable variables:  regime label + confidence; structure  |
//|    bias (Phase 3 StructureEngine); pullback depth in ATR; BOS    |
//|    event with strength; RR of the resulting geometry.            |
//|  H4 expected regime:  TREND_UP / TREND_DOWN only (disabled in    |
//|    RANGE/COMPRESSION/EXPANSION by the matrix).                   |
//|  H5 invalidation:  close back through the broken swing level     |
//|    (structure restored) or the ATR-based stop.                   |
//|  H6 expected reward/risk:  ≥ 2.0R (structural target via         |
//|    external liquidity, RR gate enforced pre-entry).              |
//|  H7 data required:  ≥ 14 days of clean MT5 M5 ticks per symbol;  |
//|    per-trade outcome journal with MAE/MFE.                       |
//|  H8 how it could fail:  synthetic indices mean-revert on short   |
//|    horizons — a 15m pullback BOS may be the local top; HTF trend |
//|    flips during TRANSITION regimes; costs eat 2R+ targets.       |
//|  H9 OOS test:  walk-forward with 60/40 train/OOS split per week, |
//|    only closed-bar signals, no parameter reuse across folds.     |
//|  H10 overfit detection:  parameter-neighborhood robustness (run  |
//|    ±1 ATR period, ±0.5 pullback depth, ±1 swing guard) and       |
//|    rejection if expectancy flips sign within the neighborhood.   |
//|  ──────────────────────────────────────────────────────────────── |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_TRENDCONTINUATION_MQH
#define MITEMSHUB_STRATEGIES_TRENDCONTINUATION_MQH

#include "../Core/Constants.mqh"

class CTrendContinuation
  {
public:
   //--- Research stub: always stands aside until validated OOS.
   static StrategyCandidate Evaluate(const double &closes[], const int count,
                                     StrategyCandidate &out)
     {
      out.strategy        = STRATEGY_TREND;
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

#endif // MITEMSHUB_STRATEGIES_TRENDCONTINUATION_MQH
