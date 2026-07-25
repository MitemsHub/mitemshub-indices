# Phase 7 MT5 Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MT5 position synchronization, supervised close handling, richer lifecycle journaling, and integrated regression while preserving fail-closed execution behavior.

**Architecture:** Extend the MT5 adapter with structured position-sync and close-result helpers, then layer supervised close control on top of synchronized broker truth. Keep the trading core unchanged by concentrating lifecycle logic inside the MT5 adapter, supervised-live helpers, CLI commands, and journal event emission.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`typing`, current `pytest`/`unittest` suite, optional `MetaTrader5` package behind lazy import, existing CLI and journal modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase7_mt5_lifecycle.py`
  - Focused Phase 7 tests for MT5 sync state, close handling, lifecycle journaling, and CLI reporting.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\mt5.py`
  - Add synchronized position snapshot types, sync result types, close request/result helpers, and MT5 close execution support.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Add sync-aware supervised close helpers and fail-closed lifecycle checks.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add explicit MT5 sync and supervised close commands.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\journal\trade_journal.py`
  - Add richer MT5 lifecycle event emission helpers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase6_mt5_live_execution.py`
  - Keep one regression proving the Phase 6 entry path still works after lifecycle changes.

## Task 1: Add MT5 Position Synchronization Types And Helper

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Create: `tests/test_phase7_mt5_lifecycle.py`

- [ ] **Step 1: Write the failing MT5 sync tests**

```python
import unittest

from synthetic_trader.config import Mt5Config
from synthetic_trader.execution.mt5 import Mt5PositionSnapshot, Mt5SyncResult, synchronize_mt5_positions


class Phase7Mt5SyncTests(unittest.TestCase):
    def test_synchronize_mt5_positions_returns_single_position_snapshot(self) -> None:
        class FakePosition:
            ticket = 101
            symbol = "Volatility 75 Index"
            volume = 0.2
            price_open = 100.5
            price_current = 101.0
            time = 1700000000
            type = 0

        class FakeModule:
            POSITION_TYPE_BUY = 0

            def positions_get(self, symbol=None):
                return [FakePosition()]

        result = synchronize_mt5_positions(
            config=Mt5Config(symbol_map={"R_75": "Volatility 75 Index"}),
            symbol="R_75",
            mt5_module=FakeModule(),
        )

        self.assertTrue(result.ready)
        self.assertEqual(len(result.positions), 1)
        self.assertEqual(result.positions[0].ticket, 101)
```

- [ ] **Step 2: Run the sync tests to verify they fail**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7Mt5SyncTests" -q`
Expected: `ImportError` because the sync types and helper do not exist yet

- [ ] **Step 3: Add MT5 sync state and synchronization helper**

```python
# src/synthetic_trader/execution/mt5.py
from synthetic_trader.domain import Direction


@dataclass(frozen=True)
class Mt5PositionSnapshot:
    symbol: str
    venue_symbol: str
    ticket: int
    direction: Direction
    volume: float
    open_price: float
    current_price: float | None
    broker_time: int | None


@dataclass(frozen=True)
class Mt5SyncResult:
    ready: bool
    failures: tuple[str, ...]
    venue_symbol: str | None
    positions: tuple[Mt5PositionSnapshot, ...]


def synchronize_mt5_positions(
    *,
    config: Mt5Config,
    symbol: str,
    mt5_module,
) -> Mt5SyncResult:
    venue_symbol = config.resolve_symbol(symbol)
    if not venue_symbol:
        return Mt5SyncResult(False, ("missing_mt5_symbol_mapping",), None, ())
    positions = mt5_module.positions_get(symbol=venue_symbol) or []
    snapshots = tuple(
        Mt5PositionSnapshot(
            symbol=symbol,
            venue_symbol=venue_symbol,
            ticket=int(position.ticket),
            direction=Direction.LONG if position.type == mt5_module.POSITION_TYPE_BUY else Direction.SHORT,
            volume=float(position.volume),
            open_price=float(position.price_open),
            current_price=float(position.price_current) if getattr(position, "price_current", None) is not None else None,
            broker_time=int(position.time) if getattr(position, "time", None) is not None else None,
        )
        for position in positions
    )
    return Mt5SyncResult(True, (), venue_symbol, snapshots)
```

