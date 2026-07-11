from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.monitoring.surface import filter_mt5_events


class Phase10Mt5FilterTests(unittest.TestCase):
    def test_filter_mt5_events_keeps_only_mt5_event_types(self) -> None:
        events = [
            {"type": "signal", "symbol": "R_75"},
            {"type": "mt5_runtime_summary", "symbol": "R_75"},
            {"type": "mt5_sync_summary", "symbol": "R_75"},
            {"type": "outcome", "symbol": "R_75"},
        ]

        filtered = filter_mt5_events(events)

        self.assertEqual(
            [entry["type"] for entry in filtered],
            ["mt5_runtime_summary", "mt5_sync_summary"],
        )


class Phase10Mt5SnapshotTests(unittest.TestCase):
    def test_build_mt5_monitor_snapshot_aggregates_latest_known_state(self) -> None:
        from synthetic_trader.monitoring.surface import build_mt5_monitor_snapshot

        events = [
            {
                "type": "mt5_runtime_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ready": True,
                "failures": [],
            },
            {
                "type": "mt5_sync_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "positions": 1,
                "failures": [],
            },
            {
                "type": "mt5_reconcile_summary",
                "symbol": "R_75",
                "target_ticket": 101,
                "actionable": True,
                "failures": [],
            },
            {
                "type": "mt5_close_result",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ticket": 101,
                "accepted": True,
                "retcode": 10009,
                "message": "close executed",
            },
            {
                "type": "mt5_modify_result",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ticket": 101,
                "accepted": True,
                "retcode": 10009,
                "message": "modify executed",
            },
        ]

        snapshot = build_mt5_monitor_snapshot(events=events)

        self.assertEqual(snapshot["symbol"], "R_75")
        self.assertEqual(snapshot["venue_symbol"], "Volatility 75 Index")
        self.assertTrue(snapshot["runtime_ready"])
        self.assertEqual(snapshot["positions"], 1)
        self.assertTrue(snapshot["reconcile_actionable"])
        self.assertEqual(snapshot["reconcile_target_ticket"], 101)
        self.assertEqual(snapshot["last_close_ticket"], 101)
        self.assertTrue(snapshot["last_close_accepted"])
        self.assertEqual(snapshot["last_modify_message"], "modify executed")

    def test_build_mt5_monitor_snapshot_returns_safe_empty_defaults(self) -> None:
        from synthetic_trader.monitoring.surface import build_mt5_monitor_snapshot

        snapshot = build_mt5_monitor_snapshot(events=[])

        self.assertIsNone(snapshot["symbol"])
        self.assertIsNone(snapshot["venue_symbol"])
        self.assertFalse(snapshot["runtime_ready"])
        self.assertEqual(snapshot["runtime_failures"], [])
        self.assertEqual(snapshot["positions"], 0)
        self.assertFalse(snapshot["reconcile_actionable"])
        self.assertIsNone(snapshot["reconcile_target_ticket"])
        self.assertIsNone(snapshot["last_close_ticket"])
        self.assertFalse(snapshot["last_close_accepted"])
        self.assertEqual(snapshot["last_modify_message"], "")

    def test_build_mt5_monitor_snapshot_tracks_live_entry_and_fail_closed_events(self) -> None:
        from synthetic_trader.monitoring.surface import build_mt5_monitor_snapshot

        snapshot = build_mt5_monitor_snapshot(
            events=[
                {
                    "type": "mt5_live_entry_result",
                    "symbol": "R_100",
                    "venue_symbol": "Volatility 100 Index",
                    "accepted": True,
                    "retcode": 10009,
                    "message": "done",
                },
                {
                    "type": "mt5_live_fail_closed",
                    "symbol": "R_100",
                    "reason": "ambiguous_shutdown_state",
                },
            ],
            symbol="R_100",
        )

        self.assertEqual(snapshot["last_live_entry_accepted"], True)
        self.assertEqual(snapshot["last_fail_closed_reason"], "ambiguous_shutdown_state")


