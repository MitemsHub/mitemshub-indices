//+------------------------------------------------------------------+
//|                                             MitemshubAI.mq5      |
//|                    MITEMSHUB AI MULTI-STRATEGY ENGINE v26.14     |
//|   Intelligent • Regime-Aware • Crash/Boom • Spike-Aware • Smart  |
//|                                                                  |
//| v26.x SERIES (2026-08-30) — see PRODUCTION_CONFIGS.md for full   |
//| details. Single fresh-build deploy line for Boom + Crash:        |
//|  v26.0 tick-fade burst guard (Crash ON / Boom OFF, per-symbol .set)
//|  v26.1-26.3 per-symbol state/review/telemetry/slip files + DAILY  |
//|     record — session counters survive re-attaches                 |
//|  v26.2 gap-through slippage journaling (realized R vs planned -1R)
//|  v26.4 event-driven close detection (OnTradeTransaction, O(1))    |
//|  v26.5 EWMA facade gate + CB strategies in the intelligence layer |
//|  v26.6 micro-balance fit (InpMicroFitPct) + live stop re-anchor   |
//|  v26.7 minute-level session cutoff (InpSessionEndOffsetMin) +     |
//|     tick-recorder flush on close                                  |
//|  v26.8 grid-searched exit geometry: SL 0.3xATR / TP 4.0xATR /     |
//|     FADE_R 0.4 / hold 6 bars (both .set files)                    |
//|  v26.9 constant-λ Poisson spike-rate model replaces the           |
//|     "time-since-spike / overdue" term (gambler's fallacy removed) |
//| v26.13 FACADE-GATE DEADLOCK FIX: the learned gate could block all |
//|     spike fades forever (expect<1.5σ with fat sigma; recovery     |
//|     required trades the gate blocked). Now: positive mean never   |
//|     blocked; quiet-day EWMA decay re-arms the gate; exploration   |
//|     budget of 3 signals after each gate close.                    |
//| v26.13 tick-fade consume-on-confirm: a rejected fade order no     |
//|     longer eats the spike (TickFadeConfirm/TickFadeRelease);      |
//|     ValidStopForModify guards every PositionModify against the    |
//|     broker stops level (retcode-10016 spam fix)                   |
//|                                                                  |
//| v25.7 CHANGES (2026-08-30):  size-scaled fade entry               |
//|  1. Retrace entry threshold scales with spike size on BOTH      |
//|     paths: lo = clamp(0.30*sqrt(12/size), 0.18, 0.40). Big      |
//|     spikes enter on shallower retrace (they decay slowly);      |
//|     small spikes demand a deeper retrace (junk filter).         |
//|  2. Backtest: tick path +17% expectancy on the recorded night;  |
//|     60d M5: +89 trades, expectancy unchanged, PF 4.19.          |
//| v25.6 CHANGES (2026-08-30):  filter tuning from evidence tally    |
//|  1. Fade retrace ceiling 0.50 -> 0.60 (overshoot was the #2      |
//|     entry blocker; 60d sweep: PF 4.06->4.22, +216 trades).       |
//|  2. Tick fast-fade timeout 600s -> 900s (big spikes retrace      |
//|     slowly; live sweep: 5 -> 9 entries on the recorded night).   |
//|  3. Strategy fade-entry default aligned to deployed 0.30.        |
//| v25.5 CHANGES (2026-08-30):                                       |
//|  1. Tick recorder opens CSV with FILE_SHARE_READ — external      |
//|     tools can analyze the live file while the EA writes it.      |
//|  2. Flush cadence tightened: 100 ticks / 10s (was 500 / 60s).    |
//| v25.4 CHANGES (2026-08-30):                                       |
//|  1. TICK-TRIGGERED FAST FADE: fades fire on the tick spike       |
//|     itself (jump >= 3pts) once retrace enters the window —       |
//|     enters ~1-3 min earlier than the M5-close path.              |
//|  2. Tick analyzers now fed EVERY tick (was: once per M5 bar).    |
//|  3. Micro-fade risk scaling applies to tick fades too.           |
//| v25.3 CHANGES (2026-08-30):                                       |
//|  1. MICRO-FADE TIER: spike threshold 2.8→2.2x avg body; small    |
//|     spikes trade at reduced risk (0.5x at 2.2x → 1.0x at 3.0x).  |
//|  2. Per-spike rejection logging: [CB-SKIP] shows exactly why     |
//|     each spike produced no trade (ATR/dir/retrace/R:R/cooldown). |
//|  3. APP_VERSION single-source: version string can never drift.   |
//| v25.1 CHANGES (2026-08-29):                                       |
//|  1. CRASH/BOOM MODE: full spike detection, post-spike fade,      |
//|     grind continuation, dynamic risk sizing, symbol calibration. |
//|  2. TICK-PATTERN ANALYZER: monitors individual tick behavior      |
//|     for spike precursors (speed, direction, size, pause, entropy).|
//|  3. MULTI-TIMEFRAME CONFIRM: M1+M5+M15 must agree (2/3).        |
//|  4. TIME-OF-DAY AWARENESS: learns spike clustering by hour.      |
//|  5. SYMBOL CALIBRATION: auto-detects Boom/Crash 300/500/1000.    |
//|  6. CB-SPECIFIC EXITS: spike-aware trailing, faster profit lock. |
//|  7. FIXED: indicator handle leaks (created once, reused).        |
//|  8. FIXED: DAILY-HALT uses realized P&L, not equity comparison.  |
//|  9. FIXED: manual close detection uses deal history price.       |
//|                                                                  |
//| v23.0 CHANGES (2026-08-27):                                      |
//|  1. CROSS-INSTANCE STACKING GUARD: blocks new entries when ANY   |
//|     fleet magic already holds a position on the same symbol.     |
//|  2. STATE PERSISTENCE: trades, wins, losses, R-multiples, and    |
//|     consecutive-loss counter survive EA restarts via file I/O.   |
//|  3. GRADUATED TIME EXIT: early-cuts losers that never got        |
//|     profitable; extends hold time for winners that are running.  |
//|  4. PROFIT LOCK: if a trade reached +1R then reverses below      |
//|     InpProfitLockR, close and bank the remainder.                |
//|  5. SESSION FILTER: block entries outside server-hour window.     |
//|  6. VOLUME SCALING: reduce lot size by InpScaleFactor per        |
//|     consecutive loss (floor at InpMinVolScale) — prevents the    |
//|     "big loss erases many small wins" pattern.                   |
//|  7. RecoverPosition now estimates bars_held from entry time.     |
//|  8. Trailing/breakeven defaults tuned for V75/V100 M15 geometry. |
//|                                                                  |
//| v22.0 FIXES (2026-08-25):                                        |
//|  - Pause auto-reset on session-day rollover                      |
//|  - Daily-loss halt wired + effective-risk guardrail              |
//|  - Band-fade leg (VALIDATED), momentum demotion                  |
//|  - Entry/regime TF overrides, telemetry journal                  |
//|  - Account-wide exposure guard across fleet magics               |
//+------------------------------------------------------------------+
#define APP_VERSION "26.14"

//--- v25.2: single source of truth for the version string.
//--- #property version, every log tag, and every order comment derive from
//--- APP_VERSION — bump THIS line only; nothing else can drift.
const string VTAG = "[v" + APP_VERSION + "] ";

#property copyright "MITEMSHUB AI"
#property version   APP_VERSION
#property strict

#include <Trade\Trade.mqh>
#include "CrashBoom/CrashBoomEngine.mqh"
#include "CrashBoom/TickRecorder.mqh"
// v26.9-phase1: modular market engine — EGARCH conditional-vol forecaster
// (locked against the Python reference by Tests/Phase10Tests.mq5).
#include "Market/GarchForecaster.mqh"
CTrade trade;
CTickRecorder g_tick_rec;   // v25.1: always-on tick microstructure archive

#define TELEM_BASE "MitemshubAI_v23_telemetry"   // v26.1: per-symbol suffix appended
#define STATE_BASE "MitemshubAI_state"           // v26.1: per-symbol suffix appended

// v26.1: per-INSTANCE file names — Boom and Crash charts must never share
// learning state. A shared state.csv let each instance overwrite the other's
// counters, and one merged review.csv mixed unrelated trades (Boom's Aug-28
// trades appeared on the Crash HUD). Files become e.g.
//   MitemshubAI_state_Crash_1000_Index.csv
//   MitemshubAI_review_Boom_1000_Index.csv
//   MitemshubAI_v23_telemetry_Boom_1000_Index.jsonl
string SymbolTaggedFile(const string base, const string ext)
{
   string tag = _Symbol;
   StringReplace(tag, " ", "_");
   return StringFormat("%s_%s%s", base, tag, ext);
}

//+------------------------------------------------------------------+
//| ENUMS                                                              |
//+------------------------------------------------------------------+
enum ENUM_REGIME { REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING, REGIME_HIGH_VOL, REGIME_NO_TRADE };

//+------------------------------------------------------------------+
//| INPUTS                                                             |
//+------------------------------------------------------------------+
input group "=== Strategy Selection ==="
input bool   InpUsePullback      = true;     // EMA Pullback (Trend)
input bool   InpUseBreakout      = true;     // Breakout
input bool   InpUseMomentum      = true;     // Momentum
input bool   InpUseMeanRevert    = true;     // Mean Reversion (Ranging only)
input bool   InpUseBandFade      = true;     // Band Fade (VALIDATED: fade |z|>=2 sigma extensions)
input int    InpMinScore         = 3;        // Minimum score to enter
input bool   InpRequire2Strats   = false;    // Require at least 2 strategies agree
input bool   InpMomentumStandalone = false;  // Allow a momentum candle ALONE to trigger entry

input group "=== Regime & Volatility ==="
input int    InpEmaFast          = 20;
input int    InpEmaMid           = 50;
input int    InpEmaSlow          = 100;
input double InpMinEmaSep        = 0.22;
input int    InpAtrPeriod        = 14;
input int    InpAtrLookback      = 120;
input double InpAtrLowPct        = 8.0;
input double InpAtrHighPct       = 90.0;

input group "=== Strategy Parameters ==="
input double InpPullbackMin      = 0.30;
input double InpPullbackMax      = 2.20;
input double InpBreakoutBuffer   = 0.10;
input int    InpBreakoutBars     = 12;
input double InpMomBodyMin       = 0.45;
input double InpRsiOversold      = 32.0;
input double InpRsiOverbought    = 68.0;

input group "=== Band Fade (validated edge) ==="
input double InpBandZEntry       = 2.0;      // |z_dev| fade trigger (R_75/R_100 optimized)
input double InpBandVolExtRatio  = 1.25;     // sigma must exceed this x sigma EMA baseline
input int    InpBandSigmaEmaLen  = 30;       // sigma baseline EMA length (bars)
input double InpBandStopSigmaMult  = 0.10;   // stop   = 0.10 x sigma_h (validated)
input double InpBandTargetSigmaMult= 0.80;   // target = 0.80 x sigma_h (R_100; R_75 use 1.20)
input int    InpBandHoldSec      = 3600;     // band hold horizon (seconds)
input double InpBandMinRR        = 2.5;      // min reward:risk for band plans
input double InpBandMaxStopPct   = 0.015;    // reject band plan if stop > 1.5% of price

// v26.4: SPIKE SLIPPAGE — realized R vs the planned -1R stop.
// Boom/Crash spikes gap the price and stops fill at the post-spike quote, so
// a "protected" -1R can realize -4R..-10R. These counters make the tail
// explicit in the journal and the HUD instead of hiding it inside g_total_r.
int    g_gap_loss_n     = 0;      // closes that lost MORE than the planned stop
double g_gap_loss_r_sum = 0.0;    // realized R summed over gap-loss closes
int    g_stop_n         = 0;      // closes realized at/beyond the planned stop
double g_slip_r_sum     = 0.0;    // sum of (realized R - planned R) over all closes

//--- Record slippage for one closed trade (called from BOTH close paths)
void RecordTradeSlippage(double actual_r, string exit_type)
{
   double planned = -1.0;
   g_slip_r_sum += (actual_r - planned);
   if(actual_r <= -0.9)          // stop territory (covers trails/BE stops too)
      g_stop_n++;
   if(actual_r < planned)
   {
      g_gap_loss_n++;
      g_gap_loss_r_sum += actual_r;
      PrintFormat(VTAG+"SPIKE SLIPPAGE: realized %+.2fR vs planned -1.00R (%s exit) — gap-through loss",
                  actual_r, exit_type);
      Telem("slippage", StringFormat("\"sym\":\"%s\",\"r\":%.3f,\"planned\":-1.0,\"exit\":\"%s\",\"gap\":true",
                  _Symbol, actual_r, exit_type));
   }
   SaveSlipState();              // v26.2: persist after every close (both paths)
}

