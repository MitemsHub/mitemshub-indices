# Monorepo Normalization Design

## Purpose

This design defines how to normalize the current workspace into one true monorepo so the Python engine and the Next.js operator app behave as one project in daily work.

The goal is not to redesign the product architecture. The goal is to remove the accidental nested Git boundary that currently makes one project behave like two separate repositories.

## Core Requirement

The operator wants the project normalized because the engine and the app are part of the same system and should be managed that way.

That means the normalized setup must:

1. use one Git repository for the whole project
2. keep both the Python engine and the operator app inside that one repository
3. preserve the current working app and engine paths unless a path change is necessary
4. avoid destructive history rewriting
5. keep the local startup flow working after normalization

## Current Problem

The current workspace contains two independent Git repositories:

1. the root engine repository at `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot`
2. the nested app repository at `external/mitemshub-indices`

That creates several problems:

1. one project appears clean or dirty in two different places
2. commits and pushes must be done twice
3. the root `.gitignore` currently hides `external/` broadly instead of letting the root repo own the app directly
4. the local structure says "same project" while the Git structure says "separate projects"
5. future changes to app and engine can drift apart operationally even when they belong to one feature

## Scope

This design covers:

1. converting the workspace into a single monorepo
2. removing the nested app Git boundary
3. updating root ignore rules so the root repo owns the app source directly
4. preserving current app file paths during the normalization pass
5. documenting the new source-of-truth workflow

## Non-Goals

This design does not cover:

1. moving the app out of `external/mitemshub-indices` during this pass
2. rewriting or squashing old history
3. rebasing or force-pushing published branches
4. changing app runtime behavior
5. changing engine logic
6. changing the launcher port or startup behavior
7. redesigning deployment strategy

## Approaches Considered

### Option 1: Single Monorepo Without Path Relocation

Keep the app at `external/mitemshub-indices`, but remove its internal `.git` directory so the root repository owns it as a normal folder.

Pros:

- lowest-risk normalization path
- keeps launcher, docs, and bridge assumptions stable
- gives one repository immediately without unnecessary file churn

Cons:

- the app remains under `external/`, which is slightly less clean than a flatter top-level layout
- old app history remains separate in GitHub rather than being merged into the root history

### Option 2: Single Monorepo With Immediate App Relocation

Remove the nested Git boundary and also move the app files to a new top-level directory such as `apps/operator-web`.

Pros:

- cleaner final folder layout
- more explicit monorepo semantics

Cons:

- much higher change surface
- more likely to break scripts, env references, docs, and bridge assumptions
- mixes repo normalization with path refactoring

### Option 3: Keep Separate Repositories But Formalize Them

Convert the nested repo into a submodule or continue with two coordinated repositories.

Pros:

- preserves repository independence
- avoids touching the nested `.git` boundary

Cons:

- does not satisfy the operator requirement for one project
- keeps the double-commit and double-push workflow
- continues the exact confusion that caused this request

## Selected Approach

Use Option 1: Single Monorepo Without Path Relocation.

This is the right choice because it solves the actual problem directly:

1. one repository becomes responsible for the whole system
2. app and engine remain in their already working locations
3. launcher scripts, bridge paths, and docs need only small updates
4. the change is structural but controlled

## Target End State

After normalization:

1. the root repository is the only active Git repository in the workspace
2. `external/mitemshub-indices` is a normal tracked folder inside the root repository
3. the nested app `.git` directory no longer exists
4. the root `.gitignore` ignores only app runtime outputs and secrets, not the whole `external/` tree
5. all future commits for engine and app happen from the root repository

## File Ownership Model

The root repository should own all of the following as ordinary tracked content:

1. app source under `external/mitemshub-indices/src`
2. app routes under `external/mitemshub-indices/app`
3. app tests under `external/mitemshub-indices/tests`
4. app scripts such as launcher and stop scripts
5. app package metadata and config files
6. engine source, tests, docs, and scripts already in the root repository

