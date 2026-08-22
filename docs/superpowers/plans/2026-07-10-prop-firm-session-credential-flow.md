# Prop Firm Session Credential Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `Prop Firm` mode prompt for session-only MT5 credentials, fall back to the own-account MT5 connection when the prop fields are blank, and keep the `R_75` / `R_100` operator workflow unchanged.

**Architecture:** Add a small client-side prop-connection prompt and keep the chosen connection only in React session state. Extend the request contracts, prop-profile route, and bridge resolution logic so live prop telemetry can use either dedicated prop credentials or the existing own-account MT5 env credentials, while keeping call generation and compliance logic honest.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS, Zod, Vitest, React Testing Library, existing `mitemshub-indices` operator app

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices`

Primary implementation targets:

- `src/lib/contracts.ts`
  - Add request schemas and shared types for session prop connection input and prop-profile POST payloads.
- `src/lib/engine-bridge.ts`
  - Resolve dedicated prop credentials vs own-account fallback and expose request-driven prop profile reads.
- `app/api/prop-profiles/current/route.ts`
  - Add `POST` handling for dynamic prop profile requests.
- `app/api/calls/run/route.ts`
  - Accept optional prop connection payload and pass it into the bridge.
- `src/hooks/use-operator-workspace.ts`
  - Hold session-only prop connection state, prompt state, prop-profile refresh flow, and prop-mode call payload composition.
- `src/components/operator/operator-shell.tsx`
  - Host the prompt component and wire the new mode-selection flow.
- `src/components/operator/command-bar.tsx`
  - Replace direct prop-mode switching with a prop-mode request action.
- `src/components/operator/prop-connection-modal.tsx`
  - New focused modal component for session-only prop credentials and fallback submission.
- `tests/engine-bridge.test.ts`
  - Lock bridge fallback and request-override behavior.
- `tests/api-routes.test.ts`
  - Lock the new prop-profile POST route and extended run route contract.
- `tests/operator-shell.test.tsx`
  - Lock the prompt flow, validation, fallback mode, and unchanged symbol workflow.

Secondary support:

- `src/components/operator/prop-compliance-panel.tsx`
  - Optionally show plain-language account-source messaging when prop mode is using own-account fallback.

### Task 1: Define The Request Contract And Bridge Resolution

**Files:**
- Modify: `src/lib/contracts.ts`
- Modify: `src/lib/engine-bridge.ts`
- Test: `tests/engine-bridge.test.ts`

- [ ] **Step 1: Add the failing bridge tests for override, fallback, and default starting balance**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import * as engineBridge from "../src/lib/engine-bridge";

describe("getCurrentPropProfileForRequest", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("uses request-supplied prop credentials before env fallback", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    vi.stubEnv("SYNTHETIC_MT5_SERVER", "EnvServer");
    vi.stubEnv("SYNTHETIC_MT5_LOGIN", "111111");
    vi.stubEnv("SYNTHETIC_MT5_PASSWORD", "env-secret");

    const propProfileSpy = vi
      .spyOn(engineBridge.livePropProfileAdapter, "read")
      .mockResolvedValue({
        profile: "deriv_2step_funded",
        startingBalance: 120000,
        currentBalance: 119800,
        currentEquity: 119700,
        todaysRealizedLoss: 100,
        todaysFloatingLossExposure: 50,
        highImpactNewsLockout: false,
      });

    await engineBridge.getCurrentPropProfileForRequest({
      connection: {
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        terminalPath: null,
      },
      startingBalance: 120000,
    });

    expect(propProfileSpy).toHaveBeenCalledWith({
      engineRoot: "c:\\engine-root",
      config: expect.objectContaining({
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        startingBalance: 120000,
      }),
    });
  });

  it("falls back to own-account env credentials when the request fields are blank", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    vi.stubEnv("SYNTHETIC_MT5_SERVER", "EnvServer");
    vi.stubEnv("SYNTHETIC_MT5_LOGIN", "111111");
    vi.stubEnv("SYNTHETIC_MT5_PASSWORD", "env-secret");

    const propProfileSpy = vi
      .spyOn(engineBridge.livePropProfileAdapter, "read")
      .mockResolvedValue({
        profile: "deriv_2step_funded",
        startingBalance: 100000,
        currentBalance: 100050,
        currentEquity: 100010,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 40,
        highImpactNewsLockout: false,
      });

    await engineBridge.getCurrentPropProfileForRequest({
      connection: {
        server: null,
        login: null,
        password: null,
        terminalPath: null,
      },
      startingBalance: null,
    });

    expect(propProfileSpy).toHaveBeenCalledWith({
      engineRoot: "c:\\engine-root",
      config: expect.objectContaining({
        server: "EnvServer",
        login: "111111",
        password: "env-secret",
        startingBalance: 100000,
      }),
    });
  });

  it("returns an honest unavailable state when neither dedicated nor fallback credentials exist", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const propProfileSpy = vi.spyOn(engineBridge.livePropProfileAdapter, "read");

    const profile = await engineBridge.getCurrentPropProfileForRequest({
      connection: null,
      startingBalance: null,
    });

    expect(propProfileSpy).not.toHaveBeenCalled();
    expect(profile).toEqual({
      profile: "deriv_2step_funded",
      startingBalance: 100000,
      currentBalance: 100000,
      currentEquity: 99840,
      todaysRealizedLoss: 0,
      todaysFloatingLossExposure: 160,
      highImpactNewsLockout: false,
    });
  });
});
```

