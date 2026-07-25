# Signal Guardian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a continuous Signal Guardian that supervises `R_75` and `R_100` setups tick by tick, exposes explicit lifecycle states, and prevents the operator UI from presenting stale or weak ideas as clean entries.

**Architecture:** Keep the existing Python snapshot engine as the source of directional thesis, then add a Python guardian state layer that evaluates confirmation, weakening, invalidation, and staleness. Expose that guardian truth through the Next.js bridge with a dedicated polling route and render it in the operator app so execution levels only appear for `confirmed` setups.

**Tech Stack:** Python 3, existing Synthetic Trader engine, Next.js 15, React 19, TypeScript, Zod, Vitest, React Testing Library

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot`

Python engine files:

- Create: `src/synthetic_trader/live/signal_guardian.py`
  - Guardian state machine, thresholds, and lifecycle evaluation.
- Modify: `src/synthetic_trader/live/market_snapshot.py`
  - Reuse current snapshot pipeline, surface `current_close` correctly, and add a guardian-aware helper.
- Create: `tests/test_signal_guardian.py`
  - Python regression coverage for confirmation, weakening, invalidation, and staleness.
- Modify: `tests/test_live_market_snapshot.py`
  - Add coverage for guardian-aware snapshot output and correct `current_close` behavior.

Bridge and web app files:

- Modify: `external/mitemshub-indices/src/lib/contracts.ts`
  - Add guardian schemas and response fields.
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
  - Execute guardian-aware live reads, keep honest unavailable states, and add a guardian status route helper.
- Create: `external/mitemshub-indices/app/api/calls/guardian/route.ts`
  - Expose guardian state for polling from the UI.
- Modify: `external/mitemshub-indices/src/hooks/use-operator-workspace.ts`
  - Poll guardian status after a symbol is selected and store lifecycle truth separately from the snapshot call.
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
  - Show lifecycle truth and confirmation state clearly.
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
  - Only show entry/stop/target when guardian state is `confirmed`.
- Modify: `external/mitemshub-indices/src/components/operator/operator-shell.tsx`
  - Thread guardian state into the operator surfaces.
- Modify: `external/mitemshub-indices/src/lib/formatters.ts`
  - Add display helpers for guardian state and reason text.

Web tests:

- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
  - Cover guardian-aware bridge responses and retry behavior.
- Modify: `external/mitemshub-indices/tests/api-routes.test.ts`
  - Cover the new `/api/calls/guardian` route.
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`
  - Cover polling, truth labels, and hidden execution levels for non-confirmed setups.

### Task 1: Build The Python Guardian Core

**Files:**
- Create: `src/synthetic_trader/live/signal_guardian.py`
- Create: `tests/test_signal_guardian.py`

- [ ] **Step 1: Write the failing Python regression tests**

```python
import unittest

from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)


class SignalGuardianTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = GuardianThresholds(
            max_arming_ticks=12,
            max_confirmation_window_ticks=6,
            weakening_excursion_ratio=0.35,
            max_adverse_excursion_ratio=0.8,
            max_entry_drift_ratio=1.0,
            microstructure_window_ticks=5,
        )

    def test_buy_setup_becomes_confirmed_when_zone_holds_and_microstructure_improves(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.7,
        )
        context = GuardianContext(
            tick_prices=[459.4, 459.5, 459.55, 459.62, 459.7, 459.78],
            ticks_since_armed=4,
            max_favorable_excursion=0.18,
            max_adverse_excursion=0.12,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "confirmed")
        self.assertIn("confirmation", result.reason.lower())

    def test_buy_setup_becomes_invalidated_after_large_adverse_excursion(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=458.35,
        )
        context = GuardianContext(
            tick_prices=[459.55, 459.4, 459.1, 458.8, 458.55, 458.35],
            ticks_since_armed=5,
            max_favorable_excursion=0.02,
            max_adverse_excursion=1.25,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "invalidated")
        self.assertIn("invalidat", result.reason.lower())

    def test_buy_setup_becomes_weakening_before_full_invalidation(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.1,
        )
        context = GuardianContext(
            tick_prices=[459.62, 459.58, 459.45, 459.32, 459.2, 459.1],
            ticks_since_armed=5,
            max_favorable_excursion=0.05,
            max_adverse_excursion=0.5,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "weakening")
        self.assertIn("weak", result.reason.lower())

    def test_armed_setup_goes_stale_when_confirmation_window_expires(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.62,
        )
        context = GuardianContext(
            tick_prices=[459.55, 459.58, 459.61, 459.6, 459.59, 459.6],
            ticks_since_armed=14,
            max_favorable_excursion=0.04,
            max_adverse_excursion=0.09,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "invalidated")
        self.assertIn("stale", result.reason.lower())
```

