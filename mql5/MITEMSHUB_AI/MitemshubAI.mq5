//+------------------------------------------------------------------+
//|                                             MitemshubAI.mq5      |
//|                    MITEMSHUB AI MULTI-STRATEGY ENGINE v26.34     |
//|   Intelligent • Regime-Aware • Volatility-Only • Spike-Aware • Smart  |
//|                                                                  |
//| v26.x SERIES (2026-08-30) — see PRODUCTION_CONFIGS.md for full   |
//| details. Volatility-only deploy line:                            |
//|  v26.34 CB ENGINE REMOVED: the dormant Crash/Boom engine, its     |
//|     inputs, learned-gate files, burst-guard policy table, and     |
//|     reject-accounting counters are physically deleted (every      |
//|     historical CB strategy question was settled net-negative;     |
//|     v26.33 already refuses CB symbols). The TickRecorder module   |
//|     survives (moved to Microstructure/) — it is the opt-in tick   |
//|     archive for Volatility microstructure studies. Strategy       |
//|     table: PB/BO/MOM/MR/BF + VB-BURST (6 slots).                  |
//|  v26.23 GOVERNOR v3.1 — QUALITY GATES: (1) SPREAD GATE: entries   |
//|     are refused when the live spread exceeds 18% of the planned   |
//|     stop distance (scalp-sweep forensics: spread was ~44% of the  |
//|     OOS loss; wide-spread moments are where the engine bleeds).   |
//|     (2) CONVICTION THROTTLE: on a net-negative day the minimum    |
//|     entry score rises by one — the governor stops digging when    |
//|     the day is red, restores full access on green days. Both are  |
//|     governor inputs, geometry untouched (sweep-validated).        |
//|  v26.22 GOVERNOR v3 — COORDINATION: (1) WIN-REARM: cooldown is    |
//|     no longer paid after winning trades — the governor re-arms    |
//|     instantly once a winner closes (cooldown=0) and organises the |
//|     next entry, while losses keep the full breather. Evidence:    |
//|     the 63-cell scalp sweep (artifacts/                           |
//|     scalp_sweep_volatility_75_index.json) rejected scalp TPs —    |
//|     every tighter-target cell lost OOS; legacy geometry stays.    |
//|  v26.20 GOVERNOR v2: (1) the auto-disable flag is now ENFORCED —  |
//|     every trade path (classic legs, CB bar, CB tick-fade, VB      |
//|     burst) gates on it; before, DISABLED strategies kept trading. |
//|     (2) No permanent freeze — a suppressed strategy PROBES every  |
//|     InpProbeEveryN-th signal so its statistics keep updating and  |
//|     a recovered edge earns reinstatement. (3) Reviews and the     |
//|     dashboard report the Wilson 95% lower bound of the win rate   |
//|     for honest small-sample reads. State file grows one field,    |
//|     backward-compatible both ways.                                |
//|  v26.18 TRADE-JOURNAL HYGIENE: (1) full per-symbol trade ledger    |
//|     MitemshubAI_history_<Symbol>.csv — one append-only row per     |
//|     close with prices/volume/PnL/R/hold — a trustworthy $ equity   |
//|     curve at last; (2) slippage counters redefined on EXIT PRICE:  |
//|     broker STOP/TARGET fills measured vs the planned g_sl/g_tp on  |
//|     the ticket (adverse R, worst-fill tracked); MANUAL/TIME closes |
//|     excluded as decisions, not execution. Slip file grows to 7     |
//|     fields, backward-compatible both ways.                        |
//|  v26.17 VOLATILITY BURST FADE (EXPERIMENTAL, default OFF): the    |
//|     tick-fade state machine ported to Volatility indices — a     |
//|     momentum BURST (net move >= InpVBVelPts over N ticks) arms   |
//|     a fade, the same retrace-window/confirm-release lifecycle    |
//|     as CB-TICKFADE. Slot 8 (VB-BURST) in the strategy tables.    |
//|     OFF everywhere until replayed against recorded Vol ticks.     |
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
#define APP_VERSION "26.34"

//--- v25.2: single source of truth for the version string.
//--- #property version, every log tag, and every order comment derive from
//--- APP_VERSION — bump THIS line only; nothing else can drift.
const string VTAG = "[v" + APP_VERSION + "] ";

#property copyright "MITEMSHUB AI"
#property version   APP_VERSION
#property strict

#include <Trade\Trade.mqh>
#include "Microstructure/TickRecorder.mqh"   // v26.34: relocated from CrashBoom/ — opt-in tick archive (default OFF)
#include "Strategies/VolBurstFade.mqh"   // v26.17: Volatility momentum-burst fade (EXPERIMENTAL, default OFF)
// v26.9-phase1: modular market engine — EGARCH conditional-vol forecaster
// (locked against the Python reference by Tests/Phase10Tests.mq5).
#include "Market/GarchForecaster.mqh"
CTrade trade;
CTickRecorder g_tick_rec;   // opt-in tick microstructure archive (v26.19: default OFF)
CVolBurstFade g_vb;         // v26.17: Volatility momentum-burst fade (EXPERIMENTAL)

#define TELEM_BASE "MitemshubAI_v23_telemetry"   // v26.1: per-symbol suffix appended
#define STATE_BASE "MitemshubAI_state"           // v26.1: per-symbol suffix appended

// v26.1: per-INSTANCE file names — two instances on different symbols must
// never share learning state (a shared state.csv once let each instance
// overwrite the other's counters). Files become e.g.
//   MitemshubAI_state_Volatility_75_Index.csv
//   MitemshubAI_review_Volatility_75_Index.csv
//   MitemshubAI_v23_telemetry_Volatility_75_Index.jsonl
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
input bool   InpPbEmaSideVeto    = false;   // v26.29: veto PB when close pierces EMA20 against trend (cert-validated on V75)
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
input double InpBandTargetSigmaMult= 0.60;   // target = 0.60 x sigma_h (validated)
input int    InpBandHoldSec      = 3600;     // band hold horizon (seconds)
input double InpBandMinRR        = 2.5;      // min reward:risk for band plans
input double InpBandMaxStopPct   = 0.015;    // reject band plan if stop > 1.5% of price

// v26.4: SPIKE SLIPPAGE — realized R vs the planned -1R stop.
// Boom/Crash spikes gap the price and stops fill at the post-spike quote, so
// a "protected" -1R can realize -4R..-10R. These counters make the tail
// explicit in the journal and the HUD instead of hiding it inside g_total_r.
int    g_gap_loss_n     = 0;      // v26.18: STOP exits filled beyond the planned -1R
double g_gap_loss_r_sum = 0.0;    // realized R summed over gap-loss closes
int    g_stop_n         = 0;      // broker-triggered STOP exits measured
double g_slip_r_sum     = 0.0;    // v26.18: sum of adverse exit-price slippage (R)
int    g_tp_n           = 0;      // v26.18: broker-triggered TARGET exits measured
double g_tp_slip_r_sum  = 0.0;    // v26.18: adverse slippage on TARGET fills (R)
double g_slip_worst_r   = 0.0;    // v26.18: worst single-fill adverse slippage (R)

//--- v26.18: EXECUTION-QUALITY slippage, measured at the exit price.
//    Replaces the v26.2 P/L-derived counters, which were polluted by design:
//    manual closes fed their full P/L into "slippage", TIME exits counted as
//    gap-throughs, and trail/BE stops blurred into the planned-stop figure.
//    Now: only broker-triggered STOP and TARGET exits are measured, and each
//    is compared against the PLANNED price on the ticket (g_sl / g_tp):
//      adverse_slip = (planned - exit) * dir   (positive = filled worse)
//    MANUAL and TIME closes are decisions, not execution — excluded.
void RecordTradeSlippage(double actual_r, double exit_p, string exit_type)
{
   double planned_p = 0;
   if(exit_type == "STOP")        planned_p = g_sl;
   else if(exit_type == "TARGET") planned_p = g_tp;
   if(planned_p > 0 && g_dir != 0 && g_orig_risk > 0)
   {
      double adverse_r  = ((planned_p - exit_p) * g_dir) / g_orig_risk;   // + = worse fill
      g_slip_r_sum     += adverse_r;
      if(adverse_r > g_slip_worst_r) g_slip_worst_r = adverse_r;
      if(exit_type == "STOP")
      {
         g_stop_n++;
         if(actual_r <= -1.02)          // filled BEYOND the planned -1R stop
         {
            g_gap_loss_n++;
            g_gap_loss_r_sum += actual_r;
            PrintFormat(VTAG+"SPIKE SLIPPAGE: STOP fill %+.2fR (exit %.5f vs planned %.5f, %+.1f pts) — gap-through",
                        actual_r, exit_p, g_sl, (exit_p - g_sl) / _Point * (g_dir > 0 ? -1 : 1));
            Telem("slippage", StringFormat("\"sym\":\"%s\",\"r\":%.3f,\"exit\":%.5f,\"planned\":%.5f,\"gap\":true",
                        _Symbol, actual_r, exit_p, g_sl));
         }
      }
      else // TARGET
      {
         g_tp_n++;
         g_tp_slip_r_sum += adverse_r;
      }
   }
   SaveSlipState();              // persist after every close (both paths)
}

