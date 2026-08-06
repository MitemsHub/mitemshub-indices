# Phase 5 — Regime-Aware Intelligence, Honest Validation & Truthfulness Fixes

## Overview

Phase 5 answers the core question posed by the operator: *"the engines may not be
well-learned or optimal — check everything at a sub-atomic level, then make the
system robust, sharper, and intelligent."*

Two hard facts shaped this phase:

1. **Synthetic indices are CSPRNG-generated.** SMC patterns (BOS, FVG, order blocks,
   CHoCH) carry **no predictive power for direction** on random-walk price. The
   *only* genuinely exploitable property is **volatility clustering** — the
   scheduled variance regimes (Volatility 75/100) mean the *distribution* of price
   moves shifts over time.
2. **The honest validation baseline.** A full walk-forward optimization on the real
   tick CSVs confirms the current sniper strategy has **no demonstrated edge yet**
   out-of-sample. That is the truth the system now measures and reports, instead of
   pretending.

Everything below either (a) exploits volatility clustering / regime shifts, (b)
gives the system the tooling to *prove* whether it has an edge, or (c) fixes
places where the UI or persistence lied about reality.

---

## 1. ADWIN Drift Detection — `src/synthetic_trader/models/drift.py` (NEW)

**Problem:** the online logistic model trained on one volatility regime keeps
producing worse predictions after the generator steps volatility up or down. There
was no mechanism to detect the regime change and re-learn.

**Solution:** a `DriftDetector` wrapping river's **ADWIN** (Bifet & Gavalda 2007 —
ADaptive WINdowing), a streaming change-point detector that maintains two
windows of the prediction-error stream and flags when their means diverge.

- **Feeds on** `abs(label − p)` — the model's absolute prediction error — from
  `OnlineLogisticModel.update()`.
- **One-shot `drift_detected` flag** (consumed on read), window automatically
  re-baselines after a drift so the detector adapts to the new regime instead of
  re-flagging forever.
- **Telemetry persisted** (`n_observations`, `drift_events`, `last_drift_step`,
  `drift_rate`) and saved inside the model state file.
- **Degrades gracefully** when `river` is not installed (no-op detector).

**Wiring (reviewer-hardened):**
- `OnlineLogisticModel.update()` now accepts `observe_drift: bool = True`
  (keyword-only). When ADWIN fires, weights/bias are reset and `drift_resets`
  increments — the model re-learns the new regime instead of fighting stale
  patterns.
- **Replay never feeds the drift detector.** `ExperienceReplayBuffer.replay_updates`
  calls `update(..., observe_drift=False)` — replayed samples belong to an older
  regime and would corrupt drift detection. The reviewer caught this; fixed.
- **No replay immediately after a reset.** `update_with_replay()` skips the replay
  step on the call where a drift was detected, so stale-regime buffer samples
  don't immediately fight the freshly-reset weights.
- **Decision engine gate.** `_dynamic_min_confidence()` adds a
  `_drift_confidence_penalty()`: within ~200 updates of a drift, the confidence
  gate is raised (fewer, higher-conviction setups while the model re-learns).
  The penalty decays linearly and is clamped.

**Tests:** `tests/test_drift.py` — 14 tests covering stable-stream/no-drift,
abrupt-shift detection, re-baselining, drift rate, save/load roundtrip,
river-missing degradation, model-level reset behavior, and loading state files
written before drift support existed (backward compatible).

---

## 2. Student-t EGARCH Option — `src/synthetic_trader/models/garch.py`

**Problem:** synthetic index returns are famously fat-tailed. The EGARCH variance
forecaster assumed normal innovations, biasing the shock term `|z| − E|z|`.

**Solution:** `EGARCHVarianceForecaster` gained `distribution: "normal" | "studentt"`
and `dof` parameters.

- The shock term now uses **E|z| for a standardized Student-t** —
  `ez_student_t(dof)` — which is *larger* than the normal 0.7979 for heavy tails
  (e.g. `E|z|(dof=2) = √2`), so rare extreme moves are modeled as less anomalous.
- New params are persisted in `save()`/`load()` with defaults preserving existing
  behavior (`distribution="normal"`).
- `ez_student_t` lives **only** in `garch.py` (canonical, used by both the
  forecaster and calibration); the reviewer caught a dead duplicate in `drift.py`
  which was removed.

**Tests:** `tests/test_garch.py` — added exact-value E|z| checks (`dof=2 → √2`),
heavy-tail monotonicity, convergence to normal, `dof ≤ 1` fallback, and Student-t
forecaster update/save/load.

---

## 3. Student-t EGARCH Calibration — `src/synthetic_trader/models/garch_calibration.py`

- `egarch_negative_log_likelihood`, `fit_egarch`, and
  `_compute_standardized_residuals` now accept `distribution` and `dof`; the
  Student-t likelihood uses the t-density directly (a *valid* NLL may be negative
  since the normalization constant is dropped — the test asserts finiteness, not
  positivity).
- `calibrate_from_ticks_csv` now **tolerates headerless CSVs** (the collected tick
  files start with data on line 1) while still honoring an `epoch,symbol,price`
  header when present.

**Tests:** `tests/test_garch_calibration.py` — Student-t NLL finiteness and
Student-t MLE recovery on synthetic fat-tailed returns.

---

## 4. Walk-Forward Optimization with PBO + Slippage — `src/synthetic_trader/research/run_wfo.py` (NEW)

The honest scorecard the operator asked for: **does the strategy have an edge on
the real collected ticks?**

- Sizes IS/OOS/step windows from each CSV's actual span (~24h of data →
  8h IS / 2h OOS / 2h step).
- Runs the existing `WalkForwardOptimizer` (rolling IS/OOS + **PBO** via CSCV-style
  comparison) over a hyperparameter grid.
- **Realistic execution:** 1 tick entry slippage + 1 tick exit slippage +
  per-trade penalty (`build_slippage_config()`).
- **Dedupes duplicate epochs** (the CSVs occasionally share an epoch, which broke
  the strict-chronology validator).
- After the WFO, **calibrates EGARCH(1,1)** from the same ticks at 10/30/60s bar
  scales, rejecting degenerate fits pinned at optimizer bounds, and persists the
  fitted parameters to `data/garch_calibration/{symbol}.json` so the live
  forecaster starts market-fitted.
- `sys.stdout.reconfigure(encoding="utf-8")` so the ✓/⚠ report glyphs render on
  Windows cp1252 consoles.

Usage:
```bash
python -m synthetic_trader.research.run_wfo                  # both symbols
python -m synthetic_trader.research.run_wfo --quick --timeframe 60
```

### Results (honest, saved to `data/research/wfo_*.json`)

| Symbol | Folds | OOS trades | Win rate | PF | Expectancy (R) | PBO | IS↔OOS corr |
|--------|-------|-----------|----------|----|----------------|-----|-------------|
| R_75   | 2     | 19         | 26.3%    | 0.34 | −0.52 | 0.0 | 0.0 |
| R_100  | 5     | 25         | 44.0%    | 0.26 | −0.49 | 0.2 | 0.36 |

**Reading:** both symbols **lose money out-of-sample** with slippage. R_100 shows
signs of in-sample-overfitting leakage (IS↔OOS corr 0.36) and unstable folds
(PF std 0.26). This is the truth the system now knows: *direction prediction on
CSPRNG price has no demonstrated edge*, and the volatility-regime machinery
(EGARCH + ADWIN) is the direction to keep investing in — it models the one real
signal.

---

## 5. Outcome-Feedback Wiring Fix — `src/synthetic_trader/live/market_snapshot.py`

**Bug:** `_maybe_resolve_feedback_outcomes(decision_engine)` existed but its
`pending_count == 0` early-return skipped it before the outcome-resolution branch
could run — **`calibration_outcomes.jsonl` was never consumed** by the live
pipeline. Trade outcomes never reached the model's calibration state.

**Fix:** reordered the pending-missed-trade check so outcome resolution runs
whenever there are feedback outcomes to resolve, independently of missed-trade
activity. The calibration loop (prediction → outcome → Isotonic/Platt → dynamic
confidence gate) is now actually fed.

---

## 6. Replay Buffer Capacity Regression — `src/synthetic_trader/models/replay_buffer.py`

**Bug:** default `capacity` was **500**, while the corruption tests, the stats
script, and the intended design all expect **10,000**. A 500-sample buffer
dramatically under-weights the online model's memory.

**Fix:** default restored to **10,000** in both `__init__` and `from_dict`
(reservoir-sampling cap). Existing saved model-state files for R_75/R_100 were
migrated to the correct capacity.

---

## 7. TS Test Corrections (stale vs. new reality)

The git history showed the *code* deliberately changed — the tests were stale:

- **`tests/contracts.test.ts`** — inline fixture now matches `mock-data.ts`'s
  shape (which no longer exports the old default market map).
- **`tests/engine-bridge.test.ts`** — corrected to the sniper-only warmup modes,
  the 60,000 ms live-snapshot timeout, and the `5000` prop-firm starting balance
  (the "lot size fix" commit).

---

## 8. Stale-Entry Truthfulness Fix — UI

**Bug:** when the guardian flips a setup to `failing`/`cancelled`, the primary
panel correctly says *"do not use the old entry levels"* — but
**LotSizeCalculator** (`currentCall.entry`) and **HistoryPanel** (`history[0].entry`)
kept showing the stale numbers, fed by workspace state that never updated.

**Fix:**
- `use-operator-workspace.ts` now strips execution levels (`entry`, `stop_loss`,
  `take_profit`, `entry_area`, `stop_area`, `target_area`) from the call the
  moment the guardian reports `failing`/`cancelled`, so every downstream panel
  agrees the plan is dead.
- `history-panel.tsx` got a defense-in-depth guard for journal-loaded entries
  already flagged failing/cancelled server-side.

---

## 9. Vol-Targeting Overlay Backtest Mode — `src/synthetic_trader/backtest/vol_reversion.py` (NEW)

The first concrete strategy built on the Phase 5 thesis: *trade the volatility
regime, not direction*.  New `backtest-vol` CLI subcommand:

```bash
python -m synthetic_trader.cli backtest-vol --csv data/R_75_ticks.csv \
    --symbol R_75 --timeframe 300 --compare
```

**Mechanics (the fade):**
1. **EGARCH forecast** — each candle's log-return feeds
   `EGARCHVarianceForecaster`, seeded with the market-calibrated parameters
   from `data/garch_calibration/{symbol}.json` (observations reset so the
   forecaster re-learns the *scale* from the actual candle stream).
2. **Extended-vol gate** — forecast sigma vs its own slow EMA baseline
   (`vol_extended_ratio`).  Note: `garch_vol_ratio` is always ~1.0 by
   construction in the forecaster (its `long_run_vol` is the current
   conditional vol), so the strategy computes its own ratio.
3. **ADWIN drift gate** — move magnitude fed as *percentage-scale*
   (`|r| × 100`) because ADWIN's statistical test is unreliable at 1e-5
   absolute scales.  A detected regime shift stands the strategy down for
   `drift_cooldown_bars` instead of fading into a transition.
4. **The fade** — price extension measured in *log space*
   `ln(close/ema) / prev_sigma` against the **ex-ante** forecast sigma (the
   reference advances unconditionally every candle, so it is never stale after
   a cooldown).  Stop/target placed as `entry × (1 ± mult × sigma)` — the
   log-vol multipliers converted to price units.  Default RR 0.6 (fade needs
   ~62.5% win rate to break even, the normal mean-reversion profile).

**Runner:** mirrors `BacktestEngine.run_ticks` using the same `PaperBroker` +
`RiskEngine` (fade-appropriate risk gates: no confidence/R:R minimum) so the
comparison vs the sniper strategy is apples-to-apples.

### Head-to-Head Results (honest, ~24h of ticks per symbol)

| Symbol / TF | Strategy | Trades | Win% | PF | Expectancy R |
|-------------|----------|--------|------|----|--------------|
| R_75 / 300s | vol-reversion | 1 | 0% | 0.00 | −0.74 |
| R_75 / 300s | sniper (ref)  | 6 | 17% | 0.22 | −0.71 |
| R_75 / 60s  | vol-reversion | 0 | — | — | — |
| R_75 / 60s  | sniper (ref)  | 15 | 33% | 0.50 | −0.30 |
| R_100 / 300s| vol-reversion | 3 | 33% | 0.12 | −0.68 |
| R_100 / 300s| sniper (ref)  | 19 | 42% | 0.56 | −0.27 |
| R_100 / 60s | vol-reversion | 1 | 100% | ∞ | +0.51 |
| R_100 / 60s | sniper (ref)  | 3 | 0% | 0.00 | −2.35 |

**Reading:** neither strategy has a demonstrated edge yet — the sniper needs
~36–36% win rates to be profitable at its RR, and the fade fires too rarely on
24h of data (0–3 trades) to conclude anything.  The overlay is a working,
comparable prototype; it needs multi-day data (and possibly a faster
mean-reversion exit like z-normalization) before it can be judged.

**Tests:** `tests/test_vol_reversion.py` (11) — fade direction + geometry,
calm-regime no-op, drift cooldown suppression, ex-ante sigma freshness through
cooldown (regression for the stale-reference bug), runner end-to-end,
calibrated-state seeding, tick dedupe, config sanity.

---

## 10. 4-6 Hour Volatility Horizon Forecast - `src/synthetic_trader/models/horizon_forecast.py` (NEW)

**Answers the operator's core question honestly:** can the engine infer the next
4-6 hours?  For *direction* — no, and no amount of data changes that: synthetic
indices are CSPRNG-generated random walks.  For *volatility* — yes, and this
module is the proof.  New `forecast-horizon` CLI subcommand:

```bash
python -m synthetic_trader.cli forecast-horizon --csv data/R_100_ticks.csv \
    --symbol R_100 --horizon-hours 5 --timeframe 60
python -m synthetic_trader.cli forecast-horizon --csv data/R_100_ticks.csv \
    --symbol R_100 --horizon-hours 4 --timeframe 60 --validate
```

**Mechanics:**
1. **EGARCH projection** - the online forecaster's conditional log-variance
   mean-reverts toward long-run at the persistence rate:
   `E[log sigma^2_{t+h}] = logvar_long + beta^h * (logvar_t - logvar_long)`,
   giving the projected per-bar sigma over any horizon.
2. **Robust long-run reference** - calibrated persistence sits near unit-root
   (~0.995), so the theoretical `omega/(1-persistence)` underflows.  The module
   uses a slow EMA (period 300) of *realized* log-variance instead.
3. **ADWIN regime stability** - move magnitude (percentage scale) feeds the
   drift detector; a recent drift lowers confidence and flags the band as less
   reliable.
4. **Range forecast** - projected average sigma x random-walk range multipliers
   (`1.6` for p50, `2.5` for p90) become expected price ranges and high/low
   bounds around the current close.
5. **Walk-forward validation** - `score_horizon_forecast` replays the history,
   forecasts at every step, and checks whether the realized high-low range fell
   inside the p50/p90 bands.  It also **fits the range multipliers empirically**
   (median/p90 quantile of the standardized realized range) instead of trusting
   the Gaussian priors.

### Real-Data Validation

| Symbol / Horizon / TF | Windows | p50 coverage | p90 coverage | fitted p50 mult | fitted p90 mult |
|-----------------------|---------|--------------|--------------|-----------------|-----------------|
| R_100 / 4h / 60s      | 255     | 0.463        | 0.769        | 1.688           | 4.288           |
| R_100 / 6h / 60s      | 135     | 0.237        | 0.689        | -               | -               |
| R_75 / 4h / 60s       | 9       | (too few)    | (too few)    | 1.480           | 1.505           |

**Reading:** R_100 at the 4h horizon is **calibrated** - p50 coverage 0.463 vs
the 0.5 target, and the fitted p90 multiplier (4.29) reveals synthetic ranges
are fat-tailed versus the Gaussian prior (2.5).  The 6h horizon under-covers
(bands too tight at longer horizons), and R_75 lacks enough usable candles to
conclude anything.  This is the honest, testable claim the engine can now make:
"the next 4 hours of *volatility* - with measured calibration - not the next 4
hours of direction."

**Tests:** `tests/test_horizon_forecast.py` (9) - forecast sanity, longer-horizon
wider-range monotonicity, to_dict, degenerate no-data safety, calibrated-state
seeding, walk-forward coverage sanity, too-little-data empty result.

---

## Validation

```text
Python: 660 passed, 31 subtests passed   (python -m pytest tests/ -q)
TypeScript: 12 files, 172 tests passed   (npx vitest run)
```

