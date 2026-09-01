//+------------------------------------------------------------------+
//|                                      Core/Constants.mqh          |
//|  MITEMSHUB AI MARKET ENGINE — shared enums, reason codes, and    |
//|  hard-limit defaults.                                            |
//|                                                                  |
//|  This is the single source of truth for every enum the engine    |
//|  uses.  No magic numbers in logic files — if it is a categorical |
//|  value it lives here.                                            |
//|                                                                  |
//|  ARCHITECTURE NOTE:                                              |
//|  This module defines the type system for the entire EA.  Every   |
//|  other module imports these enums and constants.  Changes here   |
//|  propagate to ALL modules — test thoroughly before modifying.    |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CORE_CONSTANTS_MQH
#define MITEMSHUB_CORE_CONSTANTS_MQH

//+------------------------------------------------------------------+
//| MARKET REGIMES                                                    |
//|                                                                    |
//| Classification of market conditions based on volatility and        |
//| price structure analysis.  Used by RegimeEngine to gate strategy  |
//| selection and risk parameters.                                    |
//|                                                                    |
//| Valid regime transitions:                                          |
//|   TREND_UP/DOWN <-> RANGE <-> COMPRESSION <-> EXPANSION          |
//|   HIGH_VOLATILITY <-> LOW_VOLATILITY (independent of structure)   |
//|   TRANSITION (temporary state during regime shifts)               |
//+------------------------------------------------------------------+
enum ENUM_REGIME
  {
   REGIME_UNKNOWN = 0,        // uninitialized — should never reach decision layer
   REGIME_TREND_UP,           // bullish trend: HH+HL sequence, rising EMA
   REGIME_TREND_DOWN,         // bearish trend: LH+LL sequence, falling EMA
   REGIME_RANGE,              // sideways: no clear trend, mean-reverting
   REGIME_COMPRESSION,        // volatility contracting (Bollinger squeeze)
   REGIME_EXPANSION,          // volatility expanding (breakout zone)
   REGIME_HIGH_VOLATILITY,    // absolute vol above threshold (atr_ratio > 1.5)
   REGIME_LOW_VOLATILITY,     // absolute vol below threshold (atr_ratio < 0.7)
   REGIME_TRANSITION          // regime shift detected (vol-of-vol spike)
  };

//+------------------------------------------------------------------+
//| DECISIONS                                                         |
//|                                                                    |
//| The output of the decision layer after scoring and gating.        |
//| DECISION_WAIT means no actionable signal — the EA stands aside.  |
//+------------------------------------------------------------------+
enum ENUM_DECISION
  {
   DECISION_WAIT = 0,         // no trade — stand aside
   DECISION_BUY,              // long signal approved
   DECISION_SELL              // short signal approved
  };

//+------------------------------------------------------------------+
//| SIGNAL STRENGTH                                                    |
//|                                                                    |
//| Port of Python decision_engine._classify_signal_strength().       |
//| Maps raw confidence + setup quality to actionable signal buckets. |
//|                                                                    |
//| Flow: confidence + setup_quality -> signal_strength -> decision.  |
//| STRONG signals trade at full size.                                |
//| WEAK signals are vetoed by default (m_veto_weak = true).          |
//| WAIT means no committed direction.                                |
//+------------------------------------------------------------------+
enum ENUM_SIGNAL_STRENGTH
  {
   SIGNAL_WAIT = 0,           // no committed direction — never trades
   SIGNAL_STRONG_BUY,         // high confidence buy — full size
   SIGNAL_WEAK_BUY,           // marginal buy — vetoed unless m_veto_weak=false
   SIGNAL_WEAK_SELL,           // marginal sell — vetoed unless m_veto_weak=false
   SIGNAL_STRONG_SELL          // high confidence sell — full size
  };

