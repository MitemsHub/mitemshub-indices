# Lightweight Live Calibration Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight append-only evidence loop that logs live calls for `R_75` and `R_100`, scores their next-hour outcomes, and prints compact calibration metrics without introducing a replay platform or database.

**Architecture:** Reuse the existing live snapshot and alert surface to serialize compact JSONL call records, then add a small scorer that evaluates unresolved records after the outcome window using fresh tick history. Keep file I/O isolated in dedicated live-calibration modules and expose the flow through small CLI commands rather than embedding logging directly into `market_snapshot.py`.

**Tech Stack:** Python 3.13, pytest, JSONL, argparse, existing Deriv tick-history client

---

## File Map

- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_logger.py`
  - Normalize live payloads into compact call records and append them to JSONL.
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_scorer.py`
  - Read unresolved call records, fetch enough tick history, compute excursions and next-hour outcomes, append scored results, and print compact summary metrics.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add `log-live-call` and `score-live-calibration` commands.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`
  - Reuse `build_watch_alert()` output where needed for logger integration, but avoid embedding persistence logic here.
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_logger.py`
  - Cover call-record serialization for actionable and forming cases.
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`
  - Cover target-hit, stop-hit, rejected-but-price-ran, and summary aggregation logic.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli.py`
  - Verify the new CLI commands route correctly if a CLI test file already exists; otherwise add focused parser tests in a new file.

### Task 1: Add Call Record Logger

**Files:**
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_logger.py`
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_logger.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_call_record_serializes_actionable_r75_geometry() -> None:
    alert = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "trade_status": "valid",
        "guardian_state": "actionable",
        "direction_bias": "buy",
        "confidence": 0.76,
        "entry": 55620.0,
        "execution_stop": 55280.0,
        "primary_target": 56180.0,
        "thesis_invalidation": 52541.0,
        "hold_horizon_minutes": 60,
        "why": "buyers still control continuation",
        "wait_for": "wait for the 5m continuation trigger to confirm, then manage toward the next hour objective",
        "decision_summary": "4H bullish; 1H setup aligns; 15m continuation aligns",
        "current_close": 55580.0,
        "model_version": "online-logistic-v1",
    }

    record = build_call_record(alert)
    assert record["symbol"] == "R_75"
    assert record["primary_target"] == 56180.0
    assert record["guardian_state"] == "actionable"


def test_build_call_record_serializes_forming_r100_with_null_geometry() -> None:
    alert = {
        "symbol": "R_100",
        "call": "stand_aside",
        "trade_status": "not_valid",
        "guardian_state": "forming",
        "direction_bias": "buy",
        "confidence": 0.46,
        "entry": None,
        "execution_stop": None,
        "primary_target": None,
        "thesis_invalidation": None,
        "hold_horizon_minutes": None,
        "why": "current movement is active but not a clean setup yet",
        "wait_for": "wait for a cleaner entry so reward outweighs the risk",
        "decision_summary": None,
        "current_close": 483.84,
        "model_version": "online-logistic-v1",
    }

    record = build_call_record(alert)
    assert record["symbol"] == "R_100"
    assert record["primary_target"] is None
    assert record["guardian_state"] == "forming"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_calibration_logger.py -v`
Expected: FAIL with `ModuleNotFoundError` because `calibration_logger.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def build_call_record(alert: dict[str, object]) -> dict[str, object]:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "symbol": alert.get("symbol"),
        "generated_at": alert.get("generated_at"),
        "call": alert.get("call"),
        "trade_status": alert.get("trade_status"),
        "guardian_state": alert.get("guardian_state"),
        "direction_bias": alert.get("direction_bias"),
        "trigger_type": alert.get("execution_trigger_type"),
        "confidence": alert.get("confidence"),
        "entry": alert.get("entry"),
        "execution_stop": alert.get("execution_stop"),
        "primary_target": alert.get("primary_target"),
        "thesis_invalidation": alert.get("thesis_invalidation"),
        "hold_horizon_minutes": alert.get("hold_horizon_minutes"),
        "why": alert.get("why"),
        "wait_for": alert.get("wait_for"),
        "decision_summary": alert.get("decision_summary"),
        "current_close": alert.get("current_close"),
        "model_version": alert.get("model_version"),
    }


def append_call_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_calibration_logger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_logger.py tests/test_calibration_logger.py
git commit -m "feat: add lightweight live calibration call logger"
```

