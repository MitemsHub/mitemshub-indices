from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.cli import main
from synthetic_trader.domain import Direction, FeatureSnapshot, Regime, Tick, TradeSignal
from synthetic_trader.live.paper_runner import LivePaperSummary, run_live_paper
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

    async def subscribe_ticks(self, symbol: str):
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


if __name__ == "__main__":
    unittest.main()
