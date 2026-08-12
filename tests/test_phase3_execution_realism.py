from __future__ import annotations

import asyncio
import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
from synthetic_trader.live.paper_runner import LivePaperSummary, run_live_paper
from synthetic_trader.reporting.serializers import to_json_ready
from tests.test_backtest import synthetic_ticks


class ExecutionRealismConfigTests(unittest.TestCase):
    def test_paper_execution_config_defaults_to_zero_penalties(self) -> None:
        config = PaperExecutionConfig()

        self.assertEqual(config.entry_slippage_ticks, 0.0)
        self.assertEqual(config.exit_slippage_ticks, 0.0)
        self.assertEqual(config.execution_penalty_per_trade, 0.0)

    def test_default_trader_config_exposes_paper_execution_realism_settings(self) -> None:
        config = TraderConfig.default()

        self.assertIsInstance(config.paper, PaperExecutionConfig)
        self.assertEqual(config.paper.entry_slippage_ticks, 0.0)
        self.assertEqual(config.paper.exit_slippage_ticks, 0.0)
        self.assertEqual(config.paper.execution_penalty_per_trade, 0.0)


class _EmptyClient:
    async def __aenter__(self) -> "_EmptyClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def ticks_history(self, symbol: str, count: int) -> list[object]:
        return []

    async def subscribe_ticks(self, symbol: str, timeout: float = 0.0):
        if False:
            yield None


class ExecutionRealismIntegrationTests(unittest.TestCase):
    def test_backtest_artifact_records_paper_realism_settings(self) -> None:
        config = replace(
            TraderConfig.default(),
            paper=PaperExecutionConfig(
                exit_slippage_ticks=0.5,
                execution_penalty_per_trade=0.2,
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "backtest.json"
            BacktestEngine(config=config).run_ticks(
                synthetic_ticks(),
                symbol="R_75",
                timeframe_sec=60,
                artifact_output_path=output,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["paper"]["exit_slippage_ticks"], 0.5)
        self.assertEqual(payload["paper"]["execution_penalty_per_trade"], 0.2)

    def test_run_live_paper_passes_realism_config_into_broker(self) -> None:
        config = replace(
            TraderConfig.default(),
            paper=PaperExecutionConfig(
                exit_slippage_ticks=0.25,
                execution_penalty_per_trade=0.1,
            ),
        )
        fake_broker = SimpleNamespace(positions={}, on_candle=lambda candle: [], close_all=lambda candle: [])

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "live.jsonl"
            with (
                patch("synthetic_trader.live.paper_runner.deriv_credentials_from_env", return_value=object()),
                patch("synthetic_trader.live.paper_runner.DerivWebSocketClient", return_value=_EmptyClient()),
                patch("synthetic_trader.live.execution_backends.PaperBroker", return_value=fake_broker) as broker_cls,
            ):
                summary = asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=0,
                        warmup_count=0,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=journal_path,
                        config=config,
                    )
                )

        self.assertEqual(summary.symbol, "R_75")
        self.assertEqual(summary.final_equity, config.risk.starting_equity)
        broker_cls.assert_called_once_with(config.paper)

    def test_backtest_cli_builds_paper_realism_config(self) -> None:
        from synthetic_trader.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ticks.csv"
            _write_ticks_csv(csv_path)
            result = SimpleNamespace(
                metrics=SimpleNamespace(
                    trades=0,
                    win_rate=0.0,
                    profit_factor=0.0,
                    expectancy_r=0.0,
                    net_pnl=0.0,
                ),
                signals=0,
                rejected_signals=0,
                final_equity=1000.0,
                model_version="unit-test",
            )

            with patch("synthetic_trader.cli.BacktestEngine") as engine_cls:
                engine_cls.return_value.run_ticks.return_value = result
                exit_code = main(
                    [
                        "backtest",
                        "--csv",
                        str(csv_path),
                        "--symbol",
                        "R_75",
                        "--timeframe",
                        "60",
                        "--exit-slippage-ticks",
                        "0.5",
                        "--execution-penalty",
                        "0.2",
                    ]
                )

        self.assertEqual(exit_code, 0)
        config = engine_cls.call_args.kwargs["config"]
        self.assertEqual(config.paper.exit_slippage_ticks, 0.5)
        self.assertEqual(config.paper.execution_penalty_per_trade, 0.2)

    def test_paper_live_cli_builds_paper_realism_config(self) -> None:
        from synthetic_trader.cli import main

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=0,
            warmup_ticks=0,
            signals=0,
            approved_signals=0,
            rejected_signals=0,
            closed_trades=0,
            shutdown_closed_trades=0,
            open_positions_before_shutdown=0,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1000.0,
            model_version="unit-test",
        )

        with patch("synthetic_trader.cli.run_live_paper", return_value=summary) as run_live_paper_mock:
            exit_code = main(
                [
                    "paper-live",
                    "--symbol",
                    "R_75",
                    "--duration-sec",
                    "1",
                    "--exit-slippage-ticks",
                    "0.25",
                    "--execution-penalty",
                    "0.1",
                ]
            )

        self.assertEqual(exit_code, 0)
        config = run_live_paper_mock.call_args.kwargs["config"]
        self.assertEqual(config.paper.exit_slippage_ticks, 0.25)
        self.assertEqual(config.paper.execution_penalty_per_trade, 0.1)


def _write_ticks_csv(path: Path, candles: int = 130, symbol: str = "R_75") -> None:
    ticks = synthetic_ticks(symbol=symbol, candles=candles)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["epoch", "price", "symbol"])
        writer.writeheader()
        for tick in ticks:
            writer.writerow({"epoch": tick.epoch, "price": tick.price, "symbol": tick.symbol})


if __name__ == "__main__":
    unittest.main()
