# Phase 1 Research Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make research runs durable, auditable, and reproducible before expanding paper-trading realism or supervised live execution.

**Architecture:** Keep the existing CLI-centered trading engine intact and add a thin reporting and persistence layer around it. Extend current backtest, walk-forward, journal, and model modules with additive interfaces so the system can emit structured artifacts, preserve model state, and explain both approved and rejected decisions.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`json`/`pathlib`, existing `unittest` test suite, existing CLI and domain modules

---

## File Structure

### Files To Create

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\reporting\__init__.py`
  - Package marker for report serialization helpers.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\reporting\serializers.py`
  - JSON-friendly conversion helpers for dataclasses and nested report objects.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_reporting.py`
  - Focused tests for serializer output and saved artifact payloads.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_trade_journal.py`
  - Tests for signal, rejection, outcome, and event persistence.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_paper_broker.py`
  - Tests for stop/target ambiguity, expiry, and force-close execution paths.

### Files To Modify

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\backtest\engine.py`
  - Add optional artifact output and event capture hooks without changing the core loop.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\research\walk_forward.py`
  - Add JSON-friendly report export support and richer fold metadata handling.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\journal\trade_journal.py`
  - Extend journaling to persist rejected decisions and generic run events.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\models\online.py`
  - Add lightweight metadata support around model persistence.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\cli.py`
  - Add CLI options for model load/save and report output paths.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_walk_forward.py`
  - Upgrade assertions from smoke-only checks to fold and aggregate correctness checks.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_backtest.py`
  - Add assertions for event counts and artifact-oriented behavior.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_risk_engine.py`
  - Add risk reset and state-transition checks.

## Task 1: Add Serialization Helpers And Artifact Output

**Files:**
- Create: `src/synthetic_trader/reporting/__init__.py`
- Create: `src/synthetic_trader/reporting/serializers.py`
- Modify: `src/synthetic_trader/backtest/engine.py`
- Modify: `src/synthetic_trader/research/walk_forward.py`
- Test: `tests/test_reporting.py`

- [ ] **Step 1: Write the failing serializer tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.research.walk_forward import run_walk_forward
from synthetic_trader.reporting.serializers import to_json_ready
from tests.test_backtest import synthetic_ticks


class ReportingTests(unittest.TestCase):
    def test_to_json_ready_handles_nested_dataclasses(self) -> None:
        report = run_walk_forward(
            ticks=synthetic_ticks(candles=270),
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        payload = to_json_ready(report)

        self.assertEqual(payload["symbol"], "R_75")
        self.assertIn("folds", payload)
        self.assertIn("aggregate", payload)

    def test_backtest_can_write_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "backtest.json"
            result = BacktestEngine().run_ticks(
                synthetic_ticks(),
                symbol="R_75",
                timeframe_sec=60,
                artifact_output_path=output_path,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["final_equity"], result.final_equity)
        self.assertIn("metrics", payload)
```

- [ ] **Step 2: Run the reporting tests to verify they fail**

Run: `python -m unittest tests.test_reporting -v`
Expected: `ModuleNotFoundError` for `synthetic_trader.reporting` or `TypeError` because `artifact_output_path` is not implemented yet

- [ ] **Step 3: Write the minimal reporting package**

```python
# src/synthetic_trader/reporting/__init__.py
from synthetic_trader.reporting.serializers import dump_json_file, to_json_ready

__all__ = ["dump_json_file", "to_json_ready"]
```

```python
# src/synthetic_trader/reporting/serializers.py
from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from pathlib import Path


def to_json_ready(value):
    if is_dataclass(value):
        return to_json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_ready(item) for item in value]
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        if math.isnan(value):
            return None
    return value


def dump_json_file(path: str | Path, payload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(to_json_ready(payload), indent=2, sort_keys=True), encoding="utf-8")
```

- [ ] **Step 4: Extend backtest and walk-forward to emit artifacts**

