# Phase 7 MT5 Lifecycle Management Design

## Summary

Phase 7 extends the MT5 execution path beyond first order placement by adding controlled lifecycle management. The goal is to let the system synchronize MT5 positions, support supervised close actions, and journal lifecycle events in a structured way while preserving the existing fail-closed safety model.

This phase does not introduce autonomous MT5 lifecycle automation. It introduces the minimum execution-management layer needed to observe broker-side position state, act on it through explicit supervised close paths, and record those transitions clearly.

## Context

The repository now has:

1. a stable research and backtest core,
2. venue-aware MT5 scaffolding,
3. terminal-backed MT5 runtime readiness,
4. supervised MT5 first-order placement through an explicit CLI entry.

What is still missing is the lifecycle after entry. The current MT5 path can place a supervised order, but it cannot yet:

1. synchronize open MT5 positions into a structured internal state,
2. close a known MT5 position through a controlled supervised path,
3. journal lifecycle transitions such as sync results, close attempts, close successes, and broker-side rejections,
4. expose a fuller supervised order lifecycle beyond first placement.

The correct next step is to build lifecycle management on top of synchronized broker state rather than bolting close logic directly onto isolated ticket placement.

## Goals

1. Add MT5 position synchronization based on terminal-backed broker state.
2. Add structured lifecycle state for synchronized MT5 positions.
3. Add supervised close logic for synchronized MT5 positions.
4. Add richer execution journaling for sync and close lifecycle events.
5. Keep all lifecycle management fail-closed and operator-gated.
6. Add focused tests that do not require a live MT5 terminal.

## Non-Goals

1. No unattended lifecycle automation.
2. No continuous daemon that watches and reacts to positions automatically.
3. No broad order modification engine beyond what is needed for safe supervised management.
4. No changes to alpha, signal generation, or risk policy logic.
5. No weakening of existing Deriv, paper, or MT5 entry-path behavior.

## Design Principles

1. Synchronize broker state before taking lifecycle actions.
2. Fail closed when lifecycle state is missing, stale, or ambiguous.
3. Keep broker-facing lifecycle logic at the MT5 adapter edge.
4. Represent lifecycle transitions explicitly with typed results and journal events.
5. Preserve venue-neutral trading logic by keeping lifecycle details out of strategy and risk modules.

## Scope

### 1. MT5 Position Synchronization

The MT5 adapter should gain a synchronization function that reads broker-side positions for the configured symbol and returns a structured snapshot.

That snapshot should include:

1. normalized project symbol,
2. resolved MT5 symbol,
3. MT5 ticket identifiers,
4. direction and volume,
5. open price,
6. current price where available,
7. timestamp or broker-side time information,
8. whether the sync result is empty, singular, or ambiguous.

This should become the source of truth for any later close handling in this phase.

### 2. Structured Lifecycle State

The project needs a typed representation for synchronized MT5 lifecycle state and close results.

That structure should cover:

1. synchronized position snapshot,
2. sync outcome status,
3. close request target ticket,
4. close result acceptance or rejection,
5. broker response code and message,
6. resulting ticket/deal identifiers where available.

This gives the project a clean bridge between MT5 adapter actions, CLI reporting, and journal logging.

### 3. Supervised Close Logic

Close handling should be supervised and explicit.

Requirements:

1. the close path must only act on synchronized positions,
2. it must require explicit operator arming,
3. it must fail closed if no matching position exists,
4. it must fail closed if multiple ambiguous positions exist for the target scope,
5. it must return a structured close result rather than an untyped payload.

This is intentionally narrower than a full position-management engine. The objective is safe, supervised close control.

### 4. Lifecycle Journaling

The journal should gain structured lifecycle event coverage for MT5 execution management.

Examples:

1. `mt5_sync_summary`
2. `mt5_sync_position`
3. `mt5_close_attempt`
4. `mt5_close_result`
5. `mt5_close_rejected`

The journaling should focus on observability and traceability rather than being a full broker event store.

### 5. CLI Surface

The CLI should expose explicit lifecycle-management commands or subcommands that keep the operator in control.

Expected behavior:

1. print MT5 sync results clearly,
2. print lifecycle readiness and ambiguity failures,
3. support an explicit supervised close path,
4. print structured close results,
5. preserve current `mt5-live-order` behavior and earlier MT5 flows.

### 6. Delivery Order

This phase should be delivered in the following sequence:

1. MT5 position synchronization
2. controlled close logic
3. richer lifecycle journaling
4. integrated regression

This order matters because close logic should depend on synchronized broker state, and journaling is most useful once real lifecycle transitions exist.

## Proposed Changes By Module

### `src/synthetic_trader/execution/mt5.py`

Extend the MT5 adapter with structured position synchronization, close request helpers, and close result handling.

### `src/synthetic_trader/live/supervised_live.py`

Add supervised MT5 lifecycle helpers for sync-aware close handling while preserving fail-closed behavior.

### `src/synthetic_trader/cli.py`

Add explicit MT5 lifecycle-management command surfaces for sync and supervised close reporting.

### `src/synthetic_trader/journal/trade_journal.py`

Add richer lifecycle event emission for MT5 sync and close actions.

### `tests/`

Add focused lifecycle-management tests using fakes and stubbed MT5 responses rather than a real terminal.

## Data Flow Impact

The MT5 lifecycle path should become:

1. parse lifecycle command and MT5 config,
2. run MT5 runtime readiness checks,
3. synchronize broker-side positions,
4. decide whether the synchronized lifecycle state is actionable,
5. perform a supervised close only when the operator explicitly arms it and the lifecycle state is unambiguous,
6. return structured lifecycle results and journal events.

This keeps lifecycle state anchored in broker truth rather than inferred local assumptions.

## Error Handling

1. Runtime readiness failure should block lifecycle actions.
2. Missing synchronized positions should block close actions cleanly.
3. Ambiguous synchronized position sets should block close actions cleanly.
4. Broker-side close rejection should return a structured rejected result and a journal event.
5. Any unsupported lifecycle command or mode combination should fail visibly.

## Success Criteria

Phase 7 is complete when:

1. MT5 positions can be synchronized into structured lifecycle state,
2. supervised close logic works only on synchronized and unambiguous MT5 positions,
3. lifecycle journaling captures sync and close events clearly,
4. CLI lifecycle reporting is explicit and readable,
5. existing MT5 entry flows and earlier regressions remain green.

## Follow-On Phase

Once Phase 7 is complete, the next likely phase is deeper MT5 lifecycle refinement, including controlled modify logic, richer position reconciliation, more detailed execution analytics, and additional supervised lifecycle controls.
