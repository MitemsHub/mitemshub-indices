# Phase 6 MT5 Live Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add terminal-backed MT5 connectivity, runtime readiness, and supervised tiny-stake MT5 order placement while preserving fail-closed safety and keeping autonomous trading out of scope.

**Architecture:** Extend the existing MT5 adapter from passive config storage into a thin runtime execution seam that can initialize the MT5 terminal, validate login and symbol readiness, and place a supervised order behind the current venue-aware live gates. Keep the trading core unchanged by concentrating MT5 runtime behavior inside the adapter, supervised-live helpers, and one explicit CLI entry path.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`typing`, existing `pytest`/`unittest` test suite, optional `MetaTrader5` package behind lazy import, current CLI and supervised-live modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase6_mt5_live_execution.py`
  - Focused Phase 6 coverage for MT5 runtime readiness, terminal-backed symbol checks, supervised order placement, and CLI reporting.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\mt5.py`
  - Add MT5 runtime client, terminal-backed readiness helpers, symbol selection, structured MT5 order request and result types, and supervised order placement logic.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Add MT5 runtime readiness evaluation and supervised MT5 order execution helpers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add an explicit MT5 supervised live command surface and runtime result reporting.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase5_mt5_scaffolding.py`
  - Keep one regression proving Phase 5 fail-closed behavior still works after runtime extensions.

## Task 1: Add Structured MT5 Request And Result Types

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Create: `tests/test_phase6_mt5_live_execution.py`

- [ ] **Step 1: Write the failing MT5 request/result tests**

```python
import unittest

from synthetic_trader.execution.mt5 import Mt5OrderRequest, Mt5OrderResult


class Phase6Mt5TypesTests(unittest.TestCase):
    def test_order_request_exposes_resolved_symbol_and_volume(self) -> None:
        request = Mt5OrderRequest(
            symbol="R_75",
            venue_symbol="Volatility 75 Index",
            volume=0.2,
            order_type="BUY",
            stop_loss=99.5,
            take_profit=101.0,
            comment="phase6-test",
        )

        self.assertEqual(request.venue_symbol, "Volatility 75 Index")
        self.assertEqual(request.volume, 0.2)

    def test_order_result_tracks_acceptance_and_ticket(self) -> None:
        result = Mt5OrderResult(
            accepted=True,
            order_ticket=123456,
            deal_ticket=654321,
            retcode=10009,
            message="placed",
            venue_symbol="Volatility 75 Index",
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 123456)
```

- [ ] **Step 2: Run the type tests to verify they fail**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6Mt5TypesTests" -q`
Expected: `ImportError` because `Mt5OrderRequest` and `Mt5OrderResult` do not exist yet

- [ ] **Step 3: Add the minimal MT5 request and result types**

```python
# src/synthetic_trader/execution/mt5.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Mt5OrderRequest:
    symbol: str
    venue_symbol: str
    volume: float
    order_type: str
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str | None = None


@dataclass(frozen=True)
class Mt5OrderResult:
    accepted: bool
    order_ticket: int | None
    deal_ticket: int | None
    retcode: int | None
    message: str
    venue_symbol: str
```

- [ ] **Step 4: Run the type tests to verify they pass**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6Mt5TypesTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py tests/test_phase6_mt5_live_execution.py
git commit -m "feat: add mt5 order request and result types"
```

## Task 2: Add MT5 Terminal Runtime And Readiness Helpers

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Create: `tests/test_phase6_mt5_live_execution.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`

- [ ] **Step 1: Write the failing MT5 runtime readiness tests**

```python
from synthetic_trader.config import Mt5Config
from synthetic_trader.execution.mt5 import Mt5RuntimeStatus, evaluate_mt5_runtime


class Phase6Mt5RuntimeTests(unittest.TestCase):
    def test_runtime_fails_when_symbol_is_not_selectable(self) -> None:
        class FakeModule:
            def initialize(self, path=None):
                return True

            def login(self, login, password=None, server=None):
                return True

            def symbol_info(self, symbol):
                return None

            def shutdown(self):
                return True

        status = evaluate_mt5_runtime(
            config=Mt5Config(
                server="Broker-Demo",
                login="123456",
                password="secret",
                symbol_map={"R_75": "Volatility 75 Index"},
            ),
            symbol="R_75",
            mt5_module=FakeModule(),
        )

        self.assertFalse(status.ready)
        self.assertIn("mt5_symbol_unavailable", status.failures)
```

- [ ] **Step 2: Run the MT5 runtime tests to verify they fail**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6Mt5RuntimeTests" -q`
Expected: `ImportError` because `Mt5RuntimeStatus` and `evaluate_mt5_runtime()` do not exist yet

