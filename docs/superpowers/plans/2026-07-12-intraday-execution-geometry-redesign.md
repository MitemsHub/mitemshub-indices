# Intraday Execution Geometry Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace swing-sized execution levels with realistic `30m-1h` intraday trade construction for `R_75` and `R_100` while preserving the top-down `4H` and `1H` directional engine.

**Architecture:** Keep `4H` bias, `1H` setup, and `15m` confirmation unchanged as the thesis layer. Add a dedicated intraday execution layer that derives entry and stop from `5m`, estimates a reachable primary target for the next `30m-1h`, and exposes both local execution failure and higher-timeframe thesis invalidation to the app contract.

**Tech Stack:** Python 3.13, pytest, TypeScript, Next.js, Vitest, Zod

---

## File Map

- Create: `src/synthetic_trader/strategy/intraday_execution_builder.py`
  - Builds `entry`, `execution_stop`, `thesis_invalidation`, `primary_target`, `extended_target`, and `hold_horizon_minutes` from confirmed setups and lower-timeframe candles.
- Modify: `src/synthetic_trader/domain.py`
  - Extend `TradeSignal` with distinct execution-vs-thesis fields without breaking existing risk evaluation.
- Modify: `src/synthetic_trader/config.py`
  - Add symbol-level intraday travel and hold-horizon defaults.
- Modify: `src/synthetic_trader/strategy/decision_engine.py`
  - Replace fixed `take_profit_rr` projection for live call packaging with the new intraday execution builder.
- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Serialize the new fields, update trader-facing copy, and preserve guardian behavior.
- Test: `tests/test_intraday_execution_builder.py`
  - Covers stop source, reachable primary target, and rejection of bloated geometry.
- Modify: `tests/test_decision_engine.py`
  - Verifies the decision engine emits execution-stop and reachable-target outputs.
- Modify: `tests/test_live_market_snapshot.py`
  - Verifies live snapshot payload and copy reflect `30m-1h` intraday semantics.
- Modify: `external/mitemshub-indices/src/lib/contracts.ts`
  - Add app schema fields for `execution_stop`, `thesis_invalidation`, `primary_target`, `extended_target`, and `hold_horizon_minutes`.
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
  - Normalize and preserve the new fields from Python output.
- Modify: `external/mitemshub-indices/src/hooks/use-operator-workspace.ts`
  - Carry the new contract fields through local state.
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
  - Display the execution stop as the main stop, the primary target as the main objective, and show thesis invalidation separately.
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
  - Update summary copy and visible level labels.
- Modify: `external/mitemshub-indices/src/lib/mock-data.ts`
  - Keep mocks aligned with the new contract.
- Modify: `external/mitemshub-indices/tests/contracts.test.ts`
  - Assert the expanded schema accepts the new fields.
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
  - Assert bridge normalization preserves new fields.
- Modify: `external/mitemshub-indices/tests/operator-panels.test.tsx`
  - Assert the UI shows primary target and thesis invalidation separately.

### Task 1: Add Intraday Signal Fields

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\domain.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\config.py`
- Test: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_decision_engine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_trade_signal_exposes_distinct_execution_and_thesis_levels() -> None:
    engine = DecisionEngine(TraderConfig.default())
    report = engine.evaluate("R_100", candles=trending_candles(symbol="R_100"))

    assert report.signal is not None
    assert report.signal.execution_stop is not None
    assert report.signal.thesis_invalidation is not None
    assert report.signal.primary_target is not None
    assert report.signal.hold_horizon_minutes == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_decision_engine.py::DecisionEngineTests::test_trade_signal_exposes_distinct_execution_and_thesis_levels -v`
Expected: FAIL with `AttributeError` or constructor mismatch because `TradeSignal` does not yet expose intraday execution fields.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    direction: Direction
    confidence: float
    min_confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    horizon_sec: int
    snapshot: FeatureSnapshot
    rationale: tuple[str, ...]
    model_version: str = "bootstrap"
    execution_stop: float | None = None
    thesis_invalidation: float | None = None
    primary_target: float | None = None
    extended_target: float | None = None
    hold_horizon_minutes: int | None = None
