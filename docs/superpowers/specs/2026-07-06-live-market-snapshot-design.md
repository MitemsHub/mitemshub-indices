# Live Market Snapshot Design

## Purpose

This design adds a read-only live market snapshot command for `R_75` and `R_100` so the operator can ask, in effect, "what is the market doing right now?" and receive both trader-friendly guidance and structured metrics.

The feature is meant to bridge the gap between static screenshots and full supervised session runs. It should provide live context without placing any order, modifying broker state, or entering a supervised execution mode.

## Scope

This design covers:

1. A new read-only CLI command that fetches recent live market data for `R_75` or `R_100`.
2. Reuse of the current candle, feature, regime, decision, and risk pipeline for on-demand live interpretation.
3. Dual-format output:
   - a trader-style plain-English briefing
   - structured fields for inspection and future automation

## Non-Goals

- Placing live trades or simulating execution.
- Modifying MT5 state, broker state, or account state.
- Replacing `paper-live`, `validate-system`, or rollout commands.
- Adding order book, DOM, or exchange-style volume analysis.
- Building a graphical dashboard in this iteration.

## Current Problem

The project can already:

- validate system readiness
- run seeded live dry-runs
- monitor MT5 runtime and lifecycle state
- route supervised live sessions through a stronger execution path

But it cannot yet answer the operator's immediate market question in a compact form, such as:

- what is `Volatility 75` doing right now?
- is this a valid setup or not?
- what kind of environment is this?
- what should I wait for?

The current workarounds are:

- asking the user for a screenshot
- running a longer live dry-run session

Both are weaker than a dedicated read-only market reader.

## Design Goals

- Keep the feature strictly read-only.
- Reuse the same analysis stack already trusted by the bot.
- Make the output understandable to a trader first and an engineer second.
- Avoid coupling the new command to execution, journaling, or order placement.
- Keep the command fast enough for repeated use during a live session.

## Approaches Considered

### Option 1: Dedicated Read-Only Snapshot Command

Add a new CLI command that fetches recent live ticks, builds current candles, runs the existing analysis pipeline, and renders a market snapshot.

Pros:

- clean separation from execution
- easy to reason about
- directly answers the operator's real question
- reusable for both `R_75` and `R_100`

Cons:

- requires a small new live-analysis module
- requires custom output formatting

### Option 2: Reuse `paper-live` In A Short Analysis Mode

Run the live session loop for a very short period and interpret the resulting state as a snapshot.

Pros:

- reuses existing live data flow
- less new code at first glance

Cons:

- mixes market reading with session orchestration
- heavier than necessary
- output is built for session summaries, not live trader interpretation

### Option 3: Raw Metrics Dump Only

Expose live indicators and structure fields without a trader briefing.

Pros:

- minimal implementation
- useful for debugging

Cons:

- weak operator usability
- does not satisfy the real-world trading support goal

## Selected Approach

Use Option 1: Dedicated Read-Only Snapshot Command.

This keeps the market-reading problem separate from execution and lets the project produce a direct answer to live market questions without side effects.

## Command Design

### CLI Surface

Add a new command such as:

`live-snapshot`

The command should support:

- `--symbol` with `R_75` and `R_100`
- `--warmup-count` for recent historical tick context
- `--timeframe` for primary candle timeframe
- `--higher-timeframe` for higher context timeframe
- `--max-live-ticks` for a short bounded live read window
- `--app-id` and optional token support through the existing Deriv credential path

Defaults should align with the current live stack:

- primary timeframe `60`
- higher timeframe `300`
- enough warmup history to produce a valid snapshot
- a small bounded live window so the command sees current activity without hanging indefinitely

### Read-Only Behavior

The command must:

- open a live Deriv market data connection
- fetch recent history
- optionally observe a short burst of live ticks
- build current candles
- run feature, regime, structure, model, and risk logic
- print a snapshot

The command must not:

- route into `PaperBroker`
- route into MT5
- route through supervised execution
- create or manage open positions

## Analysis Flow

### Market Data

The feature should reuse the existing Deriv WebSocket data path. It should fetch:

- warm historical ticks for context
- a bounded current live tick slice for freshness

This avoids building a second transport implementation.

### Candle Construction

The feature should reuse the same candle-building logic used elsewhere in the project. It should produce:

- primary timeframe candles
- higher timeframe candles

The snapshot must be grounded in enough recent candles to satisfy the current `DecisionEngine` minimum history requirement.

### Feature And Regime Pipeline

The feature should reuse:

- `build_snapshot()`
- `classify_regime()`
- `market_structure_features()`
- existing indicator calculations

This ensures the operator sees the same analytical worldview the strategy already uses.

### Decision And Risk Interpretation

The feature should reuse the existing `DecisionEngine` and `RiskEngine`, but in a read-only interpretive mode.

That means:

- if a valid signal exists, the snapshot can say the setup is valid
- if confidence is too low or risk rules reject the setup, the snapshot must explain why

No execution intent should be submitted anywhere. The command uses these layers only to classify and explain the current market.

## Output Design

### Trader Briefing

The command should render a trader-first section that answers:

- trade status: valid or not valid
- direction bias: buy, sell, or none
- regime: trend up, trend down, range, compression, volatile, or unknown
- confidence summary
- why the setup is valid or not valid
- what to wait for next

Examples of briefing language:

- `trade_status=valid`
- `direction_bias=buy`
- `briefing=trend continuation candidate; structure and regime aligned`

Or:

- `trade_status=not_valid`
- `direction_bias=none`
- `briefing=movement is active but confidence is below threshold; wait for cleaner structure`

### Structured Fields

The command should also print compact fields such as:

- symbol
- timeframe
- higher timeframe
- regime
- model long probability
- confidence
- recent structure notes
- risk approval
- reasons for rejection if invalid
- current close
- ATR and volatility context

These fields should remain machine-readable enough for logs and future tooling.

## Suggested Module Structure

Introduce a small live-analysis module that is separate from `paper_runner.py`.

Recommended responsibilities:

- data collection for a bounded live snapshot
- conversion from ticks to candle histories
- snapshot assembly
- trader-style rendering

This should stay focused and read-only rather than being folded into the execution layer.

## Error Handling

The command should fail clearly for:

- missing live dependency
- transport connection failure
- insufficient historical data
- unsupported symbol
- no meaningful live ticks received in the requested window

Errors should be explicit and operator-readable. The command should not silently return a misleading empty snapshot.

## Testing Strategy

Add focused tests for:

1. live snapshot command output
   - trader briefing is present
   - structured fields are present
2. read-only behavior
   - no execution backend is used
   - no MT5 calls are made
3. data-path correctness
   - fake client history plus live ticks produce enough candles
4. invalid setup interpretation
   - low-confidence or insufficient-history cases render clear rejection reasons
5. valid setup interpretation
   - aligned structure and model produce a valid trader briefing

Tests should use fake market data clients and avoid real live transport.

## Success Criteria

This design is successful when:

- the operator can ask for a live `R_75` or `R_100` snapshot through one command
- the output is understandable in trader language
- the output is backed by the same analytical stack already used by the strategy
- the command remains strictly read-only
- the feature is fast enough to run repeatedly during a live session