- [ ] **Step 3: Add runtime status and MT5 runtime evaluation**

```python
# src/synthetic_trader/execution/mt5.py
@dataclass(frozen=True)
class Mt5RuntimeStatus:
    ready: bool
    failures: tuple[str, ...]
    venue_symbol: str | None = None


def evaluate_mt5_runtime(
    *,
    config: Mt5Config,
    symbol: str,
    mt5_module=None,
) -> Mt5RuntimeStatus:
    failures: list[str] = []
    module = mt5_module
    if module is None:
        try:
            import MetaTrader5 as module  # type: ignore
        except ImportError:
            return Mt5RuntimeStatus(ready=False, failures=("missing_mt5_runtime",), venue_symbol=None)

    venue_symbol = config.resolve_symbol(symbol)
    if not venue_symbol:
        failures.append("missing_mt5_symbol_mapping")
        return Mt5RuntimeStatus(ready=False, failures=tuple(failures), venue_symbol=None)

    if not module.initialize(path=config.terminal_path):
        failures.append("mt5_initialize_failed")
        return Mt5RuntimeStatus(ready=False, failures=tuple(failures), venue_symbol=venue_symbol)
    try:
        if not module.login(int(config.login), password=config.password, server=config.server):
            failures.append("mt5_login_failed")
        if module.symbol_info(venue_symbol) is None:
            failures.append("mt5_symbol_unavailable")
    finally:
        module.shutdown()

    return Mt5RuntimeStatus(ready=not failures, failures=tuple(failures), venue_symbol=venue_symbol)
```

- [ ] **Step 4: Thread runtime status into supervised MT5 readiness**

```python
# src/synthetic_trader/live/supervised_live.py
from synthetic_trader.execution.mt5 import Mt5RuntimeStatus
```

```python
# src/synthetic_trader/live/supervised_live.py
def build_live_readiness_report(
    *,
    venue: Venue = Venue.DERIV,
    mode: LiveMode,
    symbol: str,
    app_id: str | None,
    token: str | None,
    armed: bool,
    supported_symbols: set[str],
    mt5_config: Mt5Config | None = None,
    mt5_dependency_ready: bool = False,
    mt5_runtime_status: Mt5RuntimeStatus | None = None,
) -> LiveReadinessReport:
    failures: list[str] = []
    if symbol not in supported_symbols:
        failures.append("unsupported_symbol")
    if venue is Venue.DERIV and mode in {LiveMode.DRY_RUN_LIVE, LiveMode.ARMED_LIVE} and not app_id:
        failures.append("missing_app_id")
    if venue is Venue.DERIV and mode is LiveMode.ARMED_LIVE and not token:
        failures.append("missing_api_token")
    if venue is Venue.MT5:
        cfg = mt5_config or Mt5Config()
        if not cfg.server:
            failures.append("missing_mt5_server")
        if not cfg.login:
            failures.append("missing_mt5_login")
        if not cfg.password:
            failures.append("missing_mt5_password")
        if not cfg.resolve_symbol(symbol):
            failures.append("missing_mt5_symbol_mapping")
        if not mt5_dependency_ready:
            failures.append("missing_mt5_runtime")
        runtime_status = mt5_runtime_status
        if runtime_status is not None:
            failures.extend(runtime_status.failures)
    if mode is LiveMode.ARMED_LIVE and not armed:
        failures.append("missing_armed_confirmation")
    return LiveReadinessReport(mode=mode, ready=not failures, failures=tuple(failures))
```

- [ ] **Step 5: Run the MT5 runtime tests to verify they pass**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6Mt5RuntimeTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py src/synthetic_trader/live/supervised_live.py tests/test_phase6_mt5_live_execution.py
git commit -m "feat: add mt5 terminal runtime readiness"
```

## Task 3: Add Supervised MT5 Order Placement

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Create: `tests/test_phase6_mt5_live_execution.py`

- [ ] **Step 1: Write the failing supervised MT5 order tests**

```python
from synthetic_trader.execution.mt5 import Mt5OrderRequest, place_mt5_order


class Phase6Mt5OrderPlacementTests(unittest.TestCase):
    def test_place_mt5_order_returns_structured_acceptance(self) -> None:
        class FakeResult:
            retcode = 10009
            order = 111
            deal = 222
            comment = "Request executed"

        class FakeModule:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_BUY = 0
            ORDER_TIME_GTC = 0
            ORDER_FILLING_FOK = 0

            def order_send(self, payload):
                return FakeResult()

        result = place_mt5_order(
            request=Mt5OrderRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                volume=0.2,
                order_type="BUY",
            ),
            mt5_module=FakeModule(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 111)
