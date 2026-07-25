# Real Tick-History Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace placeholder-backed live calibration scoring with real Deriv tick-history lookups so `score-live-calibration` writes market-backed outcomes for both `R_75` and `R_100`.

**Architecture:** Keep the scoring rules in `calibration_scorer.py` deterministic and compact, but add a narrow async market-data wrapper that reuses `DerivWebSocketClient` plus `deriv_credentials_from_env()`. Extend the existing tick-history interface just enough to score the exact `generated_at -> generated_at + hold_horizon_minutes` window, then wire the CLI to run that async batch scorer and print `scored`, `failed`, and `skipped` counters.

**Tech Stack:** Python 3.13, asyncio, pytest, argparse, JSONL, existing Deriv WebSocket client

---

## File Map

- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\venues.py`
  - Extend the shared market-data protocol so the scorer can request bounded tick windows without bypassing the existing client abstraction.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\deriv_ws.py`
  - Add optional `start` support to `ticks_history()` while keeping current callers compatible.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_scorer.py`
  - Add record-window parsing, async tick-history fetch, resilient batch scoring, and result counters.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Replace `price_lookup=lambda record: []` with an async real-scoring wrapper and print compact counters.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`
  - Add mocked market-backed scoring coverage for target-hit, stop-hit, skip, and failure cases.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli_calibration_logging.py`
  - Verify the CLI now reports scored/failed/skipped counters and still works with the logged-call journal flow.

### Task 1: Extend Tick-History Interface For Bounded Windows

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\venues.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\deriv_ws.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.domain import Tick
from synthetic_trader.live.calibration_scorer import fetch_prices_for_record


class FakeTickClient:
    def __init__(self, ticks: list[Tick]) -> None:
        self.ticks = ticks
        self.requests: list[dict[str, object]] = []

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]:
        self.requests.append(
            {
                "symbol": symbol,
                "count": count,
                "start": start,
                "end": end,
            }
        )
        return self.ticks


async def test_fetch_prices_for_record_requests_generated_window_and_filters_ticks() -> None:
    record = {
        "symbol": "R_100",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
    }
    client = FakeTickClient(
        [
            Tick(symbol="R_100", epoch=1752314390.0, price=479.9),
            Tick(symbol="R_100", epoch=1752314400.0, price=480.1),
            Tick(symbol="R_100", epoch=1752316200.0, price=482.2),
            Tick(symbol="R_100", epoch=1752318000.0, price=483.4),
            Tick(symbol="R_100", epoch=1752318065.0, price=484.0),
        ]
    )

    prices = await fetch_prices_for_record(record=record, client=client)

    assert prices == [480.1, 482.2, 483.4]
    assert client.requests == [
        {
            "symbol": "R_100",
            "count": 5000,
            "start": 1752314400,
            "end": 1752318000,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_calibration_scorer.py::test_fetch_prices_for_record_requests_generated_window_and_filters_ticks -v`
Expected: FAIL because `fetch_prices_for_record()` does not exist and `ticks_history()` does not accept `start`.

- [ ] **Step 3: Write minimal implementation**

In `src/synthetic_trader/execution/venues.py`, expand the shared protocol:

```python
class MarketDataClient(Protocol):
    async def __aenter__(self) -> "MarketDataClient": ...

    async def __aexit__(self, *_: object) -> None: ...

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]: ...

    async def subscribe_ticks(self, symbol: str) -> AsyncIterator[Tick]: ...
```

In `src/synthetic_trader/execution/deriv_ws.py`, keep the method backward-compatible but forward `start` when present:

```python
async def ticks_history(
    self,
    symbol: str,
    count: int = 5000,
    end: str | int = "latest",
    start: int | None = None,
) -> list[Tick]:
    payload: dict[str, Any] = {
        "ticks_history": symbol,
        "count": count,
        "end": end,
        "style": "ticks",
    }
    if start is not None:
        payload["start"] = start
    response = await self.request(payload)
    history = response.get("history", {})
    times = history.get("times", [])
    prices = history.get("prices", [])
    return [Tick(symbol=symbol, epoch=float(epoch), price=float(price)) for epoch, price in zip(times, prices)]
```

In `src/synthetic_trader/live/calibration_scorer.py`, add the window helper and bounded fetch:

