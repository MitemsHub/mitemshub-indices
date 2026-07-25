# Phase 10 MT5 Monitor Design

## Summary

Phase 10 builds the first operator-facing review surface on top of the MT5 analytics stream completed in Phase 9. The goal is to turn journal-backed MT5 lifecycle events into a concise CLI monitor so an operator can inspect MT5 readiness, synchronization, reconciliation, and recent action outcomes without reading raw JSONL.

This phase does not add new MT5 broker actions. It focuses on observability consumption, not execution expansion.

## Context

The repository now has:

1. terminal-backed MT5 readiness checks,
2. supervised MT5 order placement,
3. synchronized MT5 lifecycle state,
4. supervised close and modify handling,
5. journal-backed MT5 analytics for runtime, sync, reconcile, close, and modify flows,
6. normalized `mt5_*` CLI summary lines emitted from real MT5 command paths.

The current gap is that MT5 analytics are now being produced, but there is no operator review surface that aggregates those events into one readable MT5 state view.

Today:

1. MT5 command handlers emit analytics into JSONL journals,
2. the existing monitor surface only understands paper-live summary payloads,
3. operators must inspect raw journal lines to review MT5 lifecycle health,
4. there is no single CLI command that summarizes the recent MT5 lifecycle trail.

Because of that, observability exists at the storage layer but not yet at the operator review layer.

## Goals

1. Add an MT5-specific CLI monitor command that reads journal-backed analytics.
2. Build a normalized MT5 monitor snapshot from MT5 journal events.
3. Show the latest readiness, sync, reconcile, close, and modify state in one place.
4. Keep the monitor read-only and detached from broker execution.
5. Add focused tests for MT5 monitor parsing and rendering.

## Non-Goals

1. No new MT5 execution, close, or modify behavior.
2. No web dashboard or graphical UI.
3. No replacement of the JSONL journal with a database or alternate storage.
4. No rework of paper-live monitoring beyond what is needed to coexist cleanly.
5. No venue-wide portfolio analytics or performance attribution in this phase.

## Design Principles

1. Journal first, monitor second.
2. Read-only operator review only.
3. Reuse existing MT5 event schemas rather than inventing parallel monitor-only event types.
4. Prefer explicit latest-known-state summaries over opaque event dumps.
5. Preserve fail-closed execution by keeping monitoring completely separate from broker actions.

## Scope

### 1. MT5 Journal Snapshot Builder

The project should gain a monitor snapshot builder that reads MT5 journal entries and derives a compact MT5 state summary.

The builder should:

1. ignore non-MT5 events,
2. consume the existing MT5 event types,
3. track the latest relevant state for each MT5 lifecycle category,
4. produce a JSON-friendly snapshot dict for rendering or later serialization.

Covered MT5 event types:

1. `mt5_runtime_summary`
2. `mt5_sync_summary`
3. `mt5_reconcile_summary`
4. `mt5_close_result`
5. `mt5_modify_result`

### 2. MT5 Monitor Snapshot Shape

The MT5 monitor snapshot should be compact, explicit, and operator-readable.

The snapshot should include at least:

1. `symbol`
2. `venue_symbol`
3. `runtime_ready`
4. `runtime_failures`
5. `positions`
6. `sync_failures`
7. `reconcile_actionable`
8. `reconcile_target_ticket`
9. `reconcile_failures`
10. `last_close_ticket`
11. `last_close_accepted`
12. `last_close_retcode`
13. `last_close_message`
14. `last_modify_ticket`
15. `last_modify_accepted`
16. `last_modify_retcode`
17. `last_modify_message`

If a field has not yet been observed in the journal, the snapshot should expose a safe empty value such as `None`, `False`, `0`, or an empty string/list depending on the field type.

### 3. MT5 CLI Monitor Command

The CLI should gain a dedicated read-only MT5 monitor command.

Expected command responsibilities:

1. accept a journal path,
2. optionally filter by symbol,
3. read journal lines,
4. build the MT5 monitor snapshot,
5. print a concise text report to stdout,
6. return a non-zero exit code when the journal file is missing or unreadable.

The command should not require MT5 credentials because it is reading persisted analytics rather than contacting the terminal.

### 4. MT5 Text Rendering

The MT5 monitor command should render a compact text view that is consistent with existing CLI output patterns.

Expected rendering characteristics:

1. one key-value line per field,
2. explicit MT5-oriented field names,
3. readable output even when only partial MT5 history exists,
4. no hiding of failure reasons.

The renderer may use a dedicated helper instead of reusing the paper-live renderer directly if the MT5 surface is materially different.

### 5. Symbol Filtering

If the journal contains multiple MT5 symbols over time, the monitor command should support narrowing the view to one symbol.

Expected behavior:

1. when no symbol is supplied, show the latest MT5 state from all journaled MT5 events,
2. when a symbol is supplied, only consume MT5 events matching that symbol,
3. when the symbol filter yields no MT5 events, return an empty but valid MT5 snapshot rather than crashing.

## Proposed Changes By Module

### `src/synthetic_trader/monitoring/surface.py`

Add MT5-specific helpers for:

1. filtering MT5 journal events,
2. building an MT5 monitor snapshot,
3. rendering MT5 monitor text output.

The existing paper-live helpers should remain intact.

### `src/synthetic_trader/cli.py`

Add a new MT5 monitor command that:

1. accepts a journal path,
2. optionally accepts a symbol filter,
3. reads JSONL entries,
4. builds the MT5 snapshot,
5. prints the rendered MT5 monitor text.

### `src/synthetic_trader/reporting/serializers.py`

No required change is expected for the first MT5 monitor slice because the initial monitor output can remain text-first. This module remains a likely follow-on seam if the MT5 monitor later gains exported artifacts.

### `tests/`

Add focused tests for:

1. MT5 journal event filtering,
2. MT5 snapshot aggregation,
3. MT5 empty-snapshot behavior,
4. MT5 CLI monitor output,
5. coexistence with the existing paper-live monitor behavior.

## Data Flow

The Phase 10 MT5 monitor flow should be:

1. load a JSONL journal file,
2. parse the entries into dict payloads,
3. filter to MT5 analytics event types,
4. optionally filter by symbol,
5. aggregate the latest-known MT5 lifecycle state into one snapshot,
6. render the snapshot as CLI text,
7. exit without contacting MT5 or changing broker state.

This keeps the MT5 monitor as a pure consumer of the analytics stream created in Phase 9.

## Error Handling

1. Missing journal path should return a clear error and non-zero exit code.
2. Empty journal or no MT5 events should render a valid empty MT5 snapshot.
3. Non-MT5 journal entries should be ignored.
4. Invalid JSONL content should fail clearly rather than silently inventing state.
5. Monitor failures must never weaken supervised MT5 execution rules because the monitor is read-only.

## Testing Strategy

The phase should prove:

1. MT5 event sequences aggregate into the correct latest-known snapshot,
2. empty and filtered journal cases remain safe,
3. the CLI monitor prints the expected MT5 state lines,
4. existing paper-live monitor behavior still works,
5. the full regression suite remains green.

## Success Criteria

Phase 10 is complete when:

1. an operator can run a dedicated MT5 monitor command against a journal file,
2. the monitor summarizes readiness, sync, reconcile, close, and modify state from MT5 journal events,
3. symbol filtering works safely,
4. the monitor remains read-only,
5. focused tests and full regression remain green.

## Follow-On Phase

Once this phase is complete, the next likely phase is exporting MT5 monitor snapshots as structured artifacts or extending the monitor into richer venue-level reporting for operator review and audit trails.
