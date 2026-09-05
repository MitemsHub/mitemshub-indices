# V100 NET-EDGE STUDY — pre-registered 2026-09-05 (frozen before any net run)

## Question

Does the engine's GROSS edge on Volatility 100 Index survive its (much smaller)
spread cost, measured with the cost-inclusive engine over the full 2-year bar
set — and does any geometry pass the unchanged walk-forward gate?

## Why this is a live question, not a formality

The 2026-09-04 gross 2-year walk-forward (`artifacts/v100_replay/walkforward_v100_2y.json`,
53×14-day folds, ~1,750 trades/config, equity $200) measured:

| config | gross total R | pos folds | worst fold | t |
|---|---|---|---|---|
| legacy (tp 2.4) | **+31.66** | 26/53 | −13.53 | +0.67 |
| tp18 (reference) | +25.01 | 27/53 | −14.13 | — |
| v2629 stack | −7.09 | 25/53 | −9.22 | −0.18 |

Every config already failed the V1–V6 gate GROSS (per protocol, nothing was
deployed). But V100's cost structure differs from V75's by an order of
magnitude: spread 0.26 index units vs a ~10–30-unit stop (≈1–3% of stop; V75
pays ~7%+ of stop per round trip). With ~1,750 trades per config, even
0.01–0.02R per trade is a 20–35R cumulative drag — the same size as the entire
gross edge. Whether the edge survives is therefore an empirical question the
gross run cannot answer. The engine (per-trade stop-scaled costs, governor
feedback) measures it exactly; arithmetic approximations do not.

## Environment (identical to the certified gross run, one switch flipped)

```
CERT_DATA_DIR=artifacts/v100_replay
CERT_SPREAD=0.26  CERT_USD_PER_UNIT_PER_LOT=1.0
CERT_MIN_LOT=1.0  CERT_LOT_STEP=1.0
WF_FOLD_DAYS=14  WF_CONFIGS=legacy,v2629,tp18  EQ=200 (harness constant)
```

Net runs = default engine (fills pay the spread; entry at bid/ask, exit pays
the other half; geometry anchored to the real fill). Gross re-run = same with
`CERT_COST_LEGACY=1`.

## Integrity gate — FAILED, cause diagnosed (2026-09-05, logged before any net number was read)

The re-run did NOT reproduce the stored artifact (legacy +31.66→+29.21, v2629
−7.09→+13.86, tp18 +25.01→+23.09; trade counts shift between folds). Per the
freeze, the net run was withheld until the cause was found. Diagnosis
(localized on fold F12, then confirmed exact across the full run):

- The stored 2026-09-04 run set `CERT_SPREAD=0.26` and `CERT_USD_PER_UNIT_PER_LOT=1.0`
  but **left `CERT_MIN_LOT`/`CERT_LOT_STEP` at the V75 defaults (0.01)** — a
  broker-impossible lot grid for V100 (true floor: 1.0 lot). With 0.01 lots the
  20% risk cap never vetoes, so the stored run traded every signal on
  negligible dollar size (its `max_risk_pct: 0.5` confirms the grid).
- Old-code (a47bb8a) vs new-code (8d155fe) on the same fold and envs agree
  EXACTLY (n=7, −4.05R) — the cost-model refactor did not perturb the engine.
- Consequence: the stored numbers measure **signal quality**, not a fundable
  account. The true-spec re-run (`walkforward_v100_2y_gross_repro.json`) is
  the honest gross baseline; its V1–V6 verdicts are unchanged (NOT VALIDATED
  for every config), and v2629's apparent 2y loss (−7.09) was an artifact of
  the fictional grid — under true sizing the min-lot veto removes its worst
  trades (+13.86 gross).

**Amendment (recorded, not hidden):** the integrity gate as originally written
("exact equality with the stored artifact") is unsatisfiable because the stored
run's env was mis-specified. The gate is replaced by: exact equality of the
cost-blind engine between old and new code (PASSED on F12), plus the true-spec
gross re-run as baseline. Q1/Q2 criteria are unchanged. Canonical env block
for every future V100 run is the one in the Environment section above (all
five variables, no defaults).

## Pre-registered criteria (frozen now, one pass, no threshold archaeology)

**Q1 — "does the gross edge survive costs?" (measurement, per config):**
  - SURVIVES: net total R > 0 across all 53 folds AND fold-mean t ≥ 1.0.
  - DIES: net total R ≤ 0.
  - Also reported: per-trade cost (gross R − net R)/trades, and the paired
    fold-level drag with its t-stat (53 paired folds).

