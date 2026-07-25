from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.live.paper_runner import LivePaperSummary
from synthetic_trader.monitoring.surface import build_validation_snapshot


class Phase15ValidationPayloadTests(unittest.TestCase):
    def test_build_validation_snapshot_combines_summary_and_latency(self) -> None:
        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=10,
            warmup_ticks=5,
            signals=2,
            approved_signals=1,
            rejected_signals=1,
            closed_trades=1,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1002.5,
            model_version="unit-test",
        )

        snapshot = build_validation_snapshot(
            venue="deriv",
            mode="dry-run-live",
            live_summary=summary,
            latency_summary={"total_duration_ms": 2.5},
        )

        self.assertEqual(snapshot["venue"], "deriv")
        self.assertEqual(snapshot["mode"], "dry-run-live")
        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertEqual(snapshot["final_equity"], 1002.5)
        self.assertEqual(snapshot["latency_total_ms"], 2.5)


class Phase15ValidationRenderingTests(unittest.TestCase):
    def test_render_validation_text_outputs_compact_summary(self) -> None:
        from synthetic_trader.monitoring.surface import render_validation_text

        rendered = render_validation_text(
            {
                "venue": "mt5",
                "mode": "dry-run-live",
                "symbol": "R_75",
                "finalized": True,
                "final_equity": 1001.5,
                "latency_total_ms": 2.0,
            }
        )

        self.assertIn("validation_venue=mt5", rendered)
        self.assertIn("validation_mode=dry-run-live", rendered)
        self.assertIn("validation_final_equity=1001.5", rendered)
        self.assertIn("validation_latency_total_ms=2.0", rendered)


class Phase15ValidationArtifactTests(unittest.TestCase):
    def test_dump_json_file_writes_validation_snapshot(self) -> None:
        from synthetic_trader.reporting.serializers import dump_json_file

        snapshot = {
            "venue": "deriv",
            "mode": "dry-run-live",
            "symbol": "R_75",
            "finalized": True,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "validation.json"
            dump_json_file(path, snapshot)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(written["venue"], "deriv")
        self.assertTrue(written["finalized"])


class Phase15ValidationCliTests(unittest.TestCase):
    def test_validate_system_prints_summary_and_writes_artifact(self) -> None:
        import contextlib
        import io
        from unittest.mock import AsyncMock, patch

        from synthetic_trader.cli import main

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=10,
            warmup_ticks=5,
            signals=2,
            approved_signals=1,
            rejected_signals=1,
            closed_trades=1,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1002.5,
            model_version="unit-test",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "validation.json"
            output = io.StringIO()
            live_runner = AsyncMock(return_value=summary)
            with patch("synthetic_trader.cli.run_live_paper", new=live_runner):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    try:
                        exit_code = main(
                            [
                                "validate-system",
                                "--symbol",
                                "R_75",
                                "--artifact-output",
                                str(artifact_path),
                            ]
                        )
                    except SystemExit as exc:
                        exit_code = exc.code

            artifact = (
                json.loads(artifact_path.read_text(encoding="utf-8"))
                if artifact_path.exists()
                else None
            )

        self.assertEqual(exit_code, 0)
        live_runner.assert_awaited_once_with(symbol="R_75", duration_sec=0, max_live_ticks=0)
        self.assertIsNotNone(artifact)
        self.assertIn("validation_symbol=R_75", output.getvalue())
        self.assertEqual(artifact["symbol"], "R_75")


if __name__ == "__main__":
    unittest.main()