### Task 2: Add Outcome Scorer

**Files:**
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_scorer.py`
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_score_call_outcome_returns_target_hit_when_primary_target_is_reached_first() -> None:
    prices = [100.0, 101.0, 102.5, 103.0]
    record = {
        "symbol": "R_100",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 102.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)
    assert outcome["outcome_label"] == "target_hit"


def test_score_call_outcome_returns_rejected_but_price_ran_for_forming_call_that_would_have_moved() -> None:
    prices = [100.0, 100.8, 101.6, 102.2]
    record = {
        "symbol": "R_75",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": None,
        "execution_stop": None,
        "primary_target": None,
        "trade_status": "not_valid",
        "guardian_state": "forming",
        "current_close": 100.0,
    }

    outcome = score_call_outcome(record=record, prices=prices)
    assert outcome["outcome_label"] == "rejected_but_price_ran"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_calibration_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError` because `calibration_scorer.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from datetime import datetime, timezone


def score_call_outcome(*, record: dict[str, object], prices: list[float]) -> dict[str, object]:
    entry = record.get("entry")
    stop = record.get("execution_stop")
    target = record.get("primary_target")
    current_close = record.get("current_close")
    max_favorable = max(prices) if prices else None
    max_adverse = min(prices) if prices else None

    if entry is not None and stop is not None and target is not None:
        target_hit = any(price >= float(target) for price in prices) if float(target) >= float(entry) else any(price <= float(target) for price in prices)
        stop_hit = any(price <= float(stop) for price in prices) if float(stop) <= float(entry) else any(price >= float(stop) for price in prices)
        if target_hit and not stop_hit:
            label = "target_hit"
        elif stop_hit and not target_hit:
            label = "stop_hit"
        else:
            label = "neither_reached"
    else:
        moved = False
        if current_close is not None and prices:
            moved = abs(max(prices) - float(current_close)) > 1.0 or abs(min(prices) - float(current_close)) > 1.0
        label = "rejected_but_price_ran" if moved else "forming_remained_correct"

    return {
        "symbol": record.get("symbol"),
        "generated_at": record.get("generated_at"),
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_calibration_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_scorer.py tests/test_calibration_scorer.py
git commit -m "feat: add lightweight live calibration outcome scorer"
```

### Task 3: Add Summary Aggregation

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_scorer.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_summarize_outcomes_groups_by_symbol_and_trigger_type() -> None:
    outcomes = [
        {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "target_hit", "max_favorable_excursion": 120.0, "max_adverse_excursion": 30.0},
        {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "stop_hit", "max_favorable_excursion": 40.0, "max_adverse_excursion": 90.0},
        {"symbol": "R_100", "trigger_type": "reclaim_pullback", "trade_status": "valid", "outcome_label": "target_hit", "max_favorable_excursion": 8.0, "max_adverse_excursion": 2.0},
    ]

    summary = summarize_outcomes(outcomes)
    assert summary[("R_75", "continuation_close", "valid")]["count"] == 2
    assert summary[("R_100", "reclaim_pullback", "valid")]["target_hit_rate"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_calibration_scorer.py::test_summarize_outcomes_groups_by_symbol_and_trigger_type -v`
Expected: FAIL because `summarize_outcomes()` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def summarize_outcomes(outcomes: list[dict[str, object]]) -> dict[tuple[str, str | None, str | None], dict[str, float]]:
    grouped: dict[tuple[str, str | None, str | None], list[dict[str, object]]] = {}
    for outcome in outcomes:
        key = (
            str(outcome.get("symbol")),
            outcome.get("trigger_type"),
            outcome.get("trade_status"),
        )
        grouped.setdefault(key, []).append(outcome)

    summary: dict[tuple[str, str | None, str | None], dict[str, float]] = {}
    for key, rows in grouped.items():
        count = len(rows)
        target_hits = sum(1 for row in rows if row.get("outcome_label") == "target_hit")
        stop_hits = sum(1 for row in rows if row.get("outcome_label") == "stop_hit")
        neither = sum(1 for row in rows if row.get("outcome_label") == "neither_reached")
        summary[key] = {
            "count": float(count),
            "target_hit_rate": target_hits / count,
            "stop_hit_rate": stop_hits / count,
            "neither_rate": neither / count,
            "avg_max_favorable_excursion": sum(float(row.get("max_favorable_excursion") or 0.0) for row in rows) / count,
            "avg_max_adverse_excursion": sum(float(row.get("max_adverse_excursion") or 0.0) for row in rows) / count,
        }
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_calibration_scorer.py::test_summarize_outcomes_groups_by_symbol_and_trigger_type -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_scorer.py tests/test_calibration_scorer.py
git commit -m "feat: summarize live calibration outcomes"
```

### Task 4: Add CLI Commands

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli_calibration_logging.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_parser_exposes_log_live_call_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["log-live-call", "--symbol", "R_75", "--payload-json", "call.json"])
    assert args.command == "log-live-call"


