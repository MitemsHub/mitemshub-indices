from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from synthetic_trader.execution.deriv_ws import DerivCredentials, DerivWebSocketClient


class Phase14DerivContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticks_history_preserves_requested_symbol(self) -> None:
        class RecordingDerivClient(DerivWebSocketClient):
            def __init__(self) -> None:
                super().__init__(DerivCredentials(app_id="test-app"))
                self.requests: list[dict[str, object]] = []

            async def request(self, payload: dict[str, object]) -> dict[str, object]:
                self.requests.append(payload)
                return {
                    "history": {
                        "prices": [100.0, 101.0],
                        "times": [1, 2],
                    }
                }

        client = RecordingDerivClient()

        await client.ticks_history("R_75", count=2)

        # _deriv_api_symbol maps R_75 -> 1HZ75V for Deriv WebSocket API
        self.assertEqual(client.requests[0]["ticks_history"], "1HZ75V")
        self.assertEqual(client.requests[0]["count"], 2)


class Phase14DerivTransportPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticks_history_keeps_request_shape_stable_across_repeated_calls(self) -> None:
        class RecordingDerivClient(DerivWebSocketClient):
            def __init__(self) -> None:
                super().__init__(DerivCredentials(app_id="test-app"))
                self.requests: list[dict[str, object]] = []

            async def request(self, payload: dict[str, object]) -> dict[str, object]:
                self.requests.append(payload)
                return {
                    "history": {
                        "prices": [100.0],
                        "times": [1],
                    }
                }

        client = RecordingDerivClient()

        first = await client.ticks_history("R_75", count=1)
        second = await client.ticks_history("R_75", count=1)

        self.assertEqual(first, second)
        # _deriv_api_symbol maps R_75 -> 1HZ75V for Deriv WebSocket API
        self.assertEqual(
            client.requests,
            [
                {
                    "ticks_history": "1HZ75V",
                    "count": 1,
                    "end": "latest",
                    "style": "ticks",
                },
                {
                    "ticks_history": "1HZ75V",
                    "count": 1,
                    "end": "latest",
                    "style": "ticks",
                },
            ],
        )


class Phase14DerivLiveSafetyTests(unittest.TestCase):
    def test_deriv_stage_classification_keeps_execution_boundaries_critical(self) -> None:
        from synthetic_trader.live.paper_runner import classify_latency_stage

        self.assertEqual(classify_latency_stage("signal_decision"), "critical")
        self.assertEqual(classify_latency_stage("journal_append"), "side_effect")


class Phase14DerivLatencyCliTests(unittest.TestCase):
    def test_paper_live_deriv_path_does_not_emit_latency_without_opt_in(self) -> None:
        from synthetic_trader.cli import main
        from synthetic_trader.live.paper_runner import LivePaperSummary

        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=1,
            warmup_ticks=1,
            signals=0,
            approved_signals=0,
            rejected_signals=0,
            closed_trades=0,
            shutdown_closed_trades=0,
            open_positions_before_shutdown=0,
            unresolved_positions=0,
            finalized=True,
            session_resets=0,
            final_equity=1000.0,
            model_version="unit-test",
        )

        output = io.StringIO()
        with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
            with contextlib.redirect_stdout(output):
                exit_code = main(["paper-live", "--symbol", "R_75"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("latency_total_ms=", output.getvalue())


if __name__ == "__main__":
    unittest.main()
