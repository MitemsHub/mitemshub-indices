from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from synthetic_trader.cli import main
from synthetic_trader.config import LiveMode, Venue
from synthetic_trader.domain import Direction, FeatureSnapshot, Regime, Tick, TradeSignal
from synthetic_trader.live.paper_runner import LivePaperSummary, run_live_paper
from synthetic_trader.live.supervised_live import LiveReadinessReport
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.strategy.decision_engine import DecisionReport


class _FakeClient:
    def __init__(self, warmup: list[Tick], live_ticks: list[Tick]) -> None:
        self._warmup = warmup
        self._live_ticks = live_ticks

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def ticks_history(self, symbol: str, count: int) -> list[Tick]:
        return list(self._warmup)

    async def subscribe_ticks(self, symbol: str, timeout: float = 20.0):
        # matches the MarketDataClient protocol (run_live_paper passes the
        # remaining run duration as the stream timeout)
        del symbol, timeout
        for tick in self._live_ticks:
            yield tick


class _FakeDecisionEngine:
    def __init__(self, config, model) -> None:
        self._signal_emitted = False

    def evaluate(self, symbol: str, candles, higher_timeframe_candles=None) -> DecisionReport:
        if self._signal_emitted:
            return DecisionReport(signal=None, reasons=("signal already emitted",))
        self._signal_emitted = True
        primary = candles[-1]
        signal = TradeSignal(
            symbol=symbol,
            direction=Direction.LONG,
            confidence=0.7,
            min_confidence=0.58,
            entry=primary.close,
            stop_loss=primary.close - 1.0,
            take_profit=primary.close + 2.0,
            horizon_sec=600,
            snapshot=FeatureSnapshot(
                symbol=symbol,
                epoch=primary.open_time + primary.timeframe_sec,
                timeframe_sec=primary.timeframe_sec,
                features={"atr_14": 1.0},
                regime=Regime.RANGE,
                structure={"bias": 0.0},
            ),
            rationale=("unit-test",),
            model_version="unit-test",
        )
        return DecisionReport(signal=signal, reasons=("unit-test signal",))


