# MITEMSHUB AI MARKET ENGINE — Architecture Plan (Phase 0)

> **Status:** PHASE 0 — audit + architecture. No MQL5 implementation yet.
> **Mandate:** robustness > backtest profit; risk control > trade frequency;
> out-of-sample > in-sample; transparency > marketing claims.
> **Hard rules:** live trading disabled by default; WAIT is a valid decision;
> no martingale/grid; no fake AI; no forced trades.

---

## 1. Current repository audit

### 1.1 What exists today

| Layer | Location | State |
|---|---|---|
| Python research lab | `src/synthetic_trader/` | Mature, tested (961+31 tests green) |
| EGARCH volatility forecaster | `models/garch.py`, `models/garch_calibration.py` | Calibrated, walk-forward validated |
| Horizon forecast + band geometry | `strategy/band_geometry.py` | Zero-drawdown stop/target from σ_h |
| Regime detection | `models/regime_detector.py` (HMM + CUSUM + RegimeShift), `strategy/regime_models.py` (trend/range/breakout) | Mature |
| Risk engine | `risk/engine.py` (RiskState, daily-loss, streak, exposure limits) | Mature |
| Stage-3 empirical gate | `live/stage3_gate.py` (proven/still_learning/suppressed, break-even floors) | Mature |
| Strategy ensemble (Python) | `strategy/decision_engine.py`, `setup_builder.py`, `confirmation_builder.py`, `top_down_bias.py`, `swing_execution_builder.py`, `volatility_harvesting.py` | Present; band geometry is the only validated-positive leg |
| MT5 execution (Python IPC) | `execution/mt5.py`, `live/execution_backends.py` | Works but IPC-bound; superseded by EA for execution |
| MQL5 thin executor | `mql5/SynthCallExecutor.mq5` (498 lines) | Executes Python-emitted calls; proven-only; tested protocol |
| MQL5 docs | `mql5/README.md`, `docs/PHASE5_SUMMARY.md` §53 | Present |

### 1.2 Compiler / toolchain (verified this audit)

- **MetaEditor:** `C:/Program Files/MetaTrader 5 Terminal/metaeditor64.exe` ✅ (and a second copy under `C:/Program Files/MetaTrader 5 Terminal/`)
- **Terminal data folders:** `%APPDATA%\MetaQuotes\Terminal\DBE9B8B3...\MQL5` and `FB9A56D6...\MQL5` — the Experts folder currently has only MetaQuotes stock (`Advisors/Examples/Free Robots`)
- **So:** every development phase can **compile and run in the Strategy Tester** on this machine. No blocker.

### 1.3 What can be reused / must be replaced / is missing

| Item | Verdict | Rationale |
|---|---|---|
| `SynthCallExecutor.mq5` JSON parser, `ReadCommonFile`/`WriteCommonFile`, `NormalizeVolume`, breakeven trail, daily-loss halt | **Reuse** (refactor into `Core/` + `Execution/`) | Already correct, tested protocol |
| Band geometry (0.20σ_h / 0.80σ_h, 1h hold) | **Port** into MQL5 `Strategies/` as the primary validated strategy | §38 sweep winner, +0.994R/23 trades on R_75@300s — the only validated-positive leg |
| EGARCH dynamics in MQL5 | **Do NOT port wholesale** | Too heavy for MQL5; the Python lab already computes calibrated σ. MQL5 consumes the *call levels* (external signal) OR a lightweight ATR/vol-normalized proxy for standalone tester operation |
| HMM regime detector | **Port as deterministic approximation** (ADX + ATR-percentile + efficiency-ratio + Hurst) | Full online HMM in MQL5 is heavy; keep the output contract identical (`regime`, `regime_confidence`) |
| RiskEngine (Python) | **Port** to `Risk/` | Direct mapping; keep hard limits first, no overrides |
| Stage-3 gate | **Port as `EvidenceGate`** in `Decision/` | Per-trigger break-even floor logic is fully specified |
| SMC sniper / pattern strategies (Python) | **Do NOT port as active** | CSPRNG synthetic indices show no pattern edge; port only as *research* strategy interfaces, default OFF, clearly labeled unvalidated |
| Walk-forward / Monte Carlo / parameter sensitivity | **Stays in Python lab** | MQL5 tester cannot do this honestly; the lab already has `band_revalidate`, `vol_param_sweep`, head-to-head verifier. MQL5 exports CSV trades; Python analyzes |
| Trade journal CSV | **New** in MQL5 (`Journal/`) | §33 machine-readable log; Python consumes for analytics |

