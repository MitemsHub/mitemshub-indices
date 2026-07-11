# Supervised Rollout Enablement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the smallest practical rollout enablement layer for the MT5-first supervised rollout: a read-only rollout preflight command, focused tests, and operator-facing checklist/runbook documents.

**Architecture:** Reuse the existing MT5 readiness checks, validation artifact flow, and MT5 monitor snapshot instead of inventing a second live-control system. Add one compact rollout-preflight surface that combines current readiness, optional final-validation evidence, and optional MT5 journal evidence into one operator-readable snapshot, then document exactly how to use it during `dry-run-live` rollout sessions.

**Tech Stack:** Python 3.11+, `argparse`, existing MT5 readiness helpers, monitoring snapshot/render helpers, JSON artifacts, `unittest`/`pytest`, Markdown docs

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase16_supervised_rollout.py`
  - Focused regression tests for rollout snapshot building, rendering, and the new CLI preflight command.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\docs\superpowers\runbooks\2026-07-05-mt5-supervised-rollout.md`
  - Operator runbook for MT5-first dry-run rollout sessions, pass/fail rules, and escalation behavior.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\docs\superpowers\templates\mt5-rollout-session-record.md`
  - Session template for recording preflight status, pass/fail outcome, stop conditions, and operator notes.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\monitoring\surface.py`
  - Add rollout-preflight snapshot and text rendering helpers that reuse existing readiness, validation, and MT5 monitor data.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add a read-only `mt5-rollout-check` command that prints a compact rollout preflight summary.

## Task 1: Add Rollout Snapshot Helpers

**Files:**
- Create: `tests/test_phase16_supervised_rollout.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`

- [ ] **Step 1: Write the failing rollout-snapshot test**

```python
from __future__ import annotations

import unittest

from synthetic_trader.monitoring.surface import build_rollout_status_snapshot


class Phase16RolloutSnapshotTests(unittest.TestCase):
    def test_build_rollout_status_snapshot_combines_readiness_validation_and_mt5_state(self) -> None:
        snapshot = build_rollout_status_snapshot(
            venue="mt5",
            symbol="R_75",
            live_mode="dry-run-live",
            readiness_ok=True,
            readiness_failures=(),
            validation_snapshot={
                "finalized": True,
                "final_equity": 1003.25,
                "model_version": "unit-test",
            },
            mt5_snapshot={
                "runtime_ready": True,
                "positions": 0,
                "sync_failures": [],
            },
        )

        self.assertEqual(snapshot["rollout_stage"], "dry-run-preflight")
        self.assertEqual(snapshot["venue"], "mt5")
        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertTrue(snapshot["readiness_ok"])
        self.assertTrue(snapshot["validation_finalized"])
        self.assertEqual(snapshot["validation_final_equity"], 1003.25)
        self.assertTrue(snapshot["mt5_runtime_ready"])
        self.assertEqual(snapshot["mt5_positions"], 0)
```

