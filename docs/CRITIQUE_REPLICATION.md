# Critique Replication — Pre-Registration (frozen 2026-09-05, pre-execution)

**Status: REGISTERED.** An external critique of the project's claims arrived and
made three testable demands (its §5, Tests A–C). This document freezes the
replication protocol *before* any of those statistics are computed. One
execution pass; every number reported, ugly or not.

## Already settled before freeze (factual audit, not new statistics)

These were verified against on-disk artifacts while reading the critique and are
recorded as facts, not outcomes of the registered tests:

1. **Band Fade is not deployed.** `InpUseBandFade=false` in both
   `MitemshubAI_VOL75_FINAL.set` and `MitemshubAI_VOL75_LIVE.set`. The
   CHANGELOG (2026-07 entry) documents why: BF geometry (~22-unit stops) can
   never pass the v26.23 spread gate (18% of stop) against V75's ~18.5-unit
   live spread — 100% of BF entries were vetoed live. The critique's
   "flagship validated edge (PF ~4.2)" refers to `boom_scaled_window_backtest.json`
   — a deleted Crash/Boom artifact, not V75. **Its BF contradiction therefore
   attacks a strategy the EA does not trade.** The general question it raises
   (mean reversion vs random walk) is still tested below as Test A.
2. **Cost-model flaw CONFIRMED.** `certify_v75.py` uses the measured 18.5-unit
   spread only as a veto gate; bar-based fills never pay it in PnL. Corrected
   arithmetic on the existing certified run (computed during this audit,
   before freeze — a correction, not a test): mean stop 575.2 units →
   0.032R/trade cost → **+13.23R gross becomes +8.89R net** over 135 trades
   (per-trade expectancy 0.098R → 0.066R). The edge shrinks by ~⅓ and
   survives; the engine fix is registered as follow-up work.
3. Small-sample caution (critique §4b): accepted in principle and already
   operationalized — this is exactly why the go-live gate demands ≥30 live
   paper trades plus reconciliation, and why the TP duel used fold-paired
   statistics instead of headline totals.

## Registered tests (to be computed after this freeze, in one pass)

### Test A — Variance ratio at long horizons
- **Data**: tick lake, 2.46M ticks, 2026-06-07 → 2026-09-02 (2s grid);
  cross-checked on 19 months of H1 bars (2024-07-20 → 2026-02-01).
- **Statistic**: VR(q) = Var(q-step return) / (q·Var(1-step)), q ∈
  {4, 8, 16, 32, 64, 128, 256} steps. Tick steps = 2s each (q=256 → ~8.5min);
  H1 steps (q=256 → 256h). Overlapping estimator (full sample).
- **Null band**: ±1.96·σ where σ from 500 shuffled-step surrogates (same
  |returns|, random signs) — accounts for fat tails without assuming normality.
- **Verdict rule**: generator structure claimed at horizon q ONLY IF VR(q)
  lies outside the 95% surrogate band AND the sign is consistent across
  3 disjoint thirds of the tick window (≥2 of 3 significant, same sign) AND
  the H1 cross-check agrees in sign at the matching horizon.
- **Falsifies the critique's "no structure" stance**: VR > 1 (trend) or < 1
  (reversion) at q ∈ [4, 256] per the rule above.
- **Confirms it**: all VR inside bands.

### Test C — Regime-conditional forward drift
- **Regime mirror** (exact EA semantics, H1): EMA20/50/100 stack + close
  beyond fast EMA + |EMA20−EMA50|/ATR ≥ 0.22 → BULLISH/BEARISH; ATR(14)
  trailing-percentile (120-bar history) > 90 → HIGH_VOL; < 8 → NO_TRADE;
  else RANGING.
- **Statistic**: mean forward drift over next 4 H1 bars (4h) and next 8 (8h),
  in index points, per regime; t-stat of mean ≠ 0. Secondary: drift by ATR
  tercile within each regime.
- **Verdict rule**: directional information EXISTS iff BULLISH drift > 0 and
  BEARISH drift < 0 with |t| ≥ 2.0 at the same horizon. Otherwise the EA's
  EMA regime axis is decoration for direction (it may still gate by
  volatility — that is scored separately by the tercile rows).
- **Cost context**: any claimed drift is compared against the ~0.03R (~18.5
  units at 575-unit stops) round-trip cost bar.

