//+------------------------------------------------------------------+
//|                                    Tests/BandBacktest.mq5        |
//|  MITEMSHUB AI MARKET ENGINE — first tester backtest of the       |
//|  Phase-4 BandGeometry leg on SYN75 real ticks.                   |
//|                                                                  |
//|  Streams the tester's M5 bars through the vol-band strategy with |
//|  Python vol_band.py semantics:                                  |
//|    sigma      EGARCH(1,1) in two modes: mode 0 = faithful port of  |
//|               the Python online-SGD forecaster (models/garch.py;   |
//|               RMSProp SGD on omega/alpha/gamma, persistence soft-  |
//|               cap — the estimator backtest-vol uses, degenerate on |
//|               this data); mode 1 (default) = the SAME recursion    |
//|               with the calibrated R_75 FIXED parameters as inputs  |
//|               (omega/alpha/gamma/beta never mutated — the          |
//|               production estimator, sane long-run sigma).          |
//|    baseline   EMA(30) of garch_sigma                            |
//|    drift      ADWIN-lite: two 10-window mean shift on SIGNED     |
//|               log r*100 vs sqrt(2*ln(2/δ)/10)*pooled_std,        |
//|               δ=0.002; cooldown 10 bars after a shift (proxy).   |
//|               Signed (directional), NOT |log r|: a vol burst      |
//|               trips |log r| on the same bars the vol-extension   |
//|               gate opens — the two gates must be orthogonal,     |
//|               or the band can never enter (see 6-month diag)     |
//|    gates      prev_sigma > 1.3 x baseline AND |z| >= 1.0 fade    |
//|    levels     stop 0.20σ_h / target 0.80σ_h / 1h hold (σ_h =     |
//|               prev_sigma*sqrt(hold/bar_sec)), min RR 2.0         |
//|    trail      stop -> entry once MFE >= 0.3 x planned RR         |
//|  Execution mirrors the Python PaperBroker: entry at the signal   |
//|  candle's close, stop-first intrabar checks on subsequent bars,  |
//|  expiry at epoch+horizon (exit at close), single position at a   |
//|  time.  Data gaps re-anchor the baselines (no fake vol shocks).  |
//|                                                                  |
//|  Phase-5 decision layer: every signal is scored (ScoringEngine   |
//|  composite) and gated (ConfidenceEngine strong/weak/wait) at     |
//|  entry; each trade carries the verdict, and the report splits    |
//|  expectancy by confidence bucket so "do higher-confidence        |
//|  trades outperform?" is answered per the plan's analytics spec.  |
//|                                                                  |
//|  Stage-3 empirical floor gate: every entry is annotated with the |
//|  walk-forward gate state (still_learning / proven / suppressed)  |
//|  from the TradeQualityEngine journal — only outcomes resolved    |
//|  strictly before the bar decide, against the per-geometry        |
//|  break-even floor 1/(1+avg planned RR)+margin.  The report       |
//|  splits kept vs suppressed expectancy, exactly like the Python   |
//|  backtest-gate, so "does the empirical floor filter improve      |
//|  call quality?" is answered per the plan's analytics spec.       |
//|                                                                  |
//|  Discriminating confidence buckets: the band's z_entry and       |
//|  stop/target sigma multipliers are drawn per signal from a       |
//|  seeded sweep (MathSrand(InpGeomSeed)), so RR and setup quality  |
//|  genuinely differ across trades.  Setup quality is EDGE DEPTH    |
//|  (|z|/z_entry) — the band's own Confidence() floors at ~0.88 for |
//|  every gated signal (|z| >= z_entry by the gate), which is why   |
//|  the buckets were uniformly STRONG before — so marginal fades    |
//|  score low and deep extensions score high, and the report        |
//|  answers whether the STRONG bucket outperforms the WEAK bucket.  |
//|                                                                  |
//|  Reports: trade count, hit rate, expectancy R (gross and with    |
//|  0.05R / 0.10R per-trade costs), profit factor, max drawdown R,  |
//|  a per-direction breakdown, and the confidence-bucket split.     |
//|  Verdict: SUITE PASSED when the measurement completes with >=    |
//|  InpMinTrades closed trades.                                     |
//+------------------------------------------------------------------+
#property strict
#property copyright "Synthetic Indices Bot"
#property version   "1.00"
#property description "BandGeometry first tester backtest — SYN75 M5 real ticks"

#include "../Core/Constants.mqh"
#include "../Core/Config.mqh"
#include "../Core/StateManager.mqh"
#include "../Strategies/BandGeometry.mqh"
#include "../Decision/ScoringEngine.mqh"
#include "../Decision/ConfidenceEngine.mqh"
#include "../Decision/TradeQualityEngine.mqh"

input int    InpMinTrades       = 10;    // SUITE FAILED if fewer closed trades
input double InpZEntry          = 1.0;
input double InpVolGateRatio    = 1.10;  // re-based for the calibrated-fixed estimator:
//   1.3 + smooth calibrated sigma crosses on ~0.8% of bars and yielded 1 trade
//   in 6 months; 1.10 (8.5% of bars on the corpus) gives a measurable sample.
input int    InpEmaPeriod       = 20;
input int    InpSigmaEmaPeriod  = 30;
input int    InpSessionHourStart = 0;  // UTC session-hour gate: only enter when the bar's UTC hour
                                        // is in [start, end) — the sniper's proven hour edge (UTC
                                        // 12-24h).  0/24 = OFF (default — preserves the baseline).
input int    InpSessionHourEnd   = 24;
input double InpMaxRangeZ        = 0.0; // entry filter: |range_z_50| — z of the current M5 range vs
                                        // the prior-50 range window (population std, current bar
                                        // included — faithful to indicators.py zscore) — must be <
                                        // this.  0 = OFF (default).  Python combo: 1.0 (UTC
                                        // 12-24h & |range_z_50| < 1.0).
input double InpMaxGarchZ        = 0.0; // entry filter: |garch_z_score| — the entry bar's log-return
                                        // over the conditional EGARCH sigma updated WITH that return
                                        // (Python arch_garch.update: z_score = log_return /
                                        // current_sigma) — must be < this.  0 = OFF (default).
                                        // Python svcap combo: 1.5 (UTC 12-24h & |range_z|<1.0 &
                                        // |garch_z|<=1.5, time-exit — the best balanced cell:
                                        // +0.160R net@0.05 on the 13-day corpus).
input int    InpWarmupCandles   = 60;  input int    InpDriftCooldown   = 10;
  input bool   InpDriftGate        = false; // ADWIN regime-transition veto: OFF by default — a
                                            // vol burst IS the band's entry signal, so the veto
                                            // blocks the band's entire firing base (measured: 2899
                                            // vol crossings, 1 drift-clear, 1 entry on the 6-month
                                            // window). Enable only for research on the veto effect.
input double InpDriftDelta      = 0.002;
input double InpStopSigmaMult   = 0.20;
input double InpTargetSigmaMult = 0.60; // sweep winner (§50): 3.0 x stop.  The RR sweep on the 6-month
//   window (hit vs break-even floor): RR 1.0 hit 38.5% vs floor 55% (gap -16.5);
//   RR 1.2 39.2% vs 50.5% (-11.3); RR 2.0 32.5% vs 38.3% (-5.8, exp -0.026R);
//   RR 3.0 26.0% vs 30.0% (-4.0, exp +0.042R gross — the ONLY positive cell);
//   RR 3.5 23.1% vs 27.2% (-4.1).  The gap bottoms at ~-4 points at RR 3.0-3.5;
//   RR 3.0 is adopted as the default (closest to floor-clearing AND positive
//   gross expectancy).  Trail OFF — see InpTrailFrac.
input int    InpHoldSec         = 3600;
input int    InpExitMode        = 0;     // exit policy: 0 = TARGET (stop/target/expiry — the default),
                                          // 1 = TIME (Python time-exit port: exit at the 1R stop or the
                                          // hold-horizon close, target ignored entirely — mirrors the
                                          // harness TimeExitCapturePaperBroker).  TIME mode also disables
                                          // the breakeven trail so the stop stays at g_stop (faithful
                                          // to the Python PaperBroker, which has no trail).
input int    InpDeadExitBars    = 0;     // dead-trade time exit: exit at close once the position has
                                          // been open this many M5 bars with MFE < InpDeadExitMfeR
                                          // (0 = OFF).  Experiment: do deep-extension fades that never
                                          // show favorable excursion bleed to -1R slower than shallow?
                                          // Exiting them early cuts the tail if so.
