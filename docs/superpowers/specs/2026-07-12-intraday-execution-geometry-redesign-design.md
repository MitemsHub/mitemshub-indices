# Intraday Execution Geometry Redesign

## Purpose

This design corrects the current mismatch between:

1. a top-down directional engine built from `4H` and `1H`
2. an operator expectation of realistic `30m-1h` trade plans

The current system can now infer direction more credibly than before, but it still constructs execution levels like a swing trade. That is why some `R_100` calls produce targets that are mathematically valid yet operationally unrealistic for the intended holding window.

This redesign keeps the higher-timeframe bias architecture, but rewrites how entry, stop, invalidation, and target are built so the published plan matches a trader who wants a realistic next `30m-1h` outcome.

## Core Requirement

The platform must stop mixing:

1. higher-timeframe thesis invalidation
2. lower-timeframe execution invalidation
3. fixed reward-multiple projection

For `R_75` and `R_100`, the engine must:

1. use `4H` and `1H` to answer where price is most likely heading
2. use `5m` and `1m` to answer how to enter and where the idea fails locally
3. set the primary target to the nearest realistic objective that can be reached within the next `30m-1h`
4. reject trades whose reachable target does not justify the local execution risk

## Current Problem

The live output is still structurally wrong for an intraday operator.

### 1. Entry Is Too Broad

The current setup builder uses the recent `1H` zone as the execution entry range.

That causes:

1. entries to be too far from the immediate trigger
2. plans to look vague instead of deliberate
3. execution to feel late or already missed

### 2. Stop Is Too Deep

The current decision engine uses higher-timeframe invalidation as the actual stop.

That causes:

1. execution risk to be much larger than the trade horizon justifies
2. valid intraday ideas to look unusable
3. targets to become inflated because risk distance is inflated

### 3. Target Is Projected, Not Estimated

The current target is still derived from fixed reward-multiple expansion off the oversized stop.

That causes:

1. unrealistic take-profit levels
2. weak alignment with what price can plausibly travel in the next `30m-1h`
3. operator distrust because the published call does not match actual chart behavior

## Scope

This design covers:

1. intraday trade construction for `R_75` and `R_100`
2. separation of thesis invalidation from execution stop
3. `5m` trigger and stop derivation
4. `1m` timing and failure-guard logic
5. reachable-target estimation for the next `30m-1h`
6. UI contract changes for primary and extended targets
7. regression tests for target realism and execution geometry

## Non-Goals

This design does not cover:

1. broker execution automation changes
2. portfolio sizing redesign
3. full probabilistic forecasting of exact future price prints
4. replacing the top-down bias model introduced earlier

## Approaches Considered

### Option 1: Only Tighten Reward/Risk Multiples

Pros:

1. minimal code change
2. fast to ship

Cons:

1. still uses the wrong stop source
2. still does not model reachable targets
3. only shrinks numbers cosmetically

### Option 2: Keep Higher-Timeframe Stop But Cap Target Distance

Pros:

1. partially reduces unrealistic targets
2. preserves more of the current execution flow

Cons:

1. keeps execution risk too large
2. still mixes swing invalidation with intraday execution
3. still produces poor operator instructions

### Option 3: Separate Thesis, Execution, And Objective Estimation

Pros:

1. matches the requested `30m-1h` trading behavior
2. preserves the good part of the top-down engine
3. produces realistic entry, stop, and target geometry
4. creates cleaner trader-facing instructions

Cons:

1. requires a deeper redesign of execution packaging
2. touches both Python and app-facing contract behavior

## Selected Approach

Use Option 3.

The engine should keep top-down directional inference, but trade construction must become explicitly intraday. The system should no longer publish a swing-sized stop and then pretend the resulting projected target is useful for the next hour.

## Timeframe Responsibilities

### `4H`

Use `4H` only for:

1. dominant bias
2. high-value structural zones
3. thesis invalidation

It must not define the actual execution stop for a `30m-1h` plan.

### `1H`

Use `1H` only for:

1. setup state
2. pullback or continuation context
3. active trade-side preference

It may define the preferred execution region, but not the exact entry trigger.

### `5m`

Use `5m` for:

1. real trigger
2. local stop placement
3. first reachable liquidity objective
4. execution reward/risk screening

This becomes the main source of entry and stop geometry.

### `1m`

Use `1m` for:

1. timing refinement
2. failed-break detection
3. post-trigger deterioration monitoring

It must not override `4H` or `1H` direction.

## Decision Architecture

The engine should be split into three distinct layers after confirmation:

### 1. Thesis Layer

Source:

