# Decisive Live Call Engine Design

## Purpose

This design replaces the current slow, over-defensive `live snapshot -> guardian -> UI` flow with a faster and more decisive market-scanning system for `R_75` and `R_100`.

The operator complaint is clear:

1. symbol selection can take far too long before producing an answer
2. the answer often arrives as a weak, non-committal blanket statement
3. the system hides too much of the technical trade plan even when a direction already has a usable edge

The redesign must make the platform behave more like an experienced discretionary scanner:

1. keep both symbols warm continuously
2. produce an actionable call earlier when the edge is real but not yet perfect
3. upgrade, maintain, or cancel that call quickly as live ticks evolve
4. speak in trader-useful terms instead of generic summary language

## Core Requirement

The platform must stop forcing the operator to wait through a heavy cold scan only to receive cautious copy that still does not help with execution.

That means the new system must:

1. scan `R_75` and `R_100` continuously in the background
2. publish a real trade plan as soon as the setup becomes actionable, not only after the narrowest confirmation state
3. keep cancellation discipline so weak setups are withdrawn quickly
4. preserve exact technical context: regime, direction, entry logic, stop logic, target logic, invalidation trigger, and next condition
5. reduce time-to-first-usable-call materially relative to the current click-triggered live snapshot path

## Current Problem

The current system underdelivers for three architectural reasons.

### 1. Cold Analysis On Click

`src/synthetic_trader/live/market_snapshot.py` still collects live ticks and runs the main analysis on demand when the operator selects a symbol.

This causes:

1. long wait times before a call appears
2. repeated expensive work for every symbol selection
3. decision latency that feels disconnected from the speed of synthetic-index movement

### 2. Over-Defensive Guardian Behavior

`src/synthetic_trader/live/signal_guardian.py` is optimized to protect against false confidence, but it currently suppresses too many usable setups by:

1. downgrading to `weakening` too quickly
2. invalidating on rollover pressure before the platform has extracted enough trading value from the setup
3. treating "good enough to act with caution" and "good enough to fully confirm" as if they should produce almost the same operator behavior

### 3. Trader Context Is Too Compressed

The operator-facing app currently reduces the backend read into softer text than the engine actually has available.

That causes:

1. too much generic `wait` language
2. hidden execution levels outside the single `confirmed` state
3. a gap between the actual technical read and what the operator is allowed to see

## Scope

This design covers:

1. a continuous live scanner for `R_75` and `R_100`
2. a new public decision lifecycle built around earlier actionable calls
3. symbol-specific tuning for `R_75` and `R_100`
4. a richer trade-plan payload for the operator app
5. call freshness tracking and stale-plan handling
6. regression tests for latency-sensitive reads, actionable-call publication, cancellation, and UI rendering

## Non-Goals

This design does not cover:

1. real broker execution automation
2. automated order placement
3. post-entry position management
4. changing the app into a multi-user cloud service
5. introducing external social-media opinions directly into runtime trade decisions

## Approaches Considered

### Option 1: Relax The Existing Guardian

Adjust the current thresholds so the engine confirms more setups and phrases them more aggressively.

Pros:

1. smallest code change
2. fastest short-term relief

Cons:

1. does not solve the cold-scan latency problem
2. keeps the same architecture that caused the current frustration
3. still leaves the platform trapped in a confirmation-first output model

### Option 2: Replace The Guardian With A More Aggressive Scorer

Remove most of the current guardian discipline and let a scoring model publish earlier calls directly.

Pros:

1. more decisive output
2. simpler operator-facing logic

Cons:

1. too easy to swing into reckless low-quality calls
2. still too slow if heavy analysis remains click-triggered
3. throws away useful live invalidation discipline

### Option 3: Continuous Scanner With A Two-Stage Call Engine

Run a background scanner per symbol, publish an `actionable` call earlier, then let a live guard maintain, upgrade, or cancel it.

Pros:

1. fixes both latency and decision-quality problems together
2. preserves safety discipline without forcing silence
3. fits how an experienced trader works: scan continuously, issue a thesis early, then validate or revoke it quickly

Cons:

1. largest redesign in this set
2. requires new state storage, bridge behavior, and UI logic

## Selected Approach

Use Option 3: `continuous scanner + two-stage call engine`.

This is the only approach that directly addresses the full operator complaint:

