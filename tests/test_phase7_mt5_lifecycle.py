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
    Mt5CloseRequest,
    Mt5OrderResult,
    Mt5PositionSnapshot,
    Mt5RuntimeStatus,
    Mt5SyncResult,
    close_mt5_position,
    synchronize_mt5_positions,
)
from synthetic_trader.domain import Direction
from synthetic_trader.live.supervised_live import execute_supervised_mt5_close


class Phase7Mt5SyncTests(unittest.TestCase):
    def test_synchronize_mt5_positions_returns_single_position_snapshot(self) -> None:
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

        result = synchronize_mt5_positions(
            config=Mt5Config(symbol_map={"R_75": "Volatility 75 Index"}),
            symbol="R_75",
            mt5_module=FakeModule(),
        )

        self.assertTrue(result.ready)
        self.assertIsInstance(result, Mt5SyncResult)
        self.assertEqual(len(result.positions), 1)
        self.assertIsInstance(result.positions[0], Mt5PositionSnapshot)
        self.assertEqual(result.positions[0].ticket, 101)


class Phase7Mt5CloseTests(unittest.TestCase):
    def test_close_mt5_position_returns_structured_result(self) -> None:
        class FakeResult:
            retcode = 10009
            order = 501
            deal = 601
            comment = "close executed"

        class FakeModule:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_BUY = 0
            ORDER_TYPE_SELL = 1
            ORDER_TIME_GTC = 0
            ORDER_FILLING_FOK = 0

            def order_send(self, payload):
                self.payload = payload
                return FakeResult()

        module = FakeModule()
        result = close_mt5_position(
            request=Mt5CloseRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                volume=0.2,
                direction=Direction.LONG,
            ),
            mt5_module=module,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 501)
        self.assertEqual(module.payload["position"], 101)
        self.assertEqual(module.payload["type"], module.ORDER_TYPE_SELL)

    def test_execute_supervised_mt5_close_returns_close_result_when_armed(self) -> None:
        class FakeResult:
            retcode = 10009
            order = 701
            deal = 801
            comment = "close executed"

        class FakeModule:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_BUY = 0
            ORDER_TYPE_SELL = 1
            ORDER_TIME_GTC = 0
            ORDER_FILLING_FOK = 0

            def order_send(self, payload):
                self.payload = payload
                return FakeResult()

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

        module = FakeModule()
        result = execute_supervised_mt5_close(
            mode=LiveMode.ARMED_LIVE,
            readiness_ok=True,
            sync_result=sync_result,
            ticket=None,
            mt5_module=module,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 701)
        self.assertEqual(module.payload["position"], 101)

    def test_mt5_close_refuses_ambiguous_positions(self) -> None:
        sync_result = Mt5SyncResult(
            ready=True,
            failures=(),
            venue_symbol="Volatility 75 Index",
            positions=(
                Mt5PositionSnapshot(
                    symbol="R_75",
                    venue_symbol="Volatility 75 Index",
                    ticket=1,
                    direction=Direction.LONG,
                    volume=0.2,
                    open_price=100.0,
                    current_price=101.0,
                    broker_time=1700000000,
                ),
                Mt5PositionSnapshot(
                    symbol="R_75",
                    venue_symbol="Volatility 75 Index",
                    ticket=2,
                    direction=Direction.LONG,
                    volume=0.2,
                    open_price=100.0,
                    current_price=101.0,
                    broker_time=1700000001,
                ),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            execute_supervised_mt5_close(
                mode=LiveMode.ARMED_LIVE,
                readiness_ok=True,
                sync_result=sync_result,
                ticket=None,
                mt5_module=object(),
            )

    def test_mt5_close_refuses_unknown_ticket_with_runtime_error(self) -> None:
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

        with self.assertRaisesRegex(RuntimeError, "unknown mt5 ticket"):
            execute_supervised_mt5_close(
                mode=LiveMode.ARMED_LIVE,
                readiness_ok=True,
                sync_result=sync_result,
                ticket=999,
                mt5_module=object(),
            )


class Phase7Mt5JournalTests(unittest.TestCase):
    def test_journal_records_mt5_sync_and_close_events(self) -> None:
        from synthetic_trader.journal.trade_journal import TradeJournal

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mt5_lifecycle.jsonl"
            journal = TradeJournal(path)

            journal.record_mt5_sync_summary(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                positions=1,
                failures=(),
            )
            journal.record_mt5_close_result(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                accepted=True,
                retcode=10009,
                message="close executed",
            )

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(entries[0]["type"], "mt5_sync_summary")
        self.assertEqual(entries[0]["symbol"], "R_75")
        self.assertEqual(entries[0]["venue_symbol"], "Volatility 75 Index")
        self.assertEqual(entries[0]["positions"], 1)
        self.assertEqual(entries[0]["failures"], [])
        self.assertEqual(entries[1]["type"], "mt5_close_result")
        self.assertEqual(entries[1]["ticket"], 101)
        self.assertTrue(entries[1]["accepted"])
        self.assertEqual(entries[1]["retcode"], 10009)
        self.assertEqual(entries[1]["message"], "close executed")


class Phase7CliLifecycleTests(unittest.TestCase):
    def test_mt5_sync_command_prints_position_count(self) -> None:
        from synthetic_trader.cli import main

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
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn("positions=0", output.getvalue())

    def test_mt5_close_command_prints_structured_success(self) -> None:
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
                                    ]
                                )

        self.assertEqual(exit_code, 0)
        self.assertIn("close_accepted=True", output.getvalue())
        self.assertIn("order_ticket=501", output.getvalue())


if __name__ == "__main__":
    unittest.main()
