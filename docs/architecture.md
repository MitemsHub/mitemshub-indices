# Architecture

The platform is intentionally modular so each part can be improved without contaminating the rest of the research process.

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Operator Dashboard (Next.js 15)           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ Trade    │ │Intelligence│ │ History  │ │   Health     │   │
│  │  Plan    │ │  Panels   │ │  Panel   │ │  Dashboard   │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘   │
│       └─────────────┼───────────┼───────────────┘           │
│                     │  Engine Bridge (Python ↔ TS)           │
└─────────────────────┼───────────────────────────────────────┘
                      │
┌─────────────────────┼───────────────────────────────────────┐
│              Python Trading Engine                           │
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
│              Data Layer                                      │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │   MT5        │ │  Deriv WS    │ │   CSV Tick Store     │  │
│  │  Terminal    │ │  Adapter     │ │   (append + rotate)  │  │
│  └──────────────┘ └──────────────┘ └─────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Core Flow

1. `Tick` data enters from MT5 (Deriv) or Deriv WebSocket
2. Ticks are stored in CSV files and used to build candles
3. Feature assembly computes 46 indicators, structure proxies, and volatility regime state
4. The online model estimates directional probability
5. The 8-component decision engine fuses model probability with structure, regime, confluence, mean-reversion, displacement, momentum, and volatility evidence
6. The risk engine can veto the signal before any order intent is created
7. Paper or live execution receives an `OrderIntent`
8. Outcomes are journaled and used to update the model
9. The operator dashboard displays trade plans, intelligence panels, and health status in real-time

## Multi-Timeframe Hierarchy

The system analyzes 4 timeframes in a top-down hierarchy:

```
4H (Bias)  →  1H (Setup)  →  15M (Confirmation)  →  5M (Execution)
```

- **4H (Bias)**: Long-term directional bias, regime classification
- **1H (Setup)**: Structural setup identification, FVG/BOS detection
- **15M (Confirmation)**: Entry confirmation, pullback quality assessment
- **5M (Execution)**: Precise entry timing, risk management

Confluence scoring across timeframes: 3+ aligned trends = 0.9, 2 trends = 0.65-0.75, mixed = 0.4-0.5

## Decision Engine — 8-Component Fusion

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

## Data Sources

### MT5 (Primary)
- **Broker**: Deriv
- **Symbols**: Volatility 75 (V75), Volatility 100 (V100)
- **Data**: Real-time ticks, OHLC candles, account info
- **Connection**: MetaTrader5 Python package

### Deriv WebSocket (Fallback)
- **App ID**: 116450 (default)
- **Symbols**: R_75, R_100 (continuous contracts)
- **Data**: Historical ticks, real-time streaming
- **Note**: Deriv continuous contract prices differ from Deriv

## Strong Assumptions

Synthetic indices do not expose a normal exchange order book. For that reason, this system treats Smart Money Concepts and ICT ideas as testable structure features:

- liquidity sweep means a swing high or low was breached and reclaimed
- break of structure means close beyond a prior swing
- fair value gap means a three-candle imbalance
- displacement means body size relative to ATR

These features are useful only if walk-forward evidence proves they add expectancy.

## Deployment Architecture

### Local Development
```
Your Computer
├── Next.js Dashboard (localhost:3000)
├── Python Engine (child process)
└── MT5 Terminal (Deriv)
```

### AWS Production
```
AWS eu-north-1
├── EC2 Instance (Windows Server 2022)
│   ├── Next.js Dashboard (PM2)
│   ├── Python Engine (PM2)
│   └── MT5 Terminal (Deriv)
├── Application Load Balancer (HTTP)
├── Security Groups (RDP + HTTP)
└── EBS Volume (50GB encrypted)
```

## Credential Boundaries

- MT5 credentials stored in `.env.local` (never committed)
- AWS credentials stored in `terraform.tfvars` (gitignored)
- Deriv app ID `116450` used for historical data collection
- Real-money trading requires explicit enablement after walk-forward validation

## Upgrade Path

1. ✅ Collect high-quality tick data
2. ✅ Run walk-forward backtests
3. ✅ Run paper trading against live ticks
4. 🔲 Enable tiny-stake supervised live trading
5. 🔲 Full automation (only after surviving drawdown + drift tests)

**Never enable real execution until the paper journal proves positive expectancy** after realistic execution costs, latency, bad streaks, and regime changes.
