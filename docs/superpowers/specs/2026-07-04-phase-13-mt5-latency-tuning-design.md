# Phase 13 MT5 Latency Tuning Design

## Summary

Phase 13 focuses on MT5-specific latency tuning after the shared live path has been measured and stabilized. The goal is to reduce MT5 terminal and venue-adapter overhead that remains after Phase 11 and Phase 12, while preserving MT5 readiness safety, supervised live controls, reconcile correctness, and broker-backed lifecycle semantics.

This phase is MT5-specific on purpose. It does not attempt to optimize Deriv in parallel, and it does not replace the shared-path work already completed.

## Context

The repository now has:

1. a shared venue-aware live path,
2. MT5-specific readiness, sync, reconcile, close, and modify flows,
3. supervised MT5 safety gates,
4. journal-backed MT5 analytics and operator monitoring,
5. a shared-path latency surface and shared-path optimization baseline.

The current gap is that venue-specific MT5 overhead has not yet been tuned after the shared path was validated and stabilized.

Today:

1. the project can distinguish shared-path overhead from venue-specific work,
2. the shared path is stable enough not to be the first latency suspect,
3. MT5 still has terminal-backed and broker-synchronization seams that may carry venue-specific cost,
4. Deriv-specific tuning is explicitly sequenced after this MT5 phase.

Because of that, Phase 13 should focus only on MT5 timing hotspots that remain after shared-path overhead has been ruled down.

## Goals

1. Identify and reduce MT5-specific latency hotspots.
2. Preserve MT5 runtime readiness and supervised execution semantics.
3. Keep broker-state synchronization correct while trimming avoidable MT5 overhead.
4. Separate terminal or adapter cost from shared orchestration cost as clearly as possible.
5. Leave behind a clean handoff into Phase 14 Deriv-specific tuning.

## Non-Goals

1. No shared-path optimization rewrite; that belongs to prior completed phases.
2. No Deriv optimization in this phase.
3. No weakening of reconcile, sync, or supervised-close/modify correctness.
4. No removal of MT5 analytics or journaling.
5. No benchmark dashboard or multi-venue reporting layer.

## Design Principles

1. Optimize MT5 only where the remaining cost is venue-specific.
2. Keep safety and broker-state correctness ahead of raw speed.
3. Avoid repeated MT5 terminal work where safe.
4. Preserve the ability to inspect MT5 timing after the optimization.
5. Keep the phase narrow enough that Deriv can follow immediately.

## Scope

### 1. MT5 Runtime Boundary Tuning

The phase should focus on MT5 work near the venue boundary, where shared-path optimization no longer explains the remaining overhead.

Likely candidates include:

1. repeated MT5 runtime checks,
2. redundant MT5 symbol or terminal setup,
3. unnecessary repeated MT5 module interactions before broker-relevant actions,
4. extra venue-specific orchestration around MT5 actions that can be tightened without changing semantics.

### 2. MT5 Lifecycle Path Review

The phase should examine the MT5 command and lifecycle path for avoidable venue-specific delay across:

1. runtime readiness,
2. sync,
3. reconcile,
4. close,
5. modify.

The goal is not to remove lifecycle safeguards. The goal is to reduce repeated or unnecessary venue-specific work around them.

### 3. MT5 Timing Preservation

Any MT5-specific optimization should preserve the ability to inspect venue timing separately from the shared path.

Expected behavior:

1. timing visibility remains available,
2. optimized MT5 stages are still interpretable,
3. the project can compare MT5 timing before and after the venue-specific changes,
4. the resulting code still leaves room for later benchmark validation.

### 4. Minimal Venue Refactoring

If MT5 timing improvements require small refactors, those changes should stay narrow and local to MT5-specific seams.

This refactor must:

1. avoid touching unrelated Deriv flow,
2. preserve call contracts unless a controlled improvement is clearly justified,
3. remain easy to regression test,
4. avoid mixing MT5 tuning with new feature work.

### 5. Immediate Sequencing Into Deriv

Phase 13 should leave the project ready for immediate Deriv-specific tuning.

That means:

1. MT5 changes should be isolated,
2. shared-path assumptions should remain stable,
3. venue-specific learnings should be reusable but not over-generalized,
4. the next phase can focus on Deriv without reopening MT5 design questions.

## Proposed Changes By Module

### `src/synthetic_trader/execution/mt5.py`

Likely primary seam for venue-specific MT5 tuning because it owns runtime readiness, synchronize, reconcile, close, and modify behavior.

Potential responsibilities:

1. reduce repeated MT5-specific setup work,
2. tighten MT5 runtime-boundary overhead,
3. preserve typed result contracts and broker-state correctness.

### `src/synthetic_trader/live/supervised_live.py`

May need small MT5-specific adjustments only where supervised MT5 flow still introduces avoidable venue-specific overhead.

This should stay narrow and must preserve the shared-path baseline established earlier.

### `src/synthetic_trader/cli.py`

May need small changes if MT5-specific latency surfacing becomes more explicit during this phase.

This must remain opt-in and should not pollute the normal operator path.

### `tests/`

Add focused tests for:

1. preserved MT5 runtime behavior after tuning,
2. reduced repeated MT5 venue-specific work where justified,
3. unchanged supervised MT5 safety semantics,
4. regression safety for sync, reconcile, close, and modify flows.

## Data Flow

The Phase 13 MT5 tuning flow should be:

1. enter the already-stable shared path,
2. reach the MT5 boundary,
3. reduce repeated MT5-specific overhead before and around terminal interactions where safe,
4. preserve lifecycle correctness and timing visibility,
5. exit with MT5 behavior unchanged except for the venue-specific latency improvements.

This keeps MT5 tuning tightly scoped and distinct from the earlier shared-path work.

## Error Handling

1. MT5 tuning must never bypass readiness or supervised controls.
2. MT5 tuning must never weaken reconcile or sync correctness.
3. Any reduced or cached MT5 work must stay correct under live operator usage.
4. Optional latency reporting must remain optional.
5. The system must remain fail-closed even if MT5 timing capture is unavailable.

## Testing Strategy

The phase should prove:

1. MT5-specific flows still behave identically from a correctness perspective,
2. repeated MT5 venue work is reduced only where justified,
3. supervised MT5 commands remain safe,
4. focused MT5 regression suites remain green,
5. the full suite remains green.

## Success Criteria

Phase 13 is complete when:

1. the main remaining MT5 venue-specific hotspots have been tightened,
2. MT5 runtime, sync, reconcile, close, and modify behavior remain correct,
3. timing visibility still works for MT5-specific analysis,
4. all safety semantics remain unchanged,
5. focused tests and full regression remain green.

## Follow-On Phase

Once Phase 13 is complete, the next phase should immediately tune Deriv-specific latency with the same narrow approach, using the shared-path and MT5 baselines as reference points rather than reopening them.
