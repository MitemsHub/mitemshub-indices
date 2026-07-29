"""Tests for prop firm enforcement in the backtest system."""

from __future__ import annotations

import math

import pytest

from synthetic_trader.backtest.prop_firm import (
    BLUEBERRY_FUNDED_2STEP,
    BLUEBERRY_SYNTHETIC,
    PropFirmBreachTracker,
    PropFirmProfile,
    get_prop_firm_profile,
)


class TestPropFirmProfile:
    """Test PropFirmProfile dataclass."""

    def test_blueberry_2step_defaults(self) -> None:
        p = BLUEBERRY_FUNDED_2STEP
        assert p.name == "Blueberry Funded 2-Step"
        assert p.max_daily_loss_pct == 0.05
        assert p.max_overall_drawdown_pct == 0.10
        assert p.profit_target_phase1_pct == 0.10
        assert p.profit_target_phase2_pct == 0.05
        assert p.leverage == 30
        assert p.risk_per_trade_pct == 0.015
        assert p.min_trading_days_phase1 == 3
        assert p.min_trading_days_phase2 == 3
        assert p.allow_synthetic_indices is True

    def test_blueberry_synthetic_stricter_daily_loss(self) -> None:
        p = BLUEBERRY_SYNTHETIC
        assert p.max_daily_loss_pct == 0.04
        assert p.max_overall_drawdown_pct == 0.10
        assert p.leverage == 30
        assert p.allow_synthetic_indices is True

    def test_profile_is_frozen(self) -> None:
        p = BLUEBERRY_FUNDED_2STEP
        with pytest.raises(AttributeError):
            p.max_daily_loss_pct = 0.10  # type: ignore[misc]

    def test_custom_profile(self) -> None:
        custom = PropFirmProfile(
            name="Custom Firm",
            max_daily_loss_pct=0.03,
            max_overall_drawdown_pct=0.06,
            profit_target_phase1_pct=0.08,
            profit_target_phase2_pct=0.04,
            leverage=20,
            risk_per_trade_pct=0.01,
            min_trading_days_phase1=5,
            min_trading_days_phase2=5,
            min_daily_profit_pct=0.01,
            max_inactive_days=20,
            allow_hedging=False,
            allow_synthetic_indices=True,
        )
        assert custom.name == "Custom Firm"
        assert custom.max_daily_loss_pct == 0.03
        assert custom.allow_hedging is False


class TestGetPropFirmProfile:
    """Test prop firm profile lookup."""

    def test_lookup_blueberry_2step(self) -> None:
        p = get_prop_firm_profile("blueberry_2step")
        assert p is not None
        assert p.name == "Blueberry Funded 2-Step"

    def test_lookup_blueberry_synthetic(self) -> None:
        p = get_prop_firm_profile("blueberry_synthetic")
        assert p is not None
        assert p.name == "Blueberry Funded Synthetic"

    def test_lookup_case_insensitive(self) -> None:
        p = get_prop_firm_profile("Blueberry_2Step")
        assert p is not None

    def test_lookup_with_hyphens(self) -> None:
        p = get_prop_firm_profile("blueberry-2step")
        assert p is not None

    def test_lookup_unknown_returns_none(self) -> None:
        p = get_prop_firm_profile("unknown_firm")
        assert p is None


class TestPropFirmBreachTracker:
    """Test breach tracker."""

    def test_initial_state(self) -> None:
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        assert tracker.total_breaches == 0
        assert tracker.breached is False
        assert tracker.daily_loss_breaches == 0
        assert tracker.drawdown_breaches == 0
        assert tracker.risk_per_trade_breaches == 0

    def test_record_breach(self) -> None:
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        tracker.record_breach(
            rule="daily_loss",
            epoch=1000.0,
            message="Daily loss 5.1% >= 5%",
            equity=94_900,
        )
        assert tracker.total_breaches == 1
        assert tracker.breached is True
        assert tracker.daily_loss_breaches == 1
        assert len(tracker.breach_details) == 1
        assert tracker.breach_details[0]["rule"] == "daily_loss"
        assert tracker.breach_details[0]["equity"] == 94_900

    def test_record_multiple_breach_types(self) -> None:
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        tracker.record_breach("daily_loss", 1000.0, "Daily loss breached")
        tracker.record_breach("max_drawdown", 2000.0, "Max drawdown breached")
        tracker.record_breach("risk_per_trade", 3000.0, "Stake too large")
        assert tracker.total_breaches == 3
        assert tracker.daily_loss_breaches == 1
        assert tracker.drawdown_breaches == 1
        assert tracker.risk_per_trade_breaches == 1

    def test_summary(self) -> None:
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        tracker.record_breach("daily_loss", 1000.0, "Daily loss breached")
        summary = tracker.summary()
        assert summary["total_breaches"] == 1
        assert summary["daily_loss_breaches"] == 1
        assert len(summary["breach_details"]) == 1


