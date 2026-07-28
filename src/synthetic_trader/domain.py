from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class Regime(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    VOLATILE = "volatile"
    COMPRESSION = "compression"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    ENTER = "enter"
    HOLD = "hold"
    BLOCK = "block"


@dataclass(frozen=True)
class Tick:
    symbol: str
    epoch: float
    price: float
    # ── Rich tick columns (computed from consecutive ticks) ───────────
    # spread: estimated bid-ask spread proxy (half the absolute price change)
    spread: float = 0.0
    # direction: +1 = up, -1 = down, 0 = flat from previous tick
    tick_direction: int = 0
    # volume_proxy: ticks-per-second (1 / time_delta), higher = more activity
    volume_proxy: float = 0.0


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe_sec: int
    open_time: int
    open: float
    high: float
    low: float
    close: float
    tick_count: int = 1

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return self.close - self.open

    @property
    def body_abs(self) -> float:
        return abs(self.body)

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    epoch: float
    timeframe_sec: int
    features: Mapping[str, float]
    regime: Regime
    structure: Mapping[str, float]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    direction: Direction
    confidence: float
    min_confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    horizon_sec: int
    snapshot: FeatureSnapshot
    rationale: tuple[str, ...]
    model_version: str = "bootstrap"
    execution_stop: float | None = None
    thesis_invalidation: float | None = None
    primary_target: float | None = None
    extended_target: float | None = None
    hold_horizon_minutes: int | None = None
    execution_trigger_type: str | None = None
    signal_strength: str = "strong"  # "strong_buy" | "weak_buy" | "wait" | "weak_sell" | "strong_sell"

    @property
    def position_sizing(self) -> str:
        """Recommend position sizing based on signal strength.

        - strong_buy / strong_sell → "full" (full risk allocation)
        - weak_buy / weak_sell → "half" (reduced risk)
        - wait → "none" (no execution)
        """
        if self.signal_strength.startswith("strong"):
            return "full"
        elif self.signal_strength.startswith("weak"):
            return "half"
        return "none"

    @property
    def reward_risk(self) -> float:
        risk = abs(self.entry - self.stop_loss)
        reward = abs(self.take_profit - self.entry)
        if risk <= 0:
            return 0.0
        return reward / risk


@dataclass(frozen=True)
class OrderIntent:
    signal: TradeSignal
    stake: float
    max_loss: float
    metadata: Mapping[str, float | str] = field(default_factory=dict)


@dataclass
class Position:
    id: str
    signal: TradeSignal
    stake: float
    opened_at: float
    open_price: float
    is_open: bool = True
    closed_at: float | None = None
    close_price: float | None = None
    pnl: float = 0.0


@dataclass(frozen=True)
class TradeOutcome:
    position_id: str
    symbol: str
    direction: Direction
    entry: float
    exit: float
    pnl: float
    return_r: float
    opened_at: float
    closed_at: float
    features: Mapping[str, float]
    won: bool
