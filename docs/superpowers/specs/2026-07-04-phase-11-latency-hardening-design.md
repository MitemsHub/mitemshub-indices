# Phase 11 Latency Hardening Design

## Summary

Phase 11 focuses on live-path latency hardening for the shared supervised execution flow used by both Deriv and MT5. The goal is to measure the real hot-path cost, identify the dominant sources of latency, and make targeted optimizations without weakening fail-closed readiness, supervised controls, or broker-state correctness.

This phase is about measurement-first runtime hardening. It is not a strategy rewrite and not a broad refactor for its own sake.

## Context

The repository now has:

1. a shared venue-aware live path covering Deriv and MT5,
2. supervised live readiness gates and armed-live controls,
3. MT5 readiness, sync, reconcile, close, and modify command flows,
4. journal-backed analytics for MT5 command behavior,
5. a read-only MT5 monitor surface for operator review.

The current gap is that the system is now better instrumented functionally, but the live execution path has not yet been explicitly hardened for latency.

Today:

1. safety and observability are prioritized correctly,
2. execution and operator side effects still coexist in nearby runtime flows,
3. there is no formal latency profile for the shared live path,
4. optimization opportunities are not yet grounded in timing evidence.

Because of that, the project can execute safely, but it does not yet explain where execution time is being spent or which overheads matter most in actual live operation.

## Goals

1. Measure the shared live execution path rather than guessing at bottlenecks.
2. Add a compact latency profile surface for the main live-path boundaries.
3. Distinguish execution-critical work from operator-only and observability work.
4. Make targeted optimizations only where timing evidence justifies them.
5. Preserve all supervised and fail-closed safeguards while improving responsiveness.

## Non-Goals

1. No weakening of live safety gates, confirmations, or readiness checks.
2. No strategy, signal, or model logic changes for performance reasons alone.
3. No broker-specific optimization pass unless shared-path timing indicates it is needed.
4. No dashboard or visualization layer in this phase.
5. No speculative micro-optimization without measured evidence.

## Design Principles

1. Measure first, optimize second.
2. Preserve correctness over raw speed.
3. Separate hot-path execution from operator-facing side effects.
4. Keep instrumentation lightweight and explicit.
5. Optimize the shared path before venue-specific branches.

## Scope

### 1. Shared Live Path Instrumentation

The project should gain explicit timing instrumentation around the shared live and supervised execution path.

This instrumentation should cover the major runtime boundaries that are likely to influence perceived trading speed:

1. readiness evaluation,
2. supervised routing and orchestration,
3. venue execution boundary,
4. journaling side effects,
5. summary or print side effects where they occur on the same runtime path.

The goal is not high-frequency profiling of every function call. The goal is to measure the meaningful stage boundaries that help explain end-to-end live-path latency.

### 2. Latency Summary Shape

The system should produce a compact, structured latency summary that is easy to inspect in tests and CLI output.

The summary should include at least:

1. stage name,
2. elapsed duration in milliseconds,
3. whether the stage belongs to execution-critical or operator-side-effect work,
4. total measured duration for the profiled path,
5. per-run timing data that can be asserted in tests without being overly brittle.

The summary does not need to be a permanent artifact in this phase. A lightweight dict or typed dataclass is sufficient as long as it is reusable and JSON-friendly.

### 3. Execution-Critical Versus Side-Effect Classification

The phase should explicitly classify work on the live path into two categories:

1. execution-critical work that must remain inline,
2. operator, monitoring, journaling, and summary side effects that can be evaluated for relocation or reduction.

This classification is important because not all latency is equally harmful. A broker call or decision boundary matters differently from a post-action summary print or journal append.

### 4. Targeted Optimization Rules

Optimization should be limited to changes supported by the measured latency profile.

Valid optimization examples:

1. reducing repeated work on the shared live path,
2. avoiding unnecessary synchronous side effects before broker interaction,
3. consolidating redundant summary work,
4. making lightweight orchestration improvements in the shared path.

Invalid optimization examples:

1. skipping readiness checks,
2. weakening supervised controls,
3. suppressing correctness-critical broker synchronization,
4. removing analytics entirely rather than moving or minimizing their overhead.

### 5. Shared-Path First Sequencing

The phase should optimize the shared live path first.

Only after the timing evidence is available should the implementation conclude whether:

1. the shared path is the main source of latency,
2. venue-specific latency work is needed later,
3. MT5 or Deriv-specific follow-up should become the next phase.

This prevents duplicating optimization work separately for both venues when the real bottleneck may sit in shared orchestration.

## Proposed Changes By Module

### `src/synthetic_trader/live/supervised_live.py`

Likely primary seam for shared live-path instrumentation because it already owns supervised routing and readiness-centered execution control.

Potential responsibilities in this phase:

1. mark major shared live stages,
2. emit or return a structured latency summary,
3. keep latency measurement separate from safety behavior.

### `src/synthetic_trader/live/paper_runner.py`

Likely measurement seam for live paper execution because it represents a real runtime path shared across venue-aware operation.

Potential responsibilities in this phase:

1. expose timing boundaries around core live runtime steps,
2. help distinguish execution work from side-effect work,
3. remain functionally unchanged aside from measurement and justified optimizations.

### `src/synthetic_trader/cli.py`

May need small changes to surface the latency summary when explicitly requested or when used in a profiling-oriented command path.

This should remain minimal and must not add heavy output by default if that output would pollute or slow normal execution unnecessarily.

### `tests/`

Add focused tests for:

1. latency summary structure,
2. stage timing capture behavior,
3. classification of execution-critical versus side-effect work,
4. regression safety for existing supervised live flows.

## Data Flow

The Phase 11 latency-hardening flow should be:

1. enter the existing shared live or supervised path,
2. record timing checkpoints around major stage boundaries,
3. classify measured stages by runtime role,
4. compute a compact latency summary,
5. use the summary to guide only justified optimizations,
6. preserve existing behavior and exit semantics.

This keeps performance work grounded in real runtime evidence rather than assumptions.

## Error Handling

1. If latency measurement fails, live safety behavior must remain unchanged.
2. Instrumentation must never bypass readiness gates or supervised controls.
3. Optimization must never weaken broker-state correctness.
4. Any timing output should be optional or lightweight enough not to become a new bottleneck.
5. The system should fail closed on trading safety even if latency reporting is unavailable.

## Testing Strategy

The phase should prove:

1. the shared live path can emit a structured latency summary,
2. the measured stages match the intended live-path boundaries,
3. optimizations preserve existing supervised behavior,
4. timing-focused tests are robust without depending on fragile absolute thresholds,
5. full regression remains green.

## Success Criteria

Phase 11 is complete when:

1. the shared live path has explicit timing instrumentation,
2. the project can identify where major live-path latency is spent,
3. at least the most obvious shared-path inefficiencies are reduced where justified,
4. all safety and supervised semantics remain unchanged,
5. focused tests and full regression remain green.

## Follow-On Phase

Once Phase 11 is complete, the next likely phase is venue-specific latency tuning only if the measured results show Deriv or MT5 still have meaningful broker- or adapter-level hotspots after the shared path has been hardened.