class TestRiskEnginePropFirm:
    """Test RiskEngine with prop firm constraints."""

    def _make_signal(self, confidence: float = 0.6) -> "TradeSignal":
        from unittest.mock import MagicMock
        from synthetic_trader.domain import TradeSignal

        mock_snapshot = MagicMock()
        mock_snapshot.features = {"range_z_50": 0.5}

        return TradeSignal(
            symbol="R_100",
            direction="buy",
            confidence=confidence,
            min_confidence=0.5,
            entry=250.0,
            stop_loss=245.0,
            take_profit=260.0,
            horizon_sec=3600,
            snapshot=mock_snapshot,
            rationale=("test",),
            model_version="test",
        )

    def test_no_prop_firm_allows_normal_trades(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01)
        engine = RiskEngine(config)
        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is True

    def test_prop_firm_daily_loss_blocks_trades(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01)
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        engine = RiskEngine(config, prop_firm=BLUEBERRY_FUNDED_2STEP, breach_tracker=tracker)

        # Simulate a day starting at 100k, equity dropped to 94.5k (5.5% loss > 5% limit)
        engine.state.day_start_equity = 100_000
        engine.state.equity = 94_500

        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is False
        assert any("daily loss limit" in r for r in decision.reasons)
        assert tracker.daily_loss_breaches == 1

    def test_prop_firm_max_drawdown_blocks_trades(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01)
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        engine = RiskEngine(config, prop_firm=BLUEBERRY_FUNDED_2STEP, breach_tracker=tracker)

        # Simulate equity dropped to 89.5k (10.5% loss > 10% limit)
        engine.state.initial_balance = 100_000
        engine.state.day_start_equity = 100_000
        engine.state.equity = 89_500

        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is False
        assert any("max drawdown" in r for r in decision.reasons)
        assert tracker.drawdown_breaches == 1

    def test_prop_firm_risk_per_trade_caps_stake(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.05)  # 5% risk per trade
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        engine = RiskEngine(config, prop_firm=BLUEBERRY_FUNDED_2STEP, breach_tracker=tracker)

        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is True
        assert decision.intent is not None
        # Prop firm caps at 1.5% of 100k = 1500
        assert decision.intent.stake <= 1500.0
        # Risk per trade breach should be recorded
        assert tracker.risk_per_trade_breaches >= 1

    def test_prop_firm_daily_reset(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01)
        tracker = PropFirmBreachTracker(initial_balance=100_000)
        engine = RiskEngine(config, prop_firm=BLUEBERRY_FUNDED_2STEP, breach_tracker=tracker)

        # Simulate daily loss
        engine.state.day_start_equity = 100_000
        engine.state.equity = 94_500
        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is False

        # Reset daily limits
        engine.reset_daily_limits()
        engine.state.day_start_equity = 94_500  # new day starts at current equity
        engine.state.equity = 94_500

        decision2 = engine.evaluate(signal)
        assert decision2.approved is True  # daily drawdown is now 0%

    def test_prop_firm_within_limits_allows_trades(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        # Use a generous daily loss fraction so the base engine doesn't block
        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01, max_daily_loss_fraction=0.10)
        engine = RiskEngine(config, prop_firm=BLUEBERRY_FUNDED_2STEP)

        # Equity at 98k (2% loss < 5% daily limit, 2% drawdown < 10%)
        engine.state.initial_balance = 100_000
        engine.state.day_start_equity = 100_000
        engine.state.equity = 98_000

        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is True

    def test_prop_firm_appears_in_intent_metadata(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01)
        engine = RiskEngine(config, prop_firm=BLUEBERRY_FUNDED_2STEP)

        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is True
        assert decision.intent is not None
        assert decision.intent.metadata["prop_firm_active"] is True

    def test_no_prop_firm_metadata_flag(self) -> None:
        from synthetic_trader.config import RiskConfig
        from synthetic_trader.risk.engine import RiskEngine

        config = RiskConfig(starting_equity=100_000, risk_per_trade=0.01)
        engine = RiskEngine(config)

        signal = self._make_signal()
        decision = engine.evaluate(signal)
        assert decision.approved is True
        assert decision.intent is not None
        assert decision.intent.metadata["prop_firm_active"] is False
