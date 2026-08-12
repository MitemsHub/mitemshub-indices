from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

from synthetic_trader.config import LiveMode, Mt5Config, TraderConfig, Venue
from synthetic_trader.domain import Tick
from synthetic_trader.execution.mt5 import build_mt5_credentials, mt5_dependency_available
from synthetic_trader.live.paper_runner import LivePaperSummary, run_live_paper
from synthetic_trader.live.supervised_live import (
    build_live_readiness_report,
    run_supervised_live_session,
)


class Phase5VenueConfigTests(unittest.TestCase):
    def test_venue_exposes_deriv_and_mt5_values(self) -> None:
        self.assertEqual(Venue.DERIV.value, "deriv")
        self.assertEqual(Venue.MT5.value, "mt5")

    def test_mt5_config_maps_project_symbol_to_mt5_symbol(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal64.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        self.assertEqual(config.resolve_symbol("R_75"), "Volatility 75 Index")


class Phase5Mt5AdapterTests(unittest.TestCase):
    def test_build_mt5_credentials_preserves_symbol_map(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal64.exe",
            symbol_map={"R_100": "Volatility 100 Index"},
        )

        credentials = build_mt5_credentials(config)
        self.assertEqual(credentials.symbol_map["R_100"], "Volatility 100 Index")

    def test_mt5_dependency_available_returns_bool(self) -> None:
        self.assertIn(mt5_dependency_available(), {True, False})


class Phase5PaperRunnerVenueTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_live_paper_uses_injected_market_data_client(self) -> None:
        class FakeClient:
            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def ticks_history(
                self,
                symbol: str,
                count: int = 5000,
                end: str | int = "latest",
            ) -> list[Tick]:
                return [Tick(symbol=symbol, epoch=1.0, price=100.0)]

            async def subscribe_ticks(self, symbol: str, timeout: float = 0.0):
                if False:
                    yield Tick(symbol=symbol, epoch=2.0, price=101.0)

        summary = await run_live_paper(
            symbol="R_75",
            duration_sec=0,
            warmup_count=1,
            max_live_ticks=0,
            config=TraderConfig.default(),
            venue=Venue.MT5,
            client_factory=lambda: FakeClient(),
        )

        self.assertEqual(summary.symbol, "R_75")
        self.assertEqual(summary.warmup_ticks, 1)


class Phase5SupervisedVenueTests(unittest.IsolatedAsyncioTestCase):
    async def test_mt5_readiness_fails_without_symbol_mapping(self) -> None:
        report = build_live_readiness_report(
            venue=Venue.MT5,
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_75",
            app_id=None,
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
            mt5_config=Mt5Config(server="Broker-Demo", login="123456", password="secret"),
            mt5_dependency_ready=True,
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_mt5_symbol_mapping", report.failures)

    async def test_supervised_session_routes_mt5_runner(self) -> None:
        runner = AsyncMock(return_value={"status": "mt5-dry-run"})

        result = await run_supervised_live_session(
            venue=Venue.MT5,
            mode=LiveMode.DRY_RUN_LIVE,
            readiness_ok=True,
            dry_run_runner=runner,
            armed_runner=AsyncMock(),
        )

        self.assertEqual(result["status"], "mt5-dry-run")
        runner.assert_awaited_once()


class Phase5CliVenueTests(unittest.TestCase):
    def test_paper_live_mt5_reports_readiness_failures(self) -> None:
        from synthetic_trader.cli import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "paper-live",
                    "--venue",
                    "mt5",
                    "--symbol",
                    "R_75",
                    "--live-mode",
                    "dry-run-live",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("missing_mt5_server", output.getvalue())

    def test_paper_live_mt5_uses_mt5_runner_path(self) -> None:
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

        with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
            with patch("synthetic_trader.cli.run_live_paper", return_value=summary) as run_live_paper_mock:
                exit_code = main(
                    [
                        "paper-live",
                        "--venue",
                        "mt5",
                        "--symbol",
                        "R_75",
                        "--live-mode",
                        "dry-run-live",
                        "--mt5-server",
                        "Broker-Demo",
                        "--mt5-login",
                        "123456",
                        "--mt5-password",
                        "secret",
                        "--mt5-symbol",
                        "Volatility 75 Index",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_live_paper_mock.call_args.kwargs["venue"].value, "mt5")

    def test_paper_live_mt5_armed_mode_checks_runtime_before_starting(self) -> None:
        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        output = io.StringIO()
        runtime_status = Mt5RuntimeStatus(
            ready=False,
            failures=("mt5_initialize_failed",),
            venue_symbol="Volatility 75 Index",
        )

        with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "paper-live",
                            "--venue",
                            "mt5",
                            "--symbol",
                            "R_75",
                            "--live-mode",
                            "armed-live",
                            "--armed-live",
                            "--mt5-server",
                            "Broker-Demo",
                            "--mt5-login",
                            "123456",
                            "--mt5-password",
                            "secret",
                            "--mt5-symbol",
                            "Volatility 75 Index",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("mt5_initialize_failed", output.getvalue())


class Phase5RegressionTests(unittest.TestCase):
    def test_mt5_supervised_path_fails_closed_without_runtime(self) -> None:
        report = build_live_readiness_report(
            venue=Venue.MT5,
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_75",
            app_id=None,
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
            mt5_config=Mt5Config(
                server="Broker-Demo",
                login="123456",
                password="secret",
                symbol_map={"R_75": "Volatility 75 Index"},
            ),
            mt5_dependency_ready=False,
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_mt5_runtime", report.failures)


if __name__ == "__main__":
    unittest.main()
