# Live Market Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strictly read-only live market snapshot command for `R_75` and `R_100` that fetches current live data, runs the existing analysis stack, and prints both trader-friendly guidance and structured fields.

**Architecture:** Introduce a dedicated live-analysis module separate from the execution path. The new command reuses the existing Deriv market data client, candle builder, feature assembly, decision engine, and risk engine to produce a bounded live snapshot without routing through MT5 or any order execution logic.

**Tech Stack:** Python 3.11+, `asyncio`, `argparse`, Deriv WebSocket client, existing candle/feature/decision/risk modules, `unittest`, `pytest`

---

## File Map

- Create: `src/synthetic_trader/live/market_snapshot.py`
  - Read-only live snapshot collection, analysis, and rendering helpers.
- Modify: `src/synthetic_trader/cli.py`
  - Add the new `live-snapshot` command and wire it to the snapshot module.
- Modify: `src/synthetic_trader/live/__init__.py`
  - Export or document the live snapshot module if needed.
- Create: `tests/test_live_market_snapshot.py`
  - Add focused unit coverage for snapshot building, rendering, and read-only behavior.

### Task 1: Add CLI Coverage For The New Read-Only Command

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Write the failing CLI output test**

Create `tests/test_live_market_snapshot.py` with:

```python
from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from synthetic_trader.cli import main


class LiveSnapshotCliTests(unittest.TestCase):
    def test_live_snapshot_command_prints_briefing_and_structured_fields(self) -> None:
        snapshot = {
            "trade_status": "valid",
            "direction_bias": "buy",
            "briefing": "trend continuation candidate; structure and regime aligned",
            "symbol": "R_75",
            "regime": "trend_up",
            "confidence": 0.74,
        }

        with patch("synthetic_trader.cli.run_live_snapshot", return_value=snapshot):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["live-snapshot", "--symbol", "R_75"])

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("trade_status=valid", rendered)
        self.assertIn("direction_bias=buy", rendered)
        self.assertIn("briefing=trend continuation candidate; structure and regime aligned", rendered)
        self.assertIn("symbol=R_75", rendered)
        self.assertIn("regime=trend_up", rendered)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotCliTests::test_live_snapshot_command_prints_briefing_and_structured_fields -v
```

Expected:

```text
FAILED ... AttributeError: module 'synthetic_trader.cli' has no attribute 'run_live_snapshot'
```

- [ ] **Step 3: Add the new CLI command and placeholder wiring**

Modify `src/synthetic_trader/cli.py` imports:

```python
from synthetic_trader.live.market_snapshot import render_live_snapshot_text, run_live_snapshot
```

Add parser setup near the other live commands:

```python
live_snapshot = subparsers.add_parser(
    "live-snapshot",
    help="render a read-only live market snapshot for a symbol",
)
live_snapshot.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
live_snapshot.add_argument("--warmup-count", type=int, default=5000)
live_snapshot.add_argument("--timeframe", type=int, default=60)
live_snapshot.add_argument("--higher-timeframe", type=int, default=300)
live_snapshot.add_argument("--max-live-ticks", type=int, default=90)
live_snapshot.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")
```

Add command handling:

```python
    if args.command == "live-snapshot":
        snapshot = asyncio.run(
            run_live_snapshot(
                symbol=args.symbol,
                warmup_count=args.warmup_count,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.higher_timeframe,
                max_live_ticks=args.max_live_ticks,
                app_id=args.app_id,
            )
        )
        print(render_live_snapshot_text(snapshot))
        return 0
```

- [ ] **Step 4: Create the smallest live snapshot module needed for the CLI test**

Create `src/synthetic_trader/live/market_snapshot.py`:

```python
from __future__ import annotations


async def run_live_snapshot(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    max_live_ticks: int,
    app_id: str | None = None,
) -> dict[str, object]:
    del warmup_count, timeframe_sec, higher_timeframe_sec, max_live_ticks, app_id
    return {
        "trade_status": "not_valid",
        "direction_bias": "none",
        "briefing": "live snapshot module not implemented",
        "symbol": symbol,
        "regime": "unknown",
        "confidence": 0.0,
    }


def render_live_snapshot_text(snapshot: dict[str, object]) -> str:
    ordered = [
        "trade_status",
        "direction_bias",
        "briefing",
        "symbol",
        "regime",
        "confidence",
    ]
    return "\n".join(f"{key}={snapshot.get(key)}" for key in ordered if key in snapshot)
```

- [ ] **Step 5: Run the CLI test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotCliTests::test_live_snapshot_command_prints_briefing_and_structured_fields -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveSnapshotCliTests::...
```

- [ ] **Step 6: Commit the CLI scaffold**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add live snapshot command scaffold"
```

### Task 2: Build Read-Only Live Snapshot Collection

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Reference: `src/synthetic_trader/execution/deriv_ws.py`
- Reference: `src/synthetic_trader/data/collector.py`

- [ ] **Step 1: Write the failing data-path test**

Add to `tests/test_live_market_snapshot.py`:

```python
import asyncio

from synthetic_trader.domain import Tick
from synthetic_trader.live.market_snapshot import collect_live_snapshot_ticks


class _FakeSnapshotClient:
    def __init__(self, warmup: list[Tick], live_ticks: list[Tick]) -> None:
        self._warmup = warmup
        self._live_ticks = live_ticks

    async def __aenter__(self) -> "_FakeSnapshotClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def ticks_history(self, symbol: str, count: int) -> list[Tick]:
        return list(self._warmup)

    async def subscribe_ticks(self, symbol: str):
        for tick in self._live_ticks:
            yield tick


class LiveSnapshotDataTests(unittest.TestCase):
    def test_collect_live_snapshot_ticks_merges_warmup_and_live_ticks(self) -> None:
        warmup = [Tick(symbol="R_75", epoch=1, price=100.0), Tick(symbol="R_75", epoch=2, price=100.1)]
        live_ticks = [Tick(symbol="R_75", epoch=3, price=100.2), Tick(symbol="R_75", epoch=4, price=100.3)]

        ticks = asyncio.run(
            collect_live_snapshot_ticks(
                symbol="R_75",
                warmup_count=2,
                max_live_ticks=2,
                client_factory=lambda: _FakeSnapshotClient(warmup, live_ticks),
            )
        )

        self.assertEqual([tick.epoch for tick in ticks], [1, 2, 3, 4])
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotDataTests::test_collect_live_snapshot_ticks_merges_warmup_and_live_ticks -v
```

Expected:

```text
FAILED ... ImportError: cannot import name 'collect_live_snapshot_ticks'
```

- [ ] **Step 3: Implement bounded live tick collection**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
from collections.abc import Callable

