# Phase 4 Supervised Live Deriv Design

## Summary

Phase 4 adds supervised live scaffolding and pre-live readiness around the existing Deriv execution path. The goal is to make live execution possible only through explicit, guarded, fail-closed workflows rather than through accidental or implicit code paths.

This phase focuses on Deriv first. It does not yet add MT5, TradingView, or other venue integrations.

## Context

The repository now has a stronger research core, a more reliable paper-live path, execution realism controls, richer artifacts, and a lightweight monitoring surface. The next step is not to jump straight into unattended live trading. The next step is to create a supervised live framework that:

1. clearly separates paper, dry-run live, and armed live behavior,
2. validates readiness before any live path can proceed,
3. requires explicit operator intent before placing live orders,
4. fails closed when anything important is missing or unsafe.

## Goals

1. Add explicit supervised live execution modes.
2. Add pre-flight readiness checks for live Deriv operation.
3. Add explicit arming and confirmation controls for the live path.
4. Prevent accidental live order placement.
5. Add tests that prove the live path is blocked unless all gates pass.

## Non-Goals

1. No unattended autonomous live trading.
2. No MT5 or TradingView integration in this phase.
3. No broad multi-broker abstraction layer in this phase.
4. No production deployment platform work in this phase.

## Design Principles

1. Fail closed by default.
2. Make live intent explicit, never implicit.
3. Keep the live transport and live execution layers separable.
4. Preserve the current paper path as the safe default.
5. Make every gate and readiness outcome observable in testable outputs.

## Scope

### 1. Explicit Execution Modes

The runtime should expose distinct execution modes such as:

1. `paper`
2. `dry-run-live`
3. `armed-live`

These modes should not be encoded as loose flag combinations spread across the codebase. They should be represented clearly enough that the allowed and blocked behaviors are obvious.

### 2. Pre-Live Readiness Validation

Before any live execution path is allowed, the system should validate readiness conditions such as:

1. Deriv app id availability,
2. API token presence when the live path requires authorization,
3. symbol support,
4. safety mode compatibility,
5. runtime configuration sanity.

The output should explain why readiness passed or failed.

### 3. Dry-Run Live Mode

Dry-run live mode should connect to the live data path and run the decision process, but it should never send buy or sell requests. It should produce observable outputs showing what the system would have done.

This mode is important because it lets us validate live-decision behavior and readiness without risking account actions.

### 4. Armed Live Mode

Armed live mode should remain supervised and heavily gated.

Requirements:

1. It should require explicit CLI arming intent.
2. It should require readiness validation to pass first.
3. It should refuse to place live requests if any gate is missing.
4. It should remain operator-mediated rather than fully autonomous in this phase.

### 5. Operator Confirmation And Guardrails

The CLI and runtime should make live intent explicit enough that accidental live entry is unlikely.

Examples of the desired behavior:

1. safe defaults remain paper or dry-run,
2. live mode without explicit arming fails,
3. armed mode without credentials fails,
4. ambiguous or conflicting flags fail,
5. readiness results are printed clearly before live execution begins.

### 6. Test Coverage

Phase 4 should add focused tests around:

1. readiness failure cases,
2. dry-run live refusing to place live orders,
3. armed live refusing to run without confirmation,
4. armed live calling the live execution adapter only when all gates pass.

## Proposed Changes By Module

### `src/synthetic_trader/cli.py`

Add explicit execution mode parsing and clear live-specific gating flags.

### `src/synthetic_trader/execution/deriv_ws.py`

Keep the current transport client, but use it behind the supervised gating path rather than exposing live placement accidentally.

### `src/synthetic_trader/live/`

Add a supervised live runner or equivalent gate layer that controls whether the Deriv client is used only for observation or also for authorized order placement.

### `src/synthetic_trader/config.py`

Add any minimal configuration structure needed to represent explicit live execution modes safely.

### `tests/`

Add focused coverage for readiness, arming, blocked execution, and allowed execution paths.

## Data Flow Impact

The supervised live path should become:

1. parse explicit execution mode,
2. run readiness checks,
3. print readiness result,
4. enter live observation only if dry-run or armed-live is allowed,
5. send live requests only when armed-live gates are satisfied.

This keeps the paper, dry-run, and armed-live flows distinct.

## Error Handling

1. Missing credentials should fail during readiness, not during accidental runtime placement.
2. Unsafe mode combinations should fail before connecting to the live path.
3. Any failed live gate should stop order placement cleanly and visibly.

## Testing Strategy

1. Start with unit-like gating tests rather than broad end-to-end live network tests.
2. Use small deterministic fakes for Deriv execution calls.
3. Verify blocked paths first, then verify the minimum allowed armed path.

## Success Criteria

Phase 4 is complete when:

1. execution modes are explicit,
2. readiness validation exists and is observable,
3. dry-run live never places live orders,
4. armed-live cannot place live orders unless all gates pass,
5. the automated suite covers the new guarded live behavior and remains green.

## Follow-On Phase

Once Phase 4 is complete, the next likely phase is venue expansion and integration strategy, including MT5, TradingView, or other broker and signal surfaces, built on top of a safer supervised live model.
