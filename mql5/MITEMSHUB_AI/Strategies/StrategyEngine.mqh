//+------------------------------------------------------------------+
//|                                    Strategies/StrategyEngine.mqh |
//|  MITEMSHUB AI MARKET ENGINE — strategy registry + regime gate.   |
//|                                                                  |
//|  The Regime Engine decides which strategies are ALLOWED in the   |
//|  current regime; a strategy that is not allowed never evaluates. |
//|  This prevents the classic failure mode of running every         |
//|  strategy simultaneously without regime awareness (mean          |
//|  reversion firing into a trend, breakouts chasing an expansion). |
//|                                                                  |
//|  ACTIVE: BandGeometry (allowed in every regime — its own gates   |
//|  decide, and it is the only strategy validated OOS).  All five   |
//|  research strategies are HARD-DISABLED until they pass the same  |
//|  walk-forward gates as the band leg; the matrix marks them OFF   |
//|  via the strategy's required regime not being in the allowance   |
//|  list (they return WAIT regardless, as a belt-and-braces guard). |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_STRATEGYENGINE_MQH
#define MITEMSHUB_STRATEGIES_STRATEGYENGINE_MQH

#include "../Core/Constants.mqh"
#include "BandGeometry.mqh"
#include "TrendContinuation.mqh"
#include "BreakoutStrategy.mqh"
#include "MeanReversion.mqh"
#include "LiquiditySweep.mqh"
#include "PullbackStrategy.mqh"

class CStrategyEngine
  {
public:
   //--- Target end-state regime-allowance matrix (testable directly).
   //--- Research strategies are OFF everywhere until validated OOS — IsAllowed
   //--- applies the ResearchEnabled() guard on top of this matrix.
   static bool MatrixAllows(const ENUM_STRATEGY strategy, const ENUM_REGIME regime)
     {
      switch(regime)
        {
         case REGIME_TREND_UP:
         case REGIME_TREND_DOWN:
            return(strategy == STRATEGY_BAND || strategy == STRATEGY_TREND ||
                   strategy == STRATEGY_BREAKOUT || strategy == STRATEGY_PULLBACK);
         case REGIME_RANGE:
            return(strategy == STRATEGY_BAND || strategy == STRATEGY_MEANREVERSION ||
                   strategy == STRATEGY_LIQUIDITY_SWEEP);
         case REGIME_COMPRESSION:
            return(strategy == STRATEGY_BAND || strategy == STRATEGY_BREAKOUT ||
                   strategy == STRATEGY_LIQUIDITY_SWEEP);
         default:
            // EXPANSION / HIGH_VOL / LOW_VOL / TRANSITION / UNKNOWN: only the
            // band leg (it fades the extremes; nothing else is trusted here).
            return(strategy == STRATEGY_BAND);
        }
     }

   static bool IsAllowed(const ENUM_STRATEGY strategy, const ENUM_REGIME regime)
     {
      if(strategy == STRATEGY_BAND)
         return(true);                       // validated leg, self-gated
      if(!ResearchEnabled())
         return(false);                      // research hard-disabled today
      return(MatrixAllows(strategy, regime));
     }

   //--- The strategies a regime currently allows, oldest-first.
   static int AllowedStrategies(const ENUM_REGIME regime, ENUM_STRATEGY &out[],
                                const int max_out)
     {
      ArrayResize(out, 0);
      for(int s = (int)STRATEGY_BAND; s <= (int)STRATEGY_PULLBACK; s++)
        {
         if(ArraySize(out) >= max_out)
            break;
         if(IsAllowed((ENUM_STRATEGY)s, regime))
           {
            int n = ArraySize(out);
            ArrayResize(out, n + 1);
            out[n] = (ENUM_STRATEGY)s;
           }
        }
      return(ArraySize(out));
     }

   //--- Full candidate evaluation: band is live; research returns WAIT.
   //--- context carries the band inputs; research stubs ignore it.
   struct BandContext
     {
      double   entry;
      int      direction;       // +1 buy, -1 sell
      double   sigma_per_bar;
      int      bar_sec;
      int      hold_sec;
      double   stop_sigma_mult;
      double   target_sigma_mult;
      double   min_target_rr;
      double   max_stop_pct;
     };

   static StrategyCandidate Evaluate(const ENUM_STRATEGY strategy,
                                     const BandContext &ctx)
     {
      StrategyCandidate c;
      if(strategy == STRATEGY_BAND)
         return(EvaluateBand(ctx));
      // Research stubs: stand aside (belt and braces on top of the matrix).
      double dummy[];
      switch(strategy)
        {
         case STRATEGY_TREND:          return(CTrendContinuation::Evaluate(dummy, 0, c));
         case STRATEGY_BREAKOUT:       return(CBreakoutStrategy::Evaluate(dummy, 0, c));
         case STRATEGY_MEANREVERSION:  return(CMeanReversion::Evaluate(dummy, 0, c));
         case STRATEGY_LIQUIDITY_SWEEP: return(CLiquiditySweep::Evaluate(dummy, 0, c));
         case STRATEGY_PULLBACK:       return(CPullbackStrategy::Evaluate(dummy, 0, c));
         default:
            c.strategy = STRATEGY_NONE;
            c.decision = DECISION_WAIT;
            c.reason_codes = "unknown strategy";
            return(c);
        }
     }

   //--- Band candidate: entry gate first, then the shared level geometry.
   static StrategyCandidate EvaluateBand(const BandContext &ctx)
     {
      StrategyCandidate c;
      c.strategy        = STRATEGY_BAND;
      c.decision        = DECISION_WAIT;
      c.entry           = ctx.entry;
      c.stop_loss       = 0.0;
      c.take_profit     = 0.0;
      c.setup_quality   = 0.0;
      c.confidence      = 0.0;
      c.reason_codes    = "band: entry gate not met";
      c.required_regime = REGIME_UNKNOWN;
      if(ctx.direction == 0)
         return(c);
      CBandGeometry::BandLevels lv;
      if(!CBandGeometry::ComputeLevels(ctx.entry, ctx.direction, ctx.sigma_per_bar,
                                       ctx.bar_sec, ctx.hold_sec, ctx.stop_sigma_mult,
                                       ctx.target_sigma_mult, ctx.min_target_rr,
                                       ctx.max_stop_pct, lv))
        {
         c.reason_codes = "band: geometry not tradeable - stand aside";
         return(c);
        }
      c.decision      = ctx.direction > 0 ? DECISION_BUY : DECISION_SELL;
      c.stop_loss     = lv.stop_loss;
      c.take_profit   = lv.take_profit;
      c.setup_quality = 0.6;
      c.confidence    = 0.55;
      c.reason_codes  = "band: geometry confirmed";
      return(c);
     }

private:
   //--- Research strategies stay hard-disabled until each passes the same
   //--- walk-forward gates as the band leg.  Flip to true only after a
   //--- strategy's hypothesis block survives OOS validation.
   static bool ResearchEnabled()
     {
      return(false);
     }
  };

#endif // MITEMSHUB_STRATEGIES_STRATEGYENGINE_MQH
