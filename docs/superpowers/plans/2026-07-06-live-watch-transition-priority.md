# Live Watch Transition Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `live-watch` emit actionable setup transitions immediately while suppressing repeated low-value `context_update` churn with a short candle-close cooldown.

**Architecture:** Keep the current snapshot, payload, journal, and renderer surfaces unchanged. Extend the internal watch transition model in `market_snapshot.py` so emission decisions become alert-type-aware: setup alerts bypass cooldown, while context alerts require a material context change and a satisfied cooldown window measured in primary candle-close opportunities.

**Tech Stack:** Python 3.11+, `asyncio`, `dataclasses`, `unittest`, `unittest.mock`

---

## File Structure

- `src/synthetic_trader/live/market_snapshot.py`
  - Owns watch-state modeling, alert shaping, transition decisions, and the live watch loop.
  - Gains small internal helpers for material context comparison and context cooldown tracking.
- `tests/test_live_market_snapshot.py`
  - Owns TDD coverage for watch transitions, loop emission behavior, and renderer/review compatibility.

### Task 1: Lock Priority Rules Into Transition Tests

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing transition tests for setup priority and context cooldown**

```python
class LiveWatchTransitionPriorityTests(unittest.TestCase):
    def test_should_emit_watch_alert_allows_setup_candidate_immediately(self) -> None:
        previous = build_watch_state(
            {
                "call": "stand_aside",
                "trade_status": "not_valid",
                "direction_bias": "sell",
                "regime": "trend_down",
                "confidence": 0.51,
                "wait_for": "wait for cleaner bearish continuation",
            }
        )
        current = build_watch_state(
            {
                "call": "sell_candidate",
                "trade_status": "valid",
                "direction_bias": "sell",
                "regime": "trend_down",
                "confidence": 0.64,
                "wait_for": "wait for a clean bearish continuation close",
            }
        )

        self.assertTrue(
            should_emit_watch_alert(
                previous,
                current,
                context_cooldown_remaining=2,
            )
        )

    def test_should_emit_watch_alert_suppresses_context_update_inside_cooldown(self) -> None:
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
                "direction_bias": "sell",
                "regime": "range",
                "confidence": 0.53,
                "wait_for": "wait for bearish continuation confirmation",
            }
        )

        self.assertFalse(
            should_emit_watch_alert(
                previous,
                current,
                context_cooldown_remaining=1,
            )
        )

    def test_should_emit_watch_alert_allows_material_context_change_outside_cooldown(self) -> None:
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
                "direction_bias": "buy",
                "regime": "trend_up",
                "confidence": 0.53,
                "wait_for": "wait for bullish continuation confirmation",
            }
        )

        self.assertTrue(
            should_emit_watch_alert(
                previous,
                current,
                context_cooldown_remaining=0,
            )
        )
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "TransitionPriority or should_emit_watch_alert" -v`
Expected: FAIL with `TypeError` for the new `context_cooldown_remaining` argument and missing priority behavior.

- [ ] **Step 3: Add one loop-level failing test that proves setup alerts bypass an active context cooldown**

```python
def test_run_live_watch_emits_setup_candidate_even_when_context_cooldown_is_active(self) -> None:
    ticks = [
        Tick(symbol="R_75", epoch=0, price=100.0),
        Tick(symbol="R_75", epoch=61, price=100.5),
        Tick(symbol="R_75", epoch=121, price=101.0),
        Tick(symbol="R_75", epoch=181, price=101.4),
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
            "regime": "trend_down",
            "confidence": 0.53,
            "wait_for": "wait for bearish continuation confirmation",
            "briefing": "bearish pressure is building but not tradeable yet",
            "symbol": "R_75",
        },
        {
            "call": "sell_candidate",
            "trade_status": "valid",
            "direction_bias": "sell",
            "regime": "trend_down",
            "confidence": 0.64,
            "wait_for": "wait for a clean bearish continuation close",
            "briefing": "short setup in trend_down regime; confidence=0.64",
            "symbol": "R_75",
        },
    ]

    with patch("synthetic_trader.live.market_snapshot.collect_live_snapshot_ticks", return_value=ticks[:1]):
        with patch("synthetic_trader.live.market_snapshot.analyze_live_snapshot", side_effect=snapshots):
            with patch("synthetic_trader.live.market_snapshot.watch_live_ticks", return_value=ticks[1:]):
                alerts = asyncio.run(
                    run_live_watch(
                        symbol="R_75",
                        warmup_count=1,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path="journals/test_live_watch_priority.jsonl",
                        max_alerts=2,
                    )
                )

    self.assertEqual([alert["alert_type"] for alert in alerts], ["context_update", "setup_candidate"])
    self.assertEqual(alerts[-1]["call"], "sell_candidate")
```

