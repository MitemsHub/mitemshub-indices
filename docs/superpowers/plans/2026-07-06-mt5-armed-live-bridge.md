# MT5 Armed-Live Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a true MT5-backed `armed-live` strategy session path while preserving the existing simulated `paper` and `dry-run-live` behavior, then refresh the read-only `R_100` preflight evidence.

**Architecture:** Keep `paper-live` as the single orchestration entrypoint, but move trade lifecycle operations behind a small execution backend interface. Simulated modes use a `PaperBroker`-backed adapter, while `Venue.MT5 + LiveMode.ARMED_LIVE` uses an MT5-backed adapter that routes entries, synchronizes broker truth, and closes positions fail-closed at shutdown.

**Tech Stack:** Python 3.11+, `argparse`, `asyncio`, dataclasses, MetaTrader5 Python bridge, existing MT5 adapter helpers, `unittest`, JSONL journaling

---

## File Map

- Create: `src/synthetic_trader/live/execution_backends.py`
  - Shared execution backend protocol, simulated backend, MT5 live backend, and lightweight result containers.
- Modify: `src/synthetic_trader/live/paper_runner.py`
  - Replace hardcoded `PaperBroker` lifecycle calls with the backend abstraction and add mode-aware backend selection.
- Modify: `src/synthetic_trader/cli.py`
  - Pass `live_mode` into the session runner and keep the existing readiness gates in front of live routing.
- Modify: `src/synthetic_trader/journal/trade_journal.py`
  - Add explicit MT5 live lifecycle journal helpers.
- Modify: `src/synthetic_trader/monitoring/surface.py`
  - Extend MT5 monitor filtering and snapshot rendering to include the new live lifecycle events.
- Modify: `tests/test_live_paper_runner.py`
  - Add backend-selection and live-routing tests.
- Create: `tests/test_mt5_live_backend.py`
  - Add focused MT5 backend entry, sync, shutdown, and fail-closed tests.
- Modify: `tests/test_phase10_mt5_monitor.py`
  - Extend monitor coverage for new MT5 live event types.

### Task 1: Refresh Read-Only R_100 Preflight Evidence

**Files:**
- Modify: `artifacts/validation_r100.json`
- Modify: `journals/mt5_analytics.jsonl`
- Reference: `src/synthetic_trader/cli.py`
- Reference: `docs/superpowers/runbooks/2026-07-05-mt5-supervised-rollout.md`

- [ ] **Step 1: Run bounded validation for `R_100`**

Run:

```bash
python -m synthetic_trader.cli validate-system --symbol R_100 --artifact-output artifacts/validation_r100.json
```

Expected:

```text
validation_venue=deriv
validation_mode=paper
validation_symbol=R_100
validation_finalized=True
```

- [ ] **Step 2: Run read-only MT5 armed-live rollout check**

Run:

```bash
python -m synthetic_trader.cli mt5-rollout-check --symbol R_100 --live-mode armed-live --mt5-server "DerivSVG-Server-03" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-terminal-path "c:\Program Files\MetaTrader 5 Terminal\terminal64.exe" --mt5-symbol "Volatility 100 Index" --validation-json artifacts/validation_r100.json --journal journals/mt5_analytics.jsonl
```

Expected:

```text
rollout_stage=armed-live-preflight
rollout_symbol=R_100
rollout_readiness_ok=True
rollout_validation_finalized=True
```

- [ ] **Step 3: Run MT5 sync to confirm broker-side state**

Run:

```bash
python -m synthetic_trader.cli mt5-sync --symbol R_100 --mt5-server "DerivSVG-Server-03" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-terminal-path "c:\Program Files\MetaTrader 5 Terminal\terminal64.exe" --mt5-symbol "Volatility 100 Index" --journal journals/mt5_analytics.jsonl
```

Expected:

```text
mt5_command=mt5-sync
mt5_positions=0
positions=0
```

- [ ] **Step 4: Capture the operator-facing monitor snapshot**

Run:

```bash
python -m synthetic_trader.cli mt5-monitor --journal journals/mt5_analytics.jsonl --symbol R_100
```

Expected:

```text
mt5_symbol=R_100
mt5_runtime_ready=True
mt5_positions=0
```

- [ ] **Step 5: Commit the refreshed preflight artifacts**

```bash
git add artifacts/validation_r100.json journals/mt5_analytics.jsonl
git commit -m "chore: refresh r100 mt5 preflight evidence"
```

### Task 2: Introduce Execution Backend Abstraction

**Files:**
- Create: `src/synthetic_trader/live/execution_backends.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Test: `tests/test_live_paper_runner.py`

- [ ] **Step 1: Write the failing backend-selection tests**

Add to `tests/test_live_paper_runner.py`:

```python
from unittest.mock import Mock
from synthetic_trader.config import LiveMode

def test_run_live_paper_uses_simulated_backend_for_dry_run_mt5(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("synthetic_trader.live.paper_runner.build_execution_backend") as backend_builder:
            backend = Mock()
            backend.open_positions_count.return_value = 0
            backend_builder.return_value = backend

            asyncio.run(
                run_live_paper(
                    symbol="R_75",
                    duration_sec=0,
                    max_live_ticks=0,
                    warmup_count=0,
                    venue=Venue.MT5,
                    live_mode=LiveMode.DRY_RUN_LIVE,
                    journal_path=Path(tmpdir) / "live_paper.jsonl",
                    client_factory=lambda: _FakeClient([], []),
                )
            )

    backend_builder.assert_called_once()
    assert backend_builder.call_args.kwargs["live_mode"] is LiveMode.DRY_RUN_LIVE


def test_run_live_paper_uses_mt5_backend_for_armed_mt5(self) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("synthetic_trader.live.paper_runner.build_execution_backend") as backend_builder:
            backend = Mock()
            backend.open_positions_count.return_value = 0
            backend_builder.return_value = backend

            asyncio.run(
                run_live_paper(
                    symbol="R_75",
                    duration_sec=0,
                    max_live_ticks=0,
                    warmup_count=0,
                    venue=Venue.MT5,
                    live_mode=LiveMode.ARMED_LIVE,
                    journal_path=Path(tmpdir) / "live_paper.jsonl",
                    client_factory=lambda: _FakeClient([], []),
                )
            )

    assert backend_builder.call_args.kwargs["live_mode"] is LiveMode.ARMED_LIVE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_live_paper_runner.py -k "backend_for_dry_run_mt5 or backend_for_armed_mt5" -v
```

Expected:

```text
FAILED tests/test_live_paper_runner.py::... TypeError: run_live_paper() got an unexpected keyword argument 'live_mode'
```

- [ ] **Step 3: Create the execution backend module**

Create `src/synthetic_trader/live/execution_backends.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from synthetic_trader.config import LiveMode, Mt5Config, PaperExecutionConfig, Venue
from synthetic_trader.domain import Candle, OrderIntent, TradeOutcome
from synthetic_trader.execution.paper import PaperBroker


@dataclass(frozen=True)
class SubmitResult:
    accepted: bool
    position_id: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ShutdownResult:
    outcomes: tuple[TradeOutcome, ...]
    open_positions_before_shutdown: int
    unresolved_positions: int
    finalized: bool


class ExecutionBackend(Protocol):
    def submit(self, intent: OrderIntent) -> SubmitResult: ...
    def on_candle(self, candle: Candle) -> list[TradeOutcome]: ...
    def open_positions_count(self) -> int: ...
    def shutdown(self, candle: Candle | None) -> ShutdownResult: ...


class SimulatedExecutionBackend:
    def __init__(self, *, config: PaperExecutionConfig) -> None:
        self._broker = PaperBroker(config)

    def submit(self, intent: OrderIntent) -> SubmitResult:
        position = self._broker.submit(intent)
        return SubmitResult(accepted=True, position_id=position.id, metadata={"backend": "simulated"})

    def on_candle(self, candle: Candle) -> list[TradeOutcome]:
        return self._broker.on_candle(candle)

    def open_positions_count(self) -> int:
        return len(self._broker.positions)

    def shutdown(self, candle: Candle | None) -> ShutdownResult:
        before = len(self._broker.positions)
        outcomes = tuple(self._broker.close_all(candle)) if candle is not None else ()
        return ShutdownResult(
            outcomes=outcomes,
            open_positions_before_shutdown=before,
            unresolved_positions=len(self._broker.positions),
            finalized=True,
        )


def build_execution_backend(
    *,
    symbol: str,
    venue: Venue,
    live_mode: LiveMode,
    paper_config: PaperExecutionConfig,
    mt5_config: Mt5Config,
    journal,
):
    return SimulatedExecutionBackend(config=paper_config)
```

- [ ] **Step 4: Refactor the live runner to use the backend builder**

Modify `src/synthetic_trader/live/paper_runner.py`:

```python
from synthetic_trader.config import LiveMode, TraderConfig, Venue
from synthetic_trader.live.execution_backends import build_execution_backend
```

```python
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
    live_mode: LiveMode = LiveMode.PAPER,
    client_factory: Callable[[], MarketDataClient] | None = None,
    model: OnlineLogisticModel | None = None,
) -> LivePaperSummary:
    ...
    backend = build_execution_backend(
        symbol=symbol,
        venue=venue,
        live_mode=live_mode,
        paper_config=cfg.paper,
        mt5_config=cfg.mt5,
        journal=journal,
    )