```python
from collections.abc import Callable
from synthetic_trader.execution.venues import MarketDataClient


def _resolve_record_window(
    *,
    record: dict[str, object],
    window_minutes: int | None = None,
) -> tuple[datetime, datetime, int]:
    generated_at = datetime.fromisoformat(str(record["generated_at"]))
    hold_minutes = int(window_minutes or record.get("hold_horizon_minutes") or 60)
    window_end = generated_at + timedelta(minutes=hold_minutes)
    return generated_at, window_end, hold_minutes


async def fetch_prices_for_record(
    *,
    record: dict[str, object],
    client: MarketDataClient,
    window_minutes: int | None = None,
) -> list[float]:
    window_start, window_end, _ = _resolve_record_window(record=record, window_minutes=window_minutes)
    start_epoch = int(window_start.timestamp())
    end_epoch = int(window_end.timestamp())
    ticks = await client.ticks_history(
        symbol=str(record["symbol"]),
        count=5000,
        start=start_epoch,
        end=end_epoch,
    )
    prices = [
        tick.price
        for tick in sorted(ticks, key=lambda item: item.epoch)
        if start_epoch <= int(tick.epoch) <= end_epoch
    ]
    if not prices:
        raise ValueError("empty_price_history")
    return prices
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_calibration_scorer.py::test_fetch_prices_for_record_requests_generated_window_and_filters_ticks -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/venues.py src/synthetic_trader/execution/deriv_ws.py src/synthetic_trader/live/calibration_scorer.py tests/test_calibration_scorer.py
git commit -m "feat: add bounded tick history support for calibration scoring"
```

### Task 2: Add Resilient Market-Backed Batch Scoring

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_scorer.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from datetime import datetime, timezone
from pathlib import Path

from synthetic_trader.domain import Tick
from synthetic_trader.live.calibration_scorer import score_unresolved_records_from_market


class FakeScoringClient:
    def __init__(self, batches: list[list[Tick] | Exception]) -> None:
        self.batches = batches
        self.calls = 0

    async def __aenter__(self) -> "FakeScoringClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]:
        batch = self.batches[self.calls]
        self.calls += 1
        if isinstance(batch, Exception):
            raise batch
        return batch


@pytest.mark.asyncio
async def test_score_unresolved_records_from_market_writes_target_hit_and_counts_skip_and_failure(
    tmp_path: Path,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '\n'.join(
            [
                '{"symbol":"R_100","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":102.0,"trade_status":"valid"}',
                '{"symbol":"R_75","generated_at":"2026-07-12T10:10:00+00:00","hold_horizon_minutes":60,"entry":500.0,"execution_stop":497.0,"primary_target":505.0,"trade_status":"valid"}',
                '{"symbol":"R_75","generated_at":"2026-07-12T10:50:00+00:00","hold_horizon_minutes":60,"entry":600.0,"execution_stop":597.0,"primary_target":604.0,"trade_status":"valid"}',
            ]
        )
        + '\n',
        encoding="utf-8",
    )
    client = FakeScoringClient(
        [
            [
                Tick(symbol="R_100", epoch=1752314400.0, price=100.0),
                Tick(symbol="R_100", epoch=1752314700.0, price=101.2),
                Tick(symbol="R_100", epoch=1752315000.0, price=102.3),
            ],
            RuntimeError("transport_down"),
        ]
    )

    result = await score_unresolved_records_from_market(
        calls_path=calls_path,
        outcomes_path=outcomes_path,
        now=datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
        client_factory=lambda: client,
    )

    written = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines()]
    assert result.scored_records == 1
    assert result.failed_records == 1
    assert result.skipped_records == 1
    assert written[0]["outcome_label"] == "target_hit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_calibration_scorer.py::test_score_unresolved_records_from_market_writes_target_hit_and_counts_skip_and_failure -v`
Expected: FAIL because the async market-backed batch scorer and counter result do not exist yet.

- [ ] **Step 3: Write minimal implementation**

In `src/synthetic_trader/live/calibration_scorer.py`, add a small result dataclass plus the async batch wrapper:

```python
from dataclasses import dataclass

from synthetic_trader.data.collector import deriv_credentials_from_env
from synthetic_trader.execution.deriv_ws import DerivWebSocketClient


@dataclass(frozen=True)
class CalibrationScoringResult:
    scored_records: int = 0
    failed_records: int = 0
    skipped_records: int = 0


async def score_unresolved_records_from_market(
    *,
    calls_path: Path,
    outcomes_path: Path,
    now: datetime,
    symbol: str | None = None,
    window_minutes: int | None = None,
    app_id: str | None = None,
    token: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> CalibrationScoringResult:
    existing_outcomes = load_jsonl_records(outcomes_path)
    resolved_keys = {_record_key(record) for record in existing_outcomes}
    result = CalibrationScoringResult()
    credentials = deriv_credentials_from_env(app_id=app_id, token=token)
    factory = client_factory or (lambda: DerivWebSocketClient(credentials))

    async with factory() as client:
        for record in load_jsonl_records(calls_path):
            if symbol is not None and record.get("symbol") != symbol:
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records,
                    skipped_records=result.skipped_records + 1,
                )
                continue
            if _record_key(record) in resolved_keys:
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records,
                    skipped_records=result.skipped_records + 1,
                )
                continue

            generated_at, _, hold_minutes = _resolve_record_window(record=record, window_minutes=window_minutes)
            if generated_at > now - timedelta(minutes=hold_minutes):
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records,
                    skipped_records=result.skipped_records + 1,
                )
                continue

            try:
                prices = await fetch_prices_for_record(
                    record=record,
                    client=client,
                    window_minutes=window_minutes,
                )
            except (KeyError, TypeError, ValueError, RuntimeError):
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records + 1,
                    skipped_records=result.skipped_records,
                )
                continue

            outcome = score_call_outcome(record=record, prices=prices)
            append_jsonl_record(outcomes_path, outcome)
            resolved_keys.add(_record_key(record))
            result = CalibrationScoringResult(
                scored_records=result.scored_records + 1,
                failed_records=result.failed_records,
                skipped_records=result.skipped_records,
            )

    return result
```

