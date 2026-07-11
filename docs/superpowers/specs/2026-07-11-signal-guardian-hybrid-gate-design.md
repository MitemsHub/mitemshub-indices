# Signal Guardian Hybrid Gate Design

## Purpose

This design hardens the first Signal Guardian implementation so it becomes materially better at two things the operator cares about most:

1. blocking false entries before they ever look tradable
2. catching late reversals faster once a move starts to roll over

The upgrade keeps the existing guardian lifecycle model, but replaces the current lightweight confirmation logic with a stricter hybrid gate and a richer tick-level microstructure model.

## Core Requirement

The operator wants the system to stop producing weak or misleading setup confirmations in synthetic indices where tick behavior changes quickly.

That means the guardian must:

1. require stronger evidence before moving to `confirmed`
2. withdraw trust faster when short-term follow-through degrades
3. use more than a simple average tick slope to judge market behavior
4. remain plain and trader-facing in the UI even when the backend logic becomes more sophisticated

## Current Weakness

The current guardian in `src/synthetic_trader/live/signal_guardian.py` confirms setups too easily because it relies mainly on:

1. a short average tick slope
2. favorable excursion presence
3. adverse excursion thresholds
4. tick count windows

This is useful as a first guardrail, but it is still too permissive for synthetic-index behavior because:

1. a brief positive tick slope can look like confirmation even if the move has weak persistence
2. the system does not separate "good enough to watch" from "good enough to enter" sharply enough
3. late reversal handling is present, but it is still too shallow for fast rollover patterns

## Scope

This design covers:

1. stricter confirmation gates before `confirmed`
2. richer microstructure scoring for both buy and sell setups
3. explicit rollover detection after initial follow-through
4. stronger stale-entry blocking when price drifts or hesitates too long
5. richer guardian reason output for the operator UI
6. regression tests for false entries, delayed confirmation, and late reversals

## Non-Goals

This design does not cover:

1. broker-side automation
2. open-trade management after a real order is placed
3. changing the app transport from polling to WebSockets
4. changing the current UI style system

## Approaches Considered

### Option 1: Strict Filter Only

Focus almost entirely on pre-entry filtering and do only minor work on reversal handling.

Pros:

- smallest hardening pass
- best at reducing early bad entries quickly

Cons:

- still weaker than desired after a setup briefly looks healthy and then rolls over
- solves only half the operator complaint

### Option 2: Hybrid Gate

Use a stricter entry gate before confirmation and a separate rollover detector after arming or confirmation. Feed both from a richer microstructure score.

Pros:

- directly addresses both false entries and late reversals
- fits cleanly on top of the current guardian architecture
- improves signal quality without changing the public lifecycle model

Cons:

- more logic and test coverage than a narrow filter-only pass

### Option 3: Microstructure Deep Dive Only

Build a much richer tick-pattern scorer first and postpone explicit gate splitting.

Pros:

- strong analytical foundation
- likely improves both entry quality and reversal detection

Cons:

- too indirect as a first hardening step
- risks a better score without clearer operator-facing behavior boundaries

## Selected Approach

Use Option 2: Hybrid Gate, with the microstructure deep dive embedded inside it.

This is the right choice because the operator asked for both priorities:

1. stop false entries first
2. improve late reversal detection as well

The hybrid gate gives both outcomes in one disciplined upgrade instead of forcing two disconnected redesigns.

## High-Level Design

The hardened guardian should make decisions in three layers:

1. `baseline thesis`
   - inherited from the existing snapshot engine

2. `entry gate`
   - decides whether the setup is strong enough to become `confirmed`

3. `rollover detector`
   - decides whether a previously improving setup is now weakening or invalidated

The guardian should not move to `confirmed` unless the entry gate passes. The guardian should not remain trusted after confirmation if the rollover detector shows material deterioration.

## Entry Gate

The entry gate should be stricter than the current implementation and should require multiple checks to pass together.

### Required Buy Checks

A buy setup should only become `confirmed` if all of these conditions hold:

1. `zone acceptance`
   - price reaches, reclaims, or holds close enough to the planned entry area

2. `persistence`
   - upward tick pressure persists over a minimum number of ticks rather than appearing as one short burst

3. `pullback defense`
   - small retracements hold above a configured defense boundary instead of collapsing back through the entry structure

4. `rejection quality`
   - downward rejection is weak while upward acceptance is stronger

5. `drift control`
   - price has not moved too far away from the planned entry before confirmation is granted

6. `time discipline`
   - confirmation must happen within a bounded tick window, not after the setup has aged into something else

### Required Sell Checks

The sell entry gate is the inverse:

1. price reaches the sell area
2. downward pressure persists
3. rebounds fail beneath the defense boundary
4. upward rejection is weak while downward acceptance is stronger
5. drift away from the planned sell entry stays controlled
6. confirmation occurs before the thesis becomes stale

## Microstructure Deep Dive