- [ ] **Step 4: Run the sync tests to verify they pass**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7Mt5SyncTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py tests/test_phase7_mt5_lifecycle.py
git commit -m "feat: add mt5 position synchronization"
```

## Task 2: Add Supervised MT5 Close Logic

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Create: `tests/test_phase7_mt5_lifecycle.py`

- [ ] **Step 1: Write the failing MT5 close tests**

```python
from synthetic_trader.config import LiveMode
from synthetic_trader.execution.mt5 import Mt5CloseRequest, Mt5PositionSnapshot, close_mt5_position
from synthetic_trader.domain import Direction


class Phase7Mt5CloseTests(unittest.TestCase):
    def test_close_mt5_position_returns_structured_result(self) -> None:
        class FakeResult:
            retcode = 10009
            order = 501
            deal = 601
            comment = "close executed"

        class FakeModule:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_SELL = 1
            ORDER_TIME_GTC = 0
            ORDER_FILLING_FOK = 0

            def order_send(self, payload):
                return FakeResult()

        result = close_mt5_position(
            request=Mt5CloseRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                volume=0.2,
                direction=Direction.LONG,
            ),
            mt5_module=FakeModule(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 501)
```

- [ ] **Step 2: Run the MT5 close tests to verify they fail**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7Mt5CloseTests" -q`
Expected: `ImportError` because `Mt5CloseRequest` and `close_mt5_position()` do not exist yet

- [ ] **Step 3: Add MT5 close request/result handling**

```python
# src/synthetic_trader/execution/mt5.py
@dataclass(frozen=True)
class Mt5CloseRequest:
    symbol: str
    venue_symbol: str
    ticket: int
    volume: float
    direction: Direction


def close_mt5_position(
    *,
    request: Mt5CloseRequest,
    mt5_module,
) -> Mt5OrderResult:
    close_type = mt5_module.ORDER_TYPE_SELL if request.direction is Direction.LONG else mt5_module.ORDER_TYPE_BUY
    payload = {
        "action": mt5_module.TRADE_ACTION_DEAL,
        "symbol": request.venue_symbol,
        "position": request.ticket,
        "volume": request.volume,
        "type": close_type,
        "comment": "synthetic-trader-mt5-close",
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

- [ ] **Step 4: Add sync-aware supervised close wrapper**

```python
# src/synthetic_trader/live/supervised_live.py
from synthetic_trader.execution.mt5 import Mt5CloseRequest, Mt5SyncResult, close_mt5_position
```

```python
# src/synthetic_trader/live/supervised_live.py
def execute_supervised_mt5_close(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    sync_result: Mt5SyncResult,
    ticket: int | None,
    mt5_module,
):
    if not readiness_ok:
        raise RuntimeError("mt5 lifecycle readiness failed")
    if len(sync_result.positions) == 0:
        raise RuntimeError("no synchronized mt5 positions")
    if ticket is None and len(sync_result.positions) != 1:
        raise RuntimeError("ambiguous mt5 positions")
    target = next(position for position in sync_result.positions if ticket is None or position.ticket == ticket)
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("mt5 close is not allowed in this mode")
    return close_mt5_position(
        request=Mt5CloseRequest(
            symbol=target.symbol,
            venue_symbol=target.venue_symbol,
            ticket=target.ticket,
            volume=target.volume,
            direction=target.direction,
        ),
        mt5_module=mt5_module,
    )
```

- [ ] **Step 5: Run the MT5 close tests to verify they pass**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7Mt5CloseTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py src/synthetic_trader/live/supervised_live.py tests/test_phase7_mt5_lifecycle.py
git commit -m "feat: add supervised mt5 close handling"
```

## Task 3: Add Richer MT5 Lifecycle Journaling

**Files:**
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Create: `tests/test_phase7_mt5_lifecycle.py`

- [ ] **Step 1: Write the failing MT5 lifecycle journal tests**