### Drift audit
- Annualized drift of V75 over 19 months of H1 bars (log or arithmetic, both
  reported) vs the cost bar; resolve the 120k → 50k price-level discrepancy
  between archives (z_gate vs fresh era) before interpreting sign.

## Integrity notes
- The 2s tick grid is uniform; VR uses every tick (no resampling choices).
- No parameter in Tests A/C was tuned on the result of any prior run of
  these statistics (none existed before this freeze).
- Outcome addendum appended below AFTER execution, in the same pass as the
  computation, with no post-hoc criteria changes.

---

## OUTCOME (computed 2026-09-05, immediately after freeze — one pass)

### Test A — variance ratios: NO structure at any tested horizon

**Tick lake (2,460,772 ticks, 2s grid, Jul 6 → Sep 2; grid uniform to 0.9999):**

| horizon | VR(q) | surrogate 95% CI | significant? |
|---|---|---|---|
| 8s (q=4) | 1.000 | [0.998, 1.003] | no |
| 32s (q=16) | 0.999 | [0.994, 1.005] | no |
| ~4.3min (q=128) | 0.991 | [0.986, 1.015] | no |
| ~8.5min (q=256) | 0.992 | [0.980, 1.023] | no |

Thirds consistency: **zero** significant horizons in any third — the registered
multi-window rule is not even reached. **Supplementary (post-freeze, labeled as
such), the critique's exact horizons via tick aggregation:** 0.5h VR=0.997
[0.954,1.045], 1h VR=0.994 [0.939,1.064], 2h VR=0.976 [0.914,1.076],
4h VR=0.979 [0.892,1.136] — all `ns`, thirds sign-inconsistent
(`artifacts/critique_replication/vr_long_horizon.json`).

**H1 cross-check (19 months):** VR(64h)=0.917, VR(256h)≈0.83, all inside
surrogate bands (which widen strongly at long q). Fresh era: same — nothing
survives its own band.

**Verdict per registered rule: CONFIRM — the generator shows no linear
trend/mean-revert structure at any horizon from 8 seconds to 256 hours.**
The critique's "no directional skill in the price stream" stance is
empirically vindicated on our own data.

### Test C — regime-conditional forward drift: the EMA regime axis is
### anti-continuation, and vol state is empty

Hour-level stats (overlapping, inflated — shown for completeness): BULLISH
forward-4h drift NEGATIVE in both eras (t=−2.10 19m, t=−3.05 fresh), BEARISH
POSITIVE in both (t=+0.84, t=+1.78; h8 fresh t=+3.29).

**Corrected statistics (overlapping windows + persistent labels handled —
regime episodes are ~9h median):**

| statistic | 19m era | fresh era |
|---|---|---|
| BULLISH episode h4 (n=426 / 53) | −131 pts, t=−1.69 | **−305 pts, t=−2.57** |
| BEARISH episode h4 (n=539 / 60) | +109 pts, t=+1.73 | +70 pts, t=+0.64 |
| BULLISH non-overlap h4 | −68, t=−0.91 | −138, t=−1.40 |

The anti-continuation sign is consistent in **8 of 8** episode tests (both
regimes × both horizons × both eras) — but only fresh-era BULLISH clears
|t| ≥ 2.0. **Verdict per registered rule: NO directional information.** The
registered criterion demanded BULLISH > 0 AND BEARISH < 0 with |t| ≥ 2 —
reality shows the *opposite* sign pattern, weakly. Two honest readings:

1. The EA's EMA regime axis carries **no exploitable directional signal** —
   and if anything a weak *fade* tendency (a freshly-confirmed BULLISH regime
   is followed by below-average drift). The critique's §4e ("EMA trend regime
   is likely noise-chasing") is **substantially correct**.
2. A fade-the-regime hypothesis exists (consistent sign, one |t|>2) — but it
   is exactly the kind of post-hoc discovery that must be pre-registered on
   NEW data before it earns anything. **Registered as a candidate protocol,
   NOT adopted.**

**Vol terciles within regimes:** nothing coherent (fresh BULLISH hi-vol
tercile t=−3.28 is the anti-continuation story again, not a vol effect;
19m rows are all |t| < 1.2 with mixed signs). The GARCH/ATR *volatility*
forecasting axis remains the only defensible use of state — for SIZING and
GATES, never for direction.