1. `4H` bias
2. `1H` setup
3. `15m` confirmation

Output:

1. trade direction
2. thesis reason
3. thesis invalidation level

This layer answers whether the idea is valid in principle.

### 2. Execution Layer

Source:

1. `5m` trigger structure
2. recent `5m` swing points
3. optional `1m` micro-confirmation

Output:

1. exact entry trigger
2. execution stop
3. local invalidates-if text

This layer answers how to participate without using an oversized stop.

### 3. Objective Layer

Source:

1. nearby `5m` and `15m` swing liquidity
2. recent travel statistics for the same symbol
3. horizon budget for the next `30m-1h`

Output:

1. primary target
2. extended target if justified
3. hold expectation

This layer answers what price can realistically reach soon.

## Execution Geometry Rules

### Entry

The entry must come from `5m`, not directly from the `1H` zone edge.

Allowed trigger types:

1. `5m` continuation close through trigger level
2. `5m` reclaim of a pullback level
3. `5m` break-and-retest hold

The published entry should be:

1. a trigger price when execution is not yet printed
2. a narrow executable band only when a retest zone is genuinely present

### Stop

The execution stop must sit beyond the last valid `5m` swing or retest failure point.

It must not default to the full `4H` thesis invalidation.

The system should keep two different invalidation concepts:

1. `thesis_invalidation`
   - the higher-timeframe level that breaks the original directional idea
2. `execution_stop`
   - the local level that proves the entry attempt failed

For a published `30m-1h` trade, the stop shown in the main panel must be `execution_stop`.

### Primary Target

The primary target must be the nearest realistic objective for the next `30m-1h`.

Candidate target sources:

1. nearest opposing `5m` swing
2. nearest `15m` liquidity shelf
3. expected one-hour travel budget for the symbol under current regime

The chosen primary target should be the earliest level that is both:

1. technically meaningful
2. realistically reachable within the target horizon

### Extended Target

An extended target may be shown only if:

1. the primary target is already acceptable
2. the trend has enough continuation structure
3. the UI clearly marks it as secondary

The extended target must never replace the primary operator target.

## Reachable-Target Model

The engine must stop assuming that any `2R` target is useful.

Instead, it should estimate a realistic travel budget from:

1. recent `5m` impulse sizes
2. recent `30m` realized move span
3. current regime state

Example policy:

1. estimate expected travel over the next `6-12` `5m` candles
2. clamp the primary target to that realistic travel envelope
3. reject the trade if the clamped target cannot produce acceptable reward/risk against the local stop

This design is not trying to predict an exact future print. It is trying to publish a realistic price objective for the intended intraday horizon.

## Signal Quality Rules

The engine should reject a trade if any of the following are true:

1. `4H` and `1H` do not agree on direction
2. `15m` confirmation is not active
3. `5m` trigger has not formed
4. execution stop is too wide for the expected one-hour travel
5. nearest reachable objective does not justify the stop

This means a valid top-down idea can still be rejected as a bad intraday execution.

That is intended.

## UI Contract Changes

The response payload should separate:

1. `entry`
2. `execution_stop`
3. `thesis_invalidation`
4. `primary_target`
5. `extended_target`
6. `hold_horizon_minutes`

The operator-facing text should change from broad statements to actionable instructions such as:

1. `Buy only on a 5m close above X`
2. `Exit the attempt if 5m closes back below Y`
3. `Take first profit near Z within the next hour`

The UI should stop presenting a single oversized target as if it is the main expected outcome.

## Testing Strategy

Add or update tests to cover:

1. confirmed higher-timeframe bias with overwide local stop gets rejected
2. realistic nearby `5m` target is chosen over a distant projected `2R`
3. `R_100` uses execution stop rather than higher-timeframe invalidation for the displayed trade plan
4. UI contract preserves both primary and extended target semantics
5. operator text reflects the `30m-1h` horizon rather than swing-trade language

## Acceptance Criteria

The redesign is complete when:

1. `R_75` and `R_100` still infer direction from `4H` and `1H`
2. published entry and stop are built from `5m` execution structure
3. the main target shown in the UI is realistically reachable within `30m-1h`
4. the engine rejects bloated trade geometry instead of publishing fantasy targets
5. the operator panel clearly distinguishes local execution failure from higher-timeframe thesis failure

## Recommendation

Proceed with an intraday execution rewrite, not another threshold tweak.

The correct path now is:

1. keep top-down directional logic
2. rewrite execution geometry around `5m` and `1m`
3. introduce reachable-target estimation
4. publish trader-facing plans that match the promised horizon