input double InpDeadExitMfeR    = 0.40;   // MFE (R) threshold for the dead-trade exit above
input double InpMinTargetRR     = 3.0;  // = derived RR (never below it — the floor gate's own math)
input double InpMaxStopPct      = 0.015;
input double InpTrailFrac       = 0.0;  // OFF (§50): with same-candle checks the trail arms at
//   frac x RR and races the target, killing the hit rate at ANY target (measured:
//   51.8% -> 1.8% hit).  WITH InpTrailClosedCandle=true the wick-scratch is gone and
//   EVERY frac turns positive — best cell frac=0.2: +0.398R gross / +0.348R net@0.05,
//   maxDD 204.8R -> 5.8R (6-month window, 2026-08-11).  Default stays 0.0 pending
//   the fresh-window confirmation; flip via -Inputs InpTrailFrac=0.2.
input bool   InpTrailClosedCandle = true; // closed-candle grace on the trail's breakeven exit:
                                          // once armed (eff_stop == entry) a wick through entry
                                          // does NOT scratch the position — only a full M5 candle
                                          // CLOSING through entry exits it.  Same-candle wick
                                          // checks make every trail frac destroy the hit rate
                                          // (2-4% vs 40.4% at RR 1.2); the grace tests whether the
                                          // breakeven conversion survives when jitter can't stop
                                          // out a valid runner (mirrors the Python stop-lock).
input double InpDerivedTargetRR = 3.0;  // sweep-winning target multiplier (R units) used by the geometry sweep
input int    InpFloorMinSamples = 10;    // Stage-3 gate: resolved outcomes before the floor applies
input double InpFloorMargin     = 0.05;  // Stage-3 gate: margin added to 1/(1+RR) break-even
input bool   InpGeomSweep       = true;   // per-signal geometry sweep (seeded, reproducible)
input int    InpGeomSeed        = 42;
input double InpSweepZEntryMin  = 0.7;
input double InpSweepZEntryMax  = 1.6;
input double InpSweepStopMin    = 0.15;
input double InpSweepStopMax    = 0.35;
input double InpSweepTargetMin  = 0.50;
input double InpSweepTargetMax  = 1.20;
input double InpSetupQualityMin = 0.20;   // edge depth 1.0x (marginal fade)
input double InpSetupQualityMax = 1.00;   // edge depth >= InpDepthMax
input double InpDepthMax        = 3.00;   // |z|/z_entry where setup quality saturates
input double InpMaxEdgeDepth    = 0.0;   // edge-depth cap: block entries with |z|/z_entry > this
                                          // (0.0 = OFF).  Deep-extension fades underperform the
                                          // shallow ones (measured at RR 1.2: deep STRONG bucket
                                          // drags hit 45.3% -> 39.2%); capping depth keeps the
                                          // shallow fades that carry the edge.
input int    InpGarchMode       = 1;     // 0 = online-SGD (Python backtest port), 1 = calibrated fixed params
input double InpGarchOmega      = -1.115; // calibrated R_75 EGARCH (data/garch_calibration/r_75.json)
input double InpGarchAlpha      = 0.077;
input double InpGarchGamma      = 0.011;
input double InpGarchBeta       = 0.918;

#define BAR_SEC 300

struct BandTrade
  {
   datetime open_t;
   datetime close_t;
   int      direction;
   double   entry;
   double   stop;
   double   target;
   double   mfe_r;
   double   exit_price;
   double   rr;
   int      hold_bars;
   //--- Phase-5 decision-layer verdict at entry ----------------------
   double   setup_quality;      // band Confidence(z) (0..1)
   double   composite;          // ScoreBreakdown composite (0..1)
   double   confidence;         // blended decision confidence (0..1)
   ENUM_SIGNAL_STRENGTH signal; // strong/weak/wait verdict
   //--- Stage-3 empirical floor gate state at entry ----------------------
   int    gate_state;       // GATE_STILL_LEARNING / GATE_PROVEN / GATE_SUPPRESSED
   double floor_at_entry;   // break-even floor applied at entry (0..1)
   double hit_at_entry;     // empirical hit rate at entry (0..1)
   int    samples_at_entry; // resolved outcomes at entry
   double planned_rr;       // planned reward:risk of this geometry
   double z_entry_used;     // this signal's z_entry (sweep cell)
   double z_depth;          // |z| / z_entry (edge depth, >= 1)
   //--- deep-vs-shallow profile (drawdown investigation) ------
   ENUM_EXIT_REASON exit_reason;   // stop / target / time (incl. dead-trade exit)
   double vol_ratio_entry;         // prev_sigma / sigma_ema at entry (vol regime)
   //--- equity-curve position (per-bucket drawdown attribution) ------
   double cum_r_at_open;    // global cumulative R before this trade's outcome
   double cum_r_at_close;   // global cumulative R after this trade's outcome
   //--- trail arming-to-exit path (closed-candle grace quantification) ---
   int    arm_hold_bars;     // hold bars elapsed when the trail armed (-1 = never armed)
   double arm_mfe_r;         // MFE (R) at arming
   int    dips_after_arm;    // bars after arming that wick through entry (spared by the grace)
   bool   wick_scratch_wo_grace; // any post-arm wick would have scratched at 0R (no-grace model)
   bool   hit_target_after_dip;  // exited at target AND had >= 1 spared dip (a trade the grace SAVED)
  };

BandTrade g_trades[20000];
int       g_ntrades = 0;
double    g_cumR    = 0.0;
double    g_peakR   = 0.0;
double    g_maxDD   = 0.0;

//--- strategy state
double g_sigma        = 0.0;    // EGARCH garch_sigma (current)
double g_prev_sigma   = 0.0;    // sigma from the previous bar (used in gates)
double g_sigma_ema    = 0.0;
double g_ema          = 0.0;
double g_prev_close   = 0.0;
int    g_bars_seen    = 0;
int    g_cooldown     = 0;
//--- diagnostic attrition counters (why does the gate fire so rarely?)
long   g_diag_bars     = 0;
long   g_diag_ratio110 = 0;
long   g_diag_ratio130 = 0;
long   g_diag_drift    = 0;   // drift fires (cooldown resets)
long   g_diag_driftclear_cross = 0;  // drift-clear AND ratio>1.1
long   g_diag_zpass    = 0;   // ... AND |z| >= 1.0
long   g_diag_dir0     = 0;   // ... but EntryDirection rejected (|z| < swept z_entry)
long   g_diag_lv_fail  = 0;   // ... passed EntryDirection but ComputeLevels rejected
long   g_diag_depth_fail = 0;  // ... passed ComputeLevels but blocked by the edge-depth cap
long   g_diag_conf_fail = 0;  // ... passed ComputeLevels but the decision gate blocked
int    g_diag_warmup   = 0;   // still warming up / sigma unset
int    g_diag_gap      = 0;   // gap-reanchored bars
int    g_diag_inpos    = 0;   // skipped because in a position
long   g_diag_hourskip = 0;   // skipped by the UTC session-hour gate
long   g_diag_range_skip = 0; // skipped by the |range_z_50| entry filter
long   g_diag_gz_skip    = 0; // skipped by the |garch_z_score| entry filter
long   g_utc_offset_sec = 0;  // server->UTC offset at OnInit (tester-constant; DST caveat noted in docs)
double g_range_hist[50];      // ring of the last 50 M5 ranges (range_z_50 filter)
int    g_range_head = 0;
int    g_range_cnt  = 0;
double g_diag_ratio_max = 0.0;
double   g_drift_win[20];
int      g_drift_n      = 0;
datetime g_last_bar_end = 0;

//--- EGARCH(1,1) forecaster state.  Mode 0 = faithful port of Python
//--- models/garch.py EGARCHVarianceForecaster (online SGD — the estimator
//--- backtest-vol uses; degenerate on this data, kept for A/B).  Mode 1
//--- (default) = the SAME recursion with the calibrated R_75 FIXED
//--- parameters (data/garch_calibration/r_75.json: omega=-1.115, alpha=0.077,
//--- gamma=0.011, beta=0.918 — long-run sigma ~0.115%/bar, 138-bar half-
//--- life), the production path's estimator: omega/alpha/gamma/beta are
//--- never mutated, only the recursion runs.
double g_omega      = -2.0;
double g_alpha      = 0.10;
double g_gamma      = -0.05;
double g_beta       = 0.85;
double g_log_var    = -7.824046010856292;   // MathLog(0.0004) — the forecaster
//      constructor overrides the dataclass default with long_run_var_prior
int    g_observations = 0;
double g_gsq_omega  = 1e-6;
double g_gsq_alpha  = 1e-6;
double g_gsq_gamma  = 1e-6;
double g_gsq_beta   = 1e-6;
double g_ez         = 0.7979;   // E|z| for the normal distribution
int    g_buf_n       = 0;
double g_return_buf[50];

