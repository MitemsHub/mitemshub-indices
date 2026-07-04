# Phase 1 Research Hardening Design

## Summary

Phase 1 hardens the research core of the Synthetic AI Trader before any real-money execution work begins. The objective is to make backtest and walk-forward results more trustworthy, improve traceability of trading decisions, persist learned model state, and add targeted tests around the most failure-prone parts of the system.

This phase is intentionally scoped to the existing Python CLI architecture. It improves the current engine rather than replacing it.

## Context

The repository already has a coherent pipeline:

1. Tick ingestion and candle construction
2. Feature assembly across indicators, structure, and regimes
3. Online probability estimation
4. Decision fusion
5. Risk approval and stake sizing
6. Paper execution
7. Journaling and optional online learning

The main weaknesses are not that the system lacks a pipeline. The weaknesses are that the current validation surface is thin, reporting is limited, model state is transient, and some important trade decisions are not fully traceable after the fact.

## Goals

1. Increase trust in offline and walk-forward research results.
2. Preserve model learning state between runs when desired.
3. Make accepted and rejected trade decisions easier to audit.
4. Add focused tests around execution, validation, and risk behavior.
5. Prepare the codebase for the next phase: paper-trading realism and operational monitoring.

## Non-Goals

1. No real-money Deriv execution in this phase.
2. No frontend or dashboard in this phase.
3. No model-family replacement yet. The online logistic model remains the active model.
4. No large refactor of the repository structure unless needed to support the goals above.

## Design Principles

1. Preserve the current modular flow and CLI-first workflow.
2. Prefer additive changes over broad rewrites.
3. Improve observability and correctness before increasing automation.
4. Add tests only where they materially reduce regression risk.

## Scope

### 1. Richer Research Outputs

Backtest and walk-forward runs should produce richer structured outputs in addition to the current text summaries.

Expected additions:

1. Structured report objects that can be serialized to JSON.
2. Consistent run metadata including symbol, timeframe, training window, testing window, signal counts, rejected counts, model version, and key performance metrics.
3. Optional output paths in the CLI so reports can be saved for later comparison.

This makes runs comparable over time and creates an audit trail for strategy changes.

### 2. Model Persistence

The online model already supports save and load, but persistence is not part of the normal runtime workflow.

Phase 1 should:

1. Add explicit ways to load an existing model for research or paper workflows.
2. Add explicit ways to save the resulting model state after a run.
3. Ensure saved model artifacts include enough metadata to identify their origin and compatibility.

Persistence is needed so learning is not lost between sessions and so experiments can be reproduced more reliably.

### 3. Decision and Risk Traceability

The system currently records approved signals and trade outcomes, but rejected signals are not fully preserved for later analysis.

Phase 1 should extend journaling so that:

1. Approved signals are recorded with their rationale and model version.
2. Rejected signals are also recorded with the full rejection reason set.
3. Research runs can optionally emit a unified event stream or equivalent structured record showing what the strategy wanted to do and what risk allowed.

This will support failure analysis such as:

1. The strategy found opportunities but risk blocked most of them.
2. Confidence thresholds were too strict for a given regime.
3. A profitable-looking change produced more signals but lower approval quality.

### 4. Validation Correctness

Walk-forward research should remain chronologically correct and more explicit about what happened in each fold.

Phase 1 should:

1. Preserve strict no-leakage boundaries between training and test windows.
2. Expand fold-level metadata so each fold can be reviewed independently.
3. Make aggregate metrics and fold metrics easy to serialize and inspect.
4. Add tests that validate fold construction and expected aggregation behavior.

### 5. Targeted Test Expansion

Tests should be added where the current suite is weakest and where subtle bugs could distort research conclusions.

High-priority additions:

1. Paper execution edge cases, especially ambiguous stop and target hits, expiry, and forced close behavior.
2. Risk engine state transitions such as open position tracking, consecutive loss handling, and daily-limit resets.
3. Walk-forward fold construction and aggregation behavior.
4. Journal persistence and parsing behavior.
5. Model save and load round-trips.

Lower-priority additions, only if they provide strong value during implementation:

1. Feature-level invariants for regime or structure outputs.
2. CLI tests for new persistence and output options.

## Priority Order

Work inside Phase 1 should be executed in this order:

1. Strengthen research artifacts and reporting so results become reviewable and comparable.
2. Add model load and save support to the intended workflows.
3. Record approved and rejected decisions in a durable and structured way.
4. Add targeted tests around the highest-risk behaviors.

This order is deliberate. The first objective is to make the system's claims inspectable. The second is to make experimentation reproducible. The third is to make decisions explainable. The fourth is to lock the improved behavior in place.

## Proposed Changes By Module

### `src/synthetic_trader/backtest/engine.py`

Add richer result payload support and optional integration points for structured reporting and event capture.

### `src/synthetic_trader/research/walk_forward.py`

Add richer fold and aggregate reporting, plus serialization-friendly output helpers.

### `src/synthetic_trader/journal/trade_journal.py`

Extend the journal to record rejected decisions and possibly generalized event records without breaking current outcome handling.

### `src/synthetic_trader/models/online.py`

Keep the current model but make persistence easier to use from the surrounding workflows.

### `src/synthetic_trader/cli.py`

Add optional arguments for saving reports and loading or saving model artifacts in research-oriented commands.

### `tests/`

Expand tests around the narrow set of risk-heavy and research-heavy paths identified in this design.

## Data Flow Impact

The core trading flow remains unchanged:

1. Ticks become candles.
2. Candles produce features and a trade decision.
3. Risk approves or rejects that decision.
4. Execution manages open positions.
5. Journal and reporting layers record what happened.

The main change is that more of the system's internal decisions become durable artifacts rather than being lost after the run completes.

## Error Handling

New persistence and reporting features should fail clearly and early.

Requirements:

1. Invalid model files should raise explicit errors rather than silently resetting state.
2. Invalid output paths should fail with understandable exceptions.
3. Optional artifact generation should not corrupt the main journal or model files.

## Testing Strategy

The testing strategy for this phase is narrow and deliberate:

1. Add tests for the new behaviors being introduced.
2. Backfill tests only where current behavior is fragile or under-specified.
3. Keep test data synthetic and deterministic.
4. Prefer small unit-level tests plus a few integrated research-path tests over a large number of shallow smoke tests.

## Success Criteria

Phase 1 is complete when all of the following are true:

1. Backtest and walk-forward flows can emit structured artifacts for later comparison.
2. Model state can be loaded and saved through the intended workflows.
3. Approved and rejected decisions are both auditable after a run.
4. The added tests protect the highest-risk research and execution edge cases.
5. The existing full test suite still passes.

## Execution Cadence

This project is being handed over for active development rather than passive review. After the implementation plan is written and Phase 1 is completed, the next work should begin automatically with the highest-value follow-on priority rather than waiting for a fresh re-scoping cycle, unless a new constraint or direction is provided.

## Follow-On Phase

Once Phase 1 is complete, the next phase should be paper-trading realism and operational monitoring. That phase will improve live paper execution fidelity, shutdown handling, session awareness, and operating visibility, but it should be built on top of a research core that already produces durable and reviewable evidence.
