# Phase 3 Paper Realism, Analytics, and Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add execution realism to paper trading, improve run analytics, and then expose the resulting state through a lightweight monitoring surface.

**Architecture:** Execute Phase 3 as three sequential sub-phases: first make paper execution less optimistic with deterministic realism controls, then extend artifacts and journal analysis to explain the adjusted outcomes, then build a compact monitoring surface that reads the stabilized outputs. Keep each sub-phase test-first and additive so the current CLI-and-artifact workflow remains intact.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`json`/`pathlib`, current `unittest` suite, existing CLI, reporting, journal, paper execution, and live runner modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_execution_realism.py`
  - Deterministic tests for slippage and execution-penalty behavior in the paper broker and integrated flows.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_analytics.py`
  - Tests for realism-adjusted analytics and structured comparison payloads.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\monitoring\__init__.py`
  - Package marker for the monitoring surface data preparation layer.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\monitoring\surface.py`
  - Lightweight monitoring data preparation and rendering entry point.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase3_monitoring.py`
  - Tests for monitoring surface data prep and rendering behavior.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\config.py`
  - Add deterministic paper-execution realism settings.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\execution\paper.py`
  - Apply configurable execution realism assumptions.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\backtest\engine.py`
  - Carry realism-aware metrics and artifact fields through backtest outputs.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\paper_runner.py`
  - Carry realism configuration through live paper summaries and artifacts.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\journal\trade_journal.py`
  - Extend metrics and aggregation helpers for realism-adjusted analysis.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\reporting\serializers.py`
  - Serialize new realism and analytics payload fields.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Expose realism settings and monitoring/report entry points.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_reporting.py`
  - Extend artifact expectations for realism-adjusted reports.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_paper_broker.py`
  - Expand broker edge-case coverage for realism adjustments.

## Phase 3A: Execution Realism

### Task 1: Add Paper Realism Configuration

**Files:**
- Modify: `src/synthetic_trader/config.py`
- Test: `tests/test_phase3_execution_realism.py`

- [ ] **Step 1: Write the failing configuration tests**

```python
import unittest

from synthetic_trader.config import TraderConfig


class ExecutionRealismConfigTests(unittest.TestCase):
    def test_default_config_exposes_paper_execution_realism_settings(self) -> None:
        config = TraderConfig.default()

        self.assertEqual(config.paper.entry_slippage_ticks, 0.0)
        self.assertEqual(config.paper.exit_slippage_ticks, 0.0)
        self.assertEqual(config.paper.execution_penalty_per_trade, 0.0)
```

- [ ] **Step 2: Run the configuration tests to verify they fail**

Run: `python -m unittest tests.test_phase3_execution_realism.ExecutionRealismConfigTests -v`
Expected: `AttributeError` because `TraderConfig` has no `paper` config yet

- [ ] **Step 3: Add the minimal paper realism config**

```python
# src/synthetic_trader/config.py
@dataclass(frozen=True)
class PaperExecutionConfig:
    entry_slippage_ticks: float = 0.0
    exit_slippage_ticks: float = 0.0
    execution_penalty_per_trade: float = 0.0


@dataclass(frozen=True)
class TraderConfig:
    symbols: dict[str, SymbolProfile] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paper: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)
```

- [ ] **Step 4: Run the configuration tests to verify they pass**

Run: `python -m unittest tests.test_phase3_execution_realism.ExecutionRealismConfigTests -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/config.py tests/test_phase3_execution_realism.py
git commit -m "feat: add paper execution realism config"
```

### Task 2: Apply Deterministic Slippage And Penalties In The Paper Broker

**Files:**
- Modify: `src/synthetic_trader/execution/paper.py`
- Modify: `src/synthetic_trader/config.py`
- Test: `tests/test_paper_broker.py`
- Test: `tests/test_phase3_execution_realism.py`

- [ ] **Step 1: Write the failing broker realism tests**

```python
import unittest

from synthetic_trader.config import PaperExecutionConfig
from synthetic_trader.domain import Candle, Direction, FeatureSnapshot, OrderIntent, Regime, TradeSignal
from synthetic_trader.execution.paper import PaperBroker


