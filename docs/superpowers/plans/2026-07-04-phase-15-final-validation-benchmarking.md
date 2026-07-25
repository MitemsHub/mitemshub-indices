# Phase 15 Final Validation And Benchmarking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one final validation flow that emits both a compact CLI summary and a JSON artifact from the same normalized payload.

**Architecture:** Reuse existing live-paper summaries, optional latency profiles, and JSON-safe serialization to assemble one normalized validation payload. Render the CLI summary and write the optional artifact from that same payload so the human and machine outputs never drift apart.

**Tech Stack:** Python 3.11+, existing CLI command surface, monitoring helpers, JSON-safe serializers, `unittest`/`pytest`

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase15_final_validation.py`
  - Focused tests for validation payload structure, CLI output, artifact writing, and regression-safe final validation behavior.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\monitoring\surface.py`
  - Add normalized validation-payload and rendering helpers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\reporting\serializers.py`
  - Reuse or extend artifact dumping for final validation output if necessary.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add a final validation command path that can print the summary and optionally write the JSON artifact.

## Task 1: Add Normalized Validation Payload Builder

**Files:**
- Create: `tests/test_phase15_final_validation.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`

- [ ] **Step 1: Write the failing payload-shape test**

```python
from __future__ import annotations

import unittest

from synthetic_trader.live.paper_runner import LivePaperSummary
from synthetic_trader.monitoring.surface import build_validation_snapshot


class Phase15ValidationPayloadTests(unittest.TestCase):
    def test_build_validation_snapshot_combines_summary_and_latency(self) -> None:
        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=10,
            warmup_ticks=5,
            signals=2,
            approved_signals=1,
            rejected_signals=1,
            closed_trades=1,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1002.5,
            model_version="unit-test",
        )

        snapshot = build_validation_snapshot(
            venue="deriv",
            mode="dry-run-live",
            live_summary=summary,
            latency_summary={"total_duration_ms": 2.5},
        )

        self.assertEqual(snapshot["venue"], "deriv")
        self.assertEqual(snapshot["mode"], "dry-run-live")
        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertEqual(snapshot["final_equity"], 1002.5)
        self.assertEqual(snapshot["latency_total_ms"], 2.5)
```

- [ ] **Step 2: Run the payload-shape test to verify it fails**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationPayloadTests" -q`
Expected: FAIL because `build_validation_snapshot()` does not exist yet

- [ ] **Step 3: Write the minimal validation payload builder**

```python
# src/synthetic_trader/monitoring/surface.py
def build_validation_snapshot(
    *,
    venue: str,
    mode: str,
    live_summary,
    latency_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot = {
        "venue": venue,
        "mode": mode,
        "symbol": live_summary.symbol,
        "warmup_ticks": live_summary.warmup_ticks,
        "live_ticks": live_summary.live_ticks,
        "signals": live_summary.signals,
        "approved_signals": live_summary.approved_signals,
        "rejected_signals": live_summary.rejected_signals,
        "closed_trades": live_summary.closed_trades,
        "shutdown_closed_trades": live_summary.shutdown_closed_trades,
        "unresolved_positions": live_summary.unresolved_positions,
        "finalized": live_summary.finalized,
        "final_equity": live_summary.final_equity,
        "model_version": live_summary.model_version,
    }
    if latency_summary is not None:
        snapshot["latency_total_ms"] = latency_summary.get("total_duration_ms")
    return snapshot
```

- [ ] **Step 4: Run the payload-shape test to verify it passes**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationPayloadTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase15_final_validation.py src/synthetic_trader/monitoring/surface.py
git commit -m "feat: add final validation payload builder"
```

## Task 2: Add CLI Validation Rendering

**Files:**
- Modify: `tests/test_phase15_final_validation.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`

- [ ] **Step 1: Write the failing CLI-render test**

```python
class Phase15ValidationRenderingTests(unittest.TestCase):
    def test_render_validation_text_outputs_compact_summary(self) -> None:
        from synthetic_trader.monitoring.surface import render_validation_text

        rendered = render_validation_text(
            {
                "venue": "mt5",
                "mode": "dry-run-live",
                "symbol": "R_75",
                "finalized": True,
                "final_equity": 1001.5,
                "latency_total_ms": 2.0,
            }
        )

        self.assertIn("validation_venue=mt5", rendered)
        self.assertIn("validation_mode=dry-run-live", rendered)
        self.assertIn("validation_final_equity=1001.5", rendered)
        self.assertIn("validation_latency_total_ms=2.0", rendered)
```

- [ ] **Step 2: Run the CLI-render test to verify it fails**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationRenderingTests" -q`
Expected: FAIL because `render_validation_text()` does not exist yet

- [ ] **Step 3: Write the minimal validation renderer**

```python
# src/synthetic_trader/monitoring/surface.py
def render_validation_text(snapshot: dict[str, object]) -> str:
    ordered_keys = [
        "venue",
        "mode",
        "symbol",
        "warmup_ticks",
        "live_ticks",
        "signals",
        "approved_signals",
        "rejected_signals",
        "closed_trades",
        "shutdown_closed_trades",
        "unresolved_positions",
        "finalized",
        "final_equity",
        "model_version",
        "latency_total_ms",
    ]
    return "\n".join(
        f"validation_{key}={snapshot.get(key)}"
        for key in ordered_keys
        if key in snapshot
    )
```