```python
# src/synthetic_trader/backtest/engine.py
from synthetic_trader.reporting.serializers import dump_json_file

@dataclass(frozen=True)
class BacktestResult:
    metrics: JournalMetrics
    final_equity: float
    signals: int
    rejected_signals: int
    model_version: str

def run_ticks(
    self,
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int | None = None,
    higher_timeframe_sec: int | None = None,
    learn: bool = True,
    artifact_output_path: str | Path | None = None,
) -> BacktestResult:
    ...
    result = BacktestResult(
        metrics=metrics,
        final_equity=risk_engine.state.equity,
        signals=signals,
        rejected_signals=rejected,
        model_version=self.model.version,
    )
    if artifact_output_path is not None:
        dump_json_file(artifact_output_path, result)
    return result
```

```python
# src/synthetic_trader/research/walk_forward.py
from pathlib import Path
from synthetic_trader.reporting.serializers import dump_json_file

def save_walk_forward_report(report: WalkForwardReport, output_path: str | Path) -> None:
    dump_json_file(output_path, report)
```

- [ ] **Step 5: Run the reporting tests to verify they pass**

Run: `python -m unittest tests.test_reporting -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/reporting/__init__.py src/synthetic_trader/reporting/serializers.py src/synthetic_trader/backtest/engine.py src/synthetic_trader/research/walk_forward.py tests/test_reporting.py
git commit -m "feat: add structured research artifact outputs"
```

## Task 2: Add Model Load And Save Support To Research Commands

**Files:**
- Modify: `src/synthetic_trader/models/online.py`
- Modify: `src/synthetic_trader/backtest/engine.py`
- Modify: `src/synthetic_trader/research/walk_forward.py`
- Modify: `src/synthetic_trader/cli.py`
- Test: `tests/test_online_model.py`

- [ ] **Step 1: Write the failing model persistence tests**

```python
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.models.online import OnlineLogisticModel


class OnlineModelTests(unittest.TestCase):
    def test_model_save_and_load_round_trip_preserves_weights(self) -> None:
        model = OnlineLogisticModel()
        model.update({"atr_ratio": 1.2, "structure_bias": 0.5}, label=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            model.save(path, metadata={"symbol": "R_75", "source": "unit-test"})
            loaded = OnlineLogisticModel.load(path)

        self.assertEqual(loaded.weights, model.weights)
        self.assertEqual(loaded.bias, model.bias)
        self.assertEqual(loaded.metadata["symbol"], "R_75")
```

- [ ] **Step 2: Run the model tests to verify they fail**

Run: `python -m unittest tests.test_online_model -v`
Expected: `TypeError` because `metadata` is not supported yet or `AttributeError` because `metadata` is not stored on the model

- [ ] **Step 3: Extend the online model persistence contract**

```python
# src/synthetic_trader/models/online.py
@dataclass
class OnlineLogisticModel:
    config: ModelConfig = field(default_factory=ModelConfig)
    weights: dict[str, float] = field(default_factory=dict)
    bias: float = 0.0
    updates: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    def save(self, path: str | Path, metadata: dict[str, str] | None = None) -> None:
        payload = {
            "config": asdict(self.config),
            "weights": self.weights,
            "bias": self.bias,
            "updates": self.updates,
            "metadata": dict(self.metadata) | dict(metadata or {}),
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "OnlineLogisticModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            config=ModelConfig(**payload["config"]),
            weights={str(key): float(value) for key, value in payload["weights"].items()},
            bias=float(payload["bias"]),
            updates=int(payload["updates"]),
            metadata={str(key): str(value) for key, value in payload.get("metadata", {}).items()},
        )
```

- [ ] **Step 4: Add CLI plumbing for model load and save**

```python
# src/synthetic_trader/cli.py
backtest_parser.add_argument("--model-load", help="load model state from JSON before the run")
backtest_parser.add_argument("--model-save", help="save model state to JSON after the run")
walk_forward_parser.add_argument("--model-load", help="seed the model from a saved JSON artifact")
walk_forward_parser.add_argument("--model-save", help="save the final trained model after the run")
```

