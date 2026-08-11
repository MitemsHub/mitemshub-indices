//+------------------------------------------------------------------+
//|                                      Core/Constants.mqh          |
//|  MITEMSHUB AI MARKET ENGINE — shared enums, reason codes, and    |
//|  hard-limit defaults.                                            |
//|                                                                  |
//|  This is the single source of truth for every enum the engine    |
//|  uses.  No magic numbers in logic files — if it is a categorical  |
//|  value it lives here.                                            |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CORE_CONSTANTS_MQH
#define MITEMSHUB_CORE_CONSTANTS_MQH

//--- Market regimes ----------------------------------------------------------
enum ENUM_REGIME
  {
   REGIME_UNKNOWN = 0,
   REGIME_TREND_UP,
   REGIME_TREND_DOWN,
   REGIME_RANGE,
   REGIME_COMPRESSION,
   REGIME_EXPANSION,
   REGIME_HIGH_VOLATILITY,
   REGIME_LOW_VOLATILITY,
   REGIME_TRANSITION
  };

//--- Decisions ---------------------------------------------------------------
enum ENUM_DECISION
  {
   DECISION_WAIT = 0,
   DECISION_BUY,
   DECISION_SELL
  };

//--- Signal strength (Phase-5 ConfidenceEngine; port of Python               
//--- decision_engine._classify_signal_strength) — the four signal states     
//--- plus WAIT.                                                              
enum ENUM_SIGNAL_STRENGTH
  {
   SIGNAL_WAIT = 0,
   SIGNAL_STRONG_BUY,
   SIGNAL_WEAK_BUY,
   SIGNAL_WEAK_SELL,
   SIGNAL_STRONG_SELL
  };

//--- Strategies --------------------------------------------------------------
enum ENUM_STRATEGY
  {
   STRATEGY_NONE = 0,
   STRATEGY_BAND,           // validated EGARCH band geometry (active by default)
   STRATEGY_TREND,          // research — OFF by default
   STRATEGY_BREAKOUT,       // research — OFF by default
   STRATEGY_MEANREVERSION,  // research — OFF by default
   STRATEGY_LIQUIDITY_SWEEP,// research — OFF by default
   STRATEGY_PULLBACK        // research — OFF by default
  };

//--- Exit reasons ------------------------------------------------------------
enum ENUM_EXIT_REASON
  {
   EXIT_NONE = 0,
   EXIT_STOP_HIT,
   EXIT_TARGET_HIT,
   EXIT_TIME,
   EXIT_BREAKEVEN_TRAIL,
   EXIT_STRUCTURE,
   EXIT_OPPOSITE_SIGNAL,
   EXIT_VOLATILITY,
   EXIT_MANUAL,
   EXIT_EMERGENCY_STOP,
   EXIT_SESSION_END
  };

//--- Trade state -------------------------------------------------------------
enum ENUM_POSITION_STATE
  {
   POS_STATE_NONE = 0,
   POS_STATE_OPEN,
   POS_STATE_CLOSED,
   POS_STATE_VETOED
  };

//--- Mode --------------------------------------------------------------------
enum ENUM_ENGINE_MODE
  {
   ENGINE_MODE_BACKTEST = 0,
   ENGINE_MODE_VISUAL,
   ENGINE_MODE_FORWARD_DEMO,
   ENGINE_MODE_LIVE          // requires explicit operator confirmation
  };

//--- Risk verdict (Phase-6 RiskEngine output) ---------------------------------
// The strategy may request a trade, but the RiskEngine has final authority:
// approved=false vetoes it entirely (hard limit breached / below threshold);
// approved=true sizes it into lots (clamped to the symbol's volume grid) and
// a stake.  reasons is the human-readable decision trail for the journal.
struct RiskVerdict
  {
   bool   approved;
   double lots;       // sized volume (0.0 when vetoed or paper-only)
   double stake;      // risk amount in account currency (Python parity)
   string reasons;    // "risk approved" or the veto reason trail
  };

//--- Hard safety limits (defaults; overridable via Config.mqh inputs) --------
// These are the *outer* limits.  The RiskEngine enforces them and no code
// path may auto-override a breached hard limit.
#define DEFAULT_MAX_RISK_PER_TRADE_PCT      1.0     // % of equity at risk per trade
#define DEFAULT_MAX_DAILY_LOSS_PCT          5.0     // halt after this daily loss
#define DEFAULT_MAX_DAILY_DRAWDOWN_PCT      8.0     // halt after this intraday DD
#define DEFAULT_MAX_EQUITY_DRAWDOWN_PCT    15.0     // halt after this total DD
#define DEFAULT_MAX_OPEN_POSITIONS          1
#define DEFAULT_MAX_TOTAL_EXPOSURE_PCT     50.0     // % of equity in open margin
#define DEFAULT_MAX_CONSECUTIVE_LOSSES      5
#define DEFAULT_MAX_TRADES_PER_HOUR         3
#define DEFAULT_MAX_TRADES_PER_DAY          10

