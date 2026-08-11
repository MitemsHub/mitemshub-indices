//+------------------------------------------------------------------+
//|                                    Strategies/MeanReversion.mqh  |
//|  MITEMSHUB AI MARKET ENGINE — mean reversion (RESEARCH).         |
//|                                                                  |
//|  STATUS: DISABLED — research only.  Compiles but returns WAIT    |
//|  until it passes the walk-forward gates of the band leg.         |
//|                                                                  |
//|  ── HYPOTHESIS BLOCK ──────────────────────────────────────────── |
//|  H1 hypothesis:  In a RANGE regime (Phase 2 RangeDetector high,  |
//|    low efficiency), a close more than z_entry × σ away from the  |
//|    range mean that then rejects a tested boundary (Phase 3 S/R   |
//|    touch ≥ 2) reverts toward the mean with positive expectancy   |
//|    — the price returned to a level with known resting orders.    |
//|  H2 why it might work:  range-bound markets have a measurable    |
//|    attractor (the mean); the closer price gets to a high-touch   |
//|    boundary, the more probable the bounce, because market        |
//|    makers defend tested levels and momentum dies at them.        |
//|  H3 measurable variables:  regime = RANGE + confidence; z-score   |
//|    of close vs mean; boundary touch count; rejection candle      |
//|    (close-location); ATR percentile (must not be expanding).     |
//|  H4 expected regime:  RANGE ONLY — explicitly disabled in         |
//|    TREND/EXPANSION (the classic mean-reversion trap).            |
//|  H5 invalidation:  close beyond the boundary (range break), or   |
//|    the ATR-based stop.                                           |
//|  H6 expected reward/risk:  ≥ 2.0R, target at the opposite        |
//|    boundary or the mean.                                         |
//|  H7 data required:  ≥ 14 days clean M5 per symbol; per-trade     |
//|    outcome with regime label.                                    |
//|  H8 how it could fail:  the range is a regime, not a constant —  |
//|    what looks like a boundary bounce is the start of a trend;    |
//|    vol expansion breaks every mean; reversion edges are small    |
//|    and cost-sensitive (must net after 0.05/0.10 cost model).     |
//|  H9 OOS test:  walk-forward; regime must be RANGE *on closed     |
//|    bars* at entry; no re-entry after a range break for N bars.   |
//|  H10 overfit detection:  robustness across ±0.5 z_entry, ±1 ATR  |
//|    period, ±1 touch count; reject if expectancy flips sign in    |
//|    any neighborhood cell.                                        |
//|  ──────────────────────────────────────────────────────────────── |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_MEANREVERSION_MQH
#define MITEMSHUB_STRATEGIES_MEANREVERSION_MQH

#include "../Core/Constants.mqh"

class CMeanReversion
  {
public:
   static StrategyCandidate Evaluate(const double &closes[], const int count,
                                     StrategyCandidate &out)
     {
      out.strategy        = STRATEGY_MEANREVERSION;
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

#endif // MITEMSHUB_STRATEGIES_MEANREVERSION_MQH
