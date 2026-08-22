//+------------------------------------------------------------------+
//|                                      Core/Config.mqh             |
//|  MITEMSHUB AI MARKET ENGINE — every tunable input, grouped.      |
//|                                                                  |
//|  All `input` variables live here (single include).  Logic files  |
//|  read these globals; they never define their own magic numbers.  |
//|  Grouped so the MT5 inputs dialog is navigable.                  |
//|                                                                  |
//|  ARCHITECTURE:                                                   |
//|  This is the central configuration hub for the EA.  Every module |
//|  reads its settings through the typed accessors (cfg* functions)  |
//|  defined at the bottom.  The input groups organize parameters    |
//|  for the MT5 inputs dialog.                                      |
//|                                                                  |
//|  OVERRIDE STRATEGY:                                              |
//|  1. Use .set files for symbol-specific overrides (R_75 vs R_100) |
//|  2. Modify inputs for research/testing (Strategy Tester)         |
//|  3. Never hardcode values in logic files — always read via cfg*  |
//|                                                                  |
//|  PYTHON PARITY:                                                  |
//|  Band geometry defaults match Python backtest-vol.py exactly.    |
//|  Risk limits match Python RiskConfig.  The Phase-6/10 gates      |
//|  verify parity on every verify loop.                             |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CORE_CONFIG_MQH
#define MITEMSHUB_CORE_CONFIG_MQH

#include "Constants.mqh"

//+------------------------------------------------------------------+
//| MODE & SAFETY                                                      |
//|                                                                    |
//| Controls the EA's operating mode and emergency overrides.         |
//| These are the first parameters to check when debugging issues.    |
//|                                                                    |
//| SAFETY HIERARCHY:                                                 |
//|   EmergencyStop overrides everything (no new trades)              |
//|   LiveTradingEnabled must be true for live execution              |
//|   EngineMode controls the execution path                          |
//+------------------------------------------------------------------+
input group "Mode & Safety"
input ENUM_ENGINE_MODE InpEngineMode = ENGINE_MODE_BACKTEST; // Engine mode
input bool   InpLiveTradingEnabled = false;  // LIVE execution requires explicit true
input bool   InpEmergencyStop      = false;  // EMERGENCY_STOP: no new trades
input bool   InpDebugMode          = false;  // verbose diagnostics

//+------------------------------------------------------------------+
//| RISK LIMITS                                                        |
//|                                                                    |
//| Hard limits that cannot be overridden by strategy logic.          |
//| These protect the account from catastrophic drawdown.             |
//|                                                                    |
//| LIMIT HIERARCHY (checked in order):                               |
//|   1. EmergencyStop (immediate halt)                               |
//|   2. Daily loss limit (resets at midnight)                        |
//|   3. Consecutive loss circuit breaker (resets on win)             |
//|   4. Equity drawdown limit (total account protection)             |
//|   5. Max open positions (single position by default)              |
//|   6. Exposure limits (margin utilization)                         |
//|   7. Trades per hour/day (frequency caps)                         |
//|                                                                    |
//| PYTHON PARITY:                                                    |
//| Defaults match Python RiskConfig exactly.  Phase-6 real-corpus    |
//| gate verifies parity on every verify loop.                        |
//+------------------------------------------------------------------+
input group "Risk Limits"
input double InpRiskPerTradePct      = DEFAULT_MAX_RISK_PER_TRADE_PCT;      // risk % of equity per trade
input double InpMaxDailyLossPct      = DEFAULT_MAX_DAILY_LOSS_PCT;          // halt after daily loss %
input double InpMaxDailyDrawdownPct  = DEFAULT_MAX_DAILY_DRAWDOWN_PCT;      // halt after daily drawdown %
input double InpMaxEquityDrawdownPct = DEFAULT_MAX_EQUITY_DRAWDOWN_PCT;     // halt after total equity DD %
input int    InpMaxOpenPositions     = DEFAULT_MAX_OPEN_POSITIONS;          // max simultaneous positions
input double InpMaxTotalExposurePct  = DEFAULT_MAX_TOTAL_EXPOSURE_PCT;      // max % equity in open margin
input int    InpMaxConsecutiveLosses = DEFAULT_MAX_CONSECUTIVE_LOSSES;      // halt after N losses in a row
input int    InpMaxTradesPerHour     = DEFAULT_MAX_TRADES_PER_HOUR;
input int    InpMaxTradesPerDay      = DEFAULT_MAX_TRADES_PER_DAY;

