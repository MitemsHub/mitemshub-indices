//+------------------------------------------------------------------+
//| Risk/RiskEngine.mqh                                              |
//|  MITEMSHUB AI MARKET ENGINE — Phase 6 RiskEngine (final          |
//|  authority).                                                     |
//|                                                                  |
//|  Consumes the Phase-5 decision output (a StrategyCandidate with  |
//|  its confidence / reward_risk / direction) and decides:          |
//|    APPROVED  -> sized lots + stake (RiskVerdict)                 |
//|    VETOED    -> approved=false + the reason trail                |
//|                                                                  |
//|  The veto gates are the exact Python RiskEngine conditions       |
//|  (risk/engine.py), locked by the Phase-6 parity gate:            |
//|    max open positions, consecutive-loss circuit breaker, daily   |
//|    loss limit, confidence below min, reward/risk below min,      |
//|    exposure (netting second position / exposure %), and the      |
//|    EMERGENCY_STOP.  Sizing = CPositionSizer::Stake (Python       |
//|  parity) then CPositionSizer::Lots (MT5 volume grid).          |
//|                                                                  |
//|  Phase-5 decision-layer verdicts feed the gates (MQL5 extension, |
//|  Python has no verdict bucket): when m_veto_weak is ON (default), |
//|  a candidate whose ConfidenceEngine verdict is WEAK_BUY/WEAK_SELL|
//|  is vetoed before the sizer runs — only STRONG signals trade.    |
//|  A WAIT verdict is also vetoed (a WAIT candidate must never be   |
//|  sized, even if its raw confidence clears the minimum).          |
//|                                                                  |
//|  State lives in CRiskLimits (streaks, daily/hourly counters,     |
//|  equity) and CExposureManager (positions/exposure); this module  |
//|  only arbitrates.  No code path auto-overrides a breached hard   |
//|  limit.                                                          |
//|                                                                  |
//|  ARCHITECTURE:                                                   |
//|  This is the FINAL authority for trade approval.  Every trade    |
//|  must pass through this module before execution.  The module     |
//|  is composed of sub-engines:                                     |
//|    - CRiskLimits: streaks, daily/hourly counters, equity        |
//|    - CDrawdownProtection: drawdown tracking                     |
//|    - CExposureManager: position and margin exposure             |
//|    - CPositionSizer: lot sizing calculation                     |
//|                                                                  |
//|  PYTHON PARITY:                                                  |
//|  All veto conditions match Python RiskEngine exactly.  The       |
//|  Phase-6 real-corpus gate verifies parity on every verify loop.  |
//|  The Python parity defaults are defined in Constants.mqh.        |
//|                                                                  |
//|  VETO PRIORITY (checked in order):                               |
//|  1. EmergencyStop (immediate halt)                               |
//|  2. Max open positions                                           |
//|  3. Consecutive loss circuit breaker                             |
//|  4. Daily loss limit                                             |
//|  5. Equity drawdown limit                                        |
//|  6. Weak signal veto (MQL5 extension)                            |
//|  7. Wait signal veto                                             |
//|  8. Confidence below minimum                                     |
//|  9. Reward:risk below minimum                                    |
//|  10. Volatility z-score extreme                                  |
//|  11. Exposure limit                                              |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_RISK_RISKENGINE_MQH
#define MITEMSHUB_RISK_RISKENGINE_MQH

#include "../Core/Constants.mqh"
#include "RiskLimits.mqh"
#include "DrawdownProtection.mqh"
#include "PositionSizer.mqh"
#include "ExposureManager.mqh"

//+------------------------------------------------------------------+
//| PYTHON RISKENGINE DEFAULTS (RiskConfig)                            |
//|                                                                    |
//| These constants match the Python RiskEngine defaults exactly.     |
//| They are used as fallback values when the EA is not configured    |
//| via Config.mqh inputs.                                            |
//|                                                                    |
//| IMPORTANT: these are NOT tunable inputs — they are parity         |
//| constants.  To change risk behavior, modify Config.mqh inputs.    |
//+------------------------------------------------------------------+
#define PY_MIN_CONFIDENCE     0.48     // minimum decision confidence
#define PY_MIN_REWARD_RISK    1.2      // minimum expected reward:risk
#define PY_MAX_VOLATILITY_Z   3.0      // max volatility z-score for entry

