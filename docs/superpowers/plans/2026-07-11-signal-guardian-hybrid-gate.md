# Signal Guardian Hybrid Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing Signal Guardian so weak synthetic-index setups stay blocked before confirmation and late rollovers downgrade or invalidate faster after follow-through begins to deteriorate.

**Architecture:** Keep the existing guardian lifecycle and bridge contracts, but replace the lightweight confirmation logic with a stricter multi-check entry gate and a dedicated rollover detector built on richer tick microstructure helpers. Surface the sharper guardian reasons through the current Python snapshot, Next.js bridge, and operator UI without changing the public state vocabulary.

**Tech Stack:** Python 3, existing Synthetic Trader engine, Next.js 15, React 19, TypeScript, Zod, Vitest, React Testing Library

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot`

Python engine files:

- Modify: `src/synthetic_trader/live/signal_guardian.py`
  - Expand thresholds, add structured microstructure helpers, implement the stricter entry gate, and add a rollover detector.
- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Feed the enhanced guardian with the richer context and preserve sharper guardian reason text.
- Modify: `tests/test_signal_guardian.py`
  - Add the false-entry, drift, pullback, and late-reversal regressions that should fail against the current simple guardian.
- Modify: `tests/test_live_market_snapshot.py`
  - Verify enriched guardian reasons and state transitions survive snapshot packaging.

Web bridge and UI files:

- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
  - Preserve the stronger guardian reason output and keep unavailable behavior honest.
- Modify: `external/mitemshub-indices/src/lib/formatters.ts`
  - Add clearer trader-facing formatting for stricter guardian reasons.
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
  - Show stronger `armed`, `weakening`, and `invalidated` guidance without ambiguity.
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
  - Keep execution levels hidden until the stricter guardian gate says `confirmed`.

Web tests:

- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
  - Ensure strengthened guardian reasons and unavailable fallback still serialize correctly.
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`
  - Verify `armed` setups stay non-tradable and weakening/invalidated copy is explicit.
- Modify: `external/mitemshub-indices/tests/operator-panels.test.tsx`
  - Verify panel-level rendering for `confirmed`, `weakening`, and `invalidated` states.

### Task 1: Harden The Python Guardian Threshold Model

**Files:**
- Modify: `src/synthetic_trader/live/signal_guardian.py`
- Modify: `tests/test_signal_guardian.py`

- [ ] **Step 1: Write the failing guardian regression tests**

```python
def test_buy_setup_stays_armed_when_persistence_is_too_weak(self) -> None:
    snapshot = GuardianSnapshot(
        symbol="R_100",
        direction_bias="buy",
        trade_status="valid",
        entry=459.6,
        stop_loss=458.2,
        take_profit=462.2,
        current_close=459.67,
    )
    context = GuardianContext(
        tick_prices=[459.58, 459.61, 459.59, 459.64, 459.62, 459.67],
        ticks_since_armed=4,
        max_favorable_excursion=0.09,
        max_adverse_excursion=0.05,
    )

    result = evaluate_signal_guardian(snapshot, context, self.thresholds)

    self.assertEqual(result.state, "armed")
    self.assertIn("persistence", result.reason.lower())


def test_buy_setup_stays_armed_when_entry_drift_gets_too_large(self) -> None:
    snapshot = GuardianSnapshot(
        symbol="R_100",
        direction_bias="buy",
        trade_status="valid",
        entry=459.6,
        stop_loss=458.2,
        take_profit=462.2,
        current_close=460.9,
    )
    context = GuardianContext(
        tick_prices=[460.1, 460.2, 460.35, 460.48, 460.72, 460.9],
        ticks_since_armed=5,
        max_favorable_excursion=1.3,
        max_adverse_excursion=0.0,
    )

    result = evaluate_signal_guardian(snapshot, context, self.thresholds)

    self.assertEqual(result.state, "armed")
    self.assertIn("drift", result.reason.lower())


def test_buy_setup_weakens_when_pullback_depth_breaks_rollover_warning(self) -> None:
    snapshot = GuardianSnapshot(
        symbol="R_100",
        direction_bias="buy",
        trade_status="valid",
        entry=459.6,
        stop_loss=458.2,
        take_profit=462.2,
        current_close=459.44,
    )
    context = GuardianContext(
        tick_prices=[459.92, 459.86, 459.75, 459.62, 459.53, 459.44],
        ticks_since_armed=5,
        max_favorable_excursion=0.32,
        max_adverse_excursion=0.16,
    )

    result = evaluate_signal_guardian(snapshot, context, self.thresholds)

    self.assertEqual(result.state, "weakening")
    self.assertIn("reversal", result.reason.lower())
```