- [ ] **Step 4: Run the CLI-render test to verify it passes**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationRenderingTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase15_final_validation.py src/synthetic_trader/monitoring/surface.py
git commit -m "feat: add final validation renderer"
```

## Task 3: Add JSON Artifact Writing

**Files:**
- Modify: `tests/test_phase15_final_validation.py`
- Modify: `src/synthetic_trader/reporting/serializers.py`

- [ ] **Step 1: Write the failing artifact-writing test**

```python
class Phase15ValidationArtifactTests(unittest.TestCase):
    def test_dump_json_file_writes_validation_snapshot(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from synthetic_trader.reporting.serializers import dump_json_file

        snapshot = {
            "venue": "deriv",
            "mode": "dry-run-live",
            "symbol": "R_75",
            "finalized": True,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "validation.json"
            dump_json_file(path, snapshot)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(written["venue"], "deriv")
        self.assertTrue(written["finalized"])
```

- [ ] **Step 2: Run the artifact-writing test to verify current behavior**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationArtifactTests" -q`
Expected: PASS if the existing serializer already supports the required validation artifact shape; FAIL only if artifact writing needs adjustment

- [ ] **Step 3: Adjust serialization only if needed**

```python
# src/synthetic_trader/reporting/serializers.py
# Keep dump_json_file() as the single JSON artifact writer.
# Adjust only if the validation payload exposes a JSON-unsafe edge case.
```

- [ ] **Step 4: Run the artifact-writing test again**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationArtifactTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/reporting/serializers.py tests/test_phase15_final_validation.py
git commit -m "test: lock final validation artifact writing"
```

## Task 4: Add Final Validation CLI Command

**Files:**
- Modify: `tests/test_phase15_final_validation.py`
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`

- [ ] **Step 1: Write the failing validation CLI test**

```python
class Phase15ValidationCliTests(unittest.TestCase):
    def test_validate_system_prints_summary_and_writes_artifact(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.live.paper_runner import LivePaperSummary

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=10,
            warmup_ticks=5,
            signals=2,
            approved_signals=1,
            rejected_signals=1,
            closed_trades=1,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1002.5,
            model_version="unit-test",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "validation.json"
            output = io.StringIO()
            with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "validate-system",
                            "--symbol",
                            "R_75",
                            "--artifact-output",
                            str(artifact_path),
                        ]
                    )

            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("validation_symbol=R_75", output.getvalue())
        self.assertEqual(artifact["symbol"], "R_75")
```

- [ ] **Step 2: Run the validation CLI test to verify it fails**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationCliTests" -q`
Expected: FAIL because the `validate-system` command does not exist yet

- [ ] **Step 3: Write the minimal validation CLI path**

```python
# src/synthetic_trader/cli.py imports
from synthetic_trader.monitoring.surface import (
    build_monitor_snapshot,
    build_mt5_monitor_snapshot,
    build_validation_snapshot,
    render_monitor_text,
    render_mt5_monitor_text,
    render_validation_text,
)
from synthetic_trader.reporting.serializers import dump_json_file
```

```python
# src/synthetic_trader/cli.py parser
    validate_system = subparsers.add_parser(
        "validate-system",
        help="run final validation and benchmarking summary",
    )
    validate_system.add_argument("--symbol", required=True)
    validate_system.add_argument("--artifact-output", help="optional validation JSON output path")
```

```python
# src/synthetic_trader/cli.py command handler
    if args.command == "validate-system":
        summary = asyncio.run(
            run_live_paper(
                symbol=args.symbol,
                duration_sec=0,
                max_live_ticks=0,
            )
        )
        snapshot = build_validation_snapshot(
            venue="deriv",
            mode="paper",
            live_summary=summary,
        )
        print(render_validation_text(snapshot))
        if args.artifact_output:
            dump_json_file(args.artifact_output, snapshot)
        return 0
```

- [ ] **Step 4: Run the validation CLI test to verify it passes**

Run: `python -m pytest tests/test_phase15_final_validation.py -k "Phase15ValidationCliTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/monitoring/surface.py src/synthetic_trader/reporting/serializers.py tests/test_phase15_final_validation.py
git commit -m "feat: add final validation command"
```

## Task 5: Run Phase 15 Regression

**Files:**
- Modify: `tests/test_phase15_final_validation.py`

- [ ] **Step 1: Run the focused Phase 15 suite**

Run: `python -m pytest tests/test_phase15_final_validation.py -q`
Expected:

```text
....                                                                     [100%]
```

- [ ] **Step 2: Run the shared and venue regression suites**

Run: `python -m pytest tests/test_phase11_latency_hardening.py tests/test_phase13_mt5_latency_tuning.py tests/test_phase14_deriv_latency_tuning.py tests/test_live_paper_runner.py -q`
Expected:

```text
.........................                                                [100%]
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
git add tests/test_phase15_final_validation.py src/synthetic_trader/monitoring/surface.py src/synthetic_trader/reporting/serializers.py src/synthetic_trader/cli.py
git commit -m "test: validate final validation phase"
```

## Spec Coverage Check

- unified validation payload: covered by Task 1
- CLI validation summary: covered by Tasks 2 and 4
- JSON validation artifact: covered by Tasks 3 and 4
- shared and venue coverage: covered by Tasks 1 and 4
- benchmark repeatability: covered by Task 5 through stable payload and regression safety

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, commands, and explicit code blocks
- Each verification step states the expected pass/fail behavior directly

## Type Consistency Check

- `build_validation_snapshot()` is the single normalized validation payload builder
- `render_validation_text()` is the single CLI renderer for final validation output
- `dump_json_file()` remains the single JSON artifact writer
- `validate-system` is the single final validation command path