```python
# src/synthetic_trader/cli.py
if args.command == "backtest":
    model = OnlineLogisticModel.load(args.model_load) if args.model_load else None
    engine = BacktestEngine(model=model)
    result = engine.run_ticks(...)
    if args.model_save:
        engine.model.save(args.model_save, metadata={"symbol": args.symbol, "command": "backtest"})
```

- [ ] **Step 5: Run the persistence tests and focused CLI command tests**

Run: `python -m unittest tests.test_online_model -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/models/online.py src/synthetic_trader/cli.py tests/test_online_model.py
git commit -m "feat: add model persistence workflow support"
```

## Task 3: Journal Approved Signals, Rejections, And Run Events

**Files:**
- Modify: `src/synthetic_trader/journal/trade_journal.py`
- Modify: `src/synthetic_trader/backtest/engine.py`
- Modify: `src/synthetic_trader/live/paper_runner.py`
- Test: `tests/test_trade_journal.py`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing journal tests**

```python
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.journal.trade_journal import TradeJournal


class TradeJournalTests(unittest.TestCase):
    def test_journal_records_rejected_signal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = TradeJournal(Path(tmpdir) / "journal.jsonl")
            journal.record_rejection(
                symbol="R_75",
                epoch=123.0,
                reasons=("confidence too low", "risk veto"),
                model_version="online-logistic-v1.0",
                confidence=0.41,
            )
            lines = journal.path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        self.assertIn('"type": "rejection"', lines[0])
```

- [ ] **Step 2: Run the journal tests to verify they fail**

Run: `python -m unittest tests.test_trade_journal -v`
Expected: `AttributeError` because `record_rejection` does not exist yet

- [ ] **Step 3: Extend the journal API**

```python
# src/synthetic_trader/journal/trade_journal.py
def record_rejection(
    self,
    *,
    symbol: str,
    epoch: float,
    reasons: tuple[str, ...],
    model_version: str,
    confidence: float | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    self._append(
        {
            "type": "rejection",
            "symbol": symbol,
            "epoch": epoch,
            "reasons": list(reasons),
            "model_version": model_version,
            "confidence": confidence,
            "metadata": metadata or {},
        }
    )

def record_event(self, event_type: str, payload: dict[str, object]) -> None:
    self._append({"type": event_type, **payload})
```

- [ ] **Step 4: Emit rejections and run events from the backtest and live loops**

```python
# src/synthetic_trader/backtest/engine.py
if report.signal is None:
    if self.journal is not None:
        self.journal.record_event(
            "decision_skip",
            {"symbol": symbol, "epoch": primary.close_time, "reasons": list(report.reasons)},
        )
    continue

if not risk_decision.approved or risk_decision.intent is None:
    rejected += 1
    if self.journal is not None:
        self.journal.record_rejection(
            symbol=symbol,
            epoch=report.signal.snapshot.epoch,
            reasons=risk_decision.reasons,
            model_version=report.signal.model_version,
            confidence=report.signal.confidence,
        )
    continue
```

```python
# src/synthetic_trader/live/paper_runner.py
else:
    rejected += 1
    journal.record_rejection(
        symbol=symbol,
        epoch=report.signal.snapshot.epoch,
        reasons=risk_decision.reasons,
        model_version=report.signal.model_version,
        confidence=report.signal.confidence,
    )
```

- [ ] **Step 5: Run the journal and backtest tests**

Run: `python -m unittest tests.test_trade_journal tests.test_backtest -v`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/synthetic_trader/journal/trade_journal.py src/synthetic_trader/backtest/engine.py src/synthetic_trader/live/paper_runner.py tests/test_trade_journal.py tests/test_backtest.py
git commit -m "feat: journal trade rejections and run events"
```

## Task 4: Strengthen Walk-Forward And Risk Correctness Tests

**Files:**
- Modify: `src/synthetic_trader/research/walk_forward.py`
- Test: `tests/test_walk_forward.py`
- Test: `tests/test_risk_engine.py`

- [ ] **Step 1: Write the failing walk-forward and risk tests**

```python
import unittest