```

- [ ] **Step 2: Run the supervised MT5 order tests to verify they fail**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6Mt5OrderPlacementTests" -q`
Expected: `ImportError` or `AttributeError` because `place_mt5_order()` does not exist yet

- [ ] **Step 3: Add MT5 order placement helper**

```python
# src/synthetic_trader/execution/mt5.py
def place_mt5_order(
    *,
    request: Mt5OrderRequest,
    mt5_module,
) -> Mt5OrderResult:
    payload = {
        "action": mt5_module.TRADE_ACTION_DEAL,
        "symbol": request.venue_symbol,
        "volume": request.volume,
        "type": mt5_module.ORDER_TYPE_BUY if request.order_type == "BUY" else mt5_module.ORDER_TYPE_SELL,
        "sl": request.stop_loss,
        "tp": request.take_profit,
        "comment": request.comment or "synthetic-trader",
        "type_time": mt5_module.ORDER_TIME_GTC,
        "type_filling": mt5_module.ORDER_FILLING_FOK,
    }
    result = mt5_module.order_send(payload)
    accepted = getattr(result, "retcode", None) == 10009
    return Mt5OrderResult(
        accepted=accepted,
        order_ticket=getattr(result, "order", None),
        deal_ticket=getattr(result, "deal", None),
        retcode=getattr(result, "retcode", None),
        message=str(getattr(result, "comment", "")),
        venue_symbol=request.venue_symbol,
    )
```

- [ ] **Step 4: Add supervised MT5 execution wrapper**

```python
# src/synthetic_trader/live/supervised_live.py
from synthetic_trader.execution.mt5 import Mt5OrderRequest, Mt5OrderResult, place_mt5_order
```

```python
# src/synthetic_trader/live/supervised_live.py
def execute_supervised_mt5_order(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    request: Mt5OrderRequest,
    mt5_module,
) -> Mt5OrderResult | str:
    if not readiness_ok:
        raise RuntimeError("mt5 readiness failed")
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("mt5 order placement is not allowed in this mode")
    return place_mt5_order(request=request, mt5_module=mt5_module)
```

- [ ] **Step 5: Run the supervised MT5 order tests to verify they pass**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6Mt5OrderPlacementTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py src/synthetic_trader/live/supervised_live.py tests/test_phase6_mt5_live_execution.py
git commit -m "feat: add supervised mt5 order placement"
```

## Task 4: Add Explicit CLI Entry For MT5 Supervised Execution

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Create: `tests/test_phase6_mt5_live_execution.py`

- [ ] **Step 1: Write the failing CLI MT5 live tests**

```python
import contextlib
import io
from unittest.mock import patch

from synthetic_trader.execution.mt5 import Mt5OrderResult, Mt5RuntimeStatus