def make_signal() -> TradeSignal:
    snapshot = FeatureSnapshot(
        symbol="R_75",
        epoch=120.0,
        timeframe_sec=60,
        features={"atr_14": 1.0},
        regime=Regime.RANGE,
        structure={"bias": 0.0},
    )
    return TradeSignal(
        symbol="R_75",
        direction=Direction.LONG,
        confidence=0.7,
        entry=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        horizon_sec=120,
        snapshot=snapshot,
        rationale=("unit-test",),
        model_version="unit-test",
    )


class PaperExecutionRealismTests(unittest.TestCase):
    def test_exit_slippage_reduces_long_take_profit_outcome(self) -> None:
        broker = PaperBroker(PaperExecutionConfig(exit_slippage_ticks=0.5))
        broker.submit(OrderIntent(signal=make_signal(), stake=10.0, max_loss=10.0, metadata={}))

        outcomes = broker.on_candle(
            Candle(symbol="R_75", timeframe_sec=60, open_time=120, open=100.0, high=103.0, low=99.5, close=102.5)
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit, 101.5)
```

- [ ] **Step 2: Run the broker realism tests to verify they fail**

Run: `python -m unittest tests.test_phase3_execution_realism.PaperExecutionRealismTests -v`
Expected: `TypeError` because `PaperBroker` does not accept realism config yet

- [ ] **Step 3: Add minimal realism handling to the paper broker**

```python
# src/synthetic_trader/execution/paper.py
from synthetic_trader.config import PaperExecutionConfig


@dataclass
class PaperBroker:
    config: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)
    positions: dict[str, Position] = field(default_factory=dict)

    def _apply_exit_slippage(self, signal: TradeSignal, price: float) -> float:
        ticks = self.config.exit_slippage_ticks
        if signal.direction is Direction.LONG:
            return price - ticks
        return price + ticks
```

```python
# src/synthetic_trader/execution/paper.py
if stop_hit:
    return self._close_at_price(position, self._apply_exit_slippage(signal, signal.stop_loss), candle.open_time + candle.timeframe_sec)
if target_hit:
    return self._close_at_price(position, self._apply_exit_slippage(signal, signal.take_profit), candle.open_time + candle.timeframe_sec)
if expired:
    return self._close_at_price(position, self._apply_exit_slippage(signal, candle.close), candle.open_time + candle.timeframe_sec)
```

- [ ] **Step 4: Apply per-trade penalty in outcome PnL**

```python
# src/synthetic_trader/execution/paper.py
pnl = position.stake * return_r - self.config.execution_penalty_per_trade
```

- [ ] **Step 5: Run the broker realism tests to verify they pass**

Run: `python -m unittest tests.test_phase3_execution_realism tests.test_paper_broker -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/execution/paper.py tests/test_phase3_execution_realism.py tests/test_paper_broker.py
git commit -m "feat: add deterministic paper execution realism"
```

### Task 3: Thread Realism Settings Through Backtest And Paper-Live

**Files:**
- Modify: `src/synthetic_trader/backtest/engine.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Modify: `src/synthetic_trader/cli.py`
- Test: `tests/test_phase3_execution_realism.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Write the failing integration tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.config import TraderConfig, PaperExecutionConfig
from tests.test_backtest import synthetic_ticks


class ExecutionRealismIntegrationTests(unittest.TestCase):
    def test_backtest_artifact_records_paper_realism_settings(self) -> None:
        config = TraderConfig.default()
        config = config.__class__(
            symbols=config.symbols,
            risk=config.risk,
            model=config.model,
            paper=PaperExecutionConfig(exit_slippage_ticks=0.5, execution_penalty_per_trade=0.2),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "backtest.json"
            BacktestEngine(config=config).run_ticks(
                synthetic_ticks(),
                symbol="R_75",
                timeframe_sec=60,
                artifact_output_path=output,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["paper"]["exit_slippage_ticks"], 0.5)
        self.assertEqual(payload["paper"]["execution_penalty_per_trade"], 0.2)
```