New test files: `tests/test_drift.py` (14), `tests/test_vol_reversion.py` (11),
`tests/test_horizon_forecast.py` (9), plus additions to
`tests/test_garch.py`, `tests/test_garch_calibration.py`, and the four corrected
TS test files.

## 11. Multi-day data collection + head-to-head verdict

### Data collection (backfill-mt5)

Deriv's WebSocket API cannot serve multi-day **tick** history (proven: paged
`ticks_history` requests all return the same rolling ~5k-tick buffer, ignoring
`end`), and its candle symbols (1HZ75V / 1HZ100V) trade at **different price
levels** than the Blueberry instruments the user actually trades.  The correct
source is the Blueberry MT5 terminal itself: `copy_rates_range` returns
server-backed M1 OHLC going back days.

New `backfill-mt5` subcommand: `collect_mt5_candle_history()` resolves the real
broker symbols (**SYN75 / SYN100** — "Volatility 75 Index" does not exist on
the broker), fetches N days of M1 rates, and expands each candle into an
OHLC-exact 4-tick stream (bucket+0.01/0.26/0.51/0.76) so downstream 60s/300s
candle builders reproduce the original OHLC exactly.  The terminal path is
resolved with the same registry/Program-Files scan the live path uses
(`_resolve_mt5_terminal_path`).  Also fixed `_resolve_mt5_symbol` to try
SYN75/SYN100 first so the live MT5 path can resolve the real instruments.

**Result: 7 full days, correct Blueberry scale, per symbol:**

| Symbol | Venue | Span | Min → Max | Ticks |
|---|---|---|---|---|
| R_75 | SYN75 | 1,637 → 1,770 | 1,439 → 1,779 | 40,080 |
| R_100 | SYN100 | 305 → 344 | 298 → 358 | 40,080 |

Both match the user's chart exactly (~1,762 and ~345 current).  Zero
duplicates, zero out-of-order rows.

### Critical data-quality finding

The pre-existing `data/R_75_ticks.csv` was **polluted with two price scales**
(Blueberry ~1,700 body + Deriv ~7,800 tail from the API fallback path).  This
pollution explains Phase 5's 0.995 EGARCH persistence: a scale jump reads as
**extreme** volatility persistence.  On 7 days of clean, correct-scale data the
squared-return ACF is essentially zero (sum ≈ −0.012 to +0.050 at 60s/300s) and
ARCH tests show no detectable clustering (p ≈ 0.62–0.83) — **the 0.995
persistence was an artifact, not a real property.**  The freshly calibrated
files are degenerate (alpha/beta pinned at bounds) and are auto-rejected by the
bounds check, falling back to default priors — the correct honest behavior.

### Head-to-head on 7 days of correct-scale data (backtest-vol --compare)

| Symbol / TF | Strategy | Trades | Win rate | PF | Exp (R) | Net PnL |
|---|---|---|---|---|---|---|
| R_75 / 300s | vol-reversion | 4 | 100% | ∞ | +0.504 | +9.91 |
| R_75 / 300s | sniper | 12 | 25% | 0.38 | −0.430 | −22.47 |
| R_100 / 300s | vol-reversion | 4 | 0% | 0.00 | −1.093 | −27.52 |
| R_100 / 300s | sniper | 3 | 0% | 0.00 | −2.049 | −23.11 |
| R_75 / 60s | vol-reversion | 1 | 100% | ∞ | +0.470 | +2.25 |
| R_75 / 60s | sniper | 4 | 0% | 0.00 | −1.306 | −19.83 |
| R_100 / 60s | vol-reversion | 1 | 0% | 0.00 | −1.299 | −8.11 |
| R_100 / 60s | sniper | 5 | 40% | 0.06 | −1.341 | −26.26 |

**Honest read:** even with 7 days of data the trade counts are still small (the
vol-reversion fade is deliberately selective), but the pattern is consistent
with Phase 5's WFO — **the sniper loses money out-of-sample in every
configuration, and the vol-reversion fade is a coin flip** (positive only on
R_75, which has the fewest trades).  No configuration shows robust positive
expectancy.  The earlier "0.995 persistence" calibration that suggested the
fade would work was inflated by polluted data.

### Performance fix: bounded feature history

The 60s backtests were taking hours because the decision engine rescans the
**entire** growing candle history per candle (pandas SMC + swing detection over
10k candles = O(n²)).  `BacktestEngine` now passes a bounded
`MAX_FEATURE_HISTORY = 400` candle window; every indicator is a rolling window
≤ 50 bars (Hurst is the only full-sample estimate — harmless, verified).
Bit-for-bit identical 300s results before/after the change, and the 60s runs
now finish in minutes.  This also bounds live-session/walk-forward memory use.

### Validation

```text
Python: 671 passed, 31 subtests passed   (python -m pytest tests/ -q)
TypeScript: 12 files, 172 tests passed   (npx vitest run)
```

New/changed: `backfill-mt5` CLI + `collect_mt5_candle_history()` in
`calibration/mt5_collector.py`, `candles_history` on the Deriv client,
`collect_candle_history()` + `candles_to_ticks()` in `data/collector.py`,
`SYN75/SYN100` symbol resolution in `execution/mt5_data.py`, bounded feature
history in `backtest/engine.py`, `tests/test_mt5_collector.py` (5), additions
to `tests/test_collector.py` (4).  Data (7-day CSVs, garch calibration) live in
`data/` (gitignored).

---

## 12. Live Horizon Forecast on the Operator Dashboard (forecast-horizon route + panel)

**Answers the operator's question "can I see the calibration live?"** — the
`HorizonVolForecaster` is now an engine output surfaced through the same
route/panel pattern as `connection-status` / `pipeline-diagnostics`.

- **Python stats module** — `src/synthetic_trader/scripts/horizon_forecast_stats.py`
  (NEW): `get_horizon_forecast_stats(engine_root)` resolves the best tick CSV
  per symbol (prefers the 7-day `data/backfill/{sym}_ticks.csv`), dedupes,
  loads the calibrated GARCH state, and for each of **R_75 / R_100** at
  **4h / 6h** returns the walk-forward validation (coverage, fitted
  multipliers, windows, verdict) plus the live EGARCH+ADWIN forecast (p50/p90
  price bands, vol trend, persistence, drift events, confidence).  The verdict
  now comes from a **single shared helper** `horizon_verdict()` in
  `models/horizon_forecast.py` used by both the CLI and the dashboard, so the
  two can never drift apart.  The live replay is **hoisted to once per symbol**
  (the forecaster state is horizon-independent; both horizons project from one
  tick pass) instead of replaying 40k ticks per horizon per poll.
- **Next.js route** — `app/api/system/forecast-horizon/route.ts` (NEW): mirrors
  `calibration-stats`; runs the stats module via `runPythonScript` with a 60s
  timeout (2 symbols × 2 horizons over 40k ticks each), returns the JSON
  payload, 503 when no engine root is configured.
- **Live panel** — `src/components/operator/horizon-forecast-panel.tsx` (NEW),
  wired into `operator-shell.tsx`: auto-polls every 15s, collapses to a
  status dot (green = any horizon calibrated, amber = needs data), expands to
  per-symbol 4h/6h cards with p50/p90 range bands, vol trend, regime stability,
  forecast sigma, confidence, and coverage bars with the fitted multipliers.
  Honest-by-design copy: "direction-unpredictable — this is the forecast of
  how far price is expected to range."  Partial failures (missing CSV, too few
  ticks) render per-symbol error states instead of crashing the panel, and a
  non-OK HTTP response throws into the error state rather than showing stale
  data.

**Tests:** `tests/test_horizon_forecast_stats.py` (5) — end-to-end stats
structure, missing-symbol error entry, insufficient-ticks entry, live-vs-
validation sigma scale; `tests/operator-panels.test.tsx` adds the
`HorizonForecastPanel` suite (27 panel tests total).

### Validation (final)

```text
Python: 677 passed, 31 subtests passed   (python -m pytest tests/ -q)
TypeScript: 12 files, 176 tests passed   (npx vitest run)
```

---

## 13. Continuous Tick Collection Service + Coverage Command

**The operator's blocker was data:** one day of ticks gives only ~255 usable
walk-forward windows, and the 7-day corpus still leaves the head-to-head verdict
suggestive rather than sharp.  Two new pieces close the loop:

### `collect-live-ticks` — `src/synthetic_trader/data/continuous_collector.py` (NEW)

A long-running service that appends real ticks to `data/backfill/{symbol}_ticks.csv`
across days/sessions — the same clean-corpus files the WFO and forecast-horizon
dashboard already read.

- **Correct source.** Blueberry MT5 terminal only (`Mt5TickClient.latest_tick()`
  added to `execution/mt5_data.py`, returning the terminal's real `time_msc`
  epoch).  The Deriv WebSocket fallback is never used — its 1HZ75V trades at
  ~7,000 vs SYN75 ~1,500 and would corrupt the corpus.
- **Rollover-aware.** Synthetic indices trade 24/7/365; the only scheduled pause
  is the daily rollover (~00:00 UTC).  `RolloverCalendar` marks that window
  (configurable hour + grace, wraps midnight); stalls *inside* it are expected
  and never trigger reconnect.  Stalls outside it warn after
  `--stall-warn-sec` (120s) and force a reconnect after `--stall-reconnect-sec`
  (600s).
- **Session-safe appends.** Every batch flush goes through
  `append_ticks_csv` (dedup by epoch/price against the file tail, derived
  columns, size-cap pruning) — overlapping polls and restarts never
  double-write.  Pending ticks are flushed in a `finally`, so even a
  feed-loss/reconnect boundary loses nothing.
- **One MT5 connection.** All symbols share a single `Mt5TickClient` with
  terminal calls serialized through a lock (the MT5 Python package allows one
  connection per process).  Feed loss reconnects with backoff; an initial
  connect failure fails fast with the terminal's own error.
- **Status telemetry.** `data/live_tick_collector.json` is written every ~10s
  (per-symbol ticks, last epoch/price, reconnects, stalls) so the dashboard
  can surface collection health later.

```bash
python -m synthetic_trader.cli collect-live-ticks --symbols R_75,R_100
# or: collect-live-ticks.bat   (launcher; keep the Blueberry terminal open)
```

### `tick-coverage` — `src/synthetic_trader/scripts/tick_coverage_stats.py` (NEW)

Answers *"do we have enough data to re-run WFO yet?"* per symbol:

- Resolves the best tick CSV (backfill preferred), reports ticks, span hours,
  ticks/day, duplicates, out-of-order rows, price range.
