from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.cli import main
from synthetic_trader.monitoring.surface import build_monitor_snapshot, render_monitor_text


class Phase3MonitoringTests(unittest.TestCase):
    def test_build_monitor_snapshot_includes_core_live_fields(self) -> None:
        snapshot = build_monitor_snapshot(
            live_summary={
                "symbol": "R_75",
                "signals": 5,
                "approved_signals": 2,
                "rejected_signals": 3,
                "session_resets": 1,
                "shutdown_closed_trades": 1,
            }
        )

        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertEqual(snapshot["signals"], 5)
        self.assertEqual(snapshot["session_resets"], 1)

    def test_render_monitor_text_renders_snapshot_as_lines(self) -> None:
        rendered = render_monitor_text(
            {
                "symbol": "R_75",
                "signals": 5,
                "approved_signals": 2,
            }
        )

        self.assertEqual(
            rendered,
            "symbol=R_75\n"
            "signals=5\n"
            "approved_signals=2",
        )

    def test_monitor_live_command_renders_snapshot_from_summary_json(self) -> None:
        live_summary = {
            "symbol": "R_75",
            "signals": 5,
            "approved_signals": 2,
            "rejected_signals": 3,
            "session_resets": 1,
            "shutdown_closed_trades": 1,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "live_summary.json"
            summary_path.write_text(json.dumps(live_summary), encoding="utf-8")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["monitor-live", "--summary-json", str(summary_path)])

        expected = render_monitor_text(build_monitor_snapshot(live_summary=live_summary))
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), expected)

    def test_monitor_live_command_uses_monitoring_surface_helpers(self) -> None:
        live_summary = {"symbol": "R_75", "signals": 5, "final_equity": 1002.5}

        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "live_summary.json"
            summary_path.write_text(json.dumps(live_summary), encoding="utf-8")

            with (
                patch("synthetic_trader.cli.build_monitor_snapshot", return_value={"symbol": "R_75"}) as build_snapshot,
                patch("synthetic_trader.cli.render_monitor_text", return_value="rendered-monitor") as render_snapshot,
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = main(["monitor-live", "--summary-json", str(summary_path)])

        self.assertEqual(exit_code, 0)
        build_snapshot.assert_called_once_with(live_summary=live_summary)
        render_snapshot.assert_called_once_with({"symbol": "R_75"})
        self.assertEqual(output.getvalue().strip(), "rendered-monitor")


if __name__ == "__main__":
    unittest.main()
