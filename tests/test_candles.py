from __future__ import annotations

import unittest

from synthetic_trader.data.candles import CandleBuilder, MultiTimeframeCandleBuilder
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


def _candles_of(builder, tf=None):
    """Collect every closed candle a builder produces for a tick stream.
    ``tf`` filters multi-timeframe results to one timeframe."""
    out = []

    def _collect(result):
        if isinstance(result, dict):
            out.extend(c for c in result.values() if c is not None and (tf is None or c.timeframe_sec == tf))
        elif result is not None and (tf is None or result.timeframe_sec == tf):
            out.append(result)

    for t in _TICKS:
        _collect(builder.update(t))
    _collect(builder.flush())
    return out


_TICKS = [
    Tick("R_75", 0.0, 100.0),
    Tick("R_75", 10.0, 100.5),
    Tick("R_75", 25.0, 101.2),
    Tick("R_75", 45.0, 100.8),
    Tick("R_75", 59.0, 101.0),
    Tick("R_75", 60.0, 101.5),
    Tick("R_75", 70.0, 102.0),
    Tick("R_75", 89.0, 101.7),
    Tick("R_75", 119.0, 102.3),
    Tick("R_75", 120.0, 102.1),
    Tick("R_75", 150.0, 102.8),
    Tick("R_75", 179.0, 103.0),
    Tick("R_75", 180.0, 103.5),
]


class MultiTimeframeCandleBuilderTests(unittest.TestCase):
    def test_matches_raw_builder_exactly(self) -> None:
        """The wrapper must produce identical candles to the raw builder.

        Regression: the old early-bail "canary bucket" fast path skipped
        mid-bucket ticks for every timeframe, freezing each candle at its
        FIRST tick (tick_count == 1, close == bucket-open price) instead of
        true OHLC.  That point-sampled series silently replaced real candle
        closes in every backtest and the live warmup, and the same
        timeframe produced different candles depending on which other
        timeframes were requested.
        """
        raw = _candles_of(CandleBuilder("R_75", 60))
        wrap = _candles_of(MultiTimeframeCandleBuilder("R_75", [60]))
        self.assertEqual(len(raw), len(wrap))
        for rc, wc in zip(raw, wrap):
            self.assertEqual((rc.open, rc.high, rc.low, rc.close, rc.tick_count),
                             (wc.open, wc.high, wc.low, wc.close, wc.tick_count))
        # True OHLC: the 0-60s candle must close at the LAST tick of its
        # bucket (101.0 @ t=59), not the first (100.0 @ t=0).
        self.assertEqual(raw[0].close, 101.0)
        self.assertEqual(raw[0].tick_count, 5)

    def test_candles_invariant_to_requested_timeframe_set(self) -> None:
        """300s candles must be identical whether built alone or alongside
        other timeframes.  The old early-bail made live (5 timeframes) build
        different 300s candles than the backtest (1 timeframe), so live
        could not reproduce its own backtest."""
        alone = _candles_of(MultiTimeframeCandleBuilder("R_75", [300]), tf=300)
        with_others = _candles_of(MultiTimeframeCandleBuilder("R_75", [60, 300, 900, 3600, 14400]), tf=300)
        self.assertEqual(len(alone), len(with_others))
        for a, b in zip(alone, with_others):
            self.assertEqual((a.open, a.high, a.low, a.close, a.tick_count),
                             (b.open, b.high, b.low, b.close, b.tick_count))
        # 300s candles must contain all 5 sub-minute ticks (no mid-bucket skip).
        self.assertGreater(alone[0].tick_count, 1)


if __name__ == "__main__":
    unittest.main()