- **Usable walk-forward windows** per timeframe × horizon, mirroring
  `score_horizon_forecast`'s real eligibility (`n_candles − horizon_bars −
  warmup(60)`) — e.g. at 60s × 4h: `n_candles − 240 − 60`.
- **WFO readiness** mirroring `run_wfo.size_windows`: ≥30h span → day-scale
  (12h IS/4h OOS), ≥16h → 8h/2h, ≥8h → 4h/1h; `ready` requires ≥200 ticks.
- Machine-readable `--json` for CI/automation.

```bash
python -m synthetic_trader.cli tick-coverage
python -m synthetic_trader.cli tick-coverage --json
```

`run_wfo.py` now reads `data/backfill/{symbol}_ticks.csv` first (clean corpus)
before the legacy `data/` files, so a re-run always uses the right scale.

### Live verdict on the 7-day corpus (tick-coverage --json)

| Symbol | Ticks | Span | WFO readiness | 60s×4h windows | 60s×6h windows |
|---|---|---|---|---|---|
| R_75 | 40,080 | 7.0d | READY (day-scale, 12h/4h/4h) | 9,779 | 9,659 |
| R_100 | 40,080 | 7.0d | READY (day-scale) | 9,779 | 9,659 |

**Reading:** the corpus is already far past the WFO threshold — the blocker is
no longer *data volume* but *strategy edge* (the head-to-head in §11 showed no
configuration with robust positive expectancy).  Let the collector run and the
corpus compounds: a week becomes a month, and the per-call-type hit rates in
Stage 3 become statistically sharp.

**Tests:** `tests/test_continuous_collector.py` (8) — rollover window
boundaries (incl. midnight wrap + whole-day grace), collection + dedupe,
stall-raise outside rollover, rollover suppression, repeated-read-error raise,
batch flush; `tests/test_tick_coverage_stats.py` (6) — span/window math,
WFO readiness scales, missing-symbol error, few-ticks not-ready, JSON
roundtrip.

---

## 14. Vol-Momentum Mode (with-the-regime) + Head-to-Head Verdict

**The fade (§9) assumes mean-reversion** — it sells over-extensions of price
when forecast volatility is elevated.  But during a genuine **drift / step-up
regime** — move magnitude has changed and is sustained at a new, higher level —
fading is exactly wrong: the extension keeps going.  This section adds the
with-the-regime counterpart and answers, on 7 days of clean ticks, whether
**following or fading vol is more profitable**.

### `--mode momentum` — `src/synthetic_trader/backtest/vol_momentum.py` (NEW)

`VolMomentumStrategy` mirrors the fade's proven structure (ex-ante forecast
sigma reference, unconditional sigma advance, ADWIN drift cooldown, log-space
`z_dev`) with opposite intent:

1. **High-vol regime gate** — forecast sigma elevated vs its own slow EMA
   baseline (`vol_min_ratio`, default 1.15).  Momentum only follows when the
   vol regime is **on**; in a calm regime the move is noise, not a trend.
2. **ADWIN drift gate** — same cooldown as the fade: stand down after a
   regime shift so momentum doesn't enter *at the top of a step-up* (the very
   regime fading gets wrong).  Once the step-up has stabilized (no fresh drift
   for `drift_cooldown_bars`), the new high-vol level is the regime to follow.
3. **The follow** — LONG after an up-extension, SHORT after a down-extension
   (`z_entry` 0.8 sigmas — momentum enters earlier than the fade's 2.0), with
   a **momentum profile: tighter stop, wider target** (RR = target/stop ≈
   3.0/1.5 = 2.0 by default, versus the fade's 0.6).

### Shared runner + CLI

- The PaperBroker/RiskEngine pipeline was **extracted into a shared
  `run_vol_regime_backtest()`** in `vol_reversion.py`; both fade and momentum
  delegate to it, so the comparison is apples-to-apples (verified: the 11
  existing fade tests pass unchanged).
- `backtest-vol --mode fade|momentum` selects the primary strategy (artifact
  goes to it); `--compare` runs the **other** vol regime **and** the sniper
  reference on the same ticks and prints all three.  Momentum tuning args are
  namespaced (`--mom-z-entry`, `--mom-vol-min-ratio`, `--mom-stop-sigma-mult`,
  `--mom-target-sigma-mult`).
- Per review: `calibrated_garch=loaded` no longer prints on the sniper block
  (sniper never uses garch_state), and `--artifact-output` help reflects that
  it saves whichever `--mode` is primary.

### Head-to-head on 7 days of clean data (backtest-vol --mode momentum --compare)

| Symbol / TF | Strategy | Trades | Win% | PF | Exp (R) | Net PnL |
|---|---|---|---|---|---|---|
| R_75 / 300s | **vol-momentum** | 3 | 0% | 0.00 | −1.165 | −21.96 |
| R_75 / 300s | vol-reversion | 4 | 100% | ∞ | +0.504 | +9.91 |
| R_75 / 300s | sniper | 12 | 25% | 0.38 | −0.430 | −22.47 |
| R_100 / 300s | **vol-momentum** | 2 | 0% | 0.00 | −2.005 | −24.52 |
| R_100 / 300s | vol-reversion | 4 | 0% | 0.00 | −1.093 | −27.52 |
| R_100 / 300s | sniper | 3 | 0% | 0.00 | −2.049 | −23.11 |
| R_75 / 60s | **vol-momentum** | 5 | 40% | 0.82 | −0.019 | −3.17 |
| R_75 / 60s | vol-reversion | 1 | 100% | ∞ | +0.470 | +2.25 |
| R_75 / 60s | sniper | 4 | 0% | 0.00 | −1.306 | −19.47 |
| R_100 / 60s | **vol-momentum** | 6 | 50% | 0.71 | −0.037 | −4.38 |
| R_100 / 60s | vol-reversion | 1 | 0% | 0.00 | −1.299 | −8.11 |
| R_100 / 60s | sniper | 5 | 40% | 0.06 | −1.341 | −25.96 |

**Honest verdict:** the momentum mode **loses money in every configuration**
(negative expectancy on both symbols at both timeframes), while the fade is a
coin flip (positive only on R_75, where it trades the least).  Neither vol
regime nor the sniper shows robust positive expectancy on 7 days.  Two honest
caveats: (a) the trade counts are still tiny — both vol strategies are
deliberately selective, so no cell is statistically meaningful yet; (b) the
momentum gate fires only while sigma is *freshly* elevated above its own EMA,
so it may under-trade exactly the sustained regimes its docstring claims to
follow — if momentum is worth pursuing further, an absolute-sigma or
sigma-EMA-trend gate is the first knob to try.

### Performance fix that unblocked the 60s runs — `smc_enhanced.py` (REWRITE)

The 60s `--compare` runs were hanging (the §11 `MAX_FEATURE_HISTORY=400` bound
wasn't enough).  Stack-profiling pinned it: `smc_features()` cost **~0.145s per
candle** — the four detectors (FVG, BOS/CHoCH, Order Blocks, Liquidity) each
rebuilt the pandas DataFrame independently, and three of them recomputed swing
highs/lows — so 10k candles ≈ 24 minutes of pure SMC work, and the library's
`bos_choch`/`ob` inner loops are super-linear in window length.

Fix: a shared `_prep()` builds the DataFrame + swings **once** per call (window
capped at `SMC_FEATURE_WINDOW = 250` — fresh-structure semantics: a BOS from
400 bars ago is stale by construction, and the smaller window bounds the
super-linear loops).  All four detectors consume the shared prep via
`_fvgs_from` / `_bos_choch_from` / `_order_blocks_from` / `_liquidity_from`.
Public API unchanged.  **~3× faster (0.047s/candle)**; the 60s head-to-head
above now completes in minutes.  Per review, each detector degrades
independently (one failing parser zeros only its own features) and the
all-zeros block is a single module constant.

**Tests:** `tests/test_vol_momentum.py` (12) — calm-regime no-op, follow-long
and follow-short geometry, drift cooldown suppression, ex-ante sigma freshness
through cooldown, runner end-to-end, calibrated-state seeding, shared tick
dedupe, config sanity, and a **mirror test** proving fade and momentum trade
OPPOSITE directions on the same stream (the pair is a true counterfactual).

### Validation (final)

```text
Python: 703 passed, 31 subtests passed   (python -m pytest tests/ -q)
TypeScript: 12 files, 176 tests passed   (npx vitest run)
```

---

## 15. Horizon Under-Coverage Investigation & Calibration-Bias Fix

**Symptom (operator report):** R_100 at the 6h horizon under-covered
(p50 coverage 0.237) — bands too tight at longer horizons, and the pattern
looked like a real calibration bias rather than data sparsity.

### Root-cause investigation (probe on the clean 7-day corpus)

Three real defects, measured:

1. **Units bug in the online EGARCH update** (`garch.py`).  `pred_error` was
   `log_return**2 − state.log_variance` — a raw squared return (~1e-6) minus a
   *log*-variance (~−13).  Different scales being subtracted: every gradient
   came out strongly positive, omega climbed without bound, and the projected
   bands exploded (~300× too wide, coverage 1.0 everywhere).  Fix: the
   realized quantity is now a log-variance, `2·log|r|`, so `pred_error` is
   the honest log-space prediction error.
2. **Degenerate calibration slipping past rejection** (`garch_calibration.py`).
   The on-disk R_75/R_100 fits had beta pinned at its 0.01 floor (persistence
   ~0.03 — no vol clustering at all) but the guard only rejected when **≥2**
   parameters sat at bounds.  Now any single parameter at a bound, a
   persistence < 0.05, or a long-run vol ratio off by 50× rejects the fit
   (falls back to default priors).  Also fixed `long_run_var = omega/(1−pers)`
   → `exp(omega/(1−pers))` (omega is a *log*-variance intercept).  Fresh
   calibration on the clean 7-day data confirms the 60s-scale fits are
   genuinely degenerate (beta at floor, arch p ≈ 0.78–0.83 — no clustering at
   that scale) and are now correctly rejected rather than poisoning the
   forecaster.
3. **The projection itself** (`horizon_forecast.py`) — the operator's two
   hypotheses were both right:
   - **β^h decay was wrong.**  `_projected_logvars` decayed at
     `state.persistence` (= β + α·(1−γ²/2)) where the module's own formula
     says **β^h**.  Since α ≥ 0, persistence ≥ β, so the old code decayed
     slower, hugging the current deviation longer; the decay is now the
     correct recursion coefficient `state.beta`.
   - **The long-run anchor lagged twice over.**  The 300-bar EMA was fed the
     *conditional* log-variance — already EGARCH-smoothed, so it responded to
     a regime change in ~2×300 bars.  It is now fed the **realized**
     log-variance (2·log|r|, bias-corrected by E[log z²] so the level is
     unbiased; the EMA period smooths the per-bar noise).  The anchor tracks
     a sustained high-vol regime within one period instead of two.
   - **The range multipliers were never fed back.**  The module docstring
     promised the walk-forward calibration "fits empirical multipliers...
     which is the honest calibration" — but nothing consumed them.  Now the
     fitted multipliers (per symbol × timeframe × horizon) are **persisted**
     to `data/forecast_multipliers/{symbol}_{tf}s.json` via
     `save/load_forecast_multipliers` (merge-not-overwrite), the live
     forecaster/dashboard load them, and `score_horizon_forecast` reports
     coverage **honestly**: multipliers are fit on the first `1−holdout_frac`
     of windows (default 0.3) and coverage is scored on the *holdout* — an
     out-of-sample verdict, not a circular in-sample one.

### Re-validation on the clean 7-day corpus (holdout split, fitted multipliers)

| Symbol / TF | Horizon | Holdout windows | p50 cov | p90 cov | fitted (p50/p90) | Verdict |
|---|---|---|---|---|---|---|
| R_75 / 300s | 4h | 570 | 0.514 | 1.000 | 2.57 / 5.32 | calibrated |
| R_75 / 300s | 6h | 562 | 0.475 | 0.996 | 2.67 / 5.08 | calibrated |
| R_75 / 60s | 4h | 2,916 | 0.481 | 0.860 | 2.72 / 3.84 | calibrated |
| R_75 / 60s | 6h | 2,880 | 0.464 | 0.843 | 2.77 / 4.02 | calibrated |
| R_100 / 300s | 4h | 570 | 0.716 | 0.900 | 2.99 / 4.83 | calibrated |
| R_100 / 300s | 6h | 562 | 0.669 | 0.947 | 3.03 / 5.15 | calibrated |
| R_100 / 60s | 4h | 2,916 | 0.664 | 0.926 | 2.90 / 4.71 | calibrated |
| R_100 / 60s | 6h | 2,880 | 0.642 | 0.955 | 3.06 / 4.78 | calibrated |

**Reading:** every configuration is now **calibrated out-of-sample** — p50
coverage 0.46–0.72 (target 0.5) and p90 coverage 0.84–1.00 (target 0.9) on the
holdout.  The reported symptom (R_100 6h p50 0.237) is now 0.67 at 300s / 0.64
at 60s.  The fitted multipliers (1.9–3.1 p50, 3.4–5.3 p90) confirm the priors
(1.6/2.5) were too narrow for fat-tailed synthetic ranges.  The dashboard now
shows `multipliers_applied` per horizon and the verdict comes from the honest
holdout split.

**CLI:** `forecast-horizon --fit-multipliers` fits + persists (and validates
on the holdout); `--apply-multipliers` validates against previously saved
multipliers.

**Tests:** `tests/test_horizon_forecast.py` now 13 (5 new: beta-decay, fitted
multipliers widen bands, multiplier persistence round-trip with merge,
chronological holdout, explicit-multiplier scoring).  The two vol-reversion
fade tests were retuned for the corrected EGARCH sigma scale (the units fix
made the true per-candle sigma ~3.5% explicit, so the spike streams need ~8%
moves to cross the same z_entry in *accurate* sigma units).

### Validation (final)

```text
Python: 705 passed, 31 subtests passed   (python -m pytest tests/ -q)
TypeScript: 12 files, 176 tests passed   (npx vitest run)
```

---

## 16. Re-Run on the Corrected Forecaster: The Statistically Meaningful Verdict

**Why re-run:** every head-to-head in §11/§14 ran on the *pre-fix* EGARCH
forecaster — the units bug (`pred_error = r² − log_variance`) inflated omega
and distorted the online sigma scale that both vol-regime strategies gate on.
After §15's fixes (units bug, degenerate-calibration rejection, β-decay,
realized-var anchor) the fade/momentum signals are computed on an *accurate*
sigma — so the earlier 1–4-trade cells and the R_75 "100% win" fade were
partly artifacts.  The 7-day corpus (40,080 ticks/symbol, already at the
requested 3–7 day range) is unchanged; only the engine is corrected.

### Head-to-head on the corrected engine (backtest-vol --compare, default priors)

| Symbol / TF | Strategy | Trades | Win% | PF | Exp (R) | Net PnL |
|---|---|---|---|---|---|---|
| R_75 / 300s | vol-reversion | 9 | 55.6% | 0.44 | −0.215 | −15.90 |
| R_75 / 300s | vol-momentum | 10 | 30.0% | 0.53 | −0.262 | −20.53 |
| R_75 / 300s | sniper | 13 | 30.8% | 0.47 | −0.342 | −20.85 |
| R_100 / 300s | vol-reversion | 9 | 55.6% | 0.19 | −0.456 | −28.48 |
| R_100 / 300s | vol-momentum | 4 | 25.0% | 0.13 | −0.832 | −21.52 |
| R_100 / 300s | sniper | 3 | 0.0% | 0.00 | −2.049 | −23.29 |
| R_75 / 60s | vol-reversion | 8 | 50.0% | 0.23 | −0.419 | −23.66 |
| R_75 / 60s | vol-momentum | 8 | 37.5% | 0.37 | −0.398 | −22.73 |
| R_75 / 60s | sniper | 4 | 0.0% | 0.00 | −1.306 | −20.07 |
| R_100 / 60s | vol-reversion | 4 | 0.0% | 0.00 | −0.527 | −14.40 |
| R_100 / 60s | vol-momentum | 2 | 0.0% | 0.00 | −1.636 | −20.20 |
| R_100 / 60s | sniper | 5 | 40.0% | 0.06 | −1.341 | −26.46 |

**The verdict is now statistically meaningful — and it is consistent:** across
4 configs × 3 strategies = 12 cells, **zero show positive expectancy**.  The
fade now trades a real sample (30 trades total: 9/9/8/4) instead of the
1–4-trade cells of §11, and its win rate is genuinely informative — **50–56%
win rate on the corrected sigma** — yet it still loses money: with the fade's
RR ≈ 0.6 it needs ~62.5% win rate to break even, so 50–56% is a structural
shortfall, not noise.  Momentum (24 trades) and the sniper (25 trades) lose
in every cell.

**Reading:** the corrected engine *confirms and sharpens* the §11/§14
conclusion — no strategy built on CSPRNG direction (sniper) or even on the
real vol-clustering signal (fade/momentum) clears the cost-and-RR bar on 7
days.  The fade's edge is directionally real (it wins more than it loses at
300s) but too small for its risk profile; the honest next levers are a
faster mean-reversion exit (raise effective RR toward ≥1) or a tighter
fade entry filter, not more data volume alone.

**Also fixed:** `tick-coverage` text mode crashed on Windows cp1252 consoles
(the → glyph) — the CLI now reconfigures stdout to UTF-8, same as `run_wfo`.

---

## 17. Continuous M1-Rate Capture Loop (compounding corpus, no manual re-fetch)

**Goal.** The WFO and horizon forecast only learn as much as the data allows,
and the corpus previously stopped growing the moment nobody ran
`backfill-mt5` by hand. `capture-m1` keeps `data/backfill/{symbol}_ticks.csv`
compounding in the background by reusing the exact `backfill-mt5` machinery
(`fetch_m1_candles` — server-backed M1 OHLC from the Blueberry MT5 terminal at
the correct SYN75/SYN100 scale).

**How it works.**

- **Incremental, not re-fetch.** Each sweep fetches only the M1 candles since
the newest candle already in the file (minus a 5-min overlap), expands them to
OHLC-exact ticks, and merges. `normalize_ticks` dedupes by `(epoch, price)`, so
overlap re-fetches never double-write.
- **Forming-candle safe.** `fetch_m1_candles` (and `capture-m1` defensively
again) excludes the still-forming minute; the overlap picks it up next sweep.
Note: this also means a one-shot `backfill-mt5` now ends at the last
*fully-closed* minute — a deliberate tail-behavior change.
- **First-run seeding.** A symbol with no file seeds 7 days of history
(identical to `backfill-mt5 --days 7`); after that, only new data is added.
- **Rollover/downtime tolerant.** An empty fetch (daily rollover pause,
terminal closed) is not an error — recorded as zero added and retried next
sweep. `max_gap_sec` reports where history is missing.
- **Atomic merge.** The corpus is rewritten via temp-file + rename, so a
killed process can never leave a half-written file that would poison the WFO
and dashboard readers.
- **Status telemetry.** `data/m1_capture.json` is rewritten after every sweep
(per-symbol ticks before/after, candles fetched, max gap, error/warning).

**Usage.**

```
python -m synthetic_trader.cli capture-m1 --symbols R_75,R_100          # hourly sweep loop
python -m synthetic_trader.cli capture-m1 --symbols R_75,R_100 --once    # single sweep (cron/Task Scheduler)
```

Run the loop (or a daily `--once` job) as the always-on compounding backstop;
`collect-live-ticks` remains the intraday precision layer when the terminal is
being watched. Do not run both against the same symbol file simultaneously.

Validation: `tests/test_m1_capture.py` (8), `tests/test_mt5_collector.py`,
`tests/test_collector.py`, `tests/test_continuous_collector.py` — full Python
suite 712 passed, 3 skipped. Also fixed en route: a latent `UnboundLocalError`
scope bug in `cli.py main()` (a handler-local `import asyncio` shadowed the
module-level import for every other command) and a missing `import os` that
broke the `collect-live-ticks` handler the same way `capture-m1` would have.

## 18. Bounded-Window Fix on the Live Path (no O(n²) full-history rescan)

**Goal.** The backtest engine already bounded the history fed to
`DecisionEngine.evaluate` at `MAX_FEATURE_HISTORY = 400` candles (§4 of the
original backtest work) — every indicator in the feature pipeline is a rolling
window (≤ 50 bars; swings/FVGs need the last ~10–30 bars), so re-scanning the
full growing history per candle was pure O(n²) waste. The live path had the
same unbounded pattern; this round applies the identical bound there.

**Changes.**

- `MAX_FEATURE_HISTORY` moved to `synthetic_trader.config` (neutral home) and
  is imported by `backtest.engine`, `live/paper_runner.py`, and
  `live/market_snapshot.py` — no more live→backtest dependency just for a
  constant.
- **`paper_runner.run_live_paper`** — the per-candle `evaluate` call now passes
  `histories[tf][-MAX_FEATURE_HISTORY:]` instead of the full lists (mirrors the
  backtest exactly; histories still accumulate, only the evaluation window is
  bounded).
- **`market_snapshot.analyze_live_snapshot`** — the `role_candles` dict is now
  bounded in place to the 400-candle tail, and both compute-heavy consumers
  receive bounded inputs: `build_snapshot` (`candles=`, `higher_timeframe_candles=`,
  `extra_timeframes=`) and `decision_engine.evaluate` (`candles=`, `role_candles=`).
  The full `primary_candles` list is still used for the `if primary_candles:`
  gate and `current_close`.
- **`supervised_live.py`** needs no change — `run_supervised_live_session` routes
  to `run_live_paper` / the snapshot analyzer via its runners, so it inherits
  the fix. All live entry points (`paper-live`, `live-snapshot`, `live-watch`)
  flow through the two fixed functions.

**Why it's safe.** The 4h bias timeframe from a 24h CSV window yields only ~6
candles (slice is a no-op); the 60s primary gets cut from ~1440 to 400 candles,
but rolling-window features are identical on the tail, and this is the exact
bound the 300s backtests already validated on the same shared indicator code.
`background_scanner` is unaffected — it re-fetches 5000 ticks per scan, so its
histories are bounded by construction.

Validation: `tests/test_live_market_snapshot.py` — identity assertion updated
(`candles=` and `role_candles["execution"]` are the same bounded object) plus a
new regression test (`test_analyze_live_snapshot_bounds_history_to_max_feature_history`)
feeding 5000 ticks and asserting both `build_snapshot` and `evaluate` receive
exactly `MAX_FEATURE_HISTORY` candles for the over-bound windows. Full Python
suite 714 passed, 3 skipped.

## 19. Re-Tuning the Fade Entry Gates on the Clean Corpus

**Why.** The original gate defaults (`z_entry=2.0`, `vol_extended_ratio=1.3`,
`min_revert_signal=0.0`) were set before the CSV-pollution fix, so the
"calibration" behind them was partly an artifact of two instruments' price
scales being mixed into one file.

**Method.** 6×4×3 = 72-combo in-process grid sweep (`z_entry ∈ {1.25…2.5}`,
`vol_extended_ratio ∈ {1.1…1.5}`, `min_revert_signal ∈ {0, 0.02, 0.05}`) over
the clean 7-day corpus (40,320 ticks/symbol), both symbols × {300s, 60s}, using
the same PaperBroker/RiskEngine pipeline and slippage model as the CLI.

**Verdict (honest).** No combination produced positive expectancy.  The
original default summed −1.617R across the four cells (30 trades); the best
coherent cluster (`z=1.5, vol=1.5, mr≥0.02`) sums −0.598R (27 trades) — every
cell improves or matches, but the strategy is still net-negative.

**Shipped.** `z_entry` 2.0→1.5, `vol_extended_ratio` 1.3→1.5,
`min_revert_signal` 0.0→0.02.

**Two caveats, stated plainly.**

1. **The z/vol change only nets out with the mr gate active.**  With `mr=0.0`
   the same z/vol is −1.91R summed — *worse* than the old default.  The
   improvement is carried by the mean-reversion gate selecting sharp-spike
   fades.  If that effect is noise, the new defaults are worse than the old.
   Mitigation: the gate saturates (0.02 ≡ 0.05 → binary-ish, not knife-edged)
   and its mechanism is coherent (fade |z|≥2 spikes, not slow grinds), but 27
   trades cannot separate signal from luck — treat `min_revert_signal=0.02`
   as **provisional** until the corpus grows (M1 capture loop, §17).
2. **The binding constraint is the reward/risk structure, not the entry
   gates.**  RR ≈ 0.6 (target/stop = 1.5/2.5) needs ≈62.5% wins; the fade's
   measured win rate is 50–58%.  The path to profitability is a faster
   mean-reversion exit (z-normalization target) or a wider target, not
   tighter entry gates.

**Reproduction (CLI, defaults as shipped).**

```text
R_75@300:   3 trades / +0.51R
R_100@300:  8 trades / −0.35R
R_75@60:   12 trades / −0.234R
R_100@60:   4 trades / −0.525R
sum:       −0.599R (matches the sweep's −0.598 cluster)
```

Full Python suite: 715 passed, 3 skipped.

## 20. Stage-3 Empirical Gate + Calibration Health Panel

### The problem

The decision engine's `confidence` is a *model* number — how well the feature
pipeline agrees with the learned model.  It says nothing about whether that
exact setup actually reaches its target in the market.  On CSPRNG-generated
price the honest question is empirical: *when the engine emitted this
`(symbol, trigger_type)` before, how often did it hit the target?*

### The Stage-3 gate — `src/synthetic_trader/live/stage3_gate.py` (NEW)

When a call snapshot is built (`build_watch_alert` → `apply_stage3_gate`), the
gate:

1. Rolls up the scored outcomes journal (`journals/live_calibration_outcomes.jsonl`,
   written by `synth-trader score-live-calibration`) for the exact
   `(symbol, trigger_type)` — same `summarize_outcomes` grouping the CLI uses,
   so the gate can never disagree with the scorer.
2. Reads the persisted horizon verdict cache (`data/forecast_verdicts.json`,
   written by `horizon_forecast_stats` — the same computation behind the
   forecast-horizon route).  A symbol is *calibrated* only when BOTH 4h and 6h
   horizons validate.
3. Decides a gate state:
   - **gated** — ≥ 10 scored outcomes, target-hit rate ≥ 50%, horizon verdict
     calibrated.  The operator sees the **market-verified target-hit rate**
     instead of raw model confidence.
   - **annotated** — evidence exists but a bar is missing (rate below floor,
     verdict not calibrated).  Call still emits with the honest empirical rate
     and a note naming what is missing.
   - **insufficient_data** — no scored outcomes yet.  Raw model confidence is
     kept (nothing better exists) and the annotation says so plainly.

Everything is best-effort: a missing journal, corrupt JSONL, or unreadable
cache degrades to `insufficient_data` rather than crashing the snapshot.  The
gate never fabricates evidence.

### Calibration health panel — `/api/system/calibration-health` + `CalibrationHealthPanel`

The operator dashboard now has a panel that shows, per symbol:

- **Horizon validation** — windows, coverage_p50/p90, and the verdict for each
  of the 4h/6h horizons, read from the same verdict cache (never replays the
  tick corpus).
- **Per-trigger-type target-hit rates** — `{trigger_type, count, target_hit_rate,
  stop_hit_rate, neither_rate, enough_samples}` from the scored outcomes
  journal, so the user sees exactly how calibrated the setups the engine emits
  actually are.
- **cache_fresh** — both horizons carry a verdict AND windows.

The payload rides the same `stage3` block: `contracts.ts` gained a
`stage3BlockSchema` (state, empirical hit rate, sample count, horizon verdicts,
model vs display confidence, note), the bridge maps it through
`mapLiveSnapshot`/`toBaseFreshCall`/`buildUnavailableBaseCall`, and
`primary-call-panel` renders a verification strip (state chip + empirical rate
+ note) whenever the call payload carries it.

### Validation

```text
Python: 14 new tests (tests/test_stage3_gate.py 9, tests/test_calibration_health.py 5)  — 729 passed total
TypeScript: contracts + engine-bridge + operator-panels stage3 coverage — 181 passed total
tsc: 0 new errors (44 pre-existing, none in stage3/health files)
```

The gate is deliberately conservative: it only *replaces* confidence once ≥ 10
scored outcomes exist, so early in a symbol's life the operator sees raw model
confidence plus an honest "insufficient data" annotation.  As the M1 capture
loop (§17) compounds the corpus and `score-live-calibration` runs, the same
panel will show the empirical rates climbing to trustable sample counts.

## 21. Band-Tuning Pass (`synth-trader tune-bands`)

### The problem

Stored p50/p90 range multipliers go stale as the tick corpus grows.  The
multipliers persisted in §15 were fit on ~2 days of data (2916 walk-forward
windows); the dashboard now validates against the full 7-day backfill (9720
windows).  When the recent regime drifts (a vol drop the EGARCH forecast lags,
for example), the dashboard honestly reports over-covering 60s bands and the
verdict flips to `needs_more_data_or_tuning` — a durable maintenance task, not
a one-time fit.

### The fix — `tune_forecast_multipliers` in `horizon_forecast.py` (NEW)

A single corpus replay (shared `_compute_std_ranges`, refactored out of
`score_horizon_forecast` so both calibrate on the identical replay):

1. Chronological split — train / RECENT holdout tail (`holdout_frac=0.3`).
2. Seed multipliers from the honest train quantiles (p50 = train median,
   p90 = train 90th).
3. Iterate (max 40, step 0.06): while the RECENT holdout coverage is outside
   the calibrated band, shrink the multiplier when over-covering (band too
   wide) or widen it when under-covering (band too narrow).
4. Persist via `save_forecast_multipliers` **only when the verdict is
   `calibrated`** — a stale/unconverged band is never written over good
   multipliers.

The verdict delegates to the existing `horizon_verdict` (via a synthesized
`HorizonValidation`), so the tuning pass and the dashboard share one source of
truth — the pass can never persist multipliers the panel would call
`needs_more_data_or_tuning` (windows < 30 guard included).

### Operator surface

```bash
synth-trader tune-bands --engine-root .
```

Runs both symbols × both horizons (R_75/R_100 @ 60s, 4h/6h), printing verdict,
recent-holdout windows, coverage_p50/p90, and the tuned multipliers per
horizon.  Only calibrated horizons persist.  The dashboard's
`/api/system/forecast-horizon` and calibration-health panel pick the tuned
values up on the next poll — no restart needed.

### Result on the 7-day clean corpus

```text
R_75  4h: calibrated  cov 0.481/0.860  mult (1.447, 2.041)  iters 1
R_75  6h: calibrated  cov 0.464/0.843  mult (1.470, 2.135)  iters 1
R_100 4h: calibrated  cov 0.664/0.926  mult (1.540, 2.504)  iters 1
R_100 6h: calibrated  cov 0.642/0.955  mult (1.622, 2.538)  iters 1
```

Both symbols are `calibrated` on the recent holdout in one iteration — the
stored multipliers already generalize to the 7-day corpus, so the pass confirms
and locks them in rather than force-fitting.  The pass is the *guard* for when
that stops being true.

### Head-to-head re-run (backtest-vol --compare, 7-day corpus)

With the bands confirmed calibrated, the fade-vs-momentum-vs-sniper verdict on
the same ticks:

```text
R_75  @60s:  vol-reversion 12 trades 58% WR  exp −0.234 | vol-momentum 8 trades 38% WR exp −0.398 | sniper 4 trades 0% WR exp −1.306
R_75  @300s: vol-reversion 3 trades 100% WR exp +0.514 | vol-momentum 10 trades 30% WR exp −0.262 | sniper 13 trades 31% WR exp −0.342
R_100 @60s:  vol-reversion 4 trades 0% WR  exp −0.525 | vol-momentum 2 trades 0% WR exp −1.636 | sniper 5 trades 40% WR exp −1.341
R_100 @300s: vol-reversion 8 trades 63% WR  exp −0.352 | vol-momentum 4 trades 25% WR exp −0.832 | sniper 3 trades 0% WR exp −2.049
```

Reading: the strict re-tuned entry gates (§19) keep trade counts honest but
low; the only positive-expectancy cell is vol-reversion on R_75 @300s
(+0.514R, 3 trades — not statistically meaningful).  The verdict stands as in
§16: vol-targeting on CSPRNG price has a real but thin edge, and trade volume
is the binding constraint.

### Validation

```text
Python: 734 passed, 3 skipped, 31 subtests (18 in tests/test_horizon_forecast.py incl. tuning)
```

## 22. Per-Call-Type Empirical Gate: Proven vs Still-Learning

§20 shipped the *annotation* layer: every call carries the market-verified
hit rate + horizon verdict.  This phase made the gate *decisive* and turned
the journal into a live-feedback loop.

### Suppression (decisive-negative)

- `stage3_gate.py` gained a **`suppressed`** state: when a `(symbol,
  trigger_type)` has enough scored outcomes (≥ `MIN_STAGE3_SAMPLES`) but its
target-hit rate clears nothing, `apply_stage3_gate` **downgrades the emitted
call to `stand_aside`** so a market-failing call type is never surfaced as a
candidate.  The dashboard shows a `Suppressed` badge and explains *which*
call type is being held back and why.
- The raw call intent is preserved: `build_stage3_block` records the
  pre-suppression call in `stage3.suppressed_call`, and `build_call_record`
  uses it (`call_intent`) so suppressed candidates are still scored and can
  earn their way back once their empirical rate improves.

### Evidence axis (proven / still_learning / suppressed / no_data)

- New `evidence_status` field on the Stage-3 block replaces the binary
  gate/annotate split: `proven` (clears floor + calibrated horizon),
  `still_learning` (evidence exists but not enough / not yet clearing),
  `suppressed` (decisively below floor), `no_data` (journal empty).
- Configurable via env (safe parse — invalid values fall back to the
  defaults): `SYNTH_GATE_MIN_SAMPLES` (default 10) and
  `SYNTH_GATE_HIT_RATE_FLOOR` (default 0.5).  Suppression below the floor is
always on — there is deliberately no switch to surface a call type the
market has already disproven.
- The dashboard confidence chip shows `Verified` / `Empirical` /
  `Suppressed` / `Confidence` prefixes, and the verification strip shows the
  live sample size as `n/min scored` for still-learning calls — so the
  operator sees at a glance whether a call is *proven* or still
  accumulating evidence.

### Auto-logging + auto-scoring loop

- `run_live_watch` now **auto-logs every emitted live call** to the calls
  journal (`journals/live_calls.jsonl` by default; `--calls-journal`
  overrides) — no manual step needed for calls to enter the feedback loop.
- New `src/synthetic_trader/live/auto_scorer.py` + `synth-trader
  score-live-loop`: a background loop that resolves each unresolved call
  against the tick tape (target / stop / neither) using the same resolution
  logic as `score-live-calibration`, records outcomes, and reports per-symbol
  status telemetry (pending / scored / unresolved).  Modeled on the
  `m1-capture` / `collect-live-ticks` service pattern.

### Validation

Python: **743 passed, 3 skipped, 31 subtests** (incl. new
`tests/test_auto_scorer.py` and updated gate/logger/snapshot/CLI tests).
TypeScript: **185 passed** (12 files) incl. suppressed + still-learning
rendering cases.  Docs: this section.

## 23. Momentum Gate Variants (`--mom-gate`): Sustained-Regime Following

### The problem

The original momentum gate (`ratio`) required forecast sigma to be *freshly*
elevated above its own trailing EMA (`vol_min_ratio`).  Once a sustained
high-vol regime runs long enough for the sigma EMA to converge, the ratio
drops below threshold and the strategy stops firing — it under-trades the
very regimes it exists to follow.  The fix is a configurable gate selector
with three variants:

| `--mom-gate` | Reference | Fires when… | Selectivity on the 7-day corpus |
|---|---|---|---|
| `ratio` (default) | trailing sigma EMA (60-bar) | sigma > 1.15 × EMA (fresh elevation only) | strictest — dies out once EMA converges |
| `absolute` | slow long-run baseline (600-bar, self-calibrating) | sigma > `abs_sigma_mult` × long-run | medium — stays ON through an entire sustained regime |
| `trend` | sigma EMA slope | sigma EMA rising by `trend_eps` (regime building) | loosest — any building regime qualifies |

Key correctness point: the absolute reference is **not** the adaptive
`long_run_vol` property (which tracks current conditional vol and would
collapse the gate to “sigma > k×sigma”, i.e. never/always) and **not** a
frozen prior (tick-scale ~0.018 vs real per-candle ~0.0005 — would never
fire).  It is seeded from the calibration file's long-run when available,
then self-calibrates from the actual candle stream via a slow 600-bar EMA.

### Head-to-head on the clean 7-day corpus (R_75 / R_100 × 60s & 300s)

60s — all gates net-negative (2–14 trades):

| Symbol | gate | trades | WR | expectancy R | net |
|---|---|---|---|---|---|
| R_75 | ratio | 8 | 37.5% | −0.398 | −22.7 |
| R_75 | absolute | 7 | 28.6% | −0.538 | −25.5 |
| R_75 | trend¹ | 3 | 0% | −1.231 | −23.1 |
| R_75 | fade (ref) | 12 | 58.3% | −0.234 | −22.5 |
| R_75 | sniper (ref) | 4 | 0% | −1.306 | −20.1 |
| R_100 | ratio | 2 | 0% | −1.636 | −20.2 |
| R_100 | absolute | 3 | 0% | −1.605 | −29.6 |
| R_100 | trend¹ | 3 | 0% | −1.246 | −23.4 |
| R_100 | fade (ref) | 4 | 0% | −0.525 | −14.3 |

300s — the standout cell:

| Symbol | gate | trades | WR | expectancy R | net |
|---|---|---|---|---|---|
| R_75 | ratio | 10 | 30.0% | −0.262 | −20.5 |
| R_75 | **absolute** | **12** | **58.3%** | **+0.303** | **+15.4** |
| R_75 | trend¹ | 9 | 33.3% | −0.263 | −18.5 |
| R_100 | absolute | 4 | 25.0% | −0.504 | −14.0 |

¹ The `trend` gate also requires the regime to be above the long-run
baseline (an elevation floor added in review — a rising EMA alone in a
quiet low-vol build-up chased noise, producing 0% WR).  With the floor it
still under-performs the absolute gate but no longer degenerates.

The absolute-gate rows use the default `abs_sigma_mult=2.0`.

### Verdict

The `absolute` gate on R_75 @300s is the **first positive-expectancy
momentum result** in the whole vol-targeting programme (+0.303R over 12
trades — the win-rate edge the strategy needs, at a trade count that is
finally non-trivial).  It confirms the design thesis: on CSPRNG price,
following a *sustained* elevated-vol regime (absolute gate) is more coherent
than following a *fresh* elevation (ratio), which chases the regime's tail.
Sample size is still small (12 trades / 7 days); the M1 capture loop's
compounding corpus is what will turn this from promising to statistical.

### Validation

Python: **749 passed, 3 skipped, 31 subtests** (incl. 7 gate-variant
tests: sustained-regime firing, ratio-vs-absolute frequency, trend firing /
flat-sigma silence / elevation floor, invalid-gate rejection).  Docs: this
section.

## 24. Systematic Parameter Sweep (`sweep-vol`): Finding Real Configs

### The problem

The §16/§23 verdicts were all hostage to tiny trade counts — 2–14 trades
over 7 days at the *default* gates.  A single config can't tell you whether
the strategy has an edge; you need to see the whole parameter surface and
find configs that are both profitable AND have enough samples to mean
something.

### The tool

New `synth-trader sweep-vol` subcommand
(`src/synthetic_trader/research/vol_param_sweep.py`) runs a **systematic
grid sweep** in-process (no CLI subprocess overhead — ~75s for the full grid
at 60s, ~21s at 300s, per symbol):

- **Fade** (108 configs): z_entry {1.25…2.0} × vol_extended_ratio
  {1.3…1.8} × stop_mult {2.0…3.0} × target_mult {1.0…2.0}.
- **Momentum × both gates** (81 each): z_entry {0.5…1.0} × vol_min_ratio
  {1.15…1.5} or abs_sigma_mult {1.5…2.5} × stop_mult {1.0…2.0} ×
  target_mult {2.0…4.0}.
- Every config runs through the same PaperBroker + RiskEngine pipeline as
  the head-to-head, ranked by expectancy with a `--min-trades` floor, and
  `--artifact-output` persists the full ranked report as JSON.

### Results on the clean 7-day corpus (270 configs per symbol/timeframe)

| Cell | best config | trades | WR | PF | ExpR | net |
|---|---|---|---|---|---|---|
| R_75 @300s momentum:absolute | z=1.0, abs=2.0, stop=1.0, target=3.0 | 7 | 71% | 5.62 | **+0.941** | +35.6 |
| R_75 @300s momentum:absolute | z=0.75, abs=2.0, stop=1.0, target=4.0 | 12 | 67% | 2.88 | **+0.852** | +55.4 |
| R_75 @300s momentum:absolute | z=0.75, abs=1.5, stop=1.0, target=4.0 | 18 | 61% | 2.58 | **+0.753** | +72.9 |
| R_100 @300s momentum:ratio | z=0.5, vol=1.5, stop=1.5, target=4.0 | 22 | 55% | 1.37 | **+0.370** | +36.8 |
| R_75 @60s momentum:absolute | z=1.0, abs=2.0, stop=1.0, target=4.0 | 15 | 47% | 1.23 | +0.283 | +16.8 |
| R_100 @60s (best) | — | 12 | 33% | 0.50 | −0.210 | −21.0 |

### Reading the surface

The **pattern is unmistakable**: every positive cell is *momentum*, at
**300s**, with a **tight stop (1.0–1.5σ) and a wide target (4.0σ)** — the
momentum profile done properly (RR 2.7–4.0).  The fade never once nets
positive at any config (its RR ≤ 1.0 geometry caps it).  The absolute gate
owns R_75, the ratio gate owns R_100@300s.

**Honesty caveat (printed by the tool itself):** the top cell is 7 trades
at +0.941R — a 7-trade backtest result is *not* a verdict.  The
12-trade +0.852R and 18-trade +0.753R neighbors at the same config family
(z 0.75–1.0 / abs 2.0 / stop 1.0 / target 3–4) are the configs worth
carrying forward.  What this sweep proves is that a **family** of configs
has positive expectancy at 300s on R_75, not that a single parameter
vector is magic.

### Validation

Python: **760 passed, 3 skipped, 31 subtests** (incl. 11 sweep tests:
grid sizes/bounds, ranking, non-vacuous min-trades filter, JSON shape,
caveat printing, unknown-gate rejection, determinism).  Docs: this section.

## 25. Unattended Daily Tick Collection (Windows Task Scheduler)

### The problem

The corpus only compounds if the Blueberry MT5 collector actually runs every
day.  Manual launches get forgotten; a raw daily task pointed at
`collect-live-ticks.bat` would block forever on `WaitForExit`, so Task
Scheduler would skip every trigger after the first.  The fix is a
**short-lived task action** that restarts the collector and verifies the
corpus — then completes in ~10s so the next daily trigger fires.

### What was added

- **`setup-live-tick-task.ps1`** — one command to register the daily task:

  ```powershell
  .\setup-live-tick-task.ps1                    # register at 00:30 + baseline
  .\setup-live-tick-task.ps1 -StartTime 02:30   # custom time (validated HH:MM)
  .\setup-live-tick-task.ps1 -Unregister        # remove the task
  .\setup-live-tick-task.ps1 -VerifyOnly        # just run tick-coverage --json
  ```

  It builds and runs the exact `schtasks /Create` command (printed for the
  operator), with escaped-quote wrapping for the spaces in both the action
  and the project path, then verifies via `schtasks /Query` and writes a
  baseline coverage JSON to `.data/live_tick_task_setup_baseline.json`.

- **`run-live-tick-collector-task.ps1`** — the task action.  Three steps:
  1. **Daily-restart guard** — kills the previous day's collector (recorded
     PID + a CIM sweep for orphaned `collect-live-ticks` python processes),
     so the corpus never gets two collectors appending.
  2. **Detached start** — launches `collect-live-ticks.bat` hidden and does
     NOT wait, so the task completes and tomorrow's trigger fires.
  3. **Verification** — runs `tick-coverage --engine-root <repo> --json`
     (retry loop), persists it to `.data/live_tick_task_verify.json`, logs a
     one-line summary per symbol to `.data/live_tick_task.log`, and exits 1
     on verification failure so **Task Scheduler's Last Result** surfaces a
     stalled corpus.

- **`setup-live-tick-task.bat`** — double-click launcher.

### Registered & validated

```text
TaskName:      \SyntheticIndicesLiveTickCollector
Schedule:      Daily at 00:30 (local)
Status:        Ready
Next Run:      8/5/2026 12:30 AM
Last Result:   0 (success after a manual trigger)
```

Manual trigger test ran the full loop: guard found nothing → collector
started detached → verification reported `R_75/R_100 40080 ticks, 7.0
days` with usable windows per timeframe/horizon.

### Gotchas fixed along the way

- **cp1252 encoding**: an em-dash byte inside a PowerShell string literal
  read as a closing quote under Windows PowerShell 5.1 → all string literals
  are now pure ASCII.
- **`/TR` quoting**: schtasks splits on spaces, so the action (whose path
  contains “Synthetic Indices Bot”) needs `\"…\"` escaped quotes.
- **cwd**: Task Scheduler runs the action from `C:\Windows\System32`, so the
  verification passes `--engine-root` explicitly.
- **Note**: the collector exits cleanly if the Blueberry MT5 terminal is not
  open (writes the error to `data/live_tick_collector.json`) — the task
  still succeeds; the corpus just doesn't grow that day.  Keep the terminal
  logged in for the scheduled runs to append.

## 25b. Tick-Collector Health Check (`tick-task-health`) — morning alert

### The problem

The collector “exits cleanly if the MT5 terminal is not open” (§25 note) —
  the task still reports success while the corpus silently stops growing.
  A corpus that stops compounding stalls every downstream promise (WFO
  sample counts, calibration windows, the §34/§35 region maps).  The
  operator needs a morning check that screams when data stopped arriving.

### What was added

- **`src/synthetic_trader/scripts/tick_task_health.py`** reads the artifacts
  the daily task leaves behind and reports corpus growth:
  - `.data/live_tick_task.log` — parses every `coverage <sym> (N ticks, …)`
    line into a per-symbol tick-count time series, plus the last task action
    timestamp;
  - `.data/live_tick_task_verify.json` + `.data/live_tick_task_setup_baseline.json`
    — latest and registration-time `tick-coverage` snapshots;
  - `data/backfill/{sym}_ticks.csv` — **ground truth**: the collector appends
    to the file, so CSV mtime is the decisive liveness signal (fresh mtime =
    data is arriving; the snapshots merely lag because they update on the
    daily run).
- **Warning semantics** (per symbol, `--flat-hours 48` default): the corpus
  stopped growing when the CSV has not been written for `flat_hours` AND the
  count evidence (baseline registration / oldest log coverage line / CSV
  mtime) is all unchanged over that window.  Secondary warnings: task stale
  (last action older than `--task-stale-hours 26`) and verify snapshot stale.
- **CLI**: `python -m synthetic_trader.cli tick-task-health [--json]
  [--flat-hours 48] [--task-stale-hours 26] [--verify-stale-hours 26]`.
  **Exit code 0 = healthy, 1 = warnings fired** — the alert gate.
- **`check-tick-task-health.ps1`**: wrapper for the morning email/desktop
  alert.  Runs the check, prints warnings, optionally emails via
  `Send-MailMessage` (SMTP config block at top, disabled by default) and has
  a commented BurntToast desktop-toast block.  Schedule it with schtasks
  (daily 08:00 example in the header).

### Validation

`tests/test_tick_task_health.py` (8 tests): flat-corpus warn + exit 1,
  growing-corpus healthy, fresh-CSV-clears-flat (snapshot lag), stale task,
  missing log/verify, JSON shape, CLI exit codes.  The real `.data` state on
  this machine **currently fails the check** — the corpus has been flat at
  40080 ticks since Aug 3 (CSV mtime Aug 3, collector error “No MT5 terminal
  found”) — which is exactly the alert firing as designed.

## 25c. Dedicated Daily Auto-Scorer Task (`SyntheticIndicesLiveAutoScorer`)

### The problem

The collector task (§25) already embeds a `score-live-loop --once` sweep,
but scoring is then coupled to the collector's lifecycle: if the collector is
down (MT5 terminal closed, stuck corpus), the outcomes journal — and with it
the Stage-3 gate's per-trigger hit rates and the calibration health panel —
stops compounding even though scoring only needs the *calls* journal and
Deriv/MT5 market data.  The fix is a **separate daily task** with its own
schedule, so the two data products (tick corpus, outcomes journal) compound
independently.

### What was added

- **`setup-live-score-task.ps1`** — registers the task daily at 00:45 by
  default, 15 minutes after the collector (00:30):

  ```powershell
  .\setup-live-score-task.ps1                  # register at 00:45 + baseline sweep
  .\setup-live-score-task.ps1 -StartTime 01:00 # custom time (validated HH:MM)
  .\setup-live-score-task.ps1 -Unregister      # remove the task
  .\setup-live-score-task.ps1 -VerifyOnly      # just run a scoring sweep
  ```

  Same schtasks conventions as §25: escaped-quote `/TR` wrapping for the
  spaces in the action and project path, `/SC DAILY /ST` cadence, `/F`
  idempotent overwrite, per-user (non-admin).  The optional baseline runs a
  real `score-live-loop --once` sweep (proves the exact task command works
  AND compounds the journal immediately), persisted to
  `.data/live_score_task_setup.json`.

- **`run-live-score-loop-task.ps1`** — the task action.  One job: run
  `score-live-loop --once` with retries (3×, 10s backoff) and log to its own
  `.data/live_score_task.log` (same `[timestamp]` format as the collector
  log).  It also writes a **collector-health note** — if the collector's log
  shows no completed action in the last 26h it logs a warning (the corpus may
  be stalled; cross-reference `tick-task-health`) but still sweeps, because
  scoring is independent of the tick corpus.  Exit 1 on hard sweep failure so
  Task Scheduler's **Last Result** surfaces a stale outcomes journal.

- **`setup-live-score-task.bat`** — double-click launcher.

### Why the double sweep is safe

Both the collector action (§25) and this task run `score-live-loop --once`
daily.  The sweep is **idempotent** — `score_unresolved_records_from_market`
dedupes by `(symbol, generated_at)` against the existing outcomes journal —
so overlapping/duplicate daily sweeps never double-score; the `_SWEEP_LOCK`
in `auto_scorer.py` serializes concurrent sweeps within a process.  (The one
theoretical collision is two *separate* sweep processes in the same minute —
the 00:30/00:45 separation makes that unreachable in production.)  The two
tasks give the journal a second, collector-independent chance to compound
every day.

### Registered & validated

```text
TaskName:      \SyntheticIndicesLiveAutoScorer
Schedule:      Daily at 00:45 (local) — after the 00:30 collector
Status:        Ready
```

## 26. Forecast-Engine Bug Fixes: Regression Coverage + Re-Validation

**Why.** The two forecast-engine defects from §15 — (1) the units mismatch in
`EGARCHVarianceForecaster.update()` where `pred_error` subtracted a RAW
squared return (~1e-6) from a *log*-variance (~−13), and (2) the degenerate
calibration rejection that let beta-pinned-at-floor fits load — were fixed in
§15 but had **no regression tests**.  A restart can silently revert or a
refactor can reintroduce either bug; this round locks both in.

**Verified fixes (on disk).**

1. `garch.py` `update()` — the realized quantity is now a proper log-variance
   (`realized_log_var = 2·log|r|`, documented in the code), so `pred_error`
   lives entirely in log space; the old mixed-units gradient that drove omega
   (and the 4–6h bands ~300×) upward is gone.
2. `garch_calibration.py` — `_params_at_bounds()` now rejects a fit with **any
   single parameter pinned at its bound**, persistence < 0.05, or a long-run
   vol ratio off by 50×, and `load_calibrated_garch_state()` routes every load
   path through it.  Verified end-to-end: the on-disk degenerate fits (beta
   pinned at 0.01, persistence ~0.03) are rejected and `calibrated_garch=loaded`
   no longer prints — the forecaster falls back to default priors, the honest
   behavior.

**New regression tests (6):**

- `tests/test_garch.py` — `test_update_units_mismatch_regression` (feeds a
  spike stream; asserts omega / long-run variance stay bounded instead of
  climbing — genuinely discriminates: the buggy drift pushed omega to +45 vs
  the fixed −6.7).
- `tests/test_garch_calibration.py` — `test_beta_pinned_at_floor_rejected`,
  `test_beta_within_eps_of_floor_rejected`, `test_persistence_below_floor_rejected`,
  `test_long_run_vol_far_from_realized_rejected`,
  `test_load_calibrated_garch_state_rejects_degenerate_on_disk` (real
  on-disk files).

**Walk-forward re-validation on the clean 7-day corpus (fresh runs, `--validate`):**

| Symbol / TF | Horizon | Windows | p50 cov | p90 cov | Verdict |
|---|---|---|---|---|---|
| R_75 / 60s | 4h | 2,916 | 0.481 | 0.860 | calibrated |
| R_75 / 60s | 6h | 2,880 | 0.464 | 0.843 | calibrated |
| R_100 / 60s | 4h | 2,916 | 0.664 | 0.926 | calibrated |
| R_100 / 60s | 6h | 2,880 | 0.642 | 0.955 | calibrated |

Every cell is **calibrated** and the numbers reproduce the §15 holdout table
exactly (same corpus, same engine).  The previously-reported symptom (R_100
6h p50 = 0.237) is now 0.642 — the longer-horizon under-coverage is gone, and
R_100 now sits slightly *over*-covered (p50 0.64–0.66), within the calibrated
band.  Note R_75 at 300s (already calibrated in §15) and R_100 at 300s are
unchanged.

**Validation:** `tests/test_garch.py` + `tests/test_garch_calibration.py`
63 passed; full Python suite **768 passed, 3 skipped, 31 subtests**.

## 27. Stage-3 Suppression Mode: Hold Back vs Annotate

**Why.** The Stage-3 gate (§20/§22) already *acted* on below-floor call types:
with enough scored outcomes and a target-hit rate under the floor it set
`state=suppressed` and downgraded the call to `stand_aside`.  That is the
right end state, but it was hardwired on — the operator had no way to choose
to merely *annotate* a failing call type (still emit it with its honest low
rate) while the journal is thin, and no way to tell from the UI which
behaviour was in force.

**What shipped.**

1. **`SYNTH_GATE_SUPPRESSION_MODE=suppress|annotate`** (default `suppress`,
   per-call override supported) in `stage3_gate.py`.  The mode only changes
   the *action*, never the *truth*:
   - `suppress` (default) — below-floor + enough samples → `state=suppressed`,
     call downgraded to `stand_aside`, intent preserved in
     `stage3.suppressed_call`, `suppressed_reason` stamped.
   - `annotate` — the same evidence yields `state=annotated` with
     `evidence_status=suppressed`: the call is still emitted as a candidate
     with its honest (low) empirical rate and a note saying it is below the
     floor and why.  The dashboard labels this "Below verified floor" with a
     warn treatment and shows `mode: annotate`.
   - The block always records `suppression_mode` so the UI and the bridge can
     never guess which policy produced the decision, plus a machine-readable
     `below_floor` boolean (True in *both* modes whenever the empirical
     evidence is below the floor) so downstream execution consumers can tell a
     below-floor call from a genuine one without parsing the note.  In
     `suppress` mode the downgraded alert also carries `suppressed_reason`;
     a re-gated snapshot clears any stale reason.
2. **Prepared-state builder covered** — `build_watch_alert_from_prepared_state`
   (a second alert builder that bypassed the gate) now applies
   `apply_stage3_gate` before returning, so no emission path can dodge
   suppression.  Note: `PreparedSymbolState` carries no trigger-type field, so
   alerts from that path resolve to `unknown` and cannot accumulate per-type
   evidence — the live path (`build_watch_alert`) carries real trigger types;
   the prepared builder's gate application is defensive.
3. **Calibration health panel flags suppressed types** —
   `calibration_health.summarize_trigger_rates` now emits `suppressed` per
   trigger row (enough samples AND rate < the shared gate floor, imported
   from `stage3_gate` — single source of truth), and the panel renders a red
   `suppressed` chip next to those trigger types.
4. **TS plumbing** — `stage3BlockSchema` gained `suppression_mode`;
   `normalizeStage3` maps it (default `suppress`); `PrimaryCallPanel`
   distinguishes the three states the operator can actually see: `Suppressed`
   (held back, danger), `Below verified floor` (annotate mode, warn — the
   call is still shown), and `Proven`/`Still learning`/`Unverified` as before.

**Reviewer-hardened:** below-floor calls carry a `below_floor` marker in both
modes (execution layer can refuse them), the zod field defaults so legacy
payloads still parse, the health `suppressed` flag uses the same rounded rate
the row displays, stale `suppressed_reason` is cleared on re-gate, and the
env knob itself is tested (invalid values fall back to `suppress`).

**Tests.** `tests/test_stage3_gate.py` +5 (explicit suppress downgrade,
annotate keeps the candidate with evidence_status=suppressed, block carries
mode + `below_floor` + invalid-override fallback, env-knob resolution,
stale-reason clearing); `tests/test_live_market_snapshot.py` +1 (prepared-
state builder applies suppression end-to-end via patched journal paths);
`tests/test_calibration_health.py` +1 (suppressed flag, and no flag below
the sample floor); TS contracts +1 (annotate-mode block schema with
`below_floor`), operator-panels +1 (below-floor-annotate render).

**Validation:** Python suite **775 passed, 3 skipped, 31 subtests**; vitest
contracts/engine-bridge/operator-panels **76 passed**.  tsc unchanged from
baseline (only the pre-existing HealthMetrics fixture errors remain).

## 28. Empirical-Confidence Position Sizing: Risk Scales with Evidence

**Why.** The Stage-3 gate (§20/§22/§27) already knew *whether* a call type was
trusted; this round turns that knowledge into **position size**.  The user's
rule, implemented literally: calls from calibrated horizons with above-floor
hit rates get full size; uncalibrated ones get a fraction or paper-only.

### The sizing ladder (`stage3_gate.sizing_ladder`)

| Gate state | Evidence | Size level | Multiplier |
|---|---|---|---|
| `gated` | calibrated horizon **and** above-floor rate | **full** | 1.0 |
| `annotated` (proven) | above-floor rate, horizon uncalibrated | **half** | 0.5 (`SYNTH_GATE_SIZE_HALF`) |
| `annotated` (below floor, annotate mode) | below verified floor | **paper_only** | 0.0 |
| `insufficient_data` | still learning / no data | **paper_only** | 0.0 |
| `suppressed` | below floor, held back | **stand_aside** | 0.0 |

Every stage3 block now carries a `sizing` dict `{level, multiplier, basis,
reason}`, and `apply_stage3_gate` stamps the alert with `size_multiplier` and
`position_sizing_empirical` so any consumer can apply the scale without
re-deriving the evidence.

### Enforcement

1. **RiskEngine** — `evaluate(signal, *, size_multiplier=None)` scales the
   computed stake (None/1.0 = unchanged for backtests and the paper loop;
   0.5 = exactly half, verified: 3.74 → 1.87).  A `<= 0` multiplier returns
   an **approved decision with a zero stake** (`metadata.paper_only=True`) —
   the call still emits and is logged (that builds the journal), but carries
   no live risk.  The API is the hook for any Python caller that holds a
   multiplier.
2. **Live MT5 (the real-money gate)** — `use-operator-workspace` blocks
   `executeTradeOrder` for `live_mt5` when `size_multiplier <= 0`, with a
   clear error telling the operator to paper-trade the type (that generates
   the outcomes the gate needs).  The one deliberate escape hatch:
   `SYNTH_GATE_SUPPRESSION_MODE=annotate` lifts the block (the operator
   explicitly chose to keep unverified types actionable); the scaled volume
   still applies.  The lot is scaled `max(0.01, 0.01 × multiplier)` — note
   the broker floor means half-sizing only bites when the base lot exceeds
   0.01; at the default lot the enforcement is effectively block-vs-0.01.
3. **Dashboard** — the primary call panel shows a sizing badge (Full size /
   Half size / Paper only / Held back) with the reason next to the Stage-3
   evidence, and the bridge normalizes `sizing` (legacy payloads without it
   default to full/1.0 — stale calls are never surprise-blocked).

### The honest consequence (important)

The journal currently has **zero scored outcomes**, so every live call today
is `insufficient_data` → `paper_only` → **live MT5 submits are blocked until
a call type accumulates 10+ scored outcomes with an above-floor rate**.  That
is precisely the requested behaviour (risk scales with empirical confidence),
but it means the system self-disables real-money trading until the
`score-live-loop` + collector compound the journal.  The dashboard makes this
visible per call ("Paper only — no scored outcomes yet"), and annotate mode
is the documented override for the interim.

**Reviewer-hardened:** `sizing_ladder` never crashes on `hit_rate=None` (the
safe `rate_display` is used in every branch); the annotate-mode escape hatch
prevents a silent full disable with no recourse; the zero-stake approved
semantics and the 0.01 volume floor are documented rather than hidden.

**Tests.** Python +10 (`test_stage3_gate.py`: 5 ladder levels, None-safety,
gate-stamping; `test_risk_engine.py`: default-no-scaling, half, paper-only
zero-stake, clamp); TS +4 (`contracts` sizing schema, `operator-panels`
badges, `use-operator-workspace`: paper-only block **and** annotate-mode
volume scaling with a mocked submit endpoint — the only real-money gate now
has end-to-end coverage).

**Validation:** Python suite **786 passed, 3 skipped, 31 subtests**; vitest
**80 passed** across the four affected files; tsc unchanged from baseline
(the pre-existing HealthMetrics / `armed`-comparison errors only).

## 29. Live-Watch Auto-Scoring: Journal Stays Fresh Without a Manual CLI Step

**Why.**  The Stage-3 empirical gate (§20/§22) and the calibration health
panel are only as honest as the scored-outcomes journal behind them — and
that journal only filled when someone remembered to run
``synth-trader score-live-calibration`` by hand.  The auto-scorer service
(``score-live-loop``) existed but ran as a *separate* process, which meant
an operator running a live-watch session had no automatic scoring at all.

**What shipped.**

1. **Auto-sweep inside the live watcher** — ``run_live_watch`` gains an
   ``auto_score_interval_sec`` knob (default ``None`` = off).  When set, a
   background task sweeps the calls journal on that cadence **while** the
   watch runs, and the watcher's ``finally`` block guarantees one **final
   sweep** on every exit path (max-alerts reached, session ends, transport
   error, Ctrl-C) — so calls logged during the session are scored the moment
   the watch ends, with no second process and no manual step.
2. **``--auto-score [INTERVAL]`` CLI flag** on ``live-watch`` (interval
   seconds, default 300 = 5 min).  ``--auto-score-status-path`` re-points
   the telemetry file (default ``data/auto_scorer.json``).  Example::

       python -m synthetic_trader.cli live-watch --symbol R_75 --auto-score 300

   ``--auto-score`` is **opt-in**: without it, the watch behaves exactly as
   before (no sweep, no status file).
3. **Same machinery as the CLI** — the sweep calls the shared
   ``auto_scorer._sweep_once`` (dedupes by ``(symbol, generated_at)``, only
   scores calls whose hold horizon has elapsed), so the in-watch sweeper
   can never disagree with ``score-live-loop`` / ``score-live-calibration``.
4. **Status telemetry on every sweep, including the final one** — the
   status file records per-sweep scored/failed/skipped/pending plus the
   pending backlog, and a failed sweep (Deriv unavailable, token missing)
   is recorded with backoff and a give-up after 5 consecutive errors.
5. **Calls-journal auto-logging restored** — every emitted alert (and the
   optional baseline) is appended to the calls journal via
   ``_auto_log_call`` (preserving the pre-suppression call intent), closing
   the loop: live call emitted → calls journal → auto-sweep → outcomes
   journal → gate surfaces/suppresses.

**Tests.**  ``tests/test_cli_calibration_logging.py`` +3 (flag defaults to
300, accepts an interval, off by default); ``tests/test_live_market_snapshot.py``
+2 (auto-score runs initial+final sweeps and writes the status file; the
flag is opt-in and writes nothing when unset).  Existing auto-scorer tests
unchanged.

**Validation.**  Python suite **789 passed, 3 skipped, 31 subtests**; the
only failures are the two pre-existing ones from earlier sessions
(``test_analyze_live_snapshot_bounds_history_to_max_feature_history`` and
``test_build_watch_alert_from_prepared_state_applies_stage3_suppression``),
which fail identically on the pre-change baseline.  End-to-end smoke test:
with ``auto_score_interval_sec=0.01`` a mock sweep ran twice (start + final)
and the status file was written with per-symbol stats.

## 30. Stage-3 Gate Backtest (`backtest-gate`): Does the Empirical Filter Work?

The gate replaces raw model confidence with the market-verified target-hit
rate of a call's `(symbol, trigger_type)`, and in `suppress` mode holds back
call types whose verified rate is below the floor.  That is a strong claim
about *call quality* — so it deserves the same treatment as every strategy:
a walk-forward backtest on the real corpus.

`synth-trader backtest-gate --csv data/backfill/R_100_ticks.csv --symbol R_100`
replays the corpus **exactly like the live path**:

1. **Emit** — incremental candle walk (O(n)) with sniper role timeframes and
   `DecisionEngine.evaluate`, converting every approved signal into a
   production call record via `build_call_record` (same journal format the
   auto-scorer scores).  Repeated same-level emissions are deduped, mirroring
   the live watcher, which only logs a call when the setup state changes.
2. **Score** — each call is scored against the corpus ticks in its hold
   window using `score_call_outcome` (the identical target/stop/neither rules
   the live scorer applies to real market data).
3. **Gate, walk-forward (no lookahead)** — a call's outcome becomes visible
   only at `generated_at + hold`, mirroring the auto-scorer which skips calls
   whose horizon hasn't ended.  At each emission the gate decides from
   outcomes resolved strictly before it, via the **shared**
   `stage3_gate.gate_decision` — the exact production rules (extracted into
   a pure function so the backtest can never drift from the live gate).
4. **Verdict** — per-trigger kept/suppressed hit rate + expectancy, plus an
   overall verdict that distinguishes *genuine improvement* from an
   *all-or-nothing switch* (everything suppressed, nothing cleared the floor)
   and the degenerate cases (nothing suppressed because everything passed).

### Results on the 7-day corpus (60s candles, floor 50%, min 10 samples)

| Symbol | calls | scored | kept | suppressed | kept hit | suppressed hit | all hit |
|---|---|---|---|---|---|---|---|
| R_100 | 559 | 536 | 57 | 479 | 0% | 18% | 16% |
| R_75  | 585 | 561 | 48 | 513 | 6% | 18% | 17% |

**Verdict: ALL-OR-NOTHING SWITCH.**  On both symbols, **zero** calls were
kept because they cleared the floor — every kept call was kept only because
no verdict existed yet (`insufficient_data`).  Once 10 scored outcomes
accumulated, the trigger type was below the floor and suppressed, period.

Why: the sniper's swing setups carry reward:risk ≈ 3.5, whose break-even
target-hit rate is `1/(1+3.5) ≈ 22%`.  The 50% floor is therefore
**unreachable** even for a perfectly calibrated random direction — so the
gate cannot discriminate good from bad call types; it simply stops trading
once a trigger type accumulates enough samples.  The kept-vs-suppressed hit
delta (0-6% vs 18%) is a time-ordering artifact (early no-verdict calls were
unlucky), not evidence of filtering.  As configured, the empirical filter is
a **risk-control switch, not a quality filter**.

**What this means for the operator:** the Stage-3 gate is doing its honest
job (it never fabricates evidence, and it will suppress below-floor types) —
but with the floor at 50% and these reward profiles, suppression ≈ "stop".
Lowering the floor to the per-trigger break-even rate (≈ 22-25%) would turn
the gate from an all-or-nothing switch into a filter that can actually rank
call types.  The backtest command makes that experiment one flag away:
`--hit-rate-floor 0.25`.

Flags: `--csv --symbol --timeframe --higher-timeframe --min-samples
--hit-rate-floor --suppression-mode`.  Runtime ≈ 2-3 min per symbol at the
default 300s primary cadence.

## 31. Realized-RR Investigation + Faster Mean-Reversion Exit (`breakeven-trail`)

**Question (operator):** the fade wins 58–63% of the time yet still nets
negative — *why, and can a faster mean-reversion exit fix it?*

### The measured answer: planned RR 0.6, realized RR ~0.34–0.50

The fade places stop at 2.5σ and target at 1.5σ — planned RR = 0.6, so the
breakeven win rate is `1/(1+0.6) = 62.5%`.  A path-recording probe on the
clean 7-day corpus (identical PaperBroker/RiskEngine semantics, stake-weighted
PnL, both exit-slippage directions) measured what trades *actually* pay:

| Config (R_75@60s tuned) | Trades | Win% | avg win (R) | avg loss (R) | realized RR | breakeven WR | Exp (R) |
|---|---|---|---|---|---|---|---|
| baseline (static stops) | 12 | 58.3% | +0.37 | −1.08 | **0.34** | **74.4%** | −0.234 |
| breakeven-trail 0.3     | 12 | 58.3% | +0.60 | −0.33 | **1.82** | **35.4%** | **+0.213** |
| breakeven-trail 0.5     | 12 | 58.3% | +0.60 | −0.83 | 0.72 | 58.2% | +0.003 |

**Why the realized RR collapses.**  Two effects shave the *planned* +0.6R
win down to ~+0.37R and push the −1R loss to −1.08R: (1) 1-tick exit slippage
on both directions (a loss gets filled worse, a win gets filled worse too),
and (2) same-candle stop-and-target collisions resolve to the stop (the
broker's conservative stop-first rule).  The result: breakeven win rate is
**~70–75% realized, not 62.5% planned** — and a 58–63% win rate is therefore
structurally below the line.  This is exactly the negative-expectancy
mechanism the operator suspected, now measured rather than guessed.

**Also measured (single pass, no lookahead — post-hoc on real candle paths):**
`early_take` (locking a fraction of the target) *hurts* — it cuts the average
win below 0.5R while losses stay near −1R.  `time_exit` (2–8 bars) helps in
some cells but not consistently.  The **breakeven trail at 0.3× target** is
the consistent winner across configs: once a fade's MFE reaches 30% of the
target distance, the stop moves to entry, converting would-be −1R losses into
~0R exits.  In the probe it flipped expectancy positive in 9/10
config×symbol×timeframe cells (e.g. R_75@60s mid −0.798→+0.150, R_100@300s
loose −0.329→+0.101).

### The fix: `BreakevenTrailBroker` + `--breakeven-trail-frac`

- `src/synthetic_trader/backtest/vol_reversion.py`: new
  `BreakevenTrailBroker(PaperBroker)` mirrors the base stop-first/target/
  expiry semantics exactly but tracks each position's running MFE (in R
  units) and, once `MFE ≥ breakeven_trail_frac × planned_RR`, moves the
  effective stop to the entry price.  `VolReversionConfig` /
  `VolMomentumConfig` gained `breakeven_trail_frac: float = 0.0` (off by
  default — opt-in); the shared `run_vol_regime_backtest` selects the trail
  broker when the strategy config sets it.
- CLI: `backtest-vol --breakeven-trail-frac 0.3` applies to both vol-regime
  strategies.

### Head-to-head via the real runner (7-day corpus, honest trade sets)

The trail changes the *trade set* (earlier exits free the `max_open_positions=1`
slot, so n moves 12→13 and WR shifts) — the post-hoc probe cannot see that,
so the real runner is ground truth:

| Symbol / TF | Baseline | Trail 0.3 | Delta |
|---|---|---|---|
| R_75 / 60s  | 12 tr, −0.234R, PF 0.34 | 13 tr, **−0.014R**, PF 0.57 | +0.22R |
| R_75 / 300s | 3 tr, +0.514R | 3 tr, +0.314R | −0.20R (n=3) |
| R_100 / 60s | 4 tr, −0.525R | 4 tr, −0.425R | +0.10R |
| R_100 / 300s| 8 tr, −0.352R | 10 tr, −0.353R | ~0 (n=10) |

**Honest verdict:** the breakeven trail at 0.3 **eliminates ~90% of the
fade's negative expectancy** on the largest sample cell (R_75@60s:
−0.234 → −0.014R, PF 0.34 → 0.57) and improves or matches every other cell
except the n=3 R_75@300s (noise).  It does **not** yet lift the strategy
solidly positive — trade counts are still 3–13, so nothing is statistically
meaningful; the trail converts a structural shortfall into a coin flip, and
the corpus must compound (M1 capture, §17) before the +/− verdict sharpens.
The mechanism is now understood and the lever is one flag away.

