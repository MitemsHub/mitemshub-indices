# Live Watch Default Operator Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `live-watch` the clear default read-only operator call surface for `R_100` and extend `live-watch-review` so it shows transport/reconnect visibility alongside emitted alerts and suppressed context.

**Architecture:** Keep the existing single-journal design. Extend `market_snapshot.py` so journal loading separates three record families: emitted alerts, suppressed context records, and `watch_transport` records. Reuse the existing `live-watch-review` snapshot/renderer path to surface a compact transport summary without changing the meaning of the recent emitted-alert list, and tighten CLI help text so the operator workflow is explicit without creating a new command.

**Tech Stack:** Python 3.11+, `json`, `pathlib`, `unittest`, `unittest.mock`, existing CLI + live watch helpers

---

## File Structure

- `src/synthetic_trader/live/market_snapshot.py`
  - Extend journal parsing to return transport records.
  - Add transport filtering helpers.
  - Extend `build_live_watch_review_snapshot()` with transport summary fields.
  - Extend `render_live_watch_review_text()` with a transport summary section.
- `src/synthetic_trader/cli.py`
  - Update `live-watch` and `live-watch-review` help text so they read as the default operator workflow.
  - Keep the existing handler flow unchanged apart from the stronger wording.
- `tests/test_live_market_snapshot.py`
  - Add focused tests for transport-aware review snapshot building, rendering, and CLI review output.

### Task 1: Lock Transport Review Behavior Into Failing Tests

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add a failing snapshot test that keeps transport visible under `valid_only`**

```python
def test_build_live_watch_review_snapshot_keeps_transport_visibility_under_valid_only(self) -> None:
    journal_path = Path("journals/test_live_watch_review_transport.jsonl")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "call": "buy_candidate",
                        "symbol": "R_100",
                        "trade_status": "valid",
                        "direction_bias": "buy",
                        "regime": "trend_up",
                    }
                ),
                json.dumps(
                    {
                        "record_type": "suppressed_context",
                        "symbol": "R_100",
                        "call": "stand_aside",
                        "trade_status": "not_valid",
                        "direction_bias": "sell",
                        "regime": "range",
                        "why": "context churn during cooldown",
                        "wait_for": "wait for clearer structure",
                        "alert_type": "context_update",
                        "suppression_reason": "context_cooldown_active",
                        "suppressed_after_context_cooldown": 1,
                    }
                ),
                json.dumps(
                    {
                        "record_type": "watch_transport",
                        "symbol": "R_100",
                        "event": "reconnect_rebaseline_ok",
                        "reason": "baseline rebuilt after reconnect",
                        "attempt": 1,
                        "regime": "trend_up",
                        "direction_bias": "buy",
                        "trade_status": "not_valid",
                        "confidence": 0.58,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    snapshot = build_live_watch_review_snapshot(
        journal_path=journal_path,
        symbol="R_100",
        limit=5,
        call_filter="buy_candidate",
        valid_only=True,
    )

    self.assertEqual(snapshot["alert_count"], 1)
    self.assertEqual(snapshot["suppressed_context_count"], 0)
    self.assertEqual(snapshot["transport_event_count"], 1)
    self.assertEqual(snapshot["latest_transport_event"], "reconnect_rebaseline_ok")
    self.assertEqual(snapshot["latest_transport_direction_bias"], "buy")
```

- [ ] **Step 2: Add a failing renderer test for the new transport summary section**

```python
def test_render_live_watch_review_text_prints_transport_summary(self) -> None:
    rendered = render_live_watch_review_text(
        {
            "latest_call": "buy_candidate",
            "latest_symbol": "R_100",
            "latest_trade_status": "valid",
            "latest_direction_bias": "buy",
            "latest_regime": "trend_up",
            "latest_confidence": 0.64,
            "latest_current_close": 51234.6,
            "latest_wait_for": "wait for a clean bullish continuation close",
            "alert_count": 1,
            "suppressed_context_count": 0,
            "transport_event_count": 2,
            "latest_transport_event": "reconnect_rebaseline_ok",
            "latest_transport_reason": "baseline rebuilt after reconnect",
            "latest_transport_attempt": 2,
            "latest_transport_attempts": None,
            "latest_transport_regime": "trend_up",
            "latest_transport_direction_bias": "buy",
            "latest_transport_trade_status": "not_valid",
            "latest_transport_confidence": 0.58,
            "alerts": [],
        }
    )

    self.assertIn("review_transport_event_count=2", rendered)
    self.assertIn("review_latest_transport_event=reconnect_rebaseline_ok", rendered)
    self.assertIn("review_latest_transport_reason=baseline rebuilt after reconnect", rendered)
    self.assertIn("review_latest_transport_direction_bias=buy", rendered)
```

