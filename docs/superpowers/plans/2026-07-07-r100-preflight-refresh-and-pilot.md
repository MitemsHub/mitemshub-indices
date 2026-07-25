# R_100 Preflight Refresh + Armed-Live Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `R_100` readiness refresh repeatable by writing rollout snapshot artifacts and shipping a fail-closed armed-live pilot runbook plus session record template.

**Architecture:** Reuse the existing `mt5-rollout-check` and `paper-live` surfaces instead of inventing a new workflow. Add a small optional artifact-output path to `mt5-rollout-check`, then create two docs: a runbook for the supervised pilot and a structured template for recording operator confirmations, pass/fail checks, and outcomes.

**Tech Stack:** Python 3.11+, `json`, `pathlib`, `unittest`

---

## File Structure

- `src/synthetic_trader/cli.py`
  - Optionally writes the rollout snapshot JSON to a caller-provided artifact path.
- `tests/test_phase16_supervised_rollout.py`
  - Adds focused CLI coverage for artifact file output.
- `docs/superpowers/runbooks/2026-07-07-r100-armed-live-pilot.md`
  - Defines the supervised pilot checklist and stop conditions.
- `docs/superpowers/templates/r100-armed-live-session-record.md`
  - Defines the operator session record template.

### Task 1: Lock Rollout Artifact Output Into A Failing Test

**Files:**
- Modify: `tests/test_phase16_supervised_rollout.py`
- Test: `tests/test_phase16_supervised_rollout.py`

- [ ] **Step 1: Write the failing CLI test for `--artifact-output`**

```python
def test_mt5_rollout_check_writes_snapshot_artifact(self) -> None:
    import contextlib
    import io
    import json
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    from synthetic_trader.cli import main
    from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

    runtime_status = Mt5RuntimeStatus(
        ready=True,
        failures=(),
        venue_symbol="Volatility 100 Index",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "rollout_preflight_r100.json"
        output = io.StringIO()
        with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
            with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "mt5-rollout-check",
                            "--symbol",
                            "R_100",
                            "--live-mode",
                            "dry-run-live",
                            "--mt5-server",
                            "server",
                            "--mt5-login",
                            "123456",
                            "--mt5-password",
                            "secret",
                            "--mt5-symbol",
                            "Volatility 100 Index",
                            "--artifact-output",
                            str(artifact_path),
                        ]
                    )

        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["symbol"], "R_100")
        self.assertEqual(payload["venue"], "mt5")
        self.assertTrue(payload["readiness_ok"])
```

- [ ] **Step 2: Run the focused rollout test to verify it fails**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py::Phase16RolloutCliTests::test_mt5_rollout_check_writes_snapshot_artifact -v`
Expected: FAIL because `mt5-rollout-check` has no `--artifact-output` argument and does not write a file.

- [ ] **Step 3: Commit the red test**

```bash
git add tests/test_phase16_supervised_rollout.py
git commit -m "test: cover rollout artifact output"
```

### Task 2: Add Artifact Output To `mt5-rollout-check`

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Test: `tests/test_phase16_supervised_rollout.py`

- [ ] **Step 1: Add the optional parser argument**

```python
    mt5_rollout_check.add_argument("--artifact-output", help="optional rollout snapshot JSON output path")
```

- [ ] **Step 2: Write the snapshot JSON when the flag is supplied**

```python
        snapshot = build_rollout_status_snapshot(
            venue=Venue.MT5.value,
            symbol=args.symbol,
            live_mode=mode.value,
            readiness_ok=readiness.ready,
            readiness_failures=readiness.failures,
            validation_snapshot=validation_snapshot,
            mt5_snapshot=mt5_snapshot,
        )
        print(render_rollout_status_text(snapshot))
        if args.artifact_output:
            dump_json_file(args.artifact_output, snapshot)
        return 0
```

- [ ] **Step 3: Run the focused rollout artifact test**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py::Phase16RolloutCliTests::test_mt5_rollout_check_writes_snapshot_artifact -v`
Expected: PASS

- [ ] **Step 4: Commit the artifact-output support**

```bash
git add src/synthetic_trader/cli.py tests/test_phase16_supervised_rollout.py
git commit -m "feat: export mt5 rollout snapshot"
```

