# Phase 8 MT5 Modify And Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MT5 lifecycle reconciliation, supervised modify handling, richer refinement journaling, and regression coverage while preserving fail-closed safety.

**Architecture:** Extend the MT5 adapter with structured reconciliation and modification helpers, then gate all broker mutation through the supervised-live layer so mutation only happens against reconciled and actionable broker state. Keep analytics out of scope and preserve the current MT5 entry, sync, and close surfaces.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`typing`, current `pytest`/`unittest` suite, optional `MetaTrader5` package behind lazy import, current CLI and journal modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase8_mt5_refinement.py`
  - Focused Phase 8 tests for reconciliation state, supervised modify handling, journaling, and CLI reporting.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\mt5.py`
  - Add reconciliation result types, modify request helpers, and broker-side modify execution support.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\supervised_live.py`
  - Add sync-aware supervised MT5 modify handling on top of reconciled lifecycle state.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\journal\trade_journal.py`
  - Add explicit reconciliation and modify journal helpers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add explicit MT5 reconcile and modify commands.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase7_mt5_lifecycle.py`
  - Keep one lifecycle regression green after the refinement changes.

## Task 1: Add MT5 Reconciliation State

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Create: `tests/test_phase8_mt5_refinement.py`

- [ ] **Step 1: Write the failing MT5 reconciliation tests**

```python
import unittest

from synthetic_trader.config import Mt5Config
from synthetic_trader.execution.mt5 import Mt5ReconcileResult, reconcile_mt5_positions


class Phase8Mt5ReconcileTests(unittest.TestCase):
    def test_reconcile_mt5_positions_marks_single_target_actionable(self) -> None:
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

        result = reconcile_mt5_positions(
            config=Mt5Config(symbol_map={"R_75": "Volatility 75 Index"}),
            symbol="R_75",
            ticket=None,
            mt5_module=FakeModule(),
        )

        self.assertIsInstance(result, Mt5ReconcileResult)
        self.assertTrue(result.actionable)
        self.assertEqual(result.target_ticket, 101)
```

- [ ] **Step 2: Run the reconciliation tests to verify they fail**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8Mt5ReconcileTests" -q`
Expected: `ImportError` because `Mt5ReconcileResult` and `reconcile_mt5_positions()` do not exist yet

- [ ] **Step 3: Add MT5 reconciliation result and helper**

```python
# src/synthetic_trader/execution/mt5.py
@dataclass(frozen=True)
class Mt5ReconcileResult:
    ready: bool
    actionable: bool
    failures: tuple[str, ...]
    target_ticket: int | None
    sync_result: Mt5SyncResult


def reconcile_mt5_positions(
    *,
    config: Mt5Config,
    symbol: str,
    ticket: int | None,
    mt5_module,
) -> Mt5ReconcileResult:
    sync_result = synchronize_mt5_positions(config=config, symbol=symbol, mt5_module=mt5_module)
    failures = list(sync_result.failures)
    target_ticket: int | None = None
    if not sync_result.positions:
        failures.append("no_synchronized_mt5_positions")
    elif ticket is None:
        if len(sync_result.positions) == 1:
            target_ticket = sync_result.positions[0].ticket
        else:
            failures.append("ambiguous_mt5_positions")
    else:
        matches = [position for position in sync_result.positions if position.ticket == ticket]
        if len(matches) != 1:
            failures.append("missing_mt5_target_ticket")
        else:
            target_ticket = matches[0].ticket
    return Mt5ReconcileResult(
        ready=sync_result.ready and not failures,
        actionable=not failures and target_ticket is not None,
        failures=tuple(failures),
        target_ticket=target_ticket,
        sync_result=sync_result,
    )
```

