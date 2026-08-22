//+------------------------------------------------------------------+
//|                                 Market/GarchForecaster.mqh       |
//|  MITEMSHUB AI MARKET ENGINE — EGARCH(1,1) variance forecaster.   |
//|                                                                  |
//|  Extracted verbatim from Tests/BandBackTests.mq5 (EgarchUpdate)  |
//|  so the production EA does not depend on a test suite.  Two      |
//|  modes:                                                          |
//|    0 = online-SGD — faithful port of Python models/garch.py      |
//|        EGARCHVarianceForecaster (the estimator backtest-vol      |
//|        uses; degenerate on this data, kept for A/B parity).      |
//|    1 = calibrated-fixed (DEFAULT) — the SAME recursion with      |
//|        FIXED market-calibrated parameters (data/garch_calibration|
//|        /r_75.json: omega=-1.115, alpha=0.077, gamma=0.011,       |
//|        beta=0.918 — long-run sigma ~0.115%/bar, 138-bar half-    |
//|        life).  Parameters are never mutated; only the recursion  |
//|        runs.  This is the production estimator.                 |
//|                                                                  |
//|  Convention (locked by Tests/Phase10Tests.mq5 against Python):   |
//|    - buffer-initialized log-variance at 50 observations          |
//|    - sigma = exp(log_var/2) = sqrt(long_run_variance) during     |
//|      the <30-observation warmup (Update returns false, sigma     |
//|      nonzero) — identical to Python _default_features()          |
//|    - log_var clamped to [-30, 5]; sigma never 0 after update     |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_MARKET_GARCHFORECASTER_MQH
#define MITEMSHUB_MARKET_GARCHFORECASTER_MQH

#include "../Core/Constants.mqh"

#define GARCH_WARMUP_OBSERVATIONS 30   // Python min_observations: sigma = sqrt(long_run_variance) below this
#define GARCH_BUFFER_OBSERVATIONS 50   // log-variance initialized from the first 50 returns
#define GARCH_RETURN_BUF_SIZE     50

