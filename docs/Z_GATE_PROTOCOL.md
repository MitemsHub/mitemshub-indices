# Z-Gate Protocol — Pre-Registration (v1, frozen 2026-09-04)

**Status: REGISTERED → EXECUTED same day. Phase A verdict: NOT VALIDATED
(PRIMARY tertile-keep failed W1–W5; addendum below).** This document is the
contract; the implementation (`scripts/z_gate_phaseA.py`) executes it without
discretion. Any later edit invalidates the registration and must be recorded
as a new protocol version.

---

## Addendum — Phase A outcome (recorded 2026-09-04, after execution)

Calibration (2024-08 .. 2025-07, 720 PB trades): PRIMARY cleared the pre-bar
(keep 240tr +0.125R vs veto 480tr −0.038R, gap +0.163; C1–C3 pass). Edges
frozen: |z| ∈ (0.420, 1.240]. Validation (2025-08 .. 2026-01, one shot, 170
PB trades): gap **−0.14** — the vetoed bucket (+0.159R) beat the kept bucket
(+0.017R); kept fraction 25%; keeping mid-z trades cost −12.88R (seg 1) and
−7.35R (seg 2) against trading everything; W1–W5 all false.
**NOT VALIDATED, final for this generation.** The sign flip across windows
(calibration +0.163 vs validation −0.14) means the mid-z "effect" is
window-luck, not mechanism. Per §6: no further historical |z| gate study is
permitted without a new mechanism hypothesis or substantially more live data.
Descriptive corroboration, not a criterion: the *base strategy* scored
+20.98R over the validation window — the tp18 family has now tested positive
on two disjoint ~7-month spans (Aug 2025–Jan 2026 and Feb–Sep 2026).

---

## 1. Hypothesis and provenance (honest history of every prior look)

The candidate gate: **keep pullback trades only when the signal-time GARCH
z-extent |z| sits in the mid range — skip both tails** (over-extended chases
and dead-calm churn). Prior evidence, in order:

| Look | Data | Result | Status |
|---|---|---|---|
| v2 calibration (Feb–Jun 2026) | 283 PB trades | mid-tertile +0.203R vs tails −0.032R | fitting — spent |
| v2 validation (Jun–Sep 2026) | 90 PB trades | chosen median gate +0.072R vs vetoed −0.005R, but deleted 56% for +0.3R total | economics fail — spent |
| v3 interim (full Feb–Sep 2026) | 440 PB trades | mid-tertile gap +0.129 in-sample; **+0.316 on the clean-OOS validation folds** | descriptive — window now burned for z-questions |

**The Feb–Sep 2026 window is therefore unusable for fitting or validation of
any z-rule.** It may be reported only as descriptive context. The only clean
test left in history is **pre-2026 data**, which no z-analysis has touched.

## 2. Phase A — fresh historical test (the only look)

**Data**: broker V75 M15/H1 bars 2024-08-01 .. 2026-01-31 (18 months,
~25.9k bars), pulled to `artifacts/z_gate/`. Zero overlap with the burned
window. Burn-in 480 bars as always.

**Base config**: the deployed tp18 (tp_mult 1.8, no static filters), full
governor, $200, honest stop booking — identical to the certified V75 config.

**Gate form (committed before Phase A data is seen)**:
- PRIMARY: mid-tertile keep. Edges = the 33.3rd and 66.7th percentiles of
  |z| over all calibration-window PB signal times. Keep iff `z_lo < |z| ≤ z_hi`.
- FALLBACK (evaluated only if PRIMARY fails the calibration pre-bar §3):
  median-split keep (`|z| ≤ median`). One fallback, chosen now, not after
  peeking at validation.

## 3. Calibration pre-bar (on the calibration half: 2024-08 .. 2025-07)

The PRIMARY form proceeds to validation only if ALL hold:
- C1: kept-mean − vetoed-mean gap ≥ **+0.15 R/trade**
- C2: ≥ **120** calibration PB trades in the kept bucket (enough signal)
- C3: ≥ **120** trades in the vetoed bucket (the gate actually gates)

If PRIMARY fails, FALLBACK is fitted by the same rule and must clear the same
bar. If both fail: **NO GATE — final for this protocol generation**. The
validation window is not spent (one-look rule).

## 4. Validation (one shot, on 2025-08 .. 2026-01, six months)

Segmented for fold-consistency (the rounds-1/2 lesson): two 3-month segments;
the gate must contribute in both.

- W1: validation gap (kept-mean − vetoed-mean) ≥ **+0.15 R/trade**
- W2: economics in TOTAL R — kept_total ≥ all_trades_total + **1.5R**
      (the gate must beat doing nothing on the same signals, not just
      improve per-trade cosmetics)
- W3: kept fraction ≥ **30%** of signals (a gate that refuses to trade is
      not a gate)
- W4: segment consistency — kept_total − all_total ≥ 0 in **both** segments
- W5: worst segment contribution ≥ **−0.5R**

**Verdicts**: all five → `HISTORICAL-CANDIDATE` (frozen edges + this
document go to Phase B). Any failure → `NOT VALIDATED`, final; no re-fit, no
re-run, no third form. The Feb–Sep 2026 window may then be reported once as
descriptive corroboration only.

## 5. Phase B — paper replication (registered now, executed later)

Runs only if Phase A validates. Threshold and edges are **frozen from Phase
A calibration** — never re-fit.

- P1: ≥ **100** closed arm-A paper PB trades spanning ≥ **21 days**
- P2: `reconcile_paper_ticks.py` verdict for the same window is **MATCHED**
      (drift invalidates the test before statistics are read)
- P3: paper gap (kept − vetoed) ≥ **+0.08 R/trade** (live-friction discount)
- P4: kept_total ≥ all_total on paper (live economics)

All four → design EA input (`InpZGate`, edges as inputs), run its own 26-fold
walk-forward as a regression guard, and only then a separate paper A/B arm.
**Never auto-deployed.**

## 6. Multiple-comparisons statement

This is the third generation of z-analysis (v2, v3-interim, this). The design
 neutralizes the earlier looks by using strictly fresh data for both fitting
and validation, committing the gate form now, and allowing exactly one
validation evaluation. If Phase A fails, no further historical gate study on
|z| is permitted without (a) a new mechanism hypothesis or (b) substantially
more live data — threshold archaeology on the same bars is banned.
