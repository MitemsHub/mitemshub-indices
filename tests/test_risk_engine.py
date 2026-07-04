from __future__ import annotations

import unittest

from synthetic_trader.config import RiskConfig, TraderConfig
from synthetic_trader.domain import Direction, TradeOutcome
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine

from tests.test_decision_engine import trending_candles


class RiskEngineTests(unittest.TestCase):
    def test_approves_valid_signal(self) -> None:
        config = TraderConfig.default()
        signal = DecisionEngine(config).evaluate("R_75", trending_candles()).signal
        assert signal is not None

        decision = RiskEngine(config.risk).evaluate(signal)

        self.assertTrue(decision.approved)
        self.assertIsNotNone(decision.intent)

    def test_blocks_after_loss_limit(self) -> None:
        config = TraderConfig.default()
        risk = RiskEngine(RiskConfig(starting_equity=1000, max_consecutive_losses=0))
        signal = DecisionEngine(config).evaluate("R_75", trending_candles()).signal
        assert signal is not None

        decision = risk.evaluate(signal)

        self.assertFalse(decision.approved)
        self.assertIn("consecutive-loss circuit breaker active", decision.reasons)

    def test_reset_daily_limits_rolls_day_start_to_current_equity(self) -> None:
        engine = RiskEngine(RiskConfig(starting_equity=1000.0))
        engine.state.equity = 960.0
        engine.state.consecutive_losses = 3
        engine.state.trades_today = 4

        engine.reset_daily_limits()

        self.assertEqual(engine.state.day_start_equity, 960.0)
        self.assertEqual(engine.state.consecutive_losses, 0)
        self.assertEqual(engine.state.trades_today, 0)

    def test_register_outcome_updates_state_and_resets_loss_streak_after_win(self) -> None:
        engine = RiskEngine(RiskConfig(starting_equity=1000.0))
        engine.register_open()

        engine.register_outcome(
            TradeOutcome(
                position_id="loss-1",
                symbol="R_75",
                direction=Direction.LONG,
                entry=100.0,
                exit=99.0,
                pnl=-25.0,
                return_r=-1.0,
                opened_at=60.0,
                closed_at=120.0,
                features={},
                won=False,
            )
        )

        self.assertEqual(engine.state.open_positions, 0)
        self.assertEqual(engine.state.equity, 975.0)
        self.assertEqual(engine.state.realized_pnl, -25.0)
        self.assertEqual(engine.state.consecutive_losses, 1)

        engine.register_open()
        engine.register_outcome(
            TradeOutcome(
                position_id="win-1",
                symbol="R_75",
                direction=Direction.LONG,
                entry=100.0,
                exit=101.5,
                pnl=30.0,
                return_r=1.2,
                opened_at=180.0,
                closed_at=240.0,
                features={},
                won=True,
            )
        )

        self.assertEqual(engine.state.open_positions, 0)
        self.assertEqual(engine.state.equity, 1005.0)
        self.assertEqual(engine.state.realized_pnl, 5.0)
        self.assertEqual(engine.state.consecutive_losses, 0)
        self.assertEqual(engine.state.trades_today, 2)


if __name__ == "__main__":
    unittest.main()
