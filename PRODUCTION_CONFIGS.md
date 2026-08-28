# Production Configurations — MITEMSHUB AI v24.11

> Last updated: 2026-08-28
> EA version: **v24.11** (`MitemshubAI.mq5`)
> Architecture: 5 Core Strategies + Crash/Boom Mode + 7 Intelligence Layers

---

## EA Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| **v24.11** | 2026-08-28 | Crash/Boom mode, tick analysis, MTF confirm, time-of-day, symbol calibration, handle leak fixes, DAILY-HALT bug fixes |
| v24.0 | 2026-08-28 | Initial Crash/Boom mode (spike detection, post-spike fade, dynamic risk) |
| v23.1 | 2026-08-27 | Intelligence layer (strategy review, regime review, time-block review, auto-disable) |
| v23.0 | 2026-08-27 | Cross-instance guard, state persistence, graduated exit, profit lock, volume scaling |
| v22.0 | 2026-08-25 | Daily-loss halt, effective-risk guardrail, band-fade, TF overrides, telemetry |
| v21.0 | 2026-08-24 | 5-core strategy engine (Pullback, Breakout, Momentum, MeanRevert, BandFade) |

---

## Active Live Presets

### Volatility Indices (M15)

| Preset | Symbol | TF | Risk | Style | Status |
|--------|--------|-----|------|-------|--------|
| `VOL75_FINAL.set` | Volatility 75 | M15 | 0.50% | Conservative | ✅ **LIVE** |
| `VOL75_AGGRO.set` | Volatility 75 | M15 | 0.50% | Aggressive | ✅ **LIVE** |
| `VOL100_FINAL.set` | Volatility 100 | M15 | 0.50% | Conservative | ✅ **LIVE** |
| `VOL100_AGGRO.set` | Volatility 100 | M15 | 0.50% | Aggressive | ✅ **LIVE** |
| `VOL10_FINAL.set` | Volatility 10 | M15 | 0.50% | Conservative | ✅ Available |
| `VOL25_FINAL.set` | Volatility 25 | M15 | 0.50% | Conservative | ✅ Available |
| `VOL50_FINAL.set` | Volatility 50 | M15 | 0.50% | Conservative | ✅ Available |
| `V100_H1.set` | Volatility 100 | H1 | 0.50% | Conservative | ✅ Available |
| `V100_M5.set` | Volatility 100 | M5 | 0.50% | Conservative | ✅ Available |

### Crash/Boom Indices (M5) — NEW in v24

| Preset | Symbol | TF | Risk | Strategy | Status |
|--------|--------|-----|------|----------|--------|
| `BOOM1000_CB.set` | Boom 1000 | M5 | 0.30% | Post-Spike Fade + Grind | ✅ Available |
| `CRASH1000_CB.set` | Crash 1000 | M5 | 0.28% | Post-Spike Fade + Grind | ✅ Available |

---

## Legacy Presets (Older EA Versions)

These presets were created for earlier EA versions (v16–v19) and may not be compatible with v24.11.

| Preset | Version | Symbol | Notes |
|--------|---------|--------|-------|
| `V6_OPTIMAL.set` | v6 | — | Historical reference |
| `V16_V100.set` | v16 | V100 | Legacy |
| `V17_V10.set` | v17 | V10 | Legacy |
| `V18_StepIndex.set` | v18 | Step Index | Legacy |
| `V19_StepIndex.set` | v19 | Step Index | Legacy |

---

## Testing / Paper Trading

| Preset | Purpose | Notes |
|--------|---------|-------|
| `PAPER_TEST.set` | Paper trading mode | No live execution |
| `TESTER_BFONLY_VOL75.set` | Strategy Tester: BandFade only on V75 | Backtesting |
| `TESTER_BFONLY_VOL100.set` | Strategy Tester: BandFade only on V100 | Backtesting |

---

## Synthetic Trader Presets (Legacy — Old EA)

These belong to the older Synthetic Trader system and are NOT used by MitemshubAI v24.

| Preset | Symbol | Tier |
|--------|--------|------|
| `SYN75_LIVE.set` | SYN75 | Live |
| `SYN75_TIER1.set` | SYN75 | Tier 1 |
| `SYN75_TIER2.set` | SYN75 | Tier 2 |
| `SYN75_TIER3.set` | SYN75 | Tier 3 |
| `SYN100_LIVE.set` | SYN100 | Live |
| `SYN100_TIER1.set` | SYN100 | Tier 1 |
| `SYN100_TIER2.set` | SYN100 | Tier 2 |
| `SYN100_TIER3.set` | SYN100 | Tier 3 |

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
| **Strategy Review** | Checks each strategy's win rate and expectancy | N=8 trades |
| **Regime Review** | Checks performance per regime (trend/range/volatile) | N=15 trades |
| **Time-Block Review** | Checks performance by time of day | N=20 trades |
| **Auto-Disable** | Disables strategies with negative expectancy | Min 12 trades, min 0.1R expectancy |
| **Volume Scaling** | Reduces lot after consecutive losses | 70% per loss, floor at 25% |
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
| `InpMaxDailyLossPct` | 3% | Daily loss limit (uses realized P&L) |
| `InpCoolDownBars` | 2 | Bars to wait after loss |
| `InpMagic` | 7788010/025/050/075/100 | Fleet magic numbers |

### Crash/Boom Indices (CB preset)

| Parameter | Boom 1000 | Crash 1000 | Description |
|-----------|-----------|------------|-------------|
| `InpCBBaseRisk` | 0.30% | 0.28% | Base risk per trade |
| `InpCBMaxSpikeProb` | 0.60 | 0.58 | Block entries above this spike probability |
| `InpCBSpikeThreshold` | 3.0x | 2.8x | Body ratio to classify as spike |
| `InpCBFadeR` | 0.3R | 0.3R | Fade entry R-level |
| `InpCBFadeSL` | 0.5R | 0.5R | Fade stop loss |
| `InpCBFadeTP` | 1.5R | 1.5R | Fade take profit |
| `InpEarlyCutBars` | 5 | 4 | Faster exit for CB |
| `InpEarlyCutMaxR` | -0.35R | -0.30R | Tighter early cut |
| `InpProfitLockR` | 0.4R | 0.35R | Tighter profit lock |
| `InpTrailStartR` | 0.8R | 0.7R | Earlier trailing activation |
| `InpTrailDistR` | 0.5R | 0.45R | Tighter trailing distance |
| `InpMaxTradesPerDay` | 10 | 10 | Prevent overtrading |

---

## Deployment Checklist

When deploying a new version:

1. **Compile** in MetaEditor (F7) — must show `0 errors, 0 warnings`
2. **Copy** `MitemshubAI.mq5` + `CrashBoom/` folder to all terminal `Experts/MITEMSHUB_AI/` directories
3. **Copy** `.set` files to all terminal `Presets/` and `Profiles/Sets/MITEMSHUB_AI/` directories
4. **Remove** EA from charts → **Re-attach** → **Load preset**
5. **Verify** Experts tab shows correct version banner
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
