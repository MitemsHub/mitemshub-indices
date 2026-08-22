//+------------------------------------------------------------------+
//|                                    Strategies/BandGeometry.mqh   |
//|  MITEMSHUB AI MARKET ENGINE — band geometry (zero-drawdown).     |
//|  ★ ACTIVE strategy — port of Python `band_geometry.py` (the      |
//|  shared live/backtest level geometry) plus the `vol_band.py`     |
//|  entry gates (z-extension fade, vol-extension, drift cooldown).  |
//|                                                                  |
//|  WHY THE GEOMETRY IS HONEST: the calibrated EGARCH forecast says |
//|  price ranges `sigma_h` over the hold horizon, so levels derived |
//|  from it are ones the market actually reaches:                   |
//|    stop   = entry -+ stop_sigma_mult   x sigma_h  (tight invalidation |
//|             — being wrong is cheap, the trade dies the moment    |
//|             price leaves the band)                               |
//|    target = entry +- target_sigma_mult x sigma_h  (reachable — inside |
//|             the band)                                            |
//|  with sigma_h = sigma_per_bar x sqrt(bars), bars = hold / bar_sec.|
//|                                                                  |
//|  A wrong call costs ~0.20 sigma_h instead of the 6% stops the SMC |
//|  sniper used; the breakeven trail converts early drift-outs into |
//|  ~0R exits instead of -1R.                                       |
//|                                                                  |
//|  NOTE: the EGARCH forecaster itself stays in Python (the        |
//|  research lab); this module receives sigma_per_bar / prev_sigma / |
//|  the price EMA as inputs and reproduces the exact level math,    |
//|  entry gates, and trail decisions.                               |
//|                                                                  |
//|  ARCHITECTURE:                                                   |
//|  This is a STATIC utility class — all methods are static and    |
//|  stateless.  The calling code (StrategyEngine) maintains state.  |
//|                                                                  |
//|  KEY FORMULAS:                                                   |
//|  - sigma_h = sigma_per_bar x sqrt(bars)                         |
//|  - stop_dist = stop_sigma_mult x sigma_h                        |
//|  - target_dist = target_sigma_mult x sigma_h                    |
//|  - z_dev = ln(close/ema) / prev_sigma                           |
//|  - confidence = 0.55 + min(0.35, |z_dev| / (z_entry x 3))     |
//|  - trail_arms when MFE_R >= trail_frac x planned_rr            |
//|                                                                  |
//|  OPTIMIZED PARAMETERS (from backtest sweep):                     |
//|    R_75: z=2.0, stop=0.10, target=1.20, trail=OFF             |
//|    R_100: z=2.0, stop=0.10, target=0.80, trail=ON (0.3)      |
//|                                                                  |
//|  BREAKEVEN TRAIL INSIGHT:                                        |
//|  The trail has OPPOSITE effects depending on target multiplier:  |
//|    - High target (1.20, RR=12:1): trail KILLS performance      |
//|    - Moderate target (0.80, RR=8:1): trail HELPS performance   |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_STRATEGIES_BANDGEOMETRY_MQH
#define MITEMSHUB_STRATEGIES_BANDGEOMETRY_MQH

#include "../Core/Constants.mqh"

