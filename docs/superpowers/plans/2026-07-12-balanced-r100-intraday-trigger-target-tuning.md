# Balanced R_100 Intraday Trigger And Target Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `R_100` next-hour intraday plans by adding pattern-aware `5m` triggers, pattern-specific local stops, and balanced target estimation without loosening the current quality gate.

**Architecture:** Keep the existing top-down thesis flow unchanged and concentrate the tuning inside `intraday_execution_builder.py`. Split the builder into focused helpers for trigger classification, stop selection, and target candidate selection, then let `decision_engine.py` and `market_snapshot.py` consume the stronger execution plan without changing the `4H` and `1H` bias architecture.

**Tech Stack:** Python 3.13, pytest, TypeScript, Next.js, Vitest

---

## File Map

- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
  - Add trigger typing, pattern-aware stop selection, and balanced target candidate selection.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`
  - Add focused `R_100` fixtures for continuation, reclaim, break-retest, and failure cases.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_decision_engine.py`
  - Verify accepted patterns survive and weak patterns are rejected.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`
  - Refine action copy so `wait_for` and `invalidates_if` reflect the actual trigger type.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`
  - Verify pattern-aware intraday copy and main-target preservation.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\api-routes.test.ts`
  - Keep route fixtures aligned if copy text or payload values change.

### Task 1: Add Trigger-Type And Quality Helpers

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_classify_trigger_identifies_clean_continuation_close() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_clean_continuation(),
    )

    assert trigger is not None
    assert trigger.trigger_type == "continuation_close"
    assert trigger.quality_score > 0.7


def test_classify_trigger_identifies_reclaim_pullback() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_reclaim_pullback(),
    )

    assert trigger is not None
    assert trigger.trigger_type == "reclaim_pullback"
    assert trigger.quality_score > 0.65


def test_classify_trigger_rejects_weak_noisy_close() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_weak_noisy_close(),
    )

    assert trigger is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_classify_trigger_identifies_clean_continuation_close tests/test_intraday_execution_builder.py::test_classify_trigger_identifies_reclaim_pullback tests/test_intraday_execution_builder.py::test_classify_trigger_rejects_weak_noisy_close -v`
Expected: FAIL with `NameError` or import failure because `classify_trigger` and trigger fixtures do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class TriggerSignal:
    trigger_type: str
    entry: float
    failure_level: float
    quality_score: float


def classify_trigger(
    *,
    direction: str,
    execution_candles: list[Candle],
) -> TriggerSignal | None:
    recent = execution_candles[-6:]
    latest = recent[-1]
    prior = recent[-2]
    body_efficiency = latest.body_abs / max(latest.range, 1e-9)
    close_location = (
        (latest.close - latest.low) / max(latest.range, 1e-9)
        if direction == "buy"
        else (latest.high - latest.close) / max(latest.range, 1e-9)
    )

    if direction == "buy" and latest.close > prior.high and body_efficiency > 0.55 and close_location > 0.7:
        return TriggerSignal(
            trigger_type="continuation_close",
            entry=latest.high,
            failure_level=latest.low,
            quality_score=min(1.0, 0.5 + body_efficiency * 0.3 + close_location * 0.2),
        )

    reclaimed = latest.close > prior.close and latest.low <= min(c.low for c in recent[-4:-1])
    if direction == "buy" and reclaimed and body_efficiency > 0.45:
        shelf = min(c.low for c in recent[-3:])
        return TriggerSignal(
            trigger_type="reclaim_pullback",
            entry=latest.close,
            failure_level=shelf,
            quality_score=min(1.0, 0.45 + body_efficiency * 0.3 + close_location * 0.2),
        )

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_classify_trigger_identifies_clean_continuation_close tests/test_intraday_execution_builder.py::test_classify_trigger_identifies_reclaim_pullback tests/test_intraday_execution_builder.py::test_classify_trigger_rejects_weak_noisy_close -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/intraday_execution_builder.py tests/test_intraday_execution_builder.py
git commit -m "feat: add r100 trigger classification helpers"
```

### Task 2: Add Pattern-Aware Stop Selection

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_select_execution_stop_uses_trigger_failure_for_continuation_close() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_clean_continuation(),
    )

    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=execution_candles_for_clean_continuation(),
    )

    assert stop == pytest.approx(execution_candles_for_clean_continuation()[-1].low)


def test_select_execution_stop_uses_reclaimed_shelf_for_reclaim_pullback() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_reclaim_pullback(),
    )

    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=execution_candles_for_reclaim_pullback(),
    )

    assert stop == pytest.approx(474.6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_select_execution_stop_uses_trigger_failure_for_continuation_close tests/test_intraday_execution_builder.py::test_select_execution_stop_uses_reclaimed_shelf_for_reclaim_pullback -v`
