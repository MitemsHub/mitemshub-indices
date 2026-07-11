from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synthetic_trader.data.tick_store import inspect_ticks, normalize_ticks, write_ticks_csv
from synthetic_trader.domain import Tick


class TickStoreTests(unittest.TestCase):
    def test_normalize_removes_duplicate_ticks(self) -> None:
        ticks = [
            Tick("R_75", 2, 101.0),
            Tick("R_75", 1, 100.0),
            Tick("R_75", 1, 100.0),
        ]

        normalized, duplicates = normalize_ticks(ticks)

        self.assertEqual(duplicates, 1)
        self.assertEqual([tick.epoch for tick in normalized], [1, 2])

    def test_inspect_ticks_reports_quality(self) -> None:
        ticks = [
            Tick("R_75", 2, 101.0),
            Tick("R_75", 1, 100.0),
            Tick("R_75", 3, 102.0),
        ]

        report = inspect_ticks(ticks, symbol="R_75")

        self.assertEqual(report.ticks, 3)
        self.assertEqual(report.out_of_order, 1)
        self.assertEqual(report.symbols, ("R_75",))
        self.assertGreater(report.max_abs_return, 0.0)

    def test_write_ticks_csv_creates_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ticks.csv"
            write_ticks_csv(path, [Tick("R_75", 1, 100.0)])

            content = path.read_text(encoding="utf-8")

        self.assertIn("epoch,symbol,price", content)
        self.assertIn("R_75", content)


if __name__ == "__main__":
    unittest.main()