from synthetic_trader.config import RiskConfig
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.research.walk_forward import run_walk_forward
from tests.test_backtest import synthetic_ticks


class WalkForwardTests(unittest.TestCase):
    def test_walk_forward_fold_windows_do_not_overlap(self) -> None:
        report = run_walk_forward(
            ticks=synthetic_ticks(candles=270),
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        for fold in report.folds:
            self.assertLess(fold.train_end_epoch, fold.test_start_epoch)


class RiskEngineTests(unittest.TestCase):
    def test_reset_daily_limits_rolls_day_start_to_current_equity(self) -> None:
        engine = RiskEngine(RiskConfig(starting_equity=1000.0))
        engine.state.equity = 960.0
        engine.state.consecutive_losses = 3
        engine.state.trades_today = 4

        engine.reset_daily_limits()

        self.assertEqual(engine.state.day_start_equity, 960.0)
        self.assertEqual(engine.state.consecutive_losses, 0)
        self.assertEqual(engine.state.trades_today, 0)
```

- [ ] **Step 2: Run the upgraded correctness tests**

Run: `python -m unittest tests.test_walk_forward tests.test_risk_engine -v`
Expected: one or more failures caused by incomplete assertions or missing support for richer fold data

- [ ] **Step 3: Tighten walk-forward aggregation where needed**

```python
# src/synthetic_trader/research/walk_forward.py
folds.append(
    WalkForwardFold(
        index=index,
        train_start_epoch=train_slice[0].epoch,
        train_end_epoch=train_slice[-1].epoch,
        test_start_epoch=test_slice[0].epoch,
        test_end_epoch=test_slice[-1].epoch,
        train_ticks=len(train_slice),
        test_ticks=len(test_slice),
        train_trades=train_result.metrics.trades,
        test_trades=test_result.metrics.trades,
        test_win_rate=test_result.metrics.win_rate,
        test_profit_factor=test_result.metrics.profit_factor,
        test_expectancy_r=test_result.metrics.expectancy_r,
        test_net_pnl=test_result.metrics.net_pnl,
        model_version=model.version,
    )
)
```

- [ ] **Step 4: Re-run the correctness tests**

Run: `python -m unittest tests.test_walk_forward tests.test_risk_engine -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/research/walk_forward.py tests/test_walk_forward.py tests/test_risk_engine.py
git commit -m "test: strengthen walk-forward and risk correctness checks"
```

## Task 5: Cover Paper Broker Edge Cases

**Files:**
- Modify: `src/synthetic_trader/execution/paper.py` only if needed
- Test: `tests/test_paper_broker.py`

- [ ] **Step 1: Write the failing paper broker tests**

```python
import unittest

from synthetic_trader.domain import Candle, Direction, MarketSnapshot, Regime, TradeSignal
from synthetic_trader.execution.paper import PaperBroker


def make_signal(direction: Direction) -> TradeSignal:
    snapshot = MarketSnapshot(
        symbol="R_75",
        epoch=120.0,
        timeframe_sec=60,
        regime=Regime.RANGE,
        features={"atr_14": 1.0},
    )
    return TradeSignal(
        symbol="R_75",
        direction=direction,
        confidence=0.7,
        entry=100.0,
        stop_loss=99.0 if direction is Direction.LONG else 101.0,
        take_profit=102.0 if direction is Direction.LONG else 98.0,
        horizon_sec=120,
        snapshot=snapshot,
        rationale=("test",),
        model_version="unit-test",
    )


class PaperBrokerTests(unittest.TestCase):
    def test_stop_wins_when_stop_and_target_hit_same_candle(self) -> None:
        broker = PaperBroker()
        broker.submit(type("Intent", (), {"signal": make_signal(Direction.LONG), "stake": 10.0})())
        candle = Candle("R_75", 120.0, 60, 100.0, 103.0, 98.5, 100.5)

        outcomes = broker.on_candle(candle)

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit, 99.0)
```

- [ ] **Step 2: Run the paper broker tests to verify they fail or expose construction issues**

Run: `python -m unittest tests.test_paper_broker -v`
Expected: either import/setup failure for the new test file or an execution failure that forces the test fixture to match the real domain objects

- [ ] **Step 3: Fix the tests and minimal broker behavior**

```python
# tests/test_paper_broker.py
from synthetic_trader.domain import MarketSnapshot, OrderIntent