//+------------------------------------------------------------------+
//| REGIME & VOLATILITY                                                |
//|                                                                    |
//| Parameters for market regime classification and volatility        |
//| analysis.  Used by RegimeEngine and VolatilityEngine.             |
//|                                                                    |
//| ATR period affects volatility sensitivity:                        |
//|   - Shorter (7-10): more responsive, more false signals           |
//|   - Longer (14-20): smoother, slower to react                    |
//|                                                                    |
//| Regime lookback affects trend detection:                          |
//|   - Shorter (100): faster regime changes, more transitions       |
//|   - Longer (200): smoother trends, fewer false regime changes    |
//+------------------------------------------------------------------+
input group "Regime & Volatility"
input int    InpAtrPeriod          = DEFAULT_ATR_PERIOD;        // ATR period
input int    InpRegimeLookback     = DEFAULT_REGIME_LOOKBACK;   // regime classification window (bars)
input int    InpHurstLookback      = 100;                      // Hurst estimation window
input double InpAtrPercentileWindow = 100.0;                   // bars for ATR percentile rank

//+------------------------------------------------------------------+
//| STRUCTURE                                                           |
//|                                                                    |
//| Parameters for market structure analysis (SMC primitives).        |
//| Used by StructureEngine, SwingDetector, BOSDetector, etc.         |
//|                                                                    |
//| SWING DETECTION:                                                  |
//|   - Left/right bars define the fractal pattern                    |
//|   - Strictly greater high / lesser low (no flat tops)            |
//|   - Confirmed only after right guard bars close                   |
//|                                                                    |
//| DISPLACEMENT:                                                     |
//|   - Body/range must exceed ATR multiplier                         |
//|   - Close must be committed to direction (0.7/0.3 thresholds)    |
//+------------------------------------------------------------------+
input group "Structure"
input int    InpStructureLookback = DEFAULT_STRUCTURE_LOOKBACK; // bars
input int    InpSwingLeftBars     = 3;                         // swing fractals: bars left
input int    InpSwingRightBars    = 3;                         // swing fractals: bars right
input double InpDisplacementAtrMult = 2.0;                     // displacement = body/range vs ATR mult

//+------------------------------------------------------------------+
//| STRATEGIES (TOGGLES)                                               |
//|                                                                    |
//| Master switches for each strategy leg.  Only BandGeometry is      |
//| validated and live today.  Research legs require walk-forward     |
//| validation before activation.                                     |
//|                                                                    |
//| STRATEGY-REGIME ALLOWANCE MATRIX:                                 |
//|   TREND     -> trend, breakout, pullback                          |
//|   RANGE     -> mean-reversion, liquidity-sweep                    |
//|   COMPRESSION -> breakout, liquidity-sweep                        |
//|   EXPANSION -> band only                                          |
//|                                                                    |
//| IMPORTANT: enabling a research leg without OOS validation will    |
//| produce false confidence in unvalidated strategies.               |
//+------------------------------------------------------------------+
input group "Strategies"
input bool   InpEnableBandGeometry   = true;  // validated leg (default ON)
input bool   InpEnableTrend          = false; // research — OFF until OOS validated
input bool   InpEnableBreakout       = false; // research — OFF until OOS validated
input bool   InpEnableMeanReversion  = false; // research — OFF until OOS validated
input bool   InpEnableLiquiditySweep = false; // research — OFF until OOS validated
input bool   InpEnablePullback       = false; // research — OFF until OOS validated

