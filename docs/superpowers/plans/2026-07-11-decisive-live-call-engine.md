# Decisive Live Call Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the slow click-triggered live read with a continuous `R_75` / `R_100` watcher that returns faster, more actionable trade calls and exposes richer execution truth to the operator UI.

**Architecture:** Build a Python watcher layer that maintains rolling live symbol state, then make the Next bridge read prepared watcher packages instead of launching a fresh heavy scan on every click. Replace the current confirmed-only operator behavior with a two-stage `actionable -> confirmed` model plus `failing` and `cancelled` invalidation states, while keeping explicit freshness and degraded-mode handling.

**Tech Stack:** Python 3, pytest, existing Synthetic Trader engine, Next.js 15, React 19, TypeScript, Zod, Vitest, React Testing Library

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot`

Python engine files:

- Create: `src/synthetic_trader/live/live_symbol_watcher.py`
  - Own continuous symbol state, freshness timestamps, and prepared decision package reads.
- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Split cold snapshot analysis from watcher-backed prepared state reads and enrich decision payload fields.
- Modify: `src/synthetic_trader/live/signal_guardian.py`
  - Replace current public lifecycle mapping with `forming`, `actionable`, `confirmed`, `failing`, `cancelled`, and `unavailable`.
- Modify: `tests/test_live_market_snapshot.py`
  - Cover watcher-backed prepared reads, freshness metadata, and degraded-mode responses.
- Modify: `tests/test_signal_guardian.py`
  - Cover the new lifecycle transitions and relaxed actionable publication rules.
- Create: `tests/test_live_symbol_watcher.py`
  - Focused watcher regression coverage.

Bridge and app files:

- Modify: `external/mitemshub-indices/src/lib/contracts.ts`
  - Add the new call states and freshness / invalidation fields.
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
  - Query watcher-backed prepared state and preserve degraded-mode truth.
- Modify: `external/mitemshub-indices/app/api/calls/run/route.ts`
  - Continue returning safe JSON errors while forwarding the richer decision package.
- Modify: `external/mitemshub-indices/src/hooks/use-operator-workspace.ts`
  - Read and store freshness-aware call packages.
- Modify: `external/mitemshub-indices/src/lib/formatters.ts`
  - Replace blanket wording with technical trader-facing copy.
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
  - Show call age, sharper state labels, and richer market thesis.
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
  - Show execution levels for `actionable`, preserve stale-plan warnings for `failing`, and block `cancelled`.
- Modify: `external/mitemshub-indices/tests/contracts.test.ts`
  - Cover schema additions.
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
  - Cover watcher-backed fast reads and new state normalization.
- Modify: `external/mitemshub-indices/tests/api-routes.test.ts`
  - Cover enriched route payloads.
- Modify: `external/mitemshub-indices/tests/formatters.test.ts`
  - Cover updated state labels and action wording.
- Modify: `external/mitemshub-indices/tests/operator-panels.test.tsx`
  - Cover actionable levels, failing-state staleness, and cancelled-state blocking.
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`
  - Cover freshness rendering and end-to-end symbol selection behavior.

## Task 1: Add The Python Watcher Contract

**Files:**
- Create: `src/synthetic_trader/live/live_symbol_watcher.py`
- Create: `tests/test_live_symbol_watcher.py`

- [ ] **Step 1: Write the failing watcher tests**

```python
from synthetic_trader.live.live_symbol_watcher import (
    LiveSymbolWatcherStore,
    PreparedSymbolState,
)


def test_prepared_symbol_state_tracks_freshness_and_levels() -> None:
    store = LiveSymbolWatcherStore()
    prepared = PreparedSymbolState(
        symbol="R_75",
        call="sell_candidate",
        state="actionable",
        confidence=0.62,
        regime="range",
        market_thesis="sellers still control the upper rejection zone",
        entry_area="around 53074.2",
        entry=53074.2,
        stop_area="above 53173.2",
        stop_loss=53173.2,
        target_area="toward 52886.2",
        take_profit=52886.2,
        reward_risk=1.9,
        invalidates_if="price closes back above the rejection shelf",
        next_trigger="a fresh bearish continuation close",
        current_close=53074.2,
        call_age_seconds=3,
        generated_at="2026-07-11T20:32:54.127Z",
    )

    store.update(prepared)
    loaded = store.get("R_75")

    assert loaded is not None
    assert loaded.state == "actionable"
    assert loaded.call_age_seconds == 3
    assert loaded.entry == 53074.2


def test_store_returns_unavailable_snapshot_when_symbol_has_no_prepared_state() -> None:
    store = LiveSymbolWatcherStore()

    loaded = store.get("R_100")

    assert loaded is None
```