- [ ] **Step 2: Run the focused Python guardian tests to verify they fail**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
```

Expected: FAIL because the current guardian still confirms from a shallow slope and lacks drift and rollover-specific reasoning

- [ ] **Step 3: Expand the threshold dataclass and helper surface**

```python
@dataclass(frozen=True)
class GuardianThresholds:
    max_arming_ticks: int
    max_confirmation_window_ticks: int
    weakening_excursion_ratio: float
    max_adverse_excursion_ratio: float
    max_entry_drift_ratio: float
    microstructure_window_ticks: int
    min_persistence_ticks: int
    min_impulse_ratio: float
    max_pullback_ratio: float
    rollover_warning_ratio: float
    rollover_invalidation_ratio: float
    adverse_cluster_window_ticks: int
    max_adverse_cluster_count: int
```

```python
@dataclass(frozen=True)
class MicrostructureAssessment:
    persistence_ticks: int
    impulse_ratio: float
    pullback_ratio: float
    rejection_imbalance: float
    acceleration_shift: float
    adverse_cluster_count: int
```

- [ ] **Step 4: Implement the richer microstructure helpers**

```python
def _directional_deltas(prices: list[float], direction_bias: str) -> list[float]:
    raw = [right - left for left, right in zip(prices, prices[1:])]
    if direction_bias == "buy":
        return raw
    if direction_bias == "sell":
        return [-delta for delta in raw]
    return [0.0 for _ in raw]


def _count_persistence_ticks(direction_deltas: list[float]) -> int:
    return sum(1 for delta in direction_deltas if delta > 0)


def _count_adverse_clusters(direction_deltas: list[float]) -> int:
    clusters = 0
    previous_was_adverse = False
    for delta in direction_deltas:
        is_adverse = delta < 0
        if is_adverse and not previous_was_adverse:
            clusters += 1
        previous_was_adverse = is_adverse
    return clusters


def _assess_microstructure(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
    stop_distance: float,
) -> MicrostructureAssessment:
    prices = context.tick_prices[-thresholds.microstructure_window_ticks :]
    direction_deltas = _directional_deltas(prices, snapshot.direction_bias)
    positive = [delta for delta in direction_deltas if delta > 0]
    adverse = [abs(delta) for delta in direction_deltas if delta < 0]
    impulse_ratio = sum(positive) / stop_distance if stop_distance else 0.0
    pullback_ratio = max(adverse, default=0.0) / stop_distance if stop_distance else 0.0
    rejection_imbalance = sum(positive) - sum(adverse)
    acceleration_shift = direction_deltas[-1] - direction_deltas[0] if len(direction_deltas) >= 2 else 0.0
    return MicrostructureAssessment(
        persistence_ticks=_count_persistence_ticks(direction_deltas),
        impulse_ratio=impulse_ratio,
        pullback_ratio=pullback_ratio,
        rejection_imbalance=rejection_imbalance,
        acceleration_shift=acceleration_shift,
        adverse_cluster_count=_count_adverse_clusters(
            direction_deltas[-thresholds.adverse_cluster_window_ticks :]
        ),
    )
```

- [ ] **Step 5: Replace the lightweight confirmation path with the hybrid gate**

```python
def _entry_drift_ratio(snapshot: GuardianSnapshot, stop_distance: float) -> float:
    if snapshot.current_close is None or snapshot.entry is None or stop_distance <= 0:
        return 0.0
    return abs(snapshot.current_close - snapshot.entry) / stop_distance


