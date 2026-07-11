# Live Watch Default Operator Interface Design

## Purpose

This design makes `live-watch` the default operator-facing interface for receiving read-only trading calls on `R_100`, while extending `live-watch-review` so the operator can review transport health and recent call context after or during a session.

The goal is to give the operator one primary command for actionable market calls and one separate review command for audit, suppression visibility, and reconnect evidence, without mixing transport noise into the live call stream.

## Scope

This design covers:

1. Treating `live-watch` as the primary operator workflow for live calls on `R_100`.
2. Strengthening the live `live-watch` output so it reads as an operator call surface rather than a generic alert dump.
3. Extending `live-watch-review` to surface `watch_transport` records alongside the existing emitted-alert and suppressed-context review.
4. Defining a clear operator workflow for checking the current call, reviewing recent state, and understanding reconnect behavior.
5. Focused tests for transport-review parsing, rendering, and CLI behavior.

## Non-Goals

- Changing the decision engine, risk thresholds, or signal approval rules.
- Executing trades from `live-watch`.
- Showing reconnect events directly in the live `live-watch` stream.
- Building a GUI, dashboard, or notification channel in this step.
- Tuning reconnect backoff policy from live evidence in this step.
- Implementing armed-live reconciliation expansions in this step.

## Current Problem

The project now has the building blocks for operator use:

- `live-watch` emits meaningful state transitions and valid setup candidates.
- reconnect events are journaled as `watch_transport` records.
- `live-watch-review` shows emitted alerts and suppressed context visibility.

But the operator workflow is still incomplete:

- the default "how do I get the call right now?" interface is not explicitly standardized around `live-watch`
- the live output still reads like a raw alert renderer instead of a deliberate operator call surface
- reconnect evidence exists in the journal but is not visible in the review surface

That leaves the operator with the right raw information, but not yet the cleanest default operating loop for manual trade execution based on system calls.

## Design Goals

- Make `live-watch` the obvious default command for receiving live calls.
- Keep the live output decision-first, compact, and human-operable.
- Preserve the rule that transport events are journaled but never promoted to live call alerts.
- Make `live-watch-review` the authoritative read-only review surface for:
  - emitted call history
  - suppressed context visibility
  - transport/reconnect visibility
- Keep the implementation incremental and compatible with the existing journal file.

## Approaches Considered

### Option 1: Keep Current Commands And Document Them Better

Pros:

- lowest implementation cost
- no behavior changes

Cons:

- does not improve the actual operator-facing output
- leaves transport evidence stranded in the raw journal
- keeps the call workflow under-specified

### Option 2: Make `live-watch` The Default Operator Surface And Extend Review For Transport Visibility

Pros:

- best fit for the current architecture
- keeps the live feed clean and actionable
- makes review the single audit surface for emitted, suppressed, and transport records
- directly supports the user's intended workflow of receiving calls and placing trades manually

Cons:

- requires moderate snapshot and rendering changes
- adds more review fields to maintain

### Option 3: Build A New Dedicated Operator Command

Pros:

- allows a custom workflow without legacy constraints
- could separate operator language from internal alert language completely

Cons:

- duplicates existing watch logic
- fragments the CLI surface
- increases maintenance cost without enough added value yet

## Selected Approach

Use Option 2: keep `live-watch` as the execution-adjacent call surface and extend `live-watch-review` as the journal-backed operator review surface.

This preserves the strongest parts of the current system:

- one live read-only call stream
- one review command
- one journal file

It also keeps the workflow aligned with the user's manual execution model: the system gives the call, and the operator decides whether to place the trade manually.

## Operator Workflow

### Primary Interface

The default operator interface is:

`python -m synthetic_trader.cli live-watch --symbol R_100 --emit-initial`

This command should remain the main way to receive current and evolving calls during an active monitoring session.

### Supporting Interface

The supporting review interface is:

`python -m synthetic_trader.cli live-watch-review --journal <path> --symbol R_100`

This command is used when the operator needs to:

- confirm the latest emitted call in a compact summary
- review the recent emitted call trail
- confirm that suppressed context churn occurred
- confirm whether reconnects or transport failures happened during the session

### Intended Operator Loop

1. Start `live-watch` for `R_100`.
2. Treat `setup_candidate` output as the actionable live call surface.
3. Use `context_update` output only as directional guidance.
4. If the live session goes quiet or reconnects are suspected, run `live-watch-review`.
5. Use review output to understand:
   - what was actually emitted live
   - what context changes were suppressed
   - whether transport instability occurred

## Live Output Design

### Meaning Of The Live Feed

`live-watch` remains the only live operator-facing call stream in this phase.

Its output should communicate:

- whether there is an actionable candidate now
- why that candidate or stance exists
- what the operator should wait for next

