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

## Artifacts

- `scripts/v75_spread_tiers.py` (measurement + engine harness, spec-stamped).
- `artifacts/v75_replay/cert_report_spread_tier_<tier>.json` (fresh60, each tier).
- `artifacts/v75_costdil/cert_report_spread_tier_<tier>_f<fold>.json` — robustness
  fold runs (WF harness repeated per tier, `WF_OUT` per tier).
- Results + verdicts written into this doc; changelog entry; committed.