//+------------------------------------------------------------------+
//| CBandGeometry                                                      |
//|                                                                    |
//| Static utility class for band geometry calculations.              |
//| All methods are static and stateless — the calling code           |
//| (StrategyEngine) maintains state.                                 |
//|                                                                    |
//| This class is the EXACT port of Python band_geometry.py +         |
//| vol_band.py.  Every formula matches the Python reference to       |
//| floating-point precision.                                         |
//|                                                                    |
//| USAGE:                                                            |
//|   CBandGeometry::BandLevels levels;                               |
//|   if(CBandGeometry::ComputeLevels(entry, +1, sigma, 300, 3600,   |
//|                                   0.10, 0.80, 2.0, 0.015, levels))|
//|     { /* use levels.stop_loss, levels.take_profit */ }           |
//+------------------------------------------------------------------+
class CBandGeometry
  {
public:
   //+--------------------------------------------------------------+
   //| BAND LEVELS OUTPUT STRUCT                                      |
   //|                                                                |
   //| Contains the computed stop loss, take profit, and metadata    |
   //| for a single band geometry trade plan.                        |
   //|                                                                |
   //| FIELDS:                                                       |
   //|   stop_loss     - stop loss price                            |
   //|   take_profit   - take profit price                          |
   //|   reward_risk   - reward:risk ratio (target_dist / stop_dist)|
   //|   horizon_sigma - log-return sigma over the hold horizon     |
   //|   hold_sec      - hold horizon in seconds                    |
   //+--------------------------------------------------------------+
   struct BandLevels
     {
      double   stop_loss;       // stop loss price
      double   take_profit;     // take profit price
      double   reward_risk;     // reward:risk ratio
      double   horizon_sigma;   // log-return sigma over the hold horizon
      int      hold_sec;        // hold horizon in seconds
     };

   //+--------------------------------------------------------------+
   //| HORIZON SIGMA CALCULATION                                      |
   //|                                                                |
   //| Scale the per-bar log-return sigma to the hold horizon.       |
   //|                                                                |
   //| FORMULA:                                                      |
   //|   sigma_h = sigma_per_bar x sqrt(bars)                       |
   //|   bars = round(hold_sec / bar_sec), min 1                     |
   //|                                                                |
   //| PYTHON PARITY NOTE:                                           |
   //| Python's round() is banker's rounding; MathRound is half-away.|
   //| For the supported holds (1h/2h/3h on 300s bars -> 12/24/36) |
//|   both agree exactly; non-integer bar counts are out of the     |
//|   supported envelope.                                           |
//|                                                                |
//| PARAMS:                                                       |
//|   sigma_per_bar - per-bar log-return standard deviation       |
//|   bar_sec       - bar duration in seconds                     |
//|   hold_sec      - hold horizon in seconds                     |
//| RETURN: sigma over the hold horizon (>= 0)                    |
   //+--------------------------------------------------------------+
   static double HorizonSigma(const double sigma_per_bar, const int bar_sec,
                              const int hold_sec)
     {
      int bars = MathMax(1, (int)MathRound((double)hold_sec / MathMax(1, bar_sec)));
      return(sigma_per_bar * MathSqrt((double)bars));
     }

   //+--------------------------------------------------------------+
   //| COMPUTE BAND LEVELS (exact port of Python band_levels())      |
   //|                                                                |
   //| Computes zero-drawdown stop/target from the forecast band.    |
   //| Returns false (stand aside) whenever the geometry is not      |
   //| tradeable — callers must NEVER fall back to unreachable SMC   |
   //| levels.                                                       |
   //|                                                                |
   //| FORMULAS:                                                     |
   //|   sigma_h = HorizonSigma(sigma_per_bar, bar_sec, hold_sec)  |
   //|   stop_dist = stop_sigma_mult x sigma_h                      |
   //|   target_dist = target_sigma_mult x sigma_h                  |
   //|   long:  stop = entry x (1 - stop_dist)                     |
   //|          target = entry x (1 + target_dist)                 |
   //|   short: stop = entry x (1 + stop_dist)                     |
   //|          target = entry x (1 - target_dist)                 |
   //|   rr = target_dist / stop_dist                               |
   //|                                                                |
   //| VALIDATION (returns false):                                   |
   //|   - entry <= 0 or not finite                                 |
   //|   - sigma_per_bar <= 0 or not finite                         |
   //|   - direction not +1/-1                                      |
   //|   - hold_sec <= 0                                            |
   //|   - sigma_h <= 0 or not finite                               |
   //|   - stop_dist or target_dist <= 0                            |
   //|   - rr < min_target_rr                                       |
   //|   - |entry - stop| / entry > max_stop_pct                   |
   //|   - invalid level ordering (stop >= entry for long, etc.)    |
   //|                                                                |
//| PARAMS:                                                       |
//|   entry             - entry price                            |
//|   direction         - +1 buy, -1 sell                        |
//|   sigma_per_bar     - per-bar log-return standard deviation  |
//|   bar_sec           - bar duration in seconds                |
//|   hold_sec          - hold horizon in seconds                |
//|   stop_sigma_mult   - stop distance as multiple of sigma_h   |
//|   target_sigma_mult - target distance as multiple of sigma_h |
//|   min_target_rr     - minimum reward:risk to accept          |
//|   max_stop_pct      - max stop as fraction of price          |
//|   out               - output: computed band levels           |
//| RETURN: true if levels are tradeable, false to stand aside   |
   //+--------------------------------------------------------------+
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

   //+--------------------------------------------------------------+
   //| VOL-EXTENSION GATE                                             |
   //|                                                                |
   //| The PREVIOUS bar's forecast sigma must exceed ratio x sigma    |
   //| baseline (the market just expanded).                          |
   //|                                                                |
   //| This gates entries to high-volatility regimes only.           |
   //| When vol is expanding, mean-reversion setups have higher      |
   //| probability of reaching their targets.                        |
   //|                                                                |
   //| FORMULA:                                                      |
   //|   return prev_sigma > ratio x sigma_ema                      |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   prev_sigma - previous bar's forecast sigma                 |
   //|   sigma_ema  - sigma baseline EMA                            |
   //|   ratio      - expansion threshold (default 1.3)            |
   //| RETURN: true when volatility is extended                     |
   //+--------------------------------------------------------------+
   static bool VolExtended(const double prev_sigma, const double sigma_ema,
                           const double ratio)
     {
      return(prev_sigma > ratio * sigma_ema);
     }

   //+--------------------------------------------------------------+
   //| Z-EXTENSION FADE DIRECTION                                     |
   //|                                                                |
   //| Determines the fade direction based on z-deviation from EMA.  |
   //| When price is extended ABOVE the EMA, fade with a SHORT.      |
   //| When price is extended BELOW the EMA, fade with a LONG.       |
   //|                                                                |
   //| FORMULA:                                                      |
   //|   z_dev = ln(close/ema) / prev_sigma                        |
   //|   if z_dev >= z_entry: return -1 (sell — faded above)        |
   //|   if z_dev <= -z_entry: return +1 (buy — faded below)       |
   //|   else: return 0 (no entry)                                  |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   z_dev   - current z-deviation from EMA                    |
   //|   z_entry - minimum |z_dev| to trigger entry (default 2.0)  |
   //| RETURN: +1 buy, -1 sell, 0 no entry                         |
   //+--------------------------------------------------------------+
   static int EntryDirection(const double z_dev, const double z_entry)
     {
      if(z_dev >= z_entry)
         return(-1);   // faded extension above -> sell
      if(z_dev <= -z_entry)
         return(1);    // faded extension below -> buy
      return(0);
     }

   //+--------------------------------------------------------------+
   //| CONFIDENCE FORMULA (exact port of Python)                      |
   //|                                                                |
   //| Computes signal confidence from z-deviation.  Higher |z|      |
   //| means stronger signal (more extended = more likely to revert).|
   //|                                                                |
   //| FORMULA:                                                      |
   //|   confidence = 0.55 + min(0.35, |z_dev| / (z_entry x 3))   |
   //|   clamped to max 0.95                                         |
   //|                                                                |
   //| RANGE:                                                        |
   //|   - Minimum: 0.55 (at z_dev = 0)                             |
   //|   - Maximum: 0.95 (at |z_dev| >= z_entry x 1.05)           |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   z_dev   - current z-deviation from EMA                    |
   //|   z_entry - entry threshold (used in normalization)         |
   //| RETURN: confidence value (0.55 - 0.95)                       |
   //+--------------------------------------------------------------+
   static double Confidence(const double z_dev, const double z_entry)
     {
      double az = MathAbs(z_dev);
      double bump = MathMin(0.35, az / (z_entry * 3.0));
      double c = 0.55 + bump;
      if(c > 0.95)
         c = 0.95;
      return(c);
     }

   //+--------------------------------------------------------------+
   //| UPDATE MFE (Max Favorable Excursion)                           |
   //|                                                                |
   //| Tracks the best unrealized profit in R units.  Updated per   |
   //| bar as max(prev, current).                                    |
   //|                                                                |
   //| FORMULA:                                                      |
   //|   risk = risk_distance > 0 ? risk_distance : entry x 0.001  |
   //|   long:  mfe = (high - entry) / risk                        |
   //|   short: mfe = (entry - low) / risk                          |
   //|   return max(prev_mfe, mfe)                                  |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   direction      - +1 long, -1 short                        |
   //|   entry          - entry price                               |
   //|   high           - bar high price                            |
   //|   low            - bar low price                             |
   //|   prev_mfe       - previous MFE in R units                  |
   //|   risk_distance  - |entry - stop| in price units            |
   //| RETURN: updated MFE in R units (positive = favorable)       |
   //+--------------------------------------------------------------+
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

   //+--------------------------------------------------------------+
   //| BREAKEVEN TRAIL ARMENT CHECK                                   |
   //|                                                                |
   //| Determines if the breakeven trail should be armed.            |
   //| The trail arms when MFE in R units reaches the threshold:     |
   //|   mfe_r >= frac x planned_rr                                  |
   //|                                                                |
   //| For default frac=0.3 and a 4R trade:                         |
   //|   trail arms at MFE >= 1.2R                                   |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   mfe_r      - MFE in R units (positive = favorable)        |
   //|   frac       - fraction of planned RR to arm trail           |
   //|   planned_rr - planned reward:risk ratio                    |
   //| RETURN: true when trail should be armed                      |
   //+--------------------------------------------------------------+
   static bool TrailArmed(const double mfe_r, const double frac,
                          const double planned_rr)
     {
      return(frac > 0.0 && mfe_r >= frac * planned_rr);
     }

   //+--------------------------------------------------------------+
   //| EFFECTIVE STOP LOSS PRICE                                      |
   //|                                                                |
   //| When the breakeven trail is armed, the effective stop is      |
   //| the entry price (breakeven).  Otherwise, it is the original   |
   //| stop loss.                                                     |
   //|                                                                |
   //| PARAMS:                                                       |
   //|   trail_armed - true when breakeven trail is active          |
   //|   entry       - position entry price                        |
   //|   stop_loss   - original stop loss price                    |
   //| RETURN: effective stop price (entry if trail armed, else stop)|
   //+--------------------------------------------------------------+
   static double EffectiveStop(const bool trail_armed, const double entry,
                               const double stop_loss)
     {
      return(trail_armed ? entry : stop_loss);
     }
  };

#endif // MITEMSHUB_STRATEGIES_BANDGEOMETRY_MQH