- [ ] **Step 4: Run the reconciliation tests to verify they pass**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8Mt5ReconcileTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py tests/test_phase8_mt5_refinement.py
git commit -m "feat: add mt5 reconciliation state"
```

## Task 2: Add Supervised MT5 Modify Handling

**Files:**
- Modify: `src/synthetic_trader/execution/mt5.py`
- Modify: `src/synthetic_trader/live/supervised_live.py`
- Create: `tests/test_phase8_mt5_refinement.py`

- [ ] **Step 1: Write the failing MT5 modify tests**

```python
from synthetic_trader.config import LiveMode
from synthetic_trader.execution.mt5 import Mt5ModifyRequest, Mt5OrderResult, Mt5ReconcileResult, Mt5SyncResult, modify_mt5_position
from synthetic_trader.live.supervised_live import execute_supervised_mt5_modify


class Phase8Mt5ModifyTests(unittest.TestCase):
    def test_modify_mt5_position_returns_structured_result(self) -> None:
        class FakeResult:
            retcode = 10009
            order = 901
            deal = 902
            comment = "modify executed"

        class FakeModule:
            TRADE_ACTION_SLTP = 2

            def order_send(self, payload):
                self.payload = payload
                return FakeResult()

        result = modify_mt5_position(
            request=Mt5ModifyRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                stop_loss=99.5,
                take_profit=102.0,
            ),
            mt5_module=FakeModule(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 901)
```

- [ ] **Step 2: Run the modify tests to verify they fail**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8Mt5ModifyTests" -q`
Expected: `ImportError` because `Mt5ModifyRequest`, `modify_mt5_position()`, and `execute_supervised_mt5_modify()` do not exist yet

- [ ] **Step 3: Add MT5 modify request and adapter helper**

```python
# src/synthetic_trader/execution/mt5.py
@dataclass(frozen=True)
class Mt5ModifyRequest:
    symbol: str
    venue_symbol: str
    ticket: int
    stop_loss: float | None = None
    take_profit: float | None = None


def modify_mt5_position(
    *,
    request: Mt5ModifyRequest,
    mt5_module,
) -> Mt5OrderResult:
    payload = {
        "action": mt5_module.TRADE_ACTION_SLTP,
        "symbol": request.venue_symbol,
        "position": request.ticket,
        "sl": request.stop_loss,
        "tp": request.take_profit,
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

- [ ] **Step 4: Add supervised modify wrapper**

```python
# src/synthetic_trader/live/supervised_live.py
from synthetic_trader.execution.mt5 import Mt5ModifyRequest, Mt5ReconcileResult, modify_mt5_position
```

```python
# src/synthetic_trader/live/supervised_live.py
def execute_supervised_mt5_modify(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    reconcile_result: Mt5ReconcileResult,
    stop_loss: float | None,
    take_profit: float | None,
    mt5_module,
) -> Mt5OrderResult | str:
    if not readiness_ok:
        raise RuntimeError("mt5 refinement readiness failed")
    if not reconcile_result.actionable:
        raise RuntimeError("mt5 reconciliation is not actionable")
    target = next(
        position
        for position in reconcile_result.sync_result.positions
        if position.ticket == reconcile_result.target_ticket
    )
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("mt5 modify is not allowed in this mode")
    return modify_mt5_position(
        request=Mt5ModifyRequest(
            symbol=target.symbol,
            venue_symbol=target.venue_symbol,
            ticket=target.ticket,
            stop_loss=stop_loss,
            take_profit=take_profit,
        ),
        mt5_module=mt5_module,
    )
```

- [ ] **Step 5: Run the modify tests to verify they pass**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8Mt5ModifyTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/execution/mt5.py src/synthetic_trader/live/supervised_live.py tests/test_phase8_mt5_refinement.py
git commit -m "feat: add supervised mt5 modify handling"
```

## Task 3: Add Reconciliation And Modify Journaling

**Files:**
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Create: `tests/test_phase8_mt5_refinement.py`

- [ ] **Step 1: Write the failing journal tests**

```python
import json
import tempfile
from pathlib import Path

from synthetic_trader.journal.trade_journal import TradeJournal


class Phase8Mt5RefinementJournalTests(unittest.TestCase):
    def test_journal_records_reconcile_and_modify_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mt5_refinement.jsonl"
            journal = TradeJournal(path)

            journal.record_mt5_reconcile_summary(symbol="R_75", target_ticket=101, actionable=True, failures=())
            journal.record_mt5_modify_result(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                accepted=True,
                retcode=10009,
                message="modify executed",
            )

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_reconcile_summary")
        self.assertEqual(entries[1]["type"], "mt5_modify_result")
```

