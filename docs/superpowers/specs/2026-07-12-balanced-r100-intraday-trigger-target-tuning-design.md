# Balanced R_100 Intraday Trigger And Target Tuning

## Purpose

This design refines the newly introduced intraday execution layer for `R_100`.

The current execution rewrite fixed the major structural problem:

1. it stopped using higher-timeframe invalidation as the execution stop
2. it stopped publishing obviously bloated swing-style targets for a `30m-1h` call

That fix was necessary, but the current builder is still intentionally simple. It now needs a second pass so `R_100` can:

1. recognize better `5m` trigger quality
2. choose a more realistic local stop source
3. set a stronger next-hour objective without loosening quality recklessly

This design focuses on balanced tuning, not aggressive activation.

## Core Requirement

For `R_100`, the intraday builder must become more selective in *how* it enters, while becoming more realistic in *what* it targets.

That means:

1. do not relax the quality gate just to increase call count
2. do not keep using a single blunt `latest high or low` trigger rule
3. do not keep using a single blunt average-range target rule
4. do improve survival rate for genuinely tradable next-hour setups

## Current Problem

The current builder is now directionally safer, but still too primitive for good `R_100` intraday execution.

### 1. Trigger Typing Is Too Crude

The current builder only uses:

1. latest `5m` high for buys
2. latest `5m` low for sells

That causes:

1. weak distinction between clean continuation and noisy local expansion
2. missed opportunities where a reclaim or break-retest is valid
3. overreliance on the last candle instead of the actual trigger pattern

### 2. Stop Selection Is Too Uniform

The current builder always uses a small recent swing window.

That causes:

1. some stops to be too blunt for reclaim setups
2. some continuation setups to use the wrong failure point
3. execution risk to vary inconsistently by pattern type

### 3. Target Estimation Is Too Mechanical

The current builder uses average recent `5m` range as the main travel estimate.

That causes:

1. targets to ignore nearby `5m` or `15m` liquidity
2. insufficient distinction between trend continuation and late-stage extension
3. good setups to be rejected when the target model understates reachable movement

## Scope

This design covers:

1. `R_100` intraday trigger classification
2. pattern-specific execution stop selection
3. balanced next-hour target estimation
4. quality gating for realistic next-hour reward
5. focused Python and app-verification fixtures tied to `R_100`

## Non-Goals

This design does not cover:

1. full retraining of the direction model
2. changing `4H`, `1H`, or `15m` thesis logic
3. rewriting `R_75` behavior unless a shared helper naturally benefits both symbols
4. turning the engine into a high-frequency trigger machine

## Approaches Considered

### Option 1: Loosen The Existing Builder

Pros:

1. fastest change
2. increases call frequency

Cons:

1. weakens quality discipline
2. likely reintroduces superficial entries
3. does not actually improve trigger intelligence

### Option 2: Keep The Builder But Raise Travel Estimates

Pros:

1. simple change
2. may rescue some otherwise rejected setups

Cons:

1. still uses weak trigger typing
2. risks inflating targets again
3. treats the symptom, not the cause

### Option 3: Add Balanced Pattern-Aware Execution Logic

Pros:

1. improves real trigger quality without broad loosening
2. aligns stop placement with actual setup type
3. improves next-hour target realism using nearby liquidity and travel budget
4. directly addresses the current `R_100` weakness

Cons:

1. requires more fixture design and testing
2. adds logic inside the intraday builder

## Selected Approach

Use Option 3.

The correct next step is a pattern-aware intraday builder that stays disciplined while becoming less blunt.

## Balanced Trigger Model

The builder should classify the latest `5m` condition into one of three allowed trigger types:

1. `continuation_close`
2. `reclaim_pullback`
3. `break_retest_hold`

### `continuation_close`

Use when:

1. the latest `5m` candle closes through the local continuation trigger
2. the body is meaningfully directional
3. the close is near the candle extreme rather than a weak mid-range drift

Preferred stop source:

1. beneath the continuation candle low for buys
2. above the continuation candle high for sells
3. optionally widened to the nearest micro-swing only if that failure point is cleaner

### `reclaim_pullback`

Use when:

1. a prior pullback traded back into the setup zone
2. price reclaimed the trigger shelf
3. the latest `5m` close confirms the reclaim

Preferred stop source:

1. beneath the reclaimed shelf for buys
2. above the reclaimed shelf for sells

### `break_retest_hold`

Use when:

1. a local level is broken
2. price retests it without full failure
3. the hold is confirmed by the next `5m` close

Preferred stop source:

1. beyond the retest failure point
2. not beyond an unrelated deeper swing unless necessary

## Trigger Quality Filter

Each trigger type should produce a quality score from:

1. body-to-range efficiency
2. close location within the candle
3. local follow-through structure
4. distance from the most recent `5m` swing failure point

The engine should reject a trigger if:

1. the close is too weak
2. the pattern is late and overextended
3. the trigger candle is too noisy relative to the expected one-hour travel

## Stop Selection Rules

The stop must remain local, but it should be pattern-aware.

Priority order:

1. trigger failure point
2. reclaimed shelf or retest shelf
3. nearest valid `5m` swing beyond the trigger

The builder must not use a single fixed recent-window rule when a better pattern-specific failure point exists.

## Balanced Target Model

The primary target should be chosen from the earliest realistic next-hour objective among:

1. nearest opposing `5m` swing
2. nearest `15m` liquidity shelf
3. symbol-specific travel budget for the next `30m-1h`

The final primary target should be:

1. technically meaningful
2. reachable within the next hour under current structure
3. not farther than the balanced travel budget unless continuation structure is unusually strong

## Extended Target Logic

An extended target may be added only when:

1. the primary target already supports the trade cleanly
2. continuation quality is high
3. the move is not already late-stage

The extended target should remain informational, not the main published expectation.

## Quality Gate

The engine should publish an `R_100` intraday plan only when:

1. top-down thesis is already confirmed
2. one of the allowed trigger types is present
3. execution stop is pattern-valid and local
4. primary target is reachable within the next hour
5. primary reward against local risk meets the balanced minimum

This keeps the engine disciplined while making it less blunt.

## Implementation Shape

The likely code path should stay centered in `intraday_execution_builder.py`, but split into focused helpers such as:

1. trigger classification
2. stop selection
3. target candidate collection
4. travel-budget clamp
5. final quality decision

This keeps the builder understandable instead of growing into one long opaque function.

## Testing Strategy

Add focused `R_100` fixtures for:

1. clean continuation close that should pass
2. clean reclaim after pullback that should pass
3. break-retest hold that should pass
4. overextended late continuation that should fail
5. weak close with noisy candle body that should fail
6. target too near to pay for local stop that should fail

The decision-engine tests should verify:

1. accepted `R_100` patterns now survive with realistic next-hour targets
2. weak `R_100` patterns still get rejected

The live snapshot tests should verify:

1. `wait_for` and `invalidates_if` language remain pattern-aware and intraday
2. the main target remains the balanced primary target, not an inflated runner

## Acceptance Criteria

This tuning is complete when:

1. `R_100` valid intraday plans use explicit trigger types rather than blunt latest-candle rules
2. stop selection matches the actual pattern failure point
3. primary targets are more realistic for the next `30m-1h`
4. the engine still rejects weak or late-stage setups
5. the system produces better `R_100` intraday plans without reintroducing fantasy targets

## Recommendation

Proceed with balanced, pattern-aware `R_100` execution tuning.

Do not loosen the engine broadly.

Improve:

1. trigger intelligence
2. stop-source precision
3. target realism

Keep:

1. the current top-down thesis discipline
2. the current rejection of bloated geometry