//+------------------------------------------------------------------+
//| v26.2: persist slip counters per symbol (survive restarts)        |
//+------------------------------------------------------------------+
void SaveSlipState()
{
   int h=FileOpen(SymbolTaggedFile("MitemshubAI_slip", ".csv"), FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   FileWriteString(h, StringFormat("%d,%.4f,%d,%.4f\n",
                   g_gap_loss_n, g_gap_loss_r_sum, g_stop_n, g_slip_r_sum));
   FileClose(h);
}

void LoadSlipState()
{
   int h=FileOpen(SymbolTaggedFile("MitemshubAI_slip", ".csv"), FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   string line=FileReadString(h);
   FileClose(h);
   if(StringLen(line)==0) return;
   string p[];
   if(StringSplit(line, ',', p) >= 4)
   {
      g_gap_loss_n     = (int)StringToInteger(p[0]);
      g_gap_loss_r_sum = StringToDouble(p[1]);
      g_stop_n         = (int)StringToInteger(p[2]);
      g_slip_r_sum     = StringToDouble(p[3]);
      PrintFormat(VTAG+"SPIKE SLIPPAGE restored: gap-through %d (avg %+.2fR) | cum slip %+.2fR",
                  g_gap_loss_n,
                  (g_gap_loss_n > 0 ? g_gap_loss_r_sum / g_gap_loss_n : 0.0),
                  g_slip_r_sum);
   }
}

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.005;    // TARGET risk fraction (min-lot floor may force more)
input double InpMaxEffectiveRiskPct = 20.0;  // HARD CAP: skip entry if real min-lot risk > this % of equity
input double InpMaxTotalRiskPct  = 15.0;     // ACCOUNT GUARD: max SUMMED open risk (all fleet magics) as % of equity
input double InpMicroFitPct      = 1.5;      // v26.6: if min-lot clamping overshoots risk (micro balance), shrink SL/TP so effective risk <= this % of equity (0=off)
input string InpFleetMagicsCSV   = "7788010,7788025,7788050,7788075,7788100";
input double InpTpMult           = 2.4;
input int    InpMaxHoldBars      = 20;       // v23: raised from 14 — give winners room (20 bars = 5hr on M15)
input double InpMaxDailyLossPct  = 0.0;     // 0 = daily-loss halt DISABLED (was 0.03; user request 2026-08-30). DailyLossHalted() returns false when <= 0.
input int    InpMaxConsecLoss    = 3;        // v23: lowered from 6 — pause sooner, preserve capital
input int    InpCoolDownBars     = 3;
input bool   InpUseTrailing      = true;
input double InpTrailStartR      = 1.0;      // trailing starts once trade is +1R
input double InpTrailDistR       = 0.7;      // v23: tightened from 0.9 — lock profit sooner
input bool   InpUseBreakeven     = true;
input double InpBeTriggerR       = 1.0;      // move SL to entry at +1R

// v26.14: meta-labeling P(win) size multipliers (see scripts/meta_label_trainer.py)
input bool   InpUseMetaLabel     = false;    // Scale risk by learned P(win) regime table (0=off)
input string InpMetaLabelCSV     = "meta_label_regime_table.csv"; // File in MQL5\\Files, columns: regime,direction,n,win_rate,avg_r,multiplier,note

input group "=== GARCH Vol Engine (v26.9 phase 1) ==="
input bool   InpUseGarch         = true;     // EGARCH conditional-vol as the sigma source (fallback: legacy stddev if disabled/fails)
input int    InpGarchWarmupBars  = 50;       // Observations before the GARCH forecast is trusted (GARCH_BUFFER_OBSERVATIONS)

input group "=== Execution ==="
input string InpEntryTFOverride  = "CURRENT"; // Entry timeframe: CURRENT,M1,M5,M15,M30,H1,H4,D1
input string InpRegimeTFOverride = "CURRENT"; // Regime timeframe (default = one step above entry)
input long   InpMagic            = 7788211;
input int    InpMaxSlippagePts   = 50;
input int    InpWarmupBars       = 250;
input bool   InpDrawDashboard    = true;
input bool   InpDrawSignals      = true;
input bool   InpLiveExecution    = true;
input int    InpMaxTradesPerDay  = 0;        // 0 = DISABLED (v26.14: boundless opportunities - no daily trade cap)

input group "=== Intelligence & Safety (v23) ==="
input int    InpSessionStartHour = 6;        // Server hour to start trading (0-23)
input int    InpSessionEndHour   = 21;       // Server hour to stop trading (0-23)
input int    InpSessionEndOffsetMin = 45;    // v26.7: entries blocked this many minutes BEFORE the end hour (last entry ≤ 20:15 for end 21)
input int    InpSameSymbolMaxPos = 1;        // Max open positions on this symbol (all magics)
input bool   InpGraduatedExit    = true;     // Enable graduated time exit
input int    InpEarlyCutBars     = 6;        // Bars at which to check for early loss cut
input double InpEarlyCutMaxR     = -0.4;     // Close if R below this at early-cut check
input double InpExtendWinMult    = 1.5;      // Extend hold limit for winning trades
input bool   InpScaleAfterLoss   = true;     // Scale down volume after consecutive losses
input double InpScaleFactor      = 0.75;     // Volume multiplier per consecutive loss
input double InpMinVolScale      = 0.30;     // Floor for volume scaling
input double InpProfitLockR      = 0.5;      // Lock profit if trade reached 1R+ then fell to this R

input group "=== Execution Telemetry (v26.4) ==="
input bool   InpUseOnTradeTransaction = true; // Event-driven close detection (O(1) deals; polling fallback if off/fails)

// v26.5: CB strategies in the intelligence layer.
// PostTradeReview's strategy table only knew PB/BO/MOM/MR/BF, so the
// strategies that do ALL Crash/Boom trading (CB-TICKFADE, CB-FADE, CB-GRIND)
// were invisible to the self-review system: STRAT rows stayed at zero while
// trades accumulated, and auto-disable could never judge them (Aug-30 state
// file: 6 closed CB trades, all STRAT counters 0.0).
#define CB_STRAT_N 3
input bool   InpCBLearnStrategies = true;    // Track CB fade/grind expectancy + auto-disable
input int    InpCBMinTradesToJudge = 20;     // Min CB trades before auto-disable can act
input double InpCBMinExpectancy   = -0.10;    // Disable a CB mode below this expectancy (R/trade)

input group "=== Crash/Boom Mode (v24) ==="
input bool   InpCrashBoomMode    = false;    // Enable Crash/Boom trading mode
input bool   InpIsCrashIndex     = false;    // true = Crash (1000/500/300), false = Boom (1000/500/300)
input bool   InpCBMicroFade      = true;     // v25.3: reduce risk on small (micro) spikes

// v26.10: AUTO per-symbol resolution for the CB numeric parameters — the same
// cure as InpCBBurstGuardMode, extended to the exit geometry. AUTO (compiled
// default) = the symbol calibration profile in CrashBoomCalibration.mqh (the
// deployed v26.8 grid-search values). CUSTOM = the explicit input below wins
// on BOTH charts. A stale stored chart input can no longer poison any of
// these: unknown legacy inputs drop out, the new mode inputs default to AUTO,
// and the profile ships the policy. Resolution is logged at init as
// [CB-PARAM] lines — audit at a glance which source decided each value.
enum ENUM_CB_PARAM_SOURCE { CB_PARAM_AUTO=0,     // Auto: symbol calibration profile
                            CB_PARAM_CUSTOM=1 }; // Custom: explicit input wins
input ENUM_CB_PARAM_SOURCE InpCBSpikeThresholdMode = CB_PARAM_AUTO; // Spike threshold source
input double InpCBSpikeThreshold = 2.2;      // (CUSTOM) body ratio to count as spike (v25.3: 2.2x avg)
input ENUM_CB_PARAM_SOURCE InpCBMaxSpikeProbMode = CB_PARAM_AUTO;   // Max spike prob source
input double InpCBMaxSpikeProb   = 0.70;     // (CUSTOM) block entries above this spike probability
input ENUM_CB_PARAM_SOURCE InpCBFadeRMode        = CB_PARAM_AUTO;   // Fade R source
input double InpCBFadeR          = 0.4;      // (CUSTOM) fade entry at 0.4R into retrace (v26.8)
input ENUM_CB_PARAM_SOURCE InpCBFadeSLMode       = CB_PARAM_AUTO;   // Fade SL source
input double InpCBFadeSL         = 0.3;      // (CUSTOM) fade stop = 0.3x ATR (v26.8)
input ENUM_CB_PARAM_SOURCE InpCBFadeTPMode       = CB_PARAM_AUTO;   // Fade TP source
input double InpCBFadeTP         = 4.0;      // (CUSTOM) fade target = 4.0x ATR (v26.8)

input group "=== Tick Fast-Fade (v25.4) ==="
input bool   InpCBTickFade      = true;     // Fire fades on the tick spike itself (no M5 wait)
input double InpCBTickSpikePts  = 3.0;      // Min tick jump (points) that counts as a spike
input int    InpCBTickFadeTOSec = 900;      // Fast-fade pending timeout (v25.6: 900s — big spikes retrace slowly)
// v26.10: spike-threshold / max-spike-prob / fade R / SL / TP moved to the
// "CB Parameters — AUTO per-symbol resolution" group above (with AUTO/CUSTOM
// source selectors).
input double InpCBBaseRisk       = 0.5;      // Base risk % for Crash/Boom trades
input int    InpCBMaxConsecLoss  = 4;        // v26.5: pause CB mode after N consec losses (day-scoped)
input double InpCBMinRisk        = 0.15;     // Min risk % during high spike probability
input bool   InpCBEnableGrind    = false;    // Enable grind continuation leg (default: fade-only)
input bool   InpCBRequireSpikeDirection = true; // Only fade correctly directed spike candles
input double InpCBMinATRPoints   = 0.0;     // Optional minimum ATR in points; 0 disables
// v26.9: smart per-symbol burst-guard default. AUTO is resolved INSIDE the
// engine (Crash → ON, Boom → OFF — the §7 offline replay verdict in
// EA_UPGRADE_RESEARCH.md), so a chart that never loads its preset still
// ships the right policy. This kills the Aug-31 failure mode where the Boom
// chart ran on stale stored inputs with guard=true while the .set said off.
// Explicit ON/OFF are hard overrides and always win over AUTO.
enum ENUM_CB_BURST_GUARD { CB_BURSTGUARD_AUTO=0,  // Auto: smart per-symbol (Crash ON, Boom OFF)
                           CB_BURSTGUARD_ON=1,    // Force ON (explicit override)
                           CB_BURSTGUARD_OFF=2 }; // Force OFF (explicit override)
input ENUM_CB_BURST_GUARD InpCBBurstGuardMode = CB_BURSTGUARD_AUTO; // Burst guard mode (AUTO = Crash ON / Boom OFF; ON/OFF = override)
input int    InpCBBurstWindowSec = 1800;    // Burst window (s): count spikes inside
input int    InpCBBurstMaxSpikes = 2;       // Block fades when spikes-in-window >= this
input int    InpCBBurstMinGapSec = 600;     // Block fades when prev-spike gap < this (s); 0 disables

input group "=== Tick Recorder (v25.1) ==="
input bool   InpTickRecordEnabled = true;   // Always-on tick recorder (microstructure archive)
input int    InpTickFlushTicks    = 100;     // Flush buffer every N ticks (v25.5: live-analysis cadence)
input int    InpTickFlushSeconds  = 10;      // Max seconds between flushes (v25.5)

input group "=== Self-Review Intelligence (v23.1) ==="
input int    InpStrategyReviewN  = 10;       // Check strategy performance every N trades
input int    InpRegimeReviewN    = 20;       // Check regime performance every N trades
input int    InpTimeReviewN      = 30;       // Check time-block performance every N trades
input int    InpMinTradesToJudge = 15;       // Minimum trades before auto-disabling a strategy
input double InpMinExpectancy    = 0.0;      // Min expectancy (R/trade) to keep a strategy active
input bool   InpAutoDisableStrat = true;     // Auto-disable strategies with negative expectancy
input bool   InpAutoBlockTime    = false;    // Auto-block worst-performing time blocks
input bool   InpCBPersistLearning= true;     // v26.5: CB fade/grind expectancy survives restarts (learned gating)

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES g_tf_entry, g_tf_regime;
int hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;
int hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E, hBB_E;

double g_eq=0, g_peak_eq=0, g_daily_pnl=0;
datetime g_day_start=0;
double g_day_start_eq=0;
int g_cooldown=0, g_consec_loss=0, g_trades_today=0;
bool g_paused=false;
ENUM_REGIME g_regime = REGIME_NO_TRADE;

// band-fade state
double g_sigma_ema=0;
bool   g_sigma_init=false;

// v22 TELEMETRY
double g_sigma_now=0, g_z_dev=0, g_exp_ratio=0;
string g_fired_legs="", g_last_skip="", g_last_cb_skip="";

//--- v26.9 phase 1: GARCH conditional-volatility forecaster (modular Market
//--- engine, phase-10 locked against the Python reference). Bar-driven only
//--- (Update once per entry-TF bar); zero per-tick cost. Fallback: if the
//--- module fails to deliver a valid sigma (bad price data or invalid
//--- module output), the legacy PerBarSigma stddev keeps running unchanged.
CGarchForecaster  g_garch;                    // calibrated-fixed mode (default ctor)
bool              g_garch_ok     = true;      // sticky: false once a persistent failure is seen
bool              g_garch_init_note = false;   // one-time "GARCH ready" log
int               g_garch_fail_n = 0;         // consecutive failed updates (diagnostics)
double            g_garch_sigma  = 0.0;      // last accepted sigma (relative, per-bar)
double            g_garch_z      = 0.0;      // last standardized shock z_t (telemetry)

// per-signal exit geometry
bool   g_sig_is_band=false;
int    g_last_band_dir=0;
double g_sig_sl_atr=0, g_sig_tp_atr=0;
double g_risk_money=0;
int    g_max_hold=14;

// trade performance (v23: persisted to file)
int g_trades=0, g_wins=0, g_losses=0;
int g_target_exits=0, g_time_exits=0, g_stop_exits=0, g_early_cuts=0;
double g_total_r=0;

// open position state
ulong g_ticket=0;
int g_dir=0;
double g_entry=0, g_sl=0, g_tp=0, g_orig_risk=0, g_position_volume=0;
datetime g_entry_time=0;
int g_bars_held=0;

// v23: high-water R mark for graduated exit / profit lock
double g_high_water_r=0;

double atr_hist[];
int atr_hist_count=0;
string dash_names[26];

// account-wide exposure guard
long g_fleet_magics[];
int    g_fleet_n=0;

// v23: cumulative session P&L (money, not R)
double g_session_pnl=0;

// v23.1 INTELLIGENCE LAYER — self-review after every trade
#define REVIEW_BASE "MitemshubAI_review"         // v26.1: per-symbol suffix appended

// v26.5 strategy table: 8 slots — 0=PB,1=BO,2=MOM,3=MR,4=BF (classic)
// + 5=CB-TICKFADE,6=CB-FADE,7=CB-GRIND (Crash/Boom modes).
// v26.9-fix (2026-08-31): these arrays stayed [5] when the 8-slot table was
// introduced — every walker (CheckStrategyPerformance, the LoadReviewState
// echo, SaveReviewState, the HUD Intel line, PostTradeReview) then crashed
// with "array out of range" at i=5, aborting OnInit/OnTick on both charts
// and leaving the HUD labels without text (the "Label" spam). Resized to 8.
// v26.11-fix (2026-08-31): sizes are now NAMED CONSTANTS shared by every
// declaration, walker loop, loader guard, and name table — a size-vs-loop
// drift can no longer be reintroduced silently — and SelfTestFixedArrays()
// re-verifies all of it at init, fail-closed, BEFORE the first file-indexed
// write can reach the tables.
#define STRAT_SLOTS   8   // 5 classic + 3 CB modes
#define REGIME_SLOTS  5
#define TIME_SLOTS    5

// v26.11: name tables hoisted to constant globals sized by the same constants
// (they were duplicated inline in CheckStrategyPerformance/CheckRegime-
// Performance and AGAIN in the HUD — a third drift hazard).
const string STRAT_NAMES[STRAT_SLOTS]   = {"PB","BO","MOM","MR","BF","CB-TICKFADE","CB-FADE","CB-GRIND"};
const string REGIME_NAMES[REGIME_SLOTS] = {"BULLISH","BEARISH","RANGING","HIGH_VOL","NO_TRADE"};

double g_strat_trades[STRAT_SLOTS];     // total trades per strategy
double g_strat_wins[STRAT_SLOTS];       // wins per strategy
double g_strat_total_r[STRAT_SLOTS];    // cumulative R per strategy
bool   g_strat_enabled[STRAT_SLOTS];    // auto-disable flag

// Regime performance tracking (index 0=BULL,1=BEAR,2=RANGE,3=HVOL,4=NOTRADE)
double g_regime_trades[REGIME_SLOTS];
double g_regime_wins[REGIME_SLOTS];
double g_regime_total_r[REGIME_SLOTS];

// Time-block tracking (index 0=06-10,1=10-14,2=14-18,3=18-21,4=other)
double g_time_trades[TIME_SLOTS];
double g_time_wins[TIME_SLOTS];
double g_time_total_r[TIME_SLOTS];

// Last review counters
int g_last_strategy_review=0;
int g_last_regime_review=0;
int g_last_time_review=0;

// Current signal context (set by GenerateSignal, used by ReviewTrade)
string g_last_strategy="NONE";
string g_last_exit_type="NONE";

// v26.12: order-rejection accounting — quantifies lost fade opportunities so
// the offline loop can value them (Aug-30: 7 rejected Boom fades were invisible
// to every learning table; the offline replay had to reconstruct them by hand
// from the Experts log + broker journal).
int g_cb_reject_total   = 0;   // lifetime: all failed/aborted CB order sends
int g_cb_reject_today   = 0;   // today: reset with the daily counters
int g_cb_reject_streak  = 0;   // consecutive rejections without an accepted order
string g_cb_reject_last = "";  // last rejection: "retcode=10016" / "abort-tp-outran"

// v26.14: meta-labeling P(win) size multipliers — loaded from
// data/meta_label_regime_table.csv (produced by scripts/meta_label_trainer.py).
// Keyed by (regime, direction); the multiplier scales base risk for new entries.
#define META_LABEL_MAX_ROWS 16
string g_ml_regime[META_LABEL_MAX_ROWS];
int    g_ml_dir[META_LABEL_MAX_ROWS];
double g_ml_mult[META_LABEL_MAX_ROWS];
int    g_ml_rows = 0;

// v24: Crash/Boom engine
CCrashBoomEngine g_cb;

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES GetRegimeTF(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return PERIOD_M5;
      case PERIOD_M5:  return PERIOD_M30;
      case PERIOD_M15: return PERIOD_H1;
      case PERIOD_M30: return PERIOD_H4;
      case PERIOD_H1:  return PERIOD_H4;
      case PERIOD_H4:  return PERIOD_D1;
      default:         return PERIOD_D1;
   }
}

//+------------------------------------------------------------------+
//| v26.9: STARTUP SELF-CHECK — one glanceable banner of the v26.x    |
//| switches that drove the Aug-30 stale-chart incidents. Every row   |
//| carries the deployed expectation, so a chart running stale stored |
//| inputs is visible in the Experts log without opening the dialog.  |
//| (The banner itself only exists in fresh builds — its presence is  |
//| also a binary-freshness marker.)                                  |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| v26.10: resolve one CB numeric parameter (AUTO = calibration      |
//| profile, CUSTOM = explicit input wins) and log the decision so    |
//| the init log shows exactly which source shipped each value.       |
//+------------------------------------------------------------------+
//--- v26.10: resolved CB parameter values + source flags (filled by
//--- ResolveCBParam), consumed by the policy self-check below
double g_cb_res[5];
bool   g_cb_custom[5];
const string g_cb_names[5] = {"spike-thresh", "max-spike-prob", "fade-R", "fade-SL", "fade-TP"};

double ResolveCBParam(ENUM_CB_PARAM_SOURCE mode, double auto_val, double custom_val,
                      const string label, const int slot)
{
   if(mode == CB_PARAM_CUSTOM)
   {
      g_cb_res[slot]    = custom_val;
      g_cb_custom[slot] = true;
      PrintFormat(VTAG+"[CB-PARAM] %-14s = %.2f (explicit override)", label, custom_val);
      return custom_val;
   }
   g_cb_res[slot]    = auto_val;
   g_cb_custom[slot] = false;
   PrintFormat(VTAG+"[CB-PARAM] %-14s = %.2f (AUTO: %s calibration profile)",
               label, auto_val, InpIsCrashIndex ? "Crash" : "Boom");
   return auto_val;
}

void PrintStartupSelfCheck()
{
   string halt = (InpMaxDailyLossPct <= 0.0)
      ? "OFF"
      : StringFormat("ON %.1f%%", InpMaxDailyLossPct * 100.0);
   string bg;
   if(!InpCrashBoomMode)                             bg = "n/a (non-CB chart)";
   else if(InpCBBurstGuardMode == CB_BURSTGUARD_ON)  bg = "ON (explicit override)";
   else if(InpCBBurstGuardMode == CB_BURSTGUARD_OFF) bg = "OFF (explicit override)";
   else if(InpIsCrashIndex)                          bg = "AUTO -> ON (Crash policy)";
   else                                              bg = "AUTO -> OFF (Boom policy)";
   string mf = (InpMicroFitPct <= 0.0) ? "OFF" : StringFormat("%.1f%%", InpMicroFitPct);

   Print(VTAG+"SELF-CHECK — key v26.x switches ('<' = deployed expectation):");
   PrintFormat(VTAG+"  DailyHalt    = %-26s < expect OFF (0%% — user request 2026-08-30)", halt);
   PrintFormat(VTAG+"  BurstGuard   = %-26s < Crash AUTO->ON / Boom AUTO->OFF (v26.9 policy)", bg);
   PrintFormat(VTAG+"  MicroFit     = %-26s < expect 1.5%% on CB charts (0 = stale v26.5- inputs)", mf);
   PrintFormat(VTAG+"  LambdaModel  = %-26s < built-in ON (v26.9; λ trusted at 3 learned gaps)", "ON (built-in)");
   PrintFormat(VTAG+"  CloseDetect = %-26s < expect ON (v26.4 event-driven closes)",
               InpUseOnTradeTransaction ? "ON (event-driven)" : "OFF (polling fallback)");
   PrintFormat(VTAG+"  Rejects      = %-26s < counts lost fade entries (v26.12); today=%d streak=%d",
               StringFormat("%d total", g_cb_reject_total), g_cb_reject_today, g_cb_reject_streak);
   int n_custom = (InpCBSpikeThresholdMode==CB_PARAM_CUSTOM ? 1 : 0)
                + (InpCBMaxSpikeProbMode  ==CB_PARAM_CUSTOM ? 1 : 0)
                + (InpCBFadeRMode         ==CB_PARAM_CUSTOM ? 1 : 0)
                + (InpCBFadeSLMode        ==CB_PARAM_CUSTOM ? 1 : 0)
                + (InpCBFadeTPMode        ==CB_PARAM_CUSTOM ? 1 : 0);
   PrintFormat(VTAG+"  CB-Params    = %-26s < AUTO=calibration profile (v26.8 geometry), CUSTOM=input wins",
               n_custom==0 ? "all AUTO (profile)" : StringFormat("%d/5 CUSTOM", n_custom));
}

//+------------------------------------------------------------------+
//| v26.10: POLICY SELF-CHECK — compare the RESOLVED config against   |
//| the .set-declared deployed policy and warn on any mismatch.       |
//| The POLICY_* constants below are the runtime mirror of            |
//| MitemshubAI_{BOOM,CRASH}1000_CB.set: whenever the .set policy     |
//| changes, update these constants in the SAME commit so the check   |
//| stays meaningful. An intentional one-off override is allowed but  |
//| is made LOUD here — overrides must never be silent again (the     |
//| Aug-30/31 stale-input incidents were exactly silent drifts).      |
//+------------------------------------------------------------------+
#define POLICY_GUARD_CRASH    true     // Crash 1000: burst guard ON  (v26.0/v26.9 §7 verdict)
#define POLICY_GUARD_BOOM     false    // Boom 1000: burst guard OFF (v26.0/v26.9 §7 verdict)
#define POLICY_SPIKE_THRESH   2.2      // InpCBSpikeThreshold
#define POLICY_MAX_PROB       0.70     // InpCBMaxSpikeProb
#define POLICY_FADE_R         0.4      // InpCBFadeR (v26.8 grid-search)
#define POLICY_FADE_SL        0.3      // InpCBFadeSL xATR (v26.8)
#define POLICY_FADE_TP        4.0      // InpCBFadeTP xATR (v26.8)
#define POLICY_TICK_FADE      true     // InpCBTickFade
#define POLICY_TICK_PTS       3.0      // InpCBTickSpikePts
#define POLICY_TICK_TO_SEC    900      // InpCBTickFadeTOSec
#define POLICY_MAX_HOLD_BARS  6        // InpMaxHoldBars (1800s hold)
#define POLICY_BASE_RISK      0.30     // InpCBBaseRisk (both charts)
#define POLICY_MICRO_FADE     true     // InpCBMicroFade
#define POLICY_REQ_SPIKE_DIR  true     // InpCBRequireSpikeDirection
#define POLICY_DAILY_LOSS     0.0      // InpMaxDailyLossPct — halt OFF (user request 2026-08-30)
#define POLICY_MICRO_FIT      1.5      // InpMicroFitPct (percent units)
#define POLICY_CLOSE_DETECT   true     // InpUseOnTradeTransaction (v26.4)

int    g_pol_ok = 0, g_pol_total = 0;
string g_pol_mism = "";

void PolRow(const string name, const string resolved, const string declared,
            const bool ok, const string fix_hint)
{
   g_pol_total++;
   string line = StringFormat("  %-14s resolved=%-18s declared=%-10s", name, resolved, declared);
   if(ok) { line += " ok"; g_pol_ok++; }
   else
   {
      line += "  <-- MISMATCH";
      g_pol_mism += StringFormat("%s: resolved %s vs declared %s%s; ",
                                 name, resolved, declared,
                                 fix_hint == "" ? "" : " — " + fix_hint);
   }
   Print(VTAG+line);
}

void RunPolicySelfCheck()
{
   if(!InpCrashBoomMode)
   {
      Print(VTAG+"[POLICY] self-check n/a (non-CB chart)");
      return;
   }
   string sym = _Symbol;
   StringToUpper(sym);
   if(StringFind(sym, "1000") < 0)
   {
      PrintFormat(VTAG+"[POLICY] no declared policy table for %s — self-check skipped (Boom/Crash 1000 only)",
                  _Symbol);
      return;
   }

   g_pol_ok = 0; g_pol_total = 0; g_pol_mism = "";
   const bool   decl_guard = InpIsCrashIndex ? POLICY_GUARD_CRASH : POLICY_GUARD_BOOM;
   const string set_file   = InpIsCrashIndex ? "MitemshubAI_CRASH1000_CB.set" : "MitemshubAI_BOOM1000_CB.set";

   Print(VTAG+"[POLICY] resolved config vs .set-declared policy:");
   PolRow("BurstGuard",
          StringFormat("%s (%s)", g_cb.GetBurstGuardActive() ? "ON" : "OFF",
                       InpCBBurstGuardMode == CB_BURSTGUARD_AUTO ? "AUTO" : "override"),
          decl_guard ? "ON" : "OFF",
          g_cb.GetBurstGuardActive() == decl_guard,
          "load " + set_file);
   for(int i = 0; i < 5; i++)
   {
      double declv = 0;
      if(i == 0)      declv = POLICY_SPIKE_THRESH;
      else if(i == 1) declv = POLICY_MAX_PROB;
      else if(i == 2) declv = POLICY_FADE_R;
      else if(i == 3) declv = POLICY_FADE_SL;
      else            declv = POLICY_FADE_TP;
      PolRow(g_cb_names[i],
             StringFormat("%.2f (%s)", g_cb_res[i], g_cb_custom[i] ? "CUSTOM" : "AUTO"),
             StringFormat("%.2f", declv),
             MathAbs(g_cb_res[i] - declv) < 0.005,
             g_cb_custom[i] ? ("verify override is intentional, or load " + set_file) : "");
   }
   PolRow("tick-fade",     InpCBTickFade ? "ON" : "OFF", "ON",
          InpCBTickFade == POLICY_TICK_FADE, "load " + set_file);
   PolRow("tick-spike",    StringFormat("%.1f pts", InpCBTickSpikePts), "3.0 pts",
          MathAbs(InpCBTickSpikePts - POLICY_TICK_PTS) < 0.005, "");
   PolRow("tick-TO",       StringFormat("%ds", InpCBTickFadeTOSec), "900s",
          InpCBTickFadeTOSec == POLICY_TICK_TO_SEC, "");
   PolRow("max-hold",      StringFormat("%d bars", InpMaxHoldBars), "6 bars",
          InpMaxHoldBars == POLICY_MAX_HOLD_BARS, "");
   PolRow("base-risk",     StringFormat("%.2f%%", InpCBBaseRisk), "0.30%",
          MathAbs(InpCBBaseRisk - POLICY_BASE_RISK) < 0.005, "");
   PolRow("micro-fade",    InpCBMicroFade ? "ON" : "OFF", "ON",
          InpCBMicroFade == POLICY_MICRO_FADE, "load " + set_file);
   PolRow("req-spike-dir", InpCBRequireSpikeDirection ? "ON" : "OFF", "ON",
          InpCBRequireSpikeDirection == POLICY_REQ_SPIKE_DIR, "");
   PolRow("DailyHalt",     InpMaxDailyLossPct <= 0.0 ? "OFF" : StringFormat("%.1f%%", InpMaxDailyLossPct * 100.0), "OFF",
          InpMaxDailyLossPct <= POLICY_DAILY_LOSS, "set InpMaxDailyLossPct=0 (user request 2026-08-30)");
   PolRow("MicroFit",      InpMicroFitPct <= 0.0 ? "OFF" : StringFormat("%.1f%%", InpMicroFitPct), "1.5%",
          MathAbs(InpMicroFitPct - POLICY_MICRO_FIT) < 0.05, "0 = stale v26.5- inputs");
   PolRow("CloseDetect",  InpUseOnTradeTransaction ? "ON" : "OFF", "ON",
          InpUseOnTradeTransaction == POLICY_CLOSE_DETECT, "v26.4 event-driven closes");

   if(g_pol_mism == "")
      PrintFormat(VTAG+"[POLICY] %d/%d rows match the declared policy — config is clean.",
                  g_pol_ok, g_pol_total);
   else
   {
      PrintFormat(VTAG+"*** POLICY MISMATCH: %d of %d rows deviate from the declared policy ***",
                  g_pol_total - g_pol_ok, g_pol_total);
      Print(VTAG+"*** Deviations: " + g_pol_mism + "***");
      Print(VTAG+"*** Fix: click Load in the EA dialog and pick " + set_file + " (MQL5\\Presets), or correct the flagged inputs. If an override is intentional, update the .set AND the POLICY_* mirrors together. ***");
   }
}

//+------------------------------------------------------------------+
int OnInit()
{
   g_tf_entry  = ParseTF(InpEntryTFOverride, (ENUM_TIMEFRAMES)Period());
   ENUM_TIMEFRAMES regParsed = ParseTF(InpRegimeTFOverride, PERIOD_CURRENT);
   g_tf_regime = (regParsed == PERIOD_CURRENT) ? GetRegimeTF(g_tf_entry) : regParsed;

   hEMA_Fast_R = iMA(_Symbol, g_tf_regime, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_R  = iMA(_Symbol, g_tf_regime, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_R = iMA(_Symbol, g_tf_regime, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Fast_E = iMA(_Symbol, g_tf_entry, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Mid_E  = iMA(_Symbol, g_tf_entry, InpEmaMid,  0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow_E = iMA(_Symbol, g_tf_entry, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI_E      = iRSI(_Symbol, g_tf_entry, 14, PRICE_CLOSE);
   hATR_E      = iATR(_Symbol, g_tf_entry, InpAtrPeriod);
   hBB_E       = iBands(_Symbol, g_tf_entry, 20, 0, 2.0, PRICE_CLOSE);

   if(hEMA_Fast_R==INVALID_HANDLE || hEMA_Mid_R==INVALID_HANDLE || hEMA_Slow_R==INVALID_HANDLE ||
      hEMA_Fast_E==INVALID_HANDLE || hEMA_Mid_E==INVALID_HANDLE || hEMA_Slow_E==INVALID_HANDLE ||
      hRSI_E==INVALID_HANDLE || hATR_E==INVALID_HANDLE || hBB_E==INVALID_HANDLE)
   {
      Print("v23: Handle failed");
      return INIT_FAILED;
   }

   ArrayResize(atr_hist, InpAtrLookback+30);
   ArrayInitialize(atr_hist, 0);

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   g_peak_eq = g_eq;
   g_day_start_eq = g_eq;

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePts);
   trade.SetTypeFillingBySymbol(_Symbol);

   // parse fleet magics
   {
      string parts[];
      g_fleet_n = StringSplit(InpFleetMagicsCSV, ',', parts);
      ArrayResize(g_fleet_magics, MathMax(1, g_fleet_n));
      int k=0;
      for(int i=0;i<g_fleet_n;i++)
         if(parts[i] != "")
            g_fleet_magics[k++] = (long)StringToInteger(parts[i]);
      g_fleet_n = k;
   }

   RecoverPosition();
   // v26.11: fail-closed BEFORE the first file-indexed table write
   if(!SelfTestFixedArrays())
      return(INIT_FAILED);
   LoadReviewState();  // v23.1: restore persisted trade stats + intelligence
   LoadSlipState();    // v26.2: restore spike-slippage counters
   LoadCbSpikeState(); // v26.5: restore learned CB spike gating
   LoadMetaLabelTable(); // v26.14: restore learned P(win) regime multipliers
   RecoverDetachedClose(); // v26.9: journal closes that happened while the EA was detached
   if(InpDrawDashboard) CreateDashboard();
   // v25.1: tick recorder — degrades to no-op if the file can't be opened
   g_tick_rec.Init(_Symbol, InpTickRecordEnabled, InpTickFlushTicks, InpTickFlushSeconds);

   Print(VTAG+"MITEMSHUB AI v"+APP_VERSION+" started | 5 Strategies | Regime-Aware | Crash/Boom Mode");
   PrintFormat(VTAG+"Entry TF=%s | Regime TF=%s | Band=%s | MinScore=%d | RiskCap=%.0f%%",
               EnumToString(g_tf_entry), EnumToString(g_tf_regime),
               InpUseBandFade?"ON":"OFF", InpMinScore, InpMaxEffectiveRiskPct);
   PrintFormat(VTAG+"Session=%02d-%02d | GradExit=%s | ScaleLoss=%s | ProfitLock=%.1fR | TrailDist=%.1fR",
               InpSessionStartHour, InpSessionEndHour,
               InpGraduatedExit?"ON":"OFF", InpScaleAfterLoss?"ON":"OFF",
               InpProfitLockR, InpTrailDistR);
   if(InpMaxEffectiveRiskPct > 10.0)
      Print(VTAG+"WARNING: risk cap > 10% — tiny-account mode.");
   Print(VTAG+"Telemetry -> MQL5\\Files\\", SymbolTaggedFile(TELEM_BASE, ".jsonl"));
   Print(VTAG+"State    -> MQL5\\Files\\", SymbolTaggedFile(STATE_BASE, ".csv"));
   Print(VTAG+"Review   -> MQL5\\Files\\", SymbolTaggedFile(REVIEW_BASE, ".csv"));
   PrintFormat(VTAG+"Intelligence: StrategyReview@%d trades, RegimeReview@%d, TimeReview@%d",
               InpStrategyReviewN, InpRegimeReviewN, InpTimeReviewN);
   PrintFormat(VTAG+"Auto-disable: %s (min %d trades, min expectancy %.2fR)",
               InpAutoDisableStrat?"ON":"OFF", InpMinTradesToJudge, InpMinExpectancy);

   // v24: Initialize Crash/Boom engine
   if(InpCrashBoomMode)
   {
      g_cb.Init(true, InpIsCrashIndex);
      // v26.10: AUTO per-symbol resolution — the calibration profile ships the
      // deployed v26.8 geometry; CUSTOM mode lets an explicit input win.
      double pv;
      pv = ResolveCBParam(InpCBSpikeThresholdMode, g_cb.GetSpikeThresholdEff(), InpCBSpikeThreshold, "spike-thresh", 0);
      if(InpCBSpikeThresholdMode == CB_PARAM_CUSTOM) g_cb.SetSpikeThreshold(pv);
      pv = ResolveCBParam(InpCBMaxSpikeProbMode,   g_cb.GetMaxSpikeProbEff(),   InpCBMaxSpikeProb,   "max-spike-prob", 1);
      if(InpCBMaxSpikeProbMode   == CB_PARAM_CUSTOM) g_cb.SetMaxSpikeProb(pv);
      pv = ResolveCBParam(InpCBFadeRMode,          g_cb.GetFadeREff(),          InpCBFadeR,          "fade-R", 2);
      if(InpCBFadeRMode          == CB_PARAM_CUSTOM) g_cb.SetFadeR(pv);
      pv = ResolveCBParam(InpCBFadeSLMode,         g_cb.GetFadeSLEff(),         InpCBFadeSL,         "fade-SL", 3);
      if(InpCBFadeSLMode         == CB_PARAM_CUSTOM) g_cb.SetFadeSL(pv);
      pv = ResolveCBParam(InpCBFadeTPMode,         g_cb.GetFadeTPEff(),         InpCBFadeTP,         "fade-TP", 4);
      if(InpCBFadeTPMode         == CB_PARAM_CUSTOM) g_cb.SetFadeTP(pv);
      g_cb.SetBaseRisk(InpCBBaseRisk);
      g_cb.SetMinRisk(InpCBMinRisk);
      g_cb.SetEnableGrind(InpCBEnableGrind);
      g_cb.SetRequireSpikeDirection(InpCBRequireSpikeDirection);
      g_cb.SetMinATRPoints(InpCBMinATRPoints);
      g_cb.SetMicroFade(InpCBMicroFade);
      g_cb.SetTickFade(InpCBTickFade, InpCBTickSpikePts, InpCBTickFadeTOSec);
      g_cb.SetTickFadeGuard((int)InpCBBurstGuardMode, InpCBBurstWindowSec, InpCBBurstMaxSpikes, InpCBBurstMinGapSec);
      PrintFormat(VTAG+"Crash/Boom mode: %s | spike_thresh=%.1f | max_prob=%.2f | fade R=%.2f SL=%.2fxATR TP=%.1fxATR | risk=%.2f%% | grind=%s | micro=%s",
                  InpIsCrashIndex?"CRASH":"BOOM",
                  g_cb.GetSpikeThresholdEff(), g_cb.GetMaxSpikeProbEff(),
                  g_cb.GetFadeREff(), g_cb.GetFadeSLEff(), g_cb.GetFadeTPEff(),
                  InpCBBaseRisk,
                  InpCBEnableGrind?"ON":"OFF", InpCBMicroFade?"ON":"OFF");
      // v25.9: make a stale remembered-parameter attach impossible to miss.
      if(!InpCBMicroFade)
         Print(VTAG+"WARNING: micro=OFF on "+_Symbol+
               " — click Load in the EA dialog and pick MitemshubAI_BOOM1000_CB.set (MQL5\\Presets)");
      if(!InpCBTickFade)
         Print(VTAG+"WARNING: TickFade=OFF on "+_Symbol+
               " — the same Load fixes it (InpCBTickFade=true)");
   }
   else
   {
      g_cb.Init(false, false);
   }

   PrintStartupSelfCheck();   // v26.9: one-glance stale-chart detector in the log
   RunPolicySelfCheck();      // v26.10: resolved config vs .set-declared policy

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hEMA_Fast_R); IndicatorRelease(hEMA_Mid_R); IndicatorRelease(hEMA_Slow_R);
   IndicatorRelease(hEMA_Fast_E); IndicatorRelease(hEMA_Mid_E); IndicatorRelease(hEMA_Slow_E);
   IndicatorRelease(hRSI_E); IndicatorRelease(hATR_E); IndicatorRelease(hBB_E);
   for(int i=0;i<26;i++) ObjectDelete(0, dash_names[i]);

   SaveReviewState();  // v23.1: persist trade stats + intelligence on shutdown
   SaveSlipState();    // v26.2: persist spike-slippage counters
   if(InpCrashBoomMode) g_cb.Deinit();  // v24.1: release indicator handles
   g_tick_rec.Flush();  // v25.1: persist buffered ticks (file closed by destructor)

   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   PrintFormat(VTAG+"FINAL | Trades:%d WR:%.1f%% R:%+.2f | Stops:%d Time:%d EarlyCut:%d Target:%d",
               g_trades, wr, g_total_r, g_stop_exits, g_time_exits, g_early_cuts, g_target_exits);
}

//+------------------------------------------------------------------+
//| v23: Session filter — block entries outside trading hours         |
//| v26.7: MINUTE-LEVEL cutoff. The hour-only check (`hour < end`)    |
//| allowed entries in the whole final hour (seen live on Aug-30:     |
//| a tick-fade fired at 22:50 server — 10 min before a 23:00 end —   |
//| and every spike-gap loss that day landed inside that last hour).  |
//| New input InpSessionEndOffsetMin cuts entries N minutes earlier   |
//| (default 45 → last entry at 20:15 for a 21:00 end). Open trades   |
//| are still managed to completion; management is never session-     |
//| gated. A negative offset extends INTO the end hour instead.       |
//+------------------------------------------------------------------+
bool IsSessionActive()
{
   MqlDateTime dt;
   TimeCurrent(dt);
   if(InpSessionStartHour < InpSessionEndHour)
      return (dt.hour >= InpSessionStartHour &&
              (dt.hour < InpSessionEndHour ||
               (dt.hour == InpSessionEndHour &&
                InpSessionEndOffsetMin < 0 && dt.min < -InpSessionEndOffsetMin) ||
               (dt.hour + 1 == InpSessionEndHour &&
                dt.min < 60 - MathMax(InpSessionEndOffsetMin, 0))));
   else  // wraps midnight
      return (dt.hour >= InpSessionStartHour || dt.hour < InpSessionEndHour);
}

//--- v26.5: learned CB gating — spikes (grind+fade) survive restarts
int    g_cb_spike_n       = 0;   // CB spike trades (fade+grind attempts) accumulated
double g_cb_spike_r_sum   = 0.0; // realized R summed over CB spike trades
double g_cb_spike_expect  = 0.0; // EWMA expectancy of CB spike trades (R/trade)
double g_cb_spike_sigma   = 0.5; // EWMA std of CB spike trade R
int    g_cb_spike_streak  = 0;   // consec losses on CB spike trades (EWMA lifetime)
bool   g_cb_spike_blocked = false; // learned gate verdict (persists)
bool   g_cb_spike_was_blocked = false; // edge-trigger for the facade log line
int    g_cb_gate_probe    = 0;   // v26.13: exploration budget after a gate close
int    g_cb_quiet_days    = 0;   // v26.13: days with zero spike trades (EWMA decay)



//--- EWMA update of CB spike expectancy after each CB spike close
void UpdateCbSpikeLearning(double r)
{
   g_cb_spike_n++;
   g_cb_spike_r_sum += r;
   const double a = 0.15;                       // ~7-trade memory (day-scale)
   g_cb_spike_expect = (g_cb_spike_n <= 2) ? r : (a*r + (1.0-a)*g_cb_spike_expect);
   double dev = (r - g_cb_spike_expect);
   g_cb_spike_sigma = (g_cb_spike_n <= 2) ? 0.5 : MathSqrt(a*dev*dev + (1.0-a)*g_cb_spike_sigma*g_cb_spike_sigma);
   if(r < 0) g_cb_spike_streak++; else g_cb_spike_streak = 0;
   // v26.13: a completed trade is fresh evidence — close the exploration window
   if(g_cb_gate_probe > 0)
   {
      g_cb_gate_probe = 0;
      PrintFormat(VTAG+"CB-SPIKE GATE: exploration trade completed (R=%+.2f) — budget closed, gate verdict re-evaluated", r);
   }
   g_cb_quiet_days = 0;
}

//--- v26.13: daily EWMA decay — called once per new session day.
//    The deadlock fix: the old gate could block ALL spike trades forever
//    (expect<1.5σ with a fat sigma from one gap-through loss), and expect
//    could never recover because recovery requires trades — which the gate
//    blocked. Now a quiet day halves |expect| toward 0 and decays n, so
//    after ~2 days without trades the gate re-arms on its own.
void DecayCbSpikeLearning()
{
   if(g_cb_spike_n == 0) return;
   g_cb_quiet_days++;
   g_cb_spike_expect *= 0.5;          // mean decays toward 0 (re-arms the gate)
   g_cb_spike_sigma  = MathMax(0.5, g_cb_spike_sigma * 0.7);  // noise shrinks too
   if(g_cb_spike_n > 2) g_cb_spike_n = (int)(g_cb_spike_n * 0.6);  // evidence ages
   g_cb_spike_streak = 0;             // day-scoped, matching g_consec_loss
   PrintFormat(VTAG+"CB-SPIKE LEARNING: quiet day %d — expect decays to %+.2fR, sigma %.2f, n=%d (gate re-arms as mean → 0)",
               g_cb_quiet_days, g_cb_spike_expect, g_cb_spike_sigma, g_cb_spike_n);
}

//--- Learned gate: block CB spike entries while the fade thesis trends fake.
//    A real edge shows mean >> noise; facades show mean <= 0 with fat noise.
//    v26.13 deadlock fix:
//      * "noise swamps edge" now requires expect < 0 — a positive mean is
//        NEVER blocked (the old expect < 1.5σ froze the gate at sigma=0.5
//        default even for a healthy +0.74R mean).
//      * exploration budget: after a gate closes, the next g_cb_gate_probe
//        spike signals still fire (spaced by cooldown) so the EWMA gets
//        fresh data instead of freezing forever.
bool CbSpikeFacade()
{
   if(!InpCBPersistLearning || g_cb_spike_n < 4) return false;   // not enough evidence
   if(g_cb_gate_probe > 0) return false;                         // exploration budget open
   if(g_cb_spike_expect < -0.25)                                 // persistent negative edge
      return true;
   if(g_cb_spike_expect < 0.0 &&
      g_cb_spike_sigma > 0 && g_cb_spike_expect < 1.5*g_cb_spike_sigma)
      return true;                                               // negative mean swamped by noise
   return false;
}

//--- Persist per symbol; survives re-attaches and restarts (v26.5)
void SaveCbSpikeState()
{
   int h=FileOpen(SymbolTaggedFile("MitemshubAI_cblearn", ".csv"), FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   FileWriteString(h, StringFormat("%d,%.4f,%.4f,%.4f,%d,%d,%d,%d\n",
                   g_cb_spike_n, g_cb_spike_r_sum, g_cb_spike_expect, g_cb_spike_sigma,
                   g_cb_spike_streak, g_cb_spike_blocked?1:0,
                   g_cb_gate_probe, g_cb_quiet_days));   // v26.13: probe + quiet days persist
   FileClose(h);
}

void LoadCbSpikeState()
{
   int h=FileOpen(SymbolTaggedFile("MitemshubAI_cblearn", ".csv"), FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   string line=FileReadString(h);
   FileClose(h);
   if(StringLen(line)==0) return;
   string p[];
   if(StringSplit(line, ',', p) >= 6)
   {
      g_cb_spike_n       = (int)StringToInteger(p[0]);
      g_cb_spike_r_sum   = StringToDouble(p[1]);
      g_cb_spike_expect  = StringToDouble(p[2]);
      g_cb_spike_sigma   = StringToDouble(p[3]);
      g_cb_spike_streak  = (int)StringToInteger(p[4]);
      g_cb_spike_blocked = (StringToInteger(p[5]) == 1);
      if(StringSplit(line, ',', p) >= 8)   // v26.13 fields (tolerate old files)
      {
         g_cb_gate_probe  = (int)StringToInteger(p[6]);
         g_cb_quiet_days  = (int)StringToInteger(p[7]);
      }
      PrintFormat(VTAG+"CB-SPIKE LEARNING restored: n=%d mean=%+.3fR sigma=%.3f streak=%d gate=%s probe=%d quiet_days=%d",
                  g_cb_spike_n, g_cb_spike_expect, g_cb_spike_sigma, g_cb_spike_streak,
                  g_cb_spike_blocked ? "BLOCKED" : "OPEN", g_cb_gate_probe, g_cb_quiet_days);
   }
}

//+------------------------------------------------------------------+
//| v26.4: EVENT-DRIVEN CLOSE DETECTION                               |
//| Replaces the polling HistorySelect(0,now) scan (O(all history))   |
//| with one O(1) HistoryDealSelect on the closing deal reported by   |
//| TRADE_TRANSACTION_DEAL_ADD. The polling path stays as fallback    |
//| (InpUseOnTradeTransaction=false, or transactions missed while the |
//| EA was busy/restarting — DEAL_TIME is checked against entry time).|
//+------------------------------------------------------------------+
ulong  g_pending_close_deal = 0;   // closing deal ticket awaiting processing

void HandleTradeClose(double exit_p, string reason, ulong deal_ticket)
{
   double r = g_orig_risk>0 ? (g_dir>0?(exit_p-g_entry):(g_entry-exit_p))/g_orig_risk : 0;
   g_trades++; g_total_r += r;
   if(r>0) g_wins++; else g_losses++;

   if(reason=="TARGET") g_target_exits++;
   else if(reason=="TIME") g_time_exits++;
   else if(reason=="STOP") g_stop_exits++;
   else if(reason=="ECUT") g_early_cuts++;

   // v24.11: ALWAYS set cooldown after trade closes (not just after losses)
   // This prevents re-entry while market is still moving against us
   g_cooldown = InpCoolDownBars;
   if(r<0){ g_consec_loss++; } else g_consec_loss=0;
   if(g_consec_loss>=InpMaxConsecLoss)
   {
      g_paused=true;
      PrintFormat(VTAG+"%d consecutive losses — PAUSED", g_consec_loss);
   }
   g_daily_pnl += r*g_risk_money;
   g_session_pnl += r*g_risk_money;

   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   PrintFormat(VTAG+"CLOSE %s R=%+.3f | Trades:%d WR:%.1f%% TotalR:%+.2f SessionPnL=$%+.2f",
               reason, r, g_trades, wr, g_total_r, g_session_pnl);

   Telem("close", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"dir\":%d,\"reason\":\"%s\",\"exit\":%.5f,"
      "\"r\":%.3f,\"pnl\":%.2f,\"consec_loss\":%d,\"paused\":%s,\"daily_halt\":%s",
      _Symbol, g_ticket, g_dir, reason, exit_p, r, r*g_risk_money,
      g_consec_loss, (g_paused?"true":"false"), (DailyLossHalted()?"true":"false")));

   RecordTradeSlippage(r, reason);   // v26.2: gap-through vs planned -1R      // v26.5: learned CB spike gating — update the EWMA + persist
   if(InpCrashBoomMode)
   {
      UpdateCbSpikeLearning(r);
      g_cb_spike_blocked = CbSpikeFacade();
      if(g_cb_spike_blocked && !g_cb_spike_was_blocked)
      {
         // v26.13: grant an exploration budget — the next 3 spike signals fire
         // even while blocked, so the EWMA can recover from a bad streak.
         g_cb_gate_probe = 3;
         PrintFormat(VTAG+"CB-SPIKE GATE: BLOCKED (mean=%+.2fR sigma=%.2f n=%d streak=%d) — exploration budget 3 signals granted to break the deadlock",
                     g_cb_spike_expect, g_cb_spike_sigma, g_cb_spike_n, g_cb_spike_streak);
      }
      else if(!g_cb_spike_blocked && g_cb_spike_was_blocked)
      {
         PrintFormat(VTAG+"CB-SPIKE GATE: OPEN (mean=%+.2fR sigma=%.2f n=%d) — spike fades re-enabled",
                     g_cb_spike_expect, g_cb_spike_sigma, g_cb_spike_n);
      }
      g_cb_spike_was_blocked = g_cb_spike_blocked;
      SaveCbSpikeState();
   }

   // v24.11: Notify CB engine of trade close (for trend-reversal guard)
   if(InpCrashBoomMode && g_dir != 0)
      g_cb.OnTradeClosed(g_dir, g_entry);

   g_ticket=0; g_dir=0; g_bars_held=0; g_high_water_r=0;
   g_pending_close_deal = 0;         // v26.4: consumed (or out-of-order event ignored)

   // v23.1: Run intelligence review after every trade
   PostTradeReview(g_last_strategy, r, reason);

   SaveReviewState();  // v23.1: persist after every close
   g_tick_rec.Flush(); // v26.7: flush now so the tick CSV always contains the
                       // spikes and retrace ticks that PRODUCED this close
                       // (previously they waited up to the 10s/100-tick
                       // flush cadence, so offline replays could miss the
                       // microstructure context of a just-closed trade).
}

//+------------------------------------------------------------------+
//| v26.4: MQL5 trade-event handler — closes via a single deal lookup |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(!InpUseOnTradeTransaction) return;
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.deal == 0 || g_ticket == 0 || g_dir == 0) return;   // nothing to close
   if(trans.symbol != _Symbol) return;

   // O(1): select exactly this deal — no history sweep.
   if(!HistoryDealSelect(trans.deal))
   {
      PrintFormat(VTAG+"OnTradeTransaction: HistoryDealSelect(%I64u) failed — polling fallback will handle it", trans.deal);
      return;   // leave g_ticket set; the OnTick poll closes it next tick
   }
   if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;
   if((long)HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic) return;

   double deal_price = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   if(deal_price <= 0)
   {
      PrintFormat(VTAG+"OnTradeTransaction: deal %I64u has no price — deferring to polling fallback", trans.deal);
      return;
   }

   // Out-of-order guard: skip close events that predate the current entry.
   datetime deal_time = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
   if(g_entry_time > 0 && deal_time < g_entry_time)
   {
      PrintFormat(VTAG+"OnTradeTransaction: stale deal %I64u (%s) predates entry %s — ignored",
                  trans.deal, TimeToString(deal_time), TimeToString(g_entry_time));
      return;
   }

   // Derive exit reason from the deal, so broker-side TP/SL are labeled
   // correctly instead of "MANUAL".
   string reason = "MANUAL";
   ENUM_DEAL_REASON dr = (ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal, DEAL_REASON);
   if(dr == DEAL_REASON_TP)      reason = "TARGET";
   else if(dr == DEAL_REASON_SL) reason = "STOP";
   else if(dr == DEAL_REASON_SO) reason = "STOP";

   g_pending_close_deal = trans.deal;   // consumed below in HandleTradeClose
   PrintFormat(VTAG+"OnTradeTransaction: closing deal %I64u price=%.5f reason=%s — O(1) close",
               trans.deal, deal_price, reason);
   HandleTradeClose(deal_price, reason, trans.deal);
}

//+------------------------------------------------------------------+
void OnTick()
{
   // v25.4: per-tick feeds run BEFORE the bar-guard — they must see every tick
   double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   // v25.1: tick recorder captures EVERY tick
   if(InpTickRecordEnabled) g_tick_rec.OnTick(bid, ask);
   // v24: Crash/Boom tick handler (tick-pattern analyzer + detector tick speed)
   if(InpCrashBoomMode) g_cb.OnTick(bid, ask);
   // v25.4: tick-triggered fast fade — track every tick, fire only when gates open
   if(InpCrashBoomMode && InpCBTickFade)
   {
      bool can_trade = (g_ticket==0 && !g_paused && g_cooldown==0 && !DailyLossHalted()
                        && IsSessionActive() && !HasOpenPositionOnSymbol(_Symbol)
                        && (!g_cb_spike_blocked || g_cb_gate_probe > 0));   // v26.13: probe budget overrides the learned gate
      double fe=0, fs=0, ftp=0; string tfr="";
      int fd = g_cb.OnTickFade(bid, fe, fs, ftp, tfr, can_trade);
      if(fd != 0 && can_trade)
      {
         g_last_strategy = "CB-TICKFADE";
         // v26.13: consume-on-confirm. The spike stays pending inside the
         // engine until the order's fate is known: accepted → TickFadeConfirm
         // (cooldown + M5-path block, exactly the old consume-on-send);
         // rejected/aborted → TickFadeRelease (fade can re-fire on the next
         // tick with FRESH entry/SL/TP instead of the opportunity being
         // silently eaten by one invalid-stops rejection).
         if(OpenCBTrade(fd, fe, fs, ftp, tfr))
         {
            g_cb.TickFadeConfirm();
            if(g_cb_gate_probe > 0) g_cb_gate_probe--;   // v26.13: exploration budget consumed by a fired fade
         }
         else                                  g_cb.TickFadeRelease();
      }
   }

   static datetime last_bar=0;
   datetime cur = iTime(_Symbol, g_tf_entry, 0);
   if(cur == last_bar) { if(InpDrawDashboard) UpdateDashboard(); return; }
   last_bar = cur;

   g_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_eq > g_peak_eq) g_peak_eq = g_eq;

   datetime ds = TimeCurrent() - (TimeCurrent()%86400);
   if(ds != g_day_start)
   {       g_day_start=ds; g_daily_pnl=0; g_trades_today=0;
       g_day_start_eq = g_eq;
       g_session_pnl=0;
       g_consec_loss=0;
       g_cb_reject_today=0;   // v26.12: rejection counter follows the daily reset
      if(InpCrashBoomMode) DecayCbSpikeLearning();   // v26.13: deadlock fix — EWMA decays on quiet days
      if(g_paused)
      {
         g_paused=false;
         Print(VTAG+"New session day — consecutive-loss PAUSE lifted");
      }
      PrintFormat(VTAG+"New day — daily counters reset. Equity: %.2f", g_eq);
      SaveReviewState();   // v26.3: persist the reset immediately (fresh-day baseline)
   }

   if(g_cooldown>0) g_cooldown--;

   if(g_ticket>0)
   {
      if(PositionSelectByTicket(g_ticket)) ManagePosition();
      else
      {
         // v26.4: position vanished without a transaction event (EA was busy,
         // restarted, or InpUseOnTradeTransaction=false). Fallback: find the
         // position's closing deal with ONE targeted history query (position
         // id + symbol + time window) instead of scanning all history.
         double exit_p = 0;
         if(HistorySelectByPosition(g_ticket) && HistoryDealsTotal() > 0)
         {
            for(int d = HistoryDealsTotal()-1; d >= 0; d--)
            {
               ulong dt = HistoryDealGetTicket(d);
               if(dt == 0) continue;
               if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
               if(HistoryDealGetString(dt, DEAL_SYMBOL) != _Symbol) continue;
               double deal_price = HistoryDealGetDouble(dt, DEAL_PRICE);
               if(deal_price <= 0) continue;
               exit_p = deal_price;
               ENUM_DEAL_REASON dr = (ENUM_DEAL_REASON)HistoryDealGetInteger(dt, DEAL_REASON);
               string reason = "MANUAL";
               if(dr == DEAL_REASON_TP)      reason = "TARGET";
               else if(dr == DEAL_REASON_SL) reason = "STOP";
               else if(dr == DEAL_REASON_SO) reason = "STOP";
               PrintFormat(VTAG+"POLL CLOSE (fallback): position %I64u deal %I64u price=%.5f reason=%s",
                           g_ticket, dt, exit_p, reason);
               HandleTradeClose(exit_p, reason, dt);
               break;
            }
         }
         if(g_ticket != 0)   // no deal found at all — approximate with current price
         {
            double px = g_dir>0 ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
            PrintFormat(VTAG+"WARNING: no closing deal for position %I64u — approximating exit at %.5f", g_ticket, px);
            HandleTradeClose(px, "MANUAL", 0);
         }
      }
   }

   // v23.1: Periodic position recovery — detect positions that filled during reloads
   if(g_ticket==0)
   {
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong t=PositionGetTicket(i);
         if(t==0) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
         if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
         // Found an orphaned position — recover it
         g_ticket=t;
         g_dir = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1;
         g_entry=PositionGetDouble(POSITION_PRICE_OPEN);
         g_sl=PositionGetDouble(POSITION_SL);
         g_tp=PositionGetDouble(POSITION_TP);
         g_orig_risk=MathAbs(g_entry-g_sl);
         g_position_volume=PositionGetDouble(POSITION_VOLUME);
         g_entry_time=(datetime)PositionGetInteger(POSITION_TIME);
         int bar_sec = PeriodSeconds(g_tf_entry);
         if(bar_sec>0 && g_entry_time>0)
            g_bars_held = (int)((TimeCurrent() - g_entry_time) / bar_sec);
         else g_bars_held=0;
         g_high_water_r=0;
         PrintFormat(VTAG+"RECOVERED orphaned position %s %s @%.5f (was missed during reload)",
                     g_dir>0?"BUY":"SELL", _Symbol, g_entry);
         break;
      }
   }

   UpdateSigmaBaseline();
   UpdateBandTelemetry();

   // v23: entry gate — session filter + stacking guard + all existing gates
   if(g_ticket==0 && !g_paused && g_cooldown==0 && !DailyLossHalted() &&
      IsSessionActive() &&
      Bars(_Symbol,g_tf_entry) >= InpWarmupBars)
   {
      // v23: check if another fleet instance already has a position on this symbol
      if(HasOpenPositionOnSymbol(_Symbol))
      {
         PrintFormat(VTAG+"BLOCKED — another fleet instance already has a position on %s", _Symbol);
         g_cooldown = InpCoolDownBars;
      }
      else
      {
         // v24: Crash/Boom mode uses dedicated signal engine
         if(InpCrashBoomMode)
         {
            string cb_reason="", cb_type="";
            double cb_entry=0, cb_sl=0, cb_tp=0;
            int cb_dir = g_cb.OnBar(cb_entry, cb_sl, cb_tp, cb_reason, cb_type);
            if(cb_dir != 0)
            {
               g_last_strategy = cb_type;
               // Use CB entry/SL/TP directly via OpenCBTrade
               OpenCBTrade(cb_dir, cb_entry, cb_sl, cb_tp, cb_reason);
            }
            else if(cb_reason != "")
            {
               // v25.2: surface every CB skip to the Experts log (deduped)
               if(cb_reason != g_last_cb_skip)
               {
                  PrintFormat("[CB-SKIP] %s", cb_reason);
                  g_last_cb_skip = cb_reason;
               }
               g_last_skip = cb_reason;
               if(g_fired_legs == "")
                  Telem("sig", StringFormat(
                     "\"sym\":\"%s\",\"action\":\"%s\",\"dir\":0,\"reason\":\"%s\",\"legs\":\"CB\","
                     "\"score_b\":0,\"score_s\":0,\"regime\":\"%s\",\"z\":%.3f,\"exp\":%.3f,"
                     "\"sigma\":%.6f,\"sigma_base\":%.6f,\"band_geom\":false",
                     _Symbol, "SKIP", cb_reason, RegimeToStr(g_regime),
                     g_z_dev, g_exp_ratio, g_sigma_now, g_sigma_ema));
            }
         }
         else
         {
            // Standard Volatility mode
            string sig="";
            int dir = GenerateSignal(sig);
            if(dir != 0) OpenTrade(dir, sig);
         }
      }
   }
   else if(g_ticket==0 && (g_paused || g_cooldown>0 || DailyLossHalted() || !IsSessionActive()))
   {
      if(g_paused) Print(VTAG+"PAUSED — consecutive-loss breaker");
      if(g_cooldown>0) PrintFormat(VTAG+"COOLDOWN %d bars left", g_cooldown);
      if(DailyLossHalted()) Print(VTAG+"DAILY-HALT");
      if(!IsSessionActive()) Print(VTAG+"SESSION-OFF — outside trading hours");
   }

   if(InpDrawDashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| v26.12: ORDER-REJECTION ACCOUNTING                                |
//| A rejected/aborted CB entry is a LOST fade opportunity: it never  |
//| reaches the review journal (no position → no close → no review),  |
//| so the offline loop was blind to it (Aug-30: 7 rejected Boom      |
//| fades had to be reconstructed by hand from the broker journal).   |
//| Counters + one telemetry event per rejection fix that blindness.  |
//+------------------------------------------------------------------+
void CBRecordReject(string why, string reason)
{
   g_cb_reject_total++;
   g_cb_reject_today++;
   g_cb_reject_streak++;
   g_cb_reject_last = why;
   PrintFormat(VTAG+"CB-REJECT #%d (today %d, streak %d): %s | %s",
               g_cb_reject_total, g_cb_reject_today, g_cb_reject_streak, why, reason);
   Telem("reject", StringFormat(
      "\"sym\":\"%s\",\"why\":\"%s\",\"reason\":\"%s\",\"total\":%d,\"today\":%d,\"streak\":%d",
      _Symbol, why, reason, g_cb_reject_total, g_cb_reject_today, g_cb_reject_streak));
}

//+------------------------------------------------------------------+
//| v23: Check if ANY fleet magic has an open position on this symbol |
//+------------------------------------------------------------------+
bool HasOpenPositionOnSymbol(const string sym)
{
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0 || !PositionSelectByTicket(t)) continue;
      if(!IsFleetMagic((long)PositionGetInteger(POSITION_MAGIC))) continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym) continue;
      count++;
   }
   return (count >= InpSameSymbolMaxPos);
}

//+------------------------------------------------------------------+
void RecoverPosition()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      g_ticket=t;
      g_dir = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1;
      g_entry=PositionGetDouble(POSITION_PRICE_OPEN);
      g_sl=PositionGetDouble(POSITION_SL);
      g_tp=PositionGetDouble(POSITION_TP);
      g_orig_risk=MathAbs(g_entry-g_sl);
      g_position_volume=PositionGetDouble(POSITION_VOLUME);
      g_entry_time=(datetime)PositionGetInteger(POSITION_TIME);

      // v23: estimate bars_held from entry time instead of resetting to 0
      int bar_sec = PeriodSeconds(g_tf_entry);
      if(bar_sec>0 && g_entry_time>0)
         g_bars_held = (int)((TimeCurrent() - g_entry_time) / bar_sec);
      else
         g_bars_held=0;

      // v23: estimate high-water R from current price
      double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double cur = g_dir>0 ? bid : ask;
      g_high_water_r = g_orig_risk>0 ? (g_dir>0?(cur-g_entry):(g_entry-cur))/g_orig_risk : 0;
      if(g_high_water_r<0) g_high_water_r=0;

      PrintFormat(VTAG+"Recovered %s %s @%.5f held %d bars (estimated)", g_dir>0?"BUY":"SELL",
                  _Symbol, g_entry, g_bars_held);
      break;
   }
}

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES ParseTF(const string s, const ENUM_TIMEFRAMES fallback)
{
   string t = s;
   StringToUpper(t);
   if(t=="CURRENT" || t=="") return fallback;
   if(t=="M1")  return PERIOD_M1;
   if(t=="M5")  return PERIOD_M5;
   if(t=="M15") return PERIOD_M15;
   if(t=="M30") return PERIOD_M30;
   if(t=="H1")  return PERIOD_H1;
   if(t=="H4")  return PERIOD_H4;
   if(t=="D1")  return PERIOD_D1;
   Print(VTAG+"Unknown TF override '", s, "' — using fallback");
   return fallback;
}