def _passes_entry_gate(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
    stop_distance: float,
    micro: MicrostructureAssessment,
) -> tuple[bool, str]:
    if micro.persistence_ticks < thresholds.min_persistence_ticks:
        return False, "Directional thesis is armed, but persistence is still too weak for confirmation."
    if micro.impulse_ratio < thresholds.min_impulse_ratio:
        return False, "Directional thesis is armed, but impulse quality is still too weak for confirmation."
    if micro.pullback_ratio > thresholds.max_pullback_ratio:
        return False, "Directional thesis is armed, but pullback depth is still too large for confirmation."
    if _entry_drift_ratio(snapshot, stop_distance) > thresholds.max_entry_drift_ratio:
        return False, "Directional thesis is armed, but price drift is too large to trust the old entry."
    if context.ticks_since_armed > thresholds.max_confirmation_window_ticks:
        return False, "Directional thesis is armed, but the confirmation window has already gone stale."
    if micro.rejection_imbalance <= 0:
        return False, "Directional thesis is armed, but rejection quality is still too mixed for confirmation."
    return True, ""
```

- [ ] **Step 6: Add the dedicated rollover detector**

```python
def _detect_rollover(
    micro: MicrostructureAssessment,
    thresholds: GuardianThresholds,
) -> tuple[str | None, str | None]:
    if micro.adverse_cluster_count >= thresholds.max_adverse_cluster_count:
        return "invalidated", "Setup invalidated after reversal pressure clustered too aggressively."
    if micro.pullback_ratio >= thresholds.rollover_invalidation_ratio:
        return "invalidated", "Setup invalidated after pullback depth broke the rollover guardrail."
    if micro.pullback_ratio >= thresholds.rollover_warning_ratio or micro.acceleration_shift < 0:
        return "weakening", "Setup is weakening after reversal pressure increased against the thesis."
    return None, None
```

- [ ] **Step 7: Rebuild `evaluate_signal_guardian()` around the new checks**

```python
micro = _assess_microstructure(snapshot, context, thresholds, stop_distance)
rollover_state, rollover_reason = _detect_rollover(micro, thresholds)
if rollover_state:
    return GuardianEvaluation(rollover_state, rollover_reason or "Setup is weakening.")

passes_entry_gate, gate_reason = _passes_entry_gate(
    snapshot,
    context,
    thresholds,
    stop_distance,
    micro,
)
if passes_entry_gate:
    return GuardianEvaluation(
        "confirmed",
        f"{snapshot.direction_bias.capitalize()} setup confirmed after strong reclaim and controlled pullback.",
    )

return GuardianEvaluation("armed", gate_reason)
```

- [ ] **Step 8: Run the focused Python guardian tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
```

Expected: PASS

- [ ] **Step 9: Commit the guardian hardening core**

```bash
git add src/synthetic_trader/live/signal_guardian.py tests/test_signal_guardian.py
git commit -m "feat: harden guardian entry and rollover gates"
```

### Task 2: Thread The Sharper Guardian Reasons Through Snapshot Packaging

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Modify: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing snapshot packaging tests**

```python
def test_build_guardian_snapshot_preserves_armed_reason_for_weak_persistence() -> None:
    ticks = [
        Tick(symbol="R_100", epoch=1, price=459.58),
        Tick(symbol="R_100", epoch=2, price=459.61),
        Tick(symbol="R_100", epoch=3, price=459.59),
        Tick(symbol="R_100", epoch=4, price=459.64),
        Tick(symbol="R_100", epoch=5, price=459.62),
        Tick(symbol="R_100", epoch=6, price=459.67),
    ]
    enriched = build_guardian_snapshot(
        {
            "symbol": "R_100",
            "trade_status": "valid",
            "direction_bias": "buy",
            "entry": 459.6,
            "stop_loss": 458.2,
            "take_profit": 462.2,
        },
        ticks,
    )

    assert enriched["guardian_state"] == "armed"
    assert "persistence" in str(enriched["guardian_reason"]).lower()


def test_build_watch_alert_preserves_rollover_reason_text() -> None:
    alert = build_watch_alert(
        {
            "call": "buy_candidate",
            "trade_status": "valid",
            "direction_bias": "buy",
            "symbol": "R_100",
            "current_close": 459.44,
            "guardian_state": "weakening",
            "guardian_reason": "Setup is weakening after reversal pressure increased against the thesis.",
        }
    )

    assert alert["guardian_state"] == "weakening"
    assert "reversal pressure" in str(alert["guardian_reason"]).lower()
```

- [ ] **Step 2: Run the focused snapshot tests to verify they fail**

Run:

```powershell
py -3 -m pytest tests/test_live_market_snapshot.py -k "guardian_reason or persistence" -q
```

Expected: FAIL because the current snapshot helper does not yet produce the stronger hybrid-gate reasoning

