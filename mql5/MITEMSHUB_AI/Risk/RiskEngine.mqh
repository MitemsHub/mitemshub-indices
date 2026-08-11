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
//|    parity) then CPositionSizer::Lots (MT5 volume grid).          |
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
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_RISK_RISKENGINE_MQH
#define MITEMSHUB_RISK_RISKENGINE_MQH

#include "../Core/Constants.mqh"
#include "RiskLimits.mqh"
#include "DrawdownProtection.mqh"
#include "PositionSizer.mqh"
#include "ExposureManager.mqh"

//--- Python RiskEngine defaults (RiskConfig) ----------------------------------
#define PY_MIN_CONFIDENCE     0.48
#define PY_MIN_REWARD_RISK    1.2
#define PY_MAX_VOLATILITY_Z   3.0

class CRiskEngine
  {
public:
   //--- composed sub-engines (public members — MQL5 cannot return object
   //--- references, so the caller configures them directly, e.g.
   //--- engine.limits.SetMaxOpenPositions(...)).
   CRiskLimits         limits;
   CDrawdownProtection dd;
   CExposureManager    exposure;

private:
   double              m_risk_per_trade;   // 0.005 = 0.5% per trade
   double              m_min_confidence;
   double              m_min_reward_risk;
   double              m_stake_floor;
   double              m_vol_z;            // current candle range_z (0 = unknown)
   bool                m_state_inited;     // first SyncState: init the day window
   bool                m_veto_weak;        // veto WEAK/WAIT decision verdicts

public:
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

   void SetRiskPerTrade(double v)      { m_risk_per_trade = v; }
   void SetMinConfidence(double v)     { m_min_confidence = v; }
   void SetMinRewardRisk(double v)     { m_min_reward_risk = v; }
   void SetStakeFloor(double v)        { m_stake_floor = v; }
   void SetVolatilityZ(double z)       { m_vol_z = z; }
   void SetVetoWeakSignals(bool on)    { m_veto_weak = on; }

   //--- Sync the equity + window state ---------------------------------------
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

   void EmergencyStop(const bool on)   { limits.EmergencyStop(on); }

   //--- THE decision: consume the Phase-5 candidate and arbitrate ------------
   // cand: the decision output (confidence/reward_risk/direction/entry/stop).
   // empirical_scale: Stage-3 scale (1.0 full / 0.5 half / 0.0 paper-only).
   // Symbol volume grid comes from the SymbolAdapter (Phase-1).
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

      if(limits.EmergencyStopped())
         reasons = "EMERGENCY_STOP active — trading disabled";
      // per-limit diagnostics (Python-parity reasons) — always run so a
      // breached limit is named, never hidden behind a generic message.
      if(limits.OpenPositions() >= limits.MaxOpenPositions())
         reasons = "max open positions reached";
      else if(limits.ConsecutiveLosses() >= limits.MaxConsecutiveLosses())
         reasons = "consecutive-loss circuit breaker active";
      else if(limits.DailyDrawdownFraction() >= limits.MaxDailyLossPct())
         reasons = "daily loss limit reached";
      else if(limits.EquityDrawdownFraction() >= limits.MaxEquityDrawdownPct())
         reasons = "equity drawdown limit reached";

      // Phase-5 decision-layer verdict gate (MQL5 extension): WEAK verdicts are
      // vetoed before the sizer runs, and WAIT verdicts must never be sized.
      if(m_veto_weak &&
         (cand.signal_strength == SIGNAL_WEAK_BUY || cand.signal_strength == SIGNAL_WEAK_SELL))
         reasons = reasons == "" ? "decision-layer WEAK verdict — only STRONG signals trade"
                   : reasons + "; decision-layer WEAK verdict — only STRONG signals trade";
      if(cand.signal_strength == SIGNAL_WAIT)
         reasons = reasons == "" ? "decision-layer WAIT verdict — no tradeable setup"
                   : reasons + "; decision-layer WAIT verdict — no tradeable setup";

      if(cand.confidence < m_min_confidence)
         reasons = reasons == "" ? "signal confidence below risk threshold"
                   : reasons + "; signal confidence below risk threshold";
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
      if(m_vol_z > PY_MAX_VOLATILITY_Z)
         reasons = reasons == "" ? "current candle volatility is statistically extreme"
                   : reasons + "; current candle volatility is statistically extreme";
      if(!exposure.CanOpen(cand.decision == DECISION_BUY ? 1 : -1))
         reasons = reasons == "" ? "exposure limit reached (netting/exposure)"
                   : reasons + "; exposure limit reached";

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

   //--- state registration (delegates; caller supplies direction for close) --
   void RegisterOpen(const int direction)
     {
      limits.RegisterOpen();
      exposure.RegisterOpen(direction);
     }

   void RegisterOutcome(const double pnl, const double return_r)
     {
      limits.RegisterOutcome(pnl, return_r);
     }

   void RegisterClose(const int direction)
     {
      limits.RegisterClose();
      exposure.RegisterClose(direction);
     }
  };

#endif // MITEMSHUB_RISK_RISKENGINE_MQH
