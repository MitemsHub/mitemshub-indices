# Phase 13 MT5 Latency Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce MT5-specific venue overhead while preserving MT5 readiness, lifecycle correctness, supervised safety, and timing visibility.

**Architecture:** Keep the shared-path baseline unchanged and tune only MT5-specific seams where repeated terminal, symbol, or adapter work is likely to remain. Constrain the work to `execution/mt5.py` and any narrow supervised/CLI edges so Phase 14 can move straight into Deriv-specific tuning afterward.

**Tech Stack:** Python 3.11+, `dataclasses`, existing MT5 execution/lifecycle layer, supervised live control flow, `unittest`/`pytest`

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase13_mt5_latency_tuning.py`
  - Focused tests for reduced repeated MT5 venue work, preserved MT5 contracts, and safety regression coverage.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\mt5.py`
  - Tighten repeated MT5 runtime-boundary work while preserving typed result contracts.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Adjust only if supervised MT5 routing still introduces avoidable venue-specific overhead.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Keep MT5-specific latency surfacing opt-in and stable if this phase needs to expose venue timing more clearly.

## Task 1: Lock In MT5 Venue Contracts Before Tuning

**Files:**
- Create: `tests/test_phase13_mt5_latency_tuning.py`
- Modify: `src/synthetic_trader/execution/mt5.py`

- [ ] **Step 1: Write the failing MT5 contract tests**

```python
from __future__ import annotations

import unittest

from synthetic_trader.config import Mt5Config
from synthetic_trader.execution.mt5 import (
    Mt5Credentials,
    build_mt5_credentials,
    evaluate_mt5_runtime,
)


class Phase13Mt5ContractTests(unittest.TestCase):
    def test_build_mt5_credentials_preserves_symbol_map(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        credentials = build_mt5_credentials(config)

        self.assertEqual(credentials.server, "Broker-Demo")
        self.assertEqual(credentials.symbol_map["R_75"], "Volatility 75 Index")

    def test_evaluate_mt5_runtime_keeps_venue_symbol_resolution(self) -> None:
        class FakeMt5:
            def initialize(self, path=None, login=None, password=None, server=None):
                return True

            def last_error(self):
                return (0, "ok")

            def symbol_select(self, symbol, enable):
                return True

            def shutdown(self):
                return None

        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        status = evaluate_mt5_runtime(
            config=config,
            symbol="R_75",
            mt5_module=FakeMt5(),
        )

        self.assertTrue(status.ready)
        self.assertEqual(status.venue_symbol, "Volatility 75 Index")
```

- [ ] **Step 2: Run the MT5 contract tests to establish the baseline**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5ContractTests" -q`
Expected: FAIL first because the new test file does not exist yet, then PASS once the test file is added if the current MT5 contract already holds

- [ ] **Step 3: Adjust only if the tests expose drift**

```python
# src/synthetic_trader/execution/mt5.py
# Preserve existing MT5 contracts:
# - build_mt5_credentials() must preserve symbol_map
# - evaluate_mt5_runtime() must preserve venue_symbol resolution
# No new optimization should be introduced in this step.
```