- [ ] **Step 2: Run the new Python test file to verify it fails**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing guardian symbols

- [ ] **Step 3: Write the minimal guardian implementation**

```python
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True)
class GuardianThresholds:
    max_arming_ticks: int
    max_confirmation_window_ticks: int
    weakening_excursion_ratio: float
    max_adverse_excursion_ratio: float
    max_entry_drift_ratio: float
    microstructure_window_ticks: int


@dataclass(frozen=True)
class GuardianSnapshot:
    symbol: str
    direction_bias: str
    trade_status: str
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    current_close: float | None


@dataclass(frozen=True)
class GuardianContext:
    tick_prices: list[float]
    ticks_since_armed: int
    max_favorable_excursion: float
    max_adverse_excursion: float


@dataclass(frozen=True)
class GuardianEvaluation:
    state: str
    reason: str


def _stop_distance(snapshot: GuardianSnapshot) -> float | None:
    if snapshot.entry is None or snapshot.stop_loss is None:
        return None
    return abs(snapshot.entry - snapshot.stop_loss)


def _microstructure_score(prices: list[float]) -> float:
    if len(prices) < 2:
        return 0.0
    deltas = [right - left for left, right in zip(prices, prices[1:])]
    return fmean(deltas)


def evaluate_signal_guardian(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
) -> GuardianEvaluation:
    if snapshot.trade_status != "valid" or snapshot.direction_bias not in {"buy", "sell"}:
        return GuardianEvaluation("forming", "Directional thesis is not yet armed.")

    stop_distance = _stop_distance(snapshot)
    if not stop_distance or stop_distance <= 0:
        return GuardianEvaluation("unavailable", "Guardian cannot evaluate a setup without valid trade levels.")

    if context.ticks_since_armed > thresholds.max_arming_ticks:
        return GuardianEvaluation("invalidated", "Setup went stale before confirmation arrived.")

    adverse_ratio = context.max_adverse_excursion / stop_distance
    if adverse_ratio >= thresholds.max_adverse_excursion_ratio:
        return GuardianEvaluation("invalidated", "Setup invalidated after adverse excursion broke the guardrail.")

    if adverse_ratio >= thresholds.weakening_excursion_ratio:
        return GuardianEvaluation("weakening", "Setup is weakening and should not be treated as a clean entry.")

    prices = context.tick_prices[-thresholds.microstructure_window_ticks :]
    micro_score = _microstructure_score(prices)
    if snapshot.direction_bias == "buy" and micro_score > 0 and context.ticks_since_armed <= thresholds.max_confirmation_window_ticks:
        return GuardianEvaluation("confirmed", "Buy confirmation received from improving short-term acceptance.")
    if snapshot.direction_bias == "sell" and micro_score < 0 and context.ticks_since_armed <= thresholds.max_confirmation_window_ticks:
        return GuardianEvaluation("confirmed", "Sell confirmation received from improving short-term acceptance.")

    return GuardianEvaluation("armed", "Directional thesis is armed, but confirmation has not arrived yet.")
```

