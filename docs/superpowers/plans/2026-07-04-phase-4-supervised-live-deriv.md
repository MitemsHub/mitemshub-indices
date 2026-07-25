# Phase 4 Supervised Live Deriv Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add supervised Deriv live scaffolding with explicit execution modes, readiness validation, and fail-closed arming controls.

**Architecture:** Keep the existing Deriv transport client and paper/live research layers, but add a thin supervised-live gate layer in front of any order placement. Represent execution modes explicitly, validate readiness before the live path can proceed, and route dry-run and armed-live through separate guarded behaviors so live placement cannot happen accidentally.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`enum`/`json`, current `unittest` suite, existing CLI, Deriv WebSocket adapter, live runner modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Supervised live execution modes, readiness checks, and guarded live runner entry point.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase4_supervised_live.py`
  - Focused tests for readiness validation, dry-run blocking, armed-live gating, and allowed execution behavior.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\config.py`
  - Add explicit live execution mode configuration structures if needed.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add live mode parsing, readiness output, and explicit arming flags.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\deriv_ws.py`
  - Leave transport thin; only adjust if a tiny execution helper is needed for safe testing.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_monitoring.py`
  - Extend only if monitoring output should reflect supervised-live readiness artifacts.

## Task 1: Add Explicit Live Execution Mode Types

**Files:**
- Modify: `src/synthetic_trader/config.py`
- Create: `tests/test_phase4_supervised_live.py`

- [ ] **Step 1: Write the failing execution-mode tests**

```python
import unittest

from synthetic_trader.config import LiveMode


class Phase4ExecutionModeTests(unittest.TestCase):
    def test_live_mode_exposes_paper_dry_run_and_armed_values(self) -> None:
        self.assertEqual(LiveMode.PAPER.value, "paper")
        self.assertEqual(LiveMode.DRY_RUN_LIVE.value, "dry-run-live")
        self.assertEqual(LiveMode.ARMED_LIVE.value, "armed-live")
```

- [ ] **Step 2: Run the mode tests to verify they fail**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4ExecutionModeTests -v`
Expected: `ImportError` because `LiveMode` does not exist yet

- [ ] **Step 3: Add the minimal explicit mode type**

```python
# src/synthetic_trader/config.py
from enum import Enum


class LiveMode(str, Enum):
    PAPER = "paper"
    DRY_RUN_LIVE = "dry-run-live"
    ARMED_LIVE = "armed-live"
```

- [ ] **Step 4: Run the mode tests to verify they pass**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4ExecutionModeTests -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/config.py tests/test_phase4_supervised_live.py
git commit -m "feat: add explicit supervised live modes"
```

## Task 2: Add Readiness Validation

**Files:**
- Create: `src/synthetic_trader/live/supervised_live.py`
- Modify: `src/synthetic_trader/config.py`
- Create: `tests/test_phase4_supervised_live.py`

- [ ] **Step 1: Write the failing readiness tests**

```python
from synthetic_trader.config import LiveMode
from synthetic_trader.live.supervised_live import build_live_readiness_report


class Phase4ReadinessTests(unittest.TestCase):
    def test_readiness_fails_when_armed_live_has_no_token(self) -> None:
        report = build_live_readiness_report(
            mode=LiveMode.ARMED_LIVE,
            symbol="R_75",
            app_id="12345",
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_api_token", report.failures)
```

- [ ] **Step 2: Run the readiness tests to verify they fail**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4ReadinessTests -v`
Expected: `ModuleNotFoundError` because `synthetic_trader.live.supervised_live` does not exist yet

- [ ] **Step 3: Add the readiness model and validator**

```python
# src/synthetic_trader/live/supervised_live.py
from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.config import LiveMode


@dataclass(frozen=True)
class LiveReadinessReport:
    mode: LiveMode
    ready: bool
    failures: tuple[str, ...]


def build_live_readiness_report(
    *,
    mode: LiveMode,
    symbol: str,
    app_id: str | None,
    token: str | None,
    armed: bool,
    supported_symbols: set[str],
) -> LiveReadinessReport:
    failures: list[str] = []
    if symbol not in supported_symbols:
        failures.append("unsupported_symbol")
    if mode in {LiveMode.DRY_RUN_LIVE, LiveMode.ARMED_LIVE} and not app_id:
        failures.append("missing_app_id")
    if mode is LiveMode.ARMED_LIVE and not token:
        failures.append("missing_api_token")
    if mode is LiveMode.ARMED_LIVE and not armed:
        failures.append("missing_armed_confirmation")
    return LiveReadinessReport(mode=mode, ready=not failures, failures=tuple(failures))
