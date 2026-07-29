"""Tests for Walk-Forward Optimization (WFO) framework.

Covers:
- WindowSpec, WFOFold, WFOResult dataclasses
- HyperparameterGrid generation
- WalkForwardOptimizer with 30-day IS / 5-day OOS windows
- PBO calculation
- IS-OOS correlation
- Report rendering
- Save/load persistence
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from synthetic_trader.domain import Tick
from synthetic_trader.research.wfo import (
    HyperparameterGrid,
    WalkForwardOptimizer,
    WFOFold,
    WFOResult,
    WindowSpec,
    render_wfo_report,
)

from tests.test_backtest import synthetic_ticks


class WindowSpecTests(unittest.TestCase):
    def test_window_spec_creation(self) -> None:
        ws = WindowSpec(start_epoch=1000.0, end_epoch=2000.0, tick_count=500)
        self.assertEqual(ws.start_epoch, 1000.0)
        self.assertEqual(ws.end_epoch, 2000.0)
        self.assertEqual(ws.tick_count, 500)

    def test_window_spec_defaults(self) -> None:
        ws = WindowSpec(start_epoch=1000.0, end_epoch=2000.0)
        self.assertEqual(ws.tick_count, 0)


class WFOFoldTests(unittest.TestCase):
    def test_fold_creation(self) -> None:
        fold = WFOFold(
            fold_index=0,
            in_sample=WindowSpec(1000.0, 2000.0, 100),
            out_of_sample=WindowSpec(2000.0, 2500.0, 50),
            test_trades=10,
            test_win_rate=0.6,
            test_profit_factor=1.5,
            test_expectancy_r=0.2,
            test_net_pnl=100.0,
        )
        self.assertEqual(fold.fold_index, 0)
        self.assertEqual(fold.test_trades, 10)
        self.assertAlmostEqual(fold.test_win_rate, 0.6)


class HyperparameterGridTests(unittest.TestCase):
    def test_default_grid_combinations(self) -> None:
        grid = HyperparameterGrid()
        combos = grid.all_combinations()
        # 4 learning_rates * 3 l2_reg * 3 feature_clip = 36
        self.assertEqual(len(combos), 36)
        self.assertIn("learning_rate", combos[0])
        self.assertIn("l2", combos[0])
        self.assertIn("feature_clip", combos[0])

    def test_custom_grid(self) -> None:
        grid = HyperparameterGrid(
            learning_rates=[0.01],
            l2_reg=[0.0, 0.01],
            feature_clip=[10.0],
        )
        combos = grid.all_combinations()
        self.assertEqual(len(combos), 2)


class WalkForwardOptimizerTests(unittest.TestCase):
    def test_optimizer_default_params(self) -> None:
        opt = WalkForwardOptimizer()
        self.assertEqual(opt.is_days, 30.0)
        self.assertEqual(opt.oos_days, 5.0)
        self.assertEqual(opt.step_days, 5.0)

    def test_optimizer_custom_params(self) -> None:
        opt = WalkForwardOptimizer(
            is_days=14.0,
            oos_days=3.0,
            step_days=3.0,
            min_oos_trades=10,
        )
        self.assertEqual(opt.is_days, 14.0)
        self.assertEqual(opt.oos_days, 3.0)
        self.assertEqual(opt.min_oos_trades, 10)

    def test_optimizer_with_synthetic_ticks(self) -> None:
        """Test that the optimizer runs on synthetic tick data."""
        ticks = synthetic_ticks(candles=500)
        # Use small grid for fast tests
        small_grid = HyperparameterGrid(
            learning_rates=[0.01],
            l2_reg=[0.0],
            feature_clip=[10.0],
        )
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        self.assertIsInstance(result, WFOResult)
        self.assertEqual(result.symbol, "R_75")
        self.assertGreater(len(result.folds), 0)

    def test_pbo_score_range(self) -> None:
        """PBO should be between 0 and 1."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        self.assertGreaterEqual(result.pbo_score, 0.0)
        self.assertLessEqual(result.pbo_score, 1.0)

    def test_is_oos_correlation_range(self) -> None:
        """IS-OOS correlation should be between -1 and 1."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        self.assertGreaterEqual(result.is_oos_correlation, -1.0)
        self.assertLessEqual(result.is_oos_correlation, 1.0)

    def test_aggregate_metrics_populated(self) -> None:
        """Aggregate metrics should be populated after optimization."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        self.assertEqual(result.total_folds, len(result.folds))
        self.assertGreaterEqual(result.aggregate_trades, 0)

    def test_fold_windows_are_chronological(self) -> None:
        """Each fold's IS window should end at or before OOS start."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        for fold in result.folds:
            # Contiguous windows are valid: IS end == OOS start
            self.assertLessEqual(
                fold.in_sample.end_epoch,
                fold.out_of_sample.start_epoch,
                f"Fold {fold.fold_index}: IS end > OOS start",
            )

    def test_fold_indices_are_sequential(self) -> None:
        """Fold indices should be 0, 1, 2, ..."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        for i, fold in enumerate(result.folds):
            self.assertEqual(fold.fold_index, i)

    def test_not_enough_ticks_raises(self) -> None:
        """Should raise ValueError if not enough ticks."""
        ticks = synthetic_ticks(candles=5)
        opt = WalkForwardOptimizer(
            is_days=30.0,
            oos_days=5.0,
            step_days=5.0,
        )
        with self.assertRaises(ValueError):
            opt.optimize(ticks, symbol="R_75")

    def test_stability_metrics(self) -> None:
        """Stability metrics should be computed."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        result = opt.optimize(ticks, symbol="R_75")
        self.assertGreaterEqual(result.profit_factor_std, 0.0)
        self.assertGreaterEqual(result.win_rate_std, 0.0)

    def test_progress_callback(self) -> None:
        """Progress callback should be called."""
        ticks = synthetic_ticks(candles=500)
        small_grid = HyperparameterGrid(learning_rates=[0.01], l2_reg=[0.0], feature_clip=[10.0])
        opt = WalkForwardOptimizer(
            is_days=0.1,
            oos_days=0.05,
            step_days=0.05,
            timeframe_sec=60,
            higher_timeframe_sec=300,
            min_oos_trades=0,
            param_grid=small_grid,
        )
        progress_calls = []
        result = opt.optimize(
            ticks,
            symbol="R_75",
            progress_callback=lambda c, t: progress_calls.append((c, t)),
        )
        self.assertGreater(len(progress_calls), 0)


class WFOResultTests(unittest.TestCase):
    def test_render_report(self) -> None:
        """Render report should produce a string."""
        result = WFOResult(
            symbol="R_75",
            folds=[],
            aggregate_trades=100,
            aggregate_win_rate=0.55,
            aggregate_profit_factor=1.3,
            aggregate_expectancy_r=0.15,
            aggregate_net_pnl=500.0,
            aggregate_sharpe=0.8,
            pbo_score=0.3,
            is_oos_correlation=0.6,
            profit_factor_std=0.2,
            win_rate_std=0.05,
            min_fold_pf=0.9,
            max_fold_pf=1.8,
            is_duration_days=30.0,
            oos_duration_days=5.0,
            step_days=5.0,
            total_folds=5,
        )
        report = render_wfo_report(result)
        self.assertIn("R_75", report)
        self.assertIn("PBO Score", report)
        self.assertIn("Aggregate OOS Performance", report)

    def test_render_report_with_folds(self) -> None:
        """Render report should include fold details."""
        fold = WFOFold(
            fold_index=0,
            in_sample=WindowSpec(1000.0, 2000.0, 100),
            out_of_sample=WindowSpec(2000.0, 2500.0, 50),
            test_trades=10,
            test_win_rate=0.6,
            test_profit_factor=1.5,
            test_expectancy_r=0.2,
            test_net_pnl=100.0,
        )
        result = WFOResult(
            symbol="R_75",
            folds=[fold],
            aggregate_trades=10,
            aggregate_win_rate=0.6,
            aggregate_profit_factor=1.5,
            aggregate_expectancy_r=0.2,
            aggregate_net_pnl=100.0,
            total_folds=1,
        )
        report = render_wfo_report(result)
        self.assertIn("Fold 0", report)


class WFOPersistenceTests(unittest.TestCase):
    def test_save_and_load(self) -> None:
        """Should save and load WFOResult correctly."""
        fold = WFOFold(
            fold_index=0,
            in_sample=WindowSpec(1000.0, 2000.0, 100),
            out_of_sample=WindowSpec(2000.0, 2500.0, 50),
            test_trades=10,
            test_win_rate=0.6,
            test_profit_factor=1.5,
            test_expectancy_r=0.2,
            test_net_pnl=100.0,
            test_sharpe=0.8,
            optimized_params={"learning_rate": 0.01},
        )
        result = WFOResult(
            symbol="R_75",
            folds=[fold],
            aggregate_trades=10,
            aggregate_win_rate=0.6,
            aggregate_profit_factor=1.5,
            aggregate_expectancy_r=0.2,
            aggregate_net_pnl=100.0,
            aggregate_sharpe=0.8,
            pbo_score=0.3,
            is_oos_correlation=0.6,
            profit_factor_std=0.2,
            win_rate_std=0.05,
            min_fold_pf=1.5,
            max_fold_pf=1.5,
            is_duration_days=30.0,
            oos_duration_days=5.0,
            step_days=5.0,
            total_folds=1,
        )

        opt = WalkForwardOptimizer()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            opt.save(result, path)
            loaded = WalkForwardOptimizer.load(path)

            self.assertEqual(loaded.symbol, "R_75")
            self.assertEqual(loaded.total_folds, 1)
            self.assertAlmostEqual(loaded.aggregate_profit_factor, 1.5)
            self.assertAlmostEqual(loaded.pbo_score, 0.3)
            self.assertEqual(loaded.folds[0].optimized_params, {"learning_rate": 0.01})
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
