from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from synthetic_trader.config import LiveMode, Mt5Config, Venue
from synthetic_trader.execution.mt5 import Mt5OrderRequest, Mt5OrderResult, Mt5RuntimeStatus
from synthetic_trader.live.supervised_live import build_live_readiness_report


class Phase6Mt5TypesTests(unittest.TestCase):
    def test_order_request_exposes_resolved_symbol_and_volume(self) -> None:
        request = Mt5OrderRequest(
            symbol="R_75",
            venue_symbol="Volatility 75 Index",
            volume=0.2,
            order_type="BUY",
            stop_loss=99.5,
            take_profit=101.0,
            comment="phase6-test",
        )

        self.assertEqual(request.venue_symbol, "Volatility 75 Index")
        self.assertEqual(request.volume, 0.2)

    def test_order_result_tracks_acceptance_and_ticket(self) -> None:
        result = Mt5OrderResult(
            accepted=True,
            order_ticket=123456,
            deal_ticket=654321,
            retcode=10009,
            message="placed",
            venue_symbol="Volatility 75 Index",
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 123456)


class Phase6Mt5RuntimeTests(unittest.TestCase):
    def test_runtime_fails_when_symbol_is_not_selectable(self) -> None:
        from synthetic_trader.execution.mt5 import evaluate_mt5_runtime

        class FakeModule:
            def initialize(self, path=None):
                return True

            def login(self, login, password=None, server=None):
                return True

            def symbol_info(self, symbol):
                return None

            def shutdown(self):
                return True

        status = evaluate_mt5_runtime(
            config=Mt5Config(
                server="Broker-Demo",
                login="123456",
                password="secret",
                symbol_map={"R_75": "Volatility 75 Index"},
            ),
            symbol="R_75",
            mt5_module=FakeModule(),
        )

        self.assertFalse(status.ready)
        self.assertIn("mt5_symbol_unavailable", status.failures)

    def test_mt5_readiness_includes_runtime_failures(self) -> None:
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

        report = build_live_readiness_report(
            venue=Venue.MT5,
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_75",
            app_id=None,
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
            mt5_config=Mt5Config(
                server="Broker-Demo",
                login="123456",
                password="secret",
                symbol_map={"R_75": "Volatility 75 Index"},
            ),
            mt5_dependency_ready=True,
            mt5_runtime_status=Mt5RuntimeStatus(
                ready=False,
                failures=("mt5_symbol_unavailable",),
                venue_symbol="Volatility 75 Index",
            ),
        )

        self.assertFalse(report.ready)
        self.assertIn("mt5_symbol_unavailable", report.failures)


class Phase6Mt5OrderPlacementTests(unittest.TestCase):
    def test_place_mt5_order_returns_structured_acceptance(self) -> None:
        from synthetic_trader.execution.mt5 import place_mt5_order

        class FakeResult:
            retcode = 10009
            order = 111
            deal = 222
            comment = "Request executed"

        class FakeModule:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_BUY = 0
            ORDER_TIME_GTC = 0
            ORDER_FILLING_FOK = 0

            def order_send(self, payload):
                return FakeResult()

        result = place_mt5_order(
            request=Mt5OrderRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                volume=0.2,
                order_type="BUY",
            ),
            mt5_module=FakeModule(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order_ticket, 111)

    def test_execute_supervised_mt5_order_places_order_when_armed(self) -> None:
        from synthetic_trader.live.supervised_live import execute_supervised_mt5_order

        class FakeResult:
            retcode = 10009
            order = 333
            deal = 444
            comment = "Request executed"

        class FakeModule:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_BUY = 0
            ORDER_TIME_GTC = 0
            ORDER_FILLING_FOK = 0

            def order_send(self, payload):
                return FakeResult()

        result = execute_supervised_mt5_order(
            mode=LiveMode.ARMED_LIVE,
            readiness_ok=True,
            request=Mt5OrderRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                volume=0.2,
                order_type="BUY",
            ),
            mt5_module=FakeModule(),
        )

        self.assertIsInstance(result, Mt5OrderResult)
        self.assertEqual(result.order_ticket, 333)


class Phase6CliMt5LiveTests(unittest.TestCase):
    def test_mt5_live_order_reports_runtime_failures(self) -> None:
        from synthetic_trader.cli import main

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
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("mt5_initialize_failed", output.getvalue())

    def test_mt5_live_order_prints_structured_success(self) -> None:
        from synthetic_trader.cli import main

        runtime_status = Mt5RuntimeStatus(
            ready=True,
            failures=(),
            venue_symbol="Volatility 75 Index",
        )
        order_result = Mt5OrderResult(
            accepted=True,
            order_ticket=111,
            deal_ticket=222,
            retcode=10009,
            message="Request executed",
            venue_symbol="Volatility 75 Index",
        )

        output = io.StringIO()
        with patch("synthetic_trader.cli.mt5_dependency_available", return_value=True):
            with patch("synthetic_trader.cli.evaluate_mt5_runtime", return_value=runtime_status):
                with patch("synthetic_trader.cli._load_mt5_module", return_value=object()):
                    with patch("synthetic_trader.cli.execute_supervised_mt5_order", return_value=order_result):
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
                                ]
                            )

        self.assertEqual(exit_code, 0)
        self.assertIn("order_ticket=111", output.getvalue())


if __name__ == "__main__":
    unittest.main()
