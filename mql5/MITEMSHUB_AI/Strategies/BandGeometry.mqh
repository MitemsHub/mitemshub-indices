//+------------------------------------------------------------------+
//|                                    Strategies/BandGeometry.mqh   |
//|  MITEMSHUB AI MARKET ENGINE — band geometry (zero-drawdown).     |
//|  ★ ACTIVE strategy — port of Python `band_geometry.py` (the      |
//|  shared live/backtest level geometry) plus the `vol_band.py`     |
//|  entry gates (z-extension fade, vol-extension, drift cooldown).  |
//|                                                                  |
//|  WHY THE GEOMETRY IS HONEST: the calibrated EGARCH forecast says |
//|  price ranges `σ_h` over the hold horizon, so levels derived     |
//|  from it are ones the market actually reaches:                   |
//|    stop   = entry ∓ stop_sigma_mult   × σ_h  (tight invalidation |
//|             — being wrong is cheap, the trade dies the moment    |
//|             price leaves the band)                               |
//|    target = entry ± target_sigma_mult × σ_h  (reachable — inside |
//|             the band)                                            |
//|  with σ_h = σ_per_bar × sqrt(bars), bars = hold / bar_sec.       |
//|                                                                  |
//|  A wrong call costs ~0.20σ_h instead of the 6% stops the SMC     |
//|  sniper used; the breakeven trail converts early drift-outs into |
//|  ~0R exits instead of -1R.                                       |
//|                                                                  |
//|  NOTE: the EGARCH forecaster itself stays in Python (the        |
//|  research lab); this module receives σ_per_bar / prev_sigma /    |
//|  the price EMA as inputs and reproduces the exact level math,    |
//|  entry gates, and trail decisions.                               |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_BANDGEOMETRY_MQH
#define MITEMSHUB_STRATEGIES_BANDGEOMETRY_MQH

#include "../Core/Constants.mqh"

class CBandGeometry
  {
public:
   struct BandLevels
     {
      double   stop_loss;
      double   take_profit;
      double   reward_risk;
      double   horizon_sigma;   // log-return σ over the hold horizon
      int      hold_sec;
     };

   //--- σ_h = σ_per_bar × sqrt(bars).  bars = round(hold/bar_sec), min 1.
   //--- NOTE: Python's round() is banker's rounding; MathRound is half-away.
   //--- For the supported holds (1h/2h/3h on 300s bars → 12/24/36) both agree
   //--- exactly; non-integer bar counts are out of the supported envelope.
   static double HorizonSigma(const double sigma_per_bar, const int bar_sec,
                              const int hold_sec)
     {
      int bars = MathMax(1, (int)MathRound((double)hold_sec / MathMax(1, bar_sec)));
      return(sigma_per_bar * MathSqrt((double)bars));
     }

   //--- Exact port of Python band_levels().  direction: +1 buy, -1 sell.
   //--- Returns false (stand aside) whenever the geometry is not tradeable —
   //--- callers must NEVER fall back to unreachable SMC levels.
   static bool ComputeLevels(const double entry, const int direction,
                             const double sigma_per_bar, const int bar_sec,
                             const int hold_sec, const double stop_sigma_mult,
                             const double target_sigma_mult, const double min_target_rr,
                             const double max_stop_pct, BandLevels &out)
     {
      if(entry <= 0.0 || !MathIsValidNumber(entry))
         return(false);
      if(sigma_per_bar <= 0.0 || !MathIsValidNumber(sigma_per_bar))
         return(false);
      if(direction != 1 && direction != -1)
         return(false);
      if(hold_sec <= 0)
         return(false);

      double sigma_h = HorizonSigma(sigma_per_bar, bar_sec, hold_sec);
      if(sigma_h <= 0.0 || !MathIsValidNumber(sigma_h))
         return(false);

      double stop_dist   = stop_sigma_mult * sigma_h;
      double target_dist = target_sigma_mult * sigma_h;
      if(stop_dist <= 0.0 || target_dist <= 0.0)
         return(false);

      double stop_loss, take_profit;
      if(direction > 0)
        {
         stop_loss   = entry * (1.0 - stop_dist);
         take_profit = entry * (1.0 + target_dist);
        }
      else
        {
         stop_loss   = entry * (1.0 + stop_dist);
         take_profit = entry * (1.0 - target_dist);
        }

      double rr = target_dist / stop_dist;
      if(rr < min_target_rr)
         return(false);
      if(MathAbs(entry - stop_loss) / entry > max_stop_pct)
         return(false);
      if(direction > 0)
        {
         if(!(0.0 < stop_loss && stop_loss < take_profit))
            return(false);
        }
      else
        {
         if(!(take_profit < stop_loss))
            return(false);
        }

      out.stop_loss     = stop_loss;
      out.take_profit   = take_profit;
      out.reward_risk   = rr;
      out.horizon_sigma = sigma_h;
      out.hold_sec      = hold_sec;
      return(true);
     }

   //--- Vol-extension gate: the PREVIOUS bar's forecast sigma must exceed
   //--- ratio × the sigma baseline (the market just expanded).
   static bool VolExtended(const double prev_sigma, const double sigma_ema,
                           const double ratio)
     {
      return(prev_sigma > ratio * sigma_ema);
     }

   //--- z-extension fade direction: +1 buy (close far BELOW the EMA), -1 sell
   //--- (close far ABOVE the EMA), 0 none.  z = ln(close/ema) / prev_sigma.
   static int EntryDirection(const double z_dev, const double z_entry)
     {
      if(z_dev >= z_entry)
         return(-1);   // faded extension above → sell
      if(z_dev <= -z_entry)
         return(1);    // faded extension below → buy
      return(0);
     }

   //--- Exact port of the Python confidence formula (clamped 0.95).
   static double Confidence(const double z_dev, const double z_entry)
     {
      double az = MathAbs(z_dev);
      double bump = MathMin(0.35, az / (z_entry * 3.0));
      double c = 0.55 + bump;
      if(c > 0.95)
         c = 0.95;
      return(c);
     }

   //--- Breakeven trail (BreakevenTrailBroker): MFE in R units, updated per
   //--- bar as max(prev, current); arms once MFE ≥ frac × planned RR.
   static double UpdateMFE(const int direction, const double entry,
                           const double high, const double low,
                           const double prev_mfe, const double risk_distance)
     {
      double risk = risk_distance > 0.0 ? risk_distance : entry * 0.001;
      double mfe;
      if(direction > 0)
         mfe = (high - entry) / risk;
      else
         mfe = (entry - low) / risk;
      return(mfe > prev_mfe ? mfe : prev_mfe);
     }

   static bool TrailArmed(const double mfe_r, const double frac,
                          const double planned_rr)
     {
      return(frac > 0.0 && mfe_r >= frac * planned_rr);
     }

   static double EffectiveStop(const bool trail_armed, const double entry,
                               const double stop_loss)
     {
      return(trail_armed ? entry : stop_loss);
     }
  };

#endif // MITEMSHUB_STRATEGIES_BANDGEOMETRY_MQH
