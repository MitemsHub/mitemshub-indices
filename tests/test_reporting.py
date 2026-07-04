from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.cli import main
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

    def test_backtest_command_writes_json_artifact_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ticks.csv"
            output_path = Path(tmpdir) / "backtest.json"
            _write_ticks_csv(csv_path, candles=130)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "backtest",
                        "--csv",
                        str(csv_path),
                        "--symbol",
                        "R_75",
                        "--timeframe",
                        "60",
                        "--artifact-output",
                        str(output_path),
                    ]
                )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["model_version"].startswith("online-logistic-v1."))
        self.assertIn("final_equity", payload)

    def test_backtest_command_artifact_includes_paper_realism_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ticks.csv"
            output_path = Path(tmpdir) / "backtest.json"
            _write_ticks_csv(csv_path, candles=130)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "backtest",
                        "--csv",
                        str(csv_path),
                        "--symbol",
                        "R_75",
                        "--timeframe",
                        "60",
                        "--artifact-output",
                        str(output_path),
                        "--exit-slippage-ticks",
                        "0.5",
                        "--execution-penalty",
                        "0.2",
                    ]
                )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["paper"]["exit_slippage_ticks"], 0.5)
        self.assertEqual(payload["paper"]["execution_penalty_per_trade"], 0.2)

    def test_walk_forward_command_writes_json_artifact_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ticks.csv"
            output_path = Path(tmpdir) / "walk-forward.json"
            _write_ticks_csv(csv_path, candles=270)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "walk-forward",
                        "--csv",
                        str(csv_path),
                        "--symbol",
                        "R_75",
                        "--train-ticks",
                        "520",
                        "--test-ticks",
                        "400",
                        "--timeframe",
                        "60",
                        "--higher-timeframe",
                        "300",
                        "--artifact-output",
                        str(output_path),
                    ]
                )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["symbol"], "R_75")
        self.assertIn("folds", payload)


def _write_ticks_csv(path: Path, candles: int, symbol: str = "R_75") -> None:
    ticks = synthetic_ticks(symbol=symbol, candles=candles)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["epoch", "price", "symbol"])
        writer.writeheader()
        for tick in ticks:
            writer.writerow({"epoch": tick.epoch, "price": tick.price, "symbol": tick.symbol})


if __name__ == "__main__":
    unittest.main()
