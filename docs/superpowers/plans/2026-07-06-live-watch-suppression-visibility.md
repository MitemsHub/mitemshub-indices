# Live Watch Suppression Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `live-watch-review` so it reports suppressed context churn with counts and the latest withheld context preview, while leaving the live watch feed unchanged.

**Architecture:** Keep the current `live-watch` emitted alert payloads and renderer intact. Add a second journal record shape for cooldown-blocked material `context_update` transitions, then teach the review snapshot builder to parse mixed journal records, summarize suppression state, and render suppression fields ahead of the existing recent emitted alerts list.

**Tech Stack:** Python 3.11+, `asyncio`, `dataclasses`, `json`, `pathlib`, `unittest`, `unittest.mock`

---

## File Structure

- `src/synthetic_trader/live/market_snapshot.py`
  - Continues to own alert shaping, watch-loop journaling, journal parsing, review snapshot building, and review rendering.
  - Gains explicit helpers for suppressed-context record creation and record filtering.
- `tests/test_live_market_snapshot.py`
  - Continues to own TDD coverage for watch-loop emission behavior, journal parsing, review snapshot building, and review rendering.

### Task 1: Lock Suppressed-Record Behavior Into Failing Tests

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing review snapshot test for mixed emitted and suppressed journal records**

```python
def test_build_live_watch_review_snapshot_includes_suppressed_context_summary(self) -> None:
    journal_path = Path("journals/test_live_watch_review_suppressed.jsonl")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "call": "stand_aside",
                        "symbol": "R_75",
                        "trade_status": "not_valid",
                        "direction_bias": "sell",
                        "regime": "range",
                        "why": "bearish pressure is building but not tradeable yet",
                        "wait_for": "wait for bearish continuation confirmation",
                        "alert_type": "context_update",
                    }
                ),
                json.dumps(
                    {
                        "record_type": "suppressed_context",
                        "symbol": "R_75",
                        "call": "stand_aside",
                        "trade_status": "not_valid",
                        "direction_bias": "buy",
                        "regime": "trend_up",
                        "confidence": 0.55,
                        "why": "trend is improving but still not tradeable",
                        "wait_for": "wait for bullish continuation confirmation",
                        "alert_type": "context_update",
                        "suppression_reason": "context_cooldown_active",
                        "suppressed_after_context_cooldown": 1,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    snapshot = build_live_watch_review_snapshot(
        journal_path=journal_path,
        symbol="R_75",
        limit=5,
    )

    self.assertEqual(snapshot["alert_count"], 1)
    self.assertEqual(snapshot["suppressed_context_count"], 1)
    self.assertEqual(snapshot["latest_suppressed_direction_bias"], "buy")
    self.assertEqual(snapshot["latest_suppressed_regime"], "trend_up")
    self.assertEqual(
        snapshot["latest_suppressed_wait_for"],
        "wait for bullish continuation confirmation",
    )
```

- [ ] **Step 2: Run the focused snapshot test to verify it fails**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewSnapshotTests::test_build_live_watch_review_snapshot_includes_suppressed_context_summary -v`
Expected: FAIL with `KeyError` for `suppressed_context_count` because the snapshot builder does not yet parse suppressed records.

- [ ] **Step 3: Write the failing loop test that proves cooldown-blocked material context changes are journaled but not emitted**

```python
def test_run_live_watch_journals_suppressed_context_record_when_cooldown_blocks_emission(self) -> None:
    ticks = [
        Tick(symbol="R_75", epoch=0, price=100.0),
        Tick(symbol="R_75", epoch=61, price=100.5),
        Tick(symbol="R_75", epoch=121, price=100.7),
    ]
    snapshots = [
        {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": "none",
            "regime": "range",
            "confidence": 0.52,
            "wait_for": "wait for clearer structure",
            "briefing": "current movement is active but not a clean setup yet",
            "symbol": "R_75",
        },
        {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": "sell",
            "regime": "range",
            "confidence": 0.53,
            "wait_for": "wait for bearish continuation confirmation",
            "briefing": "bearish pressure is building but not tradeable yet",
            "symbol": "R_75",
        },
        {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": "buy",
            "regime": "trend_up",
            "confidence": 0.55,
            "wait_for": "wait for bullish continuation confirmation",
            "briefing": "trend is improving but still not tradeable",
            "symbol": "R_75",
        },
    ]
    journal_path = Path("journals/test_live_watch_suppressed_records.jsonl")
    if journal_path.exists():
        journal_path.unlink()

    with patch("synthetic_trader.live.market_snapshot.collect_live_snapshot_ticks", return_value=ticks[:1]):
        with patch("synthetic_trader.live.market_snapshot.analyze_live_snapshot", side_effect=snapshots):
            with patch("synthetic_trader.live.market_snapshot.watch_live_ticks", return_value=ticks[1:]):
                alerts = asyncio.run(
                    run_live_watch(
                        symbol="R_75",
                        warmup_count=1,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=str(journal_path),
                        max_alerts=1,
                    )
                )

    journal_lines = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    self.assertEqual(len(alerts), 1)
    self.assertEqual(alerts[0]["direction_bias"], "sell")
    self.assertEqual(len(journal_lines), 2)
    self.assertEqual(journal_lines[1]["record_type"], "suppressed_context")
    self.assertEqual(journal_lines[1]["direction_bias"], "buy")
