# Live Watch Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `live-watch-review` command that summarizes the latest watch state and renders recent journaled watch alerts in a trader-friendly format.

**Architecture:** Build the review feature on top of the existing `live-watch` journal format and current watch alert renderer. Keep the logic close to the existing watch module so parsing, filtering, snapshot-building, and rendering all reuse the same alert vocabulary and valid-signal formatting rules already used by `live-watch`.

**Tech Stack:** Python 3.11+, `argparse`, `json`, `pathlib`, existing `live.market_snapshot` helpers, existing CLI architecture, `unittest`, `pytest`

---

## File Map

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Add watch review journal parsing, filtering, summary snapshot building, and review rendering helpers.
- Modify: `src/synthetic_trader/cli.py`
  - Add `live-watch-review` parser and wire it to the new review helpers.
- Modify: `tests/test_live_market_snapshot.py`
  - Add focused tests for review snapshot filters, empty-state handling, rendering, and CLI behavior.

### Task 1: Add CLI Coverage For `live-watch-review`

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Write the failing CLI test**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchReviewCliTests(unittest.TestCase):
    def test_live_watch_review_command_prints_review_summary(self) -> None:
        snapshot = {
            "latest_call": "buy_candidate",
            "latest_symbol": "R_75",
            "latest_trade_status": "valid",
            "latest_direction_bias": "buy",
            "latest_regime": "trend_up",
            "latest_confidence": 0.66,
            "latest_current_close": 48905.54,
            "latest_wait_for": "wait for a clean bullish continuation close",
            "alert_count": 2,
            "alerts": [],
        }

        with patch("synthetic_trader.cli.build_live_watch_review_snapshot", return_value=snapshot):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "live-watch-review",
                        "--journal",
                        "journals/live_watch_alerts.jsonl",
                    ]
                )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("review_latest_call=buy_candidate", rendered)
        self.assertIn("review_latest_symbol=R_75", rendered)
        self.assertIn("review_alert_count=2", rendered)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewCliTests::test_live_watch_review_command_prints_review_summary -v
```

Expected:

```text
FAILED ... AttributeError: module 'synthetic_trader.cli' has no attribute 'build_live_watch_review_snapshot'
```

- [ ] **Step 3: Add the parser and command hook**

Modify `src/synthetic_trader/cli.py` imports:

```python
from synthetic_trader.live.market_snapshot import (
    build_live_watch_review_snapshot,
    render_live_snapshot_text,
    render_live_watch_alert_text,
    render_live_watch_review_text,
    run_live_snapshot,
    run_live_watch,
)
```

Add parser setup:

```python
live_watch_review = subparsers.add_parser(
    "live-watch-review",
    help="review recent live-watch alerts from the journal",
)
live_watch_review.add_argument("--journal", default="journals/live_watch_alerts.jsonl")
live_watch_review.add_argument("--symbol", choices=["R_75", "R_100"])
live_watch_review.add_argument("--limit", type=int, default=5)
live_watch_review.add_argument("--call", dest="call_filter")
live_watch_review.add_argument("--valid-only", action="store_true")
```

Add command handling:

```python
    if args.command == "live-watch-review":
        journal_path = Path(args.journal)
        if not journal_path.exists():
            print(f"error=journal_not_found:{journal_path}")
            return 1
        snapshot = build_live_watch_review_snapshot(
            journal_path=journal_path,
            symbol=args.symbol,
            limit=args.limit,
            call_filter=args.call_filter,
            valid_only=args.valid_only,
        )
        print(render_live_watch_review_text(snapshot))
        return 0
```

- [ ] **Step 4: Add the smallest review scaffolding to satisfy the CLI test**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
def build_live_watch_review_snapshot(
    *,
    journal_path: Path,
    symbol: str | None = None,
    limit: int = 5,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> dict[str, object]:
    del journal_path, symbol, limit, call_filter, valid_only
    return {
        "latest_call": "unknown",
        "latest_symbol": None,
        "latest_trade_status": None,
        "latest_direction_bias": None,
        "latest_regime": None,
        "latest_confidence": None,
        "latest_current_close": None,
        "latest_wait_for": None,
        "alert_count": 0,
        "alerts": [],
    }


def render_live_watch_review_text(snapshot: dict[str, object]) -> str:
    ordered = [
        "latest_call",
        "latest_symbol",
        "latest_trade_status",
        "latest_direction_bias",
        "latest_regime",
        "latest_confidence",
        "latest_current_close",
        "latest_wait_for",
        "alert_count",
    ]
    return "\n".join(
        f"review_{key}={snapshot.get(key)}"
        for key in ordered
        if key in snapshot
    )
```