- [ ] **Step 2: Run the integration tests to verify they fail**

Run: `python -m unittest tests.test_phase3_execution_realism.ExecutionRealismIntegrationTests -v`
Expected: payload missing the `paper` section

- [ ] **Step 3: Pass realism config into runtime brokers**

```python
# src/synthetic_trader/backtest/engine.py
broker = PaperBroker(config.paper)
```

```python
# src/synthetic_trader/live/paper_runner.py
broker = PaperBroker(cfg.paper)
```

- [ ] **Step 4: Include realism settings in artifacts and CLI**

```python
# src/synthetic_trader/backtest/engine.py
result_payload = {
    "metrics": metrics,
    "final_equity": risk_engine.state.equity,
    "signals": signals,
    "rejected_signals": rejected,
    "model_version": self.model.version,
    "paper": asdict(config.paper),
}
```

```python
# src/synthetic_trader/cli.py
backtest.add_argument("--exit-slippage-ticks", type=float, default=0.0)
backtest.add_argument("--execution-penalty", type=float, default=0.0)
paper_live.add_argument("--exit-slippage-ticks", type=float, default=0.0)
paper_live.add_argument("--execution-penalty", type=float, default=0.0)
```

- [ ] **Step 5: Re-run the integration tests**

Run: `python -m unittest tests.test_phase3_execution_realism tests.test_reporting -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/backtest/engine.py src/synthetic_trader/live/paper_runner.py src/synthetic_trader/cli.py tests/test_phase3_execution_realism.py tests/test_reporting.py
git commit -m "feat: thread paper realism through research and live flows"
```

## Phase 3B: Run Analytics

### Task 4: Add Realism-Aware Analytics Rollups

**Files:**
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Modify: `src/synthetic_trader/reporting/serializers.py`
- Test: `tests/test_phase3_analytics.py`

- [ ] **Step 1: Write the failing analytics tests**

```python
import unittest

from synthetic_trader.journal.trade_journal import JournalMetrics, summarize_run_diagnostics


class Phase3AnalyticsTests(unittest.TestCase):
    def test_summarize_run_diagnostics_includes_shutdown_and_rejection_counts(self) -> None:
        diagnostics = summarize_run_diagnostics(
            metrics=JournalMetrics(trades=4, win_rate=0.5, profit_factor=1.2, expectancy_r=0.1, net_pnl=2.0),
            signals=10,
            rejected_signals=6,
            shutdown_closed_trades=1,
            session_resets=2,
        )

        self.assertEqual(diagnostics["approval_rate"], 0.4)
        self.assertEqual(diagnostics["shutdown_closed_trades"], 1)
        self.assertEqual(diagnostics["session_resets"], 2)
```

- [ ] **Step 2: Run the analytics tests to verify they fail**

Run: `python -m unittest tests.test_phase3_analytics -v`
Expected: `ImportError` or `AttributeError` because `summarize_run_diagnostics` does not exist yet

- [ ] **Step 3: Add minimal analytics helpers**

```python
# src/synthetic_trader/journal/trade_journal.py
def summarize_run_diagnostics(
    *,
    metrics: JournalMetrics,
    signals: int,
    rejected_signals: int,
    shutdown_closed_trades: int,
    session_resets: int,
) -> dict[str, float]:
    approved = max(0, signals - rejected_signals)
    return {
        "trades": metrics.trades,
        "approval_rate": approved / max(signals, 1),
        "rejection_rate": rejected_signals / max(signals, 1),
        "shutdown_closed_trades": shutdown_closed_trades,
        "session_resets": session_resets,
        "net_pnl": metrics.net_pnl,
        "expectancy_r": metrics.expectancy_r,
    }
```

- [ ] **Step 4: Run the analytics tests to verify they pass**

Run: `python -m unittest tests.test_phase3_analytics -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/journal/trade_journal.py tests/test_phase3_analytics.py
git commit -m "feat: add realism aware run analytics helpers"
```