- [ ] **Step 2: Run the journal tests to verify they fail**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8Mt5RefinementJournalTests" -q`
Expected: `AttributeError` because the new journal helpers do not exist yet

- [ ] **Step 3: Add journal helpers**

```python
# src/synthetic_trader/journal/trade_journal.py
class TradeJournal:
    def record_mt5_reconcile_summary(
        self,
        *,
        symbol: str,
        target_ticket: int | None,
        actionable: bool,
        failures: tuple[str, ...],
    ) -> None:
        self.record_event(
            "mt5_reconcile_summary",
            {
                "symbol": symbol,
                "target_ticket": target_ticket,
                "actionable": actionable,
                "failures": list(failures),
            },
        )

    def record_mt5_modify_result(
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
            "mt5_modify_result",
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

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8Mt5RefinementJournalTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/journal/trade_journal.py tests/test_phase8_mt5_refinement.py
git commit -m "feat: add mt5 refinement journal helpers"
```

## Task 4: Add Explicit MT5 Reconcile And Modify CLI Commands

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Create: `tests/test_phase8_mt5_refinement.py`
- Modify: `tests/test_phase7_mt5_lifecycle.py`

- [ ] **Step 1: Write the failing CLI refinement tests**

```python
import contextlib
import io
from unittest.mock import patch

from synthetic_trader.execution.mt5 import Mt5OrderResult, Mt5ReconcileResult, Mt5RuntimeStatus, Mt5SyncResult


class Phase8CliRefinementTests(unittest.TestCase):
    def test_mt5_reconcile_command_prints_target_ticket(self) -> None:
        from synthetic_trader.cli import main

        output = io.StringIO()
        with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
            with patch(
                "synthetic_trader.cli.reconcile_mt5_positions",
                return_value=Mt5ReconcileResult(
                    ready=True,
                    actionable=True,
                    failures=(),
                    target_ticket=101,
                    sync_result=Mt5SyncResult(True, (), "Volatility 75 Index", ()),
                ),
            ):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "mt5-reconcile",
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
        self.assertIn("target_ticket=101", output.getvalue())
```

- [ ] **Step 2: Run the CLI refinement tests to verify they fail**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8CliRefinementTests" -q`
Expected: parser error because `mt5-reconcile` and `mt5-modify` do not exist yet

- [ ] **Step 3: Add MT5 reconcile and modify CLI commands**

```python
# src/synthetic_trader/cli.py
from synthetic_trader.execution.mt5 import Mt5ReconcileResult, reconcile_mt5_positions
from synthetic_trader.live.supervised_live import execute_supervised_mt5_modify
```

```python
# src/synthetic_trader/cli.py
mt5_reconcile = subparsers.add_parser("mt5-reconcile", help="reconcile MT5 lifecycle state")
mt5_reconcile.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
mt5_reconcile.add_argument("--ticket", type=int)
mt5_reconcile.add_argument("--mt5-server", required=True)
mt5_reconcile.add_argument("--mt5-login", required=True)
mt5_reconcile.add_argument("--mt5-password", required=True)
mt5_reconcile.add_argument("--mt5-terminal-path")
mt5_reconcile.add_argument("--mt5-symbol", required=True)

mt5_modify = subparsers.add_parser("mt5-modify", help="run supervised MT5 modify handling")
mt5_modify.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
mt5_modify.add_argument("--ticket", type=int)
mt5_modify.add_argument("--live-mode", default=LiveMode.DRY_RUN_LIVE.value, choices=[mode.value for mode in LiveMode])
mt5_modify.add_argument("--armed-live", action="store_true")
mt5_modify.add_argument("--stop-loss", type=float)
mt5_modify.add_argument("--take-profit", type=float)
mt5_modify.add_argument("--mt5-server", required=True)
mt5_modify.add_argument("--mt5-login", required=True)
mt5_modify.add_argument("--mt5-password", required=True)
mt5_modify.add_argument("--mt5-terminal-path")
mt5_modify.add_argument("--mt5-symbol", required=True)
```