//--- Execution defaults ------------------------------------------------------
#define DEFAULT_MAGIC_NUMBER            7788123   // matches SynthCallExecutor
#define DEFAULT_MAX_SLIPPAGE_POINTS     50
#define DEFAULT_MAX_SPREAD_POINTS       600       // SYN75 live ~1080 pts → trading is
                                                  // gated tighter by Config; this is the
                                                  // absolute sanity ceiling.

//--- Timeframe defaults (configurable; these are the engine defaults) --------
#define DEFAULT_TF_MACRO          PERIOD_H4
#define DEFAULT_TF_DIRECTIONAL    PERIOD_H1
#define DEFAULT_TF_SETUP          PERIOD_M15
#define DEFAULT_TF_CONFIRMATION   PERIOD_M5
#define DEFAULT_TF_EXECUTION      PERIOD_M1

//--- Regime/volatility defaults ----------------------------------------------
#define DEFAULT_ATR_PERIOD        14
#define DEFAULT_REGIME_LOOKBACK   200   // bars
#define DEFAULT_STRUCTURE_LOOKBACK 100  // bars

//--- Band geometry defaults (Python VolBandConfig + BandGeometryConfig) -----
#define DEFAULT_BAND_Z_ENTRY             1.0     // |ln(close/ema)| / sigma threshold
#define DEFAULT_BAND_VOL_EXTENDED_RATIO  1.3     // prev_sigma > ratio × sigma_ema
#define DEFAULT_BAND_STOP_SIGMA_MULT     0.20    // stop = entry ∓ 0.20 × σ_h
#define DEFAULT_BAND_TARGET_SIGMA_MULT   0.80    // target = entry ± 0.80 × σ_h
#define DEFAULT_BAND_HOLD_SEC            3600    // 1h default (§38 sweep winner)
#define DEFAULT_BAND_MIN_TARGET_RR       2.0
#define DEFAULT_BAND_MAX_STOP_PCT        0.015   // 1.5% of price, as a fraction
#define DEFAULT_BAND_BREAKEVEN_TRAIL_FRAC 0.3    // arm at MFE ≥ 0.3 × planned RR

//--- Strategy candidate: what every strategy returns --------------------------
// Lives here (not in Strategies/) because every strategy module and the
// StrategyEngine include it without include cycles.  decision=WAIT means the
// strategy evaluated the market and found no tradeable setup — standing aside
// is a valid decision.
struct StrategyCandidate
  {
   ENUM_STRATEGY   strategy;       // which module produced this
   ENUM_DECISION   decision;       // BUY / SELL / WAIT
   double          entry;
   double          stop_loss;
   double          take_profit;
   double          setup_quality;  // 0..1
   double          confidence;     // 0..1
   string          reason_codes;
   ENUM_REGIME     required_regime;
   // Phase-5 decision-layer verdict (ConfidenceEngine.Gate/Classify output):
   // strong/weak/wait.  The RiskEngine vetoes WEAK entries before sizing when
   // the weak-bucket gate is enabled — only STRONG signals trade.
   ENUM_SIGNAL_STRENGTH signal_strength;
  };

//--- Decision-layer outputs (Phase 5) ----------------------------------------
// Per-axis sub-scores in 0..1 and the weighted composite (also 0..1;
// rendered as 0-100 in the explanation string).  Same shape the Python
// DecisionReport carries (setup/regime/structure/risk/execution).
struct ScoreBreakdown
  {
   double setup_score;       // strategy setup quality (0..1)
   double regime_score;      // current-regime alignment with the setup (0..1)
   double structure_score;   // structure-bias agreement (0..1, 0.5 neutral)
   double risk_score;        // RR adequacy vs min RR + max-stop fit (0..1)
   double execution_score;   // execution conditions (spread/vol) (0..1)
   double composite;         // weighted sum (0..1)
  };

//--- Trade-quality journal record (Phase-5 TradeQualityEngine) ----------------
// One row per closed trade: the full R-multiple anatomy the plan requires
// (MAE/MFE in R, +1R/+2R/+3R reached, time to target/stop, exit reason).
struct OutcomeRecord
  {
   ENUM_STRATEGY    strategy;
   ENUM_REGIME      regime;
   int              direction;      // +1 long, -1 short
   double           entry;
   double           stop_loss;
   double           take_profit;
   double           exit_price;
   double           risk_distance;
   double           reward_risk;    // planned RR (|tp-entry|/risk)
   double           return_r;       // realized R
   double           mae_r;          // max adverse excursion, in R (>= 0)
   double           mfe_r;          // max favorable excursion, in R (>= 0)
   bool             r1_reached;     // MFE >= +1R
   bool             r2_reached;     // MFE >= +2R
   bool             r3_reached;     // MFE >= +3R
   datetime         opened_at;
   datetime         closed_at;
   int              hold_bars;
   ENUM_EXIT_REASON exit_reason;
   bool             won;            // return_r > 0
  };