//+------------------------------------------------------------------+
double PerBarSigma(const int lookback)
{
   int n = MathMax(3, lookback);
   if(Bars(_Symbol, g_tf_entry) < n+2) return 0.0;
   double sum=0, sum2=0;
   for(int i=1; i<=n; i++)
   {
      double c0 = iClose(_Symbol, g_tf_entry, i);
      double c1 = iClose(_Symbol, g_tf_entry, i+1);
      if(c0<=0 || c1<=0) return 0.0;
      double r = MathLog(c0/c1);
      sum += r; sum2 += r*r;
   }
   double mean = sum/n;
   double sq = sum2 - n*mean*mean;
   if(sq <= 0) return 0.0;
   return MathSqrt(sq/(n-1));
}

//+------------------------------------------------------------------+
//| v26.9 phase 1: GARCH bar feed — one Update per entry-TF bar.     |
//| Module failure handling: bad price data or an invalid module     |
//| output degrades to the legacy PerBarSigma stddev after a short   |
//| tolerance window (sticky kill for the session, logged once).     |
//+------------------------------------------------------------------+
bool GarchFeedBar()
{
   if(!InpUseGarch || !g_garch_ok)
      return(false);                           // disabled or permanently failed
   if(Bars(_Symbol, g_tf_entry) < InpGarchWarmupBars + 2)
      return(false);
   //--- log return of the last closed bar (same convention as the Python
   //--- reference: log(c_t / c_{t-1}); no indicator handles involved)
   double c1 = iClose(_Symbol, g_tf_entry, 1);
   double c2 = iClose(_Symbol, g_tf_entry, 2);
   if(c1 <= 0 || c2 <= 0)
   {
      if(++g_garch_fail_n >= 50)
      {
         g_garch_ok = false;
         Print(VTAG+"GARCH disabled: persistent bad price data — legacy sigma path active");
      }
      return(false);
   }
   double sigma = 0.0;
   bool   ready = g_garch.Update(MathLog(c1 / c2), sigma);
   if(sigma <= 0 || !MathIsValidNumber(sigma))
   {
      if(++g_garch_fail_n >= 50)
      {
         g_garch_ok = false;
         Print(VTAG+"GARCH disabled: invalid sigma from module — legacy sigma path active");
      }
      return(false);
   }
   g_garch_fail_n = 0;
   g_garch_sigma  = sigma;
   g_garch_z      = g_garch.LastZ();
   if(ready && !g_garch_init_note)
   {
      g_garch_init_note = true;
      PrintFormat(VTAG+"GARCH ready: %d observations, sigma=%.5f (EGARCH calibrated-fixed)",
                  g_garch.Observations(), g_garch_sigma);
   }
   return(ready);
}

