# MITEMSHUB AI MARKET ENGINE — Implementation Plan (Phase 0)

> Companion to `ARCHITECTURE_PLAN.md`. This is the **build order and the test
> gates**. No implementation happens until this plan is approved.
> Compiler available: `C:/Program Files/Blueberry Markets MetaTrader 5/metaeditor64.exe`.

---

## 0. Working agreements

- **Every phase ends with:** (a) clean compile via MetaEditor CLI, (b) unit-test
  functions for that phase pass, (c) the phase gate below is satisfied.
- **No strategy ships without a testable hypothesis** (the §"hypothesis" template
  in the request). A strategy that only "looks good on a chart" is rejected.
- **Live trading disabled by default.** `InpLiveTradingEnabled` defaults `false`,
  and the engine additionally refuses to run live unless the account is a demo
  or the operator explicitly confirms via a confirmation input.
- **Compile command pattern (Windows, from repo root):**
  `"C:/Program Files/Blueberry Markets MetaTrader 5/metaeditor64.exe" /compile:"<abs path to .mq5>" /log:"<abs path to .log>"` — logs land in the same dir as the source by default; the `/log` flag pins it.

---

## 1. Global conventions (all files)

- **Namespace of inputs:** every tunable is an `input` grouped in `Core/Config.mqh`
  (single include, no magic numbers in logic files).
- **Reason codes:** enums in `Core/Constants.mqh` — `ENUM_EXIT_REASON`
  (SL_HIT, TP_HIT, TIME_EXIT, STRUCTURE_EXIT, OPPOSITE_SIGNAL, EMERGENCY_STOP, ...),
  `ENUM_REGIME`, `ENUM_DECISION` (BUY/SELL/WAIT), `ENUM_STRATEGY`.
- **Closed-bar discipline:** every entry signal requires the triggering bar to be
  closed (`iTime` of the last closed bar); current-bar features are only used for
  management, never for entries.
- **SymbolAdapter gate:** any price/level arithmetic goes through the adapter.
  Nothing hard-codes R_75/R_100 prices, digits, or lots.
- **Error handling:** functions return `bool` + set a reason string; the engine
  logs and never silently continues on a failed order/state read.

---

## 2. Phase-by-phase build

### Phase 1 — Core + Market  ✅ COMPLETE (2026-08-10)

**Status:** compiled clean in MetaEditor (`0 errors, 0 warnings`, X64 Regular),
unit-test suite `Tests/Phase1Tests.mq5` staged in the terminal Experts folder;
logic verified 32/32 via the Python mirror (`phase1_logic_check.py`); **run in
the real Strategy Tester on SYN75: 61 passed, 0 failed, SUITE PASSED**
(tester log: `Tester/logs/20260810.log`, agent `127.0.0.1:3001`).

Per the scoped approval, Phase 1 delivered Core (Constants, Config,
StateManager) + Market (SymbolAdapter, NormalizationEngine, VolatilityEngine);
MarketData/CandleEngine/TimeframeManager roll into Phase 2.

**Files created (initial scope):**

| File | Contents |
|---|---|
| `Core/Constants.mqh` | enums, reason codes, default limits |
| `Core/Config.mqh` | ALL `input` params grouped (Risk, Regime, Structure, Strategy toggles, Execution, Journal, Debug, Safety) |
| `Core/StateManager.mqh` | holds current regime, structure snapshot, open positions summary, daily stats; single writer via Engine |
| `Market/SymbolAdapter.mqh` | init: collect SYMBOL_BID/ASK/POINT/DIGITS/TICK_SIZE/TICK_VALUE/VOLUME_MIN/MAX/STEP/STOPS_LEVEL/FREEZE_LEVEL/CONTRACT_SIZE/SPREAD; helpers: `NormalizeLots()`, `IsPriceValid()`, `PointToPrice()`, `PipsFromDistance()` |
| `Market/MarketData.mqh` | tick + closed-bar access; `Ask()/Bid()`, `BarClosed(tf, shift)`, `iCloseSafe()`, spread read |
| `Market/CandleEngine.mqh` | ring buffers of candles per timeframe (fixed capacity, e.g. 500); computes OHLC windows, bar count |
| `Market/TimeframeManager.mqh` | configurable 4H/1H/15M/5M/1M with defaults; maps enum↔seconds; validates inputs |
| `Market/NormalizationEngine.mqh` | `NormalizeRange(candle, atr)`, `PercentReturn()`, `ZScore()`, `RelativeDistance(price, level, atr)` |
| `Market/VolatilityEngine.mqh` | ATR (configurable period), realized vol, ATR percentile over window, expansion flag |

**Phase gate:** compiles; unit tests for SymbolAdapter (volumes, digits, price
normalization on a real V75 symbol), NormalizationEngine (known inputs → known
outputs), VolatilityEngine (ATR on a synthetic series), TimeframeManager (mapping
+ invalid input rejection).

### Phase 2 — Regime  ✅ COMPLETE (2026-08-10)

**Status:** compiled clean in MetaEditor (`0 errors, 0 warnings`);
`Tests/Phase2Tests.mq5` staged in the terminal Experts folder; logic verified
30/30 via the Python mirror (`phase2_logic_check.py`); **run in the real
Strategy Tester on SYN75: 40 passed, 0 failed, SUITE PASSED**.  The mirror
caught and fixed a test-data bug before it reached the tester: the transition
case placed its volatility change outside the detector's 2-window view, and the
"persistent" Hurst case used drift too weak for R/S to resolve — both test
series corrected. Also delivered the deferred Market infra from Phase 1:
TimeframeManager, CandleEngine, MarketData (MarketData's CopyRates/iATR
signatures were corrected against the real MQL5 API during the clean-compile
pass).

**Files created:**

| File | Contents |
|---|---|
| `Regime/HurstAnalyzer.mqh` | rolling Hurst estimate over a bounded window |
| `Regime/TrendDetector.mqh` | ADX, MA slope, efficiency ratio, EMA stack → trend score + direction |
| `Regime/RangeDetector.mqh` | overlap ratio, ADX floor, mean-reversion score |
| `Regime/CompressionDetector.mqh` | ATR percentile low + range contraction |
| `Regime/ExpansionDetector.mqh` | ATR percentile high + displacement |
| `Regime/TransitionDetector.mqh` | regime-score crossovers + persistence requirement |
| `Regime/RegimeEngine.mqh` | fuses the six; outputs regime, confidence (lowered when detectors disagree), trend_direction, volatility_state, mean_reversion_score, transition_probability |

**Hypothesis (regime fuser):** regime classification with independent measurements
is more stable than any single indicator; disagreement lowers confidence (never
forces a trade).

**Phase gate:** compiles; unit tests classify synthetic series (trend, range,
compression) correctly; disagreement test → confidence < agreeing case.

### Phase 3 — Structure  ✅ COMPLETE (2026-08-11)

**Files built:**