//+------------------------------------------------------------------+
//| STRATEGIES                                                        |
//|                                                                    |
//| Registry of all strategy legs.  Only STRATEGY_BAND is validated   |
//| and live today.  Research legs are OFF by default and require     |
//| walk-forward validation before activation.                        |
//|                                                                    |
//| Strategy-Regime Allowance Matrix:                                  |
//|   TREND     -> trend, breakout, pullback                          |
//|   RANGE     -> mean-reversion, liquidity-sweep                    |
//|   COMPRESSION -> breakout, liquidity-sweep                        |
//|   EXPANSION -> band only                                          |
//+------------------------------------------------------------------+
enum ENUM_STRATEGY
  {
   STRATEGY_NONE = 0,         // no strategy selected
   STRATEGY_BAND,             // validated EGARCH band geometry (★ ACTIVE)
   STRATEGY_TREND,            // research — OFF until OOS validated
   STRATEGY_BREAKOUT,         // research — OFF until OOS validated
   STRATEGY_MEANREVERSION,    // research — OFF until OOS validated
   STRATEGY_LIQUIDITY_SWEEP,  // research — OFF until OOS validated
   STRATEGY_PULLBACK          // research — OFF until OOS validated
  };

//+------------------------------------------------------------------+
//| EXIT REASONS                                                      |
//|                                                                    |
//| Every trade outcome carries an exit reason for journal analytics. |
//| The reason determines P&L attribution and strategy scoring.       |
//|                                                                    |
//| Priority on same-bar resolution:                                   |
//|   STOP_HIT wins over TARGET_HIT (conservative parity with Python) |
//|   BREAKEVEN_TRAIL requires MFE >= trail_frac * planned_rr         |
//|   TIME exit fires at candle close after horizon expiry             |
//+------------------------------------------------------------------+
enum ENUM_EXIT_REASON
  {
   EXIT_NONE = 0,             // uninitialized
   EXIT_STOP_HIT,             // stop loss triggered
   EXIT_TARGET_HIT,           // take profit reached
   EXIT_TIME,                 // hold horizon expired
   EXIT_BREAKEVEN_TRAIL,      // breakeven trail triggered (MFE threshold)
   EXIT_STRUCTURE,            // structure-based exit (research leg)
   EXIT_OPPOSITE_SIGNAL,      // opposite signal closed position
   EXIT_VOLATILITY,           // volatility-based exit
   EXIT_MANUAL,               // manual intervention
   EXIT_EMERGENCY_STOP,       // emergency stop triggered
   EXIT_SESSION_END           // session end cleanup
  };

//+------------------------------------------------------------------+
//| POSITION STATE                                                     |
//|                                                                    |
//| Tracks the lifecycle of a single position.                        |
//| NONE -> OPEN -> CLOSED (one direction only, no MT5 netting).     |
//+------------------------------------------------------------------+
enum ENUM_POSITION_STATE
  {
   POS_STATE_NONE = 0,        // no position tracked
   POS_STATE_OPEN,            // position is live in the market
   POS_STATE_CLOSED           // position has been closed
  };

//+------------------------------------------------------------------+
//| RISK VERDICTS                                                      |
//|                                                                    |
//| The RiskEngine's final output after all gates are evaluated.      |
//| APPROVED includes sized lots and stake.                           |
//| VETOED carries the reason trail for journal logging.              |
//+------------------------------------------------------------------+
enum ENUM_RISK_VERDICT
  {
   RISK_VETOED = 0,           // trade rejected — see reason trail
   RISK_APPROVED              // trade approved with sized lots
  };

//+------------------------------------------------------------------+
//| STAGE-3 EVIDENCE STATUS                                            |
//|                                                                    |
//| The empirical gate's verdict on a (symbol, trigger_type) pair.    |
//| Only PROVEN calls execute with full size.                         |
//|                                                                    |
//| Flow: trade outcomes -> scoring -> evidence_status -> EA gate.    |
//+------------------------------------------------------------------+
enum ENUM_EVIDENCE_STATUS
  {
   EVIDENCE_UNVERIFIED = 0,   // no scored outcomes yet — PAPER ONLY
   EVIDENCE_STILL_LEARNING,   // < MIN_STAGE3_SAMPLES outcomes — trade small
   EVIDENCE_PROVEN,           // >= MIN_STAGE3_SAMPLES + hit rate >= floor — full size
   EVIDENCE_SUPPRESSED        // enough outcomes, hit rate below floor — stopped
  };