//--- Sigma source selection with fallback (v26.9 phase 1):
//--- GARCH when enabled+healthy+warm, else the legacy stddev path.
double ActiveBarSigma(const int lookback)
{
   if(InpUseGarch && g_garch_ok && g_garch.Observations() >= InpGarchWarmupBars && g_garch_sigma > 0)
      return(g_garch_sigma);
   return(PerBarSigma(lookback));
}

//+------------------------------------------------------------------+
void UpdateSigmaBaseline()
{
   GarchFeedBar();                            // v26.9: feed module once per bar
   double sig = ActiveBarSigma(20);
   if(sig <= 0) return;
   if(!g_sigma_init){ g_sigma_ema=sig; g_sigma_init=true; return; }
   double a = 2.0/(InpBandSigmaEmaLen+1.0);
   g_sigma_ema = a*sig + (1.0-a)*g_sigma_ema;
}

//+------------------------------------------------------------------+
void UpdateBandTelemetry()
{
   g_sigma_now=ActiveBarSigma(20);
   g_z_dev=0.0; g_exp_ratio=0.0;
   if(g_sigma_now<=0) return;

   double sma=0.0;
   for(int i=1;i<=20;i++) sma += iClose(_Symbol,g_tf_entry,i);
   sma /= 20.0;
   double price=iClose(_Symbol,g_tf_entry,1);
   if(sma<=0 || price<=0) return;

   g_z_dev = MathLog(price/sma)/g_sigma_now;
   if(g_sigma_init && g_sigma_ema>0) g_exp_ratio = g_sigma_now/g_sigma_ema;
   // v26.9: under GARCH the standardized shock z_t is the module's own
   // quantity; keep the telemetry z on the SAME scale as the sigma source.
   if(InpUseGarch && g_garch_ok && g_garch.Observations() >= InpGarchWarmupBars)
      g_z_dev = g_garch_z;
}

