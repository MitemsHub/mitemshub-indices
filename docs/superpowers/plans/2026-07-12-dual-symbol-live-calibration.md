# Dual-Symbol Live Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calibrate the shared intraday execution engine for both `R_75` and `R_100` using symbol-specific trigger and travel settings while preserving one common execution architecture.

**Architecture:** Keep `intraday_execution_builder.py` as the single execution engine, but move symbol differences into `SymbolProfile` calibration fields. Add paired fixtures and tests for both symbols, then verify the same contract and live route behavior holds across both symbols with intentional, symbol-aware outcomes.

**Tech Stack:** Python 3.13, pytest, TypeScript, Next.js, Vitest

---

## File Map

- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\config.py`
  - Add symbol-specific calibration fields for trigger quality and late-move rejection.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
  - Make trigger and target selection read symbol-level settings instead of relying on hard-coded thresholds.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`
  - Add paired `R_75` and `R_100` fixtures and assertions.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_decision_engine.py`
  - Verify symbol-aware calibration still preserves the shared intraday contract.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`
  - Verify both symbols retain pattern-aware copy and primary-target-first semantics.
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\api-routes.test.ts`
  - Add route-level verification for both `R_75` and `R_100`.

### Task 1: Add Symbol Calibration Fields

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\config.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing test**

```python
def test_symbol_profiles_expose_dual_symbol_intraday_calibration_fields() -> None:
    config = TraderConfig.default()

    r75 = config.symbols["R_75"]
    r100 = config.symbols["R_100"]

    assert r75.min_continuation_body_efficiency is not None
    assert r75.late_extension_rejection_ratio is not None
    assert r100.min_continuation_body_efficiency is not None
    assert r100.late_extension_rejection_ratio is not None
    assert r75.travel_budget_5m_bars != r100.travel_budget_5m_bars or (
        r75.min_continuation_body_efficiency != r100.min_continuation_body_efficiency
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_symbol_profiles_expose_dual_symbol_intraday_calibration_fields -v`
Expected: FAIL with `AttributeError` because the new calibration fields do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class SymbolProfile:
    ...
    min_continuation_body_efficiency: float = 0.55
    min_close_location_strength: float = 0.70
    min_reclaim_quality_score: float = 0.65
    late_extension_rejection_ratio: float = 0.70
```

```python
"R_75": SymbolProfile(
    ...
    travel_budget_5m_bars=10,
    min_continuation_body_efficiency=0.58,
    min_close_location_strength=0.72,
    min_reclaim_quality_score=0.66,
    late_extension_rejection_ratio=0.74,
),
"R_100": SymbolProfile(
    ...
    travel_budget_5m_bars=12,
    min_continuation_body_efficiency=0.55,
    min_close_location_strength=0.70,
    min_reclaim_quality_score=0.65,
    late_extension_rejection_ratio=0.70,
),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_symbol_profiles_expose_dual_symbol_intraday_calibration_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/config.py tests/test_intraday_execution_builder.py
git commit -m "feat: add dual-symbol intraday calibration settings"
```

### Task 2: Make Trigger Classification Symbol-Aware

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_classify_trigger_accepts_clean_r75_continuation_under_r75_thresholds() -> None:
    trigger = classify_trigger(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_clean_continuation(),
        config=TraderConfig.default(),
    )

    assert trigger is not None
    assert trigger.trigger_type == "continuation_close"


def test_classify_trigger_rejects_marginal_r75_continuation_that_r100_would_allow() -> None:
    trigger = classify_trigger(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_marginal_continuation(),
        config=TraderConfig.default(),
    )

    assert trigger is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_classify_trigger_accepts_clean_r75_continuation_under_r75_thresholds tests/test_intraday_execution_builder.py::test_classify_trigger_rejects_marginal_r75_continuation_that_r100_would_allow -v`
Expected: FAIL because `classify_trigger()` is not symbol-aware yet.

- [ ] **Step 3: Write minimal implementation**

```python
def classify_trigger(
    *,
    symbol: str,
    direction: str,
    execution_candles: list[Candle],
    config: TraderConfig,
) -> TriggerSignal | None:
    profile = config.symbols[symbol]
    ...
    if (
        direction == "buy"
        and latest.close > prior.high
        and body_efficiency > profile.min_continuation_body_efficiency
        and close_location > profile.min_close_location_strength
    ):
        ...

    if direction == "buy" and reclaimed and quality_score >= profile.min_reclaim_quality_score:
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_classify_trigger_accepts_clean_r75_continuation_under_r75_thresholds tests/test_intraday_execution_builder.py::test_classify_trigger_rejects_marginal_r75_continuation_that_r100_would_allow -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/intraday_execution_builder.py tests/test_intraday_execution_builder.py
git commit -m "feat: use symbol-aware trigger thresholds"
```

### Task 3: Make Target Rejection Symbol-Aware

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_select_primary_target_uses_r75_travel_budget_for_next_hour_objective() -> None:
    candles = execution_candles_for_r75_balanced_target()
    trigger = classify_trigger(
        symbol="R_75",
        direction="buy",
        execution_candles=candles,
        config=TraderConfig.default(),
    )
    assert trigger is not None

    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=candles,
    )
    target = select_primary_target(
        symbol="R_75",
        direction="buy",
        entry=trigger.entry,
        execution_stop=stop,
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert target is not None
    assert target < trigger.entry + 800.0


def test_select_primary_target_rejects_r100_late_extension_using_symbol_ratio() -> None:
    candles = execution_candles_for_late_extension()
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=candles,
        config=TraderConfig.default(),
    )
    assert trigger is not None

    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=candles,
    )
    target = select_primary_target(
        symbol="R_100",
        direction="buy",
        entry=trigger.entry,
        execution_stop=stop,
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert target is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_select_primary_target_uses_r75_travel_budget_for_next_hour_objective tests/test_intraday_execution_builder.py::test_select_primary_target_rejects_r100_late_extension_using_symbol_ratio -v`
Expected: FAIL because target logic still uses shared thresholds only.

- [ ] **Step 3: Write minimal implementation**

```python
if prior:
    prior_extreme = max(candle.high for candle in prior) if direction == "buy" else min(candle.low for candle in prior)
    if (direction == "buy" and latest.close >= prior_extreme and not liquidity_candidates) or (
        direction == "sell" and latest.close <= prior_extreme and not liquidity_candidates
    ):
        if latest.range >= travel_budget * profile.late_extension_rejection_ratio:
            return None
```

Keep `travel_budget_5m_bars` and `min_primary_reward_risk` sourced from `SymbolProfile` so `R_75` and `R_100` can differ intentionally.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_select_primary_target_uses_r75_travel_budget_for_next_hour_objective tests/test_intraday_execution_builder.py::test_select_primary_target_rejects_r100_late_extension_using_symbol_ratio -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/intraday_execution_builder.py tests/test_intraday_execution_builder.py
git commit -m "feat: add symbol-aware target calibration"
```

### Task 4: Add Paired Dual-Symbol Builder Coverage

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_intraday_execution_accepts_clean_r75_plan_with_realistic_primary_target() -> None:
    plan = build_intraday_execution(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_clean_continuation(),
        thesis_invalidation=54800.0,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.primary_target > plan.entry
    assert plan.primary_target != plan.thesis_invalidation


def test_build_intraday_execution_rejects_weak_r75_late_extension() -> None:
    plan = build_intraday_execution(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_late_extension(),
        thesis_invalidation=54800.0,
        config=TraderConfig.default(),
    )

    assert plan is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py::test_build_intraday_execution_accepts_clean_r75_plan_with_realistic_primary_target tests/test_intraday_execution_builder.py::test_build_intraday_execution_rejects_weak_r75_late_extension -v`
Expected: FAIL until paired `R_75` fixtures and symbol-aware thresholds are aligned.

- [ ] **Step 3: Write minimal implementation**

```python
def execution_candles_for_r75_clean_continuation() -> list[Candle]:
    ...


def execution_candles_for_r75_late_extension() -> list[Candle]:
    ...
```

Keep the fixtures explicit and sized for realistic `R_75` next-hour travel, not copied from `R_100` prices with trivial scaling.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_intraday_execution_builder.py
git commit -m "test: add paired r75 and r100 intraday builder coverage"
```

### Task 5: Verify Decision Engine For Both Symbols

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_decision_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_decision_engine_accepts_clean_r75_pattern_with_symbol_aware_target() -> None:
    with patch(
        "synthetic_trader.strategy.decision_engine.build_intraday_execution",
        return_value=intraday_execution_plan(
            entry=55620.0,
            execution_stop=55280.0,
            thesis_invalidation=52541.0,
            primary_target=56180.0,
            hold_horizon_minutes=60,
            trigger_type="continuation_close",
        ),
    ):
        report = engine.evaluate(
            "R_75",
            candles=execution_candles,
            higher_timeframe_candles=bias_candles,
            role_candles=role_candles,
        )

    assert report.signal is not None
    assert report.signal.primary_target == 56180.0


def test_decision_engine_preserves_shared_contract_while_symbols_differ() -> None:
    assert report.signal.stop_loss == report.signal.execution_stop
    assert report.signal.take_profit == report.signal.primary_target
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_decision_engine.py::DecisionEngineTests::test_decision_engine_accepts_clean_r75_pattern_with_symbol_aware_target -v`
Expected: FAIL until the new R_75 expectations are added.

- [ ] **Step 3: Write minimal implementation**

```python
self.assertEqual(report.signal.execution_trigger_type, "continuation_close")
self.assertLess(abs(report.signal.primary_target - report.signal.entry), 800.0)
```

Update only the tests unless production code is genuinely missing shared-contract support for `R_75`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_decision_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_decision_engine.py
git commit -m "test: verify dual-symbol calibrated decision-engine behavior"
```

### Task 6: Verify Live Snapshot For Both Symbols

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_analyze_live_snapshot_emits_pattern_aware_intraday_copy_for_r75_continuation() -> None:
    snapshot = analyze_live_snapshot(...)
    assert "continuation" in str(snapshot["wait_for"]).lower()
    assert snapshot["take_profit"] == snapshot["primary_target"]


def test_analyze_live_snapshot_emits_pattern_aware_intraday_copy_for_r100_reclaim() -> None:
    snapshot = analyze_live_snapshot(...)
    assert "reclaim" in str(snapshot["wait_for"]).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_analyze_live_snapshot_emits_pattern_aware_intraday_copy_for_r75_continuation tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_analyze_live_snapshot_emits_pattern_aware_intraday_copy_for_r100_reclaim -v`
Expected: FAIL until paired symbol coverage exists.

- [ ] **Step 3: Write minimal implementation**

```python
signal = TradeSignal(
    symbol="R_75",
    ...
    primary_target=56180.0,
    execution_trigger_type="continuation_close",
)
```

Add explicit `R_75` snapshot fixtures alongside the existing `R_100` ones and keep `take_profit == primary_target`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_live_market_snapshot.py
git commit -m "test: verify dual-symbol live snapshot intraday copy"
```

### Task 7: Route And Live Verification For Both Symbols

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\api-routes.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
it("POST /api/calls/run preserves calibrated R_75 geometry", async () => {
  vi.spyOn(engineBridge, "runFreshCall").mockResolvedValue({
    ...baseCall,
    symbol: "R_75",
    execution_stop: 55280.0,
    thesis_invalidation: 52541.0,
    primary_target: 56180.0,
    hold_horizon_minutes: 60,
    wait_for:
      "wait for the 5m continuation trigger to confirm, then manage toward the next hour objective",
  });

  const response = await postRun(request);
  const payload = await response.json();
  expect(payload.primary_target).toBe(56180.0);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/api-routes.test.ts`
Expected: FAIL until the new R_75 route fixture expectations are added.

- [ ] **Step 3: Write minimal implementation**

```ts
expect(payload.execution_stop).toBe(55280.0);
expect(payload.primary_target).toBe(56180.0);
expect(payload.wait_for).toMatch(/continuation/i);
```

Keep route logic unchanged unless a contract mismatch appears.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py tests/test_decision_engine.py tests/test_live_market_snapshot.py -q`
Expected: PASS

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/api-routes.test.ts tests/contracts.test.ts tests/engine-bridge.test.ts tests/operator-panels.test.tsx`
Expected: PASS

Probe both routes live:

```bash
Invoke-RestMethod -Uri 'http://localhost:3006/api/calls/run' -Method Post -ContentType 'application/json' -Body '{"symbol":"R_75","account_mode":"own_account"}'
Invoke-RestMethod -Uri 'http://localhost:3006/api/calls/run' -Method Post -ContentType 'application/json' -Body '{"symbol":"R_100","account_mode":"own_account"}'
```

Expected: both routes respond `200` and expose the calibrated intraday geometry fields, whether the current market state is actionable or forming.

- [ ] **Step 5: Commit**

```bash
git add tests/test_intraday_execution_builder.py tests/test_decision_engine.py tests/test_live_market_snapshot.py external/mitemshub-indices/tests/api-routes.test.ts
git commit -m "test: verify dual-symbol live calibration"
```

## Self-Review

- Spec coverage:
  - shared core plus symbol overrides: Tasks 1 through 3
  - paired `R_75` and `R_100` builder coverage: Task 4
  - dual-symbol decision-engine and live snapshot behavior: Tasks 5 and 6
  - route and live verification for both symbols: Task 7
- Placeholder scan:
  - no `TODO`, `TBD`, or “similar to above” placeholders remain
  - every code-changing step includes explicit code or assertions
- Type consistency:
  - field and helper names are consistent: `min_continuation_body_efficiency`, `min_close_location_strength`, `min_reclaim_quality_score`, `late_extension_rejection_ratio`, `execution_trigger_type`, `primary_target`