Expected: FAIL because `select_execution_stop` does not exist yet and the builder still uses a blunt recent-window rule.

- [ ] **Step 3: Write minimal implementation**

```python
def select_execution_stop(
    *,
    direction: str,
    trigger: TriggerSignal,
    execution_candles: list[Candle],
) -> float:
    recent = execution_candles[-6:]
    if trigger.trigger_type == "continuation_close":
        return trigger.failure_level
    if trigger.trigger_type == "reclaim_pullback":
        shelf = min(c.low for c in recent[-3:]) if direction == "buy" else max(c.high for c in recent[-3:])
        return shelf
    if trigger.trigger_type == "break_retest_hold":
        return trigger.failure_level
    return min(c.low for c in recent[-4:]) if direction == "buy" else max(c.high for c in recent[-4:])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_select_execution_stop_uses_trigger_failure_for_continuation_close tests/test_intraday_execution_builder.py::test_select_execution_stop_uses_reclaimed_shelf_for_reclaim_pullback -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/intraday_execution_builder.py tests/test_intraday_execution_builder.py
git commit -m "feat: add pattern-aware intraday stop selection"
```

### Task 3: Add Balanced Target Candidate Selection

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_select_primary_target_prefers_nearest_liquidity_inside_balanced_travel_budget() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_clean_continuation(),
    )
    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=execution_candles_for_clean_continuation(),
    )

    target = select_primary_target(
        symbol="R_100",
        direction="buy",
        entry=trigger.entry,
        execution_stop=stop,
        execution_candles=execution_candles_for_clean_continuation(),
        config=TraderConfig.default(),
    )

    assert target == pytest.approx(488.4)


def test_select_primary_target_rejects_overextended_late_move() -> None:
    trigger = classify_trigger(
        direction="buy",
        execution_candles=execution_candles_for_late_extension(),
    )
    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=execution_candles_for_late_extension(),
    )

    target = select_primary_target(
        symbol="R_100",
        direction="buy",
        entry=trigger.entry,
        execution_stop=stop,
        execution_candles=execution_candles_for_late_extension(),
        config=TraderConfig.default(),
    )

    assert target is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_select_primary_target_prefers_nearest_liquidity_inside_balanced_travel_budget tests/test_intraday_execution_builder.py::test_select_primary_target_rejects_overextended_late_move -v`
Expected: FAIL because `select_primary_target` does not exist and the builder still uses average range directly.

- [ ] **Step 3: Write minimal implementation**

```python
def select_primary_target(
    *,
    symbol: str,
    direction: str,
    entry: float,
    execution_stop: float,
    execution_candles: list[Candle],
    config: TraderConfig,
) -> float | None:
    profile = config.symbols[symbol]
    recent = execution_candles[-12:]
    travel_budget = sum(c.range for c in recent[-profile.travel_budget_5m_bars:]) / max(profile.travel_budget_5m_bars, 1)
    liquidity_target = (
        max(c.high for c in recent[-6:])
        if direction == "buy"
        else min(c.low for c in recent[-6:])
    )
    clamped_target = min(entry + travel_budget, liquidity_target) if direction == "buy" else max(entry - travel_budget, liquidity_target)
    reward = abs(clamped_target - entry)
    risk = abs(entry - execution_stop)
    if risk <= 0 or reward / risk < config.symbols[symbol].min_primary_reward_risk:
        return None
    return clamped_target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_select_primary_target_prefers_nearest_liquidity_inside_balanced_travel_budget tests/test_intraday_execution_builder.py::test_select_primary_target_rejects_overextended_late_move -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/intraday_execution_builder.py tests/test_intraday_execution_builder.py
