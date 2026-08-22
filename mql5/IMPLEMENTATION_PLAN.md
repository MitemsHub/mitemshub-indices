# MITEMSHUB AI MARKET ENGINE — Implementation Plan (Phase 0)

> Companion to `ARCHITECTURE_PLAN.md`. This is the **build order and the test
> gates**. No implementation happens until this plan is approved.
> Compiler available: `C:/Program Files/MetaTrader 5 Terminal/metaeditor64.exe`.

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
  `"C:/Program Files/MetaTrader 5 Terminal/metaeditor64.exe" /compile:"<abs path to .mq5>" /log:"<abs path to .log>"` — logs land in the same dir as the source by default; the `/log` flag pins it.

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

**Live-path & band-path exposure + frozen-vs-live A/B (2026-08-12):** the
freeze covered every `build_snapshot` consumer — the live dashboard read
calls it directly and `evaluate` calls it again internally, so every live
call's confidence (`_confidence_score` vol-ratio/|z| branches,
`_garch_mr_component`, `_vol_regime_component`) and the ML feature vector
saw z=0.0 / mr=0.0 / constant σ=0.02, and once the calibrated priors
landed a pathological constant `garch_vol_ratio` ≈20 (→ −0.10 confidence
penalty on EVERY call).  Band stop/target LEVELS were never frozen
(`band_levels` uses the strategy's own `_prev_sigma`); the band/vol-
dynamics confidence that gates them was.  Vol-band backtest leg untouched
(own per-bar forecaster).  A/B on the 12.9-day corpus (frozen = old guard
emulated; fresh model per run; same UTC gate): FROZEN n=159 hit 50.9%
gross +0.192R vs LIVE n=155 hit 51.0% gross +0.187R — a −4-trade (−2.5%),
−0.004R gross delta; z went 0.00 → mean −0.08 (|z|>1.5 on 3.9%), σ
constant 0.02 → 0.0016–0.0131, vr 19.85 → 0.25.  The entry gate + online
model adaptation absorb the difference; the freeze's real cost was feature
health and the systematic confidence bias, not the gated trade count.
Caveat: the live read feeds `build_snapshot` twice per read (panel +
evaluate) — same last-bar log-return fed twice, minor overweight, not a
freeze.

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

**Why ADWIN never fires — and the error-based detector is dead too
(2026-08-12, `_probe_adwin_why.py`, 12.9-day / 2,356-bar corpus):** the
return-stream ADWIN (`|log_return|×100`, delta 0.002 — the band/reversion
drift gates) fired **0/2,356** bars and the model's error-stream ADWIN
(`abs(label−p)` per taken-trade update) fired **0/155** updates — so the
`_drift_confidence_penalty` / `_dynamic_min_confidence` paths and both
drift-cooldown gates are inert on this corpus.  Return stream: heavy tails
(|r|% mean 0.194 / std 0.254 / p99 0.644) swamp the weak regime signal (a
rolling-250-bar mean swing of only 0.169→0.291, ~1.7× vol), and ADWIN's
floor is above the observed shifts at every resolvable window (eps(m=10)
≈1.47 — a 7.5× instantaneous jump would be needed; m=100 sits at 0.71×;
the m=250 offline crossing to 1.39× is undone in the real detector by its
window-spanning variance).  A gentle ramp in a heavy-tailed
absolute-return stream is structurally the wrong input for a mean-shift
detector.  Error stream: starved (~12 updates/day, UTC 12-24h trades only)
and dominated by per-trade outcome noise (mean 0.516 / std 0.415) — a win
or a loss both yield large |error| in every regime.  Verdict: neither ADWIN
variant is a usable entry-timing signal here; timing is carried by the
vol-extension gate + the UTC/|range_z| filter.  (The detector does fire on
real steps — unit tests feed 0.5→5.0; R_75's regime moves are ~20× smaller.)
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

**svcap OUT-OF-SAMPLE re-check (13.02-day corpus, 2026-08-12):** the
combined-gate probe re-run on the fresh ~2.5 days of corpus growth
(`mql5/svcap_recheck.py`, same methodology: real `run_ticks` passes,
TIME-exit broker, in-loop filtering, fresh model per run):

| cell | n | hit | gross | net@0.05 | net@0.10 | maxDD | streak | WF kept |
|---|---|---|---|---|---|---|---|---|
| sv (gate only) @13.02d | 150 | 50.7% | +0.190R | +0.140R | +0.090R | 5.71R | 5 | 149/150 |
| sv (10.5d ref) | 149 | 50.3% | +0.142R | +0.092R | +0.042R | 5.71R | 5 | — |
| **svcap @13.02d** | **147** | **52.4%** | **+0.210R** | **+0.160R** | **+0.110R** | **5.85R** | **5** | **147/147** |
| svcap (10.5d ref) | 146 | 52.1% | +0.161R | +0.111R | +0.061R | 5.85R | 5 | — |

**The +0.111R net@0.05 lift HOLDS out-of-sample — and improves to
+0.160R net@0.05** (+0.049R better than ref; hit 52.1 → 52.4%; the
2.5 days of fresh data were *better* than the training window, not
worse).  The depth-cap delta is stable too: svcap − sv = +0.020R
net@0.05 now vs +0.019R at 10.5d.  maxDD (5.85R), worst streak (5) and
walk-forward behavior (KEPT 147/147, no suppression) all reproduce.
First gate cell to survive a corpus-growth re-run without decay.

**Entry gate wired into the LIVE emission path (2026-08-11), measured
end-to-end:** `SymbolProfile.entry_gate_enabled` (default True), window
UTC [12,24) and |range_z_50| < 1.0 are enforced inside
`DecisionEngine.evaluate` for sniper mode — AFTER the stateful monitors
(regime/calibration/GARCH keep seeing every bar, so live session state
never freezes for 12h) and BEFORE scoring/emission (out-of-window bars
stand aside without wasted model work, and the ML model never even
scores extreme-vol entries).  `market_snapshot` resolves sniper-only, so
the gate now governs the live dashboard calls, the watch loop, and the
real-corpus harness (which calls the same evaluate).  Harness re-run
(337 checks, 0 failed):

| leg | n | hit | gross | net@0.05 | net@0.10 | maxDD | WF gate |
|---|---|---|---|---|---|---|---|
| gated production broker (fixed 1.9R) | 155 | 51.0% | +0.187R | +0.137R | +0.087R | — | KEPT |
| **gated time-exit** | **150** | **50.7%** | **+0.190R** | **+0.140R** | **+0.090R** | **5.71R** | KEPT 149/150 |

**The gate alone turns the production sniper leg positive** (+0.187R vs
+0.008R ungated; hit 51.0% beats the 39.5% floor), and the gated
time-exit leg reproduces the probe's +0.14R net@0.05 at the live-path
level — slightly BETTER than the post-risk probe hook, because gating at
emission means the model never scores out-of-window/extreme-vol bars.
Fixture cost of the production gate: evaluate-based tests using
epoch-0 candles were re-anchored to a 13:00 UTC base
(test_decision_engine, test_decision_engine_integration,
test_backtest/test_wfo via the shared synthetic_ticks factories), and
new gate tests lock the behavior (out-of-window → None + "entry gate"
rationale; entry_gate_enabled=False restores old emission).  The harness
now also prints a permanent gated time-exit measurement (entry-gated
leg block, print-only so the 337 checks are untouched).

**Time-exit horizon sweep (2026-08-12, `_probe_time_exit_sweep.py`, 12.9-day
corpus):** exit horizon swept 4h → 1h (2h baseline = adopted mean-drift
horizon; 1R stop fixed, target ignored, same UTC gate, fresh model per run;
single-position broker → n grows as the horizon shrinks):

| h | n | hit | gross | net@0.05 | net@0.10 | tot@0.05 | tot@0.10 | maxDD |
|---|---|---|---|---|---|---|---|---|
| 4.0h | 46 | 37.0% | **+0.541R** | +0.491 | +0.441 | +22.6 | +20.3 | 6.0R |
| **3.0h** | **55** | 38.2% | +0.491R | +0.441 | +0.391 | **+24.3** | **+21.5** | 8.3R |
| 2.0h (baseline) | 75 | 40.0% | +0.276R | +0.226 | +0.176 | +17.0 | +13.2 | 8.7R |
| 1.5h | 88 | 45.5% | +0.257R | +0.207 | +0.157 | +18.2 | +13.8 | 7.9R |
| 1.0h | 119 | 49.6% | +0.237R | +0.187 | +0.137 | +22.3 | +16.4 | **5.1R** |

Per-trade gross rises monotonically with horizon (peak beyond 4h) while hit
falls (49.6% → 37.0% — early winners mean-revert, trending winners
accumulate).  Costs leave the per-trade ordering unchanged (4h best at any
cost) but move the TOTAL-return optimum: the n-collapse (46 vs 119) puts
the total-net peak at **3h** (+24.3R @0.05 / +21.5R @0.10), 1h the
runner-up at 0.05 (+22.3R, best drawdown 5.1R, best hit 49.6%).  The
adopted 2h baseline is the WORST cell on total net (+17.0R) — a local
minimum of the sweep.

**UTC 12-24h filtered-cell re-check @ 12.9 corpus days (2026-08-12,
`mql5/utc_cell_recheck.py`, durable so it re-runs as the corpus grows):**
the corpus is 12.92 days / 172,368 ticks — not yet past 15, so this is
the checkpoint measurement; fidelity replay matches realized exactly
(51.0% == 51.0%, n=155).  Note the live gate is now the production
default, so the whole capture is in the 12-24h cell (cell == baseline
by construction); the strict subset is the 18-24h cell:

| cell | n | hit@1.2 | exp@1.2 | hit@1.5 | exp@1.5 | medMFE |
|---|---|---|---|---|---|---|
| UTC 12-24h & |range_z|<1.0 (was n=34, 58.8%, +0.246R) | 155 | 54.2% | +0.175R | 51.6% | +0.199R | +0.98R |
| **UTC 18-24h & |range_z|<1.5 (was n=24, 58.8%, +0.267R)** | **67** | **58.2%** | **+0.242R** | **55.2%** | **+0.304R** | **+1.12R** |

**Verdict: the edge survives n-growth, and the narrower session window
is the robust form.**  The wide 12-24h cell diluted on the way to n=155
(hit 58.8% → 54.2%, exp +0.246R → +0.175R) — still positive and above
the RR-1.2 floor, but weaker.  The 18-24h & |range_z|<1.5 cell held
almost exactly at n=67 ≥ 60 (hit 58.2%, exp +0.242R@1.2 / +0.304R@1.5)
and shows the best medMFE (+1.12R) — the tighter session+vol filter is
the part that generalizes.  Re-run this script once the corpus passes
~15 days for the final n-growth confirmation.

**Deep-vs-shallow + vol-regime profile on the sniper leg (2026-08-12,
12.99-day corpus, 155 gated trades, fidelity replay MATCH 51.0%) —
`utc_cell_recheck.py` now records per-trade entry features and splits the
realized production geometry (fixed 1.9R target / 1R stop):**

| depth (\|range_z_50\|) | n | hit | exp | sumR | maxDD | medMFE |
|---|---|---|---|---|---|---|
| rz<0.33 (near-center) | 44 | 47.7% | +0.251R | +11.0R | 7.3R | +0.87R |
| rz 0.33-0.66 | 51 | 45.1% | +0.086R | +4.4R | 8.4R | +0.95R |
| **rz>=0.66 (band-edge)** | **60** | **58.3%** | **+0.227R** | **+13.6R** | **2.9R** | **+1.10R** |

| vol-regime (garch_vol_ratio) | n | hit | exp | sumR | maxDD | medMFE |
|---|---|---|---|---|---|---|
| **vol<=1.25** | **138** | **52.2%** | **+0.220R** | **+30.3R** | **5.7R** | **+1.02R** |
| vol>1.25 | 17 | 41.2% | −0.076R | −1.3R | 4.0R | +0.91R |

**The sniper edge CONCENTRATES — the opposite of the band's flat
profile.**  The MQL5 band holds identical hit/MFE across depth (bleeding
by volume); the sniper's edge is NOT flat: the **band-edge entries
(rz>=0.66) are the strongest cell** — 58.3% hit, +0.227R, the LOWEST
maxDD (2.9R) and highest medMFE (+1.10R) — while the mid-depth cell is
the weak pocket (45.1%, +0.086R).  And the edge lives in **normal vol**
(vol<=1.25: 52.2%, +0.220R, +30.3R sumR over 138 trades); the
extreme-vol minority (17 trades, 11%) is the only negative pocket
(41.2%, −0.076R).  Two discardable pockets identified: mid-depth and
vol>1.25.  Caveats: single 12.99-day window, n=155 total (vol>1.25 n=17),
and this band-edge axis (\|range_z_50\| within the <1.0 gate) is
consistent with — not contradictory to — the older \|garch_z\|≥1.0
finding, which measured stretched log-return z on the UNGATED book.

**Direction + hour split of the forward-pass cell (2026-08-12, 13.01-day
corpus, UTC 18-24h & |range_z|<1.5, n=67, fidelity MATCH) — does the edge
concentrate further or is it balanced?**  `utc_cell_recheck.py` now
splits the cell by side and hour (replay at RR 1.2/1.5; realized =
production 1.9R geometry):

| side | n | hit@1.2 | exp@1.2 | hit@1.5 | exp@1.5 | realized(1.9R) | medMFE |
|---|---|---|---|---|---|---|---|
| LONG | 52 | 59.6% | +0.264R | 55.8% | +0.303R | 53.8%/+0.310R | +1.13R |
| SHORT | 15 | 53.3% | +0.166R | 53.3% | +0.306R | 53.3%/+0.175R | +1.12R |
| ALL | 67 | 58.2% | +0.242R | 55.2% | +0.304R | 53.7%/+0.279R | +1.12R |

| hour | n | hit@1.2 | exp@1.2 | realized(1.9R) | medMFE |
|---|---|---|---|---|---|
| 18-19 | 9 | 66.7% | +0.226R | 66.7%/+0.229R | +1.08R |
| 19-20 | 9 | 88.9% | +0.956R | 77.8%/+0.894R | +1.40R |
| 20-21 | 13 | 46.2% | +0.096R | 46.2%/+0.307R | +0.67R |
| 21-22 | 14 | 57.1% | +0.133R | 57.1%/+0.256R | +0.73R |
| 22-23 | 9 | 44.4% | +0.146R | 33.3%/−0.036R | +0.84R |
| 23-24 | 13 | 53.8% | +0.089R | 46.2%/+0.106R | +1.10R |
| **18-21 coarse** | **31** | **64.5%** | **+0.383R** | **61.3%/+0.455R** | **+1.28R** |
| 21-24 coarse | 36 | 52.8% | +0.120R | 47.2%/+0.129R | +0.84R |

**Verdict: the edge is balanced across direction but concentrates by
hour.**  Both sides are positive (LONG 59.6%/+0.264R with 78% of the
volume; SHORT 53.3%/+0.166R) and they converge at RR 1.5 (+0.303 vs
+0.306) — no one-sided dependency, the ML scoring simply favors longs in
this window.  The hour split is the concentrated axis: the FIRST half of
the window (18-21) carries nearly all the strength — 64.5% hit,
+0.383R@1.2, realized +0.455R@1.9 — vs the back half's 52.8%/+0.120R;
19-20 is the standout hour (88.9%, +0.956R) and 22-23 is the only
sub-50% cell (44.4%, realized −0.036R).  Caveats: hourly cells are thin
(n=9-14; the coarse 18-21/21-24 split of 31/36 is the firmer read), and
this is the same single 13-day window.  The RUNNING forward pass stays
on 18-24 (changing it mid-pass would invalidate the out-of-sample test);
the 18-21 concentration is the refinement candidate for the NEXT pass.

**rz-tightening ladder (UTC 12-24h gate, 13.02-day corpus, 2026-08-12):**
the hypothesis — a tighter vol gate (rz<0.7) lifts hit/net at the cost
of trade count — is **disproven**: tightening DILUTES the edge.  Moving
the |range_z_50| cap 1.0 → 0.7 on the 155-trade gated population (fidelity
MATCH) lowers hit 54.2 → 50.0%, expectancy +0.175 → +0.110R and net@0.05
+0.125 → +0.060R while cutting trade count 34% (155 → 102); the 0.6 step
bounces to +0.145R on noise (n=85).  Mechanism: on the sniper the BAND-
EDGE entries (rz 0.7-1.0, deleted by the tighter cap) are the strongest
cell — the deep-vs-shallow profile's rz>=0.66 bucket is 58.3% hit /
+0.227R / 2.9R maxDD — the opposite of the MQL5 band where deep is the
drag.  The hour axis dominates instead: 18-24 & rz<0.7 (n=48) runs
56.2%/+0.186R because 18-21 is the strong half of the window.  Action:
keep |range_z|<1.0; the band-edge entries are the edge, not a tail to trim.

| cell | n | hit@1.2 | exp@1.2 | net@0.05 | hit@1.5 | exp@1.5 | medMFE |
|---|---|---|---|---|---|---|---|
| UTC 12-24h & rz<1.0 (gate) | 155 | 54.2% | +0.175R | +0.125R | 51.6% | +0.199R | +0.98R |
| UTC 12-24h & rz<0.8 | 118 | 51.7% | +0.141R | +0.091R | 49.2% | +0.180R | +0.95R |
| UTC 12-24h & rz<0.7 | 102 | 50.0% | +0.110R | +0.060R | 47.1% | +0.150R | +0.93R |
| UTC 12-24h & rz<0.6 | 85 | 51.8% | +0.145R | +0.095R | 48.2% | +0.184R | +0.93R |
| UTC 18-24h & rz<0.7 | 48 | 56.2% | +0.186R | +0.136R | 52.1% | +0.235R | +1.08R |
| UTC 18-24h & rz<1.5 (fwd pass) | 67 | 58.2% | +0.242R | +0.192R | 55.2% | +0.304R | +1.12R |

**12-24h hour ladder — the edge concentrates in THREE hours, not one block
(13.02-day corpus, 2026-08-12):** per-hour replay of the gated population
(155 trades, fidelity MATCH):

| hour | n | hit@1.2 | exp@1.2 | net@0.05 | trades/day |
|---|---|---|---|---|---|
| 12-13 | 17 | 64.7% | +0.390R | +0.340R | 1.3 |
| 13-14 | 12 | 50.0% | +0.034R | −0.016R | 0.9 |
| 14-15 | 19 | 42.1% | −0.035R | −0.085R | 1.5 |
| 15-16 | 15 | 46.7% | +0.055R | +0.005R | 1.2 |
| 16-17 | 15 | 60.0% | +0.289R | +0.239R | 1.2 |
| 17-18 | 10 | 40.0% | −0.064R | −0.114R | 0.8 |
| 18-19 | 9 | 66.7% | +0.226R | +0.176R | 0.7 |
| 19-20 | 9 | 88.9% | +0.956R | +0.906R | 0.7 |
| 20-21 | 13 | 46.2% | +0.096R | +0.046R | 1.0 |
| 21-22 | 14 | 57.1% | +0.133R | +0.083R | 1.1 |
| 22-23 | 9 | 44.4% | +0.146R | +0.096R | 0.7 |
| 23-24 | 13 | 53.8% | +0.089R | +0.039R | 1.0 |

Best contiguous sub-windows: **4h 16-20 → 62.8%/+0.333R/net +0.283R
(3.3/day, n=43)**; 5h 18-23 → 59.3%/+0.279R (4.1/day); 6h 16-22 →
58.6%/+0.249R (5.4/day) vs the full 12-24h gate's 54.2%/+0.175R/net
+0.125R (11.9/day).  Three strength pockets: 12-13 (n=17, 64.7%, +0.390R),
16-17 (60.0%, +0.289R) and 19-20 (n=9, 88.9%, +0.956R — thin); two
net-negative hours drag the window: 14-15 (−0.035R) and 17-18 (−0.064R).
So a tighter sub-window DOES roughly double expectancy at 28-45% of the
trade count — the 18-23h / 16-22h candidates (4-5/day) are the balance
point.  Caveats: hourly cells are thin (n=9-19) and the window was
chosen on this single 13-day corpus — the candidates need an out-of-
sample re-check before replacing the running 18-24h pass (which sits at
+0.242R, statistically indistinguishable from 16-22's +0.249R).

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

**Per-bucket drawdown attribution via equity-curve position
(2026-08-12, RR 3.0 default geometry):** `BandBackTests` now records each
trade's equity-curve position at close, so max drawdown is computed per
depth bucket directly from reconstructed per-bucket equity curves (not
sumR):

| bucket | n | hit | exp | sumR | maxDD | maxDD/trade |
|---|---|---|---|---|---|---|
| shallow ≤1.5 | 171 | 26.3% | +0.053R | +9.0R | 22.0R | 0.129R |
| mid 1.5-2.5 | 326 | 25.8% | +0.031R | +10.0R | 37.0R | 0.114R |
| deep >2.5 | 1,040 | 25.1% | +0.005R | +5.0R | 59.0R | 0.057R |

**The direct measurement refines "bleed by volume":** the deep fades own
the largest ABSOLUTE drawdown (59.0R — 68% of the book) but the SMALLEST
per-trade drawdown (0.057R/trade vs shallow 0.129R, mid 0.114R) — so the
depth-cap "6× cut" is confirmed as mechanical count-scaling (removing
1,040 trades' worth of DD accumulation), not a tail-risk fix.  The
shallow fades are the sharper per-trade risk AND the better expectancy
(+0.053R); deep is the lowest-risk-per-trade leg that never converts
(hit 25.1% vs the 30% floor).  The equity-position field ships in every
BandBackTests report going forward.

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
1830 near-scratch trades compounds instead of the clean −1R losers.Trail
stays OFF (0.0) — the current default is confirmed correct.  The
one structural escape hatch: the tester's trail exit has NO closed-candle
grace — the Python system already locks stops to closed candles (spread/
wick jitter can't stop a valid plan), so the natural next experiment is
the same closed-candle rule on the trail's breakeven exit before judging
the trail concept dead.

**Closed-candle trail grace — the trail STOPPED racing the target (same
window, 2026-08-11):** the escape hatch is now implemented
(`InpTrailClosedCandle=true`): once armed (eff_stop == entry) the
breakeven exit only fires on an M5 candle CLOSING through entry — a wick
can no longer scratch a runner.  Re-swept frac 0.2–0.8 at RR 1.2 with
the grace ON (7 runs, each a full 6-month tester pass):

| frac | arm | n | hit | exp gross | exp@0.05 | exp@0.10 | maxDD |
|---|---|---|---|---|---|---|---|
| 0.0 | off | 1,796 | 40.4% | −0.112R | −0.162R | −0.212R | 204.8R |
| **0.2** | 0.24R | **1,818** | **43.6%** | **+0.398R** | **+0.348R** | **+0.298R** | **5.8R** |
| 0.4 | 0.48R | 1,800 | 43.5% | +0.283R | +0.233R | +0.183R | 7.8R |
| 0.5 | 0.60R | 1,809 | 44.2% | +0.241R | +0.191R | +0.141R | 12.4R |
| 0.6 | 0.72R | 1,778 | 43.9% | +0.199R | +0.149R | +0.099R | 13.2R |
| 0.7 | 0.84R | 1,811 | 43.9% | +0.152R | +0.102R | +0.052R | 17.0R |
| 0.8 | 0.96R | 1,831 | 43.5% | +0.117R | +0.067R | +0.017R | 21.4R |

**Complete turnaround: every frac is positive, hit holds at 43.5–44.2%
(vs 2–4% without the grace), and drawdown collapses 204.8R → 5.8R at
frac 0.2.**  The wick-scratch was the ENTIRE problem — not late arming:
with the grace, winners survive their pullbacks and the trail converts
would-be −1R losers to 0R breakevens (~44% scratch at entry; the real
loss rate falls to ~12%: 43.6% win +1.2R, 43.9% scratch 0R, 12.5% lose
−1R → +0.398R).  **frac 0.2 is the first positive-net band geometry at
ANY RR** (+0.348R net@0.05, +0.298R net@0.10), reproduced on the next-day
window (+0.390R/+0.340R).  Expectancy degrades monotonically as frac
rises (0.398 → 0.117R) — early arming is now strictly better, opposite of
the no-grace regime.  Honesty note: the result rests on the closed-candle
fill model the user chose (wick through the breakeven level does NOT
fill); with wick fills it is the old 2%-hit disaster.  Default stays 0.0
— flipping is one flag away (`InpTrailFrac=0.2`) after fresh-window
confirmation.  Also hardened: the depth-split CI's exp upper band was
widened −0.35→+0.75R so legitimate trail-improved cells (+0.40R) don't
false-FAIL the suite; the negative collapse band is unchanged.

**RR-3.0 trail sweep with the grace (default geometry, same window,
2026-08-11):** does the trail behave the same when the target is 3.0R?
Same qualitative shape — every frac positive, hit holds (no collapse),
drawdown crushed — and the optimum moves EARLIER (frac 0.1, arm 0.30R):

| frac | arm | n | hit | exp gross | exp@0.05 | exp@0.10 | maxDD |
|---|---|---|---|---|---|---|---|
| 0.0 | off | 1,537 | 25.4% | +0.016R | −0.034R | −0.084R | 81.0R |
| **0.1** | **0.30R** | **1,537** | **28.1%** | **+0.687R** | **+0.637R** | **+0.587R** | **7.0R** |
| 0.2 | 0.60R | 1,526 | 29.0% | +0.582R | +0.532R | +0.482R | 13.0R |
| 0.4 | 1.20R | 1,526 | 28.4% | +0.380R | +0.330R | +0.280R | 18.0R |
| 0.5 | 1.50R | 1,511 | 27.5% | +0.273R | +0.223R | +0.173R | 33.0R |
| 0.6 | 1.80R | 1,506 | 27.7% | +0.233R | +0.183R | +0.133R | 32.0R |
| 0.7 | 2.10R | 1,495 | 27.7% | +0.194R | +0.144R | +0.094R | 36.0R |
| 0.8 | 2.40R | 1,529 | 27.3% | +0.156R | +0.106R | +0.056R | 47.0R |

**frac 0.1 is the strongest band configuration ever measured — +0.687R
gross / +0.637R net@0.05 / +0.587R net@0.10, maxDD 81R → 7R, hit
28.1%, all 8 depth-split CI cells PASS.**  Mix: 28.1% win +3R, ~56%
scratch 0R, ~16% lose −1R (84% never lose); STRONG (deep) +0.697R
carries it.  The longer target AMPLIFIES the conversion benefit (winners
have more room to survive pullbacks) — consistent with monotonic
degradation in frac at both RRs and an optimum at the earliest arm.
**New measurement-lens caveat:** with breakeven exits the hit-vs-floor
gate (28.1% vs 30.0%) counts 0R scratches as losses — the realized
payout BE is far below 28.1%, so the Stage-3 floor logic (tester and
Python) must treat 0R as non-loss before this geometry is judged
floor-beatable.  Default still 0.0 pending that floor-lens fix + fresh
window.

**Arming-to-exit path instrumentation (2026-08-11) — quantifying the
grace's save:** per-trade `arm_hold_bars` / `arm_mfe_r` /
`dips_after_arm` / `wick_scratch_wo_grace` / `hit_target_after_dip` now
record the trail's full arming path (arm bar, arm MFE, every post-arm
bar that wicks through entry).  Counterfactual report on the RR-3.0
cells:

| frac | armed | wick-through | saved (0R→target) | saved R | grace R/trade |
|---|---|---|---|---|---|
| 0.1 | 1,299/1,537 (84.5%) | 449 (34.6%) | **125** | **+375R** | **+0.244R** |
| 0.8 | 514/1,529 (33.6%) | 92 (17.9%) | 19 | +57R | +0.037R |

**Why the optimum is at the earliest arm, now proven trade-by-trade:**
frac 0.1 arms 84.5% of trades (nearly every position touches 0.30R MFE)
and 34.6% of armed trades wick through entry at least once — the jitter
the grace spares.  125 of those 449 wick-throughs (28%) still reached the
3.0R target: **+375R the no-grace rule would have scratched at 0R, i.e.
+0.244R per trade over the whole run** (vs frac 0.8's 33.6% arm rate,
17.9% wick-through, 19 saved = +0.037R).  The breakeven-exit group (867
at frac 0.1) nets 0R either way, so the grace's entire contribution is
the saved target-wins — and that contribution scales with arm earliness.
The instrumentation (and the arming-path report behind `InpTrailFrac >
0`) stays in the tester as a permanent diagnostic.

**Trail × edge-depth cross-tab (2026-08-11):** the arming-path stats
split by the depth buckets (shallow ≤1.5 / mid 1.5-2.5 / deep >2.5):

*frac 0.1 (arm 0.30R):* shallow n=160 hit 23.8% exp +0.531R — armed
81.9%, wick-thru 38.2%, saved 14/50 (28.0%), +0.262R/trade; **mid n=346
hit 32.4% exp +0.812R — armed 84.1%, wick-thru 34.0%, saved 36/99
(36.4%), +0.312R/trade**; deep n=1,031 hit 27.4% exp +0.670R — armed
85.1%, wick-thru 34.2%, saved 75/300 (25.0%), +0.218R/trade.
*frac 0.4 (arm 1.20R):* shallow hit 26.1% exp +0.301R saved 11/36
(30.6%) +0.216R/trade; mid hit 27.6% exp +0.355R saved 18/77 (23.4%)
+0.158R/trade; deep hit 29.1% exp +0.400R saved 52/203 (25.6%)
+0.151R/trade.

**Verdict: the shallow fades do NOT survive the trail better — at the
adopted frac 0.1 the MID bucket wins on every axis** (hit 32.4%, exp
+0.812R, wick-through conversion 36.4%, saved R/trade +0.312R); shallow
is weakest on exp (+0.531R) and conversion (28.0%) because its marginal
entries arm eagerly (81.9%) but convert to breakeven (58.1% BE-trail
exit rate — the highest) instead of running to target, dropping its hit
28.0% → 23.8% vs the no-trail measurement (scratches count as losses)
while still flipping expectancy strongly positive (+0.119R → +0.531R).
The ordering inverts at the later arm (frac 0.4: shallow converts best
30.6%) — but every bucket is positive at every frac: the trail+grace
helps all depth classes, most of all the mid fades.  Practical
implication: a depth gate that blocks deep extensions (InpMaxEdgeDepth
≤ 1.5) would NOT improve the trail geometry — it would keep the weakest
bucket and discard the strongest (mid) one.

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

**Sniper walk-forward gate contract wired into the loop (2026-08-12):** the
band's depth-split contract now has a Python-side counterpart — the sniper
leg's walk-forward gate (KEPT/SUPPRESSED per trade) is asserted by
`verify_all.ps1` via `python mql5/svcap_recheck.py --gate-check`: one real
`run_ticks` pass of the reference gate-clean svcap cell (UTC 12-24h &
|range_z|<1.0 & |garch_z|<=1.5, time-exit) with a strict `[GATECHECK]`
verdict + exit code.  A suppressed-vs-kept regression (suppressed > 10% of
the cell — the gate blocking a previously clean cell), zero kept trades, or
net@0.05 below −0.10R fails the loop; thin corpus (< 30 trades) or missing
python SKIPs instead of false-failing.  The result renders as a `SniperGate`
row in the summary table (Compile "-" = Python row); `-SkipSniperGate`
opts out.  Verified end-to-end: `[GATECHECK] PASS` (n=147 kept=147
suppressed=0 (0.0%)) and `ALL SUITES PASSED (compile + Strategy Tester +
sniper gate contract)`; verdict branches unit-tested (gate_verdict) and the
PowerShell parse fixture-tested.

**Paper->live execution parity layer (2026-08-12):** the Python engine's
three execution paths — simulated (forward-demo paper fills), MT5 python-API
(`Mt5LiveExecutionBackend`, the Python CTrade-equivalent), and the MQL5
`SynthCallExecutor` EA (polls the `ea_emitter` call file) — now carry a
shared parity contract.  New: `src/synthetic_trader/execution/mt5_simulator.py`
(`FakeMetaTrader5`, an in-memory CTrade-equivalent: FOK market fills at
ask/bid, position open/close/modify by ticket, configurable reject retcodes,
every order_send logged) and `src/synthetic_trader/execution/parity.py`
(replay engine: identical OrderIntents + candle streams through simulated
and live backends, comparing submit acceptance / open-position counts after
every step / per-outcome direction-entry-exit-return_r-won-close-time;
`run_rejection_probe` for broker-reject handling; `check_ea_contract` proving
the EA call record carries exactly the levels executed).  `mql5/execution_parity_check.py`
is the CLI harness wired into `verify_all.ps1` as the `ExecutionParity` row
(`-SkipExecutionParity` to opt out).  Fix surfaced by parity: the live
backend's `open_positions_count()` returned the stale submit-time sync
snapshot — a mid-session stop/target close left the count at 1 while the
paper side read 0 — now re-syncs with the broker.  Verified: harness PASS
(40/40 comparisons, 3 trades covering target/stop/expiry, reject probe ok,
EA contract 3/3), 30 unit tests, full Python suite 1022 passed, verifier
integration `ALL SUITES PASSED (... + execution parity)`.

**Band floor verdict wired into Test-DepthSplit (2026-08-12):** the
Stage-3 gate's own `VERDICT: achieved hit X% BEATS / does NOT beat the
Y% floor` line is now part of the band's measurement contract — the block
must be PRESENT, the verdict internally CONSISTENT with its own numbers
(declared BEATS at hit < floor, or does NOT beat at hit >= floor, fails
with `floor verdict FLIP:` — a flip is a bug, not an improvement), and
the floor in [20,60]% (the 1/(1+RR)+margin band for RR 1.0-3.5).  The
healthy state rides in the Detail column (`floor-gate: hit 25.4% does NOT
beat 30%`).  Fixtures cover both flip directions, the missing block, the
missing verdict line, and an out-of-band floor; verified end-to-end on
the default 6-month run.

**Vol-regime split contract added to Test-DepthSplit (2026-08-12):** the
suite's vol-regime split at entry (`vol_ratio_entry = prev_sigma /
sigma_ema`, `vol<=1.25` / `vol>1.25` cells) is now parsed by the same
gate — flag when the `vol>1.25` cell becomes a meaningful share of the
book: >=20% with negative expectancy fails (`high-vol entries diluting
the edge`), >=35% fails unconditionally (`the vol cell IS the book`), a
large-but-positive share is reported not failed (measured default run:
0.7% share, +0.200R), a missing `vol>1.25` row means zero high-vol
trades (normal — empty buckets aren't printed), and a missing split
header is a refactor regression.  The Detail line now ends with the
vol-split state; `verify_volsplit_fixtures.ps1` covers all branches.

**Machine depth-profile + floor-verdict lines with a bucket-composition gate
(2026-08-12):** the suite now prints one `[BANDBT] DEPTHPROFILE` line
(all 5 cumulative caps: n/hit/exp/share-of-total, empty buckets as n=0)
and one `[BANDBT] FLOORVERDICT` line (floor/achieved/verdict/mean_rr).
`Test-DepthSplit` parses them as the authoritative contract: per-cap n and
total cross-checked against the human rows (print-drift fails),
FLOORVERDICT must agree with the human VERDICT, and each cap's share must
stay in the measured bands (<=1.25 10.7-12.4%, <=1.50 20.9-24.7%, <=2.00
46.7-48.6%, <=2.50 71.7-74.3% — stable across sweep ON/OFF, 5 seeds, and
TARGET/TIME modes), guarded by total>=50 for thin windows.  A composition
shift (deep dominance or shallow collapse) fails the loop visibly.  The
Detail column gains `depth-comp: <=1.25 12.4% | <=1.50 24.7% | <=2.50
71.7% (total 693)`.  Verified: compile 0 errors, real 6-month run PASSES
with the new Detail, both machine lines present in the tester log, and all
13 fixture branches in `verify_volsplit_fixtures.ps1` pass.

**Seed-sweep harness — the RNG-reshuffle confound, quantified (2026-08-12):**
`mql5/seed_sweep.ps1` runs the RR-3.0 cap-2.0 cell across 5 geometry-sweep
seeds (7/42/123/777/2024, each one verify_all invocation ~25s with
-SkipSniperGate, tester log copied per seed) and reports the spread.  The
seed reshuffles per-signal geometry (z_entry in [0.7, 1.6], stop in [0.15,
0.35], target = 3.0 x stop) — entry membership, stop width, and depth
bucket all move.  Measured: cap-2.0 exp −0.079R to +0.111R (mean +0.023R,
spread 0.190R, ~8x the mean), hit 23.0-27.8% (spread 4.8pp), n 298-329
(entry COUNT is stable ±5%; the seed changes which signals).  The shallow
<=1.25 cell flips sign across seeds (−0.257R to +0.256R).  All depth/vol
contracts survive every seed — no false failures — but single-seed exp is
not distinguishable from noise; conclusions need >=3 seeds.  The harness
also documents a real PowerShell 5.1 trap: `[string]$Seeds` type-constrains
the param variable, so assigning the split to the case-colliding `$seeds`
silently string-converts the array (space-joined, `count=1`); the parsed
list must use a distinct name (`$seedList`).

**Seed-sweep depth gate wired into the verifier (2026-08-12):** the
measurement above became the justification for `verify_all.ps1 -SeedSweep`
— an opt-in multi-seed depth-split gate.  It compiles BandBackTests once,
re-runs it per seed (`-Seeds`, default 7/42/123/777/2024, ~25s each;
`-Inputs` pass through with InpGeomSeed swept), parses each seed's rows
from its run block, and `Test-SeedStability` fails the suite when the
cap-1.25 / cap-2.00 cell means are unstable: mean exp < +0.05R (not
positive after averaging), exp spread > 0.25R (quarter-R swing), or a
small mean (< 0.10R) with spread > 3x the mean (noise, not signal).  Hit
spread is reported, not gated (4.8pp at n~320 is counting noise).  Real
5-seed integration run: BandBackTests single-seed PASS, SeedSweep FAIL
with per-seed numbers byte-identical to seed_sweep.ps1 (seed 123
317/23.0%/-0.079R etc.) and the UNSTABLE verdict naming both cells — the
gate correctly refuses to certify a cell whose positives are seed noise.
The pure verdict is fixture-tested (`verify_seedsweep_fixtures.ps1`, 8
branches: stable PASS, measured-noise FAIL, absolute-spread FAIL,
fragile-small-mean FAIL, too-few-seeds FAIL, hit-not-gated PASS).  Also
caught and fixed a `$seed:` string-interpolation parse error (PowerShell
drive-qualifier ambiguity — use `$($seed):`).

**Pure subset test — geometry sweep OFF (2026-08-12):** with
`InpGeomSweep=false` (fixed z_entry=1.0, stop 0.20 sigma, target 0.60
sigma = 3.0R) the RNG confound is gone entirely — `MathSrand` is never
consumed, so the rows are deterministic (verified byte-identical across
seeds 42 and 7: n=54/109/220/339/456).  The shallow-fade edge survives
and sharpens: shallow <=1.50 (|z| in [1.0, 1.5]) is the ONLY positive
bucket — hit 27.5%, exp +0.101R (vs +0.053R under the sweep at seed 42)
— while every deeper bucket is negative (−0.073R at <=2.00, −0.026R at
<=3.00).  The sweep's random z_entry divisor REBUCKETS trades (a high
draw pushes genuine shallows into the mid bucket and raises the entry
bar), diluting the shallow edge; fixed geometry also shrinks the funnel
(456 vs 693 trades).  Floor verdict still stands aside: overall 24.4%
vs 30%, shallow-only 27.5% (2.5pp short, ~0.6 sigma at n=109).

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

**RR 2.5-3.5 finer map (2026-08-12, `-Inputs
InpDerivedTargetRR=<rr>;InpMinTargetRR=<rr>`, 0.25 steps, fresh 6-month
window):**

| RR | n | hit | exp gross | floor | gap (hit−floor) | tot net@0.05 |
|---|---|---|---|---|---|---|
| 2.50 | 1,649 | 27.6% | −0.034R | 33.6% | −6.0 | −138.5R |
| 2.75 | 1,572 | 26.9% | +0.009R | 31.7% | −4.8 | −64.5R |
| **3.00** | **1,537** | **25.4%** | **+0.016R** | **30.0%** | **−4.6** | **−52.3R** |
| 3.25 | 1,483 | 23.8% | −0.040R | 28.5% | −4.7 | −133.5R |
| 3.50 | 1,455 | 21.9% | −0.137R | 27.2% | −5.3 | −272.1R |

**RR 3.0 is the exact optimum of the zone** — the gap minimum (−4.6pp,
the closest any cell comes to clearing its floor) AND the best expectancy
(+0.016R vs +0.009R at 2.75; 3.25/3.50 collapse to −0.040/−0.137R — the
MFE cliff, hit 21.9% at 3.5).  The optimum is sharp: both 0.25 neighbors
already lose the edge.  Trade count falls monotonically with RR (1,649 →
1,455 — the farther target holds the single slot longer).  The 3.0 cell's
≤1.25 shallow bucket CLEARS its floor (31.4% vs 30.0%) — the shallow
fades are the floor-beatable subset — but the full population still
misses by 4.6pp, so the Stage-3 gate continues to stand the band leg
aside at every RR in the zone.

**Wider-stop test at RR 1.2 (2026-08-12, 6-month window, sweep OFF,
`InpGeomSweep=false;InpStopSigmaMult=<s>;InpTargetSigmaMult=<1.2s>`,
`InpDerivedTargetRR=1.2;InpMinTargetRR=1.2`):** hypothesis — a wider
stop cuts the ~59% stop-out rate enough to lift hit toward the 50.5%
floor:

| cell | stop/target σ | n | hit | exp gross | stop-out | floor gap |
|---|---|---|---|---|---|---|
| base RR 1.2 (sweep ON, 0.15-0.35σ) | ~0.2σ | 1,932 | 39.4% | −0.132R | 60.6% | −11.1 |
| stop 0.50 / target 0.60 | 0.50/0.60 | 1,719 | 45.2% | −0.006R | 54.8% | −5.3 |
| stop 0.60 / target 0.72 | 0.60/0.72 | 1,585 | 44.7% | −0.016R | 54.9% | −5.8 |
| stop 0.70 / target 0.84 | 0.70/0.84 | 1,501 | 45.0% | −0.015R | 53.9% | −5.5 |

**Directionally confirmed but insufficient alone:** stop-out drops
60.6% → ~54%, hit jumps 39.4% → ~45% but PLATEAUS at ~45% — still −5.5pp
short of the 50.5% floor, expectancy at raw breakeven (−0.006R at 45.2%
vs the 45.45% no-margin breakeven).  Wider stops cost trade count too
(1,932 → 1,501 — `InpMaxStopPct=1.5%` rejects more).  **The hidden
winner: the MID-depth bucket (depth 1.5-2.5) flips from the worst
(37.9%, −0.166R at baseline) to floor-beatable with wide stops —
49.6%/+0.091R (0.50σ), 50.8%/+0.119R (0.60σ — CLEARS the 50.5% floor),
49.8%/+0.102R (0.70σ).**  Next candidate: a depth-window × wide-stop
combo (depth 1.5-2.5 × 0.60σ stop), not the full book.

**Session-hour gate on the band (2026-08-12, 6-month window,
`InpSessionHourStart/End`, default 0/24 = OFF — the sniper's proven UTC
12-24h edge applied to the band):** the tester reports server→UTC
offset 0, so bar hours ARE UTC hours here (apples-to-apples with the
Python corpus's gmtime).

| geometry | gate | n | hit | exp gross | net@0.05 | floor gap |
|---|---|---|---|---|---|---|
| RR 3.0 (default) | none | 1,537 | 25.4% | +0.016R | −0.034R | −4.6 |
| **RR 3.0** | **UTC 12-24** | **846** | **26.6%** | **+0.063R** | **+0.013R** | **−3.4** |
| RR 1.2 | none | 1,932 | 39.4% | −0.132R | −0.182R | −11.1 |
| RR 1.2 | UTC 12-24 | 1,024 | 41.3% | −0.091R | −0.141R | −9.2 |

**The hour edge helps the band — most at RR 3.0, and it flips the
shallow subset floor-beatable.**  At RR 3.0 the gate cuts trade count
45% (1,537 → 846) and lifts expectancy 4× (+0.016 → **+0.063R**),
turning net@0.05 positive (+0.013R) — the first positive-cost cell on
the default geometry.  The depth-split cells now CLEAR their floors:
depth ≤1.25 → hit 40.0% vs 30.0% floor (exp **+0.600R**, n=35); ≤1.50 →
30.9%/+0.235R; ≤2.00 → 30.3%/+0.212R; ≤2.50 → 30.2%/+0.207R — only the
full population (26.6%) still misses by 3.4pp.  This revises the
earlier "depth-cap HURTS at RR 3.0" claim: cap + session hour together
DO clear the floor.  At RR 1.2 the gate lifts hit 39.4 → 41.3% but the
−9.2pp floor gap remains (expectancy still negative).  Caveat: single
6-month window; the gate removed mostly deep (>2.5) entries — the same
bucket the wide-stop test flagged as the drag.

**Time-exit + UTC-entry filter ported end-to-end (2026-08-12, 6-month
window) — does the Python harness's +0.14R edge hold on the MQL5 band
leg?**  `InpExitMode=1` (TIME) + `InpSessionHourStart/End` + the NEW
`InpMaxRangeZ` filter (|range_z_50| — z of the current M5 range vs the
prior-50 range window, population std, faithful to indicators.py
zscore; 0 = OFF):

| config (band, RR 3.0 unless noted) | n | hit | exp gross | net@0.05 | CI |
|---|---|---|---|---|---|
| TIME@1h alone (no filters) | 1,355 | 15.1% | +0.125R | +0.075R | PASS |
| **TIME + UTC 12-24 + rz<1.0** | **574** | **13.1%** | **+0.094R** | **+0.044R** | PASS |
| TIME + UTC 12-24 (no rz) | 756 | 13.0% | −0.013R | −0.063R | PASS |
| TIME + UTC 18-24 + rz<1.5 | 350 | 12.3% | −0.127R | −0.177R | FAIL (shallow 0%) |
| TIME + 12-24 + rz<1.0 @ RR 1.2 | 615 | 12.7% | −0.050R | −0.100R | FAIL (shallow −0.71R) |

**Python reference (sniper leg, same combo): n=149, hit 50.3%, +0.142R
gross / +0.092R net@0.05.**

**Verdict: the direction and the rz mechanism replicate, the magnitude
does not.**  The |range_z|<1.0 filter's contribution REPRODUCES exactly
the Python pattern — it flips the session-filtered TIME leg from
−0.063R to +0.044R net@0.05 (+0.107R/trade), confirming the port's
fidelity.  But the full +0.14R edge does NOT transfer: the ported combo
lands at +0.044R net@0.05 — roughly half the Python's +0.092R — and is
WORSE than the band's own unfiltered TIME@1h (+0.075R net@0.05,
+101.6R total vs +25.3R total; the session+rz filters cut trade count
58% and diluted the band edge).  The Python edge is sniper-leg-specific
(ML-scored entries, ~50% hit at the 1h horizon); the band leg in TIME
mode is a different population (~13% hit, ~87% stop-outs) whose edge
lives in the DEEP bucket (cell A: deep exp +0.132R, sumR +49.7R — the
1h TIME exit converts the deep fades' +2.7-3.0R median MFE into
realized gains, the opposite of TARGET mode where deep is the drag).
RR 1.2 and the 18-24h window are both negative in TIME mode on the
band.  **Band's best stays TIME@1h, no entry filters.**

**Shallow-fade + TIME-exit hypothesis DISPROVEN at RR 3.0 (2026-08-12,
seed 42, 6-month):** asked whether the shallow <=1.50 bucket's positive
TARGET-mode expectancy clears the 30% floor under the 1h TIME exit.
Measured: shallow <=1.50 hit CRASHES 26.3% -> 13.9% (floor gap -3.7pp
-> -16.1pp) while exp barely moves (+0.053R -> +0.062R); overall
verdict flips to `hit 15.1% does NOT beat the 30.0% floor`.  In TIME
mode exp rises MONOTONICALLY with depth (+0.014R at <=1.25 -> +0.229R
at <=3.00) — the 1h exit realizes the deep fades' large MFE, the
shallow fades are the weakest bucket (mirror of TARGET mode).  The 30%
floor is structurally un-beatable in TIME mode: ~14-16% positive-R
closes would need a ~9R planned geometry (1/(1+RR)+5% = 15%) — no RR
makes the current TIME-mode hit clear its own floor.  Full
TARGET-vs-TIME depth table recorded in the README.

**svcap ported to the tester as a forward-test candidate (6-month SYN75
window, 2026-08-12):** the sniper's full svcap configuration is now a
first-class tester config — `InpMaxGarchZ` (new input; |garch_z_score|,
the entry bar's log-return over the post-update conditional EGARCH sigma
— Python `arch_garch.update`'s `z_score = log_return / current_sigma`,
faithful including the current bar's own return) joins the already-ported
TIME exit, UTC 12-24h and |range_z|<1.0:

| config (all TIME exit) | n | hit | gross | net@0.05 | maxDD | CI |
|---|---|---|---|---|---|---|
| UTC 12-24 + rz<1.0 @ RR 3.0 (no gz) | 574 | 13.1% | +0.094R | +0.044R | — | PASS |
| **svcap (gz<=1.5) @ RR 3.0** | **450** | **13.3%** | **−0.082R** | **−0.132R** | **71.3R** | FAIL (shallow −0.455R) |
| UTC 12-24 + rz<1.0 @ RR 1.2 (no gz) | 615 | 12.7% | −0.050R | −0.100R | — | FAIL (shallow −0.71R) |
| **svcap (gz<=1.5) @ RR 1.2** | **478** | **13.8%** | **+0.054R** | **+0.004R** | **44.2R** | FAIL (shallow hit 0%) |

**The garch-z depth cap is geometry-dependent on the band leg — and the
sniper's svcap edge does NOT transfer.**  At RR 3.0 the cap HURTS: it
filters 5,035 candidate bars (diag gzskip) and removes exactly the
deep-extension entries the 1h TIME exit converts into gains (deep exp
flips +0.132R → −0.218R, sumR −63.8R), flipping the leg from +0.094R to
−0.082R gross.  At RR 1.2 the cap HELPS: mid-depth (1.5-2.5) concentrates
the edge — n=127, hit 18.1%, **+0.334R**, sumR +42.4R, maxDD 20.5R — and
the leg goes −0.050R → +0.054R gross (net@0.05 −0.100R → +0.004R,
breakeven), maxDD 44.2R vs the RR-3.0 cell's 71.3R.  Either way the band
leg in TIME mode stays a ~13-14% hit population vs the 50.5% (RR 1.2)
/ 30.0% (RR 3.0) floors, so the Stage-3 gate correctly stands aside at
both geometries; the mid-bucket +0.334R cell is the sharpest positive
subset measured on the band in TIME mode but is not itself gate-clean.
The Python svcap edge (52% hit, +0.160R net@0.05) remains sniper-leg-
specific — ML-scored entries on a different population — and this port
confirms the filters alone do not transplant it.

**Forward-demo paper pass (started 2026-08-12 ~02:50 UTC) — UTC 18-24h
& |range_z_50|<1.5 on the LIVE sniper leg, 30-trade target:**
`mql5/forward_demo_pass.py` runs `run_live_paper` (venue=MT5,
`Mt5TickClient` on the Deriv terminal — MT5-first, paper fills via
SimulatedExecutionBackend, NO orders ever sent) with the R_75
`SymbolProfile` entry gate overridden to UTC [18,24) & |range_z_50|<1.5
(the strongest measured cell: n=67/hit 58.2%/+0.242R@RR1.2 backtest,
+0.141R net@0.05 harness).  Journal:
`journals/forward_demo_18_24.jsonl`; log:
`.freebuff/forward_demo_18_24.log`.  The loop runs 3h chunks with
restart-on-crash, counts `type=outcome` records, stops at 30 closed
trades (~6 days at the measured ~5/day); hard cap 7 days.

**Two live-path fixes this pass required (both now in the code):**
(1) `Mt5TickClient._connect` REUSES the running terminal's session when
no credentials are configured (`account_info` populated) instead of
crashing on `int(None)` — the terminal is the source of truth for what
it's connected to; credentialed behavior is byte-identical when
credentials ARE set.  Verified live: `reusing running terminal session
(5098680@DerivSVG-Server-03)`, init 2ms, no login round-trip.
(2) `run_live_paper` now passes the remaining run duration as the tick
stream timeout — `Mt5TickClient.subscribe_ticks`/Deriv default is a 20s
batch, so `duration_sec` chunks previously ended after one batch and the
candle warmup never accumulated past its seed (every evaluation skipped
"need 30 candles"); the stream now lives as long as the session.

**Status as of launch (UTC ~02:50):** one clean instance, first 3h
chunk, 30+ candles built, journal recording the gate firing correctly
(`"entry gate: UTC hour 2 outside [18, 24) window"`) — no trades until
18:00 UTC as configured.  Progress: `grep -c '"type": "outcome"'
journals/forward_demo_18_24.jsonl`.  Caveats: the Deriv terminal
must stay running/logged in (the pass reuses its session); each chunk  starts a fresh online model (matches the backtest's fresh-model-per-run
  methodology); the single-flight guard serializes terminal init against
  the scheduled collector.

**Server-clock consistency fix (2026-08-12):** the pass's journal exposed a
3h clock skew — Deriv server time = local UTC+3h (measured exactly
+10800.9s; backfill corpus epochs are server-time, matching file mtimes to
the second).  `subscribe_ticks` stamped live ticks with `time.time()` while
the warmup used `time_msc`, so live candles ran 3h behind warmup candles:
non-monotonic journal epochs, a stuck "need 30 candles" buffer, and a gate
that would fire 3h late vs the server-time backtest cell.  Fixed by
stamping subscribe ticks with `time_msc` (fallback only when 0) + widening
the tick_store future-junk guard to +4h.  Verified monotonic on the server
clock; the pass now fires when server hour ∈ [18,24) = local 15:00-21:00,
exactly reproducing the backtest cell.  Regression test:
`test_subscribe_ticks_stamps_terminal_clock_not_local`.

**Time-exit exit mode ported to the tester + 6-month backtest (2026-08-12):**
`BandBackTests` gains `InpExitMode` (0 = TARGET default; 1 = TIME) — the
Python time-exit policy (exit at the 1R stop or the hold-horizon close,
target ignored, trail disabled — mirrors the harness
`TimeExitCapturePaperBroker`).  6-month backtest (SYN75 M5):

| exit | hold | n | hit | exp gross | total gross | tot net@0.05 | tot net@0.10 |
|---|---|---|---|---|---|---|---|
| TARGET | 1h | 1,537 | 25.4% | +0.016R | +24.6R | −52.3R | −129.1R |
| **TIME** | **1h** | **1,355** | **15.1%** | **+0.125R** | **+169.4R** | **+101.6R** | **+33.9R** |
| TIME | 2h | 1,245 | 13.3% | +0.005R | +6.2R | −56.0R | −118.3R |
| TIME | 3h | 1,160 | 12.8% | +0.017R | +19.7R | −38.3R | −96.3R |

**TIME@1h is the first clearly positive cell on the 6-month window** —
+0.125R/trade (~8× TARGET's +0.016R), +101.6R total net@0.05, still
+33.9R at 0.10 cost; exit mix 86% stop / 0% target / 14% time.  The 1h
horizon optimum on the MQL5 band leg differs from the Python UTC-gated
sniper leg (3h there) because the ungated band leg is ~70% deep
extensions whose drift mean-reverts within ~1-2h (2h → +0.005R), while
the Python leg's gated shallow entries carry a longer-lived drift; the
mid-depth fades carry the TIME edge at 1h (+0.335R).  The depth-split CI
is now exit-mode-aware ([5,60] hit band for TIME runs — TARGET's
[15,60] false-failed every TIME cell since positive-R closes run
~13-15% by design); unit fixtures + end-to-end PASS verified.

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

**Real-corpus cross-validation (2026-08-12):** `phase6_real_corpus_check.py`
— the stateful replay the stateless mirror couldn't do, same pattern as the
Phase-2/3 harnesses.  Real R_75 M5 bars (2378 / 198h) → 2078 deterministic
signals → both engines consume the same Python-driven lifecycle.
`--mode aligned` (shared gates at RiskConfig values): **100%** on veto
agreement, stake parity and per-event stateful parity (streak / daily-dd /
open counts / day-start), with per-gate veto tallies identical gate-for-gate.
`--mode defaults` (Constants vs RiskConfig): 81.4% agreement, the 386
residuals 100% attributed to config drift — Python stricter (daily loss 2%vs 5%, consecutive 4 vs 5), MQL5 adds caps Python lacks (trades/day 10,
  trades/hour 3, WEAK-verdict veto).  Machine lines `[PHASE6-REAL]` are wired
  into `verify_all.ps1` as the `RealCorpus` gate (2026-08-15): aligned mode
  must stay at 100% veto/state/stake parity or the scheduled loop FAILs.
  Carry-into-Phase-7 notes: the consecutive-loss breaker is a
per-day hard lock (nothing but a session-day roll re-arms a locked streak),
and Python's `sync_session_day` primes lazily — consumers must call it before
the first day change or the first daily reset is skipped.

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

**Status (2026-08-12):** all six files landed; `Tests/Phase7Tests.mq5` compiled
clean in MetaEditor (0 errors, 0 warnings) and ran green in the real Strategy
Tester on SYN75: **119 passed, 0 failed, SUITE PASSED**.  `verify_all.ps1`
discovers the suite automatically (`Tests/*Tests.mq5`), so Phase 7 is already
part of the one-command loop.

Design notes worth carrying forward:

- **Transport injection.**  Every order path runs through `CTradeInterface`
  (Buy/Sell/Modify/Close + retcode + position-verification hooks).  Production
  binds `CTradeAdapter` (real CTrade); the tester binds `MockTrade` with
  scripted retcodes — so the mocked-retcode gate (rejection, invalid stops,
  volume errors, margin, verify-fill failure) is exercised headless, and the
  SAME engine code runs against the live broker unchanged.
- **MQL5 gotchas discovered:** (a) this build's `CTrade::PositionClose(ticket,
  deviation)` takes a ulong DEVIATION — partial closes live in
  `PositionClosePartial`, and the adapter dispatches on volume; (b) MQL5
  forbids reference chaining (error 229) and reference return types, so the
  transport is injected by POINTER and position state is exposed via narrow
  accessors, not object references.
- **Never-assume-success is enforced twice:** `OrderManager` verifies the fill
  exists in the position table after a DONE retcode (and that a close actually
  removed it); `ExecutionEngine` runs the spread guard, price sanity,
  stops-level, and min-RR checks BEFORE the transport is ever touched.
- **Closed-candle grace is in `PositionManager` by construction** — it only
  evaluates closed bars of the execution timeframe, so the forming bar's wicks
  can never stop out a plan (band same-bar semantics: on a bar that both arms
  the trail and dips through entry, the stop is evaluated at the newly-armed
  entry — parity with `BandBackTests`).

**Real-corpus cross-validation (2026-08-15):** `phase7_real_corpus_check.py`
— the same stateful-replay pattern as the Phase-2/3/6 harnesses, applied to
EXECUTION.  Real R_75 M5 bars (2603 / 217h) → 2303 deterministic RR-1.2
signals → the MQL5 Execution mirror (ExecutionEngine gates +
PositionManager lifecycle) vs the REAL production `SimulatedExecutionBackend`
(the backend `paper_runner.py` journals).  Two modes:

- **Aligned** (gates off, wick exits, no trail, 1h time exit): **100% parity on
the 1012 traded entries** — identical entry bar, exit reason, exit price and
realized R; the exit-reason split matches exactly (577 STOP / 427 TARGET /
8 TIME).  The min-RR 1.2 float boundary (the Phase-6 footgun) agrees too: 972
signals below 1.2 on BOTH sides, 0 disagreement.
- **Defaults** (Python wick/no-trail vs MQL5 closed-candle + BE trail + gates
on): the honest divergence.  Execution gates veto 997/2303 — 957 of them the
min-RR 1.2 float boundary (Python would submit all of them), 31 spread-guard
(real corpus spreads), 9 price-sanity; the band's full production floor
(min_rr 2.0) rejects ALL RR-1.2 signals by design.  On the same approved entry
set the Python journal (wick, no trail) books **−84.8R over 764 trades** while
MQL5 (closed-candle + trail) books **+102.2R over 727 trades**: the grace
spared 201 wick-stops and the BE trail converted 259 −1R losses to scratch —the exact exit-policy edge Phase 7's management layer adds over the Python
  journal.  Machine lines `[PHASE7-REAL]` are wired into `verify_all.ps1` as
  part of the `RealCorpus` gate (2026-08-15): aligned parity must stay 100%
  with 0 min-RR boundary disagreements, and the defaults-mode management
  edge must hold (`sumR_mq > sumR_py` and grace+trail conversions > 0) or
  the scheduled loop FAILs.

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

**Status (2026-08-15):** all six files landed (`Journal/TradeJournal.mqh`,
`Journal/DecisionLogger.mqh`, `Journal/PerformanceLogger.mqh`,
`Analytics/PerformanceAnalytics.mqh`, `Analytics/ExpectancyEngine.mqh`,
`Analytics/RegimeAnalytics.mqh`); `Tests/Phase8Tests.mq5` compiled clean in
MetaEditor (0 errors, 0 warnings) and ran green in the real Strategy Tester on
SYN75: **87 passed, 0 failed, SUITE PASSED**.  The suite round-trips the §33
CSV (write → close → reopen → read back, header not duplicated), exercises the
DecisionLogger ring + counts, checks the PerformanceLogger incremental
aggregation against a hand-computed sequence (max-DD 4.0R on the cumulative-R
curve, PF 0.75, streaks 2/2), verifies PerformanceAnalytics.Metrics agrees
with the logger and every split (strategy/regime/direction/exit/confidence
bucket), locks the stage3_gate break-even floor math (1/(1+RR)+margin, clamps,
fallback), and validates RegimeAnalytics per-regime breakdowns.

Design notes: (a) `FILE_CSV`'s auto-quoting of delimiter-bearing strings is
unpredictable in the Strategy Tester sandbox, so the journal writes FILE_TXT
with hand-built rows (fields are comma-free tokens; `CsvEscape` in
`Constants.mqh` sanitizes any reason string); (b) MQL5's reference
restrictions (error 229 — no local reference variables, no reference return
types) apply to analytics structs too, so all aggregation is copy-based;
(c) the confidence-bucket split takes a parallel confidence array so the
STRONG-vs-WEAK discrimination question is directly answerable from any
journal.

**Gate wiring (2026-08-15):** `phase8_analytics_check.py` joined `verify_all.ps1` as the `Phase8Gate` Python contract row — its band replication must MATCH the CLI `backtest-vol --mode band` parity, and the floor verdict + bucket/exit split machine lines are parsed with partition/consistency checks (strong+weak == n, stop+trail+target+time == n, floor in [10,60], beats consistent with n>=min_samples AND hit>=floor).  `-SkipPhase8Gate` opts out; both branches verified end-to-end on 2026-08-15.

### Phase 9 — UI — BUILT 2026-08-15

| File | Contents |
|---|---|
| `UI/Panel.mqh` | object-lifecycle foundation: bounded named registry, lazy one-time creation, headless text cache, per-object teardown |
| `UI/Dashboard.mqh` | the §34 block: SYMBOL / MODE / REGIME / HTF BIAS / STRUCTURE / VOLATILITY / STRATEGY / SETUP SCORE / EXPECTED RR / DECISION / RISK / SL / TP / OPEN POSITIONS / TODAY / DRAWDOWN / REASON + hard-halt banner |
| `UI/VisualSignals.mqh` | reason-coded chart markers: entry/exit arrows, SL/TP/BE HLINEs, structure/liquidity markers, regime-change VLINEs (64-slot bounded ring) |

**Phase gate (PASS):** MetaEditor compile 0 errors / 0 warnings; `Tests/
Phase9Tests.mq5` green in the Strategy Tester on SYN75 — **94 passed, 0 failed**,
including the object-count tester gate (registry bounded + stable across
thousands of updates, identical across generations, all registries empty after
teardown; real ObjectCreate attempts capped).  Findings that shaped the gate:
the tester never releases chart objects mid-pass (auto-cleans at pass end), so
the leak contract is registry-level with per-object delete correct for live
terminals; this build's `OBJPROP_TIME` is an integer property; MQL5 forbids
in-class `static const` members (layout uses `#define`).

### Phase 10 — Integration (`MitemshubAI.mq5`) — WIRING PLAN (draft, awaiting approval)

Wires every built module into one EA.  The tester is the authority; nothing
new is invented — every call below is an existing, tested Phase 1-9 API.

**New files:**

| File | Contents |
|---|---|
| `MitemshubAI.mq5` | the EA: OnInit/OnTick/OnTimer/OnDeinit orchestration (~500 lines) |
| `Market/BarAggregator.mqh` | tick → closed-bar bucketter (execution TF; wall-clock, same convention as the Python candle builder) |
| `Market/GarchForecaster.mqh` | the EGARCH(1,1) estimator extracted from `BandBackTests` (InpGarchMode 0 = online-SGD port, 1 = calibrated fixed omega/alpha/gamma/beta) — the EA cannot depend on a test suite |

**OnTick pipeline (closed-candle discipline — the only place signals fire):**

```
OnTick():
  1. capture bid/ask/spread (SymbolInfoDouble/Integer)
  2. BarAggregator(bid, time) → on a CLOSED execution bar:
     CandleEngine.PushBar(tf, o, h, l, c, t)          # exec TF + HTF (TimeframeManager.SetTimeframes)
     if exec bar closed:  run steps 3-15 ONCE per bar
  3. GarchForecaster.update(log_ret) → sigma_t; sigma_ema(30); prev_sigma
  4. VolatilityEngine.OnBarWithPrevClose(prev_close, h, l, c) → ATR, ATRPercentile
  5. RegimeEngine.Classify(closes[], REGIME_LOOKBACK, atr_percentile, atr_ratio)   # CandleEngine.GetCloses
  6. StructureEngine.Update(ce, setup_tf, atr) → Bias() + last event
  7. StateManager.SetRegime(regime, conf)
  8. BAND ENTRY GATE (replication contract — must match BandBackTests exactly):
       vol_extended = prev_sigma > 1.3 × sigma_ema
       z = ln(close / ema20) / prev_sigma;  |z| ≥ 1.0 → direction
       depth = |z| / z_entry → setup_q (0.20..1.00), edge-depth cap check
       BandContext ctx{entry, direction, prev_sigma, bar_sec=300, hold_sec=3600,
                       stop 0.20σ, target 0.80σ, min_rr 2.0, max_stop 0.015}
       cand = CStrategyEngine::Evaluate(STRATEGY_BAND, ctx)   # WAIT unless gates met
  9. DECISION: composite = CScoringEngine::Evaluate(cand, regime, -1, -1, sb)
       signal = CConfidenceEngine::Gate(composite, setup_q, true, is_long, -1, 0, 5000, min_conf)
       blended = CConfidenceEngine::BlendConfidence(composite, setup_q)
       StateManager.SetDecision(decision, reasons, score, blended, rr, STRATEGY_BAND)
 10. STAGE-3 FLOOR (walk-forward, no lookahead):
       CTradeQualityEngine::Statistics(STRATEGY_BAND, ...) → floor vs hit
       → still_learning / proven / suppressed  (BandBackTests semantics)
 11. RISK: verdict = CRiskEngine::Evaluate(cand, empirical_scale, vol_min, vol_max,
       vol_step, tick_value, tick_size)                 # SymbolAdapter specs
       if hard limit breached → StateManager.SetHardHalt(true) → EMERGENCY banner
 12. EXECUTE: ok = m_exec.Execute(cand, verdict, spec, bid, ask, log)   # never assume success
       on ok: CTradeQualityEngine::StartPosition(cand, entry, t); StateManager.SetOpenPosition(ticket)
 13. JOURNAL: TradeJournal.Append(row); DecisionLogger.Add(...); PerformanceLogger.OnTrade(...)
 14. DASHBOARD: CDashboard::FromStateManager(state, symbol, st) → fill depth/score/vol → m_dash.Update(st)
 15. SIGNALS: on entry → m_signals.DrawTrade(dir, t, entry, sl, tp, be); structure/regime events → Add(...)

OnTimer (once per bar while a position is open) — POSITION MANAGEMENT:
  m_exec.ManageBar(high, low, close, bar_open_time, bar_sec, exit_price, res, partial)
    → EXIT_* reason (STOP/TARGET/TIME/BREAKEVEN_TRAIL, closed-candle only)
    → TQE.UpdatePosition(h, l) every bar; TQE.ClosePosition(exit_price, reason, ...)
    → TradeJournal.Append(outcome); StateManager.SetOpenPosition(0); dashboard; exit marker

OnDeinit: journal close; Dashboard.DestroyAll(); VisualSignals.ClearMarkers();
```

**Safety invariants:** live execution locked (`InpLiveTradingEnabled=false`);
`ENGINE_MODE_BACKTEST` default; hard halt is absolute (no code path overrides);
research strategies stay disabled (`ResearchEnabled()=false`); every order path
verifies the fill before recording.

**Phase-10 cross-validation gate — exact Strategy Tester config matrix.**
Each row is one tester run (TestModel=1 “every tick based on real ticks”,
Deposit=10000 USD, Leverage=1:500, Optimization=0) plus its contract.  The
reference numbers come from the Python harnesses on the same corpus:
`phase8_analytics_check.py` (band replication + analytics) and the phase7
real-corpus harness (management/execution parity).  The tester window must
overlap the Python corpus; if the terminal lacks history, the window shrinks
and the gate compares only the overlapping days (machine line carries both).

| Run | Symbol | TF | Window | Inputs | Contract |
|---|---|---|---|---|---|
| P10-A aligned | SYN75 | M5 (300s) | 2026.07.30→2026.08.16 | calibrated band defaults (z 1.0, vol 1.3, stop 0.20σ, target 0.80σ, hold 3600s, trail 0.3, min-revert 0.02, depth cap off, mode-0 seeded with the ANCHORED r_75.json: omega −1.8841, alpha 0.1422, gamma −0.0733, beta 0.8527) | STRICT (corpus ≥80% dense): trades Δ≤10, hit ±5pp, sumR sign, floor verdict.  Reference RE-BASELINED 2026-08-17 to aligned mode (permissive risk `--max-consecutive-losses 9999 --max-daily-loss-frac 1.0` — the EA approves every signal, so the CLI reference must too): **accepted pair EA 98 vs CLI 102 (Δ4), both NEGATIVE — PASS** |
| P10-B @60s | SYN75 | M1 (60s) | same | same (bar_sec 60) + Python default risk (consec 4, daily 2%) | parity with the Python 60s band run — **DONE 2026-08-16: EA 238 trades / 10.08% / −38.8 sumR vs CLI 226 / 9.73% / −37.5 (rejected 364)** |
| P10-C management on — DONE 2026-08-16 | SYN75 | M5 | same | + trail 0.3, closed-candle exits | mirrors phase7 defaults-mode contract: MQL5 sumR > Python wick-journal sumR; grace+trail conversions > 0 — contract PASS (harness sumR_mq +256.86 > sumR_py −29.99, grace 400 + trail 567); EA grace=ON run emits 98 trades / 58 trail exits / 0 vetoes |
| P10-D R_100 | SYN100 | M5 | same | calibrated R_100 (`r_100.json`) | sign agreement with Python R_100 band (expected negative — the gate locks the SIGN, not a win) |

**P10-B finding — the EA's risk breakers were dead (fixed).**  The first 60s
run fired 523 trades / 0 vetoes because outcomes were never registered
(no RegisterOpen/RegisterOutcome/RegisterClose, equity pinned to 10000 each
bar), so consecutive-loss / daily-loss / equity-DD limits could never trip.
P10-A masked it at 300s (Python rejected 14/104; the EA's 0 vetoes passed the
Δ≤10 tolerance).  Fixed: exit registers outcomes (pnl = stake × return_r),
tracked equity, exposure cleared on close, and the Evaluate reason chain now
has the `> 0` guards (a 0 limit = disabled, not "veto everything").  After
the fix the EA at 60s with Python's default risk produced 238 trades / 10.08%
/ −38.8R vs the CLI's 226 / 9.73% / −37.5R — parity (Δ trades 12, Δ hit
0.35pp, sumR both negative).  P10-A strict gate re-verified PASS (EA n=97
vs CLI n=90, vetoes 0).

**R_100 calibration re-check (2026-08-16, before Phase 10):** the on-disk
`r_100.json` (Aug 8) was a DEGENERATE fit — alpha=0.001 at its optimizer
floor, beta=0.111, persistence 0.112 — and `load_calibrated_garch_state`
rejected it, so every R_100 backtest and the live assembler had been running
UNcalibrated while R_75 used its params.  Re-fit on the full 16.8-day
backfill corpus (frozen snapshot, 60s bars — the same convention as
`r_75.json`): **omega=-1.8412, alpha=0.1345, gamma=-0.0374, beta=0.8557**
(persistence 0.990, NLL -74423, converged, deterministic).  The fit's
NLL is ~19-69 units BETTER than the degenerate mode — R_100 has the same
vol-clustering structure as R_75; the Aug-8 degenerate file was a local-min
artifact of the multi-start set, not a property of the data.  Two fixes
landed in `models/garch_calibration.py`: (1) `fit_egarch(initial_params=...)`
crashed with UnboundLocalError (sample_var not computed on that path) —
fixed + regression tests; (2) an explicit high-persistence anchor
`(-2.0, 0.10, 0.88, -0.04)` was added to the multi-start guesses so the
winner is chosen by NLL and corpus growth can no longer flip the fit to a
worse local optimum.  (3) 2026-08-16 — the winner selection is now
DEGENERACY-GATED: every candidate (L-BFGS-B multi-start and the DE
fallback) must pass the same `_params_at_bounds` predicate — bound-pinned,
no-clustering, or absurd-NLL (optimizer blow-up) basins can never win, even
with the best raw NLL.  Measured on the repaired full-density R_100 corpus:
the bound-pinned basin (alpha/beta at floors, NLL best) is now returned
only as a convergence=False fallback and the loader falls back to default
priors instead of seeding a broken fit.

**P10-D reference (band on R_100, 300s, repaired full-density corpus):**
calibrated **-0.591R expectancy, 81 trades, 3.70% hit, net -254.51**
(`calibrated_garch=loaded`, fresh `r_100.json` — params omega -1.8412 /
alpha 0.1345 / gamma -0.0374 / beta 0.8557 preserved, diagnostics
regenerated with the honest long_run_vol/vol_ratio computation).  The number
was updated from the sparse-corpus reference (-0.619R, 44 trades) after the
repair; the SIGN is robustly NEGATIVE under both.  The MQL5 P10-D tester
must use the fresh params above.

**Four-leg head-to-head on R_100 @300s (repaired corpus, realistic costs
slip 0.05 / penalty 0.10, 2026-08-16) — the updated four-leg reference:**

| leg | trades | hit | expectancy | net PnL |
|---|---|---|---|---|
| vol-band (P10-D reference) | 81 | 3.70% | **-0.591R** | -254.51 |
| vol-reversion (fade) | 41 | 51.22% | -0.198R | -51.32 |
| vol-momentum | 199 | 33.67% | -0.019R | -48.60 |
| sniper (reference) | 262 | 46.95% | -0.029R | -60.23 |

All four legs are NEGATIVE on R_100 at 300s; the band is the sign-lock
reference the P10-D gate contracts against.  Command: `backtest-vol --csv
data/backfill/R_100_ticks.csv --symbol R_100 --timeframe 300 --mode band
--compare`.

**P10-D row RUN (2026-08-16) — PASS (sign-lock confirmed).**  The integrated
EA on SYN100 M5 over the same 17.4-day window (tester cache, mode-0 seeded
with the fresh R_100 params): **trades=106, hit=0.94%, sumR=-53.741,
floor 25.0% NOT_BEAT, vetoes/rejects=0** — vs the Python R_100 band reference
on the repaired corpus (trades=81, win_rate=3.70%, expectancy=-0.591,
calibrated loaded).  Both sums NEGATIVE -> the P10-D sign contract holds.
The 106-vs-81 trade gap is the same data-source mismatch as P10-A (SYN100
tester cache full-density vs corpus); P10-D locks the SIGN, not trade parity.

**P10-D row RUN on R_75 (2026-08-16) — PASS (sign-lock confirmed).**  The
integrated EA on SYN75 M5 over the same 17-day window (tester cache, mode-0
seeded with the ANCHORED R_75 params as defaults): **trades=98, hit=1.02%,
sumR=-36.964, exits stop 39 / trail 58 / target 1 / time 0, floor 25.0%
NOT_BEAT, vetoes/rejects=0** (init confirms omega -1.8841 / alpha 0.1422 /
gamma -0.0733 / beta 0.8527 — identical to the CLI's regenerated
`r_75.json`) — vs the Python R_75 band reference on the repaired corpus
(trades=87, win_rate=1.15%, expectancy=-0.376, calibrated loaded).  Both
sums NEGATIVE -> the P10-D sign contract holds, the mirror of the R_100
half (106 / -53.741 vs 81 / -0.591R).  The 98-vs-87 trade gap is the
same corpus-density mismatch (93.3%) as P10-A; P10-D locks the SIGN, not
trade parity.  **Resolved 2026-08-17:** the strict reference was re-baselined
to the anchored fit in aligned mode (permissive risk), so the accepted pair
is EA 98 vs CLI 102 (Δ4 ≤ 10, STRICT PASS) — see the P10-A row note for the
finding (the Δ11 came from the reference's default-risk halts vetoing ~16
signals, not the density gap, and full-density backfill is impossible: the
interior 11:00-UTC holes exist in the terminal's own M1 history and the
corpus edges are real data boundaries).  Command: `verify_all.ps1
-Suite Phase10IntegrationTests -Symbol SYN75 -RangeDays 17
-SkipPhase10R100Gate` (plus the gate-skip flags for a focused row).

Command: `verify_all.ps1 -Suite Phase10IntegrationTests -Symbol SYN100
-RangeDays 17 -Inputs "InpGarchMode=0;InpGarchOmega=-1.8412;
InpGarchAlpha=0.1345;InpGarchGamma=-0.0374;InpGarchBeta=0.8557"` (Python
gates skipped).

| P10-E OHLC stress — DONE 2026-08-16 | SYN75 | M5 | same | TestModel=2 (1-min OHLC) via new `-TestModel` override (suite loop only; risk gate + seed sweep stay Model=1) | **DIRECTION FLIPPED — row criterion NOT met:** real ticks n=98 −36.964R / 1.02% hit → OHLC n=96 **+55.502R** / 30.21% hit, same inputs, same config (verified: 19,039 OHLC ticks vs 97,200 real ticks, 4,860 bars both). The OHLC model only sees 1-min bar closes, so wick stop-outs vanish and the 4.0σ target becomes reachable — i.e. OHLC implicitly applies closed-candle grace to ALL exits. This is the honest finding: the band's negative real-ticks result is model-true, and the flip quantifies the grace's potential if ever applied to stops. Object-count gate (Phase9Tests) green 0/0 in the full loop; EA state stable (96 vs 98 trades) |
| P10-F walk-forward — DONE 2026-08-16 | SYN75 | M5 | two halves: 08.01–08.08 IS, 08.09–08.15 OOS (boundary Aug 9 00:00 UTC) | same default VolBandConfig, NO changes between halves, realistic costs + anchored R_75 calibration | PASS — OOS sign matches IS sign (IS n=57 −0.542R NEG, OOS n=59 −0.282R NEG); boundary-robust across Aug 8/9 ±12h (4/4 splits both NEG) |

**Gate wiring (verify_all.ps1 `Invoke-Phase10Gate`) — IMPLEMENTED 2026-08-16.**
Parse the `[PHASE10]` machine lines from the tester log (last-run isolation);
run the CLI `backtest-vol --mode band` reference on the R_75 corpus; compute
the corpus M5-bucket density.  The contract is DATA-AWARE (see the P10-A
finding below): internal consistency + a RATE guard always; the STRICT
parity contract only when the corpus is ≥80% dense.  `-SkipPhase10Gate`
opts out; the gate row only runs when `Phase10IntegrationTests` is among the
invocation's suites (else SKIP, like SeedSweep).  Both branches verified:
PASS (rate 1.86 within band) and FAIL (RATE GUARD / STRICT trips).

**Corpus repair — STRICT branch now ACTIVE (2026-08-16).**  The sparse tail
(Aug 6-16) was backfilled from the terminal's M1 history:
`python -m synthetic_trader.scripts.repair_corpus --symbol R_75 --backup`
merged 47,372 OHLC-exact ticks (4 per M1 candle) into the 2,369 missing M5
buckets, keeping every real tick.  Density 0.491 -> 0.935 (2,602 -> 4,968
buckets).  First STRICT run: `EA n=97 hit=2.06% sumR=-36.172 | CLI n=90
hit=2.22% exp=-0.309` — PASS (trades Δ7≤10, hit Δ0.16pp≤5, sign agrees).
Same-data parity now enforced: the EA no longer over-fires vs the corpus
(97 vs 90, was 93 vs 28 on sparse data).  Re-run the same command after any
future collector outage; the script only fills buckets with <4 ticks so it
never overwrites real data.

**Build order within Phase 10:** (1) ~~`GarchForecaster.mqh` + `BarAggregator.mqh`~~
**DONE 2026-08-15** — extracted, `Tests/Phase10Tests.mq5` green
(**620/0**): mode-0 sigmas locked against the REAL Python
`EGARCHVarianceForecaster`, mode-1 against a fixed-params replication
(`mql5/phase10_garch_reference.py`), aggregator semantics locked
(compile + unit tests against BandBackTests numbers); (2) ~~`MitemshubAI.mq5`~~
**DONE 2026-08-16** — the integrated EA builds 0 errors / 0 warnings, runs
the full pipeline in the tester, emits the `[PHASE10]` machine lines, and the
wrapper `Tests/Phase10IntegrationTests.mq5` is green in verify_all.ps1;
(3) ~~P10-A aligned~~ **LANDED 2026-08-16 with a documented finding** — the
engine matches Python on shared full-density days (EA 22 vs Python 23 on
Aug 1-5) but the corpus is ~50% sparse (Aug 6-16 has 17-145 M5 buckets/day)
while the tester cache is dense, so same-data trade-for-trade parity is
NOT enforceable until the corpus is complete; the gate therefore enforces
the data-aware contract (rate guard + internal consistency now, STRICT
parity automatically once density ≥ 80%).  **2026-08-17: corpus repaired to
93.3% density, STRICT active, and the strict reference RE-BASELINED to the
anchored fit in aligned mode** — the CLI reference now runs with permissive
risk (`--max-consecutive-losses 9999 --max-daily-loss-frac 1.0`, matching
the EA's 0-veto aligned config) so the accepted pair is EA 98 vs CLI 102
(Δ4 ≤ 10, both NEGATIVE) and the P10-A row is GREEN; the prior Δ11 was the
reference's default-risk halts (4-streak / 2% daily) vetoing ~16 signals,
and full-density backfill was ruled out (terminal M1 history has the same
interior holes; corpus edges are data boundaries); (4) P10-B..F; (5) ~~wire the gate
into verify_all.ps1~~ **DONE 2026-08-16** (the `Phase10Gate` row).
Estimated tester cost per row ~2-5 min (M5, 2-week window); the full matrix
~20-30 min.

**Phase gate:** compile 0/0; P10-A aligned passes (the cross-validation
contract); full matrix green or explicitly sign-locked; dashboard renders in a
visual pass.

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