1. stop waiting too long after click
2. stop collapsing into blanket statements
3. keep real cancellation logic instead of replacing discipline with noise

## High-Level Design

The redesign has four layers:

1. `continuous symbol watcher`
   - keeps `R_75` and `R_100` live-scanned in the background

2. `decision engine`
   - produces a directional thesis, trade levels, regime context, and confidence package

3. `call state manager`
   - decides whether the setup is `forming`, `actionable`, `confirmed`, `failing`, or `cancelled`

4. `operator presentation layer`
   - shows the full trade plan in trader-facing language with freshness, invalidation, and execution guidance

The operator app should read current prepared state immediately instead of forcing a fresh full analysis every time a symbol is selected.

## Decision Lifecycle

The existing public lifecycle is too narrow for operator use. The new lifecycle should be:

1. `forming`
   - directional evidence is incomplete

2. `actionable`
   - a usable directional edge exists and the platform should publish a real trade plan with caution labeling

3. `confirmed`
   - the setup has gained enough follow-through to trade with normal confidence

4. `failing`
   - the original call still explains the market, but live deterioration means the operator should not treat the old plan as fresh without a refresh

5. `cancelled`
   - the trade thesis is broken and the plan should no longer be used

### State Intent

`actionable` is the key addition.

The current platform jumps too often from `armed` language into “do not enter yet” behavior. The redesign instead acknowledges a middle truth:

1. some setups are good enough to trade cautiously
2. not every usable setup needs to wait for perfect confirmation
3. the platform should say this explicitly and manage the risk honestly

## Continuous Scanner

### Watcher Model

The Python layer should run a continuously updating watcher for each supported symbol:

1. `R_75`
2. `R_100`

Each watcher should maintain a rolling state object containing:

1. latest tick window
2. latest primary and higher-timeframe candles
3. latest regime and structure read
4. latest directional thesis
5. latest trade plan
6. latest call state
7. freshness timestamp
8. invalidation timestamp if cancelled

### Refresh Policy

The watcher should:

1. consume ticks continuously
2. refresh decision state on meaningful market updates instead of waiting for explicit symbol clicks
3. expose the latest prepared state through a fast local bridge read

The UI should pull the latest watcher state instantly on symbol selection.

## Decision Engine Behavior

The directional engine should continue using technical inputs already present in the system, but the result must be shaped for trader action rather than just validity filtering.

### Required Analysis Dimensions

Every decision package should synthesize:

1. market regime
2. directional structure
3. momentum quality
4. pullback quality
5. volatility and drift behavior
6. reward-to-risk shape
7. continuation trigger
8. invalidation trigger

### Output Contract

Every non-`forming` setup should carry:

1. `call`
2. `symbol`
3. `state`
4. `confidence`
5. `regime`
6. `market_thesis`
7. `entry_area`
8. `entry`
9. `stop_area`
10. `stop_loss`
11. `target_area`
12. `take_profit`
13. `reward_risk`
14. `invalidates_if`
15. `next_trigger`
16. `call_age_seconds`
17. `last_updated_at`

## Actionable Call Policy

The platform must no longer hide all practical levels until the single `confirmed` state.

### New Visibility Rules

1. `forming`
   - no execution levels

2. `actionable`
   - show entry, stop, and target with a visible caution label and freshness timer

3. `confirmed`
   - show full execution plan as ready

4. `failing`
   - keep the last plan visible for context, but mark it stale and block new execution unless refreshed

5. `cancelled`
   - remove execution authority and clearly mark the prior plan unusable

This intentionally replaces the current confirmed-only visibility rule because that rule is part of the operator problem this redesign is solving.

## Live Cancellation Logic

The platform still needs hard discipline after becoming more decisive.

### Failing State

Move to `failing` when:

1. directional persistence degrades materially
2. adverse clusters build but have not fully broken the thesis
3. continuation quality fades
4. price drifts too far from the planned entry for the original plan to stay trustworthy

### Cancelled State

Move to `cancelled` when:

1. adverse excursion breaks guardrails
2. rollover behavior becomes dominant
3. the continuation window expires materially
4. the original technical thesis is no longer valid

## Symbol-Specific Tuning

`R_75` and `R_100` must stop sharing one generic behavior profile.

### R_75 Profile

Tune `R_75` to:

