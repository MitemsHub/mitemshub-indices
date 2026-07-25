# Signal Guardian Design

## Purpose

This design upgrades the current Synthetic Indices market-reading stack from a one-shot live snapshot into a continuous `Signal Guardian` that tracks setup quality tick by tick and tells the operator, in plain terms, whether a setup is still forming, truly confirmed, weakening, or invalidated.

The goal is not to make the system louder. The goal is to make it sharper, more honest, and materially better at catching bad follow-through before the operator acts on a stale or weak idea.

## Core User Requirement

The operator does not want vague wording such as "wait for confirmation" while still being forced to interpret the chart manually.

The operator wants:

1. engine-generated confirmation instead of chart guesswork
2. continuous tick-by-tick supervision of setup quality
3. explicit downgrade and invalidation when the market turns
4. no deceptive fallback behavior that looks like live analysis
5. a system that is materially better at live synthetic-index behavior, especially for `R_75` and `R_100`

## Current Problem

The current architecture still behaves as a snapshot decision system:

1. the web app requests one fresh read
2. the bridge executes one live snapshot
3. the Python engine evaluates one bounded slice of recent ticks
4. the response is rendered as a trade plan

This creates three operator problems:

1. `confirmation` is under-specified
   - the current engine can say `wait for a clean bullish continuation close`, but it does not define that condition tightly enough for the operator
2. setup quality can decay after the snapshot
   - the market can start as a candidate and then weaken almost immediately, but the app does not keep supervising that idea continuously
3. the UI can overstate readiness
   - a setup can appear actionable even though the market has already drifted, stalled, or reversed after the original read

## Scope

This design covers:

1. a continuous read-only `Signal Guardian` layer for `R_75` and `R_100`
2. tick-by-tick microstructure supervision between snapshot evaluations
3. explicit setup lifecycle states
4. engine-owned confirmation and invalidation rules
5. stable operator-facing truth labels in the web app
6. signal freshness, staleness, and revalidation behavior
7. testing against reversal and failed-follow-through cases

## Non-Goals

This design does not yet cover:

1. automatic broker execution
2. MT5 order placement or modification
3. full autonomous trade management after a real order is opened
4. public cloud deployment
5. adding non-Deriv market data or external volume/order-book feeds

## Design Goals

1. make setup confirmation explicit and engine-generated
2. detect weakening and invalidation earlier than the current snapshot flow
3. stay aligned with the existing strategy stack instead of creating a second unrelated engine
4. keep the system honest when live state is unavailable
5. improve signal quality without turning the UI into noisy tick commentary

## Approaches Considered

### Option 1: Stronger Snapshot Rules Only

Tighten the current snapshot thresholds, require higher confidence, and keep the web app request-response flow unchanged.

Pros:

- smallest implementation
- lower coordination cost
- reduces some weak setups

Cons:

- still not continuous
- still leaves the operator exposed to immediate post-snapshot decay
- does not solve the core request for engine-generated confirmation

### Option 2: Continuous Signal Guardian

Keep the current snapshot and watch pipeline, but add a persistent state layer that consumes live ticks continuously, maintains setup lifecycle state, and emits explicit status changes.

Pros:

- directly answers the operator requirement
- can confirm, weaken, or invalidate setups in real time
- improves honesty without needing immediate auto-execution
- fits the current local bridge architecture

Cons:

- requires new state modeling
- requires more testing than snapshot-only tightening

### Option 3: Full Auto Trader Immediately

Jump straight to autonomous signal generation, execution, and trade management.

Pros:

- strongest possible end state

Cons:

- too risky before signal quality is hardened
- would automate the current weaknesses
- harder to debug because signal quality and execution quality would fail together

## Selected Approach

Use Option 2: Continuous Signal Guardian.

This is the correct next step because it upgrades the system where the current weakness actually lives: between the initial idea and the market's next few ticks/candles.

## High-Level Architecture

The upgraded system should have four logical layers:

1. `Tick stream`
   - continuous Deriv tick subscription for `R_75` and `R_100`