```

Replace broker usage:

```python
for outcome in backend.on_candle(primary):
    closed_trades += 1
    risk_engine.register_outcome(outcome)
    journal.record_outcome(outcome)
    journal.teach(live_model, outcome)
```

```python
if risk_decision.approved and risk_decision.intent is not None:
    submit_result = backend.submit(risk_decision.intent)
    if submit_result.accepted:
        risk_engine.register_open()
        journal.record_signal(report.signal)
        approved += 1
```

Shutdown handoff:

```python
shutdown_result = backend.shutdown(final_primary)
open_positions_before_shutdown = shutdown_result.open_positions_before_shutdown
unresolved_positions = shutdown_result.unresolved_positions
finalized = shutdown_result.finalized
for outcome in shutdown_result.outcomes:
    closed_trades += 1
    shutdown_closed_trades += 1
    risk_engine.register_outcome(outcome)
    journal.record_outcome(outcome)
    journal.teach(live_model, outcome)
```

- [ ] **Step 5: Run the focused tests to verify they pass**

Run:

```bash
pytest tests/test_live_paper_runner.py -k "backend_for_dry_run_mt5 or backend_for_armed_mt5" -v
```

Expected:

```text
PASSED tests/test_live_paper_runner.py::...
```

- [ ] **Step 6: Commit the backend abstraction**

```bash
git add src/synthetic_trader/live/execution_backends.py src/synthetic_trader/live/paper_runner.py tests/test_live_paper_runner.py
git commit -m "refactor: route live sessions through execution backends"
```

### Task 3: Implement MT5 Armed-Live Backend

**Files:**
- Modify: `src/synthetic_trader/live/execution_backends.py`
- Modify: `src/synthetic_trader/cli.py`
- Test: `tests/test_mt5_live_backend.py`
- Test: `tests/test_live_paper_runner.py`

- [ ] **Step 1: Write the failing MT5 backend tests**

Create `tests/test_mt5_live_backend.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import Mock

from synthetic_trader.config import Mt5Config
from synthetic_trader.domain import Direction, FeatureSnapshot, OrderIntent, Regime, TradeSignal
from synthetic_trader.execution.mt5 import Mt5OrderResult, Mt5SyncResult
from synthetic_trader.live.execution_backends import Mt5LiveExecutionBackend


