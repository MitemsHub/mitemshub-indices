from __future__ import annotations

import unittest

from synthetic_trader.monitoring.surface import build_rollout_status_snapshot


class Phase16RolloutSnapshotTests(unittest.TestCase):
    def test_build_rollout_status_snapshot_combines_readiness_validation_and_mt5_state(self) -> None:
        snapshot = build_rollout_status_snapshot(
            venue="mt5",
            symbol="R_75",
            live_mode="dry-run-live",
            readiness_ok=True,
            readiness_failures=(),
            validation_snapshot={
                "finalized": True,
                "final_equity": 1003.25,
                "model_version": "unit-test",
            },
            mt5_snapshot={
                "runtime_ready": True,
                "positions": 0,
                "sync_failures": [],
            },
        )

        self.assertEqual(snapshot["rollout_stage"], "dry-run-preflight")
        self.assertEqual(snapshot["venue"], "mt5")
        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertFalse(snapshot["armed_confirmation"])
        self.assertTrue(snapshot["readiness_ok"])
        self.assertTrue(snapshot["validation_finalized"])
        self.assertEqual(snapshot["validation_final_equity"], 1003.25)
        self.assertTrue(snapshot["mt5_runtime_ready"])
        self.assertEqual(snapshot["mt5_positions"], 0)

    def test_build_rollout_status_snapshot_prefers_direct_mt5_runtime_status(self) -> None:
        snapshot = build_rollout_status_snapshot(
            venue="mt5",
            symbol="R_100",
            live_mode="dry-run-live",
            readiness_ok=True,
            readiness_failures=(),
            mt5_runtime_ready=True,
            mt5_runtime_failures=(),
            mt5_venue_symbol="Volatility 100 Index",
            mt5_snapshot={},
        )

        self.assertTrue(snapshot["mt5_runtime_ready"])
        self.assertEqual(snapshot["mt5_runtime_failures"], [])
        self.assertEqual(snapshot["mt5_venue_symbol"], "Volatility 100 Index")


class Phase16RolloutRenderingTests(unittest.TestCase):
    def test_render_rollout_status_text_outputs_explicit_rollout_fields(self) -> None:
        from synthetic_trader.monitoring.surface import render_rollout_status_text

        rendered = render_rollout_status_text(
            {
                "rollout_stage": "dry-run-preflight",
                "venue": "mt5",
                "symbol": "R_75",
                "live_mode": "dry-run-live",
                "readiness_ok": True,
                "validation_finalized": True,
                "mt5_runtime_ready": True,
            }
        )

        self.assertIn("rollout_stage=dry-run-preflight", rendered)
        self.assertIn("rollout_venue=mt5", rendered)
        self.assertIn("rollout_symbol=R_75", rendered)
        self.assertIn("rollout_live_mode=dry-run-live", rendered)
        self.assertIn("rollout_readiness_ok=True", rendered)
        self.assertIn("rollout_mt5_runtime_ready=True", rendered)