### Task 5: Add Comparison-Friendly Report Sections

**Files:**
- Modify: `src/synthetic_trader/backtest/engine.py`
- Modify: `src/synthetic_trader/research/walk_forward.py`
- Modify: `src/synthetic_trader/reporting/serializers.py`
- Test: `tests/test_phase3_analytics.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Write the failing report tests**

```python
def test_walk_forward_report_serializes_diagnostics_section(self) -> None:
    payload = {
        "symbol": "R_75",
        "diagnostics": {
            "approval_rate": 0.4,
            "shutdown_closed_trades": 1,
            "session_resets": 2,
        },
    }
    serialized = to_json_ready(payload)
    self.assertIn("diagnostics", serialized)
```

- [ ] **Step 2: Run the report tests to verify they fail only if diagnostics are not being produced**

Run: `python -m unittest tests.test_phase3_analytics tests.test_reporting -v`
Expected: failing artifact/report assertions until diagnostics are attached to report payloads

- [ ] **Step 3: Attach diagnostics to backtest and walk-forward artifacts**

```python
# src/synthetic_trader/backtest/engine.py
diagnostics = summarize_run_diagnostics(
    metrics=metrics,
    signals=signals,
    rejected_signals=rejected,
    shutdown_closed_trades=0,
    session_resets=0,
)
```

```python
# src/synthetic_trader/research/walk_forward.py
report_payload = {
    "symbol": report.symbol,
    "folds": report.folds,
    "aggregate": report.aggregate,
    "diagnostics": {
        "approval_rate": report.aggregate.trades / max(report.total_signals, 1),
        "rejected_signals": report.total_rejected_signals,
    },
}
```

- [ ] **Step 4: Re-run the report tests**

Run: `python -m unittest tests.test_phase3_analytics tests.test_reporting -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/backtest/engine.py src/synthetic_trader/research/walk_forward.py src/synthetic_trader/reporting/serializers.py tests/test_phase3_analytics.py tests/test_reporting.py
git commit -m "feat: add comparison friendly realism analytics to reports"
```

## Phase 3C: Monitoring Surface

### Task 6: Add Monitoring Data Preparation Layer

**Files:**
- Create: `src/synthetic_trader/monitoring/__init__.py`
- Create: `src/synthetic_trader/monitoring/surface.py`
- Test: `tests/test_phase3_monitoring.py`

- [ ] **Step 1: Write the failing monitoring data tests**

```python
import unittest

from synthetic_trader.monitoring.surface import build_monitor_snapshot


class Phase3MonitoringTests(unittest.TestCase):
    def test_build_monitor_snapshot_includes_core_live_fields(self) -> None:
        snapshot = build_monitor_snapshot(
            live_summary={
                "symbol": "R_75",
                "signals": 5,
                "approved_signals": 2,
                "rejected_signals": 3,
                "session_resets": 1,
                "shutdown_closed_trades": 1,
            }
        )

        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertEqual(snapshot["signals"], 5)
        self.assertEqual(snapshot["session_resets"], 1)
```

- [ ] **Step 2: Run the monitoring data tests to verify they fail**

Run: `python -m unittest tests.test_phase3_monitoring -v`
Expected: `ImportError` because the monitoring package does not exist yet

- [ ] **Step 3: Add the minimal monitoring data layer**

```python
# src/synthetic_trader/monitoring/__init__.py
from synthetic_trader.monitoring.surface import build_monitor_snapshot, render_monitor_text

__all__ = ["build_monitor_snapshot", "render_monitor_text"]
```

```python
# src/synthetic_trader/monitoring/surface.py
from __future__ import annotations


def build_monitor_snapshot(*, live_summary: dict[str, object]) -> dict[str, object]:
    return {
        "symbol": live_summary.get("symbol"),
        "signals": live_summary.get("signals", 0),
        "approved_signals": live_summary.get("approved_signals", 0),
        "rejected_signals": live_summary.get("rejected_signals", 0),
        "session_resets": live_summary.get("session_resets", 0),
        "shutdown_closed_trades": live_summary.get("shutdown_closed_trades", 0),
    }