//--- Port of EGARCHVarianceForecaster.update(log_return): buffer-initialized
//--- log-variance at 50 observations, then the EGARCH recursion with
//--- RMSProp-style online SGD on omega/alpha/gamma (beta only via the
//--- persistence soft-cap — a faithful quirk of the Python code).  Returns
//--- false (sigma 0) before 30 observations, exactly like the Python
//--- default features.
bool EgarchUpdate(const double log_return, double &sigma_out)
  {
   g_observations++;
   if(g_observations <= 50)
     {
      g_return_buf[g_buf_n++] = log_return;
      if(g_observations < 30)
        {
         // Python _default_features(): garch_sigma = sqrt(long_run_variance)
         // = exp(log_var/2) — NOT zero — during the warmup phase.
         sigma_out = MathExp(g_log_var / 2.0);
         return(false);
        }
      if(g_observations == 50)
        {
         double msq = 0.0;
         for(int i = 0; i < 50; i++)
            msq += g_return_buf[i] * g_return_buf[i];
         g_log_var = MathLog(MathMax(msq / 50.0, 1e-10));
        }
      // obs 30..50 fall through to the Phase-2 recursion (the Python code
      // does not return here) — with the initial log-variance until obs 50
     }
   double sigma_t = MathExp(Clamp(g_log_var, -30.0, 5.0) / 2.0);
   double z_t = log_return / MathMax(sigma_t, 1e-10);
   double shock = MathAbs(z_t) - g_ez;
   double log_var_new = g_omega + g_alpha * shock + g_gamma * z_t + g_beta * g_log_var;
   if(InpGarchMode == 0)
     {
      // online-SGD mode (faithful Python backtest port): mutate omega/alpha/
      // gamma per bar with RMSProp; beta only via the persistence soft-cap.
      double persistence = g_beta + g_alpha * (1.0 - g_gamma * g_gamma / 2.0);
      double new_beta = g_beta;
      if(persistence > 0.999)
         new_beta = g_beta * 0.999 / persistence;
      double realized = 2.0 * MathLog(MathMax(MathAbs(log_return), 1e-12));
      double pred_err = realized - g_log_var;
      double g_om = pred_err;
      double g_al = pred_err * shock;
      double g_ga = pred_err * z_t;
      double g_be = pred_err * g_log_var;
      g_gsq_omega = 0.99 * g_gsq_omega + 0.01 * g_om * g_om;
      g_gsq_alpha = 0.99 * g_gsq_alpha + 0.01 * g_al * g_al;
      g_gsq_gamma = 0.99 * g_gsq_gamma + 0.01 * g_ga * g_ga;
      g_gsq_beta  = 0.99 * g_gsq_beta  + 0.01 * g_be * g_be;
      double lr = 0.01;
      g_omega += (lr / (MathSqrt(g_gsq_omega) + 1e-8)) * g_om;
      g_alpha = Clamp(g_alpha + (lr / (MathSqrt(g_gsq_alpha) + 1e-8)) * g_al, 0.0, 0.5);
      g_gamma = Clamp(g_gamma + (lr / (MathSqrt(g_gsq_gamma) + 1e-8)) * g_ga, -0.5, 0.5);
      // Python quirk (faithful): the beta gradient is computed and accumulated
      // into _grad_sq_ema["beta"] but NEVER applied — beta is only the
      // soft-capped value, clamped to [0.0, 0.999].
      g_beta = MathMax(0.0, MathMin(new_beta, 0.999));
     }
   // calibrated-fixed mode (default): omega/alpha/gamma/beta are the InpGarch*
   // inputs, never mutated — the recursion runs with the market-calibrated
   // parameters (the production estimator), converging to a sane long-run
   // sigma instead of the online-SGD blowups.
   g_log_var = Clamp(log_var_new, -30.0, 5.0);
   sigma_out = MathExp(g_log_var / 2.0);
   return(true);
  }

//--- open position state
bool    g_in_pos  = false;
int     g_dir     = 0;
double  g_entry   = 0.0;
double  g_stop    = 0.0;
double  g_target  = 0.0;
double  g_mfe_r   = 0.0;
double  g_planned_rr = 0.0;
double  g_risk    = 0.0;
datetime g_opened_at = 0;
//--- trail arming path (per-position state persisted across ClosePosition calls)
bool    g_armed_prev     = false;   // trail armed on a previous bar
int     g_arm_hold       = 0;
double  g_arm_mfe        = 0.0;
int     g_dips_after_arm = 0;

//--- Phase-5 decision-layer state at the current entry -----------------------
double  g_setup_q   = 0.0;
double  g_composite = 0.0;
double  g_conf      = 0.0;
ENUM_SIGNAL_STRENGTH g_signal = SIGNAL_WAIT;

//--- Stage-3 empirical floor gate (TradeQualityEngine journal) ---------------
#define GATE_STILL_LEARNING 0
#define GATE_PROVEN         1
#define GATE_SUPPRESSED     2
CTradeQualityEngine g_journal;
int    g_gate_state     = GATE_STILL_LEARNING;
double g_floor_at_entry = 0.0;
double g_hit_at_entry   = 0.0;
int    g_samples_at_entry = 0;
double g_z_entry_used = 1.0;
double g_z_depth      = 1.0;
double g_vol_ratio_entry = 1.0;   // vol regime at the entry bar
int    g_res_n    = 0;                 // journal stats at the last entry gate
double g_res_hit  = 0.0;
double g_res_avg_rr = 0.0;
double g_res_avg_r  = 0.0;
double g_res_exp    = 0.0;
double g_res_floor  = 0.0;

double SafeDiv(const double a, const double b, const double def = 0.0)
  {
   return(MathAbs(b) < 1e-12 ? def : a / b);
  }

double Clamp(const double v, const double lo, const double hi)
  {
   return(v < lo ? lo : (v > hi ? hi : v));
  }

double RandRange(const double lo, const double hi)
  {
   if(hi <= lo)
      return(lo);
   return(lo + (hi - lo) * ((double)MathRand() / 32767.0));
  }

//--- gap re-anchor (Python _gap_reanchor): a multi-hour feed outage must not
//--- be read as one gigantic bar return poisoning the vol estimate.
bool GapReanchor(const datetime open_time, const double close)
  {
   if(g_last_bar_end > 0 && open_time > g_last_bar_end + (datetime)MathMax(3.0 * BAR_SEC, 600.0))
     {
      g_prev_close = close;      // re-anchor close/EMA baselines (Python
      g_ema        = close;      // _gap_reanchor: prev_close = ema = close)
      g_drift_n    = 0;
      g_cooldown   = 0;
      g_last_bar_end = open_time + BAR_SEC;
      return(true);
     }
   g_last_bar_end = open_time + BAR_SEC;
   return(false);
  }

//--- ADWIN-lite drift detector on SIGNED log r*100: a mean shift between the
//--- last two 10-observation halves beyond the ADWIN cut scale (δ=0.002
//--- confidence) flags a persistent DIRECTIONAL regime drift and starts the
//--- entry cooldown.  Note the detector must NOT use |log r|: a volatility
//--- burst trips a |log r| mean-shift on the same bars the vol-extension
//--- gate opens on — the two gates would veto each other and the band can
//--- never enter (measured: 2899 vol crossings, 1 drift-clear, 1 entry on
//--- the 6-month window).  Signed returns have ~0 mean, so only a sustained
//--- one-sided move fires the veto — the two gates become orthogonal.
void ObserveDrift(const double log_ret)
  {
   double v = log_ret * 100.0;
   int cap = 20;
   if(g_drift_n < cap)
     {
      g_drift_win[g_drift_n++] = v;
      if(g_drift_n < cap)
         return;
     }
   else
     {
      for(int i = 0; i < cap - 1; i++)
         g_drift_win[i] = g_drift_win[i + 1];
      g_drift_win[cap - 1] = v;
     }
   // pooled mean/std of the two halves
   double m0 = 0.0, m1 = 0.0;
   for(int i = 0; i < 10; i++)  m0 += g_drift_win[i];
   for(int i = 10; i < 20; i++) m1 += g_drift_win[i];
   m0 /= 10.0;
   m1 /= 10.0;
   double s = 0.0;
   for(int i = 0; i < 20; i++)
      s += (g_drift_win[i] - ((i < 10) ? m0 : m1)) * (g_drift_win[i] - ((i < 10) ? m0 : m1));
   double pooled_std = MathSqrt(s / 20.0);
   double thr = MathSqrt(2.0 * MathLog(2.0 / InpDriftDelta) / 10.0) * pooled_std;
   if(MathAbs(m0 - m1) > thr)
     {
      g_cooldown = 0;            // regime drift → block entries for the cooldown
      g_drift_n  = 0;            // ADWIN semantics: window resets at the cut
      g_diag_drift++;
     }
  }