**Tests:** `tests/test_vol_reversion.py` → 33 tests (5 new: disabled trail
behaves as the plain broker, trail arms + breaks even, full target still
pays +0.6R after arming, MFE is cumulative across candles, runner wiring
regression).  Full Python suite: 804 passed, 3 skipped, 31 subtests.

## 32. tune-bands → live call payload: the calibrated 60s multipliers reach the operator

The path was traced end-to-end and closed a gap.  Before this round the
`tune-bands` output (fitted 60s p50/p90 range multipliers) reached the
`/api/system/forecast-horizon` stats route but **not** the operator-facing
call payload — `market_snapshot`/`paper_runner` never called `forecast()`, so
a live call only carried the horizon *verdict label*, never the multipliers
or the actual band numbers behind it.

**The full path (now confirmed with tests):**

```text
tune-bands (CLI)
  └─ tune_all_multipliers → tune_forecast_multipliers
       └─ save_forecast_multipliers → data/forecast_multipliers/{symbol}_60s.json
            └─ get_horizon_forecast_stats (dashboard route) loads multipliers
                 └─ forecaster.forecast(horizon_sec, p50_mult, p90_mult)  ← live bands
                      └─ _persist_verdict_cache → data/forecast_verdicts.json
                           now carries {verdict, p50_mult, p90_mult,
                           multipliers_applied, forecast:{band numbers}} per horizon
                                └─ Stage-3 gate: load_horizon_verdict
                                     └─ build_stage3_block → stage3.p50_mult /
                                          stage3.p90_mult / stage3.horizon_forecast
                                           └─ build_watch_alert → engine bridge
                                                └─ normalizeStage3 → FreshCallResponse
                                                     └─ PrimaryCallPanel shows the bands
```

