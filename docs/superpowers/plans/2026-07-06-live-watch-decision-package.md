# Live Watch Decision Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact summary-first decision package for valid `live-watch` alerts while keeping invalid alerts concise and preserving exact trade levels.

**Architecture:** Extend the existing watch alert payload in `live.market_snapshot` with a deterministic `decision_summary` for valid `buy_candidate` and `sell_candidate` alerts. Reuse the same alert payload and renderer for both `live-watch` and `live-watch-review` so the operator sees one consistent decision package across live monitoring and journal review.

**Tech Stack:** Python 3.11+, existing `live.market_snapshot` alert pipeline, `unittest`, `pytest`

---

## File Map

- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Add a small decision-summary helper, enrich valid alerts in `build_watch_alert()`, and render valid alerts summary-first.
- Modify: `tests/test_live_market_snapshot.py`
  - Add focused tests for valid summary inclusion, invalid summary omission, summary-first rendering, and review reuse.

### Task 1: Add Decision Summary To Valid Alert Payloads

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing valid-payload test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_build_watch_alert_includes_decision_summary_for_valid_setup(self) -> None:
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
                "current_close": 48905.54,
                "entry": 48905.54,
                "stop_loss": 48880.00,
                "take_profit": 48954.08,
                "reward_risk": 1.9,
                "entry_area": "around 48905.54",
                "stop_area": "below 48880.0",
                "target_area": "toward 48954.08",
            }
        )

        self.assertEqual(
            alert["decision_summary"],
            "buy setup valid; trend continuation aligned with structure and regime; wait for a clean bullish continuation close",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_build_watch_alert_includes_decision_summary_for_valid_setup -v
```

Expected:

```text
FAILED ... KeyError: 'decision_summary'
```

- [ ] **Step 3: Add the smallest valid decision-summary helper**

Extend `src/synthetic_trader/live/market_snapshot.py`:

```python
def build_decision_summary(alert: dict[str, object]) -> str | None:
    call = str(alert.get("call", ""))
    trade_status = str(alert.get("trade_status", ""))
    why = str(alert.get("why", "")).strip()
    wait_for = str(alert.get("wait_for", "")).strip()

    if trade_status != "valid" or call not in {"buy_candidate", "sell_candidate"}:
        return None

    direction = "buy" if call == "buy_candidate" else "sell"
    return f"{direction} setup valid; {why}; {wait_for}"
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
    decision_summary = build_decision_summary(alert)
    if decision_summary is not None:
        alert["decision_summary"] = decision_summary
    return {key: value for key, value in alert.items() if value is not None}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_build_watch_alert_includes_decision_summary_for_valid_setup -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

- [ ] **Step 5: Commit the valid summary payload**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add decision summary to valid watch alerts"
```

### Task 2: Keep Invalid Alerts Concise

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing invalid-payload omission test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_build_watch_alert_omits_decision_summary_for_invalid_setup(self) -> None:
        alert = build_watch_alert(
            {
                "call": "stand_aside",
                "symbol": "R_75",
                "briefing": "current movement is active but not a clean setup yet",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "regime": "range",
                "confidence": 0.53,
                "current_close": 48814.7626,
                "wait_for": "wait for confidence above threshold and cleaner directional agreement",
            }
        )

        self.assertNotIn("decision_summary", alert)
```

- [ ] **Step 2: Run the test to verify behavior**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_build_watch_alert_omits_decision_summary_for_invalid_setup -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

If it fails, fix `build_decision_summary()` so it returns `None` for any non-valid or non-candidate alert, then rerun the test.

- [ ] **Step 3: Commit the invalid-alert guard**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: keep invalid watch alerts concise"
```

### Task 3: Render Valid Alerts Summary-First

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing render-order test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_render_live_watch_alert_text_prints_decision_summary_before_fields(self) -> None:
        rendered = render_live_watch_alert_text(
            {
                "decision_summary": "buy setup valid; trend continuation aligned with structure and regime; wait for a clean bullish continuation close",
                "call": "buy_candidate",
                "symbol": "R_75",
                "why": "trend continuation aligned with structure and regime",
                "wait_for": "wait for a clean bullish continuation close",
                "entry_area": "around 48905.54",
                "entry": 48905.54,
            }
        )

        lines = rendered.splitlines()
        self.assertEqual(
            lines[0],
            "decision_summary=buy setup valid; trend continuation aligned with structure and regime; wait for a clean bullish continuation close",
        )
        self.assertEqual(lines[1], "call=buy_candidate")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_decision_summary_before_fields -v
```

Expected:

```text
FAILED ... AssertionError
```

- [ ] **Step 3: Move `decision_summary` to the top of valid alert rendering**

Update `render_live_watch_alert_text()` in `src/synthetic_trader/live/market_snapshot.py`:

```python
def render_live_watch_alert_text(alert: dict[str, object]) -> str:
    ordered = [
        "decision_summary",
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

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchRenderTests::test_render_live_watch_alert_text_prints_decision_summary_before_fields -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchRenderTests::...
```

- [ ] **Step 5: Commit the summary-first renderer**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: render watch decision package summary first"
```

### Task 4: Reuse The Decision Package In Review Output

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `src/synthetic_trader/live/market_snapshot.py`

- [ ] **Step 1: Write the failing review render test**

Add to `tests/test_live_market_snapshot.py`:

```python
    def test_render_live_watch_review_text_reuses_decision_summary_for_recent_valid_alert(self) -> None:
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
                        "decision_summary": "buy setup valid; trend continuation aligned with structure and regime; wait for a clean bullish continuation close",
                        "call": "buy_candidate",
                        "symbol": "R_75",
                        "why": "trend continuation aligned with structure and regime",
                        "wait_for": "wait for a clean bullish continuation close",
                    }
                ],
            }
        )

        self.assertIn(
            "decision_summary=buy setup valid; trend continuation aligned with structure and regime; wait for a clean bullish continuation close",
            rendered,
        )
```

- [ ] **Step 2: Run the review test to verify behavior**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests::test_render_live_watch_review_text_reuses_decision_summary_for_recent_valid_alert -v
```

Expected:

```text
PASSED tests/test_live_market_snapshot.py::LiveWatchReviewRenderTests::...
```

If it fails, fix `render_live_watch_review_text()` only by relying on `render_live_watch_alert_text()` for recent alerts, then rerun.

- [ ] **Step 3: Commit the shared review behavior**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: reuse watch decision package in review output"
```

### Task 5: Run Full Validation For The Decision Package

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

- [ ] **Step 3: Smoke-test the decision package with a clean watch journal**

Run:

```bash
python -m synthetic_trader.cli live-watch --symbol R_75 --warmup-count 5000 --timeframe 60 --higher-timeframe 300 --journal journals/live_watch_decision_smoke.jsonl --emit-initial --max-alerts 1
python -m synthetic_trader.cli live-watch-review --journal journals/live_watch_decision_smoke.jsonl --limit 3
```

Expected:

```text
decision_summary=
call=
symbol=
```

If the live market only produces `stand_aside`, confirm that invalid alerts still render without a `decision_summary` and that the command exits cleanly.

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

- [ ] **Step 5: Commit the validated decision package feature**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: add live watch decision package"
```