//--- Structure defaults ------------------------------------------------------
#define DEFAULT_SWING_LEFT            3
#define DEFAULT_SWING_RIGHT           3
#define DEFAULT_SR_TOL_ATR            0.5     // level cluster radius, in ATR
#define DEFAULT_MIN_SR_TOUCHES        2
#define DEFAULT_SWEEP_EXCEED_ATR      0.1     // wick must exceed level by this × ATR
#define DEFAULT_DISPLACEMENT_BODY_MULT   2.0  // body ≥ 2 × ATR
#define DEFAULT_DISPLACEMENT_RANGE_MULT  3.0  // range ≥ 3 × ATR

//--- Structure state ---------------------------------------------------------
enum ENUM_STRUCTURE_BIAS
  {
   STRUCT_BIAS_NEUTRAL = 0,
   STRUCT_BIAS_BULLISH,
   STRUCT_BIAS_BEARISH
  };

enum ENUM_STRUCTURE_EVENT
  {
   STRUCT_EVENT_NONE = 0,
   STRUCT_EVENT_BOS,           // break of structure (trend continuation)
   STRUCT_EVENT_CHOCH,         // change of character (potential reversal)
   STRUCT_EVENT_SWEEP,         // liquidity sweep (wick beyond, close back)
   STRUCT_EVENT_DISPLACEMENT   // strong normalized impulse bar
  };

string StructureBiasToString(const ENUM_STRUCTURE_BIAS bias)
  {
   switch(bias)
     {
      case STRUCT_BIAS_BULLISH: return("BULLISH");
      case STRUCT_BIAS_BEARISH: return("BEARISH");
      default:                  return("NEUTRAL");
     }
  }

string StructureEventToString(const ENUM_STRUCTURE_EVENT ev)
  {
   switch(ev)
     {
      case STRUCT_EVENT_BOS:         return("BOS");
      case STRUCT_EVENT_CHOCH:       return("CHOCH");
      case STRUCT_EVENT_SWEEP:       return("SWEEP");
      case STRUCT_EVENT_DISPLACEMENT: return("DISPLACEMENT");
      default:                       return("NONE");
     }
  }

//--- Reason string helpers ---------------------------------------------------
// Human-readable labels used by the DecisionLogger and the dashboard.
string RegimeToString(const ENUM_REGIME regime)
  {
   switch(regime)
     {
      case REGIME_TREND_UP:        return("TREND_UP");
      case REGIME_TREND_DOWN:      return("TREND_DOWN");
      case REGIME_RANGE:           return("RANGE");
      case REGIME_COMPRESSION:     return("COMPRESSION");
      case REGIME_EXPANSION:       return("EXPANSION");
      case REGIME_HIGH_VOLATILITY: return("HIGH_VOLATILITY");
      case REGIME_LOW_VOLATILITY:  return("LOW_VOLATILITY");
      case REGIME_TRANSITION:      return("TRANSITION");
      default:                     return("UNKNOWN");
     }
  }

string DecisionToString(const ENUM_DECISION decision)
  {
   switch(decision)
     {
      case DECISION_BUY:  return("BUY");
      case DECISION_SELL: return("SELL");
      default:            return("WAIT");
     }
  }

string SignalStrengthToString(const ENUM_SIGNAL_STRENGTH s)
  {
   switch(s)
     {
      case SIGNAL_STRONG_BUY:  return("strong_buy");
      case SIGNAL_WEAK_BUY:    return("weak_buy");
      case SIGNAL_WEAK_SELL:   return("weak_sell");
      case SIGNAL_STRONG_SELL: return("strong_sell");
      default:                 return("wait");
     }
  }

string StrategyToString(const ENUM_STRATEGY strategy)
  {
   switch(strategy)
     {
      case STRATEGY_BAND:            return("BAND_GEOMETRY");
      case STRATEGY_TREND:           return("TREND_CONTINUATION");
      case STRATEGY_BREAKOUT:        return("BREAKOUT");
      case STRATEGY_MEANREVERSION:   return("MEAN_REVERSION");
      case STRATEGY_LIQUIDITY_SWEEP: return("LIQUIDITY_SWEEP");
      case STRATEGY_PULLBACK:        return("PULLBACK");
      default:                       return("NONE");
     }
  }

string ExitReasonToString(const ENUM_EXIT_REASON reason)
  {
   switch(reason)
     {
      case EXIT_STOP_HIT:         return("STOP_HIT");
      case EXIT_TARGET_HIT:       return("TARGET_HIT");
      case EXIT_TIME:             return("TIME_EXIT");
      case EXIT_BREAKEVEN_TRAIL:  return("BREAKEVEN_TRAIL");
      case EXIT_STRUCTURE:        return("STRUCTURE_EXIT");
      case EXIT_OPPOSITE_SIGNAL:  return("OPPOSITE_SIGNAL");
      case EXIT_VOLATILITY:       return("VOLATILITY_EXIT");
      case EXIT_MANUAL:           return("MANUAL");
      case EXIT_EMERGENCY_STOP:   return("EMERGENCY_STOP");
      case EXIT_SESSION_END:      return("SESSION_END");
      default:                    return("NONE");
     }
  }

#endif // MITEMSHUB_CORE_CONSTANTS_MQH