git commit -m "feat: add balanced r100 target candidate selection"
```

### Task 4: Rebuild build_intraday_execution Around Helpers

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_intraday_execution_accepts_clean_break_retest_hold() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_break_retest_hold(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.execution_stop < plan.entry
    assert plan.primary_target > plan.entry


def test_build_intraday_execution_rejects_weak_noisy_close_after_helper_refactor() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_weak_noisy_close(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_build_intraday_execution_accepts_clean_break_retest_hold tests/test_intraday_execution_builder.py::test_build_intraday_execution_rejects_weak_noisy_close_after_helper_refactor -v`
Expected: FAIL because the main builder does not yet consume trigger and target helper logic.

- [ ] **Step 3: Write minimal implementation**

```python
def build_intraday_execution(...):
    trigger = classify_trigger(
        direction=direction,
        execution_candles=execution_candles,
    )
    if trigger is None:
        return None

    execution_stop = select_execution_stop(
        direction=direction,
        trigger=trigger,
        execution_candles=execution_candles,
    )
    primary_target = select_primary_target(
        symbol=symbol,
        direction=direction,
        entry=trigger.entry,
        execution_stop=execution_stop,
        execution_candles=execution_candles,
        config=config,
    )
    if primary_target is None:
        return None

    return IntradayExecutionPlan(
        entry=trigger.entry,
        execution_stop=execution_stop,
        thesis_invalidation=thesis_invalidation,
        primary_target=primary_target,
        extended_target=None,
        hold_horizon_minutes=config.symbols[symbol].intraday_hold_horizon_minutes,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/intraday_execution_builder.py tests/test_intraday_execution_builder.py
git commit -m "feat: refactor r100 intraday builder around pattern-aware helpers"
```

### Task 5: Verify Decision Engine Behavior

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_decision_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_decision_engine_accepts_clean_r100_reclaim_pattern_with_balanced_target() -> None:
    with patch(
        "synthetic_trader.strategy.decision_engine.build_intraday_execution",
        return_value=intraday_execution_plan(
            entry=476.2,
            execution_stop=474.9,
            thesis_invalidation=440.67,
            primary_target=488.4,
            hold_horizon_minutes=60,
        ),
    ):
        report = engine.evaluate(
            "R_100",
            candles=execution_candles,
            higher_timeframe_candles=bias_candles,
            role_candles=role_candles,
        )

    assert report.signal is not None
    assert report.signal.primary_target == pytest.approx(488.4)