- [ ] **Step 4: Run the MT5 contract tests again**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5ContractTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase13_mt5_latency_tuning.py src/synthetic_trader/execution/mt5.py
git commit -m "test: lock mt5 latency tuning contracts"
```

## Task 2: Reduce Repeated MT5 Runtime Preparation Work

**Files:**
- Modify: `tests/test_phase13_mt5_latency_tuning.py`
- Modify: `src/synthetic_trader/execution/mt5.py`

- [ ] **Step 1: Write the failing repeated-runtime-work test**

```python
class Phase13Mt5RuntimePreparationTests(unittest.TestCase):
    def test_build_mt5_credentials_returns_reusable_frozen_credentials(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        first = build_mt5_credentials(config)
        second = build_mt5_credentials(config)

        self.assertEqual(first, second)
        self.assertIsInstance(first, Mt5Credentials)
```

- [ ] **Step 2: Run the repeated-runtime-work test**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5RuntimePreparationTests" -q`
Expected: PASS if current behavior is already reusable and stable; FAIL only if MT5 preparation still drifts from the intended reusable contract

- [ ] **Step 3: Apply the minimal MT5 preparation cleanup only if justified**

```python
# src/synthetic_trader/execution/mt5.py
def build_mt5_credentials(config: Mt5Config) -> Mt5Credentials:
    return Mt5Credentials(
        server=config.server,
        login=config.login,
        password=config.password,
        terminal_path=config.terminal_path,
        symbol_map=dict(config.symbol_map),
    )
```

- [ ] **Step 4: Run the repeated-runtime-work test again**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5RuntimePreparationTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py tests/test_phase13_mt5_latency_tuning.py
git commit -m "refactor: stabilize mt5 runtime preparation"
```

## Task 3: Preserve MT5 Lifecycle Safety While Tightening Venue Work

**Files:**
- Modify: `tests/test_phase13_mt5_latency_tuning.py`
- Modify: `src/synthetic_trader/execution/mt5.py`

- [ ] **Step 1: Write the failing MT5 lifecycle regression tests**

```python
from synthetic_trader.domain import Direction
from synthetic_trader.execution.mt5 import (
    Mt5CloseRequest,
    Mt5ModifyRequest,
    Mt5OrderResult,
    close_mt5_position,
    modify_mt5_position,
)


class Phase13Mt5LifecycleSafetyTests(unittest.TestCase):
    def test_close_mt5_position_keeps_ticket_and_symbol_fields(self) -> None:
        class FakeMt5:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_SELL = 2
            ORDER_TIME_GTC = 3
            ORDER_FILLING_IOC = 4
            TRADE_RETCODE_DONE = 10009

            def order_send(self, request):
                class Result:
                    retcode = 10009
                    order = 500
                    deal = 600
                    comment = "ok"
                self.request = request
                return Result()

        result = close_mt5_position(
            request=Mt5CloseRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                volume=0.2,
                direction=Direction.LONG,
            ),
            mt5_module=FakeMt5(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.venue_symbol, "Volatility 75 Index")

    def test_modify_mt5_position_keeps_ticket_and_symbol_fields(self) -> None:
        class FakeMt5:
            TRADE_ACTION_SLTP = 1
            TRADE_RETCODE_DONE = 10009

            def order_send(self, request):
                class Result:
                    retcode = 10009
                    order = 700
                    deal = 800
                    comment = "ok"
                self.request = request
                return Result()

        result = modify_mt5_position(
            request=Mt5ModifyRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                stop_loss=99.5,
                take_profit=101.5,
            ),
            mt5_module=FakeMt5(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.venue_symbol, "Volatility 75 Index")
```

- [ ] **Step 2: Run the lifecycle regression tests**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5LifecycleSafetyTests" -q`
Expected: PASS if current MT5 lifecycle behavior already preserves the intended contract; FAIL only if venue-specific tightening caused drift

- [ ] **Step 3: Adjust MT5 lifecycle handling only if justified**

```python
# src/synthetic_trader/execution/mt5.py
# Keep close_mt5_position() and modify_mt5_position() contract-stable:
# - preserve venue_symbol
# - preserve ticket-directed behavior
# - do not weaken MT5 broker action semantics
```

- [ ] **Step 4: Run the lifecycle regression tests again**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5LifecycleSafetyTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py tests/test_phase13_mt5_latency_tuning.py
git commit -m "test: preserve mt5 lifecycle safety"
```

## Task 4: Keep MT5 Latency Surfacing Optional And Narrow

**Files:**
- Modify: `tests/test_phase13_mt5_latency_tuning.py`
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`

- [ ] **Step 1: Write the failing MT5 latency opt-in test**

```python
class Phase13Mt5LatencyCliTests(unittest.TestCase):
    def test_mt5_commands_do_not_emit_latency_output_without_opt_in(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        output = io.StringIO()
        with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
            with patch(
                "synthetic_trader.cli.evaluate_mt5_runtime",
                return_value=Mt5RuntimeStatus(
                    ready=True,
                    failures=(),
                    venue_symbol="Volatility 75 Index",
                ),
            ):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "mt5-live-order",
                            "--symbol",
                            "R_75",
                            "--live-mode",
                            "dry-run-live",
                            "--mt5-server",
                            "Broker-Demo",
                            "--mt5-login",
                            "123456",
                            "--mt5-password",
                            "secret",
                            "--mt5-symbol",
                            "Volatility 75 Index",
                            "--volume",
                            "0.2",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertNotIn("latency_total_ms=", output.getvalue())
```

- [ ] **Step 2: Run the MT5 latency opt-in test**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5LatencyCliTests" -q`
Expected: PASS if MT5 latency output remains opt-in; FAIL only if venue-specific timing output has leaked into the default MT5 operator path

- [ ] **Step 3: Adjust CLI or supervised MT5 surfacing only if justified**

```python
# src/synthetic_trader/cli.py
# src/synthetic_trader/live/supervised_live.py
# Preserve the rule:
# - MT5 latency output must remain opt-in
# - default MT5 command output must not gain timing noise
```

- [ ] **Step 4: Run the MT5 latency opt-in test again**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -k "Phase13Mt5LatencyCliTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/live/supervised_live.py tests/test_phase13_mt5_latency_tuning.py
git commit -m "test: preserve mt5 latency opt-in behavior"
```

## Task 5: Run Phase 13 Regression

**Files:**
- Modify: `tests/test_phase13_mt5_latency_tuning.py`

- [ ] **Step 1: Run the focused Phase 13 suite**

Run: `python -m pytest tests/test_phase13_mt5_latency_tuning.py -q`
Expected:

```text
......                                                                   [100%]
```

- [ ] **Step 2: Run the MT5 regression suites**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py tests/test_phase7_mt5_lifecycle.py tests/test_phase8_mt5_refinement.py tests/test_phase11_latency_hardening.py -q`
Expected:

```text
........................                                                 [100%]
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
git add tests/test_phase13_mt5_latency_tuning.py src/synthetic_trader/execution/mt5.py src/synthetic_trader/cli.py src/synthetic_trader/live/supervised_live.py
git commit -m "test: validate mt5 latency tuning phase"
```

## Spec Coverage Check

- MT5 runtime boundary tuning: covered by Tasks 1 and 2
- MT5 lifecycle path review: covered by Task 3
- MT5 timing preservation: covered by Task 4
- minimal venue refactoring: covered by Task 2
- immediate sequencing into Deriv: supported by keeping the phase local to MT5 seams and fully regression-safe through Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, commands, and explicit code blocks
- Each verification step states the expected pass/fail behavior directly

## Type Consistency Check

- `build_mt5_credentials()` remains the primary MT5 preparation seam
- `evaluate_mt5_runtime()` remains the readiness-focused MT5 runtime seam
- MT5 lifecycle stability is enforced through `close_mt5_position()` and `modify_mt5_position()`
- latency output remains opt-in and does not become part of the default MT5 contract
