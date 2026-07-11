from __future__ import annotations

import unittest

from synthetic_trader.live.supervised_live import LatencyProfile, LatencyStage


class Phase11LatencyTypeTests(unittest.TestCase):
    def test_latency_profile_stores_stages_and_total_duration(self) -> None:
        profile = LatencyProfile(
            stages=(
                LatencyStage(name="readiness", duration_ms=1.5, category="critical"),
                LatencyStage(
                    name="summary_print",
                    duration_ms=0.5,
                    category="side_effect",
                ),
            )
        )

        self.assertEqual(profile.total_duration_ms, 2.0)
        self.assertEqual(profile.stages[0].name, "readiness")
        self.assertEqual(profile.stages[1].category, "side_effect")


class Phase11LatencyRecordingTests(unittest.TestCase):
    def test_record_latency_stage_appends_structured_stage(self) -> None:
        from synthetic_trader.live.supervised_live import LatencyRecorder

        recorder = LatencyRecorder()
        recorder.record_stage("readiness", duration_ms=1.25, category="critical")
        recorder.record_stage("journal", duration_ms=0.75, category="side_effect")

        profile = recorder.build_profile()

        self.assertEqual(len(profile.stages), 2)
        self.assertEqual(profile.stages[0].name, "readiness")
        self.assertEqual(profile.stages[1].category, "side_effect")
        self.assertEqual(profile.total_duration_ms, 2.0)


class Phase11SupervisedLatencyTests(unittest.TestCase):
    def test_run_supervised_live_session_can_return_latency_profile(self) -> None:
        import asyncio

        from synthetic_trader.config import LiveMode, Venue
        from synthetic_trader.live.supervised_live import run_supervised_live_session

        async def dry_run_runner() -> str:
            return "dry-run-result"

        result, profile = asyncio.run(
            run_supervised_live_session(
                venue=Venue.DERIV,
                mode=LiveMode.DRY_RUN_LIVE,
                readiness_ok=True,
                dry_run_runner=dry_run_runner,
                armed_runner=dry_run_runner,
                capture_latency=True,
            )
        )

        self.assertEqual(result, "dry-run-result")
        self.assertGreaterEqual(len(profile.stages), 1)
        self.assertEqual(profile.stages[0].category, "critical")


class Phase11PaperLatencyTests(unittest.TestCase):
    def test_live_paper_run_can_emit_latency_stage_names(self) -> None:
        from synthetic_trader.live.paper_runner import classify_latency_stage

        self.assertEqual(classify_latency_stage("journal_append"), "side_effect")
        self.assertEqual(classify_latency_stage("signal_decision"), "critical")


class Phase11LatencyCliTests(unittest.TestCase):
    def test_paper_live_can_print_latency_summary_when_requested(self) -> None:
        import contextlib
        import io
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

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
        profile = SimpleNamespace(total_duration_ms=2.0, stages=())

        output = io.StringIO()
        with patch(
            "synthetic_trader.cli.run_supervised_live_session",
            new=AsyncMock(return_value=(summary, profile)),
        ):
            with patch(
                "synthetic_trader.cli._render_latency_profile",
                return_value="latency_total_ms=2.0",
                create=True,
            ):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    try:
                        exit_code = main(
                            [
                                "paper-live",
                                "--symbol",
                                "R_75",
                                "--live-mode",
                                "dry-run-live",
                                "--app-id",
                                "12345",
                                "--latency-profile",
                            ]
                        )
                    except SystemExit as exc:
                        exit_code = exc.code

        self.assertEqual(exit_code, 0)
        self.assertIn("latency_total_ms=2.0", output.getvalue())


class Phase11LatencyRegressionTests(unittest.TestCase):
    def test_latency_capture_is_optional_and_existing_behavior_remains_supported(self) -> None:
        import asyncio

        from synthetic_trader.config import LiveMode, Venue
        from synthetic_trader.live.supervised_live import run_supervised_live_session

        async def dry_run_runner() -> str:
            return "ok"

        result = asyncio.run(
            run_supervised_live_session(
                venue=Venue.DERIV,
                mode=LiveMode.DRY_RUN_LIVE,
                readiness_ok=True,
                dry_run_runner=dry_run_runner,
                armed_runner=dry_run_runner,
            )
        )

        self.assertEqual(result, "ok")


if __name__ == "__main__":
    unittest.main()