- [ ] **Step 2: Run the watcher test file to verify it fails**

Run:

```powershell
py -3 -m pytest tests/test_live_symbol_watcher.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `live_symbol_watcher`

- [ ] **Step 3: Write the minimal watcher store**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedSymbolState:
    symbol: str
    call: str
    state: str
    confidence: float | None
    regime: str | None
    market_thesis: str
    entry_area: str | None
    entry: float | None
    stop_area: str | None
    stop_loss: float | None
    target_area: str | None
    take_profit: float | None
    reward_risk: float | None
    invalidates_if: str
    next_trigger: str
    current_close: float | None
    call_age_seconds: int
    generated_at: str


class LiveSymbolWatcherStore:
    def __init__(self) -> None:
        self._states: dict[str, PreparedSymbolState] = {}

    def update(self, state: PreparedSymbolState) -> None:
        self._states[state.symbol] = state

    def get(self, symbol: str) -> PreparedSymbolState | None:
        return self._states.get(symbol)
```

- [ ] **Step 4: Run the watcher test file to verify it passes**

Run:

```powershell
py -3 -m pytest tests/test_live_symbol_watcher.py -q
```

Expected: PASS with `2 passed`

- [ ] **Step 5: Commit the watcher contract**

```bash
git add src/synthetic_trader/live/live_symbol_watcher.py tests/test_live_symbol_watcher.py
git commit -m "feat: add live symbol watcher contract"
```

## Task 2: Replace Guardian Lifecycle With Actionable / Failing / Cancelled

**Files:**
- Modify: `src/synthetic_trader/live/signal_guardian.py`
- Modify: `tests/test_signal_guardian.py`

- [ ] **Step 1: Extend the failing guardian tests for the new public states**

```python
def test_usable_setup_becomes_actionable_before_full_confirmation() -> None:
    snapshot = GuardianSnapshot(
        symbol="R_75",
        direction_bias="sell",
        trade_status="valid",
        entry=53074.2,
        stop_loss=53173.2,
        take_profit=52886.2,
        current_close=53070.0,
    )
    context = GuardianContext(
        tick_prices=[53090.0, 53084.0, 53080.0, 53076.0, 53072.0, 53070.0],
        ticks_since_armed=2,
        max_favorable_excursion=24.0,
        max_adverse_excursion=8.0,
    )

    result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

    assert result.state == "actionable"
    assert "usable" in result.reason.lower() or "actionable" in result.reason.lower()


def test_deteriorating_setup_moves_to_failing_before_cancelled() -> None:
    snapshot = GuardianSnapshot(
        symbol="R_75",
        direction_bias="sell",
        trade_status="valid",
        entry=53074.2,
        stop_loss=53173.2,
        take_profit=52886.2,
        current_close=53110.0,
    )
    context = GuardianContext(
        tick_prices=[53072.0, 53076.0, 53085.0, 53094.0, 53103.0, 53110.0],
        ticks_since_armed=4,
        max_favorable_excursion=16.0,
        max_adverse_excursion=40.0,
    )

    result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

    assert result.state == "failing"
```

- [ ] **Step 2: Run the targeted guardian tests to verify they fail**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
```

Expected: FAIL because `actionable` and `failing` are not yet emitted

- [ ] **Step 3: Write the minimal lifecycle remap**

```python
def evaluate_signal_guardian(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
) -> GuardianEvaluation:
    if snapshot.trade_status != "valid" or snapshot.direction_bias not in {"buy", "sell"}:
        return GuardianEvaluation("forming", "Directional thesis is still forming.")

    stop_distance = _stop_distance(snapshot)
    if not stop_distance or stop_distance <= 0:
        return GuardianEvaluation("unavailable", "Live guard cannot score the setup without levels.")

    adverse_ratio = context.max_adverse_excursion / stop_distance
    micro = _assess_microstructure(snapshot, context, thresholds, stop_distance)

    if adverse_ratio >= thresholds.max_adverse_excursion_ratio:
        return GuardianEvaluation("cancelled", "The original trade thesis is broken and should not be used.")

    if adverse_ratio >= thresholds.weakening_excursion_ratio or micro.adverse_cluster_count > 0:
        return GuardianEvaluation("failing", "The setup is deteriorating and the old plan is no longer fresh.")

    passes_entry_gate, gate_reason = _passes_entry_gate(
        snapshot,
        context,
        thresholds,
        stop_distance,
        micro,
    )
    if passes_entry_gate:
        return GuardianEvaluation("confirmed", "Continuation quality is strong and the setup is confirmed.")

    return GuardianEvaluation("actionable", gate_reason or "The setup is actionable with caution.")
