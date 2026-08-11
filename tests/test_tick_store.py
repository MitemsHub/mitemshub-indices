from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synthetic_trader.data.tick_store import (
    SCALE_GUARD_MAX_RATIO,
    _apply_scale_guard,
    append_ticks_csv,
    inspect_ticks,
    normalize_ticks,
    write_ticks_csv,
)
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

    def test_scale_guard_rejects_wrong_venue_ticks(self) -> None:
        """Deriv 1HZ75V ticks (~7,400) must never be appended into a
        Blueberry SYN75 corpus (~1,770) — a 4.2x price-scale mismatch that
        would silently poison the compounding corpus."""
        existing = [Tick("R_75", 1_700_000_000 + i, 1770.0 + (i % 5)) for i in range(50)]
        incoming = [
            Tick("R_75", 1_700_000_100, 7402.47),  # Deriv scale — must drop
            Tick("R_75", 1_700_000_101, 7388.10),  # Deriv scale — must drop
            Tick("R_75", 1_700_000_102, 1791.55),  # correct scale — keep
            Tick("R_75", 1_700_000_103, 1812.03),  # correct scale — keep
        ]

        kept = _apply_scale_guard(incoming, existing)

        self.assertEqual([t.price for t in kept], [1791.55, 1812.03])
        # The guard MUST catch the real-world Deriv/MT5 mismatch: Deriv's R_75
        # ~6,900-7,400 vs Blueberry SYN75 ~1,800-1,980 is only ~3.7x — a 4.0
        # threshold was too loose and let the exact pollution it was built to
        # stop sail through (observed in data/R_75_ticks.csv).  The threshold
        # must be well under 3.7x while staying far above real intraday range
        # (~1.1x, p99/p1 = 1.06 on the 9.5-day corpus).
        self.assertLess(SCALE_GUARD_MAX_RATIO, 3.5)
        self.assertGreaterEqual(SCALE_GUARD_MAX_RATIO, 2.0)

    def test_scale_guard_catches_real_deriv_ratio(self) -> None:
        """The exact live mismatch — Deriv R_75 ~6,920 appended into a
        Blueberry SYN75 corpus ~1,855 (3.73x) — must be dropped."""
        existing = [Tick("R_75", 1_700_000_000 + i, 1855.0 + (i % 7)) for i in range(50)]
        incoming = [
            Tick("R_75", 1_700_000_100 + i, 6917.0 + i) for i in range(5)
        ]

        kept = _apply_scale_guard(incoming, existing)

        self.assertEqual(kept, [])

    def test_scale_guard_passes_small_corpus_through(self) -> None:
        """A corpus too small to judge scale (<20 ticks) must not reject anything."""
        existing = [Tick("R_75", 1_700_000_000 + i, 100.0 + i) for i in range(5)]
        incoming = [Tick("R_75", 1_700_000_100, 7402.47)]

        kept = _apply_scale_guard(incoming, existing)

        self.assertEqual(len(kept), 1)

    def test_append_ticks_csv_scale_guard_end_to_end(self) -> None:
        """append_ticks_csv must refuse to merge wrong-scale ticks into an
        existing file, and must still append correct-scale ticks."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ticks.csv"
            base = [Tick("R_75", 1_700_000_000 + i, 1770.0 + (i % 7)) for i in range(30)]
            write_ticks_csv(path, base)

            # Wrong-scale batch: Deriv 1HZ75V ~7,400 (should be fully dropped)
            bad = [Tick("R_75", 1_700_000_200 + i, 7400.0 + i) for i in range(10)]
            append_ticks_csv(path, bad)
            content = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(content), 31)  # header + 30 base ticks, none appended

            # Correct-scale batch: appends fine
            good = [Tick("R_75", 1_700_000_300 + i, 1790.0 + i) for i in range(5)]
            append_ticks_csv(path, good)
            content = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(content), 36)  # header + 30 base + 5 good

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
