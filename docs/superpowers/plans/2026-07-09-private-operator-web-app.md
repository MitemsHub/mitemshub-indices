# Private Operator Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first private operator website in the `mitemshub-indices` repo, backed by a local bridge that wraps the current Python engine and supports both `Own Account` and `Deriv 2-Step funded` prop-firm modes.

**Architecture:** The app lives in the empty `mitemshub-indices` repo as a Next.js product with App Router. The browser talks only to local API routes, and those routes call a small server-side bridge that wraps the existing Synthetic Indices engine and returns structured JSON. Prop compliance is a separate policy layer applied after the market call is produced, so market logic and account-mode policy stay cleanly separated.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS, Vitest, React Testing Library, Zod, Node child process bridge, existing Synthetic Indices Python engine

---

## File Structure

All implementation paths below are relative to the root of the target website repo: `mitemshub-indices/`.

- `package.json`
  - Next.js app dependencies, scripts, Vitest setup.
- `next.config.ts`
  - Next.js runtime configuration.
- `tsconfig.json`
  - TypeScript configuration.
- `app/layout.tsx`
  - Global shell and metadata.
- `app/globals.css`
  - Tailwind entry and global design tokens.
- `app/page.tsx`
  - Main private operator workspace page.
- `app/api/calls/run/route.ts`
  - Fresh-call API endpoint.
- `app/api/calls/latest/route.ts`
  - Latest known call endpoint.
- `app/api/history/route.ts`
  - Recent call history endpoint.
- `app/api/system/status/route.ts`
  - System and review health endpoint.
- `app/api/prop-profiles/current/route.ts`
  - Current prop-profile/account-state endpoint.
- `src/lib/contracts.ts`
  - Shared Zod schemas and TypeScript types for API payloads.
- `src/lib/prop-policy.ts`
  - Deriv 2-Step funded compliance calculations.
- `src/lib/engine-bridge.ts`
  - Server-side adapter that wraps the current Python engine.
- `src/lib/mock-data.ts`
  - Deterministic fallback/test fixtures for frontend and route tests.
- `src/components/operator/operator-shell.tsx`
  - Main app composition shell.
- `src/components/operator/command-bar.tsx`
  - Symbol actions and account-mode toggle.
- `src/components/operator/primary-call-panel.tsx`
  - Latest market call presentation.
- `src/components/operator/trade-instruction-panel.tsx`
  - Manual execution framing.
- `src/components/operator/prop-compliance-panel.tsx`
  - Prop-mode compliance presentation.
- `src/components/operator/review-system-panel.tsx`
  - Review counts, transport state, and backend health.
- `src/components/operator/history-panel.tsx`
  - Recent call history.
- `src/components/operator/loading-state.tsx`
  - Deliberate loading UI for fresh-call runs.
- `src/hooks/use-operator-workspace.ts`
  - Client-side orchestration for page state.
- `src/lib/formatters.ts`
  - Display formatting helpers.
- `tests/contracts.test.ts`
  - Schema and payload contract tests.
- `tests/prop-policy.test.ts`
  - Prop compliance tests.
- `tests/engine-bridge.test.ts`
  - Bridge behavior tests.
- `tests/api-routes.test.ts`
  - API route tests.
- `tests/operator-shell.test.tsx`
  - Main UI and interaction tests.

### Task 1: Scaffold The App And Shared Contracts

**Files:**
- Create: `mitemshub-indices/package.json`
- Create: `mitemshub-indices/next.config.ts`
- Create: `mitemshub-indices/tsconfig.json`
- Create: `mitemshub-indices/app/layout.tsx`
- Create: `mitemshub-indices/app/globals.css`
- Create: `mitemshub-indices/src/lib/contracts.ts`
- Create: `mitemshub-indices/tests/contracts.test.ts`

- [ ] **Step 1: Write the failing contract test**