### 1.4 Key honest finding the plan must respect

Across the entire project history the only leg with positive measured expectancy is
**EGARCH vol-dynamics band geometry** (R_75@300s). Pattern/SMC strategies repeatedly
measured ≈0 or negative. Therefore:

- The MQL5 engine is **modular with all five strategy interfaces** (Trend, Breakout,
  MeanReversion, LiquiditySweep, Pullback) as the user specified.
- **Only the band strategy is active by default**, and only after its own
  out-of-sample walk-forward in MQL5 agrees with the Python verdict.
- The other strategies exist as research modules, OFF by default, with a
  documented testable hypothesis each — per the user's "no strategy without a
  testable hypothesis" rule. They may never be switched on if they fail OOS.

---

## 2. Proposed architecture

```
MITEMSHUB_AI/
├── Core/
│   ├── Constants.mqh          ENUM_REGIME, ENUM_DECISION, ENUM_EXIT_REASON, reasons
│   ├── Config.mqh             all `input` params, grouped; one place
│   ├── StateManager.mqh       single source of truth for engine state
│   └── Engine.mqh             orchestrates: OnTick → pipeline → journal
├── Market/
│   ├── SymbolAdapter.mqh      SymbolInfo* discovery (bid/ask/point/digits/tick, stops/freeze, min/max/step lot, contract, spread)
│   ├── MarketData.mqh         price/candle access with closed-bar discipline
│   ├── CandleEngine.mqh       rolling candle windows, bar-state detection
│   ├── TimeframeManager.mqh   configurable MTF (default 4H/1H/15M/5M/1M)
│   ├── NormalizationEngine.mqh  ATR-multiples, % returns, z-scores, relative distance
│   └── VolatilityEngine.mqh   ATR, realized vol, ATR percentile, expansion
├── Regime/
│   ├── RegimeEngine.mqh       fuses the detectors below → regime + confidence
│   ├── TrendDetector.mqh      ADX, MA slope, efficiency ratio, EMA stack
│   ├── RangeDetector.mqh      overlap, ADX floor, mean-reversion score
│   ├── CompressionDetector.mqh  ATR percentile, range contraction
│   ├── ExpansionDetector.mqh  ATR percentile, displacement
│   ├── TransitionDetector.mqh crossover of regime scores, persistence req
│   └── HurstAnalyzer.mqh      Hurst over rolling window (one input, not the sole arbiter)
├── Structure/
│   ├── StructureEngine.mqh    aggregate of the detectors below
│   ├── SwingDetector.mqh      fractal swinguards + confirmed swings
│   ├── BOSDetector.mqh        break of structure (closed-bar confirmed)
│   ├── CHOCHDetector.mqh      change of character
│   ├── LiquidityEngine.mqh    swing highs/lows as liquidity, sweeps
│   ├── SupportResistance.mqh  derived levels with touch counts
│   └── DisplacementDetector.mqh  normalized range/body displacement
├── Strategies/
│   ├── StrategyEngine.mqh     registry + regime-allowance matrix + scheduling
│   ├── BandGeometry.mqh       ★ validated leg: σ_h stop/target, z_entry gate
│   ├── TrendContinuation.mqh  RESEARCH (default OFF)
│   ├── BreakoutStrategy.mqh   RESEARCH (default OFF)
│   ├── MeanReversion.mqh      RESEARCH (default OFF)
│   ├── LiquiditySweep.mqh     RESEARCH (default OFF)
│   └── PullbackStrategy.mqh   RESEARCH (default OFF)
├── Decision/
│   ├── DecisionEngine.mqh     BUY/SELL/WAIT + explanation (the user's §10 spec)
│   ├── ScoringEngine.mqh      configurable weighted scores
│   ├── ConfidenceEngine.mqh   score → confidence, calibrated-ish
│   └── TradeQualityEngine.mqh R-multiple MFE/MAE tracking, setup stats
├── Risk/
│   ├── RiskEngine.mqh         final authority over strategy requests
│   ├── PositionSizer.mqh      equity × risk% / stop-distance → lots
│   ├── ExposureManager.mqh    open exposure, hedging/netting aware
│   ├── DrawdownProtection.mqh max daily loss/drawdown/streak → hard halt
│   └── RiskLimits.mqh         Max* limits table + EMERGENCY_STOP
├── Execution/
│   ├── ExecutionEngine.mqh    CTrade wrapper; verify fills, log every attempt
│   ├── OrderManager.mqh       order lifecycle (request → verify → record)
│   ├── PositionManager.mqh    BE/trail/partial/time-exit with reason codes
│   ├── StopManager.mqh        ATR/structure/vol-adjusted SL, no arbitrary points
│   ├── TakeProfitManager.mqh  fixed-R/structure/ATR/liquidity targets
│   └── ExecutionMonitor.mqh   rejections, requotes, margin, connection
├── Journal/
│   ├── TradeJournal.mqh       CSV (per §33) + decision/exit reason codes
│   ├── DecisionLogger.mqh     every BUY/SELL/WAIT with full context (§10)
│   └── PerformanceLogger.mqh  per-strategy/regime/direction/hour/confidence buckets
├── Analytics/
│   ├── PerformanceAnalytics.mqh  PF, expectancy, avg R, DD, recovery, streaks
│   ├── ExpectancyEngine.mqh     R-based expectancy, per-bucket
│   └── RegimeAnalytics.mqh      performance by regime
├── UI/
│   ├── Dashboard.mqh          on-chart panel (the §34 spec)
│   ├── Panel.mqh              layout + drawing primitives
│   └── VisualSignals.mqh      entries/exits/SL/TP/structure/liquidity lines
└── MitemshubAI.mq5            entry point: inputs, init, pipeline, deinit
```

