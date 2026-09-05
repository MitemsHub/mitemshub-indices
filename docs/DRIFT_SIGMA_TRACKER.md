# Drift-vs-Σ Tracker — Pre-Registration (frozen 2026-09-05, 00:20, pre-execution)

**Status: REGISTERED → EXECUTED same pass. Verdict: CLOSED (1/3 criteria
passed). No EA integration. The tracker does NOT earn an input.**
Artifacts: `artifacts/drift_sigma/tracker_validation.json`, `hourly_tracker.csv`.

---

## Addendum — outcome (recorded 2026-09-05, after the single execution pass)

**K1 (predictiveness) — FAIL, and the sign inverted.** Quintile means of
next-hour aligned drift by |score|: not monotone (all ≈ 0 to 4 decimals);
daily top-minus-bottom spread mean ≈ −0.0000σ with **t = −1.90** (wrong
sign — high-conviction hours predicted *worse* forward drift);
Spearman(\|score\|, aligned drift) = **−0.056**. Reading: the EWMA drift
estimate **mean-reverts** — hours that just trended hard tend to give the
gain back, not extend it. The tracker as designed carries no positive
predictive power; it carries weak *anti*-predictive power.

**K2 (economic gating) — FAIL per the frozen bar.** Base reproduced the
published run exactly (+13.23R / 135). Median-conviction gating kept 72
trades (+9.73R) and blocked 63 (+3.50R) → D = +6.23R with better per-trade
expectancy (0.135R vs 0.056R) — but t = 0.57 (< 1.0) and worst fold −5.83R
(< −1.0). Fails two of three registered requirements. Recorded, not fished:
the gate removed more bad than good on average, far too noisily to clear
the bar. Closed.

**K3 (vol forecast) — PASS, decisively.** Tick-EWMA σ beat M15 ATR(14) at
forecasting next-hour realized vol on all 716 evaluable hours: RMSE
0.000245 vs 0.001877 (**7.7× better**), MAE 0.000154 vs 0.001838 (11.9×).
Caveat noted honestly: the EWMA and the realized target both live on the
σ₂ process (shared-scale advantage), while ATR is a range-based proxy with
a built-in ~20% overstatement — the true forecast-skill gap is smaller than
7.7×, but the direction is unambiguous.

**Verdict rule applied**: 1 of 3 → **CLOSED. No rebuild without a genuinely
new mechanism.** The one live thread this study legitimately leaves: K1's
inversion (drift mean-reversion) is a *different* mechanism — a fade-the-drift
confidence, not a follow-the-drift one. It may be re-registered only as a new
protocol with fresh criteria, and after this document's closure.

**EA consequence**: none. The v26.35 engine, the certified config, and the
paper A/B are untouched. The M15 regime layer (H1 EMA classification +
ATR-percentile gates + GARCH) remains the validated intelligence layer.

## Motivation (written before execution)

The generator fingerprint (docs/GENERATOR_FINGERPRINT.md) proved the V75
step engine is memoryless at tick scale — but its **controller** (the slow
drift-vs-σ state) is the one genuinely evolving quantity. Hypothesis: the
ratio **µ₂/σ₂** — expected drift per 2s step over the coming hour, in units
of per-step σ, measured from the tick stream — separates "trending hours"
(the pullback engine's food) from "dead chop" better than bar-derived
features, because it sees the raw step process directly. This tracker is
the candidate next intelligence layer; it must EARN an EA input.

## Test data (frozen)

- `artifacts/data/volatility_75_index_ticks_20260707_20260803.csv` (Jul 7 → Aug 2)
- `artifacts/data/volatility_75_index_ticks_20260803_20260902.csv` (Aug 3 → Sep 2)
- M15/H1 bars: `artifacts/v75_replay/` — the tracker runs on ticks; bars are
  used ONLY for (a) the incumbent ATR forecaster it must beat, and (b) the
  K2 strategy replay (existing certified engine, untouched).
- Early July (pre-Jul-7) has no tick archive: the K1/K2 evaluation period is
  exactly Jul 7 → Sep 2, 2026 (~58 days, ~2750 hours).

## The tracker (frozen spec)

Estimated strictly causally on the 2s step stream, per timestamp t:
- **σ₂(t)**: EWMA std of the last N=1800 steps (1 hour) of 2s log-returns.
- **µ₂(t)**: EWMA mean of the same window (signed drift per step).
- **score(t) = µ₂(t) / σ₂(t)** (dimensionless, signed). Long-window
  normalization uses expanding history; no future data touches t.
- Session aggregate: score sampled at each hour boundary; direction = sign,
  conviction = |score| percentile vs trailing 30 days of the same hour.
- EA integration shape (if validated): feed `conviction ∈ [0,100]` +
  `drift_sign` as INPUTS ONLY (gating/throttle multiplier), never as a
  standalone entry signal.

## Kill/adopt criteria (all pre-registered; fold-paired deltas are PRIMARY)

- **K1 (predictive?):** does |score| at hour start predict the SIGNED drift
  of the following hour (µ over next 1800 steps, in σ units)? Test: rank
  correlation + quintile spread (top |score| quintile mean signed drift vs
  bottom), with sign aligned. REQUIREMENT: monotone quintile ordering AND
  t ≥ +2.0 on the aligned spread across ~58 daily blocks.
- **K2 (economic?):** gating the certified TP-1.8 engine by the score —
  take signals only when conviction ≥ median (arm `gated`) vs never gating
  (arm `base`, must reproduce +13.23R/135 exactly). Fold-paired deltas over
  8 folds; REQUIREMENT: D = gated − base ≥ +1.5R AND fold-mean t ≥ +1.0 AND
  no fold worse than −1.0R.
- **K3 (vol forecast?):** tick-EWMA σ₂ aggregated to the hour must beat the
  incumbent M15 ATR(14) at forecasting next-hour realized vol: lower RMSE
  AND lower MAE on ~1350 hour pairs (one series each, no free parameters
  tuned on the test window).
- **Adoption bar:** ALL of K1, K2, K3 must pass for any EA integration.
  Two of three → keep-collecting, re-register later. Fewer → CLOSED, no
  rebuild without genuinely new mechanism.

## Integrity rules

Single execution pass per test; no parameter shopping; every number reported
even when ugly; artifacts under `artifacts/drift_sigma/`; any EA change is a
separate, later step gated on this document's verdict.
