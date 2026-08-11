//+------------------------------------------------------------------+
//|                                      Core/Config.mqh             |
//|  MITEMSHUB AI MARKET ENGINE — every tunable input, grouped.      |
//|                                                                  |
//|  All `input` variables live here (single include).  Logic files  |
//|  read these globals; they never define their own magic numbers.  |
//|  Grouped so the MT5 inputs dialog is navigable.                  |
//+------------------------------------------------------------------+
#ifndef MITEMSHUB_CORE_CONFIG_MQH
#define MITEMSHUB_CORE_CONFIG_MQH

#include "Constants.mqh"

//--- Mode & safety -----------------------------------------------------------
input group "Mode & Safety"
input ENUM_ENGINE_MODE InpEngineMode = ENGINE_MODE_BACKTEST; // Engine mode
input bool   InpLiveTradingEnabled = false;  // LIVE execution requires explicit true
input bool   InpEmergencyStop      = false;  // EMERGENCY_STOP: no new trades
input bool   InpDebugMode          = false;  // verbose diagnostics

//--- Risk limits -------------------------------------------------------------
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

//--- Regime / volatility -----------------------------------------------------
input group "Regime & Volatility"
input int    InpAtrPeriod          = DEFAULT_ATR_PERIOD;        // ATR period
input int    InpRegimeLookback     = DEFAULT_REGIME_LOOKBACK;   // regime classification window (bars)
input int    InpHurstLookback      = 100;                      // Hurst estimation window
input double InpAtrPercentileWindow = 100.0;                   // bars for ATR percentile rank

//--- Structure ---------------------------------------------------------------
input group "Structure"
input int    InpStructureLookback = DEFAULT_STRUCTURE_LOOKBACK; // bars
input int    InpSwingLeftBars     = 3;                         // swing fractals: bars left
input int    InpSwingRightBars    = 3;                         // swing fractals: bars right
input double InpDisplacementAtrMult = 2.0;                     // displacement = body/range vs ATR mult

//--- Strategies (toggles) ----------------------------------------------------
input group "Strategies"
input bool   InpEnableBandGeometry   = true;  // validated leg (default ON)
input bool   InpEnableTrend          = false; // research — OFF until OOS validated
input bool   InpEnableBreakout       = false; // research — OFF until OOS validated
input bool   InpEnableMeanReversion  = false; // research — OFF until OOS validated
input bool   InpEnableLiquiditySweep = false; // research — OFF until OOS validated
input bool   InpEnablePullback       = false; // research — OFF until OOS validated

//--- Band geometry parameters (validated in Python §38/§47/§48) --------------
input group "Band Geometry"
input double InpBandZEntry          = 1.0;    // |z_dev| to trigger a fade entry
input double InpBandVolExtRatio     = 1.3;    // sigma must exceed this × sigma EMA
input double InpBandSigmaEmaPeriod  = 30.0;   // sigma baseline EMA
input double InpBandStopSigmaMult   = 0.20;   // stop = 0.20 × σ_h
input double InpBandTargetSigmaMult = 0.80;   // target = 0.80 × σ_h
input int    InpBandHoldSec         = 3600;   // hold horizon (1h)
input double InpBandMinRR           = 2.0;    // min reward:risk to accept
input double InpBandMaxStopPct      = 0.015;  // max stop as fraction of price
input double InpBandBreakevenFrac   = 0.30;   // MFE fraction of target → BE trail

//--- Decision ----------------------------------------------------------------
input group "Decision"
input double InpMinConfidence     = 0.55;   // minimum decision score to act
input double InpMinSetupQuality   = 50.0;   // 0..100 minimum setup quality
input double InpMinRR             = 1.5;    // minimum expected reward:risk

//--- Execution ---------------------------------------------------------------
input group "Execution"
input long   InpMagic              = DEFAULT_MAGIC_NUMBER;
input int    InpMaxSlippagePoints  = DEFAULT_MAX_SLIPPAGE_POINTS;
input int    InpMaxSpreadPoints    = 400;   // SYN75 live ~1080 pts → tight trading gate
                                            // (400) is stricter than the 600 sanity cap.
input double InpFixedVolume        = 0.0;   // 0 = risk-based sizing

//--- Journal / debug ---------------------------------------------------------
input group "Journal"
input bool   InpJournalCsvEnabled  = true;  // append trade journal CSV
input string InpJournalFile        = "MITEMSHUB_Trades.csv";
input bool   InpDecisionLogEnabled = true;  // log every BUY/SELL/WAIT + reason

//--- Config read helpers -----------------------------------------------------
// Simple typed accessors so logic files read one consistent surface.
bool   cfgLiveTradingEnabled()        { return(InpLiveTradingEnabled); }
bool   cfgEmergencyStop()             { return(InpEmergencyStop); }
bool   cfgDebugMode()                 { return(InpDebugMode); }
double cfgRiskPerTradePct()           { return(InpRiskPerTradePct); }
double cfgMaxDailyLossPct()           { return(InpMaxDailyLossPct); }
double cfgMaxDailyDrawdownPct()       { return(InpMaxDailyDrawdownPct); }
double cfgMaxEquityDrawdownPct()      { return(InpMaxEquityDrawdownPct); }
int    cfgMaxOpenPositions()          { return(InpMaxOpenPositions); }
double cfgMaxTotalExposurePct()       { return(InpMaxTotalExposurePct); }
int    cfgMaxConsecutiveLosses()      { return(InpMaxConsecutiveLosses); }
int    cfgMaxTradesPerHour()          { return(InpMaxTradesPerHour); }
int    cfgMaxTradesPerDay()           { return(InpMaxTradesPerDay); }
int    cfgAtrPeriod()                 { return(InpAtrPeriod); }
int    cfgRegimeLookback()            { return(InpRegimeLookback); }
int    cfgHurstLookback()             { return(InpHurstLookback); }
int    cfgStructureLookback()         { return(InpStructureLookback); }
bool   cfgEnableBand()                { return(InpEnableBandGeometry); }
bool   cfgEnableTrend()               { return(InpEnableTrend); }
bool   cfgEnableBreakout()            { return(InpEnableBreakout); }
bool   cfgEnableMeanReversion()       { return(InpEnableMeanReversion); }
bool   cfgEnableLiquiditySweep()      { return(InpEnableLiquiditySweep); }
bool   cfgEnablePullback()            { return(InpEnablePullback); }
double cfgBandZEntry()                { return(InpBandZEntry); }
double cfgBandVolExtRatio()           { return(InpBandVolExtRatio); }
double cfgBandSigmaEmaPeriod()        { return(InpBandSigmaEmaPeriod); }
double cfgBandStopSigmaMult()         { return(InpBandStopSigmaMult); }
double cfgBandTargetSigmaMult()       { return(InpBandTargetSigmaMult); }
int    cfgBandHoldSec()               { return(InpBandHoldSec); }
double cfgBandMinRR()                 { return(InpBandMinRR); }
double cfgBandMaxStopPct()            { return(InpBandMaxStopPct); }
double cfgBandBreakevenFrac()         { return(InpBandBreakevenFrac); }
double cfgMinConfidence()             { return(InpMinConfidence); }
double cfgMinSetupQuality()           { return(InpMinSetupQuality); }
double cfgMinRR()                     { return(InpMinRR); }
long   cfgMagic()                     { return(InpMagic); }
int    cfgMaxSlippagePoints()         { return(InpMaxSlippagePoints); }
int    cfgMaxSpreadPoints()           { return(InpMaxSpreadPoints); }
double cfgFixedVolume()               { return(InpFixedVolume); }

#endif // MITEMSHUB_CORE_CONFIG_MQH