### 2.1 Module dependency graph (compile order)

```
Core (Constants → Config → StateManager)
  ↑
Market (SymbolAdapter → MarketData/CandleEngine → TimeframeManager →
       NormalizationEngine → VolatilityEngine)
  ↑
Regime (HurstAnalyzer → Trend/Range/Compression/Expansion/Transition → RegimeEngine)
Structure (Swing → BOS/CHOCH → Liquidity/SR → Displacement → StructureEngine)
  ↑
Strategies (BandGeometry + research strategies → StrategyEngine [needs Regime+Structure])
  ↑
Decision (Scoring → Confidence → TradeQuality → DecisionEngine [needs all above])
  ↑
Risk (PositionSizer → RiskLimits/Drawdown/Exposure → RiskEngine)
  ↑
Execution (Order/Stop/TP/Position/ExecutionMonitor → ExecutionEngine)
  ↑
Journal (TradeJournal/DecisionLogger/PerformanceLogger)
  ↑
Analytics (PerformanceAnalytics/Expectancy/RegimeAnalytics)
  ↑
UI (Panel → Dashboard → VisualSignals)
  ↑
MitemshubAI.mq5
```

Compile order is exactly this DAG — every phase adds one layer and must compile.

---

## 3. Data flow

```
MT5 terminal (ticks, history, symbol specs)
  │  (closed-bar discipline: signals only on iClose-confirmed bars)
  ▼
MarketData → CandleEngine (rolling windows per timeframe)
  ▼
SymbolAdapter (broker specs, once at init + on-demand)
  ▼
NormalizationEngine (ATR mult, % ret, z-score, relative distance)
  ▼
VolatilityEngine → RegimeEngine (fused) ──► StructureEngine
        │                                     │
        ▼                                     ▼
   StrategyEngine (regime-allowance matrix)
        │  each strategy returns setup{candles}
        ▼
   TradeQualityEngine (R-based quality)
        ▼
   DecisionEngine → BUY / SELL / WAIT + reason
        ▼
   RiskEngine (final veto) → PositionSizer
        ▼
   ExecutionEngine (CTrade, verify fill)
        ▼
   PositionManager (BE/trail/exit) + StopManager/TakeProfitManager
        ▼
   Journal (CSV) ──► Analytics ──► Dashboard
```

