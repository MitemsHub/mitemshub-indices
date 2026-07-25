# Phase 9 MT5 Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add journal-backed MT5 analytics and concise CLI summaries for readiness, sync, reconciliation, close, and modify flows without changing MT5 broker behavior.

**Architecture:** Reuse the existing typed MT5 lifecycle state and command handlers as the analytics source of truth. Emit journal events directly from the real MT5 command paths, then add normalized CLI summary lines on top so operator visibility and persistent analytics stay aligned.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`typing`/`json`, current `pytest`/`unittest` suite, existing MT5 CLI surfaces, JSONL trade journal

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase9_mt5_analytics.py`
  - Focused Phase 9 tests for command-driven MT5 journal emission and CLI analytics summaries.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\journal\trade_journal.py`
  - Add any missing MT5 runtime-summary helper used by command flows.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Emit MT5 journal analytics and normalized summary lines from existing MT5 command handlers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase8_mt5_refinement.py`
  - Keep one regression proving earlier MT5 refinement behavior stays green.

## Task 1: Add MT5 Runtime Analytics Journal Helper

**Files:**
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Create: `tests/test_phase9_mt5_analytics.py`

- [ ] **Step 1: Write the failing runtime-summary journal test**

```python
import json
import tempfile
from pathlib import Path

from synthetic_trader.journal.trade_journal import TradeJournal


class Phase9Mt5JournalTests(unittest.TestCase):
    def test_journal_records_mt5_runtime_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mt5_runtime.jsonl"
            journal = TradeJournal(path)

            journal.record_mt5_runtime_summary(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ready=False,
                failures=("mt5_initialize_failed",),
            )

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_runtime_summary")
        self.assertEqual(entries[0]["failures"], ["mt5_initialize_failed"])
```

- [ ] **Step 2: Run the runtime-summary test to verify it fails**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -k "Phase9Mt5JournalTests" -q`
Expected: `AttributeError` because `record_mt5_runtime_summary()` does not exist yet

- [ ] **Step 3: Add the runtime-summary journal helper**

```python
# src/synthetic_trader/journal/trade_journal.py
class TradeJournal:
    def record_mt5_runtime_summary(
        self,
        *,
        symbol: str,
        venue_symbol: str | None,
        ready: bool,
        failures: tuple[str, ...],
    ) -> None:
        self.record_event(
            "mt5_runtime_summary",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "ready": ready,
                "failures": list(failures),
            },
        )
```

- [ ] **Step 4: Run the runtime-summary test to verify it passes**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -k "Phase9Mt5JournalTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/journal/trade_journal.py tests/test_phase9_mt5_analytics.py
git commit -m "feat: add mt5 runtime analytics journal helper"
```

## Task 2: Add Command-Driven MT5 Analytics Emission

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Create: `tests/test_phase9_mt5_analytics.py`

- [ ] **Step 1: Write the failing command-journal analytics tests**

```python
import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.execution.mt5 import Mt5OrderResult, Mt5RuntimeStatus, Mt5SyncResult


class Phase9Mt5CommandAnalyticsTests(unittest.TestCase):
    def test_mt5_live_order_writes_runtime_summary_on_readiness_failure(self) -> None:
        from synthetic_trader.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_analytics.jsonl"
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
                            "--journal",
                            str(journal_path),
                        ]
                    )

            self.assertEqual(exit_code, 1)
            entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_runtime_summary")
```

- [ ] **Step 2: Run the command-journal tests to verify they fail**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -k "Phase9Mt5CommandAnalyticsTests" -q`
Expected: parser or assertion failure because MT5 commands do not journal analytics yet

- [ ] **Step 3: Add an MT5 journal builder and wire runtime/sync/reconcile/close/modify events**

```python
# src/synthetic_trader/cli.py
def _build_mt5_journal(args: argparse.Namespace) -> TradeJournal:
    journal_path = getattr(args, "journal", None) or "journals/mt5_analytics.jsonl"
    return TradeJournal(journal_path)
```