Keep the existing pure `score_call_outcome()` function unchanged except for any imports it now needs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_calibration_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_scorer.py tests/test_calibration_scorer.py
git commit -m "feat: add resilient market-backed calibration scoring"
```

### Task 3: Wire The CLI To Real Tick-History Scoring

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli_calibration_logging.py`

- [ ] **Step 1: Write the failing tests**

```python
import contextlib
import io
from pathlib import Path

from synthetic_trader.cli import main
from synthetic_trader.live.calibration_scorer import CalibrationScoringResult


def test_main_score_live_calibration_prints_scored_failed_and_skipped_counts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text('{"symbol":"R_100","generated_at":"2026-07-12T10:00:00+00:00"}\n', encoding="utf-8")
    output = io.StringIO()

    async def fake_score_unresolved_records_from_market(**_: object) -> CalibrationScoringResult:
        return CalibrationScoringResult(scored_records=2, failed_records=1, skipped_records=3)

    monkeypatch.setattr(
        "synthetic_trader.cli.score_unresolved_records_from_market",
        fake_score_unresolved_records_from_market,
    )

    with contextlib.redirect_stdout(output):
        exit_code = main(
            [
                "score-live-calibration",
                "--calls-journal",
                str(calls_path),
                "--output",
                str(outcomes_path),
                "--now",
                "2026-07-12T12:00:00+00:00",
            ]
        )

    assert exit_code == 0
    assert "scored_records=2" in output.getvalue()
    assert "failed_records=1" in output.getvalue()
    assert "skipped_records=3" in output.getvalue()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_cli_calibration_logging.py::test_main_score_live_calibration_prints_scored_failed_and_skipped_counts -v`
Expected: FAIL because `cli.py` still imports the old synchronous helper and only prints `scored_records`.

- [ ] **Step 3: Write minimal implementation**

In `src/synthetic_trader/cli.py`, switch the import and replace the placeholder scoring branch:

```python
from synthetic_trader.live.calibration_scorer import score_unresolved_records_from_market
```

```python
if args.command == "score-live-calibration":
    journal_path = Path(args.calls_journal)
    if not journal_path.exists():
        print(f"error=journal_not_found:{journal_path}")
        return 1
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    result = asyncio.run(
        score_unresolved_records_from_market(
            calls_path=journal_path,
            outcomes_path=Path(args.output),
            now=now,
            symbol=args.symbol,
            window_minutes=args.window_minutes,
        )
    )
    print(f"calls_journal={journal_path}")
    print(f"output={Path(args.output)}")
    print(f"scored_records={result.scored_records}")
    print(f"failed_records={result.failed_records}")
    print(f"skipped_records={result.skipped_records}")
    return 0
```

Do not add a new top-level command. Keep the existing parser arguments unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_cli_calibration_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_cli_calibration_logging.py
git commit -m "feat: wire cli to real tick history calibration scoring"
```

### Task 4: Verify End-To-End Market-Backed Scoring Behavior

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli_calibration_logging.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_score_unresolved_records_from_market_writes_stop_hit_when_stop_is_reached_first(
    tmp_path: Path,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '{"symbol":"R_75","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":103.0,"trade_status":"valid"}\n',
        encoding="utf-8",
    )
    client = FakeScoringClient(
        [[
            Tick(symbol="R_75", epoch=1752314400.0, price=100.0),
            Tick(symbol="R_75", epoch=1752314700.0, price=99.1),
            Tick(symbol="R_75", epoch=1752315000.0, price=98.0),
        ]]
    )

    result = await score_unresolved_records_from_market(
        calls_path=calls_path,
        outcomes_path=outcomes_path,
        now=datetime(2026, 7, 12, 11, 30, tzinfo=timezone.utc),
        client_factory=lambda: client,
    )

    written = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines()]
    assert result.scored_records == 1
    assert written[0]["outcome_label"] == "stop_hit"
```