The root repository should ignore app-only generated files such as:

1. `external/mitemshub-indices/node_modules/`
2. `external/mitemshub-indices/.next/`
3. `external/mitemshub-indices/.data/`
4. `external/mitemshub-indices/.env.local`
5. app-local logs, coverage, and preview artifacts where appropriate

## Migration Design

### Step 1: Freeze The Recovery Points

Before normalization starts, record the current published commits:

1. root branch commit for `feature/mt5-rollout-enablement`
2. nested app `main` commit

These are recovery anchors only. They should not be rewritten or deleted during normalization.

### Step 2: Remove The Nested Git Boundary

The nested app `.git` directory should be removed locally so `external/mitemshub-indices` becomes a normal directory.

This must be done only after confirming:

1. the nested app branch has already been pushed
2. the root branch has already been pushed
3. both local worktrees are clean

This step changes repository ownership, not application code.

### Step 3: Update Root Ignore Rules

The root `.gitignore` should stop ignoring `external/` broadly.

Instead, it should ignore only generated and secret paths inside the app. The root repository must be able to see and track the app source tree after the boundary is removed.

### Step 4: Stage The App Into The Root Repo

Once the nested `.git` is gone and root ignore rules are corrected, the root repository should stage the app files as normal tracked files.

This normalization commit should be structural and explicit. It should not be mixed with unrelated product logic changes.

### Step 5: Update Documentation

Documentation should be updated so the project describes itself as one monorepo.

At minimum, update:

1. root `README.md`
2. app `README.md`
3. any launcher or bridge instructions that imply the app is a separate repository

The new wording should make it clear that:

1. the app lives inside the same project
2. the root repo is the source of truth
3. future commits should be done from the root repo only

## History Strategy

This design deliberately does not merge Git histories.

The old nested app repository history remains available in the previously pushed remote branch history, but the normalized monorepo becomes the active future line of development.

This is preferable because:

1. it avoids risky history surgery
2. it preserves the already-published recovery anchors
3. it achieves operational simplicity immediately

## Remote Strategy

After normalization:

1. the root repository remains connected to the shared GitHub remote
2. the normalized monorepo branch becomes the only branch used for future project work in this workspace
3. the old nested app remote history is left untouched as legacy reference only

No force-push or destructive remote cleanup is part of this pass.

## Safety Rules

### No Path Churn In This Pass

Do not move the app out of `external/mitemshub-indices` during normalization.

That can be considered later, but mixing ownership normalization with a path relocation adds avoidable risk.

### No History Rewriting

Do not:

1. rebase published normalization anchors
2. force-push
3. rewrite old app history into the root repository

### No Secret Regression

The normalized root `.gitignore` must continue to protect:

1. app `.env.local`
2. app build output
3. runtime-generated artifacts
4. root-generated artifacts already intended to stay local

### No Startup Regression

Launcher scripts, local bridge assumptions, and documentation must still work after normalization.

The repo boundary must disappear without changing the verified local operator flow.

## Testing

The meaningful verification for this normalization is:

1. confirm the root repository sees app source files after the nested `.git` is removed
2. confirm app generated files remain ignored
3. confirm `git status` at the root is clean after the normalization commit
4. rerun the focused Python tests already used for the MT5 and guardian changes
5. rerun the focused app tests already used for guardian and loading-counter behavior
6. verify launcher and README instructions still match the actual normalized layout

## Acceptance Criteria

This design is complete when all of the following are true:

1. the workspace contains only one active Git repository for daily development
2. `external/mitemshub-indices` is tracked by the root repository as a normal folder
3. the nested app `.git` directory has been retired locally
4. the root `.gitignore` no longer hides the app source tree
5. app secrets and generated outputs remain ignored
6. both focused Python and app verification passes remain green after normalization
7. the documentation clearly states that the project is now a single monorepo
