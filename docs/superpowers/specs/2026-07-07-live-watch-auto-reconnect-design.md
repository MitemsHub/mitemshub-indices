# Live Watch Auto-Reconnect Design

## Purpose

This design upgrades `live-watch` so it survives Deriv websocket disconnects and keepalive timeouts without producing incorrect decisions from stale state.

Correctness is prioritized over continuity. After a reconnect, the watcher rebuilds a fresh baseline state from a new tick history snapshot, then resumes candle-close evaluation from that baseline.

## Scope

This design covers:

1. Automatic reconnect when the Deriv websocket stream disconnects or errors.
2. Baseline rebuild after reconnect using fresh tick history.
3. A single journal event record for reconnect attempts and outcomes.
4. Focused tests proving reconnect triggers baseline rebuild and state reset.

## Non-Goals

- Changing decision engine logic, risk policy, thresholds, or signal validity rules.
- Emitting extra “reconnect alerts” into the live terminal feed.
- Attempting to interpolate or fill missing ticks.
- Adding external notifications.

## Current Problem

`live-watch` reads an async tick stream from Deriv. The underlying websocket can terminate due to keepalive/ping timeouts or network issues.

If the stream breaks mid-session:

- the process crashes, or
- the operator restarts manually, losing session continuity, and
- any attempt to continue from stale state would be unsafe because candles may be missing ticks.

## Design Goals

- Keep the session alive across transport failures.
- Ensure decisions after reconnect are based on a fresh, consistent baseline.
- Keep the live feed clean: only show real market state transitions.
- Keep the journal authoritative and reviewable.
- Fail closed when reconnect cannot be re-established.

## Approaches Considered

### Option 1: Reconnect And Continue From Previous State

Pros:
- quiet feed
- minimal work

Cons:
- unsafe if ticks were missed (baseline/candles can be corrupted)
- can produce incorrect decisions

### Option 2: Reconnect With Baseline Rebuild

Pros:
- correctness-first
- deterministic state after reconnect
- reduces risk of acting on stale candles

Cons:
- requires additional state reset behavior

## Selected Approach

Use Option 2: reconnect with baseline rebuild.

## Reconnect Triggers

Reconnect attempts should occur when the tick subscription fails due to:

- websocket connection closed
- keepalive/ping timeout
- socket receive errors
- a `RuntimeError("client is not connected")` surfaced from the client

The code should treat these failures as transport errors and attempt to reconnect until:

- reconnect succeeds, or
- `--max-minutes` session bound expires, or
- a new reconnect cap is reached (default limited).

## Baseline Rebuild Rules

On reconnect success:

1. Rebuild the watch buffer using fresh tick history:
   - call the same tick-history path used by startup warmup (`ticks_history`)
   - use `warmup_count` as the baseline history target
2. Recompute a baseline snapshot using `analyze_live_snapshot()`.
3. Reset watch loop state:
   - `previous_state = build_watch_state(baseline_snapshot)`
   - `context_cooldown_remaining = 0`
4. Resume streaming ticks and candle-close evaluation normally.

Correctness rule:

- Do not emit a live alert just because a reconnect happened.
- Emission remains driven by the existing candle-close state transition logic.

## Journal Records

Write reconnect visibility into the same journal file using dedicated record types that do not collide with emitted alerts.

### Reconnect Attempt Record

- `record_type=watch_transport`
- `event=reconnect_attempt`
- `symbol`
- `attempt`
- `reason`

### Reconnect Success Record

- `record_type=watch_transport`
- `event=reconnect_rebaseline_ok`
- `symbol`
- `attempt`
- baseline preview fields (safe subset):
  - `regime`
  - `direction_bias`
  - `trade_status`
  - `confidence`

### Reconnect Failure Record

- `record_type=watch_transport`
- `event=reconnect_failed`
- `symbol`
- `attempts`
- `reason`

Transport records must not contain a `call` field so the existing emitted-alert parsing continues to treat the recent alerts list as “what was shown live”.

## CLI Surface

Keep defaults correctness-first:

- Auto-reconnect enabled by default in `live-watch`.

Add optional operator controls:

- `--max-reconnects` (default small, e.g. `5`)
- `--reconnect-backoff-sec` (default `1`, exponential backoff with cap)

No new required flags are introduced.

## Testing Strategy

Add focused tests that:

1. simulate a disconnect after N ticks
2. ensure a reconnect occurs
3. ensure baseline rebuild is executed
4. ensure cooldown/state is reset after reconnect
5. ensure reconnect records are journaled

Tests should use an injected `client_factory` (or an injected tick watcher) that:

- yields a few ticks
- raises a transport error
- then yields ticks again after “reconnect”

## Success Criteria

This design is successful when:

- `live-watch` survives Deriv websocket disconnects without crashing
- decisions after reconnect are based on a rebuilt baseline snapshot
- live terminal output remains decision-first and not spammed by reconnect events
- journal contains explicit reconnect evidence
