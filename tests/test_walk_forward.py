from __future__ import annotations

import unittest

from synthetic_trader.domain import Tick
from synthetic_trader.research.walk_forward import render_walk_forward_report, run_walk_forward

from tests.test_backtest import synthetic_ticks


class WalkForwardTests(unittest.TestCase):
    def test_walk_forward_builds_fold_report(self) -> None:
        report = run_walk_forward(
            ticks=synthetic_ticks(candles=270),
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        rendered = render_walk_forward_report(report)

        self.assertGreaterEqual(len(report.folds), 1)
        self.assertIn("folds=", rendered)
        self.assertEqual(report.symbol, "R_75")

    def test_walk_forward_keeps_fold_windows_strictly_non_overlapping_at_epoch_boundary(self) -> None:
        ticks = synthetic_ticks(candles=270)
        boundary_index = 520
        ticks[boundary_index] = Tick(
            symbol=ticks[boundary_index].symbol,
            epoch=ticks[boundary_index - 1].epoch,
            price=ticks[boundary_index].price,
        )

        report = run_walk_forward(
            ticks=ticks,
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        self.assertGreaterEqual(len(report.folds), 1)
        for fold in report.folds:
            self.assertLess(fold.train_end_epoch, fold.test_start_epoch)


if __name__ == "__main__":
    unittest.main()