broker.submit(
    OrderIntent(
        signal=make_signal(Direction.LONG),
        stake=10.0,
        max_loss=10.0,
        metadata={},
    )
)
```

```python
# src/synthetic_trader/execution/paper.py
if stop_hit and target_hit:
    return self._close_at_price(position, signal.stop_loss, candle.open_time + candle.timeframe_sec)
```

- [ ] **Step 4: Re-run the paper broker tests**

Run: `python -m unittest tests.test_paper_broker -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/execution/paper.py tests/test_paper_broker.py
git commit -m "test: cover paper broker edge cases"
```

## Task 6: Wire CLI Artifact Options And Run Full Validation

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `src/synthetic_trader/research/walk_forward.py`
- Modify: `src/synthetic_trader/backtest/engine.py`
- Test: `tests/test_reporting.py`
- Test: `tests/test_backtest.py`
- Test: `tests/test_walk_forward.py`

- [ ] **Step 1: Write the failing CLI-facing tests**

```python
import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.research.walk_forward import run_walk_forward, save_walk_forward_report
from tests.test_backtest import synthetic_ticks


class ReportingCommandTests(unittest.TestCase):
    def test_save_walk_forward_report_writes_expected_payload(self) -> None:
        report = run_walk_forward(
            ticks=synthetic_ticks(candles=270),
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "walk_forward.json"
            save_walk_forward_report(report, output_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["symbol"], "R_75")
        self.assertIn("folds", payload)
```

- [ ] **Step 2: Run the full reporting-related test slice**

Run: `python -m unittest tests.test_reporting tests.test_backtest tests.test_walk_forward -v`
Expected: `OK` only after all CLI and persistence paths are fully wired

- [ ] **Step 3: Finalize CLI output path arguments**

```python
# src/synthetic_trader/cli.py
backtest_parser.add_argument("--artifact-output", help="write structured backtest result JSON to this path")
walk_forward_parser.add_argument("--artifact-output", help="write structured walk-forward report JSON to this path")
```

```python
# src/synthetic_trader/cli.py
result = engine.run_ticks(
    ticks,
    symbol=args.symbol,
    timeframe_sec=args.timeframe,
    higher_timeframe_sec=args.higher_timeframe,
    artifact_output_path=args.artifact_output,
)

report = run_walk_forward(...)
if args.artifact_output:
    save_walk_forward_report(report, args.artifact_output)
```

- [ ] **Step 4: Run the entire test suite**

Run: `python -m unittest discover -s tests`
Expected:

```text
................................
----------------------------------------------------------------------
Ran <updated-count> tests in <time>s

OK
```

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/backtest/engine.py src/synthetic_trader/research/walk_forward.py tests/test_reporting.py tests/test_backtest.py tests/test_walk_forward.py
git commit -m "feat: expose research artifact workflows in cli"
```

## Spec Coverage Check

- Richer research outputs: covered by Task 1 and Task 6
- Model persistence workflow support: covered by Task 2
- Approved and rejected decision traceability: covered by Task 3
- Validation correctness and fold visibility: covered by Task 4 and Task 6
- Targeted test expansion for fragile execution paths: covered by Task 5
- Automatic readiness for the next phase: supported by the additive architecture and completed validation tasks above

## Placeholder Scan

- No `TODO`, `TBD`, or deferred implementation markers remain
- Every task names exact files, commands, and expected outcomes
- Every code-changing task includes concrete code snippets instead of abstract instructions

## Type Consistency Check

- `artifact_output_path` is used consistently for backtest JSON output
- `save_walk_forward_report()` is the named helper for walk-forward artifacts
- `record_rejection()` and `record_event()` are the journal extension points used by both research and live loops
- `metadata` is consistently used as the model-persistence extension field
