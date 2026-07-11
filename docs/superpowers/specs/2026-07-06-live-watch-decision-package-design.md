# Live Watch Decision Package Design

## Purpose

This design upgrades valid `live-watch` alerts from a raw field list into a compact operator-facing decision package.

The goal is to make a valid `buy_candidate` or `sell_candidate` feel like a short trade brief first, while still preserving the exact structured levels and supporting fields underneath.

## Scope

This design covers:

1. A compact summary field for valid watch alerts.
2. Summary-first rendering for valid setup alerts.
3. Reuse of the same decision package in both `live-watch` and `live-watch-review`.
4. Preservation of existing structured fields such as entry, stop, target, and reward/risk.

## Non-Goals

- Changing strategy logic, confidence thresholds, or trade filtering.
- Changing watch transition detection.
- Changing invalid `stand_aside` alerts into verbose briefs.
- Adding execution automation or broker actions.

## Current Problem

The project now emits valid setup alerts with the right trade levels and context, but the presentation is still field-led.

That means the operator sees the right information, but not in the most decision-ready order. A valid setup should read like:

- what this is
- why it matters
- what to wait for
- where the levels are

before the rest of the structured details.

## Design Goals

- Keep valid alerts trader-readable and decision-first.
- Preserve all exact trade levels already surfaced by the watch alert payload.
- Keep invalid alerts concise.
- Reuse the same payload and renderer across live watch and watch review.

## Approaches Considered

### Option 1: Renderer-Only Summary

Generate a top-line sentence only in the terminal renderer while leaving the alert payload unchanged.

Pros:

- minimal implementation
- quick visual improvement

Cons:

- review journals do not store the decision package
- live and review views can drift

### Option 2: Payload + Renderer Summary

Add a compact summary field to valid alerts and render it first anywhere the alert is shown.

Pros:

- best consistency across live output and review
- keeps one source of truth for operator wording
- preserves all structured fields

Cons:

- slightly more payload shape to maintain

### Option 3: Separate Decision Package Builder

Create a dedicated helper specifically for valid alert packages and call it from multiple places.

Pros:

- clean long-term abstraction if the package expands further

Cons:

- slightly more structure than needed right now

## Selected Approach

Use Option 2: add a summary field to valid alerts and render it first.

This is the strongest fit because the watch journal and review surface already reuse the same alert payloads and renderers. The decision package should live in that same shared path.

## Design

### Valid Alert Package

For valid `buy_candidate` and `sell_candidate` alerts, add:

- `decision_summary`

The summary should be compact, deterministic, and built from fields already available in the alert payload.

Example style:

- `buy setup valid; trend and structure aligned; wait for bullish continuation close`
- `sell setup valid; downside pressure aligned; wait for bearish continuation close`

The summary should draw from:

- `call`
- `trade_status`
- `why`
- `wait_for`

It should not introduce new market interpretation logic beyond what the system already emits.

### Invalid Alert Behavior

Invalid `stand_aside` alerts should remain concise and should not gain a decision package summary.

This keeps the feed from becoming noisy.

### Rendering Order

For valid alerts, render in this order:

1. `decision_summary`
2. `call`
3. `symbol`
4. `why`
5. `wait_for`
6. `entry_area`
7. `stop_area`
8. `target_area`
9. `entry`
10. `stop_loss`
11. `take_profit`
12. `reward_risk`
13. remaining support fields such as regime, confidence, and current close

For invalid alerts, keep the current concise ordering without `decision_summary`.

## Data Flow

1. `analyze_live_snapshot()` continues to produce the same decision content.
2. `build_watch_alert()` enriches valid alerts with `decision_summary`.
3. `render_live_watch_alert_text()` prints the summary first when present.
4. `live-watch-review` benefits automatically because it reuses the same alert renderer.

## File Plan

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - add decision package summary helper and summary-first rendering behavior
- Modify: `tests/test_live_market_snapshot.py`
  - add focused valid/invalid decision package tests

## Testing Strategy

Add focused tests for:

1. valid alert payload
   - includes `decision_summary`
2. invalid alert payload
   - omits `decision_summary`
3. valid alert rendering
   - summary appears before the other fields
4. review rendering
   - recent valid alerts show the same summary-first format

## Success Criteria

This design is successful when:

- valid watch alerts read like compact trade briefs first
- exact numeric levels remain present and unchanged
- invalid alerts stay concise
- review output shows the same decision package wording as live output
- the feature remains strictly read-only
