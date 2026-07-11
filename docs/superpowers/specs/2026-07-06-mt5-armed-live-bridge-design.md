# MT5 Armed-Live Bridge Design

## Purpose

This design closes the current gap between supervised MT5 dry-run validation and real MT5 live execution. Today, `paper-live --live-mode armed-live --venue mt5` still runs the strategy session through a simulated `PaperBroker`, which means the validated strategy loop is not yet routing approved intents to MetaTrader 5.

The goal of this design is to preserve the existing validated strategy session shape while introducing a true MT5-backed armed-live execution path with fail-closed supervision, broker-truth reconciliation, and consistent operator visibility.

## Scope

This design covers two workstreams:

1. A read-only `R_100` preflight sequence that refreshes validation evidence and confirms current MT5 readiness without placing trades.
2. A full-lifecycle MT5 armed-live bridge that allows the existing strategy session to place, reconcile, and close broker-backed positions when the operator explicitly selects `Venue.MT5` with `LiveMode.ARMED_LIVE`.

## Non-Goals

- Changing the core decision model, timeframe stack, or risk policy.
- Expanding symbol coverage beyond the current supported synthetic indices.
- Introducing unattended live trading without operator gates.
- Replacing the existing manual MT5 lifecycle commands such as `mt5-sync`, `mt5-reconcile`, `mt5-close`, and `mt5-modify`.

## Current Problem

The current `paper-live` control surface successfully validates the end-to-end strategy session for:

- warmup data loading
- candle construction
- decision evaluation
- risk approval and rejection
- journaling
- session shutdown accounting

However, in the current implementation:

- `paper-live` uses `run_live_paper()`
- `run_live_paper()` creates a `PaperBroker`
- supervised armed mode only changes gating, not execution routing

As a result, the user can validate that the strategy wants to trade, but the session path is not yet the same path that would hit the MT5 terminal during a real supervised rollout.

## Design Goals

- Keep one strategy-session orchestration path for paper, dry-run-live, and armed-live.
- Preserve the already-validated dry-run behavior and evidence trail.
- Make MT5 broker truth authoritative once a live order is placed.
- Keep readiness and operator confirmation fail-closed before any real order.
- Ensure live shutdown behavior is explicit, reconciled, and observable.
- Add focused tests that prove the live path is truly different from the simulated path only where intended.

## Approaches Considered

### Option 1: Shared Session With Execution Routing

Keep `paper-live` as the single strategy session entrypoint, but replace hardcoded simulated execution with an execution backend selected by venue and mode.

Pros:

- preserves one validated strategy loop
- minimizes drift between dry-run and armed-live
- keeps testing focused on execution seams
- matches the current operator mental model

Cons:

- requires introducing a cleaner execution abstraction
- requires carefully separating simulated and broker-backed lifecycle logic

### Option 2: Separate MT5 Armed Session Command

Create a new CLI command dedicated to MT5 live strategy execution.

Pros:

- simpler first patch
- lower short-term disruption to the existing paper-live path

Cons:

- duplicates session orchestration
- increases drift risk between dry-run and armed-live
- makes long-term validation weaker because live and dry-run stop sharing the same core loop

### Option 3: Inline MT5 Conditionals In `run_live_paper()`

Keep the current function but add direct `if venue == MT5 and mode == ARMED_LIVE` branches around order placement and shutdown logic.

Pros:

- minimal code movement
- fastest initial edit

Cons:

- mixes strategy, supervision, and venue execution concerns
- makes future maintenance and testing harder
- weakens confidence in fail-closed behavior

## Selected Approach

Use Option 1: Shared Session With Execution Routing.

This is the best fit because it preserves the already-proven dry-run session while making the live path honest. The strategy still evaluates the same candles, thresholds, and risk decisions. The only controlled difference is the execution backend used after a signal is approved.

## Target Architecture

### Session Orchestrator

`paper-live` remains the user-facing strategy session command. It continues to own:

- warmup tick loading
- live tick subscription
- candle building
- decision engine evaluation
- risk engine decisions
- event journaling
- session summary rendering

The orchestrator must no longer assume that approved signals always map to a local `PaperBroker`.

### Execution Backend Interface

Introduce a focused execution backend abstraction with the minimum lifecycle required by the strategy session. The interface should support:

- submitting an approved trade intent
- processing candle-close lifecycle updates
- reporting current open position count
- reconciling broker state when needed
- closing remaining positions during shutdown
- exposing whether the backend is simulated or broker-backed

The interface should stay intentionally small so dry-run and live modes can share the same session loop without leaking venue-specific behavior into orchestration code.

### Simulated Backend

Wrap the current `PaperBroker` behavior behind the execution backend interface for:

- `LiveMode.PAPER`
- `LiveMode.DRY_RUN_LIVE`
- any non-MT5 session path that should stay simulated

This preserves the existing journal, shutdown, and regression behavior that already exists today.

### MT5 Live Backend

Add an MT5-backed execution backend used only when all of the following are true:

- `venue == Venue.MT5`
- `mode == LiveMode.ARMED_LIVE`
- readiness passes
- explicit armed confirmation is present

This backend must:

- convert approved strategy intents into MT5 order requests
- use MT5 symbol mapping from `Mt5Config`
- submit broker-backed entry orders
- synchronize broker positions after entry attempts
- use reconcile-aware logic for shutdown and close flows
- fail closed if the session cannot prove current broker state

### Readiness And Safety Gates

No live MT5 order placement happens unless:

