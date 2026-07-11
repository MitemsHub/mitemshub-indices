from __future__ import annotations

import unittest

from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle, Direction
from synthetic_trader.strategy.decision_engine import DecisionEngine


def trending_candles(symbol: str = "R_75", count: int = 100) -> list[Candle]:
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = open_price + 0.35
        candles.append(
            Candle(
                symbol=symbol,
                timeframe_sec=60,
                open_time=index * 60,
                open=open_price,
                high=close + 0.12,
                low=open_price - 0.08,
                close=close,
                tick_count=5,
            )
        )
        price = close
    return candles


class DecisionEngineTests(unittest.TestCase):
    def test_waits_for_enough_history(self) -> None:
        engine = DecisionEngine(TraderConfig.default())
        report = engine.evaluate("R_75", trending_candles(count=10))
        self.assertIsNone(report.signal)

    def test_creates_directional_signal(self) -> None:
        engine = DecisionEngine(TraderConfig.default())
        report = engine.evaluate("R_75", trending_candles())

        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertEqual(report.signal.direction, Direction.LONG)
        self.assertGreaterEqual(report.signal.reward_risk, 1.35)


if __name__ == "__main__":
    unittest.main()
