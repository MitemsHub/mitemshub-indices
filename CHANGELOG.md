# Changelog

All notable changes to Synthetic AI Trader are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Arm C activation rehearsal: minutes-scale promise PROVEN] - 2026-09-05

### Executed — supervised 10-minute run of docs/ARM_C_TEMPLATE.md, verbatim
- **T0 12:22:46** → `authorized '140778269' on DerivSVG-Server-03` at **T+6s** → full v26.35 banner (SELFTEST OK, GARCH ready, 200-bar cold-start catch-up, `PAPER MODE: virtual equity $50.00`, tick value calibrated, `FIT ROUTER ... TOLERATED` $4.59 at live spread) at **T+8s**. Pre-flight had verified the `common.ini` login pointer (UTF-16 — plain grep reads nothing), chart magic 7788125, paper mode, and the fleet (2 running: A, B; C off).
- **Steady state**: EA evaluated real bars (first `sig`/SKIP telemetry event), state CSV fresh; telemetry quiet-window behavior matched healthy arm B exactly (event-driven cadence — recorded in the template so nobody misreads quiet as dead).
- **Parked** at T+23min — about 1 minute of procedure, the rest deliberate observation — via PID-from-ExecutablePath kill; A/B untouched, both wrote telemetry at the next M15 close. Time-to-operational ≈ **1 minute**; the doc's "minutes, not hours" promise is now measured, not assumed.

## [Spec-integrity guard: cross-instrument cert runs must STATE their specs] - 2026-09-05

### Added — the V100 0.01-lot lesson, made mechanical
- `certify_v75.py`: `assert_spec_integrity()` runs inside `certify()` — if `CERT_DATA_DIR` is set, all four spec variables (`CERT_SPREAD`, `CERT_USD_PER_UNIT_PER_LOT`, `CERT_MIN_LOT`, `CERT_LOT_STEP`) must be explicit or the run **exits 1 before any data pull**, with the correct V75 truth printed in the error. Default V75 runs (no `CERT_DATA_DIR`) are exempt: the defaults ARE the V75 truth. Every caller (walkforward, study scripts) is covered transitively.
- **Spec stamp in every artifact**: `spec_block()` — data_dir, spread, usd/unit/lot, min_lot, lot_step, cost model, geometry (`tp_mult`/`stop_mult`/`min_score_bonus`), which env vars were explicit, guard version — is written into every `cert_report_*.json` and every walk-forward artifact (which also stamps its full config registry). An artifact whose sizing implies a lot grid the instrument cannot trade is now self-identifying as invalid.
- `z_gate_phaseA.py` declares its specs explicitly (its data IS V75, pulled via `pull_v75_week`) — custom-dir runs state them like anyone else.

### Verified — four-point battery, all green
- **T2 loud-fail**: non-V75 dir without specs → `SPEC-INTEGRITY FAIL`, exit 1, no artifact written. **T2b**: z_gate's import satisfies the guard via module-level setdefaults. **T3**: explicit specs run clean and the stamp reflects them.
- **T1 bit-identity**: legacy fresh60 re-run at `--tp-mult 1.8` equals the stored 09:01 artifact on all 135 trades and every metric. Two footguns surfaced and were resolved honestly: (1) the CLI's default is `TP_MULT_CERT = 2.4` — omitting `--tp-mult 1.8` silently certifies the wrong geometry (now visible in the spec stamp's `geometry` block); (2) the stored artifact's `funnel.paused` is 947 vs 948 in every re-run — **including from a pristine worktree of the committing SHA**. A gap-aware reconstruction from the trade ledger independently computes 948, so the ledger-relevant contract reproduces exactly and the stored 947 is attributed to the transient pre-commit working tree (runs 08:58–09:01, commit 09:03). No engine issue.

## [Arm C paper-terminal template: built, validated, PARKED] - 2026-09-05

