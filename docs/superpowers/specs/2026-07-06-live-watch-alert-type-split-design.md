# Live Watch Alert Type Split Design

## Purpose

This design separates the meaning of a watch alert into two layers:

- `call` for directional trade semantics
- `alert_type` for operator-level alert class

The goal is to make the live watch feed easier to scan under pressure by distinguishing true actionable setup alerts from non-actionable market-context updates.

## Scope

This design covers:

1. Adding `alert_type` to `live-watch` alert payloads.
2. Using `setup_candidate` for valid actionable alerts.
3. Using `context_update` for non-actionable market-state changes.
4. Rendering `alert_type` in both live watch and watch review output.
5. Preserving the current decision package for valid setups.

## Non-Goals

- Changing signal generation or risk approval logic.
- Changing the existing `call` values.
- Removing the decision package from valid alerts.
- Creating separate CLI commands for setup and context feeds.
- Adding external notifications or execution behavior.

## Current Problem

The current watch feed uses one primary alert concept:

- directional `call`

That works, but it forces the operator to infer whether a line is:

- a true setup candidate
- or
- a non-actionable change in market context

This is especially inefficient when the system is already capable of surfacing decision-ready packages for valid setups.

## Design Goals

- Preserve directional `call` values already used across the watch system.
- Add a simple explicit label that tells the operator what class of alert they are seeing.
- Keep valid setup alerts decision-first.
- Keep context alerts concise and readable.
- Reuse the same payload and renderer in `live-watch` and `live-watch-review`.

## Approaches Considered

### Option 1: Rename `stand_aside`

Replace `stand_aside` with `context_update`.

Pros:

- minimal implementation
- small payload change

Cons:

- weak separation of concepts
- loses the established call vocabulary
- does not help valid setup alerts at all

### Option 2: Add `alert_type`

Keep directional `call`, but add a separate `alert_type` field to classify the alert.

Pros:

- best clarity for operators
- keeps current directional vocabulary intact
- easy to reuse in watch review
- keeps the decision package unchanged

Cons:

- adds one more field to the payload

### Option 3: Fully Separate Payload Shapes

Create one payload shape for valid setup alerts and a different payload shape for context alerts.

Pros:

- strongest semantic separation

Cons:

- heavier implementation
- more branching in renderers and tests
- unnecessary at current scope

## Selected Approach

Use Option 2: add `alert_type` while keeping the current directional `call`.

This is the cleanest way to improve the operator feed without disturbing the current strategy and watch logic.

## Alert Model

### Directional Call

Keep existing values:

- `buy_candidate`
- `sell_candidate`
- `stand_aside`

### Alert Type

Add:

- `setup_candidate`
- `context_update`

Rules:

- valid `buy_candidate` or `sell_candidate` alerts must use `alert_type=setup_candidate`
- non-actionable alerts must use `alert_type=context_update`

## Rendering Rules

### Valid Setup Alerts

For valid setup alerts, render in this order:

1. `decision_summary`
2. `alert_type`
3. `call`
4. `symbol`
5. `why`
6. `wait_for`
7. `entry_area`
8. `stop_area`
9. `target_area`
10. `entry`
11. `stop_loss`
12. `take_profit`
13. `reward_risk`
14. support fields such as `trade_status`, `direction_bias`, `regime`, `confidence`, `current_close`

### Context Alerts

For non-actionable alerts, render in this order:

1. `alert_type`
2. `call`
3. `symbol`
4. `why`
5. `wait_for`
6. support fields such as `trade_status`, `direction_bias`, `regime`, `confidence`, `current_close`, `reasons`

Context alerts should not gain trade-package noise.

## Data Flow

1. `analyze_live_snapshot()` continues producing the same directional decision information.
2. `build_watch_alert()` maps the snapshot into:
   - `alert_type=setup_candidate` for valid actionable alerts
   - `alert_type=context_update` for non-actionable alerts
3. `render_live_watch_alert_text()` renders `alert_type` in a stable order.
4. `live-watch-review` automatically benefits because it reuses the same alert payloads and renderer.

## Transition Semantics

This stage does not require changing the current candle-close evaluation model.

However, once `alert_type` exists, future watch transition logic can distinguish between:

- actionable setup changes
- context-only changes

without overloading the meaning of `call`.

## File Plan

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - enrich alert payloads with `alert_type`
  - update rendering order
- Modify: `tests/test_live_market_snapshot.py`
  - add coverage for valid and invalid alert type assignment
  - add coverage for rendering in both live watch and review output

## Testing Strategy

Add focused tests for:

1. valid alert payload
   - includes `alert_type=setup_candidate`
2. non-valid alert payload
   - includes `alert_type=context_update`
3. valid live alert rendering
   - shows `alert_type` after `decision_summary`
4. context alert rendering
   - shows `alert_type` first and stays concise
5. review rendering
   - reuses the same `alert_type` display

## Success Criteria

This design is successful when:

- the operator can instantly tell whether an alert is actionable or contextual
- valid setup alerts keep their current decision package
- context alerts remain concise
- live watch and watch review show the same alert-type split
- the system remains strictly read-only
