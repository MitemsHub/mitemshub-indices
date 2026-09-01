# Meta-Labeling Pipeline (P1) — P(win) Size Multiplier

## What this is

A López de Prado-style **meta-labeling** layer for MITEMSHUB_AI:

- The **primary signal** (tick-fade / CB spike detection) already decides *direction*.
- The **meta-model** answers a second question: *"given this context, should this signal be
  taken, and at what size?"* — output as a **P(win) prediction → position size multiplier**.

This maximizes good days/trades without touching the EA's entry engine: the EA stays fluid,
it just bets smaller when context is hostile and full-size when context is favorable.

## Current status (validated against repo data)

- **P0 (close detection + cost accounting + per-symbol state files): DONE in EA (v26.4+).**
- **P1 (this pipeline): prototype built here** — `scripts/meta_labeling_prototype.py`.
- Trained on `data/calibration_outcomes.jsonl` (236 records, 228 with complete outcomes).

### First-run findings

- All 228 valid samples have predictions in the `[0.50, 0.60)` bucket — the current
  calibration model emits near-constant predictions (~0.50), so the table is degenerate
  for now. Buckets `[0.60, 1.00)` fall back to a conservative 0.5× multiplier until
  richer prediction data accumulates.
- Overall baseline: win rate ≈ 66.7%, mean R ≈ +0.98 → baseline Kelly ≈ 0.58.
- The pipeline is correct and will differentiate as the EA logs more varied predictions.

## How it works

```
telemetry JSONL ──► load & filter ──► bucket by P(win) prediction
                                          │
                                          ▼
                     per-bucket: win rate, avg win R, avg loss R
                                          │
                                          ▼
                     fractional Kelly: f* = (p·b − q) / b
                     multiplier = clip(f* / f*_baseline, 0.0, 1.5)
                                          │
                                          ▼
                     data/meta_label_multipliers.json
                                          │
                                          ▼
        EA: actual_risk = InpBaseRisk × multiplier(prediction)
```

## Safety rails

- `MIN_TRADES_PER_BUCKET = 15` — buckets with thin evidence fall back to 0.5×
  (half risk) instead of guessing.
- `MIN_PREDICTION = 0.52` — signals the model doesn't believe in are skipped entirely.
- Multiplier is hard-clipped to `[0.0, 1.5]` — the EA can never bet more than 1.5×
  base risk, and can go to zero on hostile contexts.
- Uses **fractional** Kelly (0.25×) — full Kelly is too volatile for a micro account.

## How the multiplier table feeds back into the EA

1. The EA computes a `prediction` (P(win)) for each candidate signal from context
   features (regime, z, exp-ratio, spike probability, time-of-day, consec-loss state).
2. Before entry, it looks up `multiplier` for that prediction's bucket in
   `data/meta_label_multipliers.json`.
3. Position size = `InpBaseRisk × multiplier`. Prediction < 0.52 → skip.
4. As more telemetry accumulates, re-run the script and refresh the table —
   the loop is: **trade → log → retrain → resize**.

## Usage

```bash
python scripts/meta_labeling_prototype.py          # train + write multiplier table
python scripts/meta_labeling_prototype.py --report # print calibration report
```