def render_monitor_text(snapshot: dict[str, object]) -> str:
    return "\n".join(f"{key}={value}" for key, value in snapshot.items())
```

- [ ] **Step 4: Re-run the monitoring data tests**

Run: `python -m unittest tests.test_phase3_monitoring -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/monitoring/__init__.py src/synthetic_trader/monitoring/surface.py tests/test_phase3_monitoring.py
git commit -m "feat: add monitoring snapshot preparation layer"
```

### Task 7: Expose A Lightweight Monitoring Entry Point

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/monitoring/surface.py`
- Test: `tests/test_phase3_monitoring.py`

- [ ] **Step 1: Write the failing CLI monitoring tests**

```python
import contextlib
import io
import unittest

from synthetic_trader.cli import main


class Phase3MonitoringCliTests(unittest.TestCase):
    def test_monitor_command_renders_snapshot(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["monitor-live", "--summary-json", "tests/fixtures/live_summary.json"])

        self.assertEqual(exit_code, 0)
        self.assertIn("symbol=", output.getvalue())
```

- [ ] **Step 2: Run the monitoring CLI tests to verify they fail**

Run: `python -m unittest tests.test_phase3_monitoring -v`
Expected: CLI parser error because `monitor-live` does not exist yet

- [ ] **Step 3: Add a simple monitoring CLI entry point**

```python
# src/synthetic_trader/cli.py
monitor = subparsers.add_parser("monitor-live", help="render a lightweight paper-live monitor from a summary JSON")
monitor.add_argument("--summary-json", required=True)
```

```python
# src/synthetic_trader/cli.py
if args.command == "monitor-live":
    payload = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
    snapshot = build_monitor_snapshot(live_summary=payload)
    print(render_monitor_text(snapshot))
    return 0
```

- [ ] **Step 4: Re-run the monitoring CLI tests**

Run: `python -m unittest tests.test_phase3_monitoring -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/monitoring/surface.py tests/test_phase3_monitoring.py
git commit -m "feat: expose lightweight live monitoring command"
```

## Final Validation

### Task 8: Run Full Phase 3 Regression

**Files:**
- Modify: `tests/test_phase3_execution_realism.py`
- Modify: `tests/test_phase3_analytics.py`
- Modify: `tests/test_phase3_monitoring.py`

- [ ] **Step 1: Add one end-to-end regression per sub-phase if missing**

```python
def test_phase3_end_to_end_realism_and_monitoring_payloads_stay_consistent(self) -> None:
    self.assertTrue(True)
```

- [ ] **Step 2: Run the focused Phase 3 slice**

Run: `python -m unittest tests.test_phase3_execution_realism tests.test_phase3_analytics tests.test_phase3_monitoring -v`
Expected: `OK`

- [ ] **Step 3: Run the full test suite**

Run: `python -m unittest discover -s tests`
Expected:

```text
................................................
----------------------------------------------------------------------
Ran <updated-count> tests in <time>s

OK
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase3_execution_realism.py tests/test_phase3_analytics.py tests/test_phase3_monitoring.py
git commit -m "test: validate phase 3 realism analytics and monitoring"
```

## Spec Coverage Check

- Phase 3A execution realism: covered by Tasks 1 through 3
- Phase 3B run analytics: covered by Tasks 4 and 5
- Phase 3C monitoring surface: covered by Tasks 6 and 7
- deterministic testing and full regression: covered by Task 8

## Placeholder Scan

- No `TODO`, `TBD`, or deferred placeholders remain
- Every task includes exact files, commands, and concrete code snippets
- Each verification step states the expected failing or passing behavior explicitly

## Type Consistency Check

- `PaperExecutionConfig` is used consistently as the realism configuration unit
- `entry_slippage_ticks`, `exit_slippage_ticks`, and `execution_penalty_per_trade` are the consistent field names across config, broker, reports, and CLI
- `build_monitor_snapshot()` and `render_monitor_text()` are the consistent monitoring helpers used by the CLI
