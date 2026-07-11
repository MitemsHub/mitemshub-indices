# Phase 8 MT5 Modify And Reconcile Design

## Summary

Phase 8 refines the MT5 lifecycle layer by adding controlled position modification and richer reconciliation of broker-side position state. The goal is to make MT5 lifecycle management more accurate and safer before expanding into deeper execution analytics.

This phase does not introduce unattended position management. It introduces supervised modification controls and stronger reconciliation so the system can compare intended local lifecycle state with actual MT5 broker state and act only when that state is explicit and safe.

## Context

The repository now has:

1. MT5 runtime readiness,
2. supervised first-order placement,
3. broker-backed position synchronization,
4. supervised close handling,
5. lifecycle journaling for sync and close events.

What is still missing is the refinement layer between entry and exit. The current MT5 path does not yet:

1. support supervised modification of broker-side protection parameters,
2. reconcile broker-side lifecycle state against the system's current synchronized snapshot in a richer way,
3. report drift or mismatch clearly when positions differ from expected lifecycle assumptions,
4. provide a stronger lifecycle foundation for later execution analytics.

That makes `modify + reconcile` the correct next step before analytics. Without it, later MT5 performance analysis would be working from weaker lifecycle state.

## Goals

1. Add supervised MT5 modify logic for synchronized positions.
2. Add richer reconciliation of synchronized MT5 position state.
3. Detect and report lifecycle drift or ambiguity clearly.
4. Extend MT5 journaling with reconciliation and modify events.
5. Keep all refinement paths fail-closed and operator-gated.
6. Add focused tests that do not require a live MT5 terminal.

## Non-Goals

1. No unattended position modification.
2. No automatic trailing-stop engine in this phase.
3. No analytics expansion in this phase.
4. No changes to alpha, signal generation, or core risk policy.
5. No weakening of existing MT5 entry, sync, or close behavior.

## Design Principles

1. Reconcile broker truth before mutating broker state.
2. Fail closed when reconciliation is incomplete, stale, or ambiguous.
3. Keep MT5-specific refinement at the adapter and supervised-live edge.
4. Use typed lifecycle results rather than loose dictionaries.
5. Journal lifecycle refinements explicitly for auditability.

## Scope

### 1. Structured Reconciliation State

The MT5 lifecycle layer should gain a richer reconciliation result that goes beyond "positions exist" or "positions do not exist."

That result should describe:

1. synchronized positions,
2. whether the result is empty, singular, or ambiguous,
3. whether a requested ticket is present or missing,
4. whether the broker-side symbol mapping and position state are actionable,
5. any reconciliation failures or warnings that should block supervised mutation.

This makes lifecycle decisions depend on broker truth rather than inferred local expectations.

### 2. Supervised Modify Logic

The MT5 adapter should support supervised modification of synchronized positions.

This should include the minimum controllable fields needed for safe lifecycle refinement, such as:

1. stop-loss,
2. take-profit,
3. optional comment or request context where supported.

Modification should only be allowed when:

1. runtime readiness passes,
2. reconciliation confirms an actionable and unambiguous target,
3. the operator explicitly arms the action,
4. the requested change is structurally valid.

### 3. Reconciliation Fail-Closed Rules

The refinement layer must explicitly refuse modification when:

1. no synchronized position exists,
2. multiple positions exist and the target is ambiguous,
3. the requested ticket is not present,
4. the MT5 symbol mapping is invalid,
5. runtime readiness or broker-side state fails.

This keeps lifecycle refinement consistent with the rest of the supervised MT5 design.

### 4. Lifecycle Journaling

The journal should expand to cover modification and reconciliation events.

Examples:

1. `mt5_reconcile_summary`
2. `mt5_reconcile_mismatch`
3. `mt5_modify_attempt`
4. `mt5_modify_result`
5. `mt5_modify_rejected`

The purpose is traceability and operator review, not a full event-sourcing system.

### 5. CLI Surface

The CLI should expose explicit supervised MT5 refinement commands that remain readable and auditable.

Expected behavior:

1. print reconciliation summaries,
2. print why a target is not actionable,
3. support a supervised modify path for a specific synchronized position or a singular position result,
4. print structured modification results,
5. preserve earlier MT5 commands for entry, sync, and close.

### 6. Delivery Order

This phase should be delivered in the following order:

1. reconciliation state
2. supervised modify handling
3. richer journaling
4. integrated regression

That order keeps mutation dependent on explicit lifecycle state and keeps journaling aligned with real behavior.

## Proposed Changes By Module

### `src/synthetic_trader/execution/mt5.py`

Extend the MT5 adapter with reconciliation result types and supervised modify helpers for synchronized positions.

### `src/synthetic_trader/live/supervised_live.py`

Add sync-aware supervised MT5 modify handling that reuses the existing fail-closed lifecycle gates.

### `src/synthetic_trader/cli.py`

Add explicit MT5 reconciliation and supervised modify commands or extensions to the current lifecycle CLI surface.

### `src/synthetic_trader/journal/trade_journal.py`

Add journal helpers for reconciliation and modify results.

### `tests/`

Add focused MT5 refinement tests using fakes and stubbed broker responses rather than a real terminal.

## Data Flow Impact

The MT5 refinement path should become:

1. parse MT5 refinement command and config,
2. run runtime readiness checks,
3. synchronize broker-side positions,
4. build a reconciliation result from synchronized state,
5. decide whether the target position is actionable,
6. apply a supervised modify action only when that reconciliation result is explicit and safe,
7. return structured results and journal events.

This keeps refinement anchored in broker truth and prepares the codebase for later analytics work.

## Error Handling

1. Missing runtime readiness should block reconciliation-dependent mutation.
2. Missing synchronized positions should block modification.
3. Ambiguous synchronized positions should block modification.
4. Missing target ticket should block modification.
5. Broker-side modify rejection should return a structured rejected result and journal event.
6. Unsupported command or mode combinations should fail visibly.

## Success Criteria

Phase 8 is complete when:

1. MT5 lifecycle reconciliation produces structured actionable state,
2. supervised MT5 modify handling works only on reconciled and explicit targets,
3. journaling captures reconciliation and modify events clearly,
4. CLI refinement reporting is explicit and readable,
5. existing MT5 entry, sync, and close flows remain green.

## Follow-On Phase

Once Phase 8 is complete, the next likely phase is MT5 execution analytics expansion, including richer lifecycle summaries, reconciliation diagnostics, and venue-specific execution performance reporting.