//+------------------------------------------------------------------+
//| ENGINE MODES                                                       |
//|                                                                    |
//| Controls the EA's operating mode.  BACKTEST is the default for    |
//| the Strategy Tester.  PAPER and LIVE require explicit opt-in.     |
//+------------------------------------------------------------------+
enum ENUM_ENGINE_MODE
  {
   ENGINE_MODE_BACKTEST = 0,   // Strategy Tester mode (default)
   ENGINE_MODE_PAPER,          // paper trading — no real orders
   ENGINE_MODE_LIVE            // live trading — real orders
  };

//+------------------------------------------------------------------+
//| VETO REASON CODES                                                  |
//|                                                                    |
//| Bitfield-style reason codes for RiskEngine vetoes.  Each gate     |
//| sets its bit so the journal can log WHY a trade was rejected.     |
//+------------------------------------------------------------------+
#define VETO_NONE                 0x0000
#define VETO_MAX_POSITIONS        0x0001  // max open positions reached
#define VETO_DAILY_LOSS           0x0002  // daily loss limit breached
#define VETO_CONSECUTIVE_LOSS     0x0004  // consecutive loss circuit breaker
#define VETO_CONFIDENCE           0x0008  // confidence below minimum
#define VETO_REWARD_RISK          0x0010  // reward:risk below minimum
#define VETO_EXPOSURE             0x0020  // total exposure limit
#define VETO_EMERGENCY_STOP       0x0040  // emergency stop active
#define VETO_WEAK_SIGNAL          0x0080  // weak signal vetoed
#define VETO_WAIT_SIGNAL          0x0100  // wait signal vetoed
#define VETO_SPREAD               0x0200  // spread too wide
#define VETO_TRADES_PER_HOUR      0x0400  // hourly trade limit
#define VETO_TRADES_PER_DAY       0x0800  // daily trade limit
#define VETO_EQUITY_DD            0x1000  // equity drawdown limit
#define VETO_FLOOR_GATE           0x2000  // Stage-3 floor gate veto

//+------------------------------------------------------------------+
//| HARD-LIMIT DEFAULTS                                                |
//|                                                                    |
//| Python parity defaults from RiskConfig.  These match the Python   |
//| RiskEngine exactly — verified by the Phase-6 real-corpus gate.    |
//|                                                                    |
//| IMPORTANT: changing these affects all symbols and strategies.     |
//| Use .set files for symbol-specific overrides.                     |
//+------------------------------------------------------------------+

//--- Risk limits
#define DEFAULT_MAX_RISK_PER_TRADE_PCT    0.005   // 0.5% of equity per trade
#define DEFAULT_MAX_DAILY_LOSS_PCT        0.05    // 5% daily loss halt
#define DEFAULT_MAX_DAILY_DRAWDOWN_PCT    0.03    // 3% daily drawdown halt
#define DEFAULT_MAX_EQUITY_DRAWDOWN_PCT   0.10    // 10% total equity drawdown halt
#define DEFAULT_MAX_OPEN_POSITIONS        1       // one position at a time per symbol
#define DEFAULT_MAX_TOTAL_EXPOSURE_PCT    0.25    // 25% max total exposure
#define DEFAULT_MAX_CONSECUTIVE_LOSSES    4       // halt after 4 consecutive losses
// v26.14: 0 = DISABLED по подразбиране — без лимит за брой трейдови.
// Пазарът предлага възможности 24/7; лимитът се активира само с .set стойност > 0.
#define DEFAULT_MAX_TRADES_PER_HOUR       0       // 0 = disabled (was 6)
#define DEFAULT_MAX_TRADES_PER_DAY        0       // 0 = disabled (was 20)

