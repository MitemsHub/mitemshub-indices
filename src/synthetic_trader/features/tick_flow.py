"""Tick-level feature engine for Blueberry Volatility indices.

Computes high-frequency features from raw tick data that capture
micro-structure dynamics invisible in candle-based analysis:

- Tick direction, velocity, acceleration
- Up/down tick ratio and consecutive streaks
- Impulse vs retracement analysis
- Price position within the recent tick range
- Tick-level momentum and exhaustion signals

These features feed into the regime-specific strategy models and
enable probabilistic predictions at the tick level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class TickFlowState:
    """Accumulated tick flow statistics for a sliding window."""

    # Direction tracking
    up_ticks: int = 0
    down_ticks: int = 0
    flat_ticks: int = 0
    total_ticks: int = 0

    # Consecutive streaks
    consecutive_up: int = 0
    consecutive_down: int = 0
    max_consecutive_up: int = 0
    max_consecutive_down: int = 0

    # Velocity and acceleration
    velocity: float = 0.0  # average move per tick (signed)
    acceleration: float = 0.0  # change in velocity
    prev_velocity: float = 0.0

    # Impulse vs retracement
    impulse_up_sum: float = 0.0
    impulse_down_sum: float = 0.0
    retrace_up_sum: float = 0.0
    retrace_down_sum: float = 0.0
    impulse_count: int = 0
    retrace_count: int = 0

    # Price range
    tick_high: float = 0.0
    tick_low: float = 0.0
    current_price: float = 0.0
    price_position: float = 0.5  # 0 = at low, 1 = at high

    # Momentum
    momentum_sum: float = 0.0
    momentum_count: int = 0

    # Raw tick deltas for rolling calculations
    deltas: List[float] = field(default_factory=list)

    def up_ratio(self) -> float:
        """Fraction of up ticks (0-1)."""
        if self.total_ticks == 0:
            return 0.5
        return self.up_ticks / self.total_ticks

    def down_ratio(self) -> float:
        """Fraction of down ticks (0-1)."""
        if self.total_ticks == 0:
            return 0.5
        return self.down_ticks / self.total_ticks

    def avg_impulse(self) -> float:
        """Average impulse magnitude (upward)."""
        if self.impulse_count == 0:
            return 0.0
        return (self.impulse_up_sum + self.impulse_down_sum) / self.impulse_count

    def avg_retrace(self) -> float:
        """Average retracement magnitude."""
        if self.retrace_count == 0:
            return 0.0
        return (self.retrace_up_sum + self.retrace_down_sum) / self.retrace_count

    def impulse_retrace_ratio(self) -> float:
        """Ratio of average impulse to average retrace (>1 = trending)."""
        avg_rt = self.avg_retrace()
        if avg_rt < 1e-10:
            return 5.0  # cap at 5x if no retracements
        return min(self.avg_impulse() / avg_rt, 5.0)

    def streak_bias(self) -> float:
        """Net consecutive streak bias (-1 to +1). Positive = up streak."""
        max_streak = max(self.max_consecutive_up, self.max_consecutive_down, 1)
        return (self.consecutive_up - self.consecutive_down) / max_streak

    def exhaustion_signal(self) -> float:
        """Detect potential exhaustion (0-1, higher = more exhausted).

        Exhaustion = long streak + slowing velocity + small impulse size.
        """
        if self.total_ticks < 5:
            return 0.0

        # Long streak component
        streak_len = max(self.consecutive_up, self.consecutive_down)
        streak_component = min(streak_len / 15.0, 1.0)

        # Slowing velocity component
        velocity_component = 1.0 - min(abs(self.velocity) * 10.0, 1.0)

        # Small impulse component
        if self.impulse_count > 0:
            impulse_component = 1.0 - min(self.avg_impulse() * 5.0, 1.0)
        else:
            impulse_component = 0.5

        return (streak_component * 0.4 + velocity_component * 0.3 + impulse_component * 0.3)

    def to_features(self) -> dict[str, float]:
        """Convert accumulated state to a feature dictionary.

        Returns neutral defaults if no ticks have been processed yet.
        """
        if self.total_ticks == 0:
            return {
                "tick_up_ratio": 0.5, "tick_down_ratio": 0.5, "tick_total": 0.0,
                "tick_consecutive_up": 0.0, "tick_consecutive_down": 0.0,
                "tick_streak_bias": 0.0, "tick_velocity": 0.0, "tick_acceleration": 0.0,
                "tick_impulse_retrace_ratio": 1.0, "tick_avg_impulse": 0.0,
                "tick_avg_retrace": 0.0, "tick_impulse_count": 0.0,
                "tick_price_position": 0.5, "tick_momentum": 0.0, "tick_exhaustion": 0.0,
            }
        return {
            # Direction
            "tick_up_ratio": self.up_ratio(),
            "tick_down_ratio": self.down_ratio(),
            "tick_total": float(self.total_ticks),
            # Streaks
            "tick_consecutive_up": float(self.consecutive_up),
            "tick_consecutive_down": float(self.consecutive_down),
            "tick_streak_bias": self.streak_bias(),
            # Velocity and acceleration
            "tick_velocity": self.velocity,
            "tick_acceleration": self.acceleration,
            # Impulse vs retrace
            "tick_impulse_retrace_ratio": self.impulse_retrace_ratio(),
            "tick_avg_impulse": self.avg_impulse(),
            "tick_avg_retrace": self.avg_retrace(),
            "tick_impulse_count": float(self.impulse_count),
            # Price position
            "tick_price_position": self.price_position,
            # Momentum and exhaustion
            "tick_momentum": self.momentum_sum / max(self.momentum_count, 1),
            "tick_exhaustion": self.exhaustion_signal(),
        }


class TickFlowEngine:
    """Computes tick-level features from a sliding window of raw ticks.

    Usage:
        engine = TickFlowEngine(window_size=200)
        for tick in ticks:
            engine.update(tick.price)
        features = engine.features()
    """

    def __init__(self, window_size: int = 200):
        self.window_size = window_size
        self._prices: List[float] = []
        self._deltas: List[float] = []
        self._state = TickFlowState()

    def update(self, price: float) -> TickFlowState:
        """Add a new tick price and update all flow statistics."""
        self._prices.append(price)
        if len(self._prices) > self.window_size:
            self._prices = self._prices[-self.window_size:]
            # Recalculate window high/low from the trimmed window
            self._state.tick_high = max(self._prices)
            self._state.tick_low = min(self._prices)

        state = self._state
        state.current_price = price
        state.total_ticks += 1

        # Initialize range on first tick
        if state.total_ticks == 1:
            state.tick_high = price
            state.tick_low = price
            state.prev_velocity = 0.0
            return state

        prev_price = self._prices[-2] if len(self._prices) >= 2 else price
        delta = price - prev_price
        self._deltas.append(delta)
        if len(self._deltas) > self.window_size:
            self._deltas = self._deltas[-self.window_size:]

        # Update price range
        state.tick_high = max(state.tick_high, price)
        state.tick_low = min(state.tick_low, price)
        price_range = state.tick_high - state.tick_low
        if price_range > 1e-10:
            state.price_position = (price - state.tick_low) / price_range
        else:
            state.price_position = 0.5

        # Direction tracking
        if delta > 0:
            state.up_ticks += 1
            state.consecutive_up += 1
            state.consecutive_down = 0
            state.max_consecutive_up = max(state.max_consecutive_up, state.consecutive_up)
        elif delta < 0:
            state.down_ticks += 1
            state.consecutive_down += 1
            state.consecutive_up = 0
            state.max_consecutive_down = max(state.max_consecutive_down, state.consecutive_down)
        else:
            state.flat_ticks += 1

        # Velocity (exponential moving average of deltas)
        alpha = 2.0 / (min(state.total_ticks, 20) + 1)
        state.prev_velocity = state.velocity
        state.velocity = alpha * delta + (1 - alpha) * state.velocity

        # Acceleration (change in velocity)
        state.acceleration = state.velocity - state.prev_velocity

        # Impulse vs retracement
        if delta > 0:
            # Check if this continues the current move (impulse) or counters it (retrace)
            if state.consecutive_up > 1:
                state.impulse_up_sum += abs(delta)
                state.impulse_count += 1
            elif state.consecutive_down == 0 and state.consecutive_up == 1:
                # First tick after a down streak = potential reversal impulse
                state.impulse_up_sum += abs(delta) * 1.5  # weight reversals higher
                state.impulse_count += 1
            else:
                state.retrace_up_sum += abs(delta)
                state.retrace_count += 1
        elif delta < 0:
            if state.consecutive_down > 1:
                state.impulse_down_sum += abs(delta)
                state.impulse_count += 1
            elif state.consecutive_up == 0 and state.consecutive_down == 1:
                state.impulse_down_sum += abs(delta) * 1.5
                state.impulse_count += 1
            else:
                state.retrace_down_sum += abs(delta)
                state.retrace_count += 1

        # Momentum (rolling average of absolute deltas)
        state.momentum_sum += abs(delta)
        state.momentum_count += 1
        if state.momentum_count > 50:
            # Decay old momentum
            decay = 0.98
            state.momentum_sum *= decay
            state.momentum_count = max(int(state.momentum_count * decay), 1)

        return state

    def features(self) -> dict[str, float]:
        """Return the current tick flow features as a dictionary."""
        return self._state.to_features()

    def state(self) -> TickFlowState:
        """Return the raw tick flow state."""
        return self._state

    def reset(self) -> None:
        """Reset the engine for a new symbol."""
        self._prices.clear()
        self._deltas.clear()
        self._state = TickFlowState()