### Task 3: Add The R_100 Armed-Live Pilot Runbook

**Files:**
- Create: `docs/superpowers/runbooks/2026-07-07-r100-armed-live-pilot.md`

- [ ] **Step 1: Write the runbook with explicit prerequisites and commands**

```markdown
# R_100 Armed-Live Pilot Runbook

## Objective

Run the first supervised armed-live pilot on `R_100` only after fresh read-only readiness evidence is collected.

## Prerequisites

- MT5 terminal reachable
- `R_100` symbol configured and mapped to the correct venue symbol
- latest rollout artifact present at `artifacts/rollout_preflight_r100.json`
- operator confirms fail-closed supervision

## Step 1: Refresh rollout evidence

```bash
python -m synthetic_trader.cli mt5-rollout-check --symbol R_100 --live-mode dry-run-live --mt5-server "$env:MT5_SERVER" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-symbol "Volatility 100 Index" --artifact-output artifacts/rollout_preflight_r100.json
```

PASS:
- `rollout_readiness_ok=True`
- no unresolved readiness failures

STOP IF:
- MT5 runtime is not ready
- venue symbol mapping is incorrect

## Step 2: Optional bounded dry-run-live validation

```bash
python -m synthetic_trader.cli paper-live --symbol R_100 --live-mode dry-run-live --venue mt5 --duration-sec 120 --journal journals/mt5_analytics_r100_preflight.jsonl --mt5-server "$env:MT5_SERVER" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-symbol "Volatility 100 Index"
```

## Step 3: Armed-live pilot

Run only after the operator completes the session record and confirms stop conditions.
```
```

- [ ] **Step 2: Save the runbook exactly at the planned path**

No command needed beyond writing the file.

- [ ] **Step 3: Commit the runbook**

```bash
git add docs/superpowers/runbooks/2026-07-07-r100-armed-live-pilot.md
git commit -m "docs: add r100 armed live pilot runbook"
```

### Task 4: Add The Session Record Template

**Files:**
- Create: `docs/superpowers/templates/r100-armed-live-session-record.md`

- [ ] **Step 1: Write the session record template**

```markdown
# R_100 Armed-Live Session Record

- Date:
- Operator:
- Symbol: `R_100`
- Venue symbol:
- MT5 terminal path:
- Rollout artifact:
- Dry-run journal:

## Readiness Checks

- [ ] MT5 runtime ready
- [ ] Venue symbol mapping verified
- [ ] Rollout artifact reviewed
- [ ] Fail-closed stop conditions reviewed

## Pilot Configuration

- Live mode:
- Max duration:
- Journal path:
- Stop-loss policy:
- Position sizing confirmation:

## Stop Conditions

- [ ] MT5 sync failure
- [ ] symbol mismatch
- [ ] unexpected open position state
- [ ] operator abort

## Outcome

- Result:
- Notes:
- Evidence files kept:
```

- [ ] **Step 2: Save the template at the planned path**

No command needed beyond writing the file.

- [ ] **Step 3: Commit the session template**

```bash
git add docs/superpowers/templates/r100-armed-live-session-record.md
git commit -m "docs: add r100 session record template"
```

### Task 5: Verification

**Files:**
- Modify: `src/synthetic_trader/cli.py`
- Modify: `tests/test_phase16_supervised_rollout.py`
- Create: `docs/superpowers/runbooks/2026-07-07-r100-armed-live-pilot.md`
- Create: `docs/superpowers/templates/r100-armed-live-session-record.md`

- [ ] **Step 1: Run the rollout test module**

Run: `python -m pytest tests/test_phase16_supervised_rollout.py -v`
Expected: PASS

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 3: Manually inspect the docs for exact command paths and stop conditions**

Check:
- runbook commands use `R_100`
- artifact path is `artifacts/rollout_preflight_r100.json`
- template includes operator confirmations and evidence file tracking

- [ ] **Step 4: Commit the verification pass**

```bash
git add src/synthetic_trader/cli.py tests/test_phase16_supervised_rollout.py docs/superpowers/runbooks/2026-07-07-r100-armed-live-pilot.md docs/superpowers/templates/r100-armed-live-session-record.md
git commit -m "test: verify r100 preflight refresh workflow"
```