- [ ] **Step 2: Run the rollout-snapshot test to verify it fails**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -k "Phase16RolloutSnapshotTests" -q`
Expected: FAIL because `build_rollout_status_snapshot()` does not exist yet

- [ ] **Step 3: Write the minimal rollout snapshot builder**

```python
# src/synthetic_trader/monitoring/surface.py
def build_rollout_status_snapshot(
    *,
    venue: str,
    symbol: str,
    live_mode: str,
    readiness_ok: bool,
    readiness_failures: tuple[str, ...],
    validation_snapshot: dict[str, object] | None = None,
    mt5_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    validation_snapshot = validation_snapshot or {}
    mt5_snapshot = mt5_snapshot or {}
    return {
        "rollout_stage": "dry-run-preflight" if live_mode == "dry-run-live" else "armed-live-preflight",
        "venue": venue,
        "symbol": symbol,
        "live_mode": live_mode,
        "readiness_ok": readiness_ok,
        "readiness_failures": list(readiness_failures),
        "validation_finalized": bool(validation_snapshot.get("finalized", False)),
        "validation_final_equity": validation_snapshot.get("final_equity"),
        "validation_model_version": validation_snapshot.get("model_version"),
        "mt5_runtime_ready": bool(mt5_snapshot.get("runtime_ready", False)),
        "mt5_positions": int(mt5_snapshot.get("positions", 0)),
        "mt5_sync_failures": list(mt5_snapshot.get("sync_failures", [])),
    }
```

- [ ] **Step 4: Run the rollout-snapshot test to verify it passes**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -k "Phase16RolloutSnapshotTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase16_supervised_rollout.py src/synthetic_trader/monitoring/surface.py
git commit -m "feat: add rollout preflight snapshot"
```

## Task 2: Add Rollout Text Rendering

**Files:**
- Modify: `tests/test_phase16_supervised_rollout.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`

- [ ] **Step 1: Write the failing rollout-render test**

```python
class Phase16RolloutRenderingTests(unittest.TestCase):
    def test_render_rollout_status_text_outputs_explicit_rollout_fields(self) -> None:
        from synthetic_trader.monitoring.surface import render_rollout_status_text

        rendered = render_rollout_status_text(
            {
                "rollout_stage": "dry-run-preflight",
                "venue": "mt5",
                "symbol": "R_75",
                "live_mode": "dry-run-live",
                "readiness_ok": True,
                "validation_finalized": True,
                "mt5_runtime_ready": True,
            }
        )

        self.assertIn("rollout_stage=dry-run-preflight", rendered)
        self.assertIn("rollout_venue=mt5", rendered)
        self.assertIn("rollout_symbol=R_75", rendered)
        self.assertIn("rollout_live_mode=dry-run-live", rendered)
        self.assertIn("rollout_readiness_ok=True", rendered)
        self.assertIn("rollout_mt5_runtime_ready=True", rendered)
```

- [ ] **Step 2: Run the rollout-render test to verify it fails**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -k "Phase16RolloutRenderingTests" -q`
Expected: FAIL because `render_rollout_status_text()` does not exist yet

- [ ] **Step 3: Write the minimal rollout renderer**

```python
# src/synthetic_trader/monitoring/surface.py
def render_rollout_status_text(snapshot: dict[str, object]) -> str:
    ordered_keys = [
        "rollout_stage",
        "venue",
        "symbol",
        "live_mode",
        "readiness_ok",
        "readiness_failures",
        "validation_finalized",
        "validation_final_equity",
        "validation_model_version",
        "mt5_runtime_ready",
        "mt5_positions",
        "mt5_sync_failures",
    ]
    lines: list[str] = []
    for key in ordered_keys:
        if key not in snapshot:
            continue
        prefix = key if key == "rollout_stage" else f"rollout_{key}"
        lines.append(f"{prefix}={snapshot.get(key)}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the rollout-render test to verify it passes**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -k "Phase16RolloutRenderingTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase16_supervised_rollout.py src/synthetic_trader/monitoring/surface.py
git commit -m "feat: add rollout preflight renderer"
```

## Task 3: Add `mt5-rollout-check` CLI Command

**Files:**
- Modify: `tests/test_phase16_supervised_rollout.py`
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`

- [ ] **Step 1: Write the failing CLI preflight test**

```python
class Phase16RolloutCliTests(unittest.TestCase):
    def test_mt5_rollout_check_prints_compact_preflight_summary(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            venue_symbol="Volatility 75 Index",
            failures=(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            validation_path = Path(tmpdir) / "validation.json"
            validation_path.write_text(
                json.dumps(
                    {
                        "venue": "mt5",
                        "mode": "dry-run-live",
                        "symbol": "R_75",
                        "finalized": True,
                        "final_equity": 1003.25,
                        "model_version": "unit-test",
                    }
                ),
                encoding="utf-8",
            )
            journal_path = Path(tmpdir) / "mt5.jsonl"
            journal_path.write_text(
                json.dumps(
                    {
                        "type": "mt5_sync_summary",
                        "symbol": "R_75",
                        "venue_symbol": "Volatility 75 Index",
                        "positions": 0,
                        "failures": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-rollout-check",
                                "--symbol",
                                "R_75",
                                "--live-mode",
                                "dry-run-live",
                                "--mt5-server",
                                "server",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 75 Index",
                                "--validation-json",
                                str(validation_path),
                                "--journal",
                                str(journal_path),
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertIn("rollout_stage=dry-run-preflight", output.getvalue())
        self.assertIn("rollout_symbol=R_75", output.getvalue())
        self.assertIn("rollout_validation_finalized=True", output.getvalue())
        self.assertIn("rollout_mt5_positions=0", output.getvalue())
```

- [ ] **Step 2: Run the CLI preflight test to verify it fails**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -k "Phase16RolloutCliTests" -q`
Expected: FAIL because the `mt5-rollout-check` command does not exist yet

- [ ] **Step 3: Add the parser entry and imports**

```python
# src/synthetic_trader/cli.py imports
from synthetic_trader.monitoring.surface import (
    build_monitor_snapshot,
    build_mt5_monitor_snapshot,
    build_rollout_status_snapshot,
    build_validation_snapshot,
    render_monitor_text,
    render_mt5_monitor_text,
    render_rollout_status_text,
    render_validation_text,
)
```

```python
# src/synthetic_trader/cli.py parser
    mt5_rollout_check = subparsers.add_parser(
        "mt5-rollout-check",
        help="render a read-only MT5 rollout preflight summary",
    )
    mt5_rollout_check.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_rollout_check.add_argument(
        "--live-mode",
        default=LiveMode.DRY_RUN_LIVE.value,
        choices=[LiveMode.DRY_RUN_LIVE.value, LiveMode.ARMED_LIVE.value],
    )
    mt5_rollout_check.add_argument("--mt5-server", required=True)
    mt5_rollout_check.add_argument("--mt5-login", required=True)
    mt5_rollout_check.add_argument("--mt5-password", required=True)
    mt5_rollout_check.add_argument("--mt5-terminal-path")
    mt5_rollout_check.add_argument("--mt5-symbol", required=True)
    mt5_rollout_check.add_argument("--validation-json", help="optional validation artifact JSON path")
    mt5_rollout_check.add_argument("--journal", help="optional MT5 analytics journal JSONL path")
```

- [ ] **Step 4: Add the minimal command handler**

```python
# src/synthetic_trader/cli.py command handler
    if args.command == "mt5-rollout-check":
        mode = LiveMode(args.live_mode)
        mt5_config = _build_mt5_config(args)
        runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
        readiness = build_live_readiness_report(
            venue=Venue.MT5,
            mode=mode,
            symbol=args.symbol,
            app_id=None,
            token=None,
            armed=False,
            supported_symbols=set(TraderConfig.default().symbols),
            mt5_config=mt5_config,
            mt5_dependency_ready=mt5_dependency_available(),
            mt5_runtime_status=runtime_status,
        )

        validation_snapshot = None
        if args.validation_json:
            validation_snapshot = json.loads(Path(args.validation_json).read_text(encoding="utf-8"))

        mt5_snapshot = None
        if args.journal:
            journal_path = Path(args.journal)
            events = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            mt5_snapshot = build_mt5_monitor_snapshot(events=events, symbol=args.symbol)

        snapshot = build_rollout_status_snapshot(
            venue=Venue.MT5.value,
            symbol=args.symbol,
            live_mode=mode.value,
            readiness_ok=readiness.ready,
            readiness_failures=readiness.failures,
            validation_snapshot=validation_snapshot,
            mt5_snapshot=mt5_snapshot,
        )
        print(render_rollout_status_text(snapshot))
        return 0
```

- [ ] **Step 5: Run the CLI preflight test to verify it passes**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -k "Phase16RolloutCliTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add tests/test_phase16_supervised_rollout.py src/synthetic_trader/cli.py src/synthetic_trader/monitoring/surface.py
git commit -m "feat: add mt5 rollout preflight command"
```

## Task 4: Add MT5 Rollout Runbook

**Files:**
- Create: `docs/superpowers/runbooks/2026-07-05-mt5-supervised-rollout.md`

- [ ] **Step 1: Write the runbook document**

```md
# MT5 Supervised Rollout Runbook

## Purpose

This runbook defines the exact operator flow for the MT5-first supervised rollout using `dry-run-live` as the first live gate.

## Preflight

1. Confirm the latest validation artifact exists.
2. Run `mt5-rollout-check`.
3. Confirm `rollout_readiness_ok=True`.
4. Confirm `rollout_validation_finalized=True`.
5. Confirm `rollout_mt5_runtime_ready=True`.
6. Confirm no unresolved stop condition is active before session start.

## Dry-Run Session

Run:

```bash
python -m synthetic_trader.cli mt5-rollout-check --symbol R_75 --live-mode dry-run-live --mt5-server <server> --mt5-login <login> --mt5-password <password> --mt5-symbol "Volatility 75 Index" --validation-json artifacts/validation_r75.json --journal journals/mt5_analytics.jsonl
python -m synthetic_trader.cli paper-live --symbol R_75 --venue mt5 --live-mode dry-run-live --mt5-server <server> --mt5-login <login> --mt5-password <password> --mt5-symbol "Volatility 75 Index"
python -m synthetic_trader.cli mt5-monitor --journal journals/mt5_analytics.jsonl --symbol R_75
```

## Pass Criteria

1. Readiness remains healthy.
2. Monitor output remains explainable.
3. No unresolved lifecycle state appears.
4. Operator records a clear pass/fail decision at session end.

## Stop Conditions

1. Any readiness failure.
2. Any MT5 runtime inconsistency.
3. Any ambiguous lifecycle result.
4. Any operator uncertainty about current state.
```

- [ ] **Step 2: Review the runbook for command-path accuracy**

Run: `python - <<'PY'\nfrom pathlib import Path\npath = Path(r'docs/superpowers/runbooks/2026-07-05-mt5-supervised-rollout.md')\ntext = path.read_text(encoding='utf-8')\nassert 'mt5-rollout-check' in text\nassert 'paper-live' in text\nassert 'mt5-monitor' in text\nprint('runbook-ok')\nPY`
Expected: `runbook-ok`

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/runbooks/2026-07-05-mt5-supervised-rollout.md
git commit -m "docs: add mt5 supervised rollout runbook"
```

## Task 5: Add Session Record Template

**Files:**
- Create: `docs/superpowers/templates/mt5-rollout-session-record.md`

- [ ] **Step 1: Write the session record template**

```md
# MT5 Rollout Session Record

## Session Metadata

- Date:
- Operator:
- Symbol:
- Live mode:
- Validation artifact:
- Journal path:

## Preflight Status

- `rollout_readiness_ok=` 
- `rollout_validation_finalized=`
- `rollout_mt5_runtime_ready=`
- `rollout_mt5_positions=`
- `rollout_readiness_failures=`
- `rollout_mt5_sync_failures=`

## Session Outcome

- Result: PASS / FAIL
- Stop condition hit:
- Manual rescue required: YES / NO
- Unresolved positions: YES / NO

## Notes

- What happened:
- What was learned:
- What must change before the next session:
```

- [ ] **Step 2: Review the template for rollout field alignment**

Run: `python - <<'PY'\nfrom pathlib import Path\npath = Path(r'docs/superpowers/templates/mt5-rollout-session-record.md')\ntext = path.read_text(encoding='utf-8')\nassert 'rollout_readiness_ok=' in text\nassert 'rollout_validation_finalized=' in text\nassert 'rollout_mt5_runtime_ready=' in text\nprint('template-ok')\nPY`
Expected: `template-ok`

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/templates/mt5-rollout-session-record.md
git commit -m "docs: add mt5 rollout session template"
```

## Task 6: Run Rollout Enablement Regression

**Files:**
- Modify: `tests/test_phase16_supervised_rollout.py`

- [ ] **Step 1: Run the focused rollout suite**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -q`
Expected:

```text
...                                                                      [100%]
```

- [ ] **Step 2: Run nearby MT5 and validation regressions**

Run: `python -m pytest tests/test_phase10_mt5_monitor.py tests/test_phase15_final_validation.py tests/test_phase13_mt5_latency_tuning.py -q`
Expected:

```text
.............                                                            [100%]
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
git add tests/test_phase16_supervised_rollout.py src/synthetic_trader/cli.py src/synthetic_trader/monitoring/surface.py docs/superpowers/runbooks/2026-07-05-mt5-supervised-rollout.md docs/superpowers/templates/mt5-rollout-session-record.md
git commit -m "feat: add mt5 supervised rollout enablement"
```

## Spec Coverage Check

- MT5-first rollout alignment: covered by Tasks 3, 4, and 5
- `dry-run-live` as the first live gate: covered by Tasks 1, 3, and 4
- session rules and operator checklist: covered by Tasks 4 and 5
- stop conditions and pass/fail recording: covered by Tasks 4 and 5
- practical rollout discipline with minimal repo additions: covered by Tasks 1, 2, and 3

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact file paths, commands, and code or document content
- Each verification step states the expected pass/fail result directly

## Type Consistency Check

- `build_rollout_status_snapshot()` is the single rollout-preflight payload builder
- `render_rollout_status_text()` is the single rollout-preflight renderer
- `mt5-rollout-check` is the single read-only CLI preflight command
- the runbook and template both reference the same `rollout_*` field names emitted by the CLI