//--- close the open position if stop/target/expiry hit; returns true when closed
bool ClosePosition(const double bar_open, const double high, const double low,
                   const double close, const datetime open_time,
                   double &exit_price_out, ENUM_EXIT_REASON &reason_out)
  {
   double risk = g_risk;
   double mfe = (g_dir > 0) ? (high - g_entry) / risk : (g_entry - low) / risk;
   if(mfe > g_mfe_r) g_mfe_r = mfe;
   bool trail_armed = (InpExitMode == 0)
                     && CBandGeometry::TrailArmed(g_mfe_r, InpTrailFrac, g_planned_rr);
   double eff_stop  = CBandGeometry::EffectiveStop(trail_armed, g_entry, g_stop);
   bool expired = (open_time + BAR_SEC >= g_opened_at + InpHoldSec);
   int hold_now = (int)((long)(open_time + BAR_SEC - g_opened_at) / BAR_SEC);
   //--- trail arming-to-exit path instrumentation --------------------------
   // Record the bar the trail first arms at, then count every subsequent bar
   // that WICKS through entry without closing through — each such bar would
   // have scratched the position at 0R under the old same-candle rule, and is
   // exactly what InpTrailClosedCandle spares.  (The exit bar itself counts
   // too when it closes through: the no-grace model scratches there as well.)
   if(trail_armed && !g_armed_prev)
     {
      g_arm_hold = hold_now;
      g_arm_mfe  = g_mfe_r;
      g_armed_prev = true;
     }
   else if(g_armed_prev)
     {
      if(g_dir > 0)  { if(low < g_entry) g_dips_after_arm++; }
      else           { if(high > g_entry) g_dips_after_arm++; }
     }
   bool dead = (InpDeadExitBars > 0 && hold_now >= InpDeadExitBars
                && g_mfe_r < InpDeadExitMfeR);
   bool stop_hit, target_hit;
   if(g_dir > 0)
     {
      // Closed-candle grace on the breakeven trail: once armed
      // (eff_stop == entry) only a full M5 candle CLOSING below entry
      // exits at breakeven — an intrabar wick can't scratch a valid
      // runner.  The un-armed stop and the target keep intrabar
      // stop-first semantics (mirrors the Python PaperBroker).
      if(trail_armed && InpTrailClosedCandle)
         stop_hit = (close < eff_stop);
      else
         stop_hit = (low <= eff_stop);
      target_hit = (InpExitMode == 0) && (high >= g_target);
     }
   else
     {
      if(trail_armed && InpTrailClosedCandle)
         stop_hit = (close > eff_stop);
      else
         stop_hit = (high >= eff_stop);
      target_hit = (InpExitMode == 0) && (low <= g_target);
     }
   double exit_price = close;
   ENUM_EXIT_REASON reason = EXIT_TIME;
   if(stop_hit && target_hit)       exit_price = eff_stop;   // stop-first
   else if(stop_hit)                exit_price = eff_stop;
   else if(target_hit)              exit_price = g_target;
   else if(dead || expired)         exit_price = close;       // dead-trade exit or hold expiry
   else
      return(false);
   if(stop_hit)
      reason = trail_armed ? EXIT_BREAKEVEN_TRAIL : EXIT_STOP_HIT;
   else if(target_hit)
      reason = EXIT_TARGET_HIT;
   else
      reason = EXIT_TIME;
   exit_price_out = exit_price;
   reason_out = reason;

   double rr = (g_dir > 0) ? (exit_price - g_entry) / risk : (g_entry - exit_price) / risk;
   if(g_ntrades < 20000)
     {
      BandTrade t;
      t.open_t    = g_opened_at;
      t.close_t   = open_time + BAR_SEC;
      t.direction = g_dir;
      t.entry     = g_entry;
      t.stop      = g_stop;
      t.target    = g_target;
      t.mfe_r     = g_mfe_r;
      t.exit_price = exit_price;
      t.rr        = rr;
      t.hold_bars = (int)((long)(t.close_t - t.open_t) / BAR_SEC);
      // Phase-5 decision-layer verdict captured at entry
      t.setup_quality = g_setup_q;
      t.composite     = g_composite;
      t.confidence    = g_conf;
      t.signal        = g_signal;
      // Stage-3 empirical floor-gate state captured at entry
      t.gate_state       = g_gate_state;
      t.floor_at_entry   = g_floor_at_entry;
      t.hit_at_entry     = g_hit_at_entry;
      t.samples_at_entry = g_samples_at_entry;
      t.planned_rr       = g_planned_rr;
      t.z_entry_used     = g_z_entry_used;
      t.z_depth          = g_z_depth;
      t.exit_reason      = reason;
      t.vol_ratio_entry  = g_vol_ratio_entry;
      t.cum_r_at_open    = g_cumR;      // equity position before this trade resolved
      t.cum_r_at_close   = g_cumR + rr; // equity position after it resolved
      t.arm_hold_bars    = g_armed_prev ? g_arm_hold : -1;
      t.arm_mfe_r        = g_armed_prev ? g_arm_mfe : 0.0;
      t.dips_after_arm   = g_dips_after_arm;
      t.wick_scratch_wo_grace = (g_dips_after_arm > 0);
      t.hit_target_after_dip  = (g_dips_after_arm > 0 && reason == EXIT_TARGET_HIT);
      g_trades[g_ntrades] = t;
      g_ntrades++;
     }
   g_cumR += rr;
   if(g_cumR > g_peakR) g_peakR = g_cumR;
   double dd = g_peakR - g_cumR;
   if(dd > g_maxDD) g_maxDD = dd;
   g_in_pos = false;
   g_mfe_r = 0.0;
   g_armed_prev     = false;
   g_arm_hold       = 0;
   g_arm_mfe        = 0.0;
   g_dips_after_arm = 0;
   return(true);
  }