```python
# src/synthetic_trader/cli.py
mt5_live_order.add_argument("--journal", help="optional MT5 analytics journal path")
mt5_sync.add_argument("--journal", help="optional MT5 analytics journal path")
mt5_reconcile.add_argument("--journal", help="optional MT5 analytics journal path")
mt5_close.add_argument("--journal", help="optional MT5 analytics journal path")
mt5_modify.add_argument("--journal", help="optional MT5 analytics journal path")
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-live-order":
    journal = _build_mt5_journal(args)
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
    journal.record_mt5_runtime_summary(
        symbol=args.symbol,
        venue_symbol=runtime_status.venue_symbol,
        ready=runtime_status.ready,
        failures=runtime_status.failures,
    )
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-sync":
    journal = _build_mt5_journal(args)
    mt5_config = _build_mt5_config(args)
    sync_result = synchronize_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        mt5_module=_load_mt5_module(),
    )
    journal.record_mt5_sync_summary(
        symbol=args.symbol,
        venue_symbol=sync_result.venue_symbol,
        positions=len(sync_result.positions),
        failures=sync_result.failures,
    )
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-reconcile":
    journal = _build_mt5_journal(args)
    mt5_config = _build_mt5_config(args)
    reconcile_result = reconcile_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        ticket=args.ticket,
        mt5_module=_load_mt5_module(),
    )
    journal.record_mt5_reconcile_summary(
        symbol=args.symbol,
        target_ticket=reconcile_result.target_ticket,
        actionable=reconcile_result.actionable,
        failures=reconcile_result.failures,
    )
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-close":
    journal = _build_mt5_journal(args)
    mode = LiveMode(args.live_mode)
    mt5_config = _build_mt5_config(args)
    runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
    mt5_module = _load_mt5_module()
    sync_result = synchronize_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        mt5_module=mt5_module,
    )
    journal.record_mt5_runtime_summary(
        symbol=args.symbol,
        venue_symbol=runtime_status.venue_symbol,
        ready=runtime_status.ready,
        failures=runtime_status.failures,
    )
    journal.record_mt5_sync_summary(
        symbol=args.symbol,
        venue_symbol=sync_result.venue_symbol,
        positions=len(sync_result.positions),
        failures=sync_result.failures,
    )
    if not isinstance(result, str):
        journal.record_mt5_close_result(
            symbol=args.symbol,
            venue_symbol=result.venue_symbol,
            ticket=args.ticket or sync_result.positions[0].ticket,
            accepted=result.accepted,
            retcode=result.retcode,
            message=result.message,
        )
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-modify":
    journal = _build_mt5_journal(args)
    mode = LiveMode(args.live_mode)
    mt5_config = _build_mt5_config(args)
    runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
    mt5_module = _load_mt5_module()
    reconcile_result = reconcile_mt5_positions(
        config=mt5_config,
        symbol=args.symbol,
        ticket=args.ticket,
        mt5_module=mt5_module,
    )
    journal.record_mt5_runtime_summary(
        symbol=args.symbol,
        venue_symbol=runtime_status.venue_symbol,
        ready=runtime_status.ready,
        failures=runtime_status.failures,
    )
    journal.record_mt5_reconcile_summary(
        symbol=args.symbol,
        target_ticket=reconcile_result.target_ticket,
        actionable=reconcile_result.actionable,
        failures=reconcile_result.failures,
    )
    if not isinstance(result, str):
        journal.record_mt5_modify_result(
            symbol=args.symbol,
            venue_symbol=result.venue_symbol,
            ticket=reconcile_result.target_ticket or 0,
            accepted=result.accepted,
            retcode=result.retcode,
            message=result.message,
        )
```

- [ ] **Step 4: Run the command-journal tests to verify they pass**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -k "Phase9Mt5CommandAnalyticsTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase9_mt5_analytics.py
git commit -m "feat: wire mt5 command analytics to journal"
```

## Task 3: Add Normalized CLI MT5 Summary Lines

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Create: `tests/test_phase9_mt5_analytics.py`

- [ ] **Step 1: Write the failing CLI summary tests**

```python
import contextlib
import io
from unittest.mock import patch

from synthetic_trader.execution.mt5 import Mt5ReconcileResult, Mt5RuntimeStatus, Mt5SyncResult


class Phase9Mt5SummaryTests(unittest.TestCase):
    def test_mt5_reconcile_prints_normalized_summary_lines(self) -> None:
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
        self.assertIn("mt5_command=mt5-reconcile", output.getvalue())
        self.assertIn("mt5_actionable=True", output.getvalue())
```

- [ ] **Step 2: Run the CLI summary tests to verify they fail**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -k "Phase9Mt5SummaryTests" -q`
Expected: assertion failure because normalized MT5 summary lines do not exist yet

- [ ] **Step 3: Add a small MT5 summary printer**

```python
# src/synthetic_trader/cli.py
def _print_mt5_summary(command: str, **fields: object) -> None:
    print(f"mt5_command={command}")
    for key, value in fields.items():
        print(f"mt5_{key}={value}")
```

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
    _print_mt5_summary(
        "mt5-reconcile",
        actionable=reconcile_result.actionable,
        target_ticket=reconcile_result.target_ticket,
        failures=",".join(reconcile_result.failures) if reconcile_result.failures else "",
    )
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-sync":
    _print_mt5_summary(
        "mt5-sync",
        positions=len(sync_result.positions),
        failures=",".join(sync_result.failures) if sync_result.failures else "",
    )
