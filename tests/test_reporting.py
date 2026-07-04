from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.research.walk_forward import run_walk_forward, save_walk_forward_report
from synthetic_trader.reporting.serializers import to_json_ready

from tests.test_backtest import synthetic_ticks


class ReportingTests(unittest.TestCase):
    def test_to_json_ready_handles_nested_dataclasses(self) -> None:
        report = run_walk_forward(
            ticks=synthetic_ticks(candles=270),
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        payload = to_json_ready(report)

        self.assertEqual(payload["symbol"], "R_75")
        self.assertIn("folds", payload)
        self.assertIn("aggregate", payload)

    def test_backtest_can_write_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "backtest.json"
            result = BacktestEngine().run_ticks(
                synthetic_ticks(),
                symbol="R_75",
                timeframe_sec=60,
                artifact_output_path=output_path,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["final_equity"], result.final_equity)
        self.assertIn("metrics", payload)

    def test_save_walk_forward_report_writes_json_artifact(self) -> None:
        report = run_walk_forward(
            ticks=synthetic_ticks(candles=270),
            symbol="R_75",
            train_ticks=520,
            test_ticks=400,
            timeframe_sec=60,
            higher_timeframe_sec=300,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "walk-forward.json"
            save_walk_forward_report(report, output_path)

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["symbol"], "R_75")
        self.assertEqual(len(payload["folds"]), len(report.folds))


if __name__ == "__main__":
    unittest.main()