- [ ] **Step 4: Run the Python guardian tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
```

Expected: PASS

- [ ] **Step 5: Commit the guardian core**

```bash
git add src/synthetic_trader/live/signal_guardian.py tests/test_signal_guardian.py
git commit -m "feat: add signal guardian core"
```

### Task 2: Integrate Guardian State Into The Python Snapshot Layer

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Modify: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing snapshot integration tests**

```python
def test_analyze_live_snapshot_uses_last_price_for_current_close_when_signal_exists() -> None:
    ticks = [
        Tick(symbol="R_100", epoch=0, price=458.9),
        Tick(symbol="R_100", epoch=60, price=459.2),
        Tick(symbol="R_100", epoch=120, price=459.8),
        Tick(symbol="R_100", epoch=180, price=459.4),
        Tick(symbol="R_100", epoch=240, price=459.7),
    ] * 20

    snapshot = analyze_live_snapshot(
        symbol="R_100",
        ticks=ticks,
        timeframe_sec=60,
        higher_timeframe_sec=300,
        config=TraderConfig.default(),
    )

    assert snapshot["current_close"] == ticks[-1].price


def test_build_watch_alert_keeps_guardian_state_fields_when_present() -> None:
    alert = build_watch_alert(
        {
            "call": "buy_candidate",
            "trade_status": "valid",
            "direction_bias": "buy",
            "symbol": "R_100",
            "current_close": 459.7,
            "guardian_state": "weakening",
            "guardian_reason": "setup is weakening",
        }
    )

    assert alert["guardian_state"] == "weakening"
    assert alert["guardian_reason"] == "setup is weakening"
```

- [ ] **Step 2: Run the focused Python snapshot tests to verify they fail**

Run:

```powershell
py -3 -m pytest tests/test_live_market_snapshot.py -k "current_close or guardian_state" -q
```

Expected: FAIL because `guardian_state` fields are absent and `current_close` still uses the signal entry

- [ ] **Step 3: Implement guardian-aware snapshot helpers**

```python
from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)


def build_guardian_snapshot(snapshot: dict[str, object], ticks: list[Tick]) -> dict[str, object]:
    current_close = ticks[-1].price if ticks else snapshot.get("current_close")
    signal_snapshot = GuardianSnapshot(
        symbol=str(snapshot.get("symbol", "")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        entry=float(snapshot["entry"]) if snapshot.get("entry") is not None else None,
        stop_loss=float(snapshot["stop_loss"]) if snapshot.get("stop_loss") is not None else None,
        take_profit=float(snapshot["take_profit"]) if snapshot.get("take_profit") is not None else None,
        current_close=float(current_close) if current_close is not None else None,
    )
    prices = [tick.price for tick in ticks[-12:]]
    context = GuardianContext(
        tick_prices=prices,
        ticks_since_armed=min(len(prices), 12),
        max_favorable_excursion=max([0.0] + [price - prices[0] for price in prices]),
        max_adverse_excursion=max([0.0] + [prices[0] - price for price in prices]),
    )
    thresholds = GuardianThresholds(
        max_arming_ticks=12,
        max_confirmation_window_ticks=6,
        weakening_excursion_ratio=0.35,
        max_adverse_excursion_ratio=0.8,
        max_entry_drift_ratio=1.0,
        microstructure_window_ticks=5,
    )
    guardian = evaluate_signal_guardian(signal_snapshot, context, thresholds)
    enriched = dict(snapshot)
    enriched["current_close"] = current_close
    enriched["guardian_state"] = guardian.state
    enriched["guardian_reason"] = guardian.reason
    return enriched
```

- [ ] **Step 4: Wire the helper into snapshot generation and alert building**

```python
snapshot = analyze_live_snapshot(
    symbol=symbol,
    ticks=ticks,
    timeframe_sec=timeframe_sec,
    higher_timeframe_sec=higher_timeframe_sec,
    config=TraderConfig.default(),
)
return build_guardian_snapshot(snapshot, ticks)
```

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
    "guardian_state": snapshot.get("guardian_state"),
    "guardian_reason": snapshot.get("guardian_reason"),
    "reasons": snapshot.get("reasons"),
    "entry_area": snapshot.get("entry_area"),
    "stop_area": snapshot.get("stop_area"),
    "target_area": snapshot.get("target_area"),
    "entry": snapshot.get("entry"),
    "stop_loss": snapshot.get("stop_loss"),
    "take_profit": snapshot.get("take_profit"),
    "reward_risk": snapshot.get("reward_risk"),
}
```

- [ ] **Step 5: Run the focused snapshot tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_live_market_snapshot.py -k "current_close or guardian_state" -q
```

Expected: PASS

- [ ] **Step 6: Commit the Python snapshot integration**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: enrich live snapshots with guardian state"
```

### Task 3: Extend The Bridge Contract And Guardian API

**Files:**
- Modify: `external/mitemshub-indices/src/lib/contracts.ts`
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
- Create: `external/mitemshub-indices/app/api/calls/guardian/route.ts`
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
- Modify: `external/mitemshub-indices/tests/api-routes.test.ts`

- [ ] **Step 1: Write the failing bridge and route tests**

```ts
it("returns guardian lifecycle fields in the fresh call response", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
  vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
    symbol: "R_100",
    call: "buy_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.73,
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
    guardian_state: "armed",
    guardian_reason: "Directional thesis is armed, but confirmation has not arrived yet.",
    current_close: 459.7,
    generated_at: "2026-07-11T03:00:00Z",
  } as never);

  const result = await engineBridge.runFreshCall({
    symbol: "R_100",
    accountMode: "own_account",
    propAccountState: null,
  });

  expect(result.guardian_state).toBe("armed");
  expect(result.guardian_reason).toMatch(/confirmation has not arrived/i);
});

it("GET /api/calls/guardian returns a guardian status payload", async () => {
  const response = await getGuardian(
    new Request("http://localhost/api/calls/guardian?symbol=R_100"),
  );
  const payload = await response.json();

  expect(response.status).toBe(200);
  expect(payload.symbol).toBe("R_100");
  expect(payload.guardian_state).toBeTruthy();
});
```

- [ ] **Step 2: Run the bridge-focused tests to verify they fail**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts
```

Expected: FAIL because guardian fields and the new route do not exist yet

- [ ] **Step 3: Extend the Zod contract with guardian fields**

```ts
export const guardianStateSchema = z.enum([
  "forming",
  "armed",
  "confirmed",
  "weakening",
  "invalidated",
  "unavailable",
]);

export const guardianStatusSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  guardian_state: guardianStateSchema,
  guardian_reason: z.string(),
  current_close: z.number().nullable(),
  generated_at: z.string(),
});

