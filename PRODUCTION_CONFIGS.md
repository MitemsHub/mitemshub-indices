# Production Configurations — MITEMSHUB AI v26.23

> Last updated: 2026-09-02
> EA version: **v26.23** (`MitemshubAI.mq5` — `APP_VERSION` single source of truth)
> Architecture: 5 Core Strategies + Governor v3.1 (enforcement + coordination) + 7 Intelligence Layers
> Live lineup: **V75 M15 (trading) + V100 M5 (dormant until funding)** — Boom/Crash retired 2026-09-02
>
> **Guides:** [The Governor — how the EA benches losers, re-arms after wins,
> and gates execution quality](docs/GOVERNOR.md)

---

## EA Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| **v26.23** | 2026-09-02 | Governor v3.1 QUALITY GATES: spread gate (`InpMaxSpreadATRFrac=0.18`) refuses entries when live spread > 18% of planned stop — scalp-sweep forensics put spread at ~44% of the OOS loss; conviction throttle (`InpAdaptiveConviction`) raises MinScore +1 while the day is net-negative; `Coord:` dashboard line. Geometry untouched — the 63-cell scalp sweep (`artifacts/scalp_sweep_volatility_75_index.json`) rejected every tighter-TP cell OOS |
| **v26.22** | 2026-09-02 | Governor v3 COORDINATION — win-rearm (`InpWinRearm`): cooldown = 0 after a winning close (losses keep the full breather); scalping idea formally rejected by data before shipping |
| **v26.21** | 2026-09-02 | FOCUSED LINEUP: Boom/Crash charts deleted from the terminal profile; V75 M15 = the trading chart, V100 M5 armed-but-dormant (min-lot risk 12.8%/trade at $4.59); honest mode banners (Standard Mode); forward-split backtest protocol (`scripts/fwd_split_backtest.py`, CSV mode + per-bar spread) — V75/V100 OOS both negative, baseline archived |
| **v26.20** | 2026-09-01 | GOVERNOR v2: auto-disable flag ENFORCED on all four trade paths (was decorative); probe-based re-entry (suppressed strategies take every 10th signal, no permanent freeze); Wilson 95% lower-bound win-rate reporting; probe counters persisted; duplicate dashboard block removed |
| **v26.19** | 2026-09-01 | RECORDER RETIRED: `InpTickRecordEnabled` default OFF — broker tick history covers research (15.4M V100 ticks pulled in one call); `scripts/fetch_market_data.py` reproduces the `ts,bid,ask,mid` schema on demand (+ `--verify`); `scripts/weekly_refresh.py` + Sunday scheduled task; caveat: Boom/Crash broker spread channel is compressed, price path exact |
| **v26.18** | 2026-09-01 | Journal hygiene v2: full per-symbol trade ledger (`AppendTradeRow`); slippage counters exit-price based — live equity curve trustworthy |
| **v26.17** | 2026-08-31 | Volatility burst-fade module (tick-speed state machine) — later INVALIDATED by the 70-cell calibration (every configuration net-negative on V75/V100), pinned `InpVolBurstFade=false` permanently |
| **v26.16** | 2026-08-31 | Tick-fade verdict tooling: EA-faithful replay entry heuristic (spike-jump + retrace window) in `scripts/tick_fade_verdict.py` |
| **v26.15** | 2026-08-31 | CB fade TP 4.0 → 3.2, Quick-TP off — robustness-gate validated on recorded sessions |
| **v26.12** | 2026-08-31 | Order-rejection accounting: `CBRecordReject()` counts every failed/aborted CB order send (retcode failures + tp-outran aborts) with lifetime/today/streak counters, one `reject` telemetry event each, a `Rejects` row in the init SELF-CHECK, and a deinit summary — lost fade opportunities are now quantified in the offline loop without manual broker-journal forensics |
| **v26.11** | 2026-08-31 | Fixed-array self-test: STRAT/REGIME/TIME slot counts unified into named constants used by every declaration, walker loop, loader guard, and name table; `SelfTestFixedArrays()` walks all three tables at init (size check + full read walk + last-slot write touch) fail-closed BEFORE `LoadReviewState` — the v26.9 size-vs-loop crash class can never reach a live chart again |
| **v26.10** | 2026-08-31 | AUTO per-symbol resolution extended to spike threshold / max spike prob / fade R-SL-TP (shared `ENUM_CB_PARAM_SOURCE`, calibration profile now ships the v26.8 geometry, stale compiled defaults corrected, `[CB-PARAM]` init audit); constant-λ prob blend A/B vs the legacy overdue model — ΔR=+0.00 on all recorded sessions (the 0.70 gate is a safety valve, not an active filter) |
| **v24.11** | 2026-08-28 | Crash/Boom mode, tick analysis, MTF confirm, time-of-day, symbol calibration, handle leak fixes, DAILY-HALT bug fixes |
| v24.0 | 2026-08-28 | Initial Crash/Boom mode (spike detection, post-spike fade, dynamic risk) |
| v23.1 | 2026-08-27 | Intelligence layer (strategy review, regime review, time-block review, auto-disable) |
| v23.0 | 2026-08-27 | Cross-instance guard, state persistence, graduated exit, profit lock, volume scaling |
| v22.0 | 2026-08-25 | Daily-loss halt, effective-risk guardrail, band-fade, TF overrides, telemetry |
| v21.0 | 2026-08-24 | 5-core strategy engine (Pullback, Breakout, Momentum, MeanRevert, BandFade) |

---

## Active Live Presets

### The live lineup (v26.21+)

| Preset | Symbol | TF | Risk | Status |
|--------|--------|-----|------|--------|
| `VOL75_FINAL.set` | Volatility 75 | M15 | 0.50% | ✅ **LIVE — the trading chart.** Only family symbol with 0.01 micro-lots (min-lot risk 0.09%/trade at $30). Validated band geometry (z 2.0 / 0.10σ stop / 1.20σ target), TP 2.0×stop, all 5 legs, governor v3.1. Chart profile embedded with the full 69-key preset 2026-09-02 (earlier embedded block was stale-keyed and silently ran code defaults) |
| `V100_M5.set` | Volatility 100 | M5 | 0.50% | 🔒 **DORMANT** — strategies/execution off; min-lot risk 12.8%/trade makes it unsafe below ~$800; arms with one flip at funding. Inputs revalidated against v26.23 |
| `VOL75_AGGRO.set` | Volatility 75 | M15 | 0.50% | Available (aggressive variant) |
| `VOL100_FINAL.set`, `VOL100_AGGRO.set` | Volatility 100 | M15 | 0.50% | Available — balance-gated (needs ~$770 for sane min-lot risk) |
| `VOL10_FINAL.set` / `VOL25_FINAL.set` / `VOL50_FINAL.set` | V10 / V25 / V50 | M15 | 0.50% | Available — balance-gated (min-lot risk 5–8.7%/trade at $30; V25 unlocks ~$500, V50 ~$300, V10 ~$380) |
| `V100_H1.set` | Volatility 100 | H1 | 0.50% | Available (legacy-era profile) |

**Symbol-selection evidence:** mechanics study (min-lot risk vs balance) + family-wide forward-split — no Volatility symbol currently passes OOS with the 5-leg blend; V75 chosen purely on risk granularity. See `artifacts/fwd_split_volatility_75_index.json` baseline.

### Crash/Boom Indices (M5) — RETIRED 2026-09-02

