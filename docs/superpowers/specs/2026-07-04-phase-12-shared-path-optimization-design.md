# Phase 12 Shared-Path Optimization Design

## Summary

Phase 12 focuses on reducing avoidable latency on the shared live execution path before broker interaction. The goal is to use the Phase 11 measurement surface to remove or relocate the highest-value shared-path overheads without weakening fail-closed readiness, supervised execution controls, or broker-state correctness.

This phase is a targeted optimization pass. It is not a broad architecture rewrite and not a venue-specific tuning phase.

## Context

The repository now has:

1. a venue-aware shared live path for Deriv and MT5,
2. supervised live safety gates and fail-closed readiness behavior,
3. a latency summary surface for the supervised live path,
4. stage classification that distinguishes execution-critical work from side effects,
5. on-demand latency reporting for inspection.

The current gap is that the shared path can now be measured, but it has not yet been optimized using that measurement surface.

Today:

1. shared-path timing can be captured,
2. the project can distinguish critical-path work from side-effect work,
3. pre-broker overhead is still not explicitly reduced,
4. venue-specific latency work has not yet been justified by shared-path results.

Because of that, the project is ready for precision optimization, but the first measured reductions on the shared path are still pending.

## Goals

1. Reduce avoidable overhead before the execution boundary on the shared live path.
2. Keep execution-critical work inline and lean.
3. Relocate, defer, or minimize non-critical side effects where justified.
4. Preserve all supervised live and readiness semantics.
5. Keep the resulting design small enough to hand off cleanly into venue-specific tuning only if still needed.

## Non-Goals

1. No venue-specific optimization as the primary focus of this phase.
2. No weakening of safety gates, readiness checks, or supervised controls.
3. No strategy or signal-engine changes.
4. No observability removal; only relocation or minimization where justified.
5. No benchmark dashboard or visualization layer.

## Design Principles

1. Optimize shared-path overhead before optimizing venue-specific branches.
2. Reduce only measured or clearly redundant work.
3. Preserve correctness and safety over raw speed.
4. Keep optimizations explicit and reviewable.
5. Avoid changes that make the live path harder to reason about.

## Scope

### 1. Shared Pre-Broker Optimization

The phase should target the portion of the shared live path that occurs before the project reaches the venue execution boundary.

Likely candidates include:

1. repeated setup or recalculation in the shared path,
2. redundant routing work,
3. summary or side-effect work occurring earlier than necessary,
4. non-critical synchronous work that can be deferred until after the main execution decision is complete.

The phase should not remove safeguards. It should only reduce avoidable overhead.

### 2. Critical Versus Side-Effect Separation

The project should tighten the separation between:

1. execution-critical work that directly affects reaching the broker boundary,
2. operator-facing or observability work that can safely happen later or in a reduced form.

This separation should be guided by the existing latency stage classification rather than by intuition alone.

### 3. Minimal Runtime Refactoring

If the current shared path mixes critical and non-critical work too tightly, the phase may include a small refactor to separate them.

This refactor must stay narrow:

1. keep function responsibilities clear,
2. avoid large file churn,
3. preserve existing call contracts unless a controlled improvement is clearly justified,
4. remain easy to regression test.

### 4. Latency Summary Preservation

The Phase 11 latency summary should remain usable after the optimizations land.

Expected behavior:

1. timing capture still works,
2. stage names remain meaningful,
3. the before-versus-after structure remains inspectable,
4. the optimized path does not become harder to measure.

### 5. Sequencing Into Later Phases

This phase should explicitly prepare for:

1. Phase 13 venue-specific tuning only if the shared path still leaves meaningful hotspots,
2. Phase 14 execution validation and benchmarking so the measured improvements can be proven and preserved.

That means Phase 12 should leave behind a cleaner shared-path baseline rather than solving venue-specific timing prematurely.

## Proposed Changes By Module

### `src/synthetic_trader/live/supervised_live.py`

Likely primary seam for shared pre-broker optimization because it owns the supervised routing layer and the current latency stage recording.

Potential responsibilities:

1. tighten the routing path,
2. reduce redundant work before execution,
3. keep timing stages meaningful and stable.

### `src/synthetic_trader/live/paper_runner.py`

Likely seam for reducing avoidable synchronous side effects or repeated shared runtime work.

Potential responsibilities:

1. defer or minimize non-critical side effects where safe,
2. clarify stage boundaries,
3. preserve live-paper correctness and accounting.

### `src/synthetic_trader/cli.py`

May require only small adjustments if the optimized path changes how latency summaries are surfaced or ordered.

This should stay minimal and remain opt-in.

### `tests/`

Add focused tests for:

1. preserved behavior of the optimized shared path,
2. stage ordering and latency capture integrity,
3. optional latency behavior remaining backward compatible,
4. regression safety for supervised live and paper-live flows.

## Data Flow

The Phase 12 shared-path optimization flow should be:

1. enter the shared supervised/live path,
2. reach readiness and routing boundaries with less avoidable overhead,
3. keep critical-path work inline,
4. shift or minimize non-critical side effects where justified,
5. retain timing visibility across the optimized path,
6. preserve existing functional behavior.

This keeps the optimization grounded in the measured structure created in Phase 11.

## Error Handling

1. Optimizations must never bypass readiness or supervised controls.
2. Any deferred or minimized side-effect work must still preserve correctness-critical accounting.
3. If a latency-oriented optimization makes control flow less safe or less clear, it should be rejected.
4. Optional latency capture must remain optional and backward compatible.
5. The system must remain fail-closed regardless of optimization state.

## Testing Strategy

The phase should prove:

1. the shared path still behaves identically from a correctness perspective,
2. latency capture remains available after optimization,
3. optimized code preserves the existing default contracts,
4. focused live and supervised regressions remain green,
5. the full suite remains green.

## Success Criteria

Phase 12 is complete when:

1. the shared path reaches the execution boundary with less avoidable overhead,
2. non-critical work is reduced or relocated where justified,
3. timing capture still works and remains interpretable,
4. all supervised and readiness semantics remain unchanged,
5. focused tests and full regression remain green.

## Follow-On Phase

Once Phase 12 is complete, the next phase should be venue-specific latency tuning only if the remaining measured hotspots are clearly tied to Deriv- or MT5-specific behavior rather than the shared path.