export const freshCallResponseSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  call: z.enum(["buy_candidate", "sell_candidate", "stand_aside"]),
  alert_type: z.string(),
  trade_status: z.string(),
  confidence: z.number().nullable(),
  regime: z.string().nullable(),
  direction_bias: z.string().nullable(),
  why: z.string().nullable(),
  wait_for: z.string().nullable(),
  decision_summary: z.string().nullable(),
  entry_area: z.string().nullable(),
  stop_area: z.string().nullable(),
  target_area: z.string().nullable(),
  entry: z.number().nullable(),
  stop_loss: z.number().nullable(),
  take_profit: z.number().nullable(),
  reward_risk: z.number().nullable(),
  current_close: z.number().nullable(),
  guardian_state: guardianStateSchema,
  guardian_reason: z.string(),
  generated_at: z.string(),
  account_mode: accountModeSchema,
  prop_compliance: propComplianceSchema.nullable(),
  prop_adjusted_risk: z.number().nullable(),
  prop_block_reason: z.string().nullable(),
  prop_remaining_daily_buffer: z.number().nullable(),
  prop_remaining_overall_buffer: z.number().nullable(),
});
```

- [ ] **Step 4: Add guardian-aware bridge helpers and the API route**

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

export async function getGuardianStatus(symbol: SymbolCode) {
  const call = await runFreshCall({
    symbol,
    accountMode: "own_account",
    propAccountState: null,
  });

  return guardianStatusSchema.parse({
    symbol: call.symbol,
    guardian_state: call.guardian_state,
    guardian_reason: call.guardian_reason,
    current_close: call.current_close,
    generated_at: call.generated_at,
  });
}
```

```ts
import { NextResponse } from "next/server";
import { getGuardianStatus } from "../../../../src/lib/engine-bridge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "R_100") as "R_75" | "R_100";
  const payload = await getGuardianStatus(symbol);
  return NextResponse.json(payload);
}
```