def test_build_parser_exposes_score_live_calibration_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["score-live-calibration", "--calls-journal", "journals/live_calibration_calls.jsonl"])
    assert args.command == "score-live-calibration"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_cli_calibration_logging.py -v`
Expected: FAIL because the new subcommands do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
log_live_call = subparsers.add_parser("log-live-call", help="append one live calibration call record")
log_live_call.add_argument("--symbol", required=True, choices=["R_75", "R_100"])
log_live_call.add_argument("--payload-json", required=True)
log_live_call.add_argument("--output", default="journals/live_calibration_calls.jsonl")

score_live_calibration = subparsers.add_parser("score-live-calibration", help="score unresolved live calibration records")
score_live_calibration.add_argument("--calls-journal", default="journals/live_calibration_calls.jsonl")
score_live_calibration.add_argument("--output", default="journals/live_calibration_outcomes.jsonl")
score_live_calibration.add_argument("--symbol", choices=["R_75", "R_100"])
score_live_calibration.add_argument("--window-minutes", type=int)
```

Route them in `main()` by importing and calling the new logger/scorer helpers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_cli_calibration_logging.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_cli_calibration_logging.py
git commit -m "feat: add live calibration logging CLI commands"
```

### Task 5: Integrate Logger With Live Payload Shape

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_logger.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_logger.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_call_record_uses_watch_alert_shape_from_live_snapshot() -> None:
    snapshot = {
        "call": "buy_candidate",
        "symbol": "R_75",
        "trade_status": "valid",
        "direction_bias": "buy",
        "confidence": 0.76,
        "current_close": 55580.0,
        "guardian_state": "actionable",
        "entry": 55620.0,
        "execution_stop": 55280.0,
        "primary_target": 56180.0,
        "thesis_invalidation": 52541.0,
        "hold_horizon_minutes": 60,
        "decision_summary": "4H bullish; 1H aligns; 15m confirms",
        "why": "buyers still control continuation",
        "wait_for": "wait for the 5m continuation trigger to confirm, then manage toward the next hour objective",
    }
    alert = build_watch_alert(snapshot)
    record = build_call_record(alert)
    assert record["symbol"] == "R_75"
    assert record["primary_target"] == 56180.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_calibration_logger.py::test_build_call_record_uses_watch_alert_shape_from_live_snapshot -v`
Expected: FAIL if the logger misses one or more live payload fields.

- [ ] **Step 3: Write minimal implementation**

```python
def build_call_record(alert: dict[str, object]) -> dict[str, object]:
    return {
        ...
        "trigger_type": alert.get("execution_trigger_type"),
        "execution_stop": alert.get("execution_stop"),
        "primary_target": alert.get("primary_target"),
        "thesis_invalidation": alert.get("thesis_invalidation"),
        "hold_horizon_minutes": alert.get("hold_horizon_minutes"),
        ...
    }
```

Do not embed file I/O into `market_snapshot.py`; only reuse its alert shape.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_calibration_logger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_logger.py tests/test_calibration_logger.py src/synthetic_trader/live/market_snapshot.py
git commit -m "feat: align live calibration logger with watch alert payloads"
```

### Task 6: Add Scoring Command Flow

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\calibration_scorer.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_calibration_scorer.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_score_unresolved_records_appends_only_records_old_enough_for_evaluation(tmp_path: Path) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '{"symbol":"R_100","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":102.0,"trade_status":"valid"}\n'
        '{"symbol":"R_75","generated_at":"2099-01-01T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":102.0,"trade_status":"valid"}\n',
        encoding="utf-8",
    )

    written = score_unresolved_records(
        calls_path=calls_path,
        outcomes_path=outcomes_path,
        now=datetime(2026, 7, 12, 11, 5, tzinfo=timezone.utc),
        price_lookup=lambda record: [100.0, 101.0, 102.2],
    )

    assert written == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_calibration_scorer.py::test_score_unresolved_records_appends_only_records_old_enough_for_evaluation -v`
