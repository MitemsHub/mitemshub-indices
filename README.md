# Synthetic AI Trader

Institutional-style research and execution scaffold for Deriv Synthetic Indices, focused first on Volatility 75 (`R_75`) and Volatility 100 (`R_100`).

This is not a one-indicator Expert Advisor. The platform is designed around separated modules:

- market data ingestion and candle construction
- multi-timeframe features (4H → 1H → 15M → 5M)
- market-structure and SMC/ICT-inspired structural proxies
- volatility regime classification with Hurst/entropy
- probabilistic online learning with confidence calibration
- decision fusion with explainable trade rationales
- portfolio and risk controls
- paper execution, journaling, and post-trade learning
- Deriv WebSocket adapter hooks for future live execution

Important design stance: for synthetic indices, terms like liquidity sweep, fair value gap, order block, and displacement are treated as price-structure features. They are not assumed to represent real institutional order flow unless Deriv exposes verifiable microstructure data.

## Phase 4 — AI Evolution, Benchmarking & Self-Improving Intelligence
See [docs/PHASE4_SUMMARY.md](docs/PHASE4_SUMMARY.md) for complete details on the Phase 4 upgrades:
- FeatureSelector: automatic feature importance ranking, stability tracking, redundancy detection
- ModelCalibrator: Platt scaling & isotonic regression for probability calibration
- ConfidenceScorer: multi-factor confidence (model + regime + structure + displacement)
- EnsembleModel: weighted combination of multiple models with online updates
- ModelMonitor: drift detection (KS-statistic), performance tracking (ECE, Brier, expectancy, PF)
- FeatureImportanceReport: structured explainability with stability scores
- Experiment tracking and model lifecycle management

## Phase 3 — Core Intelligence Engine
See [docs/PHASE3_SUMMARY.md](docs/PHASE3_SUMMARY.md) for complete details on the Phase 3 upgrades:
- 4-timeframe hierarchy with confluence scoring
- Continuous background scanner
- Call lifecycle (forming→actionable→confirmed→failing→cancelled)
- Hurst exponent, entropy, volatility clustering, channel features
- FVG detection, internal BOS, equal highs/lows, liquidity sweeps
- Regime detection with persistence (trend/range/volatile/compression)
- 8-component confidence scoring with calibration
- Structured explainability for every signal
- Feature flags for experimental capabilities

## Monorepo Layout

This project is one monorepo.

- Python engine: `src/synthetic_trader`
- Operator web app: `external/mitemshub-indices`
- Shared project docs: `docs/superpowers`

The operator app is part of the same repository as the engine. Keep feature work, documentation, and release coordination in this root repository.

## Root Git Workflow

Use the root repository for Git operations, even when the change is only in the app folder.

```powershell
git status
git add README.md external/mitemshub-indices/README.md
git commit -m "docs: describe unified monorepo workflow"
```

Do not create or restore a nested `.git` directory inside `external/mitemshub-indices`.

## Quick Start

Run tests:

```powershell
python -m unittest discover -s tests
```

Run a CSV backtest:

```powershell
python -m synthetic_trader.cli backtest --csv data/ticks.csv --symbol R_75 --timeframe 60
```

Inspect a tick dataset:

```powershell
python -m synthetic_trader.cli inspect-data --csv data/ticks.csv --symbol R_75
```

Run walk-forward validation:

```powershell
python -m synthetic_trader.cli walk-forward --csv data/ticks.csv --symbol R_75 --train-ticks 50000 --test-ticks 10000
```

Collect Deriv historical ticks:

```powershell
python -m synthetic_trader.cli collect-history --symbol R_75 --count 50000 --output data/R_75_ticks.csv
```

Run live paper trading against Deriv ticks:

```powershell
python -m synthetic_trader.cli paper-live --symbol R_75 --duration-sec 900 --ticks-output data/R_75_live_ticks.csv
```

Expected CSV columns:

```text
epoch,price
```

Optional columns:

```text
symbol
```

## Live Trading Safety

The live Deriv adapter is deliberately separated from the decision engine. The recommended path is:

1. collect tick data
2. run walk-forward backtests
3. run paper trading against live ticks
4. enable tiny-stake supervised live trading
5. only then consider full automation

Never give the system trade permissions until the paper journal proves positive expectancy after realistic execution costs, latency, bad streaks, and regime changes.

## What You Need To Provide Later

For data collection and paper-live mode, the default Deriv app ID is `116450`. You can override it with `--app-id` or `DERIV_APP_ID` later.

For real Deriv execution later, provide a Deriv API token with the minimum required permissions. Do not share it until we deliberately move from paper mode to supervised live mode.

For MT5 execution later, provide the broker/server name, login, investor or trading password depending on the integration, and the exact symbol names shown inside your MT5 Market Watch.

## Phase 3 — Core Intelligence Engine (The Brain)

Completed major upgrades to the analysis engine:

### Multi-Timeframe Hierarchy (4H → 1H → 15M → 5M)
- Full 4-timeframe support with per-timeframe regime detection
- Confluence scoring across timeframes (0.4–0.9)
- Structure notes with regime alignment tracking
- Backward compatible with 2-timeframe usage

### Continuous Background Scanner
- Async scanner with configurable intervals
- Per-symbol state tracking (regime, structure bias, direction)
- Regime change detection and alerting
- Callback-based integration

### Call Lifecycle Management
- States: `forming` → `actionable` → `confirmed` → `failing` → `cancelled`
- Quality assessment with trigger identification
- R_100 special case for counter-close continuations
- Previous state awareness for proper transitions

### Enhanced Feature Engineering (14 new features)
- **Hurst Exponent** — Long-term memory/persistence (0–1)
- **Shannon Entropy** — Return distribution entropy (0–1)
- **Volatility Clustering** — Volatility autocorrelation
- **Realized Volatility** — Annualized realized vol
- **ATR Z-Score** — Volatility regime detection
- **Keltner/Donchian Channel Position** — Mean-reversion signals

### Refined Market Structure Detection
- Swing detection with strength scoring
- Fair Value Gap (FVG) detection and active tracking
- Internal BOS (micro-structure breaks)
- Equal highs/lows detection (0.1% threshold)
- Liquidity sweep detection with reclaim tracking

### Improved Regime Detection
- Hurst-persistence aware trend detection
- Entropy-based noisy range identification
- Volatility clustering penalties
- Explicit transitional regime handling

### Decision Fusion (8 components, rebalanced weights)
| Component | Weight |
|-----------|--------|
| Model | 0.28 |
| Structure | 0.22 |
| Regime | 0.15 |
| Mean Reversion | 0.08 |
| Displacement | 0.07 |
| Momentum | 0.07 |
| Volatility | 0.05 |
| Confluence | 0.08 |

### Confidence Calibration
- Isotonic Regression (non-parametric)
- Platt Scaling (parametric)
- Automatic fallback for < 30 samples
- Online updates via `update_calibration()`

### Explainability
- `engine.explain_signal(signal)` → structured dict
- 15+ specific rationale factors per signal
- Explicit entry/invalidation/target reasoning

### Feature Flags
All experimental capabilities gated via `FeatureFlags` dataclass:
```python
config.features = FeatureFlags(
    enable_hurst=True,
    enable_entropy=True,
    enable_volatility_clustering=True,
    enable_confidence_calibration=True,
    enable_explainability=True,
)
```

### Test Results
```
288 passed, 6 subtests passed
```
All existing tests pass with updated expectations.

See `docs/PHASE3_SUMMARY.md` for complete details.
