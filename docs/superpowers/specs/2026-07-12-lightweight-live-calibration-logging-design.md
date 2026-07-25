# Lightweight Live Calibration Logging For R_75 And R_100

## Purpose

This design adds a lightweight live-calibration evidence layer for both `R_75` and `R_100`.

The current engine has improved materially:

1. intraday execution geometry is now structure-led
2. both symbols use a shared pattern-aware execution engine
3. symbol-specific overrides now exist for trigger strength, travel budget, and late-extension rejection

The remaining weakness is not architecture. It is evidence.

We still need a fast way to answer:

1. which trigger types are actually paying in the next hour
2. whether `R_75` and `R_100` travel budgets are too wide or too tight
3. whether current rejection rules are correctly filtering bad setups or discarding good ones

This design solves that with lightweight logging, not a research platform.

## Core Requirement

The system must capture live call decisions and score their next-hour outcomes for `R_75` and `R_100` with minimal operational overhead.

That means:

1. append-only storage
2. no database
3. enough fields to evaluate trigger quality and target reachability
4. enough outcome tracking to inform the next calibration pass

## Current Problem

### 1. Live Probes Are Ephemeral

Right now, a route probe tells us what the engine thinks *at that moment*, but the evidence disappears unless we manually copy it.

That means:

1. we cannot accumulate a reliable sample of live behavior
2. we cannot compare “good rejection” versus “missed opportunity” over time

### 2. Calibration Still Leans On Fixtures

The current tuning is test-driven and structurally sound, but still relies heavily on curated fixtures.

That means:

1. we can verify logic
2. we cannot yet calibrate against repeated real next-hour outcomes

### 3. Outcome Quality Is Not Recorded In A Compact Form

We do not yet have a single compact record that answers:

1. what the engine saw
2. what it published
3. what price actually did in the next `30m-1h`

## Scope

This design covers:

1. lightweight append-only call logging for `R_75` and `R_100`
2. compact outcome-evaluation records after the next `30m-1h`
3. a CLI path to score unresolved records once enough time has passed
4. summary metrics by symbol and trigger type

## Non-Goals

This design does not cover:

1. a replay dataset
2. a database
3. candle-window archival for full offline simulation
4. automated tuning or auto-optimization
5. broker execution changes

## Approaches Considered

### Option 1: Full Replay Dataset

Pros:

1. maximum research flexibility
2. richest future analysis

Cons:

1. too slow for the immediate need
2. higher storage and implementation cost

### Option 2: Lightweight Logging

Pros:

1. fastest to ship
2. enough evidence for real calibration decisions
3. low operational complexity

Cons:

1. less detail than a replay dataset
2. some questions will still require future expansion

### Option 3: Hybrid Logging With Replay Hooks

Pros:

1. future-friendly
2. still lighter than full replay

Cons:

1. more upfront complexity than necessary right now

## Selected Approach

Use Option 2.

The right next step is lightweight logging that gives us live evidence quickly, not building a research warehouse before we have enough data.

## Data Model

Use append-only JSONL files.

Recommended paths:

1. `journals/live_calibration_calls.jsonl`
2. `journals/live_calibration_outcomes.jsonl`

### Call Record

Each live call record should include:

1. `recorded_at`
2. `symbol`
3. `generated_at`
4. `call`
5. `trade_status`
6. `guardian_state`
7. `direction_bias`
8. `trigger_type`
9. `confidence`
10. `entry`
11. `execution_stop`
12. `primary_target`
13. `thesis_invalidation`
14. `hold_horizon_minutes`
15. `why`
16. `wait_for`
17. `decision_summary`
18. `current_close`
19. `model_version`

For non-actionable or `forming` records, geometry fields may be `null`. That is acceptable and should still be logged.

### Outcome Record

Each outcome record should reference one call record and include:

1. `symbol`
2. `generated_at`
3. `evaluation_time`
4. `outcome_window_minutes`
5. `entry`
6. `execution_stop`
7. `primary_target`
8. `max_favorable_excursion`
9. `max_adverse_excursion`
10. `target_reached`
11. `stop_reached`
12. `outcome_label`

Allowed `outcome_label` values:

1. `target_hit`
2. `stop_hit`
3. `neither_reached`
4. `forming_remained_correct`
5. `rejected_but_price_ran`

## Logging Rules

### What To Log

Log every route-level live call for:

1. `R_75`
2. `R_100`

This includes:

1. valid actionable calls
2. `stand_aside` calls
3. `forming` states

We need evidence for both accepted and rejected scenarios.

### When To Log

Log the call record at the moment the live route or snapshot is generated.

Log the outcome record only after enough time has passed to judge the next-hour result.

## Outcome Evaluation

Use a simple next-hour scoring model.

### Evaluation Window

Default:

1. start from `generated_at`
2. evaluate over `hold_horizon_minutes`, or fallback to `60`

### Evaluation Rules

For actionable plans:

1. `target_hit` if price reaches `primary_target` first
2. `stop_hit` if price reaches `execution_stop` first
3. `neither_reached` if neither is touched in the window

For non-actionable or forming calls:

1. `forming_remained_correct` if price never produced a clean next-hour move that would have justified the rejected call
2. `rejected_but_price_ran` if price would have produced a meaningful move despite rejection

This is intentionally lightweight and directional, not perfect.

## CLI Shape

Add a small CLI surface for two commands:

1. `log-live-call`
2. `score-live-calibration`

### `log-live-call`

Inputs:

1. symbol
2. live payload JSON or snapshot source
3. output path

Behavior:

1. normalize the payload
2. append a call record to JSONL

### `score-live-calibration`

Inputs:

1. call journal path
2. output journal path
3. symbol filter optional
4. evaluation window optional

Behavior:

1. find records old enough to score
2. fetch enough tick history to evaluate the outcome window
3. compute excursions and outcome label
4. append scored outcomes for records not already evaluated

## Summary Metrics

The scorer should print a compact summary by:

1. symbol
2. trigger type
3. trade status

Useful metrics:

1. count
2. target-hit rate
3. stop-hit rate
4. neither rate
5. average max favorable excursion
6. average max adverse excursion

This is enough to guide the next manual calibration pass.

## Integration Shape

The logging path should stay lightweight and isolated.

Recommended structure:

1. `src/synthetic_trader/live/calibration_logger.py`
2. `src/synthetic_trader/live/calibration_scorer.py`

The live route or CLI path should call into these helpers rather than embedding file I/O directly in `market_snapshot.py`.

## Testing Strategy

Add tests for:

1. call record serialization for actionable `R_75`
2. call record serialization for forming `R_100`
3. outcome scoring when target is hit first
4. outcome scoring when stop is hit first
5. outcome scoring for rejected-but-price-ran
6. summary aggregation by symbol and trigger type

## Acceptance Criteria

This design is complete when:

1. live calls for both `R_75` and `R_100` can be appended to JSONL
2. scored outcomes can be generated after the next-hour window
3. both accepted and rejected calls can be analyzed
4. the CLI produces compact metrics useful for manual calibration
5. the system gains real evidence without requiring a replay platform

## Recommendation

Proceed with lightweight live calibration logging first.

Do not build a replay platform yet.

Get a fast evidence loop into place, then use real `R_75` and `R_100` outcomes to drive the next tuning decisions.