//+------------------------------------------------------------------+
void Telem(const string type, const string kv)
{
   int h=FileOpen(SymbolTaggedFile(TELEM_BASE, ".jsonl"), FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h==INVALID_HANDLE)
   { Print(VTAG+"telem write failed err=",GetLastError()); return; }
   FileSeek(h,0,SEEK_END);
   FileWriteString(h, StringFormat("{\"ts\":\"%s\",\"epoch\":%I64d,\"type\":\"%s\",%s}\n",
                   TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
                   (long)TimeCurrent(), type, kv));
   FileClose(h);
}

//+------------------------------------------------------------------+
//| STATE PERSISTENCE — v23: trade stats survive restarts             |
//+------------------------------------------------------------------+
// v26.14: load data/meta_label_regime_table.csv (from scripts/meta_label_
// trainer.py). CSV rows: regime,direction,n,win_rate,avg_r,multiplier,note
// Multiplier = relative expectancy of that (regime, dir) context; 0 = skip.
void LoadMetaLabelTable()
{
   g_ml_rows = 0;
   string path = SymbolTaggedFile("meta_label_regime_table", ".csv");
   int h=FileOpen(path, FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) { Print(VTAG+"meta-label table not found — sizing at 1.0x base risk"); return; }
   FileReadString(h);   // skip header
   while(!FileIsEnding(h) && g_ml_rows < META_LABEL_MAX_ROWS)
   {
      string line = FileReadString(h);
      if(StringLen(line)==0) continue;
      string cols[];
      if(StringSplit(line, ',', cols) < 7) continue;
      g_ml_regime[g_ml_rows] = cols[0];
      g_ml_dir[g_ml_rows]    = (cols[1]=="long") ? 1 : -1;
      g_ml_mult[g_ml_rows]   = StringToDouble(cols[5]);
      g_ml_rows++;
   }
   FileClose(h);
   PrintFormat(VTAG+"meta-label table: %d (regime,dir) rows loaded from %s", g_ml_rows, path);
}

// v26.14: risk multiplier for the current context; 1.0 when disabled/unknown.
double MetaLabelMultiplier(int direction)
{
   if(!InpUseMetaLabel || g_ml_rows == 0) return 1.0;
   for(int i=0;i<g_ml_rows;i++)
      if(g_ml_dir[i]==direction && g_ml_regime[i]==RegimeToStr(g_regime))
         return g_ml_mult[i];
   return 1.0;   // unknown context: default base risk
}

void SaveState()
{
   int h=FileOpen(SymbolTaggedFile(STATE_BASE, ".csv"), FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) { Print(VTAG+"state save failed"); return; }
   FileWriteString(h, StringFormat("%d,%d,%d,%d,%d,%.4f,%d,%d,%d\n",
                   g_trades, g_wins, g_losses,
                   g_target_exits, g_time_exits, g_total_r,
                   g_stop_exits, g_early_cuts, g_consec_loss));
   FileClose(h);
}

void LoadState()
{
   int h=FileOpen(SymbolTaggedFile(STATE_BASE, ".csv"), FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) { Print(VTAG+"no prior state found — starting fresh"); return; }
   string line = FileReadString(h);
   FileClose(h);
   if(StringLen(line)==0) return;

   string parts[];
   int n = StringSplit(line, ',', parts);
   if(n >= 7)
   {
      g_trades     = (int)StringToInteger(parts[0]);
      g_wins       = (int)StringToInteger(parts[1]);
      g_losses     = (int)StringToInteger(parts[2]);
      g_target_exits = (int)StringToInteger(parts[3]);
      g_time_exits   = (int)StringToInteger(parts[4]);
      g_total_r      = StringToDouble(parts[5]);
      g_stop_exits   = (int)StringToInteger(parts[6]);
   }
   if(n >= 8) g_early_cuts   = (int)StringToInteger(parts[7]);
   if(n >= 9) g_consec_loss  = (int)StringToInteger(parts[8]);

   // v23: if we recovered a position AND had a consecutive loss streak,
   // restore the pause state if the loss count warrants it
   if(g_ticket>0 && g_consec_loss >= InpMaxConsecLoss)
   {
      g_paused=true;
      PrintFormat(VTAG+"Restored PAUSE state — %d consecutive losses from prior session", g_consec_loss);
   }

   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   PrintFormat(VTAG+"Loaded state: Trades=%d WR=%.1f%% R=%+.2f ConsecLoss=%d",
               g_trades, wr, g_total_r, g_consec_loss);
}

//+------------------------------------------------------------------+
//| v23.1 INTELLIGENCE LAYER — self-review after every trade          |
//+------------------------------------------------------------------+

// Map strategy name to array index
int GetStrategyIndex(string strat)
{
   if(strat=="PB") return 0;
   if(strat=="BO") return 1;
   if(strat=="MOM") return 2;
   if(strat=="MR") return 3;
   if(strat=="BF") return 4;
   // v26.5: CB modes — indexes 5..7 (arrays sized 8)
   if(strat=="CB-TICKFADE") return 5;
   if(strat=="CB-FADE")     return 6;
   if(strat=="CB-GRIND")    return 7;
   return -1;
}

// Map regime to array index
int GetRegimeIndex(ENUM_REGIME r)
{
   if(r==REGIME_BULLISH) return 0;
   if(r==REGIME_BEARISH) return 1;
   if(r==REGIME_RANGING) return 2;
   if(r==REGIME_HIGH_VOL) return 3;
   return 4; // NO_TRADE
}

// Map server hour to time block index
int GetTimeBlockIndex(int hour)
{
   if(hour >= 6  && hour < 10) return 0;  // Early session
   if(hour >= 10 && hour < 14) return 1;  // Mid session
   if(hour >= 14 && hour < 18) return 2;  // Afternoon
   if(hour >= 18 && hour < 21) return 3;  // Late session
   return 4; // Off-hours
}

string TimeBlockStr(int idx)
{
   if(idx==0) return "06-10";
   if(idx==1) return "10-14";
   if(idx==2) return "14-18";
   if(idx==3) return "18-21";
   return "OFF";
}

//+------------------------------------------------------------------+
//| v26.11 INIT-TIME FIXED-ARRAY SELF-TEST                            |
//| Walks every fixed-size strategy/regime/time table array once and  |
//| verifies each size against its slot constant. Any size-vs-loop    |
//| mismatch aborts init HERE — fail-closed — instead of crashing on  |
//| a live chart (the v26.9 "[5] arrays under 8-slot walkers" class). |
//| MUST run before LoadReviewState: the loader writes file-indexed   |
//| slots straight into these arrays.                                 |
//+------------------------------------------------------------------+
bool SelfTestFixedArrays()
{
   int st=ArraySize(g_strat_trades), sw=ArraySize(g_strat_wins),
       sr=ArraySize(g_strat_total_r), se=ArraySize(g_strat_enabled);
   int rt=ArraySize(g_regime_trades), rw=ArraySize(g_regime_wins), rr=ArraySize(g_regime_total_r);
   int tt=ArraySize(g_time_trades),  tw=ArraySize(g_time_wins),  tr=ArraySize(g_time_total_r);
   int ns=ArraySize(STRAT_NAMES), nr=ArraySize(REGIME_NAMES);

   if(st!=STRAT_SLOTS || sw!=STRAT_SLOTS || sr!=STRAT_SLOTS || se!=STRAT_SLOTS ||
      rt!=REGIME_SLOTS || rw!=REGIME_SLOTS || rr!=REGIME_SLOTS ||
      tt!=TIME_SLOTS   || tw!=TIME_SLOTS   || tr!=TIME_SLOTS   ||
      ns!=STRAT_SLOTS  || nr!=REGIME_SLOTS)
   {
      PrintFormat(VTAG+"[SELFTEST] FIXED-ARRAY MISMATCH — refusing to init: "
                  "strat[t=%d w=%d r=%d en=%d names=%d] regime[t=%d w=%d r=%d names=%d] "
                  "time[t=%d w=%d r=%d] vs STRAT_SLOTS=%d REGIME_SLOTS=%d TIME_SLOTS=%d. "
                  "Fix the declarations (or the constants) and recompile.",
                  st,sw,sr,se,ns, rt,rw,rr,nr, tt,tw,tr,
                  STRAT_SLOTS,REGIME_SLOTS,TIME_SLOTS);
      return(false);
   }

   // Full walk: read every slot (the probe sums keep the reads observable in
   // the log) and identity write-touch the LAST slot of each array — the exact
   // index every loop bound reaches — proving read AND write addressability
   // up front, before anything else can touch the tables.
   double p1=0, p2=0, p3=0;
   for(int i=0;i<STRAT_SLOTS;i++)   p1 += g_strat_trades[i]+g_strat_wins[i]+g_strat_total_r[i];
   for(int i=0;i<REGIME_SLOTS;i++)  p2 += g_regime_trades[i]+g_regime_wins[i]+g_regime_total_r[i];
   for(int i=0;i<TIME_SLOTS;i++)    p3 += g_time_trades[i]+g_time_wins[i]+g_time_total_r[i];
   double v1=g_strat_trades[STRAT_SLOTS-1];    g_strat_trades[STRAT_SLOTS-1]=v1;
   double v2=g_strat_wins[STRAT_SLOTS-1];      g_strat_wins[STRAT_SLOTS-1]=v2;
   double v3=g_strat_total_r[STRAT_SLOTS-1];   g_strat_total_r[STRAT_SLOTS-1]=v3;
   bool   v4=g_strat_enabled[STRAT_SLOTS-1];   g_strat_enabled[STRAT_SLOTS-1]=v4;
   double v5=g_regime_trades[REGIME_SLOTS-1];  g_regime_trades[REGIME_SLOTS-1]=v5;
   double v6=g_regime_wins[REGIME_SLOTS-1];    g_regime_wins[REGIME_SLOTS-1]=v6;
   double v7=g_regime_total_r[REGIME_SLOTS-1]; g_regime_total_r[REGIME_SLOTS-1]=v7;
   double v8=g_time_trades[TIME_SLOTS-1];      g_time_trades[TIME_SLOTS-1]=v8;
   double v9=g_time_wins[TIME_SLOTS-1];        g_time_wins[TIME_SLOTS-1]=v9;
   double vA=g_time_total_r[TIME_SLOTS-1];     g_time_total_r[TIME_SLOTS-1]=vA;

   PrintFormat(VTAG+"[SELFTEST] fixed arrays OK: strat %d/%d p=%+.1f | regime %d/%d p=%+.1f | time %d/%d p=%+.1f (walk+write proof, pre-load)",
               STRAT_SLOTS,p1, REGIME_SLOTS,p2, TIME_SLOTS,p3);
   return(true);
}

// Main post-trade review — called from ClosePosition after every trade
void PostTradeReview(string strategy, double rMultiple, string exitType)
{
   // 1. Update strategy counters
   int si = GetStrategyIndex(strategy);
   if(si >= 0)
   {
      g_strat_trades[si]++;
      g_strat_wins[si] += (rMultiple > 0) ? 1 : 0;
      g_strat_total_r[si] += rMultiple;
   }

   // 2. Update regime counters
   int ri = GetRegimeIndex(g_regime);
   g_regime_trades[ri]++;
   g_regime_wins[ri] += (rMultiple > 0) ? 1 : 0;
   g_regime_total_r[ri] += rMultiple;

   // 3. Update time-block counters
   MqlDateTime dt; TimeCurrent(dt);
   int ti = GetTimeBlockIndex(dt.hour);
   g_time_trades[ti]++;
   g_time_wins[ti] += (rMultiple > 0) ? 1 : 0;
   g_time_total_r[ti] += rMultiple;

   // 4. Log to review file
   WriteReviewLog(strategy, RegimeToStr(g_regime), rMultiple, exitType, dt.hour);

   // 5. Periodic reviews
   if(g_trades >= g_last_strategy_review + InpStrategyReviewN)
   {
      CheckStrategyPerformance();
      g_last_strategy_review = g_trades;
   }
   if(g_trades >= g_last_regime_review + InpRegimeReviewN)
   {
      CheckRegimePerformance();
      g_last_regime_review = g_trades;
   }
   if(g_trades >= g_last_time_review + InpTimeReviewN)
   {
      CheckTimeBlockPerformance();
      g_last_time_review = g_trades;
   }

   // 6. If on losing streak, diagnose root cause
   if(g_consec_loss >= 2)
      AnalyzeLosingStreak();

   // 7. Save review state
   SaveReviewState();
}

// Check if any strategy should be auto-disabled
void CheckStrategyPerformance()
{
   Print(VTAG+"=== STRATEGY PERFORMANCE REVIEW ===");   // v26.11: shared STRAT_NAMES
   for(int i=0; i<STRAT_SLOTS; i++)
   {
      int need = (i >= 5) ? InpCBMinTradesToJudge : InpMinTradesToJudge;
      if(g_strat_trades[i] < need) continue;
      double wr = g_strat_wins[i] / g_strat_trades[i];
      double expectancy = g_strat_total_r[i] / g_strat_trades[i];
      double floor_r   = (i >= 5) ? InpCBMinExpectancy   : InpMinExpectancy;
      bool   may_kill  = (i >= 5) ? true                 : InpAutoDisableStrat;
      string status = "KEEP";

      if(may_kill && expectancy < floor_r && g_strat_trades[i] >= need)
      {
         g_strat_enabled[i] = false;
         status = "DISABLED";
         PrintFormat(VTAG+"STRATEGY %s: %.0f trades, WR=%.0f%%, ExpR=%+.2f → %s (below %.2f R/trade)",
                     STRAT_NAMES[i], g_strat_trades[i], wr*100, expectancy, status, floor_r);
      }
      else
      {
         g_strat_enabled[i] = true;
         PrintFormat(VTAG+"STRATEGY %s: %.0f trades, WR=%.0f%%, ExpR=%+.2f → %s",
                     STRAT_NAMES[i], g_strat_trades[i], wr*100, expectancy, status);
      }
   }
}

// Log regime performance
void CheckRegimePerformance()
{
   Print(VTAG+"=== REGIME PERFORMANCE REVIEW ===");   // v26.11: shared REGIME_NAMES
   for(int i=0; i<REGIME_SLOTS; i++)
   {
      if(g_regime_trades[i] < 3) continue;
      double wr = g_regime_wins[i] / g_regime_trades[i];
      double expectancy = g_regime_total_r[i] / g_regime_trades[i];
      PrintFormat(VTAG+"REGIME %s: %.0f trades, WR=%.0f%%, ExpR=%+.2f",
                  REGIME_NAMES[i], g_regime_trades[i], wr*100, expectancy);
   }
}

// Log time-block performance
void CheckTimeBlockPerformance()
{
   Print(VTAG+"=== TIME-BLOCK PERFORMANCE REVIEW ===");
   for(int i=0; i<TIME_SLOTS; i++)
   {
      if(g_time_trades[i] < 3) continue;
      double wr = g_time_wins[i] / g_time_trades[i];
      double expectancy = g_time_total_r[i] / g_time_trades[i];
      PrintFormat(VTAG+"TIME %s: %.0f trades, WR=%.0f%%, ExpR=%+.2f",
                  TimeBlockStr(i), g_time_trades[i], wr*100, expectancy);
   }
}

// Diagnose root cause of losing streaks
void AnalyzeLosingStreak()
{
   PrintFormat(VTAG+"LOSING STREAK ANALYSIS — %d consecutive losses, TotalR=%+.2f", g_consec_loss, g_total_r);

   // Check if losses are concentrated in one strategy (v26.5: 8 slots)
   for(int i=0; i<STRAT_SLOTS; i++)
   {
      if(g_strat_trades[i] == 0) continue;
      double recent_r = g_strat_total_r[i];
      if(recent_r < -1.0 && g_strat_trades[i] >= 5)
         PrintFormat(VTAG+"WARNING: Strategy index %d has R=%+.2f over %.0f trades — review needed", i, recent_r, g_strat_trades[i]);
   }

   // Check if losses are concentrated in one regime
   for(int i=0; i<REGIME_SLOTS; i++)
   {
      if(g_regime_trades[i] == 0) continue;
      if(g_regime_total_r[i] < -1.0 && g_regime_trades[i] >= 5)
         PrintFormat(VTAG+"WARNING: Regime %d has R=%+.2f over %.0f trades", i, g_regime_total_r[i], g_regime_trades[i]);
   }
}

// Write one review log line
void WriteReviewLog(string strategy, string regime, double rMultiple, string exitType, int hour)
{
   int h=FileOpen(SymbolTaggedFile(REVIEW_BASE, ".csv"), FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h==INVALID_HANDLE) return;
   FileSeek(h,0,SEEK_END);
   FileWriteString(h, StringFormat("%s,%s,%.3f,%s,%d,%.2f,%d\n",
                   TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),
                   strategy, rMultiple, exitType, hour, g_total_r, g_trades));
   FileClose(h);
}

