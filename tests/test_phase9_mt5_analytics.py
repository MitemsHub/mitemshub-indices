from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.execution.mt5 import (
    Mt5OrderResult,
    Mt5PositionSnapshot,
    Mt5ReconcileResult,
    Mt5RuntimeStatus,
    Mt5SyncResult,
)
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.domain import Direction


class Phase9Mt5JournalTests(unittest.TestCase):
    def test_journal_records_mt5_runtime_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mt5_runtime.jsonl"
            journal = TradeJournal(path)

            journal.record_mt5_runtime_summary(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ready=False,
                failures=("mt5_initialize_failed",),
            )

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_runtime_summary")
        self.assertEqual(entries[0]["symbol"], "R_75")
        self.assertEqual(entries[0]["venue_symbol"], "Volatility 75 Index")
        self.assertFalse(entries[0]["ready"])
        self.assertEqual(entries[0]["failures"], ["mt5_initialize_failed"])


class Phase9Mt5CommandAnalyticsTests(unittest.TestCase):
    def test_mt5_live_order_writes_runtime_summary_on_readiness_failure(self) -> None:
        from synthetic_trader.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_analytics.jsonl"
            output = io.StringIO()
            with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                with patch(
                    "synthetic_trader.cli.evaluate_mt5_runtime",
                    return_value=Mt5RuntimeStatus(
                        ready=False,
                        failures=("mt5_initialize_failed",),
                        venue_symbol="Volatility 75 Index",
                    ),
                ):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-live-order",
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
                                "--volume",
                                "0.2",
                                "--journal",
                                str(journal_path),
                            ]
                        )

            self.assertEqual(exit_code, 1)
            entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_runtime_summary")
        self.assertEqual(entries[0]["failures"], ["mt5_initialize_failed"])
        self.assertIn("mt5_command=mt5-live-order", output.getvalue())
        self.assertIn("mt5_readiness_ok=False", output.getvalue())

    def test_mt5_sync_writes_summary_event_and_normalized_output(self) -> None:
        from synthetic_trader.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_sync.jsonl"
            output = io.StringIO()
            with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                with patch(
                    "synthetic_trader.cli.synchronize_mt5_positions",
                    return_value=Mt5SyncResult(
                        ready=True,
                        failures=(),
                        venue_symbol="Volatility 75 Index",
                        positions=(),
                    ),
                ):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-sync",
                                "--symbol",
                                "R_75",
                                "--mt5-server",
                                "Broker-Demo",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 75 Index",
                                "--journal",
                                str(journal_path),
                            ]
                        )

            self.assertEqual(exit_code, 0)
            entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_sync_summary")
        self.assertEqual(entries[0]["positions"], 0)
        self.assertIn("mt5_command=mt5-sync", output.getvalue())
        self.assertIn("mt5_positions=0", output.getvalue())

    def test_mt5_reconcile_writes_summary_event_and_normalized_output(self) -> None:
        from synthetic_trader.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_reconcile.jsonl"
            output = io.StringIO()
            with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                with patch(
                    "synthetic_trader.cli.reconcile_mt5_positions",
                    return_value=Mt5ReconcileResult(
                        ready=True,
                        actionable=True,
                        failures=(),
                        target_ticket=101,
                        sync_result=Mt5SyncResult(
                            ready=True,
                            failures=(),
                            venue_symbol="Volatility 75 Index",
                            positions=(),
                        ),
                    ),
                ):
                    with contextlib.redirect_stdout(output):
                        exit_code = main(
                            [
                                "mt5-reconcile",
                                "--symbol",
                                "R_75",
                                "--mt5-server",
                                "Broker-Demo",
                                "--mt5-login",
                                "123456",
                                "--mt5-password",
                                "secret",
                                "--mt5-symbol",
                                "Volatility 75 Index",
                                "--journal",
                                str(journal_path),
                            ]
                        )

            self.assertEqual(exit_code, 0)
            entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_reconcile_summary")
        self.assertTrue(entries[0]["actionable"])
        self.assertEqual(entries[0]["target_ticket"], 101)
        self.assertIn("mt5_command=mt5-reconcile", output.getvalue())
        self.assertIn("mt5_actionable=True", output.getvalue())

    def test_mt5_close_writes_runtime_sync_and_result_events(self) -> None:
        from synthetic_trader.cli import main

        sync_result = Mt5SyncResult(
            ready=True,
            failures=(),
            venue_symbol="Volatility 75 Index",
            positions=(
                Mt5PositionSnapshot(
                    symbol="R_75",
                    venue_symbol="Volatility 75 Index",
                    ticket=101,
                    direction=Direction.LONG,
                    volume=0.2,
                    open_price=100.5,
                    current_price=101.0,
                    broker_time=1700000000,
                ),
            ),
        )
        close_result = Mt5OrderResult(
            accepted=True,
            order_ticket=501,
            deal_ticket=601,
            retcode=10009,
            message="close executed",
            venue_symbol="Volatility 75 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_close.jsonl"
            output = io.StringIO()
            with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                with patch(
                    "synthetic_trader.cli.evaluate_mt5_runtime",
                    return_value=Mt5RuntimeStatus(
                        ready=True,
                        failures=(),
                        venue_symbol="Volatility 75 Index",
                    ),
                ):
                    with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                        with patch(
                            "synthetic_trader.cli.synchronize_mt5_positions",
                            return_value=sync_result,
                        ):
                            with patch(
                                "synthetic_trader.cli.execute_supervised_mt5_close",
                                return_value=close_result,
                            ):
                                with contextlib.redirect_stdout(output):
                                    exit_code = main(
                                        [
                                            "mt5-close",
                                            "--symbol",
                                            "R_75",
                                            "--live-mode",
                                            "armed-live",
                                            "--armed-live",
                                            "--ticket",
                                            "101",
                                            "--mt5-server",
                                            "Broker-Demo",
                                            "--mt5-login",
                                            "123456",
                                            "--mt5-password",
                                            "secret",
                                            "--mt5-symbol",
                                            "Volatility 75 Index",
                                            "--journal",
                                            str(journal_path),
                                        ]
                                    )

            self.assertEqual(exit_code, 0)
            entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([entry["type"] for entry in entries], ["mt5_runtime_summary", "mt5_sync_summary", "mt5_close_result"])
        self.assertEqual(entries[2]["ticket"], 101)
        self.assertTrue(entries[2]["accepted"])
        self.assertIn("mt5_command=mt5-close", output.getvalue())
        self.assertIn("mt5_close_accepted=True", output.getvalue())

    def test_mt5_modify_writes_runtime_reconcile_and_result_events(self) -> None:
        from synthetic_trader.cli import main

        reconcile_result = Mt5ReconcileResult(
            ready=True,
            actionable=True,
            failures=(),
            target_ticket=101,
            sync_result=Mt5SyncResult(
                ready=True,
                failures=(),
                venue_symbol="Volatility 75 Index",
                positions=(
                    Mt5PositionSnapshot(
                        symbol="R_75",
                        venue_symbol="Volatility 75 Index",
                        ticket=101,
                        direction=Direction.LONG,
                        volume=0.2,
                        open_price=100.5,
                        current_price=101.0,
                        broker_time=1700000000,
                    ),
                ),
            ),
        )
        modify_result = Mt5OrderResult(
            accepted=True,
            order_ticket=901,
            deal_ticket=902,
            retcode=10009,
            message="modify executed",
            venue_symbol="Volatility 75 Index",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "mt5_modify.jsonl"
            output = io.StringIO()
            with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
                with patch(
                    "synthetic_trader.cli.evaluate_mt5_runtime",
                    return_value=Mt5RuntimeStatus(
                        ready=True,
                        failures=(),
                        venue_symbol="Volatility 75 Index",
                    ),
                ):
                    with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                        with patch(
                            "synthetic_trader.cli.reconcile_mt5_positions",
                            return_value=reconcile_result,
                        ):
                            with patch(
                                "synthetic_trader.cli.execute_supervised_mt5_modify",
                                return_value=modify_result,
                            ):
                                with contextlib.redirect_stdout(output):
                                    exit_code = main(
                                        [
                                            "mt5-modify",
                                            "--symbol",
                                            "R_75",
                                            "--live-mode",
                                            "armed-live",
                                            "--armed-live",
                                            "--ticket",
                                            "101",
                                            "--stop-loss",
                                            "99.5",
                                            "--take-profit",
                                            "102.0",
                                            "--mt5-server",
                                            "Broker-Demo",
                                            "--mt5-login",
                                            "123456",
                                            "--mt5-password",
                                            "secret",
                                            "--mt5-symbol",
                                            "Volatility 75 Index",
                                            "--journal",
                                            str(journal_path),
                                        ]
                                    )

            self.assertEqual(exit_code, 0)
            entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(
            [entry["type"] for entry in entries],
            ["mt5_runtime_summary", "mt5_reconcile_summary", "mt5_modify_result"],
        )
        self.assertEqual(entries[2]["ticket"], 101)
        self.assertTrue(entries[2]["accepted"])
        self.assertIn("mt5_command=mt5-modify", output.getvalue())
        self.assertIn("mt5_modify_accepted=True", output.getvalue())


if __name__ == "__main__":
    unittest.main()