//+------------------------------------------------------------------+
//| CRiskEngine                                                        |
//|                                                                    |
//| The final authority for trade approval.  This module arbitrates   |
//| between the decision layer's signal and the account's risk state. |
//|                                                                    |
//| LIFECYCLE:                                                        |
//|   1. Configure via Set* methods (risk per trade, min confidence) |
//|   2. SyncState() — update equity, margin, time window           |
//|   3. Evaluate() — consume StrategyCandidate, return RiskVerdict  |
//|   4. RegisterOpen/Close/Outcome — update state after trades     |
//|                                                                    |
//| COMPOSITION:                                                      |
//|   - limits: CRiskLimits — streaks, daily/hourly counters        |
//|   - dd: CDrawdownProtection — drawdown tracking                 |
//|   - exposure: CExposureManager — position and margin exposure   |
//|                                                                    |
//| The sub-engines are public so callers can configure them directly|
//| (MQL5 cannot return object references).                          |
//|                                                                    |
//| VETO BEHAVIOR:                                                    |
//|   - Each veto sets a reason string for journal logging          |
//|   - Multiple vetoes can be active simultaneously                |
//|   - The first veto in priority order is reported                |
//|   - No code path auto-overrides a breached hard limit           |
//+------------------------------------------------------------------+
class CRiskEngine
  {
public:
   //--- composed sub-engines (public members — MQL5 cannot return object
   //--- references, so the caller configures them directly, e.g.
   //--- engine.limits.SetMaxOpenPositions(...)).
   CRiskLimits         limits;       // streaks, daily/hourly counters, equity
   CDrawdownProtection dd;           // drawdown tracking
   CExposureManager    exposure;     // position and margin exposure

private:
   double              m_risk_per_trade;   // 0.005 = 0.5% per trade
   double              m_min_confidence;   // minimum decision confidence
   double              m_min_reward_risk;  // minimum expected reward:risk
   double              m_stake_floor;      // minimum stake (lots)
   double              m_vol_z;            // current candle range_z (0 = unknown)
   bool                m_state_inited;     // first SyncState: init the day window
   bool                m_veto_weak;        // veto WEAK/WAIT decision verdicts

public:
   //+--------------------------------------------------------------+
   //| Constructor — initialize with Python parity defaults.         |
   //+--------------------------------------------------------------+
   CRiskEngine()
     {
      m_risk_per_trade = PY_RISK_PER_TRADE;
      m_min_confidence = PY_MIN_CONFIDENCE;
      m_min_reward_risk = PY_MIN_REWARD_RISK;
      m_stake_floor = PY_STAKE_FLOOR;
      m_vol_z = 0.0;
      m_state_inited = false;
      m_veto_weak = true;
     }

   //+--------------------------------------------------------------+
   //| CONFIGURATION METHODS                                         |
   //|                                                                |
   //| Set risk parameters.  These mirror the Python RiskConfig.     |
   //+--------------------------------------------------------------+

   //+--------------------------------------------------------------+
   //| Set risk per trade as fraction of equity.                     |
   //| PARAM: v - risk fraction (0.005 = 0.5%)                      |
   //+--------------------------------------------------------------+
   void SetRiskPerTrade(double v)      { m_risk_per_trade = v; }

   //+--------------------------------------------------------------+
   //| Set minimum decision confidence for approval.                 |
   //| PARAM: v - minimum confidence (0.0-1.0)                      |
   //+--------------------------------------------------------------+
   void SetMinConfidence(double v)     { m_min_confidence = v; }

   //+--------------------------------------------------------------+
   //| Set minimum reward:risk ratio for approval.                   |
   //| PARAM: v - minimum R:R (e.g. 1.2 means 1.2:1 reward:risk)  |
   //+--------------------------------------------------------------+
   void SetMinRewardRisk(double v)     { m_min_reward_risk = v; }

   //+--------------------------------------------------------------+
   //| Set minimum stake (lots) floor.                               |
   //| PARAM: v - minimum stake in lots                              |
   //+--------------------------------------------------------------+
   void SetStakeFloor(double v)        { m_stake_floor = v; }

   //+--------------------------------------------------------------+
   //| Set current volatility z-score for extreme vol gate.          |
   //| PARAM: z - current z-score (0 = unknown, >3 = extreme)       |
   //+--------------------------------------------------------------+
   void SetVolatilityZ(double z)       { m_vol_z = z; }

   //+--------------------------------------------------------------+
   //| Enable/disable weak signal veto.                              |
   //| PARAM: on - true to veto WEAK/WAIT signals (default)         |
   //+--------------------------------------------------------------+
   void SetVetoWeakSignals(bool on)    { m_veto_weak = on; }

   //+--------------------------------------------------------------+
   //| STATE SYNCHRONIZATION                                         |
   //|                                                                |
   //| Update the risk engine's state from current account data.     |
   //| Must be called before Evaluate() to ensure accurate state.    |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   equity      - current account equity                       |
   //|   open_margin - margin used by open positions                 |
   //|   total_volume - total volume of open positions              |
   //|   now_epoch   - current time as epoch seconds                |
   //+--------------------------------------------------------------+
   void SyncState(const double equity, const double open_margin,
                  const double total_volume, const datetime now_epoch)
     {
      limits.SetEquity(equity, now_epoch);
      dd.SetEquity(equity);
      exposure.SetAccountState(equity, open_margin, total_volume);
      // mirror the session-day rollover into DrawdownProtection, and initialize
      // its day window on the first sync (day_start = current equity).
      bool day_rolled = limits.SyncWindow((int)((long)now_epoch / 3600),
                                          (int)((long)now_epoch / 86400));
      if(!m_state_inited || day_rolled)
        {
         dd.OnNewSessionDay();
         m_state_inited = true;
        }
     }

   //+--------------------------------------------------------------+
   //| Activate/deactivate emergency stop.                           |
   //| PARAM: on - true to halt all trading                         |
   //+--------------------------------------------------------------+
   void EmergencyStop(const bool on)   { limits.EmergencyStop(on); }

   //+--------------------------------------------------------------+
   //| THE DECISION: consume the Phase-5 candidate and arbitrate.     |
   //|                                                                |
   //| This is the core method that approves or vetoes a trade.      |
   //| It checks all risk gates in priority order and returns a      |
   //| RiskVerdict with approval status, sized lots, and reasons.    |
   //|                                                                |
   //| VETO GATES (checked in priority order):                       |
   //|   1. EmergencyStop — immediate halt                           |
   //|   2. Max open positions                                       |
   //|   3. Consecutive loss circuit breaker                         |
   //|   4. Daily loss limit                                         |
   //|   5. Equity drawdown limit                                    |
   //|   6. Weak signal veto (MQL5 extension)                        |
   //|   7. Wait signal veto                                         |
   //|   8. Confidence below minimum                                 |
   //|   9. Reward:risk below minimum                                |
   //|   10. Volatility z-score extreme                              |
   //|   11. Exposure limit                                          |
   //|                                                                |
   //| SIZING (if approved):                                         |
   //|   stake = CPositionSizer::Stake(equity, risk%, confidence,   |
   //|           min_confidence, empirical_scale, floor)             |
   //|   lots = CPositionSizer::Lots(stake, entry, stop, tick_value, |
   //|           tick_size, vol_min, vol_max, vol_step)             |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   cand            - StrategyCandidate from decision layer    |
   //|   empirical_scale - Stage-3 scale (1.0 full / 0.5 half)    |
   //|   vol_min         - minimum volume for symbol                |
   //|   vol_max         - maximum volume for symbol                |
   //|   vol_step        - volume step for symbol                   |
   //|   tick_value      - tick value for symbol                    |
   //|   tick_size       - tick size for symbol                     |
   //| RETURN: RiskVerdict with approved flag, lots, stake, reasons |
   //+--------------------------------------------------------------+
   RiskVerdict Evaluate(const StrategyCandidate &cand,
                        const double empirical_scale,
                        const double vol_min, const double vol_max,
                        const double vol_step,
                        const double tick_value, const double tick_size)
     {
      RiskVerdict v;
      v.approved = false;
      v.lots = 0.0;
      v.stake = 0.0;
      string reasons = "";

      //--- GATE 1: Emergency stop (highest priority) -------------------------
      if(limits.EmergencyStopped())
         reasons = "EMERGENCY_STOP active — trading disabled";

      //--- GATE 2: Max open positions ---------------------------------------
      // Guard: limit > 0 means enabled; limit == 0 means DISABLED
      if(limits.MaxOpenPositions() > 0 && limits.OpenPositions() >= limits.MaxOpenPositions())
         reasons = "max open positions reached";

      //--- GATE 3: Consecutive loss circuit breaker -------------------------
      else if(limits.MaxConsecutiveLosses() > 0
              && limits.ConsecutiveLosses() >= limits.MaxConsecutiveLosses())
         reasons = "consecutive-loss circuit breaker active";

      //--- GATE 4: Daily loss limit -----------------------------------------
      else if(limits.MaxDailyLossPct() > 0.0
              && limits.DailyDrawdownFraction() >= limits.MaxDailyLossPct())
         reasons = "daily loss limit reached";

      //--- GATE 5: Equity drawdown limit ------------------------------------
      else if(limits.MaxEquityDrawdownPct() > 0.0
              && limits.EquityDrawdownFraction() >= limits.MaxEquityDrawdownPct())
         reasons = "equity drawdown limit reached";

      //--- GATE 6: Weak signal veto (MQL5 extension) ------------------------
      // Phase-5 decision-layer verdicts feed the gates: WEAK verdicts are
      // vetoed before the sizer runs, and WAIT verdicts must never be sized.
      if(m_veto_weak &&
         (cand.signal_strength == SIGNAL_WEAK_BUY || cand.signal_strength == SIGNAL_WEAK_SELL))
         reasons = reasons == "" ? "decision-layer WEAK verdict — only STRONG signals trade"
                   : reasons + "; decision-layer WEAK verdict — only STRONG signals trade";

      //--- GATE 7: Wait signal veto -----------------------------------------
      if(cand.signal_strength == SIGNAL_WAIT)
         reasons = reasons == "" ? "decision-layer WAIT verdict — no tradeable setup"
                   : reasons + "; decision-layer WAIT verdict — no tradeable setup";

      //--- GATE 8: Confidence below minimum ---------------------------------
      if(cand.confidence < m_min_confidence)
         reasons = reasons == "" ? "signal confidence below risk threshold"
                   : reasons + "; signal confidence below risk threshold";

      //--- GATE 9: Reward:risk below minimum --------------------------------
      if(cand.decision != DECISION_WAIT)
        {
         double rr = 0.0;
         double risk_dist = MathAbs(cand.entry - cand.stop_loss);
         if(risk_dist > 0.0)
            rr = MathAbs(cand.take_profit - cand.entry) / risk_dist;
         if(rr < m_min_reward_risk)
            reasons = reasons == "" ? "reward/risk below minimum"
                      : reasons + "; reward/risk below minimum";
        }

      //--- GATE 10: Volatility z-score extreme ------------------------------
      if(m_vol_z > PY_MAX_VOLATILITY_Z)
         reasons = reasons == "" ? "current candle volatility is statistically extreme"
                   : reasons + "; current candle volatility is statistically extreme";

      //--- GATE 11: Exposure limit ------------------------------------------
      if(!exposure.CanOpen(cand.decision == DECISION_BUY ? 1 : -1))
         reasons = reasons == "" ? "exposure limit reached (netting/exposure)"
                   : reasons + "; exposure limit reached";

      //--- If any veto, return without sizing --------------------------------
      if(reasons != "")
        {
         v.reasons = reasons;
         return(v);
        }

      //--- APPROVED: size it -------------------------------------------------
      double stake = CPositionSizer::Stake(limits.Equity(), m_risk_per_trade,
                                           cand.confidence, m_min_confidence,
                                           empirical_scale, m_stake_floor);
      double lots = CPositionSizer::Lots(stake, cand.entry, cand.stop_loss,
                                         tick_value, tick_size,
                                         vol_min, vol_max, vol_step);
      v.approved = true;
      v.stake = stake;
      v.lots = lots;
      v.reasons = (empirical_scale <= 0.0)
                  ? "risk approved (paper-only — no empirical verdict)"
                  : "risk approved";
      return(v);
     }

   //+--------------------------------------------------------------+
   //| STATE REGISTRATION                                              |
   //|                                                                |
   //| Update risk state after trade events.  These delegate to the  |
   //| sub-engines (limits, exposure) to maintain accurate state.    |
   //+--------------------------------------------------------------+

   //+--------------------------------------------------------------+
   //| Register a new position open.                                 |
   //| PARAM: direction - +1 for long, -1 for short                 |
   //+--------------------------------------------------------------+
   void RegisterOpen(const int direction)
     {
      limits.RegisterOpen();
      exposure.RegisterOpen(direction);
     }

   //+--------------------------------------------------------------+
   //| Register a trade outcome (win/loss).                          |
   //| PARAMS:                                                       |
   //|   pnl      - profit/loss in account currency                 |
   //|   return_r - return in R-multiples                           |
   //+--------------------------------------------------------------+
   void RegisterOutcome(const double pnl, const double return_r)
     {
      limits.RegisterOutcome(pnl, return_r);
     }

   //+--------------------------------------------------------------+
   //| Register a position close.                                    |
   //| PARAM: direction - +1 for long, -1 for short                 |
   //+--------------------------------------------------------------+
   void RegisterClose(const int direction)
     {
      limits.RegisterClose();
      exposure.RegisterClose(direction);
     }
  };

#endif // MITEMSHUB_RISK_RISKENGINE_MQH