| Preset | Symbol | Status |
|--------|--------|--------|
| `BOOM1000_CB.set` / `CRASH1000_CB.set` | Boom / Crash 1000 | ❌ Charts deleted from the terminal profile at owner decision; data agreed (CB-TICKFADE was the only CB leg that ever paid, and its one +8.75R win was given back in three losses). Presets remain in the repo for archaeology; the CB module stays in the EA (inert when `InpCrashBoomMode=false`) |

---

## Legacy Presets (Older EA Versions) — REMOVED 2026-09-01

The presets below were created for EA versions v6–v19 and failed `verify_set_inputs.py`
against v26.14 (missing critical inputs, silently falling back to code defaults).
They were deleted from the repo and purged from every MT5 terminal on 2026-09-01.
Retrieve them from git history if ever needed (`git log --diff-filter=D -- '*V6_OPTIMAL.set'`).

Removed: `V6_OPTIMAL.set`, `V16_V100.set`, `V17_V10.set`, `V18_StepIndex.set`,
`V19_StepIndex.set`, `PAPER_TEST.set`

---

## Testing / Paper Trading

| Preset | Purpose | Notes |
|--------|---------|-------|
| `TESTER_BFONLY_VOL75.set` | Strategy Tester: BandFade only on V75 | Backtesting |
| `TESTER_BFONLY_VOL100.set` | Strategy Tester: BandFade only on V100 | Backtesting |

---

## Synthetic Trader Presets (Legacy — Old EA) — REMOVED 2026-09-01

These belonged to the older Synthetic Trader system and were NOT used by MitemshubAI.
All eight (`SYN75_LIVE`, `SYN75_TIER1–3`, `SYN100_LIVE`, `SYN100_TIER1–3`) failed
`verify_set_inputs.py` against v26.14 and were deleted from the repo and purged from
every MT5 terminal on 2026-09-01.

---

## Crash/Boom Module Files (v24.11)

All located in `mql5/MITEMSHUB_AI/CrashBoom/`:

| Module | File | Size | Purpose |
|--------|------|------|---------|
| **CrashBoomEngine** | `CrashBoomEngine.mqh` | 11.5 KB | Master coordinator, wires all modules |
| **SpikeDetector** | `SpikeDetector.mqh` | 11.6 KB | Real-time spike detection (tick speed, candle body, probability) |
| **TickPatternAnalyzer** | `TickPatternAnalyzer.mqh` | 10.4 KB | Individual tick precursor scoring (500-tick ring buffer) |
| **MultiTimeframeConfirm** | `MultiTimeframeConfirm.mqh` | 8.9 KB | M1 + M5 + M15 agreement (2-of-3 required) |
| **TimeOfDayAwareness** | `TimeOfDayAwareness.mqh` | 8.8 KB | Learns spike clustering by hour, blocks dangerous periods |
| **SymbolCalibration** | `SymbolCalibration.mqh` | 9.8 KB | Auto-detects Boom/Crash 300/500/1000, adapts parameters |
| **CrashBoomStrategy** | `CrashBoomStrategy.mqh` | 12.7 KB | Entry strategies: post-spike fade + grind continuation |
| **DynamicRiskSizing** | `DynamicRiskSizing.mqh` | 5.0 KB | Adjusts lot size based on spike probability |

---

## Intelligence Layers (v23.1 — Volatility Indices)

Built into the main EA, these run on every bar close:

| Layer | What It Does | Threshold |
|-------|-------------|-----------|
| **Strategy Review** | Checks each strategy's win rate (Wilson 95% LB shown) and expectancy | N=10 trades |
| **Regime Review** | Checks performance per regime (trend/range/volatile) | N=20 trades |
| **Time-Block Review** | Checks performance by time of day | N=30 trades |
| **Auto-Disable** | Disables strategies with negative expectancy | Min 15 trades, expectancy floor 0.10R (CB charts) / 0.00R (Vol charts) |
| **Governor enforcement (v26.20)** | Disabled strategies are BLOCKED on all four trade paths; probe every 10th signal keeps their stats alive → automatic reinstatement on recovery | `InpProbeEveryN=10` |
| **Governor coordination (v26.22–23)** | Win-rearm (cooldown 0 after winning close); spread gate (refuse entry when live spread > 18% of stop); conviction throttle (MinScore +1 while day net-negative) | `InpWinRearm`, `InpMaxSpreadATRFrac=0.18`, `InpAdaptiveConviction` |
| **Volume Scaling** | Reduces lot after consecutive losses | ×0.75 per loss, floor ×0.30 |
| **Cross-Instance Guard** | Blocks entry if fleet already has position on same symbol | 1 max position per symbol |

---

## Key Parameters Reference

### Volatility Indices (FINAL preset)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `InpRiskPerTrade` | 0.50% | Risk per trade as % of equity |
| `InpMaxHoldBars` | 20 | Maximum bars to hold a position |
| `InpEarlyCutBars` | 6 | Bars before early cut activates |
| `InpEarlyCutMaxR` | -0.40R | Early cut trigger level |
| `InpProfitLockR` | 0.5R | Profit lock level after 1.0R high-water |
| `InpTrailStartR` | 1.0R | Trailing stop activation |
| `InpTrailDistR` | 0.7R | Trailing stop distance |
| `InpMaxConsecLoss` | 3 | Consecutive losses before pause |
| `InpMaxDailyLossPct` | 0.05 (5%) in shipped presets — note: user request 2026-08-30 was to disable; the EA SELF-CHECK flags this mismatch each start. Set 0 to honour the request |
| `InpCoolDownBars` | 3 (VOL75_FINAL) — v26.22 win-rearm bypasses the cooldown after winning closes; losses keep the full breather |
| `InpMagic` | 7788010/025/050/075/100 | Fleet magic numbers |

### Crash/Boom Indices (CB preset)

