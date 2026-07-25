# MT5 Supervised Rollout Runbook

## Purpose

This runbook defines the exact operator flow for the MT5-first supervised rollout using `dry-run-live` as the first live gate.

## Preflight

1. Confirm the latest validation artifact exists.
2. Run `mt5-rollout-check`.
3. Confirm `rollout_readiness_ok=True`.
4. Confirm `rollout_validation_finalized=True`.
5. Confirm `rollout_mt5_runtime_ready=True`.
6. Confirm no unresolved stop condition is active before session start.

## Dry-Run Session

Run:

```bash
python -m synthetic_trader.cli mt5-rollout-check --symbol R_75 --live-mode dry-run-live --mt5-server <server> --mt5-login <login> --mt5-password <password> --mt5-symbol "Volatility 75 Index" --validation-json artifacts/validation_r75.json --journal journals/mt5_analytics.jsonl
python -m synthetic_trader.cli paper-live --symbol R_75 --venue mt5 --live-mode dry-run-live --mt5-server <server> --mt5-login <login> --mt5-password <password> --mt5-symbol "Volatility 75 Index"
python -m synthetic_trader.cli mt5-monitor --journal journals/mt5_analytics.jsonl --symbol R_75
```

## Pass Criteria

1. Readiness remains healthy.
2. Monitor output remains explainable.
3. No unresolved lifecycle state appears.
4. Operator records a clear pass or fail decision at session end.

## Stop Conditions

1. Any readiness failure.
2. Any MT5 runtime inconsistency.
3. Any ambiguous lifecycle result.
4. Any operator uncertainty about current state.