```

```python
@dataclass(frozen=True)
class SymbolProfile:
    ...
    intraday_hold_horizon_minutes: int = 60
    min_primary_reward_risk: float = 1.2
    travel_budget_5m_bars: int = 12
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_decision_engine.py::DecisionEngineTests::test_trade_signal_exposes_distinct_execution_and_thesis_levels -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_decision_engine.py src/synthetic_trader/domain.py src/synthetic_trader/config.py
git commit -m "feat: add intraday execution signal fields"
```

### Task 2: Build The Intraday Execution Layer

**Files:**
- Create: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\intraday_execution_builder.py`
- Test: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_intraday_execution_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_intraday_execution_uses_5m_swing_for_execution_stop() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_buy_retest(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan.execution_stop > 440.67
    assert plan.execution_stop < plan.entry
    assert plan.thesis_invalidation == 440.67


def test_build_intraday_execution_chooses_reachable_primary_target_over_projected_far_target() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_buy_retest(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan.primary_target == 488.8
    assert plan.extended_target is None or plan.extended_target > plan.primary_target


def test_build_intraday_execution_rejects_bloated_geometry_when_reachable_target_cannot_pay_for_local_stop() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_with_wide_stop_and_short_travel(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py -v`
Expected: FAIL with `ModuleNotFoundError` because the builder does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class IntradayExecutionPlan:
    entry: float
    execution_stop: float
    thesis_invalidation: float
    primary_target: float
    extended_target: float | None
    hold_horizon_minutes: int


def build_intraday_execution(
    *,
    symbol: str,
    direction: str,
    execution_candles: list[Candle],
    thesis_invalidation: float,
    config: TraderConfig,
) -> IntradayExecutionPlan | None:
    profile = config.symbols[symbol]
    recent = execution_candles[-12:]
    latest = recent[-1]
    trigger = latest.high if direction == "buy" else latest.low
    swing_stop = min(c.low for c in recent[-4:]) if direction == "buy" else max(c.high for c in recent[-4:])
    impulses = [c.range for c in recent[-profile.travel_budget_5m_bars:]]
    expected_travel = sum(impulses) / max(len(impulses), 1)
    primary_target = trigger + expected_travel if direction == "buy" else trigger - expected_travel
    reward = abs(primary_target - trigger)
    risk = abs(trigger - swing_stop)
    if risk <= 0 or reward / risk < profile.min_primary_reward_risk:
        return None
    return IntradayExecutionPlan(
        entry=trigger,
        execution_stop=swing_stop,
        thesis_invalidation=thesis_invalidation,
        primary_target=primary_target,
        extended_target=None,
        hold_horizon_minutes=profile.intraday_hold_horizon_minutes,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_intraday_execution_builder.py src/synthetic_trader/strategy/intraday_execution_builder.py
git commit -m "feat: add intraday execution builder"
```

### Task 3: Integrate The Builder Into The Decision Engine

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\strategy\decision_engine.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_decision_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_decision_engine_uses_execution_stop_not_thesis_invalidation_for_intraday_call() -> None:
    report = engine.evaluate(
        "R_100",
        candles=execution_candles,
        higher_timeframe_candles=bias_candles,
        role_candles=role_candles,
    )

    assert report.signal is not None
    assert report.signal.stop_loss == report.signal.execution_stop
    assert report.signal.stop_loss != report.signal.thesis_invalidation


def test_decision_engine_returns_no_signal_when_intraday_target_is_not_reachable() -> None:
    report = engine.evaluate(
        "R_100",
        candles=wide_stop_execution_candles,
        higher_timeframe_candles=bias_candles,
        role_candles=role_candles,
    )

    assert report.signal is None
    assert "reachable target" in " ".join(report.reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_decision_engine.py::DecisionEngineTests::test_decision_engine_uses_execution_stop_not_thesis_invalidation_for_intraday_call tests/test_decision_engine.py::DecisionEngineTests::test_decision_engine_returns_no_signal_when_intraday_target_is_not_reachable -v`
Expected: FAIL because `decision_engine.py` still assigns `stop_loss` from higher-timeframe invalidation and still derives `take_profit` from fixed risk multiple.

- [ ] **Step 3: Write minimal implementation**

```python
execution_plan = build_intraday_execution(
    symbol=symbol,
    direction=setup.trade_direction,
    execution_candles=execution_candles,
    thesis_invalidation=bias.invalidation_price if bias.invalidation_price is not None else execution_candles[-1].low,
    config=self.config,
)
if execution_plan is None:
    return DecisionReport(None, rationale + ("reachable target does not justify local execution risk",))

signal = TradeSignal(
    symbol=symbol,
    direction=direction,
    confidence=confidence,
    min_confidence=min_confidence,
    entry=execution_plan.entry,
    stop_loss=execution_plan.execution_stop,
    take_profit=execution_plan.primary_target,
    horizon_sec=execution_plan.hold_horizon_minutes * 60,
    snapshot=snapshot,
    rationale=rationale,
    model_version=self.model.version,
    execution_stop=execution_plan.execution_stop,
    thesis_invalidation=execution_plan.thesis_invalidation,
    primary_target=execution_plan.primary_target,
    extended_target=execution_plan.extended_target,
    hold_horizon_minutes=execution_plan.hold_horizon_minutes,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_decision_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_decision_engine.py src/synthetic_trader/strategy/decision_engine.py
git commit -m "feat: integrate intraday execution geometry"
```

### Task 4: Update Live Snapshot Packaging And Copy

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\src\synthetic_trader\live\market_snapshot.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_live_snapshot_emits_execution_stop_and_primary_target_fields() -> None:
    snapshot = analyze_live_snapshot(
        symbol="R_100",
        ticks=ticks,
        timeframe_sec=60,
        higher_timeframe_sec=300,
        config=TraderConfig.default(),
    )

    assert snapshot["execution_stop"] == 474.8
    assert snapshot["thesis_invalidation"] == 440.67
    assert snapshot["primary_target"] == 488.8
    assert snapshot["hold_horizon_minutes"] == 60


def test_live_snapshot_copy_uses_intraday_action_language() -> None:
    alert = build_watch_alert(snapshot_with_intraday_levels)
    assert "next hour" in str(alert["wait_for"]).lower()
    assert "5m close" in str(alert["invalidates_if"]).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py::LiveMarketSnapshotTests::test_live_snapshot_emits_execution_stop_and_primary_target_fields tests/test_live_market_snapshot.py::LiveMarketSnapshotTests::test_live_snapshot_copy_uses_intraday_action_language -v`
Expected: FAIL because `market_snapshot.py` does not yet emit the expanded payload or intraday copy.

- [ ] **Step 3: Write minimal implementation**

```python
snapshot = {
    ...
    "execution_stop": report.signal.execution_stop,
    "thesis_invalidation": report.signal.thesis_invalidation,
    "primary_target": report.signal.primary_target,
    "extended_target": report.signal.extended_target,
    "hold_horizon_minutes": report.signal.hold_horizon_minutes,
    "stop_loss": report.signal.execution_stop,
    "take_profit": report.signal.primary_target,
    "invalidates_if": _build_execution_invalidation_text(direction_bias, report.signal.execution_stop),
    "wait_for": "wait for the 5m trigger to confirm, then manage toward the next-hour objective",
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_live_market_snapshot.py src/synthetic_trader/live/market_snapshot.py
git commit -m "feat: expose intraday execution levels in live snapshot"
```

### Task 5: Expand App Contracts And Bridge Normalization

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\lib\contracts.ts`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\lib\engine-bridge.ts`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\hooks\use-operator-workspace.ts`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\contracts.test.ts`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\engine-bridge.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
it("accepts intraday execution geometry fields in the fresh call contract", () => {
  const result = freshCallResponseSchema.parse({
    ...baseCall,
    execution_stop: 474.8,
    thesis_invalidation: 440.67,
    primary_target: 488.8,
    extended_target: 493.4,
    hold_horizon_minutes: 60,
  });

  expect(result.primary_target).toBe(488.8);
});

it("normalizes intraday execution geometry from Python output", async () => {
  mockPythonOutput({
    execution_stop: "474.8",
    thesis_invalidation: "440.67",
    primary_target: "488.8",
    extended_target: "493.4",
    hold_horizon_minutes: "60",
  });

  const result = await readLiveSnapshot({ engineRoot, symbol: "R_100" });
  expect(result.execution_stop).toBe(474.8);
  expect(result.thesis_invalidation).toBe(440.67);
  expect(result.primary_target).toBe(488.8);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- --runInBand tests/contracts.test.ts tests/engine-bridge.test.ts`
Expected: FAIL because the Zod schema and bridge types do not yet include the new fields.

- [ ] **Step 3: Write minimal implementation**

```ts
export const freshCallResponseSchema = z.object({
  ...
  execution_stop: z.number().nullable().optional(),
  thesis_invalidation: z.number().nullable().optional(),
  primary_target: z.number().nullable().optional(),
  extended_target: z.number().nullable().optional(),
  hold_horizon_minutes: z.number().int().positive().nullable().optional(),
});
```

```ts
return {
  ...
  execution_stop: normalizeNumber(raw.execution_stop),
  thesis_invalidation: normalizeNumber(raw.thesis_invalidation),
  primary_target: normalizeNumber(raw.primary_target),
  extended_target: normalizeNumber(raw.extended_target),
  hold_horizon_minutes: normalizeNumber(raw.hold_horizon_minutes),
};
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- --runInBand tests/contracts.test.ts tests/engine-bridge.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add external/mitemshub-indices/src/lib/contracts.ts external/mitemshub-indices/src/lib/engine-bridge.ts external/mitemshub-indices/src/hooks/use-operator-workspace.ts external/mitemshub-indices/tests/contracts.test.ts external/mitemshub-indices/tests/engine-bridge.test.ts
git commit -m "feat: carry intraday execution fields through app bridge"
```

### Task 6: Update Operator Panels For Intraday Plans

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\components\operator\primary-call-panel.tsx`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\components\operator\trade-instruction-panel.tsx`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\lib\mock-data.ts`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\operator-panels.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it("shows primary target as the main target and thesis invalidation separately", () => {
  render(<TradeInstructionPanel call={intradayCall} />);

  expect(screen.getByText("Primary target")).toBeInTheDocument();
  expect(screen.getByText("Execution stop")).toBeInTheDocument();
  expect(screen.getByText("Thesis invalidation")).toBeInTheDocument();
  expect(screen.queryByText("Target")).not.toBeInTheDocument();
});

it("uses next-hour action language for intraday calls", () => {
  render(<PrimaryCallPanel call={intradayCall} />);

  expect(screen.getByText(/next hour/i)).toBeInTheDocument();
  expect(screen.getByText(/5m close/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- --runInBand tests/operator-panels.test.tsx`
Expected: FAIL because the panels still present a single swing-style target and do not render the new level labels.

- [ ] **Step 3: Write minimal implementation**

```tsx
<LevelCard label="Entry" value={formatPrice(call.entry)} />
<LevelCard label="Execution stop" value={formatPrice(call.execution_stop ?? call.stop_loss)} />
<LevelCard label="Primary target" value={formatPrice(call.primary_target ?? call.take_profit)} />
{call.thesis_invalidation ? (
  <LevelCard label="Thesis invalidation" value={formatPrice(call.thesis_invalidation)} />
) : null}
```

```tsx
<p>{call.hold_horizon_minutes ? `Primary objective is modeled for the next ${call.hold_horizon_minutes} minutes.` : defaultCopy}</p>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- --runInBand tests/operator-panels.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add external/mitemshub-indices/src/components/operator/primary-call-panel.tsx external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx external/mitemshub-indices/src/lib/mock-data.ts external/mitemshub-indices/tests/operator-panels.test.tsx
git commit -m "feat: present intraday primary target and thesis invalidation"
```

### Task 7: End-To-End Verification

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\api-routes.test.ts`

- [ ] **Step 1: Write the failing tests**

```python
def test_live_r100_intraday_plan_does_not_publish_swing_sized_target() -> None:
    snapshot = analyze_live_snapshot(...)
    assert snapshot["primary_target"] is not None
    assert snapshot["primary_target"] != snapshot["thesis_invalidation"]
    assert snapshot["primary_target"] == snapshot["take_profit"]
```

```ts
it("POST /api/calls/run preserves intraday execution geometry fields", async () => {
  vi.spyOn(engineBridge, "runFreshCall").mockResolvedValue({
    ...baseCall,
    execution_stop: 474.8,
    thesis_invalidation: 440.67,
    primary_target: 488.8,
    extended_target: 493.4,
    hold_horizon_minutes: 60,
  });

  const response = await postRun(request);
  const payload = await response.json();
  expect(payload.primary_target).toBe(488.8);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_live_market_snapshot.py -v`
Expected: FAIL if the payload still collapses to legacy stop/target semantics.

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- --runInBand tests/api-routes.test.ts`
Expected: FAIL until the API route fixtures and response schema preserve the new fields.

- [ ] **Step 3: Write minimal implementation**

```ts
expect(runFreshCallSpy).toHaveBeenCalledWith(
  expect.objectContaining({
    symbol: "R_100",
    reusePreparedCall: "never",
  }),
);
expect(payload.execution_stop).toBe(474.8);
expect(payload.thesis_invalidation).toBe(440.67);
expect(payload.primary_target).toBe(488.8);
```

```python
assert snapshot["stop_loss"] == snapshot["execution_stop"]
assert snapshot["take_profit"] == snapshot["primary_target"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_intraday_execution_builder.py tests/test_decision_engine.py tests/test_live_market_snapshot.py -q`
Expected: PASS

Run: `& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- --runInBand tests/contracts.test.ts tests/engine-bridge.test.ts tests/operator-panels.test.tsx tests/api-routes.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_live_market_snapshot.py external/mitemshub-indices/tests/api-routes.test.ts
git commit -m "test: verify end-to-end intraday execution geometry"
```

## Self-Review

- Spec coverage:
  - top-down bias preserved: Task 3
  - `5m` execution stop and trigger rewrite: Tasks 2 and 3
  - reachable primary target for next `30m-1h`: Tasks 2, 3, and 4
  - UI separation of execution stop vs thesis invalidation: Tasks 5 and 6
  - regression coverage across Python and app contract: Tasks 2 through 7
- Placeholder scan:
  - no `TODO`, `TBD`, or “similar to above” references remain
  - each code-changing step includes example code or assertions
- Type consistency:
  - field names are consistent across Python and TypeScript: `execution_stop`, `thesis_invalidation`, `primary_target`, `extended_target`, `hold_horizon_minutes`
