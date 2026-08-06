"""Tests for the per-symbol tick coverage / WFO readiness report."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.data.tick_store import write_ticks_csv
from synthetic_trader.domain import Tick
from synthetic_trader.scripts.tick_coverage_stats import (
    MIN_WFO_TICKS,
    WFO_DAY_SCALE_SPAN_HOURS,
    WFO_COARSE_SCALE_SPAN_HOURS,
    WFO_HOUR_SCALE_SPAN_HOURS,
    CoverageReport,
    SymbolCoverage,
    build_coverage_report,
    compute_symbol_coverage,
)


def _write_ticks(root: Path, symbol: str, ticks: list[Tick], subdir: str = "backfill") -> Path:
    target = root / "data" / subdir
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{symbol}_ticks.csv"
    write_ticks_csv(path, ticks)
    return path


def _spanned_ticks(symbol: str, days: float, ticks_per_sec: int = 4) -> list[Tick]:
    """Ticks covering ``days`` days at ``ticks_per_sec`` per second (1s index)."""
    start = 1_750_000_000
    total = int(days * 86400 * ticks_per_sec)
    step = 1.0 / ticks_per_sec
    return [
        Tick(symbol=symbol, epoch=start + i * step, price=1500.0 + (i % 100) * 0.01)
        for i in range(total)
    ]


class CoverageReportTests(unittest.TestCase):
    def test_clean_corpus_reports_span_and_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ticks(root, "R_75", _spanned_ticks("R_75", 1.0))

            cov = compute_symbol_coverage("R_75", engine_root=str(root))
            self.assertIsNone(cov.error)
            self.assertGreater(cov.span_hours, 23.0)
            self.assertLess(cov.span_hours, 25.0)
            self.assertGreater(cov.ticks, 300_000)
            self.assertGreater(cov.ticks_per_day, 0)
            # 1 day at 60s → ~1440 candles → windows at 4h (240 bars).
            # Fixture spans 86399.75s (345600 ticks × 0.25s step), so derive
            # the expected window count from the reported candle count.
            h4 = next(h for h in cov.horizons if h.timeframe_sec == 60 and h.horizon_hours == 4.0)
            expected_candles = int(cov.span_hours * 3600 / 60)
            self.assertEqual(h4.n_candles, expected_candles)
            self.assertEqual(h4.usable_windows, expected_candles - 240 - 60)
            self.assertTrue(h4.verdict_ready)

    def test_wfo_readiness_scales_with_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # < 8h → not ready
            _write_ticks(root, "R_75", _spanned_ticks("R_75", 0.2))
            cov = compute_symbol_coverage("R_75", engine_root=str(root))
            self.assertFalse(cov.wfo.ready)
            self.assertEqual(cov.wfo.scale, "insufficient")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # ~12h → coarse (>= 8h)
            _write_ticks(root, "R_75", _spanned_ticks("R_75", 0.5))
            cov = compute_symbol_coverage("R_75", engine_root=str(root))
            self.assertTrue(cov.wfo.ready)
            self.assertEqual(cov.wfo.scale, "coarse")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # ~3 days → day scale (>= 30h)
            _write_ticks(root, "R_75", _spanned_ticks("R_75", 3.0))
            cov = compute_symbol_coverage("R_75", engine_root=str(root))
            self.assertTrue(cov.wfo.ready)
            self.assertEqual(cov.wfo.scale, "day")
            self.assertEqual(cov.wfo.is_days, 0.5)

    def test_missing_symbol_returns_error_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cov = compute_symbol_coverage("R_99", engine_root=str(tmp))
            self.assertIsNotNone(cov.error)
            self.assertEqual(cov.error, "no_tick_csv")
            self.assertEqual(cov.ticks, 0)

    def test_few_ticks_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ticks = [Tick(symbol="R_75", epoch=1_750_000_000 + i, price=1500.0) for i in range(10)]
            _write_ticks(root, "R_75", ticks)
            cov = compute_symbol_coverage("R_75", engine_root=str(root))
            self.assertFalse(cov.wfo.ready)
            self.assertEqual(cov.wfo.scale, "insufficient")

    def test_build_report_and_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ticks(root, "R_75", _spanned_ticks("R_75", 0.5))
            _write_ticks(root, "R_100", _spanned_ticks("R_100", 2.0))

            report = build_coverage_report(["R_75", "R_100"], engine_root=str(root))
            self.assertIsInstance(report, CoverageReport)
            self.assertEqual(len(report.symbols), 2)
            by_sym = {s.symbol: s for s in report.symbols}
            self.assertTrue(by_sym["R_100"].wfo.ready)
            self.assertEqual(by_sym["R_100"].wfo.scale, "day")

            payload = json.loads(report.to_json())
            self.assertEqual(payload["symbols"][0]["symbol"], "R_75")
            self.assertIn("wfo", payload["symbols"][0])
            self.assertIn("horizons", payload["symbols"][0])


if __name__ == "__main__":
    unittest.main()
