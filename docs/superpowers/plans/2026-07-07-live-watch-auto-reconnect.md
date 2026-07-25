# Live Watch Auto-Reconnect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `live-watch` survive transport failures by auto-reconnecting, rebuilding baseline state from fresh history, and resuming candle-close decisions without emitting stale or synthetic alerts.

**Architecture:** Keep the existing emitted alert and review pipeline intact. Extend `market_snapshot.py` with transport-event records, a reconnect-aware watch loop, and a small amount of configurable reconnect state. Reuse the existing `collect_live_snapshot_ticks()` warmup path to rebuild the baseline after reconnect, then reset `previous_state` and `context_cooldown_remaining` before resuming normal transition logic.

**Tech Stack:** Python 3.11+, `asyncio`, `json`, `pathlib`, `unittest`, `unittest.mock`

---

## File Structure

- `src/synthetic_trader/live/market_snapshot.py`
  - Gains transport-event record helpers, reconnect error detection, and reconnect-aware watch-loop control flow.
- `src/synthetic_trader/cli.py`
  - Adds optional `live-watch` flags for reconnect control and passes them into `run_live_watch()`.
- `tests/test_live_market_snapshot.py`
  - Adds focused CLI, loop, and review tests for reconnect behavior and transport journaling.

### Task 1: Lock Reconnect Behavior Into Failing Tests

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing CLI test for reconnect flags**

```python
def test_live_watch_command_passes_reconnect_controls(self) -> None:
    with patch("synthetic_trader.cli.run_live_watch", return_value=[]) as run_mock:
        exit_code = main(
            [
                "live-watch",
                "--symbol",
                "R_75",
                "--max-reconnects",
                "4",
                "--reconnect-backoff-sec",
                "2",
            ]
        )

    self.assertEqual(exit_code, 0)
    self.assertEqual(run_mock.call_args.kwargs["max_reconnects"], 4)
    self.assertEqual(run_mock.call_args.kwargs["reconnect_backoff_sec"], 2)
```

- [ ] **Step 2: Write the failing loop test for reconnect + baseline rebuild**

```python
def test_run_live_watch_rebuilds_baseline_after_transport_failure(self) -> None:
    warmup_history = [
        [Tick(symbol="R_75", epoch=0, price=100.0)],
        [Tick(symbol="R_75", epoch=120, price=101.0)],
    ]
    tick_batches = [
        [
            Tick(symbol="R_75", epoch=61, price=100.5),
            RuntimeError("client is not connected"),
        ],
        [
            Tick(symbol="R_75", epoch=181, price=101.5),
            Tick(symbol="R_75", epoch=241, price=101.8),
        ],
    ]
    snapshots = [
        {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": "none",
            "regime": "range",
            "confidence": 0.52,
            "wait_for": "wait for clearer structure",
            "briefing": "baseline before disconnect",
            "symbol": "R_75",
        },
        {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": "buy",
            "regime": "trend_up",
            "confidence": 0.56,
            "wait_for": "wait for bullish continuation confirmation",
            "briefing": "baseline after reconnect",
            "symbol": "R_75",
        },
        {
            "call": "buy_candidate",
            "trade_status": "valid",
            "direction_bias": "buy",
            "regime": "trend_up",
            "confidence": 0.66,
            "wait_for": "wait for a clean bullish continuation close",
            "briefing": "trend continuation aligned with structure and regime",
            "symbol": "R_75",
        },
    ]
    journal_path = Path("journals/test_live_watch_reconnect.jsonl")
    if journal_path.exists():
        journal_path.unlink()

    async def fake_collect(*, symbol: str, warmup_count: int, max_live_ticks: int, app_id: str | None = None):
        return warmup_history.pop(0)

    async def fake_watch(**kwargs):
        batch = tick_batches.pop(0)
        ticks = []
        for item in batch:
            if isinstance(item, Exception):
                raise item
            ticks.append(item)
        return ticks

    with patch("synthetic_trader.live.market_snapshot.collect_live_snapshot_ticks", side_effect=fake_collect):
        with patch("synthetic_trader.live.market_snapshot.analyze_live_snapshot", side_effect=snapshots):
            with patch("synthetic_trader.live.market_snapshot.watch_live_ticks", side_effect=fake_watch):
                alerts = asyncio.run(
                    run_live_watch(
                        symbol="R_75",
                        warmup_count=1,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=str(journal_path),
                        max_alerts=1,
                    )
                )

    journal_records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    self.assertEqual(len(alerts), 1)
    self.assertEqual(alerts[0]["call"], "buy_candidate")
    self.assertEqual(journal_records[0]["record_type"], "watch_transport")
    self.assertEqual(journal_records[0]["event"], "reconnect_attempt")
    self.assertEqual(journal_records[1]["event"], "reconnect_rebaseline_ok")
```