1. tolerate larger volatility bursts
2. accept faster continuation after setup formation
3. require stronger invalidation proof before cancelling an actionable idea

### R_100 Profile

Tune `R_100` to:

1. demand slightly cleaner continuation structure
2. react faster to deterioration after momentum fade
3. use tighter stale-plan drift limits

## UI Behavior

The operator app should stop softening the technical picture into vague prose.

### Presentation Goals

The UI must show:

1. headline call
2. state label
3. confidence
4. regime
5. exact reason the market has the edge
6. exact next trigger
7. exact invalidation trigger
8. plan freshness in seconds

### Wording Rules

The formatter layer should:

1. preserve technical meaning
2. avoid generic “stay patient” filler when a real directional edge exists
3. express caution through explicit invalidation and freshness rules rather than timid blanket prose

## Bridge And Transport

The Next bridge should stop launching a heavy Python read for every operator click.

### Bridge Design

Instead:

1. Python watchers should own live market preparation
2. the bridge should query current watcher state
3. the route should return a prepared decision package quickly
4. the response should include freshness metadata so the UI can show whether the call is current

### Degraded Mode

If watcher state is unavailable:

1. the route should say the watcher is unavailable explicitly
2. the UI should not pretend the issue is a market-structure problem
3. stale or unavailable transport state must remain clearly separate from a legitimate `forming` market read

## Data Flow

1. background watcher subscribes to live ticks for `R_75` and `R_100`
2. watcher maintains rolling market state and decision package
3. bridge reads the latest watcher package instead of launching a cold full analysis
4. `POST /api/calls/run` returns the prepared package immediately
5. UI renders the call, freshness, and state-specific execution rules
6. polling continues to refresh state transitions from `actionable` to `confirmed`, `failing`, or `cancelled`

## File Plan

Python engine:

1. Modify: `src/synthetic_trader/live/market_snapshot.py`
   - separate continuous watcher state from cold snapshot analysis
2. Modify: `src/synthetic_trader/live/signal_guardian.py`
   - replace current public lifecycle behavior with the new actionable/failing/cancelled model
3. Create: `src/synthetic_trader/live/live_symbol_watcher.py`
   - maintain rolling watcher state for `R_75` and `R_100`
4. Create or modify: Python tests for watcher behavior, actionable publication, cancellation, and symbol-specific tuning

Bridge and web app:

1. Modify: `external/mitemshub-indices/src/lib/contracts.ts`
   - add new call states and freshness fields
2. Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
   - read prepared watcher state instead of cold heavy reads on click
3. Modify: `external/mitemshub-indices/app/api/calls/run/route.ts`
   - return the richer decision package
4. Modify: `external/mitemshub-indices/src/hooks/use-operator-workspace.ts`
   - display freshness and consume the richer call states
5. Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
   - render sharper call truth and freshness
6. Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
   - expose actionable levels earlier and block stale execution cleanly
7. Modify: `external/mitemshub-indices/src/lib/formatters.ts`
   - preserve technical detail and remove blanket trader-hostile copy

## Testing Strategy

Add focused coverage for:

1. watcher state becoming available without click-triggered cold analysis
2. `actionable` call publication before full confirmation
3. `confirmed` upgrades
4. `failing` deterioration handling
5. `cancelled` invalidation handling
6. `R_75` and `R_100` symbol-specific threshold behavior
7. UI rendering of freshness, actionable levels, and stale-plan blocking
8. route responses when watcher state is unavailable or stale

## Risks

1. an aggressive actionable state can become too noisy if thresholds are too loose
2. stale-plan visibility can confuse the operator if labels are not explicit enough
3. background watcher design adds long-running process complexity

## Mitigations

1. keep hard invalidation discipline even while publishing earlier calls
2. surface freshness and invalidation rules prominently in the UI
3. test `R_75` and `R_100` separately instead of relying on one generic threshold profile
4. preserve explicit degraded-mode responses when watcher transport is unhealthy

## Success Criteria

The redesign is successful when:

1. selecting `R_75` or `R_100` returns a prepared call materially faster than the current cold-scan path
2. the platform publishes earlier actionable calls instead of defaulting to vague stand-aside language too often
3. deterioration is still handled quickly through `failing` and `cancelled` states
4. the operator sees exact trade-plan context instead of broad generic summaries
5. `R_75` and `R_100` feel tuned to their own behavior rather than treated as interchangeable
