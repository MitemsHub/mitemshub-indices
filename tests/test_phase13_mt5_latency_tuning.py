from __future__ import annotations

import unittest

from synthetic_trader.config import Mt5Config
from synthetic_trader.domain import Direction
from synthetic_trader.execution.mt5 import (
    Mt5CloseRequest,
    Mt5ModifyRequest,
    build_mt5_credentials,
    close_mt5_position,
    evaluate_mt5_runtime,
    modify_mt5_position,
)


class Phase13Mt5ContractTests(unittest.TestCase):
    def test_build_mt5_credentials_preserves_symbol_map(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        credentials = build_mt5_credentials(config)

        self.assertEqual(credentials.server, "Broker-Demo")
        self.assertEqual(credentials.symbol_map["R_75"], "Volatility 75 Index")

    def test_evaluate_mt5_runtime_keeps_venue_symbol_resolution(self) -> None:
        class FakeMt5:
            def __init__(self) -> None:
                self.initialized_paths: list[str | None] = []
                self.login_attempts: list[tuple[int, str | None, str | None]] = []
                self.symbol_info_requests: list[str] = []
                self.shutdown_calls = 0

            def initialize(self, path=None):
                self.initialized_paths.append(path)
                return True

            def login(self, login, password=None, server=None):
                self.login_attempts.append((login, password, server))
                return True

            def symbol_info(self, symbol):
                self.symbol_info_requests.append(symbol)
                return object()

            def shutdown(self):
                self.shutdown_calls += 1
                return None

        module = FakeMt5()
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        status = evaluate_mt5_runtime(
            config=config,
            symbol="R_75",
            mt5_module=module,
        )

        self.assertTrue(status.ready)
        self.assertEqual(status.venue_symbol, "Volatility 75 Index")
        self.assertEqual(module.initialized_paths, ["terminal.exe"])
        self.assertEqual(
            module.login_attempts,
            [(123456, "secret", "Broker-Demo")],
        )
        self.assertEqual(module.symbol_info_requests, ["Volatility 75 Index"])
        self.assertEqual(module.shutdown_calls, 1)


class Phase13Mt5RuntimePreparationTests(unittest.TestCase):
    def test_build_mt5_credentials_returns_reusable_frozen_credentials(self) -> None:
        config = Mt5Config(
            server="Broker-Demo",
            login="123456",
            password="secret",
            terminal_path="terminal.exe",
            symbol_map={"R_75": "Volatility 75 Index"},
        )

        first = build_mt5_credentials(config)
        second = build_mt5_credentials(config)

        self.assertEqual(first, second)
        self.assertIsNot(first, second)


class Phase13Mt5LifecycleSafetyTests(unittest.TestCase):
    def test_close_mt5_position_keeps_ticket_and_symbol_fields(self) -> None:
        class FakeMt5:
            TRADE_ACTION_DEAL = 1
            ORDER_TYPE_SELL = 2
            ORDER_TIME_GTC = 3
            ORDER_FILLING_FOK = 4

            def __init__(self) -> None:
                self.request = None

            def order_send(self, request):
                class Result:
                    retcode = 10009
                    order = 500
                    deal = 600
                    comment = "ok"

                self.request = request
                return Result()

        module = FakeMt5()

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
        self.assertEqual(result.venue_symbol, "Volatility 75 Index")
        self.assertEqual(module.request["symbol"], "Volatility 75 Index")
        self.assertEqual(module.request["position"], 101)

    def test_modify_mt5_position_keeps_ticket_and_symbol_fields(self) -> None:
        class FakeMt5:
            TRADE_ACTION_SLTP = 1

            def __init__(self) -> None:
                self.request = None

            def order_send(self, request):
                class Result:
                    retcode = 10009
                    order = 700
                    deal = 800
                    comment = "ok"

                self.request = request
                return Result()

        module = FakeMt5()

        result = modify_mt5_position(
            request=Mt5ModifyRequest(
                symbol="R_75",
                venue_symbol="Volatility 75 Index",
                ticket=101,
                stop_loss=99.5,
                take_profit=101.5,
            ),
            mt5_module=module,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.venue_symbol, "Volatility 75 Index")
        self.assertEqual(module.request["symbol"], "Volatility 75 Index")
        self.assertEqual(module.request["position"], 101)


class Phase13Mt5LatencyCliTests(unittest.TestCase):
    def test_mt5_commands_do_not_emit_latency_output_without_opt_in(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        from synthetic_trader.cli import main
        from synthetic_trader.execution.mt5 import Mt5RuntimeStatus

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
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "mt5-live-order",
                            "--symbol",
                            "R_75",
                            "--live-mode",
                            "dry-run-live",
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
        self.assertNotIn("latency_total_ms=", output.getvalue())


if __name__ == "__main__":
    unittest.main()