class Phase16RolloutCliTests(unittest.TestCase):
    def test_mt5_rollout_check_prints_compact_preflight_summary(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            failures=(),
            venue_symbol="Volatility 75 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            validation_path = Path(tmpdir) / "validation.json"
            validation_path.write_text(
                json.dumps(
                    {
                        "venue": "mt5",
                        "mode": "dry-run-live",
                        "symbol": "R_75",
                        "finalized": True,
                        "final_equity": 1003.25,
                        "model_version": "unit-test",
                    }
                ),
                encoding="utf-8",
            )
            journal_path = Path(tmpdir) / "mt5.jsonl"
            journal_path.write_text(
                json.dumps(
                    {
                        "type": "mt5_sync_summary",
                        "symbol": "R_75",
                        "venue_symbol": "Volatility 75 Index",
                        "positions": 0,
                        "failures": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-rollout-check",
                                "--symbol",
                                "R_75",
                                "--live-mode",
                                "dry-run-live",
                                "--mt5-server",
                                "server",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 75 Index",
                                "--validation-json",
                                str(validation_path),
                                "--journal",
                                str(journal_path),
                            ]
                        )

        self.assertEqual(exit_code, 0)
        self.assertIn("rollout_stage=dry-run-preflight", output.getvalue())
        self.assertIn("rollout_symbol=R_75", output.getvalue())
        self.assertIn("rollout_validation_finalized=True", output.getvalue())
        self.assertIn("rollout_mt5_positions=0", output.getvalue())
        self.assertIn("rollout_mt5_runtime_ready=True", output.getvalue())

    def test_mt5_rollout_check_writes_snapshot_artifact(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            failures=(),
            venue_symbol="Volatility 100 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "rollout_preflight_r100.json"
            output = io.StringIO()
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-rollout-check",
                                "--symbol",
                                "R_100",
                                "--live-mode",
                                "dry-run-live",
                                "--mt5-server",
                                "server",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 100 Index",
                                "--artifact-output",
                                str(artifact_path),
                            ]
                        )

            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["symbol"], "R_100")
            self.assertEqual(payload["venue"], "mt5")
            self.assertTrue(payload["readiness_ok"])

    def test_mt5_rollout_check_armed_live_requires_confirmation(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            failures=(),
            venue_symbol="Volatility 100 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "rollout_armed_r100.json"
            output = io.StringIO()
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                    with contextlib.redirect_stdout(output):
                        # armed-live WITHOUT the consent flag: must record the
                        # missing_armed_confirmation failure and stay fail-closed.
                        exit_code = main(
                            [
                                "mt5-rollout-check",
                                "--symbol",
                                "R_100",
                                "--live-mode",
                                "armed-live",
                                "--mt5-server",
                                "server",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 100 Index",
                                "--artifact-output",
                                str(artifact_path),
                            ]
                        )

            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            # armed-live without consent must exit NONZERO (fail-closed) so a
            # wrapper script cannot proceed on a non-consenting artifact.
            self.assertEqual(exit_code, 1)
            self.assertFalse(payload["armed_confirmation"])
            self.assertFalse(payload["readiness_ok"])
            self.assertIn("missing_armed_confirmation", payload["readiness_failures"])
            self.assertIn("rollout_armed_confirmation=False", output.getvalue())
            self.assertIn("rollout_exit=1 fail_closed=armed-live-readiness-failed", output.getvalue())
            self.assertIn("missing_armed_confirmation", output.getvalue())

    def test_mt5_rollout_check_armed_live_fails_closed_on_runtime_not_ready(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        # Consent IS given, but the MT5 runtime itself is not ready — the
        # armed-live preflight must still fail closed (exit 1).
        runtime_status = Mt5RuntimeStatus(
            ready=False,
            failures=("terminal not connected",),
            venue_symbol="Volatility 100 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "rollout_armed_r100.json"
            output = io.StringIO()
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-rollout-check",
                                "--symbol",
                                "R_100",
                                "--live-mode",
                                "armed-live",
                                "--armed-live",
                                "--mt5-server",
                                "server",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 100 Index",
                                "--artifact-output",
                                str(artifact_path),
                            ]
                        )

            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 1)
            self.assertTrue(payload["armed_confirmation"])
            self.assertFalse(payload["readiness_ok"])
            self.assertIn("terminal not connected", payload["readiness_failures"])
            self.assertIn("rollout_exit=1 fail_closed=armed-live-readiness-failed", output.getvalue())

    def test_mt5_rollout_check_armed_live_records_confirmation(self) -> None:
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            failures=(),
            venue_symbol="Volatility 100 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "rollout_armed_r100.json"
            output = io.StringIO()
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                    with contextlib.redirect_stdout(output):
                        # armed-live WITH the explicit consent flag: the gate passes
                        # and the snapshot/artifact record the operator's consent.
                        exit_code = main(
                            [
                                "mt5-rollout-check",
                                "--symbol",
                                "R_100",
                                "--live-mode",
                                "armed-live",
                                "--armed-live",
                                "--mt5-server",
                                "server",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 100 Index",
                                "--artifact-output",
                                str(artifact_path),
                            ]
                        )

            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["armed_confirmation"])
            self.assertTrue(payload["readiness_ok"])
            self.assertEqual(payload["readiness_failures"], [])
            self.assertIn("rollout_armed_confirmation=True", output.getvalue())
            self.assertNotIn("missing_armed_confirmation", output.getvalue())


if __name__ == "__main__":
    unittest.main()
