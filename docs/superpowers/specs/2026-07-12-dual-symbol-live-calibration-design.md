# Dual-Symbol Live Calibration For R_75 And R_100

## Purpose

This design extends the new intraday execution engine into a proper calibration phase for both `R_75` and `R_100`.

The current state is uneven:

1. the structural intraday rewrite already applies to both symbols
2. the most recent balanced trigger and target tuning focused primarily on `R_100`
3. `R_75` benefits from shared logic, but does not yet have deliberate symbol-specific tuning

The next step is not another broad rewrite. The next step is live calibration:

1. keep one shared pattern-aware execution engine
2. add symbol-specific trigger and travel tuning where the symbols genuinely differ
3. verify both symbols against realistic next-hour behavior rather than synthetic expectations alone

## Core Requirement

The system must calibrate `R_75` and `R_100` together without forcing them into identical intraday behavior.

That means:

1. shared execution logic should remain shared
2. symbol-specific thresholds must be configurable
3. both symbols must target realistic next-hour moves
4. neither symbol should fall back into wide fantasy targets or superficial entries

## Current Problem

### 1. Shared Logic Exists, But Calibration Is Uneven

The execution builder is now shared, but recent tuning decisions were made primarily for `R_100`.

That means:

1. `R_75` may be acceptable by accident instead of by calibration
2. symbol differences in move shape and trigger behavior are not fully reflected

### 2. Current Symbol Profile Is Too Thin

The symbol profile currently carries only broad intraday controls:

1. `intraday_hold_horizon_minutes`
2. `min_primary_reward_risk`
3. `travel_budget_5m_bars`

That is not enough to calibrate:

1. trigger quality thresholds
2. acceptable late-stage extension
3. reclaim tolerance
4. continuation strength requirements

### 3. Live Validation Is Still Too Fixture-Heavy

The recent tuning is verified mostly through strong unit fixtures.

That is useful, but not sufficient for:

1. real `R_75` next-hour structure
2. real `R_100` next-hour structure
3. symbol-specific differences in reachability and failure behavior

## Scope

This design covers:

1. symbol-specific intraday calibration fields for `R_75` and `R_100`
2. shared trigger classification with symbol overrides
3. shared target estimation with symbol-specific travel and rejection thresholds
4. paired fixture coverage for both symbols
5. light live calibration probes to validate real route behavior for both symbols

## Non-Goals

This design does not cover:

1. changing `4H`, `1H`, or `15m` thesis logic
2. retraining the model
3. changing portfolio risk rules
4. adding automated execution

## Approaches Considered

### Option 1: One Common Calibration For Both Symbols

Pros:

1. simplest maintenance
2. fastest implementation

Cons:

1. too blunt for symbol-specific behavior
2. likely good for one symbol and mediocre for the other

### Option 2: Fully Separate Intraday Engines

Pros:

1. maximum control per symbol
2. easiest to tune independently

Cons:

1. duplicate logic
2. higher maintenance cost
3. higher regression risk

### Option 3: Shared Core With Symbol Overrides

Pros:

1. keeps logic consistent
2. allows precise symbol-specific calibration
3. best balance of maintainability and trading realism

Cons:

1. requires careful config design
2. needs paired tests for both symbols

## Selected Approach

Use Option 3.

The engine should stay shared at the logic level, while symbol profiles define how strict or permissive each pattern and travel rule should be.

## Calibration Model

### Shared Core

The following remain shared:

1. trigger families
   - `continuation_close`
   - `reclaim_pullback`
   - `break_retest_hold`
2. local execution-stop construction
3. nearest-liquidity-plus-travel target selection
4. rejection of bloated geometry

### Symbol Overrides

Each symbol should gain explicit calibration fields for:

1. minimum continuation body efficiency
2. minimum close-location strength
3. minimum reclaim quality score
4. late-extension rejection ratio
5. travel-budget multiplier or window
6. minimum reward/risk for the primary next-hour target

## R_75 Calibration Intent

`R_75` should remain strong and structure-led, but it may need:

1. a slightly different travel budget than `R_100`
2. different late-extension rejection tolerance
3. different continuation strength requirements

The purpose is not to make `R_75` more active by force. The purpose is to ensure it is deliberately tuned for its own next-hour behavior.

## R_100 Calibration Intent

`R_100` should keep the recent balanced improvements, but those rules should be expressed as explicit profile settings instead of hard-coded behavior hidden in helper logic.

That makes:

1. tuning easier
2. behavior auditable
3. shared logic safer to maintain

## Implementation Shape

The likely implementation should:

1. extend `SymbolProfile` with calibration fields
2. make `classify_trigger()` use symbol-aware thresholds
3. make `select_primary_target()` use symbol-aware travel and late-move rejection thresholds
4. avoid introducing per-symbol branches all over the builder

The builder should read symbol settings from config, not encode special cases inline wherever possible.

## Testing Strategy

Add paired fixtures and assertions for both symbols:

1. `R_75` clean continuation that should pass
2. `R_75` late extension that should fail
3. `R_100` reclaim pattern that should pass
4. `R_100` noisy weak close that should fail
5. both symbols produce realistic next-hour primary targets
6. both symbols reject geometry that cannot pay for local risk

Decision-engine tests should confirm:

1. `R_75` and `R_100` both preserve the shared intraday contract
2. symbol-specific calibration produces different, intentional outcomes where appropriate

Live snapshot and route tests should confirm:

1. both symbols keep primary-target-first semantics
2. both symbols preserve pattern-aware copy

## Acceptance Criteria

This calibration is complete when:

1. both `R_75` and `R_100` use the shared pattern-aware intraday engine
2. both symbols have explicit calibration settings in config
3. both symbols produce realistic next-hour targets
4. both symbols reject weak or overextended setups
5. the live route returns behavior that is clearly calibrated rather than accidentally inherited

## Recommendation

Proceed with dual-symbol live calibration using a shared core plus symbol-specific overrides.

Do not fork the engine.

Do not keep `R_75` as an accidental beneficiary of `R_100` tuning.
