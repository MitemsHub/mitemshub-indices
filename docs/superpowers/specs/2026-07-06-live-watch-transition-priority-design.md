# Live Watch Transition Priority Design

## Purpose

This design upgrades `live-watch` alert emission so true setup transitions always stand out, while routine context churn is suppressed unless it materially changes the market picture.

The goal is to keep the operator feed decision-first without losing the usefulness of contextual watch updates.

## Scope

This design covers:

1. Priority rules for `setup_candidate` versus `context_update` alerts.
2. A suppression or cooldown rule for repeated context updates.
3. Immediate emission for valid actionable setup transitions.
4. Reuse of the same payload and renderer already used by `live-watch` and `live-watch-review`.

## Non-Goals

- Changing signal generation, risk approval, or setup validity rules.
- Removing `context_update` alerts entirely.
- Changing the current decision package format.
- Adding external notification channels.
- Creating a second journal format.

## Current Problem

The watch system now distinguishes between:

- actionable setup alerts
- non-actionable context updates

That is an important improvement, but the current transition logic still treats any meaningful watch-state change as equally eligible for emission.

This means context updates can still compete for attention with true setup transitions.

## Design Goals

- Always emit actionable setup transitions immediately.
- Suppress repeated low-value context churn.
- Keep materially different context changes visible.
- Preserve the current live watch and review surfaces.
- Keep the logic simple enough to reason about and test.

## Approaches Considered

### Option 1: Simple Priority Gate

Always emit `setup_candidate`, and emit `context_update` only when the watch state is materially different.

Pros:

- simple
- low implementation cost

Cons:

- can still emit too many context alerts during noisy periods

### Option 2: Priority Plus Cooldown

Always emit `setup_candidate`, and emit `context_update` only when it is materially different and not inside a short suppression window.

Pros:

- strongest operator experience
- keeps setup alerts immediate
- reduces context spam during noisy market phases

Cons:

- slightly more state handling

### Option 3: Setup-Only Live Feed

Emit only setup transitions live and leave context changes only for passive review.

Pros:

- very quiet live feed

Cons:

- loses useful live market context
- weaker guidance when the market meaningfully shifts without becoming actionable

## Selected Approach

Use Option 2: priority plus cooldown.

This gives the cleanest balance between actionable immediacy and feed discipline.

## Priority Rules

### Setup Candidate Alerts

If the current alert is `alert_type=setup_candidate`, emit it immediately whenever it represents a meaningful change from the previous watch state.

Setup alerts must bypass any context cooldown rule.

### Context Update Alerts

If the current alert is `alert_type=context_update`, emit it only when:

1. the context change is materially different
2. and it is outside the context suppression window

## Material Context Change

A context update should count as materially different when at least one of these changes:

- `regime`
- `direction_bias`
- `trade_status`
- `wait_for`

Small confidence movements alone should not force a context emission if the broader picture is unchanged.

## Cooldown Design

Add a short context cooldown measured in primary candle-close emissions, not wall-clock time.

Recommended default:

- suppress repeated `context_update` emissions for `2` primary alert opportunities after the last emitted context update

This cooldown applies only to context alerts. It must not block setup alerts.

## Watch State Extension

The watch state or transition helper should gain enough information to support:

- current `alert_type`
- material context comparison
- recent emitted context position or cooldown counter

The exact implementation can remain internal as long as it is deterministic and well covered by tests.

## Data Flow

1. `analyze_live_snapshot()` produces the same directional decision snapshot.
2. `build_watch_alert()` classifies the alert as `setup_candidate` or `context_update`.
3. Transition logic evaluates:
   - did the watch state change materially?
   - is the current alert a setup or context alert?
   - if context, is it outside cooldown?
4. Emitted alerts continue to flow through the existing journal and renderer paths.

## Rendering

No new rendering format is required for this stage.

The current `alert_type` and decision package output remains sufficient.

## File Plan

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - extend transition logic with alert-type-aware priority and context cooldown handling
- Modify: `tests/test_live_market_snapshot.py`
  - add focused priority and suppression tests

## Testing Strategy

Add focused tests for:

1. setup transition priority
   - `setup_candidate` emits immediately
2. context suppression
   - repeated context changes within cooldown do not emit
3. material context change outside cooldown
   - emits correctly
4. setup bypass
   - setup alert still emits even if a context cooldown is active
5. review compatibility
   - emitted alerts still render and review normally

## Success Criteria

This design is successful when:

- setup transitions always stand out immediately
- repeated context churn is reduced
- materially different context remains visible
- live watch and review keep working with the same alert payloads
- the feature remains strictly read-only
