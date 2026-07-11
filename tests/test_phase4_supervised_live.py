from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import AsyncMock, patch

from synthetic_trader.config import LiveMode


class Phase4ExecutionModeTests(unittest.TestCase):
    def test_live_mode_exposes_paper_dry_run_and_armed_values(self) -> None:
        self.assertEqual(LiveMode.PAPER.value, "paper")
        self.assertEqual(LiveMode.DRY_RUN_LIVE.value, "dry-run-live")
        self.assertEqual(LiveMode.ARMED_LIVE.value, "armed-live")


class Phase4ReadinessTests(unittest.TestCase):
    def test_readiness_fails_when_armed_live_has_no_token(self) -> None:
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            mode=LiveMode.ARMED_LIVE,
            symbol="R_75",
            app_id="12345",
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_api_token", report.failures)
        self.assertIn("missing_armed_confirmation", report.failures)

    def test_readiness_passes_for_dry_run_live_with_supported_symbol_and_app_id(self) -> None:
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_75",
            app_id="12345",
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertTrue(report.ready)
        self.assertEqual(report.failures, ())

    def test_readiness_collects_missing_app_id_and_unsupported_symbol_failures(self) -> None:
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_50",
            app_id=None,
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            report.failures,
            ("unsupported_symbol", "missing_app_id"),
        )


class Phase4GuardedExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_live_never_calls_buy(self) -> None:
        from synthetic_trader.live.supervised_live import execute_supervised_order

        client = AsyncMock()

        result = await execute_supervised_order(
            mode=LiveMode.DRY_RUN_LIVE,
            readiness_ok=True,
            client=client,
            proposal_id="proposal-1",
            price=10.0,
        )

        self.assertEqual(result, "dry-run-only")
        client.buy.assert_not_called()

    async def test_armed_live_refuses_when_readiness_fails(self) -> None:
        from synthetic_trader.live.supervised_live import execute_supervised_order

        client = AsyncMock()

        with self.assertRaisesRegex(RuntimeError, "live readiness failed"):
            await execute_supervised_order(
                mode=LiveMode.ARMED_LIVE,
                readiness_ok=False,
                client=client,
                proposal_id="proposal-1",
                price=10.0,
            )

        client.buy.assert_not_called()

    async def test_armed_live_calls_buy_only_when_ready(self) -> None:
        from synthetic_trader.live.supervised_live import execute_supervised_order

        client = AsyncMock()
        client.buy.return_value = {"buy": {"contract_id": 42}}

        result = await execute_supervised_order(
            mode=LiveMode.ARMED_LIVE,
            readiness_ok=True,
            client=client,
            proposal_id="proposal-1",
            price=10.0,
        )

        self.assertEqual(result["buy"]["contract_id"], 42)
        client.buy.assert_awaited_once_with("proposal-1", 10.0)


class Phase4CliTests(unittest.TestCase):
    def test_paper_live_reports_readiness_failures_for_unarmed_armed_live(self) -> None:
        from synthetic_trader.cli import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "paper-live",
                    "--symbol",
                    "R_75",
                    "--live-mode",
                    "armed-live",
                ]
            )

        self.assertNotEqual(exit_code, 0)
        self.assertIn("live_mode=armed-live", output.getvalue())
        self.assertIn("readiness_ok=False", output.getvalue())
        self.assertIn("missing_armed_confirmation", output.getvalue())

    def test_paper_live_dry_run_prints_ready_state_and_runs_runner(self) -> None:
        from synthetic_trader.cli import main
        from synthetic_trader.live.paper_runner import LivePaperSummary

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=5,
            warmup_ticks=50,
            signals=1,
            approved_signals=1,
            rejected_signals=0,
            closed_trades=1,
            shutdown_closed_trades=0,
            open_positions_before_shutdown=0,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1001.5,
            model_version="unit-test",
        )

        with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "paper-live",
                        "--symbol",
                        "R_75",
                        "--duration-sec",
                        "1",
                        "--live-mode",
                        "dry-run-live",
                        "--app-id",
                        "12345",
                    ]
                )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("live_mode=dry-run-live", rendered)
        self.assertIn("readiness_ok=True", rendered)
        self.assertIn("symbol=R_75", rendered)


class Phase4SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_supervised_session_routes_dry_run_mode(self) -> None:
        from synthetic_trader.live.supervised_live import run_supervised_live_session

        dry_run_runner = AsyncMock(return_value={"status": "dry-run"})
        armed_runner = AsyncMock(return_value={"status": "armed"})

        result = await run_supervised_live_session(
            mode=LiveMode.DRY_RUN_LIVE,
            readiness_ok=True,
            dry_run_runner=dry_run_runner,
            armed_runner=armed_runner,
        )

        self.assertEqual(result["status"], "dry-run")
        dry_run_runner.assert_awaited_once()
        armed_runner.assert_not_called()

    async def test_supervised_session_refuses_paper_mode(self) -> None:
        from synthetic_trader.live.supervised_live import run_supervised_live_session

        with self.assertRaisesRegex(RuntimeError, "paper mode"):
            await run_supervised_live_session(
                mode=LiveMode.PAPER,
                readiness_ok=True,
                dry_run_runner=AsyncMock(),
                armed_runner=AsyncMock(),
            )


if __name__ == "__main__":
    unittest.main()