- [ ] **Step 3: Write the failing loop test for fail-closed reconnect exhaustion**

```python
def test_run_live_watch_journals_reconnect_failed_when_retries_are_exhausted(self) -> None:
    baseline_snapshot = {
        "call": "stand_aside",
        "trade_status": "not_valid",
        "direction_bias": "none",
        "regime": "range",
        "confidence": 0.52,
        "wait_for": "wait for clearer structure",
        "briefing": "baseline before disconnect",
        "symbol": "R_75",
    }
    journal_path = Path("journals/test_live_watch_reconnect_failed.jsonl")
    if journal_path.exists():
        journal_path.unlink()

    with patch("synthetic_trader.live.market_snapshot.collect_live_snapshot_ticks", return_value=[]):
        with patch("synthetic_trader.live.market_snapshot.analyze_live_snapshot", return_value=baseline_snapshot):
            with patch(
                "synthetic_trader.live.market_snapshot.watch_live_ticks",
                side_effect=RuntimeError("client is not connected"),
            ):
                alerts = asyncio.run(
                    run_live_watch(
                        symbol="R_75",
                        warmup_count=0,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=str(journal_path),
                        max_reconnects=1,
                    )
                )

    journal_records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    self.assertEqual(alerts, [])
    self.assertEqual(journal_records[-1]["record_type"], "watch_transport")
    self.assertEqual(journal_records[-1]["event"], "reconnect_failed")
```

- [ ] **Step 4: Run the reconnect-focused tests to verify they fail**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "reconnect" -v`
Expected: FAIL because `live-watch` has no reconnect flags, no transport records, and no reconnect-aware watch loop yet.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_live_market_snapshot.py
git commit -m "test: cover live watch auto reconnect"
```

### Task 2: Add Reconnect Controls To The CLI

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add reconnect arguments to the `live-watch` parser**

```python
    live_watch.add_argument("--max-reconnects", type=int, default=5)
    live_watch.add_argument("--reconnect-backoff-sec", type=int, default=1)
```

- [ ] **Step 2: Pass reconnect controls into `run_live_watch()`**

```python
        alerts = asyncio.run(
            run_live_watch(
                symbol=args.symbol,
                warmup_count=args.warmup_count,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.higher_timeframe,
                journal_path=args.journal,
                emit_initial=args.emit_initial,
                max_alerts=args.max_alerts,
                max_minutes=args.max_minutes,
                app_id=args.app_id,
                max_reconnects=args.max_reconnects,
                reconnect_backoff_sec=args.reconnect_backoff_sec,
            )
        )
```

- [ ] **Step 3: Run the CLI reconnect test**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchCliTests::test_live_watch_command_passes_reconnect_controls -v`
Expected: PASS

- [ ] **Step 4: Commit the CLI reconnect controls**

```bash
git add src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch reconnect controls"
```

### Task 3: Add Transport Record Helpers And Error Classification

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add helpers for transport record payloads**

```python
def build_watch_transport_record(
    *,
    symbol: str,
    event: str,
    reason: str,
    attempt: int | None = None,
    attempts: int | None = None,
    baseline_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    record = {
        "record_type": "watch_transport",
        "symbol": symbol,
        "event": event,
        "reason": reason,
        "attempt": attempt,
        "attempts": attempts,
    }
    if baseline_snapshot is not None:
        record.update(
            {
                "regime": baseline_snapshot.get("regime"),
                "direction_bias": baseline_snapshot.get("direction_bias"),
                "trade_status": baseline_snapshot.get("trade_status"),
                "confidence": baseline_snapshot.get("confidence"),
            }
        )
    return {key: value for key, value in record.items() if value is not None}
```

- [ ] **Step 2: Add a transport error classifier**

```python
def is_watch_transport_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "client is not connected" in message
        or "keepalive" in message
        or "ping timeout" in message
        or "connection closed" in message
        or "socket" in message
    )
```

- [ ] **Step 3: Run the reconnect tests to confirm they still fail at the loop level, not on missing helpers**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "reconnect" -v`
Expected: loop tests still FAIL because `run_live_watch()` does not yet reconnect or rebaseline.

