# V75 MITEMSHUB AI — Milestone Memo: v26.35 & the Cost-Inclusive Re-Baseline

**Date:** 2026-09-05 · **Status:** pre-live, paper A/B collecting · **Commit:** `8d155fe`

## The one-paragraph version

The project reached its pre-live milestone: a full line-by-line audit fixed four EA bugs
(the critical one had silently vetoed every paper trade for weeks), the certification
engine was corrected to pay the 18.5-unit spread inside PnL — not just use it as a veto
gate — and every flagship backtest number was re-baselined on the honest, cost-inclusive
stream. A four-scenario external critique was executed under a pre-registered protocol
and confirmed the cost flaw while *rejecting* the critique's structure claims. The paper
A/B (TP 1.8 vs TP 2.4) is now genuinely running on both terminals, and a pre-registered
go-live gate — not a backtest — is the only authorizer of live capital.

## What was claimed before, and what the re-baseline changed

| Claim (cost-blind engine) | Honest re-baseline (spread paid in PnL) |
|---|---|
| Fresh-60 TP 1.8: **+13.23R**, $50 → $114.76 (+130%) | **+4.37R**, $100 → $103.42; net expectancy +0.038R/trade (t = 0.35) |
| TP 2.4 arm: +4.60R (marginal positive) | **−4.07R — negative net of costs** |
| Funding: $31 viable, $50 aggressive-ok | $31 dead (10% P(profit)), $50 a coin flip (39%), **$100 the sane start** |
| 135 trades / 60d | 114 trades (costs convert flat trades to losers → more governor pauses) |

Net expectancy on the certified window is **statistically indistinguishable from zero**.
That sentence is the milestone: the project now prices its own edge honestly, and the
deployment decision moved from "backtest says +130%" to "the pre-registered gate decides."

## The critique replication (executed, not argued)

An external critique made four demands. Under a frozen, one-pass protocol:
- **Cost flaw: CONFIRMED and quantified** → engine fixed, re-baselined (above).
- **Small-sample "certification": CONFIRMED as a fair concern** → adopted: the Wilson
  lower bound, per-trade t, and the ≥30-trade live paper gate replace the old framing.
- **Band Fade contradiction: REJECTED** — BF is already spread-gated OFF on V75
  (100% of BF entries were vetoed live; documented since v26.27).
- **EMA regime as noise: CONFIRMED against the EA's own interest** — the regime axis
  carries *no directional information* (8/8 era/horizon slices weakly anti-continuation).
  Its remaining role is volatility-aware gating/sizing only, which is how the EA uses it.

Supporting studies the same week: the generator fingerprint (V75 is a memoryless 0.5 Hz
step machine — tick-speed reflexes are coin-flips by construction), the drift-vs-Σ
tracker (closed 1/3, no EA change), and the MOM-standalone duel (REJECT — the lone-
momentum demotion the EA already runs is correct).

## What v26.35 fixed in the EA (all four verified in audit doc `FULL_EA_AUDIT_v2635.md`)

1. **CRITICAL (paper):** account guard compared fleet risk against *real* equity while
   sizing used paper equity → every paper entry vetoed ($0.57 real vs $50 virtual).
   This was the root cause of the weeks-long paper silence. Guard now uses the same
   equity basis as sizing.
2. **HIGH (live):** out-of-range strategy slots returned "enabled" — a latent governor
   bypass. Now fail-closed.
3. **MEDIUM (live):** default magic was an orphan (7788211) invisible to the fleet
   guard. Now 7788075.
4. **COSMETIC:** self-test banner format bug. Fixed.

Deploy gate: MetaEditor 0 errors/0 warnings, `.ex5` synced to all instances, preset
validator 15/15 PASS, both paper arms auto-restored and TOLERATED by the fit router.

## The go-live gate (pre-registered 2026-09-04 — the only authorizer)

1. **Paper A/B adjudication**: ≥30 closed arm-A trades with positive expectancy
   (fires automatically in the Sunday pipeline; paired-test rule in `ab_adjudicate.py`).
2. **Tick reconciliation PASS**: paper fills within tolerance of the 1.5M-tick baseline
   (self-arms at 7 days of ledger).
3. **Watchdog CERTIFIED** on the morning check (currently green, 36/0/28).

**If the gate passes** → live on terminal A only, `MitemshubAI_VOL75_LIVE.set`, magic
7788075, minimum sane funding $100 (floor $31 is veto-death on this broker). **If arm A's
live net expectancy is not positive at the gate** → investigate (spread regime, session
mix, governor interactions) — do **not** deploy. Non-negotiables: live only ever on
chart01/terminal A; paper arms stay paper forever; no hand-tuning live.

## Honest standing risks (recorded, not buried)

- The 60-day net edge is indistinguishable from zero — the gate may correctly say no.
- +$50 virtual-equity sizing risks ~12.5%/trade by construction (min-lot floor); the
  real $100 start halves that; the 20% effective-risk cap is the only brake.
- Every small-sample lead this project chased (August filters, mid-z gate, V100 stack
  flip) died under power. The pre-registered protocol discipline is the reason none of
  them reached the EA — the same discipline now binds the go-live decision itself.
- Weekly MT5 access-point flaps and PC sleep shrink the effective signal-collection
  window; harmless for correctness (broker archives are pullable on demand), but they
  stretch time-to-verdict.

## Where this leaves the project

Data collection. Sunday 06:30 the pipeline adjudicates automatically and diffs every
verdict; the morning status tool (`scripts/morning_status.py`) reports arm health,
overnight gaps, and gate progress X/30 in one command; the first-trade drill
(`scripts/first_trade_drill.py`, 10/10 green) has already proven the entire paper-data
path — and caught two adjudicator bugs — before the first real fill. The next
meaningful event is the first closed paper trade, then 30 of them.
