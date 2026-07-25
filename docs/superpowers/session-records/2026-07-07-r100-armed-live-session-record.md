# R_100 Armed-Live Session Record

- Date: 2026-07-07
- Operator: USER
- Symbol: `R_100`
- Venue symbol: `Volatility 100 Index`
- MT5 terminal path: `C:\Program Files\MetaTrader 5 Terminal\terminal64.exe`
- Rollout artifact: `artifacts/rollout_preflight_r100.json`
- Armed-live rollout artifact: `artifacts/rollout_armed_r100.json`
- Dry-run journal: `journals/mt5_analytics_r100_preflight.jsonl`

## Readiness Checks

- [x] MT5 runtime reachable via direct runtime check for `R_100`
- [x] Venue symbol mapping verified as `Volatility 100 Index`
- [x] Read-only rollout artifact reviewed
- [x] Fail-closed stop conditions reviewed
- [ ] Armed-live confirmation provided

## Dry-Run Results

- Live mode: `dry-run-live`
- Warmup ticks: `5000`
- Live ticks: `60`
- Signals: `2`
- Approved signals: `1`
- Rejected signals: `1`
- Closed trades: `1`
- Shutdown closed trades: `1`
- Open positions before shutdown: `1`
- Unresolved positions: `0`
- Session resets: `0`
- Finalized: `True`
- Final equity: `1001.33`
- Model version: `online-logistic-v1.1`

## Armed-Live Preflight

- Rollout stage: `armed-live-preflight`
- Readiness ok: `False`
- Readiness failures: `missing_armed_confirmation`
- Positions: `0`
- MT5 sync failures: `[]`

## Stop Conditions

- [x] MT5 sync failure
- [x] symbol mismatch
- [x] unexpected open position state
- [x] operator abort

## Outcome

- Result: `R_100` read-only preflight and bounded MT5 dry-run completed successfully; armed-live preflight remained fail-closed because operator armed confirmation was not provided.
- Notes:
  - `mt5-rollout-check` dry-run artifact was written successfully.
  - Direct runtime check returned `ready=True` for `R_100`.
  - `mt5-monitor` did not surface runtime readiness because the dry-run journal does not currently include a standalone runtime summary record for that report path.
  - No live trade was initiated from this interface.
- Evidence files kept:
  - `artifacts/rollout_preflight_r100.json`
  - `artifacts/rollout_armed_r100.json`
  - `journals/mt5_analytics_r100_preflight.jsonl`
