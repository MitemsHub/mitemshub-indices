"""Tests for session volatility filter — tracks hourly vol patterns."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from synthetic_trader.features.session_filter import (
    HourStats,
    SessionFilterState,
    SessionVolatilityFilter,
)


class TestHourStats:
    def test_initial_state(self):
        s = HourStats()
        assert s.total_returns == 0
        assert s.mean_abs_return == 0.0
        assert s.variance == 0.0
        assert s.realized_vol == 0.0

    def test_mean_abs_return(self):
        s = HourStats(total_returns=4, sum_abs_returns=0.04)
        assert abs(s.mean_abs_return - 0.01) < 1e-9

    def test_variance_single_obs(self):
        s = HourStats(total_returns=1, sum_abs_returns=0.01, sum_squared_returns=0.0001)
        assert s.variance == 0.0

    def test_variance_multiple_obs(self):
        s = HourStats(total_returns=3, sum_abs_returns=0.03, sum_squared_returns=0.0003)
        v = s.variance
        # mean = 0.01, var = 0.0001 - 0.0001 = 0
        assert abs(v - 0.0) < 1e-9

    def test_realized_vol(self):
        s = HourStats(total_returns=10, sum_abs_returns=0.1, sum_squared_returns=0.001)
        rv = s.realized_vol
        assert rv >= 0.0


class TestSessionFilterState:
    def test_to_dict_roundtrip(self):
        state = SessionFilterState()
        state.total_observations = 42
        state.recent_hours = [10, 11, 12]
        state.hourly_stats[10] = HourStats(total_returns=5, sum_abs_returns=0.05)
        d = state.to_dict()
        restored = SessionFilterState.from_dict(d)
        assert restored.total_observations == 42
        assert restored.recent_hours == [10, 11, 12]
        assert 10 in restored.hourly_stats
        assert restored.hourly_stats[10].total_returns == 5


class TestSessionVolatilityFilter:
    def test_warmup_returns_defaults(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=10)
        features = sf.update(hour=12, log_return=0.001)
        assert features["session_quality"] == 0.5
        assert features["session_hour"] == 12.0
        assert features["session_total_observations"] == 1.0

    def test_update_accumulates_observations(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=5)
        for i in range(10):
            sf.update(hour=8, log_return=0.001 * (i + 1))
        assert sf.state.total_observations == 10
        assert sf.state.hourly_stats[8].total_returns == 10

    def test_multiple_hours(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        for h in range(24):
            for i in range(5):
                sf.update(hour=h, log_return=0.001 * (h + 1) * (i + 1))
        features = sf.update(hour=12, log_return=0.001)
        assert features["session_total_observations"] == 121.0
        assert features["session_total_hours"] >= 1.0

    def test_peak_hours(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3, peak_threshold=0.75)
        for h in range(24):
            for i in range(5):
                # Higher hours have higher vol
                sf.update(hour=h, log_return=0.001 * (h + 1) * (i + 1))
        peak = sf.get_peak_hours()
        assert len(peak) >= 1
        assert all(0 <= h < 24 for h in peak)

    def test_hour_summary(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=2)
        sf.update(hour=10, log_return=0.01)
        sf.update(hour=10, log_return=0.02)
        summary = sf.get_hour_summary()
        assert 10 in summary
        assert summary[10]["observations"] == 2

    def test_save_load_roundtrip(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        for i in range(10):
            sf.update(hour=i % 24, log_return=0.001 * (i + 1))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        sf.save(path)
        loaded = SessionVolatilityFilter.load(path)
        assert loaded.state.total_observations == 10
        assert loaded.min_observations_per_hour == 3
        Path(path).unlink()

    def test_default_features_fresh(self):
        sf = SessionVolatilityFilter()
        features = sf._default_features(15)
        assert features["session_quality"] == 0.5
        assert features["session_hour"] == 15.0
        assert features["session_is_peak"] == 0.0

    def test_vol_rank_calculation(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        # Low vol hour
        for i in range(5):
            sf.update(hour=2, log_return=0.0001 * (i + 1))
        # High vol hour
        for i in range(5):
            sf.update(hour=14, log_return=0.01 * (i + 1))
        features = sf.update(hour=14, log_return=0.01)
        # High vol hour should have high rank (>= 0.5, since it's the max)
        assert features["session_vol_rank"] >= 0.5


class TestSessionFilterGating:
    def test_warmup_always_allows_trading(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        ok, reason = sf.should_trade(hour=12, min_quality=0.5, min_observations=50)
        assert ok is True
        assert "warmup" in reason

    def test_blocks_low_vol_hour(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        # Create hours with clear low-vol vs high-vol distinction
        for i in range(10):
            sf.update(hour=3, log_return=0.0001 * (i + 1))  # very low vol
            sf.update(hour=15, log_return=0.01 * (i + 1))  # very high vol
        ok, reason = sf.should_trade(hour=3, min_quality=0.5, min_observations=5)
        # Hour 3 has lowest vol — should be blocked
        assert ok is False
        assert "low-volatility" in reason

    def test_allows_high_vol_hour(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        for i in range(10):
            sf.update(hour=3, log_return=0.0001 * (i + 1))  # very low vol
            sf.update(hour=15, log_return=0.01 * (i + 1))  # very high vol
        ok, reason = sf.should_trade(hour=15, min_quality=0.5, min_observations=5)
        # Hour 15 has highest vol — should be allowed
        assert ok is True
        assert "session quality" in reason

    def test_min_quality_threshold(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        for i in range(10):
            sf.update(hour=3, log_return=0.0001 * (i + 1))
            sf.update(hour=15, log_return=0.01 * (i + 1))
        # With a very high threshold, even the best hour might fail
        ok_high, _ = sf.should_trade(hour=15, min_quality=0.99, min_observations=5)
        # With a low threshold, even mediocre hours pass
        ok_low, _ = sf.should_trade(hour=8, min_quality=0.3, min_observations=5)
        assert ok_high is False  # 0.99 is too strict
        assert ok_low is True   # 0.3 is very lenient

    def test_min_observations_gate(self):
        sf = SessionVolatilityFilter(min_observations_per_hour=3)
        for i in range(5):
            sf.update(hour=15, log_return=0.01 * (i + 1))
        # With high min_observations, still in warmup
        ok, reason = sf.should_trade(hour=15, min_quality=0.5, min_observations=100)
        assert ok is True
        assert "warmup" in reason
        # With low min_observations, warmup complete
        ok2, reason2 = sf.should_trade(hour=15, min_quality=0.5, min_observations=3)
        assert "warmup" not in reason2