| File | Contents |
|---|---|
| `Structure/SwingDetector.mqh` | fractal swing guards (left/right N bars, closed bars only) + ATR-prominence strength; emits `SwingPoint{time, price, bar, direction, strength}` |
| `Structure/BOSDetector.mqh` | break of structure on closed bars, one event per level crossing |
| `Structure/CHOCHDetector.mqh` | change of character (HH+HL / LH+LL), stateless per-bar recompute |
| `Structure/LiquidityEngine.mqh` | swing highs/lows as liquidity; sweep = wick beyond (≥ min_exceed × ATR) + close back |
| `Structure/SupportResistance.mqh` | level clusters with touch counts + kind (support/resistance/both), min-touch filter |
| `Structure/DisplacementDetector.mqh` | normalized body/range displacement (ATR multiples) + close-location commitment |
| `Structure/StructureEngine.mqh` | aggregates over the Phase-2 CandleEngine; outputs bias + last event {type, direction, price, time} |

**Hypothesis:** objective structure events (swing/BOS/CHOCH/liquidity) on closed
bars are measurable and consistent across symbols after normalization — but on
synthetic indices they are **research inputs only** until proven OOS (they will
feed the research strategies, never the active band leg by default).

**Phase gate — MET:** compiles 0 errors / 0 warnings; Python mirror
`phase3_logic_check.py` green (70/70); Strategy Tester run on SYN75 green
(**70 passed, 0 failed** — Phase1 61 + Phase2 40 also re-verified green in the
same loop).  A lockstep bug was caught during the build: the mirror's internal
CHOCH/DISPLACEMENT event codes disagreed with `ENUM_STRUCTURE_EVENT` (2 vs 4)
— fixed before the MQL5 suite shipped.

**Real-corpus cross-validation (2026-08-11) — one engine change:**
`phase3_real_corpus_check.py` ran the StructureEngine mirror vs the real
Python SMC (`features/market_structure.py`) over every 100-bar window of the
real R_75 M5 corpus (2338 bars).  Bias agreement 71.7% (78.3% vs
`structural_direction`), displacement 98.7% — but the sweep axis was 13.4%
because `LiquidityEngine::DetectSweeps` scanned every historical swing level
(a sweep in 448/448 windows).  Reconciled: sweeps now target only the most
recent swing of each polarity (Python `recent_high/recent_low` semantics) —
sweep agreement 85.9% (recency-aligned), over-fire 448 → 113 windows, and the
bias axes lifted to 74.3% / 83.5% (stale sweeps were polluting last-event
selection).  Residual disagreements are documented semantics (event-vs-sequence
bias, momentum fallback, strict-vs-flat-top swings), not bugs.  Suite grew to
70 checks (2 new sweep tests).

**WINDOW-EDGE ALIGNMENT (2026-08-11):** the B2b residual (25 windows) was
100% window-edge recency — the MQL5 recent swing used the current bar as its
right guard while Python's `candles[:-1]` excludes it.  Fixed in mirror +
`SwingDetector.mqh` (`i + right < count - 1`): B2b is now **448/448 (100.0%)**,
recent-level agreement 74.1% → 99.1%, bias axes up (74.8% / 83.9%), B2a up to
85.9%.  All 70 unit checks stay green; the live tester gate improved 82.9 →
83.2%.

**LIVE-TESTER GATE (2026-08-11):** `Tests/StructureLiveTests.mq5` streams the
tester's own SYN75 M5 bars (up to 50k) through the real compiled
`CStructureEngine` and `PythonParity/StructureParity.mqh` (a faithful MQL5
port of Python `market_structure_features` + `structural_direction`, validated
== real Python by `mql5/structure_parity_check.py`, 279/279).  Verdict:
**41524 passed / 8377 failed = 83.2%** on 49,901 bars spanning ~6 months of
SYN75 history — matching the Python-side 83.9% and proving the compiled .mqh
reproduces the Python engine's direction at the same rate the mirror did.
`verify_all.ps1` discovery widened to `*Tests.mq5` so the suite runs with
Phases 1–4.

### Phase 4 — Strategies  ✅ COMPLETE (2026-08-11)

**Files built:**

| File | Contents | Default |
|---|---|---|
| `Strategies/BandGeometry.mqh` | ★ exact port of Python `band_geometry.py` (`ComputeLevels` = `band_levels`, `HorizonSigma` = σ_per_bar·√bars) + `vol_band.py` entry gates (`VolExtended`, `EntryDirection` z-fade, `Confidence`) + `BreakevenTrailBroker` trail (`UpdateMFE`/`TrailArmed`/`EffectiveStop`) | **ACTIVE** |
| `Strategies/TrendContinuation.mqh` | research skeleton, full H1–H10 hypothesis header | OFF |
| `Strategies/BreakoutStrategy.mqh` | research skeleton, full hypothesis header | OFF |
| `Strategies/MeanReversion.mqh` | research skeleton, full hypothesis header | OFF |
| `Strategies/LiquiditySweep.mqh` | research skeleton, full hypothesis header | OFF |
| `Strategies/PullbackStrategy.mqh` | research skeleton, full hypothesis header | OFF |
| `Strategies/StrategyEngine.mqh` | `MatrixAllows` regime matrix (end-state), `IsAllowed` (research hard-disabled today via `ResearchEnabled()`), `AllowedStrategies`, `Evaluate` dispatch + band `BandContext` wiring |

Each strategy returns `StrategyCandidate{strategy, decision, entry, stop,
target, setup_quality, confidence, reason_codes, required_regime}` — the struct
lives in `Core/Constants.mqh` (next to the enums) so every strategy and the
engine include it without include cycles.

**Phase gate — MET:** compiles 0 errors / 0 warnings; Python mirror
`phase4_logic_check.py` green (62/62) — and the mirror is itself validated
against the REAL Python `band_geometry.py` to 1e-12 on the shared cases, so
MQL5 reproduces Python `band_levels` within tolerance transitively.  Strategy
Tester run on SYN75 green (**65 passed, 0 failed** — Phase1 61 + Phase2 40 +
Phase3 70 re-verified green in the same loop).  Every research header contains
the full H1–H10 hypothesis block (hypothesis / why / variables / regime /
invalidation / expected RR / data / failure modes / OOS test / overfit
detection); research strategies return WAIT until validated OOS.  One test
bug caught during the gate: the MQL5 allowed-list assertions used the runtime
`AllowedStrategies` (which correctly returns band-only while research is
disabled) instead of the end-state `MatrixAllows` — fixed to match the mirror,
and the runtime band-only behavior is now explicitly locked by a test.

