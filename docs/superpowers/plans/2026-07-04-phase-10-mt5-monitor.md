# Phase 10 MT5 Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only MT5 monitor CLI command that aggregates Phase 9 journal events into a compact operator-facing snapshot.

**Architecture:** Extend the existing monitoring surface with MT5-specific journal parsing, snapshot aggregation, and text rendering helpers while keeping the current paper-live helpers intact. Add one dedicated CLI command that reads JSONL journal data, optionally filters by symbol, and renders the latest-known MT5 lifecycle state without contacting MT5.

**Tech Stack:** Python 3.11+, `argparse`, `json`, `pathlib`, existing CLI architecture, JSONL trade journal, `unittest`/`pytest`

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase10_mt5_monitor.py`
  - Focused tests for MT5 event filtering, snapshot aggregation, empty-state behavior, and CLI output.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\monitoring\surface.py`
  - Add MT5 event filtering, MT5 monitor snapshot building, and MT5 monitor text rendering helpers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add the read-only `mt5-monitor` command and wire it to the monitoring helpers.

## Task 1: Build MT5 Journal Filtering

**Files:**
- Modify: `src/synthetic_trader/monitoring/surface.py`
- Create: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Write the failing MT5 event filtering test**

```python
from __future__ import annotations

import unittest

from synthetic_trader.monitoring.surface import filter_mt5_events


class Phase10Mt5FilterTests(unittest.TestCase):
    def test_filter_mt5_events_keeps_only_mt5_event_types(self) -> None:
        events = [
            {"type": "signal", "symbol": "R_75"},
            {"type": "mt5_runtime_summary", "symbol": "R_75"},
            {"type": "mt5_sync_summary", "symbol": "R_75"},
            {"type": "outcome", "symbol": "R_75"},
        ]

        filtered = filter_mt5_events(events)

        self.assertEqual(
            [entry["type"] for entry in filtered],
            ["mt5_runtime_summary", "mt5_sync_summary"],
        )
```

- [ ] **Step 2: Run the filtering test to verify it fails**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5FilterTests" -q`
Expected: FAIL with `ImportError` or `AttributeError` because `filter_mt5_events()` does not exist yet

- [ ] **Step 3: Write the minimal filtering helper**

```python
# src/synthetic_trader/monitoring/surface.py
from __future__ import annotations


MT5_EVENT_TYPES = {
    "mt5_runtime_summary",
    "mt5_sync_summary",
    "mt5_reconcile_summary",
    "mt5_close_result",
    "mt5_modify_result",
}


def filter_mt5_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [event for event in events if str(event.get("type")) in MT5_EVENT_TYPES]


def build_monitor_snapshot(*, live_summary: dict[str, object]) -> dict[str, object]:
    return {
        "symbol": live_summary.get("symbol"),
        "signals": live_summary.get("signals", 0),
        "approved_signals": live_summary.get("approved_signals", 0),
        "rejected_signals": live_summary.get("rejected_signals", 0),
        "session_resets": live_summary.get("session_resets", 0),
        "shutdown_closed_trades": live_summary.get("shutdown_closed_trades", 0),
    }


def render_monitor_text(snapshot: dict[str, object]) -> str:
    return "\n".join(f"{key}={value}" for key, value in snapshot.items())
```

