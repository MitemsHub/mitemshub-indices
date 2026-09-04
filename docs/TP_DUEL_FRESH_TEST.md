# TP-Duel Fresh-Data Test — Pre-Registration (frozen 2026-09-04)

**Status: REGISTERED → EXECUTED same day. Verdict: CONFIRMS-TP18-LEAD
(addendum below).** TP 2.4 (legacy) had never been executed on pre-Feb-2026
V75 data in this project; the run below was the first and only look.

---

## Addendum — outcome (recorded 2026-09-04, after execution)

Scored window 2025-08-01 .. 2026-01-31 (~345 trades/arm):
- legacy TP 2.4: **+10.86R** (175 trades)
- tp18: **+20.98R** (170 trades, the published Phase-A figure)
- **D = −10.12R** (≤ −3.0 ✓), fold deltas [−7.71, +4.42, −13.70], **t = −1.06** (≤ −1.0 ✓)
- → **CONFIRMS-TP18-LEAD** per the registered rule. TP 1.8 wins 2/3 folds;
  both arms positive on the window; the preset stays as deployed (TP 1.8);
  the paper A/B proceeds unchanged as the final judge.

Standing duel record: Feb–Sep 2026 (26 folds, ~500 trades): tp18 +52.42R vs
legacy +51.44R — tie. Aug 2025–Jan 2026 (fresh, one-shot): tp18 by +10.12R.
Historical power for this question is now exhausted; paper data is the only
remaining adjudicator, exactly as registered.

## Provenance (every prior look at the duel)

| Look | Data | Result | Status |
|---|---|---|---|
| v26.27 preset rationale | pre-Jul-2026 era | TP 2.4 "OOS-validated" | spent (era lost to the SL-accounting bug; not re-usable) |
| Round-3/4 walk-forward | Feb–Sep 2026 | tp18 +52.42R vs legacy +51.44R (t diff ≈ 0.11σ) | statistical tie — spent |
| z-gate Phase A (tp18 side only) | Aug 2025–Jan 2026 | tp18 +20.98R published as descriptive | tp18 side of this window is seen; **legacy side is virgin** |

**What remains clean**: the *paired difference* (legacy − tp18) on Aug 2025 –
Jan 2026. TP 2.4 has never touched those bars. The tp18 margin (+20.98R) was
published without knowledge of any legacy number for that window, so the
difference is uncontaminated by selection.

## Test spec (frozen before execution)

**Data**: `artifacts/z_gate/` (pulled for Phase A: 2024-07-20 .. 2026-01-31).
Only the sub-window **2025-08-01 .. 2026-01-31** is scored. The earlier
calibration half (2024-08 .. 2025-07) is NOT used for the duel — it feeds no
threshold here, and spending it would leave nothing in reserve.

**Runs**: the full governor, $200, honest booking, identical signals by
construction. Arm 1: `tp_mult=1.8` (already known: +20.98R, n=170).
Arm 2: `tp_mult=2.4` — the one new execution.

**Scoring statistics (computed once)**:
- D  = legacy_total_R − tp18_total_R on the scored window
- Per-fold pairing: 3 × ~2-month folds (Aug–Sep, Oct–Nov, Dec–Jan), delta per fold
- Fold-level t-stat of the paired deltas

## Verdict rule (all pre-registered)

- **CONFIRMS-TP18-LEAD**: D ≤ −3.0R AND t ≤ −1.0 (tp18 clearly ahead again on
  fresh data) → the paper A/B proceeds as planned with TP 1.8 as favorite;
  paper remains the final judge.
- **UPSETS-TO-TIE**: −3.0R < D < +3.0R or |t| < 1.0 → the duel stays a tie at
  all available historical power; the paper A/B becomes the *only* possible
  adjudication (unchanged plan, stronger motivation).
- **UPSETS-TO-LEGACY**: D ≥ +3.0R AND t ≥ +1.0 (legacy clearly ahead on fresh
  data) → the paper A/B proceeds unchanged (it is two-sided by design), but
  the favorite label flips to TP 2.4 and the CHANGELOG records the reversal.
  The deployed preset is NOT touched on historical evidence alone — the
  standing rule "paper data adjudicates" outranks any backtest, including
  this one.

No re-fit, no sub-window shopping, no third window. Whatever D is, it gets
recorded and the protocol closes.

## Multiple-comparisons note

This is the last uncontaminated V75 window in broker history for the TP
question. If the result is a tie, historical testing is exhausted and paper
is the only judge — which the project has said all along. If it is decisive
either way, it still only relabels the favorite; it never flips the preset by
itself.
