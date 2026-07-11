# Live Watch Alert Type Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `alert_type` to live watch alerts so operators can instantly distinguish actionable setup alerts from non-actionable context updates while preserving the current decision package for valid setups.

**Architecture:** Extend the existing `build_watch_alert()` payload path with a deterministic `alert_type` classification and update the shared alert renderer to display it in stable order. Reuse the same alert payload and renderer for `live-watch` and `live-watch-review` so the split remains consistent across live monitoring and journal review.

**Tech Stack:** Python 3.11+, existing `live.market_snapshot` alert pipeline, `unittest`, `pytest`

---

## File Map

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Add alert-type classification and render ordering.
- Modify: `tests/test_live_market_snapshot.py`
  - Add focused tests for valid vs context classification and shared rendering behavior.

### Task 1: Classify Valid Alerts As `setup_candidate`

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing valid classification test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_build_watch_alert_marks_valid_setup_as_setup_candidate(self) -> None:
        alert = build_watch_alert(
            {
                "call": "buy_candidate",
                "symbol": "R_75",
                "briefing": "trend continuation aligned with structure and regime",
                "wait_for": "wait for a clean bullish continuation close",
                "trade_status": "valid",
                "direction_bias": "buy",
                "regime": "trend_up",
                "confidence": 0.66,
            }
        )

        self.assertEqual(alert["alert_type"], "setup_candidate")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_build_watch_alert_marks_valid_setup_as_setup_candidate -v
```

Expected:

```text
FAILED ... KeyError: 'alert_type'
```

- [ ] **Step 3: Add the smallest alert-type classifier**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
def classify_alert_type(alert: dict[str, object]) -> str:
    call = str(alert.get("call", ""))
    trade_status = str(alert.get("trade_status", ""))
    if trade_status == "valid" and call in {"buy_candidate", "sell_candidate"}:
        return "setup_candidate"
    return "context_update"
```

Update `build_watch_alert()`:

```python
    alert = {
        "call": snapshot.get("call", "stand_aside"),
        "symbol": snapshot.get("symbol"),
        "why": snapshot.get("why", snapshot.get("briefing")),
        "wait_for": snapshot.get("wait_for"),
        "trade_status": snapshot.get("trade_status"),
        "direction_bias": snapshot.get("direction_bias"),
        "regime": snapshot.get("regime"),
        "confidence": snapshot.get("confidence"),
        "current_close": snapshot.get("current_close"),
        "reasons": snapshot.get("reasons"),
        "entry_area": snapshot.get("entry_area"),
        "stop_area": snapshot.get("stop_area"),
        "target_area": snapshot.get("target_area"),
        "entry": snapshot.get("entry"),
        "stop_loss": snapshot.get("stop_loss"),
        "take_profit": snapshot.get("take_profit"),
        "reward_risk": snapshot.get("reward_risk"),
    }
    alert["alert_type"] = classify_alert_type(alert)
    decision_summary = build_decision_summary(alert)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_build_watch_alert_marks_valid_setup_as_setup_candidate -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

- [ ] **Step 5: Commit the valid alert classification**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: classify valid watch alerts as setup candidates"
```

### Task 2: Classify Non-Actionable Alerts As `context_update`

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing context classification test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_build_watch_alert_marks_non_actionable_setup_as_context_update(self) -> None:
        alert = build_watch_alert(
            {
                "call": "stand_aside",
                "symbol": "R_75",
                "briefing": "current movement is active but not a clean setup yet",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "regime": "range",
                "confidence": 0.53,
                "wait_for": "wait for confidence above threshold and cleaner directional agreement",
            }
        )

        self.assertEqual(alert["alert_type"], "context_update")
```

- [ ] **Step 2: Run the test to verify behavior**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_build_watch_alert_marks_non_actionable_setup_as_context_update -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

If it fails, fix `classify_alert_type()` so any non-valid or non-candidate alert returns `context_update`, then rerun.

- [ ] **Step 3: Commit the context classification**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: classify context watch alerts explicitly"
```

