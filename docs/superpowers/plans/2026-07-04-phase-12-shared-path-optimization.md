# Phase 12 Shared-Path Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce avoidable shared-path latency before the execution boundary while preserving all supervised live, readiness, and accounting behavior.

**Architecture:** Keep the Phase 11 latency surface intact and use it to make small, explicit reductions in shared-path overhead. Optimize the pre-broker path first by tightening routing, reducing unnecessary side effects before execution-relevant work, and preserving the optional latency-capture contract so later venue-specific tuning has a cleaner baseline.

**Tech Stack:** Python 3.11+, `asyncio`, `time.perf_counter`, `dataclasses`, shared live/supervised runtime path, `unittest`/`pytest`

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase12_shared_path_optimization.py`
  - Focused tests for pre-broker shared-path overhead reduction, preserved latency capture, and regression-safe behavior.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Tighten shared routing and preserve meaningful latency stages with minimal overhead.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Reduce avoidable synchronous side effects or repeated shared-path work where justified.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Keep latency surfacing opt-in and adjust only if optimized-path output order needs a small correction.

## Task 1: Lock In The Current Shared-Path Contract

**Files:**
- Create: `tests/test_phase12_shared_path_optimization.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`

- [ ] **Step 1: Write the failing shared-path contract tests**

```python
from __future__ import annotations

import asyncio
import unittest

from synthetic_trader.config import LiveMode, Venue
from synthetic_trader.live.supervised_live import run_supervised_live_session


class Phase12SharedPathContractTests(unittest.TestCase):
    def test_supervised_session_still_returns_plain_result_by_default(self) -> None:
        async def dry_run_runner() -> str:
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

    def test_supervised_session_keeps_latency_profile_opt_in(self) -> None:
        async def dry_run_runner() -> str:
            return "ok"

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

        self.assertEqual(result, "ok")
        self.assertGreaterEqual(len(profile.stages), 1)
```

- [ ] **Step 2: Run the contract tests to verify they pass or expose drift**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12SharedPathContractTests" -q`
Expected: PASS if the current shared-path contract remains intact; FAIL only if prior latency work drifted from the intended contract

- [ ] **Step 3: Adjust only if the tests expose contract drift**

```python
# src/synthetic_trader/live/supervised_live.py
# Preserve the contract:
# - return result when capture_latency=False
# - return (result, profile) when capture_latency=True
# No new behavior should be introduced in this step.
```

- [ ] **Step 4: Run the contract tests again**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12SharedPathContractTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase12_shared_path_optimization.py src/synthetic_trader/live/supervised_live.py
git commit -m "test: lock shared path contract"
```

## Task 2: Reduce Redundant Shared Routing Overhead

**Files:**
- Modify: `tests/test_phase12_shared_path_optimization.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`

- [ ] **Step 1: Write the failing routing-overhead test**

```python
class Phase12RoutingOptimizationTests(unittest.TestCase):
    def test_latency_profile_stage_names_remain_stable_after_shared_path_tightening(self) -> None:
        async def dry_run_runner() -> str:
            return "ok"

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

        self.assertEqual(result, "ok")
        self.assertEqual(
            [stage.name for stage in profile.stages],
            ["readiness_gate", "supervised_route"],
        )
```

- [ ] **Step 2: Run the routing test to establish the red/green baseline**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12RoutingOptimizationTests" -q`
Expected: PASS if current stage names already match; FAIL if stage naming or ordering is unstable

- [ ] **Step 3: Apply the minimal shared routing cleanup**

```python
# src/synthetic_trader/live/supervised_live.py
async def run_supervised_live_session(
    *,
    venue: Venue = Venue.DERIV,
    mode: LiveMode,
    readiness_ok: bool,
    dry_run_runner: Callable[[], Awaitable[Any]],
    armed_runner: Callable[[], Awaitable[Any]],
    capture_latency: bool = False,
) -> Any:
    recorder = LatencyRecorder() if capture_latency else None

    readiness_start = time.perf_counter()
    if not readiness_ok:
        raise RuntimeError(f"{venue.value} readiness failed")
    if recorder is not None:
        recorder.record_stage(
            "readiness_gate",
            duration_ms=(time.perf_counter() - readiness_start) * 1000.0,
            category="critical",
        )

    runner: Callable[[], Awaitable[Any]]
    if mode is LiveMode.DRY_RUN_LIVE:
        runner = dry_run_runner
    elif mode is LiveMode.ARMED_LIVE:
        runner = armed_runner
    else:
        raise RuntimeError("supervised live session is not used in paper mode")

    route_start = time.perf_counter()
    result = await runner()
    if recorder is not None:
        recorder.record_stage(
            "supervised_route",
            duration_ms=(time.perf_counter() - route_start) * 1000.0,
            category="critical",
        )
        return result, recorder.build_profile()
    return result
```