- [ ] **Step 5: Run the CLI test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewCliTests::test_live_watch_review_command_prints_review_summary -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewCliTests::...
```

- [ ] **Step 6: Commit the review CLI scaffold**

```bash
git add src/synthetic_trader/cli.py src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch review command scaffold"
```

### Task 2: Parse Watch Journal Alerts And Apply Filters

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing filter tests**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchReviewSnapshotTests(unittest.TestCase):
    def test_build_live_watch_review_snapshot_filters_by_symbol_call_and_valid_only(self) -> None:
        journal_path = Path("journals/test_live_watch_review.jsonl")
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text(
            "\n".join(
                [
                    json.dumps({"call": "stand_aside", "symbol": "R_75", "trade_status": "not_valid", "regime": "range"}),
                    json.dumps({"call": "buy_candidate", "symbol": "R_75", "trade_status": "valid", "regime": "trend_up"}),
                    json.dumps({"call": "sell_candidate", "symbol": "R_100", "trade_status": "valid", "regime": "trend_down"}),
                ]
            ),
            encoding="utf-8",
        )

        snapshot = build_live_watch_review_snapshot(
            journal_path=journal_path,
            symbol="R_75",
            limit=5,
            call_filter="buy_candidate",
            valid_only=True,
        )

        self.assertEqual(snapshot["alert_count"], 1)
        self.assertEqual(snapshot["latest_call"], "buy_candidate")
        self.assertEqual(snapshot["latest_symbol"], "R_75")
```

- [ ] **Step 2: Run the filter test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewSnapshotTests::test_build_live_watch_review_snapshot_filters_by_symbol_call_and_valid_only -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Implement journal parsing and filter helpers**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
def load_live_watch_alerts(journal_path: Path) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict) and payload.get("call") is not None and payload.get("symbol") is not None:
            alerts.append(payload)
    return alerts