class Mt5LiveBackendTests(unittest.TestCase):
    def test_submit_places_mt5_order_and_returns_accepted_result(self) -> None:
        journal = Mock()
        backend = Mt5LiveExecutionBackend(
            mt5_config=Mt5Config(symbol_map={"R_100": "Volatility 100 Index"}),
            symbol="R_100",
            journal=journal,
            mt5_module=Mock(),
        )
        backend._place_order = Mock(
            return_value=Mt5OrderResult(
                accepted=True,
                order_ticket=11,
                deal_ticket=22,
                retcode=10009,
                message="done",
                venue_symbol="Volatility 100 Index",
            )
        )
        backend._sync_positions = Mock(
            return_value=Mt5SyncResult(
                ready=True,
                failures=(),
                venue_symbol="Volatility 100 Index",
                positions=(),
            )
        )

        signal = TradeSignal(
            symbol="R_100",
            direction=Direction.LONG,
            confidence=0.7,
            entry=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            horizon_sec=600,
            snapshot=FeatureSnapshot(
                symbol="R_100",
                epoch=60,
                timeframe_sec=60,
                features={"atr_14": 1.0},
                regime=Regime.RANGE,
                structure={"bias": 0.0},
            ),
            rationale=("test",),
            model_version="unit-test",
        )
        result = backend.submit(OrderIntent(signal=signal, stake=10.0, max_loss=10.0))

        self.assertTrue(result.accepted)
        journal.record_event.assert_any_call("mt5_live_entry_result", unittest.mock.ANY)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_mt5_live_backend.py -v
```

Expected:

```text
FAILED tests/test_mt5_live_backend.py::Mt5LiveBackendTests::... ImportError: cannot import name 'Mt5LiveExecutionBackend'
```

- [ ] **Step 3: Implement the MT5 live backend**

Extend `src/synthetic_trader/live/execution_backends.py`:

```python
from synthetic_trader.execution.mt5 import (
    Mt5OrderRequest,
    Mt5SyncResult,
    close_mt5_position,
    place_mt5_order,
    synchronize_mt5_positions,
)
```

```python
class Mt5LiveExecutionBackend:
    def __init__(self, *, mt5_config: Mt5Config, symbol: str, journal, mt5_module) -> None:
        self._mt5_config = mt5_config
        self._symbol = symbol
        self._journal = journal
        self._mt5_module = mt5_module
        self._last_sync = Mt5SyncResult(ready=True, failures=(), venue_symbol=mt5_config.resolve_symbol(symbol), positions=())

    def submit(self, intent: OrderIntent) -> SubmitResult:
        venue_symbol = self._mt5_config.resolve_symbol(intent.signal.symbol)
        self._journal.record_event(
            "mt5_live_entry_submitted",
            {"symbol": intent.signal.symbol, "venue_symbol": venue_symbol, "mode": "armed-live"},
        )
        result = self._place_order(intent, venue_symbol)
        self._journal.record_event(
            "mt5_live_entry_result",
            {
                "symbol": intent.signal.symbol,
                "venue_symbol": venue_symbol,
                "accepted": result.accepted,
                "order_ticket": result.order_ticket,
                "deal_ticket": result.deal_ticket,
                "retcode": result.retcode,
                "message": result.message,
            },
        )
        self._last_sync = self._sync_positions()
        self._journal.record_event(
            "mt5_live_sync_result",
            {
                "symbol": intent.signal.symbol,
                "venue_symbol": self._last_sync.venue_symbol,
                "positions": len(self._last_sync.positions),
                "failures": list(self._last_sync.failures),
            },
        )
        if result.accepted and not self._last_sync.failures:
            return SubmitResult(accepted=True, position_id=str(result.order_ticket), metadata={"backend": "mt5"})
        self._journal.record_event(
            "mt5_live_fail_closed",
            {"symbol": intent.signal.symbol, "reason": "entry_sync_failed"},
        )
        return SubmitResult(accepted=False, position_id=None, metadata={"backend": "mt5"})

    def on_candle(self, candle: Candle) -> list[TradeOutcome]:
        return []

    def open_positions_count(self) -> int:
        return len(self._last_sync.positions)

    def shutdown(self, candle: Candle | None) -> ShutdownResult:
        sync_result = self._sync_positions()
        self._journal.record_event(
            "mt5_live_shutdown_reconcile",
            {
                "symbol": self._symbol,
                "venue_symbol": sync_result.venue_symbol,
                "positions": len(sync_result.positions),
                "failures": list(sync_result.failures),
            },
        )
        if sync_result.failures or len(sync_result.positions) > 1:
            self._journal.record_event(
                "mt5_live_fail_closed",
                {"symbol": self._symbol, "reason": "ambiguous_shutdown_state"},
            )
            return ShutdownResult(
                outcomes=(),
                open_positions_before_shutdown=len(sync_result.positions),
                unresolved_positions=len(sync_result.positions),
                finalized=False,
            )
        return ShutdownResult(
            outcomes=(),
            open_positions_before_shutdown=len(sync_result.positions),
            unresolved_positions=len(sync_result.positions),
            finalized=True,
        )

    def _place_order(self, intent: OrderIntent, venue_symbol: str | None) -> Mt5OrderResult:
        return place_mt5_order(
            request=Mt5OrderRequest(
                symbol=intent.signal.symbol,
                venue_symbol=venue_symbol or intent.signal.symbol,
                volume=float(intent.metadata.get("volume", 0.2)),
                order_type="BUY" if intent.signal.direction is Direction.LONG else "SELL",
                stop_loss=intent.signal.stop_loss,
                take_profit=intent.signal.take_profit,
                comment="synthetic-trader-mt5-live",
            ),
            mt5_module=self._mt5_module,
        )

    def _sync_positions(self) -> Mt5SyncResult:
        return synchronize_mt5_positions(
            config=self._mt5_config,
            symbol=self._symbol,
            mt5_module=self._mt5_module,
        )
