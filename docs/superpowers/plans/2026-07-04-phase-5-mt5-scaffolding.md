# Phase 5 MT5 Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MT5 venue scaffolding with explicit venue selection, MT5 config and symbol mapping, venue-aware paper/supervised routing, and fail-closed readiness checks without changing the core alpha pipeline.

**Architecture:** Introduce a narrow venue seam at the execution boundary so the paper runner and supervised-live router can work with either Deriv or MT5. Keep the decision, risk, journal, and paper broker flow unchanged while moving venue-specific behavior into small adapters and config structures.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`enum`/`typing`, current `unittest`-style test suite, existing CLI, live runner modules, optional MT5 dependency behind lazy imports

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\venues.py`
  - Venue enums, protocols, and small adapter builders shared by Deriv and MT5.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\mt5.py`
  - MT5 credentials/config helpers, symbol mapping, dependency check, and a thin lazy-import MT5 adapter scaffold.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase5_mt5_scaffolding.py`
  - Focused Phase 5 tests for venue config, readiness, CLI routing, and paper/supervised MT5 scaffolding.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\config.py`
  - Add venue enum and MT5 config structures.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Allow venue client injection and venue-aware live-paper routing.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Extend readiness/session routing to support venue-specific checks.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add `--venue mt5` and MT5-specific runtime inputs.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_paper_runner.py`
  - Extend runner coverage where venue injection changes existing seams.

## Task 1: Add Venue And MT5 Config Types

**Files:**
- Modify: `src/synthetic_trader/config.py`
- Create: `tests/test_phase5_mt5_scaffolding.py`

- [ ] **Step 1: Write the failing venue and MT5 config tests**

```python
import unittest

from synthetic_trader.config import Mt5Config, Venue