```

- [ ] **Step 4: Run the guardian tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
```

Expected: PASS

- [ ] **Step 5: Commit the guardian lifecycle upgrade**

```bash
git add src/synthetic_trader/live/signal_guardian.py tests/test_signal_guardian.py
git commit -m "feat: add actionable live guardian states"
```

## Task 3: Expose Prepared Watcher State From The Python Snapshot Layer

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Modify: `tests/test_live_market_snapshot.py`
- Create or extend: `src/synthetic_trader/live/live_symbol_watcher.py`

- [ ] **Step 1: Add the failing snapshot test for prepared-state reads**

```python
from synthetic_trader.live.live_symbol_watcher import LiveSymbolWatcherStore, PreparedSymbolState
from synthetic_trader.live.market_snapshot import build_watch_alert_from_prepared_state


def test_build_watch_alert_from_prepared_state_preserves_actionable_levels() -> None:
    prepared = PreparedSymbolState(
        symbol="R_100",
        call="buy_candidate",
        state="actionable",
        confidence=0.64,
        regime="trend_up",
        market_thesis="buyers reclaimed the pullback shelf and still control continuation",
        entry_area="around 51234.6",
        entry=51234.6,
        stop_area="below 51188.2",
        stop_loss=51188.2,
        target_area="toward 51326.4",
        take_profit=51326.4,
        reward_risk=2.0,
        invalidates_if="price closes back below the reclaimed shelf",
        next_trigger="another bullish continuation close",
        current_close=51240.1,
        call_age_seconds=2,
        generated_at="2026-07-11T22:00:00.000Z",
    )

    alert = build_watch_alert_from_prepared_state(prepared)

    assert alert["guardian_state"] == "actionable"
    assert alert["entry"] == 51234.6
    assert alert["call_age_seconds"] == 2
```

- [ ] **Step 2: Run the targeted market snapshot test to verify it fails**

Run:

```powershell
py -3 -m pytest tests/test_live_market_snapshot.py -q
```

Expected: FAIL because `build_watch_alert_from_prepared_state` does not exist

- [ ] **Step 3: Add the prepared-state alert adapter**

```python
def build_watch_alert_from_prepared_state(prepared: PreparedSymbolState) -> dict[str, object]:
    return {
        "call": prepared.call,
        "symbol": prepared.symbol,
        "trade_status": "valid" if prepared.call != "stand_aside" else "not_valid",
        "direction_bias": "buy" if prepared.call == "buy_candidate" else "sell" if prepared.call == "sell_candidate" else None,
        "regime": prepared.regime,
        "confidence": prepared.confidence,
        "why": prepared.market_thesis,
        "wait_for": prepared.next_trigger,
        "decision_summary": prepared.market_thesis,
        "entry_area": prepared.entry_area,
        "stop_area": prepared.stop_area,
        "target_area": prepared.target_area,
        "entry": prepared.entry,
        "stop_loss": prepared.stop_loss,
        "take_profit": prepared.take_profit,
        "reward_risk": prepared.reward_risk,
        "current_close": prepared.current_close,
        "guardian_state": prepared.state,
        "guardian_reason": prepared.invalidates_if if prepared.state in {"failing", "cancelled"} else prepared.market_thesis,
        "invalidates_if": prepared.invalidates_if,
        "call_age_seconds": prepared.call_age_seconds,
        "generated_at": prepared.generated_at,
    }
```

- [ ] **Step 4: Run the market snapshot tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_live_market_snapshot.py -q
```

Expected: PASS

- [ ] **Step 5: Commit the watcher-backed snapshot adapter**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py src/synthetic_trader/live/live_symbol_watcher.py
git commit -m "feat: expose prepared live symbol state"
```

## Task 4: Upgrade Bridge Contracts And Fast Reads