// Save review state
void SaveReviewState()
{
   int h=FileOpen(SymbolTaggedFile(STATE_BASE, ".csv"), FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   FileWriteString(h, StringFormat("%d,%d,%d,%d,%d,%.4f,%d,%d,%d\n",
                   g_trades, g_wins, g_losses,
                   g_target_exits, g_time_exits, g_total_r,
                   g_stop_exits, g_early_cuts, g_consec_loss));
   // Strategy performance (v26.5: 8 slots — 5 classic + 3 CB modes)
   for(int i=0;i<STRAT_SLOTS;i++)
       FileWriteString(h, StringFormat("STRAT,%d,%.0f,%.0f,%.4f,%d\n",
                      i, g_strat_trades[i], g_strat_wins[i], g_strat_total_r[i], g_strat_enabled[i]?1:0));
   // Regime performance
   for(int i=0;i<REGIME_SLOTS;i++)
       FileWriteString(h, StringFormat("REGIME,%d,%.0f,%.0f,%.4f\n",
                      i, g_regime_trades[i], g_regime_wins[i], g_regime_total_r[i]));
   // Time-block performance
   for(int i=0;i<TIME_SLOTS;i++)
       FileWriteString(h, StringFormat("TIME,%d,%.0f,%.0f,%.4f\n",
                      i, g_time_trades[i], g_time_wins[i], g_time_total_r[i]));
   // Review counters
   FileWriteString(h, StringFormat("REVIEW,%d,%d,%d\n",
                   g_last_strategy_review, g_last_regime_review, g_last_time_review));
   // v26.3: daily/session counters — a mid-day re-attach must NOT reset these.
   // (Aug-30: ~9 re-attaches printed "New day" and wiped daily P&L, the
   // consec-loss pause and cooldown on the Boom instance.)
   FileWriteString(h, StringFormat("DAILY,%I64d,%.2f,%.2f,%d,%.2f,%d,%d,%d\n",
                   (long)g_day_start, g_daily_pnl, g_session_pnl, g_trades_today,
                   g_day_start_eq, g_consec_loss, g_paused?1:0, g_cooldown));
   // v26.9: persist the OPEN-position context so a close that happens while
   // the EA is detached (recompile/restart — the Aug-30 disease) can be
   // recovered and journaled at the next init. Cleared automatically once the
   // position closes (HandleTradeClose zeroes g_ticket before any save).
   if(g_ticket > 0 && g_dir != 0)
      FileWriteString(h, StringFormat("POSITION,%I64u,%I64d,%.5f,%.5f,%d,%.2f,%s\n",
                      g_ticket, (long)g_entry_time, g_entry, g_sl, g_dir,
                      g_position_volume, g_last_strategy));
   FileClose(h);
}

// Load review state
void LoadReviewState()
{
   int h=FileOpen(SymbolTaggedFile(STATE_BASE, ".csv"), FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   
   // Read base state (first line)
   string line = FileReadString(h);
   if(StringLen(line)==0) { FileClose(h); return; }
   string parts[];
   int n = StringSplit(line, ',', parts);
   if(n >= 7)
   {
      g_trades       = (int)StringToInteger(parts[0]);
      g_wins         = (int)StringToInteger(parts[1]);
      g_losses       = (int)StringToInteger(parts[2]);
      g_target_exits = (int)StringToInteger(parts[3]);
      g_time_exits   = (int)StringToInteger(parts[4]);
      g_total_r      = StringToDouble(parts[5]);
      g_stop_exits   = (int)StringToInteger(parts[6]);
   }
   if(n >= 8) g_early_cuts  = (int)StringToInteger(parts[7]);
   if(n >= 9) g_consec_loss = (int)StringToInteger(parts[8]);

   // Read review data
   while(!FileIsEnding(h))
   {
      line = FileReadString(h);
      if(StringLen(line)==0) continue;
      string rp[];
      int rn = StringSplit(line, ',', rp);
      if(rn < 2) continue;

      if(rp[0]=="STRAT" && rn >= 6)
      {
         int idx = (int)StringToInteger(rp[1]);          if(idx >= 0 && idx < STRAT_SLOTS)   // v26.5: 8 slots (5 classic + 3 CB)
         {
            g_strat_trades[idx]  = StringToDouble(rp[2]);
            g_strat_wins[idx]    = StringToDouble(rp[3]);
            g_strat_total_r[idx] = StringToDouble(rp[4]);
            g_strat_enabled[idx] = (StringToInteger(rp[5]) == 1);
         }
      }
      else if(rp[0]=="REGIME" && rn >= 5)
      {
         int idx = (int)StringToInteger(rp[1]);          if(idx >= 0 && idx < REGIME_SLOTS)
         {
            g_regime_trades[idx]  = StringToDouble(rp[2]);
            g_regime_wins[idx]    = StringToDouble(rp[3]);
            g_regime_total_r[idx] = StringToDouble(rp[4]);
         }
      }
      else if(rp[0]=="TIME" && rn >= 5)
      {
         int idx = (int)StringToInteger(rp[1]);          if(idx >= 0 && idx < TIME_SLOTS)
         {
            g_time_trades[idx]  = StringToDouble(rp[2]);
            g_time_wins[idx]    = StringToDouble(rp[3]);
            g_time_total_r[idx] = StringToDouble(rp[4]);
         }
      }
      else if(rp[0]=="REVIEW" && rn >= 4)
      {
         g_last_strategy_review = (int)StringToInteger(rp[1]);
         g_last_regime_review   = (int)StringToInteger(rp[2]);
         g_last_time_review     = (int)StringToInteger(rp[3]);
      }
      else if(rp[0]=="DAILY" && rn >= 9)
      {
         // v26.3: restore the day-scoped counters. g_day_start comes back with
         // them, so the daily-reset check in OnTick sees "same day" and does
         // not wipe anything on a mid-day re-attach. A stale day (server
         // midnight rollover) still resets normally on the first tick.
         g_day_start     = (datetime)StringToInteger(rp[1]);
         g_daily_pnl     = StringToDouble(rp[2]);
         g_session_pnl   = StringToDouble(rp[3]);
         g_trades_today  = (int)StringToInteger(rp[4]);
         g_day_start_eq  = StringToDouble(rp[5]);
         g_consec_loss   = (int)StringToInteger(rp[6]);
         g_paused        = (StringToInteger(rp[7]) == 1);
         g_cooldown      = (int)StringToInteger(rp[8]);
         datetime today  = TimeCurrent() - (TimeCurrent()%86400);
         if(g_day_start == today && (g_daily_pnl != 0 || g_session_pnl != 0 || g_trades_today > 0 || g_paused))
            PrintFormat(VTAG+"Restored today's session state: dailyPnL=%+.2f sessionPnL=%+.2f tradesToday=%d consec=%d paused=%s cooldown=%d",
                        g_daily_pnl, g_session_pnl, g_trades_today, g_consec_loss,
                        g_paused?"YES":"NO", g_cooldown);
      }
      else if(rp[0]=="POSITION" && rn >= 8 && g_ticket == 0)
      {
         // v26.9: restore the OPEN-position context — but ONLY when
         // RecoverPosition found no live position (a live position is the
         // authoritative truth and has already set the full context). If the
         // tracked position no longer exists, RecoverDetachedClose() journals
         // the close that happened while the EA was detached.
         g_ticket          = (ulong)StringToInteger(rp[1]);
         g_entry_time      = (datetime)StringToInteger(rp[2]);
         g_entry           = StringToDouble(rp[3]);
         g_sl              = StringToDouble(rp[4]);
         g_dir             = (int)StringToInteger(rp[5]);
         g_position_volume = StringToDouble(rp[6]);
         g_last_strategy   = rp[7];
         g_orig_risk       = MathAbs(g_entry - g_sl);
      }
   }
   FileClose(h);

   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   PrintFormat(VTAG+"Loaded intelligence: Trades=%d WR=%.1f%% R=%+.2f", g_trades, wr, g_total_r);
   for(int i=0;i<STRAT_SLOTS;i++)
   {
      if(g_strat_trades[i] >= 5)
         PrintFormat(VTAG+"Strategy %d: %.0f trades, R=%+.2f, enabled=%s",
                     i, g_strat_trades[i], g_strat_total_r[i], g_strat_enabled[i]?'1':'0');
   }
}

//+------------------------------------------------------------------+
//| v26.9: RESTART-GAP CLOSE RECOVERY                                 |
//| Three-layer close coverage: (1) OnTradeTransaction fires on the   |
//| closing deal while the EA runs (O(1)); (2) the OnTick poll catches |
//| a position vanishing during runtime; (3) THIS — a broker-side     |
//| close (SL/TP/stop-out/manual) that happened while the EA was      |
//| DETACHED (recompile/restart) left no live position for            |
//| RecoverPosition and was silently lost from every learning table.  |
//| If the state file carried an open position that is now gone,      |
//| recover its closing deal with ONE targeted history query and      |
//| route it through the shared handler — counters, review, EWMA      |
//| facade gate, slippage and telemetry all see it.                   |
//+------------------------------------------------------------------+
void RecoverDetachedClose()
{
   if(g_ticket == 0 || g_dir == 0 || g_orig_risk <= 0) return;
   if(PositionSelectByTicket(g_ticket)) return;   // still live — nothing to recover

   if(!HistorySelectByPosition(g_ticket) || HistoryDealsTotal() == 0)
   {
      PrintFormat(VTAG+"RESTART RECOVERY: tracked position %I64u gone and no deals found — clearing", g_ticket);
      g_ticket=0; g_dir=0; g_orig_risk=0; return;
   }
   ulong out_deal = 0;
   for(int d = HistoryDealsTotal()-1; d >= 0; d--)
   {
      ulong dt = HistoryDealGetTicket(d);
      if(dt == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetString(dt, DEAL_SYMBOL) != _Symbol) continue;
      out_deal = dt;                              // latest OUT deal on this position
      break;
   }
   if(out_deal == 0)
   {
      PrintFormat(VTAG+"RESTART RECOVERY: no OUT deal for position %I64u — clearing", g_ticket);
      g_ticket=0; g_dir=0; g_orig_risk=0; return;
   }
   double exit_p = HistoryDealGetDouble(out_deal, DEAL_PRICE);
   ENUM_DEAL_REASON dr = (ENUM_DEAL_REASON)HistoryDealGetInteger(out_deal, DEAL_REASON);
   string reason = "MANUAL";
   if(dr == DEAL_REASON_TP)      reason = "TARGET";
   else if(dr == DEAL_REASON_SL) reason = "STOP";
   else if(dr == DEAL_REASON_SO) reason = "STOP";
   // Recompute the $ risk from the restored context — the same formula the
   // entry path used, so daily/session P&L stays exact without persisting it.
   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tick_size > 0 && tick_value > 0 && g_position_volume > 0)
      g_risk_money = g_position_volume * (g_orig_risk / tick_size) * tick_value;
   PrintFormat(VTAG+"RESTART RECOVERY: position %I64u closed while detached — deal %I64u @%.5f reason=%s — journaling now",
               g_ticket, out_deal, exit_p, reason);
   HandleTradeClose(exit_p, reason, out_deal);
}

//+------------------------------------------------------------------+
//| ACCOUNT-WIDE EXPOSURE GUARD                                       |
//+------------------------------------------------------------------+
bool IsFleetMagic(const long m)
{
   for(int i=0;i<g_fleet_n;i++)
      if(g_fleet_magics[i]==m) return true;
   return false;
}

double FleetOpenRisk(int &no_sl_count)
{
   no_sl_count=0;
   double total=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0 || !PositionSelectByTicket(t)) continue;
      if(!IsFleetMagic((long)PositionGetInteger(POSITION_MAGIC))) continue;
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      string sym   = PositionGetString(POSITION_SYMBOL);
      if(sl<=0){ no_sl_count++; continue; }
      double ts = SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE);
      double tv = SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE);
      if(ts<=0 || tv<=0) continue;
      total += MathAbs(entry-sl)/ts*tv*vol;
   }
   return total;
}

//+------------------------------------------------------------------+
bool DailyLossHalted()
{
   if(InpMaxDailyLossPct<=0 || g_day_start_eq<=0) return false;
   // FIX: Use realized daily P&L (g_daily_pnl) instead of equity comparison.
   // Equity comparison is unreliable because:
   // 1. Manual close detection used wrong price -> false P&L -> false halt
   // 2. Equity fluctuates with spread/slippage even without trades
   // g_daily_pnl only accumulates from ACTUAL trade closes.
   double daily_loss_pct = (g_daily_pnl < 0) ? MathAbs(g_daily_pnl) / g_day_start_eq : 0;
   return (daily_loss_pct >= InpMaxDailyLossPct);
}

//+------------------------------------------------------------------+
ENUM_REGIME ClassifyRegime()
{
   double emaF[1],emaM[1],emaS[1],atr[1];
   if(CopyBuffer(hEMA_Fast_R,0,1,1,emaF)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Mid_R,0,1,1,emaM)<1)  return REGIME_NO_TRADE;
   if(CopyBuffer(hEMA_Slow_R,0,1,1,emaS)<1) return REGIME_NO_TRADE;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)       return REGIME_NO_TRADE;

   if(atr_hist_count < ArraySize(atr_hist))
      atr_hist[atr_hist_count++] = atr[0];
   else
   {
      for(int i=0;i<ArraySize(atr_hist)-1;i++) atr_hist[i]=atr_hist[i+1];
      atr_hist[ArraySize(atr_hist)-1]=atr[0];
   }

   double pct = CalcATRPercentile(atr[0]);
   if(pct > InpAtrHighPct) return REGIME_HIGH_VOL;
   if(pct < InpAtrLowPct)  return REGIME_NO_TRADE;

   double price = iClose(_Symbol, g_tf_regime, 1);
   double sep = MathAbs(emaF[0]-emaM[0])/atr[0];

   if(emaF[0]>emaM[0] && emaM[0]>emaS[0] && price>emaF[0] && sep>=InpMinEmaSep)
      return REGIME_BULLISH;
   if(emaF[0]<emaM[0] && emaM[0]<emaS[0] && price<emaF[0] && sep>=InpMinEmaSep)
      return REGIME_BEARISH;

   return REGIME_RANGING;
}

double CalcATRPercentile(double current)
{
   if(atr_hist_count < 40) return 50.0;
   int below=0, look=MathMin(InpAtrLookback, atr_hist_count);
   for(int i=atr_hist_count-look; i<atr_hist_count; i++)
      if(current > atr_hist[i]) below++;
   return (double)below/look*100.0;
}

//+------------------------------------------------------------------+
//| 5 CORE STRATEGIES                                                 |
//+------------------------------------------------------------------+
int StratPullback(double &score)
{
   score=0;
   if(g_regime != REGIME_BULLISH && g_regime != REGIME_BEARISH) return 0;

   double emaF[1], emaM[1], emaS[1], rsi[1], atr[1];
   if(CopyBuffer(hEMA_Fast_E,0,1,1,emaF)<1) return 0;
   if(CopyBuffer(hEMA_Mid_E,0,1,1,emaM)<1)  return 0;
   if(CopyBuffer(hEMA_Slow_E,0,1,1,emaS)<1) return 0;
   if(CopyBuffer(hRSI_E,0,1,1,rsi)<1)       return 0;
   if(CopyBuffer(hATR_E,0,1,1,atr)<1)       return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   double body  = price - iOpen(_Symbol,g_tf_entry,1);
   int dir = (g_regime==REGIME_BULLISH) ? 1 : -1;

   double pb = MathAbs(price - emaF[0]);
   if(pb < InpPullbackMin*atr[0] || pb > InpPullbackMax*atr[0]) return 0;

   if(dir>0 && (rsi[0]>65 || body<-0.1*atr[0])) return 0;
   if(dir<0 && (rsi[0]<35 || body>0.1*atr[0])) return 0;

   if(dir>0 && !(emaF[0]>emaM[0])) return 0;
   if(dir<0 && !(emaF[0]<emaM[0])) return 0;

   score = 4.0;
   return dir;
}

int StratBreakout(double &score)
{
   score=0;
   if(g_regime == REGIME_NO_TRADE || g_regime == REGIME_HIGH_VOL) return 0;

   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double price = iClose(_Symbol,g_tf_entry,1);
   double body  = price - iOpen(_Symbol,g_tf_entry,1);

   double hh=iHigh(_Symbol,g_tf_entry,1), ll=iLow(_Symbol,g_tf_entry,1);
   for(int i=2;i<=InpBreakoutBars;i++)
   {
      hh=MathMax(hh,iHigh(_Symbol,g_tf_entry,i));
      ll=MathMin(ll,iLow(_Symbol,g_tf_entry,i));
   }
   double buf = InpBreakoutBuffer * atr[0];

   int dir=0;
   if(g_regime==REGIME_BULLISH || g_regime==REGIME_RANGING) dir=1;
   if(g_regime==REGIME_BEARISH) dir=-1;

   if(dir>0 && price>hh+buf && body>0){ score=3.5; return 1; }
   if(dir<0 && price<ll-buf && body<0){ score=3.5; return -1; }
   return 0;
}

int StratMomentum(double &score)
{
   score=0;
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   double body = iClose(_Symbol,g_tf_entry,1) - iOpen(_Symbol,g_tf_entry,1);
   double range = iHigh(_Symbol,g_tf_entry,1) - iLow(_Symbol,g_tf_entry,1);
   if(range<=0) return 0;

   double ratio = MathAbs(body)/range;
   if(ratio < InpMomBodyMin) return 0;

   if(body>0 && ratio>0.55){ score=3.0; return 1; }
   if(body<0 && ratio>0.55){ score=3.0; return -1; }
   return 0;
}

int StratMeanRevert(double &score)
{
   score=0;
   if(g_regime != REGIME_RANGING) return 0;

   double rsi[1], bb_mid[1], bb_up[1], bb_lo[1];
   if(CopyBuffer(hRSI_E,0,1,1,rsi)<1) return 0;
   if(CopyBuffer(hBB_E,0,1,1,bb_mid)<1) return 0;
   if(CopyBuffer(hBB_E,1,1,1,bb_up)<1) return 0;
   if(CopyBuffer(hBB_E,2,1,1,bb_lo)<1) return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   double prev  = iClose(_Symbol,g_tf_entry,2);

   if(prev <= bb_lo[0] && price > bb_lo[0] && rsi[0] < InpRsiOversold)
   { score=3.8; return 1; }
   if(prev >= bb_up[0] && price < bb_up[0] && rsi[0] > InpRsiOverbought)
   { score=3.8; return -1; }
   return 0;
}

//+------------------------------------------------------------------+
int StratBandFade(double &score)
{
   score=0;
   if(g_regime != REGIME_RANGING && g_regime != REGIME_HIGH_VOL) return 0;
   if(!g_sigma_init || g_sigma_ema<=0) return 0;

   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return 0;
   if(atr[0]<=0) return 0;

   double price = iClose(_Symbol,g_tf_entry,1);
   if(g_sigma_now<=0 || price<=0) return 0;

   if(!(g_sigma_init && g_exp_ratio > InpBandVolExtRatio)) return 0;

   double z_dev   = g_z_dev;
   double sig_now = g_sigma_now;

   int dir=0;
   if(z_dev >=  InpBandZEntry) dir=-1;
   if(z_dev <= -InpBandZEntry) dir= 1;
   if(dir==0) return 0;

   int bar_sec = PeriodSeconds(g_tf_entry);
   if(bar_sec<=0) bar_sec=300;
   int bars = (int)MathMax(1, MathRound((double)InpBandHoldSec/bar_sec));
   double sigma_h  = sig_now*MathSqrt((double)bars);
   double stop_f   = InpBandStopSigmaMult*sigma_h;
   double target_f = InpBandTargetSigmaMult*sigma_h;
   if(stop_f<=0 || target_f<=0) return 0;
   if(target_f/stop_f < InpBandMinRR) return 0;
   if(stop_f > InpBandMaxStopPct) return 0;

   g_sig_is_band = true;
   g_sig_sl_atr  = stop_f*price/atr[0];
   g_sig_tp_atr  = target_f*price/atr[0];

   score = 4.2;
   g_last_band_dir = dir;
   return dir;
}