- [ ] **Step 2: Run the bridge test to verify the new API is missing**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts
```

Expected: FAIL with `getCurrentPropProfileForRequest is not a function` or equivalent missing-contract errors.

- [ ] **Step 3: Extend the contracts with request schemas**

```ts
import { z } from "zod";

export const propConnectionInputSchema = z.object({
  server: z.string().trim().nullable(),
  login: z.string().trim().nullable(),
  password: z.string().trim().nullable(),
  terminalPath: z.string().trim().nullable(),
  startingBalance: z.number().nullable(),
});

export const propProfileRequestSchema = z.object({
  connection: propConnectionInputSchema.nullable().optional(),
  startingBalance: z.number().nullable().optional(),
});

export const runCallRequestSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  account_mode: accountModeSchema,
  prop_account_state: z.unknown().nullable().optional(),
  prop_connection: propConnectionInputSchema.nullable().optional(),
});

export type PropConnectionInput = z.infer<typeof propConnectionInputSchema>;
export type PropProfileRequest = z.infer<typeof propProfileRequestSchema>;
export type RunCallRequest = z.infer<typeof runCallRequestSchema>;
```

- [ ] **Step 4: Add bridge helpers for request-first credential resolution**

```ts
const DEFAULT_PROP_STARTING_BALANCE = 100000;