The live feed must not show:

- reconnect attempt lines
- reconnect success lines
- reconnect failure lines
- suppressed-context records

Those remain review-only journal records.

### Alert Presentation Rules

The rendered `live-watch` output should continue to use the current fields, but should be tightened around operator readability:

- `decision_summary` should remain first when present
- `alert_type`, `call`, `symbol`, and `why` stay near the top
- `wait_for` remains visible for non-valid and valid states
- trade package fields remain visible only for valid setup candidates

This step does not rename the underlying `call` values. The system continues to emit:

- `buy_candidate`
- `sell_candidate`
- `stand_aside`

The improvement is about treating that output as the standard operator surface, not inventing a second naming system.

## Journal And Review Design

### Single Journal, Three Record Families

`live-watch` review continues to use one JSONL journal that may contain:

- emitted alerts
- suppressed context records
- transport records

The record boundaries remain explicit:

- emitted alert: has `call` and `symbol`
- suppressed context: `record_type=suppressed_context`
- transport event: `record_type=watch_transport`

### Transport Record Review Fields

Extend the review snapshot so transport visibility becomes first-class. The snapshot should include:

- `transport_event_count`
- `latest_transport_event`
- `latest_transport_reason`
- `latest_transport_attempt`
- `latest_transport_attempts`
- `latest_transport_regime`
- `latest_transport_direction_bias`
- `latest_transport_trade_status`
- `latest_transport_confidence`

If no transport records match the current filters, these fields should resolve safely to:

- count `0`
- latest transport fields `None`

### Filtering Rules

Transport review should honor the same symbol scoping as the rest of the review surface.

Rules:

- `--symbol` filters transport records by `symbol`
- `--call` does not apply to transport records because transport records do not represent emitted calls
- `--valid-only` does not apply to transport records and should not remove them from transport visibility

This is intentional because transport health is operational evidence, not market-direction evidence.

## Review Output Design

### Existing Sections

Keep the current review sections:

- latest emitted call summary
- suppression summary
- recent emitted alerts list

### New Transport Summary Section

Insert a compact transport summary between the suppression summary and the recent emitted alerts list.

It should render:

- `review_transport_event_count`
- `review_latest_transport_event`
- `review_latest_transport_reason`
- `review_latest_transport_attempt`
- `review_latest_transport_attempts`
- `review_latest_transport_regime`
- `review_latest_transport_direction_bias`
- `review_latest_transport_trade_status`
- `review_latest_transport_confidence`

This section should always render, even when the count is zero, so the operator can see transport stability explicitly.

### Recent Alerts List

The existing recent alert list continues to mean:

"what the operator actually saw live"

Therefore:

- emitted alerts stay in the recent alert list
- suppressed records do not appear in that list
- transport records do not appear in that list

This keeps the meaning of the recent alert trail stable.

## Error Handling

The review command should keep existing failure behavior for:

- missing journal file
- invalid JSONL that cannot be parsed

Transport parsing should be defensive:

- ignore non-dict payloads
- ignore transport records missing `symbol`
- ignore unknown record types unless they clearly match an existing supported family

Empty-but-valid snapshots should still render safely.

## File Plan

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - extend journal loading to return transport records
  - extend review snapshot building with transport summary fields
  - extend review rendering with transport summary output
  - tighten any live alert rendering needed for operator readability without changing alert semantics
- Modify: `src/synthetic_trader/cli.py`
  - update help text if needed so `live-watch` and `live-watch-review` read as the primary operator workflow
- Modify: `tests/test_live_market_snapshot.py`
  - add focused tests for transport parsing, transport-aware review filtering, rendering, and CLI review output

## Testing Strategy

Add focused tests for:

1. journal parsing
   - emitted alerts, suppressed records, and transport records are separated correctly
2. transport review snapshot
   - latest transport fields are populated from the newest matching transport record
   - zero-transport snapshots remain safe
3. filter behavior
   - symbol filters affect transport counts and latest transport preview
   - `valid-only` still zeroes suppressed records but leaves transport visibility intact
   - `call` filters continue to affect emitted alerts only
4. rendering
   - transport summary lines render clearly
   - recent emitted alerts stay unchanged
5. CLI behavior
   - `live-watch-review` prints transport visibility in its output
   - `live-watch` help text remains coherent with the operator workflow

## Success Criteria

This design is successful when:

- `live-watch` is the clear default interface for receiving live `R_100` calls
- the live operator feed remains decision-first and free of transport noise
- `live-watch-review` shows emitted, suppressed, and transport visibility from one journal
- the operator can tell quickly whether a session was stable or reconnect-heavy
- the feature remains read-only and does not place trades or change signal logic