### Drift audit: the only real edge candidate is slow drift — and it flips

| era | price path | annualized drift | hourly t |
|---|---|---|---|
| Jul 2024 → Feb 2026 (19m archive) | 120,527 → 26,818 (−77.7%) | **−98.0%/yr** | −1.62 |
| Jul 2026 → Sep 2026 (fresh) | 49,909 → 49,882 (−0.1%) | −0.3%/yr | −0.00 |

- The 120k → 27k collapse is a **smooth 19-month downtrend** (max hourly move
  ±3.3%, no discontinuity) — the generator's price-level controller moved
  massively across 2024–2026. **Between Feb and Jul 2026 it nearly doubled
  (26.8k → 49.9k).** Long-run drift is real but unstable: it flipped sign
  within the last 12 months. Trading it requires deciding WHICH drift you
  will get — at hourly grain, drift is unpredictable (t=−1.62).
- Cost bar: certified stop geometry (~575 units) makes spread cost ≈ 0.03R
  per trade; any drift capture at M15 frequency pays it ~135×/60d. Drift
  capture is a *position* strategy (weeks+, one-directional, seatbelt), not
  an M15 strategy. Pre-registration for that — if ever attempted — must
  define era-conditional drift rules and drawdown budgets BEFORE execution.

### Small-sample honesty (critique §4b) — applied to ourselves

- fresh60: 65/135 wins → **Wilson 95% LB = 39.9%** — consistent with a coin.
- Per-trade expectancy: +0.098R, σ=1.19R, **t = 0.96** — NOT significant.
- Net of the corrected spread cost: +0.066R/trade, t ≈ 0.65.

**The honest standing claim is therefore not "+13.23R certified edge" but:
"a strategy consistent with zero-to-small positive expectancy, whose live
value will be decided by the ≥30-trade paper gate, not by backtests."**
This does not change the go-live mechanics (the gate was already built on
live data), but it lowers the language everywhere "certified" was used.

### Where the critique was right / wrong / already answered

| Critique claim | Verdict |
|---|---|
| §4a Band Fade contradicts fingerprint | Wrong target — BF is disabled in both deployed presets (documented since its spread-gate veto). General question still tested: no VR structure at any horizon. |
| §4b 60–135 trades prove nothing | **Right.** Wilson LB 39.9%, t=0.96. Language corrected project-wide; the live gate was already the answer. |
| §4c selection-on-the-winner | Partially right historically; the duels (TP, MOM-standalone, this doc) are the institutional fix — frozen criteria, one pass, fold-paired. |
| §4d costs are the silent killer | **Right in mechanism, small in magnitude**: spread was missing from PnL; corrected impact −4.34R on +13.23R (edge shrinks ⅓, survives). Engine fix queued. |
| §4e EMA regime is noise-chasing | **Substantially right**: Test C shows the regime axis has no (weakly anti-) directional information. Its remaining legitimate role: volatility-aware gating/sizing. |
| §5 Tests A–C | Executed above, on 2.46M ticks + 19 months of bars. |
| §7 "stop directional trading of a fair generator" | The data agrees at every tested horizon; the project's live value now rests entirely on the paper gate, risk sizing, and the small-sample honesty above — not on any claimed predictive edge. |

### Registered follow-ups (in priority order)
1. **DONE 2026-09-05 — `certify_v75.py` now pays the spread in PnL**
   (half at entry fill, half at exit; geometry anchors to the real fill).
   Integrity: `CERT_COST_LEGACY=1` reproduces the published run bit-identically
   (+13.23R / 135 / 48.1%). Cost-inclusive re-baseline (fresh 60d, $100 start):
   TP 1.8 **+4.37R / 114 trades / net expectancy +0.038R (t=0.35)**;
   TP 2.4 **−4.07R** (now negative). Funding Monte-Carlo re-priced on the net
   stream: $31 → P(profit) 10%, $50 → 39%, $100 → 92% survival with median
   +$3.42. Full details in `docs/LIVE_READINESS.md` (2026-09-05 update).
2. **Language audit**: replace "certified edge" with "gate-qualified"
   terminology in docs that feed decisions.
3. Candidate (NOT adopted): pre-registered fade-the-regime protocol on data
   that postdates this document.

**Artifacts**: `artifacts/critique_replication/results.json`,
`vr_long_horizon.json`, `scripts/critique_replication.py`.
