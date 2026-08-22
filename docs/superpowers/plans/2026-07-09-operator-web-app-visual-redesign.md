# Operator Web App Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the existing `mitemshub-indices` operator app into a premium light-theme hybrid interface with stronger hierarchy, typography, and motion while preserving the current working product flow.

**Architecture:** Keep the current Next.js product structure and backend contract intact, and redesign the experience in place. Promote color, typography, spacing, and motion into a tokenized light-theme system in `app/globals.css`, then refactor the operator surfaces so the current call becomes the visual center of gravity and support panels become quieter utility layers. Use the standards in `external/mitems-studio-os` to drive the redesign, especially color, typography, layout, dashboard composition, and motion discipline.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS, Vitest, React Testing Library, existing `mitemshub-indices` operator app

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices`

Primary redesign targets:

- `app/globals.css`
  - Replace the current dark generic theme with a tokenized light visual system.
- `app/layout.tsx`
  - Keep metadata clean and preserve hydration-safe top-level rendering.
- `src/components/operator/operator-shell.tsx`
  - Recompose the page into command rail, main decision stage, and execution/oversight band.
- `src/components/operator/command-bar.tsx`
  - Turn the current button strip into a premium command rail.
- `src/components/operator/primary-call-panel.tsx`
  - Make the current call the dominant visual surface.
- `src/components/operator/trade-instruction-panel.tsx`
  - Reframe trade guidance with cleaner numeric hierarchy.
- `src/components/operator/prop-compliance-panel.tsx`
  - Make prop mode feel formal and policy-driven.
- `src/components/operator/review-system-panel.tsx`
  - Quiet, utility-first support surface.
- `src/components/operator/history-panel.tsx`
  - Quieter chronology treatment without competing with live decision content.
- `src/components/operator/loading-state.tsx`
  - Upgrade the loading state so symbol changes feel deliberate.
- `src/lib/formatters.ts`
  - Add any text helpers needed for more editorial utility copy.
- `tests/operator-shell.test.tsx`
  - Preserve the working operator flows during visual redesign.

Secondary files for limited support:

- `src/hooks/use-operator-workspace.ts`
  - Only for small presentational state additions required by the redesign.
- `app/icon.svg`
  - Align favicon/system icon styling with the redesign.

### Task 1: Establish The Light Theme Token System

**Files:**
- Modify: `app/globals.css`
- Modify: `app/layout.tsx`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Write the failing test for the new light-theme shell**

```tsx
/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OperatorShell } from "../src/components/operator/operator-shell";