class CGarchForecaster
  {
private:
   int    m_mode;                       // 0 = online-SGD (Python port), 1 = calibrated fixed
   double m_omega, m_alpha, m_gamma, m_beta;   // EGARCH params (mutated only in mode 0)
   double m_log_var;                    // log conditional variance (clamped [-30, 5])
   int    m_observations;
   double m_gsq_omega, m_gsq_alpha, m_gsq_gamma, m_gsq_beta;  // RMSProp grad-sq EMA
   double m_ez;                         // E|z| for the normal distribution
   int    m_buf_n;
   double m_return_buf[GARCH_RETURN_BUF_SIZE];
   double m_last_z;                     // z_t of the most recent recursion (Python _z_history feed)

   double ClampVal(const double v, const double lo, const double hi) const
     {
      return(v < lo ? lo : (v > hi ? hi : v));
     }

public:
   //--- mode 0 ignores omega/alpha/gamma/beta (uses the Python forecaster
   //--- defaults, matching GARCHState); mode 1 uses the calibrated inputs.
   CGarchForecaster(const int mode = 1,
                    const double omega = -1.115,
                    const double alpha = 0.077,
                    const double gamma = 0.011,
                    const double beta  = 0.918)
     {
      m_mode = (mode == 0) ? 0 : 1;
      if(m_mode == 0)
        {
         m_omega = -2.0;   // Python GARCHState defaults
         m_alpha = 0.10;
         m_gamma = -0.05;
         m_beta  = 0.85;
        }
      else
        {
         m_omega = omega;
         m_alpha = alpha;
         m_gamma = gamma;
         m_beta  = beta;
        }
      Reset();
     }

   void Reset()
     {
      m_log_var      = -7.824046010856292;   // MathLog(0.0004) — the Python constructor's
      //                                       // long_run_var_prior override of the dataclass default
      m_observations = 0;
      m_gsq_omega    = 1e-6;
      m_gsq_alpha    = 1e-6;
      m_gsq_gamma    = 1e-6;
      m_gsq_beta     = 1e-6;
      m_ez           = 0.7979;   // E|z| for the normal distribution
      m_buf_n        = 0;
      m_last_z       = 0.0;
      ArrayInitialize(m_return_buf, 0.0);
     }

   //--- Python parity seed: VolBandStrategy does
   //---   self.forecaster.state = replace(garch_state, observations=0)
   //--- i.e. mode 0 (online-SGD) starting from the CALIBRATED params with
   //--- log_variance = log(1e-6) = -13.8 (CalibrationResult.to_garch_state)
   //--- and a fresh observation counter.  This is the P10-A aligned path.
   void SeedCalibrated(const double omega, const double alpha,
                       const double gamma, const double beta)
     {
      m_mode   = 0;          // online-SGD from the calibrated priors
      m_omega  = omega;
      m_alpha  = alpha;
      m_gamma  = gamma;
      m_beta   = beta;
      Reset();
      m_log_var = -13.8;     // log(1e-6) — the Python to_garch_state() seed
     }

   //--- Port of EGARCHVarianceForecaster.update(log_return).  Returns false
   //--- (with sigma = sqrt(long_run_variance) = exp(log_var/2)) during the
   //--- <30-observation warmup, exactly like Python _default_features().
   bool Update(const double log_return, double &sigma_out)
     {
      m_observations++;
      if(m_observations <= GARCH_BUFFER_OBSERVATIONS)
        {
         m_return_buf[m_buf_n++] = log_return;
         if(m_observations < GARCH_WARMUP_OBSERVATIONS)
           {
            sigma_out = MathExp(m_log_var / 2.0);
            return(false);
           }
         if(m_observations == GARCH_BUFFER_OBSERVATIONS)
           {
            double msq = 0.0;
            for(int i = 0; i < GARCH_BUFFER_OBSERVATIONS; i++)
               msq += m_return_buf[i] * m_return_buf[i];
            m_log_var = MathLog(MathMax(msq / (double)GARCH_BUFFER_OBSERVATIONS, 1e-10));
           }
         // obs 30..50 fall through to the recursion (Python does not return
         // here either) — with the initial log-variance until obs 50
        }
      double sigma_t = MathExp(ClampVal(m_log_var, -30.0, 5.0) / 2.0);
      double z_t = log_return / MathMax(sigma_t, 1e-10);
      m_last_z = z_t;
      double shock = MathAbs(z_t) - m_ez;
      double log_var_new = m_omega + m_alpha * shock + m_gamma * z_t + m_beta * m_log_var;
      if(m_mode == 0)
        {
         // online-SGD mode (faithful Python backtest port): mutate omega/
         // alpha/gamma per bar with RMSProp; beta only via the persistence
         // soft-cap.
         double persistence = m_beta + m_alpha * (1.0 - m_gamma * m_gamma / 2.0);
         double new_beta = m_beta;
         if(persistence > 0.999)
            new_beta = m_beta * 0.999 / persistence;
         double realized = 2.0 * MathLog(MathMax(MathAbs(log_return), 1e-12));
         double pred_err = realized - m_log_var;
         double g_om = pred_err;
         double g_al = pred_err * shock;
         double g_ga = pred_err * z_t;
         double g_be = pred_err * m_log_var;
         m_gsq_omega = 0.99 * m_gsq_omega + 0.01 * g_om * g_om;
         m_gsq_alpha = 0.99 * m_gsq_alpha + 0.01 * g_al * g_al;
         m_gsq_gamma = 0.99 * m_gsq_gamma + 0.01 * g_ga * g_ga;
         m_gsq_beta  = 0.99 * m_gsq_beta  + 0.01 * g_be * g_be;
         double lr = 0.01;
         m_omega += (lr / (MathSqrt(m_gsq_omega) + 1e-8)) * g_om;
         m_alpha = ClampVal(m_alpha + (lr / (MathSqrt(m_gsq_alpha) + 1e-8)) * g_al, 0.0, 0.5);
         m_gamma = ClampVal(m_gamma + (lr / (MathSqrt(m_gsq_gamma) + 1e-8)) * g_ga, -0.5, 0.5);
         // Python quirk (faithful): the beta gradient is computed and
         // accumulated into _grad_sq_ema["beta"] but NEVER applied — beta is
         // only the soft-capped value, clamped to [0.0, 0.999].
         m_beta = MathMax(0.0, MathMin(new_beta, 0.999));
        }
      // calibrated-fixed mode (default): params never mutated — the recursion
      // runs with the market-calibrated parameters (the production estimator)
      m_log_var = ClampVal(log_var_new, -30.0, 5.0);
      sigma_out = MathExp(m_log_var / 2.0);
      return(true);
     }

   //--- Current conditional volatility exp(log_var/2) without updating.
   double Sigma() const        { return(MathExp(m_log_var / 2.0)); }
   double LogVar() const       { return(m_log_var); }
   int    Observations() const { return(m_observations); }
   int    Mode() const         { return(m_mode); }
   //--- z_t of the most recent recursion (Python _z_history / garch_z_score feed)
   double LastZ() const        { return(m_last_z); }
  };
#endif