**Q2 — "does any geometry pass the gate?" (deployment claim):**
  - UNCHANGED round-4 criteria V1–V6, ALL must hold vs tp18 reference:
    V1 total>0 · V2 ≥60% positive folds · V3 worst fold > −3.0R ·
    V4 beats tp18 total · V5 median fold > 0 · V6 t ≥ 1.5.
  - Prior on record (frozen before running): NO config passes — none passed
    gross; costs only subtract. A pass would be a major surprise demanding
    replication, not deployment.

**Honesty constraints:**
  - One pass, no re-folding, no config additions, no threshold changes.
  - The 2-year window includes a −62% price grind (1568→602); per-trade costs
    rise as ATR shrinks — the engine handles this per-trade; no era re-weighting.
  - Whatever the outcome, V100 stays uncertified-for-funding unless Q2 passes —
    same discipline that kept V75 honest.

## Execution log (filled in after the freeze)

- Integrity gate: FAILED → diagnosed (stored run used the V75 0.01-lot grid;
  engine itself verified old==new bit-exactly). Baseline replaced by the
  true-spec gross re-run. Details above.
- Net walk-forward (53×14d, true spec): **DONE** — all configs net-negative.
- Full-period net certs ($200): **DONE** — decomposition below.
- 210-day true-spec net re-run (closing the "personality flip" loop): **DONE**.
- Verdicts: **Q1 NO — the gross edge does not survive. Q2 NO — nothing passes
  V1–V6, per the frozen prior.**

## Results (2026-09-05, one pass)

**Q1 — net walk-forward, 2 years, 53 folds (walkforward_v100_2y_net.json):**

| config | true-spec gross | net (spread paid) | drag | verdict |
|---|---|---|---|---|
| legacy (tp 2.4) | +29.21R | **−20.06R** | −49.3R | DIES |
| v2629 stack | +13.86R | **−20.07R** | −33.9R | DIES |
| tp18 (ref) | +23.09R | **−24.55R** | −47.6R | DIES |

Per-trade cost ≈ 0.028R (drag / ~1,700 trades) — 2–3× the arithmetic
back-of-envelope, because the 2-year window's −62% price grind (1568→602)
shrinks stop distances while the spread stays fixed, so the cost share of a
trade RISES over time. Q1: **SURVIVES requires net>0 AND t≥1.0 — neither
holds for any config (all t ≤ −0.46). The edge DIES.**

**Full-period net cert at $200 (cert_report_v100_2y_net200.json):** $200 →
$17.61, −5.29R over 191 trades, max DD 94.9%. Structural finding: with the
true 1.0-lot floor and early-era wide stops, single trades risk up to the 20%
cap — the compounded dollar account is destroyed even by a mildly negative
R-book. (Funnel: auto-disable 6,649, paused 1,248, risk-cap 670, spread-gate
527.)

**210-day true-spec net re-run (walkforward_v100_210d_truespec_net.json):**
legacy −10.71R, tp18 −5.81R, v2629 **−33.76R (t=−3.00)**. The Sep-4 "V100
personality flip" (stack +15.1R on 210d) is **retracted as an artifact of the
fictional 0.01-lot grid** — under true sizing the stack is the WORST config on
the same window. "No universal geometry" stands, but for a blunter reason:
there is currently no validated geometry on V100 at all.

**Q2 — V1–V6 gate:** every config NOT VALIDATED (V1 fails for all: totals
negative; V2/V3/V5/V6 fail downstream). Consistent with the pre-registered
prior. Nothing is deployed, nothing changes in the EA.

## Verdict

**V100 net-of-cost: NO EDGE. The engine's gross signal on V100 does not
survive the instrument's cost structure under true broker specs, and no
certified era of the 2-year history contained a fundable configuration.** V75
remains the only certified instrument. V100 stays uncertified; the fit router
may still name it, but funding follows certification.

**Audit lesson (fourth occurrence, now systemic):** env-var defaults are a
silent-confounder class. The 0.01-lot default produced a coherent, plausible,
completely fictional 2-year result that survived into the changelog. Standing
rule: every cross-instrument cert run MUST set all five CERT_* spec variables
explicitly, and any artifact whose `max_risk_pct` implies sizing the instrument
cannot trade is invalid on its face. (The V75 spec-default runs are exempt:
0.01 lots IS the V75 truth.)