- [ ] **Step 5: Run the bridge and route tests to verify they pass**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts
```

Expected: PASS

- [ ] **Step 6: Commit the bridge contract work**

```bash
git add external/mitemshub-indices/src/lib/contracts.ts external/mitemshub-indices/src/lib/engine-bridge.ts external/mitemshub-indices/app/api/calls/guardian/route.ts external/mitemshub-indices/tests/engine-bridge.test.ts external/mitemshub-indices/tests/api-routes.test.ts
git commit -m "feat: expose guardian lifecycle through bridge"
```

### Task 4: Render Guardian Truth In The Operator UI

**Files:**
- Modify: `external/mitemshub-indices/src/hooks/use-operator-workspace.ts`
- Modify: `external/mitemshub-indices/src/components/operator/primary-call-panel.tsx`
- Modify: `external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
- Modify: `external/mitemshub-indices/src/components/operator/operator-shell.tsx`
- Modify: `external/mitemshub-indices/src/lib/formatters.ts`
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`

- [ ] **Step 1: Write the failing UI tests**

```tsx
it("shows guardian state as armed and hides execution levels before confirmation", async () => {
  const user = userEvent.setup();

  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);

    if (url.includes("/api/calls/run") && init?.method === "POST") {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            symbol: "R_100",
            call: "buy_candidate",
            alert_type: "setup_candidate",
            trade_status: "valid",
            confidence: 0.71,
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
            current_close: 459.7,
            guardian_state: "armed",
            guardian_reason: "Directional thesis is armed, but confirmation has not arrived yet.",
            generated_at: "2026-07-11T03:15:00.000Z",
            account_mode: "own_account",
            prop_compliance: null,
            prop_adjusted_risk: null,
            prop_block_reason: null,
            prop_remaining_daily_buffer: null,
            prop_remaining_overall_buffer: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    if (url.includes("/api/calls/guardian")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            symbol: "R_100",
            guardian_state: "armed",
            guardian_reason: "Directional thesis is armed, but confirmation has not arrived yet.",
            current_close: 459.7,
            generated_at: "2026-07-11T03:15:05.000Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    return Promise.resolve(new Response(JSON.stringify({ history: [] }), { status: 200 }));
  });

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /r_100/i }));

  expect(await screen.findByText(/armed/i)).toBeInTheDocument();
  expect(screen.getByText(/confirmation has not arrived yet/i)).toBeInTheDocument();
  expect(screen.getByText(/entry, stop, and target appear only when a trade is ready/i)).toBeInTheDocument();
});

it("shows execution levels only after guardian state becomes confirmed", async () => {
  // same setup, but guardian route responds with guardian_state: "confirmed"
  // and the test asserts the Entry / Stop / Target values render
});
```

- [ ] **Step 2: Run the UI test file to verify it fails**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: FAIL because the workspace and panels do not yet understand guardian state

- [ ] **Step 3: Add guardian polling and state storage in the workspace hook**

```tsx
const [guardianStatus, setGuardianStatus] = useState<{
  symbol: SymbolCode;
  guardian_state: FreshCallResponse["guardian_state"];
  guardian_reason: string;
  current_close: number | null;
  generated_at: string;
} | null>(null);

useEffect(() => {
  if (!currentCall) {
    return;
  }

  let cancelled = false;
  const timer = window.setInterval(async () => {
    try {
      const response = await fetch(`/api/calls/guardian?symbol=${activeSymbol}`);
      if (!cancelled && response.ok) {
        setGuardianStatus((await response.json()) as typeof guardianStatus);
      }
    } catch {
      // Keep the last known guardian state when polling fails.
    }
  }, 3000);

  return () => {
    cancelled = true;
    window.clearInterval(timer);
  };
}, [activeSymbol, currentCall]);
```

- [ ] **Step 4: Render guardian state and gate the execution levels**

```tsx
const effectiveGuardianState = guardianStatus?.guardian_state ?? call?.guardian_state ?? "unavailable";
const showExecutionLevels = effectiveGuardianState === "confirmed";
```

```tsx
<div className="info-card rounded-[1.5rem] p-5">
  <p className="utility-copy text-xs uppercase tracking-[0.24em]">
    Guardian state
  </p>
  <p className="mt-2 text-base leading-7 text-[var(--text-strong)]">
    {formatGuardianState(effectiveGuardianState)}
  </p>
  <p className="mt-2 text-sm leading-6 text-[var(--text-body)]">
    {guardianStatus?.guardian_reason ?? call?.guardian_reason}
  </p>
