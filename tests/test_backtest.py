from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.config import RiskConfig, TraderConfig
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.domain import Tick


def synthetic_ticks(symbol: str = "R_75", candles: int = 130) -> list[Tick]:
    ticks: list[Tick] = []
    price = 100.0
    for candle in range(candles):
        base_epoch = candle * 60
        for offset, delta in [(1, 0.00), (20, 0.10), (40, -0.04), (59, 0.32)]:
            ticks.append(Tick(symbol=symbol, epoch=base_epoch + offset, price=price + delta))
        price += 0.30
    return ticks


class BacktestTests(unittest.TestCase):
    def test_backtest_runs(self) -> None:
        result = BacktestEngine().run_ticks(synthetic_ticks(), symbol="R_75", timeframe_sec=60)

        self.assertGreaterEqual(result.signals, 1)
        self.assertGreaterEqual(result.metrics.trades, 0)
        self.assertGreater(result.final_equity, 0)

    def test_backtest_journals_skip_and_rejection_events(self) -> None:
        config = replace(TraderConfig.default(), risk=RiskConfig(max_consecutive_losses=0))

        with tempfile.TemporaryDirectory() as tmpdir:
            journal = TradeJournal(Path(tmpdir) / "journal.jsonl")
            result = BacktestEngine(config=config, journal=journal).run_ticks(
                synthetic_ticks(),
                symbol="R_75",
                timeframe_sec=60,
            )
            payloads = [
                json.loads(line)
                for line in journal.path.read_text(encoding="utf-8").splitlines()
            ]

        event_types = {payload["type"] for payload in payloads}

        self.assertGreater(result.rejected_signals, 0)
        self.assertIn("decision_skip", event_types)
        self.assertIn("rejection", event_types)


if __name__ == "__main__":
    unittest.main()
