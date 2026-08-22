"""Tick-level feature engine for Deriv Volatility indices.

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
from typing import List
import math


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

    # ── Spread features (bid-ask proxy) ──────────────────────────
    spread_sum: float = 0.0
    spread_sq_sum: float = 0.0  # for variance calculation
    spread_max: float = 0.0
    spread_count: int = 0
    recent_spreads: List[float] = field(default_factory=list)

    # ── Direction streak features (from tick_direction) ───────────
    direction_streak_up: int = 0
    direction_streak_down: int = 0
    direction_streak_flat: int = 0
    max_direction_streak_up: int = 0
    max_direction_streak_down: int = 0
    direction_switches: int = 0
    prev_direction: int = 0  # +1, -1, 0

    # ── Volume features (ticks-per-second proxy) ──────────────────
    volume_sum: float = 0.0
    volume_sq_sum: float = 0.0  # for variance calculation
    volume_max: float = 0.0
    volume_count: int = 0
    recent_volumes: List[float] = field(default_factory=list)
    volume_surge_count: int = 0  # ticks above 2x mean

    # ── Rolling tick frequency (ticks per 10-second window) ──────
    timestamps: List[float] = field(default_factory=list)
    freq_window_sec: float = 10.0  # rolling window size in seconds
    freq_history: List[float] = field(default_factory=list)  # historical freq values

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

    # ── Spread features ──────────────────────────────────────────

    def spread_mean(self) -> float:
        """Mean spread over the window."""
        if self.spread_count == 0:
            return 0.0
        return self.spread_sum / self.spread_count

    def spread_std(self) -> float:
        """Standard deviation of spread (spread volatility)."""
        if self.spread_count < 2:
            return 0.0
        mean = self.spread_sum / self.spread_count
        variance = (self.spread_sq_sum / self.spread_count) - (mean ** 2)
        return math.sqrt(max(variance, 0.0))

    def spread_z_score(self) -> float:
        """Current spread z-score vs recent window (high = unusually wide spread)."""
        if len(self.recent_spreads) < 5 or self.spread_count < 5:
            return 0.0
        recent_mean = sum(self.recent_spreads[-50:]) / len(self.recent_spreads[-50:])
        recent_var = sum((s - recent_mean) ** 2 for s in self.recent_spreads[-50:]) / len(self.recent_spreads[-50:])
        recent_std = math.sqrt(max(recent_var, 1e-10))
        current = self.recent_spreads[-1] if self.recent_spreads else 0.0
        return (current - recent_mean) / recent_std

    def spread_features(self) -> dict[str, float]:
        """Spread feature dictionary."""
        return {
            "tick_spread_mean": self.spread_mean(),
            "tick_spread_std": self.spread_std(),
            "tick_spread_max": self.spread_max,
            "tick_spread_z_score": self.spread_z_score(),
        }

    # ── Direction streak features ─────────────────────────────────

    def direction_streak_bias(self) -> float:
        """Net direction streak bias from tick_direction data (-1 to +1)."""
        max_streak = max(self.max_direction_streak_up, self.max_direction_streak_down, 1)
        return (self.direction_streak_up - self.direction_streak_down) / max_streak

    def direction_switch_rate(self) -> float:
        """Fraction of ticks that changed direction (0-1, high = choppy)."""
        if self.total_ticks < 2:
            return 0.0
        return self.direction_switches / (self.total_ticks - 1)

    def direction_features(self) -> dict[str, float]:
        """Direction streak feature dictionary."""
        return {
            "tick_dir_streak_bias": self.direction_streak_bias(),
            "tick_dir_switch_rate": self.direction_switch_rate(),
            "tick_dir_max_streak_up": float(self.max_direction_streak_up),
            "tick_dir_max_streak_down": float(self.max_direction_streak_down),
            "tick_dir_switches": float(self.direction_switches),
        }

    # ── Volume surge features ─────────────────────────────────────

    def volume_mean(self) -> float:
        """Mean volume proxy over the window."""
        if self.volume_count == 0:
            return 0.0
        return self.volume_sum / self.volume_count

    def volume_std(self) -> float:
        """Standard deviation of volume proxy."""
        if self.volume_count < 2:
            return 0.0
        mean = self.volume_sum / self.volume_count
        variance = (self.volume_sq_sum / self.volume_count) - (mean ** 2)
        return math.sqrt(max(variance, 0.0))

    def volume_surge_ratio(self) -> float:
        """Fraction of ticks that were volume surges (above 2x mean). 0-1."""
        if self.volume_count < 10:
            return 0.0
        return self.volume_surge_count / self.volume_count

    def volume_features(self) -> dict[str, float]:
        """Volume surge feature dictionary."""
        return {
            "tick_vol_mean": self.volume_mean(),
            "tick_vol_std": self.volume_std(),
            "tick_vol_max": self.volume_max,
            "tick_vol_surge_ratio": self.volume_surge_ratio(),
        }

    # ── Rolling tick frequency features ─────────────────────────

    def tick_frequency(self) -> float:
        """Current rolling tick frequency (ticks per freq_window_sec).

        Counts how many timestamps fall within the last freq_window_sec
        seconds. High frequency = unusually active market; low = quiet.
        """
        if not self.timestamps or len(self.timestamps) < 2:
            return 0.0
        current_time = self.timestamps[-1]
        cutoff = current_time - self.freq_window_sec
        count = 0
        for ts in reversed(self.timestamps):
            if ts >= cutoff:
                count += 1
            else:
                break
        return float(count)

    def freq_mean(self) -> float:
        """Mean tick frequency over the historical window."""
        if not self.freq_history:
            return 0.0
        return sum(self.freq_history) / len(self.freq_history)

    def freq_std(self) -> float:
        """Standard deviation of tick frequency."""
        if len(self.freq_history) < 3:
            return 0.0
        mean = self.freq_mean()
        variance = sum((f - mean) ** 2 for f in self.freq_history) / len(self.freq_history)
        return math.sqrt(max(variance, 0.0))

    def freq_z_score(self) -> float:
        """Z-score of current frequency vs historical.

        Positive = unusually active; negative = unusually quiet.
        This is a regime signal: high z-score often precedes volatility.
        """
        if len(self.freq_history) < 5:
            return 0.0
        # Use recent 60 values for rolling reference (last ~10 min at 10s windows)
        recent = self.freq_history[-60:]
        recent_mean = sum(recent) / len(recent)
        recent_var = sum((f - recent_mean) ** 2 for f in recent) / len(recent)
        recent_std = math.sqrt(max(recent_var, 1e-10))
        current = self.tick_frequency()
        return (current - recent_mean) / recent_std

    def activity_regime(self) -> float:
        """Classify market activity level (0-1).

        0.0 = very quiet (low frequency, below mean)
        0.5 = normal activity
        1.0 = very active (high frequency, above mean)

        This serves as a regime signal for the decision engine.
        """
        z = self.freq_z_score()
        if len(self.freq_history) < 5:
            return 0.5  # neutral when insufficient data
        # Map z-score to 0-1: z=0 -> 0.5, z=+2 -> ~0.95, z=-2 -> ~0.05
        val = 0.5 + z * 0.225
        return max(0.0, min(val, 1.0))

    def frequency_features(self) -> dict[str, float]:
        """Tick frequency feature dictionary."""
        return {
            "tick_freq": self.tick_frequency(),
            "tick_freq_mean": self.freq_mean(),
            "tick_freq_std": self.freq_std(),
            "tick_freq_z_score": self.freq_z_score(),
            "tick_activity_regime": self.activity_regime(),
        }

    def to_features(self) -> dict[str, float]:
        """Convert accumulated state to a feature dictionary.

        Returns neutral defaults if no ticks have been processed yet.
        """
        base_features = {
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
        # Add microstructure features from spread/direction/volume
        base_features.update(self.spread_features())
        base_features.update(self.direction_features())
        base_features.update(self.volume_features())
        # Add rolling tick frequency features
        base_features.update(self.frequency_features())
        return base_features


class TickFlowEngine:
    """Computes tick-level features from a sliding window of raw ticks.

    Now accepts Tick objects to leverage spread, direction, and volume_proxy
    data for microstructure features (spread analysis, direction streaks,
    volume surge detection).

    Usage:
        engine = TickFlowEngine(window_size=200)
        for tick in ticks:
            engine.update(tick)  # pass Tick object, not just tick.price
        features = engine.features()
    """

    def __init__(self, window_size: int = 200):
        self.window_size = window_size
        self._prices: List[float] = []
        self._deltas: List[float] = []
        self._state = TickFlowState()

    def update(self, tick_or_price) -> TickFlowState:
        """Add a new tick and update all flow statistics.

        Accepts either a Tick object (preferred) or a raw price float.
        When a Tick object is provided, spread, tick_direction, and
        volume_proxy data are used for microstructure features.
        """
        # Accept both Tick objects and raw floats for backward compatibility
        if isinstance(tick_or_price, (int, float)):
            price = float(tick_or_price)
            spread = 0.0
            tick_direction = 0
            volume_proxy = 0.0
            epoch = 0.0
        else:
            # Assume Tick-like object with .price, .spread, .tick_direction, .volume_proxy, .epoch
            t = tick_or_price
            price = t.price
            spread = getattr(t, 'spread', 0.0)
            tick_direction = getattr(t, 'tick_direction', 0)
            volume_proxy = getattr(t, 'volume_proxy', 0.0)
            epoch = getattr(t, 'epoch', 0.0)

        self._prices.append(price)
        if len(self._prices) > self.window_size:
            self._prices = self._prices[-self.window_size:]
            self._state.tick_high = max(self._prices)
            self._state.tick_low = min(self._prices)

        state = self._state
        state.current_price = price
        state.total_ticks += 1

        # Store timestamp for frequency analysis (even on first tick)
        if epoch > 0:
            state.timestamps.append(epoch)
            if len(state.timestamps) > 500:
                state.timestamps = state.timestamps[-500:]

        # Initialize range on first tick
        if state.total_ticks == 1:
            state.tick_high = price
            state.tick_low = price
            state.prev_velocity = 0.0
            state.prev_direction = tick_direction
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
            if state.consecutive_up > 1:
                state.impulse_up_sum += abs(delta)
                state.impulse_count += 1
            elif state.consecutive_down == 0 and state.consecutive_up == 1:
                state.impulse_up_sum += abs(delta) * 1.5
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
            decay = 0.98
            state.momentum_sum *= decay
            state.momentum_count = max(int(state.momentum_count * decay), 1)

        # ── Spread features ──────────────────────────────────────
        if spread > 0:
            state.spread_sum += spread
            state.spread_sq_sum += spread * spread
            state.spread_max = max(state.spread_max, spread)
            state.spread_count += 1
            state.recent_spreads.append(spread)
            if len(state.recent_spreads) > 200:
                state.recent_spreads = state.recent_spreads[-200:]

        # ── Direction streak features (from tick_direction) ───────
        if tick_direction != 0 and state.prev_direction != 0:
            # Count direction switches
            if tick_direction != state.prev_direction:
                state.direction_switches += 1
                # Reset the appropriate streak and start the other
                if tick_direction > 0:
                    state.direction_streak_up = 1
                    state.direction_streak_down = 0
                    state.direction_streak_flat = 0
                elif tick_direction < 0:
                    state.direction_streak_down = 1
                    state.direction_streak_up = 0
                    state.direction_streak_flat = 0
            else:
                # Continue the current streak
                if tick_direction > 0:
                    state.direction_streak_up += 1
                    state.max_direction_streak_up = max(
                        state.max_direction_streak_up, state.direction_streak_up)
                elif tick_direction < 0:
                    state.direction_streak_down += 1
                    state.max_direction_streak_down = max(
                        state.max_direction_streak_down, state.direction_streak_down)
        elif tick_direction == 0:
            state.direction_streak_flat += 1
        elif state.prev_direction == 0 and tick_direction != 0:
            # Starting a new streak from flat
            if tick_direction > 0:
                state.direction_streak_up = 1
            elif tick_direction < 0:
                state.direction_streak_down = 1

        state.prev_direction = tick_direction

        # ── Rolling tick frequency (update history every 10 ticks) ─
        if state.total_ticks % 10 == 0 and len(state.timestamps) >= 2:
            freq = state.tick_frequency()
            state.freq_history.append(freq)
            if len(state.freq_history) > 200:
                state.freq_history = state.freq_history[-200:]

        # ── Volume surge features ─────────────────────────────────
        if volume_proxy > 0:
            state.volume_sum += volume_proxy
            state.volume_sq_sum += volume_proxy * volume_proxy
            state.volume_max = max(state.volume_max, volume_proxy)
            state.volume_count += 1
            state.recent_volumes.append(volume_proxy)
            if len(state.recent_volumes) > 200:
                state.recent_volumes = state.recent_volumes[-200:]
            # Detect surge: above 2x mean volume
            if state.volume_count >= 10:
                vol_mean = state.volume_sum / state.volume_count
                if volume_proxy > 2.0 * vol_mean:
                    state.volume_surge_count += 1

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
