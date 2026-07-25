# Monorepo Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize the workspace into one active monorepo by retiring the nested app Git boundary and making the root repository own the operator app directly.

**Architecture:** Keep the app at `external/mitemshub-indices` to avoid path churn, but remove its internal `.git` directory so the root repository becomes the only active repository. Update root ignore rules, rewrite monorepo-facing documentation, then verify both Python and app workflows from the root-owned layout.

**Tech Stack:** Git, PowerShell, Python 3.13, pytest, Next.js 15, React 19, Vitest

---

## File Structure

**Files to modify**

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\.gitignore`
  - Replace the broad `external/` ignore with targeted ignores for the app's generated files and secrets.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\README.md`
  - Update the root docs to describe the project as one monorepo and explain where the app lives.
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\README.md`
  - Remove separate-repo wording and explain that the app is now part of the root monorepo.

**Files or directories to remove locally**

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\.git`
  - Retire the nested repository boundary after safety checks pass.

**Files to verify but not edit by default**

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\launch-mitemshub-indices.bat`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\launch-mitemshub-indices.ps1`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\stop-mitemshub-indices.ps1`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\operator-shell.test.tsx`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_signal_guardian.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase5_mt5_scaffolding.py`
- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase7_mt5_lifecycle.py`

---

### Task 1: Freeze Recovery Points And Verify Clean Starting State

**Files:**
- Modify: none
- Verify: root repo and nested app repo Git state

- [ ] **Step 1: Capture the current published anchors**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" rev-parse HEAD
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices" rev-parse HEAD
```

Expected:

```text
<root commit sha>
<app commit sha>
```

- [ ] **Step 2: Verify the root repo is clean before the cutover**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" status --short --branch
```

Expected:

```text
## feature/mt5-rollout-enablement...origin/feature/mt5-rollout-enablement
```