**Files:**
- Modify: `external/mitemshub-indices/src/lib/contracts.ts`
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
- Modify: `external/mitemshub-indices/tests/contracts.test.ts`
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
- Modify: `external/mitemshub-indices/tests/api-routes.test.ts`

- [ ] **Step 1: Write the failing TypeScript contract test**

```typescript
import { freshCallResponseSchema } from "../src/lib/contracts";

it("accepts actionable and failing live call states with freshness metadata", () => {
  const parsed = freshCallResponseSchema.parse({
    symbol: "R_75",
    call: "sell_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.62,
    regime: "range",
    direction_bias: "sell",
    why: "sellers still control the upper rejection zone",
    wait_for: "a fresh bearish continuation close",
    decision_summary: "sell setup actionable; sellers still control the upper rejection zone",
    entry_area: "around 53074.2",
    stop_area: "above 53173.2",
    target_area: "toward 52886.2",
    entry: 53074.2,
    stop_loss: 53173.2,
    take_profit: 52886.2,
    reward_risk: 1.9,
    current_close: 53074.2,
    guardian_state: "actionable",
    guardian_reason: "The setup is actionable with caution.",
    invalidates_if: "price closes back above the rejection shelf",
    call_age_seconds: 2,
    generated_at: "2026-07-11T22:00:00.000Z",
    account_mode: "own_account",
    prop_compliance: null,
    prop_adjusted_risk: null,
    prop_block_reason: null,
    prop_remaining_daily_buffer: null,
    prop_remaining_overall_buffer: null,
  });

  expect(parsed.guardian_state).toBe("actionable");
  expect(parsed.call_age_seconds).toBe(2);
});
```

- [ ] **Step 2: Run the focused contract and bridge tests to verify they fail**

Run:

```powershell
$env:Path='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:Path; & 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/contracts.test.ts tests/engine-bridge.test.ts tests/api-routes.test.ts
```

Expected: FAIL because the schemas do not yet accept `actionable`, `failing`, `cancelled`, `invalidates_if`, or `call_age_seconds`

- [ ] **Step 3: Add the richer contract shape and bridge normalization**

```typescript
export const guardianStateSchema = z.enum([
  "forming",
  "actionable",
  "confirmed",
  "failing",
  "cancelled",
  "unavailable",
]);

export const freshCallResponseSchema = z.object({
  // existing fields...
  guardian_state: guardianStateSchema,
  guardian_reason: z.string(),
  invalidates_if: z.string().nullable().optional(),
  call_age_seconds: z.number().int().nonnegative().nullable().optional(),
  generated_at: z.string(),
  // existing fields...
});
```

```typescript
function normalizeGuardianState(
  value: unknown,
): BaseFreshCall["guardian_state"] {
  return value === "forming" ||
    value === "actionable" ||
    value === "confirmed" ||
    value === "failing" ||
    value === "cancelled" ||
    value === "unavailable"
    ? value
    : "unavailable";
}
```

- [ ] **Step 4: Run the focused contract and bridge tests to verify they pass**

Run:

```powershell
$env:Path='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:Path; & 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/contracts.test.ts tests/engine-bridge.test.ts tests/api-routes.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit the watcher bridge and contract work**

```bash
git add external/mitemshub-indices/src/lib/contracts.ts external/mitemshub-indices/src/lib/engine-bridge.ts external/mitemshub-indices/tests/contracts.test.ts external/mitemshub-indices/tests/engine-bridge.test.ts external/mitemshub-indices/tests/api-routes.test.ts
git commit -m "feat: surface actionable live call payloads"
```

## Task 5: Render Actionable Calls In The Operator UI

**Files:**
- Modify: `external/mitemshub-indices/src/hooks/use-operator-workspace.ts`
- Modify: `external/mitemshub-indices/src/lib/formatters.ts`
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
- Modify: `external/mitemshub-indices/tests/formatters.test.ts`
- Modify: `external/mitemshub-indices/tests/operator-panels.test.tsx`
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`

- [ ] **Step 1: Write the failing UI tests**