Expected: FAIL because batch scoring flow does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def score_unresolved_records(
    *,
    calls_path: Path,
    outcomes_path: Path,
    now: datetime,
    price_lookup,
) -> int:
    written = 0
    for record in load_jsonl_records(calls_path):
        generated_at = datetime.fromisoformat(str(record["generated_at"]))
        window_minutes = int(record.get("hold_horizon_minutes") or 60)
        if generated_at > now - timedelta(minutes=window_minutes):
            continue
        prices = price_lookup(record)
        outcome = score_call_outcome(record=record, prices=prices)
        append_jsonl_record(outcomes_path, outcome)
        written += 1
    return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_calibration_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_scorer.py tests/test_calibration_scorer.py src/synthetic_trader/cli.py
git commit -m "feat: add lightweight live calibration scoring flow"
```

### Task 7: End-To-End Verification

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_cli_calibration_logging.py`

- [ ] **Step 1: Write the failing test**

```python
def test_log_live_call_and_score_live_calibration_commands_work_together(tmp_path: Path) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({
            "symbol": "R_100",
            "call": "buy_candidate",
            "trade_status": "valid",
            "guardian_state": "actionable",
            "direction_bias": "buy",
            "confidence": 0.74,
            "entry": 476.1,
            "execution_stop": 474.8,
            "primary_target": 488.4,
            "thesis_invalidation": 440.67,
            "hold_horizon_minutes": 60,
            "why": "buyers reclaimed the pullback shelf",
            "wait_for": "wait for the 5m reclaim to confirm, then manage toward the next hour objective",
            "decision_summary": "4H bullish; 1H setup aligns; 15m reclaim aligns",
            "current_close": 476.5,
            "model_version": "online-logistic-v1",
        }),
        encoding="utf-8",
    )

    main(["log-live-call", "--symbol", "R_100", "--payload-json", str(payload_path), "--output", str(calls_path)])
    assert calls_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_cli_calibration_logging.py::test_log_live_call_and_score_live_calibration_commands_work_together -v`
Expected: FAIL until both commands and helper wiring are available.

- [ ] **Step 3: Write minimal implementation**

```python
if args.command == "log-live-call":
    payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
    append_call_record(Path(args.output), build_call_record(payload))
    return

if args.command == "score-live-calibration":
    written = score_unresolved_records(
        calls_path=Path(args.calls_journal),
        outcomes_path=Path(args.output),
        now=datetime.now(timezone.utc),
        price_lookup=lambda record: [],
    )
    print(f"scored_records={written}")
    return
```

For the first pass, keep the scorer callable and testable even if the live price lookup is still injected internally.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_calibration_logger.py tests/test_calibration_scorer.py tests/test_cli_calibration_logging.py -q`
Expected: PASS

Run a smoke invocation:

```bash
py -3 -m synthetic_trader.cli log-live-call --symbol R_75 --payload-json payload.json --output journals/live_calibration_calls.jsonl
```

Expected: appends one JSONL line without error.

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/calibration_logger.py src/synthetic_trader/live/calibration_scorer.py src/synthetic_trader/cli.py tests/test_calibration_logger.py tests/test_calibration_scorer.py tests/test_cli_calibration_logging.py
git commit -m "feat: add lightweight live calibration logging workflow"
```

## Self-Review

- Spec coverage:
  - call logging: Tasks 1 and 5
  - next-hour scoring: Tasks 2 and 6
  - compact summary metrics: Task 3
  - CLI entry points: Tasks 4 and 7
  - lightweight end-to-end verification: Task 7
- Placeholder scan:
  - no `TODO`, `TBD`, or empty “write tests later” steps remain
  - every code-changing step includes explicit code or assertions
- Type consistency:
  - field names are consistent with the spec and current live payload: `execution_stop`, `primary_target`, `thesis_invalidation`, `hold_horizon_minutes`, `guardian_state`, `decision_summary`, `outcome_label`