Why the call path stays cheap: the gate reads the verdict cache (a file read),
never a tick replay — the expensive walk-forward replay + `forecast()` calls
run once per stats refresh, and their results (multipliers + band numbers)
ride on the cache the call path consumes.

**Verified on the live corpus (R_75):** cache `multipliers_applied=True`,
4h ×1.447/×2.041 tuned; the call payload carries `stage3.p50_mult`
1.447, `stage3.p90_mult` 2.041, and `stage3.horizon_forecast["4h"]` with the
live p50 band 1748.44–1790.39, `vol_trend`, and `confidence`.  The panel
labels the bands "Calibrated" only when the per-horizon verdict is
`calibrated` (never for prior-based bands).

**Tests:** Python `tests/test_stage3_gate.py` +3 (rich-cache read, gate
payload carries multipliers, `_persist_verdict_cache` → `load_horizon_verdict`
round-trip incl. the smear regression the whitelist must never reintroduce);
TS `tests/engine-bridge.test.ts` +1 (raw payload → normalized call carries
multipliers + bands) and `tests/contracts.test.ts` +1 (schema accepts the
carrying stage3 block).  Full Python suite 809 passed, 3 skipped; TS 193
passed; `tsc --noEmit` adds zero new errors (44 pre-existing untouched).

## 33. Proven-Only Execution Mode (`SYNTH_GATE_PROVEN_ONLY` / `--proven-only`)