- [ ] **Step 4: Run the filtering test to verify it passes**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5FilterTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/monitoring/surface.py tests/test_phase10_mt5_monitor.py
git commit -m "feat: add mt5 event filtering"
```

## Task 2: Build MT5 Snapshot Aggregation

**Files:**
- Modify: `src/synthetic_trader/monitoring/surface.py`
- Modify: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Write the failing snapshot aggregation tests**

```python
class Phase10Mt5SnapshotTests(unittest.TestCase):
    def test_build_mt5_monitor_snapshot_aggregates_latest_known_state(self) -> None:
        from synthetic_trader.monitoring.surface import build_mt5_monitor_snapshot

        events = [
            {
                "type": "mt5_runtime_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ready": True,
                "failures": [],
            },
            {
                "type": "mt5_sync_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "positions": 1,
                "failures": [],
            },
            {
                "type": "mt5_reconcile_summary",
                "symbol": "R_75",
                "target_ticket": 101,
                "actionable": True,
                "failures": [],
            },
            {
                "type": "mt5_close_result",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ticket": 101,
                "accepted": True,
                "retcode": 10009,
                "message": "close executed",
            },
            {
                "type": "mt5_modify_result",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ticket": 101,
                "accepted": True,
                "retcode": 10009,
                "message": "modify executed",
            },
        ]

        snapshot = build_mt5_monitor_snapshot(events=events)

        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertEqual(snapshot["venue_symbol"], "Volatility 75 Index")
        self.assertTrue(snapshot["runtime_ready"])
        self.assertEqual(snapshot["positions"], 1)
        self.assertTrue(snapshot["reconcile_actionable"])
        self.assertEqual(snapshot["reconcile_target_ticket"], 101)
        self.assertEqual(snapshot["last_close_ticket"], 101)
        self.assertTrue(snapshot["last_close_accepted"])
        self.assertEqual(snapshot["last_modify_message"], "modify executed")

    def test_build_mt5_monitor_snapshot_returns_safe_empty_defaults(self) -> None:
        from synthetic_trader.monitoring.surface import build_mt5_monitor_snapshot

        snapshot = build_mt5_monitor_snapshot(events=[])

        self.assertIsNone(snapshot["symbol"])
        self.assertIsNone(snapshot["venue_symbol"])
        self.assertFalse(snapshot["runtime_ready"])
        self.assertEqual(snapshot["runtime_failures"], [])
        self.assertEqual(snapshot["positions"], 0)
        self.assertFalse(snapshot["reconcile_actionable"])
        self.assertIsNone(snapshot["reconcile_target_ticket"])
        self.assertIsNone(snapshot["last_close_ticket"])
        self.assertFalse(snapshot["last_close_accepted"])
        self.assertEqual(snapshot["last_modify_message"], "")
```

- [ ] **Step 2: Run the snapshot tests to verify they fail**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5SnapshotTests" -q`
Expected: FAIL because `build_mt5_monitor_snapshot()` does not exist yet

- [ ] **Step 3: Write the minimal MT5 snapshot builder**

```python
# src/synthetic_trader/monitoring/surface.py
def build_mt5_monitor_snapshot(
    *,
    events: list[dict[str, object]],
    symbol: str | None = None,
) -> dict[str, object]:
    filtered = filter_mt5_events(events)
    if symbol is not None:
        filtered = [event for event in filtered if event.get("symbol") == symbol]

    snapshot: dict[str, object] = {
        "symbol": None,
        "venue_symbol": None,
        "runtime_ready": False,
        "runtime_failures": [],
        "positions": 0,
        "sync_failures": [],
        "reconcile_actionable": False,
        "reconcile_target_ticket": None,
        "reconcile_failures": [],
        "last_close_ticket": None,
        "last_close_accepted": False,
        "last_close_retcode": None,
        "last_close_message": "",
        "last_modify_ticket": None,
        "last_modify_accepted": False,
        "last_modify_retcode": None,
        "last_modify_message": "",
    }

    for event in filtered:
        event_type = event.get("type")
        if event.get("symbol") is not None:
            snapshot["symbol"] = event.get("symbol")
        if event.get("venue_symbol") is not None:
            snapshot["venue_symbol"] = event.get("venue_symbol")

        if event_type == "mt5_runtime_summary":
            snapshot["runtime_ready"] = bool(event.get("ready", False))
            snapshot["runtime_failures"] = list(event.get("failures", []))
        elif event_type == "mt5_sync_summary":
            snapshot["positions"] = int(event.get("positions", 0))
            snapshot["sync_failures"] = list(event.get("failures", []))
        elif event_type == "mt5_reconcile_summary":
            snapshot["reconcile_actionable"] = bool(event.get("actionable", False))
            snapshot["reconcile_target_ticket"] = event.get("target_ticket")
            snapshot["reconcile_failures"] = list(event.get("failures", []))
        elif event_type == "mt5_close_result":
            snapshot["last_close_ticket"] = event.get("ticket")
            snapshot["last_close_accepted"] = bool(event.get("accepted", False))
            snapshot["last_close_retcode"] = event.get("retcode")
            snapshot["last_close_message"] = str(event.get("message", ""))
        elif event_type == "mt5_modify_result":
            snapshot["last_modify_ticket"] = event.get("ticket")
            snapshot["last_modify_accepted"] = bool(event.get("accepted", False))
            snapshot["last_modify_retcode"] = event.get("retcode")
            snapshot["last_modify_message"] = str(event.get("message", ""))

    return snapshot
```