def filter_live_watch_alerts(
    alerts: list[dict[str, object]],
    *,
    symbol: str | None = None,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> list[dict[str, object]]:
    filtered = list(alerts)
    if symbol is not None:
        filtered = [alert for alert in filtered if alert.get("symbol") == symbol]
    if call_filter is not None:
        filtered = [alert for alert in filtered if alert.get("call") == call_filter]
    if valid_only:
        filtered = [alert for alert in filtered if alert.get("trade_status") == "valid"]
    return filtered
```

Update `build_live_watch_review_snapshot()`:

```python
def build_live_watch_review_snapshot(
    *,
    journal_path: Path,
    symbol: str | None = None,
    limit: int = 5,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> dict[str, object]:
    filtered = filter_live_watch_alerts(
        load_live_watch_alerts(journal_path),
        symbol=symbol,
        call_filter=call_filter,
        valid_only=valid_only,
    )
    recent = list(reversed(filtered[-max(limit, 0) :]))
    latest = filtered[-1] if filtered else {}
    return {
        "latest_call": latest.get("call"),
        "latest_symbol": latest.get("symbol"),
        "latest_trade_status": latest.get("trade_status"),
        "latest_direction_bias": latest.get("direction_bias"),
        "latest_regime": latest.get("regime"),
        "latest_confidence": latest.get("confidence"),
        "latest_current_close": latest.get("current_close"),
        "latest_wait_for": latest.get("wait_for"),
        "alert_count": len(filtered),
        "alerts": recent,
    }
```

- [ ] **Step 4: Run the filter test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewSnapshotTests::test_build_live_watch_review_snapshot_filters_by_symbol_call_and_valid_only -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewSnapshotTests::...
```

- [ ] **Step 5: Commit the review filter logic**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch review filters"
```

### Task 3: Add Empty-State And Recent Alert Rendering

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing render tests**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchReviewRenderTests(unittest.TestCase):
    def test_render_live_watch_review_text_prints_summary_and_recent_alerts(self) -> None:
        rendered = render_live_watch_review_text(
            {
                "latest_call": "buy_candidate",
                "latest_symbol": "R_75",
                "latest_trade_status": "valid",
                "latest_direction_bias": "buy",
                "latest_regime": "trend_up",
                "latest_confidence": 0.66,
                "latest_current_close": 48905.54,
                "latest_wait_for": "wait for a clean bullish continuation close",
                "alert_count": 1,
                "alerts": [
                    {
                        "call": "buy_candidate",
                        "symbol": "R_75",
                        "why": "trend continuation aligned with structure and regime",
                        "entry_area": "around 48905.54",
                    }
                ],
            }
        )

        self.assertIn("review_latest_call=buy_candidate", rendered)
        self.assertIn("review_alert_count=1", rendered)
        self.assertIn("call=buy_candidate", rendered)
        self.assertIn("entry_area=around 48905.54", rendered)

    def test_build_live_watch_review_snapshot_returns_safe_empty_state_when_no_alerts_match(self) -> None:
        journal_path = Path("journals/test_live_watch_review_empty.jsonl")
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text("", encoding="utf-8")

        snapshot = build_live_watch_review_snapshot(
            journal_path=journal_path,
            symbol="R_75",
            limit=5,
            call_filter="buy_candidate",
            valid_only=True,
        )

        self.assertEqual(snapshot["alert_count"], 0)
        self.assertEqual(snapshot["alerts"], [])
        self.assertIsNone(snapshot["latest_call"])
```

- [ ] **Step 2: Run the render tests to verify they fail**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Render summary plus recent alert trail**

Update `src/synthetic_trader/live/market_snapshot.py`:

```python
def render_live_watch_review_text(snapshot: dict[str, object]) -> str:
    ordered = [
        "latest_call",
        "latest_symbol",
        "latest_trade_status",
        "latest_direction_bias",
        "latest_regime",
        "latest_confidence",
        "latest_current_close",
        "latest_wait_for",
        "alert_count",
    ]
    lines = [
        f"review_{key}={snapshot.get(key)}"
        for key in ordered
    ]
    alerts = snapshot.get("alerts", [])
    if isinstance(alerts, list) and alerts:
        lines.append("review_recent_alerts=")
        for alert in alerts:
            lines.append(render_live_watch_alert_text(alert))
    return "\n".join(lines)
```

- [ ] **Step 4: Run the render tests to verify they pass**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests::...
```

- [ ] **Step 5: Commit the review rendering**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: render live watch review output"
```

### Task 4: Handle Missing Journal Paths And Final CLI Surface

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Write the failing missing-journal CLI test**

Add to `tests/test_live_market_snapshot.py`:

```python
class LiveWatchReviewCliFailureTests(unittest.TestCase):
    def test_live_watch_review_command_returns_non_zero_for_missing_journal(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "live-watch-review",
                    "--journal",
                    "journals/does_not_exist.jsonl",
                ]
            )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("error=journal_not_found:", rendered)
```

- [ ] **Step 2: Run the CLI failure test to verify it passes or adjust if needed**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewCliFailureTests::test_live_watch_review_command_returns_non_zero_for_missing_journal -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewCliFailureTests::...
```

If it fails because the CLI does not yet emit the expected error, fix `src/synthetic_trader/cli.py` to match the behavior shown in Task 1 Step 3, then rerun the test.

- [ ] **Step 3: Add a CLI filtering smoke test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_live_watch_review_command_forwards_filters(self) -> None:
        with patch(
            "synthetic_trader.cli.build_live_watch_review_snapshot",
            return_value={"latest_call": None, "latest_symbol": None, "latest_trade_status": None, "latest_direction_bias": None, "latest_regime": None, "latest_confidence": None, "latest_current_close": None, "latest_wait_for": None, "alert_count": 0, "alerts": []},
        ) as builder:
            exit_code = main(
                [
                    "live-watch-review",
                    "--journal",
                    "journals/live_watch_alerts.jsonl",
                    "--symbol",
                    "R_75",
                    "--limit",
                    "3",
                    "--call",
                    "buy_candidate",
                    "--valid-only",
                ]
            )

        self.assertEqual(exit_code, 0)
        builder.assert_called_once()
        self.assertEqual(builder.call_args.kwargs["symbol"], "R_75")
        self.assertEqual(builder.call_args.kwargs["limit"], 3)
        self.assertEqual(builder.call_args.kwargs["call_filter"], "buy_candidate")
        self.assertTrue(builder.call_args.kwargs["valid_only"])
```

- [ ] **Step 4: Run the CLI filter smoke test**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewCliFailureTests::test_live_watch_review_command_forwards_filters -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewCliFailureTests::...
```

- [ ] **Step 5: Commit the final review CLI behavior**

```bash
git add src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: complete live watch review cli"
```

### Task 5: Run Full Validation For Live Watch Review

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Reference: `src/synthetic_trader/live/market_snapshot.py`
- Reference: `src/synthetic_trader/cli.py`

- [ ] **Step 1: Run the full watch test file**

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

- [ ] **Step 3: Smoke-test the new review command manually**

Run:

```bash
python -m synthetic_trader.cli live-watch-review --journal journals/live_watch_alerts.jsonl --limit 3
```

Expected:

```text
review_latest_call=
review_latest_symbol=
review_alert_count=
review_recent_alerts=
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

- [ ] **Step 5: Commit the validated live watch review feature**

```bash
git add src/synthetic_trader/live/market_snapshot.py src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch review command"
```