- [ ] **Step 3: Add a failing CLI review test that prints transport visibility**

```python
def test_live_watch_review_command_prints_transport_summary(self) -> None:
    snapshot = {
        "latest_call": "buy_candidate",
        "latest_symbol": "R_100",
        "latest_trade_status": "valid",
        "latest_direction_bias": "buy",
        "latest_regime": "trend_up",
        "latest_confidence": 0.66,
        "latest_current_close": 51234.6,
        "latest_wait_for": "wait for a clean bullish continuation close",
        "alert_count": 1,
        "suppressed_context_count": 0,
        "transport_event_count": 1,
        "latest_transport_event": "reconnect_attempt",
        "latest_transport_reason": "client is not connected",
        "latest_transport_attempt": 1,
        "latest_transport_attempts": None,
        "latest_transport_regime": None,
        "latest_transport_direction_bias": None,
        "latest_transport_trade_status": None,
        "latest_transport_confidence": None,
        "alerts": [],
    }
    journal_path = Path("journals/test_live_watch_review_transport_cli.jsonl")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text("{}", encoding="utf-8")

    with patch("synthetic_trader.cli.build_live_watch_review_snapshot", return_value=snapshot):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "live-watch-review",
                    "--journal",
                    str(journal_path),
                    "--symbol",
                    "R_100",
                ]
            )

    rendered = output.getvalue()
    self.assertEqual(exit_code, 0)
    self.assertIn("review_transport_event_count=1", rendered)
    self.assertIn("review_latest_transport_event=reconnect_attempt", rendered)
```

- [ ] **Step 4: Run the focused review tests to verify they fail**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "transport_summary or keeps_transport_visibility" -v`
Expected: FAIL because the current review snapshot does not expose transport fields and the renderer does not print them.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_live_market_snapshot.py
git commit -m "test: cover live watch transport review"
```

### Task 2: Add Transport Parsing And Snapshot Fields

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Extend `load_live_watch_journal_records()` to return transport records**

```python
def load_live_watch_journal_records(
    journal_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    alerts: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []
    transport: list[dict[str, object]] = []
    for index, line in enumerate(journal_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid journal JSON at line {index}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            continue
        record_type = payload.get("record_type")
        if record_type == "suppressed_context" and payload.get("symbol") is not None:
            suppressed.append(payload)
        elif record_type == "watch_transport" and payload.get("symbol") is not None:
            transport.append(payload)
        elif payload.get("call") is not None and payload.get("symbol") is not None:
            alerts.append(payload)
    return alerts, suppressed, transport
```

- [ ] **Step 2: Add a dedicated transport filter helper**

```python
def filter_watch_transport_records(
    records: list[dict[str, object]],
    *,
    symbol: str | None = None,
) -> list[dict[str, object]]:
    filtered = list(records)
    if symbol is not None:
        filtered = [record for record in filtered if record.get("symbol") == symbol]
    return filtered
```

- [ ] **Step 3: Extend `build_live_watch_review_snapshot()` with transport summary fields**