```

- [ ] **Step 4: Run the focused loop test to verify it fails**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchLoopTests::test_run_live_watch_journals_suppressed_context_record_when_cooldown_blocks_emission -v`
Expected: FAIL because `run_live_watch()` currently suppresses the context alert without writing a journal record.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_live_market_snapshot.py
git commit -m "test: cover live watch suppression visibility"
```

### Task 2: Add Suppressed-Context Journal Helpers

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add a helper that builds suppressed-context records from an existing watch snapshot**

```python
def build_suppressed_context_record(
    snapshot: dict[str, object],
    *,
    suppressed_after_context_cooldown: int,
) -> dict[str, object]:
    record = {
        "record_type": "suppressed_context",
        "symbol": snapshot.get("symbol"),
        "call": snapshot.get("call", "stand_aside"),
        "alert_type": "context_update",
        "trade_status": snapshot.get("trade_status"),
        "direction_bias": snapshot.get("direction_bias"),
        "regime": snapshot.get("regime"),
        "confidence": snapshot.get("confidence"),
        "why": snapshot.get("why", snapshot.get("briefing")),
        "wait_for": snapshot.get("wait_for"),
        "suppression_reason": "context_cooldown_active",
        "suppressed_after_context_cooldown": suppressed_after_context_cooldown,
    }
    return {key: value for key, value in record.items() if value is not None}
```

- [ ] **Step 2: Journal the suppressed record only when a material context update is blocked by cooldown**

```python
        current_state = build_watch_state(snapshot)
        should_emit = should_emit_watch_alert(
            previous_state,
            current_state,
            context_cooldown_remaining=context_cooldown_remaining,
        )
        if should_emit:
            alert = build_watch_alert(snapshot)
            append_watch_alert(journal, alert)
            alerts.append(alert)
            if current_state.alert_type == "context_update":
                context_cooldown_remaining = DEFAULT_CONTEXT_ALERT_COOLDOWN
            previous_state = current_state
            if max_alerts is not None and len(alerts) >= max_alerts:
                break
        else:
            if (
                previous_state is not None
                and current_state.alert_type == "context_update"
                and has_material_context_change(previous_state, current_state)
                and context_cooldown_remaining > 0
            ):
                suppressed_record = build_suppressed_context_record(
                    snapshot,
                    suppressed_after_context_cooldown=context_cooldown_remaining,
                )
                append_watch_alert(journal, suppressed_record)
            previous_state = current_state
```

- [ ] **Step 3: Run the two focused tests to verify the loop behavior is now green**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "suppressed_context_record or suppression_visibility" -v`
Expected: one test still fails in review snapshot parsing, but the loop journaling test passes.