| Parameter | Boom 1000 | Crash 1000 | Description |
|-----------|-----------|------------|-------------|
| `InpCBBaseRisk` | 0.30% | 0.30% | Base risk per trade (verified in both .set files 2026-08-31 — the old table row's 0.28% for Crash was stale) |
| `InpMicroFitPct` | 1.5% | 1.5% | v26.6: if min-lot clamping overshoots risk (micro balance), shrink SL/TP so effective risk ≤ this % of equity; 0 = off |
| `InpCBSpikeThresholdMode` / `InpCBSpikeThreshold` | 1 (CUSTOM, 2.2) | 1 (CUSTOM, 2.2) | v26.10: AUTO/CUSTOM source selector — compiled default AUTO(0) resolves to the calibration profile (2.2 on both 1000 symbols); CUSTOM = explicit input wins. Kills stale stored inputs (this table's old 3.0x/2.8x row was stale and never matched the .set files) |
| `InpCBMaxSpikeProbMode` / `InpCBMaxSpikeProb` | 1 (CUSTOM, 0.70) | 1 (CUSTOM, 0.70) | v26.10: same AUTO/CUSTOM pattern; profile value 0.70; compiled numeric default corrected 0.65→0.70. The offline A/B ("Constant-λ Spike-Probability A/B" below) shows the 0.70 gate never binds on recorded sessions under either blend — it stays a safety valve |
| `InpCBBurstGuardMode` | 2 (Force OFF) | 1 (Force ON) | **DEPLOYED POLICY (2026-08-31).** v26.0 burst guard (≥2 spikes/30min or gap <10min blocks tick-fades), per-symbol from the §7 offline replay (EA_UPGRADE_RESEARCH.md): Crash keep ON (blocked the live −7.0R gap-through trade, maxDD 14.6→6.7R, cost only −0.09R); Boom turn OFF (guard defaults cost −7.7R vs baseline — Boom's winners live inside evening bursts; no swept config beat baseline on both Boom days). v26.9: the old bool became a tri-state enum — **AUTO (0, compiled default) resolves Crash→ON / Boom→OFF inside the engine**, so a chart that never loads its preset still ships the right policy (kills the Aug-31 stale-stored-input failure mode); explicit 1/2 always win. **v26.9: the cluster geometry is λ-scaled** — window = 2.0× and min-gap = 0.6× the symbol's *measured* mean inter-spike gap (clamped 300–7200s / 60–1800s; fixed 1800/600 fallback until 3 gaps are learned). Crash's measured cadence (≈26 min) reproduces the validated behavior (replay: ΔR +0.00 vs fixed) |
| `InpCBFadeRMode` / `InpCBFadeR` | 1 (CUSTOM, 0.4R) | 1 (CUSTOM, 0.4R) | v26.8 grid-search (deeper retrace entry, was 0.3) + v26.10 AUTO/CUSTOM: compiled AUTO(0) = profile 0.4; compiled numeric default corrected 0.3→0.4 |
| `InpCBFadeSLMode` / `InpCBFadeSL` | 1 (CUSTOM, 0.3xATR) | 1 (CUSTOM, 0.3xATR) | v26.8 grid-search (tighter stop, was 0.4) + v26.10: compiled numeric default corrected 0.5→0.3 |
| `InpCBFadeTPMode` / `InpCBFadeTP` | 1 (CUSTOM, 4.0xATR) | 1 (CUSTOM, 4.0xATR) | v26.8 grid-search (wider target to ride the post-spike drift, was Boom 3.2 / Crash 3.5) + v26.10: compiled numeric default corrected 1.5→4.0 |
| `InpCBQuickTP` / `InpCBQuickTPTPMult` | false / 2.5 | false / 2.5 | **v26.15 EXPERIMENTAL — default OFF.** Quick-TP tick-fade exit: banks a small fixed target (`InpCBQuickTPTPMult` x ATR) and disables trailing/profit-lock/early-cut/breakeven on tick-fade positions (exits at TP/SL/time only, exactly the trail=False replay in `scripts/cb_quick_tp_study.py`). Study evidence: TP 2.5xATR trail-OFF was the BEST small-TP family (+42.9R base over the 3 recorded sessions) but it **FAILED robustness gate F2** — worst session −2.1R vs +1.8R for the deployed TP 3.2 trail-ON geometry, and every TP ≤ 2.5 lost the +10R runners that pay for the stop-outs. Do not enable without accepting deeper worst-case session drawdowns |
| `InpEarlyCutBars` | 5 | 4 | Faster exit for CB |
| `InpEarlyCutMaxR` | -0.35R | -0.30R | Tighter early cut |
| `InpProfitLockR` | 0.4R | 0.35R | Tighter profit lock |
| `InpTrailStartR` | 0.8R | 0.7R | Earlier trailing activation |
| `InpTrailDistR` | 0.5R | 0.45R | Tighter trailing distance |
| (λ model — built-in, no input) | ON | ON | v26.9: spike probability uses the learned constant-λ Poisson hazard (per-symbol EWMA of inter-spike bar gaps) instead of the "time-since-spike / overdue" term; trusted after 3 learned gaps. **Not an input switch — earlier doc rows named `InpLambdaModel`/`InpMinLambdaSamples`, which never existed as inputs (corrected 2026-08-31)**; the SELF-CHECK banner prints it as a binary-freshness marker |
| `InpUseGarch` | ON | ON | v26.9 phase 1: EGARCH conditional-vol as the sigma source (legacy stddev fallback if disabled/fails). No .set change needed — compiled default ON |
| `InpGarchWarmupBars` | 50 | 50 | Observations before the GARCH forecast is trusted |
| `InpMaxTradesPerDay` / `InpMaxTradesPerHour` | 0 (disabled) | 0 (disabled) | **v26.14 (2026-08-31): лимитите за брой трейдови са премахнати изцяло** — boundless opportunities, no daily/hourly cap. 0 = disabled; бяха 10/ден и 6/час. Компилираните дефолтове вече са 0 (Constants/Config/RiskLimits), така че дори чарт без .set файл не се ограничава. Throttle на честотата остават собствените gate-ове на EA-то: cooldown, spike probability, burst guard, facade gate |

### Micro-Balance Operation ($10–$25) — v26.6

Boom/Crash 1000 cannot trade below **0.20 lots** (~$1 per price-unit per 1.0 lot), so on a
small balance the min-lot clamp silently multiplies configured risk:

- Configured CB risk 0.30% of $14 ≈ $0.04 → computes ~0.01 lots → **clamped up to 0.20**
  → real planned risk = 0.20 × SL distance (e.g. 4.1-unit stop = $0.82 ≈ **5.7% per trade**).
- A spike that gaps through the stop costs `jump × lot` regardless of where the SL sat
  (15–34-unit jumps = **$3–$7 ≈ 20–50% of balance per gap event**). This is the binding
  constraint at micro balance — no code can shrink it below the exchange minimum lot.

v26.6 `InpMicroFitPct` (default 1.5%) adapts the geometry instead: when effective min-lot
risk exceeds this % of equity, the EA rescales SL (and TP proportionally, R:R preserved)
so planned 1R ≈ 1.5% of equity. The stop is never tightened below spread + broker
min-stop distance (floor logged as `[floor: spread-bound]`). Set 0 to restore the old
oversized min-lot risk behavior.

Recommended at this balance tier:

| Setting | Value | Why |
|---|---|---|
| `InpMicroFitPct` | 1.5 | Planned loss ≤ ~1.5% per normal stop-out |
| `InpCBMaxConsecLoss` | 2 | At 0.20 lots a gap-through = 20–50% of balance; pause after 2, not 4 |
| `InpMaxEffectiveRiskPct` | 20 | Absolute veto only — keep loose so the EA keeps trading at any balance |
| `InpCBBurstGuardMode` | ON (Crash, .set=1) / OFF (Boom, .set=2) | Per-symbol policy from the offline backtest (§7, EA_UPGRADE_RESEARCH.md) — deployed in both .set files; **compiled default = AUTO** which resolves the same policy in-engine for charts without a preset |

Survival horizon at $14 with these defaults: ~9 normal stop-outs (≈1.5% each) before the
consecutive-loss pause, but only **2–3 spike gap-throughs** — burst days are the real
risk window, and the burst guard + facade gate are what throttle exposure there.

---

## Exit-Geometry Grid Search (2026-08-30) — v26.8 InpCBFade values

Offline sweep over ALL recorded tick sessions (Boom 08-29, Boom 08-30, Crash 08-30;
16.5k+24.3k+14.4k ticks) with the validated tick-fade replay, **net of spread
(0.483 pts per round trip)**. 1,296 configs (SL × TP × FADE_R × retrace-ceiling ×
hold) ranked by aggregate net R; harness `scripts/cb_exit_grid_search.py`, full
output `artifacts/cb_exit_grid_results.txt`.

**Incumbent (SL 0.4 / TP 3.2 / R 0.3 / hold 2400s) ranked #387 of 1296** and bled on
the two newest sessions (Boom 08-30 −9.48R, Crash 08-30 −2.41R) while Boom 08-29's
+31.5R carried the total.

**Adopted (both .set files): `InpCBFadeSL=0.3`, `InpCBFadeTP=4.0`, `InpCBFadeR=0.4`,
`InpMaxHoldBars=6` (1800s).** Aggregate +42.4R across the three sessions vs +19.6R
incumbent; the live-similar Boom 08-30 day flips from **−9.5R → ≈ +13.6R** on the same
spikes with the same spread.

Robustness gates every finalist had to pass (only 27/1296 did):

| Check | Threshold | Adopted config |
|---|---|---|
| F1 sample | ≥4 trades total | 32 trades ✓ |
| F2 worst session | ≥ −1.5R | **+1.2R (positive on all 3 sessions)** ✓ |
| F3 ATR ×0.8 | ≥ 0R | +53.8R ✓ |
| F3 ATR ×1.2 | ≥ 0R | +29.0R ✓ (hold 2400s variant only +15.3 — shorter hold is the robustness win) |
| F4 spread ×1.5 | ≥ 0R | +33.0R ✓ |

Honest caveats: 3 sessions only (single Crash day); the +13R targets are long-drift
rides that depend on post-spike drift persisting; spike gap-through losers still exist
(−6.8R/−7.7R on Boom 08-30) — geometry changed their frequency and the R-price of
normal stops, not the tail depth, which stays lot-bound; retrace ceiling (0.5/0.6)
proved insensitive. This is directional evidence from the EA's own recorded
microstructure, not a proof — let the per-symbol state files accumulate and re-run the
sweep weekly.

### Re-run on the fuller sample (2026-08-31 00:10, artifacts/cb_exit_grid_results2.txt)

Same sweep re-run after the evening recording grew the sample (Boom 08-30: 24.3k →
26.4k ticks incl. the 22:00–23:30 burst; Crash 08-30: 14.4k → 16.4k ticks incl. the
late-evening drops; no new live trades after the v26.9 deploy — charts were
SESSION-OFF with the halt still stored).

| Config | TOT R | worst session | ATR×0.8 | ATR×1.2 | spread×1.5 |
|---|---|---|---|---|---|
| **Adopted v26.8 (0.3/4.0/0.4/hold1800)** | ≈+51 | −2.8R (Crash) | +63.2 | +35.3 | +43.1 |
| Challenger (0.3/3.2/0.2/remax0.4/hold2400) | +56.6 | −1.2R | +49.8 | +43.3 | +43.5 |
| Challenger (0.3/3.2/0.4/hold1800) | +54.8 | **+1.8R** | +63.2 | +35.3 | +43.1 |
| Incumbent old (0.4/3.2/0.3/hold2400) | +29.6 | +1.9R (Crash) | — | — | — |

**Verdict: the adopted v26.8 geometry still passes every gate and its TP=4.0 is
confirmed insensitive (TP 2.5–5.0 give near-identical results at FADE_R 0.4/hold
1800).** The fuller sample moved it from 27th-of-1296 class to ≈+51R aggregate with
all stress tests positive. The interesting new signal: with FADE_R 0.4, TP 3.2 and
4.0 are now equivalent (the 4.0×TP targets that made 4.0 special in run 1 were
pre-midnight rides; tonight's post-midnight data trimmed them) — so TP=4.0 is kept
(no change needed), and FADE_R=0.4 remains the robust choice (every R=0.2 variant
still fails the worst-session gate on Boom 08-30: −1.2R to −3.5R).

Note for interpretation: R units are relative to each config's own 1R (planned stop),
so totals compare geometry, not dollars — on the $14 account the micro-fit caps
dollar risk per trade, which is exactly the regime this ranking was built for.

---

## v26.7 Fresh-Build Deploy (2026-08-30)

All pending v26.x upgrades ship in ONE build (`APP_VERSION 26.7`) so both charts run the
same binary and the HUD version line is the deploy-verification signal:

- **v26.0** tick-fade burst guard — Crash ON, Boom OFF (per-symbol .set)
- **v26.1–26.3** per-symbol state/review/telemetry/slip files + DAILY record (session counters survive re-attaches)
- **v26.2** slippage journaling (gap-through stops measured explicitly)
- **v26.4** event-driven close detection (`OnTradeTransaction`, real SL/TP exit reasons)
- **v26.5** EWMA facade gate + CB strategy counters in the intelligence layer
- **v26.6** micro-balance fit (`InpMicroFitPct=1.5`), live stop re-anchor (kills retcode 10016 on fast fades)
- **v26.7** tick-recorder flush on close (tick CSVs now always contain the context of a just-closed trade)

Deploy procedure (both charts, from one build):

1. Sources synced to `MQL5\Experts\MITEMSHUB_AI\` (+ `CrashBoom\` includes) and compiled — verify **HUD shows v26.7 on BOTH charts** (a stale v25.9 line means that chart is still running the old binary).
2. **Remove EA → re-attach → load the v26.7 .set** on each chart. This is mandatory, not optional: recompile alone keeps the chart's STORED inputs, which still carry the old `InpMaxDailyLossPct=0.03` daily halt and lack every v26.x input. The refreshed `.set` files now carry all v26.x inputs with `InpMaxDailyLossPct=0.0`.
3. Verify in the Experts log per chart: `DAILY-HALT` prints gone (Crash), `Restored today's session state` line on re-attach, and on the first close: `OnTradeTransaction: closing deal … — O(1) close` + `SPIKE SLIPPAGE` rows.
4. First close after deploy also creates the per-symbol files `MitemshubAI_state_<Symbol>.csv`, `MitemshubAI_review_<Symbol>.csv`, `MitemshubAI_v23_telemetry_<Symbol>.jsonl`, `MitemshubAI_slip_<Symbol>.csv`, `MitemshubAI_cblearn_<Symbol>.csv`.

Note: re-attaching resets in-memory counters once (old per-symbol state is restored at init from the state file; the very first attach after this deploy starts Boom/Crash counters clean). Do NOT re-attach mid-trade.

---

## v26.9 — Remaining P0 Upgrades (2026-08-30)

**OnTradeTransaction close detection** was already wired in v26.4 (O(1) deal lookup,
real SL/TP exit reasons, stale-event guard, targeted `HistorySelectByPosition` fallback
— no full-history scans anywhere).

**v26.9 constant-λ spike model** replaces the old "time since spike / overdue" term
(the 25%-weight gambler's fallacy the 15.19M-tick study disproved):

- Spike probability is now: body-ratio 35% + tick-change 25% + grind 25% + **constant-λ hazard 15%**.
- λ (spikes/bar) is learned per symbol as an EWMA of observed inter-spike bar gaps
  (first 3 gaps seed it; persists in the session state file as a `LAMBDA` row).
- The hazard is flat at λ after a short refractory tail — no "overdue" inflation on
  long gaps (which previously pushed prob=0.26 onto a 29.6-min-old spike and could
  block valid fades via the spike-prob gate).
- HUD shows `λ=x.xxx/b (gap y.yb)` once learned; the Experts log prints the learned
  rate every 25 bars with the projected next-spike hazard `P = 1 − e^(−Δt/mean_gap)`.

Dashboard prob semantic change: with λ≈1/33 bars the hazard floor is ≈0.03; the
combined prob now ranges ≈0.03–0.6 instead of 0.1–1.0 — the SPIKE-AVOID gate
(`InpCBMaxSpikeProb`) thresholds are unchanged, but expect fewer prob-driven blocks.

---

## v26.9 Phase 1 — GARCH Conditional-Vol Wired In (2026-08-31)

First module of the modular market engine is live in the production EA:

- **Module:** `Market/GarchForecaster.mqh` — EGARCH(1,1) in calibrated-fixed
  mode (params from `data/garch_calibration/r_75.json`: ω −1.115, α 0.077,
  γ 0.011, β 0.918; long-run σ ≈ 0.115%/bar, 138-bar half-life). The recursion
  is locked against the Python reference by `Tests/Phase10Tests.mq5`
  (buffer-initialized log-variance at 50 obs, warmup σ = √long-run below 30
  obs, log-var clamp [−30, 5]).
- **Inputs:** `InpUseGarch` (default ON) — set false to revert fully to the
  legacy stddev path; `InpGarchWarmupBars` (50) — observations before the
  forecast is trusted.
- **Feed:** one `Update(log-return of the last closed entry-TF bar)` per bar
  (`GarchFeedBar()`); zero per-tick cost, no indicator handles involved.
- **Consumers:** `ActiveBarSigma()` returns GARCH σ when enabled + healthy +
  warm, else the legacy `PerBarSigma` stddev. That sigma drives the band
  telemetry (z-deviation, expansion ratio) **and directly the band-fade
  leg's geometry** (`StratBandFade` stop/target = σ·√bars multiples), plus the
  band vol gate. Under GARCH the reported z is the module's own standardized
  shock z_t (same scale as the sigma source).
- **Failure handling (sticky):** 50 consecutive bad updates (bad price data or
  invalid σ) disable GARCH for the session and log `GARCH disabled: … — legacy
  sigma path active`; a healthy warmup logs `GARCH ready: 50 observations,
  σ=…` once.
- **HUD:** the sigma line carries a badge — `[GARCH]` when warm,
  `[GARCH warmup]` during the first bars, `[legacy sigma]` when disabled/failed.

**Collision fix shipped with this build:** `GarchForecaster.mqh` deliberately
includes no `Constants.mqh` (the forecaster is pure numeric recursion and needs
no enums). The stale terminal `Experts/MITEMSHUB_AI/Core/` folder and a stray
root-level `Constants.mqh` were removed — their modular `ENUM_REGIME`
(with `REGIME_RANGE`) collided with the EA's own `ENUM_REGIME` (with
`REGIME_HIGH_VOL`) and caused the 2026-08-30 compile breakage (first 274
errors on the stale tree, then 1 error + 45 enum-conversion warnings on the
half-synced one). The live include chain is now only `Trade.mqh` →
`CrashBoom/*` + `TickRecorder` + `Market/GarchForecaster.mqh`. Fresh build
compiled `0 errors, 0 warnings` and synced 2026-08-31.

---

## Seeded Learning Memory (2026-08-31) — facade gate + slippage from day one

The v26.5 facade gate needs ≥4 spike trades before it adjudicates. Today's realized
outcomes were back-filled into the per-symbol learning files so the gate starts warm
instead of re-learning the same losses (also fixes a stray double `LoadCbSpikeState()`
call found during this change; loader now prints what it restored):

| File (MQL5\Files) | Seeded state | Meaning |
|---|---|---|
| `MitemshubAI_cblearn_Boom_1000_Index.csv` | n=3, mean −2.25R, σ 0.75, streak 2, **gate BLOCKED** | +2.0R grind (08-28), −2.0R (08-28), −3.78R (08-30 22:00) — mean≤0 with noise > edge |
| `MitemshubAI_cblearn_Crash_1000_Index.csv` | n=3, mean −6.49R, σ 0.50, streak 2, **gate BLOCKED** | +8.75R, −6.40R, −7.00R today — deep negative expectancy |
| `MitemshubAI_slip_Boom_1000_Index.csv` | 1 gap-through (−3.78R), cum slip −3.78R | today's spike-gap close |
| `MitemshubAI_slip_Crash_1000_Index.csv` | 2 gap-throughs (avg −6.70R), cum slip −10.81R | today's two gap-through stops |

Behavior note: both charts start with `CB-SPIKE LEARNING ... gate=BLOCKED` on init.
The gate self-lifts from live evidence — every close updates the EWMA (α=0.15), so a
few wins under the v26.8 geometry (positive expectancy, mean > 1.5σ) re-open fades
automatically; nothing is frozen permanently. `InpCBPersistLearning=false` overrides.
Verify at init: the Experts log prints `CB-SPIKE LEARNING restored: ...` and
`SPIKE SLIPPAGE restored: ...` per chart.

---

## Boom Aug-30 Reconciliation (2026-08-31) — the "7 missing trades" were rejected orders

Forensic pass over the Aug-30 Experts log + the broker journal:

- **Boom's 7 "missing" trades never existed as positions.** The broker journal
  shows seven `failed market sell 0.2 Boom 1000 Index ... [Invalid stops]`
  (retcode **10016**) at 19:39 / 19:50 / 20:30 / 20:55 / 21:10 / 22:11 / 22:28
  local. The stale v25.9 binary computed its tick-fade SL at 0.4×ATR, which sat
  **below Boom 1000's broker minimum stop distance** during low-ATR grind
  conditions, so every entry was rejected. Each failure also triggered the
  3-bar cooldown — the EA sat out exactly the evening-burst window the §7
  backtest identified as Boom's winners.
- **The only real Boom trade that day:** SELL 22:50:55 @14877.6796, SL 14881.7919
  (risk 4.112 ≈ the broker's minimum stop — why it alone was accepted),
  manually closed 22:57:53 @14893.2304 → **−3.782R / −$3.11**. It is already in
  the seeded `cblearn` (n=3, streak=2) and `slip` files — nothing to add there.
- The EA's own deinit `FINAL | Trades:3 WR:33.3% R:-3.76` matches this exactly:
  2× Aug-28 CB-GRIND (+2.001 / −1.982) + the Aug-30 CB-TICKFADE −3.782R.

**Record-keeping fixed (2026-08-31):**
- `MitemshubAI_review_Boom_1000_Index.csv` **created** with Boom's three true
  rows (migrated verbatim from the old shared `review.csv` — the merge-bug era
  file that mixed Boom and Crash rows).
- `MitemshubAI_state_Boom_1000_Index.csv` **rewritten with honest counters**:
  3 trades / 1 win / −3.763R, `STRAT,5` (CB-TICKFADE) 1/−3.782, `STRAT,7`
  (CB-GRIND) 2/+0.019, `TIME,3` 3/1/−3.763, consec=2 (matches the cblearn
  streak), and a historical `DAILY` row for Aug-30 (−$3.11, day-start $17.50)
  that the Aug-31 load auto-resets. REGIME rows stay zero — per-trade regime
  is not reconstructable from the log (documented limitation).
- `cblearn` and `slip` are untouched: their seeds already match the true
  history exactly.

**Prevention is already shipped:** the current build's `OpenCBTrade` re-anchors
entry/SL/TP to the live price, clamps the SL to the broker's
`SYMBOL_TRADE_STOPS_LEVEL` minimum (widening only), aborts when the target is
outrun, and micro-fits the stop to the balance floor — the v25.9 rejection
pattern cannot recur on this build. (The in-code v26.6 note says "two"
rejections; the full count was seven, all from the stale binary.)

**Counterfactual valuation of the 7 rejected windows (2026-08-31):**
`scripts/cb_rejected_windows_replay.py` re-simulates what that evening would
have earned if the clamped-SL geometry (v26.8 exits + broker-min clamp) had
been live. **Clock calibration (critical):** the Experts-log clock runs
**+3595s (~1h) ahead** of the tick-CSV clock — validated by 5/7 windows
landing on a recorded spike within 5s at `log_t − 3595 − age`, and the other 2
matching the logged jump exactly (6.0→5.98, 7.8→7.84). The earlier "same
clock" assumption produced 7× "no live episode" and was wrong.

| Window (log) | Spike (tick) | Entry→Exit (tick) | R | $ @0.2 lots | Exit |
|---|---|---|---|---|---|
| 19:39:37 (j6.0) | 18:37:01 | 18:39:42→18:44:47 | −0.89 | −0.74 | STOP |
| 19:50:01 (j7.8) | 18:44:47 | — | 0 | 0 | expired (retrace 61% > 60%) |
| 20:30:40 (j27.9) | 19:24:19 | 19:32:38→19:51:11 | +0.75 | +0.62 | STOP |
| 20:55:22 (j12.9) | 19:51:11 | 19:56:46→19:56:59 | −4.77 | −3.92 | STOP |
| 21:10:01 (j21.0) | 19:58:34 | 20:10:06→20:40:06 | +6.60 | +5.43 | TIME |
| 22:11:36 (j33.2) | 21:05:00 | — | 0 | 0 | expired (no retrace entry) |
| 22:28:13 (j23.2) | 21:22:17 | 21:33:35→21:43:04 | +0.80 | +0.66 | STOP |
| **Total** | | | **+2.49R** | **+$2.05** | |

Robustness: ATR ±20% identical (SL rides the 4.112 clamp floor, so ATR
scaling doesn't move entries); spread ×1.5 → +2.19R / +$1.80. **Verdict:** the
rejected evening would have netted ≈ **+$2.05** (≈ +0.26% of the ~$14-17
balance), dominated by one +6.6R time-exit winner offsetting one −4.8R
stop-out — the same gap-through risk the slippage journal tracks. The v26.6
clamp converts these from lost orders into tradeable entries, but the
expected value of that specific burst window was modest, not the windfall the
§7 baseline numbers might suggest.

---

## Lifetime-Counter Rebuild from the Merge-Bug-Era Shared Files (2026-08-31)

The intelligence layer now starts from the **real shared-era history** instead
of zeros. Forensics (old `MitemshubAI_state.csv` + `MitemshubAI_review.csv`,
both retained in `MQL5\Files` as evidence — no loader reads unsuffixed names
anymore):

- The shared header `5,2,3,−4.6310` = **Crash's own 3 tick-fades (−4.6500) +
  Boom's 2 grinds (+0.0190)** that the Crash instance had absorbed from the
  shared file (the merge bug). Boom's 3rd row — the 22:00 tick-fade −3.782 —
  lived only in the Boom instance's memory and appears **only in the shared
  review journal**, never in the header.
- Shared journal rows carry each writer's *own* cumulative series: Crash rows
  are inflated by the absorbed +0.019 (cums 8.77/2.37/−4.63), Boom rows are
  clean (2.00/0.02/−3.76).
- `REGIME,2` (RANGING) = Crash's 3 tick-fades (−4.6497); `REGIME,4`
  (NO_TRADE) = Boom's 2 grinds (+0.0187, rebuilt as +0.0190 to match the
  journal/cblearn rounding); `TIME,3` (18–21 server) carried all five merged
  closes; Boom's tick-fade close (hour 22) belongs in `TIME,4`.

**Rebuilt files (verified loader-compatible row by row):**
- **Crash state**: 3/1/2, −4.6500, consec 2; `STRAT,5` (CB-TICKFADE) 3/1/
  −4.6500; `REGIME,2` 3/1/−4.6500; `TIME,3` 3/1/−4.6500; `REVIEW,5,2,3`.
  No `DAILY` row — Crash's per-trade dollar P&L cannot be split authoritatively
  from the shared era (documented limitation); daily counters reset at server
  midnight anyway.
- **Crash review journal created** with Crash's *own clean* cumulative series
  (8.75 → 2.35 → −4.65, counts 1/2/3) — replacing the merge-inflated series.
- **Boom state corrected**: `TIME,3` = 2/1/+0.0190 (grinds), `TIME,4` = 1/0/
  −3.7820 (tick-fade — hour-22 close), `REGIME,4` = 2/1/+0.0190 (grinds).
  Boom's tick-fade regime bucket remains unrecoverable (documented above);
  `REVIEW,5,0,4`; the Aug-30 `DAILY` row is preserved (stale day → auto-reset
  on the Aug-31 load).
- **Cross-footed**: header = STRAT = TIME sums for both symbols; a loader
  emulation applying the exact parse rules (9-field header, 6-field STRAT,
  5-field REGIME/TIME, 4-field REVIEW, 9-field DAILY) loads every row; the
  `cblearn` seed mean-R matches the rebuilt headers exactly (Boom −3.7630,
  Crash −4.6500).

**Expected init lines on the next attach (note: the strategy echo only prints
for strategies with ≥5 trades, so neither symbol prints per-strategy lines
yet — the tables still load):**
- Both charts, BEFORE `Loaded intelligence`: `[v26.11] [SELFTEST] fixed arrays OK: strat 8/8 p=+0.0 | regime 5/5 p=+0.0 | time 5/5 p=+0.0 (walk+write proof, pre-load)`
- Boom: `[v26.11] Loaded intelligence: Trades=3 WR=33.3% R=-3.76`
- Crash: `[v26.11] Loaded intelligence: Trades=3 WR=33.3% R=-4.65`

---

## v26.11 — Fixed-Array Self-Test: the v26.9 Crash Class Made Impossible (2026-08-31)

The v26.9 live crash was a **size-vs-loop drift**: the intelligence tables'
walker loops were widened to 8 slots while the arrays stayed `[5]`, so every
walker died at `i=5` (`array out of range` at init and on the first tick,
killing both charts and leaving the orphaned "Label" HUD). v26.11 makes that
class structurally impossible AND fail-closed at init:

1. **Named size constants** — `STRAT_SLOTS` (8), `REGIME_SLOTS` (5),
   `TIME_SLOTS` (5) are the single source of truth: the array declarations,
   every walker loop (strategy/regime/time reviews, losing-streak analysis,
   state save, state load + its `idx < SLOTS` guards, the post-load echo,
   the HUD Intel line), and the name tables all use the same constants. No
   bare `8`/`5` literal remains in the table code to drift out of sync.
2. **Shared name tables** — `STRAT_NAMES[]` / `REGIME_NAMES[]` were hoisted
   from three duplicated inline copies (CheckStrategyPerformance,
   CheckRegimePerformance, and the HUD — itself a drift hazard) to constant
   globals sized by the same constants.
3. **Init-time self-test, fail-closed** — `SelfTestFixedArrays()` runs in
   OnInit BEFORE `LoadReviewState` (whose loader writes file-indexed slots
   straight into the arrays). It (a) verifies every array's `ArraySize`
   against its constant — including the name tables — and (b) walks each
   table once: reads every slot (probe sums printed to the log) and identity
   write-touches the LAST slot of each array — the exact index every loop
   bound reaches — proving read AND write addressability up front. On any
   mismatch it prints `[SELFTEST] FIXED-ARRAY MISMATCH — refusing to init: …`
   naming actual sizes vs constants and returns `INIT_FAILED`: a broken
   build can never again reach a live chart silently.

Pass line (every attach, immediately before `Loaded intelligence`):
`[v26.11] [SELFTEST] fixed arrays OK: strat 8/8 p=+0.0 | regime 5/5 p=+0.0 | time 5/5 p=+0.0 (walk+write proof, pre-load)`

---

## Complete Journal Coverage Across Restarts (v26.9, 2026-08-31)

Close detection now covers all three windows a trade can end in:

1. **Runtime, event-driven** — `OnTradeTransaction` catches the closing deal
   the instant it prints (O(1) `HistoryDealSelect`, true `TARGET`/`STOP`
   reasons from `DEAL_REASON`, stale-event guard) — shipped v26.4.
2. **Runtime, fallback poll** — if a position vanishes without an event
   (EA busy during a spike, handler miss), the OnTick fallback finds the OUT
   deal with one targeted `HistorySelectByPosition` query — shipped v26.4.
3. **Detached window (NEW)** — a broker-side close that happens while the EA
   is *not running* (mid-day recompile, restart — Aug-30's ~9 re-attaches)
   left no live position for `RecoverPosition`, so the close was silently
   lost from every learning table. Now: the state file carries a `POSITION`
   row (ticket, entry time/price, SL, direction, volume, strategy) while a
   position is open; at init, if the tracked position is gone,
   `RecoverDetachedClose()` recovers its OUT deal with one targeted history
   query, derives the true exit reason, recomputes the $ risk from the
   restored context, and routes the close through the shared handler —
   counters, strategy/regime/time tables, the EWMA facade gate, slippage,
   telemetry and the review row all see it.

The recovery is idempotent: the `POSITION` row is written only while the
position is open and is cleared on close, so a close is journaled exactly
once. At init the live position always wins over the persisted context.
Watch for `RESTART RECOVERY: position … closed while detached … — journaling
now` in the Experts log after a re-attach that follows a mid-trade restart.

---

## λ-Scaled Burst Guard (v26.9, 2026-08-31)

The burst guard's cluster definition no longer assumes a fixed 30-minute
world. Once the symbol's mean inter-spike gap is learned (≥3 gaps, the same
λ EWMA that feeds the spike probability), the guard scales:

- **window = 2.0 × mean gap** (clamped 300–7200 s) — "two spikes inside two
  average inter-spike intervals" is the cluster definition at any cadence;
- **min-gap = 0.6 × mean gap** (clamped 60–1800 s) — blocks only pairs faster
  than 60% of the symbol's own average;
- before 3 gaps are learned, the fixed 1800 s / 600 s inputs apply (the
  backtest-validated Crash configuration);
- no new inputs — the multipliers are offline-validated engine policy, so the
  stale-input disease can't touch them.

Offline replay on the recorded tick CSVs (scripts/cb_burst_guard_backtest.py,
AdaptiveRing mirrors the engine exactly):

| Session | Learned mean gap | Adaptive vs fixed guard |
|---|---|---|
| Crash 1000 08-30 (deployed ON) | 1581 s (26.3 min, 6 gaps) | **ΔR +0.00 — identical trades, identical blocks; validated Crash behavior preserved** |
| Boom 1000 08-29 (guard OFF) | 768 s (12.8 min, 9 gaps) | cost only **−0.60R** vs baseline (fixed guard cost −4.93R) — 1 block, +30.9R session kept |
| Boom 1000 08-30 (guard OFF) | warm-up transient (mg 6356→2222 s) | more conservative early (bigger window ⇒ more blocks); self-corrects as gaps accumulate |

Notes: the warm-up transient errs on the safe side (inflated mean gap →
inflated window → more blocks, not fewer). Boom stays guard-OFF per the
deployed policy, but the −0.60R adaptive result makes a Boom-side
re-enable worth re-validating on both recorded days before deciding. The
λ scale-invariance also pre-tunes the guard for any future Boom/Crash 150
pilot (mean gap ≈2.6 min → window ≈312 s, min-gap ≈94 s automatically).

---

## Constant-λ Spike-Probability A/B (2026-08-31) — verdict: keep the λ model

Offline A/B of the deployed constant-λ blend against the legacy
"time-since-spike" (overdue) blend on all three recorded tick sessions
(`scripts/cb_spike_prob_backtest.py`, full log
`artifacts/cb_spike_prob_results.txt`). The replay mirrors
`CrashBoomEngine.OnTickFade` in the engine's exact order (expire checks →
retrace window → burst-guard chain → min-RR → entry) and rebuilds
`CSpikeDetector` from the tick stream (body EMA with outlier exclusion,
grind walk, tick-speed ring, bar-spike detection at 2.2×EMA, λ EWMA trusted
at 3 gaps — the same λ feeds the adaptive guard geometry). The OLD
replication is validated against the 08-30 Experts-log entry prints (the
live charts ran the OLD model that day): matched prints 0.14 / 0.02 / 0.02
(Crash 3.4pts; Boom 7.8 / 33.9pts) — probabilities reproduce to the second
decimal wherever the sim recreates the same episode.

- **OLD blend** (v25.9, ran live 08-30): weights .30/.20/.25/.25; comp4 =
  min(1, bars_since_spike/50), 0.5 when never spiked — gambler's-fallacy
  growth with elapsed time.
- **NEW blend** (v26.9 deployed): weights .35/.25/.25/.15; comp4 = λ ramped
  over the refractory tail max(2, min_gap_obs), then flat at λ — no overdue
  term. 0.05 until λ is learned.

| Session | ΔR OLD→NEW (deployed guard) | entry flips | prob-blocks OLD | prob-blocks NEW | max prob at evals |
|---|---|---|---|---|---|
| Crash 1000 08-30 | +0.00 | 0 | 0 | 0 | 0.14 (OLD) / 0.10 (NEW) |
| Boom 1000 08-30 | +0.00 | 0 | 0 | 0 | 0.23 (OLD) / 0.13 (NEW) |
| Boom 1000 08-29 | +0.00 | 0 | 0 | 0 | 0.14 (both) |

Robustness: ATR ×0.8/×1.2 and spread ×1.5 on the deployed pair → **ΔR =
+0.00 in all 18 runs**. Gate sensitivity down to 0.20: still zero
prob-blocks under either model on every session.

**Verdict:**

1. At the deployed 0.70 gate the spike-probability gate is a **safety
   valve, not an active filter** — it never fired on any recorded session
   under either blend (live max print 0.26 on 08-30). The burst guard
   (cluster + min-gap, λ-scaled) is what actually throttles entries; the λ
   swap changed zero entries and zero R, net of spread.
2. What the λ model changes for real: printed probabilities are stable and
   principled (no growth with elapsed gap; comp4 max 0.50→0.35; entry
   prints drop e.g. 0.14→0.02). That feeds (a) **DynamicRiskSizing** — the
   OLD inflation could push prob past the 0.5 risk-reduction threshold on
   long-gap entries and silently shrink position size; NEW won't — and
   (b) the always-on M5-fade SPIKE-AVOID gate (outside tick-replay scope):
   with OLD, a 50-bar gap alone contributes a constant +0.25 toward the
   0.70 gate; NEW caps the contribution at ≈0.02. The upgrade removes a
   failure mode that simply hadn't manifested in three short sessions.
3. Keep: λ model deployed, gate 0.70. No parameter change justified by the
   data.

Known characteristics (documented, not bugs):

- The λ learner sees intra-cluster micro-gaps: Crash's 19:16/19:27/19:38
  cluster is 2-3 bar gaps, pulling the session λ to 0.458/bar (implied mean
  gap 11 min vs the .set's empirical ~39 min). The α=0.05 EWMA dilutes it,
  and the bias is conservative — it raises prob and tightens the shared
  adaptive-guard geometry exactly where throttling is wanted.
- Per-file replays start with a cold body EMA; the OLD model's
  "unknown → 0.5" default then inflates early-session prints (live charts
  are warm from prior days — authoritative live prints: 0.02-0.26). Both
  sim models share the same detector state, so the A/B itself is unaffected.
- On the tick-fade path the prob gate only runs while the burst guard is
  armed (the chain lives inside `if(m_burst_guard)`): Boom's deployed
  guard-OFF makes tick fades prob-immune there — the Boom A/B above is run
  under the fixed-guard counterfactual.

---

## v26.10 — AUTO Per-Symbol CB Parameters (2026-08-31)

The `InpCBBurstGuardMode` AUTO cure extended to the five CB numeric
parameters a stale stored chart input could poison. On 08-30 the compiled
defaults were v25.x-era (`max_prob 0.65`, `fade R 0.3`, `SL 0.5`,
`TP 1.5`) — a chart that never loaded its preset silently traded the wrong
exit geometry.

| Parameter | AUTO (0, compiled default) | CUSTOM (1) | Compiled numeric default (corrected v26.10) |
|---|---|---|---|
| spike-threshold | calibration profile: 2.2 (both 1000 symbols) | `InpCBSpikeThreshold` wins | 2.2 (unchanged) |
| max-spike-prob | profile: 0.70 | `InpCBMaxSpikeProb` wins | 0.65 → 0.70 |
| fade R | profile: 0.4 | `InpCBFadeR` wins | 0.3 → 0.4 |
| fade SL | profile: 0.3×ATR | `InpCBFadeSL` wins | 0.5 → 0.3 |
| fade TP | profile: 4.0×ATR | `InpCBFadeTP` wins | 1.5 → 4.0 |

Mechanics:

- `CrashBoomCalibration` profiles for Boom/Crash 1000 now carry the deployed
  v26.8 geometry (SL 0.3 / TP 4.0 / R 0.4) — single source of truth. The
  engine applies the profile at Init (including fade R, previously not
  profile-fed), and the EA only overrides in CUSTOM mode.
- Init logs one `[CB-PARAM] <name> = value (explicit override)` line per
  parameter on preset-loaded charts, or `(AUTO: Crash|Boom calibration
  profile)` on charts running the smart default. Both paths ship identical
  values; the log tells you which source decided.
- The SELF-CHECK banner gained a `CB-Params` row (`all AUTO (profile)` or
  `N/5 CUSTOM`).
- Both .set files pin all five `*Mode=1` (CUSTOM) with the deployed values,
  mirroring the burst-guard preset pinning — preset and no-preset charts
  agree by construction.
- The 500/300 profiles keep their legacy values (not grid-searched); AUTO
  on those symbols resolves to their own profile, not to the 1000 values.

**Policy self-check (v26.10):** at the end of init the EA prints a
`[POLICY] resolved config vs .set-declared policy` table — 16 rows comparing
what the chart will actually run with against the runtime mirror of the
presets (the `POLICY_*` constants in MitemshubAI.mq5): burst guard state +
the five CB parameters + tick-fade / spike-pts / timeout / max-hold /
base-risk / micro-fade / spike-direction / DailyHalt / MicroFit /
CloseDetect. Every row prints `resolved=… declared=… ok`; any deviation
prints `<-- MISMATCH` and a loud three-line summary listing each deviation
and the fix (load the symbol .set, or correct the flagged inputs).
Intentional overrides are allowed but **loud** — the Aug-30/31 stale-input
incidents were exactly silent drifts. Maintenance rule: whenever a .set
value changes, update the `POLICY_*` mirrors in the same commit; the check
is only as honest as the mirror.

---

## Deployment Checklist

When deploying a new version:

1. **Compile** in MetaEditor (F7) — must show `0 errors, 0 warnings`
2. **Copy** `MitemshubAI.mq5` + `CrashBoom/` folder + `Market/GarchForecaster.mqh` to all terminal `Experts/MITEMSHUB_AI/` directories — do NOT copy `Core/` (the modular `Constants.mqh` collides with the EA's own `ENUM_REGIME`; a stale terminal `Core/` caused the 2026-08-30 compile breakage)
3. **Copy** `.set` files to all terminal `Presets/` and `Profiles/Sets/MITEMSHUB_AI/` directories
4. **Remove** EA from charts → **Re-attach** → **Load preset**
5. **Verify** Experts tab shows correct version banner
6. **Verify burst-guard policy at init:** the Crash chart must log `[CB-BURSTGUARD] armed (AUTO: Crash policy)` or `armed (explicit override)`, and the Boom chart must log `[CB-BURSTGUARD] off (AUTO: Boom policy)` — the engine now prints the resolution source. If Boom logs `off (explicit override)` that's the pinned preset working; if Boom ever logs `armed`, the policy regressed — investigate. Later in the session, once 3 spike gaps are learned, Crash should log `[CB-BURSTGUARD] adaptive: window=… min-gap=…` (Boom must never log an armed line)
7. **Read the SELF-CHECK banner + `[CB-PARAM]` lines + the `[POLICY]` table** (all at the end of init): banner rows carry the deployed expectations — `DailyHalt=OFF`, Crash `BurstGuard=AUTO -> ON` / Boom `AUTO -> OFF`, `MicroFit=1.5%`, `LambdaModel=ON (built-in)`, `CloseDetect=ON`, `CB-Params=all AUTO (profile)` or `N/5 CUSTOM` (preset-loaded charts pin all five). The five `[CB-PARAM]` lines must show `(explicit override)` with spike-thresh 2.20 / max-spike-prob 0.70 / fade-R 0.40 / fade-SL 0.30 / fade-TP 4.00 on preset-loaded charts, or `(AUTO: … calibration profile)` with the SAME values on no-preset charts. The init must END with `[POLICY] 16/16 rows match the declared policy — config is clean.` — any `*** POLICY MISMATCH ***` block names the exact deviations and the fix; treat it as a blocker before the session's first trade. Maintenance: the `POLICY_*` constants are the runtime mirror of the presets — update them whenever a .set value changes. The v26.11 fixed-array self-test must print `[SELFTEST] fixed arrays OK …` BEFORE `Loaded intelligence`; a `[SELFTEST] FIXED-ARRAY MISMATCH — refusing to init` line means the binary is unsafe to trade — do not attach it.
6. **Check** Algo Trading is enabled (green button)

### Terminal Locations (12 instances)

All under `%APPDATA%\MetaQuotes\Terminal\`:
- `Common\MQL5\`
- `Community\MQL5\`
- `DBE9B8B347D025DD139E103EE3B63FD8\MQL5\`
- `DBE9B8FD872B0D86F5ACB327544180B7\MQL5\`
- `DBE9B8FD8D3F0A5F63E78FFB3541AD89\MQL5\`
- `FB9A56A49B919E62ABE10C65D15A49B9\MQL5\`
- `FB9A56A49B9660FC7FF1725BE43269F6\MQL5\`
- `FB9A56D617EDDDFE29EE54EBEFFA49B9\MQL5\`
- `FB9A56D617EDDDFE29EE54EBEFFE96C1\MQL5\` ← **Primary (VPS)**
- `FB9AED25E068D08A5E569156768947C5\MQL5\`
- `FB9AEDC55456465310AC15EDF0F2D6D5\MQL5\`
- `FB9AEDC5A0F7C1CF6B3ED6790FC09C1C\MQL5\`

---

## Known Issues & Fixes (v24.11)

| Issue | Status | Fix |
|-------|--------|-----|
| DAILY-HALT triggered from false loss (manual close) | ✅ Fixed | Uses deal history price instead of current market price |
| DAILY-HALT used equity comparison (unreliable) | ✅ Fixed | Uses realized P&L from g_daily_pnl |
| DAILY-HALT didn't reset at midnight | ✅ Fixed | Resets daily counters on new server day |
| Indicator handle leaks (Crash/Boom) | ✅ Fixed | Created once in Init(), released in Deinit() |
| SymbolCalibration never adapted | ✅ Fixed | UpdateLive() called on every bar + spike |
| Exit logic wrong for Crash/Boom | ✅ Fixed | CB-specific exits (spike-aware trailing, faster cuts) |

---

*This document is the single source of truth for all MITEMSHUB AI production configurations.*