### Task 3: Render `alert_type` In The Correct Order

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing valid render-order test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_render_live_watch_alert_text_prints_alert_type_after_decision_summary_for_valid_setup(self) -> None:
        rendered = render_live_watch_alert_text(
            {
                "decision_summary": "buy setup valid; trend continuation aligned with structure and regime; wait for a clean bullish continuation close",
                "alert_type": "setup_candidate",
                "call": "buy_candidate",
                "symbol": "R_75",
                "why": "trend continuation aligned with structure and regime",
                "wait_for": "wait for a clean bullish continuation close",
            }
        )

        lines = rendered.splitlines()
        self.assertEqual(lines[0].startswith("decision_summary="), True)
        self.assertEqual(lines[1], "alert_type=setup_candidate")
        self.assertEqual(lines[2], "call=buy_candidate")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_alert_type_after_decision_summary_for_valid_setup -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Write the failing context render-order test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_render_live_watch_alert_text_prints_alert_type_first_for_context_update(self) -> None:
        rendered = render_live_watch_alert_text(
            {
                "alert_type": "context_update",
                "call": "stand_aside",
                "symbol": "R_75",
                "why": "current movement is active but not a clean setup yet",
                "wait_for": "wait for confidence above threshold and cleaner directional agreement",
            }
        )

        lines = rendered.splitlines()
        self.assertEqual(lines[0], "alert_type=context_update")
        self.assertEqual(lines[1], "call=stand_aside")
```

- [ ] **Step 4: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_alert_type_first_for_context_update -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 5: Update the shared renderer ordering**

Update `render_live_watch_alert_text()` in `src/synthetic_trader/live/market_snapshot.py`:

```python
def render_live_watch_alert_text(alert: dict[str, object]) -> str:
    ordered = [
        "decision_summary",
        "alert_type",
        "call",
        "symbol",
        "why",
        "wait_for",
        "entry_area",
        "stop_area",
        "target_area",
        "entry",
        "stop_loss",
        "take_profit",
        "reward_risk",
        "trade_status",
        "direction_bias",
        "regime",
        "confidence",
        "current_close",
        "reasons",
    ]
    return "\n".join(f"{key}={alert.get(key)}" for key in ordered if key in alert)
```

- [ ] **Step 6: Run both render-order tests to verify they pass**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_alert_type_after_decision_summary_for_valid_setup tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_alert_type_first_for_context_update -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

- [ ] **Step 7: Commit the alert-type renderer**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: render watch alert type explicitly"
```

### Task 4: Reuse `alert_type` In Watch Review Output

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing review render test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_render_live_watch_review_text_reuses_alert_type_for_recent_alerts(self) -> None:
        rendered = render_live_watch_review_text(
            {
                "latest_call": "sell_candidate",
                "latest_symbol": "R_75",
                "latest_trade_status": "valid",
                "latest_direction_bias": "sell",
                "latest_regime": "trend_down",
                "latest_confidence": 0.635,
                "latest_current_close": 48479.2421,
                "latest_wait_for": "wait for a clean bearish continuation close",
                "alert_count": 1,
                "alerts": [
                    {
                        "decision_summary": "sell setup valid; short setup in trend_down regime; confidence=0.635; wait for a clean bearish continuation close",
                        "alert_type": "setup_candidate",
                        "call": "sell_candidate",
                        "symbol": "R_75",
                        "why": "short setup in trend_down regime; confidence=0.635",
                        "wait_for": "wait for a clean bearish continuation close",
                    }
                ],
            }
        )

        self.assertIn("alert_type=setup_candidate", rendered)
```

- [ ] **Step 2: Run the review test to verify behavior**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests::test_render_live_watch_review_text_reuses_alert_type_for_recent_alerts -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests::...
```

If it fails, fix `render_live_watch_review_text()` only by ensuring it continues to rely on `render_live_watch_alert_text()` for recent alerts, then rerun.

- [ ] **Step 3: Commit the shared review behavior**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: reuse watch alert type in review output"
```

### Task 5: Run Full Validation For Alert-Type Split

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Reference: `src/synthetic_trader/live/market_snapshot.py`

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

- [ ] **Step 3: Smoke-test the split with a clean watch journal**

Run:

```bash
python -m synthetic_trader.cli live-watch --symbol R_75 --warmup-count 5000 --timeframe 60 --higher-timeframe 300 --journal journals/live_watch_alert_type_smoke.jsonl --emit-initial --max-alerts 1
python -m synthetic_trader.cli live-watch-review --journal journals/live_watch_alert_type_smoke.jsonl --limit 3
```

Expected:

```text
alert_type=
call=
symbol=
```

If the live market yields a valid setup, confirm `alert_type=setup_candidate`.
If the live market yields a non-actionable alert, confirm `alert_type=context_update`.

- [ ] **Step 4: Review diagnostics on modified files**

Review diagnostics for:

```text
src/synthetic_trader/live/market_snapshot.py
tests/test_live_market_snapshot.py
```

Expected:

```text
No new syntax or import errors.
```

- [ ] **Step 5: Commit the validated alert-type split**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: split watch setup alerts from context updates"
```
