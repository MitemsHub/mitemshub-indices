# Synthetic AI Trader

Institutional-style research and execution scaffold for Deriv Synthetic Indices, focused first on Volatility 75 (`R_75`) and Volatility 100 (`R_100`).

This is not a one-indicator Expert Advisor. The platform is designed around separated modules:

- market data ingestion and candle construction
- multi-timeframe features
- market-structure and SMC/ICT-inspired structural proxies
- volatility regime classification
- probabilistic online learning
- decision fusion with explainable trade rationales
- portfolio and risk controls
- paper execution, journaling, and post-trade learning
- Deriv WebSocket adapter hooks for future live execution

Important design stance: for synthetic indices, terms like liquidity sweep, fair value gap, order block, and displacement are treated as price-structure features. They are not assumed to represent real institutional order flow unless Deriv exposes verifiable microstructure data.

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
