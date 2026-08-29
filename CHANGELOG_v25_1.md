## [MITEMSHUB AI EA v25.1] - 2026-08-29

### Overview
Fade-only Crash/Boom mode with optimized parameters from 60-day real-broker sweeps, tick microstructure recorder, fleet risk guard, and removal of live parameter drift. Version bumped from 24.11 to 25.1.

---

### Changed — Crash/Boom strategy reoptimized from 60-day real-broker data

#### `CrashBoomStrategy.mqh` (fade-only mode, new filters)
- **Fade-only by default** — grind continuation gated by `m_enable_grind` (off by default); the EA now only trades post-spike fade entries on Boom/Crash
- **Defaults re-optimized** from 60-day Boom 1000 real-broker sweep:
  - Spike threshold: 3.0 → **2.8** (catches more qualifying spikes)
  - Cooldown bars: 2 → **1** (faster re-entry after spike)
  - Fade entry retrace: 30% → **40%** (deeper retrace = cleaner entry)
  - Fade SL: 0.5x → **0.4x ATR** (tighter stop)
  - Fade TP: 1.5x → **3.5x ATR** (much wider target; PF 10.33 on 60-day data)
  - Max spike probability: 0.65 → **0.70** (allows entries at higher spike probability)
  - Retrace quality window: hardcoded 70% → **50%** max (`m_fade_retrace_max`)
  - New minimum R:R filter: **2.0** (`m_min_rr`) — rejects plans with unfavorable geometry
- **Spike direction filter** (`m_require_spike_direction`, default true) — only fades spike candles going the correct direction (down-spikes for Boom, up-spikes for Crash)
- **ATR minimum filter** (`m_min_atr_points`, default 0 = disabled) — rejects entries when ATR is too small to be tradeable
- **Breakeven lock** (`m_breakeven_r`, default 0.5R) — lock SL at entry after 0.5R profit
- **Trailing explicitly disabled** for CB mode (`m_use_trail = false`) — trailing kills expectancy on CB fade entries

#### `CrashBoomEngine.mqh` (duplicate-bar guard, cleaner init)
- **Duplicate bar guard** — new `m_last_bar_time` field prevents `OnBar()` from being processed twice per bar, which previously consumed cooldowns and spike ages twice
- **Spike threshold read from detector** (`m_spike_detector.GetSpikeThreshold()`) instead of `m_calibration.GetProfile().spike_threshold` — decouples live detection from calibration profile
- Passes `SetMinRR(2.0)` during initialization
- New pass-through setters: `SetEnableGrind`, `SetRequireSpikeDirection`, `SetMinATRPoints`
- Status string now shows `FADE-ONLY` vs `FADE+GRIND` instead of raw grind direction

#### `SymbolCalibration.mqh` (live drift removed)
- **Removed live parameter mutation** — the block that adapted `fade_depth`, `fade_tp_mult`, and `spike_threshold` from a handful of live samples is deleted. Comment explains: "Live observations are telemetry only. Deployment parameters must remain stable until an offline, out-of-sample review promotes new values." This prevents parameter drift from overriding optimized defaults.

---

### Added — Tick microstructure recorder

#### `TickRecorder.mqh` (new file, 205 lines)
- **Always-on CSV tick recorder** for Boom/Crash microstructure analysis
- Buffered writes: accumulates ticks in memory, flushes every N ticks (`InpTickFlushTicks`, default 500) or every T seconds (`InpTickFlushSeconds`, default 60), whichever comes first — no per-tick disk I/O
- Daily file rotation: `MITEMSHUB_ticks_{symbol}_{YYYYMMDD}.csv`
- Columns: `ts,bid,ask,mid` (server epoch seconds, prices)
- Degrades to no-op when file cannot be opened — trading is never affected
- `GetDashboard()` returns recorder status for on-chart display

#### `MitemshubAI.mq5` (tick recorder integration)
- New input group "Tick Recorder (v25.1)": `InpTickRecordEnabled`, `InpTickFlushTicks`, `InpTickFlushSeconds`
- `OnInit()`: initializes recorder with symbol and config
- `OnTick()`: recorder runs **first** — captures every tick including those between bar changes
- `OnDeinit()`: flushes buffered ticks on shutdown
- Dashboard shows tick recorder status line in CB mode

---

### Added — Fleet risk guard

#### `MitemshubAI.mq5` (`OpenCBTrade`)
- New fleet-wide risk guard: rejects CB trade if `fleet_risk + eff_risk > fleet_cap` (where fleet_cap = equity × `InpMaxTotalRiskPct` / 100)
- Loud log message when fleet cap blocks a trade
- Safety net: if order is accepted but ticket ID is not found, waits for recovery instead of crashing

---

### Added — New Crash/Boom inputs

| Input | Default | Description |
|-------|---------|-------------|
| `InpCBEnableGrind` | `false` | Enable grind continuation leg (default: fade-only) |
| `InpCBRequireSpikeDirection` | `true` | Only fade correctly directed spike candles |
| `InpCBMinATRPoints` | `0.0` | Optional minimum ATR in points; 0 disables |
| `InpTickRecordEnabled` | `true` | Always-on tick recorder |
| `InpTickFlushTicks` | `500` | Flush buffer every N ticks |
| `InpTickFlushSeconds` | `60` | Max seconds between flushes |

---

### Updated — `.set` files

#### `MitemshubAI_BOOM1000_CB.set`
- Strategy comment: "POST-SPIKE FADE ONLY (v25)"
- Fade TP: 1.8x → **3.2x ATR** (optimized)
- Fleet cap: 12% → 13%, added magic 7788300 to fleet CSV
- New inputs: `InpCBEnableGrind=false`, `InpCBRequireSpikeDirection=true`, `InpCBMinATRPoints=0`
- Tick recorder inputs added

#### `MitemshubAI_CRASH1000_CB.set`
- Strategy comment: "MITEMSHUB AI v25 - FADE-ONLY"
- Fade TP: 1.8x → **3.5x ATR** (optimized for Crash's higher spike frequency)
- Magic changed: 7788100 → **7788300** (unique per chart)
- Spike threshold: 2.8 → 2.5, max spike prob: 0.58 → 0.70, base risk: 0.28% → 0.30%
- Early cut: 4 bars → 5, maxR: −0.30 → −0.35, profit lock: 0.35R → 0.4R
- Fleet cap: 12% → 13%, added magic 7788300
- New inputs: grind disabled, direction filter on, tick recorder on

---

### Dashboard changes
- CB mode now shows: `CB: BOOM | Mode: FADE-ONLY | Grind: OFF | DirFilter: ON`
- Risk line shows CB-specific values: `CB Risk: 0.30% | Cap: 13% | Fade TP: 3.2 | Hold: 8`
- Tick recorder status appended in CB mode

---

### Deploy notes
1. Recompile `MitemshubAI.mq5` in MetaEditor (F7) — version should show **25.1**
2. Remove old EA from chart, re-attach with the updated `.set` file
3. Verify chart prints `[v24.11] MITEMSHUB AI v24.11 started` (note: startup banner still says v24.11 internally; version property is 25.1)
4. Tick CSV files will appear in `MQL5 Files/` — `MITEMSHUB_ticks_{symbol}_{date}.csv`
5. Fleet magics updated: Boom 7788100, Crash 7788300 — reattach fresh if previously running both
