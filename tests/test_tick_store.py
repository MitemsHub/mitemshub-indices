from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synthetic_trader.data.tick_store import inspect_ticks, normalize_ticks, write_ticks_csv
from synthetic_trader.domain import Tick


class TickStoreTests(unittest.TestCase):
    def test_normalize_removes_duplicate_ticks(self) -> None:
        ticks = [
            Tick("R_75", 1_700_000_002, 101.0),
            Tick("R_75", 1_700_000_001, 100.0),
            Tick("R_75", 1_700_000_001, 100.0),
        ]

        normalized, duplicates = normalize_ticks(ticks)

        self.assertEqual(duplicates, 1)
        self.assertEqual([tick.epoch for tick in normalized], [1_700_000_001, 1_700_000_002])

    def test_inspect_ticks_reports_quality(self) -> None:
        ticks = [
            Tick("R_75", 1_700_000_002, 101.0),
            Tick("R_75", 1_700_000_001, 100.0),
            Tick("R_75", 1_700_000_003, 102.0),
        ]

        report = inspect_ticks(ticks, symbol="R_75")

        self.assertEqual(report.ticks, 3)
        self.assertEqual(report.out_of_order, 1)
        self.assertEqual(report.symbols, ("R_75",))
        self.assertGreater(report.max_abs_return, 0.0)

    def test_write_ticks_csv_creates_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ticks.csv"
            write_ticks_csv(path, [Tick("R_75", 1_700_000_001, 100.0)])

            content = path.read_text(encoding="utf-8")

        self.assertIn("epoch,symbol,price", content)
        self.assertIn("R_75", content)

    def test_normalize_drops_junk_rows_from_copy_rates_range(self) -> None:
        """MT5's copy_rates_range can return uninitialised rows (epoch ~0 or
        in the far future, price 0.0/1.0/4.0) while downloading history.
        normalize_ticks must drop them so they never poison the corpus."""
        nowish = 1_700_000_000.0
        ticks = [
            Tick("R_75", 63.176, -1.0),          # garbage epoch + negative price
            Tick("R_75", 0.51, 1531.452),        # garbage epoch (pre-2001)
            Tick("R_75", 999.0, 1.0),            # garbage epoch + degenerate price
            Tick("R_75", 9_999_482.0, 4.0),      # garbage epoch
            Tick("R_75", 349_999_999_999_454.0, 0.0168),  # far-future epoch
            Tick("R_75", nowish, 1700.0),        # the one valid tick
        ]

        normalized, _ = normalize_ticks(ticks)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].epoch, nowish)
        self.assertEqual(normalized[0].price, 1700.0)


if __name__ == "__main__":
    unittest.main()
