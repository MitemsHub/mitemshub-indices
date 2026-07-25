# Architecture

The platform is intentionally modular so each part can be improved without contaminating the rest of the research process.

## Core Flow

1. `Tick` data enters the candle builders.
2. Closed candles update the multi-timeframe history.
3. Feature assembly computes indicators, structure proxies, and volatility regime state.
4. The online model estimates directional probability.
5. The decision engine fuses model probability with structure, trend, mean-reversion, and displacement evidence.
6. The risk engine can veto the signal before any order intent is created.
7. Paper or live execution receives an `OrderIntent`.
8. Outcomes are journaled and used to update the model.

## Strong Assumptions

Synthetic indices do not expose a normal exchange order book. For that reason, this system treats Smart Money Concepts and ICT ideas as testable structure features:

- liquidity sweep means a swing high or low was breached and reclaimed
- break of structure means close beyond a prior swing
- fair value gap means a three-candle imbalance
- displacement means body size relative to ATR

These features are useful only if walk-forward evidence proves they add expectancy.

## Recommended Upgrade Path

1. Build a high-quality tick archive for `R_75` and `R_100`.
2. Add walk-forward splits and out-of-sample reports.
3. Replace the bootstrap online model with a calibrated ensemble.
4. Add a regime-specific policy selector.
5. Add live paper trading from Deriv ticks.
6. Add supervised tiny-stake execution.
7. Add full automation only after the system survives drawdown and drift tests.

## Current Commands

- `inspect-data`: checks tick count, symbols, duplicate ticks, ordering, price range, intervals, and largest single-tick return.
- `collect-history`: downloads Deriv historical ticks into CSV using the WebSocket adapter.
- `backtest`: runs the paper broker against a CSV tick file.
- `walk-forward`: repeatedly trains on one chronological window and tests on the next one.
- `paper-live`: subscribes to live Deriv ticks, simulates trades, journals outcomes, and never buys real contracts.

## Credential Boundaries

Market-data collection uses Deriv app ID `116450` by default. Real-money trading is not wired into the CLI yet. That is intentional: execution should be added only after out-of-sample and paper-live results show durable expectancy.