function normalizeConnectionField(value: string | null | undefined) {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function resolveRequestedPropConfig(
  request: PropProfileRequest | null | undefined,
): LivePropProfileConfig | null {
  const requestedServer = normalizeConnectionField(request?.connection?.server ?? null);
  const requestedLogin = normalizeConnectionField(request?.connection?.login ?? null);
  const requestedPassword = normalizeConnectionField(request?.connection?.password ?? null);
  const requestedTerminalPath = normalizeConnectionField(
    request?.connection?.terminalPath ?? null,
  );

  const requestedBalance =
    typeof request?.startingBalance === "number" && Number.isFinite(request.startingBalance)
      ? request.startingBalance
      : typeof request?.connection?.startingBalance === "number" &&
          Number.isFinite(request.connection.startingBalance)
        ? request.connection.startingBalance
        : DEFAULT_PROP_STARTING_BALANCE;

  if (requestedServer && requestedLogin && requestedPassword) {
    return {
      server: requestedServer,
      login: requestedLogin,
      password: requestedPassword,
      terminalPath: requestedTerminalPath,
      startingBalance: requestedBalance,
      highImpactNewsLockout:
        String(process.env.SYNTHETIC_PROP_NEWS_LOCKOUT ?? "").toLowerCase() === "true",
      profile: "deriv_2step_funded",
    };
  }

  const fallback = getConfiguredLivePropProfile();
  if (!fallback) {
    return null;
  }

  return {
    ...fallback,
    startingBalance: requestedBalance,
  };
}

export async function getCurrentPropProfileForRequest(
  request: PropProfileRequest | null | undefined,
) {
  const engineRoot = getConfiguredEngineRoot();
  const liveConfig = resolveRequestedPropConfig(request);

  if (!engineRoot || !liveConfig) {
    return mockCurrentPropProfile;
  }

  try {
    return await livePropProfileAdapter.read({
      engineRoot,
      config: liveConfig,
    });
  } catch {
    return mockCurrentPropProfile;
  }
}
```

- [ ] **Step 5: Run the bridge tests again**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lib/contracts.ts src/lib/engine-bridge.ts tests/engine-bridge.test.ts
git commit -m "feat: add request-driven prop credential resolution"
```

### Task 2: Add The Request-Driven Prop Profile Route And Extend The Run Route

**Files:**
- Modify: `app/api/prop-profiles/current/route.ts`
- Modify: `app/api/calls/run/route.ts`
- Modify: `src/lib/contracts.ts`
- Test: `tests/api-routes.test.ts`

- [ ] **Step 1: Add failing route tests for prop-profile POST and prop-connection pass-through**

```ts
import { describe, expect, it, vi } from "vitest";
import { POST as postRun } from "../app/api/calls/run/route";
import {
  GET as getCurrentPropProfile,
  POST as postCurrentPropProfile,
} from "../app/api/prop-profiles/current/route";
import * as engineBridge from "../src/lib/engine-bridge";

it("POST /api/prop-profiles/current uses the request connection", async () => {
  const profileSpy = vi
    .spyOn(engineBridge, "getCurrentPropProfileForRequest")
    .mockResolvedValue({
      profile: "deriv_2step_funded",
      startingBalance: 100000,
      currentBalance: 100000,
      currentEquity: 99840,
      todaysRealizedLoss: 0,
      todaysFloatingLossExposure: 160,
      highImpactNewsLockout: false,
    });

  const response = await postCurrentPropProfile(
    new Request("http://localhost/api/prop-profiles/current", {
      method: "POST",
      body: JSON.stringify({
        connection: {
          server: "PropServer",
          login: "222222",
          password: "prop-secret",
          terminalPath: null,
        },
        startingBalance: 120000,
      }),
    }),
  );

  expect(response.status).toBe(200);
  expect(profileSpy).toHaveBeenCalledWith({
    connection: {
      server: "PropServer",
      login: "222222",
      password: "prop-secret",
      terminalPath: null,
    },
    startingBalance: 120000,
  });
});

it("POST /api/calls/run forwards prop_connection when prop mode is active", async () => {
  const runFreshCallSpy = vi
    .spyOn(engineBridge, "runFreshCall")
    .mockResolvedValue({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.71,
      regime: "trend_up",
      direction_bias: "buy",
      why: "buyers still control the short-term move",
      wait_for: "wait for a clean bullish continuation close",
      decision_summary: "buy setup ready",
      entry_area: "around 500.0",
      stop_area: "below 496.0",
      target_area: "toward 510.0",
      entry: 500,
      stop_loss: 496,
      take_profit: 510,
      reward_risk: 2.5,
      generated_at: "2026-07-10T11:00:00.000Z",
      account_mode: "prop_firm",
      prop_compliance: "allowed",
      prop_adjusted_risk: 1,
      prop_block_reason: null,
      prop_remaining_daily_buffer: 4800,
      prop_remaining_overall_buffer: 9800,
    });

  const response = await postRun(
    new Request("http://localhost/api/calls/run", {
      method: "POST",
      body: JSON.stringify({
        symbol: "R_100",
        account_mode: "prop_firm",
        prop_account_state: {
          profile: "deriv_2step_funded",
          startingBalance: 100000,
          currentBalance: 100000,
          currentEquity: 99840,
          todaysRealizedLoss: 0,
          todaysFloatingLossExposure: 160,
          highImpactNewsLockout: false,
        },
        prop_connection: {
          server: "PropServer",
          login: "222222",
          password: "prop-secret",
          terminalPath: null,
          startingBalance: 120000,
        },
      }),
    }),
  );

  expect(response.status).toBe(200);
  expect(runFreshCallSpy).toHaveBeenCalledWith(
    expect.objectContaining({
      accountMode: "prop_firm",
      propConnection: {
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        terminalPath: null,
        startingBalance: 120000,
      },
    }),
  );
});
```

- [ ] **Step 2: Run the route tests to verify the new POST handler and payload are not wired yet**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/api-routes.test.ts
```

Expected: FAIL because `POST /api/prop-profiles/current` does not exist yet and `runFreshCall` does not accept `propConnection`.

- [ ] **Step 3: Parse the new request schemas in both route files**

```ts
// app/api/prop-profiles/current/route.ts
import { NextResponse } from "next/server";
import { propProfileRequestSchema } from "../../../../src/lib/contracts";
import {
  getCurrentPropProfile,
  getCurrentPropProfileForRequest,
} from "../../../../src/lib/engine-bridge";

export async function GET() {
  const payload = await getCurrentPropProfile();
  return NextResponse.json(payload);
}

export async function POST(request: Request) {
  const body = propProfileRequestSchema.parse(await request.json());
  const payload = await getCurrentPropProfileForRequest(body);
  return NextResponse.json(payload);
}
```

```ts
// app/api/calls/run/route.ts
import { NextResponse } from "next/server";
import { runCallRequestSchema } from "../../../../src/lib/contracts";
import { runFreshCall } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  const body = runCallRequestSchema.parse(await request.json());

  const payload = await runFreshCall({
    symbol: body.symbol,
    accountMode: body.account_mode,
    propAccountState: body.prop_account_state ?? null,
    propConnection: body.prop_connection ?? null,
  });

  return NextResponse.json(payload);
}
```

- [ ] **Step 4: Extend the bridge call signature**

```ts
export async function runFreshCall({
  symbol,
  accountMode,
  propAccountState,
  propConnection,
}: {
  symbol: SymbolCode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
  propConnection: PropConnectionInput | null;
}): Promise<FreshCallResponse> {
  void propConnection;

  const engineRoot = getConfiguredEngineRoot();
  let result: FreshCallResponse;

  if (!engineRoot) {
    result = buildMockFreshCall({ symbol, accountMode, propAccountState });
  } else {
    try {
      const base = await liveSnapshotAdapter.read({ engineRoot, symbol });
      result = applyAccountMode({
        base,
        accountMode,
        propAccountState,
      });
    } catch {
      result = buildMockFreshCall({ symbol, accountMode, propAccountState });
    }
  }

  try {
    await appendHistoryEntry(result);
  } catch {}

  return result;
}
```

- [ ] **Step 5: Run the route tests again**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/api-routes.test.ts
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/api/prop-profiles/current/route.ts app/api/calls/run/route.ts src/lib/contracts.ts tests/api-routes.test.ts src/lib/engine-bridge.ts
git commit -m "feat: add dynamic prop profile route contract"
```