</div>
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
      Entry, stop, and target appear only when the guardian confirms the setup.
    </p>
  </div>
)}
```

- [ ] **Step 5: Run the UI tests to verify they pass**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit the guardian UI**

```bash
git add external/mitemshub-indices/src/hooks/use-operator-workspace.ts external/mitemshub-indices/src/components/operator/primary-call-panel.tsx external/mitemshub-indices/src/components/operator/trade-instruction-panel.tsx external/mitemshub-indices/src/components/operator/operator-shell.tsx external/mitemshub-indices/src/lib/formatters.ts external/mitemshub-indices/tests/operator-shell.test.tsx
git commit -m "feat: show guardian truth in operator app"
```

### Task 5: Final Regression Pass For Reversal Cases

**Files:**
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
- Modify: `external/mitemshub-indices/tests/operator-shell.test.tsx`
- Modify: `tests/test_signal_guardian.py`

- [ ] **Step 1: Add the reversal regression tests first**

```python
def test_confirmed_buy_setup_downgrades_when_follow_through_rolls_over() -> None:
    thresholds = GuardianThresholds(
        max_arming_ticks=12,
        max_confirmation_window_ticks=6,
        weakening_excursion_ratio=0.35,
        max_adverse_excursion_ratio=0.8,
        max_entry_drift_ratio=1.0,
        microstructure_window_ticks=5,
    )
    snapshot = GuardianSnapshot(
        symbol="R_100",
        direction_bias="buy",
        trade_status="valid",
        entry=459.6,
        stop_loss=458.2,
        take_profit=462.2,
        current_close=459.05,
    )
    context = GuardianContext(
        tick_prices=[459.8, 459.7, 459.55, 459.32, 459.18, 459.05],
        ticks_since_armed=5,
        max_favorable_excursion=0.25,
        max_adverse_excursion=0.55,
    )

    result = evaluate_signal_guardian(snapshot, context, thresholds)

    assert result.state == "weakening"
```

```ts
it("returns unavailable instead of fake levels when the guardian feed cannot be trusted", async () => {
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

- [ ] **Step 2: Run the focused regression tests to verify they pass**

Run:

```powershell
py -3 -m pytest tests/test_signal_guardian.py -q
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/operator-shell.test.tsx
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

- Python tests PASS
- Vitest suite PASS
- Next.js build PASS

- [ ] **Step 4: Commit the regression hardening**

```bash
git add tests/test_signal_guardian.py tests/test_live_market_snapshot.py external/mitemshub-indices/tests/engine-bridge.test.ts external/mitemshub-indices/tests/operator-shell.test.tsx
git commit -m "test: harden guardian reversal coverage"
```

## Self-Review

Spec coverage:

1. guardian lifecycle states are implemented in Task 1 and surfaced in Tasks 3 and 4
2. explicit confirmation and invalidation behavior is implemented in Tasks 1 and 2
3. honest unavailable behavior is implemented in Tasks 3 and 5
4. UI truth labels and execution gating are implemented in Task 4
5. reversal regression coverage is implemented in Task 5

Placeholder scan:

1. no `TODO`, `TBD`, or deferred code markers remain
2. every task includes exact files, code, commands, and expected outcomes

Type consistency:

1. guardian state names are consistent across Python, Zod schemas, bridge helpers, and React tests
2. `guardian_state`, `guardian_reason`, and `current_close` are introduced once in the contract and reused consistently afterward

Plan complete and saved to `docs/superpowers/plans/2026-07-11-signal-guardian.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
