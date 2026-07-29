"""Backtesting and walk-forward simulation."""

from synthetic_trader.backtest.engine import BacktestEngine, BacktestResult, load_ticks_csv
from synthetic_trader.backtest.synthetic_generator import (
    DerivCSPRNG,
    GARCHParams,
    SyntheticIndexConfig,
    SyntheticPriceGenerator,
    generate_synthetic_datasets,
    generate_multi_symbol_datasets,
)
from synthetic_trader.backtest.synthetic_validation import (
    ValidationResult,
    SyntheticDataReport,
    validate_synthetic_data,
)
from synthetic_trader.backtest.synthetic_runner import (
    EpisodeResult,
    CurveFittingReport,
    SyntheticBacktestRunner,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "load_ticks_csv",
    "DerivCSPRNG",
    "GARCHParams",
    "SyntheticIndexConfig",
    "SyntheticPriceGenerator",
    "generate_synthetic_datasets",
    "generate_multi_symbol_datasets",
    "ValidationResult",
    "SyntheticDataReport",
    "validate_synthetic_data",
    "EpisodeResult",
    "CurveFittingReport",
    "SyntheticBacktestRunner",
]