```python
def test_log_live_call_and_score_live_calibration_commands_work_together_with_real_scoring_wrapper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "symbol": "R_100",
                "call": "buy_candidate",
                "trade_status": "valid",
                "guardian_state": "actionable",
                "entry": 476.1,
                "execution_stop": 474.8,
                "primary_target": 488.4,
            }
        ),
        encoding="utf-8",
    )

    async def fake_score_unresolved_records_from_market(**kwargs: object) -> CalibrationScoringResult:
        append_jsonl_record(
            Path(kwargs["outcomes_path"]),
            {"symbol": "R_100", "outcome_label": "neither_reached"},
        )
        return CalibrationScoringResult(scored_records=1, failed_records=0, skipped_records=0)

    monkeypatch.setattr(
        "synthetic_trader.cli.score_unresolved_records_from_market",
        fake_score_unresolved_records_from_market,
    )

    assert main(
        [
            "log-live-call",
            "--symbol",
            "R_100",
            "--payload-json",
            str(payload_path),
            "--output",
            str(calls_path),
        ]
    ) == 0
    assert main(
        [
            "score-live-calibration",
            "--calls-journal",
            str(calls_path),
            "--output",
            str(outcomes_path),
            "--now",
            "2026-07-12T12:00:00+00:00",
        ]
    ) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_calibration_scorer.py tests/test_cli_calibration_logging.py -q`
Expected: FAIL until stop-first scoring and the CLI-to-wrapper flow are both covered.

- [ ] **Step 3: Write minimal implementation**

Keep the implementation narrow:

```python
def score_call_outcome(*, record: dict[str, object], prices: list[float]) -> dict[str, object]:
    entry = record.get("entry")
    stop = record.get("execution_stop")
    target = record.get("primary_target")
    current_close = record.get("current_close")
    max_favorable = max(prices) if prices else None
    max_adverse = min(prices) if prices else None

    if entry is not None and stop is not None and target is not None:
        entry_value = float(entry)
        stop_value = float(stop)
        target_value = float(target)
        label = "neither_reached"

        for price in prices:
            if _price_hits_target(price=price, entry=entry_value, target=target_value):
                label = "target_hit"
                break
            if _price_hits_stop(price=price, entry=entry_value, stop=stop_value):
                label = "stop_hit"
                break
    else:
        moved = False
        if current_close is not None and prices:
            reference_price = float(current_close)
            moved = any(abs(price - reference_price) > 1.0 for price in prices)
        label = "rejected_but_price_ran" if moved else "forming_remained_correct"

    return {
        "symbol": record.get("symbol"),
        "generated_at": record.get("generated_at"),
        "trigger_type": record.get("trigger_type"),
        "trade_status": record.get("trade_status"),
        "guardian_state": record.get("guardian_state"),
        "evaluation_time": datetime.now(timezone.utc).isoformat(),
        "outcome_window_minutes": record.get("hold_horizon_minutes") or 60,
        "entry": entry,
        "execution_stop": stop,
        "primary_target": target,
        "max_favorable_excursion": max_favorable,
        "max_adverse_excursion": max_adverse,
        "target_reached": label == "target_hit",
        "stop_reached": label == "stop_hit",
        "outcome_label": label,
    }
```

No extra persistence layer, no replay dataset, and no model-updating logic belong in this task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_calibration_scorer.py tests/test_cli_calibration_logging.py -q`
Expected: PASS

Run an optional real-transport smoke check when `DERIV_APP_ID` is available:

```bash
py -3 -m synthetic_trader.cli score-live-calibration --calls-journal journals/live_calibration_calls.jsonl --output journals/live_calibration_outcomes.jsonl
```

Expected: prints `scored_records=<n>`, `failed_records=<n>`, and `skipped_records=<n>` without crashing the batch. If there are no old-enough records yet, `scored_records=0` is acceptable.

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/venues.py src/synthetic_trader/execution/deriv_ws.py src/synthetic_trader/live/calibration_scorer.py src/synthetic_trader/cli.py tests/test_calibration_scorer.py tests/test_cli_calibration_logging.py
git commit -m "feat: score live calibration calls from deriv tick history"
```

## Self-Review

- Spec coverage:
  - real tick-history lookup: Tasks 1 and 2
  - async helper(s) inside the scorer: Tasks 1 and 2
  - CLI integration without a new command: Task 3
  - per-record failure handling and counters: Tasks 2 and 3
  - mocked real-scoring tests plus smoke verification: Task 4
- Placeholder scan:
  - no `TODO`, `TBD`, or deferred "write tests later" language remains
  - every code step names the exact functions, return types, and CLI output expected
- Type consistency:
  - `CalibrationScoringResult`, `fetch_prices_for_record()`, and `score_unresolved_records_from_market()` are used consistently across scorer and CLI tasks
  - field names stay aligned with the existing journal shape: `generated_at`, `hold_horizon_minutes`, `entry`, `execution_stop`, `primary_target`, `trigger_type`, `trade_status`
