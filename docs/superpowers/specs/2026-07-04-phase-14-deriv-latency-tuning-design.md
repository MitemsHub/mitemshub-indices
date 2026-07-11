# Phase 14 Deriv Latency Tuning Design

## Summary

Phase 14 focuses on Deriv-specific latency tuning after the shared live path and MT5-specific path have both been stabilized. The goal is to reduce Deriv WebSocket and venue-adapter overhead that remains after the earlier phases, while preserving Deriv readiness behavior, supervised controls, and execution correctness.

This phase is Deriv-specific on purpose. It does not reopen shared-path tuning and does not revisit MT5-specific work unless a clear cross-venue regression is exposed.

## Context

The repository now has:

1. a stable shared live path with optional latency visibility,
2. MT5-specific latency tuning completed and regression-safe,
3. supervised live safety gates and fail-closed readiness controls,
4. venue-aware execution routing,
5. journal-backed and operator-facing observability surfaces.

The current gap is that Deriv-specific runtime and WebSocket-adapter overhead has not yet been tightened with the same venue-specific focus used for MT5.

Today:

1. the shared path is no longer the main suspected latency layer,
2. MT5-specific tuning has already been completed,
3. Deriv still has venue-specific transport and runtime behavior that may carry avoidable cost,
4. the project is ready for a final narrow venue-tuning pass before benchmark-style validation.

Because of that, Phase 14 should focus only on Deriv-specific hotspots that remain after the earlier phases have ruled down shared and MT5 overhead.

## Goals

1. Identify and reduce Deriv-specific latency hotspots.
2. Preserve Deriv readiness, execution correctness, and supervised behavior.
3. Keep transport and venue-adapter overhead as lean as possible without weakening safety.
4. Maintain clear separation between Deriv-specific work and the already-stable shared path.
5. Leave the project ready for a final validation and benchmarking phase.

## Non-Goals

1. No reopening of shared-path optimization.
2. No reopening of MT5-specific tuning except for cross-venue regression protection.
3. No weakening of Deriv readiness or supervised controls.
4. No observability removal.
5. No dashboard or reporting expansion in this phase.

## Design Principles

1. Tune only what is truly Deriv-specific.
2. Preserve correctness and safety before raw speed.
3. Avoid unnecessary WebSocket or adapter work where safe.
4. Keep the phase narrow and regression-friendly.
5. Leave behind a clean baseline for final validation.

## Scope

### 1. Deriv Transport Boundary Tuning

The phase should focus on Deriv work near the venue boundary, where remaining overhead is tied to transport or Deriv-specific orchestration rather than shared routing.

Likely candidates include:

1. repeated Deriv transport setup,
2. redundant request preparation around Deriv interactions,
3. avoidable synchronous work before reaching Deriv execution-relevant boundaries,
4. venue-specific orchestration around Deriv runtime checks.

### 2. Deriv Readiness And Execution Path Review

The phase should examine the Deriv live path for venue-specific delay around:

1. readiness-related checks,
2. Deriv client setup,
3. execution-boundary preparation,
4. any Deriv-specific summary or side-effect work that still occurs too early.

The goal is not to remove safeguards. The goal is to tighten the Deriv-specific path while preserving behavior.

### 3. Deriv Timing Preservation

Any Deriv-specific optimization should preserve the ability to reason about venue timing separately from the shared path.

Expected behavior:

1. Deriv timing remains inspectable,
2. optimized Deriv stages remain interpretable,
3. the project can compare pre- and post-tuning Deriv behavior,
4. later validation can use the cleaned Deriv baseline.

### 4. Minimal Venue Refactoring

If Deriv tuning requires small refactors, those changes should stay narrow and local to Deriv-specific seams.

This refactor must:

1. avoid touching unrelated MT5 flow,
2. preserve existing contracts unless a controlled improvement is clearly justified,
3. remain easy to regression test,
4. avoid mixing in non-latency feature work.

### 5. Preparation For Final Validation

Phase 14 should leave the project ready for a final validation/benchmarking phase.

That means:

1. Deriv changes should be isolated,
2. the shared and MT5 baselines should remain stable,
3. venue-specific learnings should now exist for both venues,
4. the next phase can focus on proving the end-to-end gains rather than finding new hotspots.

## Proposed Changes By Module

### `src/synthetic_trader/execution/deriv.py`

Likely primary seam for Deriv-specific tuning because it owns venue-specific transport and execution interactions.

Potential responsibilities:

1. reduce repeated Deriv setup work,
2. tighten Deriv execution-boundary preparation,
3. preserve typed or normalized runtime behavior.

### `src/synthetic_trader/live/paper_runner.py`

May need small Deriv-specific adjustments only where the Deriv live path still performs avoidable venue work before the execution boundary.

This should remain narrow and should not disturb the shared baseline.

### `src/synthetic_trader/cli.py`

May need small changes only if Deriv-specific latency surfacing becomes more explicit during this phase.

This must remain opt-in and should not pollute normal operator output.

### `tests/`

Add focused tests for:

1. preserved Deriv runtime behavior after tuning,
2. reduced repeated Deriv-specific venue work where justified,
3. unchanged supervised and readiness semantics,
4. regression safety for Deriv-facing live flows.

## Data Flow

The Phase 14 Deriv tuning flow should be:

1. enter the already-stable shared path,
2. reach the Deriv boundary,
3. reduce repeated or unnecessary Deriv-specific overhead where safe,
4. preserve readiness and execution correctness,
5. exit with Deriv behavior unchanged except for venue-specific latency improvements.

This keeps Deriv tuning narrow and completes the venue-specific hardening sequence.

## Error Handling

1. Deriv tuning must never bypass readiness or supervised controls.
2. Deriv tuning must never weaken execution correctness.
3. Any reduced or cached Deriv-specific work must remain correct under live operator usage.
4. Optional latency reporting must remain optional.
5. The system must remain fail-closed even if Deriv timing capture is unavailable.

## Testing Strategy

The phase should prove:

1. Deriv-specific flows still behave identically from a correctness perspective,
2. repeated Deriv venue work is reduced only where justified,
3. supervised/live Deriv behavior remains safe,
4. focused Deriv regression suites remain green,
5. the full suite remains green.

## Success Criteria

Phase 14 is complete when:

1. the main remaining Deriv-specific hotspots have been tightened,
2. Deriv readiness and execution behavior remain correct,
3. timing visibility still works for Deriv-specific analysis,
4. all safety semantics remain unchanged,
5. focused tests and full regression remain green.

## Follow-On Phase

Once Phase 14 is complete, the next phase should be final validation and benchmarking so the shared, MT5, and Deriv improvements can be measured together and preserved as the project approaches a production-ready supervised state.