//+------------------------------------------------------------------+
//| OnInit — load M5 bars, stream the strategy, print the verdict    |
//+------------------------------------------------------------------+
int OnInit()
  {
   Print("[BANDBT] === BandGeometry tester backtest on SYN75 M5 starting ===");
   MathSrand(InpGeomSeed);   // deterministic per-signal geometry sweep

   // --- EGARCH parameter mode -----------------------------------------
   if(InpGarchMode == 0)
     {
      Print("[BANDBT] garch mode: online-SGD (faithful Python backtest port — degenerate on this data)");
     }
   else
     {
      g_omega = InpGarchOmega;
      g_alpha = InpGarchAlpha;
      g_gamma = InpGarchGamma;
      g_beta  = InpGarchBeta;
      Print(StringFormat("[BANDBT] garch mode: calibrated-fixed (omega=%.3f alpha=%.3f gamma=%.3f beta=%.3f)",
                         g_omega, g_alpha, g_gamma, g_beta));
      Print(StringFormat("[BANDBT] gate inputs: vol_ratio=%.2f drift_gate=%s drift_cooldown=%d z_entry=%.2f geom_sweep=%s "
                         "dead_exit=%d/%s mfe_cut=%.2f exit_mode=%s session_hour=%d-%d range_z=%.2f garch_z=%.2f",
                         InpVolGateRatio, (InpDriftGate ? "ON" : "OFF"), InpDriftCooldown,
                         InpZEntry, (InpGeomSweep ? "ON" : "OFF"),
                         InpDeadExitBars, (InpDeadExitBars > 0 ? "ON" : "OFF"), InpDeadExitMfeR,
                         (InpExitMode == 0 ? "TARGET" : "TIME"), InpSessionHourStart, InpSessionHourEnd,
                         InpMaxRangeZ, InpMaxGarchZ));
      g_utc_offset_sec = (long)(TimeCurrent() - TimeGMT());
      Print(StringFormat("[BANDBT] server->UTC offset %d sec (session-hour gate uses bar_utc = bar_time - offset)",
                         (int)g_utc_offset_sec));
     }

   MqlRates rates[];
   int got = CopyRates(_Symbol, PERIOD_M5, 0, 50000, rates);
   if(got <= 0)
     {
      Print("[BANDBT] CopyRates(M5) failed, error=", GetLastError());
      Print("[BANDBT] SUITE FAILED — no M5 data in the tester");
      return(INIT_FAILED);
     }
   int n = got;
   Print(StringFormat("[BANDBT] loaded %d M5 bars on %s", n, _Symbol));
   if(n < InpWarmupCandles + 60)
     {
      Print(StringFormat("[BANDBT] not enough history: %d bars (need >= %d)", n, InpWarmupCandles + 60));
      Print("[BANDBT] SUITE FAILED — insufficient tester history");
      return(INIT_FAILED);
     }

   int n_long = 0, n_short = 0;
   double exp_long = 0.0, exp_short = 0.0;
   double alpha = 2.0 / (InpEmaPeriod + 1.0);
   double sigma_alpha = 2.0 / (InpSigmaEmaPeriod + 1.0);

   for(int k = 0; k < n; k++)
     {
      MqlRates r = rates[k];
      datetime t = r.time;
      if(g_prev_close <= 0.0)
        {
         g_prev_close = r.close;
         g_ema        = r.close;
         g_last_bar_end = t + BAR_SEC;
         continue;
        }
      if(GapReanchor(t, r.close))
        {
         g_diag_gap++;
         continue;
        }

      double log_ret = MathLog(r.close / g_prev_close);
      g_prev_close = r.close;

      // range_z_50 feed: current M5 range (high-low) into the 50-bar ring
      g_range_hist[g_range_head] = r.high - r.low;
      g_range_head = (g_range_head + 1) % 50;
      if(g_range_cnt < 50) g_range_cnt++;

      g_prev_sigma = g_sigma;                    // sigma from the previous bar
      EgarchUpdate(log_ret, g_sigma);            // faithful Python EGARCH
      g_sigma_ema = (g_sigma_ema <= 0.0) ? g_sigma
                    : g_sigma_ema * (1.0 - sigma_alpha) + g_sigma * sigma_alpha;
      g_ema = g_ema * (1.0 - alpha) + r.close * alpha;
      g_bars_seen++;
      ObserveDrift(log_ret);
      if(g_cooldown < InpDriftCooldown)
         g_cooldown++;

      // 1) close an open position FIRST (Python runner: broker then strategy)
      if(g_in_pos)
        {
         g_journal.UpdatePosition(r.high, r.low);   // feed the bar path (MAE/MFE)
         double exit_price = 0.0;
         ENUM_EXIT_REASON exit_reason = EXIT_NONE;
         if(ClosePosition(r.open, r.high, r.low, r.close, t, exit_price, exit_reason))
           {
            g_journal.ClosePosition(exit_price, exit_reason, t + BAR_SEC);
            if(g_dir > 0)
              {
               n_long++;
               exp_long += g_trades[g_ntrades - 1].rr;
              }
            else
              {
               n_short++;
               exp_short += g_trades[g_ntrades - 1].rr;
              }
           }
        }

      // 2) strategy gates on the same closed bar
      g_diag_bars++;
      double ratio_now = SafeDiv(g_prev_sigma, g_sigma_ema);
      if(ratio_now > g_diag_ratio_max) g_diag_ratio_max = ratio_now;
      if(ratio_now > 1.1) g_diag_ratio110++;
      if(ratio_now > 1.3) g_diag_ratio130++;
      if(g_in_pos)
        {
         g_diag_inpos++;
         continue;
        }
      if(g_bars_seen < InpWarmupCandles)
        {
         g_diag_warmup++;
         continue;
        }
      if(g_sigma_ema <= 0.0 || g_prev_sigma <= 0.0)
         continue;
      if(InpSessionHourStart < InpSessionHourEnd)
        {
         MqlDateTime _dt;
         TimeToStruct(t - g_utc_offset_sec, _dt);
         int hour_utc = _dt.hour;
         if(hour_utc < InpSessionHourStart || hour_utc >= InpSessionHourEnd)
           {
            g_diag_hourskip++;
            continue;
           }
        }
      if(InpMaxRangeZ > 0.0 && g_range_cnt >= 50)
        {
         double _mean = 0.0, _var = 0.0;
         for(int i = 0; i < 50; i++) _mean += g_range_hist[i];
         _mean /= 50.0;
         for(int i = 0; i < 50; i++)
           {
            double _d = g_range_hist[i] - _mean;
            _var += _d * _d;
           }
         double _sigma = MathSqrt(_var / 50.0);
         double rz = (_sigma > 0.0) ? (g_range_hist[(g_range_head + 49) % 50] - _mean) / _sigma : 0.0;
         if(MathAbs(rz) >= InpMaxRangeZ)
           {
            g_diag_range_skip++;
            continue;
           }
        }
      if(InpMaxGarchZ > 0.0)
        {
         // Python garch_z_score = log_return / current_sigma AFTER the
         // EGARCH update with the entry bar's own return (arch_garch.py
         // update(): z_score = log_return / current_sigma).  g_sigma is the
         // post-update conditional vol here — the faithful value.
         double garch_z = log_ret / MathMax(g_sigma, 1e-10);
         if(MathAbs(garch_z) >= InpMaxGarchZ)
           {
            g_diag_gz_skip++;
            continue;
           }
        }
      if(InpDriftGate && g_cooldown < InpDriftCooldown)
         continue;
      if(!(g_prev_sigma > InpVolGateRatio * g_sigma_ema))
         continue;
      if(!InpDriftGate || g_cooldown >= InpDriftCooldown)
         g_diag_driftclear_cross++;
      double z_dev_gate = MathLog(r.close / g_ema) / g_prev_sigma;
      if(MathAbs(z_dev_gate) < 1.0)
         continue;
      g_diag_zpass++;

      // --- per-signal geometry sweep (seeded): z_entry and the stop/target
      // sigma multipliers differ per trade, so RR and setup quality genuinely
      // vary across the run — the confidence buckets become discriminating.
      double z_entry = InpZEntry;
      double stop_mult = InpStopSigmaMult;
      double target_mult = InpTargetSigmaMult;
      if(InpGeomSweep)
        {
         z_entry   = RandRange(InpSweepZEntryMin, InpSweepZEntryMax);
         stop_mult = RandRange(InpSweepStopMin, InpSweepStopMax);
         // §50 sweep-winning target: RR fixed at 3.0 (the cell closest to its
         // break-even floor with positive gross expectancy) so per-signal
         // variety (z_entry, stop, depth) survives while every trade keeps
         // the tuned geometry.
         target_mult = InpDerivedTargetRR * stop_mult;
        }

      double z_dev = MathLog(r.close / g_ema) / g_prev_sigma;
      int dir = CBandGeometry::EntryDirection(z_dev, z_entry);
      if(dir == 0)
        {
         g_diag_dir0++;
         continue;
        }

      CBandGeometry::BandLevels lv;
      if(!CBandGeometry::ComputeLevels(r.close, dir, g_prev_sigma, BAR_SEC, InpHoldSec,
                                       stop_mult, target_mult, InpMinTargetRR,
                                       InpMaxStopPct, lv))
        {
         g_diag_lv_fail++;
         continue;
        }

      // --- Phase-5 decision layer: score + confidence verdict per signal ---
      // The vol gate (prev_sigma > ratio x sigma_ema) IS the band's expansion
      // regime, so current_regime = EXPANSION for every entered signal and
      // regime_score is 1.0 by construction.  The discriminating axis is
      // SETUP QUALITY = edge depth: the band's own Confidence() floors at
      // ~0.88 for every gated signal (the z gate guarantees |z| >= z_entry,
      // so |z|/(3*z_entry) >= 1/3) — which is why all 3,831 trades landed
      // in the STRONG bucket before.  Depth-based quality (marginal fade
      // ~0.2, deep extension ~1.0) spreads the blended confidence across
      // STRONG/WEAK/WAIT so the buckets can actually discriminate.
      double az = MathAbs(z_dev);
      double depth = (z_entry > 0.0) ? az / z_entry : 1.0;
      // --- edge-depth gate: block the deep-extension fades ---------------
      // Measured (RR 1.2, 6-month window): trades with depth > ~2 drag the
      // hit rate from the shallow bucket's 45.3% down to the 39.2% overall
      // — deep z-extensions revert harder than the shallow fades carry.
      if(InpMaxEdgeDepth > 0.0 && depth > InpMaxEdgeDepth)
        {
         g_diag_depth_fail++;
         continue;
        }
      g_diag_conf_fail++;  // reached the decision layer (every one enters)
      double setup_q = InpSetupQualityMin
                       + (InpSetupQualityMax - InpSetupQualityMin)
                         * Clamp((depth - 1.0) / MathMax(0.01, InpDepthMax - 1.0), 0.0, 1.0);
      g_z_entry_used = z_entry;
      g_z_depth      = depth;
      g_vol_ratio_entry = SafeDiv(g_prev_sigma, g_sigma_ema);

      StrategyCandidate cand;
      cand.strategy        = STRATEGY_BAND;
      cand.decision        = (dir > 0) ? DECISION_BUY : DECISION_SELL;
      cand.entry           = r.close;
      cand.stop_loss       = lv.stop_loss;
      cand.take_profit     = lv.take_profit;
      cand.setup_quality   = setup_q;
      cand.confidence      = setup_q;
      cand.required_regime = REGIME_EXPANSION;
      cand.reason_codes    = "VOL_EXTENDED+Z_FADE";
      ScoreBreakdown sb;
      g_composite = CScoringEngine::Evaluate(cand, REGIME_EXPANSION, -1.0, -1.0, sb);
      // No calibration data in the tester (samples=0 -> base min-confidence
      // 0.48) and no drift detector (steps >= decay window -> 0 penalty).
      double min_conf = 0.0;
      g_signal = CConfidenceEngine::Gate(g_composite, cand.confidence, true,
                                         dir > 0, -1.0, 0, 5000, min_conf);
      g_setup_q = cand.setup_quality;
      g_conf    = CConfidenceEngine::BlendConfidence(g_composite, cand.confidence);

      // --- Stage-3 empirical floor gate (walk-forward, no lookahead) ---
      // The journal holds only band outcomes resolved so far (trades closed
      // strictly before this bar), so its stats are exactly the walk-forward
      // state the Python gate_backtest sees at emission.  Floor = break-even
      // target-hit rate for the band's running avg planned RR + margin:
      //   1/(1+RR) + margin  ->  ~25% for the 4.0-RR geometry.
      // Gate: below min_samples -> still_learning (paper warm-up); at/above
      // the floor -> proven (would trade); below -> suppressed (stand aside).
      g_journal.Statistics(STRATEGY_BAND, g_res_n, g_res_hit, g_res_avg_r,
                           g_res_exp, g_res_avg_rr, g_res_floor);
      g_floor_at_entry  = CTradeQualityEngine::BreakEvenFloor(g_res_avg_rr, InpFloorMargin);
      g_hit_at_entry    = g_res_hit;
      g_samples_at_entry = g_res_n;
      if(g_res_n < InpFloorMinSamples)
         g_gate_state = GATE_STILL_LEARNING;
      else if(g_res_hit >= g_floor_at_entry)
         g_gate_state = GATE_PROVEN;
      else
         g_gate_state = GATE_SUPPRESSED;

      g_in_pos   = true;
      g_dir      = dir;
      g_entry    = r.close;
      g_stop     = lv.stop_loss;
      g_target   = lv.take_profit;
      g_risk     = MathAbs(g_entry - g_stop);
      g_planned_rr = MathAbs(g_target - g_entry) / (g_risk > 0.0 ? g_risk : g_entry * 0.001);
      g_mfe_r    = 0.0;
      g_opened_at = t + BAR_SEC;
      g_armed_prev     = false;   // fresh trail-arm state per position
      g_arm_hold       = 0;
      g_arm_mfe        = 0.0;
      g_dips_after_arm = 0;
      g_journal.StartPosition(cand, r.close, t + BAR_SEC);
     }

   //--- report --------------------------------------------------------
   Print(StringFormat("[BANDBT] diag: bars=%d gap=%d inpos=%d warmup=%d drift_fires=%d  ratio>1.1=%d ratio>1.3=%d  "
                      "ratio_max=%.3f  driftclear+cross=%d  +zpass=%d  dir0=%d  lv_fail=%d  "
                      "depth_fail=%d  conf=%d  hourskip=%d  rangeskip=%d  gzskip=%d  entries=%d",
                      g_diag_bars, g_diag_gap, g_diag_inpos, g_diag_warmup, g_diag_drift,
                      g_diag_ratio110, g_diag_ratio130, g_diag_ratio_max,
                      g_diag_driftclear_cross, g_diag_zpass, g_diag_dir0,
                      g_diag_lv_fail, g_diag_depth_fail, g_diag_conf_fail, g_diag_hourskip,
                      g_diag_range_skip, g_diag_gz_skip, g_ntrades));
   if(g_ntrades < InpMinTrades)
     {
      Print(StringFormat("[BANDBT] only %d trades — measurement too thin", g_ntrades));
      Print(StringFormat("[BANDBT] === %d passed, %d failed ===", 0, 0));
      Print("[BANDBT] SUITE FAILED — fewer than ", InpMinTrades, " closed trades");
      return(INIT_FAILED);
     }

   int wins = 0, losses = 0;
   double gross_win = 0.0, gross_loss = 0.0, sum_r = 0.0;
   for(int i = 0; i < g_ntrades; i++)
     {
      double rr = g_trades[i].rr;
      sum_r += rr;
      if(rr > 0.0) { wins++; gross_win += rr; }
      else         { losses++; gross_loss += -rr; }
     }
   double hit  = 100.0 * (double)wins / g_ntrades;
   double exp0 = sum_r / g_ntrades;
   double exp5 = exp0 - 0.05;
   double exp10 = exp0 - 0.10;
   double pf = (gross_loss > 0.0) ? gross_win / gross_loss : (gross_win > 0.0 ? 99.0 : 0.0);
   double avg_win = (wins > 0) ? gross_win / wins : 0.0;
   double avg_loss = (losses > 0) ? gross_loss / losses : 0.0;
   double e_long = n_long > 0 ? exp_long / n_long : 0.0;
   double e_short = n_short > 0 ? exp_short / n_short : 0.0;

   Print(StringFormat("[BANDBT] trades=%d  wins=%d  losses=%d  hit=%.1f%%  "
                      "(long %d, short %d)", g_ntrades, wins, losses, hit, n_long, n_short));
   Print(StringFormat("[BANDBT] expectancy: %.3f R/trade gross | %.3f R @0.05 cost | %.3f R @0.10 cost",
                      exp0, exp5, exp10));
   Print(StringFormat("[BANDBT] avg win +%.3fR  avg loss -%.3fR  profit factor %.2f",
                      avg_win, avg_loss, pf));
   Print(StringFormat("[BANDBT] max drawdown %.2fR (peak %.2fR)  |  long %.3fR  short %.3fR",
                      g_maxDD, g_peakR, e_long, e_short));
   Print(StringFormat("[BANDBT] sample trades: %s @ %.1f -> %.1f R=%.2f hold=%db "
                      "[%s comp=%.2f conf=%.2f]; "
                      "%s @ %.1f -> %.1f R=%.2f hold=%db [%s comp=%.2f conf=%.2f]",
                      g_trades[0].direction > 0 ? "BUY " : "SELL", g_trades[0].entry,
                      g_trades[0].exit_price, g_trades[0].rr, g_trades[0].hold_bars,
                      SignalStrengthToString(g_trades[0].signal), g_trades[0].composite,
                      g_trades[0].confidence,
                      g_trades[g_ntrades / 2].direction > 0 ? "BUY " : "SELL",
                      g_trades[g_ntrades / 2].entry, g_trades[g_ntrades / 2].exit_price,
                      g_trades[g_ntrades / 2].rr, g_trades[g_ntrades / 2].hold_bars,
                      SignalStrengthToString(g_trades[g_ntrades / 2].signal),
                      g_trades[g_ntrades / 2].composite, g_trades[g_ntrades / 2].confidence));

   // --- Phase-5 decision layer: expectancy split by confidence bucket ---
   int s_n = 0, w_n = 0, wt_n = 0;
   double s_r = 0.0, w_r = 0.0;
   double c_min = 99.0, c_max = -99.0, c_sum = 0.0, conf_sum = 0.0;
   double s_rr = 0.0, w_rr = 0.0, s_z = 0.0, w_z = 0.0, s_d = 0.0, w_d = 0.0;
   for(int i = 0; i < g_ntrades; i++)
     {
      double rr = g_trades[i].rr;
      double comp = g_trades[i].composite;
      c_sum += comp;
      conf_sum += g_trades[i].confidence;
      if(comp < c_min) c_min = comp;
      if(comp > c_max) c_max = comp;
      if(g_trades[i].signal == SIGNAL_STRONG_BUY || g_trades[i].signal == SIGNAL_STRONG_SELL)
        { s_n++; s_r += rr; s_rr += g_trades[i].planned_rr; s_z += g_trades[i].z_entry_used; s_d += g_trades[i].z_depth; }
      else if(g_trades[i].signal == SIGNAL_WEAK_BUY || g_trades[i].signal == SIGNAL_WEAK_SELL)
        { w_n++; w_r += rr; w_rr += g_trades[i].planned_rr; w_z += g_trades[i].z_entry_used; w_d += g_trades[i].z_depth; }
      else
         wt_n++;
     }
   int s_w = 0, w_w = 0;
   for(int i = 0; i < g_ntrades; i++)
     {
      if(g_trades[i].signal == SIGNAL_STRONG_BUY || g_trades[i].signal == SIGNAL_STRONG_SELL)
        { if(g_trades[i].rr > 0.0) s_w++; }
      else if(g_trades[i].signal == SIGNAL_WEAK_BUY || g_trades[i].signal == SIGNAL_WEAK_SELL)
        { if(g_trades[i].rr > 0.0) w_w++; }
     }
   double s_exp = s_n > 0 ? s_r / s_n : 0.0;
   double w_exp = w_n > 0 ? w_r / w_n : 0.0;
   double s_rr_m = s_n > 0 ? s_rr / s_n : 0.0;
   double w_rr_m = w_n > 0 ? w_rr / w_n : 0.0;
   double s_z_m = s_n > 0 ? s_z / s_n : 0.0;
   double w_z_m = w_n > 0 ? w_z / w_n : 0.0;
   double s_d_m = s_n > 0 ? s_d / s_n : 0.0;
   double w_d_m = w_n > 0 ? w_d / w_n : 0.0;
   Print("[BANDBT] confidence buckets (per-signal geometry sweep — strong >= 0.52 w/ setup, weak >= 0.48):");
   Print(StringFormat("[BANDBT]   STRONG: n=%d  hit=%.1f%%  exp=%+.3fR  (avgRR=%.2f avg z_entry=%.2f avg depth=%.2f)",
                      s_n, s_n > 0 ? 100.0 * s_w / s_n : 0.0, s_exp, s_rr_m, s_z_m, s_d_m));
   Print(StringFormat("[BANDBT]   WEAK:   n=%d  hit=%.1f%%  exp=%+.3fR  (avgRR=%.2f avg z_entry=%.2f avg depth=%.2f)",
                      w_n, w_n > 0 ? 100.0 * w_w / w_n : 0.0, w_exp, w_rr_m, w_z_m, w_d_m));
   Print(StringFormat("[BANDBT]   WAIT:   n=%d  (signals the decision gate would have blocked)", wt_n));
   Print(StringFormat("[BANDBT]   composite: min %.3f  max %.3f  mean %.3f  |  blended confidence mean %.3f",
                      c_min, c_max, c_sum / MathMax(1, g_ntrades),
                      conf_sum / MathMax(1, g_ntrades)));
   // --- does the STRONG bucket outperform WEAK? ---
   if(s_n > 0 && w_n > 0)
     {
      double lift = s_exp - w_exp;
      string better = lift > 0.0 ? "STRONG" : "WEAK";
      Print(StringFormat("[BANDBT]   BUCKET VERDICT: STRONG %+.3fR vs WEAK %+.3fR (%+.3fR lift) — %s bucket outperforms; "
                         "STRONG hit %.1f%% vs WEAK hit %.1f%%",
                         s_exp, w_exp, lift, better,
                         s_n > 0 ? 100.0 * s_w / s_n : 0.0,
                         w_n > 0 ? 100.0 * w_w / w_n : 0.0));
     }
   else
      Print(StringFormat("[BANDBT]   BUCKET VERDICT: insufficient coverage — STRONG n=%d, WEAK n=%d (need both > 0)",
                         s_n, w_n));

   // --- edge-depth gate: shallow-only subset vs the floor -----------------
   // Depth = |z|/z_entry at entry (>= 1 by the gate).  The user-facing
   // question: does blocking the deep-extension STRONG bucket (depth > ~2)
   // leave a shallow-only subset that clears its own break-even floor?
   Print("[BANDBT] edge-depth split (|z|/z_entry cap;  depth >= 1 by the z gate):");
   double d_caps[5] = {1.25, 1.5, 2.0, 2.5, 3.0};
   int    d_n[5];      double d_hit[5];      double d_exp[5];
   for(int dc = 0; dc < 5; dc++)
     {
      int dn = 0, dw = 0;
      double dr = 0.0, dfloor = 0.0;
      for(int i = 0; i < g_ntrades; i++)
        {
         if(g_trades[i].z_depth <= d_caps[dc])
           {
            dn++;
            dr += g_trades[i].rr;
            dfloor += g_trades[i].floor_at_entry;
            if(g_trades[i].rr > 0.0) dw++;
           }
        }
      d_n[dc] = dn;
      d_hit[dc] = (dn > 0) ? 100.0 * dw / dn : 0.0;
      d_exp[dc] = (dn > 0) ? dr / dn : 0.0;
      if(dn == 0)
         continue;
      double dhit = d_hit[dc];
      double dexp = d_exp[dc];
      double dfloor_m = 100.0 * dfloor / dn;
      string dverdict = (dfloor_m > 0.0 && dhit >= dfloor_m) ? "CLEARS" : "misses";
      Print(StringFormat("[BANDBT]   depth <= %.2f:  n=%d  hit=%.1f%%  exp=%+.3fR  "
                         "(mean floor at entry %.1f%%)  -> %s the floor",
                         d_caps[dc], dn, dhit, dexp, dfloor_m, dverdict));
     }
   // Machine-parseable depth profile for verify_all.ps1's bucket-composition
   // contract: all 5 cumulative caps in one line (n / hit / exp / share of
   // total), empty buckets emitted as n=0 — a refactor that changes which
   // depth buckets the entries land in must fail the scheduled loop visibly.
   Print(StringFormat("[BANDBT] DEPTHPROFILE caps=1.25,1.50,2.00,2.50,3.00 "
                      "n=%d,%d,%d,%d,%d "
                      "hit=%.1f,%.1f,%.1f,%.1f,%.1f "
                      "exp=%+.3f,%+.3f,%+.3f,%+.3f,%+.3f "
                      "share=%.1f,%.1f,%.1f,%.1f,%.1f total=%d",
                      d_n[0], d_n[1], d_n[2], d_n[3], d_n[4],
                      d_hit[0], d_hit[1], d_hit[2], d_hit[3], d_hit[4],
                      d_exp[0], d_exp[1], d_exp[2], d_exp[3], d_exp[4],
                      d_n[4] > 0 ? 100.0 * d_n[0] / d_n[4] : 0.0,
                      d_n[4] > 0 ? 100.0 * d_n[1] / d_n[4] : 0.0,
                      d_n[4] > 0 ? 100.0 * d_n[2] / d_n[4] : 0.0,
                      d_n[4] > 0 ? 100.0 * d_n[3] / d_n[4] : 0.0,
                      d_n[4] > 0 ? 100.0 * d_n[4] / d_n[4] : 0.0,
                      d_n[4]));

   // --- trail arming-to-exit path: how many trades does the grace save? ----
   // Counterfactual: every armed trade that wick-throughs entry (any post-arm
   // bar with low < entry / high > entry) would have been scratched at 0R by
   // the old same-candle rule.  The ones that STILL reached target afterwards
   // are trades the closed-candle grace converted from a 0R scratch to a +RR
   // win — the quantified reason the trail stopped racing the target.
   if(InpTrailFrac > 0.0)
     {
      int a_n = 0, a_dip = 0, a_saved = 0, a_tgt_nodip = 0, a_be = 0, a_time = 0;
      double a_saved_r = 0.0, a_arm_mfe = 0.0, a_arm_mfe_dip = 0.0;
      int a_dip_sum = 0, a_dip_saved = 0;
      for(int i = 0; i < g_ntrades; i++)
        {
         if(g_trades[i].arm_hold_bars < 0)
            continue;
         a_n++;
         a_arm_mfe += g_trades[i].arm_mfe_r;
         a_dip_sum += g_trades[i].dips_after_arm;
         if(g_trades[i].wick_scratch_wo_grace)
           {
            a_dip++;
            a_arm_mfe_dip += g_trades[i].arm_mfe_r;
           }
         if(g_trades[i].hit_target_after_dip)
           {
            a_saved++;
            a_saved_r += g_trades[i].rr;
            a_dip_saved += g_trades[i].dips_after_arm;
           }
         else if(g_trades[i].exit_reason == EXIT_TARGET_HIT)
            a_tgt_nodip++;
         else if(g_trades[i].exit_reason == EXIT_BREAKEVEN_TRAIL)
            a_be++;
         else
            a_time++;
        }
      Print(StringFormat("[BANDBT] trail arming path (InpTrailFrac=%.2f, grace %s): %d of %d trades armed (%.1f%%), "
                         "avg arm-MFE %.2fR, avg dips-after-arm %.2f",
                         InpTrailFrac, (InpTrailClosedCandle ? "ON" : "OFF"), a_n, g_ntrades,
                         100.0 * a_n / g_ntrades, a_n > 0 ? a_arm_mfe / a_n : 0.0,
                         a_n > 0 ? (double)a_dip_sum / a_n : 0.0));
      Print(StringFormat("[BANDBT]   armed -> target, NO dip:      %d (would win anyway)", a_tgt_nodip));
      Print(StringFormat("[BANDBT]   armed -> target AFTER dip(s): %d  (+%.2fR SAVED by the grace: 0R scratch -> target win)",
                         a_saved, a_saved_r));
      Print(StringFormat("[BANDBT]   armed -> breakeven exit:      %d (0R with or without the grace)", a_be));
      Print(StringFormat("[BANDBT]   armed -> time exit:           %d", a_time));
      Print(StringFormat("[BANDBT]   wick-through trades: %d (%.1f%% of armed), avg %d spared dips each, "
                         "avg arm-MFE %.2fR vs %.2fR for the saved subset",
                         a_dip, a_n > 0 ? 100.0 * a_dip / a_n : 0.0,
                         a_dip > 0 ? a_dip_sum / a_dip : 0,
                         a_dip > 0 ? a_arm_mfe_dip / a_dip : 0.0,
                         a_saved > 0 ? a_saved_r / a_saved : 0.0));
      Print(StringFormat("[BANDBT]   => the grace converts %d 0R scratches to %d target wins worth +%.2fR "
                         "(+%.3fR/trade over all %d trades)",
                         a_dip, a_saved, a_saved_r,
                         g_ntrades > 0 ? a_saved_r / g_ntrades : 0.0, g_ntrades));
      // --- arming path by edge-depth bucket: do shallow fades survive the
      // trail better than the deep extensions? -----------------------------
      // Same buckets as the deep-vs-shallow profile below (depth = |z|/z_entry
      // at entry).  Per bucket: arm rate, wick-through rate, how many wick-
      // throughs the grace converted to target wins (saved) and the saved R
      // per bucket trade — the trail's benefit attributed to shallow vs deep.
      double d_edges[4] = {1.0, 1.5, 2.5, 999.0};
      string d_labels[3] = {"shallow <=1.5", "mid 1.5-2.5", "deep >2.5"};
      Print("[BANDBT] arming path by depth bucket (shallow fades vs deep extensions):");
      for(int b = 0; b < 3; b++)
        {
         int bn = 0, bw = 0, barm = 0, bdip = 0, bsaved = 0, bbe = 0;
         double br = 0.0, bsaved_r = 0.0, bdip_sum = 0.0, barm_mfe = 0.0;
         for(int i = 0; i < g_ntrades; i++)
           {
            double d = g_trades[i].z_depth;
            if(d < d_edges[b] || d >= d_edges[b + 1])
               continue;
            bn++;
            br += g_trades[i].rr;
            if(g_trades[i].rr > 0.0) bw++;
            if(g_trades[i].arm_hold_bars < 0)
               continue;
            barm++;
            barm_mfe += g_trades[i].arm_mfe_r;
            if(g_trades[i].wick_scratch_wo_grace)
              {
               bdip++;
               bdip_sum += g_trades[i].dips_after_arm;
              }
            if(g_trades[i].hit_target_after_dip)
              {
               bsaved++;
               bsaved_r += g_trades[i].rr;
              }
            else if(g_trades[i].exit_reason == EXIT_BREAKEVEN_TRAIL)
               bbe++;
           }
         if(bn == 0)
            continue;
         Print(StringFormat(
            "[BANDBT]   %-14s n=%4d hit=%5.1f%% exp=%+.3fR  armed %4d (%4.1f%%)  "
            "wick-thru %3d (%4.1f%% of armed)  saved %3d/%3d conv %4.1f%% (+%.1fR, %+.3fR/trade)  "
            "BE %3d  avg arm-MFE %.2fR",
            d_labels[b], bn, 100.0 * bw / bn, br / bn, barm,
            bn > 0 ? 100.0 * barm / bn : 0.0, bdip,
            barm > 0 ? 100.0 * bdip / barm : 0.0, bsaved, bdip,
            bdip > 0 ? 100.0 * bsaved / bdip : 0.0, bsaved_r,
            bn > 0 ? bsaved_r / bn : 0.0, bbe,
            barm > 0 ? barm_mfe / barm : 0.0));
        }
     }

   // --- deep-vs-shallow profile (drawdown investigation) -----------------
   // Why do the deep-extension fades bleed the drawdown?  Compare per-depth
   // bucket: hold time, MFE, exit-reason mix, vol regime at entry, the
   // bucket's total R contribution (sumR), and the bucket's OWN max drawdown
   // computed directly from its realized equity curve (path-dependent, not
   // just the sumR share).
   Print("[BANDBT] deep-vs-shallow profile (depth = |z|/z_entry at entry):");
   double d_edges[4] = {1.0, 1.5, 2.5, 999.0};
   string d_labels[3] = {"shallow <=1.5", "mid 1.5-2.5", "deep >2.5"};
   for(int b = 0; b < 3; b++)
     {
      int dn = 0, dw = 0, ds = 0, dt = 0, dbt = 0, dd = 0;
      double dr = 0.0, dhold = 0.0, dmfe = 0.0, dvol = 0.0;
      for(int i = 0; i < g_ntrades; i++)
        {
         double d = g_trades[i].z_depth;
         if(d >= d_edges[b] && d < d_edges[b + 1])
           {
            dn++;
            dr += g_trades[i].rr;
            dhold += g_trades[i].hold_bars;
            dmfe += g_trades[i].mfe_r;
            dvol += g_trades[i].vol_ratio_entry;
            if(g_trades[i].rr > 0.0) dw++;
            if(g_trades[i].exit_reason == EXIT_STOP_HIT) ds++;
            else if(g_trades[i].exit_reason == EXIT_TARGET_HIT) dt++;
            else if(g_trades[i].exit_reason == EXIT_BREAKEVEN_TRAIL) dbt++;
            else dd++;   // EXIT_TIME (incl. dead-trade exits)
           }
        }
      if(dn == 0)
        {
         Print(StringFormat("[BANDBT]   %-14s n=0", d_labels[b]));
         continue;
        }
      // Per-bucket drawdown DIRECTLY from the equity curve: walk the bucket's
      // trades in chronological order (g_trades is appended in close order) and
      // track the bucket's own peak-to-trough on its realized cumulative-R
      // curve, using each trade's recorded equity position (close - open).
      double dcum = 0.0, dpeak = 0.0, ddd = 0.0;
      for(int i = 0; i < g_ntrades; i++)
        {
         double d = g_trades[i].z_depth;
         if(d >= d_edges[b] && d < d_edges[b + 1])
           {
            dcum += g_trades[i].cum_r_at_close - g_trades[i].cum_r_at_open;
            if(dcum > dpeak) dpeak = dcum;
            if(dpeak - dcum > ddd) ddd = dpeak - dcum;
           }
        }
      Print(StringFormat("[BANDBT]   %-14s n=%4d hit=%5.1f%% exp=%+.3fR sumR=%+.1fR maxDD=%+.1fR  "
                         "hold=%4.1fb mfe=%+.2fR vol@entry=%.2f  exits: stop %4.1f%% target %4.1f%% BE-trail %4.1f%% time %4.1f%%",
                         d_labels[b], dn, 100.0 * dw / dn, dr / dn, dr, ddd,
                         dhold / dn, dmfe / dn, dvol / dn,
                         100.0 * ds / dn, 100.0 * dt / dn, 100.0 * dbt / dn,
                         100.0 * dd / dn));
     }
   // Vol-regime split (independent of depth): is the bleed concentrated in
   // the highest-vol-regime entries?
   double v_edges[3] = {1.0, 1.25, 999.0};
   string v_labels[2] = {"vol<=1.25", "vol>1.25"};
   Print("[BANDBT] vol-regime split at entry (prev_sigma / sigma_ema):");
   for(int b = 0; b < 2; b++)
     {
      int dn = 0, dw = 0, dd = 0;
      double dr = 0.0, dhold = 0.0;
      for(int i = 0; i < g_ntrades; i++)
        {
         double v = g_trades[i].vol_ratio_entry;
         if(v >= v_edges[b] && v < v_edges[b + 1])
           {
            dn++;
            dr += g_trades[i].rr;
            dhold += g_trades[i].hold_bars;
            if(g_trades[i].rr > 0.0) dw++;
            if(g_trades[i].exit_reason == EXIT_STOP_HIT) dd++;
           }
        }
      if(dn == 0)
         continue;
      Print(StringFormat("[BANDBT]   %-12s n=%4d hit=%5.1f%% exp=%+.3fR sumR=%+.1fR  "
                         "hold=%4.1fb  stop-outs=%4.1f%%",
                         v_labels[b], dn, 100.0 * dw / dn, dr / dn, dr,
                         dhold / dn, 100.0 * dd / dn));
     }

   // --- Stage-3 empirical floor gate: kept vs suppressed ------------------
   int kept_n = 0, supp_n = 0, prov_n = 0, learn_n = 0, kept_w = 0, supp_w = 0;
   double kept_r = 0.0, supp_r = 0.0, floor_sum = 0.0;
   for(int i = 0; i < g_ntrades; i++)
     {
      double rr = g_trades[i].rr;
      floor_sum += g_trades[i].floor_at_entry;
      if(g_trades[i].gate_state == GATE_SUPPRESSED)
        {
         supp_n++; supp_r += rr;
         if(rr > 0.0) supp_w++;
        }
      else
        {
         kept_n++; kept_r += rr;
         if(rr > 0.0) kept_w++;
        }
      if(g_trades[i].gate_state == GATE_PROVEN) prov_n++;
      else if(g_trades[i].gate_state == GATE_STILL_LEARNING) learn_n++;
     }
   double mean_floor = g_ntrades > 0 ? 100.0 * floor_sum / g_ntrades : 0.0;
   double kept_hit = kept_n > 0 ? 100.0 * kept_w / kept_n : 0.0;
   double supp_hit = supp_n > 0 ? 100.0 * supp_w / supp_n : 0.0;
   double kept_exp = kept_n > 0 ? kept_r / kept_n : 0.0;
   double supp_exp = supp_n > 0 ? supp_r / supp_n : 0.0;
   Print("[BANDBT] Stage-3 empirical floor gate (TradeQualityEngine.BreakEvenFloor):");
   Print(StringFormat("[BANDBT]   floor = 1/(1+avg planned RR) + margin;  margin=%.2f  min_samples=%d  "
                      "(journal@last-entry: n=%d hit=%.1f%% avgRR=%.2f exp=%+.3fR)",
                      InpFloorMargin, InpFloorMinSamples,
                      g_res_n, 100.0 * g_res_hit, g_res_avg_rr, g_res_exp));
   Print(StringFormat("[BANDBT]   mean floor at entry %.1f%%  (band %.2f-RR geometry needs %.1f%% to break even)",
                      mean_floor, g_res_avg_rr,
                      100.0 * CTradeQualityEngine::BreakEvenFloor(g_res_avg_rr, InpFloorMargin)));
   Print(StringFormat("[BANDBT]   KEPT (would trade):       n=%d  hit=%.1f%%  exp=%+.3fR  [proven %d, still_learning %d]",
                      kept_n, kept_hit, kept_exp, prov_n, learn_n));
   Print(StringFormat("[BANDBT]   SUPPRESSED (stand aside):  n=%d  hit=%.1f%%  exp=%+.3fR",
                      supp_n, supp_hit, supp_exp));
   double all_hit = 100.0 * (double)wins / g_ntrades;
   bool beatable = (mean_floor > 0.0) && (all_hit >= mean_floor);
   Print(StringFormat("[BANDBT]   VERDICT: achieved hit %.1f%% %s the %.1f%% floor — the band's %.2f-RR geometry %s",
                      all_hit, beatable ? "BEATS" : "does NOT beat", mean_floor, g_res_avg_rr,
                      beatable ? "is floor-beatable on this window" : "is NOT floor-beatable on this window — the gate stands aside"));
   Print(StringFormat("[BANDBT] FLOORVERDICT floor=%.1f achieved=%.1f verdict=%s mean_rr=%.2f",
                      mean_floor, all_hit, beatable ? "BEAT" : "NOT_BEAT", g_res_avg_rr));
   if(exp0 <= 0.0)
      Print("[BANDBT] NOTE: expectancy non-positive — the band leg is not yet tradeable on this window");
   Print(StringFormat("[BANDBT] === %d passed, %d failed ===  (%.1f%% hit rate, %.3f R expectancy on %s)",
                      wins, losses, hit, exp0, _Symbol));
   Print("[BANDBT] SUITE PASSED — backtest measurement complete");
   return(INIT_SUCCEEDED);
  }

void OnTick()
  {
  }

void OnDeinit(const int reason)
  {
  }
//+------------------------------------------------------------------+
