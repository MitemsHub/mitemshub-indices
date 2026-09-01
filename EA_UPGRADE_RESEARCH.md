# EA Upgrade Research — MITEMSHUB AI on Deriv Boom/Crash
_Compiled 2026-08-30. Sources: web research (Deriv official docs/blog, an independent 15M-tick study, MQL5 docs & forum, GitHub, Reddit/deriv community) + hard verification against our own recorded tick/journal data from the live account._

---

## 0. Executive summary

The single most important finding: **the Boom/Crash spike process is memoryless, and the spread is the dominant cost.** Everything else follows from those two facts. The EA's current edge claims (post-spike timing, "spike is due" hazard, hourly drift regimes) are not supported by 15M ticks of independent research — and our own recorded day agrees (mean spike gap ≈ 17.5 min ≈ 1000 ticks; flat hazard). The realistic path to a genuinely better EA is not a magic timing trick; it is:

1. **Honest accounting** (spread + spike slippage per trade, in the journal),
2. **Hazard-aware exits and sizing** (P(spike during hold) drives TP/SL/hold geometry and position size),
3. **Instant execution telemetry** (OnTradeTransaction instead of polling),
4. **Offline validation loop with pre-registered kill criteria** (we already record every tick — use it properly),
5. **Wire in the already-built-and-tested intelligence** (GARCH forecaster, Hurst/regime engine — they exist in this repo but are NOT running in the live EA),
6. **Expand to the new Deriv markets** (Crash/Boom 150, Flip, Hybrid) where the same machinery generalizes.

---

## 1. Hard numbers from our own data (Aug 30, recorded tick CSVs)

| Quantity | Measured value | Implication |
|---|---|---|
| Tick rate | 0.957 ticks/sec | 1000 ticks ≈ 17.4 min → spike rate λ ≈ 0.057/min |
| Mean gap between ≥3pt spikes | 17.5 min (n=7 gaps) | Matches λ = 1 spike / 1000 ticks almost exactly |
| Spike sizes seen | 3.4 / 4.3 / 5.4 / 6.8 / 7.5 / 7.6 / 8.7 / 11.0 pts | Realized spike loss on a held fade ≈ 4–10R |
| Spread (ask−bid) | **constant ≈ 0.483 pts** (max 0.4832) | = 57% of the 0.855-pt fade stop — a fixed tax on every round trip |
| Planned vs realized loss | planned −1R; realized −6.4R and −7.0R | Spikes gap *through* stops; SL cannot cap tail loss |

**Hazard math (memoryless model, λ = 1/17.3 min):**

- P(spike during a hold of T minutes) = 1 − e^(−T/17.3) → T=10min: 44%, T=20min: 69%, T=25min: 76%.
- Today's tick-fade geometry: TP ≈ +8.75R gross, E[loss | spike during hold] ≈ 6.7R (observed).
- Break-even spike probability ≈ 8.75 / (8.75 + 6.7) ≈ **56.6%** → achieved by holding ~13.5 min.
- Full hold-to-TP (~25 min) ⇒ p ≈ 76% ⇒ EV ≈ 8.75·0.24 − 6.7·0.76 ≈ **−3.0R** (before spread). The trade that won (+8.75R) survived a 29.6-min gap — luck, not edge, under the memoryless model.
- **Conclusion:** exit geometry (TP/hold), not entry timing, is where the expectancy lives or dies. This must be optimized on net-of-spread data, then walk-forward validated.

---

## 2. What the internet says (sources that actually matter)

