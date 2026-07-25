# Live Watch Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `live-watch` command that continuously monitors `R_75` or `R_100`, evaluates on primary candle close, and emits trader-friendly alerts only when the market meaningfully changes.

**Architecture:** Build the watch mode on top of the existing read-only `live-snapshot` analysis stack instead of creating a second strategy path. Add a compact watch-state and alert renderer so the command can compare successive evaluated snapshots, emit alerts to terminal and JSONL only on significant transitions, and remain fully separated from MT5 or execution logic.

**Tech Stack:** Python 3.11+, `asyncio`, `argparse`, existing Deriv WebSocket client, candle builders, live snapshot analysis module, JSONL journaling, `unittest`, `pytest`

---

## File Map

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Add watch-state model, alert transition logic, live watch loop, alert rendering, and journal helpers.
- Modify: `src/synthetic_trader/cli.py`
  - Add `live-watch` command and wire it to the read-only watch loop.
- Modify: `tests/test_live_market_snapshot.py`
  - Add focused watch-mode, transition, rendering, and journal tests.

### Task 1: Add CLI Coverage For `live-watch`

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Write the failing CLI test**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchCliTests(unittest.TestCase):
    def test_live_watch_command_prints_emitted_alerts(self) -> None:
        alerts = [
            {
                "call": "stand_aside",
                "symbol": "R_75",
                "why": "direction is mixed and confidence is below threshold",
                "wait_for": "wait for cleaner bearish continuation or stronger bullish reclaim",
            }
        ]

        with patch("synthetic_trader.cli.run_live_watch", return_value=alerts):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "live-watch",
                        "--symbol",
                        "R_75",
                        "--max-alerts",
                        "1",
                    ]
                )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("call=stand_aside", rendered)
        self.assertIn("symbol=R_75", rendered)
        self.assertIn("why=direction is mixed and confidence is below threshold", rendered)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchCliTests::test_live_watch_command_prints_emitted_alerts -v
```

Expected:

```text
FAILED ... AttributeError: module 'synthetic_trader.cli' has no attribute 'run_live_watch'
```

- [ ] **Step 3: Add the `live-watch` parser and command handler**

Modify `src/synthetic_trader/cli.py` imports:

```python
from synthetic_trader.live.market_snapshot import (
    render_live_snapshot_text,
    render_live_watch_alert_text,
    run_live_snapshot,
    run_live_watch,
)
```

Add parser setup:

```python
live_watch = subparsers.add_parser(
    "live-watch",
    help="continuously monitor a symbol and emit read-only alerts on meaningful change",
)
live_watch.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
live_watch.add_argument("--warmup-count", type=int, default=5000)
live_watch.add_argument("--timeframe", type=int, default=60)
live_watch.add_argument("--higher-timeframe", type=int, default=300)
live_watch.add_argument("--journal", default="journals/live_watch_alerts.jsonl")
live_watch.add_argument("--max-alerts", type=int)
live_watch.add_argument("--max-minutes", type=int)
live_watch.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")
```

Add command handling:

```python
    if args.command == "live-watch":
        alerts = asyncio.run(
            run_live_watch(
                symbol=args.symbol,
                warmup_count=args.warmup_count,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.higher_timeframe,
                journal_path=args.journal,
                max_alerts=args.max_alerts,
                max_minutes=args.max_minutes,
                app_id=args.app_id,
            )
        )
        for alert in alerts:
            print(render_live_watch_alert_text(alert))
        return 0
```

- [ ] **Step 4: Add the smallest watch scaffolding to satisfy the CLI test**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
async def run_live_watch(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    journal_path: str,
    max_alerts: int | None = None,
    max_minutes: int | None = None,
    app_id: str | None = None,
) -> list[dict[str, object]]:
    del warmup_count, timeframe_sec, higher_timeframe_sec, journal_path, max_alerts, max_minutes, app_id
    return [
        {
            "call": "stand_aside",
            "symbol": symbol,
            "why": "direction is mixed and confidence is below threshold",
            "wait_for": "wait for cleaner bearish continuation or stronger bullish reclaim",
        }
    ]


def render_live_watch_alert_text(alert: dict[str, object]) -> str:
    ordered = ["call", "symbol", "why", "wait_for"]
    return "\n".join(f"{key}={alert.get(key)}" for key in ordered if key in alert)
```

- [ ] **Step 5: Run the CLI test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchCliTests::test_live_watch_command_prints_emitted_alerts -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchCliTests::...
```

- [ ] **Step 6: Commit the watch CLI scaffold**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch command scaffold"
```

### Task 2: Add Watch-State And Transition Detection

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing transition tests**

Add to `tests/test_live_market_snapshot.py`:

```python
from synthetic_trader.live.market_snapshot import build_watch_state, should_emit_watch_alert


class LiveWatchTransitionTests(unittest.TestCase):
    def test_should_emit_watch_alert_returns_false_when_meaningful_state_is_unchanged(self) -> None:
        previous = build_watch_state(
            {
                "call": "stand_aside",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "regime": "range",
                "confidence": 0.52,
                "wait_for": "wait for clearer structure",
            }
        )
        current = build_watch_state(
            {
                "call": "stand_aside",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "regime": "range",
                "confidence": 0.53,
                "wait_for": "wait for clearer structure",
            }
        )

        self.assertFalse(should_emit_watch_alert(previous, current))

    def test_should_emit_watch_alert_returns_true_when_call_changes(self) -> None:
        previous = build_watch_state(
            {
                "call": "stand_aside",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "regime": "range",
                "confidence": 0.52,
                "wait_for": "wait for clearer structure",
            }
        )
        current = build_watch_state(
            {
                "call": "buy_candidate",
                "trade_status": "valid",
                "direction_bias": "buy",
                "regime": "trend_up",
                "confidence": 0.66,
                "wait_for": "wait for a clean bullish continuation close",
            }
        )

        self.assertTrue(should_emit_watch_alert(previous, current))
```

- [ ] **Step 2: Run the transition tests to verify they fail**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchTransitionTests -v
```

Expected:

```text
FAILED ... ImportError: cannot import name 'build_watch_state'
```

- [ ] **Step 3: Implement compact watch-state and transition rules**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
from dataclasses import dataclass
```

```python
@dataclass(frozen=True)
class WatchState:
    call: str
    trade_status: str
    direction_bias: str
    regime: str
    confidence_bucket: str
    wait_for: str
```

```python
def build_watch_state(snapshot: dict[str, object]) -> WatchState:
    confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    if confidence >= 0.58:
        bucket = "above_threshold"
    elif confidence >= 0.50:
        bucket = "near_threshold"
    else:
        bucket = "low_confidence"
    return WatchState(
        call=str(snapshot.get("call", "stand_aside")),
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        regime=str(snapshot.get("regime", "unknown")),
        confidence_bucket=bucket,
        wait_for=str(snapshot.get("wait_for", "")),
    )


def should_emit_watch_alert(previous: WatchState | None, current: WatchState) -> bool:
    if previous is None:
        return False
    return previous != current
```

- [ ] **Step 4: Run the transition tests to verify they pass**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchTransitionTests -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchTransitionTests::...
```

- [ ] **Step 5: Commit the transition logic**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch transition rules"
```

### Task 3: Implement Candle-Close Watch Loop

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing candle-close watch test**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchLoopTests(unittest.TestCase):
    def test_run_live_watch_evaluates_on_primary_candle_close_and_emits_alert_on_change(self) -> None:
        ticks = [
            Tick(symbol="R_75", epoch=0, price=100.0),
            Tick(symbol="R_75", epoch=10, price=100.1),
            Tick(symbol="R_75", epoch=61, price=100.5),
            Tick(symbol="R_75", epoch=121, price=101.0),
        ]
        snapshots = [
            {
                "call": "stand_aside",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "regime": "range",
                "confidence": 0.52,
                "wait_for": "wait for clearer structure",
                "why": "direction is mixed",
                "symbol": "R_75",
            },
            {
                "call": "buy_candidate",
                "trade_status": "valid",
                "direction_bias": "buy",
                "regime": "trend_up",
                "confidence": 0.66,
                "wait_for": "wait for a clean bullish continuation close",
                "why": "trend continuation aligned with structure and regime",
                "symbol": "R_75",
            },
        ]

        with patch("synthetic_trader.live.market_snapshot.collect_live_snapshot_ticks", return_value=ticks[:2]):
            with patch("synthetic_trader.live.market_snapshot.analyze_live_snapshot", side_effect=snapshots):
                with patch("synthetic_trader.live.market_snapshot.watch_live_ticks", return_value=ticks[2:]):
                    alerts = asyncio.run(
                        run_live_watch(
                            symbol="R_75",
                            warmup_count=2,
                            timeframe_sec=60,
                            higher_timeframe_sec=300,
                            journal_path="journals/test_live_watch.jsonl",
                            max_alerts=1,
                        )
                    )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["call"], "buy_candidate")
```

- [ ] **Step 2: Run the loop test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchLoopTests::test_run_live_watch_evaluates_on_primary_candle_close_and_emits_alert_on_change -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Implement the bounded watch loop**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
import json
from pathlib import Path
```

```python
async def watch_live_ticks(
    *,
    symbol: str,
    app_id: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> list[Tick]:
    credentials = deriv_credentials_from_env(app_id=app_id)
    factory = client_factory or (lambda: DerivWebSocketClient(credentials))
    async with factory() as client:
        collected: list[Tick] = []
        async for tick in client.subscribe_ticks(symbol):
            collected.append(tick)
            if len(collected) >= 1:
                return collected
    return []
```