- [ ] **Step 3: Update the guardian thresholds used by snapshot enrichment**

```python
DEFAULT_GUARDIAN_THRESHOLDS = GuardianThresholds(
    max_arming_ticks=12,
    max_confirmation_window_ticks=6,
    weakening_excursion_ratio=0.35,
    max_adverse_excursion_ratio=0.8,
    max_entry_drift_ratio=0.75,
    microstructure_window_ticks=6,
    min_persistence_ticks=4,
    min_impulse_ratio=0.12,
    max_pullback_ratio=0.22,
    rollover_warning_ratio=0.18,
    rollover_invalidation_ratio=0.3,
    adverse_cluster_window_ticks=4,
    max_adverse_cluster_count=2,
)
```

- [ ] **Step 4: Keep the stronger guardian output in snapshot packaging**

```python
guardian = evaluate_signal_guardian(
    signal_snapshot,
    GuardianContext(
        tick_prices=prices,
        ticks_since_armed=len(prices),
        max_favorable_excursion=max_favorable_excursion,
        max_adverse_excursion=max_adverse_excursion,
    ),
    DEFAULT_GUARDIAN_THRESHOLDS,
)
enriched["guardian_state"] = guardian.state
enriched["guardian_reason"] = guardian.reason
```

- [ ] **Step 5: Run the focused snapshot tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_live_market_snapshot.py -k "guardian_reason or persistence" -q
```

Expected: PASS

- [ ] **Step 6: Commit the snapshot packaging changes**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: carry hybrid guardian reasons through snapshots"
```

### Task 3: Preserve Harder Guardian Truth In The Bridge

**Files:**
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`

- [ ] **Step 1: Write the failing bridge tests**

```ts
it("preserves armed guardian reasons when confirmation is blocked", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
  vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
    symbol: "R_100",
    call: "buy_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.7,
    regime: "trend_up",
    direction_bias: "buy",
    why: "buyers still control the short-term move",
    wait_for: "wait for a clean bullish continuation close",
    decision_summary: "buy thesis present",
    entry_area: "around 459.6",
    stop_area: "below 458.2",
    target_area: "toward 462.2",
    entry: 459.6,
    stop_loss: 458.2,
    take_profit: 462.2,
    reward_risk: 2,
    current_close: 459.67,
    guardian_state: "armed",
    guardian_reason: "Directional thesis is armed, but persistence is still too weak for confirmation.",
    generated_at: "2026-07-11T04:00:00Z",
  } as never);

  const result = await engineBridge.runFreshCall({
    symbol: "R_100",
    accountMode: "own_account",
    propAccountState: null,
  });

  expect(result.guardian_state).toBe("armed");
  expect(result.guardian_reason).toMatch(/persistence is still too weak/i);
  expect(result.entry).toBe(459.6);
});

it("keeps unavailable execution levels null when live analysis cannot be trusted", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
  vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockRejectedValue(new Error("bridge down"));

  const result = await engineBridge.runFreshCall({
    symbol: "R_100",
    accountMode: "own_account",
    propAccountState: null,
  });

  expect(result.guardian_state).toBe("unavailable");
  expect(result.entry).toBeNull();
  expect(result.stop_loss).toBeNull();
  expect(result.take_profit).toBeNull();
});
```

- [ ] **Step 2: Run the focused bridge tests to verify they fail**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts
```

Expected: FAIL because the current bridge tests do not yet lock the stronger guardian reasons

- [ ] **Step 3: Keep the bridge serialization unchanged but expand the regression coverage**

```ts
function buildUnavailableBaseCall({
  symbol,
  detail,
}: {
  symbol: SymbolCode;
  detail: string;
}): BaseFreshCall {
  return {
    symbol,
    call: "stand_aside",
    alert_type: "context_update",
    trade_status: "not_valid",
    confidence: null,
    regime: null,
    direction_bias: null,
    why: `Live market read unavailable. ${detail}`,
    wait_for: "wait for the live bridge to reconnect, then refresh the call",
    decision_summary: "Live market read unavailable. Refresh after the live bridge reconnects.",
    entry_area: null,
    stop_area: null,
    target_area: null,
    entry: null,
    stop_loss: null,
    take_profit: null,
    reward_risk: null,
    current_close: null,
    guardian_state: "unavailable",
    guardian_reason: `Live market read unavailable. ${detail}`,
    generated_at: new Date().toISOString(),
  };
}
```

