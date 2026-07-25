# Runtime Alignment Manual Run Reuse Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent user-triggered manual runs from reusing weak prepared `forming`/`not_valid` entries while preserving existing prepared reuse behavior for non-manual paths.

**Architecture:** Add a small prepared-reuse policy to the app bridge so callers can explicitly allow or bypass prepared-cache reuse. Keep the policy default aligned with current behavior, then make the `/api/calls/run` route opt out only for user-triggered runs. Prove the change with failing bridge and route tests first, then run focused Vitest coverage.

**Tech Stack:** Next.js route handlers, TypeScript, Zod, Vitest

---

### Task 1: Bridge Policy Tests

**Files:**
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
- Test: `external/mitemshub-indices/tests/engine-bridge.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("does not reuse a weak prepared forming call when manual reuse is disabled", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
  const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-manual-weak-forming-"));
  const journalPath = join(tempDir, "call-history.jsonl");
  vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

  await writeFile(
    journalPath,
    `${JSON.stringify({
      symbol: "R_75",
      call: "stand_aside",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: 0.2,
      regime: "range",
      direction_bias: "sell",
      why: "setup still forming",
      wait_for: "wait for confirmation",
      decision_summary: "setup still forming",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: null,
      stop_loss: null,
      take_profit: null,
      reward_risk: null,
      current_close: 320.1,
      guardian_state: "forming",
      guardian_reason: "The setup is still forming and needs confirmation.",
      invalidates_if: null,
      call_age_seconds: 2,
      generated_at: new Date(Date.now() - 2_000).toISOString(),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    })}\n`,
    "utf8",
  );

  const liveSnapshotSpy = vi
    .spyOn(engineBridge.liveSnapshotAdapter, "read")
    .mockResolvedValue(buildLiveSnapshot("R_75"));

  const result = await engineBridge.runFreshCall({
    symbol: "R_75",
    accountMode: "own_account",
    propAccountState: null,
    reusePreparedCall: "never",
  });

  expect(liveSnapshotSpy).toHaveBeenCalledWith({
    engineRoot: "c:\\engine-root",
    symbol: "R_75",
  });
  expect(result.trade_status).toBe("valid");
  expect(result.guardian_state).toBe("actionable");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run tests/engine-bridge.test.ts`
Expected: FAIL because `runFreshCall()` does not yet accept `reusePreparedCall`

- [ ] **Step 3: Write minimal implementation**

```ts
type PreparedReusePolicy = "eligible_only" | "never";

export async function runFreshCall({
  symbol,
  accountMode,
  propAccountState,
  propConnection,
  reusePreparedCall = "eligible_only",
}: {
  symbol: SymbolCode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
  propConnection?: PropConnectionInput | null;
  reusePreparedCall?: PreparedReusePolicy;
}): Promise<FreshCallResponse> {
  const prepared =
    reusePreparedCall === "never" ? null : await readPreparedCall(symbol);
  // existing fallback path unchanged
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --run tests/engine-bridge.test.ts`
Expected: PASS for the new bridge policy test and existing bridge coverage

- [ ] **Step 5: Commit**

```bash
git add external/mitemshub-indices/tests/engine-bridge.test.ts external/mitemshub-indices/src/lib/engine-bridge.ts
git commit -m "fix: skip weak prepared reuse on manual runs"
```

### Task 2: Route Policy Tests

**Files:**
- Modify: `external/mitemshub-indices/tests/api-routes.test.ts`
- Modify: `external/mitemshub-indices/app/api/calls/run/route.ts`
- Test: `external/mitemshub-indices/tests/api-routes.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("POST /api/calls/run opts out of prepared reuse for user-triggered runs", async () => {
  const runFreshCallSpy = vi.spyOn(engineBridge, "runFreshCall").mockResolvedValue({
    symbol: "R_75",
    call: "sell_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.62,
    regime: "range",
    direction_bias: "sell",
    why: "fresh live snapshot",
    wait_for: "wait for a clean bearish continuation close",
    decision_summary: "sell setup ready",
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
    call_age_seconds: 0,
    generated_at: "2026-07-12T10:00:00.000Z",
    account_mode: "own_account",
    prop_compliance: null,
    prop_adjusted_risk: null,
    prop_block_reason: null,
    prop_remaining_daily_buffer: null,
    prop_remaining_overall_buffer: null,
  });

  const response = await postRun(
    new Request("http://localhost/api/calls/run", {
      method: "POST",
      body: JSON.stringify({
        symbol: "R_75",
        account_mode: "own_account",
      }),
    }),
  );

  expect(response.status).toBe(200);
  expect(runFreshCallSpy).toHaveBeenCalledWith(
    expect.objectContaining({
      symbol: "R_75",
      reusePreparedCall: "never",
    }),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run tests/api-routes.test.ts`
Expected: FAIL because the route does not yet pass the explicit prepared-reuse policy

- [ ] **Step 3: Write minimal implementation**

```ts
const payload = await runFreshCall({
  symbol: body.symbol,
  accountMode: body.account_mode,
  propAccountState: body.prop_account_state ?? null,
  propConnection: body.prop_connection ?? null,
  reusePreparedCall: "never",
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --run tests/api-routes.test.ts`
Expected: PASS for the new route policy test and existing route coverage

- [ ] **Step 5: Commit**

```bash
git add external/mitemshub-indices/tests/api-routes.test.ts external/mitemshub-indices/app/api/calls/run/route.ts
git commit -m "test: cover manual run prepared reuse policy"
```

### Task 3: Focused Verification

**Files:**
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
- Modify: `external/mitemshub-indices/app/api/calls/run/route.ts`
- Modify: `external/mitemshub-indices/tests/engine-bridge.test.ts`
- Modify: `external/mitemshub-indices/tests/api-routes.test.ts`

- [ ] **Step 1: Run focused verification**

```bash
npm test -- --run tests/engine-bridge.test.ts tests/api-routes.test.ts
```

- [ ] **Step 2: Check diagnostics on edited files**

```text
Inspect:
- external/mitemshub-indices/src/lib/engine-bridge.ts
- external/mitemshub-indices/app/api/calls/run/route.ts
- external/mitemshub-indices/tests/engine-bridge.test.ts
- external/mitemshub-indices/tests/api-routes.test.ts
```

- [ ] **Step 3: Record exact outputs for handoff**

```text
Capture:
- failing test output before implementation
- passing focused Vitest output after implementation
- exact files changed and the prepared-reuse policy name/value
```

- [ ] **Step 4: Commit**

```bash
git add external/mitemshub-indices/src/lib/engine-bridge.ts external/mitemshub-indices/app/api/calls/run/route.ts external/mitemshub-indices/tests/engine-bridge.test.ts external/mitemshub-indices/tests/api-routes.test.ts
git commit -m "fix: align manual run freshness policy"
```