- [ ] **Step 4: Commit the helper layer**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add watch transport helpers"
```

### Task 4: Make `run_live_watch()` Reconnect And Rebaseline

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Extend `run_live_watch()` signature with reconnect controls**

```python
async def run_live_watch(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    journal_path: str,
    emit_initial: bool = False,
    max_alerts: int | None = None,
    max_minutes: int | None = None,
    app_id: str | None = None,
    max_reconnects: int = 5,
    reconnect_backoff_sec: int = 1,
) -> list[dict[str, object]]:
```

- [ ] **Step 2: Add a local helper inside `run_live_watch()` that rebuilds baseline state**

```python
    async def load_baseline_state() -> tuple[list[Tick], dict[str, object], WatchState]:
        history = await collect_live_snapshot_ticks(
            symbol=symbol,
            warmup_count=warmup_count,
            max_live_ticks=0,
            app_id=app_id,
        )
        baseline_snapshot = analyze_live_snapshot(
            symbol=symbol,
            ticks=history,
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            config=TraderConfig.default(),
        )
        return history, baseline_snapshot, build_watch_state(baseline_snapshot)
```

- [ ] **Step 3: Wrap the tick-watch phase in reconnect control flow**

```python
    reconnect_attempts = 0
    history, baseline_snapshot, previous_state = await load_baseline_state()
    alerts: list[dict[str, object]] = []
    buffer = list(history)
    journal = Path(journal_path)
    context_cooldown_remaining = 0

    while True:
        try:
            ticks = await watch_live_ticks(symbol=symbol, app_id=app_id, max_minutes=max_minutes)
        except Exception as exc:
            if not is_watch_transport_error(exc):
                raise
            reconnect_attempts += 1
            append_watch_alert(
                journal,
                build_watch_transport_record(
                    symbol=symbol,
                    event="reconnect_attempt",
                    reason=str(exc),
                    attempt=reconnect_attempts,
                ),
            )
            if reconnect_attempts > max_reconnects:
                append_watch_alert(
                    journal,
                    build_watch_transport_record(
                        symbol=symbol,
                        event="reconnect_failed",
                        reason=str(exc),
                        attempts=reconnect_attempts,
                    ),
                )
                break
            await asyncio.sleep(min(max(reconnect_backoff_sec, 1) * reconnect_attempts, 10))
            history, baseline_snapshot, previous_state = await load_baseline_state()
            buffer = list(history)
            context_cooldown_remaining = 0
            append_watch_alert(
                journal,
                build_watch_transport_record(
                    symbol=symbol,
                    event="reconnect_rebaseline_ok",
                    reason="baseline rebuilt after reconnect",
                    attempt=reconnect_attempts,
                    baseline_snapshot=baseline_snapshot,
                ),
            )
            continue
```

- [ ] **Step 4: Keep candle-close evaluation unchanged after reconnect**

```python
        for tick in ticks:
            buffer.append(tick)
            bucket = int(tick.epoch // timeframe_sec) * timeframe_sec
            previous_bucket = int(buffer[-2].epoch // timeframe_sec) * timeframe_sec if len(buffer) > 1 else bucket
            if bucket == previous_bucket:
                continue
            if context_cooldown_remaining > 0:
                context_cooldown_remaining -= 1

            snapshot = analyze_live_snapshot(
                symbol=symbol,
                ticks=buffer,
                timeframe_sec=timeframe_sec,
                higher_timeframe_sec=higher_timeframe_sec,
                config=TraderConfig.default(),
            )
            current_state = build_watch_state(snapshot)
            ...
```

- [ ] **Step 5: Run the reconnect-focused test slice**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "reconnect" -v`
Expected: PASS

- [ ] **Step 6: Commit the reconnect loop**

```bash
git add src/synthetic_trader/live/market_snapshot.py src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: auto reconnect live watch"
```

### Task 5: Full Verification

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Modify: `src/synthetic_trader/cli.py`
- Modify: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Run the full live market snapshot module**

Run: `python -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 2: Run a bounded reconnect-capable smoke**

Run: `python -m synthetic_trader.cli live-watch --symbol R_75 --emit-initial --max-minutes 1 --max-alerts 2 --max-reconnects 2 --journal journals/live_watch_reconnect_smoke.jsonl`
Expected: either a clean bounded run or a reconnect attempt recorded in the journal without a crash.

- [ ] **Step 3: Review the resulting journal**

Run: `python -m synthetic_trader.cli live-watch-review --journal journals/live_watch_reconnect_smoke.jsonl --limit 5`
Expected: existing review output remains stable; transport records should not appear as recent emitted alerts.

- [ ] **Step 4: Commit the verification pass**

```bash
git add src/synthetic_trader/live/market_snapshot.py src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "test: verify live watch reconnect flow"
```