```python
import json
import tempfile
from pathlib import Path

from synthetic_trader.journal.trade_journal import TradeJournal


class Phase7Mt5JournalTests(unittest.TestCase):
    def test_journal_records_mt5_sync_and_close_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mt5_lifecycle.jsonl"
            journal = TradeJournal(path)

            journal.record_event("mt5_sync_summary", {"symbol": "R_75", "positions": 1})
            journal.record_event("mt5_close_result", {"ticket": 101, "accepted": True})

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_sync_summary")
        self.assertEqual(entries[1]["type"], "mt5_close_result")
```

- [ ] **Step 2: Run the journal tests to verify they fail for the new helper API**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7Mt5JournalTests" -q`
Expected: failure after adding a new explicit journal helper test because lifecycle helpers do not exist yet

- [ ] **Step 3: Add MT5 lifecycle journal helpers**

```python
# src/synthetic_trader/journal/trade_journal.py
class TradeJournal:
    def record_mt5_sync_summary(self, *, symbol: str, venue_symbol: str | None, positions: int, failures: tuple[str, ...]) -> None:
        self.record_event(
            "mt5_sync_summary",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "positions": positions,
                "failures": list(failures),
            },
        )

    def record_mt5_close_result(
        self,
        *,
        symbol: str,
        venue_symbol: str,
        ticket: int,
        accepted: bool,
        retcode: int | None,
        message: str,
    ) -> None:
        self.record_event(
            "mt5_close_result",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "ticket": ticket,
                "accepted": accepted,
                "retcode": retcode,
                "message": message,
            },
        )
```

- [ ] **Step 4: Run the journal tests to verify they pass**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7Mt5JournalTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/journal/trade_journal.py tests/test_phase7_mt5_lifecycle.py
git commit -m "feat: add mt5 lifecycle journal helpers"
```

## Task 4: Add Explicit CLI Commands For MT5 Sync And Close

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Create: `tests/test_phase7_mt5_lifecycle.py`
- Modify: `tests/test_phase6_mt5_live_execution.py`

- [ ] **Step 1: Write the failing CLI lifecycle tests**

```python
import contextlib
import io
from unittest.mock import patch

from synthetic_trader.execution.mt5 import Mt5OrderResult, Mt5SyncResult


class Phase7CliLifecycleTests(unittest.TestCase):
    def test_mt5_sync_command_prints_position_count(self) -> None:
        from synthetic_trader.cli import main

        output = io.StringIO()
        with patch(
            "synthetic_trader.cli.synchronize_mt5_positions",
            return_value=Mt5SyncResult(True, (), "Volatility 75 Index", ()),
        ):
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "mt5-sync",
                        "--symbol",
                        "R_75",
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
        self.assertIn("positions=0", output.getvalue())
```

- [ ] **Step 2: Run the CLI lifecycle tests to verify they fail**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7CliLifecycleTests" -q`
Expected: parser error because `mt5-sync` and `mt5-close` do not exist yet

- [ ] **Step 3: Add MT5 sync and close CLI commands**

```python
# src/synthetic_trader/cli.py
from synthetic_trader.execution.mt5 import Mt5SyncResult, synchronize_mt5_positions
from synthetic_trader.live.supervised_live import execute_supervised_mt5_close
```

```python
# src/synthetic_trader/cli.py
mt5_sync = subparsers.add_parser("mt5-sync", help="synchronize MT5 lifecycle state")
mt5_sync.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
mt5_sync.add_argument("--mt5-server", required=True)
mt5_sync.add_argument("--mt5-login", required=True)
mt5_sync.add_argument("--mt5-password", required=True)
mt5_sync.add_argument("--mt5-terminal-path")
mt5_sync.add_argument("--mt5-symbol", required=True)

mt5_close = subparsers.add_parser("mt5-close", help="run supervised MT5 close handling")
mt5_close.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
mt5_close.add_argument("--live-mode", default=LiveMode.DRY_RUN_LIVE.value, choices=[mode.value for mode in LiveMode])
mt5_close.add_argument("--armed-live", action="store_true")
mt5_close.add_argument("--ticket", type=int)
mt5_close.add_argument("--mt5-server", required=True)
mt5_close.add_argument("--mt5-login", required=True)
mt5_close.add_argument("--mt5-password", required=True)
mt5_close.add_argument("--mt5-terminal-path")
mt5_close.add_argument("--mt5-symbol", required=True)
```

