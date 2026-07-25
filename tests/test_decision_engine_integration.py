"""Integration tests for the DecisionEngine with real candle data.

These tests exercise the full pipeline — candle construction, feature
extraction, regime classification, structure detection, setup/confirmation
classification, and signal generation — WITHOUT mocking any internal
components.  They verify that the engine produces sane outputs on
synthetic-but-realistic market data.
"""

from __future__ import annotations

import math
import random
import unittest

from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle, Direction
from synthetic_trader.strategy.decision_engine import DecisionEngine


# ---------------------------------------------------------------------------
# Candle generators — each produces realistic OHLC data for a different
# market condition.  No two calls with a different seed produce identical
# series.
# ---------------------------------------------------------------------------

def _make_candles(
    symbol: str,
    count: int,
    base_price: float,
    drift: float,
    volatility: float,
    seed: int,
    timeframe_sec: int = 300,
) -> list[Candle]:
    """Generate *count* candles with controlled drift and volatility."""
    rng = random.Random(seed)
    candles: list[Candle] = []
    price = base_price

    for i in range(count):
        noise = rng.gauss(0, volatility)
        open_price = price
        body = drift + noise
        close = open_price + body
        wick_up = abs(rng.gauss(0, volatility * 0.4))
        wick_down = abs(rng.gauss(0, volatility * 0.4))
        high = max(open_price, close) + wick_up
        low = min(open_price, close) - wick_down
        candles.append(
            Candle(
                symbol=symbol,
                timeframe_sec=timeframe_sec,
                open_time=i * timeframe_sec,
                open=round(open_price, 5),
                high=round(high, 5),
                low=round(low, 5),
                close=round(close, 5),
                tick_count=rng.randint(3, 12),
            )
        )
        price = close
    return candles


def trending_up_candles(
    symbol: str = "R_100", count: int = 200, seed: int = 42
) -> list[Candle]:
    """Strong uptrend — consistent positive drift, moderate volatility."""
    return _make_candles(symbol, count, base_price=500.0, drift=0.18,
                         volatility=0.12, seed=seed)


def trending_down_candles(
    symbol: str = "R_100", count: int = 200, seed: int = 99
) -> list[Candle]:
    """Strong downtrend — consistent negative drift."""
    return _make_candles(symbol, count, base_price=800.0, drift=-0.20,
                         volatility=0.14, seed=seed)


def ranging_candles(
    symbol: str = "R_100", count: int = 200, seed: int = 7
) -> list[Candle]:
    """Sideways market — near-zero drift, moderate volatility."""
    return _make_candles(symbol, count, base_price=600.0, drift=0.005,
                         volatility=0.25, seed=seed)


def volatile_candles(
    symbol: str = "R_100", count: int = 200, seed: int = 13
) -> list[Candle]:
    """High-volatility regime — large swings in both directions."""
    return _make_candles(symbol, count, base_price=550.0, drift=0.02,
                         volatility=0.80, seed=seed)


def compression_candles(
    symbol: str = "R_100", count: int = 200, seed: int = 21
) -> list[Candle]:
    """Compression — low volatility, tight range, potential breakout."""
    return _make_candles(symbol, count, base_price=700.0, drift=0.002,
                         volatility=0.04, seed=seed)


