# Prop Telemetry Status Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend-truth prop telemetry status to the prop profile response and render a compact operator-facing label above the prop compliance panel.

**Architecture:** Extend the prop profile contract so the backend returns both account numbers and a telemetry status object. Keep the UI small by storing that response in the workspace hook and rendering one compact status line above the existing prop panel instead of adding a new warning surface.

**Tech Stack:** Next.js 15, React 19, TypeScript, Zod, Vitest, React Testing Library, existing `mitemshub-indices` operator app

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices`

Primary files:

- `src/lib/contracts.ts`
  - Add telemetry status schema and prop profile response schema/type.
- `src/lib/mock-data.ts`
  - Add a mock prop profile response with truthful default telemetry status.
- `src/lib/engine-bridge.ts`
  - Return backend-truth telemetry state for live success, own-account fallback success, and unavailable verification.
- `app/api/prop-profiles/current/route.ts`
  - Keep using the backend-truth response shape for `GET` and `POST`.
- `src/hooks/use-operator-workspace.ts`
  - Store the prop profile response object instead of only raw account-state fields.
- `src/components/operator/operator-shell.tsx`
  - Render the telemetry label above the prop compliance panel.
- `src/components/operator/prop-compliance-panel.tsx`
  - Continue to receive only the raw account-state slice it needs.
- `tests/api-routes.test.ts`
  - Lock route telemetry state behavior.
- `tests/engine-bridge.test.ts`
  - Lock backend telemetry-state behavior.
- `tests/operator-shell.test.tsx`
  - Lock label rendering in prop mode.

### Task 1: Add Telemetry Status To The Backend Contract

**Files:**
- Modify: `src/lib/contracts.ts`
- Modify: `src/lib/mock-data.ts`
- Modify: `src/lib/engine-bridge.ts`
- Test: `tests/engine-bridge.test.ts`

- [ ] **Step 1: Write the failing backend tests**

```ts
it("labels dedicated prop reads as live confirmed", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

  vi.spyOn(engineBridge.livePropProfileAdapter, "read").mockResolvedValue({
    profile: "blueberry_2step_funded",
    startingBalance: 120000,
    currentBalance: 119800,
    currentEquity: 119700,
    todaysRealizedLoss: 100,
    todaysFloatingLossExposure: 50,
    highImpactNewsLockout: false,
  });

  const profile = await engineBridge.getCurrentPropProfileForRequest({
    connection: {
      server: "PropServer",
      login: "222222",
      password: "prop-secret",
      terminalPath: null,
    },
    startingBalance: 120000,
  });

  expect(profile.telemetry.status).toBe("live_confirmed");
  expect(profile.telemetry.message).toBe("Live prop check confirmed");
});

it("labels blank prop credentials as own-account fallback when live fallback succeeds", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
  vi.stubEnv("SYNTHETIC_MT5_SERVER", "EnvServer");
  vi.stubEnv("SYNTHETIC_MT5_LOGIN", "111111");
  vi.stubEnv("SYNTHETIC_MT5_PASSWORD", "env-secret");

  vi.spyOn(engineBridge.livePropProfileAdapter, "read").mockResolvedValue({
    profile: "blueberry_2step_funded",
    startingBalance: 100000,
    currentBalance: 100050,
    currentEquity: 100010,
    todaysRealizedLoss: 0,
    todaysFloatingLossExposure: 40,
    highImpactNewsLockout: false,
  });

  const profile = await engineBridge.getCurrentPropProfileForRequest({
    connection: {
      server: null,
      login: null,
      password: null,
      terminalPath: null,
    },
    startingBalance: 100000,
  });

  expect(profile.telemetry.status).toBe("own_account_fallback");
  expect(profile.telemetry.message).toBe("Using own-account fallback");
});

it("labels unavailable live verification honestly", async () => {
  vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

  const profile = await engineBridge.getCurrentPropProfileForRequest({
    connection: null,
    startingBalance: null,
  });

  expect(profile.telemetry.status).toBe("live_unavailable");
  expect(profile.telemetry.message).toBe("Live prop check unavailable");
});
```

- [ ] **Step 2: Run the backend test to verify it fails**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts
```

Expected: FAIL because the current prop profile response does not include `telemetry`.

- [ ] **Step 3: Add the new telemetry schemas and response type**

```ts
export const propTelemetryStatusSchema = z.enum([
  "live_confirmed",
  "own_account_fallback",
  "live_unavailable",
]);

export const propTelemetryStateSchema = z.object({
  status: propTelemetryStatusSchema,
  message: z.string(),
});

export const propProfileResponseSchema = propAccountStateSchema.extend({
  telemetry: propTelemetryStateSchema,
});

export type PropProfileResponse = z.infer<typeof propProfileResponseSchema>;
```

- [ ] **Step 4: Return telemetry truth from mock data and the bridge**

```ts
export const mockCurrentPropProfile: PropProfileResponse = {
  profile: "blueberry_2step_funded",
  startingBalance: 100200,
  currentBalance: 100200,
  currentEquity: 100100,
  todaysRealizedLoss: 0,
  todaysFloatingLossExposure: 0,
  highImpactNewsLockout: false,
  telemetry: {
    status: "live_unavailable",
    message: "Live prop check unavailable",
  },
};
```

