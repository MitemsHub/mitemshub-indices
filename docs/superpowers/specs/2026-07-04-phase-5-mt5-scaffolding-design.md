# Phase 5 MT5 Scaffolding Design

## Summary

Phase 5 extends the platform beyond Deriv by introducing a minimal venue abstraction layer and an MT5 integration scaffold. The goal is to make MT5 a first-class venue for paper-mode session routing and supervised readiness checks without weakening the existing safety model or duplicating the trading pipeline.

This phase does not introduce unattended MT5 live trading. It introduces the structure needed so MT5 can plug into the same research, paper, and supervised guardrails already established for Deriv.

## Context

The repository currently has:

1. a stable research and backtest path,
2. a more realistic paper broker,
3. a reliable live-paper runner for Deriv,
4. explicit supervised live gating for Deriv.

The next step is venue expansion. MT5 is the most logical follow-on venue because:

1. the user has already indicated MT5 is expected later,
2. MT5 introduces different credential, symbol, and transport requirements,
3. adding MT5 directly into the current Deriv-specific seams would create duplication and unsafe coupling.

The right move is to add a small venue abstraction that keeps alpha, risk, and journaling venue-neutral while letting venue adapters handle data access, credential resolution, and supervised execution readiness.

## Goals

1. Add a small venue abstraction for market data and supervised execution routing.
2. Add MT5-specific configuration and credential scaffolding.
3. Add MT5 readiness validation for supervised operation.
4. Allow paper/live session orchestration to select Deriv or MT5 through explicit venue selection.
5. Keep the fail-closed safety model intact across venues.
6. Add tests proving MT5 routing and readiness work without requiring a real MT5 terminal during test runs.

## Non-Goals

1. No unattended autonomous MT5 trading.
2. No production-grade MT5 execution engine in this phase.
3. No broad multi-broker feature matrix beyond the minimum abstractions needed for Deriv and MT5.
4. No strategy or alpha changes driven by venue expansion.
5. No attempt to normalize every venue-specific nuance in one phase.

## Design Principles

1. Keep alpha logic separate from venue logic.
2. Fail closed across every supervised path.
3. Prefer small abstractions over a heavy broker framework.
4. Keep Deriv behavior stable while MT5 support is introduced.
5. Make MT5 integration testable with fakes rather than terminal-dependent tests.

## Scope

### 1. Venue Abstraction

The codebase should gain a small execution-venue seam rather than spreading MT5 conditionals through the existing Deriv flow.

This abstraction should cover:

1. market-data access needed by live-paper or live-observation flows,
2. supervised execution entry points,
3. readiness and capability checks,
4. venue-specific symbol mapping where needed.

It should remain intentionally narrow. The goal is not to model every broker feature. The goal is to give the current paper and supervised flows a venue-neutral contract.

### 2. MT5 Configuration And Credentials

MT5 requires a different configuration shape than Deriv. The scaffold should support fields such as:

1. broker or server name,
2. login,
3. password or other required secret,
4. terminal path when required by the runtime environment,
5. symbol aliases that map project symbols such as `R_75` and `R_100` to the exact names visible in MT5.

This configuration should be resolved explicitly from CLI flags or environment variables rather than being hidden in ad hoc runtime logic.

### 3. MT5 Readiness Validation

MT5 supervised readiness should mirror the existing Deriv readiness philosophy, but with MT5-specific checks.

Examples:

1. venue is `mt5`,
2. required MT5 credentials are present,
3. target symbol is mapped,
4. required runtime dependencies are available,
5. supervised mode is compatible with the requested operation.

The output should clearly explain why MT5 readiness passed or failed.

### 4. Paper Session Routing

The existing paper/live session orchestration should be able to select a venue explicitly.

Requirements:

1. Deriv remains the default so existing flows do not break.
2. MT5 can be selected through explicit CLI input.
3. MT5 paper-mode routing should use the same candle, decision, risk, paper-broker, and journal flow already used elsewhere.
4. Venue-specific data access should happen behind the venue seam rather than inside decision or risk modules.