class Phase6CliMt5LiveTests(unittest.TestCase):
    def test_mt5_live_order_reports_runtime_failures(self) -> None:
        from synthetic_trader.cli import main

        output = io.StringIO()
        with patch(
            "synthetic_trader.cli.evaluate_mt5_runtime",
            return_value=Mt5RuntimeStatus(
                ready=False,
                failures=("mt5_initialize_failed",),
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
                        "armed-live",
                        "--armed-live",
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

        self.assertEqual(exit_code, 1)
        self.assertIn("mt5_initialize_failed", output.getvalue())

    def test_mt5_live_order_prints_structured_success(self) -> None:
        from synthetic_trader.cli import main

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            failures=(),
            venue_symbol="Volatility 75 Index",
        )
        order_result = Mt5OrderResult(
            accepted=True,
            order_ticket=111,
            deal_ticket=222,
            retcode=10009,
            message="Request executed",
            venue_symbol="Volatility 75 Index",
        )

        output = io.StringIO()
        with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
            with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                with patch("synthetic_trader.cli.execute_supervised_mt5_order", return_value=order_result):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-live-order",
                                "--symbol",
                                "R_75",
                                "--live-mode",
                                "armed-live",
                                "--armed-live",
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
        self.assertIn("order_ticket=111", output.getvalue())
```

- [ ] **Step 2: Run the CLI MT5 live tests to verify they fail**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6CliMt5LiveTests" -q`
Expected: parser error because `mt5-live-order` does not exist yet

- [ ] **Step 3: Add the MT5 live order CLI command**

```python
# src/synthetic_trader/cli.py
from synthetic_trader.execution.mt5 import (
    Mt5OrderRequest,
    evaluate_mt5_runtime,
    mt5_dependency_available,
    _load_mt5_module,
)
from synthetic_trader.live.supervised_live import execute_supervised_mt5_order
```

```python
# src/synthetic_trader/cli.py
mt5_live_order = subparsers.add_parser(
    "mt5-live-order",
    help="run terminal-backed supervised MT5 order placement",
)
mt5_live_order.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
mt5_live_order.add_argument("--live-mode", default=LiveMode.DRY_RUN_LIVE.value, choices=[mode.value for mode in LiveMode])
mt5_live_order.add_argument("--armed-live", action="store_true")
mt5_live_order.add_argument("--mt5-server", required=True)
mt5_live_order.add_argument("--mt5-login", required=True)
mt5_live_order.add_argument("--mt5-password", required=True)
mt5_live_order.add_argument("--mt5-terminal-path")
mt5_live_order.add_argument("--mt5-symbol", required=True)
mt5_live_order.add_argument("--volume", type=float, required=True)
```

- [ ] **Step 4: Wire MT5 runtime readiness and supervised order execution**

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-live-order":
    mode = LiveMode(args.live_mode)
    mt5_config = _build_mt5_config(args)
    runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
    readiness = build_live_readiness_report(
        venue=Venue.MT5,
        mode=mode,
        symbol=args.symbol,
        app_id=None,
        token=None,
        armed=args.armed_live,
        supported_symbols=set(TraderConfig.default().symbols),
        mt5_config=mt5_config,
        mt5_dependency_ready=mt5_dependency_available(),
        mt5_runtime_status=runtime_status,
    )
    print(f"live_mode={mode.value}")
    print(f"readiness_ok={readiness.ready}")
    if readiness.failures:
        print(f"readiness_failures={','.join(readiness.failures)}")
    if not readiness.ready:
        return 1

    mt5_module = _load_mt5_module()
    request = Mt5OrderRequest(
        symbol=args.symbol,
        venue_symbol=runtime_status.venue_symbol or args.mt5_symbol,
        volume=args.volume,
        order_type="BUY",
        comment="synthetic-trader-mt5",
    )
    result = execute_supervised_mt5_order(
        mode=mode,
        readiness_ok=readiness.ready,
        request=request,
        mt5_module=mt5_module,
    )
    print(f"order_accepted={result.accepted}")
    print(f"order_ticket={result.order_ticket}")
    print(f"deal_ticket={result.deal_ticket}")
    print(f"retcode={result.retcode}")
    print(f"message={result.message}")
    return 0
```

- [ ] **Step 5: Run the CLI MT5 live tests to verify they pass**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -k "Phase6CliMt5LiveTests" -q`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase6_mt5_live_execution.py
git commit -m "feat: add mt5 supervised live order cli"
```

## Task 5: Run Phase 6 Regression

**Files:**
- Modify: `tests/test_phase6_mt5_live_execution.py`
- Modify: `tests/test_phase5_mt5_scaffolding.py`

- [ ] **Step 1: Add one explicit Phase 5 regression if missing**

```python
class Phase6RegressionTests(unittest.TestCase):
    def test_phase5_mt5_fail_closed_static_readiness_still_works(self) -> None:
        from synthetic_trader.config import LiveMode, Mt5Config, Venue
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            venue=Venue.MT5,
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_75",
            app_id=None,
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
            mt5_config=Mt5Config(server="Broker-Demo", login="123456", password="secret"),
            mt5_dependency_ready=True,
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_mt5_symbol_mapping", report.failures)
```

- [ ] **Step 2: Run the focused Phase 6 slices**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py tests/test_phase5_mt5_scaffolding.py -q`
Expected: all focused MT5 tests pass

- [ ] **Step 3: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
........................................................................
[100%]
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase6_mt5_live_execution.py tests/test_phase5_mt5_scaffolding.py
git commit -m "test: validate mt5 live execution scaffolding"
```

## Spec Coverage Check

- terminal-backed MT5 connectivity: covered by Task 2
- runtime-backed MT5 readiness: covered by Task 2
- structured MT5 request and result payloads: covered by Task 1
- supervised tiny-stake MT5 order placement: covered by Task 3
- explicit CLI MT5 live execution entry path: covered by Task 4
- regression safety for existing MT5 scaffolding: covered by Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, concrete commands, and explicit code blocks
- Each verification step states the expected failing or passing behavior directly

## Type Consistency Check

- `Mt5OrderRequest` and `Mt5OrderResult` are the consistent MT5 execution payload types across adapter, supervised-live, and CLI layers
- `Mt5RuntimeStatus` is the consistent runtime-backed readiness payload used by MT5 adapter, supervised-live readiness, and CLI reporting
- `evaluate_mt5_runtime()` is the single MT5 runtime readiness entry point
- `execute_supervised_mt5_order()` is the single supervised MT5 live execution gate above the adapter