- [ ] **Step 4: Run the loop-level test to verify it fails**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveWatchLoopTests::test_run_live_watch_emits_setup_candidate_even_when_context_cooldown_is_active -v`
Expected: FAIL because `run_live_watch()` does not track or apply context cooldown state yet.

- [ ] **Step 5: Commit the red tests**

```bash
git add tests/test_live_market_snapshot.py
git commit -m "test: cover live watch transition priority"
```

### Task 2: Implement Alert-Type-Aware Transition Helpers

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Extend `WatchState` with the current `alert_type` and a material-context view**

```python
@dataclass(frozen=True)
class WatchState:
    call: str
    alert_type: str
    trade_status: str
    direction_bias: str
    regime: str
    confidence_bucket: str
    wait_for: str


def build_watch_state(snapshot: dict[str, object]) -> WatchState:
    confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    if confidence >= 0.58:
        bucket = "above_threshold"
    elif confidence >= 0.50:
        bucket = "near_threshold"
    else:
        bucket = "low_confidence"

    alert_type = str(snapshot.get("alert_type", ""))
    if not alert_type:
        alert_type = classify_alert_type(snapshot)

    return WatchState(
        call=str(snapshot.get("call", "stand_aside")),
        alert_type=alert_type,
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        regime=str(snapshot.get("regime", "unknown")),
        confidence_bucket=bucket,
        wait_for=str(snapshot.get("wait_for", "")),
    )
```

- [ ] **Step 2: Add focused helpers for material context change and cooldown-aware emission**

```python
DEFAULT_CONTEXT_ALERT_COOLDOWN = 2


def has_material_context_change(previous: WatchState, current: WatchState) -> bool:
    return (
        previous.regime != current.regime
        or previous.direction_bias != current.direction_bias
        or previous.trade_status != current.trade_status
        or previous.wait_for != current.wait_for
    )


def should_emit_watch_alert(
    previous: WatchState | None,
    current: WatchState,
    *,
    context_cooldown_remaining: int = 0,
) -> bool:
    if previous is None:
        return False
    if previous == current:
        return False
    if current.alert_type == "setup_candidate":
        return True
    if not has_material_context_change(previous, current):
        return False
    return context_cooldown_remaining <= 0
```

- [ ] **Step 3: Run the transition-priority tests to verify the helper implementation passes**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "TransitionPriority or should_emit_watch_alert" -v`
Expected: PASS

- [ ] **Step 4: Commit the helper implementation**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: prioritize live watch setup transitions"
```

### Task 3: Apply Cooldown State Inside The Watch Loop

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add loop state for context cooldown and decrement it on each primary candle-close evaluation**

```python
context_cooldown_remaining = 0