- [ ] **Step 4: Run the snapshot tests to verify they pass**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5SnapshotTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/monitoring/surface.py tests/test_phase10_mt5_monitor.py
git commit -m "feat: add mt5 monitor snapshot builder"
```

## Task 3: Add MT5 Monitor Text Rendering

**Files:**
- Modify: `src/synthetic_trader/monitoring/surface.py`
- Modify: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Write the failing render test**

```python
class Phase10Mt5RenderTests(unittest.TestCase):
    def test_render_mt5_monitor_text_prints_explicit_mt5_fields(self) -> None:
        from synthetic_trader.monitoring.surface import render_mt5_monitor_text

        snapshot = {
            "symbol": "R_75",
            "venue_symbol": "Volatility 75 Index",
            "runtime_ready": True,
            "runtime_failures": [],
            "positions": 1,
            "sync_failures": [],
            "reconcile_actionable": True,
            "reconcile_target_ticket": 101,
            "reconcile_failures": [],
            "last_close_ticket": 101,
            "last_close_accepted": True,
            "last_close_retcode": 10009,
            "last_close_message": "close executed",
            "last_modify_ticket": 101,
            "last_modify_accepted": True,
            "last_modify_retcode": 10009,
            "last_modify_message": "modify executed",
        }

        rendered = render_mt5_monitor_text(snapshot)

        self.assertIn("mt5_symbol=R_75", rendered)
        self.assertIn("mt5_runtime_ready=True", rendered)
        self.assertIn("mt5_positions=1", rendered)
        self.assertIn("mt5_reconcile_target_ticket=101", rendered)
        self.assertIn("mt5_last_modify_message=modify executed", rendered)
```

- [ ] **Step 2: Run the render test to verify it fails**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5RenderTests" -q`
Expected: FAIL because `render_mt5_monitor_text()` does not exist yet

- [ ] **Step 3: Write the minimal MT5 renderer**

```python
# src/synthetic_trader/monitoring/surface.py
def render_mt5_monitor_text(snapshot: dict[str, object]) -> str:
    ordered_keys = [
        "symbol",
        "venue_symbol",
        "runtime_ready",
        "runtime_failures",
        "positions",
        "sync_failures",
        "reconcile_actionable",
        "reconcile_target_ticket",
        "reconcile_failures",
        "last_close_ticket",
        "last_close_accepted",
        "last_close_retcode",
        "last_close_message",
        "last_modify_ticket",
        "last_modify_accepted",
        "last_modify_retcode",
        "last_modify_message",
    ]
    return "\n".join(f"mt5_{key}={snapshot.get(key)}" for key in ordered_keys)
```

- [ ] **Step 4: Run the render test to verify it passes**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5RenderTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/monitoring/surface.py tests/test_phase10_mt5_monitor.py
git commit -m "feat: add mt5 monitor renderer"
```

## Task 4: Add Read-Only MT5 Monitor CLI Command

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Write the failing CLI monitor tests**

```python
import contextlib
import io
import json
import tempfile
from pathlib import Path


