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

Recommended pilot shape:

- symbol: `R_100`
- one supervised session
- bounded duration
- operator present for the full session
- fail-closed on any sync or symbol anomaly

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