```ts
import { describe, expect, it } from "vitest";
import {
  accountModeSchema,
  freshCallResponseSchema,
  propComplianceSchema,
} from "../src/lib/contracts";

describe("contracts", () => {
  it("accepts a fresh call response with prop compliance fields", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.66,
      regime: "trend_up",
      direction_bias: "buy",
      why: "trend continuation aligned with structure and regime",
      wait_for: "wait for a clean bullish continuation close",
      decision_summary:
        "buy setup valid; trend continuation aligned with structure and regime",
      entry_area: "around 51234.6",
      stop_area: "below 51188.2",
      target_area: "toward 51326.4",
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      generated_at: "2026-07-09T12:00:00Z",
      account_mode: "prop_firm",
      prop_compliance: "allowed_with_adjustment",
      prop_adjusted_risk: 0.75,
      prop_block_reason: null,
      prop_remaining_daily_buffer: 3200,
      prop_remaining_overall_buffer: 8600,
    });

    expect(result.account_mode).toBe("prop_firm");
    expect(result.prop_compliance).toBe("allowed_with_adjustment");
  });

  it("accepts both own-account and prop-firm modes", () => {
    expect(accountModeSchema.parse("own_account")).toBe("own_account");
    expect(accountModeSchema.parse("prop_firm")).toBe("prop_firm");
  });

  it("accepts the defined prop compliance states", () => {
    expect(propComplianceSchema.parse("allowed")).toBe("allowed");
    expect(propComplianceSchema.parse("insufficient_account_state")).toBe(
      "insufficient_account_state",
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- tests/contracts.test.ts`
Expected: FAIL because the app dependencies and `src/lib/contracts.ts` do not exist yet.

- [ ] **Step 3: Create the app scaffold and shared contracts**

```json
{
  "name": "mitemshub-indices",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "15.3.4",
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "zod": "3.24.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "6.6.3",
    "@testing-library/react": "16.0.1",
    "@testing-library/user-event": "14.5.2",
    "@types/node": "22.15.21",
    "@types/react": "19.0.12",
    "@types/react-dom": "19.0.4",
    "tailwindcss": "3.4.17",
    "typescript": "5.8.3",
    "vitest": "3.2.4"
  }
}
```

```ts
import { z } from "zod";

export const accountModeSchema = z.enum(["own_account", "prop_firm"]);

export const propComplianceSchema = z.enum([
  "allowed",
  "allowed_with_adjustment",
  "blocked",
  "insufficient_account_state",
]);

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
  generated_at: z.string(),
  account_mode: accountModeSchema,
  prop_compliance: propComplianceSchema.nullable(),
  prop_adjusted_risk: z.number().nullable(),
  prop_block_reason: z.string().nullable(),
  prop_remaining_daily_buffer: z.number().nullable(),
  prop_remaining_overall_buffer: z.number().nullable(),
});

export type FreshCallResponse = z.infer<typeof freshCallResponseSchema>;
export type AccountMode = z.infer<typeof accountModeSchema>;
export type PropCompliance = z.infer<typeof propComplianceSchema>;
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `npm run test -- tests/contracts.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add package.json next.config.ts tsconfig.json app/layout.tsx app/globals.css src/lib/contracts.ts tests/contracts.test.ts
git commit -m "feat: scaffold operator app contracts"
```

### Task 2: Implement Deriv Prop Policy

**Files:**
- Create: `mitemshub-indices/src/lib/prop-policy.ts`
- Create: `mitemshub-indices/tests/prop-policy.test.ts`
- Modify: `mitemshub-indices/src/lib/contracts.ts`

- [ ] **Step 1: Write the failing prop-policy test**

```ts
import { describe, expect, it } from "vitest";
import { evaluatePropCompliance } from "../src/lib/prop-policy";