### 2.1 The 15M-tick pre-registered study (Medium, Apr 2026 — repo: `Orphy123/deriv-research`)
Independent researcher, 90 days, 15.19M ticks from Deriv's MT5 feed, pre-registered protocol with kill gates:
- **Spike process is memoryless (Poisson-like):** KS test vs exponential fails to reject (Boom p=0.26, Crash p=0.07); hourly dispersion index 0.895/0.856 (negligibly under-dispersed); lag-1 autocorrelation of inter-arrivals ≈ 0; empirical hazard flat at λ ≈ 0.0009/s (≈ 1 spike/18.5 min — consistent with our 17.5-min census).
- **Post-spike drift = random windows:** 16 comparisons (2 symbols × 2 thresholds × 4 window sizes), zero at p<5%. In some configs post-spike drift was *worse* than random.
- **Hourly drift regimes are white noise:** drift-variance explained by spike count alone ≈ 72–74%; residual autocorrelation −0.041/−0.018 (kill gate was |ACF| ≥ 0.15 — failed by 4–8×).
- **Take-away for us:** "wait for a spike, then trade the calm" has no statistical basis; hourly "clean session" filters are placebo. Our EA's `m_prob_time_since_spike` term (25% weight in spike probability) is the classic gambler's fallacy and should be replaced by a constant-λ model (Gamma–Poisson online estimate of the rate). Note the *mild under-dispersion* (0.86–0.90) — real but tiny; not a tradable edge at our sample sizes.

### 2.2 Deriv official
- Crash & Boom 150 (added Oct 2025): spikes on average **every 150 ticks** (≈ 2.6 min at our tick rate). High-frequency variant of the same mechanics; λ = 1/150 per tick. New SymbolCalibration profile candidate.
- **Flip indices** (Deriv blog, Aug 2026) and **Hybrid indices** (synthetic + real-market behavior): new families; hybrids behave differently (real-market microstructure) → different edge class, worth a separate pre-registered study before trading.
- Deriv's own social post confirms Boom/Crash **stop-losses can fill at a different price during spikes** — the gap-through behavior we measured (-6.4R/-7.0R realized on -1R planned stops) is structural, not a bug.
- **Zero Spread MT5 account exists for synthetic indices** (added to Zero Spread July 2025): zero spread, fixed commission per lot instead. Our measured 0.48-pt constant spread vs stop distances of 0.855–1.07 pts makes a commission-vs-spread A/B test on demo one of the highest-leverage, lowest-risk experiments available.

### 2.3 Community (Reddit, Deriv forum, GitHub)
- Reddit (r/FOREXTRADING, r/Forexstrategy, r/Kenya threads): virtually all Boom/Crash retail content is EMA-crossover + stochastic + "catch the spike" recipes — exactly the class of strategy the 15M-tick study falsifies. Nothing to import, but confirms our EA is already above community state-of-the-art.
- Deriv forum "Spike-Catching Strategy" thread: EMA(5/15) cross + >50-pip move + stochastic confirm. Naive; the interesting signal is that the top replies admit SL losses exceeding the stop — spike slippage again.
- GitHub: `EarnForex/Spike-Trader` (fade-the-spike on D1 forex — same *shape* of idea as ours, but not synthetic-aware); `PetrJoe/sophisticated-mt5-trading-bot` and the `synthetic-indices` topic bots are simple direction-followers. No repo found doing tick-microstructure fade work at our level — our recorder + replay harness is the differentiator.

