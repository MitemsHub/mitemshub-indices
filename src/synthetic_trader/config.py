from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Maximum number of candles fed to the decision/feature pipeline per
# evaluation.  Every indicator is a rolling window (<= 50 bars: atr_50,
# ema_50, MACD needs 35); swings/FVGs only need the last ~10-30 bars.
# Bounding the history prevents an O(n^2) full-history rescan per candle as
# the backtest (or live session) grows — over 10k candles that rescan made a
# 60s backtest take hours.
#
# Semantics note: hurst_exponent() estimates over whatever sample it is given,
# so once history exceeds this bound the Hurst estimate uses a fixed 400-bar
# sample instead of the full growing history.  Verified results-identical on
# the 300s backtest (2k candles, bound engaged), so this is harmless in
# practice — the rolling-window indicators are all far below the bound.
MAX_FEATURE_HISTORY = 400


DEFAULT_DERIV_APP_ID = "116450"


class LiveMode(str, Enum):
    PAPER = "paper"
    DRY_RUN_LIVE = "dry-run-live"
    ARMED_LIVE = "armed-live"


class Venue(str, Enum):
    DERIV = "deriv"
    MT5 = "mt5"


@dataclass(frozen=True)
class SymbolProfile:
    symbol: str
    display_name: str
    pip_size: float
    default_timeframe_sec: int = 60
    higher_timeframe_sec: int = 300
    stop_atr_multiple: float = 1.25
    take_profit_rr: float = 1.8
    min_history_candles: int = 30
    confidence_relaxation: float = 0.0
    bias_timeframe_sec: int = 14_400
    setup_timeframe_sec: int = 3_600
    confirmation_timeframe_sec: int = 900
    execution_timeframe_sec: int = 300
    monitoring_timeframe_sec: int = 60
    hold_bars_bias: int = 6
    hold_bars_setup: int = 8
    confirmed_setup_confidence_floor: float = 0.0
    intraday_hold_horizon_minutes: int = 60
    min_primary_reward_risk: float = 1.2
    travel_budget_5m_bars: int = 12
    min_continuation_body_efficiency: float = 0.55
    min_close_location_strength: float = 0.70
    min_reclaim_quality_score: float = 0.65
    late_extension_rejection_ratio: float = 0.70
    max_stop_distance_pct: float = 0.05


@dataclass(frozen=True)
class RiskConfig:
    starting_equity: float = 1_000.0
    risk_per_trade: float = 0.005
    max_daily_loss_fraction: float = 0.02
    max_consecutive_losses: int = 4
    max_open_positions: int = 1
    min_confidence: float = 0.48
    min_reward_risk: float = 1.2
    max_volatility_z: float = 3.0
    stake_floor: float = 0.35
    min_session_quality: float = 0.35  # session filter gate: block bottom-third low-vol hours
    session_filter_warmup: int = 500  # minimum observations (~8 min at 1/sec) before filter activates


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
class Mt5Config:
    server: str | None = None
    login: str | None = None
    password: str | None = None
    terminal_path: str | None = None
    symbol_map: dict[str, str] = field(default_factory=dict)

    def resolve_symbol(self, symbol: str) -> str | None:
        return self.symbol_map.get(symbol)


@dataclass(frozen=True)
class FeatureFlags:
    enable_hurst: bool = True
    enable_entropy: bool = True
    enable_volatility_clustering: bool = True
    enable_keltner_donchian: bool = True
    enable_fvg_detection: bool = True
    enable_internal_structure: bool = True
    enable_equal_highs_lows: bool = True
    enable_confidence_calibration: bool = True
    enable_explainability: bool = True
    enable_regime_persistence: bool = True
    enable_multi_tf_confluence: bool = True


@dataclass(frozen=True)
class TraderConfig:
    symbols: dict[str, SymbolProfile] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paper: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)
    mt5: Mt5Config = field(default_factory=Mt5Config)
    features: FeatureFlags = field(default_factory=FeatureFlags)

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
                    confidence_relaxation=0.08,
                    travel_budget_5m_bars=10,
                    min_continuation_body_efficiency=0.58,
                    min_close_location_strength=0.72,
                    min_reclaim_quality_score=0.66,
                    late_extension_rejection_ratio=0.74,
                    max_stop_distance_pct=0.04,
                ),
                "R_100": SymbolProfile(
                    symbol="R_100",
                    display_name="Volatility 100 Index",
                    pip_size=0.01,
                    stop_atr_multiple=1.45,
                    take_profit_rr=2.0,
                    confidence_relaxation=0.08,
                    confirmed_setup_confidence_floor=0.52,
                    travel_budget_5m_bars=12,
                    min_continuation_body_efficiency=0.55,
                    min_close_location_strength=0.70,
                    min_reclaim_quality_score=0.65,
                    late_extension_rejection_ratio=0.70,
                    max_stop_distance_pct=0.05,
                ),
            }
        )