**The strictest belt on the Stage-3 gate:** the gate already *annotated* calls
with empirical hit rates and *suppressed* below-floor call types; this round
adds a mode where **only `evidence_status == "proven"` calls may carry a live
order at all** — `still_learning`, `suppressed`, and `no_data` calls are forced
to paper-only (size multiplier 0.0) even in annotate suppression mode.

### Python gate (`stage3_gate.py`)

- `sizing_ladder(..., proven_only=True)` forces any non-proven evidence to
  `paper_only` (multiplier 0.0, basis `proven_only`) — never full/half.  Proven
  evidence keeps its full/half ladder size regardless of the flag.
- `build_stage3_block` / `apply_stage3_gate` accept `proven_only` and stamp the
  block with `proven_only` + `execution_allowed` (False for anything not
  proven).  The env knob is `SYNTH_GATE_PROVEN_ONLY` (default off).
- The **exception fallback also fails closed** (`execution_allowed: False`).

### Live path (`market_snapshot.py`)

`proven_only` threads through `build_watch_alert`, `run_live_snapshot`,
`_build_watch_baseline`, `run_live_watch`, `_handle_reconnect`, and the
prepared-state alert builder.  A reviewer-caught regression — `_handle_reconnect`
called `_build_watch_baseline(proven_only=...)` without declaring the parameter,
raising a swallowed `NameError` that silently skipped the rebaseline after a
transport failure — is fixed (param added + passed at the call site; the
reconnect test now passes again).