---

## 4. Decision flow (the user's §10 spec, made concrete)

```
1. Regime:  fused classification → regime + confidence (detectors disagree → lower confidence)
2. Structure: confirmed swings/BOS/CHOCH/liquidity on closed bars
3. Strategy selection: regime-allowance matrix → candidate strategies
4. Setup: each allowed strategy computes entry/stop/target candidates + quality
5. Trade quality: expected R vs invalidation; historical setup stats when available
6. Score: configurable weighted sum (statistical, structure, regime, setup, momentum,
   vol, RR, execution) → 0..100
7. Confidence: score bucket → confidence
8. Decision: BUY / SELL / WAIT, with a human-readable explanation
   (e.g. "WAIT — REGIME=RANGE, TREND ALIGNMENT=LOW, SETUP=54, RR=INSUFFICIENT")
9. Explanation → DecisionLogger (journal), always
```

**WAIT is first-class.** No signal → WAIT. Regime forbids strategy → WAIT with
reason. Score below `MinConfidence` → WAIT. Risk vetoes → WAIT with reason.

---

## 5. Risk flow

```
Strategy request (direction, lots, sl, tp)
  │
  ▼
RiskEngine.evaluate():
  1. hard limits table (MaxRiskPerTrade, MaxDailyLoss, MaxDailyDrawdown,
     MaxOpenPositions, MaxTotalExposure, MaxConsecutiveLosses, MaxEquityDrawdown,
     MaxTradesPerHour, MaxTradesPerDay) — ANY breach → TRADING DISABLED
  2. EMERGENCY_STOP input → no new trades, hard
  3. exposure check (hedging vs netting via ACCOUNT_MARGIN_MODE)
  4. margin check (free margin ≥ required × safety factor)
  5. if approved → PositionSizer: lots = (equity × risk%) / (stopDist × tickValue/tickSize)
     clamped to volume min/step/max
  │
  ▼
ExecutionEngine (place, verify, journal) → PositionManager (manage, exit)
```

Never auto-override a hard safety stop. No martingale. No averaging down.

---

## 6. Execution flow

```
CTrade wrapper (magic, deviation, filling-by-symbol)
  → order_send with explicit request struct
  → result retcode: DONE → verify position exists (PositionGetTicket / select)
  → every attempt logged (request + retcode + response)
  → failures handled by type: rejection, invalid stops, volume error, market closed,
    requote, trade context, connection, insufficient margin, symbol restrictions
  → no assumption of success without verification
```

Account mode: `ACCOUNT_MARGIN_MODE` — hedging → allow multiple positions (bounded
by ExposureManager); netting → single position per symbol, opposite direction
flips the position (documented, no hidden assumptions).

---

## 7. What stays in Python (deliberately)

- Walk-forward validation, parameter sensitivity, Monte Carlo trade-sequence
  analysis, out-of-sample verdicts (`band_revalidate`, `vol_param_sweep`,
  `headtohead_verify`) — MQL5 exports CSV; Python does the statistics.
- EGARCH calibrated σ and the Stage-3 outcomes journal — the live EA can consume
  the Python-emitted call file (`SYNTH_EA_EMIT=1`, already built) as the
  **external signal interface**, while the standalone MQL5 band leg keeps the
  tester self-sufficient.

This is the honest two-sided contract: **MQL5 = market intelligence +
execution + journal + visual tester engine; Python = the statistical lab that
validates what MQL5 is allowed to trade.**

---

## 8. Technical risks & MQL5-specific limitations

1. **"Every tick based on real ticks" needs broker tick history.** Deriv
   synthetic indices: tick history must be downloaded in the tester; if the
   broker does not serve full tick history, fall back to "Every tick based on
   real ticks" → if unavailable, document and use 1-minute OHLC with the
   known grail-risk caveat (never "Open prices only" for the final verdict).
2. **No numpy/pandas in MQL5.** Rolling statistics are hand-rolled arrays;
   keep windows bounded (e.g. 500 bars) to bound tester memory/CPU.
