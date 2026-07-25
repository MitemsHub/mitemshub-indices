# Phase 9 MT5 Analytics Design

## Summary

Phase 9 expands the MT5 execution surface into a proper analytics layer. The goal is to persist MT5 lifecycle analytics in the journal and expose concise CLI summaries so the system can explain MT5 readiness, synchronization, reconciliation, close, and modify outcomes in a structured and reusable way.

This phase does not introduce new MT5 broker actions. It focuses on observability, diagnostics, and reporting for the MT5 execution paths that already exist.

## Context

The repository now has:

1. terminal-backed MT5 readiness,
2. supervised MT5 order placement,
3. synchronized MT5 lifecycle state,
4. supervised close and modify handling,
5. MT5 journal event schemas for sync, reconciliation, close, and modify.

The current gap is that the MT5 analytics path is only partially realized:

1. the MT5 command handlers print results to stdout,
2. MT5 event schemas exist in the journal module,
3. but the live MT5 command handlers do not yet write those journal analytics consistently,
4. and there is no unified MT5 analytics summary surface for operator review.

Because of that, the system can execute MT5 lifecycle operations, but it still lacks a persistent analytics trail and consistent MT5 summaries.

## Goals

1. Wire MT5 execution and lifecycle commands into structured journal analytics.
2. Add concise CLI MT5 analytics summaries on top of journal-backed events.
3. Capture readiness, sync, reconciliation, close, and modify outcomes in a consistent schema.
4. Add focused tests proving MT5 analytics are emitted correctly.
5. Keep all existing MT5 execution behavior unchanged except for richer analytics output.

## Non-Goals

1. No new MT5 broker actions in this phase.
2. No graphical dashboard or web UI in this phase.
3. No long-term storage migration beyond the current JSONL journal path.
4. No rework of the backtest or paper analytics stack.
5. No attempt to solve the separate tick-versus-candle data-usability topic in this phase.

## Design Principles

1. Journal first, summary second.
2. Reuse existing typed MT5 lifecycle state rather than reconstructing analytics from stdout.
3. Keep MT5 analytics append-only and JSON-friendly.
4. Prefer small, explicit event types over large ambiguous payloads.
5. Preserve fail-closed MT5 behavior while making it more observable.

## Scope

### 1. Journal-Backed MT5 Analytics

The MT5 command handlers should write analytics events into the trade journal whenever they evaluate or mutate MT5 lifecycle state.

This should cover at least:

1. runtime readiness outcomes,
2. sync summaries,
3. reconciliation summaries,
4. close outcomes,
5. modify outcomes.

The journal should become the source of truth for later MT5 analytics surfaces.

### 2. MT5 Analytics Summary Payloads

The project should gain a typed or structured summary builder for MT5 analytics so CLI surfaces can render concise analytics without duplicating business logic across commands.

The summary should include:

1. command type,
2. symbol and MT5 venue symbol where relevant,
3. readiness state,
4. lifecycle state counts such as synchronized positions,
5. actionable or ambiguous reconciliation state,
6. broker response acceptance and retcode where relevant,
7. failure reasons where applicable.

### 3. CLI Summary Improvements

MT5 CLI commands should keep their readable output while also producing consistent analytics summaries.

Expected behavior:

1. preserve the current operator-facing prints,
2. add a more unified MT5 analytics summary block or equivalent normalized lines,
3. keep command-specific outputs explicit and readable,
4. avoid hiding critical failures in overly compressed summaries.

### 4. Journal Event Coverage

The journal should explicitly cover the MT5 command lifecycle in a consistent way.

Examples:

1. `mt5_runtime_summary`
2. `mt5_sync_summary`
3. `mt5_reconcile_summary`
4. `mt5_close_result`
5. `mt5_modify_result`

If a command fails before the broker mutation happens, the journal should still capture the relevant summary event and failure reasons.

### 5. Testing Strategy

The analytics phase should prove:

1. MT5 journal events are emitted from real command flows rather than only through direct journal tests,
2. summaries reflect the typed MT5 lifecycle results correctly,
3. earlier MT5 lifecycle flows still behave the same functionally,
4. full regression remains green.

## Proposed Changes By Module

### `src/synthetic_trader/journal/trade_journal.py`

Add any missing MT5 summary helpers needed for analytics coverage, especially around runtime readiness.

### `src/synthetic_trader/cli.py`

Wire existing MT5 commands so they write analytics to a journal path and print normalized MT5 analytics summaries.

### `src/synthetic_trader/execution/mt5.py`

Expose any small helper functions needed to normalize MT5 lifecycle state into summary-friendly payloads if the existing dataclasses are not enough.

### `tests/`

Add focused MT5 analytics tests for command-driven journal emission and CLI summaries.

## Data Flow Impact

The MT5 analytics flow should become:

1. run the existing MT5 command path,
2. collect typed readiness or lifecycle results,
3. emit structured journal analytics,
4. print concise CLI summary lines,
5. preserve existing command exit behavior.

This keeps analytics attached to the real execution flow instead of reconstructing it later.

## Error Handling

1. Readiness failures should still emit journal analytics with failure reasons.
2. Synchronization and reconciliation failures should still emit summary events.
3. Broker-side close or modify rejection should emit structured journal analytics and remain visible in CLI output.
4. Analytics emission should not weaken or bypass fail-closed execution rules.

## Success Criteria

Phase 9 is complete when:

1. MT5 commands emit journal-backed analytics consistently,
2. CLI summaries expose MT5 lifecycle analytics in a normalized way,
3. readiness, sync, reconciliation, close, and modify outcomes are all journaled,
4. existing MT5 lifecycle functionality remains unchanged,
5. focused analytics tests and full regression remain green.

## Follow-On Phase

Once Phase 9 is complete, the next likely phase is broader MT5 execution reporting and operator review surfaces, such as richer analytics artifacts, monitoring extensions, and venue-specific performance summaries.
