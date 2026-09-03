# Changelog

All notable changes to Synthetic AI Trader are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

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
