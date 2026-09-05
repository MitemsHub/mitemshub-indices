# MOM-Standalone Duel — Pre-Registration (frozen 2026-09-04, pre-execution)

**Status: REGISTERED → EXECUTED same day (single pass). Verdict:
REJECT-standalone (window a) / NO-ADOPT (window b) — demotion rule stays.**
Outcome addendum below; artifacts: `mom_duel_fresh60.json`, `mom_duel_zgate.json`.

---

## Addendum — outcome (recorded 2026-09-04, after execution)

**Window (a) — fresh60 (Jul 7 → Sep 4, 2026), $200, 8×~7-day paired folds:**

| Arm | Total R | Trades | WR |
|---|---|---|---|
| demote (deployed) | **+13.23** | 135 | 48.1% |
| standalone | +10.01 | 167 | 49.7% |

D = **−3.22R** (≤ −3.0 ✓), fold deltas [−0.70, −4.51, +2.50, −1.44, +2.15,
−4.46, **−11.55**, −3.63] → mean −2.71R/fold, **t = −1.70** (≤ −1.0 ✓) →
**REJECT-standalone.** Standalone was worse in 6/8 folds; its one blowup fold
(F7, −11.55R) exceeds the entire 60-day D by itself. Note: the standalone arm
triggered the governor's auto-disable (MOM, MOM+PB disabled mid-run; 433
funnel events) while the demote arm never did — meaning the governor was
already *rescuing* standalone from itself, and it still finished worse.

**Window (b) — z_gate (Jul 2024 → Jan 2026, $200, 28×~20-day paired folds):**

| Arm | Total R | Trades | WR |
|---|---|---|---|
| demote (deployed) | −16.03 | 69 | 36.2% |
| standalone | −23.17 | 719 | 45.5% |

Full-window D = −7.14, **but this comparison is confounded and the protocol
says so**: in a 19-month continuous run the governor's auto-disable diverges
between arms (demote arm had the whole PB family disabled — only 69 trades —
while standalone kept MOM alive with 719). The arms are no longer measuring
the same system. The clean statistic is the fold-level paired delta (state
resets per fold): **mean +2.17R/fold, t = +1.15, 16/28 folds positive.**

Per the registered rule: window (b) meets neither REJECT (t is positive) nor
ADOPT (D ≥ +3.0 AND t ≥ +1.0 — full-window D is negative; fold-mean t +1.15
alone adopts nothing) → **NO-ADOPT / KEEP-COLLECTING for that era.**

**Combined verdict: REJECT-standalone.** The only window that reflects the
regime the EA will actually trade (current era) rejects it decisively; the
historical era fails to clear the adoption bar (and its standalone arm was
still net-negative, −23R). `InpMomentumStandalone` stays `false`. The paper
A/B is untouched.

**Era note (descriptive, not actionable)**: lone-MOM was *additive* on the
margin in 2024–2025 (+2.2R/fold) but a drag in 2026 (−2.7R/fold). If a future
regime resembles 2024–2025 again, this question can be re-registered — with
fold-based paired deltas as the PRIMARY statistic (see methodology note).

**Methodology lesson (for all future duels)**: in long continuous sims, the
stateful governor (auto-disable, loss-scaling) makes arm trajectories diverge,
so full-window totals stop being a pure signal-rule comparison. Fold-based
paired deltas with per-fold state reset are the honest statistic; the
confound here also explains why fold sums and continuous totals can
legitimately disagree (window b: folds sum to +60.7R vs continuous −7.14R
because the continuous runs disable different strategies at different times,
while folds restart the governor fresh).

---

## Motivation (written before execution)

On 2026-09-04 19:15–21:15 V75 printed a 1,417-point waterfall. The EA skipped
every bar (`mom-demoted-lone-candle`). Enabling `InpMomentumStandalone` would
have taken 2 SELLs at ~20:45/21:00 — both would have paid. One evening of
hindsight is exactly the kind of teaser this project has learned to distrust
(the V100 stack flip, the mid-z flip, the August filters). The question gets
the standard treatment: freeze criteria, then look.

**Question**: does removing the lone-momentum demotion
(`InpMomentumStandalone=true`) beat the deployed demotion rule, or is
lone-candle momentum a net drag (noise-chasing)?

## Provenance (every prior look at this question)

| Look | Data | Result | Status |
|---|---|---|---|
| v26.23 demotion design | pre-validation era | MOM never standalone by default | design decision, no standalone statistics ever computed |
| Evening observation (2026-09-04) | 19:15–21:15 today | 2 would-be SELLs, both winners | **hindsight teaser — spent by this registration** |
| All walk-forward rounds, all cert runs | Feb–Sep 2026 | always demote | standalone arm never executed |

**Clean on both sides**: no standalone-vs-demote *paired* statistic exists
anywhere in this project's history. Both windows below are uncontaminated.

## Test spec (frozen before execution)

**Data**: (a) current 60-day sample `artifacts/v75_replay/` (Jul 7 → Sep 4,
2026); (b) z-gate dataset `artifacts/z_gate/` (2024-07-20 → 2026-01-31) —
fully disjoint from (a), still uncontaminated for this question.

**Runs**: full governor, equity $200, honest booking, identical signal and
money layers by construction. **The only difference between arms is the
demotion rule.**
- Arm `demote` (deployed): lone MOM votes discarded (today's EA behavior).
- Arm `standalone`: lone MOM votes trade (`InpMomentumStandalone=true`).

**Statistics (computed once)**:
- D = standalone_total_R − demote_total_R (60-day window)
- Fold-level paired deltas: 8 × ~7-day folds over the 60 days, fold-mean t-stat
- z-gate window: same arm totals + fold t-stat (28 × ~20-day folds)

## Verdict rule (all pre-registered)

- **REJECT-standalone**: D ≤ −3.0R AND t ≤ −1.0 → standalone is noise-chasing;
  demotion stays; protocol closed.
- **TIE/KEEP-COLLECTING**: −3.0R < D < +3.0R or |t| < 1.0 → inconclusive at
  available power; paper data may re-open it (register again before any look).
- **ADOPT-standalone**: D ≥ +3.0R AND t ≥ +1.0 → relabel the favorite
  (config change still requires the paper gate — a backtest never flips the
  preset by itself; the A/B would be redesigned around the winner first).

One execution pass per window, then closed. No sub-window shopping, no
threshold tuning after seeing D or t.
