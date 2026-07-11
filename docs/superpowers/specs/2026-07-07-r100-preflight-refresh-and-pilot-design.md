# R_100 Preflight Refresh + Armed-Live Pilot Design

## Purpose

This design refreshes read-only `R_100` readiness evidence and produces a supervised armed-live pilot checklist that minimizes the risk of incorrect live execution.

The goal is to ensure that when the system produces a `buy_candidate` / `sell_candidate` decision package, the operator can trust:

- MT5 runtime readiness
- symbol mapping correctness
- fail-closed supervision gates
- clear stop conditions and audit evidence for the first armed-live session

## Scope

This design covers:

1. A read-only preflight refresh run for `R_100` that produces fresh evidence artifacts.
2. A dedicated pilot checklist/runbook for the first supervised armed-live session on `R_100`.
3. Reuse of existing readiness and rollout snapshot builders (`mt5-rollout-check`).

## Non-Goals

- Placing live trades automatically.
- Changing strategy logic, thresholds, or risk policy.
- Expanding symbol coverage beyond configured symbols.
- Adding new monitoring dashboards.

## Current Problem

The system has:

- a shared strategy session (`paper-live`) with execution routing
- MT5 readiness checks
- a rollout preflight surface (`mt5-rollout-check`)

But the operator still needs a single, current, symbol-specific evidence refresh and a checklist that removes ambiguity for the first armed-live trial on `R_100`.

## Design Goals

- Produce fresh, timestamped evidence for `R_100` readiness.
- Keep the preflight strictly read-only (no trade placement).
- Provide an unambiguous supervised pilot checklist with pass/fail rules.
- Use existing CLI surfaces whenever possible to minimize drift.

## Preflight Refresh Design

### Operator-Facing Workflow

The preflight refresh consists of two read-only actions:

1. Run `mt5-rollout-check` for `R_100` in `dry-run-live` mode to confirm readiness and runtime state.
2. Run `paper-live` in `dry-run-live` for a short bounded session (optional) to prove the live session loop still behaves and journaling remains explainable.

### Evidence Outputs

Preflight should produce:

- `journals/mt5_analytics_r100_preflight.jsonl`
- `artifacts/rollout_preflight_r100.json` (captured `mt5-rollout-check` output)
- optional `artifacts/validation_r100_dry_run.json` (captured `paper-live` summary converted to validation snapshot)

The preflight refresh should be repeatable without manual edits.

## Pilot Checklist Design

### Runbook

Create a runbook that defines:

- required prerequisites before running armed-live
- exact commands to run
- pass/fail criteria
- hard stop conditions
- required evidence artifacts to keep

### Session Record Template

Create a session record template to capture:

- date/time
- symbol (`R_100`)
- venue symbol mapping
- readiness summary
- operator confirmations
- outcomes and stop condition triggers

## Implementation Notes

### Prefer Reuse Over New Commands

The codebase already provides:

- `mt5-rollout-check` which prints a rollout snapshot
- `paper-live` with `--venue mt5 --live-mode dry-run-live`
- `mt5-monitor` for reviewing MT5 analytics journals

This design prefers:

- adding a thin wrapper command only if needed to dump `mt5-rollout-check` output to a JSON file
- otherwise using existing commands and focusing changes on:
  - runbook + template
  - standardized artifact paths

## Files

- Modify (optional): `src/synthetic_trader/cli.py`
  - add `--artifact-output` to `mt5-rollout-check` for dumping the rollout snapshot JSON
- Create: `docs/superpowers/runbooks/2026-07-07-r100-armed-live-pilot.md`
- Create: `docs/superpowers/templates/r100-armed-live-session-record.md`

## Testing Strategy

If `--artifact-output` is added:

- add a focused CLI test that:
  - runs `mt5-rollout-check` with a mocked runtime status
  - writes an artifact JSON
  - asserts the artifact contains the rollout snapshot keys

Docs-only changes require no code tests.

## Success Criteria

This design is successful when:

- the operator can refresh `R_100` readiness evidence on demand
- evidence artifacts are written in a consistent location
- the armed-live pilot checklist is explicit and fail-closed
- the process remains strictly supervised and read-only until the operator chooses armed-live
