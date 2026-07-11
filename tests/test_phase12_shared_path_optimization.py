from __future__ import annotations

import asyncio
import unittest

from synthetic_trader.config import LiveMode, Venue
from synthetic_trader.live.supervised_live import run_supervised_live_session


class Phase12SharedPathContractTests(unittest.TestCase):
    def test_supervised_session_still_returns_plain_result_by_default(self) -> None:
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

    def test_supervised_session_keeps_latency_profile_opt_in(self) -> None:
        async def dry_run_runner() -> str:
            return "ok"

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

        self.assertEqual(result, "ok")
        self.assertGreaterEqual(len(profile.stages), 1)


class Phase12RoutingOptimizationTests(unittest.TestCase):
    def test_latency_profile_stage_names_remain_stable_after_shared_path_tightening(
        self,
    ) -> None:
        async def dry_run_runner() -> str:
            return "ok"

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

        self.assertEqual(result, "ok")
        self.assertEqual(
            [stage.name for stage in profile.stages],
            ["readiness_gate", "supervised_route"],
        )


class Phase12SharedSideEffectTests(unittest.TestCase):
    def test_shared_side_effect_stage_names_stay_classified_as_side_effects(self) -> None:
        from synthetic_trader.live.paper_runner import classify_latency_stage

        self.assertEqual(classify_latency_stage("journal_append"), "side_effect")
        self.assertEqual(classify_latency_stage("summary_print"), "side_effect")
        self.assertEqual(classify_latency_stage("readiness_gate"), "critical")


class Phase12LatencyCliStabilityTests(unittest.TestCase):
    def test_paper_live_does_not_emit_latency_lines_without_opt_in(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.live.paper_runner import LivePaperSummary

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=1,
            warmup_ticks=1,
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

        output = io.StringIO()
        with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
            with contextlib.redirect_stdout(output):
                exit_code = main(["paper-live", "--symbol", "R_75"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("latency_total_ms=", output.getvalue())


if __name__ == "__main__":
    unittest.main()