Note: the EGARCH forecaster stays in Python (the research lab) — the MQL5
module receives σ_per_bar / prev_sigma / the price EMA as inputs and
reproduces the exact level math, entry gates, and trail decisions.  Also
note `MathRound` (half-away) vs Python `round` (banker's): identical for the
supported holds (1h/2h/3h on 300s bars → 12/24/36 exact bars); non-integer
bar counts are out of the supported envelope.

### Phase 5 — Decision  ✅ COMPLETE (2026-08-11)

**Files built:**

| File | Contents |
|---|---|
| `Decision/ScoringEngine.mqh` | weighted composite of the plan's per-axis scores (setup / regime / structure / risk / execution, weights sum 1.0, configurable) → 0..1 (rendered 0-100); `RegimeAlignment` (exact 1.0 / family 0.7 / transition 0.4 / conflict 0.2), `RiskScore` (RR adequacy 0.7 + max-stop fit 0.3), `Evaluate` one-shot from a `StrategyCandidate` + context, `Explain` = the §10 journal format (`REGIME=… TREND_ALIGNMENT=… SETUP_QUALITY=… RISK/REWARD=… EXECUTION_QUALITY=…`) |
| `Decision/ConfidenceEngine.mqh` | faithful port of Python `decision_engine` confidence math: `Classify` = `_classify_signal_strength` (strong 0.52 w/ setup, 0.65 w/o; weak ≥ min; else WAIT), `DynamicMinConfidence` = Brier auto-raise (0.48→0.55, floor/ceil 0.25/0.10, ≥30 samples), `DriftPenalty` = ADWIN decay (0.02 over 500 steps), `BlendConfidence` (composite vs candidate confidence), `Gate` one-shot |
| `Decision/TradeQualityEngine.mqh` | R-multiple journal: `StartPosition`/`UpdatePosition`/`ClosePosition` track MAE/MFE in R, +1R/+2R/+3R reached, hold bars, exit reason (Python PaperBroker R math: `(exit−entry)/|entry−stop|`, fallback `entry·0.001`); `Statistics` per strategy → n / hit / avg R / avg planned RR / break-even floor; `BreakEvenFloor` = exact port of `stage3_gate.break_even_floor` (1/(1+rr)+margin, clamp [0.10, 0.60], fallback 0.50) |
| `Decision/DecisionEngine.mqh` | deferred — BUY/SELL/WAIT arbitration is covered by `ConfidenceEngine.Classify` (strong/weak/wait) + `ScoringEngine.Explain`; the full DecisionEngine wrapper is folded into Phase 6 (Risk/Execution consumption) so the Decision layer isn't built twice |

**Phase gate — MET:** compiles 0 errors / 0 warnings; Python mirror
`phase5_logic_check.py` green (**87/87**) — and the mirror is validated
against the REAL Python production code on the shared cases: `Classify` vs
`_classify_signal_strength`, `DynamicMinConfidence`/`DriftPenalty` vs
`_dynamic_min_confidence`/`_drift_confidence_penalty` (stub-constructed
DecisionEngine), and `BreakEvenFloor` vs `stage3_gate.break_even_floor` — so
MQL5 carries the Python confidence semantics transitively.  Strategy Tester
run on SYN75 green (**62 passed, 0 failed**, Phases 1–4 + the band backtest
re-verified green in the same loop).  One real deviation caught by the parity
gate: Python has NO negative-Brier guard (it simply clamps to the Brier
floor/ceil) — my first port added one and the gate caught it; the compiled
engine now matches Python exactly.  Two of my own test expectations werealso
wrong (composite arithmetic) and were corrected in both mirror and
suite.  The `OutcomeRecord`/`ScoreBreakdown` structs and
`ENUM_SIGNAL_STRENGTH` live in `Core/Constants.mqh` with the other shared
vocabulary.

**TradeQualityEngine real-corpus gate (2026-08-11) — FOUR-LEG complete:**
`mql5/tradequality_real_corpus_check.py` runs the real R_75 backtests
(band/momentum/fade, calibrated EGARCH, 165k ticks → M5) PLUS the **sniper
decision-engine leg via `BacktestEngine.run_ticks`** (default TraderConfig,
learn=True — the online ML model's calls AND its per-outcome learning are in
the path), replays every trade through the engine mirror, and asserts its
`Statistics()` against the Python journal — **350/350** (n / hit / avg R /
avg planned RR / break-even floor per strategy identical, per-trade return_r
+ MAE/MFE to 1e-9).  The sniper leg's capture replica is PROVEN identical to
the real `run_ticks` (fresh model: n / avg R / signals / rejected / model
version all match — `online-logistic-v1.178`, 178 trades).  The parity gate
caught a real leak: `features/assembler.py` EGARCH / session-filter /
fingerprint detectors are module-level caches, so a second run inherited the
first's warm-up state and diverged by 19 trades; `clear_assembler_caches()`
before each run makes both hermetic.  The R-multiple journal now coversthe full four-leg head-to-head (band 56 / momentum 62 / fade 8 / sniper 178)
against the production corpus, not just crafted cases.

**Walk-forward Stage-3 gate on the sniper leg (same run, 2026-08-11):** the
harness now tags each of the 178 `run_ticks` trades at entry with its
walk-forward gate state — only outcomes resolved STRICTLY before that entry
are visible (`closed_at < opened_at`, no lookahead), floor = per-geometry
break-even `1/(1+avg planned RR)+margin` over the running average RR of the
resolved trades, exactly the band backtest's `BandBackTests.mq5` rule and the
Python `simulate_gate_walk_forward`.  **Verdict: mean floor at entry 39.5%
(the 1.90-RR sniper geometry), achieved hit 41.6% BEATS it — KEPT 178 (167
proven + 11 still_learning), SUPPRESSED 0** — the sniper ML leg is the ONLY
leg that clears its own break-even floor walk-forward (band 25.0% floor vs
5.4% hit, momentum 38.3% vs 29.0%, fade 60.0% vs 50.0% all fail).  The gate
self-consistency checks (states account for all trades, suppressed below
floor at entry, proven ≥ floor with ≥ min_samples, still_learning only below
min_samples) are hard PASS — **354/354** total.

**Sniper geometry re-tuned toward MFE (same gate, 2026-08-11):** the
captured sniper leg's planned RR is 1.90 vs median MFE 0.76R (mean 0.93R).
The 2-D replay sweep over the captured intrabar paths found exactly one cell
where hit ≥ its own floor: target 0.60R, stop 1R (RR 0.60, hit 60.1%,
+0.006R — clearing only because `BreakEvenFloor` clamps at 60%; raw
break-even is 67.5%).  The literal toward-MFE target 0.76R (RR 0.76) does
NOT clear (53.4% vs 60% floor, −0.010R); every RR ≥ 1.2 cell is negative.
Wired end-to-end through the real `run_ticks` path (research override:
take_profit_rr=0.60, min_reward_risk=0, min_primary_reward_risk=0): **n=444,
hit 62.6%, avgR +0.027R gross, floor 60.0% — walk-forward gate KEEPS it
(442 kept / 2 suppressed; online ML learning improves on the replay, 444 vs
178 trades)** — but **444/444 trades have planned RR < 1.2, so both the
RiskEngine and profile minimum-RR gates veto the entire geometry in
production**, and +0.027R gross ≈ −0.023R net at 0.05R cost.  Honest read:
the MFE-vs-target mismatch is confirmed as the leg's core geometry problem;
re-tuning toward the MFE zone only reaches the floor with a
production-illegal sub-1.2-RR geometry at statistically zero net edge — the
sniper leg stays untradeable, and the fix must come from the entry/momentum
side (better entries), not the target/stop side alone.  **360/360** checks
pass (6 new: retuned run executed, all-retuned-RR-below-production-min,
+ the 4 gate self-consistency checks).

**Sniper time-based exit at the hold horizon (same gate, 2026-08-11):** the
exit-quality table's TIME exits average +0.394R — positive drift that never
reaches the fixed 1.9R target.  The harness now carries a
`TimeExitCapturePaperBroker` (production entry path untouched: 1R stop,
RiskEngine min_reward_risk 1.2, planned RR 1.9 for gating; only the
take-profit branch is removed — exit at the 1R stop or at
`signal.horizon_sec` at close).  End-to-end re-run of the real `run_ticks`
path, both exits: **baseline n=178 hit 41.6% −0.007R vs time-exit n=229 hit
45.9% +0.059R gross — hit beats the 39.5% floor AND the realized-payout
break-even (42.8%, avg win +1.111R / avg loss −0.833R); walk-forward gate
KEPT 229 / SUPPRESSED 0.**  The online model learns from the new exits, so
the run emits more trades (229 vs 178; risk-rejected 2079 vs 2130).  Honest
read: gross-positive but ≈ +0.009R net at 0.05R cost (≈ −0.041R at 0.10R)
— statistically zero after costs; the time exit is research-only and
confirms the edge sits in the first hours after entry, not at the far
target.  **360/360** checks pass (unchanged; the time-exit path is verified
by the probe end-to-end, not by new harness assertions).

**GARCH feature freeze found & fixed (2026-08-11):** the entry-filter sweep
proved `garch_z_score` was exactly 0.00 on all 178 captured trades.  Root
cause: the assembler guarded the GARCH update with
`garch.state.observations > 0` — the FIRST update was never allowed, so
observations froze at 0 and `get_forecast()` returned z=0.0 forever in
every process (caches are cleared per run).  The guard is removed (`update()`
handles warm-up internally); `garch_z_score` / `garch_vol_ratio` are live
features again (entry |z| now spans 0.00–4.08, median 0.75), and the sniper
capture shifts 178 → 185 trades (the ML model finally sees the feature).
Regression tests in `tests/test_assembler.py` (warm-up + cache-reset)
lock it.  Note: removing the guard also activates the periodic arch refit
(obs % 100 == 0) — its DataScaleWarning is now suppressed inside
`_try_fit_arch` (optional diagnostics; the online EWMA path is primary).

**Entry-filter sweep on the captured sniper set (2026-08-11):** with the
z feature live, the sweep replays each captured trade's intrabar path
(exact PaperBroker stop-first semantics) under production-legal targets:

- **z-depth: deep-extension entries are WORSE** — |garch_z| ≥ 1.0 → medMFE
  0.62R, exp −0.19R; the sniper's edge is NOT in stretched entries.
- **vol-z at entry is the discriminator** — |range_z_50| ≥ 1.5 → medMFE
  0.59R, exp −0.35R (statistically extreme entry candles underperform).
- **session hours carry the edge** — UTC 12-24h entries: medMFE 0.96–1.06R;
  the top-4 hour cluster [0-3] is the worst (medMFE 0.62R).
- **drift alignment: null** — ADWIN over the M5 return series fired 0 times
  in 2,338 bars (9.5 days), so no drift filter can discriminate on this
  corpus (the model's own error-based detector is a separate axis).
- **THE ANSWER: two cells clear the 1.0R median-MFE bar with
  production-legal targets** — `UTC 12-24h & |range_z|<1.0` (n=34, medMFE
  +1.10R, meanMFE +1.10R: hit 58.8% at RR 1.2 AND RR 1.5 vs floors 50%/45%,
  exp +0.246R/+0.267R) and `UTC 18-24h & |range_z|<1.5` (n=24, medMFE
  +1.10R, meanMFE +1.19R: hit 58.3%, exp +0.226R/+0.364R).  RR 1.5 with the
  session+vol filter is the strongest cell (+0.267R / +0.364R).  So the
  target can STAY production-legal (RR ≥ 1.2) — no illegal sub-1.2-RR
  geometry needed — provided entries are gated to UTC 12-24h with
  non-extreme entry-candle vol.  Honest caveat: n=34/24 are small (one
  month-ish of trades) and the vol-z + hour interaction needs the next
  corpus growth to confirm before production.

**Time-exit × shallow-fade entry filter, end-to-end (same corpus,
2026-08-11):** the two proven levers combined IN THE RUN LOOP — the
entry filter (UTC 12-24h & |range_z|<1.0, or UTC 18-24h & |range_z|<1.5)
gates signals after the risk engine, so the online ML model never learns
from filtered trades, exactly like production; the time-exit broker exits
at the hold horizon.  The harness now carries the `entry_filter` hook
(permanent, default None) for exactly this.  Three real `run_ticks`
passes:

| run | n | hit | gross | net@0.05 | net@0.10 | floor | payout BE |
|---|---|---|---|---|---|---|---|
| time-exit baseline | 208 | 41.8% | −0.018R | −0.068R | −0.118R | 39.5% ✓ | ✗ |
| **+ UTC12-24h/rz<1.0** | **149** | **50.3%** | **+0.142R** | **+0.092R** | **+0.042R** | ✓ | **✓** |
| **+ UTC18-24h/rz<1.5** | **77** | **51.9%** | **+0.191R** | **+0.141R** | **+0.091R** | ✓ | **✓** |

**Net expectancy survives realistic costs — the first time any cell in
the research program has cleared 0.05–0.10 R/trade.**  UTC18-24h/rz<1.5
is +0.141R net@0.05; the more robust UTC12-24h/rz<1.0 variant (149
vs 77 trades, ~15/day) is +0.092R net@0.05 and still +0.042R at 0.10
cost.  Both beat the 39.5% Stage-3 floor AND the realized-payout
break-even, and the walk-forward gate would trade them (KEPT 148/149 at
50.0% and KEPT 77/77 at 51.9%).  Caveats: single 9.5-day window (no
fresh out-of-sample yet — the differential +0.160R / +0.209R vs baseline
is the robust read, not the absolute level), and the time exit is a
research-only policy (no production ground truth).  The hour filter uses
the true entry-bar hour from `snapshot.epoch` (production-feasible; the
`session_hour` feature is wall-clock at build time).

**Session-vol gate × depth cap, with realized DRAWDOWN (10.5-day corpus,
2026-08-11):** the band's drawdown-reducing depth cap layered on the
sniper's session-vol gate — the cap analog is `|garch_z_score| ≤ 1.5`
(entry-bar return vs EGARCH forecast sigma, the same edge-depth axis the
band's |z|/z_entry measures; the entry-filter sweep showed |garch_z| ≥
1.0 entries carry medMFE 0.62R vs 0.76R overall).  Four real `run_ticks`
passes, all time-exit, in-loop filtering (model learns only from taken
outcomes); drawdown is the realized cumulative-R curve (close-ordered):

| run | n | hit | gross | net@0.05 | net@0.10 | maxDD | worst streak |
|---|---|---|---|---|---|---|---|
| time-exit baseline | 208 | 41.8% | −0.018R | −0.068R | −0.118R | 18.28R | 8 |
| + sv 12-24h/rz<1.0 | 149 | 50.3% | +0.142R | +0.092R | +0.042R | 5.71R | 5 |
| **+ svcap …/gz≤1.5** | **146** | **52.1%** | **+0.161R** | **+0.111R** | **+0.061R** | 5.85R | 5 |
| + evcap 18-24h/rz<1.5/gz≤1.5 | 77 | 50.6% | +0.186R | +0.136R | +0.086R | 6.80R | 4 |

**The depth cap adds a small expectancy lift on top of the session-vol
gate** (svcap gross +0.161R vs sv +0.142R; hit 52.1% vs 50.3% — the ~3
extra filtered trades were losers), **but the drawdown win comes almost
entirely from the session-vol gate itself**: baseline maxDD 18.28R →
5.71R with the gate (3.2× cut, worst streak 8 → 5), and the depth cap
changes drawdown essentially not at all (5.85R vs 5.71R — the band's
cap-vs-drawdown relationship did not transfer to the sniper side).  The
combined svcap cell is the best balanced result to date: **146 trades
(~14/day), +0.111R net@0.05, still +0.061R at 0.10 cost**, KEPT 146/146
by the walk-forward gate, payout BE 43.3% vs 52.1% hit.  Honest
caveats: this is the full available Python corpus (~10.5 days — the
6-month window exists only as M5 bars in the MT5 terminal and the sniper
ML path is not ported there, so the 6-month combined measurement requires
that port), and the time-exit policy remains research-only.

**Why the deep-extension fades are the drawdown machines (6-month tester,
RR 1.2, 2026-08-11):** `BandBackTests` now records per trade its exit
reason, vol regime at entry (prev_sigma/sigma_ema) and the deep-vs-shallow
profile + vol-regime split:

| bucket | n | hit | exp | sumR | avg hold | avg MFE | vol@entry | stop/target/time |
|---|---|---|---|---|---|---|---|---|
| shallow ≤1.5 | 196 | 41.3% | −0.091R | −17.8R | 2.6b | +1.43R | 1.13 | 59/41/0% |
| mid 1.5-2.5 | 417 | 40.8% | −0.103R | −43.0R | 1.2b | +1.40R | 1.13 | 59/41/0% |
| deep >2.5 | 1,183 | 40.1% | −0.119R | **−140.2R** | 2.9b | +1.45R | 1.13 | 60/40/0% |

**The deep fades are NOT different animals — they are the drawdown
machines purely by VOLUME.**  Identical hit (40.1 vs 41.3%), identical
MFE (+1.45 vs +1.43R), identical vol regime at entry (1.13), identical
exit mix (~59% stop / ~41% target): the profile is flat across depth.  The
deep bucket is 66% of the trades (1,183/1,796) at marginally worse
per-trade expectancy (−0.119R), so it carries 71% of the −202R total
bleed (−140.2R sumR) — and the earlier depth-cap "6× drawdown cut" was
MECHANICAL count-scaling (404/198 trades × the same negative expectancy),
not a tail-risk fix.  The vol-regime split adds nothing: vol>1.25 entries
(n=12) were even positive (+0.10R) — noise.  **And there is no time
dimension to fix: 0% of trades reach the 1h expiry (all resolve by stop
or target within ~1-3 M5 bars), so a time-based exit cannot cut the
tail.**  Tested anyway: a dead-trade time exit (exit at close when MFE <
0.4R after N bars) never fires at N=4 (no trade is "dead" at bar 4), and
at the pathological N=1 it makes things WORSE (exp −0.121R, maxDD 227.8R
vs 204.8R — it cuts eventual recoverers and adds negative-expectancy
trade count).  Conclusion: the tail is entry-side — hit rate toward the
50.5% floor (the sniper combo's direction), not exits.

**Depth-cap grid on the RR-3.0 DEFAULT geometry (6-month tester,
2026-08-11):** confirms the cap HURTS at RR 3.0 and CORRECTS the old
"deep beats shallow" claim:

| cap | n | hit | exp gross | exp@0.05 | maxDD |
|---|---|---|---|---|---|
| OFF (default) | 1,503 | **25.9%** | **+0.039R** | −0.011R | 81.0R |
| 2.0 | 378 | 23.0% | −0.079R | −0.129R | 48.0R |
| 1.5 | 181 | 23.8% | −0.050R | −0.100R | 36.0R |

**The cap destroys the RR-3.0 geometry's ONLY positive-gross cell
(+0.039R → −0.079R/−0.050R, hit 25.9% → 23.0-23.8%)** — the direction
the docs predicted, but the SUPPORTING claim was wrong: the old
"STRONG 25.8% vs WEAK 17.1% (deep beats shallow)" rested on a 60-trade
WEAK bucket that flips on re-run (now 28.3%, +0.133R).  The STRONG 25.8%
reproduces stably; the depth-bucket PROFILE (large n) shows the opposite
of the old claim at RR 3.0: shallow ≤1.5 → hit 28.0% exp **+0.119R**
sumR **+20.0R**, mid 1.5-2.5 → 28.0% +0.120R +40.0R, deep >2.5 → 24.9%
−0.002R −2.0R — the shallow and mid fades are the positive buckets, the
deep ones are flat.  (Caveat: with the seeded per-signal geometry sweep,
blocking entries reshuffles the RNG, so the capped runs are NOT pure
subsets of the baseline — the +0.12R implied by the profile does not
carry into the capped runs; the measured cap cells are what they are:
negative.)  Drawdown still drops with the cap (81 → 36-48R) — the same
mechanical count-scaling as RR 1.2.  The cap stays default OFF; at both
geometries it only trades expectancy for drawdown.

**Edge-depth cap on the band entries (6-month tester, RR 1.2 geometry,
2026-08-11):** hypothesis — the deep-extension STRONG bucket drags hit
from 45.3% (shallow) to 39.2% (all), so blocking depth > ~2 should leave a
shallow-only subset that clears the 50.5% floor.  Added `InpMaxEdgeDepth`
(block |z|/z_entry > cap, 0 = OFF) + a per-cap depth-split table + a
`depth_fail` attrition counter, then ran the RR-1.2 6-month grid:

| cap | n | hit | exp gross | floor | maxDD |
|---|---|---|---|---|---|
| OFF (baseline) | 1,796 | 40.4% | −0.112R | 50.5% | 204.8R |
| 2.0 | 198 | 40.4% | −0.111R | 50.5% | 32.4R |
| 1.5 | 404 | **41.1%** | **−0.096R** | 50.5% | **42.2R** |
| ≤1.25 slice (inside 1.5) | 86 | **46.5%** | **+0.023R** | 50.5% | — |

**The hypothesis does NOT hold — but the cap is a real RISK lever.**
(1) Blocking depth > 2.0 leaves 198 trades with hit 40.4% — IDENTICAL to
the uncapped set, so the deep trades are not dragging hit down at the
entry level; the earlier "45.3% vs 39.2%" was a 64-trade WEAK-bucket
sample that flips run-to-run (37.9% / 41.7% / 45.9% across the three
runs).  (2) Every depth cell misses the 50.5% floor — the tightest slice
(depth ≤ 1.25, n=86) is the best RR-1.2 cell ever (46.5% hit, +0.023R
gross ≈ −0.03R net at 0.05 cost) but still 4 points short.  (3) The cap's
REAL effect is tail risk: max drawdown collapses 204.8R → 42.2R (cap 1.5)
→ 32.4R (cap 2.0) — a 6× cut with expectancy roughly flat — because the
deep-extension fades are the drawdown machines.  Cap stays default OFF
(no hit-rate win); the drawdown benefit is available via `-Inputs
InpMaxEdgeDepth=1.5` and worth revisiting once the entry side improves.

**Trail sweep at the derived 1.2-RR target (6-month tester, 2026-08-11):**
can a trail_frac be found that stops RACING the target (arm near it,
0.8×1.2 = 0.96R) while still scratching some −1R losers?  Ran
InpTrailFrac 0.0–0.8 at RR 1.2 (arm point = frac × 1.2R):

| frac | arm | n | hit | exp gross | avg loss | maxDD |
|---|---|---|---|---|---|---|
| 0.0 | off | 1,796 | **40.4%** | **−0.112R** | −1.000R | 204.8R |
| 0.2 | 0.24R | 1,902 | 2.1% | −0.109R | −0.137R | 208.2R |
| 0.4 | 0.48R | 1,900 | 2.4% | −0.199R | −0.234R | 380.0R |
| 0.5 | 0.60R | 1,885 | 2.5% | −0.260R | −0.297R | 489.8R |
| 0.6 | 0.72R | 1,861 | 3.0% | −0.292R | −0.337R | 543.2R |
| 0.7 | 0.84R | 1,831 | 2.8% | −0.347R | −0.392R | 634.8R |
| 0.8 | 0.96R | 1,832 | 3.8% | −0.367R | −0.429R | 672.0R |

**There is NO trail_frac where the trail stops racing the target — even
at 0.8 (arming 0.96R, 80% of the way there) the trail still kills the hit
rate (3.8% vs 40.4%) and expectancy degrades MONOTONICALLY with every
increase.**  The breakeven conversion is real (avg loss −1.0 → −0.14R at
frac 0.2) but it buys the entire winner side: a position that arms the
trail and would reach 1.2R almost always dips back through entry first on
M5 wicks, and the same-candle stop-first exit scratches it at 0R.  Max
DD also WORSENS with the trail (204.8 → 672R) — the steady −0.3R bleed of
1830 near-scratch trades compounds instead of the clean −1R losers.
Trail stays OFF (0.0) — the current default is confirmed correct.  The
one structural escape hatch: the tester's trail exit has NO closed-candle
grace — the Python system already locks stops to closed candles (spread/
wick jitter can't stop a valid plan), so the natural next experiment is
the same closed-candle rule on the trail's breakeven exit before judging
the trail concept dead.

**Live decision gate (2026-08-11):** `StructureLiveTests` now runs
`CConfidenceEngine.Gate` on every structure bar inside the tester (setup
quality = structure-event density, formal setup = bias-aligned BOS/CHOCH,
composite = `CScoringEngine`, verdict logged per bar).  On 49,901 SYN75 M5
bars the gate's directional verdicts agree with Python `structural_direction`
on **89.9%** of committed bars (strong 39,467 / weak 6,705 / wait 3,729) —
above the raw 83.2% bias agreement — and the suite carries a second PASS
threshold (gate ≥ 65%).  Same uniformly-high-confidence finding as the band
leg: all 3,729 WAITs are the engine-neutral windows, none of the 46,172
committed directions fell below min-confidence.

**Empirical floor gate in the band backtest (2026-08-11):**
`BandBackTests` now journals every band trade through the real
`CTradeQualityEngine` (`StartPosition`/`UpdatePosition`/`ClosePosition` with
the true exit reason) and, at each entry, applies the walk-forward Stage-3
gate from the journal's resolved outcomes only (no lookahead): floor =
`BreakEvenFloor(avg planned RR, 0.05)` — the exact
`stage3_gate.break_even_floor` — with `min_samples=10`, splitting every trade
into still_learning / proven / suppressed.  Re-run on the 50k-bar SYN75
window (all 8 suites PASS): **KEPT n=10 (+0.400R, warm-up only), SUPPRESSED
n=3821 (−0.349R), mean floor 25.0% vs achieved hit 4.4% — NOT floor-beatable;
the gate stands aside.**  Same conclusion as the Python `backtest-gate` on
R_75: the 4.0-RR band geometry never clears its own break-even, so the
empirical gate correctly refuses it until a re-tuned geometry proves it can.

**Discriminating confidence buckets (same run, 2026-08-11):** the band's
confidence buckets were structurally uniform — every gated signal carries
`Confidence(z) ∈ [0.88, 0.90]` because the z gate guarantees `|z| ≥ z_entry`
(so `|z|/(3·z_entry) ≥ 1/3`) — and the composite's regime+risk constants keep
blended confidence ≥ 0.52, so all 3,831 trades landed STRONG.  The test now
sweeps the band's geometry per signal (seeded `MathSrand(InpGeomSeed)`,
z_entry 0.7–1.6, stop 0.15–0.35σ_h, target 0.50–1.20σ_h) and scores setup
quality by EDGE DEPTH (`|z|/z_entry`: marginal fade ~0.2 → deep extension
~1.0), spreading the verdicts.  Tester re-run (all 8 suites PASS):
**STRONG n=2795 (−0.343R, hit 4.6%) vs WEAK n=311 (−0.236R, hit 8.0%) with
WAIT n=197 blocked — WEAK outperforms STRONG (−0.108R lift).**  The honest
answer to "do higher-confidence trades outperform?" is NO on this leg: the
buckets discriminate cleanly (WEAK avg depth 1.18 vs STRONG 2.62) but deep
z-fades lose MORE than shallow ones — the confidence axis isnot predictive of outcomes, and both buckets are negative.  The leg stays untradeable; the
z-depth fade edge itself needs re-testing.

**Calibrated fixed-EGARCH run (2026-08-11):** `BandBackTests` now defaults to
the calibrated R_75 EGARCH as FIXED inputs (ω=-1.115, α=0.077, γ=0.011,
β=0.918 — `InpGarchOmega/…/Beta`, the production estimator recursion) instead
of the degenerate online-SGD state.  Two gate changes were needed for a
measurable sample on the smooth calibrated σ: the vol gate re-based 1.3 → 1.10
(1.3× crosses 1 bar in 50k; ratio_max 1.35; at 1.10 it crosses 5.8% of bars),
and the ADWIN drift gate fixed to measure DIRECTION (signed log r) instead of
|log r| — the |log r| detector fired on vol bursts, the SAME bars the vol-
extension gate opens on, vetoing the band's entire firing base (measured:
2,899 vol crossings → 1 drift-clear → 1 entry).  Drift is now a switchable
input (`InpDriftGate`, OFF by default).

**Harness bug found during the re-run:** the tester silently loads the saved
input set `MQL5\Profiles\Tester\<expert>.set` OVER the freshly compiled
defaults — a stale `BandBackTests.set` pinned `InpVolGateRatio=1.30` (and the
old drift gate) regardless of the source, which is why the first calibrated
runs all reported 1 trade.  `verify_all.ps1` now purges the suite's `.set`
before every tester run (a rebuilt .ex5 always runs its own defaults).

Re-run on the 50k-bar SYN75 window (all 8 suites PASS): **trades=2059,
hit 1.5%, −0.396R gross; STRONG n=1949 (−0.393R) vs WEAK n=75 (−0.440R),
+0.047R lift — STRONG outperforms here (flip vs the SGD-era sweep); floor
gate still stands aside (mean floor 25.8% vs achieved 1.5%).**  Honest read:
the calibrated estimator confirms the Python `backtest-gate` verdict INSIDE
the tester — the 4.0-RR fade geometry is not floor-beatable on the production
σ — and the earlier SGD-driven positive cells were artifacts of the
degenerate estimator, not the market.

**MFE-derived target (§50, same 50k-bar window):** the R-journal's band MFE
(median 1.18R vs the 4.0R target — target ~3.4× median travel) drove a
replay of the captured paths under candidate target multipliers (stop 1R,
exact `_maybe_close` semantics).  Two findings: (1) the 0.3×-RR breakeven
trail is the binding constraint — it arms at 0.36R at the derived RR and
races the target, so hit stays ~2-5% at ANY target (1.8% with trail vs
51.8% without at k=1.2R); (2) without the trail the MFE zone clears its own
floor (k=1.2R: hit 51.8% vs 50.5% floor, +0.125R).  Geometry updated:
`InpTargetSigmaMult` 0.80 → 0.24σ (= 1.2 × stop → RR 1.2), `InpMinTargetRR`
2.0 → 1.2, `InpTrailFrac` 0.3 → 0.0, sweep couples `target = 1.2 × stop`.

Re-run (all 8 suites PASS): **trades=1818, hit 39.2%, −0.138R gross (was
2059 / 1.5% / −0.396R); avg win +1.200R, avg loss −1.000R, PF 0.77; STRONG
n=1680 hit 38.8% −0.148R vs WEAK n=64 hit 45.3% −0.003R (WEAK outperforms —
shallow fades beat deep extensions again); floor gate: mean floor at entry
50.5% vs achieved 39.2% — NOT floor-beatable, gate stands aside (KEPT 10 /
SUPPRESSED 1808).**  Honest read: the reachable target multiplied hit 26×
and cut the loss 2.9×, but entry quality still misses the 50.5% break-even
by 11 points, concentrated in the deep-extension STRONG bucket — the entry
side (not the target) is now the remaining lever.

**Verifier hardening from this run:** the MT5 tester AUTO-SAVES the
parameters it ran with to `Profiles\Tester\<expert>.set` at run end, so a
stale `.set` (pinning e.g. `InpMinTargetRR=2.0` while the rebuilt geometry
emits RR 1.2) silently re-blocked the re-run — the pre-run purge alone was
not enough.  `verify_all.ps1` now ALSO purges the suite's `.set` AFTER each
tester run; diagnostics split the entry attrition (dir0 / lv_fail / conf) so
a gate regression is visible in one line instead of "entries=0".

**Stop/target/z-entry re-tune sweep (§50, same 6-month window) — and the
purge bug it exposed:** a new `-Inputs "k=v;k=v"` verifier parameter writes
a UTF-16 `MQL5\Profiles\Tester\<expert>.set` (post-purge) and points
`ExpertParameters=` at it, so a full geometry grid runs without touching the
suite source.  The grid (z fixed per cell, trail OFF): RR 1.0 hit 38.5% vs
floor 55% (−16.5, −0.230R); RR 1.2 39.2% vs 50.5% (−11.3, −0.138R); RR 2.0
32.5% vs 38.3% (−5.8, −0.026R); RR 2.5 28.9% vs 33.6% (−4.7, +0.013R); RR
3.0 26.0% vs 30.0% (−4.0, **+0.042R gross — the only positive cell**); RR
3.5 23.1% vs 27.2% (−4.1).  The hit-vs-floor gap narrows monotonically to a
~−4-point minimum at RR 3.0-3.5 (then the MFE cliff), so **the committed
default is now the sweep winner**: `InpTargetSigmaMult` 0.60σ (= 3.0 ×
stop), `InpMinTargetRR` 3.0, `InpDerivedTargetRR` 3.0, trail OFF — default
run reproduces **trades=1558, hit 25.7%, floor 30.0% (gap −4.3), expectancy
+0.026R gross / −0.024R @0.05 cost, PF 1.04** — the band's closest
floor-gate result ever, but the gate still stands aside.  At RR ≥ 2.5 the
bucket pattern flips (STRONG deep beats WEAK — the farther target needs the
deep entry).  The sweep also exposed a real verifier bug: `@($name + ".set",
$name.Replace(...))` parses as ONE space-joined string in PowerShell, so
Test-Path always failed and the `.set` purge silently never ran (every run
inherited the tester's auto-saved set — the reason the RR-1.2 → 3.0 default
kept producing stale numbers).  Fixed by parenthesizing each array element;
pre-run + post-run purges now both work ("purged stale input set" prints).

### Phase 6 — Risk  ✅ COMPLETE (2026-08-11)

**Files built:**

| File | Contents |
|---|---|
| `Risk/PositionSizer.mqh` | two layers: `Stake` = exact Python RiskEngine stake math (risk_budget × (0.55+0.70·quality), floor 0.35, × empirical scale, cap 1.25× budget; paper-only scale → 0) and `Lots` = the plan's MT5 conversion (lots = stake / (|entry−stop| · tick_value/tick_size)), floored to the symbol's volume step, clamped [vol_min, vol_max] |
| `Risk/RiskLimits.mqh` | the Max* table (Constants defaults) + account state: equity/peak/day-start, daily/hourly trade counters, open positions, consecutive-loss streak (Python −0.10R scratch threshold), EMERGENCY_STOP; `AnyHardLimitBreached()` = TRADING DISABLED; `SyncWindow` reports the day roll so the engine mirrors it |
| `Risk/DrawdownProtection.mqh` | Python-parity fractions (daily loss from day-start, intraday peak-to-trough, all-time equity DD) + `Halted()` returning the FIRST breached limit name |
| `Risk/ExposureManager.mqh` | account-mode aware (`ACCOUNT_MARGIN_MODE` at runtime, `SetMode` override for tests): netting forbids a second position of EITHER direction, hedging allows one per direction; exposure fraction vs the max-exposure % |
| `Risk/RiskEngine.mqh` | final authority consuming the Phase-5 `StrategyCandidate`: Python-parity veto gates (max open, consecutive-loss breaker, daily loss, confidence < min, reward/risk < min, extreme volatility z, exposure, EMERGENCY_STOP) with named reasons, then `Stake`+`Lots` sizing into `RiskVerdict{approved, lots, stake, reasons}` |

**Phase gate — MET:** compiles 0 errors / 0 warnings; Python mirror
`phase6_logic_check.py` green (**45/45**) — validated against the REAL Python
`RiskEngine`: the stake formula on 6 scenarios (0.005 cent-rounding tolerance),
each veto gate's reason, the −0.10R streak threshold, daily_drawdown_fraction,
and register_open counting.  Strategy Tester run on SYN75 green (**45 passed, 0
failed**, Phases 1–5 + the band backtest + structure live re-verified green in
the same loop).  Three MQL5-side issues caught and fixed during the gate: MQL5
cannot return object references (the composed sub-engines are now public
members — `engine.limits` / `engine.dd` / `engine.exposure`); the reason trail
hid the specific breached limit behind a generic message (now always named);
and `CDrawdownProtection` day-window initialization is the caller's
responsibility (`SyncState` does it on first sync / day roll — direct users
call `OnNewSessionDay()`).  The Phase-6 gate cases — sizing math, hard-limit
breach → disabled, netting forbids the second position, EMERGENCY_STOP blocks
everything — are all locked by tests.

**Decision-layer veto wired in (2026-08-11):** the Phase-5 verdict now feeds
`RiskEngine.Evaluate` ahead of the sizer.  `StrategyCandidate` carries
`signal_strength` (the `CConfidenceEngine.Gate` output), and two MQL5-side
gates enforce it: a WEAK verdict is vetoed before sizing when the gate is on
(`SetVetoWeakSignals`, default ON — only STRONG signals trade), and a WAIT
verdict is vetoed unconditionally (a WAIT candidate must never be sized, even
if its raw confidence clears the minimum — a hole the old gate would have let
through).  `Phase6Tests` grew 5 checks (45 total): WEAK vetoed with the named
reason, WAIT never sized, STRONG approved with the gate on, WEAK passing when
the gate is off (research mode), WAIT veto persisting regardless — all green
in the tester on SYN75.

### Phase 7 — Execution

**Files to create:**

| File | Contents |
|---|---|
| `Execution/OrderManager.mqh` | CTrade wrapper; request → verify fill → record |
| `Execution/StopManager.mqh` | ATR/structure/vol-adjusted SL with min-distance checks (stops level) |
| `Execution/TakeProfitManager.mqh` | fixed-R / structure / ATR / liquidity targets |
| `Execution/PositionManager.mqh` | BE, trailing, partial close, time/volatility/structure/opposite-signal exits; every modification has a reason code |
| `Execution/ExecutionMonitor.mqh` | rejection/requote/margin/connection/symbol-restriction handling; every attempt logged |
| `Execution/ExecutionEngine.mqh` | orchestrates the five; never assumes success — verifies position/deal |

**Phase gate:** compiles; simulated order tests (mock retcodes) for rejection,
invalid stops, volume errors, margin; verification path tested.

### Phase 8 — Journal + Analytics

**Files to create:**

| File | Contents |
|---|---|
| `Journal/TradeJournal.mqh` | CSV append per §33 schema (timestamp, symbol, strategy, regime, direction, entry, SL, TP, volume, risk, confidence, score, exit, PnL, R, MAE, MFE, exit_reason) |
| `Journal/DecisionLogger.mqh` | every decision + reason + features |
| `Journal/PerformanceLogger.mqh` | per-strategy/regime/direction/timeframe/hour/day/vol-state/confidence-bucket aggregates |
| `Analytics/PerformanceAnalytics.mqh` | net/gross PF, expectancy, avg R, win rate, DD, recovery factor, streaks, avg duration, MAE/MFE |
| `Analytics/ExpectancyEngine.mqh` | R-based expectancy + per-bucket |
| `Analytics/RegimeAnalytics.mqh` | performance by regime |

**Phase gate:** compiles; CSV schema verified (round-trip a record); aggregates
match a hand-computed example.

### Phase 9 — UI

**Files to create:**

| File | Contents |
|---|---|
| `UI/Panel.mqh` | dashboard panel primitives (the §34 layout) |
| `UI/Dashboard.mqh` | REGIME / TREND / VOL / STRATEGY / SIGNAL / CONFIDENCE / RISK / POSITION / DAILY P/L / DD / TRADE COUNT |
| `UI/VisualSignals.mqh` | chart objects: entries, exits, SL/TP, swings, liquidity, regime change markers |

**Phase gate:** compiles; dashboard renders in a visual tester run.

### Phase 10 — Integration + Strategy Tester

- `MitemshubAI.mq5` wires the full pipeline (OnTick → state → decide → risk →
  execute → journal → dashboard).
- Strategy Tester runs: R_75 & R_100, 60s/300s execution TF, "Every tick based
  on real ticks", walk-forward windows matching the Python corpus split.
- **Cross-validation gate:** MQL5 band-leg expectancy sign and R/trade must agree
  with Python `backtest-vol` on the same window/params; divergence = bug.

### Phase 11 — Robustness

- Neighboring-parameter sweeps on the CSV (ATR period, z_entry, σ multipliers).
- Monte Carlo trade-sequence randomization on the CSV: drawdown distribution,
  max losing streak, equity variability, risk of ruin.
- 100%-win-rate and "too good" results are treated as data errors, not wins.
- Only robust parameter regions are promoted.

### Phase 12 — Forward / demo / live

- Forward test on a demo account for a documented period.
- Live requires: `InpLiveTradingEnabled=true` AND a separate explicit
  confirmation input AND demo-first evidence. No path from backtest straight to
  live.

---

## 3. Testing strategy summary

| Layer | Method |
|---|---|
| Symbol independence | SymbolAdapter unit tests on V75, V100, and a synthetic test symbol |
| Math correctness | hand-computed ATR/z/volume/RR cases |
| Regime/structure | crafted series with known labels |
| Engine integration | tester runs with expected trade counts/order |
| Cross-validation | MQL5 CSV vs Python backtest on identical windows/params |
| Robustness | neighboring params + Monte Carlo on CSV |
| Anti-overfit | train/validate/OOS split; never tune on OOS |

---

## 4. Files to create / modify summary

**Create (~32 MQL5 files):** full tree in §2 of ARCHITECTURE_PLAN.md.
**Modify:** `mql5/SynthCallExecutor.mq5` (refactor shared primitives into
`Core/`; keep thin-executor compatibility), `mql5/README.md` (link).
**Create (docs):** this plan, `ARCHITECTURE_PLAN.md`, per-strategy hypothesis
headers.

---

## 5. Risks & mitigations (recap)

- **Broker tick history availability** → test at Phase 10; fall back documented.
- **Tester file-I/O sandbox** → guard with `MQLInfoInteger(MQL_OPTIMIZATION/FORWARD)`.
- **Hurst/ADX approximations** → fused regime, disagreement lowers confidence.
- **Port divergence from Python** → cross-validation gate at Phase 10.
- **Strategy overfit** → OOS-only promotion, robustness sweeps, Monte Carlo.

---

*End of IMPLEMENTATION_PLAN.md — awaiting approval before Phase 1.*

---

## Appendix — running the unit tests headlessly in the Strategy Tester

Each `Tests/Phase*Tests.mq5` is an EA whose `OnInit` runs the suite and prints
PASS/FAIL (returning `INIT_FAILED` on any failure). Verified working recipe
(2026-08-10, both suites green):

1. Compile clean (MetaEditor, `start /wait` + `/compile:` + `/log:`).
2. Stage the tree at
   `C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<TerminalID>\MQL5\Experts\MITEMSHUB_AI\`.
3. Write a tester config with a `[Tester]` section and
   `Expert=MITEMSHUB_AI\Tests\PhaseNTests` (the subpath is required — the
   tester looks in `MQL5\Experts`), `Symbol=SYN75`, `Period=M5`, `Model=1`
   (1-minute OHLC — enough for OnInit-only suites), a 1-day range,
   `Report=...`, `ReplaceReport=1`, `ShutdownTerminal=1`, and
   **`Port=3001`**.
4. Close the running terminal, launch
   `terminal64.exe /config:path\to\tester.ini` via `start /wait ""`, wait for
   it to self-shut-down, then relaunch the terminal normally.

**Critical gotcha:** the local tester agent defaults to port **3000**, which on
this machine is taken by the Next.js dashboard dev server — the agent cannot
bind, the terminal's handshake lands on the HTTP server, drops, and after ~30s
you get `tester agent authorization error` with the EA never running. Setting
`Port=3001` (any free port) in the `[Tester]` section fixes it completely.
Tester output appears in `Tester/logs/YYYYMMDD.log` (UTF-16).
