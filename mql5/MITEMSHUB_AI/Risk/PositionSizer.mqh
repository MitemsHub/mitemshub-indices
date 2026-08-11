//+------------------------------------------------------------------+
//| Risk/PositionSizer.mqh                                           |
//|  MITEMSHUB AI MARKET ENGINE — Phase 6 PositionSizer.             |
//|                                                                  |
//|  Two layers, both deterministic and parity-locked:               |
//|                                                                  |
//|  1. `Stake` — the Python RiskEngine's stake formula (the exact   |
//|     research-lab math the backtests use):                        |
//|       risk_budget = equity * risk_per_trade                     |
//|       quality     = clamp((conf - min_conf) / (1 - min_conf))   |
//|       stake       = max(stake_floor, risk_budget*(0.55+0.70*q)) |
//|                     * empirical_scale, capped at 1.25*risk_budget|
//|     scale <= 0.0 (paper-only, no empirical verdict) -> stake 0.  |
//|                                                                  |
//|  2. `Lots` — the plan's production conversion to MT5 volume:     |
//|       risk money per lot = |entry-stop| * tick_value / tick_size |
//|       lots = stake / risk_money_per_lot                          |
//|     floored to the symbol's volume step and clamped to           |
//|     [vol_min, vol_max] — the SymbolAdapter contract feeds these. |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_RISK_POSITIONSIZER_MQH
#define MITEMSHUB_RISK_POSITIONSIZER_MQH

#include "../Core/Constants.mqh"

//--- Python RiskEngine defaults (risk/engine.py RiskConfig) -------------------
#define PY_RISK_PER_TRADE       0.005
#define PY_STAKE_FLOOR          0.35
#define PY_STAKE_CAP_MULT       1.25
#define PY_STAKE_BASE_FRAC      0.55
#define PY_STAKE_QUALITY_FRAC   0.70

class CPositionSizer
  {
public:
   static double Clamp(const double v, const double lo, const double hi)
     {
      return(v < lo ? lo : (v > hi ? hi : v));
     }

   //--- Python-parity stake (paper $).  equity, confidence, min_confidence
   //--- 0..1; scale 0..1 (0 = paper-only); stake_floor in $.
   static double Stake(const double equity, const double risk_per_trade,
                       const double confidence, const double min_confidence,
                       const double empirical_scale, const double stake_floor)
     {
      double scale = Clamp(empirical_scale, 0.0, 1.0);
      double risk_budget = equity * MathMax(risk_per_trade, 0.0);
      if(scale <= 0.0)
         return(0.0);                       // paper-only — no empirical verdict
      double quality = (1.0 - min_confidence) > 1e-9
                       ? Clamp((confidence - min_confidence) / (1.0 - min_confidence),
                               0.0, 1.0)
                       : 0.0;
      double stake = MathMax(stake_floor,
                             risk_budget * (PY_STAKE_BASE_FRAC + PY_STAKE_QUALITY_FRAC * quality));
      stake *= scale;
      stake = MathMin(stake, risk_budget * PY_STAKE_CAP_MULT);
      return(MathMax(0.0, stake));
     }

   //--- MT5 lot conversion (production).  Spec inputs come from the
   //--- SymbolAdapter: tick_value ($ per tick per 1.0 lot), tick_size (the
   //--- price step), vol_min / vol_max / vol_step (the volume grid).
   static double Lots(const double stake, const double entry, const double stop,
                      const double tick_value, const double tick_size,
                      const double vol_min, const double vol_max,
                      const double vol_step)
     {
      if(stake <= 0.0 || entry <= 0.0)
         return(0.0);
      double dist = MathAbs(entry - stop);
      if(dist <= 0.0)
         dist = entry * 0.001;              // degenerate guard (Python parity)
      if(tick_value <= 0.0 || tick_size <= 0.0)
         return(0.0);
      double risk_money_per_lot = dist * tick_value / tick_size;
      if(risk_money_per_lot <= 0.0)
         return(0.0);
      double raw = stake / risk_money_per_lot;
      double step = (vol_step > 0.0) ? vol_step : 0.01;
      double floored = MathFloor(raw / step + 1e-9) * step;   // never round UP
      return(Clamp(floored, vol_min, vol_max));
     }
  };

#endif // MITEMSHUB_RISK_POSITIONSIZER_MQH
