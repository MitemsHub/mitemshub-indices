"""Tests for volatility harvesting strategy — exploits GARCH mean reversion."""
from __future__ import annotations

from synthetic_trader.domain import Direction
from synthetic_trader.strategy.volatility_harvesting import (
    VolatilityHarvestSignal,
    VolatilityHarvester,
)


class TestVolatilityHarvestSignal:
    def test_frozen_dataclass(self):
        sig = VolatilityHarvestSignal(
            direction=Direction.LONG,
            entry=312.7,
            stop_loss=305.7,
            take_profit=337.2,
            confidence=0.72,
            z_score=-3.1,
            mean_revert_signal=0.81,
            hold_minutes=60,
            rationale=("test",),
        )
        assert sig.direction is Direction.LONG
        assert sig.entry == 312.7
        assert sig.confidence == 0.72


class TestVolatilityHarvester:
    def test_no_signal_during_cooldown(self):
        vh = VolatilityHarvester(cooldown_bars=10)
        features = {
            "garch_z_score": -4.0,
            "garch_mean_revert_signal": 0.9,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        # First call should signal
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is not None
        # Second call should be blocked by cooldown
        result2 = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result2 is None

    def test_no_signal_below_z_threshold(self):
        vh = VolatilityHarvester(z_threshold=2.5)
        features = {
            "garch_z_score": -1.0,  # below threshold
            "garch_mean_revert_signal": 0.9,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is None

    def test_no_signal_below_mr_threshold(self):
        vh = VolatilityHarvester(mr_signal_threshold=0.6)
        features = {
            "garch_z_score": -3.0,
            "garch_mean_revert_signal": 0.4,  # below threshold
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is None

    def test_no_signal_low_vol_regime(self):
        vh = VolatilityHarvester()
        features = {
            "garch_z_score": -3.0,
            "garch_mean_revert_signal": 0.9,
            "garch_vol_regime": 0.5,  # low vol
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is None

    def test_no_signal_below_atr_z(self):
        vh = VolatilityHarvester(min_atr_z=1.5)
        features = {
            "garch_z_score": -3.0,
            "garch_mean_revert_signal": 0.9,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 0.5,  # below threshold
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is None

    def test_long_signal_on_negative_z(self):
        vh = VolatilityHarvester()
        features = {
            "garch_z_score": -3.5,  # extreme down move → expect reversion UP
            "garch_mean_revert_signal": 0.85,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is not None
        assert result.direction is Direction.LONG
        assert result.entry == 312.7
        assert result.stop_loss < result.entry
        assert result.take_profit > result.entry

    def test_short_signal_on_positive_z(self):
        vh = VolatilityHarvester()
        features = {
            "garch_z_score": 3.5,  # extreme up move → expect reversion DOWN
            "garch_mean_revert_signal": 0.85,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is not None
        assert result.direction is Direction.SHORT
        assert result.stop_loss > result.entry
        assert result.take_profit < result.entry

    def test_confidence_increases_with_extreme_z(self):
        vh = VolatilityHarvester(z_threshold=2.5)
        features_base = {
            "garch_mean_revert_signal": 0.8,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        # Z = 3.0
        features_3 = {**features_base, "garch_z_score": -3.0}
        result_3 = vh.evaluate(features_3, current_price=312.7, atr_14=5.0)
        # Z = 4.0 — reset both bar count and last signal bar to bypass cooldown
        vh._bar_count = 0
        vh._last_signal_bar = 0
        features_4 = {**features_base, "garch_z_score": -4.0}
        result_4 = vh.evaluate(features_4, current_price=312.7, atr_14=5.0)
        assert result_3 is not None
        assert result_4 is not None
        assert result_4.confidence >= result_3.confidence

    def test_hurst_boost(self):
        vh = VolatilityHarvester()
        features_mr = {
            "garch_z_score": -3.0,
            "garch_mean_revert_signal": 0.8,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,  # mean-reverting
        }
        result_mr = vh.evaluate(features_mr, current_price=312.7, atr_14=5.0)
        # Reset both bar count and last signal bar to bypass cooldown
        vh._bar_count = 0
        vh._last_signal_bar = 0
        features_trend = {
            "garch_z_score": -3.0,
            "garch_mean_revert_signal": 0.8,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.65,  # trending
        }
        result_trend = vh.evaluate(features_trend, current_price=312.7, atr_14=5.0)
        assert result_mr is not None
        assert result_trend is not None
        assert result_mr.confidence >= result_trend.confidence

    def test_invalid_inputs_returns_none(self):
        vh = VolatilityHarvester()
        features = {
            "garch_z_score": -3.0,
            "garch_mean_revert_signal": 0.9,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.0,  # invalid
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is None

    def test_to_trade_signal_conversion(self):
        vh = VolatilityHarvester()
        sig = VolatilityHarvestSignal(
            direction=Direction.LONG,
            entry=312.7,
            stop_loss=305.7,
            take_profit=337.2,
            confidence=0.72,
            z_score=-3.1,
            mean_revert_signal=0.81,
            hold_minutes=60,
            rationale=("test",),
        )
        trade = vh.to_trade_signal(
            signal=sig,
            symbol="R_100",
            min_confidence=0.5,
            position_scale=1.0,
            snapshot=None,
            model_version="v1",
        )
        assert trade.symbol == "R_100"
        assert trade.direction is Direction.LONG
        assert trade.entry == 312.7
        assert trade.stop_loss == 305.7
        assert trade.take_profit == 337.2
        assert trade.execution_trigger_type == "volatility_harvest"
        assert trade.signal_strength == "strong_buy"

    def test_rationale_contains_key_info(self):
        vh = VolatilityHarvester()
        features = {
            "garch_z_score": -3.5,
            "garch_mean_revert_signal": 0.85,
            "garch_vol_regime": 2.0,
            "garch_sigma": 0.05,
            "atr_z_20": 2.0,
            "hurst_exponent": 0.35,
        }
        result = vh.evaluate(features, current_price=312.7, atr_14=5.0)
        assert result is not None
        rationale_text = " ".join(result.rationale)
        assert "volatility harvesting" in rationale_text
        assert "z=" in rationale_text
        assert "mr_signal=" in rationale_text