- [ ] **Step 4: Run the focused bridge tests to verify they pass**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit the bridge regression hardening**

```bash
git add external/mitemshub-indices/src/lib/engine-bridge.ts external/mitemshub-indices/tests/engine-bridge.test.ts
git commit -m "test: lock stronger guardian bridge behavior"
```

### Task 4: Tighten Operator-Facing Guardian Messaging

**Files:**
- Modify: `external/mitemshub-indices/src/lib/formatters.ts`
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`
- Modify: `external/mitemshub-indices/tests/operator-panels.test.tsx`

- [ ] **Step 1: Write the failing UI tests**

```tsx
it("shows a plain-language armed warning when persistence is too weak", async () => {
  render(
    <TradeInstructionPanel
      call={{
        symbol: "R_100",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.7,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers still control the short-term move",
        wait_for: "wait for a clean bullish continuation close",
        decision_summary: "buy thesis present",
        entry_area: "around 459.6",
        stop_area: "below 458.2",
        target_area: "toward 462.2",
        entry: 459.6,
        stop_loss: 458.2,
        take_profit: 462.2,
        reward_risk: 2,
        current_close: 459.67,
        guardian_state: "armed",
        guardian_reason: "Directional thesis is armed, but persistence is still too weak for confirmation.",
        generated_at: "2026-07-11T04:10:00.000Z",
        account_mode: "own_account",
        prop_compliance: null,
        prop_adjusted_risk: null,
        prop_block_reason: null,
        prop_remaining_daily_buffer: null,
        prop_remaining_overall_buffer: null,
      }}
      guardianStatus={null}
    />,
  );

  expect(screen.getByText(/persistence is still too weak/i)).toBeInTheDocument();
  expect(screen.queryByText(/^entry$/i)).not.toBeInTheDocument();
});

