# LIVE READINESS — v26.34 (2026-09-04, post operator-steps 2+3)

## State after today's setup (all machine-side DONE)

| Component | Status |
|---|---|
| Terminal A (arm A) | **LIVE-RUNNING**: v26.34, paper, TP 1.8, magic 7788075, router TOLERATED (risk 12.5%/trade @ $50 virtual) |
| Terminal B (arm B) | **LIVE-RUNNING**: v26.34, paper, TP 2.4, magic 7788100, router TOLERATED — installed via cloned instance at `%LOCALAPPDATA%\MitemshubMT5_B`, data folder `49E0383C…`, auto-attach verified in Experts log |
| chart04 landmine | **GONE** (MT5 exit-flush dropped it; Default profile = chart01 with EA + one plain chart) |
| Sunday 06:30 pipeline | Armed; discovers arms automatically at each arm's first closed trade |
| `MitemshubAI_VOL75_LIVE.set` | **NEW, validated (PASS)**: identical to `VOL75_FINAL` except `InpLiveExecution=true` (TP 1.8, magic 7788075) |

## The "$10 account" question — broker-math answer

The EA's min-lot risk router (`order_calc_profit`-based, verified against the EA's own FIT ROUTER line):
**V75 min lot 0.01 ⇒ $6.19 stop-risk per trade at current ATR ⇒ minimum equity $30.93 at the 20% cap.**

