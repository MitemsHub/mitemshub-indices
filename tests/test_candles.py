from __future__ import annotations

import unittest

from synthetic_trader.data.candles import CandleBuilder
from synthetic_trader.domain import Tick


class CandleBuilderTests(unittest.TestCase):
    def test_closes_candle_on_new_bucket(self) -> None:
        builder = CandleBuilder("R_75", 60)
        self.assertIsNone(builder.update(Tick("R_75", 1, 100.0)))
        self.assertIsNone(builder.update(Tick("R_75", 30, 101.0)))
        closed = builder.update(Tick("R_75", 61, 102.0))

        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertEqual(closed.open_time, 0)
        self.assertEqual(closed.open, 100.0)
        self.assertEqual(closed.high, 101.0)
        self.assertEqual(closed.low, 100.0)
        self.assertEqual(closed.close, 101.0)
        self.assertEqual(closed.tick_count, 2)


if __name__ == "__main__":
    unittest.main()