```ts
function withTelemetry(
  profile: PropAccountState,
  telemetry: PropProfileResponse["telemetry"],
): PropProfileResponse {
  return {
    ...profile,
    telemetry,
  };
}

export async function getCurrentPropProfileForRequest(
  request: PropProfileRequest | null | undefined,
) {
  const engineRoot = getConfiguredEngineRoot();
  const liveConfig = resolveRequestedPropConfig(request);
  const usedFallback = !request?.connection?.server && !request?.connection?.login && !request?.connection?.password;

  if (!engineRoot || !liveConfig) {
    return mockCurrentPropProfile;
  }

  try {
    const profile = await livePropProfileAdapter.read({
      engineRoot,
      config: liveConfig,
    });

    return withTelemetry(
      profile,
      usedFallback
        ? { status: "own_account_fallback", message: "Using own-account fallback" }
        : { status: "live_confirmed", message: "Live prop check confirmed" },
    );
  } catch {
    return mockCurrentPropProfile;
  }
}
```

- [ ] **Step 5: Run the backend tests again**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts
```

Expected: PASS

### Task 2: Surface Backend-Truth Status In Routes And UI

**Files:**
- Modify: `tests/api-routes.test.ts`
- Modify: `tests/operator-shell.test.tsx`
- Modify: `src/hooks/use-operator-workspace.ts`
- Modify: `src/components/operator/operator-shell.tsx`
- Modify: `src/components/operator/prop-compliance-panel.tsx`

- [ ] **Step 1: Write the failing route and UI tests**

```ts
it("POST /api/prop-profiles/current returns telemetry status", async () => {
  vi.spyOn(engineBridge, "getCurrentPropProfileForRequest").mockResolvedValue({
    profile: "blueberry_2step_funded",
    startingBalance: 100000,
    currentBalance: 100000,
    currentEquity: 100100,
    todaysRealizedLoss: 0,
    todaysFloatingLossExposure: 0,
    highImpactNewsLockout: false,
    telemetry: {
      status: "own_account_fallback",
      message: "Using own-account fallback",
    },
  });

  const response = await postCurrentPropProfile(new Request("http://localhost/api/prop-profiles/current", {
    method: "POST",
    body: JSON.stringify({ connection: null, startingBalance: 100000 }),
  }));
  const payload = await response.json();

  expect(payload.telemetry.status).toBe("own_account_fallback");
});
```

```tsx
it("renders the backend-truth telemetry label above the prop panel", async () => {
  const user = userEvent.setup();

  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);

    if (url.includes("/api/history")) {
      return Promise.resolve(new Response(JSON.stringify({ history: [] }), { status: 200 }));
    }

    if (url.includes("/api/system/status")) {
      return Promise.resolve(new Response(JSON.stringify({
        latest_call: "R_100 stand_aside",
        alert_count: 0,
        suppressed_context_count: 0,
        transport_event_count: 0,
        latest_transport_event: "steady",
        latest_transport_reason: "test route",
        backend_status: "live_bridge_ready",
        journal_status: "fresh",
      }), { status: 200 }));
    }

    if (url.includes("/api/prop-profiles/current") && init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify({
        profile: "blueberry_2step_funded",
        startingBalance: 100000,
        currentBalance: 100200,
        currentEquity: 100150,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
        telemetry: {
          status: "own_account_fallback",
          message: "Using own-account fallback",
        },
      }), { status: 200 }));
    }

    if (url.includes("/api/prop-profiles/current")) {
      return Promise.resolve(new Response(JSON.stringify({
        profile: "blueberry_2step_funded",
        startingBalance: 100200,
        currentBalance: 100200,
        currentEquity: 100100,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
        telemetry: {
          status: "live_unavailable",
          message: "Live prop check unavailable",
        },
      }), { status: 200 }));
    }

    return Promise.resolve(new Response(JSON.stringify({ symbol: "R_100" }), { status: 200 }));
  });

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /prop firm/i }));
  await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

  expect(screen.getByText(/using own-account fallback/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the route and UI tests to verify they fail**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/api-routes.test.ts tests/operator-shell.test.tsx
```

Expected: FAIL because the current response and hook state do not include telemetry.

- [ ] **Step 3: Store the full prop profile response in the hook and render the backend label**

```ts
const [propProfile, setPropProfile] = useState<PropProfileResponse>(mockCurrentPropProfile);
```

```tsx
{workspace.accountMode === "prop_firm" ? (
  <div className="space-y-3">
    <p className="utility-copy text-xs uppercase tracking-[0.2em]">
      {workspace.propProfile.telemetry.message}
    </p>
    <PropCompliancePanel
      call={workspace.propCallPreview}
      profile={workspace.propProfile}
    />
  </div>
) : (
  <ReviewSystemPanel status={workspace.systemStatus} />
)}
```

- [ ] **Step 4: Keep the prop panel focused on account numbers only**

```ts
type PropCompliancePanelProps = {
  call: FreshCallResponse | null;
  profile: PropAccountState;
};
```

No status-guessing logic should be added inside the panel itself.

- [ ] **Step 5: Run the route and UI tests again**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/api-routes.test.ts tests/operator-shell.test.tsx
```

Expected: PASS

### Task 3: Final Verification, Preview, And GitHub Push

**Files:**
- Modify: `tests/engine-bridge.test.ts`
- Modify: `tests/api-routes.test.ts`
- Modify: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Run the focused suite**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 2: Run the full suite and build**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run build
```

Expected: PASS

- [ ] **Step 3: Launch preview**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run start -- --port 3006
```

Expected: local preview serves successfully.

- [ ] **Step 4: Commit only the app repo changes**

```bash
git add src/lib/contracts.ts src/lib/mock-data.ts src/lib/engine-bridge.ts app/api/prop-profiles/current/route.ts src/hooks/use-operator-workspace.ts src/components/operator/operator-shell.tsx src/components/operator/prop-compliance-panel.tsx tests/engine-bridge.test.ts tests/api-routes.test.ts tests/operator-shell.test.tsx
git commit -m "feat: label prop telemetry status"
```

- [ ] **Step 5: Push to GitHub**

```bash
git push origin main
```

Expected: push succeeds to `https://github.com/MitemsHub/mitemshub-indices.git`