```python
def build_live_watch_review_snapshot(
    *,
    journal_path: Path,
    symbol: str | None = None,
    limit: int = 5,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> dict[str, object]:
    alerts, suppressed, transport = load_live_watch_journal_records(journal_path)
    filtered = filter_live_watch_alerts(
        alerts,
        symbol=symbol,
        call_filter=call_filter,
        valid_only=valid_only,
    )
    filtered_suppressed = filter_suppressed_context_records(
        suppressed,
        symbol=symbol,
        call_filter=call_filter,
        valid_only=valid_only,
    )
    filtered_transport = filter_watch_transport_records(transport, symbol=symbol)
    recent = list(reversed(filtered[-max(limit, 0) :]))
    latest = filtered[-1] if filtered else {}
    latest_suppressed = filtered_suppressed[-1] if filtered_suppressed else {}
    latest_transport = filtered_transport[-1] if filtered_transport else {}
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
        "suppressed_context_count": len(filtered_suppressed),
        "latest_suppressed_symbol": latest_suppressed.get("symbol"),
        "latest_suppressed_call": latest_suppressed.get("call"),
        "latest_suppressed_direction_bias": latest_suppressed.get("direction_bias"),
        "latest_suppressed_regime": latest_suppressed.get("regime"),
        "latest_suppressed_why": latest_suppressed.get("why"),
        "latest_suppressed_wait_for": latest_suppressed.get("wait_for"),
        "latest_suppressed_confidence": latest_suppressed.get("confidence"),
        "transport_event_count": len(filtered_transport),
        "latest_transport_event": latest_transport.get("event"),
        "latest_transport_reason": latest_transport.get("reason"),
        "latest_transport_attempt": latest_transport.get("attempt"),
        "latest_transport_attempts": latest_transport.get("attempts"),
        "latest_transport_regime": latest_transport.get("regime"),
        "latest_transport_direction_bias": latest_transport.get("direction_bias"),
        "latest_transport_trade_status": latest_transport.get("trade_status"),
        "latest_transport_confidence": latest_transport.get("confidence"),
        "alerts": recent,
    }
```

- [ ] **Step 4: Keep `load_live_watch_alerts()` compatible with the new tuple shape**

```python
def load_live_watch_alerts(journal_path: Path) -> list[dict[str, object]]:
    alerts, _suppressed, _transport = load_live_watch_journal_records(journal_path)
    return alerts
```

- [ ] **Step 5: Run the transport snapshot test**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewSnapshotTests::test_build_live_watch_review_snapshot_keeps_transport_visibility_under_valid_only -v`
Expected: PASS

- [ ] **Step 6: Commit the transport snapshot implementation**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add transport visibility to live watch review snapshot"
```

### Task 3: Render Transport Summary And Clarify Operator Workflow

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Modify: `src/synthetic_trader/cli.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Extend `render_live_watch_review_text()` with transport lines**

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
        "suppressed_context_count",
        "latest_suppressed_direction_bias",
        "latest_suppressed_regime",
        "latest_suppressed_why",
        "latest_suppressed_wait_for",
        "transport_event_count",
        "latest_transport_event",
        "latest_transport_reason",
        "latest_transport_attempt",
        "latest_transport_attempts",
        "latest_transport_regime",
        "latest_transport_direction_bias",
        "latest_transport_trade_status",
        "latest_transport_confidence",
    ]
    lines = [f"review_{key}={snapshot.get(key)}" for key in ordered]
    alerts = snapshot.get("alerts", [])
    if isinstance(alerts, list) and alerts:
        lines.append("review_recent_alerts=")
        for alert in alerts:
            lines.append(render_live_watch_alert_text(alert))
    return "\n".join(lines)
```

- [ ] **Step 2: Update parser help text so the operator workflow is explicit**

```python
    live_watch = subparsers.add_parser(
        "live-watch",
        help="monitor a symbol and emit read-only operator calls on meaningful change",
    )
```

```python
    live_watch_review = subparsers.add_parser(
        "live-watch-review",
        help="review live-watch calls, suppression, and transport health from the journal",
    )
```

- [ ] **Step 3: Run the renderer and CLI transport tests**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "prints_transport_summary" -v`
Expected: PASS

- [ ] **Step 4: Run the full live-watch test module**

Run: `python -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: Commit the review rendering and CLI wording**

```bash
git add src/synthetic_trader/live/market_snapshot.py src/synthetic_trader/cli.py tests/test_live_market_snapshot.py
git commit -m "feat: clarify live watch operator workflow"
```

### Task 4: Final Verification

**Files:**
- Modify: none
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Run the focused repo checks for this feature**

Run: `python -m pytest tests/test_live_market_snapshot.py tests/test_phase16_supervised_rollout.py -v`
Expected: PASS with no regressions in live-watch review behavior or rollout-related CLI wiring.

- [ ] **Step 2: Smoke-check the review surface with a real journal file**

Run: `python -m synthetic_trader.cli live-watch-review --journal journals/live_watch_reconnect_smoke.jsonl --symbol R_100`
Expected: Output includes:
- `review_transport_event_count=...`
- `review_latest_transport_event=...`
- existing `review_alert_count=...`

- [ ] **Step 3: Commit the verification checkpoint**

```bash
git add docs/superpowers/plans/2026-07-09-live-watch-default-operator-interface.md
git commit -m "docs: add live watch operator interface plan"
```
