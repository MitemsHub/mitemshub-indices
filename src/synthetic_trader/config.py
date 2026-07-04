from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


DEFAULT_DERIV_APP_ID = "116450"


class LiveMode(str, Enum):
    PAPER = "paper"
    DRY_RUN_LIVE = "dry-run-live"
    ARMED_LIVE = "armed-live"


@dataclass(frozen=True)
class SymbolProfile:
    symbol: str
    display_name: str
    pip_size: float
    default_timeframe_sec: int = 60
    higher_timeframe_sec: int = 300
    stop_atr_multiple: float = 1.25
    take_profit_rr: float = 1.8
    min_history_candles: int = 80


@dataclass(frozen=True)
class RiskConfig:
    starting_equity: float = 1_000.0
    risk_per_trade: float = 0.005
    max_daily_loss_fraction: float = 0.02
    max_consecutive_losses: int = 4
    max_open_positions: int = 1
    min_confidence: float = 0.58
    min_reward_risk: float = 1.35
    max_volatility_z: float = 3.0
    stake_floor: float = 0.35


@dataclass(frozen=True)
class ModelConfig:
    learning_rate: float = 0.05
    l2: float = 0.0005
    decision_threshold: float = 0.58
    feature_clip: float = 8.0
    version: str = "online-logistic-v1"


@dataclass(frozen=True)
class PaperExecutionConfig:
    entry_slippage_ticks: float = 0.0
    exit_slippage_ticks: float = 0.0
    execution_penalty_per_trade: float = 0.0


@dataclass(frozen=True)
class TraderConfig:
    symbols: dict[str, SymbolProfile] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paper: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)

    @classmethod
    def default(cls) -> "TraderConfig":
        return cls(
            symbols={
                "R_75": SymbolProfile(
                    symbol="R_75",
                    display_name="Volatility 75 Index",
                    pip_size=0.01,
                    stop_atr_multiple=1.35,
                    take_profit_rr=1.9,
                ),
                "R_100": SymbolProfile(
                    symbol="R_100",
                    display_name="Volatility 100 Index",
                    pip_size=0.01,
                    stop_atr_multiple=1.45,
                    take_profit_rr=2.0,
                ),
            }
        )
