# Phase 2 Paper-Live Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `paper-live` path shut down deterministically, reset daily risk controls from timestamps, and produce accurate final summaries and journal events.

**Architecture:** Extend the existing live runner with a small finalization tail rather than redesigning the trading loop. Keep the broker and risk engine mostly intact, add timestamp-driven reset hooks, and make shutdown behavior explicit through summary fields and journal events.

**Tech Stack:** Python 3.11+, standard library `asyncio` and `dataclasses`, current `unittest` suite, existing CLI/live/risk/journal modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_paper_runner.py`
  - Focused deterministic tests for live-paper shutdown finalization, session resets, and final summary fields.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Add orderly shutdown finalization, session-boundary handling, and richer summary fields.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\risk\engine.py`
  - Add lightweight timestamp/session-reset support if the tests require explicit state tracking.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\journal\trade_journal.py`
  - Record shutdown-flush, forced-close, and session-reset events distinctly.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\paper.py`
  - Modify only if the new shutdown tests reveal a missing broker finalization behavior.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Print any new live summary fields when `paper-live` finishes.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_trade_journal.py`
  - Extend coverage for new live-run event types.

## Task 1: Add Live Shutdown Finalization Tests

**Files:**
- Create: `tests/test_live_paper_runner.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Test: `tests/test_live_paper_runner.py`

- [ ] **Step 1: Write the failing shutdown-finalization tests**

```python
import asyncio
import unittest
from unittest.mock import patch

from synthetic_trader.domain import Tick
from synthetic_trader.live.paper_runner import run_live_paper


class _FakeClient:
    def __init__(self, warmup, live_ticks):
        self._warmup = warmup
        self._live_ticks = live_ticks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def ticks_history(self, symbol: str, count: int):
        return list(self._warmup)

    async def subscribe_ticks(self, symbol: str):
        for tick in self._live_ticks:
            yield tick


class LivePaperRunnerTests(unittest.TestCase):
    def test_run_live_paper_finalizes_open_positions_on_shutdown(self) -> None:
        warmup = []
        live_ticks = [
            Tick(symbol="R_75", epoch=1, price=100.0),
            Tick(symbol="R_75", epoch=20, price=100.1),
            Tick(symbol="R_75", epoch=40, price=100.0),
            Tick(symbol="R_75", epoch=59, price=100.4),
        ] * 90

        with patch(
            "synthetic_trader.live.paper_runner.DerivWebSocketClient",
            return_value=_FakeClient(warmup, live_ticks),
        ):
            summary = asyncio.run(
                run_live_paper(
                    symbol="R_75",
                    duration_sec=0,
                    max_live_ticks=len(live_ticks),
                    warmup_count=0,
                    timeframe_sec=60,
                    higher_timeframe_sec=300,
                )
            )

        self.assertGreaterEqual(summary.shutdown_closed_trades, 0)
        self.assertEqual(summary.unresolved_positions, 0)
        self.assertTrue(summary.finalized)
```

- [ ] **Step 2: Run the live runner tests to verify they fail**

Run: `python -m unittest tests.test_live_paper_runner -v`
Expected: `AttributeError` for missing summary fields like `shutdown_closed_trades`, `unresolved_positions`, or `finalized`

- [ ] **Step 3: Extend the live summary shape**

```python
# src/synthetic_trader/live/paper_runner.py
@dataclass(frozen=True)
class LivePaperSummary:
    symbol: str
    live_ticks: int
    warmup_ticks: int
    signals: int
    approved_signals: int
    rejected_signals: int
    closed_trades: int
    shutdown_closed_trades: int
    open_positions_before_shutdown: int
    unresolved_positions: int
    finalized: bool
    final_equity: float
    model_version: str
```

- [ ] **Step 4: Add the shutdown finalization tail**

```python
# src/synthetic_trader/live/paper_runner.py
shutdown_closed_trades = 0
open_positions_before_shutdown = len(broker.positions)
unresolved_positions = 0
finalized = False

flushed = builders.flush()
final_primary = flushed.get(timeframe_sec)
if final_primary is not None:
    _store_closed_candles(flushed, histories)
    for outcome in broker.on_candle(final_primary):
        shutdown_closed_trades += 1
        closed_trades += 1
        risk_engine.register_outcome(outcome)
        journal.record_outcome(outcome)
        journal.record_event("shutdown_flush_close", {"position_id": outcome.position_id, "symbol": outcome.symbol})
        journal.teach(model, outcome)
    for outcome in broker.close_all(final_primary):
        shutdown_closed_trades += 1
        closed_trades += 1
        risk_engine.register_outcome(outcome)
        journal.record_outcome(outcome)
        journal.record_event("shutdown_forced_close", {"position_id": outcome.position_id, "symbol": outcome.symbol})
        journal.teach(model, outcome)

unresolved_positions = len(broker.positions)
finalized = True
```

- [ ] **Step 5: Run the shutdown-finalization tests to verify they pass**

