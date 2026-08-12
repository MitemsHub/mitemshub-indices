from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from unittest import mock

from synthetic_trader.backtest import engine as backtest_engine
from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.config import RiskConfig, TraderConfig
from synthetic_trader.features import assembler
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.domain import Tick


def synthetic_ticks(symbol: str = "R_75", candles: int = 130) -> list[Tick]:
    ticks: list[Tick] = []
    price = 100.0
    for candle in range(candles):
        # 13:00 UTC base — inside the sniper entry-gate window (UTC [12,24))
        # so run_ticks-based tests emit signals instead of standing aside.
        base_epoch = 13 * 3600 + candle * 60
        for offset, delta in [(1, 0.00), (20, 0.10), (40, -0.04), (59, 0.32)]:
            ticks.append(Tick(symbol=symbol, epoch=base_epoch + offset, price=price + delta))
        price += 0.30
    return ticks


def random_walk_ticks(symbol: str = "R_75", candles: int = 300, seed: int = 7) -> list[Tick]:
    """Seeded random-walk ticks with a volatility regime shift, so the
    EGARCH / session / fingerprint caches accumulate meaningful statistical
    state (kurtosis, autocorrelation, session-hour stats) that a leaked
    warm-up would change."""
    import random

    rng = random.Random(seed)
    ticks: list[Tick] = []
    price = 100.0
    for candle in range(candles):
        # 13:00 UTC base — inside the sniper entry-gate window.
        base_epoch = 13 * 3600 + candle * 60
        # regime shift halfway: calmer first half, wilder second half
        sigma = 0.05 if candle < candles // 2 else 0.16
        for offset in (1, 20, 40, 59):
            price += rng.gauss(0.0, sigma)
            ticks.append(Tick(symbol=symbol, epoch=base_epoch + offset, price=max(price, 1.0)))
    return ticks


class BacktestTests(unittest.TestCase):
    def test_backtest_runs(self) -> None:
        result = BacktestEngine().run_ticks(synthetic_ticks(), symbol="R_75", timeframe_sec=60)

        self.assertGreaterEqual(result.signals, 1)
        self.assertGreaterEqual(result.metrics.trades, 0)
        self.assertGreater(result.final_equity, 0)

    def test_run_ticks_is_hermetic_across_sequential_runs(self) -> None:
        """run_ticks must be hermetic: two sequential runs on the same symbol
        (no manual cache clearing between them) must produce identical
        results.

        Regression for the assembler-cache leak: the module-level EGARCH /
        session-filter / fingerprint caches in features/assembler.py warm up
        during the first run, so a second run in the same process inherits the
        first run's state (e.g. fingerprint_observations 1 -> 599) and its
        features -- and therefore its signals and trades -- silently diverge.
        """
        ticks = synthetic_ticks(candles=130)

        first = BacktestEngine().run_ticks(ticks, symbol="R_75", timeframe_sec=60)
        second = BacktestEngine().run_ticks(ticks, symbol="R_75", timeframe_sec=60)

        self.assertEqual(first.model_version, second.model_version)
        self.assertEqual(first.signals, second.signals)
        self.assertEqual(first.rejected_signals, second.rejected_signals)
        self.assertEqual(first.metrics.trades, second.metrics.trades)
        self.assertEqual(first.metrics.expectancy_r, second.metrics.expectancy_r)
        self.assertEqual(first.final_equity, second.final_equity)

    def test_run_ticks_clears_assembler_caches_at_entry(self) -> None:
        """run_ticks's public contract: every run starts hermetic.  The
        module-level assembler caches (EGARCH / session filter / fingerprint)
        are warm-up state that must be cleared at entry, so a sequential run
        in the same process can never inherit a previous run's state."""
        ticks = synthetic_ticks(candles=40)

        with mock.patch.object(backtest_engine, "clear_assembler_caches") as clear:
            clear.side_effect = assembler.clear_assembler_caches
            BacktestEngine().run_ticks(ticks, symbol="R_75", timeframe_sec=60)

        clear.assert_called_once()

    def test_run_ticks_starts_each_run_with_cold_caches(self) -> None:
        """The hermetic contract at the feature level: when the second of two
        sequential runs begins assembling features, the assembler caches must
        already be cold — the exact leak signature is a warm cache at the
        first snapshot (fingerprint_observations 1 -> 599).  Guards against a
        refactor that clears too late (after the first evaluate) or clears
        the wrong state."""
        from synthetic_trader.strategy import decision_engine

        ticks = synthetic_ticks(candles=40)
        BacktestEngine().run_ticks(ticks, symbol="R_75", timeframe_sec=60)  # warms caches

        cold_at_first_snapshot: list[bool] = []
        real_build = decision_engine.build_snapshot

        def spy(*args, **kwargs):
            if not cold_at_first_snapshot:
                cold_at_first_snapshot.append(
                    not assembler._garch_forecasters
                    and not assembler._session_filters
                    and not assembler._fingerprint_detectors
                )
            return real_build(*args, **kwargs)

        with mock.patch.object(decision_engine, "build_snapshot", side_effect=spy):
            BacktestEngine().run_ticks(ticks, symbol="R_75", timeframe_sec=60)

        self.assertEqual(cold_at_first_snapshot, [True],
                         "second run's first feature snapshot saw a WARM cache "
                         "— the assembler-cache leak")
        # Clean up the spy's own warm-up residue (run 2 built features too).
        assembler.clear_assembler_caches()

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