//+------------------------------------------------------------------+
//| BAND GEOMETRY                                                      |
//|                                                                    |
//| Parameters for the active band geometry strategy.  Port of       |
//| Python band_geometry.py + vol_band.py entry gates.                |
//|                                                                    |
//| OPTIMIZED PARAMETERS (from backtest sweep):                       |
//|   R_75: z=2.0, stop=0.10, target=1.20, trail=OFF                |
//|   R_100: z=2.0, stop=0.10, target=0.80, trail=ON (0.3)         |
//|                                                                    |
//| KEY INSIGHT: the breakeven trail has OPPOSITE effects depending   |
//| on the target multiplier:                                         |
//|   - High target (1.20, RR=12:1): trail KILLS performance         |
//|   - Moderate target (0.80, RR=8:1): trail HELPS performance      |
//|                                                                    |
//| PYTHON PARITY:                                                    |
//| Defaults match Python backtest-vol.py exactly.  Phase-10 P10-A   |
//| aligned verification reproduces trade-for-trade on the corpus.    |
//+------------------------------------------------------------------+
input group "Band Geometry"
input double InpBandZEntry          = 2.2;    // optimized: |z_dev| to trigger fade entry (was 1.0)
input double InpBandVolExtRatio     = 1.3;    // sigma must exceed this * sigma_ema
input double InpBandSigmaEmaPeriod  = 30.0;   // sigma baseline EMA
input double InpBandStopSigmaMult   = 0.12;   // optimized: stop = 0.12 * sigma_h (was 0.20)
input double InpBandTargetSigmaMult = 1.0;    // optimized: target = 1.0 * sigma_h (was 0.80)
input int    InpBandHoldSec         = 3600;   // hold horizon (1h)
input double InpBandMinRR           = 2.0;    // min reward:risk to accept
input double InpBandMaxStopPct      = 0.015;  // max stop as fraction of price
input double InpBandBreakevenFrac   = 0.00;   // R_100 optimized: trail HURTS performance

//+------------------------------------------------------------------+
//| DECISION                                                            |
//|                                                                    |
//| Parameters for the decision layer (ConfidenceEngine + ScoringEngine).
//| These gate which signals reach the risk layer.                    |
//|                                                                    |
//| CONFIDENCE:                                                        |
//|   - Raw model confidence (0-1) from online logistic model        |
//|   - NOT a probability of winning — it is a relative signal strength|
//|   - Minimum 0.55 to pass (tunable via .set files)                |
//|                                                                    |
//| SETUP QUALITY:                                                     |
//|   - 0-100 score from structure analysis                          |
//|   - Higher = more structure events supporting the signal          |
//|   - Minimum 50 to pass                                           |
//|                                                                    |
//| REWARD:RISK:                                                       |
//|   - Geometry-derived from band levels                             |
//|   - Minimum 1.5 to pass (risk-adjusted return)                   |
//+------------------------------------------------------------------+
input group "Decision"
input double InpMinConfidence     = 0.55;   // minimum decision score to act
input double InpMinSetupQuality   = 50.0;   // 0..100 minimum setup quality
input double InpMinRR             = 1.5;    // minimum expected reward:risk

//+------------------------------------------------------------------+
//| EXECUTION                                                            |
//|                                                                    |
//| Parameters for order execution and position management.           |
//| These control how orders are placed and managed in the market.    |
//|                                                                    |
//| MAGIC NUMBER:                                                      |
//|   - Separates EA trades from manual trades                       |
//|   - Must match Python EA_DEFAULT_MAGIC (7788123)                 |
//|   - Each EA instance should have a unique magic if running        |
//|     multiple symbols on the same terminal                         |
//|                                                                    |
//| SLIPPAGE & SPREAD:                                                 |
//|   - MaxSlippagePoints: maximum allowed deviation from requested   |
//|     price (50 points = 5 pips for 5-digit brokers)               |
//|   - MaxSpreadPoints: skip entry if spread exceeds this            |
//|     (SYN75 normal spread ~1000-1100 points)                       |
//|                                                                    |
//| VOLUME:                                                            |
//|   - FixedVolume > 0: use this fixed lot size                      |
//|   - FixedVolume = 0: risk-based sizing (equity * risk% / risk)   |
//+------------------------------------------------------------------+
input group "Execution"
input long   InpMagic              = DEFAULT_MAGIC_NUMBER;
input int    InpMaxSlippagePoints  = DEFAULT_MAX_SLIPPAGE_POINTS;
input int    InpMaxSpreadPoints    = 400;   // SYN75 live ~1080 pts -> tight trading gate
                                            // (400) is stricter than the 600 sanity cap.
input double InpFixedVolume        = 0.0;   // 0 = risk-based sizing