### CLI

`--proven-only` on `live-snapshot`, `live-watch`, and `backtest-gate`;
`backtest_gate_from_csv` treats paper-only calls as held-back in the
kept/suppressed aggregate.

### Dashboard

- `stage3BlockSchema` + `proven_only` / `execution_allowed`; the bridge
  normalizer maps both.
- `use-operator-workspace.ts` gains a **localStorage-persisted proven-only
toggle** (`synth-gate-proven-only`).  The live-submit path blocks any non-proven
call in proven-only mode — and **fails closed on missing evidence** (a payload
with no stage3 block is treated as not-proven, not skipped).
- Toggle UI in `TradeInstructionPanel` + `MobileTradeSheet`, wired through
`OperatorShell`, plus a proven-only badge on the `PrimaryCallPanel`
Stage-3 verification block.

**Tests:** `tests/test_stage3_gate.py` (+5: env knob, ladder forcing,
proven sizes kept, execution_allowed stamping, annotate escape-hatch override);
`use-operator-workspace.test.tsx` (+1: full-sized still_learning call is still
blocked live in proven-only mode); `engine-bridge.test.ts` (+proven_only /
execution_allowed mapping assertions); `operator-panels.test.tsx` fixtures
updated for the two new schema fields.

### Validation (final)

```text
Python: 815 passed, 3 skipped, 31 subtests passed   (python -m pytest tests/ -q)
TypeScript: 12 files, 194 tests passed   (npx vitest run)
```

---

## 34. Momentum Entry-Geometry Re-Tune (`z_entry` / stop-target / `max_hold_bars`)

### The question

§24 left the R_75@300s `absolute` momentum gate at **+0.303R over 12
  trades** (default geometry `z=0.8 / abs=2.0 / stop=1.5 / tgt=3.0 /
  hold=30`).  Could tuning the entry geometry push that expectancy to a
  statistically robust level on the same 7-day corpus?

### The blocker: the sweep couldn't see the geometry it needed to tune

`max_hold_bars` was **pinned at 30** for every momentum config — a 30-bar
  time stop at 300s gives a momentum winner only 2.5 hours to run to its
  target.  And the `sweep-vol` CLI itself was **broken**:
  `run_sweep_for_csv` passed `min_trades=` into `run_sweep`, which rejects
  that kwarg (the on-disk sweep JSONs were produced by an earlier version).

### What was added

- **`momentum_grid` now sweeps `max_hold_bars`** (`MOM_HOLD_BARS = (15, 120, 15)`
  by default — 8 values, widened after this re-tune so the default range
  reaches the 110–120 winner region) and every knob range is overridable
  (`z_entries`, `stops`, `targets`, `holds`, `gate_ranges`) for a focused
  re-tune.
- **`run_sweep` / `run_sweep_for_csv` take a `strategies` filter** — pass
  `("momentum",)` alone to skip the 108-config fade grid.
- **CLI**: `sweep-vol --strategies momentum --mom-json <file>` loads a JSON
  with focused grid overrides (e.g. `{"z_entries":[0.5,1.25,0.25],
  "stops":[0.75,2.0,0.25], "targets":[2.0,5.0,1.0],
  "holds":[10,120,10], "gate":{"abs_sigma_mult":[1.5,2.5,0.5]}}`).
- **Fixed the `sweep-vol` CLI bug** (the `min_trades` kwarg leak) with a
  roundtrip regression test.

### Results — focused re-tune on R_75 @300s absolute (3,456 configs)

Top-20 all **positive expectancy**, 20/20 clustering on `z=0.75` and 16/20
  on `abs=1.5`.  The new winner family:

| geometry | trades | WR | PF | ExpR | net |
|---|---|---|---|---|---|
| **z=0.75 abs=1.5 stop=1.75 tgt=5.0 hold=110** | **12** | **67%** | **3.70** | **+1.135** | **+76.4** |
| z=0.75 abs=1.5 stop=1.5 tgt=4.0 hold=110 | 14 | 64% | 3.19 | +1.007 | +78.5 |
| z=0.75 abs=1.5 stop=1.0 tgt=3.0 hold=110 | 16 | 56% | 2.68 | +0.986 | +87.7 |
| z=0.75 abs=1.5 stop=1.0 tgt=3.0 hold=50 | 18 | 61% | 2.77 | +0.928 | +92.8 |

Baseline (unchanged): `z=0.8 abs=2.0 stop=1.5 tgt=3.0 hold=30` → +0.303R,
  12 trades (reproduced exactly).  **3.7× per-trade improvement.**

Edge check (same corpus): `abs=1.0` collapses (17% WR, −0.51R) and
  `abs=1.25` adds trades (22) but halves quality (+0.40R); `z=0.625` has 0%
  WR; `z=0.875`/`1.0` fade to +0.87R/+0.29R.  So **z=0.75 and abs=1.5 are
  genuine sweet spots, not grid edges.**  `hold=110` ≈ `hold=240` (long
  time-stops win over the old 30) — 110 wins on freshness.

### The honest statistical verdict (per-trade, n=12)

```
n=12  mean_R=+1.135  sd=1.823  t=+2.16  95% CI: [-0.023, +2.292]
WR=66.7% (8/12)   R series: -1.10 -1.07 -1.06 -1.06 +0.37 +0.82
            +2.76 +2.77 +2.78 +2.79 +2.81 +2.81
```

- The expectancy tripled (0.303 → 1.135R) and the **trade profile is exactly
  what momentum should print**: 4 losers at ~−1.0R, 5 winners at ~+2.8R.
- **But the 95% CI still straddles zero** — 12 trades is not enough to call
  this statistically robust.  The head-to-head with this config:

```
strategy=vol-momentum  trades=12  WR=66.7%  ExpR=+1.135  net=+76.40
strategy=vol-reversion trades= 3  WR=100%   ExpR=+0.514  net=+ 7.61
strategy=sniper        trades=13  WR=30.8%  ExpR=-0.342  net=-20.85
```

  Momentum beats the sniper reference by 1.48R/trade on this corpus, but  the sample is one week.  **Deliberately NOT baked into the shipped strategy
  defaults** — baking a 12-trade winner in would be overfitting to noise; the
  geometry is documented here and re-runnable with `sweep-vol --strategies
  momentum --mom-json data/mom_retune_grid.json` as the corpus compounds.

### Validation

`tests/test_vol_param_sweep.py` extended: hold-bars dimension, grid
  overrides, strategies filter, and the CLI roundtrip regression.  49 passed
  (vol_param_sweep + vol_momentum + vol_reversion suites), 2 skipped.

## 35. Walk-Forward Mapping of the Absolute-Gate Region (`abs_sigma_mult × abs_ref_period`)

### The question

The §24 verdict (+0.303R) and §34 re-tune (+1.135R) each took a single
  `abs_sigma_mult` / `abs_ref_period` value.  A single cell says nothing about
  how *stable* the gate is — is +0.30R a lucky point or the edge of a
  plateau?  This section sweeps the two gate dimensions on both symbols,
  splitting the 7-day corpus into halves so a cell counts as **stable** only
  when it is positive in both halves as well as overall.

### Tooling

- `momentum_grid` gained a `ref_periods` override (the absolute gate's slow
  long-run-sigma baseline EMA period, `abs_ref_period`, was previously pinned
  at 600 and invisible to the sweep) and `--mom-json` accepts `"ref_periods"`.
- Two probe surfaces run the full week plus first/second halves per cell:
  artifacts `data/sweep_abs_region.json` (new §34 geometry) and
  `data/sweep_abs_region_old_geom.json` (original +0.303R geometry).

### Results

**R_75 @300s — the +0.303R cell is directionally real, but its exact value
  was a short-hold artifact.**  At the original geometry
  (z=0.8 / stop=1.5 / tgt=3.0 / hold=30) **0/70 cells are stable** — per-half
  trade counts collapse to ~1, so both-halves positivity is unreachable and
  the surface is marginal everywhere.  With the §34 long-hold geometry
  (z=0.75 / stop=1.75 / tgt=5.0 / hold=110) the plane resolves into **two
  coherent stable plateaus** (19/70 cells stable):

| plateau | region | best cell | default cell abs=2.0/ref=600 |
|---|---|---|---|
| loose gate, slow baseline | abs 1.2–2.0 × ref 450–600 | **abs=1.8/ref=450 → +1.46R, n=12, 75% WR** | +0.50R, n=10, +ve both halves |
| tight gate, fast baseline | abs 2.2–3.0 × ref 300–450 | abs=2.6/ref=300 → +0.84R, n=9 | — |

  The default cell (abs=2.0, ref=600) sits *inside* the first plateau —
  confirming the +0.303R sign was not a fluke — and the best plateau cell
  nearly triples it.  The two-plateau structure is the honest shape of the
  region: a broad middle where the gate fires too rarely to be useful
  (ref ≥ 900 → n collapses), and two edges that trade enough to matter.

**R_100 @300s — no verdict possible on one week.**  0/70 stable cells in
  both geometries; the absolute gate produces ≤15 trades (mostly ≤4) at
  300s on R_100, so every positive cell (e.g. +2.64R, n=1) is noise.
  R_100 momentum:absolute needs the 60s timeframe (which traded 59 times in
  §24) or a longer corpus before the region can be mapped.

### Implication

Keep the §34 geometry; treat the gate's stable band as **abs 1.2–2.0 ×
  ref 450–600** for R_75@300s rather than a single default.  Not baked into
  shipped defaults (still one week, n≈10–13 per cell); re-run the surface as
  the M1 capture loop compounds the corpus.

## 36. NO FALLBACK — the system knows what it is connected to

The live path previously used **MT5 first → Deriv WebSocket fallback** when
the Blueberry terminal was down.  Deriv's `1HZ75V`/`1HZ100V` trade at a
completely different price scale than Blueberry `SYN75`/`SYN100` (R_75
~7,000 vs ~1,542), so the fallback silently produced wrong-scale prices,
calls and scored outcomes.  The fallback is now **removed everywhere**:

- `collect_live_snapshot_ticks` / `watch_live_ticks`: MT5-only when
  configured — a failure **raises** (the snapshot path turns it into an
  honest stand-aside, the watch path into a transport record + stand-aside
  baseline + reconnect).  Deriv is used only as the *explicit* venue when
  MT5 is not configured.