```python
def build_watch_alert(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "call": snapshot.get("call", "stand_aside"),
        "symbol": snapshot.get("symbol"),
        "why": snapshot.get("briefing"),
        "wait_for": snapshot.get("wait_for"),
        "trade_status": snapshot.get("trade_status"),
        "direction_bias": snapshot.get("direction_bias"),
        "regime": snapshot.get("regime"),
        "confidence": snapshot.get("confidence"),
        "current_close": snapshot.get("current_close"),
        "reasons": snapshot.get("reasons"),
    }
```

```python
async def run_live_watch(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    journal_path: str,
    max_alerts: int | None = None,
    max_minutes: int | None = None,
    app_id: str | None = None,
) -> list[dict[str, object]]:
    del max_minutes
    history = await collect_live_snapshot_ticks(
        symbol=symbol,
        warmup_count=warmup_count,
        max_live_ticks=0,
        app_id=app_id,
    )
    baseline_snapshot = analyze_live_snapshot(
        symbol=symbol,
        ticks=history,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        config=TraderConfig.default(),
    )
    previous_state = build_watch_state(baseline_snapshot)
    alerts: list[dict[str, object]] = []
    buffer = list(history)

    for tick in await watch_live_ticks(symbol=symbol, app_id=app_id):
        buffer.append(tick)
        bucket = int(tick.epoch // timeframe_sec) * timeframe_sec
        previous_bucket = int(buffer[-2].epoch // timeframe_sec) * timeframe_sec if len(buffer) > 1 else bucket
        if bucket == previous_bucket:
            continue

        snapshot = analyze_live_snapshot(
            symbol=symbol,
            ticks=buffer,
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            config=TraderConfig.default(),
        )
        current_state = build_watch_state(snapshot)
        if should_emit_watch_alert(previous_state, current_state):
            alert = build_watch_alert(snapshot)
            append_watch_alert(Path(journal_path), alert)
            alerts.append(alert)
            previous_state = current_state
            if max_alerts is not None and len(alerts) >= max_alerts:
                break
        else:
            previous_state = current_state

    return alerts
```

```python
def append_watch_alert(path: Path, alert: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(alert) + "\n")
```

- [ ] **Step 4: Run the loop test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchLoopTests::test_run_live_watch_evaluates_on_primary_candle_close_and_emits_alert_on_change -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchLoopTests::...
```

- [ ] **Step 5: Commit the watch loop**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add read-only live watch loop"
```

### Task 4: Improve Trader Alert Output And Journal Coverage

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing alert rendering and journal test**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchRenderTests(unittest.TestCase):
    def test_render_live_watch_alert_text_prints_trader_short_fields(self) -> None:
        rendered = render_live_watch_alert_text(
            {
                "call": "buy_candidate",
                "symbol": "R_75",
                "why": "trend continuation aligned with structure and regime",
                "wait_for": "wait for a clean bullish continuation close",
                "current_close": 48905.54,
            }
        )

        self.assertIn("call=buy_candidate", rendered)
        self.assertIn("why=trend continuation aligned with structure and regime", rendered)
        self.assertIn("wait_for=wait for a clean bullish continuation close", rendered)
        self.assertIn("current_close=48905.54", rendered)
```

- [ ] **Step 2: Run the rendering test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_trader_short_fields -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Extend alert rendering to include trader-short supporting fields**

Modify `src/synthetic_trader/live/market_snapshot.py`:

```python
def render_live_watch_alert_text(alert: dict[str, object]) -> str:
    ordered = [
        "call",
        "symbol",
        "why",
        "wait_for",
        "trade_status",
        "direction_bias",
        "regime",
        "confidence",
        "current_close",
        "reasons",
    ]
    return "\n".join(f"{key}={alert.get(key)}" for key in ordered if key in alert)
```

- [ ] **Step 4: Run the rendering test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_trader_short_fields -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

- [ ] **Step 5: Commit the alert output refinement**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: render trader-short live watch alerts"
```

### Task 5: Run Full Validation For Watch Mode

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Reference: `src/synthetic_trader/live/market_snapshot.py`
- Reference: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Run the full live snapshot/watch test file**

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
python -m synthetic_trader.cli live-watch --symbol R_75 --warmup-count 5000 --timeframe 60 --higher-timeframe 300 --journal journals/live_watch_alerts.jsonl --max-alerts 1
```

Expected:

```text
call=
symbol=R_75
why=
wait_for=
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

- [ ] **Step 5: Commit the validated live watch alert feature**

```bash
git add src/synthetic_trader/live/market_snapshot.py src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: add read-only live watch alerts"
```