//+------------------------------------------------------------------+
//| v26.18: FULL TRADE HISTORY — one append-only row per closed trade |
//| The old MitemshubAI_trades.csv declared this schema but no writer |
//| was ever wired, so the only live ledger (review CSV) lacked       |
//| prices/volume/PnL — not enough to reconstruct a $ equity curve.   |
//| Append-only, per symbol, never rotated or rewritten.              |
//+------------------------------------------------------------------+
#define HISTORY_BASE "MitemshubAI_history"
void AppendTradeRow(string reason, double exit_p, double r)
{
   int h = FileOpen(SymbolTaggedFile(HISTORY_BASE, ".csv"),
                    FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
   {
      PrintFormat(VTAG+"WARNING: cannot open trade-history file — row for ticket %I64u lost", g_ticket);
      return;
   }
   if(FileSize(h) == 0)   // first row ever: column header
      FileWriteString(h, "closed_at,ticket,strategy,dir,volume,entry,sl,tp,exit,exit_reason,r,pnl_money,risk_money,hold_sec,magic\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, StringFormat("%s,%I64u,%s,%d,%.2f,%.5f,%.5f,%.5f,%.5f,%s,%.3f,%.2f,%.2f,%d,%I64d\n",
                   TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
                   g_ticket, g_last_strategy, g_dir, g_position_volume,
                   g_entry, g_sl, g_tp, exit_p, reason, r,
                   r * g_risk_money, g_risk_money,
                   g_entry_time > 0 ? (int)(TimeCurrent() - g_entry_time) : 0,
                   (long)InpMagic));
   FileClose(h);
}

//+------------------------------------------------------------------+
//| v26.2: persist slip counters per symbol (survive restarts)        |
//+------------------------------------------------------------------+
void SaveSlipState()
{
   int h=FileOpen(SymbolTaggedFile("MitemshubAI_slip", ".csv"), FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return;
   // v26.18: 7 fields. Field order is append-only — old 4-field files load
   // fine (LoadSlipState bounds-checks), and old EA builds simply ignore the
   // 3 extra trailing fields of new files.
   FileWriteString(h, StringFormat("%d,%.4f,%d,%.4f,%d,%.4f,%.4f\n",
                   g_gap_loss_n, g_gap_loss_r_sum, g_stop_n, g_slip_r_sum,
                   g_tp_n, g_tp_slip_r_sum, g_slip_worst_r));
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
   int n_p = StringSplit(line, ',', p);
   if(n_p >= 4)
   {
      g_gap_loss_n     = (int)StringToInteger(p[0]);
      g_gap_loss_r_sum = StringToDouble(p[1]);
      g_stop_n         = (int)StringToInteger(p[2]);
      g_slip_r_sum     = StringToDouble(p[3]);
      // v26.18: extended fields (old 4-field files keep code defaults)
      if(n_p >= 7)
      {
         g_tp_n          = (int)StringToInteger(p[4]);
         g_tp_slip_r_sum = StringToDouble(p[5]);
         g_slip_worst_r  = StringToDouble(p[6]);
      }
      PrintFormat(VTAG+"SLIPPAGE restored (v26.18 exit-price basis): STOPs=%d gap-through=%d (avg %+.2fR) | adverse slip %+.3fR worst %+.3fR | TPs=%d (slip %+.3fR)",
                  g_stop_n, g_gap_loss_n,
                  (g_gap_loss_n > 0 ? g_gap_loss_r_sum / g_gap_loss_n : 0.0),
                  (g_stop_n + g_tp_n > 0 ? g_slip_r_sum / (g_stop_n + g_tp_n) : 0.0),
                  g_slip_worst_r, g_tp_n, g_tp_slip_r_sum);
   }
}

input group "=== Risk & Exits ==="
input double InpRiskPerTrade     = 0.005;    // TARGET risk fraction (min-lot floor may force more)
input double InpMaxEffectiveRiskPct = 20.0;  // HARD CAP: skip entry if real min-lot risk > this % of equity
input double InpMaxTotalRiskPct  = 15.0;     // ACCOUNT GUARD: max SUMMED open risk (all fleet magics) as % of equity
input double InpMicroFitPct      = 1.5;      // v26.6: if min-lot clamping overshoots risk (micro balance), shrink SL/TP so effective risk <= this % of equity (0=off)
input string InpFleetMagicsCSV   = "7788010,7788025,7788050,7788075,7788100";
input double InpTpMult           = 2.4;   // v26.22: unchanged — 63-cell scalp sweep rejected tighter TPs (all cells OOS-negative on V75; artifacts/scalp_sweep_volatility_75_index.json)
input bool   InpWinRearm         = true;  // v26.22: governor coordination — instant re-arm after a winning close (losses keep the cooldown breather)
input double InpMaxSpreadATRFrac = 0.18;   // v26.23: governor spread gate — skip entries when live spread > this fraction of the stop distance (0 = off)
input bool   InpAdaptiveConviction= true;  // v26.23: governor conviction throttle — MinScore +1 while the day is net-negative
input int    InpMaxHoldBars      = 20;       // v23: raised from 14 — give winners room (20 bars = 5hr on M15)
input double InpMaxDailyLossPct  = 0.0;     // 0 = daily-loss halt DISABLED (was 0.03; user request 2026-08-30). DailyLossHalted() returns false when <= 0.
input int    InpMaxConsecLoss    = 3;        // v23: lowered from 6 — pause sooner, preserve capital
input int    InpCoolDownBars     = 1;
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
input double InpPaperEquity      = 50.0;     // v26.28 PAPER: virtual starting equity (InpLiveExecution=false)
input bool   InpFitRouter        = true;     // v26.30: min-lot risk router — refuse an instrument whose min lot cannot fit the risk cap
input double InpRouterScanATR    = 1.7;      // v26.30: stop distance (x ATR) used for the min-lot fit measurement
input double InpPaperSpreadMult  = 1.0;      // v26.28 PAPER: spread multiplier for conservative virtual fills
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

input group "=== Volatility Burst Fade (v26.17, EXPERIMENTAL) ==="
// v26.17: momentum-burst fade for Volatility indices — a fast net move over
// N ticks arms a fade with a retrace-window/confirm-release lifecycle.
// Every threshold is unvalidated until replayed against recorded Vol ticks;
// the master switch defaults OFF and stays off in every shipped preset.
input bool   InpVolBurstFade     = false;    // Master: enable the Vol burst-fade leg
input int    InpVBLookTicks      = 8;        // Velocity lookback (ticks) for burst detection
input double InpVBVelPts         = 4.0;      // Net move (points) over lookback that arms a burst
input double InpVBRetrMin        = 0.30;     // Fire when retrace enters the window (min)
input double InpVBRetrMax        = 0.60;     // Window closes beyond this retrace (max)
input int    InpVBTimeoutSec     = 600;      // Pending burst expiry (s)
input double InpVBSL_ATR         = 0.3;      // Burst-fade stop = this x entry-TF ATR
input double InpVBTP_ATR         = 3.2;      // Burst-fade target = this x entry-TF ATR
input double InpVBMinRR          = 2.0;      // R:R gate at signal time
input int    InpVBCooldownSec    = 300;      // Quiet period after a confirmed burst fade (s)

input group "=== Tick Recorder (v25.1) ==="
input bool   InpTickRecordEnabled = false;  // Tick recorder (OFF by default: broker tick history covers research; enable per-preset only for microstructure studies)
input int    InpTickFlushTicks    = 100;     // Flush buffer every N ticks (v25.5: live-analysis cadence)
input int    InpTickFlushSeconds  = 10;      // Max seconds between flushes (v25.5)

input group "=== Self-Review Intelligence (v23.1) ==="
input int    InpStrategyReviewN  = 10;       // Check strategy performance every N trades
input int    InpRegimeReviewN    = 20;       // Check regime performance every N trades
input int    InpTimeReviewN      = 30;       // Check time-block performance every N trades
input int    InpMinTradesToJudge = 15;       // Minimum trades before auto-disabling a strategy
input double InpMinExpectancy    = 0.0;      // Min expectancy (R/trade) to keep a strategy active
input bool   InpAutoDisableStrat = true;     // Auto-disable strategies with negative expectancy
input bool   InpProbeDisabled    = true;     // v26.20: suppressed strategies probe every Nth signal (no permanent freeze)
input int    InpProbeEveryN      = 10;       // v26.20: probe every Nth blocked signal (0 = full freeze)
input bool   InpAutoBlockTime    = false;    // Auto-block worst-performing time blocks

//+------------------------------------------------------------------+
//| GLOBALS                                                            |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES g_tf_entry, g_tf_regime;
int hEMA_Fast_R, hEMA_Mid_R, hEMA_Slow_R;
int hEMA_Fast_E, hEMA_Mid_E, hEMA_Slow_E, hRSI_E, hATR_E, hBB_E;

double g_eq=0, g_peak_eq=0, g_daily_pnl=0;
bool   g_fit_ok=true;            // v26.30: min-lot risk router verdict for the chart symbol
string g_fit_recommend="";       // v26.30: last router recommendation line
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
string g_fired_legs="", g_last_skip="";

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

// v26.5 strategy table: v26.34 — 6 slots — 0=PB,1=BO,2=MOM,3=MR,4=BF (classic)
// + 5=VB-BURST (v26.17 Volatility burst fade). The Crash/Boom modes that
// previously occupied slots 5..7 were removed with the CB engine (v26.34).
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
#define STRAT_SLOTS   6   // 5 classic + 1 Vol burst (v26.34: CB modes removed)
#define REGIME_SLOTS  5
#define TIME_SLOTS    5

// v26.11: name tables hoisted to constant globals sized by the same constants
// (they were duplicated inline in CheckStrategyPerformance/CheckRegime-
// Performance and AGAIN in the HUD — a third drift hazard).
const string STRAT_NAMES[STRAT_SLOTS]   = {"PB","BO","MOM","MR","BF","VB-BURST"};
const string REGIME_NAMES[REGIME_SLOTS] = {"BULLISH","BEARISH","RANGING","HIGH_VOL","NO_TRADE"};

double g_strat_trades[STRAT_SLOTS];     // total trades per strategy
double g_strat_wins[STRAT_SLOTS];       // wins per strategy
double g_strat_total_r[STRAT_SLOTS];    // cumulative R per strategy
bool   g_strat_enabled[STRAT_SLOTS];    // auto-disable flag
int    g_strat_probe_n[STRAT_SLOTS];    // v26.20: blocked-signal counter per strategy (drives probing)

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
int g_cb_reject_total   = 0;   // v26.34: kept for state continuity; no longer incremented (CB engine removed)
int g_cb_reject_today   = 0;
int g_cb_reject_streak  = 0;
string g_cb_reject_last = "";

// v26.14: meta-labeling P(win) size multipliers — loaded from
// data/meta_label_regime_table.csv (produced by scripts/meta_label_trainer.py).
// Keyed by (regime, direction); the multiplier scales base risk for new entries.
#define META_LABEL_MAX_ROWS 16
string g_ml_regime[META_LABEL_MAX_ROWS];
int    g_ml_dir[META_LABEL_MAX_ROWS];
double g_ml_mult[META_LABEL_MAX_ROWS];
int    g_ml_rows = 0;

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
void PrintStartupSelfCheck()
{
   string halt = (InpMaxDailyLossPct <= 0.0)
      ? "OFF"
      : StringFormat("ON %.1f%%", InpMaxDailyLossPct * 100.0);
   string bg = "removed (v26.34)";
   string mf = (InpMicroFitPct <= 0.0) ? "OFF" : StringFormat("%.1f%%", InpMicroFitPct);

   Print(VTAG+"SELF-CHECK — key v26.x switches ('<' = deployed expectation):");
   PrintFormat(VTAG+"  DailyHalt    = %-26s < expect OFF (0%% — user request 2026-08-30)", halt);
   PrintFormat(VTAG+"  BurstGuard   = %-26s < Crash/Boom engine removed (v26.34)", bg);
   PrintFormat(VTAG+"  MicroFit     = %-26s < expect 1.5%% on CB charts (0 = stale v26.5- inputs)", mf);
   PrintFormat(VTAG+"  LambdaModel  = %-26s < built-in ON (v26.9; λ trusted at 3 learned gaps)", "ON (built-in)");
   PrintFormat(VTAG+"  CloseDetect = %-26s < expect ON (v26.4 event-driven closes)",
               InpUseOnTradeTransaction ? "ON (event-driven)" : "OFF (polling fallback)");
}


//+------------------------------------------------------------------+
//| v26.25: CALIBRATED TICK VALUE — trusts the broker only after a    |
//| cross-check. The sizing chain everywhere consumes                 |
//| (stop/tick_size)*tick_value*vol as the $ at risk. On Deriv SVG,   |
//| Volatility 75 Index reports trade_tick_value=0.0001 for           |
//| tick_size=0.01 & contract_size=1.0 — 100x understated             |
//| (truth, from the 2026-09-03 closed trade: $1.0009 per price-unit  |
//| per 1.0 lot; the broker number implies $0.01). The EA believed    |
//| its 500pt stop risked $5/lot and sized 0.03-0.04 lots — real      |
//| risk $15-20 = 57-61% of equity, while the dashboard said 0.5%.    |
//| Every guardrail passed because they share the poisoned input.     |
//| For instruments quoted in the account currency the identity       |
//| tick_value == tick_size * contract_size must hold; when it does   |
//| not, derive from the identity. Non-USD quotes keep the broker     |
//| number (a conversion factor we cannot reconstruct locally).       |
//+------------------------------------------------------------------+
double CalibTickValue(const string sym)
{
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double cs = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   if(ts <= 0.0 || cs <= 0.0) return(tv);

   string acct_ccy = AccountInfoString(ACCOUNT_CURRENCY);
   string prof_ccy = SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT);
   if(acct_ccy == "" || prof_ccy != acct_ccy)
      return(tv);   // quote converted to another account ccy: broker value may be right

   double tv_identity = ts * cs;
   if(tv <= 0.0 || MathAbs(tv - tv_identity) > 0.05 * tv_identity)
   {
      PrintFormat(VTAG+"TICKVALUE CALIBRATED on %s: broker says %.6f, geometry says %.6f (tick_size %.5f x contract %.2f) — using geometry",
                  sym, tv, tv_identity, ts, cs);
      return(tv_identity);
   }
   return(tv);
}

