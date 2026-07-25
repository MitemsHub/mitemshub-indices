# Real Tick-History Scoring For Live Calibration

## Purpose

This design upgrades the lightweight live-calibration workflow from placeholder-backed scoring to real market-backed outcome evaluation.

The current workflow already works structurally:

1. live calls can be logged
2. outcome records can be generated
3. CLI commands exist for logging and scoring
4. summary metrics can be computed

The remaining gap is the market-data source used by the scorer.

Right now, the CLI scoring flow still depends on injected placeholder price sequences. That is sufficient for unit tests, but not sufficient for real calibration.

This design closes that gap by reusing the existing Deriv tick-history infrastructure already used in the live snapshot pipeline.

## Core Requirement

The live calibration scorer must fetch real tick history for each eligible call record and score the next-hour outcome from actual market prices.

That means:

1. no second market-data stack
2. reuse the existing Deriv client and credential path
3. avoid crashing the whole batch when one record cannot be scored
4. preserve the current compact JSONL workflow

## Current Problem

### 1. Outcome Scoring Is Structurally Real But Data-Source Fake

The scorer logic is now implemented, but the CLI currently injects an empty placeholder price lookup.

That means:

1. the pipeline runs
2. the scores are not yet market-backed

### 2. Live Evidence Loop Is Still Incomplete

Without real tick-history scoring, the calibration journals cannot answer the most important question:

1. what price actually did after the call

### 3. Error Handling Must Be Narrow

Tick-history requests can fail for transport reasons or partial data reasons.

That means:

1. one bad record must not break a whole scoring run
2. the scorer must skip safely and report what it could not score

## Scope

This design covers:

1. real tick-history lookup for calibration scoring
2. async helper(s) inside the scorer module
3. CLI integration for market-backed batch scoring
4. resilient per-record failure handling
5. tests for real-scoring control flow using mocked history fetches

## Non-Goals

This design does not cover:

1. a replay dataset
2. a database
3. model retraining
4. full candle-window archival
5. automatic calibration updates

## Approaches Considered

### Option 1: Keep Placeholder Lookup

Pros:

1. simplest code path
2. fully deterministic

Cons:

1. useless for real calibration
2. not acceptable as the final system

### Option 2: Reuse Existing Deriv Tick-History Client

Pros:

1. fastest path to real evidence
2. consistent with the live snapshot path
3. avoids new infrastructure

Cons:

1. requires async integration in the scorer path
2. needs careful failure handling

### Option 3: Build A Separate Scoring Data Client

Pros:

1. full freedom in scorer design

Cons:

1. duplicates existing transport logic
2. increases maintenance and failure surface

## Selected Approach

Use Option 2.

The scorer should reuse the current Deriv tick-history client and credential flow instead of building a second market-data stack.

## Data Source

Use:

1. `DerivWebSocketClient`
2. existing Deriv credentials from environment
3. `ticks_history(...)`

The scorer should fetch enough ticks to cover the outcome window from `generated_at` through `generated_at + hold_horizon_minutes`.

## Scoring Flow

### 1. Load Candidate Records

Continue using the existing JSONL call journal.

Keep the current filters:

1. skip already-scored records
2. skip records too recent for evaluation
3. optional symbol filter

### 2. Fetch Outcome Prices

For each eligible record:

1. fetch tick history beginning at or immediately after `generated_at`
2. collect enough ticks to cover the outcome window
3. convert ticks to an ordered price list

If no usable history is returned:

1. skip the record
2. count the failure
3. continue the batch

### 3. Score Outcome

Use the existing scoring rules:

1. `target_hit`
2. `stop_hit`
3. `neither_reached`
4. `forming_remained_correct`
5. `rejected_but_price_ran`

The scoring logic itself should stay compact and deterministic. The only change is that its input prices now come from real history.

## Integration Shape

Keep the real-scoring integration inside `calibration_scorer.py`.

Recommended additions:

1. async tick-history fetch helper
2. async per-record scoring helper
3. batch wrapper that returns:
   - written count
   - skipped count
   - failed count

The CLI should call a synchronous wrapper that runs the async scorer with `asyncio.run(...)`.

## Time Window Rules

Default outcome window:

1. `hold_horizon_minutes`
2. fallback to `60`

Price history should be scored from:

1. `generated_at`
2. through the end of the evaluation window

The design does not require perfect tick-for-tick reconstruction. It requires a faithful enough price path to judge whether target or stop was hit first, or whether a rejected call still ran.

## Failure Handling

If a record cannot be scored because of:

1. transport failure
2. malformed timestamp
3. empty tick response

then:

1. do not append an outcome
2. increment a failure counter
3. continue the rest of the batch

The CLI should print compact counters such as:

1. `scored_records=<n>`
2. `failed_records=<n>`
3. `skipped_records=<n>`

## CLI Behavior

The `score-live-calibration` command should stop using the placeholder `lambda record: []`.

Instead it should:

1. run the async real-scoring wrapper
2. print compact result counters
3. keep the current journal/output/symbol/window arguments

No new top-level command is required.

## Testing Strategy

Add tests for:

1. scoring a valid call from fetched prices where target is hit first
2. scoring a valid call from fetched prices where stop is hit first
3. skipping a record that is not old enough
4. skipping a record when history fetch fails
5. CLI output showing scored, skipped, and failed counts

Use mocked tick-history fetches in tests. Do not make network calls in test runs.

## Acceptance Criteria

This design is complete when:

1. `score-live-calibration` scores outcomes from real tick history
2. the scorer reuses the existing Deriv client path
3. one failed record does not break the whole scoring run
4. outcome journals are populated from real market data
5. the CLI prints useful counters for scoring progress

## Recommendation

Proceed with real tick-history scoring now.

The lightweight evidence loop already exists. This step turns it into a real calibration system instead of a scaffold.