```typescript
it("shows execution levels for actionable setups with a caution label", () => {
  render(
    <TradeInstructionPanel
      call={{
        symbol: "R_75",
        call: "sell_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.62,
        regime: "range",
        direction_bias: "sell",
        why: "sellers still control the upper rejection zone",
        wait_for: "a fresh bearish continuation close",
        decision_summary: "sell setup actionable; sellers still control the upper rejection zone",
        entry_area: "around 53074.2",
        stop_area: "above 53173.2",
        target_area: "toward 52886.2",
        entry: 53074.2,
        stop_loss: 53173.2,
        take_profit: 52886.2,
        reward_risk: 1.9,
        current_close: 53074.2,
        guardian_state: "actionable",
        guardian_reason: "The setup is actionable with caution.",
        invalidates_if: "price closes back above the rejection shelf",
        call_age_seconds: 2,
        generated_at: "2026-07-11T22:00:00.000Z",
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

  expect(screen.getByText(/Entry/i)).toBeInTheDocument();
  expect(screen.getByText(/Actionable with caution/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the UI-focused test suite to verify it fails**

Run:

```powershell
$env:Path='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:Path; & 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/formatters.test.ts tests/operator-panels.test.tsx tests/operator-shell.test.tsx
```

Expected: FAIL because actionable levels are still hidden and the old wording path still says “Do not enter yet”

- [ ] **Step 3: Implement the minimal UI behavior**

```typescript
export function formatGuardianState(
  state: FreshCallResponse["guardian_state"] | null | undefined,
): string {
  switch (state) {
    case "actionable":
      return "Actionable with caution";
    case "confirmed":
      return "Confirmed and ready";
    case "failing":
      return "Plan is losing strength";
    case "cancelled":
      return "Setup cancelled";
    default:
      return "Live read unavailable";
  }
}
```

```typescript
const showExecutionLevels =
  (effectiveGuardianState === "actionable" ||
    effectiveGuardianState === "confirmed") &&
  call?.entry !== null &&
  call?.stop_loss !== null &&
  call?.take_profit !== null;

const actionSummary = call
  ? effectiveGuardianState === "cancelled"
    ? "Do not execute this plan. The original setup is cancelled."
    : effectiveGuardianState === "failing"
      ? "Do not execute the old plan until you refresh the call. The setup is losing strength."
      : formatActionSummary(call)
  : null;
```

- [ ] **Step 4: Run the UI-focused test suite to verify it passes**

Run:

```powershell
$env:Path='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:Path; & 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/formatters.test.ts tests/operator-panels.test.tsx tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 5: Commit the UI rendering upgrade**

```bash
git add external/mitemshub-indices/src/hooks/use-operator-workspace.ts external/mitemshub-indices/src/lib/formatters.ts external/mitemshub-indices/src/components/operator/primary-call-panel.tsx external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx external/mitemshub-indices/tests/formatters.test.ts external/mitemshub-indices/tests/operator-panels.test.tsx external/mitemshub-indices/tests/operator-shell.test.tsx
git commit -m "feat: render actionable live trade plans"
```

## Task 6: Full Verification And Runtime Smoke Check

**Files:**
- Modify if needed after test failures discovered in verification

- [ ] **Step 1: Run the Python regression slice**

Run:

```powershell
py -3 -m pytest tests/test_live_symbol_watcher.py tests/test_signal_guardian.py tests/test_live_market_snapshot.py -q
```

Expected: PASS

- [ ] **Step 2: Run the app regression slice**

Run:

```powershell
$env:Path='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:Path; & 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' test -- tests/contracts.test.ts tests/engine-bridge.test.ts tests/api-routes.test.ts tests/formatters.test.ts tests/operator-panels.test.tsx tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 3: Restart the local app and smoke-test the live routes**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File '.\external\mitemshub-indices\stop-mitemshub-indices.ps1'
powershell -ExecutionPolicy Bypass -File '.\external\mitemshub-indices\launch-mitemshub-indices.ps1'
```

Expected: app rebuilds and starts on `http://localhost:3006`

- [ ] **Step 4: Verify both a valid call and a degraded call shape**

Run:

```powershell
$body = @{ symbol = 'R_75'; account_mode = 'own_account'; prop_account_state = $null } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://localhost:3006/api/calls/run' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 180 | ConvertTo-Json -Depth 10
```

Expected:

1. payload returns quickly from prepared watcher state
2. payload includes `guardian_state`, `call_age_seconds`, and `invalidates_if`
3. payload can legitimately return `actionable`, `confirmed`, `failing`, `cancelled`, `forming`, or `unavailable`

- [ ] **Step 5: Commit the final verification pass**

```bash
git add .
git commit -m "test: verify decisive live call engine rollout"
```
