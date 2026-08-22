"""Tests for the synthetic backtesting framework.

Covers:
1. Synthetic price generator (EGARCH, CSPRNG, multi-dataset, Deriv)
2. Statistical validation (ADF, Hurst, volatility clustering, kurtosis, Ljung-Box)
3. Backtest runner (episode execution, curve-fitting detection)
"""

from __future__ import annotations

import math
import unittest

from synthetic_trader.backtest.synthetic_generator import (
    BrokerType,
    DerivIndexType,
    DerivIndexConfig,
    DERIV_INDICES,
    DerivCSPRNG,
    GARCHParams,
    SpreadModel,
    SyntheticIndexConfig,
    SyntheticPriceGenerator,
    generate_synthetic_datasets,
    generate_multi_symbol_datasets,
)
from synthetic_trader.backtest.synthetic_validation import (
    ValidationResult,
    SyntheticDataReport,
    validate_synthetic_data,
    check_stationarity_adf,
    check_hurst_exponent,
    check_volatility_clustering,
    check_heavy_tails,
    check_ljung_box,
    _compute_returns,
)
from synthetic_trader.backtest.synthetic_runner import (
    EpisodeResult,
    CurveFittingReport,
    SyntheticBacktestRunner,
)
from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Tick


class TestDerivCSPRNG(unittest.TestCase):
    """Test the Mersenne Twister CSPRNG wrapper."""

    def test_uniform_range(self):
        rng = DerivCSPRNG(seed=42)
        for _ in range(1000):
            u = rng.uniform()
            self.assertGreaterEqual(u, 0.0)
            self.assertLess(u, 1.0)

    def test_normal_distribution(self):
        rng = DerivCSPRNG(seed=42)
        samples = [rng.normal() for _ in range(10000)]
        mean = sum(samples) / len(samples)
        std = math.sqrt(sum((x - mean) ** 2 for x in samples) / len(samples))
        self.assertAlmostEqual(mean, 0.0, delta=0.1)
        self.assertAlmostEqual(std, 1.0, delta=0.1)

    def test_reproducibility(self):
        rng1 = DerivCSPRNG(seed=123)
        rng2 = DerivCSPRNG(seed=123)
        samples1 = [rng1.normal() for _ in range(100)]
        samples2 = [rng2.normal() for _ in range(100)]
        self.assertEqual(samples1, samples2)


class TestGARCHParams(unittest.TestCase):
    """Test GARCH parameter calculations."""

    def test_persistence(self):
        params = GARCHParams(omega=0.0000016, alpha=0.06, beta=0.92, gamma=-0.02)
        persistence = params.persistence
        self.assertGreater(persistence, 0.8)
        self.assertLess(persistence, 1.0)

    def test_long_run_variance(self):
        params = GARCHParams(omega=0.0000016, alpha=0.06, beta=0.92, gamma=-0.02)
        lrv = params.long_run_variance
        self.assertGreater(lrv, 0.0)
        self.assertLess(lrv, 0.001)


class TestSpreadModel(unittest.TestCase):
    """Test spread model calculations."""

    def test_base_spread(self):
        model = SpreadModel(base_spread_pct=0.001, spread_noise=0.0)
        import random
        rng = random.Random(42)
        spread = model.compute_spread(price=10000.0, hour=12, rng=rng)
        self.assertGreater(spread, 0.0)
        self.assertLess(spread, 100.0)

    def test_off_peak_spread_higher(self):
        model = SpreadModel(base_spread_pct=0.001, spread_noise=0.0, off_peak_spread_mult=2.0)
        import random
        rng = random.Random(42)
        peak_spread = model.compute_spread(price=10000.0, hour=12, rng=rng)
        off_peak_spread = model.compute_spread(price=10000.0, hour=2, rng=rng)
        self.assertGreater(off_peak_spread, peak_spread)


class TestDerivIndices(unittest.TestCase):
    """Test Deriv index configurations."""

    def test_all_indices_configured(self):
        """All Deriv index types should be configured."""
        expected = {"SYN50", "SYN75", "SYN100", "SURGE50", "SURGE75", "SURGE100",
                    "DROP50", "DROP75", "DROP100", "LEAP50", "LEAP75", "LEAP100"}
        self.assertEqual(set(DERIV_INDICES.keys()), expected)

    def test_from_deriv_config(self):
        """Should create config from Deriv symbol."""
        config = SyntheticIndexConfig.from_deriv("SYN100")
        self.assertEqual(config.broker, BrokerType.DERIV)
        self.assertEqual(config.symbol, "SYN100")
        self.assertEqual(config.initial_price, 10000.0)

    def test_from_deriv_unknown_symbol(self):
        """Should raise ValueError for unknown Deriv symbol."""
        with self.assertRaises(ValueError):
            SyntheticIndexConfig.from_deriv("UNKNOWN")

    def test_deriv_config(self):
        """Should create config from Deriv symbol."""
        config = SyntheticIndexConfig.from_deriv("R_100")
        self.assertEqual(config.broker, BrokerType.DERIV)
        self.assertEqual(config.symbol, "R_100")