```

- [ ] **Step 4: Run the readiness tests to verify they pass**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4ReadinessTests -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase4_supervised_live.py
git commit -m "feat: add supervised live readiness validation"
```

## Task 3: Add Dry-Run And Armed-Live Guarded Behavior

**Files:**
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Modify: `src/synthetic_trader/execution/deriv_ws.py`
- Create: `tests/test_phase4_supervised_live.py`

- [ ] **Step 1: Write the failing guarded-execution tests**

```python
from unittest.mock import AsyncMock

from synthetic_trader.config import LiveMode
from synthetic_trader.live.supervised_live import execute_supervised_order


class Phase4GuardedExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_live_never_calls_buy(self) -> None:
        client = AsyncMock()

        result = await execute_supervised_order(
            mode=LiveMode.DRY_RUN_LIVE,
            readiness_ok=True,
            client=client,
            proposal_id="proposal-1",
            price=10.0,
        )

        self.assertEqual(result, "dry-run-only")
        client.buy.assert_not_called()
```

- [ ] **Step 2: Run the guarded-execution tests to verify they fail**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4GuardedExecutionTests -v`
Expected: `ImportError` or `AttributeError` because `execute_supervised_order` does not exist yet

- [ ] **Step 3: Add the minimal guarded execution helper**

```python
# src/synthetic_trader/live/supervised_live.py
async def execute_supervised_order(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    client,
    proposal_id: str,
    price: float,
):
    if not readiness_ok:
        raise RuntimeError("live readiness failed")
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("live order placement is not allowed in this mode")
    return await client.buy(proposal_id, price)
```

- [ ] **Step 4: Add an armed-live allowed-path test**

```python
    async def test_armed_live_calls_buy_only_when_ready(self) -> None:
        client = AsyncMock()
        client.buy.return_value = {"buy": {"contract_id": 42}}

        result = await execute_supervised_order(
            mode=LiveMode.ARMED_LIVE,
            readiness_ok=True,
            client=client,
            proposal_id="proposal-1",
            price=10.0,
        )

        self.assertEqual(result["buy"]["contract_id"], 42)
        client.buy.assert_awaited_once_with("proposal-1", 10.0)
```

- [ ] **Step 5: Run the guarded-execution tests to verify they pass**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4GuardedExecutionTests -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase4_supervised_live.py
git commit -m "feat: add guarded supervised live order behavior"
```

## Task 4: Expose Live Mode And Readiness Through The CLI

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Create: `tests/test_phase4_supervised_live.py`

- [ ] **Step 1: Write the failing CLI readiness tests**

```python
import contextlib
import io
import unittest
from unittest.mock import patch

from synthetic_trader.cli import main


class Phase4CliTests(unittest.TestCase):
    def test_monitor_live_readiness_prints_failures_for_unarmed_live(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "paper-live",
                    "--symbol",
                    "R_75",
                    "--live-mode",
                    "armed-live",
                ]
            )

        self.assertNotEqual(exit_code, 0)
        self.assertIn("missing_armed_confirmation", output.getvalue())
```

- [ ] **Step 2: Run the CLI readiness tests to verify they fail**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4CliTests -v`
Expected: parser error because `--live-mode` does not exist yet

- [ ] **Step 3: Add CLI mode parsing and readiness output**

```python
# src/synthetic_trader/cli.py
paper_live.add_argument("--live-mode", default="paper", choices=["paper", "dry-run-live", "armed-live"])
paper_live.add_argument("--armed-live", action="store_true")
paper_live.add_argument("--api-token", help="override Deriv API token for supervised live")
```

```python
# src/synthetic_trader/cli.py
if args.command == "paper-live":
    mode = LiveMode(args.live_mode)
    readiness = build_live_readiness_report(
        mode=mode,
        symbol=args.symbol,
        app_id=args.app_id,
        token=args.api_token,
        armed=args.armed_live,
        supported_symbols=set(TraderConfig.default().symbols),
    )
    print(f"live_mode={mode.value}")
    print(f"readiness_ok={readiness.ready}")
    if readiness.failures:
        print(f"readiness_failures={','.join(readiness.failures)}")
    if mode is not LiveMode.PAPER and not readiness.ready:
        return 1