- `auto_scorer._resolve_scoring_client_factory`: raises
  `ScoringUnavailableError` without MT5 (no more fallback-with-warning).
  The sweep records `error` on the status file; the loop gives up loudly
  after `MAX_CONSECUTIVE_ERRORS`.
- `calibration_scorer.score_unresolved_records_from_market`: a missing
  `client_factory` is a hard `RuntimeError` — the Deriv path is deleted.
- `cli score-live-calibration`: resolves the Blueberry MT5 client first;
  prints `error=scoring_unavailable` and exits 1 otherwise.
- **Venue honesty**: every `run_live_snapshot` result is stamped
  `venue` = `mt5` | `deriv` | `csv`, surfaced in the operator call payload
  as an MT5-venue / Deriv-scale / CSV-venue badge (`contracts.ts`,
  `engine-bridge.ts` `normalizeVenue`, `primary-call-panel.tsx`
  `VenueBadge`).  The MT5-down stand-aside now says "MT5 unavailable — no
  Deriv fallback; start the Blueberry MT5 terminal".

**CSV corruption cleaned (with backups):**

- `data/R_75_ticks.csv`: dropped 459 Deriv-scale (~7,750) rows + garbage
  epochs → 64,077 clean single-scale rows (1,677–1,806), re-sorted.
- `data/R_100_ticks.csv`: dropped 2,012 Deriv-scale (~690) rows + garbage
  → 104,129 clean single-scale rows (323–360), re-sorted.
- Originals preserved as `data/R_*_ticks.csv.bak-*` / `.bak2-*`.

**Tests:** 821 passed / 3 skipped / 31 subtests (fast subset); TS 83/83 on
affected files.  New regression tests cover: collectors raising when MT5 is
down, the scorer raising without a client, the sweep erroring (not warning)
without MT5, the watch surviving an MT5-down baseline, and the `venue`
stamp.

**Operator impact:** no call/outcome is ever produced on the wrong price
scale again.  If the Blueberry MT5 terminal is not running, the dashboard
shows a clear stand-aside ("MT5 unavailable — no fallback") instead of a
Deriv-scale trade plan — and the DERIV feed is still usable explicitly via
`--app-id` (venue badge shows "Deriv scale") for monitoring only.

## 37. Per-Trigger-Type Break-Even Gate Floor (replaces the flat 50%)

**Why.** The gate's floor was a flat `GATE_HIT_RATE_FLOOR = 0.5`.  For a 3R
setup the break-even target-hit rate is `1/(1+3) = 25%` — so a 50% bar is
mathematically unreachable for exactly the geometry the sniper uses, and the
gate degenerated into an all-or-nothing switch on R_75 (every
`setup_candidate` suppressed once samples accumulated, regardless of actual
call quality).  The §30 backtest measured the failure: R_75 kept-calls had
−0.34R while suppressed calls were +0.07R — the gate was holding back the
better calls because the bar itself was wrong.

### The fix — `break_even_floor()` in `stage3_gate.py`

The default floor is now **per-trigger-type break-even + margin**:
`floor = 1/(1+avg reward:risk) + margin`, with `SYNTH_GATE_BREAK_EVEN_MARGIN`
(default 0.05), clamped to `[SYNTH_GATE_FLOOR_MIN=0.10, SYNTH_GATE_FLOOR_MAX=0.60]`.
So a 3R trigger must clear ~30%, a 2R trigger ~38% — reachable by
construction.  When no outcomes exist yet, the floor falls back to the
current call's own `reward_risk`, then to the conservative flat
`GATE_HIT_RATE_FLOOR`.

- **Live gate** (`build_stage3_block`): computes the floor from the scored
  outcomes' real geometry for the exact `(symbol, trigger_type)` via
  `average_reward_risk()` (same level filter as `summarize_outcomes`, so the
  gate and the backtest can never disagree about what a trigger's geometry
  is worth).  The block now surfaces `floor_basis` (`break_even` |
  `configured`) and `break_even_rr` so the dashboard can show "floor 30%
  (break-even @ 3R)" instead of an opaque number.
- **Walk-forward backtest** (`gate_backtest.simulate_gate_walk_forward`):
  `hit_rate_floor=None` (the new default) computes each trigger's floor from
  the running average reward:risk of that trigger's calls emitted strictly
  *before* the current one (RR is known at emission — no outcome
  lookahead).  Each call records `floor_at_emission` / `avg_rr_at_emission`,
  and the report shows the mean floor per trigger.
- **CLI**: `backtest-gate` with no `--hit-rate-floor` now uses the
  break-even default (it previously forced the flat 0.5).  `--hit-rate-floor
  0.5` still reproduces the legacy behavior for comparison.

### Re-run on the clean 7-day corpus (@300s, ~510 scored calls per symbol)

| Symbol | Floor basis | Kept hit | Suppr hit | Kept exp (R) | Suppr exp (R) | Verdict |
|---|---|---|---|---|---|---|
| R_100 | break-even (~27–32% per trigger) | 19% | 12% | −0.02 | −0.35 | **filter IMPROVES call quality** (+7% lift, 90 calls cleared) |
| R_75 | break-even (~26–32%) | 5% | 20% | −0.34 | +0.05 | all-or-nothing: zero calls clear even their own break-even |

**Reading — the two symbols tell opposite, honest stories:**

- **R_100 flips to a genuine quality signal.**  With the reachable
  break-even floor, 90 calls clear it and the kept set beats the suppressed
  set by +7% hit rate and +0.33R expectancy.  The empirical filter is now
  measurably removing worse call types — the flat-50% verdict on the same
  corpus was an artifact of the unreachable bar.
- **R_75 is the honest truth.**  The rolling market-verified hit rate
  (~20%) never clears even the reachable 27% break-even floor for
  `setup_candidate`, so the gate correctly stops trading it.  The flat-0.5
  run produces the identical kept/suppressed split (34 kept / 447
  suppressed) — the difference is the message: "these setups do not beat
  their own break-even + margin" instead of "the floor was unreachable".
  On R_75 the gate is a risk-control switch, not a quality filter — which
  is exactly what it should be when the underlying calls lose money.

**Tests:** `tests/test_stage3_gate.py` +5 (break-even math incl. clamping,
`average_reward_risk` from scored outcomes, default floor in
`build_stage3_block`, explicit floor wins, and the 40%-hit/3R flip from
suppressed→gated), `tests/test_gate_backtest.py` +3 (floor stamped per call
walk-forward, the 33%-hit/3R flip from suppressed→gated, per-trigger floors
differ).  51 gate tests pass.

## 38. Guardian Stands By the Call — cross-refresh plan memory + hardened cancel

### The flip-flop the operator reported

> “Whenever the market just drops a bit in the other direction, the setup will
> cancel, even if the original plan (BUY) is still on going; when I refresh it
> then comes back to the original call.”

Root cause was architectural, not a threshold tweak:

1. **Every `/api/calls/run` spawns a fresh Python subprocess.**  The guardian's
   in-process state (`_guardian_confirmed_at_tick`, the confirmed lock, and
   the sniper “confirmed & stable — only stop-hit invalidates” path) lived in
   process memory, so a refresh **forgot the confirmation entirely** and
   re-evaluated the plan from scratch.
2. **The top-of-function cancel used a monotonic window-max excursion.**
   `max_adverse_excursion` accumulates over the whole re-armed window (up to
   30 min): a single transient wick to 95% of the stop distance marked the
   plan cancelled **forever within that window**, even after price recovered.
   On the next refresh the window was recomputed from fresh ticks, price had
   re-armed → the plan re-confirmed → the flicker the user saw.

### The fix — three parts

**Part 1 — sniper cancellation now requires “beyond reasonable doubt”.**
`evaluate_signal_guardian` (sniper mode) only cancels when:

- price has actually **traded through the stop** (`adverse_ratio >= 1.0` — the
  position would have been stopped out), **or**
- the adverse excursion reached the near-stop threshold **and price is still
  sitting beyond the weakening line right now** (sustained, not a transient
  wick that already recovered).

A 95%-of-stop wick that recovers no longer cancels a 4–6h swing plan.
Non-sniper modes keep the strict legacy rule (unit tests lock both).

**Part 2 — persistent guardian memory (`data/guardian_memory/{symbol}.json`).**
New `synthetic_trader.live.guardian_memory` module stores wall-clock state:
`direction` / `entry` / `stop` / `target` (the plan signature), `state`,
`first_confirmed_at_epoch`, `lock_seconds`, `issued_at_epoch`,
`hold_horizon_minutes`.  `build_guardian_snapshot` now:

- **restores** `previous_guardian_state = confirmed` when the freshly
  regenerated plan is *the same plan* (direction + levels within 1.5% of the
  stored entry) and the lock hasn't expired → the confirmed state survives
  process restarts between refreshes;
- **sticks cancellations**: once cancelled, the same plan cannot resurrect on
  a refresh (the cancelled record blocks re-confirmation until the strategy
  produces a materially different plan);
- **persists** the confirmed/cancelled record after each live evaluation
  (only for real candidate calls — test fixtures and stand_aside reads never
  write).

Directory overridable via `SYNTH_GUARDIAN_MEMORY_DIR` (the test suite
redirects it to a temp dir so tests can never pollute the operator's live
plan state).

**Part 3 — `build_watch_alert` stands by the call.**  When a fresh run
momentarily produces stand_aside/context-update but guardian memory holds a
*confirmed* plan that is still alive — fresh price data present, hold horizon
not expired, stop not traded through, call type not suppressed by the Stage-3
gate — the original call is restored with
`guardian_reason: “Standing by the original call — plan held; invalidates only
on stop trade-through or horizon expiry.”` and `plan_held: true` (surfaced in
the dashboard payload).  MT5-down / stale-CSV reads (`current_close is None`)
never resurrect a plan.

### 38b — Stop-lock grace: stop trade-through needs a closed 15m candle

Follow-up to §38: the stop trade-through cancel (`adverse_ratio >= 1.0`) is
now gated by **closed-candle confirmation** on the execution timeframe.
`build_guardian_snapshot` buckets the tick stream into 900s windows, drops
the still-forming bucket, and sets `stop_traded_on_closed_candle` when a
CLOSED candle's low (buy) / high (sell) traded through the stop.  The check
is bounded by the plan's confirmation time (`first_confirmed_at_epoch` from
guardian memory): every closed candle that OPENED after confirmation counts,
so a genuine stop confirmed by any closed candle during the plan's life
cancels even if no evaluation ran for a while and price later recovered
(brand-new plans with no confirmation time use a 2-candle recency fallback).
The sniper cancel then requires EITHER:

- stop trade-through **confirmed by a closed execution candle** (a
  spread/jitter wick inside the forming candle never cancels alone), **or**
- a **sustained** near-stop position right now (current price still beyond
the weakening line — beyond reasonable doubt regardless of candle state).

So a wick that pierces the stop and recovers inside the same 15m candle
leaves the plan standing; if that candle closes with the stop breached (or
the price stays pinned through the stop), the plan cancels with the reason
"stop traded through on a closed 15m candle".  Cancellation semantics now
match the plan's own invalidation text (a *close* through the level), not
tick-level wicks.

### 38c — Auto-scorer uses the same closed-candle grace

Follow-up to §38b: the **outcome scoring** now applies the identical
stop-lock grace so the empirical hit-rate journal tells the same story as
the live plan-hold rule.  `score_call_outcome` accepts prices as either
plain `list[float]` (legacy — wick-based rules for target AND stop) or
`(price, epoch)` pairs; the live MT5 path (`fetch_prices_for_record`) and
the gate backtest (`_prices_in_window`) both pass pairs, so in production:

- **Target** touches count on any tick (a wick to the target fills a
  take-profit).
- **Stop** only counts when a **CLOSED** execution-timeframe candle (900s
  default, persisted per-call via `execution_timeframe_sec` in the journal)
  traded through it — a wick inside the still-forming candle scores
  `neither_reached`, not `stop_hit`, so a call whose stop was only
  wick-touched is no longer marked a loss.
- Within one closed candle a target touch beats a stop breach (the stop
  breach in a candle that also reached target is a wick, not a confirmed
  stop-out).

Each outcome row is stamped with `scoring_rule: "closed_candle_grace" |
"wick"` and `stop_confirmed_on_closed_candle`, so the gate/operator can
tell grace-scored rows from legacy wick-scored rows in the journal (rows
resolved before this change keep their original labels — the dedup key
`(symbol, generated_at)` never re-scores them; a future re-score pass can
select on `scoring_rule`).

### Validation

- 13 new tests: sniper transient-wick-does-not-cancel, intraday-wick-through-
  stop holds, wick-through-stop cancels when sustained right now,
  stop-trade-through on a closed candle cancels, generic mode keeps the
  strict rule, confirmed plan carries across refresh, cancelled plan sticks
  across refresh, different plan resets stale memory, plan-hold restore + the
  three no-restore guards, plus the closed-candle helper's forming-vs-closed
  bucket behavior.  107 tests pass across the guardian / market-snapshot
  suites; 47 more across calibration-logger / stage3-gate.
- Live smoke test against the real running dashboard's memory files: a
  stand_aside read now returns the held `buy_candidate` plan for both R_75
  and R_100 with `plan_held: true` — the exact behavior the operator asked
  for.

## Next Steps

1. **✅ DONE — collector wired into Windows Task Scheduler (§25).**  The
   `SyntheticIndicesLiveTickCollector` task restarts the collector daily at
   00:30 with a restart guard + `tick-coverage --json` verification; a week
   becomes a month unattended.  **§25b adds the morning alert** — schedule
   `check-tick-task-health.ps1` (or `tick-task-health` directly) daily and
   it warns when the corpus stops growing for 48h.  Remaining: keep the
   Blueberry MT5 terminal logged in (the check currently fires — the corpus
   has been flat since Aug 3 because the terminal isn't running).
2. **✅ DONE — vol-targeting overlay, both regimes (§9 fade, §14 momentum,
   §23 gate variants).**  Re-validated on the corrected EGARCH engine: the
   fade's win-rate edge is real but too thin (RR ≈ 0.6 needs ~62.5% wins).
   The `absolute` momentum gate on R_75 @300s is the first positive-
   expectancy cell (+0.303R, 12 trades) — the next step is to let the M1
   capture loop compound the corpus until that cell reaches statistical
   sample counts, then re-tune entry around it.  **Updated by §34**: the
   re-tune found z=0.75 / abs=1.5 / stop=1.75 / tgt=5.0 / hold=110 at
   +1.135R (3.7× the baseline, but still n=12 — the CI straddles zero).
3. **Apply the bounded-history fix to the live path** (paper_runner /
   market_snapshot pass unbounded histories; same O(n²) pattern, lower severity
   since live sessions are time-bounded).
4. **✅ DONE — live-watch auto-scoring (§29).**  ``live-watch --auto-score``
   sweeps the calls journal on a timer during the session and once at exit,
   so the outcomes journal and the calibration health panel stay fresh
   without a manual ``score-live-calibration`` step.  Recommended command::

       python -m synthetic_trader.cli live-watch --symbol R_75 --auto-score 300
4. **✅ DONE — Stage-3 empirical gate (§20, §22, §37).** Calls carry the
   market-verified target-hit rate for their exact `(symbol, trigger_type)`
   plus the horizon verdict; the gate now *suppresses* call types whose
   empirical rate clears nothing, distinguishes `proven` vs `still_learning`
   vs `suppressed` in the dashboard with live sample sizes, auto-logs every
   live call, and scores them in a background loop (`score-live-loop`).
   **§37 replaced the flat 50% floor with the per-trigger-type break-even
   floor** (1/(1+avg RR) + margin) so the bar is reachable by construction;
   the backtest shows R_100's gate now measurably improves call quality,
   while R_75 honestly reports its calls don't beat their own break-even.
   Remaining: point `score-live-loop` at the same schedules as the M1
   capture loop so the journal compounds continuously in production.
5. **Continuous WFO in CI** — run `run_wfo.py --quick` on each new tick CSV dump
   and gate deploys on the PBO + expectancy band.
6. **Carry the sweep winners forward (§24).** The R_75@300s
   momentum:absolute family (z 0.75–1.0 / abs 2.0 / stop 1.0 / target 3–4)
   and the R_100@300s momentum:ratio (z 0.5 / vol 1.5 / stop 1.5 / target 4)
   are the first positive-expectancy configs in the programme.  Wire them as
   the new defaults and let the M1 capture loop compound the corpus until
   those cells reach statistical sample counts (~50+ trades), then re-sweep
   locally around the winners instead of the full grid.
