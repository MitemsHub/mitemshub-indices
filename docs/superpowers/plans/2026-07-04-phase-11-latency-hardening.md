# Phase 11 Latency Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure and harden the shared live execution path so the project can identify and reduce real latency overhead without weakening safety behavior.

**Architecture:** Add a small, explicit latency profile surface around the shared supervised/live path rather than scattering ad-hoc timers across the codebase. Use that profile to classify execution-critical stages versus operator-side-effect stages, then make only the smallest optimizations justified by the measured results.

**Tech Stack:** Python 3.11+, `dataclasses`, `time.perf_counter`, `argparse`, existing supervised live and paper-live runtime paths, `unittest`/`pytest`

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase11_latency_hardening.py`
  - Focused tests for latency stage recording, summary structure, classification, CLI surfacing, and regression safety.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Add shared-path latency stage recording and summary helpers around supervised routing.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Add timing boundaries for key shared live runtime work and any small justified overhead reduction.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add a minimal latency-summary surfacing path only when explicitly requested.

## Task 1: Add Shared Latency Summary Types

**Files:**
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Create: `tests/test_phase11_latency_hardening.py`

- [ ] **Step 1: Write the failing latency summary type test**

```python
from __future__ import annotations

import unittest

from synthetic_trader.live.supervised_live import LatencyProfile, LatencyStage


class Phase11LatencyTypeTests(unittest.TestCase):
    def test_latency_profile_stores_stages_and_total_duration(self) -> None:
        profile = LatencyProfile(
            stages=(
                LatencyStage(name="readiness", duration_ms=1.5, category="critical"),
                LatencyStage(name="summary_print", duration_ms=0.5, category="side_effect"),
            )
        )

        self.assertEqual(profile.total_duration_ms, 2.0)
        self.assertEqual(profile.stages[0].name, "readiness")
        self.assertEqual(profile.stages[1].category, "side_effect")
```

- [ ] **Step 2: Run the type test to verify it fails**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyTypeTests" -q`
Expected: FAIL with `ImportError` because `LatencyProfile` and `LatencyStage` do not exist yet

- [ ] **Step 3: Write the minimal latency summary types**

```python
# src/synthetic_trader/live/supervised_live.py
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LatencyStage:
    name: str
    duration_ms: float
    category: str


@dataclass(frozen=True)
class LatencyProfile:
    stages: tuple[LatencyStage, ...] = field(default_factory=tuple)

    @property
    def total_duration_ms(self) -> float:
        return round(sum(stage.duration_ms for stage in self.stages), 6)
```

- [ ] **Step 4: Run the type test to verify it passes**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyTypeTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase11_latency_hardening.py
git commit -m "feat: add latency summary types"
```

## Task 2: Add Stage Recording and Classification Helpers

**Files:**
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Modify: `tests/test_phase11_latency_hardening.py`

- [ ] **Step 1: Write the failing stage recording test**

```python
class Phase11LatencyRecordingTests(unittest.TestCase):
    def test_record_latency_stage_appends_structured_stage(self) -> None:
        from synthetic_trader.live.supervised_live import LatencyRecorder

        recorder = LatencyRecorder()
        recorder.record_stage("readiness", duration_ms=1.25, category="critical")
        recorder.record_stage("journal", duration_ms=0.75, category="side_effect")

        profile = recorder.build_profile()

        self.assertEqual(len(profile.stages), 2)
        self.assertEqual(profile.stages[0].name, "readiness")
        self.assertEqual(profile.stages[1].category, "side_effect")
        self.assertEqual(profile.total_duration_ms, 2.0)
```

- [ ] **Step 2: Run the recording test to verify it fails**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyRecordingTests" -q`
Expected: FAIL because `LatencyRecorder` does not exist yet

- [ ] **Step 3: Write the minimal stage recording helper**

```python
# src/synthetic_trader/live/supervised_live.py
class LatencyRecorder:
    def __init__(self) -> None:
        self._stages: list[LatencyStage] = []

    def record_stage(self, name: str, *, duration_ms: float, category: str) -> None:
        self._stages.append(
            LatencyStage(
                name=name,
                duration_ms=round(duration_ms, 6),
                category=category,
            )
        )

    def build_profile(self) -> LatencyProfile:
        return LatencyProfile(stages=tuple(self._stages))
```

