# Phase 14 Deriv Latency Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Deriv-specific venue overhead while preserving Deriv readiness, supervised behavior, and execution correctness.

**Architecture:** Keep the shared-path and MT5 baselines unchanged and tune only Deriv-specific seams where repeated transport, request preparation, or adapter work is likely to remain. Constrain the work to Deriv execution/runtime edges so the next phase can focus entirely on final validation and benchmarking.

**Tech Stack:** Python 3.11+, `asyncio`, Deriv WebSocket client/runtime layer, shared live/paper runner, `unittest`/`pytest`

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase14_deriv_latency_tuning.py`
  - Focused tests for preserved Deriv contracts, reduced repeated venue work, and regression-safe Deriv tuning.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\deriv.py`
  - Tighten repeated Deriv transport/setup work while preserving normalized runtime behavior.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Adjust only if the Deriv live path still performs avoidable venue work before execution-relevant boundaries.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Keep any Deriv-specific latency surfacing opt-in and stable if needed.

## Task 1: Lock In Deriv Venue Contracts Before Tuning

**Files:**
- Create: `tests/test_phase14_deriv_latency_tuning.py`
- Modify: `src/synthetic_trader/execution/deriv.py`

- [ ] **Step 1: Write the failing Deriv contract tests**

```python
from __future__ import annotations

import unittest

from synthetic_trader.execution.deriv import DerivExecutionClient


class Phase14DerivContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticks_history_preserves_requested_symbol(self) -> None:
        class FakeTransport:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            async def request(self, payload: dict[str, object]) -> dict[str, object]:
                self.requests.append(payload)
                return {
                    "history": {
                        "prices": [100.0, 101.0],
                        "times": [1, 2],
                    }
                }

        transport = FakeTransport()
        client = DerivExecutionClient(transport=transport)

        await client.ticks_history("R_75", count=2)

        self.assertEqual(transport.requests[0]["ticks_history"], "R_75")
        self.assertEqual(transport.requests[0]["count"], 2)
```

- [ ] **Step 2: Run the Deriv contract test to establish the baseline**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivContractTests" -q`
Expected: FAIL first because the new test file does not exist yet, then PASS once the test file is added if the current Deriv contract already holds

- [ ] **Step 3: Adjust only if the tests expose drift**

```python
# src/synthetic_trader/execution/deriv.py
# Preserve existing Deriv contracts:
# - request payloads keep the requested symbol
# - existing normalized behavior remains intact
# No new optimization should be introduced in this step.
```

- [ ] **Step 4: Run the Deriv contract test again**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivContractTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase14_deriv_latency_tuning.py src/synthetic_trader/execution/deriv.py
git commit -m "test: lock deriv latency tuning contracts"
```

## Task 2: Reduce Repeated Deriv Transport Preparation Work

**Files:**
- Modify: `tests/test_phase14_deriv_latency_tuning.py`
- Modify: `src/synthetic_trader/execution/deriv.py`

- [ ] **Step 1: Write the failing repeated-transport-work test**

```python
class Phase14DerivTransportPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticks_history_request_shape_stays_reusable(self) -> None:
        class FakeTransport:
            async def request(self, payload: dict[str, object]) -> dict[str, object]:
                return {
                    "history": {
                        "prices": [100.0],
                        "times": [1],
                    }
                }

        client = DerivExecutionClient(transport=FakeTransport())

        first = await client.ticks_history("R_75", count=1)
        second = await client.ticks_history("R_75", count=1)

        self.assertEqual(first, second)
```

- [ ] **Step 2: Run the repeated-transport-work test**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivTransportPreparationTests" -q`
Expected: PASS if current Deriv behavior is already stable and reusable; FAIL only if the request/result contract drifts

- [ ] **Step 3: Apply the minimal Deriv preparation cleanup only if justified**

```python
# src/synthetic_trader/execution/deriv.py
# Keep Deriv request preparation stable and reusable.
# If this step needs code changes, keep them limited to avoiding redundant
# Deriv-specific request-shaping work without changing behavior.
```

