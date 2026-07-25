from __future__ import annotations

import unittest

from synthetic_trader.config import PaperExecutionConfig
from synthetic_trader.domain import Candle, Direction, FeatureSnapshot, OrderIntent, Regime, TradeSignal
from synthetic_trader.execution.paper import PaperBroker


def make_signal(
    direction: Direction,
    *,
    symbol: str = "R_75",
    epoch: float = 120.0,
    entry: float = 100.0,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    horizon_sec: int = 120,
) -> TradeSignal:
    snapshot = FeatureSnapshot(
        symbol=symbol,
        epoch=epoch,
        timeframe_sec=60,
        features={"atr_14": 1.0},
        regime=Regime.RANGE,
        structure={"bias": 0.0},
    )
    if direction is Direction.LONG:
        stop = 99.0 if stop_loss is None else stop_loss
        target = 102.0 if take_profit is None else take_profit
    else:
        stop = 101.0 if stop_loss is None else stop_loss
        target = 98.0 if take_profit is None else take_profit
    return TradeSignal(
        symbol=symbol,
        direction=direction,
        confidence=0.7,
        min_confidence=0.58,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        horizon_sec=horizon_sec,
        snapshot=snapshot,
        rationale=("unit-test",),
        model_version="unit-test",
    )


def make_intent(signal: TradeSignal, *, stake: float = 10.0) -> OrderIntent:
    return OrderIntent(signal=signal, stake=stake, max_loss=stake, metadata={})


class PaperBrokerTests(unittest.TestCase):
    def test_stop_wins_when_stop_and_target_hit_same_candle(self) -> None:
        broker = PaperBroker()
        broker.submit(make_intent(make_signal(Direction.LONG)))

        outcomes = broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=120,
                open=100.0,
                high=103.0,
                low=98.5,
                close=100.5,
            )
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit, 99.0)
        self.assertLess(outcomes[0].pnl, 0.0)

    def test_expiry_closes_at_candle_close_on_horizon_boundary(self) -> None:
        broker = PaperBroker()
        broker.submit(make_intent(make_signal(Direction.LONG, horizon_sec=120)))

        no_outcomes_yet = broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=120,
                open=100.0,
                high=100.8,
                low=99.4,
                close=100.3,
            )
        )
        expired_outcomes = broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=180,
                open=100.3,
                high=100.9,
                low=99.5,
                close=100.6,
            )
        )

        self.assertEqual(no_outcomes_yet, [])
        self.assertEqual(len(expired_outcomes), 1)
        self.assertEqual(expired_outcomes[0].exit, 100.6)
        self.assertEqual(expired_outcomes[0].closed_at, 240)

    def test_close_all_force_closes_matching_symbol_at_candle_close(self) -> None:
        broker = PaperBroker()
        broker.submit(make_intent(make_signal(Direction.LONG, symbol="R_75")))
        other_position = broker.submit(make_intent(make_signal(Direction.SHORT, symbol="R_100")))

        outcomes = broker.close_all(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=240,
                open=100.4,
                high=100.8,
                low=99.7,
                close=100.2,
            )
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].symbol, "R_75")
        self.assertEqual(outcomes[0].exit, 100.2)
        self.assertNotIn(outcomes[0].position_id, broker.positions)
        self.assertIn(other_position.id, broker.positions)

    def test_exit_slippage_reduces_long_take_profit_exit_price(self) -> None:
        broker = PaperBroker(PaperExecutionConfig(exit_slippage_ticks=0.5))
        broker.submit(make_intent(make_signal(Direction.LONG)))

        outcomes = broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=120,
                open=100.0,
                high=103.0,
                low=99.5,
                close=102.5,
            )
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit, 101.5)
        self.assertEqual(outcomes[0].return_r, 1.5)
        self.assertEqual(outcomes[0].pnl, 15.0)

    def test_exit_slippage_applies_to_expiry_close(self) -> None:
        broker = PaperBroker(PaperExecutionConfig(exit_slippage_ticks=0.25))
        broker.submit(make_intent(make_signal(Direction.LONG, horizon_sec=120)))

        broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=120,
                open=100.0,
                high=100.6,
                low=99.4,
                close=100.3,
            )
        )
        outcomes = broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=180,
                open=100.3,
                high=100.9,
                low=99.6,
                close=100.8,
            )
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit, 100.55)
        self.assertEqual(outcomes[0].closed_at, 240)

    def test_execution_penalty_reduces_realized_pnl_without_changing_r_multiple(self) -> None:
        broker = PaperBroker(PaperExecutionConfig(execution_penalty_per_trade=0.2))
        broker.submit(make_intent(make_signal(Direction.LONG)))

        outcomes = broker.on_candle(
            Candle(
                symbol="R_75",
                timeframe_sec=60,
                open_time=120,
                open=100.0,
                high=103.0,
                low=99.5,
                close=102.5,
            )
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].exit, 102.0)
        self.assertEqual(outcomes[0].return_r, 2.0)
        self.assertEqual(outcomes[0].pnl, 19.8)
        self.assertTrue(outcomes[0].won)


if __name__ == "__main__":
    unittest.main()