### Added — docs/ARM_C_TEMPLATE.md: a third paper arm that can start collecting within minutes of an adoption decision
- Clone of B's install at `%LOCALAPPDATA%\MitemshubMT5_C`, data folder `71BF6B2AB5548CFBA970FA2F38007C31`, magic **7788125** (verified unused), chart = arm A's validated paper chart (TP 1.8 placeholder), auto-login verified (`authorized '140778269' on DerivSVG-Server-03`), sync gate PASS, v26.35 banner + FIT ROUTER TOLERATED ($4.65 min-lot risk, 9.3%/trade at $50 virtual) + paper equity $50 initialized.
- **Login gotcha recorded**: `accounts.dat` alone does not enable auto-login — the pointer lives in `config\common.ini` (`Login=`/`Server=`). Also: launch MT5 clones via PowerShell `Start-Process` (Bash `&` hangs on the child's handles), and never kill by image name (the 2026-09-04 terminal-A mishap) — kill by PID from the ExecutablePath.
- **Parked by protocol**: the cost-dilution verdict was NO-ADOPT 5/5 and no study has ever returned VALIDATED-CANDIDATE, so C stays OFF until (a) a candidate exists and (b) the primary A/B adjudicates uncontaminated. A running C before adoption would trade an un-adopted config and mint unread data. Activation is a one-input edit + one Start-Process + a morning-status line.

## [V75 cost-dilution study: NO-ADOPT 5/5 — geometry cannot outrun the spread] - 2026-09-05

### Executed — frozen protocol (docs/V75_COST_DILUTION_STUDY.md), one pass, priors held exactly
- **Amendment before the pull** (transparent, committed): the frozen "28 days yields 8 folds" was arithmetically wrong; the power requirement (≥8 fresh folds) dominates, window corrected to 70 days. One pull (Jun 27 → Sep 5, 6,719 bars), all six arms on the same file, cost-inclusive engine, 9×8-day folds.
- **Result**: ws13 −5.42R/141tr, ws17 −4.27R/128tr, ws25 +1.51R/111tr, lf13 −2.65R/143tr, bs17 −4.27R/128tr vs ref −1.21R/158tr — best variant expectancy +0.014R/trade vs the frozen W4 bar of +0.08R. **All five NO-ADOPT, matching all five frozen priors; the cost-dilution thesis is dead on V75.**
- **Reference-failure clause examined, NOT exercised**: ref printed 3/9 positive folds but worst −3.33R (inside its normal certified range) — choppy window, not a regime break; re-pulling after seeing the reference fail would be outcome-fishing.
- **Descriptive finding**: bs17's folds are identical to ws17's — the MinScore+1 frequency lever never bound at current volatility; MinScore is not a live frequency lever on V75.
- **Consequence**: no geometry lever exists on V75; the path forward is the paper A/B gate on the deployed config, and if a cost lever exists it is broker-side (spread tier), not geometry-side. EA and presets untouched.
- Artifact: `artifacts/v75_costdil/costdil_results.json` (+ `walkforward` env block in the doc).

## [V100 net-edge study: NO EDGE + 2y artifact retracted] - 2026-09-05

### Executed — pre-registered study (docs/V100_NET_EDGE_STUDY.md): does the gross edge survive V100's 15x-lower spread cost? NO.
- **Integrity gate caught a systemic confounder first**: the stored Sep-4 2y/210d "gross" V100 runs set spread+tick-value but left `CERT_MIN_LOT/CERT_LOT_STEP` at V75's 0.01 defaults — a broker-impossible lot grid for V100 (true floor 1.0). Every signal traded on negligible dollar size (`max_risk_pct: 0.5` gives it away). Old-code vs new-code on identical envs agree bit-exactly, so the cost refactor was not the cause.
- **Q1 (survival) — the edge DIES.** True-spec net walk-forward, 53×14d folds, ~1,700 trades/config: legacy +29.21→**−20.06R**, v2629 +13.86→**−20.07R**, tp18 +23.09→**−24.55R**. Per-trade cost ≈0.028R (2–3× the naive arithmetic — the −62% price grind shrinks stops while the spread stays fixed, so cost share *rises* over time). Full-period cert at $200: $200→$17.61, DD 94.9% — the true 1.0-lot floor plus early-era wide stops risks up to 20%/trade.
- **Q2 (gate) — nothing passes V1–V6**, matching the frozen prior. V100 stays uncertified; funding follows certification; EA unchanged.
- **Retraction**: the Sep-4 "V100 personality flip" (stack +15.1R on 210d) was an artifact of the same fictional lot grid — under true specs the stack scores **−33.76R (t=−3.00)** on the same window. "No universal geometry" stands for a blunter reason: no validated geometry exists on V100 at all.
- **Standing rule (fourth small-sample-lead-class death, now systemic)**: every cross-instrument cert run must set all five CERT_* spec variables explicitly; any artifact whose `max_risk_pct` implies sizing the instrument cannot trade is invalid on its face. V75 default-spec runs exempt (0.01 IS the V75 truth).
- Artifacts: `artifacts/v100_replay/walkforward_v100_2y_gross_repro.json` (true-spec gross baseline), `walkforward_v100_2y_net.json`, `walkforward_v100_210d_truespec_net.json`, `artifacts/v75_replay/cert_report_v100_2y_net200.json`.

## [Morning status tool + first-trade drill + 2 adjudicator fixes] - 2026-09-05

### Added — scripts/morning_status.py: the one-command morning check (read-only)
- Arm health per terminal (process count via tasklist, EA telemetry write age with a 2h staleness line, ledger veq + integrity), night-gap audit from the UTF-16 terminal journals ("connection lost → authorized" pairs, cross-midnight capable, sub-60s MT5 access-point flaps summarized instead of listed), and go-live gate progress X/30 per arm with days-to-30 at the observed rate. `--strict` exits 1 on unhealthy signals. Validated live: catches the 01:14→08:24 sleep exactly.

### Added — scripts/first_trade_drill.py: prove the paper-data path BEFORE the first real fill (10/10 green)
- Generates synthetic ledgers in the exact EA v26.35 wire format (OPEN/CLOSE/EQ, seconds epochs) in temp dirs and runs the real downstream tools: adjudicator verdicts for empty arms (KEEP COLLECTING), below-gate (ETA projection), clean A-win (P1/P2/P3 all hold), and symmetric-noise pairs (INCONCLUSIVE — the rule refuses to declare on noise); reconciler 7-day gate fires with no broker pull; morning-status ledger parser + cross-midnight journal pairing unit-checked. Ends by restoring truthful real-state artifacts (removes drill-written ones when no real ledger exists yet).
- **Bug found by the drill #1 (HIGH): `ab_adjudicate.py` paired on CLOSE epochs, not the frozen OPEN-epoch rule** — the arms hold different durations under different TP geometry, so in production their CLOSE times would almost never align and the adjudication would starve. Fixed to pair on `open_epoch` (falls back to close epoch only for OPEN-less rows).
- **Bug found by the drill #2 (MEDIUM): zero pairs crashed the adjudicator** (`None` mean formatted with `:+.3f` → TypeError, exit 1, no verdict line). Now prints an explicit zero-pair diagnostic.
- Drill-design lesson recorded in-code: giving the B arm a different `tp_mult` in the "no signal" scenario embeds a REAL winner-pay effect (2.4 vs 1.8) that the paired test correctly catches — the noise arm must share A's outcomes plus symmetric noise.

### Added — docs/MILESTONE_MEMO_v2635.md: one-page milestone memo
- What was claimed (cost-blind +130%), what the re-baseline says (+4.37R net, t=0.35, TP 2.4 negative), the critique replication outcome (cost flaw confirmed; structure claims rejected), the four v26.35 EA fixes, the pre-registered gate as sole authorizer, and the honest standing risks.

## [Verification re-run + CLI hotfix] - 2026-09-05 (morning)

### Fixed — certify_v75.py CLI crashed after writing every report (cosmetic, engine untouched)
- **Bug** — `certify()` pops `r_extra`/`tp_r` from trade records before returning, but `main()`'s trade-dump print loop still read `t['r_extra']` → `KeyError` after the report file was written. Every CLI invocation of the new engine crashed at the final print step; last night's verifications imported `certify()` directly and never hit it. Fix: `t.get('r_extra', 0.0)`.
- **Backward test re-run (legacy engine, CERT_COST_LEGACY=1)** — fresh60 window reproduces the stored `cert_report_legacy_repro_tp18.json` **bit-identically**: all metrics AND all 135 trade records equal (+13.23R / 48.1% / DD 42.2% / $114.76).
- **Forward test re-run (cost-inclusive engine)** — all three re-baselines reproduce exactly: TP 1.8 +4.37R/114/45.6%, TP 2.4 −4.07R/68/39.7%, TP 1.8 @$100 +4.37R/114. Four reports in `artifacts/v75_replay/*_check0905.json`.
- **EA-side deploy gate re-check** — `verify_set_inputs.py` 15/15 presets PASS on v26.35 source.
- **Morning ops check** — both paper arms healthy (v26.35, router TOLERATED at $50 virtual, clean reconnects); PC slept ~01:14→08:24 (accepted: broker archives make any data window pullable on demand; only the paper ledger accrues and sleep nights stretch, never lose, gate time). No closed paper trades yet — gate clock starts with the first fill.

## [Cost-inclusive certification engine + re-baseline] - 2026-09-05

### Fixed — certify_v75.py pays the spread in PnL (fills at bid/ask, not mid)
- **Why** — the critique replication (same day) proved the engine used the 18.5-unit spread only as a veto gate; PnL never paid it. Audit arithmetic said −4.34R on +13.23R; the full dynamic re-baseline says worse.
- **How** — entry fills at the adverse half-spread (BUY at ask, SELL at bid), exit pays the other half via `r_extra`; SL/TP/BE/trail anchor to the real fill like the EA. `CERT_COST_LEGACY=1` restores the cost-blind engine.
- **Integrity** — legacy mode reproduces the published fresh60 run **bit-identically** (+13.23R / 135 / 48.1%) before the new mode is trusted.
- **Re-baseline (fresh 60d, $100)** — TP 1.8: **+4.37R / 114 trades / DD 36.7% / net expectancy +0.038R per trade (t=0.35)** — statistically indistinguishable from zero on this window. TP 2.4: **−4.07R** (negative net of costs; the A/B now adjudicates marginal-positive vs negative). Governor trajectory shifts (MOM+PB auto-disabled at −2.08R; PB carries +6.22R alone). Funding Monte-Carlo re-priced on the net stream: $31 → 10% P(profit), $50 → 39%, $100 → 92% survival, median +$3.42/60d.
- **Consequence** — the pre-registered go-live gate (≥30 positive-expectancy arm-A paper trades + tick reconciliation PASS + watchdog) is the only authorizer; a non-positive gate outcome triggers investigation, not live deployment.
- Artifacts: `cert_report_fresh60_tp18_net.json`, `cert_report_fresh60_tp24_net.json`, `cert_report_fresh60_tp18_net100.json`, `cert_report_legacy_repro_tp18.json`, `funding_plan.json`.

## [Critique replication: Tests A/C, drift audit, cost correction] - 2026-09-05

### Added — docs/CRITIQUE_REPLICATION.md + scripts/critique_replication.py: external critique's demands executed under frozen protocol
- **Why** — an external critique challenged the project's claims (Band Fade contradiction, small-sample "certification", missing costs, EMA regime as noise). Response: verify its factual claims against artifacts, then run its Tests A–C on our own data under a pre-registered protocol (`frozen before execution`, one pass).
- **Test A (variance ratios, 8s→256h + supplementary 0.5h/1h/2h/4h)** — all inside surrogate null bands (2.46M ticks + 19 months of H1): no linear trend/mean-revert structure at any horizon. Generator confirmed memoryless at every tested scale.
- **Test C (regime-conditional forward drift, exact EA mirror)** — the EMA regime axis carries NO directional information; sign is weakly anti-continuation (BULLISH label → negative forward drift, consistent 8/8 across eras/horizons, strongest fresh-era episode t=−2.57). Vol terciles: nothing. The regime axis's remaining legitimate role is volatility-aware gating/sizing, never direction.
- **Cost flaw CONFIRMED and quantified** — the cert engine never subtracted the 18.5-unit spread from PnL (veto gate only). Corrected: +13.23R → **+8.89R net** (0.098R→0.066R/trade). Engine fix queued so all future certs are cost-inclusive.
- **Small-sample honesty applied to ourselves** — fresh60 Wilson 95% LB = 39.9% win rate, per-trade t=0.96: the honest claim is "consistent with zero-to-small positive expectancy", and the ≥30-trade live paper gate (not backtests) decides live value. Drift audit: 19-month −78% downtrend then a near-doubling Feb→Jul 2026 — long-run drift real but sign-unstable; hourly-grain drift unpredictable (t=−1.62); drift capture would be a position strategy, not M15.
- Artifacts: `artifacts/critique_replication/results.json`, `vr_long_horizon.json`.
- **Queued fix**: spread-cost-inclusive fills in certify_v75.py (all future certifications cost-inclusive, flagship numbers re-baselined once).

## [Drift-vs-Σ tracker: CLOSED (1/3) — no EA integration] - 2026-09-05

### Registered → executed in one pass (docs/DRIFT_SIGMA_TRACKER.md, artifacts/drift_sigma/)
- **Question**: can a causal tick-stream tracker (EWMA drift µ₂ / EWMA σ₂ over trailing 1800 steps) estimate the generator controller's state well enough to feed the EA a regime-confidence input?
- **Tick lake extended**: July gap filled (+1,165,557 quotes → 2.46M ticks, Jun 7 → Sep 2).
- **K1 predictiveness — FAIL, sign inverted**: quintiles flat, daily spread t = −1.90 (wrong sign), Spearman −0.056 → the EWMA drift estimate **mean-reverts** (hours that trended hard give it back). No positive predictive power.
- **K2 economic gating — FAIL per frozen bar**: gating kept +9.73R/72 vs blocked +3.50R/63 (D = +6.23R, better per-trade expectancy) but t = 0.57, worst fold −5.83R — two of three requirements missed. Base arm reproduced the published +13.23R/135 exactly (integrity check held).
- **K3 vol forecast — PASS decisively**: tick-EWMA σ beat M15 ATR(14) on all 716 hours (RMSE 7.7× lower, MAE 11.9× lower; caveat: shared-scale advantage vs a range-based proxy).
- **Verdict: CLOSED (1/3)** — no EA change. Only legitimate open thread: K1's inversion suggests a *fade-the-drift* mechanism, re-registrable only as a new protocol. The M15 regime layer remains the validated intelligence.

## [Generator fingerprint study: the V75 machine decoded] - 2026-09-04 (night)

### Added — `scripts/generator_fingerprint.py` + docs/GENERATOR_FINGERPRINT.md: how the tick generator actually works
- **Data**: 1,295,215 real ticks over 30 continuous days (broker archive), cadence cross-validated against broker-history probes (the feed itself is 0.5 Hz — one tick per 2.000 s, zero jitter: a deterministic step machine).
- **Findings (T1–T7)**: Gaussian steps (skew 0.00, kurtosis 0.01); up/down 0.4998; tick-return ACF max |ρ|=0.0025 over 100 lags (no direction memory); run lengths match a memoryless coin to 4 decimals; variance ratio ≈ 1.00 at 1s–1m and 0.97–0.98 at 15m–1h (pure random walk); no volatility clustering at tick scale; hour-of-day vol flat to 1.8% (per-step vol targeting confirmed).
- **Conclusions**: "working ahead of the generator" at tick level is mathematically impossible — each step carries zero information about the next, so tick-momentum, spike-runs, and tick-mean-reversion are coin-flip noise by construction (consistent with the earlier tick-fade rejection). The only evolving signal is slow drift-vs-vol — exactly what the M15/H1 regime layer and GARCH already estimate. **The M15 operating point is the correct one, not a compromise.** The 2s clock is an execution/simulation gift (event-exact fills, reconciler ground truth).
- No EA config changes; research direction settled: regime intelligence at bar scale, not tick-speed reflexes.

## [v26.35 — Full pre-live code audit: 4 bugs fixed] - 2026-09-04 (night)

### Fixed — findings from the line-by-line audit (docs/FULL_EA_AUDIT_v2635.md)
- **CRITICAL (paper)**: the ACCOUNT GUARD in `OpenTrade` compared fleet risk against **real account equity** while sizing used paper virtual equity — with $0.57 real vs $50 paper, every paper entry was vetoed (`fleet $0 + $6.25 > $0.086 cap`). Root cause of the weeks-long v26.28-era paper silence. Guard now uses the same equity basis as sizing (`PaperActive() ? PaperEquity() : AccountEquity()`). Consequence: paper A/B statistics genuinely start from tonight; pre-fix paper data is zero by construction.
- **HIGH (live)**: `StratEnabledOrProbe(i)` returned `true` on out-of-range index — a latent governor bypass on any future slot-index slip (the v26.34 VB-BURST `8` bug would have sailed through). Now fail-closed (OOB = deny).
- **MEDIUM (live)**: default `InpMagic` was `7788211` — an orphan not in the fleet CSV, invisible to the fleet guard and close filters on a default-input attach. Now `7788075`.
- **COSMETIC**: self-test banner had 9 format specifiers / 6 args (doubles consumed `%d` slots → garbage `regime 1250694476/5`); counters cast to int. Dashboard fleet-cap display got the same equity-basis fix.
- **Verified clean**: sizing chain = certified model; server-side SL/TP always attached; stops-level validity + entry-abort guards; exit ladder = certified ladder; close detection triple-redundant with dedupe; state files symbol-tagged and terminal-local; all 15 presets PASS; zero CB remnants in live paths.
- **Deployed**: MetaEditor 0 errors / 0 warnings, `.ex5` synced to 13 instances, both paper terminals auto-restored on v26.35 (banner, `TOLERATED` router at $6.31/12.6%, paper $50) — paper A/B continues on the fixed engine.

## [MOM-standalone duel: REJECT] - 2026-09-04 (night)

### Registered, executed, closed — lone-momentum trading is noise-chasing (docs/MOM_STANDALONE_DUEL.md)
- **Trigger**: the 2026-09-04 19:15–21:15 V75 waterfall (1,417 pts) that the EA skipped via the lone-momentum demotion — hindsight showed 2 would-be SELL winners. Treated as a hindsight teaser and pre-registered instead of acted on.
- **Engine**: `certify_v75.py` gained a surgical `mom_standalone` toggle (default off — verified to reproduce the published fresh60 run to the trade: +13.23R/135/48.1%).
- **Window (a), fresh 60 days, 8 paired folds**: demote **+13.23R/135** vs standalone **+10.01R/167** → D = −3.22R ✓, t = −1.70 ✓, worse in 6/8 folds (one −11.55R blowup fold) → **REJECT**. The standalone arm even triggered governor auto-disable (MOM, MOM+PB) and *still* finished worse while being rescued.
- **Window (b), 19 months (z-gate data), 28 paired folds**: full-window totals confounded by stateful-governor divergence (auto-disable killed PB in the demote arm: 69 vs 719 trades) — clean fold deltas: +2.17R/fold, t = +1.15, neither REJECT nor ADOPT → **NO-ADOPT** for that era (standalone still net-negative overall, −23R).
- **Methodology lesson recorded**: in long continuous sims the stateful governor (auto-disable, loss-scaling) diverges between arms — full-window totals stop being a pure signal-rule comparison; fold-based paired deltas with state reset are the honest statistic (all future duels).
- **Decision**: `InpMomentumStandalone` stays `false`; deployed preset and paper A/B untouched.

## [Funding-growth plan tool] - 2026-09-04 (evening)

### Added — `scripts/funding_plan.py`: balance simulation + withdrawal-schedule comparison
- Replays the certified 60-day TP 1.8 trade sequence (135 trades, `sd`/`r` pairs) through the exact EA money layer (`v75_money.py`: min-lot clamp, 0.75^loss scaling, 20% effective-risk cap, compounding) at $31/$50/$100/$200 starting equity.
- **Monte Carlo**: 1,000 shuffles of the trade order (geometry kept paired with its own outcome); measures P(profit), P(ever min-lot-stuck), terminal-equity percentiles.
- **Withdrawal policies simulated inside the walk** (later trades sized on post-withdrawal equity): compound / weekly bank-above-$100-buffer / weekly bank-half-of-profit.
- **Findings**: $31 viable in name only (93% stuck, 25% profitable, median $22); $50 coin-flip (59% stuck, p05 ≈ $19); **$100 = safe floor (97.6% profitable, path-independent +$64.76, veto rare and recovering)**; $200 adds only veto headroom. Recommended schedule: weekly withdrawal of everything above a $100 working buffer (banked $92 in 60 days at $100 start, min equity $72).
- Outputs: `artifacts/v75_replay/funding_plan.{json,md}` (md carries the frozen recommendation). `docs/LIVE_READINESS.md` funding section updated to cite it.

## [Paper A/B live + LIVE readiness package] - 2026-09-04 (evening)

### Added — both paper arms running (operator steps 2+3 completed autonomously)
- **Arm B terminal created without user action**: cloned the MT5 install to `%LOCALAPPDATA%\MitemshubMT5_B` (non-portable first launch generated data folder `49E0383C…`), copied login/`accounts.dat`/`servers.dat` from terminal A, seeded a UTF-16 `chart01.chr` cloned from A's validated profile with `InpTpMult=2.4` + `InpMagic=7788100`, ran `sync-mt5.ps1` (13 instances), launched — EA auto-attached with the v26.34 banner, paper mode, router TOLERATED, authorized on the same demo account.
- **chart04 landmine resolved** by MT5's own exit-flush: the Default profile now holds only chart01 (EA, validated config) + one plain chart; detacher verified nothing to strip.
- One controlled mishap during B's setup: the name-based process fallback killed terminal A alongside B; A was relaunched immediately and auto-restored the validated config (v26.34 banner, TOLERATED router). No state lost (paper mode).

### Added — live-trading readiness (`docs/LIVE_READINESS.md`)
- **`MitemshubAI_VOL75_LIVE.set`** — identical to `VOL75_FINAL` except `InpLiveExecution=true` (TP 1.8, magic 7788075); `verify_set_inputs.py` PASS.
- **Broker-exact funding math** (`order_calc_profit`-based, cross-checked against the EA's FIT ROUTER): V75 min-lot stop-risk $6.19 ⇒ **$31 equity floor** (20% cap); $10 accounts cannot trade V75 on this broker (lot floor, not strategy); $2,800 unlocks V100 (uncertified).
- **Fresh 60-day certification** (Jul 7 → Sep 4): TP 1.8 **+13.23R, $50 → $114.76** (135 trades, 48.1% WR, 42.2% max DD) vs TP 2.4 +4.60R — third consecutive fresh window with TP 1.8 ahead.
- **Pre-registered GO-LIVE GATE**: A/B expectancy positive at ≥30 trades + tick reconciliation PASS + watchdog CERTIFIED; documented accelerated option (20 trades + recon PASS) and the live-deploy procedure.

## [v26.34 — Crash/Boom engine physically removed] - 2026-09-04

### Removed — the dormant CB engine is gone from the source tree (user request)
- **Deleted**: `mql5/MITEMSHUB_AI/CrashBoom/` (CrashBoomEngine, CrashBoomStrategy, SpikeDetector, TickPatternAnalyzer, MultiTimeframeConfirm, TimeOfDayAwareness, SymbolCalibration, DynamicRiskSizing) — ~9 modules reachable only from the retired CB path. History preserved in git and `artifacts/v2633_source_backup/`.
- **Deleted from the EA**: every CB input (mode/is-crash/micro-fade/AUTO-param sources/quick-TP/tick-fade/burst-guard group), the learned CB spike gate (EWMA + `MitemshubAI_cblearn` persistence), the burst-guard policy self-check table, `CBRecordReject` reject-accounting (counters kept, no longer incremented), the CB signal branch and CB exits in both live and paper manage paths.
- **Survived, deliberately**: the Volatility-only init guard (now cites v26.34), the tick recorder (`TickRecorder.mqh` relocated to `Microstructure/` — the opt-in microstructure archive, default OFF), `OpenTradeLive` (the engine-plan opener, kept for the VB-BURST leg) now using the standard risk-planned sizing chain, and the v26.12 reject counters for state-file continuity.
- **Strategy table**: 9 → 6 slots (PB/BO/MOM/MR/BF + VB-BURST at slot 5); `STRAT_SLOTS=6`, names table, governor thresholds, and the state-file loader (old rows 5–8 dropped cleanly) all aligned. Fixed a latent bug in the same stroke: the VB-BURST governor gate called `StratEnabledOrProbe(8)`, which would have silently bypassed the governor on the 6-slot table.
- **Verified**: MetaEditor compile **0 errors / 0 warnings**, fresh `.ex5` synced to all 12 instances (108 orphans pruned on first sync), `verify_set_inputs.py` passes on the V75 presets (zero CB keys), weekly drift report parses v26.34 banners.


## [Paper pipeline: weekly scheduled run] - 2026-09-04

### Added — automated weekly verdict tracking (no manual runs to remember)
- **`scripts/paper_pipeline_weekly.cmd`** — scheduled-task entry point (repo's `%~dp0` wrapper convention, venv python); appends every run to `artifacts/v75_replay/paper_pipeline_sched.log` so unattended runs are permanently recorded.
- **Scheduled task `Mitemshub Paper Pipeline Weekly`** — Sundays 06:30, deliberately 30 min after the existing `Mitemshub Weekly Data Refresh` (Sundays 06:00) so reconciliation/regime tools see the week's fresh bars. Read-only by design.
- Verified end-to-end via `Start-ScheduledTask`: run completed with result 0, next fire 2026-09-06 06:30. From the first paper trade onward, the log's diff section is the automatic "which verdicts changed" report.

---

## [Regime-gate study round 2 (harness-only, no EA change)] - 2026-09-04

### Studied — adaptive regime gating re-tested on the 210-day sample: NOT VALIDATED, three independent ways
- **"What changed after Aug 9" — nothing anomalous.** Post-Aug9 legacy fold z-scores −0.08..−1.23 sit inside the pre-Aug distribution (9/22 pre-Aug folds were also negative); fold-to-fold R autocorrelation is **−0.12** (a momentum regime gate would have scored +23.7R vs buy-and-hold-the-strategy's +51.4R). A perfect ex-ante gate's oracle bound is +40R over legacy — the prize exists, so the question moved to trade level.
- **Trade level (scripts/regime_gate_study_v2.py, pre-registered calibration F01–F16 / validation F17–F26 split)**: on 283 calibration PB trades, mild separators finally appear at real sample size — mid-|z| bucket +0.203R vs tails −0.032R, hour-bucket B1 +0.270R, and the family-throttle's causal basis is real but weak (trades taken while the 10-trade window is below −3R: +0.013R vs +0.099R cold). The chosen `|z| ≤ 1.08` gate was directionally right out-of-sample (vetoed bucket worse OOS, kept-total higher) but **deleted 56% of trades to gain +0.3R** → G3 fail → GATE NOT VALIDATED.
- **Round-4 walk-forward (walkforward_210d_r4_gate.json, reference = tp18)**: the never-tested tp18+throttle combination scores **+45.88R vs tp18's +52.42R — the throttle costs 6.5R on the validated base config**. Every adaptive variant (throttle, gate+stack, tp18+thr) fails V2/V3/V4/V6; static **TP 1.8 remains the only walk-forward-consistent config**.
- Standing architecture: the harness keeps `--family-throttle` for re-testing as paper data grows, and trades now carry `atr_pct` in their records for future regime work — but no gate is deployed. The EA's existing outcome-adaptive machinery (per-strategy auto-disable, 3-loss pause, probe re-entry) remains the only adaptation with a validated basis.

## [TP-duel fresh-data test] - 2026-09-04

### Studied — the last uncontaminated V75 window adjudicates the TP duel: CONFIRMS-TP18-LEAD
- **Design** (docs/TP_DUEL_FRESH_TEST.md, frozen before execution): legacy TP 2.4 had never run on pre-Feb-2026 bars, so the paired difference on 2025-08 .. 2026-01 was uncontaminated; D = legacy − tp18 with registered thresholds (CONFIRMS ≤ −3.0R & t ≤ −1.0; tie-band between; UPSET ≥ +3.0R & t ≥ +1.0 relabels the favorite but never touches the preset); 3 registered ~2-month folds; one look, then closed.
- **Result**: legacy +10.86R vs tp18 +20.98R → **D = −10.12R, fold deltas [−7.71, +4.42, −13.70], t = −1.06 → CONFIRMS-TP18-LEAD**. TP 1.8 wins 2/3 folds; both arms positive on the window; deployed preset unchanged; paper A/B proceeds as the final judge (two-sided by design).
- **Standing duel record**: Feb–Sep 2026 (26 folds, ~500 tr): tie (+52.42 vs +51.44). Aug 2025–Jan 2026 (fresh one-shot): tp18 by +10.12R. Historical power for this question is now exhausted — paper data is the only remaining adjudicator, as it always was. Also notable: the tp18 family is now positive on **three** disjoint multi-month spans (Oct–Dec 2024 +17.4R probe, Aug 2025–Jan 2026 +20.98R, Feb–Sep 2026 +52.4R).

## [V100 two-year walk-forward] - 2026-09-04

### Studied — the stack-vs-legacy flip was fold-count noise: the veto+depth stack loses on BOTH instruments; question settled
- **Power**: 2 years of V100 bars (2024-08 .. 2026-09, 71,038 M15 bars; 210-day set snapshotted), 53×14-day folds, ~2,000 trades per config — ~5× the V75 round-3 power. Driver gained env knobs (`WF_FOLD_DAYS`, `WF_CONFIGS`) so per-symbol runs never touch V75 defaults.
- **Result**: legacy TP 2.4 +31.66R (26/53 folds, t=+0.67) | **v2629 stack −7.09R (t=−0.18)** | tp18 +25.01R (reference). The 210-day stack lead (+15.1R vs legacy −2.05R) **inverts completely under power** — the stack is now measured harmful on V75 (~33R drag) AND net-negative on V100. There is no instrument where it wins; the "V100's config" hypothesis is dead.
- **Second settled question**: no V100 geometry validates (best t=+0.67, worst fold −13.5R). V100 stays uncertified — the fit router may name it, but funding follows certification, and V75 remains the only certified instrument.
- **Meta-lesson (third occurrence)**: August filters → 33R drag at 26 folds; mid-z effect → sign flip on fresh data; V100 stack flip → inversion at 53 folds. Every small-sample lead this project has chased died under power. The pre-registered walk-forward discipline is the only reason none of them reached the EA.

## [Pipeline runner] - 2026-09-04

### Added — scripts/paper_pipeline.py: one command runs every study tool and reports which verdicts changed
- Dynamic tools re-executed (all self-gating, read-only): A/B adjudicator, paper↔tick reconciler, regime-gate replication v3, weekly report (ledger + watchdog + preset drift). Registered one-look contracts read from artifacts, never re-run: z-gate Phase A, V75/V100 walk-forwards, regime3 interim.
- Arm A/B discovery is automatic (chart-magic scan of terminal profiles, ledger-presence fallback). Verdict extraction handles VERDICT/Verdict lines and the watchdog's CERTIFIED/VIOLATIONS format.
- State: `artifacts/v75_replay/pipeline_state.json` — every run diffs verdicts against the previous run and prints NEW / CHANGED (was → now) / unchanged. This is the "re-run once a week of paper data exists and report what changed" deliverable: it is one command, and it reports nothing-but-the-truth today (arm dirs: none — still gated on the MT5 reload; zgate NOT VALIDATED; both walk-forwards NOT VALIDATED for adaptive configs; watchdog CERTIFIED 36/0/28).

## [Z-gate Phase A] - 2026-09-04

### Studied — the z-only gate gets its pre-registered fresh-data test and fails comprehensively: NOT VALIDATED, final for this generation
- **Protocol first** (docs/Z_GATE_PROTOCOL.md, frozen before any data point was examined): Phase A on strictly untouched history (2024-08 .. 2026-01 — zero overlap with the burned Feb–Sep 2026 window), gate forms committed in advance (PRIMARY tertile-keep, FALLBACK median-keep), calibration pre-bar C1–C3, one-shot validation W1–W5 with segment-consistency requirements, multiple-comparisons ban on further threshold archaeology. Pull tooling gained `--end` for historical windows; `z_gate_phaseA.py` executes the contract mechanically.
- **Outcome**: calibration passed decisively (720 PB trades, keep +0.125R vs veto −0.038R, gap +0.163 → edges frozen |z| ∈ (0.420, 1.240]) — then validation (one shot, 170 trades) **flipped sign**: kept +0.017R vs vetoed +0.159R (gap −0.14), kept only 25% of trades, and keeping mid-z trades cost −12.9R/−7.4R per segment against +20.98R for trading everything. W1–W5 all false → NOT VALIDATED, final.
- **Reading**: the mid-z effect was window-luck with a clean mechanism-shaped costume — it fit in Feb–Sep 2026, reversed in Aug 2025–Jan 2026. This is exactly what the protocol was designed to catch: one look, fresh data, sign-flip exposed. The |z| gate question is closed at this sample size.
- **Descriptive silver lining** (not a criterion): the tp18 base strategy scored +20.98R on the Aug 2025–Jan 2026 window — positive on two disjoint ~7-month spans now.

## [Cross-instrument certification: V100] - 2026-09-04

> **SUPERSEDED 2026-09-05**: the V100 numbers below (and the "personality flip") used the V75 0.01-lot default — a broker-impossible grid for V100. See the 2026-09-05 net-edge study entry and docs/V100_NET_EDGE_STUDY.md. Kept for the audit trail.

### Studied — the harness now certifies any Volatility symbol; V100 measured, NOT VALIDATED, and the lesson is structural
- **Capability (sharpening the Volatility mandate)**: `certify_v75.py` is now symbol-agnostic via env (`CERT_DATA_DIR/CERT_SPREAD/CERT_USD_PER_UNIT_PER_LOT/CERT_MIN_LOT/CERT_LOT_STEP/CERT_SPREAD_GATE_FRAC`), `pull_v75_week.py` takes `--symbol/--outdir`. V75 defaults byte-identical; all prior artifacts reproduce.
- **V100 fit (live specs)**: honest broker tick value (identity verified — unlike V75's 100× lie), spread 0.26 (3% of a 1.7×ATR stop, so the spread gate passes instead of strangling), min lot 1.0 → $8.76/min-lot trade = 4.4% at $200. Risk-wise the best Volatility instrument yet.
- **V100 verdict (210 days, 26 folds, ~500 trades, pre-registered V1–V6)**: every config NOT VALIDATED. The surprise is a **personality flip vs V75**: legacy TP 2.4 scores −2.05R (t=−0.09) while the v26.29 stack scores +15.1R (t=+0.69) — the veto+depth filters that were a 33R drag on V75 are a +17R swing on V100. There is **no universal geometry**: instrument personality differs, and every symbol needs its own walk-forward + paper evidence before funding. Per protocol nothing is deployed for V100; the stack-positive lead (t=0.69, 12/26 folds) is recorded for a future, properly powered study (2y of V100 bars or a paper arm) — not promoted on t=0.69.
- **Standing conclusion hardened**: V75 (TP 1.8) remains the only certified instrument. "Sharpening Volatility skills" = per-instrument certification discipline, now executable in one env-prefixed command for any symbol in the family.

## [MITEMSHUB AI EA v26.33] - 2026-09-04

### Changed — VOLATILITY-ONLY MANDATE (owner decision: nothing to do with Crash/Boom, ever)
- **`OnInit` refuses Crash/Boom symbols** — `INIT_FAILED` with a loud log naming the mandate; the EA can no longer be attached to a Boom/Crash chart by accident. Rationale on record: spike-gap mechanics fill stops at post-spike quotes (structurally incompatible with the BE/trail ladder), the tick-burst family measured net-negative across the full 70-cell calibration, and no CB walk-forward exists or is planned.
- **Fit-router universe trimmed** to Volatility 10/25/50/75/100 — the router can no longer recommend Crash 500 (or any CB) to a small account; its advice now always points inside the certifiable Volatility family.
- **CB presets deleted** (`MitemshubAI_BOOM1000_CB.set`, `MitemshubAI_CRASH1000_CB.set`) from the repo and all terminals; sync prunes them henceforth (24 orphans pruned on this deploy). CB *engine code* stays dormant for historical reference — nothing references it on Volatility charts.
- **Banner rebranded** ("Volatility-Only | Standard Mode"); `APP_VERSION` → 26.33. Deploy gate passed (preset validator PASS, 12 instances synced, fresh `.ex5` newer than source). The v26.32 strategy config on the paper presets is untouched.

## [Regime-gate study round 3 protocol] - 2026-09-04

### Added — scripts/regime_gate_study_v3.py: pre-registered replication protocol for the near-miss separators, triggered by paper data
- **Protocol** (fixed before any paper data exists): bucket edges FROZEN from the v2 calibration artifact (abort rather than re-fit if missing); sample gate ≥150 closed arm-A paper trades over ≥21 days; features attach to ledger trades by pairing OPENs to harness sig_t ≤120s (z/hour recomputed with identical definitions; unmatched counted as signal-drift indicator); criteria R1 mid-z paper gap ≥+0.10R, R2 hour-B1 gap ≥+0.10R, R3 AND-keep economics ≥+0.15R/trade over ≥40% of trades, R4 same-sign agreement on the harness companion sample over the paper window. Verdict: VALIDATED-CANDIDATE (→ EA-input design + dedicated walk-forward + paper A/B, never auto-deploy) or NO GATE. Interim mode reports the in-sample extension when run without paper data.
- **Interim result already informative**: on all 440 harness PB trades (Feb–Sep) both gaps persist (mid-z +0.129, hour +0.212) — but the clean-OOS context (v2 validation folds only, n=90) splits them: **mid-z +0.316 (replicates, stronger than calibration), hour-B1 −0.281 (sign flips — calibration-window luck)**. Expectation for the paper round: the v2 AND-gate likely fails via R2, and the surviving candidate is a z-only gate, which would need its own pre-registered protocol — the v3 artifact preserves the evidence trail for that decision.
- Still gated on the operator reload: no paper ledger exists yet.

## [Weekly report tooling] - 2026-09-04

### Added — scripts/paper_weekly.py: one command for ledger expectancy + watchdog verdict + preset drift
- **[1] Ledger expectancy** — per terminal: n, days, total/mean R (vs the walk-forward tp18 reference +0.105R/trade), WR, $pnl, virtual-equity drawdown, worst streak, exit-reason split; explicitly exploratory below 30 closed trades. Prompts the A/B adjudicator + tick reconciler once n ≥ 30.
- **[2] Watchdog** — reuses demo_watchdog's audit()/paper_audit() verbatim (same checks, same verdict).
- **[3] Preset drift, three layers** — (a) chart-attached inputs (parsed from each terminal's UTF-16 `.chr` profile: the ground truth for what the EA would run with after a reload) vs the magic-matched deployed preset — catches the "preset updated, EA never reloaded" failure mode; (b) repo preset vs deployed Common\Presets copy; (c) terminal .ex5 mtime vs repo source. Also flags banner-version staleness, duplicate magics across charts, and V75 charts with InpLiveExecution=true. Read-only; writes weekly_report_YYYYMMDD.json.
- **First live run caught two real findings**: chart01 runs v26.28-era inputs (InpTpMult 2.4 vs deployed 1.8 — the never-done reload, now machine-verified), and chart04 is a second V75 chart with **InpLiveExecution=true and the same magic 7788075** — on demo it contaminates the experiment (double signals, one magic); migrated to a funded terminal as-is it would trade real money on unvalidated settings. Both flagged with explicit NEXT ACTIONS.

### Added — scripts/reconcile_paper_ticks.py: verifies the live paper engine against the tick-study baseline the first week data exists
- **Purpose** — the fast-fail tick study validated the EA exit ladder offline against 1.5M real broker ticks; this tool checks the LIVE paper engine still matches that reality and catches drift early. Per closed ledger trade, re-simulates the identical ladder (constants imported from study_fastfail_ticks — single source of truth) through real broker ticks from the ledger's own fill, and measures: ladder delta (ledger R − tick R), fill shift vs the fair tick fill (quantifies the InpPaperSpreadMult conservatism), exit-reason agreement (STOP→SL / TARGET→TP), and exit-price sanity (≤3×median spread).
- **Pre-registered verdicts**: KEEP COLLECTING (<7d coverage) / MATCHED (|mean ΔR| ≤ 0.10R, CI covers 0, mechanics pass) / OPTIMISTIC-DRIFT (ledger better than reality — dangerous) / CONSERVATIVE-DRIFT (ledger worse — cert numbers understate live) / REASON- or PRICE-DRIFT (mechanics diverged). Auto-pulls missing tick windows from the broker (pull_v75_ticks.py).
- **Self-tested against the real 1.5M-tick file** with synthetic ledgers in the exact EA wire format: zero-bias → MATCHED (Δ −0.007R, CI[−0.057,+0.041]), +0.25R → OPTIMISTIC-DRIFT, −0.25R → CONSERVATIVE-DRIFT, short window and missing ledger → KEEP COLLECTING. All five verdicts correct; injected +4.0 fill shift recovered exactly.
- **Ledger-format correction found on the way**: ledger epochs are SECONDS (TimeCurrent), not ms. Fixed a latent units bug in scripts/ab_adjudicate.py (pairing tolerance was 25h instead of 90s; days/ETA 1000× off); re-verified pairing at 60s offsets and sane ETA.

## [A/B adjudicator tooling] - 2026-09-04

### Added — scripts/ab_adjudicate.py: pre-registered decision rule for the TP 1.8 vs TP 2.4 paper arms
- Fixes the verdict rule **before** any paper data exists: data gate (≥30 closed trades/arm, with ETA from observed rate), greedy pairing by OPEN epoch within 90s (arms share the signal engine and broker clock), then declare only if P1 |paired t| ≥ 1.0, P2 sign agreement between paired delta and total-R difference, P3 ledger integrity (dangling OPENs, veq discontinuity). Otherwise KEEP COLLECTING / INCONCLUSIVE. Scope note: adjudicates TP only — the veto/depth question was settled by the 210-day walk-forward and must not be resurrected on paper subsamples.
- Self-tested on synthetic ledgers in the exact EA wire format, 5 scenarios (A wins, B wins, tie → INCONCLUSIVE, <30 trades → KEEP COLLECTING with ETA, missing arm → KEEP COLLECTING): PASS. Key validity detail: paired tests need shared per-pair market noise to have power (independent draws are unpairable) — real arms share signals, so this holds live.
- One command the moment data flows: `python scripts/ab_adjudicate.py --a-dir "<terminalA>/MQL5/Files" --b-dir "<terminalB>/MQL5/Files"` → `artifacts/v75_replay/ab_adjudication.json`.

## [VOL75 preset v26.32] - 2026-09-04

### Changed — 210-day walk-forward (26 folds) overturns the August filter conclusions
- **Data** — pulled 210 days of broker M15/H1 (2026-02-06 → 2026-09-04, 20,160 bars; 40-day snapshots preserved as `m15/h1_40d_snapshot_20260904.csv`). Round 3 of scripts/walkforward_v75.py: 26×8-day folds, 5 configs, pre-registered criteria (V1–V6), ~508 trades per config.
- **Result** — the strategy family was never broken: legacy geometry scores **+51.4R (t=1.57)** over 7 months; August (the basis of rounds 1–2) was merely a drawdown stretch. **TP 1.8 alone is the best config: +52.4R, t=1.68, 15/26 folds positive** — the only candidate passing the edge criteria (V1 total>0, V4 beats legacy, V5 median>0, V6 t≥1.5). The v26.29 static stack (EMA-side veto + pb-min 0.60) measures **+18.3R — a ~33R drag** vs legacy on the long sample: curve-fit to August, now **OFF** (`InpPbEmaSideVeto=false`, `InpPullbackMin=0.30` in VOL75_FINAL.set; `InpTpMult=1.8` kept). The family throttle adds nothing over tp18 (+50.4R).
- **Still honest** — every candidate failed the strict 60%-positive-folds bar (58% best). Modest, choppy edge on one instrument/broker/regime-stretch; the paper run remains the final gate before any live capital.
- Note: 4-fold walk-forwards on 5 weeks of data are noise machines. Minimum viable validation from here on: 25+ folds or paper data, never both-datasets-from-August.

## [v26.31 strategy round (harness-only, no EA change)] - 2026-09-04

### Studied — adaptive regime gate: the honest answer is that no causal regime feature separates PB wins from losses
- **Diagnostic** — characterized every walk-forward fold (ATR level/percentile, EMA separation, trend age, |z|, path efficiency): F3 (Aug 17–25) was the *most* trending fold (net +7.2%, highest path efficiency) yet PB's *worst* (−9.07R) — runaway markets don't retrace; churn happens in all measured regimes. Every causal feature split tested put BOTH buckets negative; vetoing "bad-regime" trades would mostly just delete trades (some good).
- **Built anyway, as outcome-adaptation instead** — `certify_v75.py --family-throttle`: when the PB family's last 10 trades sum < −3R, PB-family signals need a probe (every 5th) until the window recovers. Zero fitted regime constants; the gate watches realized expectancy only. Full-period: −8.03R → −4.72R, DD 33.7% → 24.8% (on legacy entries, honest booking).
- **Pre-registered gate round (scripts/walkforward_v75.py round 2, artifact walkforward_v2631_gate.json): NOT VALIDATED.** Throttle-on-legacy: +0.92R total vs legacy +1.36R (G1 ✗ — the legacy book's interleaved strategies blunt it end-to-end), positive folds 1/4 (G2 ✗). gate+stack: +7.35R vs stack +7.06R (G4 ✓, tiny gain), positive folds 1/4 (G5 ✗), worst fold −4.0R (G6 ✗). Conclusion: the static **tp18-only** config remains the only walk-forward-consistent improvement (+5.49R, positive 3/4 folds); throttle helps the full-period metric but not fold-consistency; the deployed v26.29 stack (veto+depth) is carried by F1–F2 luck per round 1. Standing decision unchanged: paper data adjudicates, not these folds.

## [MITEMSHUB AI EA v26.30] - 2026-09-04

### Added — Min-lot risk router: tiny accounts get truth, not silent ruin
- **Why** — at $10 on V75 the broker minimum lot (0.01) risks the *full calibrated* $5.10 ≈ 51% of the account on one trade; the 20% cap then vetoes every signal, and before this version the EA did so **silently** — the operator had no way to know the instrument cannot fit the account.
- **`RunFitRouter()` (init) + OnTick gate** — measures the chart symbol's smallest achievable stop-risk (broker min lot × calibrated tick value at the EA's real stop geometry, `InpRouterScanATR`×ATR): fits the 0.5% plan → good fit; exceeds plan but inside `InpMaxEffectiveRiskPct` → tolerated with loud per-trade risk warning; exceeds the cap → entries refused (`g_fit_ok=false`) and `ScanFitAlternatives()` prints which monitored instruments *do* fit. Auto re-checks when equity grows 50% (a grown account may unlock the symbol). Emits a `fit` telemetry event; both money paths use the v26.25 `CalibTickValue()` identity — the router must not inherit the broker's 100× tick-value lie (raw-broker math falsely "fits" V75 at $0.05/trade).
- **Measured with live broker specs (calibrated)** — at $10 every monitored symbol is refused (cheapest honest fit: Crash 500 ≈ $2.23/min-lot trade → needs ≈ $12); V75 needs ≈ $26. At $50 all ten symbols fit (V75 = 10.2% per trade). Instrument choice cannot be defaulted any more: the EA states the minimum funding for each chart.
- Inputs default ON (`InpFitRouter=true`, `InpRouterScanATR=1.7`), pinned in VOL75_FINAL.set; paper mode untouched.

---

## [MITEMSHUB AI EA v26.29] - 2026-09-04

### Changed — VOL75 strategy: first positive certification (+0.85R, was −30.05R)
- **Why** — cert200 forensics showed PB/MOM+PB's −29R was three stacked causes: (1) the cert harness booked every SL as −1.00R even after break-even had moved the stop (~23.5R accounting artifact, fixed in scripts/certify_v75.py with `--legacy-sl` preserving the old numbers exactly); (2) an asymmetric exit ladder (TP 2.4R vs −1R losses with winners PLOCK-capped ≤0.5R); (3) genuine entry-churn (26/34 losers went ≥0.25R in favor first, then rolled over).
- **Fix (VOL75_FINAL preset)** — `InpTpMult` 2.4 → **1.8**; new input `InpPbEmaSideVeto=true` (veto the pullback leg when the close pierces EMA20 against the trend — the single biggest contributor, −30.05 → −3.17R); `InpPullbackMin` 0.30 → **0.60** (skip shallow chases). End-to-end through the full governor: **$200 → $213.24, +0.85R, WR 50%, max DD 20.2%** (n=56). At the paper scenario ($50): $50 → $52.09, −1.13R vs the old preset's $50 → $19.70.
- **Caveat carried, not buried** — the EMA-side veto showed no separation on the independent 103-trade baseline (−0.62 vs −0.59 R/trade) and TP 1.8 partially contradicts the v26.27 OOS-validated 2.4. This stack is the paper run's candidate, not proven edge; walk-forward validation is the gate before any funded deployment. EA defaults stay OFF (`InpPbEmaSideVeto=false`) so other instruments are unaffected.
- Also — fast-fail reflex (cut stalled trades early, re-enter) was tested and **rejected by the data** on M15 bars (−0.72R vs −0.13R on the filtered stack): BE already rescues the trades the reflex would convert into small losses. A tick-level version can be revisited once the paper ledger has data.
- **Tick-level fast-fail follow-up: still rejected** — scripts/study_fastfail_ticks.py replayed the certified trade sets through 1.5M real broker V75 ticks (data/v75_ticks_cert_window.csv, COPY_TICKS_INFO, real-spread fills; note data/R_75_ticks.csv is a mislabeled non-V75 series, return corr 0.011 — do not reuse). Eight FF arms (giveback G0.3–0.8, stall 45–90m) vs the EA ladder, paired with bootstrap CIs: no arm significantly positive on both sets (best v2629 arm +0.085R/trade CI[−0.12,+0.29]; the one "significant" baseline-arm result +0.088 fails to replicate on v2629 and is the expected 1-in-16 multiple-comparison fluke). Tick-true ladder for v2629 = −1.30R vs −0.18R bar-sim → spread+intra-bar friction ≈ 0.02R/trade, well inside the paper engine's ×1.5 spread conservatism. WR inflation from FF arms (77% vs 48%) is an illusion — expectancy unchanged. The BE+trail ladder already captures what FF would.
- **Walk-forward gate (same day): NOT VALIDATED** — scripts/walkforward_v75.py, 4 scored 8-day folds + tail, 7 pre-registered configs, criteria fixed before running. Totals F1–F4: v2629 +7.06R > legacy +1.36R (C1 ✓), TP-neighbor robustness ✓ (+11.7R combined), but consistency failed: positive in only 2/4 folds (C2 ✗), worst fold −4.29R (C3 ✗), and only the TP ablation beats legacy — the veto's contribution flips sign across folds (C5 ✗). Period effect dominates: every config printed its best numbers in F1 (Aug 1–9) and struggled after. The stack stays the PAPER candidate (zero-cost to test live-data), but funded promotion is now blocked on paper-first evidence, not on this backtest.

## [MITEMSHUB AI EA v26.28] - 2026-09-04

### Added — Real paper trading engine (the stub is gone)
- **Why** — `InpLiveExecution=false` was a stub: it faked a ticket with a timestamp, the ticket was then zeroed by the position-search fallback, and virtual positions were **never managed or closed**. No exits, no learning, no data — useless for validating the system without a demo account.
- **`PaperOpen/PaperManage/PaperClose`** — virtual fill at live bid/ask with a configurable conservatism multiplier (`InpPaperSpreadMult`); the position runs the **exact ManagePosition ladder** (STOP/TARGET/PLOCK/ECUT/TIME/BE/trailing + CB spike exits, same thresholds and reason strings); every close flows through `HandleTradeClose` so the governor, learning tables, cooldown, and pause logic all train on paper trades.
- **Virtual equity** — `InpPaperEquity` (default **50.0**) drives `g_eq` in paper mode, so sizing, the 20% real-risk cap, loss-streak scaling, and compounding all validate the *funded* scenario instead of the real account balance. Paper equity persists across restarts via `MitemshubAI_paper_*.csv` (EQ/OPEN/CLOSE ledger, dangling-position restore).
- **Instrumentation** — `paper_open`/`paper_close` telemetry events + a `PAPER:` dashboard row; the watchdog's [2]/[3] checks now work in paper mode via the `veq` field. Banner prints the paper-mode line at init.

## [MITEMSHUB AI EA v26.27] - 2026-09-04

### Fixed — VOL75_FINAL preset fidelity: TP 2.0 -> 2.4, BandFade disabled for the live-spread regime
- **Why** — the 5-week certification backtest (103 trades, 17.5% WR, -62.6R) exposed two preset/source inconsistencies. The source default `InpTpMult=2.4` is OOS-validated (63-cell scalp sweep, artifacts/scalp_sweep_volatility_75_index.json, all tighter cells OOS-negative) but the preset carried 2.0. BandFade's geometry (~22-unit stops) can never pass the v26.23 spread gate against V75's ~18.5-unit live spread (18% of stop): **100% of BF entries were vetoed live**, and the 8 BF trades in the 5-week replay (stop-capped at 1.5% of price) all lost.
- **Fix** — preset `InpTpMult=2.4`; preset `InpUseBandFade=false` on V75 (kept ON where spreads allow). Certification harness: scripts/certify_v75.py (full governor + v26.26 money layer on real bars). Watchdog for demo accounts: scripts/demo_watchdog.py.

## [MITEMSHUB AI EA v26.26] - 2026-09-03

### Added — Post-entry Risk Sentinel: the broker's fill is now audited, never trusted
- **Why** — the v26.25 incident proved that planned and real risk can diverge silently: every pre-send guard validated the *plan*, and nothing re-measured after the fill. Any broker-side volume normalization, stop adjustment, fill slippage, or spec change would have altered real risk invisibly.
- **`RunRiskSentinel()`** — runs after every confirmed entry (main opener, CB opener, and orphan recovery) and reads the position back as the **broker recorded it** (`POSITION_PRICE_OPEN`, `POSITION_SL`, `POSITION_VOLUME`). Computes real dollar-at-risk with **calibrated** tick values, prints a `RISK AUDIT` line (planned vs actual, with `[broker adjusted]` flag on any divergence), and **adopts the broker geometry** into `g_entry/g_sl/g_orig_risk/g_risk_money` so R-math, exit management, and the learning tables all operate on truth.
- **Breach = fatal, not advisory** — if real risk exceeds `InpMaxEffectiveRiskPct` of equity (the same policy the entry chain enforces), the EA pauses itself, logs a `SENTINEL BREACH`, writes a `sentinel` telemetry event, and force-closes the position. The 2026-09-03 failure mode (57% of equity at stake while every guard passed) is now structurally impossible to repeat silently.

## [MITEMSHUB AI EA v26.25] - 2026-09-03

### Fixed — CRITICAL: position sizing consumed a broker tick value 100x understated on Volatility 75 Index
- **Root cause (evidence, not theory)** — Deriv SVG reports `SYMBOL_TRADE_TICK_VALUE=0.0001` for V75 with `tick_size=0.01`, `contract_size=1.0`, account USD. The true value, measured from the 2026-09-03 closed trade (SELL 0.03, 251.55 pts, +$7.55 = $1.0009 per price-unit per 1.0 lot), is **$1.0009** — the broker number is **100.09x understated**. Sibling symbols (V100, Crash 1000, Boom 1000) are consistent with the identity `tick_value == tick_size * contract_size`; only V75 lies.
- **Impact** — the sizing chain believed the 500-point stop risked $5/lot and sized 0.03–0.04 lots; the *real* risk was **$15.03 (57% of equity)** on the morning trade and **$20.02 (61%)** on the 15:00 signal. Every guardrail (`InpMaxEffectiveRiskPct=20%`, fleet cap, v26.6 micro-fit) validated against the same poisoned number and passed silently. The dashboard's `Risk: 0.50%` was fiction. The user's manual save of the morning trade hid this from the account record.
- **Fix** — new `CalibTickValue(sym)`: when profit currency == account currency, the identity `tick_value == tick_size * contract_size` must hold; if the broker value deviates >5%, the geometry value is used and a loud `TICKVALUE CALIBRATED` line prints. Non-USD-quoted instruments keep the broker value (genuine conversion factor). Wired into **all** consumers: main trade opener, CB opener (which feeds the CB engine's dynamic sizing), detached-close recovery, and fleet-wide open-risk accounting.
- Post-fix behavior on this account: wanted vol for a 500pt stop ≈ 0.0003 lots → min-lot 0.01 clamps to **$5.00 true risk = 14.7% of equity**, and the v26.6 micro-fit then shrinks SL/TP to bring effective risk to ≈1.5% (spread-bound floor). Realistic worst case per trade falls from 57–61% to ~4%.

## [MITEMSHUB AI EA v26.24] - 2026-09-03

### Fixed — Governor bootstrap: fresh installs/migrations can no longer wake up benched
- **State-load hardening (`LoadReviewState`)** — a `STRAT,i` row with `enabled=0` but **zero recorded trades** is now loaded as enabled. The performance review needs ≥ `InpMinTradesToJudge` (15) trades to legitimately disable a strategy, so a zero-trade suppress can only come from a stale/zeroed state file — and under v26.20's `StratEnabledOrProbe` gate it benched the strategy at init (Sep-03 Volatility 75: banner said `Trades=0` yet PB/BO/MOM/MR all showed `(probe n/10)`; every candidate bar was vetoed, the classic legs could never fire, and no probe trade could ever accumulate to earn reinstatement — a permanent deadlock).
- Probe counters for zero-trade strategies are reset so probing restarts from a clean slate.

### Fixed — Cold-start blindness: regime/sigma/GARCH gates are warm on the first bar after a restart
- **`SeedHistoryState()` (new, called from `OnInit`)** — after a restart/migration the EA previously woke up blind: the ATR-percentile history was empty (percentile pinned at the 50 default → the regime classifier could not leave `RANGING` → Pullback/BO-sell sat out every trend), the sigma EMA was unseeded (`exp_ratio ≈ 1.0` → BandFade's `>1.25` expansion gate could not pass), and the GARCH module was cold (telemetry `z` stuck on the legacy-stddev scale for another 50 bars, tagged `[GARCH warmup]`).
- The replay walks the last `max(InpAtrLookback, InpGarchWarmupBars+2)` closed bars oldest→newest through the **same** per-bar feeds as live (`ClassifyRegime`'s ATR append, `GarchFeedBar`, `UpdateSigmaBaseline` EMA with `PerBarSigma`/`ActiveBarSigma` now accepting a shift so historical sigma is measured as-of each replay cursor). One-time init log: `Cold-start catch-up: N bars replayed | ATR hist N | GARCH obs N | sigma EMA X`.
- Short-history charts (< need+2 bars) keep the old gradual warmup. Defensive no-op when state is already warm (state files do not persist these series by design).
- Sep-03 evidence: dashboard showed `Telem: z=-4.02 … [GARCH warmup]`, `ATR%: 50` (pinned), `Regime: RANGING` through a 2,400-point trend day, `exp 1.00x` while price collapsed — all four classic strategies either benched (bug 1) or regime/sigma-starved (bug 2). Zero trades was the product of both, not signal selectivity.

## [MITEMSHUB AI EA v26.15] - 2026-09-01

### Added — Quick-TP tick-fade exit mode (v26.15)
- **`InpCBQuickTP` / `InpCBQuickTPTPMult` (default OFF / 2.5)** — opt-in Quick-TP exit for the tick-fade leg: banks a small fixed target (`N x ATR`) and disables trailing, profit locks, early cut and breakeven on tick-fade positions (exits at TP/SL/time only). The M5 fade path and Volatility-mode management are untouched.
- Backed by `scripts/cb_quick_tp_study.py` (new): EA-order tick-fade replay with a TP × minRR × trail-mode × cooldown × hold sweep over all recorded Boom/Crash 1000 tick sessions, plus an EA-faithful band-fade target/cooldown sweep on the 104-day M5 caches, plus the F1–F4 robustness gate (≥4 trades, no session < −1.5R, ATR ×0.8/×1.2 ≥ 0R, spread ×1.5 ≥ 0R).
- **Study verdict (why the mode ships OFF):** only TP ≥ 3.2×ATR geometries survive the gate; the deployed TP 4.0 trail-ON itself fails F2 (worst session −3.8R, ATR ×1.2 stress +0.8R). Quick-TP's best family (TP 2.5×ATR, trail off, +42.9R base) fails F2 at −2.1R — cutting the target truncates the +10R runners that pay for the stop-outs. Both deployed .set files carry the new keys at OFF; policy table logs `quick-tp`.

## [MITEMSHUB AI EA v25.1] - 2026-08-29

### Overview
Fade-only Crash/Boom mode with optimized parameters from 60-day real-broker sweeps, tick microstructure recorder, fleet risk guard, and removal of live parameter drift.

### Changed — Crash/Boom strategy reoptimized
- **Fade-only by default** — grind gated by `InpCBEnableGrind` (off); EA only trades post-spike fade on Boom/Crash
- Defaults re-optimized from 60-day sweep: spike threshold 3.0→2.8, cooldown 2→1 bars, entry retrace 30%→40%, SL 0.5x→0.4x ATR, TP 1.5x→3.5x ATR, max spike prob 0.65→0.70
- New minimum R:R filter (2.0), spike direction filter, ATR minimum filter, retrace quality window (max 50%)
- Duplicate-bar guard prevents double-processing cooldowns and spike ages
- Spike threshold read from detector instead of calibration profile
- **Removed live parameter drift** — SymbolCalibration no longer mutates fade_depth/tp/threshold from live samples; parameters stable until offline review

### Added — Tick microstructure recorder
- New `TickRecorder.mqh`: buffered CSV writes (every 500 ticks or 60s), daily rotation, degrades to no-op on errors
- Integrated into `OnTick()` (runs first, captures every tick), `OnInit()`, `OnDeinit()`, and dashboard

### Added — Fleet risk guard
- `OpenCBTrade()` now rejects trades if fleet-wide risk exceeds cap
- Safety net for ticket=0 on accepted orders

### New inputs
`InpCBEnableGrind`, `InpCBRequireSpikeDirection`, `InpCBMinATRPoints`, `InpTickRecordEnabled`, `InpTickFlushTicks`, `InpTickFlushSeconds`

### Updated `.set` files
- BOOM1000_CB: TP 1.8→3.2, fade-only, tick recorder on, fleet cap 12→13%, added magic 7788300
- CRASH1000_CB: TP 1.8→3.5, magic→7788300, fade-only, tick recorder on, fleet cap 12→13%

---

## [MITEMSHUB AI EA v22.0] - 2026-08-25

### Fixed — why the live bot was bleeding opportunities (Aug 17 journal: 1W/8L, −19.87, 287 signals blocked)

#### `mql5/MITEMSHUB_AI/MitemshubAI.mq5` (v21.1 → v22.0)
- **Permanent pause latch removed** — after `InpMaxConsecLoss` losses, `g_paused` latched forever (day rollover never reset it): the #1 opportunity killer. Now auto-resets with counters on each session-day rollover.
- **Dead daily-loss halt wired** — `InpMaxDailyLossPct` existed but was never referenced; now freezes new entries at −3% from the day-start equity baseline and resets next session day.
- **Effective-risk guardrail** — broker min-lot on a ~$30 account forced ~25–27% equity risk per trade. New `InpMaxEffectiveRiskPct` (default 30%) hard-caps REAL min-lot risk and skips the trade (with a loud log) instead of silently over-risking; target risk lowered to 0.5%.
- **Momentum demoted** — a lone big candle no longer triggers an entry (`InpMomentumStandalone=false`); this chase-top/chase-bottom behavior produced all eight Aug-17 losses (entries at bb_position 0.0).
- **HIGH_VOL regime no longer a global block** — only legs that self-gate skip it; the new band-fade leg *trades* expansion by design.
- **Band-geometry guard** — sigma-derived stops/targets only apply when the winning direction matches the direction band-fade fired; otherwise classic ATR geometry is used.
- **Regime-TF ladder completed** — M5→M30→H4 mapping fixed (was M5→H4); entry/regime timeframe overrides (`InpEntryTFOverride`, `InpRegimeTFOverride`) let you run M15 execution off an H1 chart.
- Order comments updated to `MITEM_v22.0`; startup banner/dashboard show the new controls.

#### Added
- **Band-fade strategy leg** (port of validated `band_geometry.py` semantics): fade |z_dev| ≥ 2σ extensions only when volatility just expanded (> 1.25× its EMA baseline), stop = 0.10×sigma_h, target = 0.80×sigma_h, per-trade hold horizon in seconds, min-RR and max-stop-% gates. This is the walk-forward-validated edge (PF≈3.02) that was previously trapped in Python-only backtests.

#### Configs (same filenames the controller deploys)
- `MitemshubAI_VOL100_FINAL.set` / `MitemshubAI_VOL75_FINAL.set` regenerated with **complete v22 key coverage** — the old files were written for v15 input names, so MT5 silently dropped them and traded code defaults.

#### Tooling & integrations
- **`scripts/verify_set_inputs.py`** — cross-checks every `.set` key against EA `input` declarations, flags missing critical inputs, and brace-checks the source. Run before any deploy: `python scripts/verify_set_inputs.py mql5/MITEMSHUB_AI/MitemshubAI.mq5 mql5/MITEMSHUB_AI/*.set`.
- **`src/dashboard.py`** — EA-log parser now understands `[v22]` lines (was hard-coded to `[v21.1]`, which would have blinded the dashboard to v22 trades).

#### Telemetry journal (v22.0, 2026-08-25)
- **Per-bar measured values**: `UpdateBandTelemetry()` computes `z_dev`, sigma-expansion ratio (`sigma/sigma_base`) and per-bar sigma once per closed entry-TF bar, BEFORE strategy evaluation — gates and dashboard consume the same numbers the journal records.
- **JSONL journal** `MQL5\Files\MitemshubAI_v22_telemetry.jsonl` with three event types:
  - `sig` — every evaluated bar with a fired leg: action TAKE/SKIP, skip reason (e.g. `mom-demoted-lone-candle`, `score B2/S0 < min 3`), fired legs (`"legs":"MOM-|MR-|BF-"`), buy/sell scores, regime, z, exp, sigma/base, band-geometry flag.
  - `open` — ticket, dir, entry/sl/tp, volume, effective $ risk, legs, regime, timeframe, z, exp.
  - `close` — exit reason/price, R multiple, money P&L, consec-loss count, pause/daily-halt state.
- **Dashboard row 11** shows live `z=… exp=…x sig=… base=…`; StratBandFade now reuses the measured globals instead of recomputing (identical semantics).

#### Strategy Tester validation kit (v22.0, 2026-08-25)
- **`STRATEGY_TESTER_VALIDATION.md`** — exact tester panel settings, 3-pass protocol (raw edge / $30 realism / robustness sweep) and quantitative pass criteria for validating the band-fade leg on Volatility 75 & 100 over 6 months of M15.
- **`MitemshubAI_TESTER_BFONLY_VOL100.set` / `_VOL75.set`** — isolation rigs (band-fade only, breakers neutralized, trailing/BE off) for clean raw-edge measurement; verified against EA inputs. Deploy configs unchanged.

#### Five-symbol parallel profiles (v22.1, 2026-08-25)
- **`MitemshubAI_VOL10_FINAL.set` / `_VOL25_` / `_VOL50_`** — vol-tier-scaled band-fade tunes for low-volatility synthetics: deeper z-entry (2.3/2.2/2.0), nearer targets (0.60/0.70/0.80 σ_h), tighter max-stop-% and risk caps where min-lot finally allows sane sizing. Marked UNVALIDATED — Strategy-Tester Pass-A gates required before sizing up.
- **Unique magic per chart** across all five FINAL sets (`7788010/025/050/075/100` = `77880`+vol tier) so parallel EA instances never cross-attribute positions; V75/V100 re-magicked from the old ad-hoc values — reattach fresh.
- **PRODUCTION_CONFIGS.md** gained the five-symbol matrix plus a venue-name warning: this Deriv terminal has no "Volatility XX Index" symbols — tradable names are SYN-series (SYN75/SYN100 verified in `mt5_collector.DERIV_SYMBOL_MAP`).

#### Pass-A real-data validation of VOL10/25/50 profiles (2026-08-25)
- `backtest_real_history.py` extended: per-profile tuned z/targets, exit-reason tracking, avg band-stop-width %, and explicit promotion-gate verdicts (≥30 tr, PF≥1.30, expR≥+0.15, maxDD≤12R, TIME≤40%).
- **208-day real M15 verdicts**: VOL10 ❌ REJECTED (PF 0.96, expR −0.04 — no edge; spread ≈26% of its 0.013% band stops); VOL25 ⏸ SHELVED (PF 1.44/+0.36R but 27R DD); VOL50 🟡 CONDITIONAL (PF 1.55/+0.46R, 0% TIME exits, DD 16R → risk ≤0.9%). Reference anchors V75/V100 pass all edge gates and trip only the fixed DD line.
- **Gate policy revision** documented: fixed R-drawdown gate replaced by sizing rule (`risk% ≤ tolerance / DD_R`), since every always-on leg exceeds 12R over 7 months.

#### Telemetry-native replay (2026-08-25)
- **`scripts/replay_v22_bandfade.py`** now auto-discovers `MitemshubAI_v22_telemetry.jsonl` (explicit `--telem` → MT5 terminal Files dirs → repo fallbacks). When found, a new **Part T** replaces proxy-based auditing with EXACT EA values: ticket-paired trades (R/$/z/exp/legs/risk), band-fade vs classic-ATR leg performance split, skip-reason histograms (`mom-demoted-lone-candle`, score blocks…), live gate hit-rates (|z|≥2 / expansion>1.25× / both), breaker-state counts, and still-open tickets. `--legacy` forces the old proxy Parts A+B; without telemetry the script behaves exactly as before.

#### Live-terminal ground truth & real-history validation (2026-08-25)
- **`scripts/mt5_probe.py`** — read-only Deriv terminal probe: enumerates all 730 symbols, verifies trade modes/min-lots/tick values, computes per-symbol min-lot risk floors at reference stop sizes, exports real candle history to `artifacts/real_*.csv`.
- **SYN-series claim REVERSED by ground truth**: the terminal DOES expose "Volatility XX Index" display names (FULL-tradeable) and has NO SYNxx symbols. `DERIV_SYMBOL_MAP` now maps R_10…R_100 (+V75/V100) to verified display names; controller aliases simplified to a safety net. Earlier stale comment removed.
- **Min-lot risk floors rewrite the fleet plan**: V75 min lot 0.01 → ~$0.08/trade risk floor (🟢 anchor); V100 $10.39 (42% eq); V25/V10 unviable ($23/$40 = 90%/162%). PRODUCTION_CONFIGS matrix updated — live fleet is V75-first, equity-gated.
- **`scripts/backtest_real_history.py`** — EA-faithful band-fade backtest over 208 days of real broker M5 candles (exported via probe). Result: deployed **z=2.0 wins on ALL tested symbols at M15** (V75 PF 1.57 +0.50R; V100 PF 1.63 +0.52R; V75(1s) PF 1.62); looser z gates from the synthetic sweep do NOT survive real microstructure; H1 loses → M15-only confirmed. Deployed configs validated as-is.
- **`scripts/daily_scoreboard.py --weekly`** — ISO-week rollups plus an explicit promotion verdict (≥20 demo trades, expectancy ≥ +0.15R, positive total, beats old-logic baseline when present) printing PROMOTE CANDIDATE / HOLD ON DEMO with unmet criteria.

#### Band-fade frequency sweep tooling (2026-08-25)
- **`scripts/sweep_bandfade_params.py`** — grid-sweeps `z_entry` × timeframe(M15/M30/H1) × `stop_sigma_mult`(0.10/0.20) through the repo's own EGARCH band-strategy runner (`run_vol_band_backtest`) with risk-halts relaxed to expose raw edge; synthesizes seeded 1-min calibrated series per vol tier (GBM + AR(1) clustering, post-hoc variance-normalized), optional `--ticks-csv` real-data sanity, automatic walk-forward half-split on frontier winners, JSON export.
- **Fixed import-blocking bug**: duplicate `DERIV = "deriv"` enum member in `backtest/synthetic_generator.py` crashed the entire `synthetic_trader.backtest` package under Python 3.14.
- 120-day findings (see artifacts/bandfade_sweep.json): M15 dominates the frequency-profit frontier; `z=1.0/stop=0.10` roughly doubles trade frequency vs the deployed `z=2.0` at modest expectancy cost and passes walk-forward halves on both symbols; stop=0.20 fails outright on R_100. Deployed configs unchanged pending real-broker tester confirmation.

#### Symbol alignment across the stack (2026-08-25 audit)
- **Root cause documented**: the Python engine trades INTERNAL names (`R_75`/`R_100`; every CLI default) and its forward-demo is an OFFLINE tick replay — it never touched MT5. Meanwhile this broker's terminal only exposes SYN-series symbols (`SYN75`/`SYN100` verified), so the controller keyed to "Volatility XX Index" could never find its symbols and silently skipped enablement.
- **`autonomous_controller.py`** now resolves configured symbols through `SYMBOL_ALIASES` (display name → SYN fallback, cached) at all `symbol_info`/`symbol_select` sites including order routing.
- **`mt5_collector.DERIV_SYMBOL_MAP` fixed**: `V75`/`V100` no longer map to Boom/Crash 1000 (different instruments!) but to SYN75/SYN100. `R_10/R_25/R_50` deliberately unmapped until venue names are Market-Watch-verified — unknowns fail loudly by design.
- **Docs de-staled**: attach instructions and Strategy-Tester symbol rows now name SYN-series; legacy `_LIVE.set` rows marked superseded.
- Known leftovers: old one-off forensics/backtest scripts (`backtest_v17_*`, `walk_forward.py`, `v100_forensic.py`) still probe display-name symbols — inert research artifacts, not part of the live loop.

#### Audit completion pass (2026-08-25, session 2)
- **Dead shadow map removed**: `mt5_collector.DERIV_SYMBOL_MAP` was defined twice — a stale SYN/SURGE/DROP/LEAP dict silently overridden by the corrected map below it. Dead dict deleted; single authoritative map remains.
- **PRODUCTION_CONFIGS.md de-staled** (three dangerous leftovers): safety rule #6 demanded ONE shared magic (7788123), contradicting the v22.1 unique-magic fleet design — now mandates per-chart fleet magics; attach instructions still claimed "SYN-series only" — replaced with the verified display-name truth; tiny-account advice recommended V10/V25 — backwards per verified min-lot floors ($40/$22 = 162%/90% of $30 equity) — now points at V75 ($0.08 floor).
- **Dashboard log parser accepts `[v22.x]` tags**: matched literal `[v22]`, which would have missed `[v22.1]`-tagged journal lines (same blindness class the v22 fix targeted).
- **Controller SYMBOLS params aligned to deployed tunes**: z_entry 1.8→2.0, targets →1.20 (V75) / 0.80 (V100), timeframe H1→M15, vol_ratio→1.25 (= InpBandVolExtRatio). Self-optimization suggestions are now comparable to what actually trades.
- **Exposure-guard inputs pinned in all seven sets**: `InpMaxTotalRiskPct=15` + full five-magic fleet CSV on the FINAL profiles; `=100` (neutralized like their other breakers) on the `_TESTER_BFONLY_` rigs. `verify_set_inputs.py` reports zero default-fallback notes.
- **Artifact-clobber footgun fixed**: a `--only` rerun of `backtest_real_history.py` rewrote `bandfade_real_M15.json` with just its own rows, silently erasing every other symbol's results (the recorded V75/V100 M15 cells were lost exactly this way). Output now MERGES by (symbol, tf, z, tgt) — partial reruns update their own cells and keep the rest.
- **Deal comments bumped to `MITEM_v22.1`** for order traceability. Telemetry filename deliberately stays `MitemshubAI_v22_telemetry.jsonl` — replay/scoreboard auto-discovery depends on it; renaming would blind the analytics pipeline. Verified: `daily_scoreboard.py` tag regexes already capture any `[vNN.N]` build tag.

#### Terminal source deployment + AGGRO profiles (2026-08-25)
- **Root cause of "MetaEditor still shows v21.1" found and fixed**: the terminals' `MQL5\Experts\MitemshubAI.mq5` copies were never updated — only the repo had v22.1, so every recompile rebuilt the OLD engine. Deployed the v22.1 source (old file preserved as `MitemshubAI_v21_1_backup_20260825.mq5`) to ALL THREE terminal data folders on this machine, plus all nine current `.set` files into each terminal's Presets and Experts locations.
- **AGGRO max-frequency profiles** `MitemshubAI_VOL100_AGGRO.set` / `_VOL75_AGGRO.set`: z=1.0 (deepest validated gate, ~3× frequency), consec-loss pause 6, cooldown 1 bar, account ceiling 50%. V100's effective-risk cap raised to 45% so its ~$10.39 min-lot floor can trade at $30 equity — documented with the explicit math that ~40%/trade means three losers ≈ −78% of the account.

#### Config de-stale pass: `MitemshubAI_V100_H1.set` (2026-08-25)
- The last `.set` still carrying a v21.1 header was also missing all four v22-critical inputs (`InpBandZEntry/StopSigma/TargetSigma`, `InpMaxEffectiveRiskPct`) and pinned the hazardous legacy `InpRiskPerTrade=0.25` (= 25% target risk under fraction semantics that date back to v16). Regenerated with full v22.1 coverage: band-fade V100 tune (z=2.0 / stop 0.10σ / target 0.80σ), momentum-standalone demoted, effective-risk cap 30%, account guard `InpMaxTotalRiskPct=15` with fleet CSV extended by this profile's own magic 7788211 for correct self-accounting. TF overrides intentionally left at CURRENT to preserve the file's H1 identity. `verify_set_inputs.py` now PASSES it. Remaining stale `.set` families (PAPER_TEST, SYN TIER/LIVE ×8, V6/V16–V20 archaeology) are superseded research artifacts per PRODUCTION_CONFIGS.md — do not load them on v22.x.

#### Daily scoreboard (v22.0, 2026-08-25)
- **`scripts/daily_scoreboard.py`** — accumulating daily comparison of v22 demo results vs old-logic baselines. Sources combine when present: v22 telemetry JSONL (trades, R/$, exit split, band share, avg entry-z; plus decision analytics — TAKE/SKIP counts and lone-momentum chase-entries avoided, reported as counts only, never invented P&L), MT5 Experts logs (true parallel-shadow per build tag `[v22]`/`[v21.1]`/`[v16.5]`), and Python-engine journals (`--engine-glob`) as historical baseline. `--selftest` verifies the pipeline on synthetic events; `--json` exports the summary.

### ⚠️ Deploy note
The terminal previously ran an unknown build printing "v10 starting" that matches nothing in this repo. **Recompile `MitemshubAI.mq5` v22.0 in MetaEditor, attach it fresh with the regenerated `.set` file, and verify the chart prints `[v22] ... started`.** Until then, what trades live is not what's in this repo.

---

## [0.1.0] - 2026-07-25

### Added

#### Infrastructure & Deployment
- **Terraform templates** for AWS EC2 deployment (Windows Server 2022)
- Application Load Balancer with HTTP listener
- Security groups: RDP restricted to admin IP, web traffic through ALB
- Auto-start on boot via PM2 + Windows Scheduled Task
- Chocolatey-based provisioning: Node.js 20, Python 3.10, Git, PM2

#### Operator Dashboard (Next.js 15)
- **Trade Plan Panel** — Real-time trade recommendations with entry/invalidation/target levels
- **AI Market Intelligence** — Regime analysis, bias scoring, market thesis
- **Multi-Timeframe Alignment** — Visual alignment matrix across 4H→1H→15M→5M
- **Bullish vs Bearish Evidence** — Ranked evidence with strength bars
- **Current Market Thesis** — AI-generated thesis with confidence and invalidation
- **Health Dashboard** — System health monitoring, MT5 diagnostics, bridge status
- **Trade History** — Complete trade journal with outcomes and performance metrics
- **Mobile-First Design** — Responsive layout with bottom navigation
- **Dark Mode** — Full dark theme support with proper contrast ratios
- **Haptic Feedback** — Tactile feedback for mobile interactions (`src/components/ui/haptic.ts`)
- **Pull-to-Refresh** — Swipe down to refresh market data on mobile
- **Loading Skeletons** — Shimmer states for MultiTimeframe, Evidence, and MarketThesis panels
- **Intel Accordion** — Collapsible intelligence panels with smooth animations

#### Python Trading Engine
- **Missing live-watch functions restored** — `run_live_watch`, `render_live_snapshot_text`, `render_live_watch_alert_text`, `build_live_watch_review_snapshot`, `render_live_watch_review_text`, `build_watch_alert_from_prepared_state`, `_append_journal`
- **Bucket-based cooldown** — `DEFAULT_CONTEXT_ALERT_COOLDOWN=2` for context update suppression
- **StopIteration handling** — Clean exit when snapshot source is exhausted
- **MT5 price sanity check** — Alerts when CSV tick prices deviate from expected ranges
- **build_watch_alert** — Added `why` field from briefing for better explainability

#### Documentation
- **Comprehensive README.md** — Architecture diagrams, quickstart guide, CLI commands, deployment docs
- **CHANGELOG.md** — This file
- **Architecture diagrams** — ASCII art showing full system flow

### Fixed
- **Missing Python functions** that caused import errors breaking the Python engine bridge
- **Cooldown mechanism** — Restored bucket-based countdown (was incorrectly using 120-second epoch-based)
- **Dark mode command-rail** — Fixed washed-out appearance with proper dark theme CSS overrides
- **StopIteration in run_live_watch** — Previously fell into reconnect handler, creating spurious journal entries
- **build_decision_summary** — Now falls back to `briefing` when `why` is not present

### Changed
- **Merged feature/mt5-rollout-enablement into main** — All development consolidated into production branch
- **Updated .env.example** — `SYNTHETIC_ENGINE_MAX_LIVE_TICKS=5` → `15`
- **README overhaul** — Complete rewrite with architecture, features, CLI, and deployment documentation

---

## Previous Phases

### Phase 4 — AI Evolution & Self-Improving Intelligence
See [docs/PHASE4_SUMMARY.md](docs/PHASE4_SUMMARY.md)
- FeatureSelector, ModelCalibrator, ConfidenceScorer
- EnsembleModel, ModelMonitor, FeatureImportanceReport
- 13 new tests, experiment tracking framework

### Phase 3 — Core Intelligence Engine
See [docs/PHASE3_SUMMARY.md](docs/PHASE3_SUMMARY.md)
- 4-timeframe hierarchy with confluence scoring
- Continuous background scanner
- Call lifecycle management (forming→actionable→confirmed→failing→cancelled)
- Hurst exponent, entropy, volatility clustering
- FVG detection, internal BOS, equal highs/lows, liquidity sweeps
- Regime detection with persistence
- 8-component decision fusion
- Confidence calibration (isotonic + Platt)
- Explainability engine

### Phase 1–2 — Foundation
- Market data ingestion and candle construction
- Online logistic regression model
- Paper execution and journaling
- Walk-forward validation
- Risk engine with position sizing and drawdown limits