- [ ] **Step 4: Run the recording test to verify it passes**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyRecordingTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase11_latency_hardening.py
git commit -m "feat: add latency recorder"
```

## Task 3: Instrument Supervised Routing Boundaries

**Files:**
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Modify: `tests/test_phase11_latency_hardening.py`

- [ ] **Step 1: Write the failing supervised-routing latency test**

```python
class Phase11SupervisedLatencyTests(unittest.TestCase):
    def test_run_supervised_live_session_can_return_latency_profile(self) -> None:
        import asyncio

        from synthetic_trader.config import LiveMode, Venue
        from synthetic_trader.live.supervised_live import run_supervised_live_session

        async def dry_run_runner():
            return "dry-run-result"

        result, profile = asyncio.run(
            run_supervised_live_session(
                venue=Venue.DERIV,
                mode=LiveMode.DRY_RUN_LIVE,
                readiness_ok=True,
                dry_run_runner=dry_run_runner,
                armed_runner=dry_run_runner,
                capture_latency=True,
            )
        )

        self.assertEqual(result, "dry-run-result")
        self.assertGreaterEqual(len(profile.stages), 1)
        self.assertEqual(profile.stages[0].category, "critical")
```

- [ ] **Step 2: Run the supervised-routing test to verify it fails**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11SupervisedLatencyTests" -q`
Expected: FAIL because `run_supervised_live_session()` does not support `capture_latency`

- [ ] **Step 3: Add minimal optional latency capture to supervised routing**

```python
# src/synthetic_trader/live/supervised_live.py
import time


async def run_supervised_live_session(
    *,
    venue,
    mode,
    readiness_ok: bool,
    dry_run_runner,
    armed_runner,
    capture_latency: bool = False,
):
    recorder = LatencyRecorder() if capture_latency else None

    start = time.perf_counter()
    if not readiness_ok:
        raise RuntimeError("supervised live session requires readiness")
    if recorder is not None:
        recorder.record_stage(
            "readiness_gate",
            duration_ms=(time.perf_counter() - start) * 1000.0,
            category="critical",
        )

    route_start = time.perf_counter()
    if mode.value == "dry-run-live":
        result = await dry_run_runner()
    elif mode.value == "armed-live":
        result = await armed_runner()
    else:
        raise RuntimeError(f"unsupported supervised live mode: {mode.value}")

    if recorder is not None:
        recorder.record_stage(
            "supervised_route",
            duration_ms=(time.perf_counter() - route_start) * 1000.0,
            category="critical",
        )
        return result, recorder.build_profile()
    return result
```

- [ ] **Step 4: Run the supervised-routing test to verify it passes**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11SupervisedLatencyTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase11_latency_hardening.py
git commit -m "feat: instrument supervised live routing"
```

## Task 4: Instrument Shared Paper-Live Runtime Stages

**Files:**
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Modify: `tests/test_phase11_latency_hardening.py`

- [ ] **Step 1: Write the failing shared-runtime latency test**

```python
class Phase11PaperLatencyTests(unittest.TestCase):
    def test_live_paper_run_can_emit_latency_stage_names(self) -> None:
        from synthetic_trader.live.paper_runner import classify_latency_stage

        self.assertEqual(classify_latency_stage("journal_append"), "side_effect")
        self.assertEqual(classify_latency_stage("signal_decision"), "critical")
```

- [ ] **Step 2: Run the shared-runtime test to verify it fails**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11PaperLatencyTests" -q`
Expected: FAIL because `classify_latency_stage()` does not exist yet

- [ ] **Step 3: Write the minimal shared-stage classifier**

```python
# src/synthetic_trader/live/paper_runner.py
def classify_latency_stage(stage_name: str) -> str:
    if stage_name in {"journal_append", "summary_print", "monitor_emit"}:
        return "side_effect"
    return "critical"
```