Run: `python -m unittest tests.test_live_paper_runner -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/live/paper_runner.py tests/test_live_paper_runner.py
git commit -m "feat: finalize paper live shutdown accounting"
```

## Task 2: Add Timestamp-Driven Session Reset Coverage

**Files:**
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Modify: `src/synthetic_trader/risk/engine.py`
- Test: `tests/test_live_paper_runner.py`
- Test: `tests/test_risk_engine.py`

- [ ] **Step 1: Write the failing session reset tests**

```python
def test_run_live_paper_resets_daily_limits_once_on_new_day(self) -> None:
    warmup = []
    live_ticks = [
        Tick(symbol="R_75", epoch=86341, price=100.0),
        Tick(symbol="R_75", epoch=86360, price=100.1),
        Tick(symbol="R_75", epoch=86420, price=100.3),
        Tick(symbol="R_75", epoch=86459, price=100.5),
    ] * 50

    with patch(
        "synthetic_trader.live.paper_runner.DerivWebSocketClient",
        return_value=_FakeClient(warmup, live_ticks),
    ):
        summary = asyncio.run(
            run_live_paper(
                symbol="R_75",
                duration_sec=0,
                max_live_ticks=len(live_ticks),
                warmup_count=0,
                timeframe_sec=60,
                higher_timeframe_sec=300,
            )
        )

    self.assertGreaterEqual(summary.session_resets, 1)
```

```python
def test_reset_daily_limits_is_safe_to_call_multiple_times_same_day(self) -> None:
    engine = RiskEngine(RiskConfig(starting_equity=1000.0))
    engine.reset_daily_limits()
    engine.reset_daily_limits()
    self.assertEqual(engine.state.day_start_equity, 1000.0)
```

- [ ] **Step 2: Run the session-reset tests to verify they fail**

Run: `python -m unittest tests.test_live_paper_runner tests.test_risk_engine -v`
Expected: `AttributeError` for missing `session_resets` in the live summary or missing reset-tracking behavior

- [ ] **Step 3: Add deterministic session-boundary tracking**

```python
# src/synthetic_trader/live/paper_runner.py
current_session_day: int | None = None
session_resets = 0

def _day_bucket(epoch: float) -> int:
    return int(epoch // 86400)
```

```python
# src/synthetic_trader/live/paper_runner.py
tick_day = _day_bucket(tick.epoch)
if current_session_day is None:
    current_session_day = tick_day
elif tick_day != current_session_day:
    risk_engine.reset_daily_limits()
    journal.record_event("session_reset", {"symbol": symbol, "epoch": tick.epoch, "session_day": tick_day})
    current_session_day = tick_day
    session_resets += 1
```

- [ ] **Step 4: Return the session-reset count in the summary**

```python
# src/synthetic_trader/live/paper_runner.py
return LivePaperSummary(
    symbol=symbol,
    live_ticks=live_ticks,
    warmup_ticks=warmup_ticks,
    signals=signals,
    approved_signals=approved,
    rejected_signals=rejected,
    closed_trades=closed_trades,
    shutdown_closed_trades=shutdown_closed_trades,
    open_positions_before_shutdown=open_positions_before_shutdown,
    unresolved_positions=unresolved_positions,
    finalized=finalized,
    session_resets=session_resets,
    final_equity=risk_engine.state.equity,
    model_version=model.version,
)
```

- [ ] **Step 5: Run the session-reset tests again**

Run: `python -m unittest tests.test_live_paper_runner tests.test_risk_engine -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/live/paper_runner.py src/synthetic_trader/risk/engine.py tests/test_live_paper_runner.py tests/test_risk_engine.py
git commit -m "feat: add timestamp driven live session resets"
```

## Task 3: Journal Shutdown And Session Events Clearly

**Files:**
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Test: `tests/test_trade_journal.py`
- Test: `tests/test_live_paper_runner.py`

- [ ] **Step 1: Write the failing journal-event tests**

```python
def test_journal_records_shutdown_event_payload(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        journal = TradeJournal(Path(tmpdir) / "journal.jsonl")
        journal.record_event(
            "shutdown_flush_close",
            {"symbol": "R_75", "position_id": "abc123", "epoch": 600.0},
        )
        lines = journal.path.read_text(encoding="utf-8").splitlines()

    payload = json.loads(lines[0])
    self.assertEqual(payload["type"], "shutdown_flush_close")
    self.assertEqual(payload["position_id"], "abc123")
```

- [ ] **Step 2: Run the journal-event tests to verify they fail only if event payloads are incomplete**

Run: `python -m unittest tests.test_trade_journal tests.test_live_paper_runner -v`
Expected: live-run event assertions fail until shutdown/session-reset paths emit the new events consistently

- [ ] **Step 3: Emit explicit live-run finalization events**

```python
# src/synthetic_trader/live/paper_runner.py
journal.record_event(
    "shutdown_summary",
    {
        "symbol": symbol,
        "live_ticks": live_ticks,
        "shutdown_closed_trades": shutdown_closed_trades,
        "unresolved_positions": unresolved_positions,
        "session_resets": session_resets,
    },
)
```

