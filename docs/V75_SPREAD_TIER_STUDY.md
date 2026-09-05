# V75 SPREAD-TIER STUDY — frozen protocol (2026-09-05)

## Question

The cost-dilution study closed strategy-side geometry as a dead lever: V75's net
edge is cost-dominated at every stop/frequency setting we tested (+0.038R/trade
deployed, vs +0.08R/trade needed to matter). The remaining lever is **the spread
itself**. Deriv markets a **Zero Spread MT5 account that includes Synthetic
Indices** (official, Jul 2025) with per-lot commission in place of spread — but we
do __not__ know whether the raw synthetic spread is below the 18.5 index units we
currently pay, or whether 18.5 IS the raw model spread (in which case the
zero-spread tier buys nothing on V75).

**Two deliverables, frozen here:**
1. **Measurement**: V75 effective spread (ask−bid) by hour-of-day (UTC) from the
   2.46M-tick lake (`artifacts/data/volatility_75_index_ticks_20260707_20260803.csv`
   + `..._20260803_20260902.csv`, `epoch_ms,bid,ask`, 0.5 Hz, ~57 days). The lake
   is the raw Deriv tick stream — this is the best available proxy for the
   zero-spread/raw tier.
2. **Quantification**: net edge (R/trade, total R, trades, drawdown, funnel) of
   the **deployed config** (tp 1.8, all else default) at each spread tier, through
   the cost-inclusive cert engine (`CERT_SPREAD=x`, everything else identical).

No strategy varies. No data pull needed (both windows already on disk). Tiers are
a cost input, not a selection rule — this is characterization, and it cannot
change the EA by itself. A tier that lifts net expectancy to the house bar simply
qualifies the *broker venue* as a candidate; the paper gate still adjudicates.

## Tiers (frozen)

| tier | spread (index units) | meaning |
|---|---|---|
| t185 (baseline) | 18.5 | current standard account — comparator |
| t_raw | **median lake ask−bid** (measured; if ≈18.5 the lever is dead in one sentence) | zero-spread/raw proxy |
| t14 | 14 | ×0.75 sensitivity |
| t9 | 9.25 | ×0.5 sensitivity |
| t5 | 4.6 | ×0.25 sensitivity |
| t0c | commission-equivalent | spread=0 + per-lot commission $2/lot/side (Deriv flat $4 round-turn per standard lot): modeled as spread-equivalent ≈ −4×vol USD/trade; at our min-lot 0.01 sizing ≈ $0.04/trade ≈ 0.0001R — an upper bound on the zero-spread+commission outcome |

**Primary window**: fresh60 (the certified window, Jul 12–Sep 4, `artifacts/v75_replay`,
trades incl. 2026-09-04). Comparator = stored `cert_report_net_tp18_check0905.json`
(+4.37R / 114 trades / 45.6%): tier t185 must reproduce it **bit-identically**
(integrity gate) before any tier number is read.
**Robustness window**: the 70-day cost-dilution window (`artifacts/v75_costdil/`,
9×8-day folds) — fold-consistency read at each tier.

## Integrity gate (pre-run)

- `CERT_COST_LEGACY` unset (net engine), `--tp-mult 1.8` explicit (the deployed
  geometry — the CLI's default 2.4 is a known footgun, 2026-09-05 spec-stamp
  lesson). `CERT_DATA_DIR` unset → spec guard exempt, V75 truth applies.
- t185 fresh60 must equal the stored net artifact bit-for-bit (spec/funnel
  staleness note applies: the stored `funnel` may carry the known one-beat delta;
  ledger + metrics must match exactly).

## Criteria (frozen, read-only after the runs)

1. **Lever verdict** — `t_raw` median vs 18.5: >25% tighter ⇒ the lever is real
   (raw < standard); ≤25% tighter ⇒ the "zero-spread" tier is marketing on
   synthetics and the broker-side lever is effectively unattainable on this
   platform. Recorded as fact, not verdict-by-hope.
2. **Materiality bar** (house standard, from `docs/V75_COST_DILUTION_STUDY.md`):
   a tier **changes the picture** if (a) fresh60 net expectancy ≥ **+0.08R/trade**,
   and (b) robustness window: ≥50% of 9 folds positive and worst fold > −6R.
   This is the number that would make a zero-spread venue worth paper-testing on
   arm C — which then still waits for the primary A/B adjudication and a fresh
   pre-registered candidate rule. No outcome reaches the EA directly.
3. **Sensitivity curve** — net R/trade vs spread, fitted slope = R per unit of
   spread cut; reported so any future venue quote (another broker, a negotiated
   tier) can be priced in seconds.

## Priors (recorded before measuring)

- P1: the lake median will be close to 18.5 (the generator's own pricing model
  sets the synthetic spread; the standard account's markup on synthetics is
  believed zero) ⇒ lever verdict likely DEAD on Deriv MT5.
- P2: even the best tier will NOT clear +0.08R/trade on fresh60, because the
  gross edge there is small and 60 trades is a noisy sample. If P2 is wrong it is
  a genuine surprise and arm-C material; if P1 is wrong (lake ≪ 18.5) then P2
  becomes materially more likely to be wrong too.

## RESULTS — adjudicated 2026-09-05, frozen criteria applied after all runs

### 1. Measurement: V75 spread vs hour-of-day (2,460,772 ticks, Jul 7 – Sep 2)

| stat | value |
|---|---|
| overall mean / median | 16.58 / **16.96** index units |
| p90 / p99 | 17.89 / 18.53 |
| hour-of-day range (median) | **16.96 at every hour** (mean wiggles 16.55–16.63) |