def _journal_entries(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class LivePaperRunnerTests(unittest.TestCase):
    def test_run_live_paper_uses_simulated_backend_for_dry_run_mt5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("synthetic_trader.live.paper_runner.build_execution_backend") as backend_builder:
                backend = Mock()
                backend.open_positions_count.return_value = 0
                backend.on_candle.return_value = []
                backend.shutdown.return_value = Mock(
                    outcomes=(),
                    open_positions_before_shutdown=0,
                    unresolved_positions=0,
                    finalized=True,
                )
                backend_builder.return_value = backend

                asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=0,
                        warmup_count=0,
                        venue=Venue.MT5,
                        live_mode=LiveMode.DRY_RUN_LIVE,
                        journal_path=Path(tmpdir) / "live_paper.jsonl",
                        client_factory=lambda: _FakeClient([], []),
                    )
                )

        backend_builder.assert_called_once()
        self.assertIs(backend_builder.call_args.kwargs["live_mode"], LiveMode.DRY_RUN_LIVE)

    def test_run_live_paper_uses_mt5_backend_for_armed_mt5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("synthetic_trader.live.paper_runner.build_execution_backend") as backend_builder:
                backend = Mock()
                backend.open_positions_count.return_value = 0
                backend.on_candle.return_value = []
                backend.shutdown.return_value = Mock(
                    outcomes=(),
                    open_positions_before_shutdown=0,
                    unresolved_positions=0,
                    finalized=True,
                )
                backend_builder.return_value = backend

                asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=0,
                        warmup_count=0,
                        venue=Venue.MT5,
                        live_mode=LiveMode.ARMED_LIVE,
                        journal_path=Path(tmpdir) / "live_paper.jsonl",
                        client_factory=lambda: _FakeClient([], []),
                    )
                )

        backend_builder.assert_called_once()
        self.assertIs(backend_builder.call_args.kwargs["live_mode"], LiveMode.ARMED_LIVE)

    def test_paper_live_summary_prints_shutdown_fields(self) -> None:
        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=50,
            warmup_ticks=100,
            signals=4,
            approved_signals=2,
            rejected_signals=2,
            closed_trades=2,
            shutdown_closed_trades=1,
            open_positions_before_shutdown=1,
            unresolved_positions=0,
            finalized=True,
            session_resets=1,
            final_equity=1002.5,
            model_version="unit-test",
        )

        with patch("synthetic_trader.cli.run_live_paper", return_value=summary):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["paper-live", "--symbol", "R_75", "--duration-sec", "1"])

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("shutdown_closed_trades=1", rendered)
        self.assertIn("open_positions_before_shutdown=1", rendered)
        self.assertIn("unresolved_positions=0", rendered)
        self.assertIn("session_resets=1", rendered)
        self.assertIn("finalized=True", rendered)

    def test_run_live_paper_finalizes_open_positions_on_shutdown(self) -> None:
        warmup: list[Tick] = []
        live_ticks = [
            Tick(symbol="R_75", epoch=1, price=100.0),
            Tick(symbol="R_75", epoch=20, price=100.1),
            Tick(symbol="R_75", epoch=40, price=100.0),
            Tick(symbol="R_75", epoch=59, price=100.4),
            Tick(symbol="R_75", epoch=61, price=100.45),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch(
                    "synthetic_trader.live.paper_runner.DerivWebSocketClient",
                    return_value=_FakeClient(warmup, live_ticks),
                ),
                patch(
                    "synthetic_trader.live.paper_runner.DecisionEngine",
                    _FakeDecisionEngine,
                ),
            ):
                summary = asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=len(live_ticks),
                        warmup_count=0,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=Path(tmpdir) / "live_paper.jsonl",
                    )
                )

        self.assertEqual(summary.live_ticks, len(live_ticks))
        self.assertEqual(summary.closed_trades, 1)
        self.assertEqual(summary.shutdown_closed_trades, 1)
        self.assertEqual(summary.open_positions_before_shutdown, 1)
        self.assertEqual(summary.unresolved_positions, 0)
        self.assertTrue(summary.finalized)

    def test_run_live_paper_records_shutdown_events(self) -> None:
        warmup: list[Tick] = []
        live_ticks = [
            Tick(symbol="R_75", epoch=1, price=100.0),
            Tick(symbol="R_75", epoch=20, price=100.1),
            Tick(symbol="R_75", epoch=40, price=100.0),
            Tick(symbol="R_75", epoch=59, price=100.4),
            Tick(symbol="R_75", epoch=61, price=100.45),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "live_paper.jsonl"
            with (
                patch(
                    "synthetic_trader.live.paper_runner.DerivWebSocketClient",
                    return_value=_FakeClient(warmup, live_ticks),
                ),
                patch(
                    "synthetic_trader.live.paper_runner.DecisionEngine",
                    _FakeDecisionEngine,
                ),
            ):
                summary = asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=len(live_ticks),
                        warmup_count=0,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=journal_path,
                    )
                )

            entries = _journal_entries(journal_path)

        forced_close_events = [entry for entry in entries if entry["type"] == "shutdown_forced_close"]
        summary_events = [entry for entry in entries if entry["type"] == "shutdown_summary"]
        self.assertEqual(len(forced_close_events), 1)
        self.assertEqual(forced_close_events[0]["symbol"], "R_75")
        self.assertEqual(forced_close_events[0]["epoch"], 120)
        self.assertEqual(len(summary_events), 1)
        self.assertEqual(summary_events[0]["symbol"], "R_75")
        self.assertEqual(summary_events[0]["live_ticks"], len(live_ticks))
        self.assertEqual(summary_events[0]["shutdown_closed_trades"], summary.shutdown_closed_trades)
        self.assertEqual(summary_events[0]["unresolved_positions"], summary.unresolved_positions)
        self.assertEqual(summary_events[0]["session_resets"], summary.session_resets)
        self.assertEqual(
            summary_events[0]["open_positions_before_shutdown"],
            summary.open_positions_before_shutdown,
        )
        self.assertEqual(summary_events[0]["finalized"], summary.finalized)
        self.assertEqual(summary_events[0]["final_equity"], summary.final_equity)

    def test_run_live_paper_reports_session_reset_when_ticks_cross_day_boundary(self) -> None:
        warmup: list[Tick] = []
        live_ticks = [
            Tick(symbol="R_75", epoch=86341, price=100.0),
            Tick(symbol="R_75", epoch=86360, price=100.1),
            Tick(symbol="R_75", epoch=86420, price=100.3),
            Tick(symbol="R_75", epoch=86459, price=100.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "synthetic_trader.live.paper_runner.DerivWebSocketClient",
                return_value=_FakeClient(warmup, live_ticks),
            ):
                summary = asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=len(live_ticks),
                        warmup_count=0,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=Path(tmpdir) / "live_paper.jsonl",
                    )
                )

        self.assertEqual(summary.session_resets, 1)

    def test_run_live_paper_records_session_reset_event(self) -> None:
        warmup: list[Tick] = []
        live_ticks = [
            Tick(symbol="R_75", epoch=86341, price=100.0),
            Tick(symbol="R_75", epoch=86360, price=100.1),
            Tick(symbol="R_75", epoch=86420, price=100.3),
            Tick(symbol="R_75", epoch=86459, price=100.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "live_paper.jsonl"
            with patch(
                "synthetic_trader.live.paper_runner.DerivWebSocketClient",
                return_value=_FakeClient(warmup, live_ticks),
            ):
                asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=len(live_ticks),
                        warmup_count=0,
                        timeframe_sec=60,
                        higher_timeframe_sec=300,
                        journal_path=journal_path,
                    )
                )

            entries = _journal_entries(journal_path)

        session_reset_events = [entry for entry in entries if entry["type"] == "session_reset"]
        summary_events = [entry for entry in entries if entry["type"] == "shutdown_summary"]
        self.assertEqual(len(session_reset_events), 1)
        self.assertEqual(session_reset_events[0]["symbol"], "R_75")
        self.assertEqual(session_reset_events[0]["session_day"], 1)
        self.assertEqual(session_reset_events[0]["epoch"], 86420)
        self.assertEqual(len(summary_events), 1)
        self.assertEqual(summary_events[0]["session_resets"], 1)

    def test_run_live_paper_uses_deriv_client_builder_by_default(self) -> None:
        warmup = [Tick(symbol="R_75", epoch=1, price=100.0)]

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_client = _FakeClient(warmup, [])
            with patch(
                "synthetic_trader.live.paper_runner._build_deriv_client",
                return_value=fake_client,
            ) as builder_mock:
                summary = asyncio.run(
                    run_live_paper(
                        symbol="R_75",
                        duration_sec=0,
                        max_live_ticks=0,
                        warmup_count=1,
                        venue=Venue.DERIV,
                        journal_path=Path(tmpdir) / "live_paper.jsonl",
                    )
                )

        self.assertEqual(summary.symbol, "R_75")
        self.assertEqual(summary.warmup_ticks, 1)
        builder_mock.assert_called_once_with(app_id=None, token=None)

    def test_run_live_paper_uses_provided_model_version(self) -> None:
        provided_model = OnlineLogisticModel(updates=4)

        with tempfile.TemporaryDirectory() as tmpdir:
            summary = asyncio.run(
                run_live_paper(
                    symbol="R_75",
                    duration_sec=0,
                    max_live_ticks=0,
                    warmup_count=0,
                    journal_path=Path(tmpdir) / "live_paper.jsonl",
                    client_factory=lambda: _FakeClient([], []),
                    model=provided_model,
                )
            )

        self.assertEqual(summary.model_version, "online-logistic-v1.4")

    def test_paper_live_loads_model_artifact_when_requested(self) -> None:
        summary = LivePaperSummary(
            symbol="R_75",
            live_ticks=0,
            warmup_ticks=0,
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
            model_version="online-logistic-v1.4",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "model.json"
            OnlineLogisticModel(updates=4).save(model_path)
            with patch("synthetic_trader.cli.run_live_paper", new=AsyncMock(return_value=summary)) as run_live_paper_mock:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "paper-live",
                            "--symbol",
                            "R_75",
                            "--duration-sec",
                            "0",
                            "--max-live-ticks",
                            "0",
                            "--model-load",
                            str(model_path),
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_live_paper_mock.call_args.kwargs["model"].updates, 4)

    def test_paper_live_passes_live_mode_to_runner(self) -> None:
        summary = LivePaperSummary(
            symbol="R_100",
            live_ticks=0,
            warmup_ticks=0,
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
            model_version="online-logistic-v1.0",
        )

        with patch("synthetic_trader.cli.run_live_paper", new=AsyncMock(return_value=summary)) as run_live_paper_mock:
            with patch(
                "synthetic_trader.cli.build_live_readiness_report",
                return_value=LiveReadinessReport(
                    mode=LiveMode.ARMED_LIVE,
                    ready=True,
                    failures=(),
                ),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = main(
                        [
                            "paper-live",
                            "--symbol",
                            "R_100",
                            "--venue",
                            "mt5",
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
                            "--duration-sec",
                            "0",
                            "--max-live-ticks",
                            "0",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIs(run_live_paper_mock.call_args.kwargs["live_mode"], LiveMode.ARMED_LIVE)


if __name__ == "__main__":
    unittest.main()
