"""Session-based volatility filtering for synthetic indices.

Different hours of the day produce different volatility levels on synthetic
indices.  The generator's server load balancing creates time-dependent
behavior — certain hours consistently produce more volatile moves than others.

This module tracks historical volatility by hour-of-day and generates a
"session quality score" that the decision engine uses to filter trades.

Key insight: On synthetic indices, the random generator runs on servers
that have predictable load patterns.  During high-load periods, the
generator's tick production rate changes, which affects the distribution
of price movements.  This creates exploitable time-of-day effects.

Output features:
    - session_quality: 0.0 (worst) to 1.0 (best) — how favorable the current hour is
    - session_vol_rank: percentile rank of current hour's volatility (0-1)
    - session_is_peak: whether current hour is in the top 25% of volatile hours
    - session_hour: current hour (0-23)
    - session_trend: is volatility increasing or decreasing vs 1 hour ago
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HourStats:
    """Statistics for a single hour of the day."""
    total_returns: int = 0
    sum_abs_returns: float = 0.0
    sum_squared_returns: float = 0.0
    max_abs_return: float = 0.0
    
    @property
    def mean_abs_return(self) -> float:
        return self.sum_abs_returns / max(self.total_returns, 1)
    
    @property
    def variance(self) -> float:
        if self.total_returns < 2:
            return 0.0
        mean = self.sum_abs_returns / self.total_returns
        return self.sum_squared_returns / self.total_returns - mean ** 2
    
    @property
    def realized_vol(self) -> float:
        if self.total_returns < 2:
            return 0.0
        return math.sqrt(max(self.variance, 1e-10))


@dataclass
class SessionFilterState:
    """Persistent state for the session filter."""
    hourly_stats: dict[int, HourStats] = field(default_factory=dict)
    recent_hours: list[int] = field(default_factory=list)
    total_observations: int = 0
    
    def to_dict(self) -> dict:
        return {
            "hourly_stats": {
                str(h): {
                    "total_returns": s.total_returns,
                    "sum_abs_returns": s.sum_abs_returns,
                    "sum_squared_returns": s.sum_squared_returns,
                    "max_abs_return": s.max_abs_return,
                }
                for h, s in self.hourly_stats.items()
            },
            "recent_hours": self.recent_hours[-100:],
            "total_observations": self.total_observations,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> SessionFilterState:
        state = cls()
        state.total_observations = data.get("total_observations", 0)
        state.recent_hours = data.get("recent_hours", [])
        for h_str, s_data in data.get("hourly_stats", {}).items():
            h = int(h_str)
            state.hourly_stats[h] = HourStats(
                total_returns=s_data.get("total_returns", 0),
                sum_abs_returns=s_data.get("sum_abs_returns", 0.0),
                sum_squared_returns=s_data.get("sum_squared_returns", 0.0),
                max_abs_return=s_data.get("max_abs_return", 0.0),
            )
        return state


class SessionVolatilityFilter:
    """Tracks volatility by hour-of-day and scores session quality.
    
    Parameters
    ----------
    lookback_days : int
        Number of days of history to maintain (default 30).
    min_observations_per_hour : int
        Minimum observations before a hour's stats are considered reliable (default 10).
    peak_threshold : float
        Percentile threshold for "peak" hours (default 0.75 = top 25%).
    decay_factor : float
        Exponential decay for old observations (default 0.99).
    """
    
    def __init__(
        self,
        lookback_days: int = 30,
        min_observations_per_hour: int = 10,
        peak_threshold: float = 0.75,
        decay_factor: float = 0.99,
    ) -> None:
        self.lookback_days = lookback_days
        self.min_observations_per_hour = min_observations_per_hour
        self.peak_threshold = peak_threshold
        self.decay_factor = decay_factor
        
        self.state = SessionFilterState()
    
    def update(self, hour: int, log_return: float) -> dict[str, float]:
        """Record a new observation and return session features.
        
        Parameters
        ----------
        hour : int
            Hour of day (0-23) in UTC.
        log_return : float
            The log-return of the latest price movement.
            
        Returns
        -------
        dict[str, float]
            Session features to inject into the decision engine.
        """
        self.state.total_observations += 1
        
        # Update hourly stats
        if hour not in self.state.hourly_stats:
            self.state.hourly_stats[hour] = HourStats()
        
        stats = self.state.hourly_stats[hour]
        stats.total_returns += 1
        stats.sum_abs_returns += abs(log_return)
        stats.sum_squared_returns += log_return ** 2
        stats.max_abs_return = max(stats.max_abs_return, abs(log_return))
        
        # Track recent hours for trend detection
        self.state.recent_hours.append(hour)
        if len(self.state.recent_hours) > 100:
            self.state.recent_hours.pop(0)
        
        return self._build_features(hour)
    
    def _build_features(self, current_hour: int) -> dict[str, float]:
        """Build session feature dictionary."""
        # Calculate realized vol for each hour
        hourly_vols = {}
        for h, stats in self.state.hourly_stats.items():
            if stats.total_returns >= self.min_observations_per_hour:
                hourly_vols[h] = stats.realized_vol
        
        if not hourly_vols:
            return self._default_features(current_hour)
        
        # Rank current hour's volatility
        sorted_vols = sorted(hourly_vols.values())
        current_vol = hourly_vols.get(current_hour, 0.0)
        
        # Percentile rank
        rank = 0.0
        if sorted_vols:
            below = sum(1 for v in sorted_vols if v < current_vol)
            rank = below / len(sorted_vols)
        
        # Session quality: higher vol = more opportunity for harvesting
        # But also more risk.  Balance: peak vol = 0.7, low vol = 0.3
        if rank >= self.peak_threshold:
            quality = 0.7  # peak volatility — good for harvesting
        elif rank >= 0.5:
            quality = 0.6  # above average
        elif rank >= 0.25:
            quality = 0.5  # average
        else:
            quality = 0.3  # low vol — less opportunity
        
        # Is current hour a peak hour?
        is_peak = 1.0 if rank >= self.peak_threshold else 0.0
        
        # Trend: compare current hour's vol to 1-hour-ago
        prev_hour = (current_hour - 1) % 24
        prev_vol = hourly_vols.get(prev_hour, current_vol)
        trend = 0.0
        if prev_vol > 0:
            vol_change = (current_vol - prev_vol) / prev_vol
            trend = max(-1.0, min(1.0, vol_change))
        
        # Consistency: how stable is this hour's volatility?
        hour_stats = self.state.hourly_stats.get(current_hour)
        consistency = 0.5
        if hour_stats and hour_stats.total_returns >= self.min_observations_per_hour * 2:
            # Low coefficient of variation = consistent
            cv = hour_stats.realized_vol / max(hour_stats.mean_abs_return, 1e-10)
            consistency = max(0.0, min(1.0, 1.0 - cv * 0.5))
        
        return {
            "session_quality": quality,
            "session_vol_rank": rank,
            "session_is_peak": is_peak,
            "session_hour": float(current_hour),
            "session_trend": trend,
            "session_consistency": consistency,
            "session_total_hours": float(len(hourly_vols)),
            "session_total_observations": float(self.state.total_observations),
        }
    
    def _default_features(self, current_hour: int) -> dict[str, float]:
        """Return neutral features during warmup."""
        return {
            "session_quality": 0.5,
            "session_vol_rank": 0.5,
            "session_is_peak": 0.0,
            "session_hour": float(current_hour),
            "session_trend": 0.0,
            "session_consistency": 0.5,
            "session_total_hours": 0.0,
            "session_total_observations": float(self.state.total_observations),
        }
    
    def get_peak_hours(self) -> list[int]:
        """Get the list of peak volatility hours."""
        hourly_vols = {}
        for h, stats in self.state.hourly_stats.items():
            if stats.total_returns >= self.min_observations_per_hour:
                hourly_vols[h] = stats.realized_vol
        
        if not hourly_vols:
            return []
        
        sorted_items = sorted(hourly_vols.items(), key=lambda x: x[1], reverse=True)
        n_peak = max(1, int(len(sorted_items) * (1.0 - self.peak_threshold)))
        return [h for h, _ in sorted_items[:n_peak]]
    
    def get_hour_summary(self) -> dict[int, dict]:
        """Get a summary of all hourly statistics."""
        result = {}
        for h, stats in self.state.hourly_stats.items():
            result[h] = {
                "observations": stats.total_returns,
                "mean_abs_return": stats.mean_abs_return,
                "realized_vol": stats.realized_vol,
                "max_abs_return": stats.max_abs_return,
            }
        return result

    def should_trade(
        self,
        hour: int,
        min_quality: float = 0.5,
        min_observations: int = 50,
    ) -> tuple[bool, str]:
        """Determine whether the current hour is suitable for trading.

        This is the gating function that blocks signal generation during
        low-volatility windows.  On synthetic indices, the generator's
        server load patterns create exploitable time-of-day effects —
        certain hours consistently produce more volatile moves.

        Parameters
        ----------
        hour : int
            Current UTC hour (0-23).
        min_quality : float
            Minimum session quality score to allow trading (default 0.5).
        min_observations : int
            Minimum total observations before the filter is considered
            reliable enough to gate trades (default 50).

        Returns
        -------
        tuple[bool, str]
            (should_trade, reason) — True if the hour is suitable,
            False with an explanation if blocked.
        """
        # During warmup, don't block — we need data to learn.
        if self.state.total_observations < min_observations:
            return True, f"warmup ({self.state.total_observations}/{min_observations} observations)"

        # Build features for the current hour
        features = self._build_features(hour)
        quality = features["session_quality"]
        vol_rank = features["session_vol_rank"]
        is_peak = features["session_is_peak"] == 1.0

        if quality >= min_quality:
            return True, f"session quality {quality:.2f} >= {min_quality:.2f} (rank={vol_rank:.2f}, peak={is_peak})"
        else:
            return False, f"session quality {quality:.2f} < {min_quality:.2f} — low-volatility hour (rank={vol_rank:.2f}, peak={is_peak})"
    
    # ── Persistence ────────────────────────────────────────────────
    
    def save(self, path: str | Path) -> None:
        """Persist state to JSON."""
        data = {
            "lookback_days": self.lookback_days,
            "min_observations_per_hour": self.min_observations_per_hour,
            "peak_threshold": self.peak_threshold,
            "decay_factor": self.decay_factor,
            "state": self.state.to_dict(),
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    @classmethod
    def load(cls, path: str | Path) -> SessionVolatilityFilter:
        """Restore state from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        filt = cls(
            lookback_days=data.get("lookback_days", 30),
            min_observations_per_hour=data.get("min_observations_per_hour", 10),
            peak_threshold=data.get("peak_threshold", 0.75),
            decay_factor=data.get("decay_factor", 0.99),
        )
        filt.state = SessionFilterState.from_dict(data.get("state", {}))
        return filt