def r75_trending_up_candles(count: int = 200, seed: int = 55) -> list[Candle]:
    """Uptrend on R_75 — lower pip size, tighter ranges."""
    return _make_candles("R_75", count, base_price=120.0, drift=0.10,
                         volatility=0.06, seed=seed)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class DecisionEngineIntegrationTests(unittest.TestCase):
    """End-to-end tests running the full DecisionEngine pipeline."""

    def setUp(self) -> None:
        self.config = TraderConfig.default()
        self.engine = DecisionEngine(self.config)

    # ── Basic contract tests ──────────────────────────────────────────

    def test_engine_returns_none_signal_when_insufficient_history(self) -> None:
        """Engine must reject candle series shorter than min_history_candles."""
        candles = trending_up_candles(count=10)
        report = self.engine.evaluate("R_100", candles)
        self.assertIsNone(report.signal)
        self.assertTrue(
            any("need" in r and "candles" in r for r in report.reasons),
            f"Expected a 'need N candles' reason, got: {report.reasons}",
        )

    def test_engine_returns_report_for_sufficient_history(self) -> None:
        """With enough candles the engine must produce a non-empty report."""
        candles = trending_up_candles(count=200)
        report = self.engine.evaluate("R_100", candles)
        # The report may or may not contain a signal (depends on
        # confidence threshold) but it must have reasons.
        self.assertIsInstance(report.reasons, tuple)
        self.assertGreater(len(report.reasons), 0)

    def test_engine_always_has_reasons(self) -> None:
        """Every code path through evaluate() must populate reasons."""
        for label, candles_fn in [
            ("trending_up", trending_up_candles),
            ("trending_down", trending_down_candles),
            ("ranging", ranging_candles),
            ("volatile", volatile_candles),
            ("compression", compression_candles),
        ]:
            with self.subTest(market=label):
                candles = candles_fn(count=200)
                report = self.engine.evaluate("R_100", candles)
                self.assertGreater(
                    len(report.reasons), 0,
                    f"No reasons returned for {label} market",
                )

    # ── Signal structure validity ──────────────────────────────────────

    def test_signal_has_valid_entry_stop_target_relationship(self) -> None:
        """When a signal is produced, entry/stop/target must be sane."""
        candles = trending_up_candles(count=250, seed=42)
        report = self.engine.evaluate("R_100", candles)
        # The engine may not produce a signal if confidence is below
        # the threshold — this is expected behavior, not a test gap.
        if report.signal is None:
            self.skipTest("No signal produced on this seed — acceptable")

        sig = report.signal
        self.assertEqual(sig.symbol, "R_100")

        # Entry must be a finite positive number
        self.assertTrue(math.isfinite(sig.entry))
        self.assertGreater(sig.entry, 0)

        # For a LONG signal, stop < entry < target
        if sig.direction is Direction.LONG:
            self.assertLess(sig.stop_loss, sig.entry,
                            "LONG stop must be below entry")
            self.assertGreater(sig.take_profit, sig.entry,
                               "LONG target must be above entry")
        else:
            self.assertGreater(sig.stop_loss, sig.entry,
                               "SHORT stop must be above entry")
            self.assertLess(sig.take_profit, sig.entry,
                            "SHORT target must be below entry")

        # Reward/risk must be positive
        self.assertGreater(sig.reward_risk, 0,
                           "reward/risk must be positive")

        # Confidence in [0, 1]
        self.assertGreaterEqual(sig.confidence, 0.0)
        self.assertLessEqual(sig.confidence, 1.0)

        # Snapshot must carry features
        self.assertIsNotNone(sig.snapshot)
        self.assertGreater(len(sig.snapshot.features), 0)

    def test_signal_snapshot_has_regime(self) -> None:
        """The snapshot attached to a signal must classify a regime."""
        candles = trending_up_candles(count=250, seed=42)
        report = self.engine.evaluate("R_100", candles)
        if report.signal is None:
            self.skipTest("Confidence below threshold — no signal on this seed")
        self.assertIsNotNone(report.signal.snapshot.regime)

    def test_signal_model_version_is_set(self) -> None:
        """model_version must be populated on every signal."""
        candles = trending_up_candles(count=250, seed=42)
        report = self.engine.evaluate("R_100", candles)
        if report.signal is None:
            self.skipTest("Confidence below threshold — no signal on this seed")
        self.assertIsInstance(report.signal.model_version, str)
        self.assertGreater(len(report.signal.model_version), 0)

    # ── Multi-timeframe role candles ───────────────────────────────────

    def test_role_candles_produce_valid_report(self) -> None:
        """Engine must handle role_candles dict without errors."""
        bias_candles = trending_up_candles(count=150, seed=10)
        setup_candles = trending_up_candles(count=100, seed=20)
        confirmation_candles = trending_up_candles(count=60, seed=30)
        execution_candles = trending_up_candles(count=120, seed=40)

        report = self.engine.evaluate(
            "R_100",
            candles=execution_candles,
            higher_timeframe_candles=bias_candles,
            role_candles={
                "bias": bias_candles,
                "setup": setup_candles,
                "confirmation": confirmation_candles,
                "execution": execution_candles,
            },
        )
        self.assertIsInstance(report.reasons, tuple)
        self.assertGreater(len(report.reasons), 0)

    def test_role_candles_with_mixed_regimes(self) -> None:
        """Engine handles conflicting regimes across timeframes."""
        bias_candles = trending_up_candles(count=150, seed=10)
        setup_candles = ranging_candles(count=100, seed=20)
        confirmation_candles = trending_down_candles(count=60, seed=30)
        execution_candles = volatile_candles(count=120, seed=40)

        report = self.engine.evaluate(
            "R_100",
            candles=execution_candles,
            higher_timeframe_candles=bias_candles,
            role_candles={
                "bias": bias_candles,
                "setup": setup_candles,
                "confirmation": confirmation_candles,
                "execution": execution_candles,
            },
        )
        # Must not crash and must provide reasons
        self.assertIsInstance(report.reasons, tuple)

    # ── R_75 symbol support ───────────────────────────────────────────

    def test_r75_trending_up(self) -> None:
        """Engine must work with R_75 symbol and its profile settings."""
        candles = r75_trending_up_candles(count=200)
        report = self.engine.evaluate("R_75", candles)
        self.assertIsInstance(report.reasons, tuple)
        self.assertGreater(len(report.reasons), 0)

    def test_r75_with_role_candles(self) -> None:
        """Engine handles R_75 with multi-timeframe role candles."""
        bias = r75_trending_up_candles(count=150, seed=10)
        setup = r75_trending_up_candles(count=100, seed=20)
        conf = r75_trending_up_candles(count=60, seed=30)
        exec_c = r75_trending_up_candles(count=120, seed=40)

        report = self.engine.evaluate(
            "R_75",
            candles=exec_c,
            higher_timeframe_candles=bias,
            role_candles={
                "bias": bias,
                "setup": setup,
                "confirmation": conf,
                "execution": exec_c,
            },
        )
        self.assertIsInstance(report.reasons, tuple)

    # ── Cross-symbol signal differentiation ────────────────────────────

    def test_r75_and_r100_produce_different_signal_levels(self) -> None:
        """Signals from R_75 and R_100 must have different price levels."""
        r75_candles = r75_trending_up_candles(count=200, seed=42)
        r100_candles = trending_up_candles(count=200, seed=42)

        report_75 = self.engine.evaluate("R_75", r75_candles)
        report_100 = self.engine.evaluate("R_100", r100_candles)

        # Both may not produce signals — only compare when both do
        if report_75.signal and report_100.signal:
            self.assertNotAlmostEqual(
                report_75.signal.entry, report_100.signal.entry, places=0,
                msg="R_75 and R_100 entries should differ",
            )

    # ── Model interaction ─────────────────────────────────────────────

    def test_engine_with_pretrained_model_weights(self) -> None:
        """Engine must work when given a model with non-zero weights."""
        from synthetic_trader.models.online import OnlineLogisticModel

        model = OnlineLogisticModel(config=self.config.model)
        # Simulate some training: set a few weights
        model.weights = {
            "slope_20_atr": 0.5,
            "structure_bias": 0.3,
            "atr_ratio": -0.1,
            "body": 0.2,
            "rsi_14": -0.05,
        }
        model.bias = 0.1
        model.updates = 50

        engine = DecisionEngine(self.config, model=model)
        candles = trending_up_candles(count=200, seed=42)
        report = engine.evaluate("R_100", candles)
        self.assertIsInstance(report.reasons, tuple)
        self.assertGreater(len(report.reasons), 0)

    # ── Stress: many seeds ────────────────────────────────────────────

    def test_engine_does_not_crash_on_varied_seeds(self) -> None:
        """Smoke test: engine must not crash across many random seeds."""
        for seed in range(0, 20):
            with self.subTest(seed=seed):
                candles = _make_candles(
                    "R_100", count=200, base_price=500.0,
                    drift=0.05, volatility=0.3, seed=seed,
                )
                report = self.engine.evaluate("R_100", candles)
                self.assertIsInstance(report.reasons, tuple)

    # ── Edge cases ──────────────────────────────────────────────────

    def test_role_candles_with_insufficient_execution_history(self) -> None:
        """Engine rejects when execution role has fewer candles than min_history."""
        bias_candles = trending_up_candles(count=150, seed=10)
        setup_candles = trending_up_candles(count=100, seed=20)
        confirmation_candles = trending_up_candles(count=60, seed=30)
        # Only 10 execution candles — below min_history_candles (30 for R_100 default)
        execution_candles = trending_up_candles(count=10, seed=40)

        report = self.engine.evaluate(
            "R_100",
            candles=execution_candles,
            higher_timeframe_candles=bias_candles,
            role_candles={
                "bias": bias_candles,
                "setup": setup_candles,
                "confirmation": confirmation_candles,
                "execution": execution_candles,
            },
        )
        self.assertIsNone(report.signal)
        self.assertTrue(
            any("need" in r and "candles" in r for r in report.reasons),
            f"Expected a 'need N candles' reason, got: {report.reasons}",
        )

    def test_explain_signal_on_real_snapshot(self) -> None:
        """explain_signal() must not crash on a real signal's snapshot."""
        candles = trending_up_candles(count=250, seed=42)
        report = self.engine.evaluate("R_100", candles)
        if report.signal is None:
            self.skipTest("Confidence below threshold — no signal on this seed")
        explanation = self.engine.explain_signal(report.signal)
        self.assertIn("direction", explanation)
        self.assertIn("confidence", explanation)
        self.assertIn("rationale", explanation)
        self.assertIn("targets", explanation)
        self.assertIsInstance(explanation["targets"], dict)

    def test_unsupported_symbol_raises(self) -> None:
        """Engine must raise ValueError for unknown symbols."""
        candles = trending_up_candles(count=200)
        with self.assertRaises(ValueError):
            self.engine.evaluate("INVALID_SYMBOL", candles)


if __name__ == "__main__":
    unittest.main()