it("shows weakening guidance when reversal pressure is increasing", async () => {
  render(
    <PrimaryCallPanel
      call={{
        symbol: "R_100",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.7,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers still control the short-term move",
        wait_for: "wait for a clean bullish continuation close",
        decision_summary: "buy thesis present",
        entry_area: "around 459.6",
        stop_area: "below 458.2",
        target_area: "toward 462.2",
        entry: 459.6,
        stop_loss: 458.2,
        take_profit: 462.2,
        reward_risk: 2,
        current_close: 459.44,
        guardian_state: "weakening",
        guardian_reason: "Setup is weakening after reversal pressure increased against the thesis.",
        generated_at: "2026-07-11T04:10:00.000Z",
        account_mode: "own_account",
        prop_compliance: null,
        prop_adjusted_risk: null,
        prop_block_reason: null,
        prop_remaining_daily_buffer: null,
        prop_remaining_overall_buffer: null,
      }}
      guardianStatus={null}
      loading={false}
    />,
  );

  expect(screen.getByText(/reversal pressure increased/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused UI tests to verify they fail**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx tests/operator-panels.test.tsx
```

Expected: FAIL because the current UI copy does not yet emphasize the harder hybrid-gate reasons strongly enough

- [ ] **Step 3: Add trader-facing formatter helpers for sharper guardian copy**

```ts
export function formatGuardianState(state: FreshCallResponse["guardian_state"]): string {
  switch (state) {
    case "forming":
      return "Forming"
    case "armed":
      return "Armed"
    case "confirmed":
      return "Confirmed"
    case "weakening":
      return "Weakening"
    case "invalidated":
      return "Invalidated"
    case "unavailable":
      return "Unavailable"
  }
}

export function formatGuardianAction(state: FreshCallResponse["guardian_state"]): string {
  switch (state) {
    case "confirmed":
      return "The setup is confirmed and the execution levels are active."
    case "armed":
      return "The setup is not confirmed yet. Do not use the old entry levels."
    case "weakening":
      return "The setup is degrading. Do not act on the old plan."
    case "invalidated":
      return "The original setup is no longer valid."
    default:
      return "Wait for a fresh live read before acting."
  }
}
```

- [ ] **Step 4: Render the harder guidance in the panels**

```tsx
<p className="mt-2 text-sm leading-6 text-[var(--text-body)]">
  {guardianReason}
</p>
<p className="mt-3 text-sm leading-6 text-[rgba(15,23,42,0.72)]">
  {formatGuardianAction(effectiveGuardianState)}
</p>
```

```tsx
{showExecutionLevels ? (
  <dl className="grid gap-3 md:grid-cols-3">
    {/* Entry / Stop / Target */}
  </dl>
) : (
  <div className="info-card rounded-[24px] p-4">
    <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
      Execution levels
    </p>
    <p className="mt-3 text-sm leading-7 text-[var(--text-body)]">
      {formatGuardianAction(effectiveGuardianState)}
    </p>
  </div>
)}
```

- [ ] **Step 5: Run the focused UI tests to verify they pass**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx tests/operator-panels.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit the UI hardening**

```bash
git add external/mitemshub-indices/src/lib/formatters.ts external/mitemshub-indices/src/components/operator/primary-call-panel.tsx external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx external/mitemshub-indices/tests/operator-shell.test.tsx external/mitemshub-indices/tests/operator-panels.test.tsx
git commit -m "feat: sharpen guardian operator guidance"
```

### Task 5: Final Regression Pass For False Entries And Late Rollovers

**Files:**
- Modify: `tests/test_signal_guardian.py`
- Modify: `tests/test_live_market_snapshot.py`
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`
- Modify: `external/mitemshub-indices/tests/operator-panels.test.tsx`

- [ ] **Step 1: Add the full false-entry and rollover regression cases**

```python
def test_buy_setup_stays_armed_when_single_impulse_is_not_supported_by_persistence(self) -> None:
    snapshot = GuardianSnapshot(
        symbol="R_100",
        direction_bias="buy",
        trade_status="valid",
        entry=459.6,
        stop_loss=458.2,
        take_profit=462.2,
        current_close=459.74,
    )
    context = GuardianContext(
        tick_prices=[459.56, 459.58, 459.57, 459.59, 459.6, 459.74],
        ticks_since_armed=4,
        max_favorable_excursion=0.14,
        max_adverse_excursion=0.04,
    )

    result = evaluate_signal_guardian(snapshot, context, self.thresholds)

    self.assertEqual(result.state, "armed")
```

```ts
it("keeps execution levels hidden while a setup is only armed", async () => {
  render(
    <TradeInstructionPanel
      call={buildCall({
        guardian_state: "armed",
        guardian_reason: "Directional thesis is armed, but persistence is still too weak for confirmation.",
      })}
      guardianStatus={null}
    />,
  );

  expect(screen.queryByText(/^entry$/i)).not.toBeInTheDocument();
  expect(screen.getByText(/do not use the old entry levels/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused regression suites**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py tests/test_live_market_snapshot.py -q
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/operator-shell.test.tsx tests/operator-panels.test.tsx
```

Expected: PASS

- [ ] **Step 3: Run the full verification suite**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py tests/test_live_market_snapshot.py -q
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run build
```

Expected:

- Python guardian and snapshot tests PASS
- Vitest suite PASS
- Next.js build PASS

- [ ] **Step 4: Commit the final hardening regression pass**

```bash
git add tests/test_signal_guardian.py tests/test_live_market_snapshot.py external/mitemshub-indices/tests/engine-bridge.test.ts external/mitemshub-indices/tests/operator-shell.test.tsx external/mitemshub-indices/tests/operator-panels.test.tsx
git commit -m "test: harden guardian false-entry and rollover coverage"
```

## Self-Review

Spec coverage:

1. stricter entry-gate behavior is implemented in Task 1
2. richer microstructure helpers are implemented in Task 1
3. dedicated rollover detection is implemented in Task 1
4. sharper guardian reasons are preserved through snapshot packaging in Task 2
5. operator-facing hardening is implemented in Task 4
6. false-entry and late-reversal regressions are covered in Task 5

Placeholder scan:

1. no `TODO`, `TBD`, or undefined future references remain
2. each task contains exact files, code, commands, and expected outcomes

Type consistency:

1. `guardian_state` and `guardian_reason` are reused consistently across Python, bridge, and UI tasks
2. the new threshold names introduced in Task 1 are reused consistently in later tasks
3. the UI continues using the existing public guardian lifecycle values without renaming them

Plan complete and saved to `docs/superpowers/plans/2026-07-11-signal-guardian-hybrid-gate.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