2. `Snapshot engine`
   - existing candle, feature, regime, decision, and risk logic
   - still produces the baseline directional thesis

3. `Signal Guardian`
   - new continuous state layer
   - owns setup lifecycle, confirmation, weakening, invalidation, and freshness

4. `Operator bridge and UI`
   - exposes the guardian state truthfully
   - never implies live readiness when the guardian cannot confirm it

The existing snapshot engine remains the analytical core. The new guardian layer sits above it and supervises whether the thesis is still alive.

## Signal Lifecycle

The system should stop collapsing everything into `buy candidate`, `sell candidate`, or `stand aside` only.

The guardian should introduce these live states:

1. `forming`
   - directional structure is emerging, but the entry condition is not yet armed

2. `armed`
   - the larger setup is acceptable and price is close enough to the planned zone to start watching for confirmation

3. `confirmed`
   - the engine has observed explicit confirmation behavior and the setup is currently valid for entry

4. `weakening`
   - the setup has not fully failed yet, but follow-through quality has degraded enough that the operator should stop treating it as a clean entry

5. `invalidated`
   - the market has violated the guardrails of the setup and the idea should no longer be treated as tradable

6. `unavailable`
   - live guardian state cannot be trusted because the bridge or feed is not healthy

These states should exist independently of the older `call` label. The older `call` label can remain, but it should no longer be the only operator-facing truth.

## Confirmation Model

The phrase `wait for confirmation` must become an explicit engine rule set.

### Buy Confirmation

A buy setup should only move from `armed` to `confirmed` when all of the following categories are satisfied within a bounded window:

1. `zone interaction`
   - price reaches, reclaims, or holds the planned entry area

2. `defense quality`
   - price does not immediately lose the invalidation buffer below the entry zone

3. `microstructure improvement`
   - tick-level behavior stops producing fresh short-term weakness and begins producing short-term upward acceptance

4. `short-window acceptance`
   - the latest confirmation window closes back in the expected direction rather than rejecting the move instantly

5. `adverse excursion control`
   - the distance moved against the idea after arming remains below a hard degradation threshold

### Sell Confirmation

The sell logic is the inverse:

1. price reaches the sell area
2. price fails to keep accepting higher
3. microstructure starts leaning back downward
4. the latest confirmation window closes in favor of sellers
5. adverse excursion remains within the allowed tolerance

### Confirmation Ownership

The engine, not the operator, should decide whether those conditions are met.

The UI should therefore show:

- `forming`
- `armed`
- `confirmed`
- `weakening`
- `invalidated`

instead of merely telling the user to infer the answer visually.

## Threshold Policy

The guardian must not use hidden or discretionary thresholds.

The first implementation should define explicit configuration values for:

1. `max_arming_ticks`
   - how many ticks a setup may remain in `armed` state before it goes stale

2. `max_confirmation_window_ticks`
   - how many ticks the engine may use to decide whether the market accepted the setup after zone interaction

3. `max_adverse_excursion_ratio`
   - how far price may move against the idea, expressed as a fraction of the planned stop distance

4. `weakening_excursion_ratio`
   - the smaller adverse-excursion ratio that downgrades the setup to `weakening` before full invalidation

5. `max_entry_drift_ratio`
   - how far price may drift away from the planned entry, expressed as a fraction of the planned stop distance, before the original thesis becomes stale

6. `microstructure_window_ticks`
   - the short rolling tick window used to measure local directional improvement or deterioration

These values should be:

1. explicit in configuration
2. symbol-aware where needed for `R_75` versus `R_100`
3. testable through deterministic regression fixtures
4. adjustable without rewriting the guardian state machine

The plan phase should define the first concrete defaults. The implementation phase must not leave them implicit.

## Tick-Level Guardian Logic

The guardian should consume every live tick after the baseline setup is produced.

It should maintain:

1. current best bidirectional setup thesis from the snapshot engine
2. distance from planned entry zone
3. maximum favorable excursion since arming
4. maximum adverse excursion since arming
5. short-window tick slope or directional balance
6. elapsed time and elapsed ticks since arming
7. last lifecycle transition reason