- symbol is supported
- MT5 dependency is installed
- MT5 credentials and symbol mapping are present
- MT5 runtime check passes
- live mode is `armed-live`
- operator supplied explicit armed confirmation

These gates already exist conceptually and must remain in front of the live backend selection.

## Lifecycle Design

### Entry Flow

1. Strategy evaluates a primary candle close.
2. Risk engine approves a signal and produces an execution intent.
3. The session sends that intent to the selected execution backend.
4. In simulated modes, the simulated backend opens the local position.
5. In MT5 armed-live mode, the MT5 backend translates the intent into an `Mt5OrderRequest`, submits it, records the result, and synchronizes broker truth.
6. If order placement or post-submit synchronization is ambiguous, the session records a fail-closed event and stops using local assumptions.

### In-Session Position Management

The simulated backend can keep using candle-based local lifecycle handling.

The MT5 live backend must treat broker truth as authoritative. That means:

- the backend cannot assume local open positions equal broker positions
- synchronization must be used to refresh state
- close and modify decisions must operate against reconciled tickets

This first live bridge does not change the decision model. It only changes how approved lifecycle actions are executed and confirmed.

### Shutdown Flow

Shutdown is the most important supervision point. On session end:

- simulated mode keeps the existing flush and forced-close semantics
- MT5 live mode must first synchronize broker state
- if exactly one actionable live position exists when the strategy expects one close target, shutdown may close it through the MT5 close path
- if the broker state is ambiguous, shutdown must stop and record a fail-closed condition instead of guessing

The final session summary must clearly distinguish:

- positions seen before shutdown
- positions successfully closed during shutdown
- unresolved positions remaining afterward
- whether shutdown was fully finalized

## Journaling And Monitoring

The existing journaling surface should be extended, not replaced. New explicit MT5 live events should include:

- `mt5_live_entry_submitted`
- `mt5_live_entry_result`
- `mt5_live_sync_result`
- `mt5_live_shutdown_reconcile`
- `mt5_live_shutdown_close_result`
- `mt5_live_fail_closed`

These events should carry enough context for operator review:

- project symbol
- venue symbol
- ticket where applicable
- mode
- acceptance result
- retcode and message when MT5 responds
- readiness and reconciliation failures where relevant

The existing monitor and rollout surfaces should remain usable with minimal or no operator workflow changes.

## Read-Only Preflight Sequence

Before implementing or using the new live bridge, the operator should refresh the read-only `R_100` readiness evidence:

1. Run `validate-system` for `R_100` and refresh `artifacts/validation_r100.json`.
2. Run `mt5-rollout-check` for `R_100` in `armed-live` mode using the validation artifact and current journal.
3. Run `mt5-sync` for `R_100` to inspect broker-side position state.
4. Run `mt5-monitor` to render the latest operator-facing snapshot.

This sequence places no new trade and confirms the environment is still in a safe starting state.

## CLI Behavior

The existing `paper-live` command remains the primary session entrypoint. The command behavior changes as follows:

- `paper-live --live-mode paper` remains fully simulated
- `paper-live --live-mode dry-run-live` remains fully simulated, even for `--venue mt5`
- `paper-live --live-mode armed-live --venue mt5 --armed-live` uses the MT5 live execution backend

This keeps the user-facing workflow simple:

- one command for strategy sessions
- one set of readiness expectations
- different execution backends selected by supervised mode

The existing manual MT5 lifecycle commands remain available for direct operator intervention and diagnostics.

## Failure Handling

The system must fail closed for any of the following:

- MT5 readiness failure
- missing armed confirmation
- order placement rejection that leaves state ambiguous
- synchronization failure after a live action
- reconciliation failure during close or shutdown
- multiple broker positions where the session cannot identify the correct target

Fail-closed behavior means:

- do not guess
- do not silently fall back to local-only assumptions
- record the failure explicitly
- leave the session summary in an honest unresolved state

## Test Plan

Add or update focused tests for:

1. backend selection
   - `paper` uses simulated backend
   - `dry-run-live` uses simulated backend
   - `armed-live + mt5 + armed confirmation` uses MT5 live backend
2. entry routing
   - approved signals call MT5 order placement in armed-live mode
   - rejected signals do not call MT5 order placement
3. shutdown handling
   - MT5 live mode synchronizes before shutdown close
   - ambiguous broker state triggers fail-closed behavior
4. CLI gating
   - missing readiness or missing armed confirmation blocks MT5 live routing
5. regression coverage
   - existing dry-run and journal behavior remains intact

Tests should prefer mocks and focused lifecycle assertions over broad end-to-end simulations.

## Implementation Sequence

1. Run the read-only `R_100` preflight sequence and capture current readiness evidence.
2. Introduce the execution backend abstraction around simulated trading.
3. Refactor `run_live_paper()` to use the backend abstraction instead of directly constructing `PaperBroker`.
4. Implement the MT5 live backend for entry, sync, reconcile, and shutdown close flows.
5. Extend journaling for MT5 live lifecycle visibility.
6. Add focused tests for backend selection, live routing, and fail-closed shutdown behavior.
7. Re-run the supervised dry-run evidence path to confirm no regression.
8. Promote the same path to a supervised MT5 armed-live pilot only after preflight and dry-run remain clean.

## Success Criteria

This design is successful when:

- the operator can run one strategy-session command across paper, dry-run-live, and armed-live
- `armed-live + venue mt5` truly routes approved strategy intents to MT5
- dry-run behavior stays unchanged and validated
- broker-truth reconciliation is used for live lifecycle actions
- ambiguous broker state halts execution instead of being guessed through
- monitoring and journal output make operator review straightforward