- [ ] **Step 4: Run the routing test to verify it passes**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12RoutingOptimizationTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase12_shared_path_optimization.py
git commit -m "refactor: tighten shared supervised routing"
```

## Task 3: Defer Non-Critical Shared Side Effects Where Safe

**Files:**
- Modify: `tests/test_phase12_shared_path_optimization.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`

- [ ] **Step 1: Write the failing side-effect classification test**

```python
class Phase12SharedSideEffectTests(unittest.TestCase):
    def test_shared_side_effect_stage_names_stay_classified_as_side_effects(self) -> None:
        from synthetic_trader.live.paper_runner import classify_latency_stage

        self.assertEqual(classify_latency_stage("journal_append"), "side_effect")
        self.assertEqual(classify_latency_stage("summary_print"), "side_effect")
        self.assertEqual(classify_latency_stage("readiness_gate"), "critical")
```

- [ ] **Step 2: Run the side-effect classification test**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12SharedSideEffectTests" -q`
Expected: PASS if the current classifier still reflects the intended separation; FAIL only if classification drift exists

- [ ] **Step 3: Apply the minimal shared side-effect cleanup only if justified**

```python
# src/synthetic_trader/live/paper_runner.py
# Keep classify_latency_stage() as the single source of truth for deciding
# which shared-path work is side-effect-oriented versus execution-critical.
# If this step needs code changes, keep them limited to classifier clarity
# or tiny reductions in pre-broker synchronous side-effect work.
```

- [ ] **Step 4: Run the side-effect classification test again**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12SharedSideEffectTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/paper_runner.py tests/test_phase12_shared_path_optimization.py
git commit -m "refactor: preserve shared side-effect separation"
```

## Task 4: Keep Latency Surfacing Opt-In And Stable

**Files:**
- Modify: `tests/test_phase12_shared_path_optimization.py`
- Modify: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Write the failing opt-in CLI stability test**

```python
class Phase12LatencyCliStabilityTests(unittest.TestCase):
    def test_paper_live_does_not_emit_latency_lines_without_opt_in(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.live.paper_runner import LivePaperSummary

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=1,
            warmup_ticks=1,
            signals=0,
            approved_signals=0,
            rejected_signals=0,
            closed_trades=0,
            shutdown_closed_trades=0,
            open_positions_before_shutdown=0,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1000.0,
            model_version="unit-test",
        )

        output = io.StringIO()
        with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
            with contextlib.redirect_stdout(output):
                exit_code = main(["paper-live", "--symbol", "R_75"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("latency_total_ms=", output.getvalue())
```

- [ ] **Step 2: Run the CLI stability test**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12LatencyCliStabilityTests" -q`
Expected: PASS if opt-in latency output remains isolated; FAIL only if latency output has leaked into the default path

- [ ] **Step 3: Adjust CLI surfacing only if the test exposes drift**

```python
# src/synthetic_trader/cli.py
# Preserve latency output as opt-in only:
# - do not print latency lines unless --latency-profile is explicitly supplied
# - keep paper mode behavior unchanged
```

- [ ] **Step 4: Run the CLI stability test again**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -k "Phase12LatencyCliStabilityTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase12_shared_path_optimization.py
git commit -m "test: preserve opt-in latency output"
```

## Task 5: Run Phase 12 Regression

**Files:**
- Modify: `tests/test_phase12_shared_path_optimization.py`

- [ ] **Step 1: Run the focused Phase 12 suite**

Run: `python -m pytest tests/test_phase12_shared_path_optimization.py -q`
Expected:

```text
.....                                                                    [100%]
```

- [ ] **Step 2: Run the shared live regression suites**

Run: `python -m pytest tests/test_phase11_latency_hardening.py tests/test_phase4_supervised_live.py tests/test_live_paper_runner.py -q`
Expected:

```text
.......................                                                  [100%]
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
git add tests/test_phase12_shared_path_optimization.py src/synthetic_trader/live/supervised_live.py src/synthetic_trader/live/paper_runner.py src/synthetic_trader/cli.py
git commit -m "test: validate shared path optimization phase"
```

## Spec Coverage Check

- shared pre-broker optimization: covered by Tasks 2 and 3
- critical versus side-effect separation: covered by Task 3
- minimal runtime refactoring: covered by Task 2
- latency summary preservation: covered by Tasks 2 and 4
- clean sequencing into later phases: supported by keeping the optimized shared path measurable and stable through Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, commands, and explicit code blocks
- Each verification step states the expected pass/fail behavior directly

## Type Consistency Check

- `run_supervised_live_session()` remains the shared-path seam for opt-in latency capture
- `classify_latency_stage()` remains the single source of truth for side-effect versus critical stage classification
- `--latency-profile` remains the only CLI opt-in for latency output
- Phase 11 latency summary types remain unchanged and reusable through this plan
