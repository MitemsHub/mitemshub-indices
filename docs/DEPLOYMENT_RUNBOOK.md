# Deployment Runbook: Going Live on Deriv

## Overview

This runbook walks you through deploying the Synthetic Indices EA
(MitemshubAI) to a live Deriv MT5 account, from pre-flight
checks to live monitoring.

**Estimated time:** 45-60 minutes for first deployment.
**Risk level:** LIVE MONEY — follow every step carefully.

---

## CRITICAL: Breakeven Trail Configuration

**The breakeven trail has OPPOSITE effects depending on the symbol.**
This was discovered during the timeframe testing session:

| Symbol | Target | RR Ratio | Trail Setting | Why |
|--------|--------|----------|---------------|-----|
| **R_75** | 1.20 | 12:1 | **OFF** | Trail activates at 3.6R MFE — too early, converts all trades to breakeven exits (0% WR) |
| **R_100** | 0.80 | 8:1 | **ON (0.3)** | Trail activates at 2.4R MFE — just right, converts losing trades to breakeven exits (13.3% WR) |

**DO NOT** use the same trail setting for both symbols. The .set files in this repo are already configured correctly:
- `MitemshubAI_SYN75_*.set` → `InpTrailOn=false`
- `MitemshubAI_SYN100_*.set` → `InpTrailOn=true`

---

## Pre-Deployment Checklist

Complete every item before proceeding. Do NOT skip any step.

- [ ] Python backend passes mypy with zero errors
- [ ] All unit tests pass (`python -m pytest tests/ -x -q`)
- [ ] MQL5 EA compiles without errors in MetaEditor (F7)
- [ ] EGARCH calibration files exist for both symbols:
  - `data/garch_calibration/r_75.json`
  - `data/garch_calibration/r_100.json`
- [ ] Tick corpus is recent (last 24h):
  ```bash
  python -m synthetic_trader.cli tick-task-health
  ```
- [ ] .set preset files match the optimized parameters (verified in this session):
  - R_75: z=2.0, stop=0.10, target=1.20, trail=OFF
  - R_100: z=2.0, stop=0.10, target=0.80, trail=ON (0.3)
- [ ] You have admin access to the Deriv client portal
- [ ] You understand the risks (see "Honest Limits" at the end)

---

## Quick Start (TL;DR)

```bash
# 1. Verify Python environment
python -m pytest tests/test_ea_emitter.py tests/test_band_geometry.py -x -q

# 2. Verify EGARCH calibration
python -m synthetic_trader.cli calibrate-health --symbol R_75
python -m synthetic_trader.cli calibrate-health --symbol R_100

# 3. Verify tick data freshness
python -m synthetic_trader.cli tick-task-health

# 4. Start live monitoring dashboard
python -m synthetic_trader live-dashboard --interval 5

# 5. Start live pipeline (after MT5 EA is attached)
python -m synthetic_trader.cli live-watch --symbol R_75
python -m synthetic_trader.cli live-watch --symbol R_100
```

---

## Phase 1: MT5 Terminal Setup

### 1.1 Install MetaTrader 5

1. Download MT5 from Deriv:
   `https://www.deriv.com/metatrader-5/`