### 5. Supervised MT5 Session Scaffolding

This phase should support supervised MT5 session entry, but only at the scaffold level.

That means:

1. readiness checks exist,
2. session routing exists,
3. fail-closed behavior exists,
4. real terminal-dependent execution can still remain stubbed or guarded until a later phase.

This gives the project a clean supervised pathway for MT5 without prematurely expanding into a production live engine.

### 6. Symbol Mapping

The project currently uses normalized symbols such as `R_75` and `R_100`. MT5 may expose different symbol names depending on broker configuration.

The design should add a symbol alias layer so:

1. internal research and strategy modules continue to use normalized symbols,
2. venue adapters translate those normalized symbols into venue-native names,
3. readiness fails cleanly if the requested symbol has no MT5 mapping.

### 7. Test Coverage

Phase 5 should add focused tests around:

1. MT5 config resolution,
2. MT5 readiness pass and failure cases,
3. venue routing in the CLI,
4. paper session routing through a fake MT5 adapter,
5. fail-closed supervised MT5 session behavior,
6. regression coverage proving existing Deriv behavior still passes.

## Proposed Changes By Module

### `src/synthetic_trader/config.py`

Add the minimum venue-aware configuration needed for MT5, such as venue type, MT5 credential fields, and symbol alias support.

### `src/synthetic_trader/execution/`

Add a small venue abstraction module and an MT5 adapter module. The abstraction should define the narrow contracts needed by paper-session and supervised-session orchestration.

### `src/synthetic_trader/live/paper_runner.py`

Refactor the Deriv-specific live-paper runner so the market-data client or venue adapter can be injected. Preserve the current paper logic and finalization behavior.

### `src/synthetic_trader/live/supervised_live.py`

Extend supervised readiness and session routing so they can evaluate venue-specific readiness and select a venue-specific supervised session path.

### `src/synthetic_trader/cli.py`

Add explicit venue parsing and MT5-related runtime inputs. Print readiness results clearly before any supervised session can proceed.

### `tests/`

Add MT5-focused tests using fakes and small stubs rather than any hard dependency on a running MT5 terminal.

## Data Flow Impact

The live paper and supervised path should become:

1. parse venue and execution mode,
2. resolve venue-specific config,
3. map normalized symbol to venue symbol,
4. run venue-specific readiness checks,
5. route into a venue adapter for data access or supervised session handling,
6. keep the existing decision, risk, paper broker, and journal pipeline unchanged.

This keeps the existing system core stable while moving venue-specific behavior to the edges.

## Error Handling

1. Missing MT5 credentials should fail during readiness.
2. Missing symbol mappings should fail before session start.
3. Unsupported venue/mode combinations should fail early and visibly.
4. Any unavailable MT5 dependency should fail closed rather than silently degrading into a risky partial path.
5. Existing Deriv behavior should remain the fallback default unless the user explicitly selects MT5.

## Testing Strategy

1. Start with unit-like tests for MT5 config, readiness, symbol mapping, and routing.
2. Use fake venue adapters for MT5 session tests.
3. Avoid real terminal dependencies in the automated suite.
4. Run focused MT5 slices first, then rerun the full project regression suite.

## Success Criteria

Phase 5 is complete when:

1. venue selection is explicit,
2. MT5 config and symbol mapping are representable,
3. MT5 readiness validation is observable,
4. MT5 paper and supervised routing are scaffolded behind a venue seam,
5. the supervised MT5 path remains fail-closed,
6. existing Deriv regressions remain green.

## Follow-On Phase

Once Phase 5 is complete, the next likely phase is controlled MT5 live execution wiring, including terminal-backed connectivity checks, supervised tiny-stake execution, and venue-specific order/fill handling, still gated behind explicit operator confirmation and readiness validation.