The current guardian uses a simple short-window average tick slope. The hardening pass should replace that with a richer set of observable tick behaviors.

### New Microstructure Signals

The guardian should score at least these components:

1. `directional persistence`
   - whether the last window contains repeated in-thesis movement rather than scattered noise

2. `impulse quality`
   - whether the most favorable push has enough size and continuity to matter

3. `pullback quality`
   - whether counter-moves are shallow and controlled or deep and sloppy

4. `rejection imbalance`
   - whether rejected ticks against the thesis are weaker than accepted ticks in favor of it

5. `acceleration shift`
   - whether the move is strengthening, flattening, or losing force

6. `adverse clustering`
   - whether multiple short bursts against the thesis are appearing close together

These signals should combine into structured gate checks, not just one blended number. The guardian should still be explainable in plain language even if the internal scoring becomes richer.

## Rollover Detector

The system also needs a dedicated late-reversal detector instead of assuming confirmation stays valid until excursion thresholds are hit.

The rollover detector should watch for:

1. loss of persistence after an initially healthy move
2. growing pullback depth after favorable excursion has already occurred
3. failure to hold reclaimed territory
4. adverse tick clusters appearing more frequently
5. flattening or reversing short-window acceleration

### Rollover Actions

The rollover detector should:

1. downgrade to `weakening` before hard invalidation when deterioration first becomes meaningful
2. move to `invalidated` faster if rollover pressure continues building
3. prevent the UI from continuing to show the old execution plan as if it were fresh

## State Behavior

The public guardian states remain:

1. `forming`
2. `armed`
3. `confirmed`
4. `weakening`
5. `invalidated`
6. `unavailable`

The difference is that the rules behind `confirmed`, `weakening`, and `invalidated` become more selective and more responsive.

### Updated Meanings

- `armed`
  - the directional thesis is viable enough to watch, but the stricter entry gate has not passed yet
- `confirmed`
  - the multi-check entry gate passed and no active rollover warning is present
- `weakening`
  - the setup either failed part of the confirmation quality checks after initial progress or the rollover detector found meaningful deterioration
- `invalidated`
  - the setup broke hard guardrails or decayed far enough that the original thesis is no longer trustworthy

## Threshold Policy

The hybrid gate needs more explicit thresholds than the first guardian pass.

The implementation must define configurable values for:

1. `min_persistence_ticks`
2. `min_impulse_ratio`
3. `max_pullback_ratio`
4. `max_entry_drift_ratio`
5. `max_confirmation_window_ticks`
6. `rollover_warning_ratio`
7. `rollover_invalidation_ratio`
8. `adverse_cluster_window_ticks`
9. `max_adverse_cluster_count`
10. `microstructure_window_ticks`

These values should be:

1. explicit in configuration
2. symbol-aware when needed for `R_75` versus `R_100`
3. covered by deterministic regression fixtures
4. exposed clearly enough that future tuning does not require redesigning the guardian

## Operator-Facing Output

The operator UI should remain simple even as the backend gets sharper.

### Good Guardian Reason Examples

- `Buy thesis is armed, but persistence is still too weak for confirmation`
- `Buy setup confirmed after strong reclaim and controlled pullback`
- `Buy setup weakening after follow-through stalled and reversal pressure increased`
- `Sell setup invalidated after rebound pressure broke the defense boundary`

### UI Rules

1. `confirmed` is the only state that can show entry, stop, and target as active execution levels
2. `armed` must explicitly say the setup is not yet confirmed
3. `weakening` must tell the operator not to act on the old plan
4. `invalidated` must make clear that the thesis is dead

## Testing Strategy

This hardening pass must be tested against both classes of failure the operator cares about.

### False Entry Tests

1. setup reaches the zone briefly but persistence is too weak
2. setup shows one impulse but pullback quality is too poor
3. setup drifts too far before confirmation and should stay unconfirmed

### Late Reversal Tests

1. setup confirms, then loses persistence and downgrades to `weakening`
2. setup confirms, then adverse clusters build and the setup is invalidated sooner
3. setup makes favorable progress, stalls, and fails to defend reclaimed territory

### UI Truth Tests

1. entry levels remain hidden while the setup is only `armed`
2. weakening and invalidated states show explicit operator guidance
3. unavailable state never looks like a valid live plan

## Acceptance Criteria

This hardening design is complete when:

1. the guardian confirms fewer weak setups than the current implementation
2. setups can no longer become `confirmed` from a shallow short-window slope alone
3. late rollovers downgrade faster than in the first guardian pass
4. the operator can distinguish `armed` from truly `confirmed` with no ambiguity
5. regression tests cover both false-entry blocking and reversal handling

## Recommended Delivery Sequence

The implementation should be done in this order:

1. enrich the guardian threshold model
2. add structured microstructure helpers
3. replace the current confirmation logic with the multi-check entry gate
4. add the dedicated rollover detector
5. update guardian reason output and UI truth tests
6. run full Python and web verification
