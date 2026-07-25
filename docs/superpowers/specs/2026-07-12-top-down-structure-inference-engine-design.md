# Top-Down Structure Inference Engine Design

## Purpose

This design replaces the current short-horizon synthetic-indices decision style with a higher-timeframe-led structure trader for `R_75` and `R_100`.

The operator requirement is clear:

1. the engine must infer where the market is likely heading from what price has already done
2. the system must stop behaving like a tick-reactive scalp bot
3. entries, stops, invalidation, and targets must come from structure and liquidity, not just the latest close
4. higher timeframes must control direction, while lower timeframes only confirm and refine execution

## Core Requirement

The platform must behave like a disciplined top-down technical analyst.

That means the engine must:

1. define directional bias from higher-timeframe structure
2. derive setup context from the next lower timeframe
3. require lower-timeframe confirmation before publishing a real trade
4. place stop loss beyond meaningful invalidation, not inside local noise
5. target structural objectives instead of tiny local ATR hops
6. expose its internal checks and balances through trader-useful reasoning

## Current Problem

The current system remains too close to the tape.

### 1. Timeframe Model Is Too Small

The current runtime profile is effectively centered on `1m` execution and `5m` context.

That causes:

1. directional bias to be too sensitive to local noise
2. trade plans to stay too close to the current candle
3. stop and target placement to feel marginal and short-lived

### 2. Execution Is Close-Anchored

The current decision engine still builds trades around the latest close, then scales stop and target from recent ATR.

That causes:

1. entries to appear reactive rather than planned
2. stops to sit too close to noise
3. targets to reflect short-horizon movement rather than structural objectives

### 3. Structure Is Present But Underused

The codebase already extracts regime and market-structure features, but that information is not yet the dominant source of trade construction.

That causes:

1. structure to act like a score input instead of the trade map
2. higher-timeframe context to be too weak in the final decision
3. invalidation logic to be less meaningful than it should be

## Scope

This design covers:

1. the new multi-timeframe analysis stack
2. higher-timeframe bias inference
3. structure-led setup formation
4. lower-timeframe confirmation and execution logic
5. structure-based stop, invalidation, and target generation
6. a longer structural holding horizon
7. regression tests for directional inference, setup filtering, and trade-plan generation

## Non-Goals

This design does not cover:

1. broker-side automation changes
2. portfolio-level execution optimization
3. social-media or external sentiment ingestion at runtime
4. changing the operator app into a discretionary charting terminal

## Research Direction

The redesign should follow standard top-down multi-timeframe practice:

1. higher timeframes define trend, structure, and important price zones
2. mid timeframes define whether the market is building a continuation or reversal setup
3. lower timeframes confirm entry timing and precision
4. the lowest timeframe should never be the primary source of directional bias

This means the earlier emphasis on `1m` and `5m` was too short for the requested trader style.

## Approaches Considered

### Option 1: Keep The Existing Engine And Only Widen Stops

Pros:

1. smallest change
2. quick to implement

Cons:

1. still close-anchored
2. still not structure-led
3. still uses the wrong trader style

### Option 2: Add Structure Levels On Top Of The Existing Short Stack

Pros:

1. improves stop and target quality
2. keeps more of the current architecture

Cons:

1. still lets short-horizon scoring dominate direction
2. only partially solves the operator complaint

### Option 3: Replace The Trading Style With A Top-Down Structure Engine

Pros:

1. matches the requested trader behavior
2. makes higher timeframes the real source of market bias
3. lets lower timeframes act as confirmation rather than story invention
4. gives a stronger basis for meaningful stops and targets

Cons:

1. largest redesign
2. requires changes across feature extraction, decision packaging, and tests

## Selected Approach

Use Option 3: `top-down structure inference engine`.

This is the only approach that directly changes the trader style rather than cosmetically improving the old one.

## Timeframe Stack

The new stack should be:

1. `4H` for dominant bias and structural map
2. `1H` for active setup context
3. `15m` for confirmation
4. `5m` for execution refinement
5. `1m` for optional micro-monitoring only

### Timeframe Responsibilities

#### `4H`

The `4H` layer should define:

1. major swing highs and lows
2. structural trend or structural range
3. key liquidity shelves
4. major break-of-structure and sweep events
5. dominant invalidation zone

#### `1H`

The `1H` layer should define:

1. whether price is pulling back, continuing, or attempting reversal inside the `4H` map
2. whether a setup is developing near a meaningful structural zone
3. the nearer invalidation shelf for the active idea

#### `15m`

The `15m` layer should define:

1. whether the `1H` setup is actually taking shape
2. whether market intent is confirming through reclaim, rejection, continuation, or breakdown
3. whether the setup is tradable yet or still only contextual

#### `5m`

The `5m` layer should define:

1. the precise trigger zone
2. the refined entry range
3. the immediate micro confirmation used for execution timing

#### `1m`

The `1m` layer should not control market direction.

It may be used for:

1. live freshness checks
2. short-horizon deterioration monitoring
3. optional operator review details

## Decision Architecture

The engine should be broken into four clear layers.

### 1. Higher-Timeframe Bias Builder

Input:

1. `4H` candles
2. `4H` regime
3. `4H` swings, liquidity, and structure features

Output:

1. `bullish`, `bearish`, or `neutral` bias
2. dominant structural invalidation zone
3. primary directional thesis

### 2. Setup Builder

Input:

1. higher-timeframe bias package
2. `1H` candles and structure

Output:

1. continuation setup
2. pullback setup
3. reversal attempt
4. no setup

### 3. Confirmation Builder

Input:

1. setup package
2. `15m` price behavior

Output:

1. confirmed
2. still forming
3. rejected

If higher-timeframe bias and confirmation disagree, the engine must not publish a trade.

### 4. Execution Builder

Input:

1. confirmed setup package
2. `5m` trigger behavior

Output:

1. entry zone
2. stop zone
3. invalidates-if
4. target one
5. extended target
6. holding horizon

## Structure-Led Trade Construction

### Entry

Entry should come from one of:

1. retest of a reclaimed structural zone
2. breakdown retest into resistance
3. continuation after a confirmed sweep and displacement
4. confirmation close through the trigger shelf

Entry must not default to the latest candle close unless that close is itself the structural trigger.

### Stop Loss

Stop loss should be placed beyond:

1. the confirming swing high or low
2. the failed reclaim or failed rejection shelf
3. the higher-timeframe invalidation boundary when required

Stop loss must not be placed inside obvious short-term noise.

### Invalidation

Invalidation should state what market behavior breaks the trade thesis.

Examples:

1. bullish reclaim fails and price closes back below the defended shelf
2. bearish rejection fails and price reclaims above the last lower-high zone
3. confirmation structure breaks in the opposite direction

### Targets

Targets should come from structure and liquidity:

1. next internal liquidity objective
2. next opposing swing zone
3. extended structural expansion target

The trade package should support at least:

1. `target_one`
2. `target_extended`

## Holding Horizon

The current short fixed horizon is too small for this trader style.

The new holding horizon should be inferred from:

1. timeframe stack
2. structural distance to target
3. setup type
4. regime persistence

This means the horizon should be longer for `4H`-supported continuation setups than for short-range tactical setups.

## Internal Checks And Balances

The engine should only publish a trade if all of the following are coherent:

1. `4H` bias exists
2. `1H` setup matches the `4H` bias
3. `15m` confirms intent
4. `5m` gives an acceptable trigger
5. invalidation is structurally clear
6. target is structurally meaningful
7. reward relative to structural invalidation is acceptable

If some but not all of these are true, the engine should publish context, not a trade.

## Output Contract

Every published non-context trade should include:

1. timeframe-aligned directional bias
2. setup type
3. entry zone
4. stop zone
5. invalidates-if
6. target one
7. extended target
8. confidence
9. structural rationale
10. confirmation rationale
11. hold horizon estimate

## State Lifecycle

The public lifecycle remains:

1. `forming`
2. `actionable`
3. `confirmed`
4. `failing`
5. `cancelled`

### Interpretation

1. `forming`
   - higher-timeframe story may exist, but confirmation is incomplete
2. `actionable`
   - structure and confirmation are aligned enough to publish a cautious plan
3. `confirmed`
   - follow-through is strong and the setup is fully established
4. `failing`
   - the existing plan is losing validity
5. `cancelled`
   - the structural thesis is broken

## Implementation Slices

### Slice 1: Timeframe Expansion

1. extend feature and candle pipelines to support `4H`, `1H`, `15m`, and `5m`
2. keep `1m` optional for live monitoring only

### Slice 2: Bias And Setup Layers

1. add a dedicated higher-timeframe bias builder
2. add a setup builder that maps `1H` structure into concrete setup classes

### Slice 3: Confirmation And Execution Layers

1. add `15m` confirmation logic
2. add `5m` trigger and entry refinement logic

### Slice 4: Structure-Led Trade Plan

1. replace close-anchored entry
2. replace ATR-only stop and target construction
3. add invalidation and multi-target output

### Slice 5: Runtime And Presentation

1. upgrade live snapshot and watcher payloads
2. expose structural rationale in operator-facing output
3. preserve actionable vs confirmed discipline

### Slice 6: Regression And Benchmarking

1. tests for higher-timeframe bias selection
2. tests for setup rejection when lower frames disagree
3. tests for structure-led stop and target generation
4. tests for longer-horizon trade plans
5. runtime verification for `R_75` and `R_100`

## Acceptance Criteria

This redesign is successful when:

1. the engine no longer depends on `1m` or `5m` to decide market direction
2. directional bias is demonstrably driven by `4H` and `1H`
3. entries, stops, and targets are structure-led
4. published plans are less marginal and less noise-sensitive
5. runtime outputs for `R_75` and `R_100` show trader-like structural reasoning rather than short tactical blur