class Phase10Mt5CliMonitorTests(unittest.TestCase):
    def test_mt5_monitor_command_renders_latest_mt5_snapshot(self) -> None:
        from synthetic_trader.cli import main

        events = [
            {"type": "signal", "symbol": "R_75"},
            {
                "type": "mt5_runtime_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ready": True,
                "failures": [],
            },
            {
                "type": "mt5_sync_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "positions": 1,
                "failures": [],
            },
            {
                "type": "mt5_modify_result",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ticket": 101,
                "accepted": True,
                "retcode": 10009,
                "message": "modify executed",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_monitor.jsonl"
            journal_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "mt5-monitor",
                        "--journal",
                        str(journal_path),
                        "--symbol",
                        "R_75",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("mt5_symbol=R_75", output.getvalue())
        self.assertIn("mt5_positions=1", output.getvalue())
        self.assertIn("mt5_last_modify_message=modify executed", output.getvalue())

    def test_mt5_monitor_command_returns_non_zero_for_missing_journal(self) -> None:
        from synthetic_trader.cli import main

        missing_path = Path("does-not-exist.jsonl")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["mt5-monitor", "--journal", str(missing_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("error=", output.getvalue())
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5CliMonitorTests" -q`
Expected: FAIL because the `mt5-monitor` command does not exist yet

- [ ] **Step 3: Write the minimal CLI command**

```python
# src/synthetic_trader/cli.py imports
from synthetic_trader.monitoring.surface import (
    build_monitor_snapshot,
    build_mt5_monitor_snapshot,
    render_monitor_text,
    render_mt5_monitor_text,
)
```

```python
# src/synthetic_trader/cli.py parser
    mt5_monitor = subparsers.add_parser(
        "mt5-monitor",
        help="render a read-only MT5 monitor from journal analytics",
    )
    mt5_monitor.add_argument("--journal", required=True, help="MT5 analytics journal JSONL path")
    mt5_monitor.add_argument("--symbol", help="optional MT5 symbol filter")
```

```python
# src/synthetic_trader/cli.py command handler
    if args.command == "mt5-monitor":
        journal_path = Path(args.journal)
        if not journal_path.exists():
            print(f"error=journal_not_found:{journal_path}")
            return 1

        lines = journal_path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
        snapshot = build_mt5_monitor_snapshot(events=events, symbol=getattr(args, "symbol", None))
        print(render_mt5_monitor_text(snapshot))
        return 0
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5CliMonitorTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase10_mt5_monitor.py
git commit -m "feat: add mt5 monitor command"
```

## Task 5: Verify Empty and Coexistence Behavior

**Files:**
- Modify: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Write the failing empty and coexistence tests**

```python
class Phase10Mt5CoexistenceTests(unittest.TestCase):
    def test_mt5_monitor_command_returns_empty_snapshot_when_symbol_has_no_mt5_events(self) -> None:
        from synthetic_trader.cli import main

        events = [
            {
                "type": "mt5_runtime_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ready": True,
                "failures": [],
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_empty.jsonl"
            journal_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "mt5-monitor",
                        "--journal",
                        str(journal_path),
                        "--symbol",
                        "R_100",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("mt5_symbol=None", output.getvalue())
        self.assertIn("mt5_positions=0", output.getvalue())

    def test_existing_paper_monitor_helpers_still_render_summary_text(self) -> None:
        from synthetic_trader.monitoring.surface import build_monitor_snapshot, render_monitor_text

        snapshot = build_monitor_snapshot(
            live_summary={
                "symbol": "R_75",
                "signals": 3,
                "approved_signals": 2,
                "rejected_signals": 1,
                "session_resets": 0,
                "shutdown_closed_trades": 0,
            }
        )

        rendered = render_monitor_text(snapshot)

        self.assertIn("symbol=R_75", rendered)
        self.assertIn("signals=3", rendered)
```

- [ ] **Step 2: Run the coexistence tests to verify they fail if behavior is incomplete**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5CoexistenceTests" -q`
Expected: FAIL if symbol-filtered empty MT5 snapshots or paper-monitor coexistence are not behaving as specified

- [ ] **Step 3: Adjust the implementation only if needed**

```python
# src/synthetic_trader/monitoring/surface.py
# No new API is needed if Task 2 and Task 4 were implemented exactly.
# If the empty filtered snapshot test fails, keep the existing defaults and
# return the empty snapshot unchanged when no filtered MT5 events exist.
```

- [ ] **Step 4: Run the coexistence tests to verify they pass**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -k "Phase10Mt5CoexistenceTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase10_mt5_monitor.py src/synthetic_trader/monitoring/surface.py src/synthetic_trader/cli.py
git commit -m "test: cover mt5 monitor edge cases"
```

## Task 6: Run Phase 10 Regression

**Files:**
- Modify: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Run the focused Phase 10 suite**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py -q`
Expected:

```text
......                                                                   [100%]
```

- [ ] **Step 2: Run the Phase 9 analytics suite**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -q`
Expected:

```text
......                                                                   [100%]
```

- [ ] **Step 3: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
........................................................................
[100%]
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase10_mt5_monitor.py
git commit -m "test: validate mt5 monitor phase"
```

## Spec Coverage Check

- MT5 journal snapshot builder: covered by Tasks 1 and 2
- MT5 monitor snapshot shape: covered by Task 2
- read-only MT5 CLI monitor command: covered by Task 4
- MT5 text rendering: covered by Task 3
- symbol filtering and empty-state behavior: covered by Task 5
- focused tests and regression safety: covered by Task 6

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, commands, and code blocks
- Each test step states the expected failing or passing behavior directly

## Type Consistency Check

- `filter_mt5_events()` is the single event-filtering helper used by the MT5 monitor snapshot builder
- `build_mt5_monitor_snapshot()` is the single MT5 aggregation helper used by the CLI command
- `render_mt5_monitor_text()` is the single MT5 text rendering helper used by the CLI command
- Existing paper monitor helpers remain `build_monitor_snapshot()` and `render_monitor_text()` without renaming