//--- Band geometry defaults
#define DEFAULT_BAND_Z_ENTRY             2.0     // |z_dev| to trigger fade entry
#define DEFAULT_BAND_VOL_EXT_RATIO       1.3     // sigma must exceed this * sigma_ema
#define DEFAULT_BAND_SIGMA_EMA_PERIOD    30      // sigma baseline EMA period
#define DEFAULT_BAND_STOP_SIGMA_MULT     0.10    // stop = 0.10 * sigma_h
#define DEFAULT_BAND_TARGET_SIGMA_MULT   0.80    // target = 0.80 * sigma_h (R_100)
#define DEFAULT_BAND_HOLD_SEC            3600    // 1 hour hold horizon
#define DEFAULT_BAND_MIN_RR              2.0     // min reward:risk
#define DEFAULT_BAND_MAX_STOP_PCT        0.015   // max stop as fraction of price
#define DEFAULT_BAND_BREAKEVEN_TRAIL_FRAC 0.30   // MFE fraction of target -> BE trail

//--- Execution defaults
#define DEFAULT_MAGIC_NUMBER             7788123 // EA magic number
#define DEFAULT_MAX_SLIPPAGE_POINTS      50      // max deviation for market orders
#define DEFAULT_MAX_SPREAD_POINTS        1500    // max spread for entry (SYN75 normal ~1000-1100)
#define DEFAULT_FIXED_VOLUME             0.0     // 0 = risk-based sizing

//--- Risk engine defaults (Python parity)
#define PY_RISK_PER_TRADE               0.005    // 0.5% of equity per trade
#define PY_MIN_CONFIDENCE               0.48     // minimum decision confidence
#define PY_MIN_REWARD_RISK              1.2      // minimum expected reward:risk
#define PY_STAKE_FLOOR                  0.01     // minimum stake (lots)

//--- Structure defaults
#define DEFAULT_STRUCTURE_LOOKBACK       100     // bars for structure analysis
#define DEFAULT_SWING_LEFT_BARS          3       // swing fractal: bars left
#define DEFAULT_SWING_RIGHT_BARS         3       // swing fractal: bars right

//--- Market defaults
#define DEFAULT_ATR_PERIOD               14      // ATR period
#define DEFAULT_REGIME_LOOKBACK          200     // regime classification window

//+------------------------------------------------------------------+
//| HELPER FUNCTIONS                                                   |
//|                                                                    |
//| Utility functions for enum conversions and validation.            |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| Convert ENUM_REGIME to readable string.                            |
//| PARAM: regime - the regime enum value                             |
//| RETURN: human-readable regime name                                |
//+------------------------------------------------------------------+
string RegimeToString(const ENUM_REGIME regime)
  {
   switch(regime)
     {
      case REGIME_UNKNOWN:        return "UNKNOWN";
      case REGIME_TREND_UP:       return "TREND_UP";
      case REGIME_TREND_DOWN:     return "TREND_DOWN";
      case REGIME_RANGE:          return "RANGE";
      case REGIME_COMPRESSION:    return "COMPRESSION";
      case REGIME_EXPANSION:      return "EXPANSION";
      case REGIME_HIGH_VOLATILITY: return "HIGH_VOLATILITY";
      case REGIME_LOW_VOLATILITY:  return "LOW_VOLATILITY";
      case REGIME_TRANSITION:     return "TRANSITION";
      default:                    return "INVALID";
     }
  }

//+------------------------------------------------------------------+
//| Convert ENUM_DECISION to readable string.                          |
//| PARAM: decision - the decision enum value                         |
//| RETURN: human-readable decision name                              |
//+------------------------------------------------------------------+
string DecisionToString(const ENUM_DECISION decision)
  {
   switch(decision)
     {
      case DECISION_WAIT:  return "WAIT";
      case DECISION_BUY:   return "BUY";
      case DECISION_SELL:  return "SELL";
      default:             return "INVALID";
     }
  }