### Task 3: Build The Prop Connection Prompt And Session State

**Files:**
- Create: `src/components/operator/prop-connection-modal.tsx`
- Modify: `src/components/operator/command-bar.tsx`
- Modify: `src/components/operator/operator-shell.tsx`
- Modify: `src/hooks/use-operator-workspace.ts`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Add failing UI tests for prompt open, fallback submit, and partial validation**

```tsx
it("opens the prop connection prompt before switching modes", async () => {
  const user = userEvent.setup();
  render(<OperatorShell />);

  await user.click(screen.getByRole("button", { name: /prop firm/i }));

  expect(screen.getByRole("dialog", { name: /prop firm connection/i })).toBeInTheDocument();
  expect(screen.getByText(/leave these fields blank to use your own account connection/i)).toBeInTheDocument();
});

it("allows blank submit and switches to prop mode using own-account fallback", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);

    if (url.includes("/api/history")) {
      return Promise.resolve(
        new Response(JSON.stringify({ history: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }

    if (url.includes("/api/system/status")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            latest_call: "R_100 stand_aside",
            alert_count: 0,
            suppressed_context_count: 0,
            transport_event_count: 0,
            latest_transport_event: "steady",
            latest_transport_reason: "test route",
            backend_status: "live_bridge_ready",
            journal_status: "fresh",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    if (url.includes("/api/prop-profiles/current") && init?.method === "POST") {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            profile: "deriv_2step_funded",
            startingBalance: 100000,
            currentBalance: 100200,
            currentEquity: 100150,
            todaysRealizedLoss: 0,
            todaysFloatingLossExposure: 0,
            highImpactNewsLockout: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    if (url.includes("/api/prop-profiles/current")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            profile: "deriv_2step_funded",
            startingBalance: 100000,
            currentBalance: 100200,
            currentEquity: 100100,
            todaysRealizedLoss: 0,
            todaysFloatingLossExposure: 0,
            highImpactNewsLockout: false,
          }),
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }

    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /prop firm/i }));
  await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

  expect(screen.getByText(/prop checks are using the same mt5 account as own account/i)).toBeInTheDocument();
});

it("blocks partial manual input instead of silently falling back", async () => {
  const user = userEvent.setup();
  render(<OperatorShell />);

  await user.click(screen.getByRole("button", { name: /prop firm/i }));
  await user.type(screen.getByLabelText(/server/i), "PropServer");
  await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

  expect(screen.getByText(/enter login and password or leave all three fields blank/i)).toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: /prop firm connection/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the UI test to verify the prompt flow does not exist yet**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: FAIL because clicking `Prop Firm` currently switches mode immediately and no dialog exists.

- [ ] **Step 3: Create the prompt component**

```tsx
import React, { useEffect, useState } from "react";
import type { PropConnectionInput } from "../../lib/contracts";