3. **File I/O in the tester** is sandboxed to the tester's Files folder; the
   call-file interface must be tester-aware (write only when not optimizing;
   guard with `MQLInfoInteger(MQL_OPTIMIZATION/FORWARD)` — the MQL5 docs rule).
4. **OnTimer** min period 1s; tick-driven work must live in OnTick.
5. **Look-ahead discipline:** signals only on closed bars; current-bar features
   explicitly labeled and never used for entries.
6. **Hurst/ADX in MQL5** are approximations of the Python HMM; the fused regime
   engine must tolerate detector disagreement by lowering confidence, never by
   forcing a trade.
7. **Digits/point differences between brokers** — SymbolAdapter is mandatory;
   every level computation goes through it. No hardcoded 7734-style prices.
8. **Parameter fragility:** the config surface is large; robustness tests
   (neighboring values) are a Phase-11 gate, and only robust regions ship.
9. **100% win rates are suspicious, not impressive** — a Phase-11 QA rule.

---

## 9. Validation strategy

- **Phase gates:** compile after every phase (MetaEditor CLI: `metaeditor64.exe
  /compile:path /log`), unit-test functions per §32 (symbol info, volume, SL/TP,
  ATR, normalization, regime, structure, sizing, risk limits, order validation).
- **Backtest:** Strategy Tester, "Every tick based on real ticks", walk-forward
  date windows mirroring the Python corpus split (train/validate/OOS).
- **Cross-validation with Python:** MQL5 band-leg trades (CSV) vs Python
  `backtest-vol` on the same corpus/params → the two engines must agree in
  direction of expectancy; divergence is a bug to fix, not a feature.
- **Robustness:** neighboring-parameter sweeps in Python on MQL5-exported CSV;
  Monte Carlo trade-sequence randomization on the CSV (drawdown/streak/ruin).
- **Forward/demo:** only after all gates pass; live requires explicit
  `InpLiveTradingEnabled=true` + hard confirmation.

---

## 10. File manifest

**Create (all under `mql5/MITEMSHUB_AI/`):** the full tree in §2 (≈30 `.mqh` +
`MitemshubAI.mq5`), plus `mql5/MITEMSHUB_AI/README.md` and
`mql5/IMPLEMENTATION_PLAN.md`.

**Modify:** `mql5/SynthCallExecutor.mq5` — refactor shared primitives
(JSON reader, Common-File I/O, volume normalization) into `Core/`; keep it as
the thin executor or fold its role into the new engine's `Execution/` with a
compat shim. `mql5/README.md` — link to the new engine docs.

**Do not touch:** the Python engine (it is the validation authority), except
where the CSV/trade-log consumer is added later (analytics only).

---

## 11. Development phases (see IMPLEMENTATION_PLAN.md for detail)

```
Phase 1  Core + Market (SymbolAdapter, MarketData, CandleEngine, Timeframe,
         Normalization, Volatility)                 → compile + unit tests
Phase 2  Regime (all detectors + fuser)             → compile + tests
Phase 3  Structure (swings, BOS, CHOCH, liquidity, SR, displacement) → compile + tests
Phase 4  Strategies (BandGeometry active; 4 research stubs) → compile + tests
Phase 5  Decision (scoring, confidence, quality, decision+reason) → compile + tests
Phase 6  Risk (sizer, limits, drawdown, exposure)   → compile + tests
Phase 7  Execution (order/stop/TP/position/monitor) → compile + tests
Phase 8  Journal + Analytics                        → compile + tests
Phase 9  UI (dashboard, signals)                    → compile + tester run
Phase 10 Integration + Strategy Tester walk-forward (R_75/R_100, 60s/300s)
Phase 11 Robustness (neighboring params, Monte Carlo on CSV, Python cross-check)
Phase 12 Forward/demo mode only after all gates; live requires explicit switch
```

Each phase ends **only** when: compiles clean, unit tests pass, and the phase
gate documented in IMPLEMENTATION_PLAN.md is satisfied.

---

*End of ARCHITECTURE_PLAN.md — pending review before Phase 1.*
