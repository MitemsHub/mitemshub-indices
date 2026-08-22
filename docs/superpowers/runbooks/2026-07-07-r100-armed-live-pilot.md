# R_100 Armed-Live Pilot Runbook

## Objective

Run the first supervised armed-live pilot on `R_100` only after fresh read-only readiness evidence is collected and reviewed.

This runbook is fail-closed. If any readiness check or supervision gate fails, stop and do not continue into armed-live.

## Prerequisites

- MT5 terminal is installed and reachable.
- MT5 login, password, and server are available.
- The venue symbol is confirmed as `Volatility 100 Index`.
- The latest rollout artifact is written to `artifacts/rollout_preflight_r100.json`.
- The operator has reviewed the session record template before the live session starts.

## Step 1: Refresh Read-Only Rollout Evidence

Run:

```bash
python -m synthetic_trader.cli mt5-rollout-check --symbol R_100 --live-mode dry-run-live --mt5-server "$env:MT5_SERVER" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-symbol "Volatility 100 Index" --artifact-output artifacts/rollout_preflight_r100.json
```

Pass criteria:

- `rollout_readiness_ok=True`
- `rollout_symbol=R_100`
- `rollout_live_mode=dry-run-live`
- no unresolved readiness failures

Stop if:

- MT5 runtime is not ready
- venue symbol mapping is wrong
- the artifact file is not written

## Step 2: Optional Bounded Dry-Run Validation

Use this when you want one more supervised read-only/live-routing sanity pass before armed-live.

Run:

```bash
python -m synthetic_trader.cli paper-live --symbol R_100 --live-mode dry-run-live --venue mt5 --duration-sec 120 --journal journals/mt5_analytics_r100_preflight.jsonl --mt5-server "$env:MT5_SERVER" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" --mt5-symbol "Volatility 100 Index"
```

Pass criteria:

- session exits cleanly
- journal file is written
- no MT5 sync failures are reported

Stop if:

- session errors
- symbol mapping mismatch appears
- any unexpected live-order path is attempted

## Step 3: Review Evidence

Confirm the following before armed-live:

- `artifacts/rollout_preflight_r100.json` exists and matches `R_100`
- `journals/mt5_analytics_r100_preflight.jsonl` exists if Step 2 was run
- the session record is filled out
- operator stop conditions are reviewed and accepted

## Step 4: Armed-Live Pilot

Proceed only after all prior steps pass.

1. **Refresh the armed-live preflight WITH the explicit consent flag** (read-only;
   this is what records the operator's consent in the artifact):

   ```bash
   python -m synthetic_trader.cli mt5-rollout-check --symbol R_100 --live-mode armed-live --armed-live \
     --mt5-server "$env:MT5_SERVER" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" \
     --mt5-symbol "Volatility 100 Index" --artifact-output artifacts/rollout_armed_r100.json
   ```

   Pass criteria: the preflight **exits 0** AND the artifact records
   `rollout_readiness_ok=True` AND `rollout_armed_confirmation=True` with no
   `missing_armed_confirmation` in `rollout_readiness_failures`.  The command
   exits `1` with `rollout_exit=1 fail_closed=armed-live-readiness-failed`
   when the armed gate is not ready (missing `--armed-live` consent or the
   MT5 runtime not ready) — treat any nonzero exit as a STOP, never proceed
   on a stale or non-consenting artifact.  Consent must be explicit and
   recorded, never implied by `--live-mode armed-live` alone.

2. **Run the bounded supervised armed-live session** (same flag; `paper-live`
   exits nonzero before any order path if the armed gate fails):

   ```bash
   python -m synthetic_trader.cli paper-live --symbol R_100 --venue mt5 --live-mode armed-live --armed-live \
     --duration-sec <bounded> --journal journals/mt5_analytics_r100_armed.jsonl \
     --mt5-server "$env:MT5_SERVER" --mt5-login "$env:MT5_LOGIN" --mt5-password "$env:MT5_PASSWORD" \
     --mt5-symbol "Volatility 100 Index"
   ```

Recommended pilot shape:

- symbol: `R_100`
- one supervised session
- bounded duration
- operator present for the full session
- fail-closed on any sync or symbol anomaly
- the session record must note the `--armed-live` confirmation and the
  artifact's `armed_confirmation=True` line

## Hard Stop Conditions

Stop immediately if any of the following happens:

- MT5 runtime becomes not ready
- venue symbol mismatches expected `Volatility 100 Index`
- unexpected open position state appears
- sync failures appear in MT5 analytics
- operator confidence in the session state drops below “fully understood”

## Evidence To Keep

- `artifacts/rollout_preflight_r100.json`
- `journals/mt5_analytics_r100_preflight.jsonl` if generated
- completed `docs/superpowers/templates/r100-armed-live-session-record.md`
