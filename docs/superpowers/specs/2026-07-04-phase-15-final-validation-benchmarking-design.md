# Phase 15 Final Validation And Benchmarking Design

## Summary

Phase 15 focuses on final validation and benchmarking for the supervised trading system after the shared path, MT5 path, and Deriv path have all been stabilized and tuned. The goal is to prove the current system state with one validation flow that emits both a human-readable CLI summary and a machine-readable JSON artifact from the same run.

This phase is about proof, packaging, and repeatable validation. It is not a new trading-feature phase.

## Context

The repository now has:

1. supervised live safety gates and fail-closed readiness behavior,
2. MT5 execution, lifecycle, analytics, and monitor surfaces,
3. Deriv venue execution support,
4. shared-path latency visibility,
5. MT5-specific and Deriv-specific latency tuning completed,
6. JSON-safe serialization support for structured artifacts.

The current gap is that the project does not yet have one final validation layer that summarizes the current supervised trading system as a whole and emits a reusable benchmark artifact from the same source data.

Today:

1. individual runtime and venue seams are covered,
2. regression safety is strong,
3. latency visibility exists,
4. operator summaries and machine-readable artifacts are still fragmented across commands and modules.

Because of that, the project is ready for a final proof phase that turns the current system state into a clear validation output for both humans and tooling.

## Goals

1. Add one validation/benchmark flow that emits both CLI and JSON outputs.
2. Reuse the current truth sources rather than inventing a parallel reporting path.
3. Summarize shared, MT5, and Deriv validation points in one place.
4. Keep the validation path read-only and safe.
5. Make the final validation output repeatable and regression-testable.

## Non-Goals

1. No new live trading behavior.
2. No strategy or model changes.
3. No dashboard or web UI.
4. No replacement of existing journal or monitor surfaces.
5. No weakening of supervised or readiness semantics.

## Design Principles

1. One run, two outputs.
2. Reuse existing summaries and timing surfaces.
3. Keep validation read-only.
4. Keep the output compact, explicit, and comparable.
5. Prefer a single normalized validation payload that can feed both CLI and artifact rendering.

## Scope

### 1. Unified Validation Payload

The phase should build one normalized validation payload that captures the current supervised trading system state at the level needed for final proof and comparison.

The payload should include at least:

1. venue or mode context,
2. summary fields from live-paper execution,
3. latency summary fields when requested,
4. readiness or validation-related status fields,
5. benchmark-friendly scalar values that are easy to compare across runs.

The payload should be JSON-safe and suitable for both rendering and file output.

### 2. CLI Validation Summary

The CLI should gain a concise validation summary that presents the most important validation fields in a human-readable terminal form.

The summary should:

1. remain compact,
2. focus on operator-relevant pass/fail style signals,
3. include venue-aware highlights,
4. avoid excessive noise.

### 3. JSON Validation Artifact

The same validation flow should optionally write a JSON artifact using the normalized validation payload.

The artifact should:

1. be deterministic and JSON-safe,
2. preserve the same information used by the CLI summary,
3. be usable for future audits, comparisons, or automation.

### 4. Shared And Venue Coverage

The validation flow should cover the current system at three levels:

1. shared-path validation,
2. MT5-specific validation signals,
3. Deriv-specific validation signals.

This does not require a live venue connection during tests. It requires that the validation payload shape can represent the current system state across those concerns.

### 5. Benchmark Repeatability

The phase should make the final validation flow repeatable enough to support comparison across future changes.

That means:

1. stable output fields,
2. stable artifact structure,
3. focused tests around payload shape and rendering,
4. clear CLI contract.

## Proposed Changes By Module

### `src/synthetic_trader/monitoring/surface.py`

Likely seam for building a normalized validation snapshot and rendering a compact validation summary.

Potential responsibilities:

1. build validation payloads from live summaries and optional latency data,
2. render validation text output,
3. preserve existing monitor helpers.

### `src/synthetic_trader/reporting/serializers.py`

Likely seam for writing the JSON validation artifact because it already provides JSON-safe serialization helpers.

Potential responsibilities:

1. serialize the normalized validation payload,
2. dump the artifact to disk,
3. preserve deterministic output formatting.

### `src/synthetic_trader/cli.py`

Likely seam for exposing the final validation flow to operators.

Potential responsibilities:

1. accept artifact-output options,
2. run the validation flow,
3. print the validation summary,
4. write the optional JSON artifact from the same payload.

### `tests/`

Add focused tests for:

1. validation payload structure,
2. CLI rendering behavior,
3. artifact writing,
4. shared and venue-aware field coverage,
5. regression safety for the final validation command path.

## Data Flow

The Phase 15 validation and benchmarking flow should be:

1. run or receive the existing supervised/live summary inputs,
2. combine them into one normalized validation payload,
3. render the CLI validation summary,
4. optionally write the JSON artifact from that same payload,
5. return without changing trading behavior.

This keeps the final proof layer grounded in the current system rather than inventing a separate reporting stack.

## Error Handling

1. Validation must remain read-only.
2. Artifact writing failures must be reported clearly.
3. Validation output must not weaken supervised safety behavior.
4. Optional latency information should remain optional and not break validation when absent.
5. The system should fail clearly on invalid output paths or malformed payload assembly.

## Testing Strategy

The phase should prove:

1. the normalized validation payload has the expected shape,
2. the CLI summary reflects the payload correctly,
3. the JSON artifact matches the same payload content,
4. venue-aware validation fields are preserved,
5. focused tests and the full suite remain green.

## Success Criteria

Phase 15 is complete when:

1. one validation flow can emit both CLI and JSON outputs,
2. the outputs are driven by the same normalized payload,
3. shared, MT5, and Deriv validation points are represented,
4. the validation path remains read-only and regression-safe,
5. focused tests and full regression remain green.

## Follow-On Phase

Once Phase 15 is complete, the project should be in a much stronger position for a production-readiness decision, supervised live rollout planning, or future reporting enhancements without needing more core venue plumbing first.