2. Install with default settings
3. Launch MT5 and log in with your **live account credentials**
   - Server: `DerivSVG-Server-03` (or your account's server)
   - Account number: your live account number
   - Password: your trading password

**IMPORTANT:** Verify you are logged into a LIVE account, not demo.
Check the account number and server in the bottom-right corner of MT5.

### 1.2 Enable Algo Trading

1. Go to **Tools > Options > Expert Advisors**
2. Check:
   - [x] Allow Algo Trading
   - [x] Allow WebRequest for listed URL (add `https://www.mql5.com` if needed)
3. Click OK

### 1.3 Install the EA

1. Copy these files to the MT5 Experts folder:
   ```
   Source:  mql5/MITEMSHUB_AI/MitemshubAI.mq5
   Target:  C:\Users\<YOU>\AppData\Roaming\MetaQuotes\Terminal\<ID>\MQL5\Experts\
   ```
   Also copy the entire `MITEMSHUB_AI/` folder structure (Core/, Strategies/, etc.)

2. Open **MetaEditor** (F4 in MT5)
3. Open `MitemshubAI.mq5` and compile (F7)
4. Verify: **0 errors, 0 warnings** in the Toolbox

### 1.4 Attach EA to Charts

**For R_75 (Volatility 75):**

1. Open a **SYN75** chart (any timeframe — the EA uses its own M15 candles)
2. Drag `MitemshubAI` from the Navigator panel onto the chart
3. In the inputs dialog, configure:
   - `InpCallFile` = `synth_calls_R_75.json`
   - `InpStateFile` = `synth_ea_state_R_75.json`
   - `InpSymbol` = `R_75`
   - `InpVenueSymbol` = `SYN75`
4. Click OK

**For R_100 (Volatility 100):**

1. Open a **SYN100** chart
2. Attach a second instance of `MitemshubAI`
3. Configure:
   - `InpCallFile` = `synth_calls_R_100.json`
   - `InpStateFile` = `synth_ea_state_R_100.json`
   - `InpSymbol` = `R_100`
   - `InpVenueSymbol` = `SYN100`

### 1.5 Load Optimized Presets

**Alternative to manual input configuration — use .set files:**

1. Copy the preset files to the MT5 Presets folder:
   ```
   Source:  mql5/MITEMSHUB_AI/MitemshubAI_SYN75_TIER1.set
   Target:  C:\Users\<YOU>\AppData\Roaming\MetaQuotes\Terminal\<ID>\MQL5\Profiles\Tester\
   ```
   (Repeat for all .set files)

2. When attaching the EA, click **Load** in the inputs dialog and select the
   appropriate .set file:
   - `MitemshubAI_SYN75_TIER1.set` — conservative risk for R_75
   - `MitemshubAI_SYN100_TIER1.set` — conservative risk for R_100

**CRITICAL: Verify the trail setting in the .set file matches the symbol:**

| .set File | InpTrailOn | InpTargetSigmaMult | Notes |
|-----------|------------|-------------------|-------|
| SYN75_TIER1 | **false** | 1.20 | Trail KILLS R_75 (12:1 RR) |
| SYN100_TIER1 | **true** | 0.80 | Trail HELPS R_100 (8:1 RR) |
| SYN75_LIVE | **false** | 1.20 | Same as TIER1 |
| SYN100_LIVE | **true** | 0.80 | Same as TIER1 |

**DO NOT** load a SYN75 .set file on a SYN100 chart or vice versa.

---

## Phase 2: Python Backend Setup

### 2.1 Verify the Environment

```bash
cd "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot"

# Check Python version
python --version  # Should be 3.11+

# Verify all dependencies
pip install -r requirements.txt 2>/dev/null || pip install -e ".[dev]"

# Verify mypy passes
python -m mypy src/synthetic_trader --ignore-missing-imports 2>&1 | tail -5
# Expected: Success: no issues found in 118 source files

# Verify all tests pass
python -m pytest tests/test_ea_emitter.py tests/test_band_geometry.py tests/test_decision_engine.py tests/test_risk_engine.py -x -q
# Expected: 61 passed
```

### 2.2 Verify EGARCH Calibration

```bash
python -m synthetic_trader.cli calibrate-health --symbol R_75
python -m synthetic_trader.cli calibrate-health --symbol R_100
```

Expected: both show `convergence=True` and healthy `vol_ratio`:
- R_75: vol_ratio ~0.607
- R_100: vol_ratio ~0.814

### 2.3 Verify Tick Data

```bash
python -m synthetic_trader.cli tick-task-health
```

Expected: collector is running and data is fresh (last update < 1h).

### 2.4 Verify EA Communication Path

```bash
# Check the Common Files folder exists
ls "$APPDATA/MetaQuotes/Terminal/Common/Files/" 2>/dev/null || echo "Folder not found"

# Or on Windows PowerShell:
dir "$env:APPDATA\MetaQuotes\Terminal\Common\Files\"
```

### 2.5 Verify Timeframe Configuration

The optimized parameters use M15 (900s) as the execution timeframe:

```bash
# Run timeframe comparison to verify
python -c "
from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_band import VolBandConfig, run_vol_band_backtest
from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.config import PaperExecutionConfig
from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

paper = PaperExecutionConfig(entry_slippage_ticks=0.05, exit_slippage_ticks=0.05)

for symbol, target, trail in [('R_75', 1.20, 0.0), ('R_100', 0.80, 0.3)]:
    ticks = dedupe_ticks(load_ticks_csv(f'data/backfill/{symbol}_ticks.csv', default_symbol=symbol))
    garch_state = load_calibrated_garch_state(symbol)
    config = VolBandConfig(z_entry=2.0, stop_sigma_mult=0.10, target_sigma_mult=target,
                           max_hold_sec=3600, breakeven_trail_frac=trail)
    report = run_vol_band_backtest(ticks, symbol, timeframe_sec=900,
                                   strategy_config=config, paper=paper, garch_state=garch_state)
    m = report.metrics
    print(f'{symbol} M15: trades={m.trades}, wr={m.win_rate:.1%}, pf={m.profit_factor:.2f}, exp={m.expectancy_r:+.4f}R')
"
```

Expected:
- R_75: trades=11, wr=27.3%, pf=4.04, exp=+2.22R
- R_100: trades=15, wr=13.3%, pf=2.34, exp=+0.61R

---

## Phase 3: Paper Trading (CRITICAL — Do Not Skip)

### 3.1 Run Paper-First Validation

Before live execution, verify the full pipeline works end-to-end:

```bash
python -m synthetic_trader.cli validate-system --symbol R_75 --duration-sec 60
```

This runs a zero-duration paper test to verify:
- EA state files are readable
- Call files are written atomically
- The EA can parse and execute calls

### 3.2 Start the Live Snapshot Pipeline

```bash
# Terminal 1: Start the live data feed
python -m synthetic_trader.cli live-watch --symbol R_75

# Terminal 2: Start the live data feed for R_100
python -m synthetic_trader.cli live-watch --symbol R_100
```

### 3.3 Monitor with the Dashboard

```bash
# Terminal 3: Live monitoring dashboard
python -m synthetic_trader live-dashboard --interval 5
```

Or use the direct module:
```bash
python -m synthetic_trader.live.dashboard --interval 5
```

### 3.4 Verify File Handoff

In the dashboard, confirm:
- Connection shows **LIVE** (not STALE) for both symbols
- Status shows `executed` or `pending` (not `no_file`)
- Pending orders appear when signals are generated

---

## Phase 4: Going Live

### 4.1 Confirm Paper Trading Results

After 24-48 hours of paper trading, check:

```bash
# Check execution history
python -m synthetic_trader.cli score-live-loop --once

# View the journal
python -m synthetic_trader.cli read-journal --symbol R_75 --limit 20
```

Verify:
- Trades are being executed (not just signals)
- P&L is within expected range
- No risk halt triggers on paper mode

### 4.2 Switch to Live Execution

1. **Stop the paper pipeline** (Ctrl+C in Terminal 1 and 2)

2. **Update the .env file** to enable live execution:
   ```bash
   # In .env or .env.local:
   SYNTH_EA_EMIT=1
   SYNTH_EA_VOLUME=0.1       # Start with MINIMUM volume
   SYNTH_LIVE_MODE=armed-live
   SYNTH_EA_FILES_DIR=C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal\Common\Files
   ```

3. **Restart the pipeline:**
   ```bash
   # Terminal 1
   python -m synthetic_trader.cli live-watch --symbol R_75

   # Terminal 2
   python -m synthetic_trader.cli live-watch --symbol R_100
   ```

4. **Enable Algo Trading in MT5:**
   - Click the "Algo Trading" button on the toolbar (should turn green)
   - Verify both EA instances show a smiley face in the top-right corner

5. **Verify the EA is receiving calls:**
   ```bash
   # Check if call files are being written
   ls -la "$APPDATA/MetaQuotes/Terminal/Common/Files/synth_calls_*.json"
   ```

   Expected: call files appear within 1-2 minutes of a signal.

### 4.3 First Live Trade Verification

1. Wait for the first signal to be generated
2. In the dashboard, verify the pending order appears
3. Watch MT5 for the order execution
4. In the dashboard, verify the position shows TICKET # with entry/SL

---

## Phase 5: Live Monitoring

### 5.1 Dashboard Monitoring

Keep the dashboard running at all times during live trading:

```bash
python -m synthetic_trader live-dashboard --interval 3
```

**What to watch:**

| Indicator | Healthy | Warning | Critical |
|-----------|---------|---------|----------|
| Connection | LIVE (< 30s) | STALE (> 5min) | NO STATE FILE |
| Position | FLAT or TICKET # | - | Multiple positions |
| Risk Halt | OK (no halts) | DAILY LOSS | CONSECUTIVE LOSS |
| Pending | (none) or valid call | - | Expired calls |

### 5.2 Daily Checklist

Every trading day, verify:

- [ ] Dashboard shows LIVE connection for both symbols
- [ ] No risk halt indicators are active
- [ ] EA instances have smiley faces (not frowning)
- [ ] Tick data is fresh (collector running)
- [ ] No error messages in MT5 Experts log

### 5.3 Emergency Procedures

**If the EA shows a frowning face:**
1. Check MT5 Experts tab for error messages
2. Verify Algo Trading is enabled (green button)
3. Right-click chart > Expert Advisors > Remove, then re-attach

**If the dashboard shows STALE:**
1. Check if the Python pipeline is still running
2. Verify the Common Files folder is accessible
3. Restart the live-watch pipeline

**If you see DAILY LOSS halt:**
1. This is NORMAL — the EA is protecting your account
2. The halt resets at midnight (server time)
3. Do NOT override the halt manually

**If you see CONSECUTIVE LOSS halt:**
1. The EA has hit its consecutive loss limit
2. Review recent trades in the journal
3. Consider reducing volume or pausing trading

---

## Phase 6: Going Live Checklist (Final Verification)

Before the first live trade, confirm:

- [ ] MT5 shows your live account balance (not demo)
- [ ] Both EA instances are attached and show smiley faces
- [ ] Algo Trading button is green
- [ ] Dashboard shows LIVE for both R_75 and R_100
- [ ] First call file appears in Common Files folder
- [ ] EA reads the call and places the order
- [ ] Dashboard shows the open position with ticket number

---

## Quick Reference: Key Commands

```bash
# Live monitoring
python -m synthetic_trader live-dashboard              # Continuous dashboard
python -m synthetic_trader live-dashboard --once       # One-shot snapshot

# Live pipeline
python -m synthetic_trader.cli live-watch --symbol R_75   # Start live feed
python -m synthetic_trader.cli live-snapshot --symbol R_75 # One-shot signal

# Health checks
python -m synthetic_trader.cli tick-task-health            # Collector health
python -m synthetic_trader.cli calibrate-health --symbol R_75  # Calibration

# Trading
python -m synthetic_trader.cli score-live-loop --once       # Score outcomes
python -m synthetic_trader.cli read-journal --symbol R_75   # View journal
```

---

## Honest Limits (Read Before Risking Real Money)

1. **Direction is ~50/50.** The model does not know whether R_75 will go up
   or down. The edge is in volatility timing and plan geometry, not direction.

2. **The volatility edge is real but small.** Calibrated EGARCH bands cover
   ~49-55% of p50 outcomes and ~88-92% of p90 outcomes — close to ideal,
   but the edge is small.

3. **Trade counts are still small.** The empirical gate needs >=10 scored
   outcomes per trigger type. Most types are still `still_learning`.

4. **Never trade money you cannot afford to lose.** This system is a
   research/automation platform, not a guarantee.

5. **Start with minimum volume.** The optimized parameters work in backtest,
   but live execution has slippage, spread, and execution delays that
   backtest does not capture.

---

## Appendix: Optimized Parameters (as of 2026-08-21)

### Symbol-Specific Configuration

| Parameter | R_75 | R_100 | Source |
|-----------|------|-------|--------|
| z_entry | 2.0 | 2.0 | Backtest sweep |
| stop_sigma_mult | 0.10 | 0.10 | Backtest sweep |
| target_sigma_mult | 1.20 | 0.80 | Backtest sweep |
| max_hold_sec | 3600 | 3600 | 1 hour default |
| min_target_rr | 2.0 | 2.0 | Risk gate |
| max_stop_pct | 0.015 | 0.015 | Safety cap |
| breakeven_trail_frac | **0.0 (OFF)** | **0.3 (ON)** | Timeframe test |
| execution_timeframe | **M15 (900s)** | **M15 (900s)** | Timeframe test |

### Timeframe Comparison Results

| Symbol | TF | Trail | Trades | WR% | PF | E[R] | PnL(R) |
|--------|-----|-------|--------|-----|-----|-------|--------|
| R_75 | M5 | none | 34 | 2.9% | 0.34 | -0.66 | -126 |
| R_75 | M5 | 0.3 | 47 | 0.0% | 0.00 | -0.74 | -187 |
| **R_75** | **M15** | **none** | **11** | **27.3%** | **4.04** | **+2.22** | **+148** |
| R_75 | M15 | 0.3 | 11 | 0.0% | 0.00 | -0.67 | -43 |
| R_75 | H1 | - | 0 | - | - | - | - |
| R_100 | M5 | none | 31 | 9.7% | 0.70 | -0.28 | -53 |
| R_100 | M5 | 0.3 | 34 | 5.9% | 0.56 | -0.32 | -65 |
| R_100 | M15 | none | 14 | 7.1% | 0.53 | -0.48 | -40 |
| **R_100** | **M15** | **0.3** | **15** | **13.3%** | **2.34** | **+0.61** | **+53** |
| R_100 | H1 | - | 0 | - | - | - | - |

### Key Findings

1. **M15 is the best execution timeframe** for both symbols
2. **H1 generates zero trades** — insufficient data (12-day corpus)
3. **M5 is too noisy** — consistently negative expectancy
4. **Breakeven trail has opposite effects** based on RR ratio:
   - R_75 (12:1 RR): trail KILLS performance (0% WR)
   - R_100 (8:1 RR): trail HELPS performance (13.3% WR)

---

## Appendix: File Locations

| File | Location | Purpose |
|------|----------|---------|
| EA state | `%APPDATA%\MetaQuotes\Terminal\Common\Files\synth_ea_state_*.json` | EA writes execution status |
| Call files | `%APPDATA%\MetaQuotes\Terminal\Common\Files\synth_calls_*.json` | Python writes approved calls |
| Calibration | `data/garch_calibration/r_*.json` | EGARCH model parameters |
| Tick data | `data/backfill/*_ticks.csv` | Historical tick corpus |
| Journal | `data/journal/*.jsonl` | Trade outcomes journal |

---

*Generated with Codebuff*
*Last updated: 2026-08-21*
