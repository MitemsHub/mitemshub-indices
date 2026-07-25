# Phase 3 Paper Realism, Analytics, and Monitoring Design

## Summary

Phase 3 expands the paper-trading layer beyond reliability into realism, analysis, and operator visibility. It is a three-part program:

1. Phase 3A: execution realism
2. Phase 3B: run analytics
3. Phase 3C: monitoring surface

This phase remains strictly paper-only. It does not enable real-money execution.

## Context

Phase 1 hardened the research core. Phase 2 made the live paper path shut down and account cleanly. The next step is to make paper-trading outputs more useful for actual decision-making by making them:

1. closer to live conditions,
2. easier to analyze across runs,
3. easier to observe during operation.

These should not be treated as separate unrelated projects. Execution realism changes outcome quality, analytics should explain the realism-adjusted results, and the monitoring surface should display the resulting data model.

## Goals

1. Reduce optimism in paper-trading outcomes by adding controlled execution realism.
2. Improve post-run analysis so strategy quality is easier to compare across runs.
3. Provide a lightweight operator-facing monitoring surface for paper-live sessions.
4. Keep all new behavior deterministic, testable, and clearly observable in artifacts.

## Non-Goals

1. No real-money trading.
2. No exchange-grade market impact simulation.
3. No large web platform or dashboard framework unless the monitoring requirements justify it.
4. No replacement of the current decision engine or model family in this phase.

## Design Principles

1. Build realism before analytics, and analytics before the monitoring surface.
2. Prefer configurable, deterministic assumptions over opaque realism logic.
3. Make each new assumption visible in outputs so runs remain comparable.
4. Keep the monitoring layer lightweight and grounded in already-produced artifacts.

## Program Structure

### Phase 3A: Execution Realism

The paper broker currently exits at exact strategy prices within a simplified candle model. That is useful for baseline research, but it can flatter strategy results.

Phase 3A should add configurable realism controls such as:

1. entry slippage,
2. exit slippage,
3. optional execution penalty or cost per trade,
4. explicit reporting of how these assumptions changed outcomes.

Requirements:

1. The realism model must be deterministic for a given run configuration.
2. The assumptions must be visible in artifacts and summaries.
3. The broker behavior must remain testable with small deterministic cases.

### Phase 3B: Run Analytics

Once execution realism exists, run analysis should become richer and more comparison-oriented.

Phase 3B should add:

1. stronger breakdowns of approved versus rejected signals,
2. shutdown-close and forced-close counts in performance summaries,
3. run-to-run comparison-friendly structured outputs,
4. execution-adjusted expectancy and PnL analysis,
5. useful rollups from journaled events.

This phase should improve both backtest and paper-live reporting where appropriate, while staying aligned with the current CLI-and-artifact architecture.

### Phase 3C: Monitoring Surface

The monitoring surface should be lightweight and operator-focused. It should not start as a large application unless that becomes clearly necessary.

It should provide visibility into:

1. current paper-live session state,
2. recent signals, approvals, rejections, and closes,
3. session resets and shutdown events,
4. recent performance summaries,
5. realism configuration currently applied.

The initial implementation can be a compact local monitoring surface backed by existing report and journal data, rather than a broad platform.

## Proposed Changes By Sub-Phase

### 3A Modules

Likely modules:

1. `src/synthetic_trader/execution/paper.py`
2. `src/synthetic_trader/config.py`
3. `src/synthetic_trader/backtest/engine.py`
4. `src/synthetic_trader/live/paper_runner.py`
5. `tests/test_paper_broker.py`

### 3B Modules

Likely modules:

1. `src/synthetic_trader/journal/trade_journal.py`
2. `src/synthetic_trader/reporting/serializers.py`
3. `src/synthetic_trader/backtest/engine.py`
4. `src/synthetic_trader/research/walk_forward.py`
5. `tests/test_reporting.py`

### 3C Modules

Likely modules:

1. a lightweight monitoring entry point or report surface
2. existing live/journal/reporting modules as data sources
3. tests covering monitoring data preparation and rendering behavior

## Data Flow Impact

The data flow becomes:

1. strategy generates intents,
2. paper execution applies realism assumptions,
3. journal stores richer execution-aware outcomes,
4. reports aggregate realism-adjusted outcomes,
5. monitoring surface displays the resulting operational state and summaries.

## Error Handling

1. Realism settings must fail fast if configured with invalid values.
2. Reports must distinguish missing data from zero values.
3. Monitoring views must degrade gracefully when no current session exists.

## Testing Strategy

1. Add deterministic broker tests first for realism assumptions.
2. Add report tests that verify execution-adjusted summaries.
3. Add lightweight monitoring tests around data preparation and rendering, not just visual snapshots.
4. Keep the full suite passing after each sub-phase.

## Success Criteria

Phase 3 is complete when:

1. paper execution supports explicit realism assumptions,
2. those assumptions appear in artifacts and affect results deterministically,
3. analytics explain realism-adjusted outcomes more clearly than the current summaries,
4. a lightweight monitoring surface exists for paper-live operation,
5. the automated test suite covers the new behavior and remains green.

## Follow-On Phase

Once Phase 3 is complete, the next likely phase is supervised live scaffolding and controlled pre-live readiness work, but only after the paper system is both realistic enough and observable enough to justify that step.
