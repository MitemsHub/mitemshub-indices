# Live Watch Alert Design

## Purpose

This design adds a continuous read-only live watch mode for `R_75` and `R_100` that monitors the market, evaluates the existing strategy stack on a stable cadence, and emits trader-friendly alerts only when the market meaningfully changes.

The feature is intended to turn the current one-shot `live-snapshot` command into a more useful live assistant workflow without introducing real execution, MT5 order placement, or broker-side side effects.

## Scope

This design covers:

1. A new read-only watch command for `R_75` and `R_100`.
2. Continuous live monitoring using the existing Deriv market data path.
3. Snapshot evaluation on a stable cadence, recommended as primary candle close.
4. Alert emission only when the market state changes meaningfully.
5. Dual output targets:
   - terminal for live trader-facing updates
   - JSONL journal for structured alert history

## Non-Goals

- Live order execution or execution suggestions that bypass current safety boundaries.
- Continuous tick-by-tick commentary.
- Replacing `live-snapshot`, `paper-live`, or MT5 monitoring commands.
- Building a GUI, dashboard, or notification service in this iteration.
- Adding order book, DOM, or real volume/order-flow analysis.

## Current Problem

The project now has a working read-only `live-snapshot` command, but it is:

- on-demand only
- single-shot rather than continuous
- useful for checking the market now, but not for keeping watch over the market for the user

This leaves a gap between:

- static repeated checks
- and
- a true read-only assistant that watches the market and speaks only when conditions change

## Design Goals

- Keep the feature strictly read-only.
- Reuse the current snapshot analysis stack instead of creating a second strategy path.
- Avoid constant chatter and noisy updates.
- Prefer stable market evaluation points over arbitrary sub-second commentary.
- Make alert history reviewable after the session.

## Approaches Considered

### Option 1: Fixed-Interval Polling Watcher

Poll the market every fixed interval, generate a fresh snapshot, compare it to the previous one, and emit alerts when the state changes.

Pros:

- straightforward to build
- easy to understand
- can reuse `live-snapshot` logic directly

Cons:

- cadence can be either noisy or laggy
- updates may occur mid-candle, which can produce unstable interpretations

### Option 2: Candle-Close Watcher

Keep watching live ticks, but only evaluate once a new primary candle closes.

Pros:

- aligns with the current strategy timing
- less noisy than interval polling
- more stable trader-facing commentary

Cons:

- less frequent than short-interval polling
- requires continuous live tick observation rather than simple repeat calls

### Option 3: Hybrid Watch + Alert Engine

Continuously observe live ticks, evaluate on candle close, and emit alerts only for meaningful state transitions.

Pros:

- best trader experience
- stable evaluation points
- alerts only when the market meaningfully changes
- reduces spam while maintaining active monitoring

Cons:

- more state logic than a single polling loop
- requires an explicit transition model

## Selected Approach

Use Option 3: Hybrid Watch + Alert Engine, with candle-close evaluation as the core cadence.

This is the best fit because the current strategy stack already reasons on candle structure. Evaluating on each closed primary candle is more consistent than evaluating on arbitrary partial intrabar movement, and alerting only on state changes keeps the output useful.

## Command Design

### CLI Surface

Add a new command such as:

`live-watch`

The command should support:

- `--symbol` with `R_75` and `R_100`
- `--warmup-count`
- `--timeframe`
- `--higher-timeframe`
- `--journal` for structured alert history
- `--max-alerts` to bound the session for testing or operator preference
- `--max-minutes` or similar optional session limit
- `--app-id`

Defaults should favor:

- `60` second primary timeframe
- `300` second higher timeframe
- a writable journal path
- no need for MT5 or execution-specific inputs

## Watch Loop Design

### Warm Start

At command start:

- fetch historical ticks for warm context
- build current primary and higher timeframe candle histories
- create the first baseline snapshot

This baseline should not necessarily emit an alert immediately unless configured to do so. The default behavior should be:

- establish state first
- alert only on meaningful change afterward

### Continuous Market Observation

After warm start:

- subscribe to live ticks
- update the candle builders with each new tick
- detect when a primary candle closes

The watcher should only run the full snapshot analysis when:

- a primary candle closes

This keeps the monitoring cadence aligned with the current strategy logic.

## Alert Transition Model

The watch engine should compare:

- the previous evaluated snapshot
- the current evaluated snapshot

It should emit an alert only if one or more significant fields changed, such as:

- `call` changed
- `trade_status` changed
- `direction_bias` changed
- `regime` changed
- confidence crosses the decision threshold
- the wait condition changes materially

Examples:

- `stand_aside -> buy_candidate`
- `buy_candidate -> stand_aside`
- `sell_candidate -> stand_aside`
- `range -> trend_down`
- confidence moved from below threshold to above threshold

Small numeric changes that do not alter trader meaning should not emit alerts on their own.

## Output Design

### Trader-Facing Terminal Output

Each emitted alert should be concise and human-readable.

Suggested leading fields:

- `call=stand_aside | buy_candidate | sell_candidate`
- `symbol=R_75 | R_100`
- `why=...`
- `wait_for=...`

If the setup is valid:

- `entry_area=...`
- `stop_area=...`
- `target_area=...`
- `reward_risk=...`

If the setup is invalid:

- keep the explanation short and trader-focused

### Journal Output

Each alert should also be recorded as a structured JSONL event.

Suggested event type:

- `live_watch_alert`

Suggested fields:

- symbol
- epoch
- trade_status
- call
- direction_bias
- regime
- confidence
- why
- wait_for
- current_close
- reasons
- entry_area if present
- stop_area if present
- target_area if present

This gives the operator a post-session alert trail that can be reviewed or mined later.

## State Model

Introduce a compact watch-state representation that captures the trader-meaningful fields needed for transition detection.

This state should be smaller than the full snapshot and focus on:

- `call`
- `trade_status`
- `direction_bias`
- `regime`
- `confidence_bucket`
- `wait_for`

The watch engine can compare these values between evaluations to decide whether to emit an alert.

## Error Handling

The watch command should fail clearly for:

- live dependency missing
- Deriv transport failure
- unsupported symbol
- insufficient warm context that never recovers
- journal path write failure

The command should not silently degrade into a misleading idle loop.

## Testing Strategy

Add focused tests for:

1. watch-state transition detection
   - no alert when state is materially unchanged
   - alert when call changes
   - alert when regime changes meaningfully
2. candle-close evaluation cadence
   - no alert on partial intrabar updates alone
   - alert evaluation triggered on primary candle close
3. alert rendering
   - concise trader-facing output
   - structured journal event output
4. read-only guarantees
   - no MT5 calls
   - no execution backend use
5. bounded watch sessions
   - command can exit cleanly after max alerts or session limit during tests

## Success Criteria

This design is successful when:

- the operator can run one read-only watch command for `R_75` or `R_100`
- the system keeps monitoring live market state continuously
- the system only emits alerts when the trader meaning changes
- alerts are visible in the terminal and persisted to a journal
- the command remains strictly read-only and does not touch execution paths