//+------------------------------------------------------------------+
int GenerateSignal(string &sig_type)
{
   g_regime = ClassifyRegime();
   if(g_regime==REGIME_NO_TRADE) return 0;

   g_sig_is_band=false; g_last_band_dir=0; g_sig_sl_atr=0; g_sig_tp_atr=0;

   double scores[5];
   int dirs[5];
   ArrayInitialize(scores,0);
   ArrayInitialize(dirs,0);

   int buy_score=0, sell_score=0, buy_cnt=0, sell_cnt=0;

   if(InpUsePullback)   { dirs[0]=StratPullback(scores[0]); }
   if(InpUseBreakout)   { dirs[1]=StratBreakout(scores[1]); }
   if(InpUseMomentum)   { dirs[2]=StratMomentum(scores[2]); }
   if(InpUseMeanRevert) { dirs[3]=StratMeanRevert(scores[3]); }
   if(InpUseBandFade)   { dirs[4]=StratBandFade(scores[4]); }

   const string LEGNAMES[5]={"PB","BO","MOM","MR","BF"};
   g_fired_legs="";
   for(int i=0;i<5;i++)
      if(dirs[i]!=0)
      {
         string sep=(g_fired_legs=="") ? "" : "|";
         g_fired_legs += sep+LEGNAMES[i]+(dirs[i]>0?"+":"-");
      }

   for(int i=0;i<5;i++)
   {
      if(dirs[i]>0){ buy_score += (int)scores[i]; buy_cnt++; }
      if(dirs[i]<0){ sell_score += (int)scores[i]; sell_cnt++; }
   }

   if(g_regime==REGIME_BULLISH) buy_score += 2;
   if(g_regime==REGIME_BEARISH) sell_score += 2;

   bool mom_demoted=false;
   if(!InpMomentumStandalone)
   {
      if(buy_cnt==1  && dirs[2]>0){ buy_score=0;  buy_cnt=0; mom_demoted=true; }
      if(sell_cnt==1 && dirs[2]<0){ sell_score=0; sell_cnt=0; mom_demoted=true; }
   }

   int final_dir=0;
   string skip_reason="";
   if(buy_score >= InpMinScore && buy_score > sell_score)
   {
      if(InpRequire2Strats && buy_cnt<2) skip_reason="need-2-strats-BUY";
      else final_dir=1;
   }
   else if(sell_score >= InpMinScore && sell_score > buy_score)
   {
      if(InpRequire2Strats && sell_cnt<2) skip_reason="need-2-strats-SELL";
      else final_dir=-1;
   }
   if(final_dir==0 && skip_reason=="")
      skip_reason=(buy_cnt==0 && sell_cnt==0)
                ? (mom_demoted ? "mom-demoted-lone-candle" : "no-legs")
                : StringFormat("score B%d/S%d < min %d", buy_score, sell_score, InpMinScore);

   if(g_sig_is_band && (final_dir==0 || g_last_band_dir!=final_dir))
   { g_sig_is_band=false; g_sig_sl_atr=0; g_sig_tp_atr=0; }

   if(final_dir!=0)
   {
      sig_type = StringFormat("SC%d%s", MathMax(buy_score,sell_score),
                              g_sig_is_band ? "B" : "");
      g_last_skip="";

      // v23.1: Capture the primary strategy for intelligence review
      g_last_strategy = "NONE";
      if(g_sig_is_band) g_last_strategy = "BF";
      else if(final_dir>0)
      {
         if(dirs[0]>0) g_last_strategy = "PB";
         else if(dirs[1]>0) g_last_strategy = "BO";
         else if(dirs[2]>0) g_last_strategy = "MOM";
         else if(dirs[3]>0) g_last_strategy = "MR";
      }
      else
      {
         if(dirs[0]<0) g_last_strategy = "PB";
         else if(dirs[1]<0) g_last_strategy = "BO";
         else if(dirs[2]<0) g_last_strategy = "MOM";
         else if(dirs[3]<0) g_last_strategy = "MR";
      }
   }
   else g_last_skip=skip_reason;

   if(g_fired_legs!="")
      Telem("sig", StringFormat(
         "\"sym\":\"%s\",\"action\":\"%s\",\"dir\":%d,\"reason\":\"%s\",\"legs\":\"%s\","
         "\"score_b\":%.1f,\"score_s\":%.1f,\"regime\":\"%s\",\"z\":%.3f,\"exp\":%.3f,"
         "\"sigma\":%.6f,\"sigma_base\":%.6f,\"band_geom\":%s",
         _Symbol, (final_dir!=0?"TAKE":"SKIP"), final_dir,
         (final_dir!=0?"-":skip_reason), g_fired_legs,
         buy_score, sell_score, RegimeToStr(g_regime),
         g_z_dev, g_exp_ratio, g_sigma_now, g_sigma_ema,
         g_sig_is_band?"true":"false"));

   return final_dir;
}

//+------------------------------------------------------------------+
//| v23: Volume scaling — reduce lot after consecutive losses         |
//+------------------------------------------------------------------+
double GetScaledVolume(double base_vol)
{
   if(!InpScaleAfterLoss || g_consec_loss<=0) return base_vol;

   double scale = MathPow(InpScaleFactor, (double)g_consec_loss);
   scale = MathMax(scale, InpMinVolScale);
   double scaled = base_vol * scale;

   if(scaled < base_vol)
      PrintFormat(VTAG+"Volume scaled %.2f -> %.2f (%d consecutive losses, factor=%.2f)",
                  base_vol, scaled, g_consec_loss, scale);
   return scaled;
}

//+------------------------------------------------------------------+
void OpenTrade(int direction, string sig_type)
{
   double atr[1]; if(CopyBuffer(hATR_E,0,1,1,atr)<1) return;

   double entry = direction>0 ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID);

   double stop_dist;
   if(g_sig_is_band && g_sig_sl_atr>0)
      stop_dist = g_sig_sl_atr*atr[0];
   else
   {
      stop_dist = 1.7 * atr[0];
      if(direction>0)
      {
         double lo = iLow(_Symbol,g_tf_entry,1);
         for(int k=2;k<=5;k++) lo=MathMin(lo,iLow(_Symbol,g_tf_entry,k));
         stop_dist = MathMax(stop_dist, entry - (lo - 0.15*atr[0]));
      }
      else
      {
         double hi = iHigh(_Symbol,g_tf_entry,1);
         for(int k=2;k<=5;k++) hi=MathMax(hi,iHigh(_Symbol,g_tf_entry,k));
         stop_dist = MathMax(stop_dist, (hi + 0.15*atr[0]) - entry);
      }
      if(stop_dist < atr[0]*0.5) stop_dist = atr[0]*0.5;
   }

   double min_stop = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
   if(min_stop>0 && stop_dist<min_stop) stop_dist=min_stop;
   if(stop_dist > entry*0.03) stop_dist = entry*0.03;

   double tp_dist = (g_sig_is_band && g_sig_tp_atr>0) ? g_sig_tp_atr*atr[0]
                                                      : InpTpMult*stop_dist;
   double sl = direction>0 ? entry-stop_dist : entry+stop_dist;
   double tp = direction>0 ? entry+tp_dist : entry-tp_dist;

   // Risk volume (with v23 consecutive-loss scaling)
   // v26.14: meta-labeling P(win) multiplier scales the target risk before sizing
   double ml_mult = MetaLabelMultiplier(direction);
   if(ml_mult <= 0.0)
   {
      PrintFormat(VTAG+"SKIP %s — meta-label gate: P(win) too low for this context (%s/%s)",
                  direction>0?"BUY":"SELL", RegimeToStr(g_regime), direction>0?"long":"short");
      g_cooldown=1;
      return;
   }
   double risk_money = g_eq * InpRiskPerTrade * ml_mult;
   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tick_size<=0 || tick_value<=0) return;
   double vol = risk_money / ((stop_dist/tick_size)*tick_value);
   vol = NormalizeVolume(vol);
   if(vol<=0) return;

   // v23: apply consecutive-loss volume scaling
   vol = GetScaledVolume(vol);
   vol = NormalizeVolume(vol);
   if(vol<=0) return;

   // EFFECTIVE-RISK GUARDRAIL
   double eff_risk   = vol*((stop_dist/tick_size)*tick_value);
   double cap_money  = g_eq*InpMaxEffectiveRiskPct/100.0;
   if(eff_risk > cap_money)
   {
      PrintFormat(VTAG+"SKIP %s — min-lot risk $%.2f exceeds cap $%.2f (%.0f%% equity)",
                  direction>0?"BUY":"SELL", eff_risk, cap_money, InpMaxEffectiveRiskPct);
      g_cooldown=1;
      return;
   }
   g_risk_money = eff_risk;
   if(eff_risk > g_eq*0.05)
      PrintFormat(VTAG+"WARNING: effective risk $%.2f = %.1f%% of equity",
                  eff_risk, eff_risk/g_eq*100);

   // ACCOUNT-WIDE EXPOSURE GUARD
   int no_sl=0;
   double fleet_risk = FleetOpenRisk(no_sl);
   double acct_eq    = AccountInfoDouble(ACCOUNT_EQUITY);
   double total_cap  = acct_eq*InpMaxTotalRiskPct/100.0;
   if(fleet_risk + eff_risk > total_cap)
   {
      PrintFormat(VTAG+"SKIP %s — ACCOUNT GUARD: fleet $%.2f + new $%.2f > cap $%.2f",
                  direction>0?"BUY":"SELL", fleet_risk, eff_risk, total_cap);
      Telem("risk_block", StringFormat(
         "\"sym\":\"%s\",\"fleet_risk\":%.2f,\"new_risk\":%.2f,\"ceiling\":%.2f,\"eq\":%.2f",
         _Symbol, fleet_risk, eff_risk, total_cap, acct_eq));
      g_cooldown=1;
      return;   // v26.14 fix: OpenTrade is void — no value return
   }

   bool ok=false;
   if(InpLiveExecution)
   {
      PrintFormat(VTAG+"Executing %s vol=%.2f SL=%.5f TP=%.5f", direction>0?"BUY":"SELL", vol, sl, tp);
      if(direction>0) ok=trade.Buy(vol,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"MITEM_v"+APP_VERSION);
      else            ok=trade.Sell(vol,_Symbol,0,NormalizeDouble(sl,_Digits),NormalizeDouble(tp,_Digits),"MITEM_v"+APP_VERSION);
      if(!ok)
      {
         uint retcode = trade.ResultRetcode();
         string desc   = trade.ResultRetcodeDescription();
         PrintFormat(VTAG+"ORDER FAILED retcode=%d desc=%s", retcode, desc);
      }
   }
   else { g_ticket=(ulong)TimeCurrent(); ok=true; Print(VTAG+"PAPER MODE"); }   if(!ok) { g_cooldown = InpCoolDownBars; return; }

   g_ticket=0;
   for(int a=0;a<6;a++)
   {
      Sleep(60);
      for(int i=PositionsTotal()-1;i>=0;i--)
      {
         ulong t=PositionGetTicket(i);
         if(t>0 && PositionGetInteger(POSITION_MAGIC)==InpMagic && PositionGetString(POSITION_SYMBOL)==_Symbol)
         { g_ticket=t; break; }
      }
      if(g_ticket>0) break;
   }
   if(g_ticket==0) g_ticket=trade.ResultOrder();

   g_dir=direction; g_entry=entry; g_sl=sl; g_tp=tp;
   g_orig_risk=stop_dist; g_position_volume=vol;
   g_entry_time=TimeCurrent(); g_bars_held=0;
   g_high_water_r=0;  // v23: reset high-water mark
   g_max_hold = (g_sig_is_band && g_sig_sl_atr>0)
      ? (int)MathMax(4, (int)MathRound((double)InpBandHoldSec/MathMax(60,PeriodSeconds(g_tf_entry)))+2)
      : InpMaxHoldBars;
   g_trades_today++;

   if(InpDrawSignals) DrawArrow(direction,TimeCurrent(),entry,sig_type);
   PrintFormat(VTAG+"%s %s @%.5f SL=%.5f TP=%.5f vol=%.2f", sig_type, direction>0?"BUY":"SELL", entry,sl,tp,vol);

   Telem("open", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"dir\":%d,\"entry\":%.5f,\"sl\":%.5f,\"tp\":%.5f,"
      "\"vol\":%.2f,\"eff_risk\":%.2f,\"band\":%s,\"legs\":\"%s\",\"regime\":\"%s\","
      "\"tf\":\"%s\",\"z\":%.3f,\"exp\":%.3f",
      _Symbol, g_ticket, direction, entry, sl, tp, vol, g_risk_money,
      (g_sig_is_band?"true":"false"), g_fired_legs, RegimeToStr(g_regime),
      EnumToString(g_tf_entry), g_z_dev, g_exp_ratio));
}

//+------------------------------------------------------------------+
//| v24: Crash/Boom trade opener — uses CB-specific risk sizing      |
//| v26.13: returns bool — true = order accepted (or paper mode).    |
//| The tick-fade caller uses it to confirm/release the pending      |
//| spike; the M5 path ignores the return as before.                 |
//+------------------------------------------------------------------+
bool OpenCBTrade(int direction, double entry, double sl, double tp, string reason)
{
   double stop_dist = MathAbs(entry - sl);
   double tp_dist = MathAbs(tp - entry);
   if(stop_dist <= 0 || tp_dist <= 0) return(false);

   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   double min_lot    = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double lot_step   = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(tick_size<=0 || tick_value<=0) return(false);

   // v24: Use dynamic risk sizing from Crash/Boom engine
   double vol = g_cb.CalculateVolume(g_eq, stop_dist, tick_size, tick_value,
                                     min_lot, max_lot, lot_step);
   if(vol <= 0) return(false);

   //--- v26.6: RE-ANCHOR stops to the live price before sending.
   //    During fast spike retraces the signal-time entry is stale by the time
   //    the order reaches the broker (2026-08-30 Boom log: two fade orders
   //    rejected retcode 10016 "invalid stops" because the retrace outran
   //    the pre-computed SL). Delta-shift keeps the geometry intact;
   //    boundary clamps fix residual invalidity; abort if price already
   //    reached the target — the fade thesis is dead at that point.
   {
      double bid_now  = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double ask_now  = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double fill     = (direction > 0) ? ask_now : bid_now;
      double delta    = fill - entry;
      if(MathAbs(delta) > 0) { entry += delta; sl += delta; tp += delta; }
      double st       = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL) * _Point;
      if(direction > 0)
      {
         if(sl >= bid_now - st) sl = bid_now - st - tick_size;   // tighten only (risk-reducing)
         if(tp <= ask_now + st + tick_size)
          {         PrintFormat(VTAG+"ENTRY ABORT %s — price outran target during send (tp %.5f vs ask %.5f)",
                     direction>0?"BUY":"SELL", tp, ask_now);
             CBRecordReject("abort-tp-outran", reason);   // v26.12
             return(false);
          }
      }
      else
      {
         if(sl <= ask_now + st) sl = ask_now + st + tick_size;   // tiny widening for validity; micro-fit re-tightens below
         if(tp >= bid_now - st - tick_size)
          {         PrintFormat(VTAG+"ENTRY ABORT %s — price outran target during send (tp %.5f vs bid %.5f)",
                     direction>0?"BUY":"SELL", tp, bid_now);
             CBRecordReject("abort-tp-outran", reason);   // v26.12
             return(false);
          }
      }
      entry = fill;
      stop_dist = MathAbs(entry - sl);
      tp_dist   = MathAbs(tp - entry);
   }

   //--- v26.6: MICRO-BALANCE FIT — on a micro account the risk budget buys
   //    less than one minimum lot, so the min-lot clamp silently multiplies
   //    planned risk (2026-08-30: $14 equity, 0.20 lots x 4.1-unit stop =
   //    5.7% per trade and 20-48% per spike gap-through). Rescale SL/TP to
   //    fit the balance instead of oversizing or freezing the EA.
   if(InpMicroFitPct > 0)
   {
      double eff0    = vol * ((stop_dist / tick_size) * tick_value);
      double fit_cap = g_eq * InpMicroFitPct / 100.0;
      if(eff0 > fit_cap)
      {
         double old_stop  = stop_dist;
         double per_unit  = tick_value / tick_size;                // $ per price-unit per 1.0 lot
         double max_stop  = fit_cap / (vol * per_unit);
         double sprd      = SymbolInfoDouble(_Symbol,SYMBOL_ASK) - SymbolInfoDouble(_Symbol,SYMBOL_BID);
         double stp_level = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL) * _Point;
         double floor_stop= MathMax(sprd*1.2 + stp_level + 3.0 * tick_size, 2.0 * tick_size);
         double new_stop  = MathMax(max_stop, floor_stop);
         double scale     = new_stop / stop_dist;
         if(direction > 0) { sl = entry - new_stop; tp = entry + tp_dist * scale; }
         else              { sl = entry + new_stop; tp = entry - tp_dist * scale; }
         stop_dist = new_stop;
         double eff1 = vol * ((stop_dist / tick_size) * tick_value);
         PrintFormat(VTAG+"MICRO-FIT stop %.2f->%.2f (eff risk $%.2f->$%.2f = %.2f%% eq)%s",
                     old_stop, new_stop, eff0, eff1, eff1 / MathMax(g_eq,0.01) * 100.0,
                     (max_stop < floor_stop) ? " [floor: spread-bound]" : "");
      }
   }

   // EFFECTIVE-RISK GUARDRAIL
   double eff_risk = vol * ((stop_dist/tick_size)*tick_value);
   double cap_money = g_eq * InpMaxEffectiveRiskPct / 100.0;
   int fleet_no_sl = 0;
   double fleet_risk = FleetOpenRisk(fleet_no_sl);
   double fleet_cap = g_eq * InpMaxTotalRiskPct / 100.0;
   if(fleet_risk + eff_risk > fleet_cap)
   {
      PrintFormat(VTAG+"SKIP %s — fleet risk $%.2f + new $%.2f exceeds cap $%.2f",
                  direction>0?"BUY":"SELL", fleet_risk, eff_risk, fleet_cap);
      g_cooldown = 1;
      return(false);
   }
   if(eff_risk > cap_money)
   {
      PrintFormat(VTAG+"SKIP %s — min-lot risk $%.2f exceeds cap $%.2f",
                  direction>0?"BUY":"SELL", eff_risk, cap_money);
      g_cooldown = 1;
      return(false);
   }
   g_risk_money = eff_risk;

   bool ok = false;
   if(InpLiveExecution)
   {
      PrintFormat(VTAG+"Executing %s vol=%.2f SL=%.5f TP=%.5f | %s",
                  direction>0?"BUY":"SELL", vol, sl, tp, reason);
      if(direction>0) ok = trade.Buy(vol, _Symbol, 0, NormalizeDouble(sl,_Digits), NormalizeDouble(tp,_Digits), "CB_v"+APP_VERSION);
      else            ok = trade.Sell(vol, _Symbol, 0, NormalizeDouble(sl,_Digits), NormalizeDouble(tp,_Digits), "CB_v"+APP_VERSION);
      if(!ok)
      {
         uint retcode = trade.ResultRetcode();
         string desc = trade.ResultRetcodeDescription();
         PrintFormat(VTAG+"ORDER FAILED retcode=%d desc=%s", retcode, desc);
         // v26.12: quantify the lost fade opportunity for the offline loop
         CBRecordReject(StringFormat("retcode=%u %s", retcode, desc), reason);
      }
   }
   else { g_ticket = (ulong)TimeCurrent(); ok = true; Print(VTAG+"PAPER MODE"); }

   if(!ok) { g_cooldown = InpCoolDownBars; return(false); }

   g_ticket = 0;
   for(int a=0; a<6; a++)
   {
      Sleep(60);
      for(int i=PositionsTotal()-1; i>=0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t>0 && PositionGetInteger(POSITION_MAGIC)==InpMagic && PositionGetString(POSITION_SYMBOL)==_Symbol)
         { g_ticket = t; break; }
      }
      if(g_ticket > 0) break;
   }
   if(g_ticket == 0) g_ticket = trade.ResultOrder();
   if(g_ticket == 0)
   {
      Print(VTAG+"ORDER accepted but position ticket was not found; waiting for recovery");
      g_cooldown = InpCoolDownBars;
      return(false);
   }

   g_dir = direction; g_entry = entry; g_sl = sl; g_tp = tp;
   g_orig_risk = stop_dist; g_position_volume = vol;
   g_entry_time = TimeCurrent(); g_bars_held = 0;
   g_high_water_r = 0;
   g_max_hold = InpMaxHoldBars;
   g_trades_today++;
   g_sig_is_band = false;

   if(InpDrawSignals) DrawArrow(direction, TimeCurrent(), entry, reason);
   PrintFormat(VTAG+"%s %s @%.5f SL=%.5f TP=%.5f vol=%.2f | %s",
               reason, direction>0?"BUY":"SELL", entry, sl, tp, vol,
               g_cb.GetDashboardInfo());

   Telem("open", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"dir\":%d,\"entry\":%.5f,\"sl\":%.5f,\"tp\":%.5f,"
      "\"vol\":%.2f,\"eff_risk\":%.2f,\"band\":false,\"legs\":\"%s\",\"regime\":\"%s\","
      "\"tf\":\"%s\",\"z\":%.3f,\"exp\":%.3f",
      _Symbol, g_ticket, direction, entry, sl, tp, vol, g_risk_money,
      reason, RegimeToStr(g_regime),
      EnumToString(g_tf_entry), g_z_dev, g_exp_ratio));
   return(true);
}