def test_decision_engine_rejects_weak_r100_pattern_even_when_top_down_thesis_is_confirmed() -> None:
    with patch(
        "synthetic_trader.strategy.decision_engine.build_intraday_execution",
        return_value=None,
    ):
        report = engine.evaluate(
            "R_100",
            candles=execution_candles,
            higher_timeframe_candles=bias_candles,
            role_candles=role_candles,
        )

    assert report.signal is None
    assert "reachable target" in " ".join(report.reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_decision_engine.py::DecisionEngineTests::test_decision_engine_accepts_clean_r100_reclaim_pattern_with_balanced_target tests/test_decision_engine.py::DecisionEngineTests::test_decision_engine_rejects_weak_r100_pattern_even_when_top_down_thesis_is_confirmed -v`
Expected: FAIL until the updated pattern-oriented fixtures and expected target values are aligned.

- [ ] **Step 3: Write minimal implementation**

```python
self.assertEqual(report.signal.stop_loss, report.signal.execution_stop)
self.assertEqual(report.signal.take_profit, report.signal.primary_target)
self.assertLess(abs(report.signal.primary_target - report.signal.entry), 20.0)
```

Use the existing `intraday_execution_plan(...)` helper in `tests/test_decision_engine.py` and update expected values to the balanced target fixtures instead of the blunt builder values.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_decision_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_decision_engine.py
git commit -m "test: cover balanced r100 intraday decision-engine outcomes"
```

### Task 6: Update Live Snapshot Copy For Pattern-Aware Triggers

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_live_snapshot_uses_pattern_aware_wait_copy_for_reclaim_pullback() -> None:
    snapshot = analyze_live_snapshot(...)
    assert "reclaim" in str(snapshot["wait_for"]).lower()


def test_live_snapshot_keeps_primary_target_as_main_intraday_objective() -> None:
    snapshot = analyze_live_snapshot(...)
    assert snapshot["take_profit"] == snapshot["primary_target"]
    assert snapshot["primary_target"] != snapshot["thesis_invalidation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_live_snapshot_uses_pattern_aware_wait_copy_for_reclaim_pullback tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_live_snapshot_keeps_primary_target_as_main_intraday_objective -v`
Expected: FAIL because current copy only says `5m trigger` generically and does not mention the trigger pattern.

- [ ] **Step 3: Write minimal implementation**

```python
def _build_intraday_wait_for(..., trigger_type: str | None = None) -> str:
    horizon = _format_hold_horizon(hold_horizon_minutes)
    if trigger_type == "reclaim_pullback":
        return f"wait for the 5m reclaim to confirm, then manage toward the {horizon} objective"
    if trigger_type == "break_retest_hold":
        return f"wait for the 5m retest hold to confirm, then manage toward the {horizon} objective"
    return f"wait for the 5m continuation trigger to confirm, then manage toward the {horizon} objective"
```

Pass `trigger_type` through from the execution plan if it exists.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: use pattern-aware intraday execution copy"
```

### Task 7: Focused End-To-End Verification

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\api-routes.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("POST /api/calls/run preserves balanced intraday R_100 geometry", async () => {
  vi.spyOn(engineBridge, "runFreshCall").mockResolvedValue({
    ...baseCall,
    symbol: "R_100",
    execution_stop: 474.9,
    thesis_invalidation: 440.67,
    primary_target: 488.4,
    extended_target: null,
    hold_horizon_minutes: 60,
    wait_for:
      "wait for the 5m reclaim to confirm, then manage toward the next hour objective",
  });

  const response = await postRun(request);
  const payload = await response.json();
  expect(payload.primary_target).toBe(488.4);
  expect(payload.wait_for).toMatch(/reclaim/i);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/api-routes.test.ts`
Expected: FAIL until the route fixture and expected balanced copy are aligned.

- [ ] **Step 3: Write minimal implementation**

```ts
expect(payload.execution_stop).toBe(474.9);
expect(payload.primary_target).toBe(488.4);
expect(payload.wait_for).toContain("5m reclaim");
```

Keep the route logic unchanged unless a fixture or contract expectation must be updated to match the new Python copy.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py tests/test_decision_engine.py tests/test_live_market_snapshot.py -q`
Expected: PASS

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/api-routes.test.ts tests/contracts.test.ts tests/engine-bridge.test.ts tests/operator-panels.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_intraday_execution_builder.py tests/test_decision_engine.py tests/test_live_market_snapshot.py external/mitemshub-indices/tests/api-routes.test.ts
git commit -m "test: verify balanced r100 intraday tuning"
```

## Self-Review

- Spec coverage:
  - pattern-aware `R_100` trigger types: Tasks 1 and 4
  - pattern-specific stop selection: Task 2
  - balanced target estimation: Task 3
  - decision-engine acceptance/rejection behavior: Task 5
  - pattern-aware live copy and route verification: Tasks 6 and 7
- Placeholder scan:
  - no `TODO`, `TBD`, or “similar to Task N” references remain
  - every code-changing step includes explicit code or assertions
- Type consistency:
  - helper and field names are consistent across tasks: `TriggerSignal`, `classify_trigger`, `select_execution_stop`, `select_primary_target`, `primary_target`, `execution_stop`, `hold_horizon_minutes`