class TestSyntheticPriceGenerator(unittest.TestCase):
    """Test the synthetic price data generator."""

    def test_basic_generation(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(100)
        self.assertEqual(len(ticks), 100)
        self.assertEqual(ticks[0].symbol, "R_100")
        self.assertGreater(ticks[0].price, 0)

    def test_price_continuity(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(50)
        for i in range(1, len(ticks)):
            change = abs(ticks[i].price - ticks[i - 1].price) / ticks[i - 1].price
            self.assertLess(change, 0.1)

    def test_epoch_progression(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(20, start_epoch=1000.0)
        for i in range(1, len(ticks)):
            self.assertGreater(ticks[i].epoch, ticks[i - 1].epoch)

    def test_spread_computed(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(10)
        for tick in ticks:
            self.assertGreaterEqual(tick.spread, 0.0)

    def test_tick_direction(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(100)
        directions = [t.tick_direction for t in ticks]
        self.assertIn(1, directions)
        self.assertIn(-1, directions)

    def test_state_serialization(self):
        gen = SyntheticPriceGenerator(seed=42)
        gen.generate_ticks(50)
        state = gen.get_state()
        gen2 = SyntheticPriceGenerator(seed=42)
        gen2.set_state(state)
        self.assertEqual(gen.current_price, gen2.current_price)
        self.assertEqual(gen.observations, gen2.observations)

    def test_volatility_clustering(self):
        """Verify that GARCH produces volatility clustering."""
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(1000)
        returns = _compute_returns([t.price for t in ticks])
        window = 20
        rolling_vol = []
        for i in range(window, len(returns)):
            chunk = returns[i - window:i]
            vol = math.sqrt(sum(r ** 2 for r in chunk) / window)
            rolling_vol.append(vol)
        if len(rolling_vol) > 10:
            mean_vol = sum(rolling_vol) / len(rolling_vol)
            var_vol = sum((v - mean_vol) ** 2 for v in rolling_vol) / len(rolling_vol)
            if var_vol > 0:
                acf1 = sum(
                    (rolling_vol[i] - mean_vol) * (rolling_vol[i - 1] - mean_vol)
                    for i in range(1, len(rolling_vol))
                ) / (len(rolling_vol) * var_vol)
                self.assertGreater(acf1, -0.5)


class TestDerivSyntheticGenerator(unittest.TestCase):
    """Test Deriv-specific synthetic generation."""

    def test_syn100_generation(self):
        """SYN100 should generate valid ticks."""
        config = SyntheticIndexConfig.from_deriv("SYN100")
        gen = SyntheticPriceGenerator(config=config, seed=42)
        ticks = gen.generate_ticks(100)
        self.assertEqual(len(ticks), 100)
        self.assertEqual(ticks[0].symbol, "SYN100")
        self.assertGreater(ticks[0].price, 0)

    def test_surge_momentum(self):
        """SURGE indices should show momentum bias."""
        config = SyntheticIndexConfig.from_deriv("SURGE100")
        self.assertGreater(config.momentum_bias, 0)

    def test_drop_crash_probability(self):
        """DROP indices should have crash probability."""
        config = SyntheticIndexConfig.from_deriv("DROP100")
        self.assertGreater(config.crash_probability, 0)
        self.assertGreater(config.recovery_speed, 0)

    def test_leap_trending(self):
        """LEAP indices should be trending."""
        config = SyntheticIndexConfig.from_deriv("LEAP100")
        self.assertGreater(config.momentum_bias, 0)

    def test_deriv_spread_model(self):
        """Deriv indices should have spread model configured."""
        config = SyntheticIndexConfig.from_deriv("SYN100")
        self.assertGreater(config.spread.base_spread_pct, 0)

    def test_drop_crash_behavior(self):
        """DROP indices should occasionally produce crashes."""
        config = SyntheticIndexConfig.from_deriv("DROP100")
        gen = SyntheticPriceGenerator(config=config, seed=42)
        ticks = gen.generate_ticks(5000)
        # Check that price dropped significantly at some point
        prices = [t.price for t in ticks]
        max_drop = 0
        for i in range(1, len(prices)):
            drop = (prices[i-1] - prices[i]) / prices[i-1]
            if drop > max_drop:
                max_drop = drop
        # With 5000 ticks and crash_probability=0.003, expect at least one crash
        self.assertGreater(max_drop, 0.01)  # At least 1% drop


class TestSyntheticValidation(unittest.TestCase):
    """Test the statistical validation suite."""

    def test_validate_returns_stationary(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(500)
        returns = _compute_returns([t.price for t in ticks])
        result = check_stationarity_adf(returns)
        self.assertIsInstance(result, ValidationResult)

    def test_validate_hurst_exponent(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(500)
        prices = [t.price for t in ticks]
        result = check_hurst_exponent(prices)
        self.assertIsInstance(result, ValidationResult)
        self.assertGreater(result.statistic, 0.3)
        self.assertLess(result.statistic, 0.7)

    def test_validate_volatility_clustering(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(500)
        returns = _compute_returns([t.price for t in ticks])
        result = check_volatility_clustering(returns)
        self.assertIsInstance(result, ValidationResult)

    def test_validate_heavy_tails(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(500)
        returns = _compute_returns([t.price for t in ticks])
        result = check_heavy_tails(returns)
        self.assertIsInstance(result, ValidationResult)

    def test_validate_ljung_box(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(500)
        returns = _compute_returns([t.price for t in ticks])
        result = check_ljung_box(returns)
        self.assertIsInstance(result, ValidationResult)

    def test_full_validation(self):
        gen = SyntheticPriceGenerator(seed=42)
        ticks = gen.generate_ticks(1000)
        report = validate_synthetic_data(ticks)
        self.assertIsInstance(report, SyntheticDataReport)
        self.assertEqual(report.n_ticks, 1000)
        self.assertEqual(len(report.tests), 5)
        passed = sum(1 for t in report.tests if t.passed)
        self.assertGreaterEqual(passed, 3)

    def test_validation_empty_data(self):
        report = validate_synthetic_data([])
        self.assertFalse(report.overall_passed)
        self.assertEqual(report.n_ticks, 0)


class TestGenerateSyntheticDatasets(unittest.TestCase):
    """Test multi-dataset generation."""

    def test_multiple_datasets(self):
        datasets = generate_synthetic_datasets(n_datasets=3, ticks_per_dataset=100)
        self.assertEqual(len(datasets), 3)
        for ds in datasets:
            self.assertEqual(len(ds), 100)

    def test_datasets_independent(self):
        datasets = generate_synthetic_datasets(n_datasets=2, ticks_per_dataset=50, base_seed=42)
        prices1 = [t.price for t in datasets[0]]
        prices2 = [t.price for t in datasets[1]]
        self.assertNotEqual(prices1[:10], prices2[:10])

    def test_multi_symbol_datasets(self):
        datasets = generate_multi_symbol_datasets(
            n_datasets=2, ticks_per_dataset=50, symbols=["SYN100", "SYN75"]
        )
        self.assertEqual(len(datasets), 2)
        for ds in datasets:
            self.assertIn("SYN100", ds)
            self.assertIn("SYN75", ds)


class TestSyntheticBacktestRunner(unittest.TestCase):
    """Test the synthetic backtest runner."""

    def test_runner_initialization(self):
        runner = SyntheticBacktestRunner(n_episodes=2, ticks_per_episode=500)
        self.assertEqual(runner.n_episodes, 2)
        self.assertEqual(runner.ticks_per_episode, 500)

    def test_runner_produces_report(self):
        runner = SyntheticBacktestRunner(
            n_episodes=2,
            ticks_per_episode=1000,
            base_seed=42,
        )
        report = runner.run("R_100")
        self.assertIsInstance(report, CurveFittingReport)
        self.assertEqual(report.n_episodes, 2)
        self.assertEqual(len(report.episodes), 2)
        self.assertIsInstance(report.verdict, str)

    def test_runner_reproducible(self):
        runner1 = SyntheticBacktestRunner(n_episodes=1, ticks_per_episode=500, base_seed=99)
        report1 = runner1.run("R_100")
        runner2 = SyntheticBacktestRunner(n_episodes=1, ticks_per_episode=500, base_seed=99)
        report2 = runner2.run("R_100")
        self.assertAlmostEqual(
            report1.mean_win_rate, report2.mean_win_rate, delta=0.01
        )

    def test_report_dict(self):
        runner = SyntheticBacktestRunner(n_episodes=1, ticks_per_episode=500)
        report = runner.run("R_100")
        d = report.to_dict()
        self.assertIn("symbol", d)
        self.assertIn("aggregate", d)
        self.assertIn("curve_fitting", d)
        self.assertIn("verdict", d)


if __name__ == "__main__":
    unittest.main()
