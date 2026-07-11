from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.config import LiveMode, Mt5Config
from synthetic_trader.execution.mt5 import (
    Mt5OrderResult,
    Mt5ReconcileResult,
    Mt5RuntimeStatus,
    Mt5SyncResult,
    reconcile_mt5_positions,
)
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.live.supervised_live import execute_supervised_mt5_modify


class Phase8Mt5ReconcileTests(unittest.TestCase):
    def test_reconcile_mt5_positions_marks_single_target_actionable(self) -> None:
        class FakePosition:
            ticket = 101
            symbol = "Volatility 75 Index"
            volume = 0.2
            price_open = 100.5
            price_current = 101.0
            time = 1700000000
            type = 0

        class FakeModule:
            POSITION_TYPE_BUY = 0

            def positions_get(self, symbol=None):
                return [FakePosition()]

        result = reconcile_mt5_positions(
            config=Mt5Config(symbol_map={"R_75": "Volatility 75 Index"}),
            symbol="R_75",
            ticket=None,
            mt5_module=FakeModule(),
        )

        self.assertIsInstance(result, Mt5ReconcileResult)
        self.assertTrue(result.actionable)
        self.assertEqual(result.target_ticket, 101)


class Phase8Mt5ModifyTests(unittest.TestCase):
    def test_modify_mt5_position_returns_structured_result(self) -> None:
        from synthetic_trader.execution.mt5 import Mt5ModifyRequest, modify_mt5_position

        class FakeResult:
            retcode = 10009
            order = 901
            deal = 902
            comment = "modify executed"

        class FakeModule:
            TRADE_ACTION_SLTP = 2

            def order_send(self, payload):
                self.payload = payload
                return FakeResult()

        module = FakeModule()
        result = modify_mt5_position(
            request=Mt5ModifyRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                stop_loss=99.5,
                take_profit=102.0,
            ),
            mt5_module=module,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 901)
        self.assertEqual(module.payload["position"], 101)
        self.assertEqual(module.payload["sl"], 99.5)
        self.assertEqual(module.payload["tp"], 102.0)

    def test_execute_supervised_mt5_modify_returns_modify_result_when_armed(self) -> None:
        class FakeResult:
            retcode = 10009
            order = 903
            deal = 904
            comment = "modify executed"

        class FakeModule:
            TRADE_ACTION_SLTP = 2

            def order_send(self, payload):
                self.payload = payload
                return FakeResult()

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
                    type(
                        "Snapshot",
                        (),
                        {
                            "symbol": "R_75",
                            "venue_symbol": "Volatility 75 Index",
                            "ticket": 101,
                        },
                    )(),
                ),
            ),
        )

        module = FakeModule()
        result = execute_supervised_mt5_modify(
            mode=LiveMode.ARMED_LIVE,
            readiness_ok=True,
            reconcile_result=reconcile_result,
            stop_loss=99.5,
            take_profit=102.0,
            mt5_module=module,
        )

        self.assertIsInstance(result, Mt5OrderResult)
        self.assertEqual(result.order_ticket, 903)
        self.assertEqual(module.payload["position"], 101)


class Phase8Mt5RefinementJournalTests(unittest.TestCase):
    def test_journal_records_reconcile_and_modify_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mt5_refinement.jsonl"
            journal = TradeJournal(path)

            journal.record_mt5_reconcile_summary(
                symbol="R_75",
                target_ticket=101,
                actionable=True,
                failures=(),
            )
            journal.record_mt5_modify_result(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                accepted=True,
                retcode=10009,
                message="modify executed",
            )

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_reconcile_summary")
        self.assertEqual(entries[1]["type"], "mt5_modify_result")


class Phase8CliRefinementTests(unittest.TestCase):
    def test_mt5_reconcile_command_prints_target_ticket(self) -> None:
        from synthetic_trader.cli import main

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
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn("target_ticket=101", output.getvalue())

    def test_mt5_modify_command_prints_structured_success(self) -> None:
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
                    type(
                        "Snapshot",
                        (),
                        {
                            "symbol": "R_75",
                            "venue_symbol": "Volatility 75 Index",
                            "ticket": 101,
                        },
                    )(),
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
                                    ]
                                )

        self.assertEqual(exit_code, 0)
        self.assertIn("modify_accepted=True", output.getvalue())
        self.assertIn("order_ticket=901", output.getvalue())


if __name__ == "__main__":
    unittest.main()