```

Update the builder in the same file:

```python
def build_execution_backend(
    *,
    symbol: str,
    venue: Venue,
    live_mode: LiveMode,
    paper_config: PaperExecutionConfig,
    mt5_config: Mt5Config,
    journal,
):
    if venue is Venue.MT5 and live_mode is LiveMode.ARMED_LIVE:
        import MetaTrader5  # type: ignore

        return Mt5LiveExecutionBackend(
            mt5_config=mt5_config,
            symbol=symbol,
            journal=journal,
            mt5_module=MetaTrader5,
        )
    return SimulatedExecutionBackend(config=paper_config)
```

- [ ] **Step 4: Pass live mode through the CLI session runner**

Modify `src/synthetic_trader/cli.py`:

```python
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
    config=config,
    venue=venue,
    live_mode=mode,
    model=OnlineLogisticModel.load(args.model_load) if args.model_load else None,
)
```

- [ ] **Step 5: Run the MT5 backend and live-runner tests**

Run:

```bash
pytest tests/test_mt5_live_backend.py tests/test_live_paper_runner.py -k "mt5 or armed" -v
```

Expected:

```text
PASSED tests/test_mt5_live_backend.py::...
PASSED tests/test_live_paper_runner.py::...
```

- [ ] **Step 6: Commit the MT5 backend routing**

```bash
git add src/synthetic_trader/live/execution_backends.py src/synthetic_trader/live/paper_runner.py src/synthetic_trader/cli.py tests/test_mt5_live_backend.py tests/test_live_paper_runner.py
git commit -m "feat: add mt5 armed-live execution backend"
```

### Task 4: Add Fail-Closed Shutdown And MT5 Live Monitoring

**Files:**
- Modify: `src/synthetic_trader/live/execution_backends.py`
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`
- Modify: `tests/test_mt5_live_backend.py`
- Modify: `tests/test_phase10_mt5_monitor.py`

- [ ] **Step 1: Write failing tests for shutdown journaling and monitoring**

Add to `tests/test_mt5_live_backend.py`:

```python
def test_shutdown_records_fail_closed_when_multiple_positions_exist(self) -> None:
    journal = Mock()
    backend = Mt5LiveExecutionBackend(
        mt5_config=Mt5Config(symbol_map={"R_100": "Volatility 100 Index"}),
        symbol="R_100",
        journal=journal,
        mt5_module=Mock(),
    )
    backend._sync_positions = Mock(
        return_value=Mt5SyncResult(
            ready=True,
            failures=(),
            venue_symbol="Volatility 100 Index",
            positions=(Mock(ticket=1), Mock(ticket=2)),
        )
    )

    result = backend.shutdown(None)

    self.assertFalse(result.finalized)
    journal.record_event.assert_any_call(
        "mt5_live_fail_closed",
        {"symbol": "R_100", "reason": "ambiguous_shutdown_state"},
    )
```

Add to `tests/test_phase10_mt5_monitor.py`:

```python
def test_build_mt5_monitor_snapshot_tracks_live_entry_and_fail_closed_events(self) -> None:
    snapshot = build_mt5_monitor_snapshot(
        events=[
            {"type": "mt5_live_entry_result", "symbol": "R_100", "venue_symbol": "Volatility 100 Index", "accepted": True, "retcode": 10009, "message": "done"},
            {"type": "mt5_live_fail_closed", "symbol": "R_100", "reason": "ambiguous_shutdown_state"},
        ],
        symbol="R_100",
    )

    self.assertEqual(snapshot["last_live_entry_accepted"], True)
    self.assertEqual(snapshot["last_fail_closed_reason"], "ambiguous_shutdown_state")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_mt5_live_backend.py tests/test_phase10_mt5_monitor.py -k "fail_closed or live_entry" -v
```

Expected:

```text
FAILED ... KeyError: 'last_live_entry_accepted'
```

- [ ] **Step 3: Add journal helper methods for MT5 live lifecycle events**

Modify `src/synthetic_trader/journal/trade_journal.py`:

```python
def record_mt5_live_entry_result(
    self,
    *,
    symbol: str,
    venue_symbol: str | None,
    accepted: bool,
    order_ticket: int | None,
    deal_ticket: int | None,
    retcode: int | None,
    message: str,
) -> None:
    self.record_event(
        "mt5_live_entry_result",
        {
            "symbol": symbol,
            "venue_symbol": venue_symbol,
            "accepted": accepted,
            "order_ticket": order_ticket,
            "deal_ticket": deal_ticket,
            "retcode": retcode,
            "message": message,
        },
    )


def record_mt5_live_fail_closed(self, *, symbol: str, reason: str) -> None:
    self.record_event(
        "mt5_live_fail_closed",
        {"symbol": symbol, "reason": reason},
    )
```

- [ ] **Step 4: Extend the MT5 monitor snapshot with live lifecycle fields**

Modify `src/synthetic_trader/monitoring/surface.py`:

```python
MT5_EVENT_TYPES = {
    "mt5_runtime_summary",
    "mt5_sync_summary",
    "mt5_reconcile_summary",
    "mt5_close_result",
    "mt5_modify_result",
    "mt5_live_entry_result",
    "mt5_live_shutdown_reconcile",
    "mt5_live_fail_closed",
}
```

Add new snapshot keys:

```python
"last_live_entry_accepted": False,
"last_live_entry_retcode": None,
"last_live_entry_message": "",
"last_fail_closed_reason": "",
```

Add event handling:

```python
elif event_type == "mt5_live_entry_result":
    snapshot["last_live_entry_accepted"] = bool(event.get("accepted", False))
    snapshot["last_live_entry_retcode"] = event.get("retcode")
    snapshot["last_live_entry_message"] = str(event.get("message", ""))
elif event_type == "mt5_live_fail_closed":
    snapshot["last_fail_closed_reason"] = str(event.get("reason", ""))
```

Update rendering order:

```python
"last_live_entry_accepted",
"last_live_entry_retcode",
"last_live_entry_message",
"last_fail_closed_reason",
```

- [ ] **Step 5: Replace direct `record_event()` calls in the MT5 backend with journal helpers**

Modify `src/synthetic_trader/live/execution_backends.py`:

```python
self._journal.record_mt5_live_entry_result(
    symbol=intent.signal.symbol,
    venue_symbol=venue_symbol,
    accepted=result.accepted,
    order_ticket=result.order_ticket,
    deal_ticket=result.deal_ticket,
    retcode=result.retcode,
    message=result.message,
)
```

```python
self._journal.record_mt5_live_fail_closed(
    symbol=self._symbol,
    reason="ambiguous_shutdown_state",
)
```

- [ ] **Step 6: Run the shutdown and monitor tests**

Run:

```bash
pytest tests/test_mt5_live_backend.py tests/test_phase10_mt5_monitor.py -v
```

Expected:

```text
PASSED tests/test_mt5_live_backend.py::...
PASSED tests/test_phase10_mt5_monitor.py::...
```

- [ ] **Step 7: Commit the fail-closed monitoring work**

```bash
git add src/synthetic_trader/live/execution_backends.py src/synthetic_trader/journal/trade_journal.py src/synthetic_trader/monitoring/surface.py tests/test_mt5_live_backend.py tests/test_phase10_mt5_monitor.py
git commit -m "feat: add mt5 live fail-closed monitoring"
```

### Task 5: Run Full Regression And Re-Validate The Shared Path

**Files:**
- Modify: `artifacts/validation_r100.json`
- Modify: `journals/r100_seeded_model_dry_run.jsonl`
- Test: `tests/test_live_paper_runner.py`
- Test: `tests/test_mt5_live_backend.py`
- Test: `tests/test_phase10_mt5_monitor.py`
- Test: `tests/test_phase16_supervised_rollout.py`

- [ ] **Step 1: Run focused regression tests**

Run:

```bash
pytest tests/test_live_paper_runner.py tests/test_mt5_live_backend.py tests/test_phase10_mt5_monitor.py tests/test_phase16_supervised_rollout.py -v
```

Expected:

```text
PASSED tests/test_live_paper_runner.py::...
PASSED tests/test_mt5_live_backend.py::...
PASSED tests/test_phase10_mt5_monitor.py::...
PASSED tests/test_phase16_supervised_rollout.py::...
```

- [ ] **Step 2: Run a shared-path MT5 dry-run regression**

Run:

```bash
python -m synthetic_trader.cli paper-live --symbol R_100 --venue mt5 --live-mode dry-run-live --mt5-server "DerivSVG-Server-03" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-terminal-path "c:\Program Files\MetaTrader 5 Terminal\terminal64.exe" --mt5-symbol "Volatility 100 Index" --model-load artifacts/r100_live_seed_model.json --journal journals/r100_seeded_model_dry_run.jsonl --duration-sec 180
```

Expected:

```text
live_mode=dry-run-live
readiness_ok=True
symbol=R_100
finalized=True
```

- [ ] **Step 3: Refresh the read-only `R_100` validation artifact after code changes**

Run:

```bash
python -m synthetic_trader.cli validate-system --symbol R_100 --artifact-output artifacts/validation_r100.json
```

Expected:

```text
validation_symbol=R_100
validation_finalized=True
```

- [ ] **Step 4: Review diagnostics on modified Python files**

Run the editor diagnostics for:

```text
src/synthetic_trader/live/execution_backends.py
src/synthetic_trader/live/paper_runner.py
src/synthetic_trader/cli.py
src/synthetic_trader/journal/trade_journal.py
src/synthetic_trader/monitoring/surface.py
```

Expected:

```text
No new syntax or import errors in modified files.
```

- [ ] **Step 5: Commit the validated MT5 armed-live bridge**

```bash
git add src/synthetic_trader/live/execution_backends.py src/synthetic_trader/live/paper_runner.py src/synthetic_trader/cli.py src/synthetic_trader/journal/trade_journal.py src/synthetic_trader/monitoring/surface.py tests/test_live_paper_runner.py tests/test_mt5_live_backend.py tests/test_phase10_mt5_monitor.py tests/test_phase16_supervised_rollout.py artifacts/validation_r100.json journals/r100_seeded_model_dry_run.jsonl
git commit -m "feat: add supervised mt5 armed-live strategy bridge"
```