- [ ] **Step 4: Wire sync and supervised close flows**

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-sync":
    mt5_config = _build_mt5_config(args)
    sync_result = synchronize_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        mt5_module=_load_mt5_module(),
    )
    print(f"positions={len(sync_result.positions)}")
    if sync_result.failures:
        print(f"sync_failures={','.join(sync_result.failures)}")
        return 1
    return 0

if args.command == "mt5-close":
    mode = LiveMode(args.live_mode)
    mt5_config = _build_mt5_config(args)
    runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
    sync_result = synchronize_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        mt5_module=_load_mt5_module(),
    )
    result = execute_supervised_mt5_close(
        mode=mode,
        readiness_ok=runtime_status.ready,
        sync_result=sync_result,
        ticket=args.ticket,
        mt5_module=_load_mt5_module(),
    )
    if isinstance(result, str):
        print(f"close_result={result}")
        return 0
    print(f"close_accepted={result.accepted}")
    print(f"order_ticket={result.order_ticket}")
    return 0
```

- [ ] **Step 5: Run the CLI lifecycle tests to verify they pass**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -k "Phase7CliLifecycleTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Keep a Phase 6 regression green**

Run: `python -m pytest tests/test_phase6_mt5_live_execution.py -q`
Expected: all Phase 6 MT5 entry tests still pass

- [ ] **Step 7: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase7_mt5_lifecycle.py tests/test_phase6_mt5_live_execution.py
git commit -m "feat: add mt5 lifecycle cli commands"
```

## Task 5: Run Phase 7 Regression

**Files:**
- Modify: `tests/test_phase7_mt5_lifecycle.py`

- [ ] **Step 1: Add one ambiguity regression if missing**

```python
class Phase7RegressionTests(unittest.TestCase):
    def test_mt5_close_refuses_ambiguous_positions(self) -> None:
        from synthetic_trader.config import LiveMode
        from synthetic_trader.execution.mt5 import Mt5PositionSnapshot, Mt5SyncResult
        from synthetic_trader.live.supervised_live import execute_supervised_mt5_close
        from synthetic_trader.domain import Direction

        sync_result = Mt5SyncResult(
            True,
            (),
            "Volatility 75 Index",
            (
                Mt5PositionSnapshot("R_75", "Volatility 75 Index", 1, Direction.LONG, 0.2, 100.0, 101.0, 1700000000),
                Mt5PositionSnapshot("R_75", "Volatility 75 Index", 2, Direction.LONG, 0.2, 100.0, 101.0, 1700000001),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            execute_supervised_mt5_close(
                mode=LiveMode.ARMED_LIVE,
                readiness_ok=True,
                sync_result=sync_result,
                ticket=None,
                mt5_module=object(),
            )
```

- [ ] **Step 2: Run the focused Phase 7 slice**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -q`
Expected: all Phase 7 tests pass

- [ ] **Step 3: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
........................................................................
[100%]
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase7_mt5_lifecycle.py
git commit -m "test: validate mt5 lifecycle management"
```

## Spec Coverage Check

- position synchronization: covered by Task 1
- structured lifecycle state: covered by Tasks 1 and 2
- supervised close logic: covered by Task 2
- richer lifecycle journaling: covered by Task 3
- explicit CLI lifecycle commands: covered by Task 4
- integrated lifecycle regression: covered by Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, explicit commands, and concrete code blocks
- Each verification step states the expected failing or passing behavior directly

## Type Consistency Check

- `Mt5PositionSnapshot` and `Mt5SyncResult` are the consistent MT5 synchronization payloads across adapter, supervised lifecycle handling, and CLI reporting
- `Mt5CloseRequest` is the consistent close target payload used between the supervised lifecycle layer and MT5 adapter
- `synchronize_mt5_positions()` is the single synchronization entry point
- `execute_supervised_mt5_close()` is the single supervised close gate above the MT5 adapter