- [ ] **Step 4: Commit the journal helper implementation**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: journal suppressed live watch context"
```

### Task 3: Parse Mixed Journal Records In Review

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add a journal loader that returns emitted alerts and suppressed records separately**

```python
def load_live_watch_journal_records(
    journal_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    alerts: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []
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
        elif payload.get("call") is not None and payload.get("symbol") is not None:
            alerts.append(payload)
    return alerts, suppressed


def load_live_watch_alerts(journal_path: Path) -> list[dict[str, object]]:
    alerts, _suppressed = load_live_watch_journal_records(journal_path)
    return alerts
```

- [ ] **Step 2: Add a focused filter helper for suppressed context records**

```python
def filter_suppressed_context_records(
    records: list[dict[str, object]],
    *,
    symbol: str | None = None,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> list[dict[str, object]]:
    filtered = list(records)
    if symbol is not None:
        filtered = [record for record in filtered if record.get("symbol") == symbol]
    if call_filter is not None:
        filtered = [record for record in filtered if record.get("call") == call_filter]
    if valid_only:
        return []
    return filtered
```

- [ ] **Step 3: Extend `build_live_watch_review_snapshot()` with suppression summary fields**

```python
def build_live_watch_review_snapshot(
    *,
    journal_path: Path,
    symbol: str | None = None,
    limit: int = 5,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> dict[str, object]:
    alerts, suppressed = load_live_watch_journal_records(journal_path)
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
    recent = list(reversed(filtered[-max(limit, 0) :]))
    latest = filtered[-1] if filtered else {}
    latest_suppressed = filtered_suppressed[-1] if filtered_suppressed else {}
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
        "alerts": recent,
    }
```

- [ ] **Step 4: Run the focused snapshot test to verify parsing and filtering pass**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewSnapshotTests::test_build_live_watch_review_snapshot_includes_suppressed_context_summary -v`
Expected: PASS

- [ ] **Step 5: Commit the mixed-record review parser**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: parse suppressed live watch review records"
```

### Task 4: Render Suppression Summary In Review Output

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing review renderer tests for suppression summary fields**

```python
def test_render_live_watch_review_text_prints_suppression_summary(self) -> None:
    rendered = render_live_watch_review_text(
        {
            "latest_call": "stand_aside",
            "latest_symbol": "R_75",
            "latest_trade_status": "not_valid",
            "latest_direction_bias": "sell",
            "latest_regime": "range",
            "latest_confidence": 0.53,
            "latest_current_close": 48479.24,
            "latest_wait_for": "wait for bearish continuation confirmation",
            "alert_count": 1,
            "suppressed_context_count": 2,
            "latest_suppressed_direction_bias": "buy",
            "latest_suppressed_regime": "trend_up",
            "latest_suppressed_why": "trend is improving but still not tradeable",
            "latest_suppressed_wait_for": "wait for bullish continuation confirmation",
            "alerts": [],
        }
    )

    self.assertIn("review_suppressed_context_count=2", rendered)
    self.assertIn("review_latest_suppressed_direction_bias=buy", rendered)
    self.assertIn("review_latest_suppressed_regime=trend_up", rendered)
    self.assertIn("review_latest_suppressed_why=trend is improving but still not tradeable", rendered)
```

- [ ] **Step 2: Run the renderer test to verify it fails**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests::test_render_live_watch_review_text_prints_suppression_summary -v`
Expected: FAIL because the review renderer does not yet output suppression lines.

- [ ] **Step 3: Extend `render_live_watch_review_text()` to print suppression summary before recent emitted alerts**

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
    ]
    lines = [f"review_{key}={snapshot.get(key)}" for key in ordered]
    alerts = snapshot.get("alerts", [])
    if isinstance(alerts, list) and alerts:
        lines.append("review_recent_alerts=")
        for alert in alerts:
            lines.append(render_live_watch_alert_text(alert))
    return "\n".join(lines)
```

- [ ] **Step 4: Run the review-focused tests**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "suppression_summary or LiveWatchReview" -v`
Expected: PASS

- [ ] **Step 5: Commit the review rendering changes**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: surface suppressed watch context in review"
```

### Task 5: Full Verification And Diagnostics

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add one compatibility test that `valid-only` leaves suppressed count at zero**

```python
def test_build_live_watch_review_snapshot_valid_only_zeros_suppressed_context_count(self) -> None:
    journal_path = Path("journals/test_live_watch_review_valid_only_suppressed.jsonl")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "record_type": "suppressed_context",
                        "symbol": "R_75",
                        "call": "stand_aside",
                        "trade_status": "not_valid",
                        "direction_bias": "buy",
                        "regime": "trend_up",
                        "why": "trend is improving but still not tradeable",
                        "wait_for": "wait for bullish continuation confirmation",
                    }
                ),
                json.dumps(
                    {
                        "call": "buy_candidate",
                        "symbol": "R_75",
                        "trade_status": "valid",
                        "direction_bias": "buy",
                        "regime": "trend_up",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    snapshot = build_live_watch_review_snapshot(
        journal_path=journal_path,
        symbol="R_75",
        valid_only=True,
    )

    self.assertEqual(snapshot["alert_count"], 1)
    self.assertEqual(snapshot["suppressed_context_count"], 0)
```

- [ ] **Step 2: Run the full live market snapshot test module**

Run: `python -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 3: Run targeted diagnostics on edited files**

Run diagnostics for:
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`

Expected: no new errors introduced.

- [ ] **Step 4: Optional bounded read-only smoke**

Run: `python -m synthetic_trader.cli live-watch --symbol R_75 --emit-initial --max-minutes 0 --max-alerts 1 --journal journals/live_watch_suppression_visibility_smoke.jsonl`
Expected: one emitted baseline alert and no crashes. Review can then inspect the same journal with `live-watch-review`.

- [ ] **Step 5: Commit the verification pass**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "test: verify live watch suppression visibility"
```