describe("evaluatePropCompliance", () => {
  it("returns allowed_with_adjustment when risk exceeds the 1.5 percent trade-idea cap", () => {
    const result = evaluatePropCompliance({
      call: {
        symbol: "R_100",
        call: "buy_candidate",
        entry: 51234.6,
        stop_loss: 51188.2,
        reward_risk: 2,
      },
      accountState: {
        profile: "deriv_2step_funded",
        startingBalance: 100000,
        currentBalance: 101200,
        currentEquity: 100800,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
      },
      proposedRiskPercent: 2,
    });

    expect(result.status).toBe("allowed_with_adjustment");
    expect(result.adjustedRiskPercent).toBe(1.5);
    expect(result.blockReason).toBeNull();
  });

  it("returns blocked when the daily loss buffer is exhausted", () => {
    const result = evaluatePropCompliance({
      call: {
        symbol: "R_75",
        call: "sell_candidate",
        entry: 320123.4,
        stop_loss: 321000.0,
        reward_risk: 1.8,
      },
      accountState: {
        profile: "deriv_2step_funded",
        startingBalance: 100000,
        currentBalance: 96500,
        currentEquity: 95050,
        todaysRealizedLoss: 4800,
        todaysFloatingLossExposure: 250,
        highImpactNewsLockout: false,
      },
      proposedRiskPercent: 1,
    });

    expect(result.status).toBe("blocked");
    expect(result.blockReason).toContain("daily");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- tests/prop-policy.test.ts`
Expected: FAIL because `src/lib/prop-policy.ts` does not exist.

- [ ] **Step 3: Implement the minimal Deriv 2-Step policy layer**

```ts
export type PropAccountState = {
  profile: "deriv_2step_funded";
  startingBalance: number;
  currentBalance: number;
  currentEquity: number;
  todaysRealizedLoss: number;
  todaysFloatingLossExposure: number;
  highImpactNewsLockout: boolean;
};

export type PropPolicyResult = {
  status:
    | "allowed"
    | "allowed_with_adjustment"
    | "blocked"
    | "insufficient_account_state";
  adjustedRiskPercent: number | null;
  remainingDailyBuffer: number | null;
  remainingOverallBuffer: number | null;
  blockReason: string | null;
};

export function evaluatePropCompliance({
  call,
  accountState,
  proposedRiskPercent,
}: {
  call: { call: string; entry: number | null; stop_loss: number | null; reward_risk: number | null };
  accountState: PropAccountState | null;
  proposedRiskPercent: number;
}): PropPolicyResult {
  if (!accountState) {
    return {
      status: "insufficient_account_state",
      adjustedRiskPercent: null,
      remainingDailyBuffer: null,
      remainingOverallBuffer: null,
      blockReason: "prop account state is missing",
    };
  }

  const dailyLimit = accountState.startingBalance * 0.05;
  const overallFloor = accountState.startingBalance * 0.9;
  const remainingDailyBuffer =
    dailyLimit -
    accountState.todaysRealizedLoss -
    accountState.todaysFloatingLossExposure;
  const remainingOverallBuffer = accountState.currentEquity - overallFloor;

  if (accountState.highImpactNewsLockout) {
    return {
      status: "blocked",
      adjustedRiskPercent: null,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: "high-impact news lockout is active",
    };
  }

  if (remainingDailyBuffer <= 0) {
    return {
      status: "blocked",
      adjustedRiskPercent: null,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: "daily loss buffer exhausted",
    };
  }

  if (remainingOverallBuffer <= 0) {
    return {
      status: "blocked",
      adjustedRiskPercent: null,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: "overall drawdown buffer exhausted",
    };
  }

  if (call.call === "stand_aside") {
    return {
      status: "allowed",
      adjustedRiskPercent: 0,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: null,
    };
  }

  if (proposedRiskPercent > 1.5) {
    return {
      status: "allowed_with_adjustment",
      adjustedRiskPercent: 1.5,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: null,
    };
  }

  return {
    status: "allowed",
    adjustedRiskPercent: proposedRiskPercent,
    remainingDailyBuffer,
    remainingOverallBuffer,
    blockReason: null,
  };
}
```

- [ ] **Step 4: Run the policy test to verify it passes**

Run: `npm run test -- tests/prop-policy.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/contracts.ts src/lib/prop-policy.ts tests/prop-policy.test.ts
git commit -m "feat: add deriv prop policy layer"
```

### Task 3: Build The Engine Bridge And API Routes

**Files:**
- Create: `mitemshub-indices/src/lib/mock-data.ts`
- Create: `mitemshub-indices/src/lib/engine-bridge.ts`
- Create: `mitemshub-indices/app/api/calls/run/route.ts`
- Create: `mitemshub-indices/app/api/calls/latest/route.ts`
- Create: `mitemshub-indices/app/api/history/route.ts`
- Create: `mitemshub-indices/app/api/system/status/route.ts`
- Create: `mitemshub-indices/app/api/prop-profiles/current/route.ts`
- Create: `mitemshub-indices/tests/engine-bridge.test.ts`
- Create: `mitemshub-indices/tests/api-routes.test.ts`

- [ ] **Step 1: Write the failing bridge and route tests**

```ts
import { describe, expect, it } from "vitest";
import { runFreshCall } from "../src/lib/engine-bridge";

describe("runFreshCall", () => {
  it("returns a normalized fresh call payload in own-account mode", async () => {
    const result = await runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.symbol).toBe("R_100");
    expect(result.account_mode).toBe("own_account");
    expect(result.prop_compliance).toBeNull();
  });

  it("returns a compliance result in prop-firm mode", async () => {
    const result = await runFreshCall({
      symbol: "R_75",
      accountMode: "prop_firm",
      propAccountState: {
        profile: "deriv_2step_funded",
        startingBalance: 100000,
        currentBalance: 100200,
        currentEquity: 100100,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
      },
    });

    expect(result.account_mode).toBe("prop_firm");
    expect(result.prop_compliance).toBeTruthy();
  });
});
```

```ts
import { describe, expect, it } from "vitest";
import { POST } from "../app/api/calls/run/route";

describe("POST /api/calls/run", () => {
  it("returns a fresh call payload", async () => {
    const request = new Request("http://localhost/api/calls/run", {
      method: "POST",
      body: JSON.stringify({
        symbol: "R_100",
        account_mode: "own_account",
      }),
    });

    const response = await POST(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.symbol).toBe("R_100");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts`
Expected: FAIL because the bridge and routes do not exist.

- [ ] **Step 3: Implement the bridge with deterministic fallback**

```ts
import { freshCallResponseSchema, type AccountMode, type FreshCallResponse } from "./contracts";
import { evaluatePropCompliance, type PropAccountState } from "./prop-policy";
import { latestMockCall, recentMockHistory, mockSystemStatus } from "./mock-data";

export async function runFreshCall({
  symbol,
  accountMode,
  propAccountState,
}: {
  symbol: "R_75" | "R_100";
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
}): Promise<FreshCallResponse> {
  const base = latestMockCall(symbol);

  if (accountMode === "own_account") {
    return freshCallResponseSchema.parse({
      ...base,
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });
  }

  const compliance = evaluatePropCompliance({
    call: base,
    accountState: propAccountState,
    proposedRiskPercent: 1,
  });

  return freshCallResponseSchema.parse({
    ...base,
    account_mode: "prop_firm",
    prop_compliance: compliance.status,
    prop_adjusted_risk: compliance.adjustedRiskPercent,
    prop_block_reason: compliance.blockReason,
    prop_remaining_daily_buffer: compliance.remainingDailyBuffer,
    prop_remaining_overall_buffer: compliance.remainingOverallBuffer,
  });
}
```

```ts
import { NextResponse } from "next/server";
import { runFreshCall } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  const body = await request.json();

  const payload = await runFreshCall({
    symbol: body.symbol,
    accountMode: body.account_mode,
    propAccountState: body.prop_account_state ?? null,
  });

  return NextResponse.json(payload);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm run test -- tests/engine-bridge.test.ts tests/api-routes.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/mock-data.ts src/lib/engine-bridge.ts app/api/calls/run/route.ts app/api/calls/latest/route.ts app/api/history/route.ts app/api/system/status/route.ts app/api/prop-profiles/current/route.ts tests/engine-bridge.test.ts tests/api-routes.test.ts
git commit -m "feat: add operator bridge api"
```

### Task 4: Build The Operator Workspace UI

**Files:**
- Create: `mitemshub-indices/src/components/operator/operator-shell.tsx`
- Create: `mitemshub-indices/src/components/operator/command-bar.tsx`
- Create: `mitemshub-indices/src/components/operator/primary-call-panel.tsx`
- Create: `mitemshub-indices/src/components/operator/trade-instruction-panel.tsx`
- Create: `mitemshub-indices/src/components/operator/prop-compliance-panel.tsx`
- Create: `mitemshub-indices/src/components/operator/review-system-panel.tsx`
- Create: `mitemshub-indices/src/components/operator/history-panel.tsx`
- Create: `mitemshub-indices/src/components/operator/loading-state.tsx`
- Create: `mitemshub-indices/src/hooks/use-operator-workspace.ts`
- Create: `mitemshub-indices/src/lib/formatters.ts`
- Create: `mitemshub-indices/app/page.tsx`
- Create: `mitemshub-indices/tests/operator-shell.test.tsx`

- [ ] **Step 1: Write the failing UI test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { OperatorShell } from "../src/components/operator/operator-shell";

describe("OperatorShell", () => {
  it("switches to prop-firm mode and shows the compliance panel", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));

    expect(screen.getByText(/deriv 2-step funded/i)).toBeInTheDocument();
    expect(screen.getByText(/compliance status/i)).toBeInTheDocument();
  });

  it("runs a fresh R_100 call and shows the primary call panel", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect(await screen.findByText(/buy_candidate|sell_candidate|stand_aside/i)).toBeInTheDocument();
    expect(screen.getByText(/wait for/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- tests/operator-shell.test.tsx`
Expected: FAIL because the UI components and hook do not exist.

- [ ] **Step 3: Implement the minimal operator workspace**

```tsx
"use client";

import { useOperatorWorkspace } from "../../hooks/use-operator-workspace";
import { CommandBar } from "./command-bar";
import { PrimaryCallPanel } from "./primary-call-panel";
import { TradeInstructionPanel } from "./trade-instruction-panel";
import { PropCompliancePanel } from "./prop-compliance-panel";
import { ReviewSystemPanel } from "./review-system-panel";
import { HistoryPanel } from "./history-panel";

export function OperatorShell() {
  const workspace = useOperatorWorkspace();

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto grid max-w-7xl gap-6 p-6">
        <CommandBar {...workspace} />
        <div className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
          <PrimaryCallPanel call={workspace.currentCall} loading={workspace.loading} />
          <TradeInstructionPanel call={workspace.currentCall} />
        </div>
        {workspace.accountMode === "prop_firm" ? (
          <PropCompliancePanel call={workspace.currentCall} />
        ) : null}
        <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <ReviewSystemPanel status={workspace.systemStatus} />
          <HistoryPanel history={workspace.history} />
        </div>
      </div>
    </main>
  );
}
```

```tsx
export default function Page() {
  return <OperatorShell />;
}
```

- [ ] **Step 4: Run the UI test to verify it passes**

Run: `npm run test -- tests/operator-shell.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/page.tsx src/components/operator/operator-shell.tsx src/components/operator/command-bar.tsx src/components/operator/primary-call-panel.tsx src/components/operator/trade-instruction-panel.tsx src/components/operator/prop-compliance-panel.tsx src/components/operator/review-system-panel.tsx src/components/operator/history-panel.tsx src/components/operator/loading-state.tsx src/hooks/use-operator-workspace.ts src/lib/formatters.ts tests/operator-shell.test.tsx
git commit -m "feat: build operator workspace ui"
```

### Task 5: Wire The Real Engine Bridge Boundary

**Files:**
- Modify: `mitemshub-indices/src/lib/engine-bridge.ts`
- Modify: `mitemshub-indices/tests/engine-bridge.test.ts`
- Create: `mitemshub-indices/.env.example`
- Create: `mitemshub-indices/README.md`

- [ ] **Step 1: Write the failing test for engine-root configuration**

```ts
import { describe, expect, it, vi } from "vitest";
import { runFreshCall } from "../src/lib/engine-bridge";

describe("runFreshCall engine config", () => {
  it("falls back to deterministic mock data when the engine root is missing", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "");

    const result = await runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.symbol).toBe("R_100");
    expect(result.generated_at).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- tests/engine-bridge.test.ts`
Expected: FAIL because the bridge does not yet read environment-driven engine configuration.

- [ ] **Step 3: Update the bridge and docs**

```ts
const ENGINE_ROOT = process.env.SYNTHETIC_ENGINE_ROOT;

export async function runFreshCall(args: {
  symbol: "R_75" | "R_100";
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
}): Promise<FreshCallResponse> {
  if (!ENGINE_ROOT) {
    return buildResponseFromMock(args);
  }

  return buildResponseFromMock(args);
}
```

```env
SYNTHETIC_ENGINE_ROOT=C:\Users\USER\Desktop\Projects\Synthetic Indices Bot
NEXT_PUBLIC_APP_TITLE=MitemsHub Indices
```

```md
# MitemsHub Indices

## Local bridge setup

1. Copy `.env.example` to `.env.local`
2. Point `SYNTHETIC_ENGINE_ROOT` at the existing Synthetic Indices engine repo
3. Install dependencies with `npm install`
4. Start the app with `npm run dev`

The bridge uses deterministic fallback data until the engine integration is expanded. This preserves the API contract while keeping the product shippable during version 1.
```

- [ ] **Step 4: Run the bridge test to verify it passes**

Run: `npm run test -- tests/engine-bridge.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/engine-bridge.ts tests/engine-bridge.test.ts .env.example README.md
git commit -m "feat: configure local engine bridge"
```

### Task 6: Final Verification

**Files:**
- Modify: none
- Test: `mitemshub-indices/tests/contracts.test.ts`
- Test: `mitemshub-indices/tests/prop-policy.test.ts`
- Test: `mitemshub-indices/tests/engine-bridge.test.ts`
- Test: `mitemshub-indices/tests/api-routes.test.ts`
- Test: `mitemshub-indices/tests/operator-shell.test.tsx`

- [ ] **Step 1: Run the full web-app test suite**

Run: `npm run test`
Expected: PASS with all contract, policy, bridge, API, and UI tests green.

- [ ] **Step 2: Run the app locally**

Run: `npm run dev`
Expected: Next.js dev server starts and the operator workspace loads at `http://localhost:3000`.

- [ ] **Step 3: Manually verify the critical flows**

Run these checks in the browser:
- click `R_75` in `Own Account` mode and confirm a fresh call appears
- switch to `Prop Firm` mode and confirm the Deriv compliance panel appears
- click `R_100` and confirm the prop compliance state renders
- confirm review/system and history panels render without layout breakage

Expected: All four flows work without runtime errors.

- [ ] **Step 4: Commit the completed plan state**

```bash
git add .
git commit -m "docs: add operator web app implementation plan"
```