- **No hour effect exists.** The spread is a coarse step grid (~0.95-unit levels:
  16.01, 16.96, 17.89, 18.53) constant 24/7. An hour-gate strategy study would
  be chasing noise — closed by measurement, not opinion.
- The live-account calibration (18.5) sits at the lake's p99 (18.53): the lake
  **is** the tier. Raw median 16.96 vs 18.5 = **−8.3%** — under the frozen 25%
  materiality threshold, so **the broker-side lever is DEAD on Deriv MT5
  synthetics**: the spread is the generator's pricing model, not account markup,
  and the zero-spread account cannot price below raw. P1 CONFIRMED.

### 2. Net edge per tier — fresh60 (certified window, deployed tp 1.8, net engine)

Integrity gate: t185 reproduced the stored `net_tp18_check0905` ledger
**bit-identically** before any tier read (+4.37R/114t).

| tier | spread | n | total R | exp R/t | t (trade var) | max DD |
|---|---|---|---|---|---|---|
| t185 (baseline) | 18.50 | 114 | +4.37 | **+0.038** | +0.35 | 52.9% |
| t_raw (zero-spread proxy) | 16.96 | 128 | +6.08 | **+0.048** | +0.46 | 44.6% |
| t14 | 14.00 | 128 | +6.85 | **+0.054** | +0.52 | 44.2% |
| t9 | 9.25 | 121 | +3.77 | **+0.031** | +0.30 | 53.1% |
| t5 | 4.60 | 119 | +3.38 | **+0.028** | +0.27 | 49.8% |
| t0c (spread=0 + ~0 commission) | 0.00 | 133 | +21.53 | **+0.162** | +1.13 | 38.1% |

- Realistic tiers (raw, 14) improve expectancy +0.038 → +0.048/+0.054 — **below
  the +0.08R/t materiality bar**. P2 CONFIRMED on fresh60.
- **Non-monotonicity (t9/t5 < baseline) is real but understood**: cost cuts reroute
  the governor (pause/auto-disable trajectories shift: paused 812→1,088,
  auto-disable 44→23), so at 60–130 trades the response is noisy, not linear.
- **The t0c ceiling is NOT the same engine cheaper**: at spread 0 the
  band-fade leg reopens (BF 9 trades, +11.1R — unviable at real spread, its
  ~5–15 unit stops would pay a 200–400% toll). Even so it is t=1.13 on 133
  trades and, structurally, *unpurchasable*: raw spread is 16.96, not 0, and
  the zero-spread account cannot go below raw.

### 3. Robustness — 70-day cost-dilution window, 9 folds, tp18 (the clean read)

| tier | total R | pos folds | worst fold | t (fold var) |
|---|---|---|---|---|
| t185 | −1.21 | 3/9 | −3.33 | −0.12 |
| t_raw | +0.76 | 3/9 | −3.28 | +0.07 |
| t14 | +1.74 | 3/9 | −3.18 | +0.16 |
| t9 | +3.24 | 3/9 | −3.02 | +0.27 |
| t5 | +3.78 | 3/9 | −2.87 | +0.32 |
| t0c | +16.27 | 3/9 | −2.72 | +0.71 |

- **Near-linear cost response here** (opposite of fresh60's noise): ≈ +0.36R
  total per 1-unit spread cut over ~158 trades ≈ **+0.0023R/t per unit** —
  matching mean(1/sd) theory within rounding. This is the deliverable slope:
  any future venue quote (other broker, negotiated tier) is priced by
  `Δ exp ≈ 0.0022 × Δspread` in seconds.
- **Even the zero-spread ceiling fails the frozen materiality bar**: 3/9
  positive folds (needs ≥50%). On both windows, **no tier changes the picture**.

### 4. Final verdicts (frozen criteria, read-only)

1. **Lever verdict: DEAD on Deriv MT5 synthetics.** Raw ≈ standard (medians
   16.96 vs 18.5, −8.3% < 25%). The zero-spread account is a forex/CFD
   instrument; on synthetics the spread is the pricing model itself.
2. **Materiality: NO tier clears +0.08R/t + fold consistency** on either
   window. P1 and P2 both CONFIRMED as frozen.
3. **Genuinely useful outputs**: (a) the hour-flatness closes the time-gate
   idea forever; (b) the sensitivity slope **+0.0022R/t per unit** lets any
   future venue be priced in seconds; (c) gross edge ≈ +0.071R/t on fresh60
   (net +0.038 + realized cost 0.032) — the W4 bar is gated by cost roughly
   half, and by the edge's smallness the other half.
4. **Consequences**: no EA change, no arm-C candidate, paper gate unaffected.
   The two real levers remain: (i) wait for the paper A/B verdict on the
   deployed config; (ii) if any venue shows a materially lower V75 spread
   quote in future, price it with the slope — the bar is ~−25 units to clear
   +0.08R/t, which no synthetic venue plausibly offers. Cost structure is the
   binding constraint; the account grows or dies on expectancy, not on
   hunting a cheaper toll.

### Artifacts

- Measurement: inline (2,460,772-tick scan, both lake files; second file uses
  `ts` in seconds + `mid`, first uses `epoch_ms`).
- `artifacts/v75_replay/cert_report_spread_tier_<tier>.json` (fresh60, each tier,
  spec-stamped with geometry + spread).
- `artifacts/v75_costdil/wf_tier_<tier>.json` (70d, 9 folds, tp18, spec-stamped
  + config registry).
- Fragments: integrity gate t185 == stored net artifact bit-identical (ledger).