//+------------------------------------------------------------------+
//| Convert ENUM_EXIT_REASON to readable string.                       |
//| PARAM: reason - the exit reason enum value                        |
//| RETURN: human-readable exit reason name                           |
//+------------------------------------------------------------------+
string ExitReasonToString(const ENUM_EXIT_REASON reason)
  {
   switch(reason)
     {
      case EXIT_NONE:             return "NONE";
      case EXIT_STOP_HIT:         return "STOP_HIT";
      case EXIT_TARGET_HIT:       return "TARGET_HIT";
      case EXIT_TIME:             return "TIME";
      case EXIT_BREAKEVEN_TRAIL:  return "BREAKEVEN_TRAIL";
      case EXIT_STRUCTURE:        return "STRUCTURE";
      case EXIT_OPPOSITE_SIGNAL:  return "OPPOSITE_SIGNAL";
      case EXIT_VOLATILITY:       return "VOLATILITY";
      case EXIT_MANUAL:           return "MANUAL";
      case EXIT_EMERGENCY_STOP:   return "EMERGENCY_STOP";
      case EXIT_SESSION_END:      return "SESSION_END";
      default:                    return "INVALID";
     }
  }

//+------------------------------------------------------------------+
//| Convert ENUM_STRATEGY to readable string.                          |
//| PARAM: strategy - the strategy enum value                         |
//| RETURN: human-readable strategy name                              |
//+------------------------------------------------------------------+
string StrategyToString(const ENUM_STRATEGY strategy)
  {
   switch(strategy)
     {
      case STRATEGY_NONE:             return "NONE";
      case STRATEGY_BAND:             return "BAND";
      case STRATEGY_TREND:            return "TREND";
      case STRATEGY_BREAKOUT:         return "BREAKOUT";
      case STRATEGY_MEANREVERSION:    return "MEANREVERSION";
      case STRATEGY_LIQUIDITY_SWEEP:  return "LIQUIDITY_SWEEP";
      case STRATEGY_PULLBACK:         return "PULLBACK";
      default:                        return "INVALID";
     }
  }

//+------------------------------------------------------------------+
//| Convert ENUM_SIGNAL_STRENGTH to readable string.                   |
//| PARAM: strength - the signal strength enum value                  |
//| RETURN: human-readable signal strength name                       |
//+------------------------------------------------------------------+
string SignalStrengthToString(const ENUM_SIGNAL_STRENGTH strength)
  {
   switch(strength)
     {
      case SIGNAL_WAIT:         return "WAIT";
      case SIGNAL_STRONG_BUY:   return "STRONG_BUY";
      case SIGNAL_WEAK_BUY:     return "WEAK_BUY";
      case SIGNAL_WEAK_SELL:    return "WEAK_SELL";
      case SIGNAL_STRONG_SELL:  return "STRONG_SELL";
      default:                  return "INVALID";
     }
  }

//+------------------------------------------------------------------+
//| Validate that a regime value is within the valid range.           |
//| PARAM: regime - the regime enum value to validate                 |
//| RETURN: true if the regime is valid                               |
//+------------------------------------------------------------------+
bool IsValidRegime(const ENUM_REGIME regime)
  {
   return(regime >= REGIME_UNKNOWN && regime <= REGIME_TRANSITION);
  }

//+------------------------------------------------------------------+
//| Validate that a decision value is within the valid range.         |
//| PARAM: decision - the decision enum value to validate             |
//| RETURN: true if the decision is valid                             |
//+------------------------------------------------------------------+
bool IsValidDecision(const ENUM_DECISION decision)
  {
   return(decision >= DECISION_WAIT && decision <= DECISION_SELL);
  }

//+------------------------------------------------------------------+
//| Validate that a strategy value is within the valid range.         |
//| PARAM: strategy - the strategy enum value to validate             |
//| RETURN: true if the strategy is valid                             |
//+------------------------------------------------------------------+
bool IsValidStrategy(const ENUM_STRATEGY strategy)
  {
   return(strategy >= STRATEGY_NONE && strategy <= STRATEGY_PULLBACK);
  }

#endif // MITEMSHUB_CORE_CONSTANTS_MQH
