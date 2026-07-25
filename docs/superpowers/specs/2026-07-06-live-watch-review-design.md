# Live Watch Review Design

## Purpose

This design adds a dedicated `live-watch-review` command that reads the `live-watch` JSONL journal and turns recent alert history into a compact trader-facing review surface.

The goal is to make the watch trail usable during or after a monitoring session without forcing the operator to manually inspect raw JSONL lines.

## Scope

This design covers:

1. A new CLI command for reviewing stored `live-watch` alerts.
2. Journal parsing for the existing `live-watch` JSONL output.
3. Optional filtering for symbol, call type, and valid-only review.
4. A compact summary of the latest meaningful watch state.
5. A trader-readable listing of recent alerts.

## Non-Goals

- Changing live market analysis logic.
- Changing watch transition rules.
- Replacing `live-watch` or `live-snapshot`.
- Building a GUI or dashboard.
- Adding notifications or broker actions.

## Current Problem

The project now has a useful `live-watch` command and a working JSONL journal trail, but the journal is only useful if the operator manually opens and interprets raw lines.

This leaves a gap between:

- real-time watch output
- and
- practical review of what the watch engine has been saying over time

## Design Goals

- Keep the feature read-only.
- Reuse the existing `live-watch` journal format.
- Make recent alert history easy to inspect quickly.
- Preserve trader-readable output instead of exposing raw JSON.
- Keep the new surface separate from MT5 monitoring and paper-live summaries.

## Approaches Considered

### Option 1: Tail Raw Journal Lines

Add a thin command that prints the last `N` JSONL lines from the `live-watch` journal.

Pros:

- fastest to build
- minimal logic

Cons:

- still noisy
- not trader-friendly
- forces the operator to parse raw payloads

### Option 2: Dedicated `live-watch-review` Command

Add a focused CLI surface that reads the watch journal, filters alerts, summarizes the latest state, and renders recent alerts cleanly.

Pros:

- best operator usability
- fits current CLI architecture
- keeps watch review separate from unrelated monitor tools

Cons:

- slightly more implementation than raw tailing

### Option 3: Extend Existing Monitor Commands

Fold watch journal review into `monitor-live` or `mt5-monitor`.

Pros:

- fewer commands
- some renderer reuse

Cons:

- mixes different monitoring concepts
- harder to keep clear
- weaker long-term maintainability

## Selected Approach

Use Option 2: a dedicated `live-watch-review` command.

This is the cleanest fit for the existing architecture because the repository already uses separate builder and renderer helpers for distinct operator surfaces. `live-watch-review` should follow that pattern rather than overload other monitoring commands.

## Command Design

### CLI Surface

Add a new command:

`live-watch-review`

Supported arguments:

- `--journal` with default `journals/live_watch_alerts.jsonl`
- `--symbol` optional symbol filter
- `--limit` number of recent alerts to show, defaulting to a trader-friendly small value such as `5`
- `--call` optional call filter such as `stand_aside`, `buy_candidate`, or `sell_candidate`
- `--valid-only` to show only approved trade candidates

### Expected Use Cases

Examples:

- review the latest few alerts quickly
- review only `R_75`
- review only valid candidates
- review only `buy_candidate` transitions

## Data Flow

1. Read the JSONL journal from disk.
2. Parse only `live-watch` alert entries.
3. Apply optional filters.
4. Identify the latest alert in the filtered set as the summary state.
5. Render a compact summary plus recent alert list.

The feature should not mutate journals or trigger any live market activity.

## Snapshot Design

Introduce a compact review snapshot builder, likely in the existing monitoring surface or in the live watch module, with these responsibilities:

- extract relevant watch alerts from JSONL lines
- filter by symbol if requested
- filter by call if requested
- filter to valid setups when requested
- produce:
  - `latest_call`
  - `latest_symbol`
  - `latest_trade_status`
  - `latest_direction_bias`
  - `latest_regime`
  - `latest_confidence`
  - `latest_current_close`
  - `latest_wait_for`
  - `alerts`
  - `alert_count`

If no alerts match the filters, return a safe empty snapshot instead of failing.

## Output Design

### Summary Section

The top of the output should show the latest filtered watch state, for example:

- latest call
- symbol
- trade status
- direction bias
- regime
- confidence
- current close
- wait-for guidance
- number of alerts in scope

### Recent Alerts Section

Below the summary, print recent alerts in newest-first order using the existing trader-readable alert style.

Valid alerts should include:

- `entry_area`
- `stop_area`
- `target_area`
- `entry`
- `stop_loss`
- `take_profit`
- `reward_risk`

Invalid alerts should stay concise and should not show empty trade-level fields.

## Error Handling

The command should fail clearly for:

- missing journal file
- invalid JSONL lines that prevent parsing

For empty-but-valid cases, the command should return a safe empty review snapshot rather than erroring.

## File Plan

- Modify: `src/synthetic_trader/cli.py`
  - add `live-watch-review` parser and handler
- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - add review parsing, filtering, and rendering helpers if kept close to the watch feature
- Optionally modify: `src/synthetic_trader/monitoring/surface.py`
  - only if review helpers fit better with existing monitor snapshot builders
- Modify: `tests/test_live_market_snapshot.py`
  - add focused review tests

## Testing Strategy

Add focused tests for:

1. journal parsing
   - reads JSONL watch alerts correctly
   - ignores irrelevant lines if needed
2. filtering
   - symbol filter
   - call filter
   - valid-only filter
3. empty-state handling
   - missing matching alerts returns a safe empty snapshot
4. rendering
   - summary is compact and clear
   - recent alert listing remains trader-readable
5. CLI
   - command prints rendered review output
   - missing journal path returns non-zero

## Success Criteria

This design is successful when:

- the operator can review recent `live-watch` history with a single command
- the latest meaningful watch state is visible immediately
- the recent alert trail is readable without opening raw JSONL
- valid trade candidates retain their enriched trade-level package
- the feature remains read-only and does not alter live monitoring behavior
