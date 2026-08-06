from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from synthetic_trader.config import DEFAULT_DERIV_APP_ID
from synthetic_trader.data.candles import CandleBuilder
from synthetic_trader.data.collector import (
    candles_to_ticks,
    collect_candle_history,
    collect_history,
    deriv_credentials_from_env,
)


class CollectorTests(unittest.TestCase):
    def test_uses_default_app_id(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            credentials = deriv_credentials_from_env()

        self.assertEqual(credentials.app_id, DEFAULT_DERIV_APP_ID)
        self.assertIsNone(credentials.token)

    def test_explicit_app_id_overrides_default(self) -> None:
        credentials = deriv_credentials_from_env(app_id="123")

        self.assertEqual(credentials.app_id, "123")

    def test_collect_history_rejects_invalid_count(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(collect_history("R_75", 0, "ignored.csv"))

    def test_collect_candle_history_rejects_invalid_days(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(collect_candle_history("R_75", 0, "ignored.csv"))

    def test_candles_to_ticks_reproduces_exact_ohlc(self) -> None:
        # Use epochs aligned to the 60s grid (1_000_000_000 is NOT on the
        # grid: 1e9 % 60 = 40, so the bucket becomes 999_999_960).
        candles = [
            {"epoch": 999_999_960.0, "open": 100.0, "high": 105.5, "low": 98.2, "close": 103.7},
            {"epoch": 1_000_000_020.0, "open": 103.7, "high": 107.0, "low": 102.0, "close": 104.0},
        ]
        ticks = candles_to_ticks("R_75", candles, timeframe_sec=60)

        self.assertEqual(len(ticks), 8)
        # 4 ticks per candle, all inside the source bucket
        self.assertEqual([t.epoch for t in ticks[:4]], [999_999_960.01, 999_999_960.26, 999_999_960.51, 999_999_960.76])
        self.assertEqual([t.price for t in ticks[:4]], [100.0, 105.5, 98.2, 103.7])

        # Feeding the reconstructed ticks back through the candle builder
        # must reproduce the exact OHLC of every source candle.
        builder = CandleBuilder("R_75", 60)
        closed = []
        for tick in sorted(ticks, key=lambda t: t.epoch):
            candle = builder.update(tick)
            if candle is not None:
                closed.append(candle)
        final = builder.flush()
        if final is not None:
            closed.append(final)

        self.assertEqual(len(closed), 2)
        for source, rebuilt in zip(candles, closed):
            self.assertEqual(rebuilt.open, source["open"])
            self.assertEqual(rebuilt.high, source["high"])
            self.assertEqual(rebuilt.low, source["low"])
            self.assertEqual(rebuilt.close, source["close"])

    def test_candles_to_ticks_rejects_invalid_timeframe(self) -> None:
        with self.assertRaises(ValueError):
            candles_to_ticks("R_75", [{"epoch": 1.0, "open": 1, "high": 1, "low": 1, "close": 1}], timeframe_sec=0)

    def test_collect_candle_history_pages_back_until_cutoff(self) -> None:
        now = 1_800_000_000.0
        candle = lambda epoch: {"epoch": epoch, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
        # days=0.1 -> cutoff = now - 8640s.  Page 1 spans now..now-5940
        # (does NOT cross the cutoff -> keep paging); page 2 spans
        # now-6000..now-11940 (crosses it -> loop breaks).
        pages = [
            [candle(now - i * 60) for i in range(100)],
            [candle(now - 6000 - i * 60) for i in range(100)],
        ]

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.candles_history = AsyncMock(side_effect=pages)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ticks.csv"
            with patch(
                "synthetic_trader.data.collector.deriv_credentials_from_env",
                return_value=MagicMock(app_id="116450"),
            ), patch("synthetic_trader.data.collector.DerivWebSocketClient", return_value=client):
                with patch("synthetic_trader.data.collector.time.time", return_value=now):
                    report = asyncio.run(
                        collect_candle_history("R_75", days=0.1, output_path=output, granularity=60)
                    )

            # cutoff = now - 8640s.  Page 1 candles all survive
            # (now..now-5940).  Page 2 candles up to now-8640 survive:
            # epochs now-6000..now-8640 are ~44 of the 100 -> ticks in
            # (100, 200) candles * 4.
            self.assertGreaterEqual(report.ticks, 100 * 4)
            self.assertLess(report.ticks, 200 * 4)
            self.assertTrue(output.exists())
            self.assertEqual(client.candles_history.call_count, 2)
            # end advanced: first call "latest", then earliest of page 1 - 1
            ends = [call.kwargs["end"] for call in client.candles_history.call_args_list]
            self.assertEqual(ends[0], "latest")
            self.assertEqual(ends[1], 1_800_000_000 - 5940 - 1)

    def test_collect_candle_history_filters_below_cutoff(self) -> None:
        now = 1_800_000_000.0
        candle = lambda epoch: {"epoch": epoch, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
        # Single page entirely older than the cutoff
        pages = [[candle(now - 3 * 86400 - i * 60) for i in range(50)]]

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.candles_history = AsyncMock(side_effect=pages)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ticks.csv"
            with patch(
                "synthetic_trader.data.collector.deriv_credentials_from_env",
                return_value=MagicMock(app_id="116450"),
            ), patch("synthetic_trader.data.collector.DerivWebSocketClient", return_value=client):
                with patch("synthetic_trader.data.collector.time.time", return_value=now):
                    report = asyncio.run(
                        collect_candle_history("R_75", days=1.0, output_path=output, granularity=60)
                    )

            # cutoff = now - 86400; every candle is older -> all filtered out
            self.assertEqual(report.ticks, 0)
            self.assertTrue(output.exists())

    def test_collect_candle_history_stops_on_empty_page(self) -> None:
        now = 1_800_000_000.0
        candle = lambda epoch: {"epoch": epoch, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
        pages = [[candle(now - i * 60) for i in range(10)], []]

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.candles_history = AsyncMock(side_effect=pages)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ticks.csv"
            with patch(
                "synthetic_trader.data.collector.deriv_credentials_from_env",
                return_value=MagicMock(app_id="116450"),
            ), patch("synthetic_trader.data.collector.DerivWebSocketClient", return_value=client):
                with patch("synthetic_trader.data.collector.time.time", return_value=now):
                    report = asyncio.run(
                        collect_candle_history("R_75", days=0.1, output_path=output, granularity=60)
                    )

            self.assertEqual(client.candles_history.call_count, 2)
            self.assertGreaterEqual(report.ticks, 10 * 4)


if __name__ == "__main__":
    unittest.main()