- [ ] **Step 4: Wire reconcile and supervised modify flows**

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-reconcile":
    mt5_config = _build_mt5_config(args)
    reconcile_result = reconcile_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        ticket=args.ticket,
        mt5_module=_load_mt5_module(),
    )
    print(f"actionable={reconcile_result.actionable}")
    print(f"target_ticket={reconcile_result.target_ticket}")
    if reconcile_result.failures:
        print(f"reconcile_failures={','.join(reconcile_result.failures)}")
        return 1
    return 0

if args.command == "mt5-modify":
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
    if not readiness.ready:
        print(f"readiness_failures={','.join(readiness.failures)}")
        return 1
    mt5_module = _load_mt5_module()
    reconcile_result = reconcile_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        ticket=args.ticket,
        mt5_module=mt5_module,
    )
    print(f"actionable={reconcile_result.actionable}")
    print(f"target_ticket={reconcile_result.target_ticket}")
    if reconcile_result.failures:
        print(f"reconcile_failures={','.join(reconcile_result.failures)}")
        return 1
    result = execute_supervised_mt5_modify(
        mode=mode,
        readiness_ok=readiness.ready,
        reconcile_result=reconcile_result,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        mt5_module=mt5_module,
    )
    if isinstance(result, str):
        print(f"modify_result={result}")
        return 0
    print(f"modify_accepted={result.accepted}")
    print(f"order_ticket={result.order_ticket}")
    return 0
```

- [ ] **Step 5: Run the CLI refinement tests to verify they pass**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -k "Phase8CliRefinementTests" -q`
Expected: `1 passed`

- [ ] **Step 6: Keep Phase 7 lifecycle tests green**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -q`
Expected: all Phase 7 lifecycle tests still pass

- [ ] **Step 7: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase8_mt5_refinement.py tests/test_phase7_mt5_lifecycle.py
git commit -m "feat: add mt5 refinement cli commands"
```

## Task 5: Run Phase 8 Regression

**Files:**
- Modify: `tests/test_phase8_mt5_refinement.py`

- [ ] **Step 1: Add one ambiguity or missing-ticket regression if missing**

```python
class Phase8RegressionTests(unittest.TestCase):
    def test_reconcile_reports_missing_target_ticket(self) -> None:
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

        result = reconcile_mt5_positions(
            config=Mt5Config(symbol_map={"R_75": "Volatility 75 Index"}),
            symbol="R_75",
            ticket=999,
            mt5_module=FakeModule(),
        )

        self.assertFalse(result.actionable)
        self.assertIn("missing_mt5_target_ticket", result.failures)
```

- [ ] **Step 2: Run the focused Phase 8 slice**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -q`
Expected: all Phase 8 tests pass

- [ ] **Step 3: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
........................................................................
[100%]
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase8_mt5_refinement.py
git commit -m "test: validate mt5 refinement"
```

## Spec Coverage Check

- structured reconciliation state: covered by Task 1
- supervised modify logic: covered by Task 2
- refinement fail-closed rules: covered by Tasks 1, 2, and 5
- journaling for reconciliation and modify events: covered by Task 3
- explicit CLI refinement commands: covered by Task 4
- integrated regression and lifecycle safety: covered by Task 5

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task contains exact files, concrete commands, and explicit code blocks
- Each verification step states the expected failing or passing behavior directly

## Type Consistency Check

- `Mt5ReconcileResult` is the consistent reconciliation payload across adapter, supervised refinement handling, and CLI reporting
- `Mt5ModifyRequest` is the consistent MT5 modification payload used between the supervised layer and the MT5 adapter
- `reconcile_mt5_positions()` is the single reconciliation entry point
- `execute_supervised_mt5_modify()` is the single supervised modify gate above the MT5 adapter