class Phase5VenueConfigTests(unittest.TestCase):
    def test_venue_exposes_deriv_and_mt5_values(self) -> None:
        self.assertEqual(Venue.DERIV.value, "deriv")
        self.assertEqual(Venue.MT5.value, "mt5")

    def test_mt5_config_maps_project_symbol_to_mt5_symbol(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal64.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        self.assertEqual(config.resolve_symbol("R_75"), "Volatility 75 Index")
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5VenueConfigTests" -q`
Expected: `ImportError` because `Venue` and `Mt5Config` do not exist yet

- [ ] **Step 3: Add the minimal venue enum and MT5 config**

```python
# src/synthetic_trader/config.py
from dataclasses import dataclass, field
from enum import Enum


class Venue(str, Enum):
    DERIV = "deriv"
    MT5 = "mt5"


@dataclass(frozen=True)
class Mt5Config:
    server: str | None = None
    login: str | None = None
    password: str | None = None
    terminal_path: str | None = None
    symbol_map: dict[str, str] = field(default_factory=dict)

    def resolve_symbol(self, symbol: str) -> str | None:
        return self.symbol_map.get(symbol)
```

```python
# src/synthetic_trader/config.py
@dataclass(frozen=True)
class TraderConfig:
    symbols: dict[str, SymbolProfile] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paper: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)
    mt5: Mt5Config = field(default_factory=Mt5Config)
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5VenueConfigTests" -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/config.py tests/test_phase5_mt5_scaffolding.py
git commit -m "feat: add venue and mt5 config types"
```

## Task 2: Add Venue Protocols And MT5 Adapter Scaffold

**Files:**
- Create: `src/synthetic_trader/execution/venues.py`
- Create: `src/synthetic_trader/execution/mt5.py`
- Create: `tests/test_phase5_mt5_scaffolding.py`

- [ ] **Step 1: Write the failing MT5 adapter tests**

```python
from synthetic_trader.config import Mt5Config
from synthetic_trader.execution.mt5 import build_mt5_credentials, mt5_dependency_available


class Phase5Mt5AdapterTests(unittest.TestCase):
    def test_build_mt5_credentials_preserves_symbol_map(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal64.exe",
            symbol_map={"R_100": "Volatility 100 Index"},
        )

        credentials = build_mt5_credentials(config)
        self.assertEqual(credentials.symbol_map["R_100"], "Volatility 100 Index")

    def test_mt5_dependency_available_returns_bool(self) -> None:
        self.assertIn(mt5_dependency_available(), {True, False})
```

- [ ] **Step 2: Run the MT5 adapter tests to verify they fail**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5Mt5AdapterTests" -q`
Expected: `ModuleNotFoundError` because `synthetic_trader.execution.mt5` does not exist yet

- [ ] **Step 3: Add the venue protocols**

```python
# src/synthetic_trader/execution/venues.py
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from synthetic_trader.domain import Tick


class MarketDataClient(Protocol):
    async def __aenter__(self) -> "MarketDataClient":
        pass

    async def __aexit__(self, *_: object) -> None:
        pass

    async def ticks_history(self, symbol: str, count: int = 5000, end: str | int = "latest") -> list[Tick]:
        pass

    async def subscribe_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        pass
```

- [ ] **Step 4: Add the minimal MT5 adapter scaffold**

```python
# src/synthetic_trader/execution/mt5.py
from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.config import Mt5Config


@dataclass(frozen=True)
class Mt5Credentials:
    server: str | None
    login: str | None
    password: str | None
    terminal_path: str | None
    symbol_map: dict[str, str]


def build_mt5_credentials(config: Mt5Config) -> Mt5Credentials:
    return Mt5Credentials(
        server=config.server,
        login=config.login,
        password=config.password,
        terminal_path=config.terminal_path,
        symbol_map=dict(config.symbol_map),
    )


def mt5_dependency_available() -> bool:
    try:
        import MetaTrader5  # type: ignore
    except ImportError:
        return False
    return True
```

- [ ] **Step 5: Run the MT5 adapter tests to verify they pass**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5Mt5AdapterTests" -q`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/execution/venues.py src/synthetic_trader/execution/mt5.py tests/test_phase5_mt5_scaffolding.py
git commit -m "feat: add mt5 adapter scaffold"
```

## Task 3: Make The Live Paper Runner Venue-Aware

**Files:**
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Create: `tests/test_phase5_mt5_scaffolding.py`
- Modify: `tests/test_live_paper_runner.py`

- [ ] **Step 1: Write the failing venue-injection runner test**

```python
from unittest.mock import AsyncMock

from synthetic_trader.config import TraderConfig, Venue
from synthetic_trader.domain import Tick
from synthetic_trader.live.paper_runner import run_live_paper


class Phase5PaperRunnerVenueTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_live_paper_uses_injected_market_data_client(self) -> None:
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def ticks_history(self, symbol: str, count: int = 5000, end: str | int = "latest") -> list[Tick]:
                return [Tick(symbol=symbol, epoch=1.0, price=100.0)]

            async def subscribe_ticks(self, symbol: str):
                if False:
                    yield Tick(symbol=symbol, epoch=2.0, price=101.0)

        summary = await run_live_paper(
            symbol="R_75",
            duration_sec=0,
            warmup_count=1,
            max_live_ticks=0,
            config=TraderConfig.default(),
            venue=Venue.MT5,
            client_factory=lambda: FakeClient(),
        )

        self.assertEqual(summary.symbol, "R_75")
        self.assertEqual(summary.warmup_ticks, 1)
```

- [ ] **Step 2: Run the venue-injection runner test to verify it fails**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5PaperRunnerVenueTests" -q`
Expected: `TypeError` because `run_live_paper()` does not accept `venue` or `client_factory`

- [ ] **Step 3: Add venue and client injection to the paper runner**

```python
# src/synthetic_trader/live/paper_runner.py
from collections.abc import Callable

from synthetic_trader.config import TraderConfig, Venue
from synthetic_trader.execution.venues import MarketDataClient
```

```python
# src/synthetic_trader/live/paper_runner.py
def _build_deriv_client(app_id: str | None, token: str | None):
    credentials = deriv_credentials_from_env(app_id=app_id, token=token)
    return DerivWebSocketClient(credentials)
```

```python
# src/synthetic_trader/live/paper_runner.py
async def run_live_paper(
    symbol: str,
    app_id: str | None = None,
    token: str | None = None,
    duration_sec: int = 900,
    max_live_ticks: int | None = None,
    warmup_count: int = 5000,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
    journal_path: str | Path = "journals/live_paper.jsonl",
    ticks_output_path: str | Path | None = None,
    config: TraderConfig | None = None,
    venue: Venue = Venue.DERIV,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> LivePaperSummary:
    cfg = config or TraderConfig.default()
    if symbol not in cfg.symbols:
        raise ValueError(f"unsupported symbol {symbol!r}")
    factory = client_factory or (lambda: _build_deriv_client(app_id=app_id, token=token))
    async with factory() as client:
        if warmup_count > 0:
            warmup = await client.ticks_history(symbol=symbol, count=warmup_count)
            warmup_ticks = len(warmup)
```

- [ ] **Step 4: Extend one existing runner regression to prove Deriv still works**

```python
# tests/test_live_paper_runner.py
class LivePaperRunnerTests(unittest.TestCase):
    def test_paper_live_summary_prints_shutdown_fields(self) -> None:
        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=50,
            warmup_ticks=100,
            signals=4,
            approved_signals=2,
            rejected_signals=2,
            closed_trades=2,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=1,
            final_equity=1002.5,
            model_version="unit-test",
        )
        with patch("synthetic_trader.cli.run_live_paper", return_value=summary) as run_live_paper_mock:
            exit_code = main(["paper-live", "--symbol", "R_75", "--duration-sec", "1"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_live_paper_mock.call_args.kwargs["venue"].value, "deriv")
```

- [ ] **Step 5: Run the runner tests to verify they pass**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5PaperRunnerVenueTests" tests/test_live_paper_runner.py -q`
Expected: all selected tests pass

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/live/paper_runner.py tests/test_phase5_mt5_scaffolding.py tests/test_live_paper_runner.py
git commit -m "feat: make paper runner venue aware"
```

## Task 4: Add Venue-Aware Supervised Readiness And Session Routing

**Files:**
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Create: `tests/test_phase5_mt5_scaffolding.py`

- [ ] **Step 1: Write the failing MT5 readiness and routing tests**

```python
from unittest.mock import AsyncMock

from synthetic_trader.config import LiveMode, Mt5Config, Venue
from synthetic_trader.live.supervised_live import build_live_readiness_report, run_supervised_live_session


class Phase5SupervisedVenueTests(unittest.IsolatedAsyncioTestCase):
    async def test_mt5_readiness_fails_without_symbol_mapping(self) -> None:
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

    async def test_supervised_session_routes_mt5_runner(self) -> None:
        runner = AsyncMock(return_value={"status": "mt5-dry-run"})

        result = await run_supervised_live_session(
            venue=Venue.MT5,
            mode=LiveMode.DRY_RUN_LIVE,
            readiness_ok=True,
            dry_run_runner=runner,
            armed_runner=AsyncMock(),
        )

        self.assertEqual(result["status"], "mt5-dry-run")
        runner.assert_awaited_once()
```

- [ ] **Step 2: Run the MT5 readiness tests to verify they fail**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5SupervisedVenueTests" -q`
Expected: `TypeError` because `build_live_readiness_report()` and `run_supervised_live_session()` are not venue-aware yet

- [ ] **Step 3: Extend readiness for venue-specific validation**

```python
# src/synthetic_trader/live/supervised_live.py
from synthetic_trader.config import LiveMode, Mt5Config, Venue
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
    if mode is LiveMode.ARMED_LIVE and not armed:
        failures.append("missing_armed_confirmation")
    return LiveReadinessReport(mode=mode, ready=not failures, failures=tuple(failures))
```

- [ ] **Step 4: Make the supervised session router accept a venue parameter**

```python
# src/synthetic_trader/live/supervised_live.py
async def run_supervised_live_session(
    *,
    venue: Venue = Venue.DERIV,
    mode: LiveMode,
    readiness_ok: bool,
    dry_run_runner,
    armed_runner,
):
    if not readiness_ok:
        raise RuntimeError(f"{venue.value} readiness failed")
    if mode is LiveMode.DRY_RUN_LIVE:
        return await dry_run_runner()
    if mode is LiveMode.ARMED_LIVE:
        return await armed_runner()
    raise RuntimeError("supervised live session is not used in paper mode")
```

- [ ] **Step 5: Run the MT5 readiness tests to verify they pass**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5SupervisedVenueTests" -q`
Expected: all selected tests pass

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/live/supervised_live.py tests/test_phase5_mt5_scaffolding.py
git commit -m "feat: add venue aware supervised readiness"
```

## Task 5: Add CLI Venue Parsing And MT5 Session Wiring

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/execution/mt5.py`
- Create: `tests/test_phase5_mt5_scaffolding.py`

- [ ] **Step 1: Write the failing CLI MT5 tests**

```python
import contextlib
import io
from unittest.mock import patch

from synthetic_trader.live.paper_runner import LivePaperSummary


class Phase5CliVenueTests(unittest.TestCase):
    def test_paper_live_mt5_reports_readiness_failures(self) -> None:
        from synthetic_trader.cli import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "paper-live",
                    "--venue",
                    "mt5",
                    "--symbol",
                    "R_75",
                    "--live-mode",
                    "dry-run-live",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("missing_mt5_server", output.getvalue())

    def test_paper_live_mt5_uses_mt5_runner_path(self) -> None:
        from synthetic_trader.cli import main

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=0,
            warmup_ticks=0,
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

        with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
            with patch("synthetic_trader.cli.run_live_paper", return_value=summary) as run_live_paper_mock:
                exit_code = main(
                    [
                        "paper-live",
                        "--venue",
                        "mt5",
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
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_live_paper_mock.call_args.kwargs["venue"].value, "mt5")
```

- [ ] **Step 2: Run the CLI MT5 tests to verify they fail**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5CliVenueTests" -q`
Expected: parser error because `--venue` and MT5 flags do not exist yet

- [ ] **Step 3: Add MT5 flag parsing and config assembly**

```python
# src/synthetic_trader/cli.py
from synthetic_trader.config import LiveMode, Mt5Config, PaperExecutionConfig, TraderConfig, Venue
from synthetic_trader.execution.mt5 import mt5_dependency_available
```

```python
# src/synthetic_trader/cli.py
paper_live.add_argument("--venue", default=Venue.DERIV.value, choices=[venue.value for venue in Venue])
paper_live.add_argument("--mt5-server")
paper_live.add_argument("--mt5-login")
paper_live.add_argument("--mt5-password")
paper_live.add_argument("--mt5-terminal-path")
paper_live.add_argument("--mt5-symbol", help="venue symbol alias for the selected project symbol")
```

```python
# src/synthetic_trader/cli.py
def _build_mt5_config(args: argparse.Namespace) -> Mt5Config:
    symbol_map = {args.symbol: args.mt5_symbol} if getattr(args, "mt5_symbol", None) else {}
    return Mt5Config(
        server=getattr(args, "mt5_server", None),
        login=getattr(args, "mt5_login", None),
        password=getattr(args, "mt5_password", None),
        terminal_path=getattr(args, "mt5_terminal_path", None),
        symbol_map=symbol_map,
    )
```

- [ ] **Step 4: Wire venue-aware readiness and runner calls**

```python
# src/synthetic_trader/cli.py
if args.command == "paper-live":
    venue = Venue(args.venue)
    mode = LiveMode(args.live_mode)
    mt5_config = _build_mt5_config(args)
    readiness = build_live_readiness_report(
        venue=venue,
        mode=mode,
        symbol=args.symbol,
        app_id=args.app_id,
        token=args.api_token,
        armed=args.armed_live,
        supported_symbols=set(TraderConfig.default().symbols),
        mt5_config=mt5_config,
        mt5_dependency_ready=mt5_dependency_available() if venue is Venue.MT5 else False,
    )
    run_kwargs = dict(
        symbol=args.symbol,
        app_id=args.app_id,
        token=args.api_token,
        duration_sec=args.duration_sec,
        max_live_ticks=args.max_live_ticks,
        warmup_count=args.warmup_count,
        timeframe_sec=args.timeframe,
        higher_timeframe_sec=args.higher_timeframe,
        journal_path=args.journal,
        ticks_output_path=args.ticks_output,
        config=_build_runtime_config(args),
        venue=venue,
    )
    summary = asyncio.run(
        run_supervised_live_session(
            venue=venue,
            mode=mode,
            readiness_ok=readiness.ready,
            dry_run_runner=lambda: run_live_paper(**run_kwargs),
            armed_runner=lambda: run_live_paper(**run_kwargs),
        )
    )
```

- [ ] **Step 5: Run the CLI MT5 tests to verify they pass**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -k "Phase5CliVenueTests" -q`
Expected: all selected tests pass

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/execution/mt5.py tests/test_phase5_mt5_scaffolding.py
git commit -m "feat: add mt5 cli scaffolding"
```

## Task 6: Run Full Phase 5 Regression

**Files:**
- Modify: `tests/test_phase5_mt5_scaffolding.py`

- [ ] **Step 1: Add a fail-closed regression if missing**

```python
class Phase5RegressionTests(unittest.TestCase):
    def test_mt5_supervised_path_fails_closed_without_runtime(self) -> None:
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
            mt5_config=Mt5Config(
                server="Broker-Demo",
                login="123456",
                password="secret",
                symbol_map={"R_75": "Volatility 75 Index"},
            ),
            mt5_dependency_ready=False,
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_mt5_runtime", report.failures)
```

- [ ] **Step 2: Run the focused Phase 5 slice**

Run: `python -m pytest tests/test_phase5_mt5_scaffolding.py -q`
Expected: all Phase 5 tests pass

- [ ] **Step 3: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
.................................................................
[100%]
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase5_mt5_scaffolding.py
git commit -m "test: validate mt5 scaffolding and regressions"
```

## Spec Coverage Check

- venue abstraction: covered by Tasks 1 and 2
- MT5 config and credentials: covered by Tasks 1, 2, and 5
- MT5 readiness validation: covered by Task 4
- explicit paper/supervised venue selection: covered by Tasks 3 and 5
- symbol mapping: covered by Tasks 1, 4, and 5
- fail-closed behavior and regression safety: covered by Task 6

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task names exact files and concrete commands
- Each code-changing step includes explicit code snippets rather than vague instructions

## Type Consistency Check

- `Venue` is the consistent venue selector across config, CLI, paper runner, and supervised live routing
- `Mt5Config` is the consistent MT5 configuration type across config, readiness, and CLI wiring
- `MarketDataClient` is the consistent venue adapter protocol used for injected paper-runner clients
- `build_live_readiness_report()` and `run_supervised_live_session()` remain the single supervised-live entry points, extended to support venue-aware behavior rather than replaced
