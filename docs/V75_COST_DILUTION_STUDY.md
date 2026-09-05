# V75 COST-DILUTION STUDY — pre-registered 2026-09-05 (frozen before execution)

## Question

V75's certified net edge is +0.038R/trade (t = 0.35) because the fixed 18.5-unit
spread costs ≈ 0.07–0.09R per trade against a ~250-unit stop. Cost per R falls
as stop distance rises. Can wider-stop and/or lower-frequency geometry variants
dilute the spread enough to clear a materially positive net edge — or is V75's
cost structure structurally hostile at every tested geometry?

## Why this is registered (and not a hand-tune)

This is the one lever the V100 net-edge study (2026-09-05) pointed at that
applies to the certified instrument: net edge = gross edge − (spread / stop
distance). All prior geometry rounds walked folds GROSS or with the veto-gate
only; this is the first pre-registered walk of the COST-INCLUSIVE engine on
V75. The discipline is unchanged: frozen variants, frozen folds, frozen
criteria, one pass, and nothing touches the EA unless the paper arm confirms.

## Frozen design

### Variants (exactly five + reference — no others will be scored)

The engine scales stop distance by `--stop-mult` with TP anchored at
`tp_mult × sd` (geometry re-anchored to the real fill; spread paid in PnL).
All variants run the deployed signal family unchanged (no veto, no throttle,
`InpPbEmaSideVeto=false`, `InpPullbackMin=0.30` — the VOL75_FINAL signal set):

| arm | stop_mult | tp_mult | rationale (frozen reasoning) |
|---|---|---|---|
| ref | 1.0 | 1.8 | deployed VOL75_FINAL geometry; the comparator |
| ws13 | 1.3 | 1.8 | mild widening; TP distance unchanged in R |
| ws17 | 1.7 | 1.8 | spread share ≈ /1.7 |
| ws25 | 2.5 | 1.8 | aggressive widening; hits the 3%-of-price cap often |
| lf13 | 1.3 | **2.4** | wider stop AND legacy TP: fewer, larger winners |
| bs17 | 1.7 | **1.8 but MIN_SCORE+1** | breadth-survival: same geometry as ws17, half the signals |

`bs17` uses the harness's existing conviction-throttle raised by +1 (a
score-requirement increase = lower frequency); it is the only variant that
changes signal selection rather than geometry, registered deliberately as the
frequency lever. `lf13` pairs widening with the OOS-validated legacy TP 2.4.

**Hard ceiling (existing EA rule, kept):** `sd ≤ entry × 3%`. On V75 near 50,000
that caps stops at ~1,500 units; ws25's ×2.5 on a 600-unit ATR stop is inside
it, but the cap is honored wherever it binds — no cap changes.

### Data window (fresh, to be pulled AT execution — no leakage)

`python scripts/pull_v75_week.py --days 28 --outdir artifacts/v75_costdil/`
— the 28 M15 days immediately preceding execution, pulled once, all six arms
run on the SAME file. Fresh data only: every prior V75 window (Feb–Sep,
Aug-2025–Jan, the cert window) is burned for these variants by exposure to
prior rounds' conclusions; the point of this study is an uncontaminated read.
The 480-bar burn-in eats ~5 days; 28 days yields **8 non-overlapping 8-day
folds** (7 full + remainder fold), consistent with the minimum-viable-power
rule (≥ 8 folds fresh; the round-3 lesson "4-fold walks are noise machines"
is why 4 was rejected).

Env block (full spec, per the standing rule after the V100 lesson):
`CERT_DATA_DIR=artifacts/v75_costdil` + default V75 specs (spread 18.5,
$1.009/unit/lot, 0.01 min lot — these ARE the V75 truth, exempt from the
explicit-five rule by the same clause). Equity $200 (sizing comparable to
paper virtual equity scale, keeps the risk-cap from binding on the reference).

### Criteria (frozen; per candidate arm vs the reference, fold-paired)

  - **W1 (net economics):** net total R across folds > reference's net total R.
  - **W2 (fold consistency):** positive folds ≥ 50% (reference is the deployed
    config; a dilution variant must at least match a coin on fresh folds).
  - **W3 (worst fold):** worst fold R > −6.0 (V75 8-day folds can print −4 to
    −5 on the deployed config; −6 is the catastrophe line).
  - **W4 (edge size, the actual point):** net expectancy ≥ +0.08R/trade —
    double the deployed +0.038R. Dilution that leaves expectancy unchanged is
    noise (fewer trades, same edge); only a per-trade improvement justifies
    the paper arm.
  - **W5 (fold-paired significance):** paired per-fold delta vs reference has
    t ≥ +1.0 in the variant's favor.
  - **W6 (trade count floor):** ≥ 60 trades over the window (enough for the
    W4 expectancy to mean anything at ~1.0 spread of outcomes).

**Verdict per arm:** VALIDATED-CANDIDATE (all six) → earns a paper arm +
dedicated protocol; otherwise NO-ADOPT. **Reference failure clause:** if the
reference itself fails W2/W3 on the fresh window, the window is a regime
outlier — the study reports descriptives and re-arms (one re-pull allowed,
same protocol, noted here as pre-declared).

### Priors (frozen before the pull — honesty record)

  - ws13: NO-ADOPT (widening helps cost share but drags the winner-cut loss
    mode; +0.04–0.05R/trade at best — fails W4).
  - ws17: NO-ADOPT (same direction, weaker; the 5-bar low/high floor
    (`max(sd, entry − lo5)` logic) partially re-tightens widened stops, so the
    effective spread dilution is less than ×1.7).
  - ws25: NO-ADOPT (the 3% cap binds intermittently; TP at ×1.8 of a doubled
    stop rarely completes inside MAX_HOLD; expected to fail W4 AND W6).
  - lf13: NO-ADOPT (TP 2.4's lower completion rate is why the preset moved to
    1.8; widening does not fix winner completion).
  - bs17: NO-ADOPT (the z-gate lesson: frequency gates that look sensible in
    calibration flip on fresh data; expect W2/W5 failure).
  - Reference: ~+0.03R/trade on the fresh window (regression toward the
    honest mean), W2/W3 pass, W4 fails by design — the reference is the
    comparator, not a candidate.
  - **Any VALIDATED-CANDIDATE would be a genuine surprise** and must survive
    the paper arm before the EA ever changes.

### Paper-arm gate (pre the EA change, before anyone asks)

Even a VALIDATED-CANDIDATE changes NOTHING in `MitemshubAI.mq5` or the
deployed preset until: (a) a dedicated third paper terminal runs the variant
for ≥ 30 closed trades with positive net expectancy (same machinery as the
A/B adjudicator, pre-registered separately at that time), AND (b) the
primary TP A/B (arm A vs arm B) has adjudicated without contamination from
this experiment. The deployed VOL75_FINAL and both current arms are untouched
by this study regardless of outcome.

## Execution log

- Pulled window: PENDING (at execution)
- Folds: PENDING
- Per-arm results: PENDING
- Verdicts vs priors: PENDING

## Commit discipline

The protocol is committed BEFORE the data pull. The execution results land in
a separate commit with the artifact paths, whatever they say.
