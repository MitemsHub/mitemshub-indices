# Synthetic AI Trader

**Institutional-grade AI trading intelligence for synthetic indices — powered by multi-timeframe analysis, probabilistic online learning, and structured explainability.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 15](https://img.shields.io/badge/next.js-15-black.svg)](https://nextjs.org/)
[![Tests](https://img.shields.io/badge/tests-313%20passed-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/license-proprietary-red.svg)](#license)

---

## What This Is

This is not another one-indicator Expert Advisor. Synthetic AI Trader is a **modular, research-first trading platform** that separates market data ingestion, multi-timeframe feature engineering, probabilistic modeling, decision fusion, risk controls, and execution into independent, testable components.

Built for **Volatility 75 (V75)** and **Volatility 100 (V100)** on Deriv via MT5.

### Key Design Principles

- **Separated concerns** — each module is independently testable and replaceable
- **Explainability first** — every signal comes with structured rationale, confidence breakdown, and invalidation levels
- **Paper-first** — the system must prove positive expectancy through walk-forward validation before any real execution
- **Online learning** — the model continuously adapts to regime changes without catastrophic forgetting
- **Feature flags** — experimental capabilities are gated and can be toggled without code changes

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Operator Dashboard (Next.js)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ Trade    │ │Intelligence│ │ History  │ │   Health     │   │
│  │  Plan    │ │  Panels   │ │  Panel   │ │  Dashboard   │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
│       └─────────────┼───────────┼───────────────┘           │
│                     │  Engine Bridge (Python ↔ TS)           │
└─────────────────────┼───────────────────────────────────────┘
                      │
┌─────────────────────┼───────────────────────────────────────┐
│              Python Trading Engine                            │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │ Market Data  │ │   Strategy   │ │   Risk Engine        │  │
│  │  Snapshot    │ │  Decision    │ │  Position sizing     │  │
│  │  Collector   │ │  Engine      │ │  Drawdown limits     │  │
│  └──────┬───────┘ └──────┬───────┘ └──────────┬──────────┘  │
│         │                │                     │              │
│  ┌──────┴───────┐ ┌──────┴───────┐ ┌──────────┴──────────┐  │
│  │   Feature    │ │    Model     │ │   Execution          │  │
│  │   Engine     │ │   Ensemble   │ │   Backend            │  │
│  │  46 features │ │  Online LR   │ │  MT5 / Deriv WS      │  │
│  └──────────────┘ └──────────────┘ └──────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────┼───────────────────────────────────────┐
│              Data Layer                                       │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │   MT5        │ │  Deriv WS    │ │   CSV Tick Store     │  │
│  │  Terminal    │ │  Adapter     │ │   (append + rotate)  │  │
│  └──────────────┘ └──────────────┘ └─────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## Features

### Phase 3 — Core Intelligence Engine

| Feature | Description |
|---------|-------------|
| **4-Timeframe Hierarchy** | 4H → 1H → 15M → 5M with per-timeframe regime detection |
| **Confluence Scoring** | Cross-timeframe alignment scores (0.4–0.9) |
| **Call Lifecycle** | `forming` → `actionable` → `confirmed` → `failing` → `cancelled` |
| **Hurst Exponent** | Long-term memory/persistence detection (0–1) |
| **Shannon Entropy** | Return distribution randomness quantification |
| **Market Structure** | FVG detection, internal BOS, equal highs/lows, liquidity sweeps |
| **Regime Detection** | Trend/range/volatile/compression with Hurst-aware persistence |
| **Background Scanner** | Async continuous monitoring with regime change alerts |

### Phase 4 — AI Evolution & Self-Improving Intelligence

| Feature | Description |
|---------|-------------|
| **FeatureSelector** | Automatic importance ranking, stability tracking, redundancy detection |
| **ModelCalibrator** | Platt scaling & isotonic regression for probability calibration |
| **ConfidenceScorer** | Multi-factor confidence (model + regime + structure + displacement) |
| **EnsembleModel** | Weighted combination of multiple models with online updates |
| **ModelMonitor** | Drift detection (KS-statistic), performance tracking (ECE, Brier) |
| **Explainability** | 15+ rationale factors per signal with structured trade rationales |

### Decision Engine — 8-Component Fusion

| Component | Weight | Purpose |
|-----------|--------|---------|
| Model | 0.28 | Calibrated directional probability |
| Structure | 0.22 | BOS, FVG, sweeps, internal structure |
| Regime | 0.15 | Regime + Hurst + entropy + volatility clustering |
| Confluence | 0.08 | Multi-timeframe alignment |
| Mean Reversion | 0.08 | Range position, RSI, Keltner/Donchian channels |
| Displacement | 0.07 | Body/ATR directional alignment |
| Momentum | 0.07 | Slope, EMA spread, recent returns |
| Volatility | 0.05 | ATR ratio, realized vol, volatility clustering |

---

## Operator Dashboard

The **MitemsHub Indices** operator dashboard is a Next.js 15 application providing:

- **Trade Plan Panel** — Real-time trade recommendations with entry/invalidation/target levels
- **AI Market Intelligence** — Regime analysis, bias scoring, and market thesis
- **Multi-Timeframe Alignment** — Visual alignment matrix across all timeframes
- **Bullish vs Bearish Evidence** — Ranked evidence with strength bars
- **Current Market Thesis** — AI-generated thesis with confidence and invalidation
- **Health Dashboard** — System health monitoring, MT5 diagnostics, bridge status
- **Trade History** — Complete trade journal with outcomes and performance metrics
- **Mobile-First Design** — Responsive layout with bottom navigation, haptic feedback, and pull-to-refresh

### Screenshots

The dashboard supports both light and dark themes with a sophisticated glass-morphism design system.

---

## Project Structure

```
Synthetic Indices Bot/
├── src/synthetic_trader/          # Python trading engine
│   ├── cli.py                     # Command-line interface
│   ├── config.py                  # Trader configuration & feature flags
│   ├── domain.py                  # Domain models (Tick, Candle, Signal)
│   ├── backtest/                  # Backtesting engine
│   ├── execution/                 # Execution backends (MT5, Deriv WS)
│   ├── features/                  # Feature engineering (46 features)
│   │   ├── indicators.py          # Technical indicators
│   │   ├── market_structure.py    # SMC/ICT-inspired structure detection
│   │   ├── regimes.py             # Volatility regime classification
│   │   └── multi_timeframe_structure.py
│   ├── journal/                   # Trade journaling
│   ├── live/                      # Live data collection
│   │   ├── market_snapshot.py     # Snapshot builder & alert engine
│   │   ├── signal_guardian.py     # Signal validation
│   │   └── execution_backends.py  # MT5 execution
│   ├── models/                    # ML models
│   │   ├── online.py              # Online logistic regression
│   │   └── advanced.py            # FeatureSelector, Calibrator, Ensemble
│   ├── research/                  # Walk-forward validation
│   ├── risk/                      # Risk management engine
│   ├── scanner/                   # Background scanner
│   └── strategy/                  # Decision engine & confirmation
│
├── external/mitemshub-indices/    # Next.js operator dashboard
│   ├── app/                       # Next.js App Router
│   │   ├── page.tsx               # Main dashboard
│   │   ├── globals.css            # Design system (light + dark themes)
│   │   └── api/                   # API routes
│   ├── src/
│   │   ├── components/
│   │   │   ├── intelligence/      # AI analysis panels
│   │   │   ├── operator/          # Dashboard shell & controls
│   │   │   └── ui/                # Shared UI utilities (haptic, skeleton)
│   │   └── lib/
│   │       ├── engine-bridge.ts   # Python ↔ TypeScript bridge
│   │       ├── health-logic.ts    # System health computation
│   │       └── python-runner.ts   # Python process management
│   └── tests/                     # Vitest test suite
│
├── infra/                         # AWS infrastructure (Terraform)
│   ├── main.tf                    # EC2, ALB, Security Groups
│   ├── variables.tf               # Input variables
│   ├── outputs.tf                 # Resource outputs
│   └── user_data.ps1              # Windows Server bootstrap
│
├── tests/                         # Python test suite (313 tests)
├── docs/                          # Architecture & phase documentation
│   ├── architecture.md            # System architecture
│   ├── PHASE3_SUMMARY.md          # Phase 3 implementation details
│   ├── PHASE4_SUMMARY.md          # Phase 4 implementation details
│   └── superpowers/               # Design specs & plans
└── pyproject.toml                 # Python project configuration
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- MT5 Terminal (Deriv) — for live data
- Git

### 1. Clone the Repository

```bash
git clone https://github.com/MitemsHub/mitemshub-indices.git
cd "Synthetic Indices Bot"
```

### 2. Set Up Python Engine

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -e ".[research,live]"
```

### 3. Set Up Operator Dashboard

```bash
cd external/mitemshub-indices
npm install
```

### 4. Configure Environment

Copy the environment template and fill in your MT5 credentials:

```bash
cp external/mitemshub-indices/.env.example external/mitemshub-indices/.env.local
```

Edit `.env.local` with your MT5 server, login, and password:

```
SYNTHETIC_MT5_SERVER=DerivSVG-Server-03
SYNTHETIC_MT5_LOGIN=your_login
SYNTHETIC_MT5_PASSWORD=your_password
SYNTHETIC_MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 Terminal\terminal64.exe
```

### 5. Start the Dashboard

```bash
cd external/mitemshub-indices
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## CLI Commands

### Backtest

```bash
python -m synthetic_trader.cli backtest --csv data/ticks.csv --symbol R_75 --timeframe 60
```

### Walk-Forward Validation

```bash
python -m synthetic_trader.cli walk-forward --csv data/ticks.csv --symbol R_75 --train-ticks 50000 --test-ticks 10000
```

### Collect Historical Data

```bash
python -m synthetic_trader.cli collect-history --symbol R_75 --count 50000 --output data/R_75_ticks.csv
```

### Paper Trading

```bash
python -m synthetic_trader.cli paper-live --symbol R_75 --duration-sec 900 --ticks-output data/R_75_live_ticks.csv
```

### Inspect Data

```bash
python -m synthetic_trader.cli inspect-data --csv data/ticks.csv --symbol R_75
```

---

## Testing

### Python Tests (313 tests)

```bash
python -m pytest tests/ -v
```

### Next.js Tests (88 tests)

```bash
cd external/mitemshub-indices
npm test
```

### Run All Tests

```bash
# Python
python -m pytest tests/ -v

# Next.js
cd external/mitemshub-indices && npm test
```

---

## Infrastructure (AWS Deployment)

The project includes Terraform templates for deploying to AWS EC2:

```bash
cd infra

# Initialize Terraform
terraform init

# Plan deployment
terraform plan -var-file="terraform.tfvars"

# Apply deployment
terraform apply -var-file="terraform.tfvars"
```

### What Gets Deployed

- **EC2 Instance** — t3.large Windows Server 2022
- **Application Load Balancer** — HTTP on port 80
- **Security Groups** — RDP restricted to admin IP, HTTP through ALB
- **Auto-Start** — PM2 + Windows Scheduled Task for boot persistence
- **Pre-installed** — Node.js 20, Python 3.10, Git, MT5 Terminal

### Required Variables

```hcl
aws_access_key    = "your-access-key"
aws_secret_key    = "your-secret-key"
aws_region        = "eu-north-1"
admin_ip          = "your.public.ip"
mt5_server        = "DerivSVG-Server-03"
mt5_login         = "your_login"
mt5_password      = "your_password"
```

See `infra/terraform.tfvars.example` for a template.

---

## Configuration

### Feature Flags

All experimental capabilities are gated via `FeatureFlags` in `config.py`:

```python
from synthetic_trader.config import TraderConfig, FeatureFlags

config = TraderConfig(
    features=FeatureFlags(
        enable_hurst=True,                    # Hurst exponent analysis
        enable_entropy=True,                  # Shannon entropy analysis
        enable_volatility_clustering=True,    # Vol autocorrelation
        enable_keltner_donchian=True,         # Channel position signals
        enable_fvg_detection=True,            # Fair value gap detection
        enable_internal_structure=True,       # Internal BOS detection
        enable_equal_highs_lows=True,         # Equal highs/lows detection
        enable_confidence_calibration=True,   # Probability calibration
        enable_explainability=True,           # Structured explanations
        enable_regime_persistence=True,       # Regime persistence tracking
        enable_multi_tf_confluence=True,      # Multi-timeframe confluence
    )
)
```

### Risk Configuration

```python
from synthetic_trader.config import RiskConfig

risk = RiskConfig(
    min_confidence=0.58,      # Minimum confidence to generate a signal
    max_position_pct=0.02,    # Max 2% of equity per trade
    max_drawdown_pct=0.10,    # Max 10% drawdown before pause
)
```

---

## Important Design Stances

### Synthetic Indices vs Real Markets

For synthetic indices, terms like **liquidity sweep**, **fair value gap**, **order block**, and **displacement** are treated as **price-structure features** — not as representations of real institutional order flow. These features are useful only if walk-forward evidence proves they add expectancy.

### Safety-First Upgrade Path

1. ✅ Collect high-quality tick data
2. ✅ Run walk-forward backtests
3. ✅ Run paper trading against live ticks
4. 🔲 Enable tiny-stake supervised live trading
5. 🔲 Full automation (only after surviving drawdown + drift tests)

**Never enable real execution until the paper journal proves positive expectancy** after realistic execution costs, latency, bad streaks, and regime changes.

---

## Monorepo Workflow

This is a monorepo. All Git operations happen at the root, even for changes in `external/mitemshub-indices/`.

```bash
# Always work from the root
git status
git add external/mitemshub-indices/src/components/
git commit -m "feat(dashboard): add new intelligence panel"
git push origin feature/mt5-rollout-enablement
```

Do not create or restore a nested `.git` directory inside `external/mitemshub-indices/`.

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code |
| `feature/mt5-rollout-enablement` | Active development for MT5 integration |
| `feat/phase2-paper-live-reliability` | Paper trading reliability improvements |

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Dashboard** | Next.js 15, React 18, TypeScript 5, Tailwind CSS |
| **Backend** | Python 3.11+, Online ML, NumPy, Pandas, scikit-learn |
| **Bridge** | Python child_process ↔ Next.js API routes |
| **Data** | MT5 Terminal (Deriv), Deriv WebSocket API |
| **Infrastructure** | Terraform, AWS EC2 (t3.large), ALB, PM2 |
| **Testing** | pytest (313 tests), Vitest (88 tests) |

---

## Contributing

1. Create a feature branch from `main`
2. Make your changes with tests
3. Ensure all tests pass: `python -m pytest tests/ -v && cd external/mitemshub-indices && npm test`
4. Submit a pull request with a clear description

---

## License

This is proprietary software. All rights reserved.

---

## Acknowledgments

Built with a research-first mindset — every feature must prove its value through walk-forward validation before being trusted with real capital.