type PropConnectionModalProps = {
  open: boolean;
  initialValue: PropConnectionInput | null;
  onCancel: () => void;
  onConfirm: (value: PropConnectionInput) => void;
};

export function PropConnectionModal({
  open,
  initialValue,
  onCancel,
  onConfirm,
}: PropConnectionModalProps) {
  const [server, setServer] = useState(initialValue?.server ?? "");
  const [login, setLogin] = useState(initialValue?.login ?? "");
  const [password, setPassword] = useState(initialValue?.password ?? "");
  const [startingBalance, setStartingBalance] = useState(
    String(initialValue?.startingBalance ?? 100000),
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    setServer(initialValue?.server ?? "");
    setLogin(initialValue?.login ?? "");
    setPassword(initialValue?.password ?? "");
    setStartingBalance(String(initialValue?.startingBalance ?? 100000));
    setError(null);
  }, [initialValue, open]);

  if (!open) {
    return null;
  }

  const handleSubmit = () => {
    const trimmedServer = server.trim();
    const trimmedLogin = login.trim();
    const trimmedPassword = password.trim();
    const providedCount = [trimmedServer, trimmedLogin, trimmedPassword].filter(Boolean).length;

    if (providedCount > 0 && providedCount < 3) {
      setError("Enter login and password or leave all three fields blank.");
      return;
    }

    onConfirm({
      server: trimmedServer || null,
      login: trimmedLogin || null,
      password: trimmedPassword || null,
      terminalPath: null,
      startingBalance: Number(startingBalance) || 100000,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(15,23,42,0.18)] px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Prop firm connection"
        className="surface w-full max-w-xl rounded-[2rem] p-6"
      >
        <h2 className="text-2xl font-semibold text-[var(--text-strong)]">
          Prop firm connection
        </h2>
        <p className="mt-3 text-sm leading-6 text-[var(--text-body)]">
          Leave these fields blank to use your own account connection for prop checks.
        </p>
        <label className="mt-5 block text-sm font-medium text-[var(--text-strong)]">
          Server
          <input value={server} onChange={(event) => setServer(event.target.value)} className="mt-2 w-full rounded-xl border px-3 py-2" />
        </label>
        <label className="mt-4 block text-sm font-medium text-[var(--text-strong)]">
          Login
          <input value={login} onChange={(event) => setLogin(event.target.value)} className="mt-2 w-full rounded-xl border px-3 py-2" />
        </label>
        <label className="mt-4 block text-sm font-medium text-[var(--text-strong)]">
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border px-3 py-2" />
        </label>
        <label className="mt-4 block text-sm font-medium text-[var(--text-strong)]">
          Starting balance
          <input value={startingBalance} onChange={(event) => setStartingBalance(event.target.value)} className="mt-2 w-full rounded-xl border px-3 py-2" />
        </label>
        {error ? <p className="mt-4 text-sm text-[var(--accent-warn)]">{error}</p> : null}
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" className="rounded-xl px-4 py-2 text-sm" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="command-button rounded-xl px-4 py-2 text-sm font-semibold" onClick={handleSubmit}>
            Continue in prop mode
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the workspace and shell around the prompt**

```tsx
const [propConnectionDraftOpen, setPropConnectionDraftOpen] = useState(false);
const [propConnection, setPropConnection] = useState<PropConnectionInput | null>(null);
const [propConnectionStatus, setPropConnectionStatus] = useState<
  "idle" | "using_own_account_fallback" | "using_dedicated_prop_account"
>("idle");

const requestPropMode = () => {
  setPropConnectionDraftOpen(true);
};

const confirmPropMode = async (value: PropConnectionInput) => {
  const usingDedicatedConnection = Boolean(value.server && value.login && value.password);

  setPropConnection(value);
  setPropConnectionStatus(
    usingDedicatedConnection
      ? "using_dedicated_prop_account"
      : "using_own_account_fallback",
  );
  setAccountMode("prop_firm");
  setPropConnectionDraftOpen(false);

  const response = await fetch("/api/prop-profiles/current", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      connection: usingDedicatedConnection
        ? {
            server: value.server,
            login: value.login,
            password: value.password,
            terminalPath: value.terminalPath,
          }
        : null,
      startingBalance: value.startingBalance,
    }),
  });

  if (response.ok) {
    setPropProfile((await response.json()) as PropAccountState);
  }
};

<CommandBar
  accountMode={workspace.accountMode}
  loading={workspace.loading}
  onRunSymbol={workspace.runSymbol}
  onSelectMode={workspace.setAccountMode}
  onRequestPropMode={workspace.requestPropMode}
/>

<PropConnectionModal
  open={workspace.propConnectionDraftOpen}
  initialValue={workspace.propConnection}
  onCancel={workspace.cancelPropModeRequest}
  onConfirm={workspace.confirmPropMode}
/>
```

- [ ] **Step 5: Run the UI tests again**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/components/operator/prop-connection-modal.tsx src/components/operator/command-bar.tsx src/components/operator/operator-shell.tsx src/hooks/use-operator-workspace.ts tests/operator-shell.test.tsx
git commit -m "feat: add session-only prop connection prompt"
```

### Task 4: Send The Selected Prop Connection Through Live Calls

**Files:**
- Modify: `src/hooks/use-operator-workspace.ts`
- Modify: `src/components/operator/prop-compliance-panel.tsx`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Add the failing UI test for prop-mode run payload composition**

```tsx
it("sends the selected prop connection when running a symbol in prop mode", async () => {
  const user = userEvent.setup();
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);

    if (url.includes("/api/history")) {
      return Promise.resolve(
        new Response(JSON.stringify({ history: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }

    if (url.includes("/api/system/status")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            latest_call: "R_100 stand_aside",
            alert_count: 0,
            suppressed_context_count: 0,
            transport_event_count: 0,
            latest_transport_event: "steady",
            latest_transport_reason: "test route",
            backend_status: "live_bridge_ready",
            journal_status: "fresh",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    if (url.includes("/api/prop-profiles/current")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            profile: "deriv_2step_funded",
            startingBalance: 120000,
            currentBalance: 119900,
            currentEquity: 119850,
            todaysRealizedLoss: 100,
            todaysFloatingLossExposure: 50,
            highImpactNewsLockout: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    if (url.includes("/api/calls/run")) {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        symbol: "R_100",
        account_mode: "prop_firm",
        prop_connection: {
          server: "PropServer",
          login: "222222",
          password: "prop-secret",
          terminalPath: null,
          startingBalance: 120000,
        },
      });

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
            decision_summary: "buy setup ready",
            entry_area: "around 500.0",
            stop_area: "below 496.0",
            target_area: "toward 510.0",
            entry: 500,
            stop_loss: 496,
            take_profit: 510,
            reward_risk: 2.5,
            generated_at: "2026-07-10T11:00:00.000Z",
            account_mode: "prop_firm",
            prop_compliance: "allowed",
            prop_adjusted_risk: 1,
            prop_block_reason: null,
            prop_remaining_daily_buffer: 4800,
            prop_remaining_overall_buffer: 9800,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }

    return Promise.reject(new Error(`Unexpected fetch: ${url}`));
  });

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /prop firm/i }));
  await user.type(screen.getByLabelText(/server/i), "PropServer");
  await user.type(screen.getByLabelText(/login/i), "222222");
  await user.type(screen.getByLabelText(/password/i), "prop-secret");
  await user.clear(screen.getByLabelText(/starting balance/i));
  await user.type(screen.getByLabelText(/starting balance/i), "120000");
  await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));
  await user.click(screen.getByRole("button", { name: /r_100/i }));

  expect(fetchSpy).toHaveBeenCalled();
  expect(await screen.findByText(/buy setup ready/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the UI test to verify the prop call payload is incomplete**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: FAIL because `runSymbol` does not yet include `prop_connection`.

- [ ] **Step 3: Include the selected connection in prop-mode run requests and show the account source**

```tsx
const runSymbol = async (symbol: SymbolCode) => {
  setLoading(true);
  setActiveSymbol(symbol);

  try {
    if (typeof fetch === "function") {
      const response = await fetch("/api/calls/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          symbol,
          account_mode: accountMode,
          prop_account_state: accountMode === "prop_firm" ? propProfile : null,
          prop_connection: accountMode === "prop_firm" ? propConnection : null,
        }),
      });

      if (response.ok) {
        const payload = (await response.json()) as FreshCallResponse;
        setCurrentCall(payload);
        return;
      }
    }
  } finally {
    setLoading(false);
  }
};

{workspace.accountMode === "prop_firm" ? (
  <>
    {workspace.propConnectionStatus === "using_own_account_fallback" ? (
      <p className="utility-copy mb-3 text-xs uppercase tracking-[0.2em]">
        Prop checks are using the same MT5 account as Own Account
      </p>
    ) : null}
    <PropCompliancePanel
      call={workspace.propCallPreview}
      profile={workspace.propProfile}
    />
  </>
) : (
  <ReviewSystemPanel status={workspace.systemStatus} />
)}
```

- [ ] **Step 4: Make the fallback state explicit in the prompt submit logic**

```tsx
const usingDedicatedConnection = Boolean(value.server && value.login && value.password);

setPropConnection(
  usingDedicatedConnection
    ? value
    : {
        server: null,
        login: null,
        password: null,
        terminalPath: null,
        startingBalance: value.startingBalance,
      },
);
setPropConnectionStatus(
  usingDedicatedConnection
    ? "using_dedicated_prop_account"
    : "using_own_account_fallback",
);
```

- [ ] **Step 5: Run the UI tests again**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/hooks/use-operator-workspace.ts src/components/operator/operator-shell.tsx src/components/operator/prop-compliance-panel.tsx tests/operator-shell.test.tsx
git commit -m "feat: send selected prop connection with prop-mode calls"
```

### Task 5: Run Full Verification And Clean Up Any Contract Drift

**Files:**
- Modify: `tests/api-routes.test.ts`
- Modify: `tests/engine-bridge.test.ts`
- Modify: `tests/operator-shell.test.tsx`
- Modify: `src/lib/contracts.ts`

- [ ] **Step 1: Run the focused test suite together**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 2: Run the full project test suite**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test
```

Expected: PASS

- [ ] **Step 3: Run the production build**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run build
```

Expected: PASS

- [ ] **Step 4: Fix any type or contract drift discovered by tests**

```ts
// Keep these names consistent everywhere after the build:
// - PropConnectionInput
// - prop_connection
// - getCurrentPropProfileForRequest()
// - runCallRequestSchema
// - propProfileRequestSchema
```

- [ ] **Step 5: Re-run the focused suite after any cleanup**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/api-routes.test.ts tests/engine-bridge.test.ts tests/operator-shell.test.tsx src/lib/contracts.ts
git commit -m "test: verify prop firm session credential flow"
```