This allows the system to detect situations such as:

1. setup armed but never accepted
2. setup briefly armed then instantly rejected
3. setup confirmed and still healthy
4. setup confirmed then weakening before entry
5. setup invalidated before it should be trusted

## Stable Evaluation Cadence

The system should not spam the operator on every tick even though it watches every tick.

The correct pattern is:

1. consume every tick continuously
2. update guardian state continuously
3. expose operator-facing changes only when state meaning changes materially

This preserves sharpness without turning the app into unreadable noise.

## Freshness And Staleness Rules

Every setup should have a freshness budget.

A setup should become stale when:

1. too many ticks have passed without confirmation
2. price has drifted too far from the planned entry
3. the microstructure context has changed enough that the original thesis is no longer the same thesis

When stale, the setup should downgrade to `weakening` or `invalidated` rather than continuing to look like a current opportunity.

## Operator UI Design

The web app should show two truths clearly:

1. `directional thesis`
   - buy bias, sell bias, or no trade

2. `guardian state`
   - forming, armed, confirmed, weakening, invalidated, unavailable

### Primary UI Behavior

The trade panel should:

1. show execution levels only when the guardian says `confirmed`
2. show plain language warning text when the setup is `weakening` or `invalidated`
3. show explicit unavailable text when live guardian truth is unavailable

### Language Rules

Good examples:

- `Buy thesis present, but confirmation not received yet`
- `Buy setup confirmed and still healthy`
- `Buy setup weakening; do not enter from the old plan`
- `Setup invalidated; price no longer respects the original thesis`
- `Live guardian unavailable; refresh after the bridge reconnects`

Bad examples:

- `Buy setup ready` without guardian state
- `Wait for confirmation` without engine-owned meaning
- any fallback numbers that look like live market levels

## Bridge Design

The backend bridge should evolve from one-shot `runFreshCall()` behavior into two related capabilities:

1. `fresh snapshot request`
   - still useful for generating the baseline thesis

2. `continuous guardian status`
   - a live state source that the UI can poll or subscribe to

The exact transport can remain simple at first:

- short interval polling from the UI is acceptable for the first guardian version

WebSockets can be deferred if the guardian state model is not yet proven.

## Safety Rules

1. no fake trade levels when live analysis fails
2. no `confirmed` state unless the guardian has observed explicit confirmation behavior
3. no stale setup should remain visually equivalent to a fresh setup
4. invalidation must be explicit, not implied

## Testing Strategy

This upgrade should be tested against the exact class of failure the user described: a buy thesis that looks valid initially, then quickly loses follow-through and stops out.

### Test Categories

1. `arming without confirmation`
   - setup enters watch state but never qualifies as confirmed

2. `confirmed then weakening`
   - setup qualifies briefly, then loses short-term quality before entry should be trusted

3. `confirmed then invalidated`
   - setup crosses the hard invalidation threshold and is withdrawn

4. `price drift stale-out`
   - setup never confirms and drifts far enough to become stale

5. `bridge unavailable`
   - UI shows unavailable truth rather than fake trade levels

6. `operator wording`
   - the UI text must clearly distinguish between thesis, confirmation, and invalidation

## Acceptance Criteria

This design is complete when all of the following are true:

1. the operator no longer has to guess what `confirmation` means
2. the engine can represent live states beyond a single snapshot decision
3. the system can mark a setup as `confirmed`, `weakening`, or `invalidated` based on live ticks
4. the UI never presents failed live reads as real trade plans
5. the operator can tell whether a directional thesis is current, stale, degrading, or dead
6. regression tests cover reversal cases similar to the failed buy example the user reported

## Recommended Delivery Sequence

The implementation should be done in this order:

1. define guardian state and transport contract
2. build a continuous guardian core around the existing snapshot engine
3. add explicit confirmation and invalidation rules
4. expose guardian truth in the bridge and UI
5. add reversal and stale-signal regression tests

This keeps the upgrade disciplined and avoids jumping into full auto-trading before the signal-quality layer is actually trustworthy.
