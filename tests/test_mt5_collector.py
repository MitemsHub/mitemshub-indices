from __future__ import annotations

import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from synthetic_trader.calibration.mt5_collector import (
    get_venue_symbol,
    collect_mt5_candle_history,
    collect_ticks_from_mt5,
)


def _fake_mt5(rates):
    """Build a fake MetaTrader5 module returning the given rates array."""

    def _make_rates(rows):
        class RateArray:
            def __init__(self, data):
                self._data = data

            def __len__(self):
                return len(self._data)

            def __getitem__(self, idx):
                return self._data[idx]

        return RateArray(rows)

    fake = types.ModuleType("MetaTrader5")
    fake.TIMEFRAME_M1 = 1
    fake.TIMEFRAME_M5 = 5
    fake.COPY_TICKS_ALL = 2
    fake.COPY_TICKS_INFO = 1
    fake.initialize = MagicMock(return_value=True)
    fake.shutdown = MagicMock()
    fake.last_error = MagicMock(return_value=(0, "ok"))
    fake.symbol_select = MagicMock(return_value=True)
    fake.symbol_info = MagicMock(return_value=MagicMock())
    fake.copy_rates_range = MagicMock(return_value=_make_rates(rates))
    fake.copy_ticks = MagicMock(return_value=())
    fake.login = MagicMock(return_value=True)
    return fake


class Mt5CollectorTests(unittest.TestCase):
    def test_get_venue_symbol_maps_r75_to_syn75(self) -> None:
        # Verified live on the Blueberry terminal: SYN75/SYN100 are the real
        # broker symbols, NOT "Volatility 75 Index".
        self.assertEqual(get_venue_symbol("R_75"), "SYN75")
        self.assertEqual(get_venue_symbol("R_100"), "SYN100")
        self.assertEqual(get_venue_symbol("SYN75"), "SYN75")

    def test_collect_mt5_candle_history_writes_ohlc_exact_ticks(self) -> None:
        # Candles must be strictly in the past: fetch_m1_candles excludes the
        # still-forming candle at the current minute bucket, so a one-shot
        # backfill ends at the last fully-closed minute.
        now = datetime.now(timezone.utc)
        base = int(now.timestamp() // 60) * 60
        rates = []
        for i in range(10):
            t = base - (10 - i) * 60
            rates.append(
                {
                    "time": t,
                    "open": 1500.0 + i,
                    "high": 1502.0 + i,
                    "low": 1498.0 + i,
                    "close": 1501.0 + i,
                }
            )
        fake = _fake_mt5(rates)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ticks.csv"
            with patch.dict(sys.modules, {"MetaTrader5": fake}):
                result = collect_mt5_candle_history(
                    symbol="R_75",
                    days=7,
                    output_path=output,
                )

            self.assertEqual(result.ticks_collected, 40)  # 10 candles x 4 ticks
            self.assertEqual(result.venue_symbol, "SYN75")
            self.assertTrue(output.exists())
            fake.symbol_select.assert_called_once_with("SYN75", True)
            fake.copy_rates_range.assert_called_once()

            # Rebuild candles from the reconstructed ticks and verify OHLC.
            from synthetic_trader.backtest.engine import load_ticks_csv
            from synthetic_trader.data.candles import CandleBuilder

            ticks = load_ticks_csv(output, default_symbol="R_75")
            ticks.sort(key=lambda tick: tick.epoch)
            builder = CandleBuilder("R_75", 60)
            closed = []
            for tick in ticks:
                candle = builder.update(tick)
                if candle is not None:
                    closed.append(candle)
            final = builder.flush()
            if final is not None:
                closed.append(final)

            self.assertEqual(len(closed), 10)
            for source, rebuilt in zip(rates, closed):
                self.assertAlmostEqual(rebuilt.open, source["open"])
                self.assertAlmostEqual(rebuilt.high, source["high"])
                self.assertAlmostEqual(rebuilt.low, source["low"])
                self.assertAlmostEqual(rebuilt.close, source["close"])

    def test_collect_mt5_candle_history_rejects_invalid_days(self) -> None:
        fake = _fake_mt5([])
        with patch.dict(sys.modules, {"MetaTrader5": fake}):
            with self.assertRaises(ValueError):
                collect_mt5_candle_history("R_75", 0, "ignored.csv")

    def test_collect_mt5_candle_history_raises_when_select_fails(self) -> None:
        fake = _fake_mt5([])
        fake.symbol_select = MagicMock(return_value=False)
        fake.last_error = MagicMock(return_value=(-1, "Terminal: Call failed"))
        with patch.dict(sys.modules, {"MetaTrader5": fake}):
            with self.assertRaises(RuntimeError):
                collect_mt5_candle_history("R_75", 7, "ignored.csv")

    def test_collect_mt5_candle_history_raises_when_no_rates(self) -> None:
        fake = _fake_mt5([])
        fake.copy_rates_range = MagicMock(return_value=None)
        with patch.dict(sys.modules, {"MetaTrader5": fake}):
            with self.assertRaises(RuntimeError):
                collect_mt5_candle_history("R_75", 7, "ignored.csv")


if __name__ == "__main__":
    unittest.main()