from synthetic_trader.data.collector import deriv_credentials_from_env
from synthetic_trader.domain import Tick
from synthetic_trader.execution.deriv_ws import DerivWebSocketClient
from synthetic_trader.execution.venues import MarketDataClient
```

```python
async def collect_live_snapshot_ticks(
    *,
    symbol: str,
    warmup_count: int,
    max_live_ticks: int,
    app_id: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> list[Tick]:
    credentials = deriv_credentials_from_env(app_id=app_id)
    factory = client_factory or (lambda: DerivWebSocketClient(credentials))
    collected: list[Tick] = []

    async with factory() as client:
        if warmup_count > 0:
            collected.extend(await client.ticks_history(symbol=symbol, count=warmup_count))
        if max_live_ticks > 0:
            async for tick in client.subscribe_ticks(symbol):
                collected.append(tick)
                if len([item for item in collected if item.epoch > 0]) >= warmup_count + max_live_ticks:
                    break

    return sorted(collected, key=lambda item: item.epoch)
```

- [ ] **Step 4: Run the data-path test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotDataTests::test_collect_live_snapshot_ticks_merges_warmup_and_live_ticks -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveSnapshotDataTests::...
```

- [ ] **Step 5: Commit the read-only live collection layer**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add read-only live snapshot data collection"
```

### Task 3: Reuse The Existing Analysis Stack For Snapshot Interpretation

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Reference: `src/synthetic_trader/data/candles.py`
- Reference: `src/synthetic_trader/strategy/decision_engine.py`
- Reference: `src/synthetic_trader/risk/engine.py`

- [ ] **Step 1: Write the failing interpretation tests**

Add to `tests/test_live_market_snapshot.py`:

```python
from synthetic_trader.config import TraderConfig
from synthetic_trader.live.market_snapshot import analyze_live_snapshot


class LiveSnapshotAnalysisTests(unittest.TestCase):
    def test_analyze_live_snapshot_reports_not_valid_when_history_is_insufficient(self) -> None:
        snapshot = analyze_live_snapshot(
            symbol="R_75",
            ticks=[Tick(symbol="R_75", epoch=1, price=100.0)],
            timeframe_sec=60,
            higher_timeframe_sec=300,
            config=TraderConfig.default(),
        )

        self.assertEqual(snapshot["trade_status"], "not_valid")
        self.assertIn("need", str(snapshot["reasons"]))
```

- [ ] **Step 2: Run the interpretation test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_analyze_live_snapshot_reports_not_valid_when_history_is_insufficient -v
```

Expected:

```text
FAILED ... ImportError: cannot import name 'analyze_live_snapshot'
```

- [ ] **Step 3: Implement read-only snapshot analysis**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
from dataclasses import replace

from synthetic_trader.config import TraderConfig
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.strategy.decision_engine import DecisionEngine
from synthetic_trader.risk.engine import RiskEngine
```

```python
def analyze_live_snapshot(
    *,
    symbol: str,
    ticks: list[Tick],
    timeframe_sec: int,
    higher_timeframe_sec: int,
    config: TraderConfig,
) -> dict[str, object]:
    builder = MultiTimeframeCandleBuilder(symbol, [timeframe_sec, higher_timeframe_sec])
    histories: dict[int, list[object]] = {timeframe_sec: [], higher_timeframe_sec: []}

    for tick in ticks:
        closed = builder.update(tick)
        for timeframe, candle in closed.items():
            histories.setdefault(timeframe, []).append(candle)

    flushed = builder.flush()
    for timeframe, candle in flushed.items():
        histories.setdefault(timeframe, []).append(candle)

    decision_engine = DecisionEngine(config)
    report = decision_engine.evaluate(
        symbol=symbol,
        candles=histories[timeframe_sec],
        higher_timeframe_candles=histories[higher_timeframe_sec],
    )
    if report.signal is None:
        return {
            "trade_status": "not_valid",
            "direction_bias": "none",
            "briefing": "current movement is active but not a clean setup yet",
            "symbol": symbol,
            "regime": "unknown",
            "confidence": 0.0,
            "reasons": list(report.reasons),
        }

    risk_engine = RiskEngine(config.risk)
    risk_decision = risk_engine.evaluate(report.signal)
    return {
        "trade_status": "valid" if risk_decision.approved else "not_valid",
        "direction_bias": report.signal.direction.value,
        "briefing": "; ".join(report.signal.rationale[:2]),
        "symbol": symbol,
        "regime": report.signal.snapshot.regime.value,
        "confidence": round(report.signal.confidence, 3),
        "reasons": list(risk_decision.reasons or report.signal.rationale),
        "model_version": report.signal.model_version,
        "current_close": report.signal.entry,
    }
```

- [ ] **Step 4: Wire the main snapshot command to the analysis function**

Replace the placeholder `run_live_snapshot()` in `src/synthetic_trader/live/market_snapshot.py` with:

```python
async def run_live_snapshot(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    max_live_ticks: int,
    app_id: str | None = None,
) -> dict[str, object]:
    ticks = await collect_live_snapshot_ticks(
        symbol=symbol,
        warmup_count=warmup_count,
        max_live_ticks=max_live_ticks,
        app_id=app_id,
    )
    config = TraderConfig.default()
    return analyze_live_snapshot(
        symbol=symbol,
        ticks=ticks,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        config=config,
    )
```

- [ ] **Step 5: Run the interpretation test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_analyze_live_snapshot_reports_not_valid_when_history_is_insufficient -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::...
```

- [ ] **Step 6: Commit the snapshot analysis pipeline**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add read-only live market snapshot analysis"
```

### Task 4: Improve Trader-Friendly Rendering

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing rendering-format test**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveSnapshotRenderTests(unittest.TestCase):
    def test_render_live_snapshot_text_prints_briefing_before_structured_fields(self) -> None:
        rendered = render_live_snapshot_text(
            {
                "trade_status": "valid",
                "direction_bias": "buy",
                "briefing": "trend continuation candidate; structure and regime aligned",
                "symbol": "R_75",
                "regime": "trend_up",
                "confidence": 0.74,
                "reasons": ["risk approved"],
            }
        )

        self.assertIn("trade_status=valid", rendered)
        self.assertIn("direction_bias=buy", rendered)
        self.assertIn("briefing=trend continuation candidate; structure and regime aligned", rendered)
        self.assertIn("reasons=['risk approved']", rendered)
```

- [ ] **Step 2: Run the rendering test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotRenderTests::test_render_live_snapshot_text_prints_briefing_before_structured_fields -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Extend rendering with trader-first plus structured output**

Modify `src/synthetic_trader/live/market_snapshot.py`:

```python
def render_live_snapshot_text(snapshot: dict[str, object]) -> str:
    briefing_keys = [
        "trade_status",
        "direction_bias",
        "briefing",
    ]
    structured_keys = [
        "symbol",
        "regime",
        "confidence",
        "model_version",
        "current_close",
        "reasons",
    ]
    lines: list[str] = []
    for key in briefing_keys + structured_keys:
        if key in snapshot:
            lines.append(f"{key}={snapshot.get(key)}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the rendering test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotRenderTests::test_render_live_snapshot_text_prints_briefing_before_structured_fields -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveSnapshotRenderTests::...
```

- [ ] **Step 5: Commit the trader-friendly rendering**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: render trader-friendly live market snapshots"
```

### Task 5: Run Full Validation For The New Read-Only Feature

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Reference: `src/synthetic_trader/live/market_snapshot.py`
- Reference: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Run the dedicated live snapshot test file**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::...
```

- [ ] **Step 2: Run the existing live and rollout regressions**

Run:

```bash
python -m pytest tests/test_live_paper_runner.py tests/test_phase10_mt5_monitor.py tests/test_phase15_final_validation.py tests/test_phase16_supervised_rollout.py -v
```

Expected:

```text
PASSED tests/test_live_paper_runner.py::...
PASSED tests/test_phase10_mt5_monitor.py::...
PASSED tests/test_phase15_final_validation.py::...
PASSED tests/test_phase16_supervised_rollout.py::...
```

- [ ] **Step 3: Smoke-test the new command manually**

Run:

```bash
python -m synthetic_trader.cli live-snapshot --symbol R_75 --warmup-count 5000 --timeframe 60 --higher-timeframe 300 --max-live-ticks 60
```

Expected:

```text
trade_status=
direction_bias=
briefing=
symbol=R_75
```

- [ ] **Step 4: Review diagnostics on modified files**

Review diagnostics for:

```text
src/synthetic_trader/live/market_snapshot.py
src/synthetic_trader/cli.py
tests/test_live_market_snapshot.py
```

Expected:

```text
No new syntax or import errors.
```

- [ ] **Step 5: Commit the validated live snapshot feature**

```bash
git add src/synthetic_trader/live/market_snapshot.py src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: add read-only live market snapshot command"
```
