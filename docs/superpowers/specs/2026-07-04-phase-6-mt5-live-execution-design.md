# Phase 6 MT5 Live Execution Design

## Summary

Phase 6 adds controlled MT5 live execution wiring on top of the MT5 scaffolding introduced in Phase 5. The goal is to make MT5 capable of terminal-backed connectivity checks and supervised tiny-stake order placement while preserving the current fail-closed safety model and keeping unattended automation out of scope.

This phase does not introduce full autonomous MT5 trading. It introduces the minimum viable live execution layer needed to connect to MT5 safely, validate readiness with real terminal state, and place supervised orders only when explicit operator intent and runtime checks are satisfied.

## Context

The repository now has:

1. a stable research and backtest path,
2. a realistic paper execution layer,
3. explicit supervised-live gating,
4. venue-aware MT5 scaffolding with config, symbol mapping, and CLI routing.

What is still missing is the actual MT5 live execution boundary. The current MT5 module can describe credentials and detect whether the MT5 dependency is installed, but it cannot yet:

1. connect to a running MT5 terminal,
2. verify login and symbol availability against terminal state,
3. place a supervised tiny-stake order,
4. capture MT5 ticket and result details in a structured way.

That gap is the correct next step. It gives the project a real MT5 live seam without bypassing the safety principles already established in the Deriv path.

## Goals

1. Add terminal-backed MT5 connectivity checks.
2. Add MT5 runtime readiness validation based on real terminal state.
3. Add supervised tiny-stake MT5 order placement scaffolding.
4. Capture MT5 order results in a structured, testable format.
5. Keep the MT5 live path fail-closed and operator-gated.
6. Add test coverage using fakes so the automated suite does not depend on a live MT5 terminal.

## Non-Goals

1. No unattended autonomous MT5 trading.
2. No broad MT5 position-management engine in this phase.
3. No close/modify/cancel lifecycle automation beyond what is needed for safe scaffolding.
4. No change to strategy logic, alpha generation, or research flow.
5. No weakening of existing Deriv and paper-mode behavior.

## Design Principles

1. Fail closed on every MT5 live path.
2. Treat terminal state as a readiness dependency, not an optional convenience.
3. Keep order placement behind supervised-live gates.
4. Capture broker responses explicitly rather than hiding them in ad hoc dictionaries.
5. Preserve venue-neutral decision and risk layers.

## Scope

### 1. MT5 Terminal Connectivity

The MT5 adapter should move from passive config storage to active connectivity support.

This should include:

1. lazy import of the MT5 Python package,
2. initialize or attach to the MT5 terminal,
3. login verification using configured credentials,
4. terminal shutdown or cleanup handling where appropriate,
5. terminal-backed symbol lookup.

This layer should remain thin and testable. It should not absorb trading logic.

### 2. MT5 Runtime Readiness

The current readiness checks already validate missing config and symbol aliasing at a static level. Phase 6 should extend that into runtime-backed readiness.

Examples:

1. MT5 dependency is importable,
2. terminal initializes successfully,
3. login succeeds,
4. the mapped MT5 symbol exists and is selectable,
5. account or terminal state is compatible with supervised order placement.

Readiness output should clearly explain the first-order failures so operators can fix them before attempting any supervised live action.

### 3. Structured MT5 Order Requests

The project needs a typed internal representation for a supervised MT5 order request and MT5 execution result.

That structure should capture:

1. normalized project symbol,
2. resolved MT5 symbol,
3. direction and stake or volume,
4. stop and target where supported,
5. MT5 ticket or order identifiers,
6. broker response code and message,
7. whether the order was accepted, rejected, or only simulated.

This gives the project a clean handoff between the supervised execution layer and later analytics or journaling work.

### 4. Supervised MT5 Order Placement

The MT5 live path should support supervised tiny-stake order placement only.

Requirements:

1. it must only be reachable in explicitly armed supervised mode,
2. it must refuse when runtime readiness fails,
3. it must resolve project symbols through the MT5 symbol map,
4. it must return a structured result,
5. it must remain easy to stub in tests.

This is intentionally narrower than a full MT5 execution engine. The objective is a safe, testable first live step.

### 5. CLI Surface

The CLI should expose enough MT5 runtime information to make supervised operation understandable and auditable.

Expected behavior:

1. print venue and mode,
2. print readiness status,
3. print MT5 runtime failures clearly,
4. print order-placement outcome in a structured way when a supervised MT5 order path is exercised,
5. preserve current behavior for paper and Deriv flows.

### 6. Testing Strategy

Phase 6 should add focused tests around:

1. MT5 terminal init success and failure using fakes,
2. runtime readiness pass and failure cases,
3. symbol resolution against MT5 terminal metadata,
4. supervised MT5 order placement allowed-path behavior,
5. fail-closed refusal when readiness or arming is missing,
6. CLI reporting of MT5 runtime readiness and order result summaries.

## Proposed Changes By Module

### `src/synthetic_trader/execution/mt5.py`

Extend the MT5 adapter with terminal-backed connectivity helpers, runtime symbol resolution, and supervised order-placement functions.

### `src/synthetic_trader/live/supervised_live.py`

Extend the supervised execution layer so it can route an MT5-specific order request through runtime readiness and controlled order placement.

### `src/synthetic_trader/cli.py`

Add MT5 runtime readiness reporting and a supervised MT5 order execution entry path that remains explicitly gated.

### `src/synthetic_trader/domain.py`

Add any small typed result structures needed for MT5 order request or execution result payloads if the existing domain models are insufficient.

### `tests/`

Add MT5 live execution tests that rely on fakes and stub responses rather than a real terminal.

## Data Flow Impact

The MT5 supervised live path should become:

1. parse venue and live mode,
2. resolve MT5 config and symbol alias,
3. verify MT5 dependency and terminal connectivity,
4. verify MT5 login and symbol availability,
5. build a structured MT5 order request from the supervised execution layer,
6. place the MT5 order only when all gates pass,
7. return a structured MT5 result to the CLI and future journal surfaces.

This keeps venue-specific execution details at the adapter edge while the trading core remains unchanged.

## Error Handling

1. MT5 import failure should be reported as a readiness failure.
2. Terminal initialization failure should fail closed.
3. Login failure should fail closed.
4. Missing or unselectable MT5 symbols should fail before order placement.
5. Broker-side order rejection should return a structured rejected result rather than crashing the session.
6. Any unsupported execution mode should refuse order placement cleanly.

## Success Criteria

Phase 6 is complete when:

1. MT5 runtime connectivity is testably supported,
2. MT5 readiness includes terminal-backed checks,
3. supervised tiny-stake MT5 order placement exists behind fail-closed gates,
4. MT5 execution responses are structured and observable,
5. existing Deriv and Phase 5 MT5 scaffolding regressions remain green.

## Follow-On Phase

Once Phase 6 is complete, the next likely phase is deeper MT5 execution management, including controlled close logic, position synchronization, execution journaling expansion, and richer supervised order lifecycle support.