for tick in await watch_live_ticks(symbol=symbol, app_id=app_id, max_minutes=max_minutes):
    buffer.append(tick)
    bucket = int(tick.epoch // timeframe_sec) * timeframe_sec
    previous_bucket = int(buffer[-2].epoch // timeframe_sec) * timeframe_sec if len(buffer) > 1 else bucket
    if bucket == previous_bucket:
        continue

    if context_cooldown_remaining > 0:
        context_cooldown_remaining -= 1

    snapshot = analyze_live_snapshot(
        symbol=symbol,
        ticks=buffer,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        config=TraderConfig.default(),
    )
    current_state = build_watch_state(snapshot)
```

- [ ] **Step 2: Emit setup alerts immediately, but reset cooldown only when a context alert is actually emitted**

```python
if should_emit_watch_alert(
    previous_state,
    current_state,
    context_cooldown_remaining=context_cooldown_remaining,
):
    alert = build_watch_alert(snapshot)
    append_watch_alert(journal, alert)
    alerts.append(alert)
    if current_state.alert_type == "context_update":
        context_cooldown_remaining = DEFAULT_CONTEXT_ALERT_COOLDOWN
    previous_state = current_state
    if max_alerts is not None and len(alerts) >= max_alerts:
        break
else:
    previous_state = current_state
```

- [ ] **Step 3: Add one more loop-level test for context suppression and later re-emission**

```python
def test_run_live_watch_suppresses_context_updates_inside_cooldown_and_re_emits_after_expiry(self) -> None:
    ticks = [
        Tick(symbol="R_75", epoch=0, price=100.0),
        Tick(symbol="R_75", epoch=61, price=100.5),
        Tick(symbol="R_75", epoch=121, price=100.7),
        Tick(symbol="R_75", epoch=181, price=101.0),
        Tick(symbol="R_75", epoch=241, price=101.3),
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
            "regime": "range",
            "confidence": 0.54,
            "wait_for": "wait for bullish continuation confirmation",
            "briefing": "bullish pressure is building but not tradeable yet",
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

    with patch("synthetic_trader.live.market_snapshot.collect_live_snapshot_ticks", return_value=ticks[:1]):
        with patch("synthetic_trader.live.market_snapshot.analyze_live_snapshot", side_effect=snapshots):
            with patch("synthetic_trader.live.market_snapshot.watch_live_ticks", return_value=ticks[1:]):
                alerts = asyncio.run(
                    run_live_watch(
                        symbol="R_75",
                        warmup_count=1,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path="journals/test_live_watch_context_cooldown.jsonl",
                        max_alerts=2,
                    )
                )

    self.assertEqual(len(alerts), 2)
    self.assertEqual(alerts[0]["direction_bias"], "sell")
    self.assertEqual(alerts[1]["regime"], "trend_up")
```

- [ ] **Step 4: Run the focused loop tests**

Run: `python -m pytest tests/test_live_market_snapshot.py -k "cooldown or setup_candidate_even_when_context_cooldown_is_active or evaluates_on_primary_candle_close" -v`
Expected: PASS

- [ ] **Step 5: Commit the loop-state implementation**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: suppress noisy live watch context churn"
```

### Task 4: Prove Review Compatibility And Finish Verification

**Files:**
- Modify: `tests/test_live_market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Add a review compatibility test that uses emitted priority-aware alerts unchanged**

```python
def test_render_live_watch_review_text_handles_priority_filtered_alerts(self) -> None:
    rendered = render_live_watch_review_text(
        {
            "latest_call": "sell_candidate",
            "latest_symbol": "R_75",
            "latest_trade_status": "valid",
            "latest_direction_bias": "sell",
            "latest_regime": "trend_down",
            "latest_confidence": 0.64,
            "latest_current_close": 48479.24,
            "latest_wait_for": "wait for a clean bearish continuation close",
            "alert_count": 2,
            "alerts": [
                {
                    "alert_type": "setup_candidate",
                    "decision_summary": "sell setup valid; short setup in trend_down regime; wait for a clean bearish continuation close",
                    "call": "sell_candidate",
                    "symbol": "R_75",
                    "why": "short setup in trend_down regime",
                    "wait_for": "wait for a clean bearish continuation close",
                },
                {
                    "alert_type": "context_update",
                    "call": "stand_aside",
                    "symbol": "R_75",
                    "why": "bearish pressure is building but not tradeable yet",
                    "wait_for": "wait for bearish continuation confirmation",
                },
            ],
        }
    )

    self.assertIn("review_alert_count=2", rendered)
    self.assertIn("alert_type=setup_candidate", rendered)
    self.assertIn("alert_type=context_update", rendered)
```

- [ ] **Step 2: Run the full live market snapshot test module**

Run: `python -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 3: Run targeted diagnostics on edited files**

Run diagnostics for:
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`

Expected: no new errors introduced by the transition-priority changes.

- [ ] **Step 4: Optional live smoke for bounded read-only watch behavior**

Run: `python -m synthetic_trader.cli live-watch --symbol R_75 --emit-initial --max-minutes 2 --max-alerts 3 --journal journals/live_watch_transition_priority_smoke.jsonl`
Expected: either one baseline/context alert plus any later setup transition, or a quiet bounded run with no crashes.

- [ ] **Step 5: Commit the final verification pass**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "test: verify live watch transition priority flow"
```