- [ ] **Step 4: Run the shared-runtime test to verify it passes**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11PaperLatencyTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/paper_runner.py tests/test_phase11_latency_hardening.py
git commit -m "feat: classify latency stages"
```

## Task 5: Surface Latency Profile Only On Demand

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `tests/test_phase11_latency_hardening.py`

- [ ] **Step 1: Write the failing CLI latency test**

```python
class Phase11LatencyCliTests(unittest.TestCase):
    def test_paper_live_can_print_latency_summary_when_requested(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        from synthetic_trader.cli import main

        output = io.StringIO()
        with patch("synthetic_trader.cli.run_live_paper", return_value="summary"):
            with patch("synthetic_trader.cli._render_latency_profile", return_value="latency_total_ms=2.0"):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "paper-live",
                            "--symbol",
                            "R_75",
                            "--latency-profile",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn("latency_total_ms=2.0", output.getvalue())
```

- [ ] **Step 2: Run the CLI latency test to verify it fails**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyCliTests" -q`
Expected: FAIL because `--latency-profile` support does not exist yet

- [ ] **Step 3: Add minimal CLI latency surfacing**

```python
# src/synthetic_trader/cli.py parser
    paper_live.add_argument(
        "--latency-profile",
        action="store_true",
        help="print shared live-path latency summary",
    )
```

```python
# src/synthetic_trader/cli.py helper
def _render_latency_profile(profile) -> str:
    lines = [f"latency_total_ms={profile.total_duration_ms}"]
    for stage in profile.stages:
        lines.append(f"latency_stage={stage.name},{stage.category},{stage.duration_ms}")
    return "\n".join(lines)
```

```python
# src/synthetic_trader/cli.py paper-live branch
        latency_profile = None
        if args.latency_profile and mode is not LiveMode.PAPER:
            summary, latency_profile = asyncio.run(
                run_supervised_live_session(
                    venue=venue,
                    mode=mode,
                    readiness_ok=readiness.ready,
                    dry_run_runner=lambda: run_live_paper(**run_kwargs),
                    armed_runner=lambda: run_live_paper(**run_kwargs),
                    capture_latency=True,
                )
            )
        elif mode is LiveMode.PAPER:
            summary = asyncio.run(run_live_paper(**run_kwargs))
        else:
            summary = asyncio.run(
                run_supervised_live_session(
                    venue=venue,
                    mode=mode,
                    readiness_ok=readiness.ready,
                    dry_run_runner=lambda: run_live_paper(**run_kwargs),
                    armed_runner=lambda: run_live_paper(**run_kwargs),
                )
            )

        if latency_profile is not None:
            print(_render_latency_profile(latency_profile))
```

- [ ] **Step 4: Run the CLI latency test to verify it passes**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyCliTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase11_latency_hardening.py
git commit -m "feat: add on-demand latency summary"
```

## Task 6: Verify Regression Safety And Summary Shape

**Files:**
- Modify: `tests/test_phase11_latency_hardening.py`

- [ ] **Step 1: Write the failing regression-safety test**

```python
class Phase11LatencyRegressionTests(unittest.TestCase):
    def test_latency_capture_is_optional_and_existing_behavior_remains_supported(self) -> None:
        import asyncio

        from synthetic_trader.config import LiveMode, Venue
        from synthetic_trader.live.supervised_live import run_supervised_live_session

        async def dry_run_runner():
            return "ok"

        result = asyncio.run(
            run_supervised_live_session(
                venue=Venue.DERIV,
                mode=LiveMode.DRY_RUN_LIVE,
                readiness_ok=True,
                dry_run_runner=dry_run_runner,
                armed_runner=dry_run_runner,
            )
        )

        self.assertEqual(result, "ok")
```

- [ ] **Step 2: Run the regression-safety test to verify it fails if behavior drift exists**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -k "Phase11LatencyRegressionTests" -q`
Expected: PASS if optional latency capture preserved existing behavior; FAIL if the instrumentation changed the default return contract incorrectly

- [ ] **Step 3: Adjust implementation only if needed**

```python
# src/synthetic_trader/live/supervised_live.py
# Keep the default behavior unchanged:
# - return the existing session result when capture_latency is False
# - return (result, profile) only when capture_latency is True
```

- [ ] **Step 4: Run the full focused Phase 11 suite**

Run: `python -m pytest tests/test_phase11_latency_hardening.py -q`
Expected:

```text
......                                                                   [100%]
```

- [ ] **Step 5: Run the shared live regression suites**

Run: `python -m pytest tests/test_phase4_supervised_live.py tests/test_live_paper_runner.py -q`
Expected:

```text
............                                                             [100%]
```

- [ ] **Step 6: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
........................................................................
[100%]
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_phase11_latency_hardening.py src/synthetic_trader/live/supervised_live.py src/synthetic_trader/live/paper_runner.py src/synthetic_trader/cli.py
git commit -m "test: validate latency hardening phase"
```

## Spec Coverage Check

- shared live-path instrumentation: covered by Tasks 1, 2, and 3
- compact latency summary shape: covered by Tasks 1 and 2
- critical versus side-effect classification: covered by Task 4
- on-demand CLI surfacing only: covered by Task 5
- regression-safe optimization and unchanged safety semantics: covered by Task 6

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, explicit commands, and concrete code blocks
- Each verification step states the expected failure or pass condition directly

## Type Consistency Check

- `LatencyStage`, `LatencyProfile`, and `LatencyRecorder` are introduced first and reused consistently later
- `capture_latency` is the single optional flag for latency capture in the supervised path
- `_render_latency_profile()` is the single CLI rendering helper for latency output
- `classify_latency_stage()` is the single stage-category helper referenced in this plan