### 2.4 MQL5 engineering best practices (docs + forum)
- **`OnTradeTransaction`** is the event-driven way to detect fills/closes (DEAL_ADD with the closing deal's price, reason, entry/exit type) — no polling, no full-history rescans. Our EA currently *polls*: `HistorySelect(0, TimeCurrent())` full-history scans when a ticket vanishes. Replace with a transaction handler that `HistoryDealSelect(deal_ticket)`s the single deal — O(1), and it kills the whole class of manual-close detection bugs (v24.11 fixed one such bug; the polling design invites more).
- **`CopyTicks` / `CopyTicksRange`**: use to reconcile the recorder (OnTick can drop ticks while the EA is busy); synthetics keep only shallow tick history server-side, so our recorder remains the ground truth — but gap-fill via CopyTicks should be tested (depth limits on synthetics unverified).
- **Strategy Tester**: for synthetics, bar-derived tick generation is a lie (spikes are single-tick events). Where real tick history is too shallow, replay our own recorded CSVs (we already have the harness). Add an **`OnTester()` custom criterion** (e.g., expectancy × √trades with a drawdown penalty, or net-of-cost profit factor) and use the tester's built-in **Forward mode** as a first-line walk-forward.

### 2.5 Quant literature applicable here
- **Meta-labeling / triple-barrier labeling (López de Prado, *Advances in Financial Machine Learning*):** keep the primary signal (tick-fade), train a secondary model to predict P(win | context) per trade; use it as a size multiplier (fractional Kelly), not a binary filter. Our per-strategy/regime/time tables + telemetry JSONL (which already logs every SKIP with its reason) are exactly the training corpus.
- **Fractional Kelly with hazard-adjusted loss distribution:** size k* = edge/odds, then take a quarter; the "odds" must use E[loss | spike during hold] measured from our tick data, not the nominal −1R.
- **Pre-registration + kill criteria (the deriv-research methodology):** before any new edge hypothesis (e.g., tick-precursor prediction), write the hypothesis, thresholds, and kill gates into the repo *before* running the test. Our repo already has a contracts/verification culture (`verify_all.ps1`, locked references) — extend it to strategy research.
- **Walk-forward with purge/embargo:** rolling re-fit windows with an embargo gap so spike-adjacent information can't leak across the split.

---

## 3. What our own EA does *not* yet use (free wins sitting in the repo)

The live monolith (`MitemshubAI.mq5`) includes only `Trade.mqh` + the CrashBoom modules. Meanwhile the repo contains a **fully tested, phase-gated intelligence stack that is not wired into live trading**:

| Already built & unit-tested | Phase tests | Live status |
|---|---|---|
| `Market/GarchForecaster.mqh` (EGARCH(1,1) σ forecast, calibrated + online-SGD modes) | Phase10 ✅ | **not included in live EA** |
| `Regime/RegimeEngine.mqh` + HurstAnalyzer + range/expansion/transition detectors | Phase2 ✅ | live EA uses plain EMA stacking instead |
| `Structure/*` (BOS/CHOCH/displacement/swing) | Phase3 ✅ | unused live |
| `Decision/ScoringEngine` + `ConfidenceEngine` + `TradeQualityEngine` | Phase5 ✅ | live EA has its own ad-hoc scoring |
| `Risk/RiskEngine` + `PositionSizer` + `DrawdownProtection` | Phase6 ✅ | live EA hand-rolls risk |
| `Journal/*` (TradeJournal, DecisionLogger, PerformanceLogger) | Phase8 ✅ | live EA writes its own CSVs (and both instances share one state file — cross-contamination bug) |

Wiring the validated stack into the live monolith (or migrating to the modular build) is the highest-value "smarter" upgrade available — it was already built and locked against Python references.

---

## 4. Prioritized roadmap

### P0 — this week (cheap, safe, verifiable)
1. **OnTradeTransaction close detection.** Delete the polling `HistorySelect(0,now)` path; handle DEAL_ADD/DEAL_ENTRY_OUT instantly. Also fixes the "MANUAL" mislabeling.
2. **Cost accounting in the journal.** Log per trade: entry ask vs exit bid, spread paid (pts and R), realized R vs planned R (slippage). From today's data: spread = 0.48 pt = ~0.55R per round trip — it must appear in every expectancy number.
3. **Replace the gambler's-fallacy hazard term.** `m_prob_time_since_spike` (0.25 weight) → constant-λ model with a Gamma–Poisson online estimate of spike rate from live tick counts. Re-derive `DynamicRiskSizing` thresholds from P(spike during hold) instead of "spike is due".
4. **Per-symbol state/telemetry files** (`MitemshubAI_state_<symbol>.csv` etc.) — Boom and Crash instances currently clobber each other's learning memory.
5. **Honest HUD line:** `Today: -4.63R | Spread paid: 1.44pt | Spike hits: 2` so exposure is visible now that the daily halt is off.

### P1 — validation (before any new live behavior)
6. **✅ DONE 2026-08-30 — Grid-search exit geometry on our own recorded ticks:** 1,296-config sweep (SL × TP × FADE_R × retrace-ceiling × hold) over all three recorded sessions, net of spread (`scripts/cb_exit_grid_search.py`, results `artifacts/cb_exit_grid_results.txt`). Incumbent (SL 0.4/TP 3.2/R 0.3/2400s) ranked #387; the robust winner (only 27/1296 passed the F1–F4 gates: per-session floor, ATR ±20%, spread ×1.5) is **SL 0.3×ATR / TP 4.0×ATR / FADE_R 0.4 / hold 1800s** — Boom 08-30 flips −9.5R → ≈+13.6R. Deployed to both .set files (v26.8); walk-forward re-check pending as more tick days accumulate.
7. **Meta-labeling prototype (Python)** on `review.csv` + telemetry JSONL: features = (strategy, regime, z, exp-ratio, spike prob, retrace %, jump size, time-of-day, consec state) → P(win). Deploy as size multiplier.
8. **Pre-register each hypothesis with kill gates** (adopt deriv-research's protocol style; e.g., "tick-fade expectancy net of spread after ≥50 trades must be > 0, else mode disabled").

### P2 — bigger bets
9. **Wire the modular stack into live** (RegimeEngine+Hurst, GarchForecaster σ, RiskEngine, Journal modules) — or move live trading onto the modular build; it's already phase-tested against Python references.
10. **Crash & Boom 150 profiles** (λ=1/150 → ~2.6-min spike rhythm; different optimal hold/TP; SymbolCalibration profile + demo pilot). Also evaluate Flip and Hybrid indices with their own pre-registered protocols.
11. **Zero-spread account A/B on demo:** commission-per-lot vs 0.48-pt fixed spread at our typical 0.20-lot size; adopt whichever wins, then revisit stop/TP geometry again (cheaper costs change the optimum).
12. **Portfolio tail diversification check:** Boom-fade and Crash-fade tails are independent (Boom spikes UP kill Boom-shorts; Crash spikes DOWN kill Crash-longs); measure joint drawdown distribution from recorded data before scaling fleet size.

---

## 5. Kill criteria (so "better" stays honest)

- Any new mode runs **demo-first** until ≥ 50 closed trades with net-of-cost expectancy > 0 (auto-disable already exists per-strategy — extend it to whole modes with a minimum-sample gate).
- Spike-slippage reality check: no stop geometry is "safe" on Boom/Crash; size for E[loss | spike], not for the nominal stop.
- If a hypothesis fails its pre-registered gate, it dies — no threshold-tweaking afterwards.

## 6. Source list

- Medium (Oheneba Berko, Apr 2026): "I Analyzed 15 Million Ticks of Deriv Synthetic Data…" + `github.com/Orphy123/deriv-research`
- Deriv Traders Academy: "Crash & Boom 150: Timed spikes…"
- Deriv Blog (Aug 2026): "Flip vs Crash and Boom Indices explained"; Hybrid Indices guide
- Deriv community forum: "Spike-Catching Strategy for Boom and Crash"; "Calculation of Zero Spread Commission"
- Deriv official social post: Boom/Crash SL fills at different prices during spikes
- GitHub: `EarnForex/Spike-Trader`; `PetrJoe/sophisticated-mt5-trading-bot`; `synthetic-indices` topic
- MQL5: `OnTradeTransaction` reference/book; "Testing trading strategies on real ticks" (article 2612); "Custom Walk Forward optimization" (article 3279); "Creating Custom Criteria of Optimization" (article 286)
- Reddit: r/FOREXTRADING, r/Forexstrategy Boom/Crash threads (community signal check)
- López de Prado, *Advances in Financial Machine Learning* (meta-labeling, purged CV, deflated Sharpe)

---

## 7. v26.0 burst-guard offline backtest (added 2026-08-30, post-implementation)

Replay harness: `scripts/cb_burst_guard_backtest.py` — replays the deployed
v25.7 tick fast-fade on the EA's own recorded tick CSVs (artifacts/ticks/),
then re-runs the identical stream with the v26.0 burst guard (cluster + min-gap
rules exactly as wired in CrashBoomEngine.OnTickFade), plus a 24-config sweep.

Credibility checks:
* **Crash 08-30: sim reproduced all 3 live entries to the second** (18:50:41,
  19:23:57, 19:35:06; exits match within one tick) — harness validated against
  ground truth. The 2 sim-only entries are trades live never took because the
  daily-loss halt was active.
* **Boom 08-30: 4/7 live entries reproduced exactly; the other 3 are the same
  spikes with entry-timing gating differences.**
* ATR(±20%) sweep: Crash day flips +1.41R → −2.23R/−2.61R — exit geometry, not
  entry timing, drives the outcome (confirms §1 hazard math).

Results (net of spread, gap-safe; guard = window 1800s / max 2 / gap 600s):

| Session | Baseline R | Guard R | Δ | Blocks | Blocked winners / losers |
|---|---|---|---|---|---|
| Crash 08-30 | +1.41 | +1.32 | −0.09 | 3 | 1 winner (+8.0) / 2 losers (−7.7, −0.2) |
| Boom 08-30 | −1.07 | −8.78 | **−7.71** | 9 | 4 winners (+20.2R forgone) / 5 losers (+12.4R saved) |
| Boom 08-29 | +31.51 | +26.58 | **−4.93** | 2 | 2 winners (+12.8R forgone) / 0 losers |
| **Total** | **+31.85** | **+19.12** | **−12.73** | 14 | ~40.9R forgone / ~20.4R saved |

maxDD: Crash 14.59 → 6.68 (halved ✓); Boom 08-30 11.55 → 14.17 (worse ✗);
Boom 08-29 6.93 → 6.93 (=).

Verdict:
1. The guard is a **tail-throttle, not an edge**: it saved ~20.4R of loser-fades
   but forwent ~40.9R of winner-fades. Consistent with the memoryless-spike
   research (§2.1) — "clustered" is not predictive.
2. On **Crash** it is nearly free (−0.09R) and halved the drawdown while
   blocking the exact trade that caused the live day's collapse — keep ON.
3. On **Boom** it is expensive at every clustering config that actually fires
   (Boom's winners live inside evening bursts); no swept config beat the
   baseline on both Boom days — set `InpCBBurstGuard=false` on the Boom chart.
4. Pre-registered re-test: accumulate ≥20 recorded sessions, re-run this
   harness weekly; keep the guard on a symbol only if blocked-trade
   counterfactual expectancy > 0 AND maxDD is not worse on that symbol.

Ops findings from the Experts log (2026-08-30):
* The Boom EA was recompiled/re-attached ~9× during the day (v23 → v25.7 →
  v25.8 → v25.9 "New day" resets in the log) — every re-attach wipes the
  in-memory learning state; Boom's 7 live tick-fades today never reached
  `MitemshubAI_review.csv` (orphaned trades across restarts).
* Combined with the shared state-file issue (§P0-4), the Boom instance's
  self-review memory is effectively unreliable until per-symbol state files
  land.

**FIXED (v26.1):** state/review/telemetry files now carry a per-symbol suffix
(`MitemshubAI_state_Crash_1000_Index.csv`, `MitemshubAI_review_Boom_1000_Index.csv`,
`MitemshubAI_v23_telemetry_<symbol>.jsonl`) — the two chart instances no longer
clobber each other's learning state. Old shared files remain on disk as an
archive; each symbol's counters start clean on first deploy of v26.1.

**FIXED (v26.3):** day-scoped counters now survive re-attaches too. The state
file gained a `DAILY` record (day-start epoch, daily P&L, session P&L, trades
today, day-start equity, consec losses, paused flag, cooldown bars) that is
restored at init — so a mid-day re-attach no longer prints "New day" and wipes
daily P&L / the consec-loss pause / cooldown (the Aug-30 failure mode). A stale
day still resets normally at server midnight, and the reset itself is persisted
immediately.

**Deploy note (Aug-30 log):** the Boom chart was running an OLDER compiled
binary (log tags v25.7→v25.8 vs Crash's v25.9) — a plausible cause of Boom's 7
live tick-fades missing from the journal. After each source change, BOTH charts
must be recompiled and re-attached with the same fresh build; the HUD version
line makes mismatches visible.
