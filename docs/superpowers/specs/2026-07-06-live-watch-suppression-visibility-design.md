# Live Watch Suppression Visibility Design

## Purpose

This design makes `live-watch-review` show what the transition-priority system intentionally suppressed, without reintroducing that noise into the live operator feed.

The goal is to preserve the clean decision-first live stream while giving the operator post-hoc visibility into withheld context churn.

## Scope

This design covers:

1. Visibility for suppressed `context_update` transitions inside `live-watch-review`.
2. A compact suppression summary with counts and the latest withheld context preview.
3. Journal handling for both emitted alerts and suppressed-context records in the same JSONL file.
4. Reuse of the existing emitted-alert renderer for normal recent alerts.

## Non-Goals

- Changing signal generation, risk approval, or setup validity rules.
- Changing the current `live-watch` terminal output format.
- Emitting suppressed context updates live.
- Adding dashboards, push notifications, or broker execution behavior.
- Creating a separate journal file for suppressed records.

## Current Problem

The transition-priority upgrade correctly suppresses repeated low-value context churn, but it also creates an operator blind spot during review:

- the operator can see what was emitted
- but cannot see whether context transitions were withheld on purpose

That makes it harder to distinguish between:

- a quiet market with no relevant context change
- and
- a noisy context phase that the system intentionally filtered out

## Design Goals

- Keep the live feed unchanged and decision-first.
- Show that suppression is happening when it happens.
- Give the operator the latest withheld context picture without dumping a full noisy trail.
- Preserve a single journal source for both live watch and review.
- Keep the design deterministic and easy to test.

## Approaches Considered

### Option 1: Counts Only

Show only the number of suppressed context transitions in the review output.

Pros:

- lowest output noise
- lowest implementation cost

Cons:

- too opaque
- does not tell the operator what kind of context was withheld

### Option 2: Counts Plus Latest Withheld Preview

Show suppression counts plus a compact preview of the latest withheld context transition.

Pros:

- strongest balance between clarity and noise control
- gives proof of suppression activity
- preserves the clean live feed

Cons:

- slightly more snapshot-building logic

### Option 3: Full Withheld Trail

Show a dedicated newest-first list of all suppressed context transitions.

Pros:

- maximum transparency

Cons:

- reintroduces the churn the priority system was designed to suppress
- weakens scanability of the review output

## Selected Approach

Use Option 2: counts plus latest withheld preview.

This keeps `live-watch` clean while making review substantially more informative. The operator gets both proof that suppression was active and a concise picture of the latest withheld market context.

## Journal Design

### Single Journal, Two Record Types

Keep using the existing `live-watch` JSONL journal.

The file may contain:

- emitted alert records
- suppressed context records

Emitted alerts keep their current shape.

Suppressed context records should use an explicit marker so review parsing can distinguish them safely, for example:

- `record_type=suppressed_context`

The rest of the payload should remain aligned with existing watch fields where practical:

- `symbol`
- `call`
- `alert_type`
- `trade_status`
- `direction_bias`
- `regime`
- `confidence`
- `why`
- `wait_for`

The suppressed record should also include a small amount of suppression-specific metadata:

- `suppression_reason`
- `suppressed_after_context_cooldown`

This remains read-only journaling and does not alter emitted alert payloads.

## Emission Behavior

### Live Feed

No change to live terminal rendering.

Suppressed context transitions must not print to the live feed.

### Journaling

When a materially different `context_update` is blocked by the cooldown rule, the watch loop should append a suppressed-context record to the same journal.

Setup alerts still emit immediately and do not generate suppressed records.

Context transitions that are not materially different should remain fully ignored and should not produce suppressed records, because they do not represent meaningful operator context.

## Review Snapshot Design

Extend the `live-watch-review` snapshot builder to return both emitted-alert review fields and suppression visibility fields.

In addition to the current summary, include:

- `suppressed_context_count`
- `latest_suppressed_symbol`
- `latest_suppressed_call`
- `latest_suppressed_direction_bias`
- `latest_suppressed_regime`
- `latest_suppressed_why`
- `latest_suppressed_wait_for`
- `latest_suppressed_confidence`

If no suppressed records match the current filters, these fields should resolve safely to:

- count `0`
- latest suppressed fields `None`

## Filtering Rules

Review filters should apply consistently to suppressed records as well as emitted alerts.

### Symbol Filter

If `--symbol` is supplied, suppression counts and latest withheld preview should include only records for that symbol.

### Call Filter

If `--call` is supplied, the emitted alert list should still filter by `call`.

Suppressed records should also honor the same `call` filter if their `call` field is present.

### Valid-Only

`--valid-only` should continue to filter emitted alerts to approved setups.

For suppressed records, `valid-only` should normally result in zero suppressed context matches because suppressed records are specifically for `context_update` entries rather than valid setup alerts. This behavior should be explicit and stable.

## Output Design

### Existing Review Summary

Keep the current emitted-alert summary unchanged:

- latest call
- symbol
- trade status
- direction bias
- regime
- confidence
- current close
- wait-for guidance
- alert count

### Suppression Summary

Insert a compact suppression section after the existing summary and before recent emitted alerts:

- `review_suppressed_context_count`
- `review_latest_suppressed_direction_bias`
- `review_latest_suppressed_regime`
- `review_latest_suppressed_why`
- `review_latest_suppressed_wait_for`

This section should appear even when the count is zero so the operator can see suppression status explicitly.

### Recent Alerts Section

Keep the current recent emitted alert section unchanged.

Do not render suppressed records in the normal recent alert list.

This preserves the meaning of that list as "what the operator was actually shown live."

## Error Handling

The review command should keep the same error behavior for:

- missing journal file
- invalid JSONL lines

Suppressed-context records must be parsed defensively:

- ignore malformed non-dict payloads
- treat unknown record types conservatively

Empty-but-valid cases should continue to return a safe review snapshot.

## File Plan

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - add suppressed-context journaling helpers
  - extend journal loading and review snapshot building
  - extend review rendering with suppression summary fields
- Modify: `tests/test_live_market_snapshot.py`
  - add focused tests for suppressed-context journaling, filtering, snapshot building, and review rendering
- Modify: `src/synthetic_trader/cli.py`
  - only if needed to clarify help text

## Testing Strategy

Add focused tests for:

1. suppressed-context journaling
   - a materially different context change blocked by cooldown writes a suppressed record
2. ignored non-material churn
   - unchanged or non-material context does not create suppressed records
3. review snapshot parsing
   - mixed journals with emitted alerts and suppressed records parse correctly
4. review filtering
   - symbol filter applies to suppression counts and latest withheld preview
   - `valid-only` leaves suppression count at zero
5. review rendering
   - suppression summary fields print clearly
   - recent emitted alerts remain unchanged
6. compatibility
   - existing emitted alert rendering and review behavior stay intact

## Success Criteria

This design is successful when:

- `live-watch` stays as quiet as it is today
- `live-watch-review` shows whether context suppression occurred
- the operator can see the latest withheld context picture quickly
- recent emitted alerts remain clearly separated from suppressed records
- the feature remains read-only and uses one journal file