//+------------------------------------------------------------------+
int OnInit()
{
   // VOLATILITY-ONLY MANDATE (v26.33, owner decision 2026-09-04): this EA
   // trades Volatility indices only. Boom/Crash is permanently retired
   // (v26.21 lineup, 2026-09-02): spike-gap mechanics fill stops at the
   // post-spike quote (structurally incompatible with the BE/trail ladder),
   // the tick-burst family measured net-negative across the full 70-cell
   // calibration. v26.34: the dormant CB engine has been removed entirely.
   // Refuse to run on Crash/Boom symbols entirely.
   string cbchk = _Symbol;
   StringToLower(cbchk);
   if(StringFind(cbchk, "crash ") == 0 || StringFind(cbchk, "boom ") == 0)
   {
      Print(VTAG+"REFUSED: "+_Symbol+" is a Crash/Boom symbol. This build is "
            "VOLATILITY-ONLY (mandate 2026-09-04) - attach it to a Volatility "
            "index (10/25/50/75/100) instead. Crash/Boom stays retired; the "
            "engine was removed in v26.34.");
      return(INIT_FAILED);
   }

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
   LoadMetaLabelTable(); // v26.14: restore learned P(win) regime multipliers
   SeedHistoryState();   // v26.24: warm ATR/sigma/GARCH from chart history — no blind window after restarts
   RecoverDetachedClose(); // v26.9: journal closes that happened while the EA was detached
   if(InpDrawDashboard) CreateDashboard();
   // v25.1: tick recorder — degrades to no-op if the file can't be opened
   g_tick_rec.Init(_Symbol, InpTickRecordEnabled, InpTickFlushTicks, InpTickFlushSeconds);

   Print(VTAG+"MITEMSHUB AI v"+APP_VERSION+" started | Volatility-Only | Regime-Aware | " +
         "Standard Mode (Crash/Boom retired v26.21, refused v26.33, engine removed v26.34)");
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
   PrintFormat(VTAG+"Governor v2: enforcement ON; suppressed strategies probe every %d-th signal (%s)",
               InpProbeEveryN, InpProbeDisabled?"probing enabled":"full freeze");
   PrintFormat(VTAG+"Governor v3 coordination: spread-gate %s (max %.0f%% of stop), conviction throttle %s, win-rearm %s",
               InpMaxSpreadATRFrac>0?"ON":"OFF", InpMaxSpreadATRFrac*100.0,
               InpAdaptiveConviction?"ON":"OFF", InpWinRearm?"ON":"OFF");

   // v26.28: PAPER TRADING ENGINE — virtual equity, virtual fills, real logic
   PaperInit();
   if(PaperActive())
      PrintFormat(VTAG+"PAPER MODE: virtual equity $%.2f | fills at live spread x%.1f | NO real orders",
                  g_paper_eq, InpPaperSpreadMult);

   // v26.30: MIN-LOT RISK ROUTER — can this account trade this instrument at all?
   if(InpFitRouter) RunFitRouter();

   //--- v26.17: Volatility burst-fade leg (EXPERIMENTAL, default OFF).
   //    Built for symbols that tick without spikes; independent of the
   //    classic bar-based legs.
   g_vb.Init(InpVolBurstFade,
             InpVBLookTicks, InpVBVelPts, InpVBRetrMin, InpVBRetrMax,
             InpVBTimeoutSec, InpVBSL_ATR, InpVBTP_ATR, InpVBMinRR,
             InpVBCooldownSec);

   PrintStartupSelfCheck();   // v26.9: one-glance stale-chart detector in the log

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

   // v24.11: cooldown after every close — v26.22: WIN-REARM — after a
   // WINNER the governor re-arms instantly (cooldown=0): momentum is live,
   // the next signal is already organised, waiting serves no purpose. After
   // a LOSS the full breather still applies (re-entry into the move that
   // just stopped us out is how accounts die).
   if(r > 0 && InpWinRearm)
      g_cooldown = 0;                 // v26.22: instant re-arm after wins
   else
      g_cooldown = InpCoolDownBars;   // losses keep the full breather
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

   RecordTradeSlippage(r, exit_p, reason);   // v26.18: exit-price-based execution quality
   AppendTradeRow(reason, exit_p, r);        // v26.18: full per-symbol trade ledger

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
   // v26.30 fit router: an instrument whose min lot cannot hold the risk cap
   // gets no entries at all (re-checked if equity grows 50% — it may then fit)
   if(InpFitRouter && !g_fit_ok)
   {
      static double s_last_eq = 0.0;
      double eq_now = PaperActive() ? PaperEquity() : AccountInfoDouble(ACCOUNT_EQUITY);
      if(eq_now >= s_last_eq * 1.5) { RunFitRouter(); s_last_eq = eq_now; }
      if(!g_fit_ok) return;
   }
   // v26.17: Volatility momentum-burst fade — track every tick, fire only when
   // gates open. A self-contained tick-level leg (v26.34: the CB tick-fade
   // machinery it originally mirrored was removed with the CB engine).
   if(g_vb.Enabled())
   {
      bool can_trade = (g_ticket==0 && !g_paused && g_cooldown==0 && !DailyLossHalted()
                        && IsSessionActive() && !HasOpenPositionOnSymbol(_Symbol));
      double ve=0, vs=0, vtp=0; string vr="";
      int vd = g_vb.OnTick(bid, ve, vs, vtp, vr, can_trade);
      if(vd != 0 && can_trade && StratEnabledOrProbe(5))   // v26.20 governor gate (v26.34: VB-BURST is slot 5; probe counts only when a burst actually fires)
      {
         g_last_strategy = "VB-BURST";
         if(OpenTradeLive(vd, ve, vs, vtp, vr))   // same re-anchor + micro-fit + guardrail path as the classic opener
            g_vb.Confirm();                     // accepted: consume burst + cooldown
         else                                   g_vb.Release();   // rejected: burst stays pending
      }
   }

   static datetime last_bar=0;
   datetime cur = iTime(_Symbol, g_tf_entry, 0);
   if(cur == last_bar) { if(InpDrawDashboard) UpdateDashboard(); return; }
   last_bar = cur;

   g_eq = PaperActive() ? PaperEquity() : AccountInfoDouble(ACCOUNT_EQUITY);   // v26.28: virtual equity in paper mode
   if(g_eq > g_peak_eq) g_peak_eq = g_eq;

   datetime ds = TimeCurrent() - (TimeCurrent()%86400);
   if(ds != g_day_start)
   {       g_day_start=ds; g_daily_pnl=0; g_trades_today=0;
       g_day_start_eq = g_eq;
       g_session_pnl=0;
       g_consec_loss=0;
       g_cb_reject_today=0;   // v26.34: legacy counter (no longer incremented)
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
      if(PaperActive()) PaperManage();          // v26.28: virtual position lifecycle
      else if(PositionSelectByTicket(g_ticket)) ManagePosition();
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
         RunRiskSentinel(g_position_volume, g_sl, g_tp, -1.0, "RECOVERY");   // v26.26: audit orphans too — breach closes them
         break;
      }
   }

   UpdateSigmaBaseline();
   UpdateBandTelemetry();

   // v26.17: feed the burst-fade module the entry-TF ATR (last closed bar,
   // same series the classic strategies read) so its geometry stays current
   if(g_vb.Enabled())
   {
      double vb_atr[1];
      if(CopyBuffer(hATR_E, 0, 1, 1, vb_atr) == 1) g_vb.SetATR(vb_atr[0]);
   }

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
         // Standard Volatility mode (v26.34: the Crash/Boom signal branch was
         // removed with the CB engine — this is the only entry path now)
         string sig="";
         int dir = GenerateSignal(sig);
         if(dir != 0) OpenTrade(dir, sig);
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
//--- v26.24: optional shift — stddev of the returns ending at bar `shift+1`
//--- (shift=0 keeps the live behavior: last closed bar). Used by the
//--- cold-start replay so the sigma EMA is seeded from the HISTORICAL
//--- sigma path, not N copies of the current stddev.
double PerBarSigma(const int lookback, const int shift=0)
{
   int n = MathMax(3, lookback);
   if(Bars(_Symbol, g_tf_entry) < shift+n+2) return 0.0;
   double sum=0, sum2=0;
   for(int i=1; i<=n; i++)
   {
      double c0 = iClose(_Symbol, g_tf_entry, shift+i);
      double c1 = iClose(_Symbol, g_tf_entry, shift+i+1);
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
bool GarchFeedBar(const double forced_return = EMPTY_VALUE)
{
   if(!InpUseGarch || !g_garch_ok)
      return(false);                           // disabled or permanently failed
   if(Bars(_Symbol, g_tf_entry) < InpGarchWarmupBars + 2)
      return(false);
   //--- log return of the last closed bar (same convention as the Python
   //--- reference: log(c_t / c_{t-1}); no indicator handles involved).
   //--- v26.24: history replay (SeedHistoryState) passes the return directly.
   double lr = forced_return;
   if(lr == EMPTY_VALUE)
   {
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
      lr = MathLog(c1 / c2);
   }
   double sigma = 0.0;
   bool   ready = g_garch.Update(lr, sigma);
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
double ActiveBarSigma(const int lookback, const int shift=0)
{
   if(InpUseGarch && g_garch_ok && g_garch.Observations() >= InpGarchWarmupBars && g_garch_sigma > 0)
      return(g_garch_sigma);
   return(PerBarSigma(lookback, shift));
}

//+------------------------------------------------------------------+
//| v26.24: cold-start catch-up. After a restart/migration the EA    |
//| woke up blind: empty ATR history pins the percentile at 50 (the  |
//| regime classifier cannot leave RANGING), the sigma EMA is        |
//| unseeded (exp_ratio pinned ~1.0 fails BandFade's expansion gate) |
//| and the GARCH module is cold (z on the legacy-stddev scale for   |
//| another 50 bars). The classifier blindness also silently switches|
//| OFF the trend legs (PB needs BULL/BEAR; BO sells only in BEAR).  |
//| Replay the last closed bars through the SAME per-bar feeds once  |
//| at init so every gate is warm on the first live bar.             |
//+------------------------------------------------------------------+
void SeedHistoryState()
{
   if(g_sigma_init || atr_hist_count > 0 || g_garch.Observations() > 0)
      return;                                          // already warm (defensive)
   int need = MathMax(InpAtrLookback, InpGarchWarmupBars + 2);
   if(Bars(_Symbol, g_tf_entry) < need + 2)
      return;                                          // short history: warm up the legacy way
   for(int i = need; i >= 1; i--)                       // oldest → newest closed bar
   {
      double c1 = iClose(_Symbol, g_tf_entry, i);
      double c2 = iClose(_Symbol, g_tf_entry, i + 1);
      double atr_i[1];
      bool   have_atr = (CopyBuffer(hATR_E, 0, i, 1, atr_i) == 1 && atr_i[0] > 0);
      if(have_atr)                                        // same append as ClassifyRegime
      {
         if(atr_hist_count < ArraySize(atr_hist)) atr_hist[atr_hist_count++] = atr_i[0];
         else
         {
            for(int k = 0; k < ArraySize(atr_hist) - 1; k++) atr_hist[k] = atr_hist[k + 1];
            atr_hist[ArraySize(atr_hist) - 1] = atr_i[0];
         }
      }
      if(c1 > 0 && c2 > 0) GarchFeedBar(MathLog(c1 / c2));
      if(have_atr)
      {
         double sig = ActiveBarSigma(20, i);   // stddev AS OF the replay cursor
         if(sig > 0)
         {
            if(!g_sigma_init) { g_sigma_ema = sig; g_sigma_init = true; }
            else
            {
               double a = 2.0 / (InpBandSigmaEmaLen + 1.0);
               g_sigma_ema = a * sig + (1.0 - a) * g_sigma_ema;
            }
         }
      }
   }
   PrintFormat(VTAG+"Cold-start catch-up: %d bars replayed | ATR hist %d | GARCH obs %d | sigma EMA %.5f%s",
               need, atr_hist_count, g_garch.Observations(), g_sigma_ema,
               g_sigma_init ? "" : " (sigma EMA NOT seeded)");
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
   if(strat=="VB-BURST")    return 5;   // v26.17: Volatility burst fade (slot 5 since v26.34)
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

//--- v26.20: Wilson 95% lower bound on win rate — an honest worst-case view
//--- of small samples (2/2 wins reports 0.342, not 1.0). Reported in reviews;
//--- the kill/reinstate DECISION stays on measured expectancy, which is what
//--- protects capital while the probe stream keeps the evidence current.
double WilsonWinLB(double wins, double n)
{
   if(n <= 0.0) return 0.0;
   double z = 1.96, z2 = z * z, p = wins / n;
   double denom  = 1.0 + z2 / n;
   double center = p + z2 / (2.0 * n);
   double margin = z * MathSqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n));
   return (center - margin) / denom;
}

//--- v26.20: the single authority on whether a strategy may trade. Until now
//--- nothing read g_strat_enabled, so "DISABLED" strategies kept trading.
//--- Suppressed strategies still probe every InpProbeEveryN-th signal so their
//--- statistics keep updating (no permanent freeze) and a recovered edge
//--- earns reinstatement at the next review.
bool StratEnabledOrProbe(int i)
{
   if(i < 0 || i >= STRAT_SLOTS) return true;
   if(g_strat_enabled[i]) return true;
   if(!InpProbeDisabled || InpProbeEveryN <= 0) return false;
   g_strat_probe_n[i]++;
   return (g_strat_probe_n[i] % InpProbeEveryN) == 1;
}

// Check if any strategy should be auto-disabled / reinstated (v26.20 governor)
void CheckStrategyPerformance()
{
   Print(VTAG+"=== STRATEGY PERFORMANCE REVIEW ===");   // v26.11: shared STRAT_NAMES
   for(int i=0; i<STRAT_SLOTS; i++)
   {
      int    need       = InpMinTradesToJudge;
      int    n          = (int)g_strat_trades[i];
      if(n < need) continue;
      double wr         = g_strat_wins[i] / g_strat_trades[i];
      double expectancy = g_strat_total_r[i] / g_strat_trades[i];
      double floor_r    = InpMinExpectancy;
      bool   may_kill   = InpAutoDisableStrat;
      double wr_lb      = WilsonWinLB(g_strat_wins[i], g_strat_trades[i]);

      if(!g_strat_enabled[i])
      {
         if(!may_kill)
         {  // master switch off: honour the user and reinstate
            g_strat_enabled[i] = true;
            PrintFormat(VTAG+"STRATEGY %s: %d trades, WR=%.0f%% (LB %.0f%%), ExpR=%+.2f → REINSTATED (auto-disable off)",
                        STRAT_NAMES[i], n, wr*100, wr_lb*100, expectancy);
            continue;
         }
         if(expectancy >= floor_r)
         {  // v26.20: probe trades provided fresh evidence of recovery
            g_strat_enabled[i] = true;
            PrintFormat(VTAG+"STRATEGY %s: %d trades, WR=%.0f%% (LB %.0f%%), ExpR=%+.2f → REINSTATED (recovered above %.2f R/trade)",
                        STRAT_NAMES[i], n, wr*100, wr_lb*100, expectancy, floor_r);
            continue;
         }
         PrintFormat(VTAG+"STRATEGY %s: %d trades, WR=%.0f%% (LB %.0f%%), ExpR=%+.2f → SUPPRESSED (probing every %dth signal)",
                     STRAT_NAMES[i], n, wr*100, wr_lb*100, expectancy, InpProbeEveryN);
         continue;
      }

      if(may_kill && expectancy < floor_r && n >= need)
      {
         g_strat_enabled[i] = false;
         g_strat_probe_n[i] = 0;   // fresh probe cycle after a new kill
         PrintFormat(VTAG+"STRATEGY %s: %d trades, WR=%.0f%% (LB %.0f%%), ExpR=%+.2f → DISABLED (below %.2f R/trade)",
                     STRAT_NAMES[i], n, wr*100, wr_lb*100, expectancy, floor_r);
      }
      else
      {
         g_strat_enabled[i] = true;
         PrintFormat(VTAG+"STRATEGY %s: %d trades, WR=%.0f%% (LB %.0f%%), ExpR=%+.2f → KEEP",
                     STRAT_NAMES[i], n, wr*100, wr_lb*100, expectancy);
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
       FileWriteString(h, StringFormat("STRAT,%d,%.0f,%.0f,%.4f,%d,%d\n",
                      i, g_strat_trades[i], g_strat_wins[i], g_strat_total_r[i], g_strat_enabled[i]?1:0,
                      g_strat_probe_n[i]));
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
            // v26.24: governor bootstrap — a strategy with ZERO recorded trades
            // can never be legitimately suppressed (the review needs >=
            // InpMinTradesToJudge trades to disable anything). An enabled=0 at
            // zero trades can only come from a stale/zeroed state file; it used
            // to bench the strategy at init (Sep-03 V75: "Trades=0" yet
            // PB/BO/MOM/MR all "(probe n/10)" — nothing could trade).
            g_strat_enabled[idx] = (StringToInteger(rp[5]) == 1) || (StringToDouble(rp[2]) <= 0.0);
            if(StringToDouble(rp[2]) <= 0.0) g_strat_probe_n[idx] = 0;   // fresh probe cycle
            if(rn >= 7) g_strat_probe_n[idx] = (int)StringToInteger(rp[6]);   // v26.20: probe counters survive restarts
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
   // v26.25: calibrated tick value (see CalibTickValue).
   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = CalibTickValue(_Symbol);
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
      double tv = CalibTickValue(sym);   // v26.25: calibrated — fleet risk must not inherit the broker lie
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

   // v26.29 cert-validated filter (scripts/certify_v75.py sweep, +0.85R vs -30.05R legacy):
   // a close through EMA20 against the trend means the pullback already failed.
   if(InpPbEmaSideVeto)
   {
      if(dir>0 && price<=emaF[0]) return 0;
      if(dir<0 && price>=emaF[0]) return 0;
   }
   // shallow-chase floor rides on the existing InpPullbackMin (cert-validated 0.60 on V75).

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

   // v26.23: GOVERNOR CONVICTION THROTTLE — on a net-negative day the bar for
   // new entries rises by one score point; a flat/green day restores it. The
   // governor stops digging when the day is against us, without touching
   // geometry (the 63-cell sweep proved geometry is already optimal).
   int min_score_eff = InpMinScore;
   if(InpAdaptiveConviction && g_daily_pnl < 0.0)
      min_score_eff += 1;

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

   // v26.20: governor gate — suppressed strategies are dropped here unless the
   // probe schedule lets this signal through (keeps their statistics alive).
   for(int i=0;i<5;i++)
      if(dirs[i]!=0 && !StratEnabledOrProbe(i))
      { dirs[i]=0; scores[i]=0; }

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
   if(buy_score >= min_score_eff && buy_score > sell_score)
   {
      if(InpRequire2Strats && buy_cnt<2) skip_reason="need-2-strats-BUY";
      else final_dir=1;
   }
   else if(sell_score >= min_score_eff && sell_score > buy_score)
   {
      if(InpRequire2Strats && sell_cnt<2) skip_reason="need-2-strats-SELL";
      else final_dir=-1;
   }
   if(final_dir==0 && skip_reason=="")
      skip_reason=(buy_cnt==0 && sell_cnt==0)
                ? (mom_demoted ? "mom-demoted-lone-candle" : "no-legs")
                : StringFormat("score B%d/S%d < min %d", buy_score, sell_score, min_score_eff);

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

   // v26.23: GOVERNOR SPREAD-QUALITY GATE — refuse entries whose execution
   // cost eats too much of the planned risk. Scalp-sweep forensics: spread
   // was ~44% of the OOS loss; wide-spread moments (news ticks, illiquid
   // hours) are where the engine bleeds most. No cooldown charged — a fresh
   // quote arrives next bar and the gate re-checks it.
   double spread_now = SymbolInfoDouble(_Symbol,SYMBOL_ASK) - SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(InpMaxSpreadATRFrac > 0 && stop_dist > 0 && spread_now > InpMaxSpreadATRFrac*stop_dist)
   {
      PrintFormat(VTAG+"SKIP %s — governor spread gate: spread %.1f > %.0f%% of stop (%.1f)",
                  direction>0?"BUY":"SELL", spread_now, InpMaxSpreadATRFrac*100.0, stop_dist);
      g_last_skip = StringFormat("spread-gate %.1f > %.0f%% of %.1f",
                                  spread_now, InpMaxSpreadATRFrac*100.0, stop_dist);
      return;
   }

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
   double tick_value = CalibTickValue(_Symbol);   // v26.25: broker understates V75 tick value 100x — size on truth
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
   else { ok=PaperOpen(direction, entry, sl, tp, vol, g_risk_money, sig_type, g_sig_is_band, g_sig_sl_atr); }   if(!ok) { g_cooldown = InpCoolDownBars; return; }

   if(!PaperActive())
   {
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
   }

   g_dir=direction; g_entry=entry; g_sl=sl; g_tp=tp;
   g_orig_risk=stop_dist; g_position_volume=vol;
   g_entry_time=TimeCurrent(); g_bars_held=0;
   g_high_water_r=0;  // v23: reset high-water mark
   g_max_hold = (g_sig_is_band && g_sig_sl_atr>0)
      ? (int)MathMax(4, (int)MathRound((double)InpBandHoldSec/MathMax(60,PeriodSeconds(g_tf_entry)))+2)
      : InpMaxHoldBars;
   g_trades_today++;

   if(PaperActive())
   { g_entry=g_pp_entry; g_sl=g_pp_sl; g_tp=g_pp_tp; g_orig_risk=g_pp_orig_risk; g_max_hold=g_pp_max_hold; }   // v26.28: adopt virtual fill
   else
      RunRiskSentinel(vol, sl, tp, g_risk_money, "OPEN");   // v26.26: audit the fill, adopt broker reality

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
//| Trade opener for engine-provided entry/SL/TP plans (v24 origin:    |
//| the CB fades; since v26.34 also the VB-BURST leg). Uses the same   |
//| re-anchor, micro-fit, and guardrail path as the classic opener.    |
//| v26.13: returns bool — true = order accepted (or paper mode).      |
//| The burst-fade caller uses it to confirm/release the pending burst;|
//| other callers may ignore the return.                               |
//+------------------------------------------------------------------+
bool OpenTradeLive(int direction, double entry, double sl, double tp, string reason)
{
   double stop_dist = MathAbs(entry - sl);
   double tp_dist = MathAbs(tp - entry);
   if(stop_dist <= 0 || tp_dist <= 0) return(false);

   double tick_size  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value = CalibTickValue(_Symbol);   // v26.25: calibrated — see CalibTickValue()
   double min_lot    = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double lot_step   = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   if(tick_size<=0 || tick_value<=0) return(false);

   // Risk volume via the standard sizing chain (v26.34: the CB engine's
   // dynamic sizing went with the engine; this is the classic path —
   // risk-planned lots, clamped, then consec-loss-scaled by the caller's
   // guardrails below)
   double vol = (g_eq * InpRiskPerTrade) / MathMax(((stop_dist / tick_size) * tick_value), 1e-9);
   vol = NormalizeVolume(vol);
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
             return(false);
          }
      }
      else
      {
         if(sl <= ask_now + st) sl = ask_now + st + tick_size;   // tiny widening for validity; micro-fit re-tightens below
         if(tp >= bid_now - st - tick_size)
          {         PrintFormat(VTAG+"ENTRY ABORT %s — price outran target during send (tp %.5f vs bid %.5f)",
                     direction>0?"BUY":"SELL", tp, bid_now);
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
      if(direction>0) ok = trade.Buy(vol, _Symbol, 0, NormalizeDouble(sl,_Digits), NormalizeDouble(tp,_Digits), "VOL_v"+APP_VERSION);
      else            ok = trade.Sell(vol, _Symbol, 0, NormalizeDouble(sl,_Digits), NormalizeDouble(tp,_Digits), "VOL_v"+APP_VERSION);
      if(!ok)
      {
         uint retcode = trade.ResultRetcode();
         string desc = trade.ResultRetcodeDescription();
         PrintFormat(VTAG+"ORDER FAILED retcode=%d desc=%s", retcode, desc);
      }
   }   else { ok = PaperOpen(direction, entry, sl, tp, vol, g_risk_money, reason, false, 0); }

   if(!ok) { g_cooldown = InpCoolDownBars; return(false); }

   if(!PaperActive())
   {
      g_ticket = 0;
      for(int a = 0; a < 6; a++)
      {
         Sleep(60);
         for(int i = PositionsTotal()-1; i >= 0; i--)
         {
            ulong t = PositionGetTicket(i);
            if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic && PositionGetString(POSITION_SYMBOL) == _Symbol)
            { g_ticket = t; break; }
         }
         if(g_ticket > 0) break;
      }
      if(g_ticket == 0) g_ticket = trade.ResultOrder();
   }
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

   if(PaperActive())
   { g_entry=g_pp_entry; g_sl=g_pp_sl; g_tp=g_pp_tp; g_orig_risk=g_pp_orig_risk; g_max_hold=g_pp_max_hold; }   // v26.28: adopt virtual fill
   else
      RunRiskSentinel(vol, sl, tp, g_risk_money, "OPEN");   // v26.26: audit the fill, adopt broker reality

   if(InpDrawSignals) DrawArrow(direction, TimeCurrent(), entry, reason);
   PrintFormat(VTAG+"%s %s @%.5f SL=%.5f TP=%.5f vol=%.2f",
               reason, direction>0?"BUY":"SELL", entry, sl, tp, vol);

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
//| v26.26: POST-ENTRY RISK SENTINEL — verify the fill against the    |
//| plan. The sizing chain validates BEFORE the send; this validates  |
//| AFTER, from the broker-confirmed position, because the broker may |
//| normalize volume, adjust stops, or the fill may slip — and the    |
//| 2026-09-03 incident (broker tick value 100x understated on V75)   |
//| proved that planned and real risk can diverge silently. The       |
//| sentinel re-measures with CALIBRATED values; any breach of the    |
//| same InpMaxEffectiveRiskPct policy the entry chain enforces is    |
//| loud and fatal (pause + close), never advisory.                   |
//| Also adopts reality: g_entry/g_sl/g_orig_risk/g_risk_money are    |
//| overwritten with the broker-confirmed geometry so R-math, exits,  |
//| and the learning tables all operate on truth, not the plan.       |
//+------------------------------------------------------------------+
void RunRiskSentinel(double planned_vol, double planned_sl, double planned_tp,
                     double planned_risk, string tag)
{
   if(g_ticket==0 || g_dir==0) return;

   // 1. Read the position as the BROKER recorded it (falls back to plan in
   //    paper mode, where no real position exists — audit is then a no-op).
   double real_entry = g_entry, real_sl = g_sl, real_vol = g_position_volume;
   if(PositionSelectByTicket(g_ticket))
   {
      real_entry = PositionGetDouble(POSITION_PRICE_OPEN);
      real_sl    = PositionGetDouble(POSITION_SL);
      real_vol   = PositionGetDouble(POSITION_VOLUME);
   }

   // 2. Real dollar-at-risk from calibrated symbol values.
   double ts = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double tv = CalibTickValue(_Symbol);
   if(ts<=0 || tv<=0 || real_vol<=0 || real_sl<=0) return;   // unmeasurable — keep plan values
   double real_risk = real_vol * (MathAbs(real_entry-real_sl)/ts) * tv;

   // 3. Loud planned-vs-actual audit line, always.
   string adj = (MathAbs(real_vol-planned_vol)>0.0001 || MathAbs(real_sl-planned_sl)>1e-9)
                ? "  [broker adjusted]" : "";
   if(planned_risk > 0)
      PrintFormat(VTAG+"RISK AUDIT %s: planned $%.2f (vol %.2f) -> actual $%.2f (vol %.2f, %+.1f%%)%s",
                  tag, planned_risk, planned_vol, real_risk, real_vol,
                  (real_risk-planned_risk)/MathMax(planned_risk,0.01)*100.0, adj);
   else
      PrintFormat(VTAG+"RISK AUDIT %s: actual $%.2f (vol %.2f)%s",
                  tag, real_risk, real_vol, adj);

   // 4. Adopt reality into every downstream consumer.
   g_risk_money      = real_risk;
   g_orig_risk       = MathAbs(real_entry-real_sl);
   g_entry           = real_entry;
   g_sl              = real_sl;
   g_position_volume = real_vol;

   // 5. Policy breach on REAL money: pause + close. This is the account-killer
   //    tripwire the 2026-09-03 incident lacked (real risk was 57% of equity
   //    while the plan said 0.5% and every pre-send guard passed).
   double cap_money = g_eq * InpMaxEffectiveRiskPct / 100.0;
   if(real_risk > cap_money)
   {
      PrintFormat(VTAG+"SENTINEL BREACH: real risk $%.2f > cap $%.2f (%.1f%% of equity) — PAUSED, closing position %I64u",
                  real_risk, cap_money, real_risk/MathMax(g_eq,0.01)*100.0, g_ticket);
      Telem("sentinel", StringFormat(
         "\"sym\":\"%s\",\"action\":\"CLOSE\",\"real_risk\":%.2f,\"cap\":%.2f,\"eq\":%.2f,\"vol\":%.2f",
         _Symbol, real_risk, cap_money, g_eq, real_vol));
      g_paused = true;
      ClosePosition("SENTINEL");
   }
}

//+------------------------------------------------------------------+
//| v26.28: PAPER TRADING ENGINE                                      |
//| InpLiveExecution=false is now a real simulator: virtual fill at   |
//| live bid/ask (spread-multiplier for conservatism), the position   |
//| is managed with the exact ManagePosition ladder (SL/TP/PLOCK/    |
//| ECUT/TIME/BE/trail + CB spike exits), closes flow through         |
//| HandleTradeClose so governor/learning/cooldown train on paper     |
//| trades, and sizing runs on VIRTUAL equity (InpPaperEquity) so the |
//| 20% cap and compounding validate the funded scenario.             |
//+------------------------------------------------------------------+
bool    g_pp_open=false;
int     g_pp_dir=0;
double  g_pp_entry=0, g_pp_sl=0, g_pp_tp=0, g_pp_orig_risk=0;
double  g_pp_vol=0, g_pp_eff_risk=0;
int     g_pp_bars=0, g_pp_max_hold=0;
double  g_pp_hw=0;
datetime g_pp_entry_time=0;
string  g_pp_tag="";
double  g_paper_eq=0, g_paper_start=0;

bool PaperActive() { return(!InpLiveExecution); }

//+------------------------------------------------------------------+
//| v26.30 MIN-LOT RISK ROUTER                                        |
//| Measures the SMALLEST achievable stop-risk on the chart symbol    |
//| (broker min lot at the EA's real stop geometry vs the risk plan   |
//| and the InpMaxEffectiveRiskPct cap), warns loudly when the account|
//| cannot trade this instrument, and points at instruments that fit. |
//+------------------------------------------------------------------+
void RunFitRouter()
{
   double point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double tv     = CalibTickValue(_Symbol);   // v26.25 truth: broker understates V75 tv 100x
   double tsz    = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double minlot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double atr_arr[1];
   bool have_atr = (CopyBuffer(hATR_E, 0, 1, 1, atr_arr)==1 && atr_arr[0]>0);
   double stop_dist = have_atr ? InpRouterScanATR*atr_arr[0] : 100*point;
   if(tsz<=0 || tv<=0 || stop_dist<=0 || minlot<=0)
   {
      Print(VTAG+"FIT ROUTER: skipped — symbol specs unavailable");
      return;
   }
   double eq         = PaperActive() ? PaperEquity() : AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = eq * InpRiskPerTrade;
   double cap_money  = eq * InpMaxEffectiveRiskPct / 100.0;
   double min_risk   = stop_dist / tsz * tv * minlot;   // $ risk of ONE min-lot trade
   bool fits_plan    = (min_risk <= risk_money + 1e-9);
   bool fits_cap     = (min_risk <= cap_money  + 1e-9);
   g_fit_ok          = fits_cap;

   if(fits_plan)
      g_fit_recommend = StringFormat("%s min-lot stop-risk $%.2f <= plan $%.2f (%.2f%% of eq) - GOOD FIT",
                                     _Symbol, min_risk, risk_money, min_risk/eq*100.0);
   else if(fits_cap)
      g_fit_recommend = StringFormat("%s min-lot stop-risk $%.2f exceeds the %.2f%% plan ($%.2f) but sits inside the %.0f%% cap - TOLERATED, each trade risks %.1f%% of equity",
                                     _Symbol, min_risk, InpRiskPerTrade*100.0, risk_money,
                                     InpMaxEffectiveRiskPct, min_risk/eq*100.0);
   else
   {
      double need_eq = min_risk / (InpMaxEffectiveRiskPct/100.0);
      g_fit_recommend = StringFormat("%s CANNOT FIT: min-lot stop-risk $%.2f > %.0f%% cap $%.2f - every signal would be vetoed. Suggested minimum equity for this symbol: $%.2f",
                                     _Symbol, min_risk, InpMaxEffectiveRiskPct, cap_money, need_eq);
   }
   Print(VTAG+"FIT ROUTER: "+g_fit_recommend);
   if(!g_fit_ok) ScanFitAlternatives(eq, cap_money);
   Telem("fit", StringFormat("\"sym\":\"%s\",\"eq\":%.2f,\"min_risk\":%.2f,\"plan\":%.2f,\"cap\":%.2f,\"fit\":%s,\"recommend\":\"%s\"",
          _Symbol, eq, min_risk, risk_money, cap_money,
          g_fit_ok?"true":"false", g_fit_recommend));
}

// v26.30: per-instrument fit comparison at the EA's REAL stop geometry
// (1.7 x mean M15 range via CopyRates — no indicator warmup needed). Symbols
// with no bar history fall back to a 100-point floor, which UNDERSTATES
// high-volatility instruments, so the basis is printed either way.
void ScanFitAlternatives(const double eq, const double cap_money)
{
   // VOLATILITY-ONLY universe (v26.33): the router may only recommend
   // Volatility indices. Boom/Crash never fits a mandate the EA cannot
   // certify (no V75-style walk-forward exists for CB, and none is planned).
   string cands[] = {"Volatility 10 Index","Volatility 25 Index","Volatility 50 Index",
                     "Volatility 75 Index","Volatility 100 Index"};
   Print(VTAG+"FIT ROUTER: instruments vs a $"+DoubleToString(eq,2)+
         " account (min-lot stop-risk at 1.7xATR M15):"
         );
   for(int i=0; i<ArraySize(cands); i++)
   {
      if(cands[i]==_Symbol) continue;
      if(!SymbolSelect(cands[i], true)) continue;   // pull specs via Market Watch
      double p   = SymbolInfoDouble(cands[i], SYMBOL_POINT);
      double tv  = CalibTickValue(cands[i]);   // calibrated — the scan must not inherit the broker lie
      double tsz = SymbolInfoDouble(cands[i], SYMBOL_TRADE_TICK_SIZE);
      double mlot= SymbolInfoDouble(cands[i], SYMBOL_VOLUME_MIN);
      if(tsz<=0 || tv<=0 || p<=0 || mlot<=0) continue;
      double basis_atr = 0.0;
      MqlRates rr[];
      if(CopyRates(cands[i], PERIOD_M15, 1, 60, rr)==60)
      {
         double s=0; for(int k=0;k<60;k++) s += (rr[k].high-rr[k].low);
         basis_atr = s/60.0;
      }
      double stop  = (basis_atr>0 ? InpRouterScanATR*basis_atr : 100.0*p);
      double r     = stop / tsz * tv * mlot;
      if(r <= cap_money)
         PrintFormat(VTAG+"   FITS: %-24s min-lot stop-risk $%.2f (%.1f%% of eq) [%s]",
                     cands[i], r, r/eq*100.0,
                     basis_atr>0?"1.7xATR":"100pt FLOOR — verify");
   }
}

double PaperEquity() { return(g_paper_eq>0 ? g_paper_eq : InpPaperEquity); }

string PaperFile() { return(SymbolTaggedFile("MitemshubAI_paper",".csv")); }

void PaperLog(string line)
{
   int h=FileOpen(PaperFile(), FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) { Print(VTAG+"paper log open failed: ", GetLastError()); return; }
   FileSeek(h,0,SEEK_END);
   FileWriteString(h, line+"\r\n");
   FileClose(h);
}

bool PaperInit()
{
   g_paper_eq=InpPaperEquity; g_paper_start=InpPaperEquity;
   int h=FileOpen(PaperFile(), FILE_READ|FILE_TXT|FILE_ANSI);
   if(h==INVALID_HANDLE) return(true);      // fresh start
   double eq=InpPaperEquity;
   double o_dir=0,o_entry=0,o_sl=0,o_tp=0,o_vol=0,o_eff=0,o_risk=0,o_hold=0;
   string  o_tag=""; datetime o_time=0; ulong o_ticket=0; bool dangling=false;
   while(!FileIsEnding(h))
   {
      string ln=FileReadString(h);
      if(StringLen(ln)<2) continue;
      string p[];
      int n=StringSplit(ln, ',', p);
      if(n<=0) continue;
      if(p[0]=="EQ" && n>=2)                 eq=StringToDouble(p[1]);
      else if(p[0]=="OPEN" && n>=11)
      {
         o_time=(datetime)StringToInteger(p[1]); o_ticket=(ulong)StringToInteger(p[2]);
         o_dir=(int)StringToInteger(p[3]);
         o_entry=StringToDouble(p[4]); o_sl=StringToDouble(p[5]); o_tp=StringToDouble(p[6]);
         o_vol=StringToDouble(p[7]); o_eff=StringToDouble(p[8]); o_risk=StringToDouble(p[9]);
         o_hold=(int)StringToInteger(p[10]); o_tag=(n>=12?p[11]:""); dangling=true;
      }
      else if(p[0]=="CLOSE" && n>=8)       { eq=StringToDouble(p[7]); dangling=false; }
   }
   FileClose(h);
   g_paper_eq=eq; g_paper_start=eq;         // paper equity survives restarts
   if(dangling)
   {
      g_pp_open=true; g_pp_dir=(int)o_dir; g_pp_entry=o_entry; g_pp_sl=o_sl; g_pp_tp=o_tp;
      g_pp_orig_risk=o_risk; g_pp_vol=o_vol; g_pp_eff_risk=o_eff; g_pp_max_hold=(int)o_hold;
      g_pp_tag=o_tag; g_pp_bars=0; g_pp_hw=0; g_pp_entry_time=o_time;
      g_ticket=o_ticket; g_dir=g_pp_dir; g_entry=g_pp_entry; g_sl=g_pp_sl; g_tp=g_pp_tp;
      g_orig_risk=g_pp_orig_risk; g_position_volume=g_pp_vol; g_risk_money=g_pp_eff_risk;
      g_max_hold=g_pp_max_hold; g_bars_held=0; g_high_water_r=0; g_entry_time=o_time;
      PrintFormat(VTAG+"PAPER restore: virtual %s position #%I64u from %s",
                  g_pp_dir>0?"BUY":"SELL", o_ticket, TimeToString(o_time));
   }
   return(true);
}

bool PaperOpen(int direction,double entry,double sl,double tp,double vol,
               double eff_risk,string tag,bool is_band,double sl_atr)
{
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double sprd=ask-bid;
   double extra=MathMax(InpPaperSpreadMult-1.0,0.0)*sprd;
   double fill=(direction>0)?ask+extra:bid-extra;   // conservative virtual fill
   double delta=fill-entry;
   if(MathAbs(delta)>0){ entry+=delta; sl+=delta; tp+=delta; }
   ulong ticket=(ulong)TimeCurrent();
   g_pp_open=true; g_pp_dir=direction; g_pp_entry=entry; g_pp_sl=sl; g_pp_tp=tp;
   g_pp_orig_risk=MathAbs(entry-sl); g_pp_vol=vol; g_pp_eff_risk=eff_risk;
   g_pp_bars=0; g_pp_hw=0; g_pp_entry_time=TimeCurrent(); g_pp_tag=tag;
   g_pp_max_hold=(is_band && sl_atr>0)
      ? (int)MathMax(4,(int)MathRound((double)InpBandHoldSec/MathMax(60,PeriodSeconds(g_tf_entry)))+2)
      : InpMaxHoldBars;
   g_ticket=ticket; g_dir=direction; g_entry=entry; g_sl=sl; g_tp=tp;
   g_orig_risk=g_pp_orig_risk; g_position_volume=vol; g_risk_money=eff_risk;
   g_entry_time=g_pp_entry_time; g_bars_held=0; g_high_water_r=0; g_max_hold=g_pp_max_hold;
   PrintFormat(VTAG+"PAPER FILL %s vol=%.2f @%.5f SL=%.5f TP=%.5f risk=$%.2f (%.1f%% vEq) | %s",
               direction>0?"BUY":"SELL", vol, entry, sl, tp, eff_risk,
               eff_risk/MathMax(PaperEquity(),0.01)*100.0, tag);
   Telem("paper_open", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"dir\":%d,\"entry\":%.5f,\"sl\":%.5f,\"tp\":%.5f,"
      "\"vol\":%.2f,\"eff_risk\":%.2f,\"regime\":\"%s\",\"strat\":\"%s\",\"veq\":%.2f",
      _Symbol,ticket,direction,entry,sl,tp,vol,eff_risk,RegimeToStr(g_regime),tag,PaperEquity()));
   PaperLog(StringFormat("OPEN,%I64d,%I64u,%d,%.5f,%.5f,%.5f,%.2f,%.2f,%.5f,%d,%s",
            (long)TimeCurrent(),ticket,direction,entry,sl,tp,vol,eff_risk,g_pp_orig_risk,g_pp_max_hold,tag));
   return(true);
}

void PaperClose(string reason)
{
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double exit=(g_pp_dir>0)?bid:ask;
   double r=g_pp_orig_risk>0?((g_pp_dir>0)?(exit-g_pp_entry):(g_pp_entry-exit))/g_pp_orig_risk:0;
   double pnl=g_pp_eff_risk*r;
   ulong ticket=g_ticket;
   PaperLog(StringFormat("CLOSE,%I64d,%I64u,%s,%.5f,%.3f,%.2f,%.2f",
            (long)TimeCurrent(),ticket,reason,exit,r,pnl,PaperEquity()+pnl));
   HandleTradeClose(exit, reason, 0);        // full close bookkeeping on the virtual trade
   g_paper_eq+=pnl;
   PaperLog(StringFormat("EQ,%.2f",g_paper_eq));
   g_pp_open=false; g_pp_dir=0; g_pp_entry=0; g_pp_sl=0; g_pp_tp=0;
   g_pp_orig_risk=0; g_pp_vol=0; g_pp_eff_risk=0; g_pp_hw=0; g_pp_bars=0;
   g_ticket=0;
   PrintFormat(VTAG+"PAPER CLOSE %s R=%+.2f pnl=$%+.2f vEq=$%.2f", reason, r, pnl, g_paper_eq);
   Telem("paper_close", StringFormat(
      "\"sym\":\"%s\",\"ticket\":%I64u,\"reason\":\"%s\",\"exit\":%.5f,\"r\":%.3f,\"pnl\":%.2f,\"veq\":%.2f",
      _Symbol,ticket,reason,exit,r,pnl,g_paper_eq));
}

void PaperManage()
{
   if(!g_pp_open){ g_ticket=0; return; }
   g_pp_bars++; g_bars_held=g_pp_bars;
   double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   if(g_pp_dir>0){ if(bid<=g_pp_sl){PaperClose("STOP");return;} if(bid>=g_pp_tp){PaperClose("TARGET");return;} }
   else         { if(ask>=g_pp_sl){PaperClose("STOP");return;} if(ask<=g_pp_tp){PaperClose("TARGET");return;} }
   double r_now=g_pp_orig_risk>0?((g_pp_dir>0)?(bid-g_pp_entry):(g_pp_entry-ask))/g_pp_orig_risk:0;
   if(r_now>g_pp_hw) g_pp_hw=r_now;
   if(g_pp_hw>=1.0 && r_now<=InpProfitLockR && r_now>0){PaperClose("PLOCK");return;}
   if(InpGraduatedExit && g_pp_bars>=InpEarlyCutBars && g_pp_bars<g_pp_max_hold
      && r_now<=InpEarlyCutMaxR && g_pp_hw<0.3){PaperClose("ECUT");return;}
   int eff_hold=g_pp_max_hold;
   if(InpGraduatedExit && r_now>0.3 && g_pp_bars>=g_pp_max_hold)
      eff_hold=(int)(g_pp_max_hold*InpExtendWinMult);
   if(g_pp_bars>=eff_hold && r_now<=0.2){PaperClose("TIME");return;}
   if(InpUseBreakeven && r_now>=InpBeTriggerR)   // virtual BE: state-only
   {
      double be=(g_pp_dir>0)?g_pp_entry+2*_Point:g_pp_entry-2*_Point;
      if((g_pp_dir>0 && g_pp_sl<be)||(g_pp_dir<0 && g_pp_sl>be)) g_pp_sl=be;
   }
   if(InpUseTrailing && r_now>=InpTrailStartR)   // virtual trail
   {
      double dist=InpTrailDistR*g_pp_orig_risk;
      if(g_pp_dir>0){ double ns=bid-dist; if(ns>g_pp_sl && ns>g_pp_entry) g_pp_sl=ns; }
      else         { double ns=ask+dist; if(ns<g_pp_sl && ns<g_pp_entry) g_pp_sl=ns; }
   }
   g_high_water_r=g_pp_hw;
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
   // v26.13: validity guard before every PositionModify — the price can gap
   // between bid/ask read and the modify call, so an unguarded SL can land
   // inside the broker's stops level → retcode 10016 spam.
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

   // trailing stop
   if(InpUseTrailing && r_now >= InpTrailStartR)
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
   L[6]=StringFormat("Strats: PB=%s BO=%s MOM=%s MR=%s BF=%s | VBurst: %s",
         InpUsePullback?"ON":"OFF", InpUseBreakout?"ON":"OFF",
         InpUseMomentum?"ON":"OFF", InpUseMeanRevert?"ON":"OFF", InpUseBandFade?"ON":"OFF",
         g_vb.GetDashboard());
   L[7]=StringFormat("MinScore: %d | 2+Agree: %s | Cooldown: %d",InpMinScore,InpRequire2Strats?"YES":"NO", g_cooldown);
   //--- v26.16: StartHour == EndHour means the wrap-midnight branch of
   //--- IsSessionActive() is always true — the EA trades 24/7.
   string sessTxt = (InpSessionStartHour == InpSessionEndHour)
      ? "24/7"
      : StringFormat("%02d:00-%02d:%02d", InpSessionStartHour, InpSessionEndHour - 1,
                     60 - MathMax(InpSessionEndOffsetMin, 0));   L[8]=StringFormat("Risk: %.2f%% (cap %.0f%%) | TP: %.1fx | Hold: %d",
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
      // v26.20: show which strategies the governor holds back (and probe position)
      string dis="";
      for(int i=0; i<STRAT_SLOTS; i++)
         if(!g_strat_enabled[i])
            dis += (dis==""?"":", ")+STRAT_NAMES[i]+
                   ((InpProbeDisabled && InpProbeEveryN>0)
                     ? StringFormat("(probe %d/%d)", g_strat_probe_n[i] % InpProbeEveryN, InpProbeEveryN)
                     : "(frozen)");
      if(dis!="") L[line++]=StringFormat("Governor: %s", dis);
      // v26.23: governor coordination status — spread gate + conviction throttle
      L[line++]=StringFormat("Coord: spread-gate %s (%.0f%% stop) | conviction %s",
                             InpMaxSpreadATRFrac>0?"ON":"OFF", InpMaxSpreadATRFrac*100.0,
                             (InpAdaptiveConviction && g_daily_pnl<0.0) ? "min+1 (day in red)" : "normal");
      if(PaperActive() && line<25)   // v26.28
         L[line++]=StringFormat("PAPER: vEq $%.2f (start $%.2f) | fill spread x%.1f | no real orders",
                                g_paper_eq, g_paper_start, InpPaperSpreadMult);
      // v26.12: legacy reject counters (no longer incremented since v26.34)
      if(g_cb_reject_total > 0)
         L[line++]=StringFormat("Rejects: %d total (legacy, CB engine removed)",
                                g_cb_reject_total);
   }

   // v25.1: tick recorder status (when enabled)
   if(InpTickRecordEnabled)
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