- [ ] **Step 4: Verify the journal-event tests pass**

Run: `python -m unittest tests.test_trade_journal tests.test_live_paper_runner -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/journal/trade_journal.py src/synthetic_trader/live/paper_runner.py tests/test_trade_journal.py tests/test_live_paper_runner.py
git commit -m "feat: journal live shutdown and session events"
```

## Task 4: Expose Richer Paper-Live Summary Output

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Test: `tests/test_live_paper_runner.py`

- [ ] **Step 1: Write the failing summary-output tests**

```python
from synthetic_trader.cli import main


def test_paper_live_summary_prints_shutdown_fields(self) -> None:
    with patch(
        "synthetic_trader.cli.run_live_paper",
        return_value=LivePaperSummary(
            symbol="R_75",
            live_ticks=50,
            warmup_ticks=100,
            signals=4,
            approved_signals=2,
            rejected_signals=2,
            closed_trades=2,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=1,
            final_equity=1002.5,
            model_version="unit-test",
        ),
    ):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["paper-live", "--symbol", "R_75", "--duration-sec", "1"])

    rendered = output.getvalue()
    self.assertEqual(exit_code, 0)
    self.assertIn("shutdown_closed_trades=1", rendered)
    self.assertIn("session_resets=1", rendered)
    self.assertIn("finalized=True", rendered)
```

- [ ] **Step 2: Run the summary-output tests to verify they fail**

Run: `python -m unittest tests.test_live_paper_runner -v`
Expected: CLI output assertions fail until the new fields are printed

- [ ] **Step 3: Print the new summary fields in the CLI**

```python
# src/synthetic_trader/cli.py
print(f"shutdown_closed_trades={summary.shutdown_closed_trades}")
print(f"open_positions_before_shutdown={summary.open_positions_before_shutdown}")
print(f"unresolved_positions={summary.unresolved_positions}")
print(f"session_resets={summary.session_resets}")
print(f"finalized={summary.finalized}")
```

- [ ] **Step 4: Re-run the summary-output tests**

Run: `python -m unittest tests.test_live_paper_runner -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/live/paper_runner.py tests/test_live_paper_runner.py
git commit -m "feat: expose paper live shutdown summary fields"
```

## Task 5: Run Full Reliability Regression

**Files:**
- Modify: `tests/test_live_paper_runner.py`
- Modify: `tests/test_trade_journal.py`
- Modify: `tests/test_risk_engine.py`

- [ ] **Step 1: Add one end-to-end reliability regression test**

```python
def test_live_paper_run_finishes_with_consistent_summary_accounting(self) -> None:
    warmup = []
    live_ticks = [
        Tick(symbol="R_75", epoch=1, price=100.0),
        Tick(symbol="R_75", epoch=20, price=100.1),
        Tick(symbol="R_75", epoch=40, price=100.0),
        Tick(symbol="R_75", epoch=59, price=100.4),
    ] * 120

    with patch(
        "synthetic_trader.live.paper_runner.DerivWebSocketClient",
        return_value=_FakeClient(warmup, live_ticks),
    ):
        summary = asyncio.run(
            run_live_paper(
                symbol="R_75",
                duration_sec=0,
                max_live_ticks=len(live_ticks),
                warmup_count=0,
                timeframe_sec=60,
                higher_timeframe_sec=300,
            )
        )

    self.assertTrue(summary.finalized)
    self.assertGreaterEqual(summary.closed_trades, summary.shutdown_closed_trades)
    self.assertGreaterEqual(summary.final_equity, 0.0)
```

- [ ] **Step 2: Run the focused reliability slice**

Run: `python -m unittest tests.test_live_paper_runner tests.test_trade_journal tests.test_risk_engine tests.test_paper_broker -v`
Expected: `OK`

- [ ] **Step 3: Run the full test suite**

Run: `python -m unittest discover -s tests`
Expected:

```text
........................................
----------------------------------------------------------------------
Ran <updated-count> tests in <time>s

OK
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_live_paper_runner.py tests/test_trade_journal.py tests/test_risk_engine.py
git commit -m "test: validate paper live reliability end to end"
```

## Spec Coverage Check

- Graceful live shutdown: covered by Task 1 and Task 5
- Session-aware risk resets: covered by Task 2
- Stronger live summary: covered by Task 1 and Task 4
- Richer journal metadata: covered by Task 3
- Targeted test expansion: covered by Tasks 1 through 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task names exact files, commands, and concrete code snippets
- Each verification step states the expected test outcome explicitly

## Type Consistency Check

- `shutdown_closed_trades`, `open_positions_before_shutdown`, `unresolved_positions`, `finalized`, and `session_resets` are used consistently as `LivePaperSummary` fields
- `shutdown_flush_close`, `shutdown_forced_close`, `session_reset`, and `shutdown_summary` are the event names used consistently across journal and live-run tasks
- `_FakeClient` is the shared async test fixture used by the live runner tests