describe("OperatorShell light theme", () => {
  it("renders the operator workspace with light-theme shell copy intact", () => {
    render(<OperatorShell />);

    expect(screen.getByText(/operator workspace/i)).toBeInTheDocument();
    expect(screen.getByText(/fresh-call command bar/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails in the current dark theme context**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS on existing behavior but no redesign yet. Treat this as the safety net before changing the shell.

- [ ] **Step 3: Replace the global dark defaults with a tokenized light theme**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: light;
  --bg-canvas: #f5f1e8;
  --bg-panel: rgba(255, 252, 245, 0.86);
  --bg-panel-strong: #fffdf9;
  --line-subtle: rgba(37, 45, 61, 0.12);
  --line-strong: rgba(37, 45, 61, 0.24);
  --text-strong: #1d2430;
  --text-body: #4b5565;
  --text-muted: #7d8796;
  --accent-ink: #274690;
  --accent-positive: #145a4a;
  --accent-warn: #9a6a18;
  --shadow-soft: 0 24px 60px rgba(31, 41, 55, 0.08);
}

html {
  background: var(--bg-canvas);
}

body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at top left, rgba(39, 70, 144, 0.08), transparent 32%),
    linear-gradient(180deg, #f8f4ec 0%, #f3eee3 100%);
  color: var(--text-strong);
  font-family: "Georgia", "Times New Roman", serif;
}

@layer components {
  .app-shell {
    @apply min-h-screen;
    color: var(--text-strong);
  }

  .surface {
    background: var(--bg-panel);
    border: 1px solid var(--line-subtle);
    box-shadow: var(--shadow-soft);
    backdrop-filter: blur(16px);
  }

  .utility-copy {
    color: var(--text-muted);
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
  }
}
```

- [ ] **Step 4: Keep `layout.tsx` hydration-safe and metadata-clean**

```tsx
import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MitemsHub Indices",
  description: "Private operator workspace for synthetic indices calls",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 5: Run the UI test to verify the shell still passes**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/globals.css app/layout.tsx tests/operator-shell.test.tsx
git commit -m "feat: add light theme design tokens"
```

### Task 2: Redesign The Command Rail And Main Decision Stage

**Files:**
- Modify: `src/components/operator/operator-shell.tsx`
- Modify: `src/components/operator/command-bar.tsx`
- Modify: `src/components/operator/primary-call-panel.tsx`
- Modify: `src/components/operator/loading-state.tsx`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Extend the UI test to lock the new hierarchy**

```tsx
it("renders the main decision stage as the primary focal surface", async () => {
  const user = userEvent.setup();

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /r_100/i }));

  expect(await screen.findByText(/current call/i)).toBeInTheDocument();
  expect(screen.getByText(/market rationale/i)).toBeInTheDocument();
  expect(screen.getByText(/next trigger/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: FAIL because the current surfaces do not expose the new hierarchy labels or composition.

- [ ] **Step 3: Recompose the shell into command rail plus decision-led layout**

```tsx
export function OperatorShell() {
  const workspace = useOperatorWorkspace();

  return (
    <main className="app-shell">
      <div className="mx-auto max-w-[1480px] px-5 py-5 md:px-8 md:py-8 xl:px-10">
        <CommandBar
          accountMode={workspace.accountMode}
          loading={workspace.loading}
          onRunSymbol={workspace.runSymbol}
          onSelectMode={workspace.setAccountMode}
        />

        <section className="mt-8 grid gap-8 xl:grid-cols-[1.55fr_0.9fr]">
          <PrimaryCallPanel
            call={workspace.currentCall}
            loading={workspace.loading}
          />
          <TradeInstructionPanel call={workspace.currentCall} />
        </section>

        <section className="mt-8 grid gap-8 xl:grid-cols-[1.1fr_0.9fr]">
          {workspace.accountMode === "prop_firm" ? (
            <PropCompliancePanel
              call={workspace.propCallPreview}
              profile={workspace.propProfile}
            />
          ) : (
            <ReviewSystemPanel status={workspace.systemStatus} />
          )}
          <HistoryPanel history={workspace.history} />
        </section>
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Upgrade the command rail and main call surface**

```tsx
export function CommandBar(...) {
  return (
    <section className="surface rounded-[32px] px-6 py-6 md:px-8 md:py-7">
      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.9fr_0.9fr] xl:items-end">
        <div>
          <p className="utility-copy text-[11px] uppercase tracking-[0.28em]">
            Operator workspace
          </p>
          <h1 className="mt-3 max-w-xl text-4xl leading-none text-[var(--text-strong)] md:text-6xl">
            Fresh-call command rail
          </h1>
        </div>
        ...
      </div>
    </section>
  );
}
```

```tsx
export function PrimaryCallPanel({ call, loading }: PrimaryCallPanelProps) {
  return (
    <section className="surface rounded-[40px] px-6 py-7 md:px-10 md:py-10">
      <p className="utility-copy text-[11px] uppercase tracking-[0.28em]">
        Current call
      </p>
      <h2 className="mt-4 text-5xl leading-[0.92] text-[var(--text-strong)] md:text-7xl">
        {call ? formatLabel(call.call) : "Stand by"}
      </h2>
      <div className="mt-8 grid gap-5 md:grid-cols-2">
        <div>
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
            Market rationale
          </p>
          <p className="mt-3 text-base leading-7 text-[var(--text-body)]">
            {call?.why}
          </p>
        </div>
        <div>
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
            Next trigger
          </p>
          <p className="mt-3 text-base leading-7 text-[var(--text-body)]">
            {call?.wait_for}
          </p>
        </div>
      </div>
      {loading ? <LoadingState /> : null}
    </section>
  );
}
```

- [ ] **Step 5: Run the UI test to verify it passes**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/components/operator/operator-shell.tsx src/components/operator/command-bar.tsx src/components/operator/primary-call-panel.tsx src/components/operator/loading-state.tsx tests/operator-shell.test.tsx
git commit -m "feat: redesign command rail and decision stage"
```

### Task 3: Redesign Execution, Prop, Review, And History Surfaces

**Files:**
- Modify: `src/components/operator/trade-instruction-panel.tsx`
- Modify: `src/components/operator/prop-compliance-panel.tsx`
- Modify: `src/components/operator/review-system-panel.tsx`
- Modify: `src/components/operator/history-panel.tsx`
- Modify: `src/lib/formatters.ts`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Extend the UI test for prop and support hierarchy**

```tsx
it("reveals a formal prop policy overlay in prop mode", async () => {
  const user = userEvent.setup();

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /prop firm/i }));

  expect(screen.getByText(/prop overlay/i)).toBeInTheDocument();
  expect(screen.getByText(/compliance status/i)).toBeInTheDocument();
  expect(screen.getByText(/remaining daily buffer/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: FAIL because the current support surfaces do not yet expose the redesigned policy/utility copy structure.

- [ ] **Step 3: Redesign the execution and oversight surfaces**

```tsx
export function TradeInstructionPanel({ call }: TradeInstructionPanelProps) {
  return (
    <section className="surface rounded-[32px] px-6 py-7 md:px-8 md:py-8">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
        Execution brief
      </p>
      <h3 className="mt-3 text-2xl text-[var(--text-strong)]">
        Manual trade framing
      </h3>
      ...
    </section>
  );
}
```

```tsx
export function PropCompliancePanel({ call, profile }: PropCompliancePanelProps) {
  return (
    <section className="rounded-[32px] border border-[rgba(154,106,24,0.22)] bg-[rgba(255,248,232,0.92)] px-6 py-7 shadow-[0_18px_40px_rgba(154,106,24,0.08)]">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
        Prop overlay
      </p>
      <h3 className="mt-3 text-3xl text-[var(--text-strong)]">
        Compliance status
      </h3>
      <p className="mt-4 text-sm text-[var(--text-body)]">
        Deriv 2-Step funded
      </p>
      ...
      <p className="utility-copy mt-6 text-[11px] uppercase tracking-[0.24em]">
        Remaining daily buffer
      </p>
      ...
    </section>
  );
}
```

- [ ] **Step 4: Update history and review to read as quieter utility surfaces**

```ts
export function formatLabel(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatPercent(value: number | null) {
  return value === null ? "N/A" : `${value.toFixed(2)}%`;
}
```

- [ ] **Step 5: Run the UI test to verify it passes**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/components/operator/trade-instruction-panel.tsx src/components/operator/prop-compliance-panel.tsx src/components/operator/review-system-panel.tsx src/components/operator/history-panel.tsx src/lib/formatters.ts tests/operator-shell.test.tsx
git commit -m "feat: redesign execution and oversight surfaces"
```

### Task 4: Add Motion And Polish Without Breaking Hydration

**Files:**
- Modify: `src/components/operator/operator-shell.tsx`
- Modify: `src/components/operator/command-bar.tsx`
- Modify: `src/components/operator/loading-state.tsx`
- Modify: `app/globals.css`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Write the failing test for preserved symbol interactions**

```tsx
it("still runs a fresh symbol call while preserving the redesigned shell", async () => {
  const user = userEvent.setup();

  render(<OperatorShell />);
  await user.click(screen.getByRole("button", { name: /r_75/i }));

  expect(await screen.findByText(/current call/i)).toBeInTheDocument();
  expect(screen.getByText(/manual trade framing/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails only if the redesign breaks interaction flow**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS before motion changes. Use this as the guard rail.

- [ ] **Step 3: Add restrained motion and interaction polish**

```css
@media (prefers-reduced-motion: no-preference) {
  .decision-stage {
    animation: decisionEnter 420ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .support-stage {
    animation: supportEnter 520ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .command-button {
    transition:
      transform 160ms ease,
      background-color 160ms ease,
      border-color 160ms ease,
      box-shadow 180ms ease;
  }

  .command-button:hover {
    transform: translateY(-1px);
  }
}
```

```tsx
<section className="decision-stage surface rounded-[40px] ...">
```

```tsx
<button className="command-button ...">R_100</button>
```

- [ ] **Step 4: Re-check hydration safety while keeping the layout deterministic**

```tsx
export function OperatorShell() {
  const workspace = useOperatorWorkspace();

  return (
    <main className="app-shell">
      ...
    </main>
  );
}
```

Keep these rules:
- no `Date.now()` in render
- no `Math.random()` in render
- no `typeof window` branches in JSX output
- no app-authored theme attribute mutation on `<html>`

- [ ] **Step 5: Run the UI test to verify the redesign still passes**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test -- tests/operator-shell.test.tsx
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/components/operator/operator-shell.tsx src/components/operator/command-bar.tsx src/components/operator/loading-state.tsx app/globals.css tests/operator-shell.test.tsx
git commit -m "feat: add redesign motion polish"
```

### Task 5: Full Verification And Preview Check

**Files:**
- Modify: none unless a minimal fix is required
- Test: `tests/contracts.test.ts`
- Test: `tests/prop-policy.test.ts`
- Test: `tests/engine-bridge.test.ts`
- Test: `tests/api-routes.test.ts`
- Test: `tests/operator-shell.test.tsx`

- [ ] **Step 1: Run the full suite**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test
```

Expected: PASS with all five test files green.

- [ ] **Step 2: Start the app locally**

Run:

```bash
$env:PATH='c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'c:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run dev
```

Expected: Next.js dev server starts on an available local port such as `http://localhost:3000` or `http://localhost:3001`.

- [ ] **Step 3: Manually verify the redesigned experience**

Check:
- the app is light-theme only
- the main call stage is visually dominant
- `Prop Firm` mode reveals a formal policy overlay
- symbol switches feel deliberate and polished
- history and review panels feel quieter than the decision stage
- no app-authored hydration mismatch is introduced

Expected: all checks pass.

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: redesign operator app visuals"
```