| Account size | What happens on V75 |
|---|---|
| $10 | **Every signal vetoed** — min-lot risk $6.19 > $2.00 cap. The router would print CANNOT FIT. No EA can trade V75 at $10 without breaking the 20%-of-equity cap; this is a broker lot floor, not a strategy defect. |
| $31+ (min viable) | Trades, but ~20% of equity at risk per trade. |
| $50 (today's replay basis) | ~12.5% per trade — this is what the paper run tests. |
| $100–200 | 6.2%/3.1% per trade — first sizes where a normal loss streak cannot destroy the account. |
| $2,800+ | V100 becomes available as a second instrument (uncertified — funding follows certification, so V75 only for now). |

Cent accounts or a broker tier with 0.001 min-lot would make $10 viable; on this broker, **$31 is the true floor and ~$100 the sane floor.**

**Funding-growth plan (Monte-Carlo, `artifacts/v75_replay/funding_plan.md`, regenerable via `scripts/funding_plan.py`)**: at $31 the account hits the min-lot veto in 93% of shuffled trade orderings (median outcome below the floor) — not viable. At $50, 59% of orderings touch the veto (aggressive tier only). **$100 is the recommended start**: 97.6% of orderings profit, and because min-lot sizing is equity-invariant above the veto, the dollar outcome is path-independent. Withdrawals: **weekly, everything above a $100 working buffer** — at $100 start that banked $92 in 60 days with equity never below $72. Keep the buffer ≥ 2x the $31 floor at all times. *(Superseded 2026-09-05: those figures were gross of spread — see the cost-inclusive update at the end of this document.)*

## What the freshest replay says (60 days, Jul 7 → Sep 4, includes the last 4 weeks live-market data)

| Config | Trades | Total R | $ on $50 start | Max DD | Worst streak |
|---|---|---|---|---|---|
| **TP 1.8 (arm A / LIVE preset)** | 135 | **+13.23R** | **$50 → $114.76 (+130%)** | 42.2% | 5 losses |
| TP 2.4 (arm B) | ~135 | +4.60R | $50 → $68.59 | — | — |

Third consecutive fresh window where TP 1.8 leads. Also honest: +130%/60d comes **with** a 42% max drawdown and 19% per-trade risk — that is the price of min-lot sizing on $50, it is not free money, and on $100+ the same trades risk ~6% each with the same dollar expectancy.

## GO-LIVE GATE (pre-registered — do not skip)

Live trading is authorized when **all three** hold:

1. **Paper A/B adjudication**: arm A expectancy positive over ≥30 closed trades (fires automatically in the Sunday pipeline; `ab_adjudicate.py` prints the verdict). Expected ~2–3 weeks at current signal rate.
2. **Tick reconciliation PASS**: `reconcile_paper_ticks.py` reports paper fills within tolerance of the 1.5M-tick baseline (runs automatically at ≥7 days of ledger).
3. **Watchdog CERTIFIED** on the morning check (already green; must stay green).

**Accelerated option** (if you accept earlier risk): after gate 3 plus **20 closed arm-A trades with positive expectancy and reconciliation PASS on ≥5 days**, deploy live at the minimum viable size ($50), keeping the paper arms running for the full A/B.

## Deploying live (when the gate passes)

1. Terminal A → chart01 → remove EA → re-attach **MitemshubAI** → Load **`MitemshubAI_VOL75_LIVE.set`** → confirm banner shows `LIVE` (not `PAPER MODE`) and magic 7788075 → OK.
2. Same account, same chart, **one EA on V75 only** — never also load TP24/LIVE on a second chart in the same terminal.
3. Start with broker equity ≥ $50 (floor $31). Withdraw profits on a schedule; the EA carries no deposit-protection, the 20% cap is the only brake.
4. First week live: run `python scripts/morning_status.py` each morning (arm health, overnight connection gaps, closed-trade counts, gate progress X/30 — read-only) and `python scripts/paper_pipeline.py` daily; compare live fills against the paper ledger (same signals should print in both — any divergence means the live attach drifted from the preset).

## Non-negotiables

- **Live only ever on terminal A chart01**, magic 7788075. The paper arms and any other attachment stay paper forever.
- If the A/B verdict favors TP 2.4, update the LIVE preset's `InpTpMult` **only after** re-reading the adjudication — never tune live by hand.
- The demo account currently holds **$0.57** — before any live attach, fund the live account; the router will refuse to fire until equity ≥ ~$31 (by design).

---

## 2026-09-05 UPDATE — cost-inclusive re-baseline (spread now paid in PnL)

The external critique found that `certify_v75.py` never subtracted the 18.5-unit
spread from PnL (it was only a veto gate). **Fixed**: fills now pay half the
spread at entry and half at exit; stop/TP geometry anchors to the real fill
exactly like the EA. `CERT_COST_LEGACY=1` reproduces the old engine and was
verified **bit-identical** (+13.23R / 135 / 48.1%) before re-baselining.

Fresh 60 days (Jul 7 → Sep 4), $100 start:

| Config | Trades | Total R (net) | $ on $100 | Max DD | Net expectancy |
|---|---|---|---|---|---|
| **TP 1.8 (arm A / LIVE preset)** | 114 | **+4.37R** | $100 → $103.42 | 36.7% | +0.038R/trade (t = 0.35) |
| TP 2.4 (arm B) | 68 | **−4.07R** | −$28.16 | 61.3% | negative |

What changed vs the gross numbers:

- **TP 2.4 is negative net of costs.** The paper A/B now adjudicates
  "marginal positive vs negative" — the gate matters more than we thought.
- **Trade count drops 135 → 114**: costs turn flat trades into small losers,
  which triggers the governor's auto-disable (MOM+PB disabled at −2.08R) and
  more pauses. PB alone still carries +6.22R.
- **Funding table re-priced on the net stream**: $31 dead (P(profit) 10%),
  $50 a coin flip (39%), $100 survival 92% — but median 60-day outcome only
  **+$3.42**, and the 5% worst case grinds to ~$23. Edge and survivability are
  now the same conversation.
- **Honest standing claim**: net expectancy on this window is statistically
  indistinguishable from zero. The pre-registered gate — ≥30 live arm-A paper
  trades with positive expectancy + tick reconciliation PASS + watchdog green —
  is therefore the ONLY authorizer of live trading. If arm A's live net
  expectancy is not positive at the gate, we do not go live on this config;
  we investigate (spread regime, session mix, governor interactions) instead.

Artifacts: `cert_report_fresh60_tp18_net.json`, `cert_report_fresh60_tp24_net.json`,
`cert_report_fresh60_tp18_net100.json`, `cert_report_legacy_repro_tp18.json`,
`funding_plan.json` (regenerated on the net stream).

**2026-09-05 morning verification**: both engine modes re-run fresh — legacy reproduces
its artifact bit-identically (all 135 trades equal), all three net re-baselines reproduce
exactly (`*_check0905.json`). Found and fixed a CLI-only crash in the trade-dump print
(`r_extra` popped from trades before `main()` printed them; reports were written before
the crash — engine math untouched). Preset validator 15/15 PASS.

**2026-09-05 pre-data drill**: the entire paper-data path (wire-format ledger → A/B
adjudication → reconciler gate → status parsing) proven on synthetic ledgers
(`scripts/first_trade_drill.py`, 10/10). Caught two adjudicator bugs before any real
data: pairing used CLOSE epochs instead of the frozen OPEN-epoch rule, and zero pairs
crashed the verdict. Both fixed. `scripts/morning_status.py` = the one-command morning
check (arms, gaps, gate X/30).
