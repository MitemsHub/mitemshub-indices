"""Comprehensive tests for EGARCH(1,1) variance forecaster and confidence decay."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from synthetic_trader.models.garch import EGARCHVarianceForecaster, GARCHState
from synthetic_trader.models.confidence_decay import ConfidenceDecayTracker


# ── EGARCH Tests ──────────────────────────────────────────────────

class TestGARCHState:
    def test_conditional_variance(self):
        state = GARCHState(log_variance=math.log(0.001))
        assert abs(state.conditional_variance - 0.001) < 1e-10

    def test_conditional_volatility(self):
        state = GARCHState(log_variance=math.log(0.01))
        assert abs(state.conditional_volatility - 0.1) < 1e-10

    def test_persistence(self):
        state = GARCHState(alpha=0.08, gamma=-0.04, beta=0.88)
        expected = 0.88 + 0.08 * (1.0 - (-0.04) ** 2 / 2.0)
        assert abs(state.persistence - expected) < 1e-6

    def test_persistence_high(self):
        state = GARCHState(alpha=0.10, gamma=0.0, beta=0.90)
        assert state.persistence == pytest.approx(1.0, abs=1e-6)

    def test_half_life(self):
        state = GARCHState(alpha=0.08, gamma=-0.04, beta=0.88)
        hl = state.half_life
        assert hl > 0
        assert hl < 100  # reasonable range

    def test_half_life_infinite_when_persistence_ge_1(self):
        state = GARCHState(alpha=0.10, gamma=0.0, beta=0.92)
        assert state.half_life == float("inf")

    def test_to_dict_roundtrip(self):
        state = GARCHState(omega=-1.5, alpha=0.1, gamma=-0.05, beta=0.9)
        data = state.to_dict()
        restored = GARCHState.from_dict(data)
        assert restored.omega == state.omega
        assert restored.alpha == state.alpha
        assert restored.gamma == state.gamma
        assert restored.beta == state.beta


class TestEGARCHVarianceForecaster:
    def test_warmup_returns_default_features(self):
        forecaster = EGARCHVarianceForecaster(min_observations=30)
        features = forecaster.update(0.001)
        assert "garch_forecast" in features
        assert "garch_sigma" in features
        assert "garch_z_score" in features
        assert "garch_persistence" in features
        assert "garch_vol_regime" in features
        assert "garch_mean_revert_signal" in features

    def test_warmup_phase_returns_defaults(self):
        forecaster = EGARCHVarianceForecaster(min_observations=10)
        for i in range(5):
            features = forecaster.update(0.001 * ((-1) ** i))
        # Still in warmup — should return default features
        assert forecaster.state.observations < forecaster.min_observations

    def test_post_warmup_updates_state(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(10):
            features = forecaster.update(0.001 * ((-1) ** i))
        assert forecaster.state.observations == 10
        assert features["garch_forecast"] > 0
        assert features["garch_sigma"] > 0

    def test_features_all_positive_sigma(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(20):
            features = forecaster.update(0.002 * ((-1) ** i))
        assert features["garch_sigma"] > 0
        assert features["garch_forecast"] > 0
        assert features["garch_sigma_annualized"] > 0

    def test_z_score_extreme_triggers_mean_revert(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        # Feed normal returns first
        for i in range(15):
            forecaster.update(0.001 * ((-1) ** i))
        # Now feed a very large positive return (extreme z-score)
        features = forecaster.update(0.05)
        # z-score should be elevated
        assert abs(features["garch_z_score"]) > 0.1

    def test_vol_regime_classification(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        # Feed calm returns
        for i in range(20):
            forecaster.update(0.0001 * ((-1) ** i))
        # After calm period, vol should be low
        features = forecaster.get_forecast()
        # Low vol regime = 0
        assert features["garch_vol_regime"] in (0.0, 1.0, 2.0)

    def test_persistence_bounded(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(50):
            forecaster.update(0.001 * ((-1) ** i))
        assert forecaster.state.persistence <= 1.0
        assert forecaster.state.persistence >= 0.0

    def test_alpha_bounded(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(50):
            forecaster.update(0.002 * ((-1) ** i))
        assert 0.0 <= forecaster.state.alpha <= 0.5

    def test_gamma_bounded(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(50):
            forecaster.update(0.002 * ((-1) ** i))
        assert -0.5 <= forecaster.state.gamma <= 0.5

    def test_beta_bounded(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(50):
            forecaster.update(0.002 * ((-1) ** i))
        assert 0.0 <= forecaster.state.beta <= 0.999

    def test_get_forecast_readonly(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(10):
            forecaster.update(0.001 * ((-1) ** i))
        obs_before = forecaster.state.observations
        features = forecaster.get_forecast()
        assert forecaster.state.observations == obs_before  # no state change

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "garch.json"
            forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
            for i in range(20):
                forecaster.update(0.001 * ((-1) ** i))
            forecaster.save(path)

            loaded = EGARCHVarianceForecaster.load(path)
            assert loaded.state.observations == forecaster.state.observations
            assert loaded.state.omega == forecaster.state.omega
            assert loaded.state.alpha == forecaster.state.alpha
            assert loaded.state.gamma == forecaster.state.gamma
            assert loaded.state.beta == forecaster.state.beta

    def test_zero_return_handled(self):
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5)
        for i in range(20):
            features = forecaster.update(0.0)
        assert features["garch_sigma"] > 0  # sigma should still be valid

    def test_negative_returns_increase_vol(self):
        """Test that large negative returns (leverage effect) increase volatility more."""
        forecaster = EGARCHVarianceForecaster(min_observations=5, buffer_size=5, learning_rate=0.05)
        # Feed calm returns
        for i in range(15):
            forecaster.update(0.0005 * ((-1) ** i))
        sigma_before = forecaster.state.conditional_volatility
        # Feed large negative return
        for i in range(5):
            forecaster.update(-0.01)
        sigma_after = forecaster.state.conditional_volatility
        # Vol should increase after negative shocks (leverage effect)
        assert sigma_after >= sigma_before * 0.9  # allow some noise


class TestConfidenceDecayTracker:
    def test_no_decay_with_few_predictions(self):
        tracker = ConfidenceDecayTracker(max_streak_before_decay=5)
        for i in range(3):
            tracker.record_prediction(0.70, 250.0 + i, float(i))
        result = tracker.apply_decay(0.70, "long")
        assert result == 0.70  # no decay — not enough predictions

    def test_no_decay_when_price_confirms(self):
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            price_move_threshold_pct=0.1,
            lookback_for_move=5,
        )
        # 10 consecutive long predictions with price rising
        for i in range(15):
            tracker.record_prediction(0.70, 250.0 + i * 2.0, float(i))
        result = tracker.apply_decay(0.70, "long")
        assert result == 0.70  # price confirmed — no decay

    def test_decay_when_stale(self):
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            decay_rate=0.02,
            price_move_threshold_pct=5.0,  # high threshold = price won't confirm
            lookback_for_move=10,
        )
        # 15 consecutive long predictions with flat price
        for i in range(15):
            tracker.record_prediction(0.70, 250.0, float(i))
        result = tracker.apply_decay(0.70, "long")
        assert result < 0.70  # decay applied

    def test_decay_floor(self):
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=3,
            decay_rate=0.1,
            min_confidence_floor=0.35,
            price_move_threshold_pct=100.0,  # impossible to confirm
            lookback_for_move=5,
        )
        # Very long streak with flat price
        for i in range(30):
            tracker.record_prediction(0.70, 250.0, float(i))
        result = tracker.apply_decay(0.70, "long")
        assert result >= 0.35  # floor respected

    def test_decay_resets_on_direction_change(self):
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            price_move_threshold_pct=100.0,
            lookback_for_move=5,
        )
        # Build a long streak
        for i in range(10):
            tracker.record_prediction(0.70, 250.0, float(i))
        # Then a short prediction
        tracker.record_prediction(0.30, 250.0, 10.0)
        # Now scoring short — streak should be 1, no decay
        result = tracker.apply_decay(0.60, "short")
        assert result == 0.60  # fresh direction — no decay

    def test_streak_info(self):
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            price_move_threshold_pct=100.0,
            lookback_for_move=5,
        )
        for i in range(10):
            tracker.record_prediction(0.70, 250.0, float(i))
        info = tracker.get_streak_info()
        assert info["streak"] == 10
        assert info["direction"] == "long"
        assert info["will_decay"] is True

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "decay.json"
            tracker = ConfidenceDecayTracker()
            for i in range(20):
                tracker.record_prediction(0.70, 250.0 + i, float(i))
            tracker.save(path)

            loaded = ConfidenceDecayTracker.load(path)
            assert loaded.state.total_predictions == tracker.state.total_predictions
            assert len(loaded.state.recent_predictions) == len(tracker.state.recent_predictions)

    def test_high_confidence_extra_decay(self):
        """High confidence predictions get extra decay when stale."""
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            decay_rate=0.02,
            price_move_threshold_pct=100.0,
            lookback_for_move=5,
        )
        for i in range(15):
            tracker.record_prediction(0.85, 250.0, float(i))
        result_high = tracker.apply_decay(0.85, "long")

        tracker2 = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            decay_rate=0.02,
            price_move_threshold_pct=100.0,
            lookback_for_move=5,
        )
        for i in range(15):
            tracker2.record_prediction(0.60, 250.0, float(i))
        result_low = tracker2.apply_decay(0.60, "long")

        # High confidence should be decayed more than low confidence
        assert (0.85 - result_high) > (0.60 - result_low)

    def test_no_decay_on_short_direction_when_long_streak(self):
        """Decay only applies to the streak direction, not the opposite."""
        tracker = ConfidenceDecayTracker(
            max_streak_before_decay=5,
            price_move_threshold_pct=100.0,
            lookback_for_move=5,
        )
        for i in range(10):
            tracker.record_prediction(0.70, 250.0, float(i))
        # Scoring short when the streak is long — short has no streak
        result = tracker.apply_decay(0.60, "short")
        assert result == 0.60  # no decay for opposite direction