- [ ] **Step 3: Verify the nested app repo is also clean before retirement**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices" status --short --branch
```

Expected:

```text
## main...origin/main
```

- [ ] **Step 4: Commit the checkpoint note to the working session**

```bash
# No Git commit in this step.
# Record the two SHAs in the implementation notes or task log before continuing.
```

---

### Task 2: Make The Root Repo Ready To Own The App

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\.gitignore`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices`

- [ ] **Step 1: Write the root ignore change**

Replace the current tail of `.gitignore`:

```gitignore
data/
journals/
models/*.json
artifacts/
external/
```

with:

```gitignore
data/
journals/
models/*.json
artifacts/

external/mitemshub-indices/node_modules/
external/mitemshub-indices/.next/
external/mitemshub-indices/.data/
external/mitemshub-indices/.env.local
external/mitemshub-indices/dist/
external/mitemshub-indices/coverage/
external/mitemshub-indices/*.log
external/mitemshub-indices/task5-preview-check.png
external/mitemshub-indices/vitest-task4.json
```

- [ ] **Step 2: Verify the new ignore rules behave correctly**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" check-ignore -v external/mitemshub-indices/.env.local
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" check-ignore -v external/mitemshub-indices/node_modules
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" check-ignore -v external/mitemshub-indices/src/components/operator/command-bar.tsx
```

Expected:

```text
.gitignore:<line>:external/mitemshub-indices/.env.local external/mitemshub-indices/.env.local
.gitignore:<line>:external/mitemshub-indices/node_modules/ external/mitemshub-indices/node_modules
```

Expected final command behavior:

```text
# no output for command-bar.tsx because source files must not be ignored
```

- [ ] **Step 3: Verify the root repo can now see the app tree**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" status --short --untracked-files=all -- external/mitemshub-indices
```

Expected:

```text
# either no output yet because the nested .git still hides ownership,
# or visible untracked app files after the next task removes the boundary
```

- [ ] **Step 4: Commit the ignore-rule preparation**

```bash
git add .gitignore
git commit -m "chore: prepare root repo to own operator app"
```

---

### Task 3: Retire The Nested Git Boundary

**Files:**
- Remove locally: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\.git`
- Verify: root Git status after boundary removal

- [ ] **Step 1: Re-check the nested app remote anchor before deletion**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices" rev-parse --short HEAD
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices" status --short --branch
```

Expected:

```text
<short sha>
## main...origin/main
```

- [ ] **Step 2: Remove the nested `.git` directory**

Run:

```powershell
Remove-Item -Recurse -Force "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\.git"
```

Expected:

```text
# no output
```

- [ ] **Step 3: Verify the nested folder is no longer its own repo**

Run:

```powershell
Test-Path "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\.git"
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" status --short --untracked-files=all -- external/mitemshub-indices
```

Expected:

```text
False
?? external/mitemshub-indices/app/api/calls/guardian/route.ts
?? external/mitemshub-indices/src/components/operator/command-bar.tsx
...
```

- [ ] **Step 4: Commit the structural ownership flip**

```bash
git add external/mitemshub-indices
git commit -m "chore: absorb operator app into monorepo"
```

---

### Task 4: Rewrite The Documentation For One Monorepo

**Files:**
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\README.md`
- Modify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\README.md`

- [ ] **Step 1: Update the root README to describe the app as part of the project**

Add this section after the introductory architecture content in `README.md`:

```markdown
## Monorepo Layout

This project is one monorepo.

- Python engine: `src/synthetic_trader`
- Operator web app: `external/mitemshub-indices`
- Shared project docs: `docs/superpowers`

The operator app is not a separate repository anymore. Commit engine and app changes from the root repository.
```

- [ ] **Step 2: Update the app README to remove separate-repo wording**

Replace the opening setup section in `external/mitemshub-indices/README.md` with:

```markdown
# MitemsHub Indices

This operator app lives inside the main Synthetic Indices Bot monorepo.

## Local bridge setup

1. From the monorepo root, keep the engine code in place.
2. In this app folder, copy `.env.example` to `.env.local`.
3. Point `SYNTHETIC_ENGINE_ROOT` at the monorepo root:
   `C:\Users\USER\Desktop\Projects\Synthetic Indices Bot`
4. Install dependencies with `npm install`.
5. Start the app with `npm run dev`.
```

- [ ] **Step 3: Add explicit monorepo commit guidance to the app README**

Append this section near the end of `external/mitemshub-indices/README.md`:

```markdown
## Repository Ownership

This app is part of the same project as the Python engine.

- run Git commands from the monorepo root
- do not recreate a nested `.git` directory here
- keep app secrets in `.env.local`, which remains ignored by the root repo
```

- [ ] **Step 4: Verify the docs describe the same source-of-truth model**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" diff -- README.md external/mitemshub-indices/README.md
```

Expected:

```text
# diff shows both files now describe one monorepo and one root Git workflow
```

- [ ] **Step 5: Commit the documentation update**

```bash
git add README.md external/mitemshub-indices/README.md
git commit -m "docs: describe unified monorepo workflow"
```

---

### Task 5: Verify The Normalized Monorepo End To End

**Files:**
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_signal_guardian.py`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_live_market_snapshot.py`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase5_mt5_scaffolding.py`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\tests\test_phase7_mt5_lifecycle.py`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\operator-shell.test.tsx`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\operator-panels.test.tsx`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\engine-bridge.test.ts`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\contracts.test.ts`
- Verify: `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\tests\api-routes.test.ts`

- [ ] **Step 1: Run the focused Python verification from the root repo**

Run:

```powershell
python -m pytest tests/test_signal_guardian.py tests/test_live_market_snapshot.py tests/test_phase5_mt5_scaffolding.py tests/test_phase7_mt5_lifecycle.py
```

Expected:

```text
80 passed
```

- [ ] **Step 2: Run the focused app verification from the app folder under root ownership**

Run:

```powershell
$nodeDir = 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node'
$env:Path = "$nodeDir;$env:Path"
& "$nodeDir\npm.cmd" test -- tests/operator-shell.test.tsx tests/operator-panels.test.tsx tests/engine-bridge.test.ts tests/contracts.test.ts tests/api-routes.test.ts
```

Expected:

```text
Test Files  5 passed (5)
Tests  47 passed (47)
```

- [ ] **Step 3: Verify the root repo is the only active worktree**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" status --short --branch
Test-Path "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\.git"
```

Expected:

```text
## feature/mt5-rollout-enablement...origin/feature/mt5-rollout-enablement [ahead <n>]
False
```

- [ ] **Step 4: Verify app generated outputs are still ignored**

Run:

```powershell
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" check-ignore -v external/mitemshub-indices/.env.local
git -C "c:\Users\USER\Desktop\Projects\Synthetic Indices Bot" check-ignore -v external/mitemshub-indices/.next
```

Expected:

```text
.gitignore:<line>:external/mitemshub-indices/.env.local external/mitemshub-indices/.env.local
.gitignore:<line>:external/mitemshub-indices/.next/ external/mitemshub-indices/.next
```

- [ ] **Step 5: Commit the final verified normalization state**

```bash
git add .gitignore README.md external/mitemshub-indices
git commit -m "chore: normalize workspace into one monorepo"
git push origin feature/mt5-rollout-enablement
```