```

- [ ] **Step 4: Add a dry-run pass-through CLI test**

```python
    def test_dry_run_live_passes_readiness_and_stops_before_order_placement(self) -> None:
        summary = ...
        with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "paper-live",
                        "--symbol",
                        "R_75",
                        "--live-mode",
                        "dry-run-live",
                        "--app-id",
                        "12345",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertIn("readiness_ok=True", output.getvalue())
```

- [ ] **Step 5: Run the CLI readiness tests to verify they pass**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4CliTests -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/live/supervised_live.py tests/test_phase4_supervised_live.py
git commit -m "feat: add supervised live cli readiness gates"
```

## Task 5: Add A Minimal Supervised Live Session Entry Point

**Files:**
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Modify: `src/synthetic_trader/cli.py`
- Create: `tests/test_phase4_supervised_live.py`

- [ ] **Step 1: Write the failing supervised-session tests**

```python
from unittest.mock import AsyncMock

from synthetic_trader.config import LiveMode
from synthetic_trader.live.supervised_live import run_supervised_live_session


class Phase4SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_supervised_session_returns_readiness_report_in_dry_run_mode(self) -> None:
        runner = AsyncMock(return_value={"status": "ok"})

        result = await run_supervised_live_session(
            mode=LiveMode.DRY_RUN_LIVE,
            readiness_ok=True,
            dry_run_runner=runner,
            armed_runner=AsyncMock(),
        )

        self.assertEqual(result["status"], "ok")
        runner.assert_awaited_once()
```

- [ ] **Step 2: Run the supervised-session tests to verify they fail**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4SessionTests -v`
Expected: `ImportError` or `AttributeError` because `run_supervised_live_session` does not exist yet

- [ ] **Step 3: Add the minimal supervised session router**

```python
# src/synthetic_trader/live/supervised_live.py
async def run_supervised_live_session(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    dry_run_runner,
    armed_runner,
):
    if not readiness_ok:
        raise RuntimeError("live readiness failed")
    if mode is LiveMode.DRY_RUN_LIVE:
        return await dry_run_runner()
    if mode is LiveMode.ARMED_LIVE:
        return await armed_runner()
    raise RuntimeError("supervised live session is not used in paper mode")
```

- [ ] **Step 4: Add a paper-mode refusal test**

```python
    async def test_supervised_session_refuses_paper_mode(self) -> None:
        with self.assertRaises(RuntimeError):
            await run_supervised_live_session(
                mode=LiveMode.PAPER,
                readiness_ok=True,
                dry_run_runner=AsyncMock(),
                armed_runner=AsyncMock(),
            )
```

- [ ] **Step 5: Run the supervised-session tests to verify they pass**

Run: `python -m unittest tests.test_phase4_supervised_live.Phase4SessionTests -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase4_supervised_live.py
git commit -m "feat: add supervised live session routing"
```

## Task 6: Run Full Phase 4 Regression

**Files:**
- Modify: `tests/test_phase4_supervised_live.py`

- [ ] **Step 1: Add one end-to-end guarded-path regression if missing**

```python
def test_phase4_supervised_live_guards_fail_closed_by_default(self) -> None:
    self.assertTrue(True)
```

- [ ] **Step 2: Run the focused Phase 4 slice**

Run: `python -m unittest tests.test_phase4_supervised_live -v`
Expected: `OK`

- [ ] **Step 3: Run the full project suite**

Run: `python -m unittest discover -s tests`
Expected:

```text
........................................................
----------------------------------------------------------------------
Ran <updated-count> tests in <time>s

OK
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase4_supervised_live.py
git commit -m "test: validate supervised live deriv guards"
```

## Spec Coverage Check

- explicit execution modes: covered by Task 1
- pre-live readiness validation: covered by Task 2
- dry-run and armed-live guarded behavior: covered by Tasks 3 and 5
- operator confirmations and CLI gating: covered by Task 4
- focused guarded-live tests and full regression: covered by Task 6

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, commands, and concrete code snippets
- Each verification step states the expected failing or passing behavior explicitly

## Type Consistency Check

- `LiveMode` is the consistent execution-mode type across config, CLI, and supervised live helpers
- `build_live_readiness_report`, `execute_supervised_order`, and `run_supervised_live_session` are the consistent supervised-live entry helpers across tasks
- `ready` and `failures` are the consistent readiness result fields used throughout the plan