//+------------------------------------------------------------------+
//| JOURNAL / DEBUG                                                     |
//|                                                                    |
//| Parameters for trade journaling and debug logging.                |
//| The journal records every trade outcome for analytics.           |
//| Decision logs record every BUY/SELL/WAIT with reasons.           |
//+------------------------------------------------------------------+
input group "Journal"
input bool   InpJournalCsvEnabled  = true;  // append trade journal CSV
input string InpJournalFile        = "MITEMSHUB_Trades.csv";
input bool   InpDecisionLogEnabled = true;  // log every BUY/SELL/WAIT + reason

//+------------------------------------------------------------------+
//| CONFIG READ HELPERS                                                 |
//|                                                                    |
//| Typed accessors so logic files read one consistent surface.       |
//| These hide the raw input variables behind a clean API.            |
//|                                                                    |
//| USAGE:                                                            |
//|   double risk = cfgRiskPerTradePct();  // instead of InpRiskPerTradePct |
//|                                                                    |
//| BENEFIT:                                                          |
//|   - Single point of change if input names change                 |
//|   - Type safety (returns correct type)                           |
//|   - Easy to mock for testing                                     |
//+------------------------------------------------------------------+

//--- Mode & Safety
bool   cfgLiveTradingEnabled()        { return(InpLiveTradingEnabled); }
bool   cfgEmergencyStop()             { return(InpEmergencyStop); }
bool   cfgDebugMode()                 { return(InpDebugMode); }

//--- Risk Limits
double cfgRiskPerTradePct()           { return(InpRiskPerTradePct); }
double cfgMaxDailyLossPct()           { return(InpMaxDailyLossPct); }
double cfgMaxDailyDrawdownPct()       { return(InpMaxDailyDrawdownPct); }
double cfgMaxEquityDrawdownPct()      { return(InpMaxEquityDrawdownPct); }
int    cfgMaxOpenPositions()          { return(InpMaxOpenPositions); }
double cfgMaxTotalExposurePct()       { return(InpMaxTotalExposurePct); }
int    cfgMaxConsecutiveLosses()      { return(InpMaxConsecutiveLosses); }
int    cfgMaxTradesPerHour()          { return(InpMaxTradesPerHour); }
int    cfgMaxTradesPerDay()           { return(InpMaxTradesPerDay); }

//--- Regime & Volatility
int    cfgAtrPeriod()                 { return(InpAtrPeriod); }
int    cfgRegimeLookback()            { return(InpRegimeLookback); }
int    cfgHurstLookback()             { return(InpHurstLookback); }

//--- Structure
int    cfgStructureLookback()         { return(InpStructureLookback); }

//--- Strategy Toggles
bool   cfgEnableBand()                { return(InpEnableBandGeometry); }
bool   cfgEnableTrend()               { return(InpEnableTrend); }
bool   cfgEnableBreakout()            { return(InpEnableBreakout); }
bool   cfgEnableMeanReversion()       { return(InpEnableMeanReversion); }
bool   cfgEnableLiquiditySweep()      { return(InpEnableLiquiditySweep); }
bool   cfgEnablePullback()            { return(InpEnablePullback); }

//--- Band Geometry
double cfgBandZEntry()                { return(InpBandZEntry); }
double cfgBandVolExtRatio()           { return(InpBandVolExtRatio); }
double cfgBandSigmaEmaPeriod()        { return(InpBandSigmaEmaPeriod); }
double cfgBandStopSigmaMult()         { return(InpBandStopSigmaMult); }
double cfgBandTargetSigmaMult()       { return(InpBandTargetSigmaMult); }
int    cfgBandHoldSec()               { return(InpBandHoldSec); }
double cfgBandMinRR()                 { return(InpBandMinRR); }
double cfgBandMaxStopPct()            { return(InpBandMaxStopPct); }
double cfgBandBreakevenFrac()         { return(InpBandBreakevenFrac); }

//--- Decision
double cfgMinConfidence()             { return(InpMinConfidence); }
double cfgMinSetupQuality()           { return(InpMinSetupQuality); }
double cfgMinRR()                     { return(InpMinRR); }

//--- Execution
long   cfgMagic()                     { return(InpMagic); }
int    cfgMaxSlippagePoints()         { return(InpMaxSlippagePoints); }
int    cfgMaxSpreadPoints()           { return(InpMaxSpreadPoints); }
double cfgFixedVolume()               { return(InpFixedVolume); }

#endif // MITEMSHUB_CORE_CONFIG_MQH
