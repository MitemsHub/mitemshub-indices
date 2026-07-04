from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.domain import Direction, FeatureSnapshot, Regime, Tick, TradeSignal
from synthetic_trader.live.paper_runner import run_live_paper
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


class LivePaperRunnerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