class Phase10Mt5RenderTests(unittest.TestCase):
    def test_render_mt5_monitor_text_prints_explicit_mt5_fields(self) -> None:
        from synthetic_trader.monitoring.surface import render_mt5_monitor_text

        snapshot = {
            "symbol": "R_75",
            "venue_symbol": "Volatility 75 Index",
            "runtime_ready": True,
            "runtime_failures": [],
            "positions": 1,
            "sync_failures": [],
            "reconcile_actionable": True,
            "reconcile_target_ticket": 101,
            "reconcile_failures": [],
            "last_close_ticket": 101,
            "last_close_accepted": True,
            "last_close_retcode": 10009,
            "last_close_message": "close executed",
            "last_modify_ticket": 101,
            "last_modify_accepted": True,
            "last_modify_retcode": 10009,
            "last_modify_message": "modify executed",
        }

        rendered = render_mt5_monitor_text(snapshot)

        self.assertIn("mt5_symbol=R_75", rendered)
        self.assertIn("mt5_runtime_ready=True", rendered)
        self.assertIn("mt5_positions=1", rendered)
        self.assertIn("mt5_reconcile_target_ticket=101", rendered)
        self.assertIn("mt5_last_modify_message=modify executed", rendered)


class Phase10Mt5CliMonitorTests(unittest.TestCase):
    def test_mt5_monitor_command_renders_latest_mt5_snapshot(self) -> None:
        from synthetic_trader.cli import main

        events = [
            {"type": "signal", "symbol": "R_75"},
            {
                "type": "mt5_runtime_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ready": True,
                "failures": [],
            },
            {
                "type": "mt5_sync_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "positions": 1,
                "failures": [],
            },
            {
                "type": "mt5_modify_result",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ticket": 101,
                "accepted": True,
                "retcode": 10009,
                "message": "modify executed",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_monitor.jsonl"
            journal_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "mt5-monitor",
                        "--journal",
                        str(journal_path),
                        "--symbol",
                        "R_75",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("mt5_symbol=R_75", output.getvalue())
        self.assertIn("mt5_positions=1", output.getvalue())
        self.assertIn("mt5_last_modify_message=modify executed", output.getvalue())

    def test_mt5_monitor_command_returns_non_zero_for_missing_journal(self) -> None:
        from synthetic_trader.cli import main

        missing_path = Path("does-not-exist.jsonl")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["mt5-monitor", "--journal", str(missing_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("error=", output.getvalue())


class Phase10Mt5CoexistenceTests(unittest.TestCase):
    def test_mt5_monitor_command_returns_empty_snapshot_when_symbol_has_no_mt5_events(self) -> None:
        from synthetic_trader.cli import main

        events = [
            {
                "type": "mt5_runtime_summary",
                "symbol": "R_75",
                "venue_symbol": "Volatility 75 Index",
                "ready": True,
                "failures": [],
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_empty.jsonl"
            journal_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "mt5-monitor",
                        "--journal",
                        str(journal_path),
                        "--symbol",
                        "R_100",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("mt5_symbol=None", output.getvalue())
        self.assertIn("mt5_positions=0", output.getvalue())

    def test_existing_paper_monitor_helpers_still_render_summary_text(self) -> None:
        from synthetic_trader.monitoring.surface import build_monitor_snapshot, render_monitor_text

        snapshot = build_monitor_snapshot(
            live_summary={
                "symbol": "R_75",
                "signals": 3,
                "approved_signals": 2,
                "rejected_signals": 1,
                "session_resets": 0,
                "shutdown_closed_trades": 0,
            }
        )

        rendered = render_monitor_text(snapshot)

        self.assertIn("symbol=R_75", rendered)
        self.assertIn("signals=3", rendered)


if __name__ == "__main__":
    unittest.main()