//+------------------------------------------------------------------+
double NormalizeVolume(double vol)
{
   double minv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxv=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(step<=0) step=0.01;
   vol=MathFloor(vol/step)*step;
   if(vol<minv) vol=minv; if(vol>maxv) vol=maxv;
   return NormalizeDouble(vol,2);
}

//+------------------------------------------------------------------+
//| v23: MANAGE POSITION — graduated exit, profit lock, trailing      |
//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByTicket(g_ticket)){ g_ticket=0; return; }
   g_bars_held++;

   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);

   // hard checks first: stop / target
   if(g_dir>0){ if(bid<=g_sl){ClosePosition("STOP");return;} if(bid>=g_tp){ClosePosition("TARGET");return;} }
   else       { if(ask>=g_sl){ClosePosition("STOP");return;} if(ask<=g_tp){ClosePosition("TARGET");return;} }

   double r_now = g_orig_risk>0 ? (g_dir>0?(bid-g_entry):(g_entry-ask))/g_orig_risk : 0;

   // v24.1: CRASH/BOOM SPIKE-AWARE EXIT — check spike probability first
   if(InpCrashBoomMode && g_cb.IsEnabled())
   {
      double spike_prob = g_cb.GetSpikeProbability();
      
      // If spike probability > 80% and trade is in profit, exit NOW
      if(spike_prob > 0.80 && r_now > 0)
      {
         PrintFormat(VTAG+"CB SPIKE EXIT — prob=%.2f R=+.2f, banking profit before spike",
                     spike_prob, r_now);
         ClosePosition("CB-SPIKE");
         return;
      }
      
      // If spike probability > 60% and trade is losing, cut immediately
      if(spike_prob > 0.60 && r_now < 0)
      {
         PrintFormat(VTAG+"CB SPIKE-CUT — prob=%.2f R=%.2f, cutting loss before spike",
                     spike_prob, r_now);
         ClosePosition("CB-SPIKE-CUT");
         return;
      }
      
      // CB-specific tighter trailing: start at 0.5R instead of 1.0R
      // v26.13: routed through ValidStopForModify — an unguarded modify during
      // a spike (price moving fast) was the retcode-10016 "invalid stops"
      // source on the Boom chart (SL landed inside the stops level, or the
      // TP sat on the wrong side of a just-gapped price).
      if(r_now >= 0.5)
      {
         double cb_dist = 0.4 * g_orig_risk;  // tighter than standard 0.7R
         if(g_dir>0){ double ns=NormalizeDouble(ValidStopForModify(bid-cb_dist,1,g_tp),_Digits); if(ns>g_sl && ns>g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl=ns; }
         else       { double ns=NormalizeDouble(ValidStopForModify(ask+cb_dist,-1,g_tp),_Digits); if(ns<g_sl && ns<g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl=ns; }
      }
      
      // CB-specific profit lock: lock at 0.3R if reached 0.8R (tighter than standard)
      if(g_high_water_r >= 0.8 && r_now <= 0.3 && r_now > 0)
      {
         PrintFormat(VTAG+"CB PROFIT LOCK — high-water %.2fR now %.2fR", g_high_water_r, r_now);
         ClosePosition("CB-PLOCK");
         return;
      }
      
      // CB-specific early cut: 4 bars instead of 6
      if(g_bars_held >= 4 && r_now <= -0.3 && g_high_water_r < 0.2)
      {
         PrintFormat(VTAG+"CB EARLY CUT — %d bars R=%.2f", g_bars_held, r_now);
         ClosePosition("CB-ECUT");
         return;
      }
   }

   // v23: update high-water mark
   if(r_now > g_high_water_r) g_high_water_r = r_now;

   // v23: PROFIT LOCK — trade reached 1R+ then reversed below InpProfitLockR
   if(g_high_water_r >= 1.0 && r_now <= InpProfitLockR && r_now > 0)
   {
      PrintFormat(VTAG+"PROFIT LOCK — high-water %.2fR now at %.2fR, banking profit", g_high_water_r, r_now);
      ClosePosition("PLOCK");
      return;
   }

   // v23: GRADUATED TIME EXIT — early cut losers that never got profitable
   if(InpGraduatedExit && g_bars_held >= InpEarlyCutBars && g_bars_held < g_max_hold)
   {
      if(r_now <= InpEarlyCutMaxR && g_high_water_r < 0.3)
      {
         PrintFormat(VTAG+"EARLY CUT — %d bars, R=%.2f, high-water=%.2fR, cutting loss",
                     g_bars_held, r_now, g_high_water_r);
         ClosePosition("ECUT");
         return;
      }
   }

   // v23: EXTEND HOLD for winning trades — don't time-exit a trade that's running
   int effective_hold = g_max_hold;
   if(InpGraduatedExit && r_now > 0.3 && g_bars_held >= g_max_hold)
   {
      effective_hold = (int)(g_max_hold * InpExtendWinMult);
      if(g_bars_held >= effective_hold)
      {
         // still winning at extended hold — let it go (don't cut a winner)
         PrintFormat(VTAG+"EXTENDED HOLD — %d bars, R=%.2f, letting winner run", g_bars_held, r_now);
      }
   }

   // time exit (only if not a winner being extended)
   if(g_bars_held >= effective_hold)
   {
      if(r_now > 0.2)
      {
         // v23: winning trade at time limit — don't cut it, let trailing handle it
         PrintFormat(VTAG+"WINNING TIME — %d bars, R=%.2f, holding via trailing", g_bars_held, r_now);
      }
      else
         { ClosePosition("TIME"); return; }
   }

   // breakeven: move SL to entry + 2 points at +1R
   // v26.13: validity guard before every PositionModify — on Boom/Crash the
   // price can gap between bid/ask read and the modify call, so an unguarded
   // SL can land inside the broker's stops level → retcode 10016 spam.
   if(InpUseBreakeven && r_now >= InpBeTriggerR)
   {
      double be = g_dir>0 ? g_entry+2*_Point : g_entry-2*_Point;
      if((g_dir>0 && g_sl<be) || (g_dir<0 && g_sl>be))
      {
         double be_sl = NormalizeDouble(ValidStopForModify(be, g_dir, g_tp), _Digits);
         if(be_sl != 0 && ((g_dir>0 && be_sl>g_sl) || (g_dir<0 && be_sl<g_sl)))
            if(trade.PositionModify(g_ticket,be_sl,g_tp)) g_sl=be_sl;
      }
   }

   // trailing stop (standard mode — CB mode handled above)
   if(!InpCrashBoomMode && InpUseTrailing && r_now >= InpTrailStartR)
   {
      double dist = InpTrailDistR * g_orig_risk;
      if(g_dir>0){ double ns=NormalizeDouble(ValidStopForModify(bid-dist,1,g_tp),_Digits); if(ns>g_sl && ns>g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl=ns; }
      else       { double ns=NormalizeDouble(ValidStopForModify(ask+dist,-1,g_tp),_Digits); if(ns<g_sl && ns<g_entry) if(trade.PositionModify(g_ticket,ns,g_tp)) g_sl=ns; }
   }
}

//+------------------------------------------------------------------+
//| v26.13: stop validity guard for PositionModify                    |
//| Clamps a desired SL to the broker's SYMBOL_TRADE_STOPS_LEVEL       |
//| against the CURRENT bid/ask and rejects impossible stops (returns  |
//| 0 → caller skips the modify) instead of spamming retcode 10016.    |
//| Tightening-only semantics are preserved by the caller's compare.   |
//+------------------------------------------------------------------+
double ValidStopForModify(double desired_sl, int dir, double tp)
{
   double bid = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double st  = (double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double ts  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(ts<=0) ts=_Point;
   if(dir>0)
   {
      // long: SL must be < bid - stopsLevel; TP must be > bid + stopsLevel
      double max_sl = bid - st - ts;
      if(desired_sl >= max_sl)
      {
         if(max_sl <= 0) return 0;                       // nothing valid
         desired_sl = max_sl;                            // clamp tighter-bound
      }
      if(tp > 0 && tp <= bid + st + ts) return 0;        // TP invalid vs current price → skip
   }
   else
   {
      // short: SL must be > ask + stopsLevel; TP must be < ask - stopsLevel
      double min_sl = ask + st + ts;
      if(desired_sl <= min_sl)
      {
         desired_sl = min_sl;
      }
      if(tp > 0 && tp >= ask - st - ts) return 0;
   }
   return NormalizeDouble(desired_sl, _Digits);
}

//+------------------------------------------------------------------+
void ClosePosition(string reason)
{
   if(g_ticket==0) return;
   ulong closed_ticket=g_ticket;
   double exit_p = g_dir>0 ? SymbolInfoDouble(_Symbol,SYMBOL_BID) : SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   if(!trade.PositionClose(g_ticket)) return;

   HandleTradeClose(exit_p, reason, 0);   // v26.4: shared close handler
}

//+------------------------------------------------------------------+
void CreateDashboard()
{
   // v26.9-fix: a crashed session leaves its HUD labels on the chart forever
   // (OnDeinit never ran, so the delete loop in OnDeinit was skipped), and a
   // bare OBJ_LABEL renders as the terminal's default "Label" text — the
   // Aug-31 spam on both charts. Sweep stale M230_* objects first, and give
   // every fresh label text immediately so a mid-run crash can never leave
   // mystery labels behind again.
   ObjectsDeleteAll(0, "M230_");
   for(int i=0;i<26;i++)
   {
      dash_names[i]="M230_"+IntegerToString(i);
      ObjectCreate(0,dash_names[i],OBJ_LABEL,0,0,0);
      ObjectSetString(0,dash_names[i],OBJPROP_TEXT,"...");   // replaced on first tick
      ObjectSetInteger(0,dash_names[i],OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,dash_names[i],OBJPROP_XDISTANCE,10);
      ObjectSetInteger(0,dash_names[i],OBJPROP_YDISTANCE,15+i*15);
      ObjectSetString(0,dash_names[i],OBJPROP_FONT,"Consolas");
      ObjectSetInteger(0,dash_names[i],OBJPROP_FONTSIZE,9);
   }
}

void UpdateDashboard()
{
   double wr = g_trades>0 ? 100.0*g_wins/g_trades : 0;
   double atr[1]; CopyBuffer(hATR_E,0,0,1,atr);
   double pct = CalcATRPercentile(atr[0]);

   string L[26];
   L[0]=StringFormat("=== MITEMSHUB AI v%s ===", APP_VERSION);
   L[1]=StringFormat("%s | %s -> %s",_Symbol,EnumToString(g_tf_entry),EnumToString(g_tf_regime));
   // v23.1: Show real-time session P&L including unrealized gains
   double realtime_pnl = g_session_pnl;
   if(g_ticket>0 && PositionSelectByTicket(g_ticket))
   {
      double cur = g_dir>0?SymbolInfoDouble(_Symbol,SYMBOL_BID):SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double unr = g_dir>0 ? (cur-g_entry) : (g_entry-cur);
      double unr_risk = g_orig_risk>0 ? unr/g_orig_risk : 0;
      realtime_pnl += unr_risk * g_risk_money;
   }
   L[2]=StringFormat("Equity: $%.2f | Session: $%+.2f",g_eq, realtime_pnl);
   L[3]=StringFormat("Regime: %s | ATR%%: %.0f",RegimeToStr(g_regime),pct);
   // v23.1: Show closed trades + open position count
   int open_count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t>0 && IsFleetMagic((long)PositionGetInteger(POSITION_MAGIC)) &&
         PositionGetString(POSITION_SYMBOL)==_Symbol)
         open_count++;
   }
   L[4]=StringFormat("Trades: %d closed | Open: %d | WR: %.1f%% | R: %+.2f",
                      g_trades, open_count, wr, g_total_r);
   L[5]=StringFormat("Status: %s%s", g_paused?"PAUSED":(DailyLossHalted()?"DAILY-HALT":"ACTIVE"),
        IsSessionActive()?" | SESSION-ON":" | SESSION-OFF");
   if(InpCrashBoomMode)
      L[6]=StringFormat("CB: %s | Mode: FADE-ONLY | Grind: %s | DirFilter: %s | TickFade: %s",
         InpIsCrashIndex?"CRASH":"BOOM", InpCBEnableGrind?"ON":"OFF",
         InpCBRequireSpikeDirection?"ON":"OFF", InpCBTickFade?"ON":"OFF");
   else
      L[6]=StringFormat("Strats: PB=%s BO=%s MOM=%s MR=%s BF=%s",
         InpUsePullback?"ON":"OFF", InpUseBreakout?"ON":"OFF",
         InpUseMomentum?"ON":"OFF", InpUseMeanRevert?"ON":"OFF", InpUseBandFade?"ON":"OFF");
   L[7]=StringFormat("MinScore: %d | 2+Agree: %s | Cooldown: %d",InpMinScore,InpRequire2Strats?"YES":"NO", g_cooldown);
   L[8]=InpCrashBoomMode
      ? StringFormat("CB Risk: %.2f%% | Cap: %.0f%% | MicroFit: %.1f%% | Sess: %02d:00-%02d:%02d | Fade TP: %.1fx | Hold: %d | Thr: %.1fx%s",
         InpCBBaseRisk, InpMaxEffectiveRiskPct, InpMicroFitPct,
         InpSessionStartHour, InpSessionEndHour - 1, 60 - MathMax(InpSessionEndOffsetMin, 0),
         InpIsCrashIndex ? InpCBFadeTP : InpCBFadeTP, InpMaxHoldBars,
         InpCBSpikeThreshold, InpCBMicroFade?" MICRO":"" )
      : StringFormat("Risk: %.2f%% (cap %.0f%%) | TP: %.1fx | Hold: %d",
         InpRiskPerTrade*100,InpMaxEffectiveRiskPct,InpTpMult,InpMaxHoldBars);
   L[9]=StringFormat("Band: z>=%.1f tgt=%.2f sig | Trail: %s (%.1fR/%.1fR) BE: %s",
        InpBandZEntry,InpBandTargetSigmaMult,
        InpUseTrailing?"ON":"OFF",InpTrailStartR,InpTrailDistR,
        InpUseBreakeven?"ON":"OFF");
   L[10]=(g_sigma_init && g_sigma_now>0)
        ? StringFormat("Telem: z=%+.2f exp=%.2fx sig=%.5f %s",
            g_z_dev,g_exp_ratio,g_sigma_now,
            (InpUseGarch && g_garch_ok ? (g_garch.Observations() >= InpGarchWarmupBars ? "[GARCH]" : "[GARCH warmup]") : "[legacy sigma]"))
        : "Telem: warming up...";
   {
      int nsl=0;
      double fr=FleetOpenRisk(nsl);
      double cap=AccountInfoDouble(ACCOUNT_EQUITY)*InpMaxTotalRiskPct/100.0;
      L[11]=StringFormat("Guard: fleet $%.2f / $%.2f cap%s",
                         fr,cap, nsl>0?StringFormat(" [%d no-SL!]",nsl):"");
   }
   L[12]=StringFormat("GradExit: %s ECut@%.1fR/%dbars | PLock: %.1fR",
        InpGraduatedExit?"ON":"OFF", InpEarlyCutMaxR, InpEarlyCutBars, InpProfitLockR);
   L[13]=StringFormat("ScaleLoss: %s (%.0f%% per loss, floor %.0f%%) | ConsecLoss: %d",
        InpScaleAfterLoss?"ON":"OFF", InpScaleFactor*100, InpMinVolScale*100, g_consec_loss);
   // v26.2: spike slippage — the real cost of gap-through stops
   L[14]=StringFormat("SpikeSlip: stops hit %d | gap-through %d (avg %+.2fR) | cum slip %+.2fR",
        g_stop_n, g_gap_loss_n,
        (g_gap_loss_n>0 ? g_gap_loss_r_sum/g_gap_loss_n : 0.0),
        g_slip_r_sum);
   // v26.14: meta-labeling status
   L[15]=InpUseMetaLabel
        ? StringFormat("MetaLabel: %s | rows=%d | next mult=%+.2fx",
                       InpMetaLabelCSV, g_ml_rows, MetaLabelMultiplier(1))
        : "MetaLabel: OFF";

   int line=16;   // v26.14: L[15] is the MetaLabel line now
   // v23.1: Always scan for open positions (not just g_ticket)
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0 || !PositionSelectByTicket(t)) continue;
      if(!IsFleetMagic((long)PositionGetInteger(POSITION_MAGIC))) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      double pe=PositionGetDouble(POSITION_PRICE_OPEN);
      double psl=PositionGetDouble(POSITION_SL);
      double ptp=PositionGetDouble(POSITION_TP);
      double pvol=PositionGetDouble(POSITION_VOLUME);
      int pdir = PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1;
      double cur = pdir>0?SymbolInfoDouble(_Symbol,SYMBOL_BID):SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      double prisk = MathAbs(pe-psl);
      double rnow = prisk>0 ? (pdir>0?(cur-pe):(pe-cur))/prisk : 0;
      L[line++]=StringFormat("OPEN %s %.2flot @%.5f R:%+.2f SL=%.0f TP=%.0f",
                             pdir>0?"BUY":"SELL",pvol,pe,rnow,psl,ptp);
      if(line>=25) break;
   }

   // v23.1: Intelligence layer status (v26.5: includes CB modes; v26.11: shared STRAT_NAMES)
   {
      double best_r = -999; int best_i = -1;
      double worst_r = 999; int worst_i = -1;
      for(int i=0; i<STRAT_SLOTS; i++)
      {
         if(g_strat_trades[i] < 3) continue;
         if(g_strat_total_r[i] > best_r) { best_r = g_strat_total_r[i]; best_i = i; }
         if(g_strat_total_r[i] < worst_r) { worst_r = g_strat_total_r[i]; worst_i = i; }
      }
      if(best_i >= 0)
         L[line++]=StringFormat("Intel: Best=%s(%+.1fR) Worst=%s(%+.1fR) Reviews:%d",
                                STRAT_NAMES[best_i], best_r, STRAT_NAMES[worst_i], worst_r,
                                g_last_strategy_review);
      else
         L[line++]="Intel: Collecting data... (need 15+ trades)";
      // v26.12: lost fade opportunities (rejected/aborted entries) — visible at a glance
      if(g_cb_reject_total > 0)
         L[line++]=StringFormat("Rejects: %d total / %d today (streak %d) last: %s",
                                g_cb_reject_total, g_cb_reject_today,
                                g_cb_reject_streak, g_cb_reject_last);
      // v26.12: lost fade opportunities (rejected/aborted entries) — visible at a glance
      if(g_cb_reject_total > 0)
         L[line++]=StringFormat("Rejects: %d total / %d today (streak %d) last: %s",
                                g_cb_reject_total, g_cb_reject_today,
                                g_cb_reject_streak, g_cb_reject_last);
   }

   // v25.1: tick recorder status (CB mode only)
   if(InpCrashBoomMode)
      L[line++]=g_tick_rec.GetDashboard();

   while(line<26) L[line++]=" ";

   for(int i=0;i<26;i++)
   {
      ObjectSetString(0,dash_names[i],OBJPROP_TEXT,L[i]);
      color c=clrWhite;
      if(i==0) c=clrGold;
      if(i==3){
         if(g_regime==REGIME_BULLISH) c=clrLime;
         else if(g_regime==REGIME_BEARISH) c=clrRed;
         else if(g_regime==REGIME_RANGING) c=clrYellow;
         else c=clrGray;
      }
      if(i==5) c=g_paused?clrRed:clrLime;
      ObjectSetInteger(0,dash_names[i],OBJPROP_COLOR,c);
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
string RegimeToStr(ENUM_REGIME r)
{
   if(r==REGIME_BULLISH) return "BULLISH";
   if(r==REGIME_BEARISH) return "BEARISH";
   if(r==REGIME_RANGING) return "RANGING";
   if(r==REGIME_HIGH_VOL) return "HIGH_VOL";
   return "NO_TRADE";
}

//+------------------------------------------------------------------+
void DrawArrow(int dir, datetime t, double price, string tag)
{
   string name="M230_"+tag+"_"+IntegerToString((int)t);
   ObjectCreate(0,name,OBJ_ARROW,0,t,price);
   ObjectSetInteger(0,name,OBJPROP_ARROWCODE,dir>0?233:234);
   ObjectSetInteger(0,name,OBJPROP_COLOR,dir>0?clrLime:clrRed);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
}
//+------------------------------------------------------------------+