```

```python
# src/synthetic_trader/cli.py
if args.command == "mt5-live-order":
    _print_mt5_summary(
        "mt5-live-order",
        readiness_ok=readiness.ready,
        venue_symbol=runtime_status.venue_symbol,
        failures=",".join(readiness.failures) if readiness.failures else "",
    )
```

- [ ] **Step 4: Run the CLI summary tests to verify they pass**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -k "Phase9Mt5SummaryTests" -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py tests/test_phase9_mt5_analytics.py
git commit -m "feat: add mt5 analytics summary lines"
```

## Task 4: Keep Earlier MT5 Lifecycle Flows Green

**Files:**
- Modify: `tests/test_phase8_mt5_refinement.py`

- [ ] **Step 1: Add one regression if missing for journal-enabled command flow**

```python
class Phase9RegressionTests(unittest.TestCase):
    def test_mt5_modify_still_reports_actionable_result(self) -> None:
        from synthetic_trader.cli import main
        output = io.StringIO()
        with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
            with patch(
                "synthetic_trader.cli.evaluate_mt5_runtime",
                return_value=Mt5RuntimeStatus(True, (), "Volatility 75 Index"),
            ):
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
                    with patch(
                        "synthetic_trader.cli.execute_supervised_mt5_modify",
                        return_value=Mt5OrderResult(True, 901, 902, 10009, "modify executed", "Volatility 75 Index"),
                    ):
                        with contextlib.redirect_stdout(output):
                            main(
                                [
                                    "mt5-modify",
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
                                    "--stop-loss",
                                    "99.5",
                                ]
                            )
        self.assertIn("modify_accepted=True", output.getvalue())
```

- [ ] **Step 2: Run Phase 8 refinement tests**

Run: `python -m pytest tests/test_phase8_mt5_refinement.py -q`
Expected: all Phase 8 refinement tests still pass

- [ ] **Step 3: Run Phase 7 lifecycle tests**

Run: `python -m pytest tests/test_phase7_mt5_lifecycle.py -q`
Expected: all Phase 7 lifecycle tests still pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase8_mt5_refinement.py
git commit -m "test: preserve mt5 lifecycle regressions"
```

## Task 5: Run Phase 9 Regression

**Files:**
- Modify: `tests/test_phase9_mt5_analytics.py`

- [ ] **Step 1: Add one combined analytics regression if missing**

```python
class Phase9CombinedAnalyticsTests(unittest.TestCase):
    def test_mt5_sync_writes_journal_and_prints_summary(self) -> None:
        from synthetic_trader.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_analytics.jsonl"
            output = io.StringIO()
            with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                with patch(
                    "synthetic_trader.cli.synchronize_mt5_positions",
                    return_value=Mt5SyncResult(True, (), "Volatility 75 Index", ()),
                ):
                    with contextlib.redirect_stdout(output):
                        main(
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
                                "--journal",
                                str(journal_path),
                            ]
                        )
        self.assertIn("mt5_command=mt5-sync", output.getvalue())
```

- [ ] **Step 2: Run the focused Phase 9 suite**

Run: `python -m pytest tests/test_phase9_mt5_analytics.py -q`
Expected: all Phase 9 analytics tests pass

- [ ] **Step 3: Run the full project suite**

Run: `python -m pytest tests -q`
Expected:

```text
........................................................................
[100%]
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase9_mt5_analytics.py
git commit -m "test: validate mt5 analytics"
```

## Spec Coverage Check

- journal-backed MT5 analytics: covered by Tasks 1 and 2
- concise CLI MT5 summaries: covered by Task 3
- readiness, sync, reconciliation, close, and modify analytics coverage: covered by Tasks 2 and 5
- real command-flow journal emission: covered by Task 2
- regression safety for earlier MT5 lifecycle flows: covered by Task 4

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Each task includes exact files, concrete commands, and explicit code blocks
- Each verification step states the expected failing or passing behavior directly

## Type Consistency Check

- `TradeJournal` remains the single analytics sink for persistent MT5 command events
- `_build_mt5_journal()` is the consistent CLI entry point for MT5 analytics emission
- `_print_mt5_summary()` is the consistent CLI summary output helper
- existing typed MT5 lifecycle state remains the source of truth for analytics rather than duplicated summary-only structures