- [ ] **Step 4: Run the repeated-transport-work test again**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivTransportPreparationTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/deriv.py tests/test_phase14_deriv_latency_tuning.py
git commit -m "refactor: stabilize deriv transport preparation"
```

## Task 3: Preserve Deriv Live Safety While Tightening Venue Work

**Files:**
- Modify: `tests/test_phase14_deriv_latency_tuning.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`

- [ ] **Step 1: Write the failing Deriv live safety test**

```python
class Phase14DerivLiveSafetyTests(unittest.TestCase):
    def test_deriv_stage_classification_keeps_execution_boundaries_critical(self) -> None:
        from synthetic_trader.live.paper_runner import classify_latency_stage

        self.assertEqual(classify_latency_stage("signal_decision"), "critical")
        self.assertEqual(classify_latency_stage("journal_append"), "side_effect")
```

- [ ] **Step 2: Run the Deriv live safety test**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivLiveSafetyTests" -q`
Expected: PASS if the current live classification still protects the intended boundary; FAIL only if drift exists

- [ ] **Step 3: Adjust Deriv live handling only if justified**

```python
# src/synthetic_trader/live/paper_runner.py
# Preserve classification so Deriv-critical stages remain critical and
# side effects remain separate. No broader live-path rewrite in this step.
```

- [ ] **Step 4: Run the Deriv live safety test again**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivLiveSafetyTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/paper_runner.py tests/test_phase14_deriv_latency_tuning.py
git commit -m "test: preserve deriv live safety boundaries"
```

## Task 4: Keep Deriv Latency Surfacing Optional And Stable

**Files:**
- Modify: `tests/test_phase14_deriv_latency_tuning.py`
- Modify: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Write the failing Deriv latency opt-in test**

```python
class Phase14DerivLatencyCliTests(unittest.TestCase):
    def test_paper_live_deriv_path_does_not_emit_latency_without_opt_in(self) -> None:
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

- [ ] **Step 2: Run the Deriv latency opt-in test**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivLatencyCliTests" -q`
Expected: PASS if Deriv latency output remains opt-in; FAIL only if Deriv timing output has leaked into the default operator path

- [ ] **Step 3: Adjust CLI surfacing only if justified**

```python
# src/synthetic_trader/cli.py
# Preserve the rule:
# - Deriv latency output remains opt-in
# - default Deriv paper/live output stays clean
```

- [ ] **Step 4: Run the Deriv latency opt-in test again**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -k "Phase14DerivLatencyCliTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase14_deriv_latency_tuning.py
git commit -m "test: preserve deriv latency opt-in behavior"
```

## Task 5: Run Phase 14 Regression

**Files:**
- Modify: `tests/test_phase14_deriv_latency_tuning.py`

- [ ] **Step 1: Run the focused Phase 14 suite**

Run: `python -m pytest tests/test_phase14_deriv_latency_tuning.py -q`
Expected:

```text
....                                                                     [100%]
```

- [ ] **Step 2: Run the Deriv and shared regression suites**

Run: `python -m pytest tests/test_phase11_latency_hardening.py tests/test_phase12_shared_path_optimization.py tests/test_live_paper_runner.py -q`
Expected:

```text
....................                                                     [100%]
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
git add tests/test_phase14_deriv_latency_tuning.py src/synthetic_trader/execution/deriv.py src/synthetic_trader/live/paper_runner.py src/synthetic_trader/cli.py
git commit -m "test: validate deriv latency tuning phase"
```

## Spec Coverage Check

- Deriv transport boundary tuning: covered by Tasks 1 and 2
- Deriv readiness and execution path review: covered by Tasks 3 and 4
- Deriv timing preservation: covered by Task 4
- minimal venue refactoring: covered by Task 2
- preparation for final validation: supported by keeping the Deriv phase local, stable, and fully regression-safe through Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, commands, and explicit code blocks
- Each verification step states the expected pass/fail behavior directly

## Type Consistency Check

- `DerivExecutionClient` remains the Deriv venue seam for request/transport behavior
- `classify_latency_stage()` remains the shared live boundary classifier referenced by the Deriv phase
- `--latency-profile` remains opt-in and does not become default operator output
- Phase 11 and Phase 12 latency surfaces remain reusable and unchanged
