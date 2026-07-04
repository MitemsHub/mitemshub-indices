from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
