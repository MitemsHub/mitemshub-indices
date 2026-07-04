# Phase 2 Paper-Live Reliability Design

## Summary

Phase 2 strengthens the operational trustworthiness of the paper-live trading path. The goal is to ensure that live paper sessions shut down cleanly, account for unfinished market state deterministically, reset risk controls on explicit session boundaries, and produce summaries that accurately reflect what happened during the run.

This phase stays strictly paper-only. It does not enable or scaffold real-money execution.

## Context

Phase 1 improved research trust by adding structured artifacts, model persistence, richer journaling, and stronger validation coverage. The next highest-value gap is the live paper runner. It currently streams ticks, generates trades, and journals outcomes, but its end-of-run behavior is not as rigorous as the backtest path.

That gap matters because live paper results are only useful if the final accounting is complete and reproducible. A paper session that exits without flushing incomplete state can make expectancy, drawdown, and risk behavior look better or worse than they really were.

## Goals

1. Make live paper shutdown behavior deterministic and auditable.
2. Flush remaining candle state and process final trade outcomes when a run ends.
3. Close or explicitly account for open paper positions at shutdown.
4. Reset daily risk controls using timestamp-based session boundaries.
5. Expand the live paper summary and journal to better describe run-end state.
6. Add targeted automated tests for these behaviors.

## Non-Goals

1. No real-money Deriv execution.
2. No live order placement scaffolding.
3. No advanced slippage or market-impact modeling in this phase.
4. No dashboard or external monitoring service in this phase.

## Design Principles

1. Keep the live paper path aligned with the existing backtest accounting model.
2. Prefer explicit summaries over silent assumptions.
3. Base resets and shutdown behavior on market timestamps rather than implicit wall-clock behavior.
4. Add only the minimum new state needed to make the live runner reliable.

## Scope

### 1. Graceful Live Shutdown

When the live paper loop ends because of duration, tick count, or another planned stop condition, the runner should not simply return the current counters. It should execute a shutdown finalization sequence.

That sequence should:

1. Flush any remaining candle-builder state.
2. Process resulting final candle outcomes through the broker.
3. Update risk state and the journal for any resulting closes.
4. Force-close any still-open paper positions using the final available candle.
5. Record enough summary data to make the final treatment explicit.

### 2. Session-Aware Risk Resets

The risk engine already supports `reset_daily_limits()`, but the live paper path does not currently drive it from timestamp boundaries.

Phase 2 should add lightweight session tracking so that:

1. Risk limits can reset once per new trading day or explicit session boundary.
2. The reset is deterministic in tests.
3. The behavior is local to paper-live operation and does not introduce hidden wall-clock coupling into the research path.

### 3. Stronger Live Summary

The current live paper summary captures high-level counters, but it should better explain how the run ended and what state remained.

The expanded summary should include fields such as:

1. Whether a final flush occurred.
2. How many trades were closed during shutdown finalization.
3. How many positions remained open before final forced closure.
4. Whether any positions could not be finalized cleanly.
5. The final equity after all shutdown accounting steps.

### 4. Richer Journal Metadata

The journal should preserve finalization-relevant events so later analysis can distinguish:

1. trades closed during normal candle processing,
2. trades closed during shutdown flush,
3. trades closed by forced end-of-run liquidation,
4. session-boundary resets.

This does not require a new storage system. It extends the current event-style JSONL journal model.

### 5. Targeted Test Expansion

Phase 2 should add tests where live-paper behavior is currently least trustworthy.

High-priority cases:

1. Run termination with an incomplete final candle.
2. Run termination with one or more open positions.
3. Risk reset behavior across timestamp day boundaries.
4. Final summary correctness after shutdown processing.
5. Journal event emission for flush, forced close, and session reset actions.

## Proposed Changes By Module

### `src/synthetic_trader/live/paper_runner.py`

Add an explicit finalization step that mirrors the backtest path more closely and expands the returned run summary.

### `src/synthetic_trader/risk/engine.py`

Keep the current risk engine simple, but make it easier for the live runner to drive deterministic session resets from timestamps.

### `src/synthetic_trader/execution/paper.py`

Reuse existing force-close behavior where possible. Only change broker behavior if tests reveal a gap in finalization handling.

### `src/synthetic_trader/journal/trade_journal.py`

Extend event recording so shutdown and session-reset actions are distinguishable in later analysis.

### `tests/`

Add focused tests for live-paper shutdown, risk reset timing, and final summary correctness.

## Data Flow Impact

The main live trading flow remains:

1. warmup history,
2. live ticks,
3. candle construction,
4. trade evaluation,
5. risk approval,
6. paper execution,
7. journaling.

The main addition is a deterministic finalization tail:

1. stop condition reached,
2. final candle flush,
3. pending position resolution,
4. risk and journal updates,
5. final summary emission.

## Error Handling

1. If no final candle is available for forced closure, the summary must report that explicitly.
2. If shutdown closes trades, those closures must be journaled distinctly from ordinary candle exits.
3. Session resets must be idempotent for a given boundary and must not fire repeatedly on every tick after a rollover.

## Testing Strategy

1. Add small deterministic tests around the live runner rather than relying on long async integration runs.
2. Reuse the existing synthetic tick and candle patterns where possible.
3. Treat shutdown accounting as correctness-critical, not just operational detail.

## Success Criteria

Phase 2 is complete when all of the following are true:

1. The live paper runner finalizes remaining market state at shutdown.
2. Open paper positions are either closed deterministically or reported explicitly as unresolved.
3. Session-boundary risk resets occur deterministically from timestamps.
4. The live summary reflects shutdown and finalization behavior accurately.
5. The automated test suite covers the new live-paper reliability behavior and still passes in full.

## Follow-On Phase

Once Phase 2 is complete, the next logical phase is paper-trading realism and operational insight beyond reliability, such as more nuanced execution assumptions, stronger reporting for run comparisons, and possibly a lightweight operator-facing monitoring surface.
