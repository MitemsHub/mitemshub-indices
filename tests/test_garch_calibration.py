"""Tests for EGARCH calibration from tick data."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from synthetic_trader.models.garch_calibration import (
    CalibrationResult,
    compute_log_returns,
    egarch_negative_log_likelihood,
    fit_egarch,
    save_calibration_result,
    load_calibration_result,
    calibrate_from_ticks_csv,
)


class TestComputeLogReturns:
    """Test log-return computation."""

    def test_basic(self) -> None:
        prices = np.array([100.0, 101.0, 99.0, 100.5])
        lr = compute_log_returns(prices)
        assert len(lr) == 3
        assert abs(lr[0] - math.log(101.0 / 100.0)) < 1e-10
        assert abs(lr[1] - math.log(99.0 / 101.0)) < 1e-10

    def test_single_price(self) -> None:
        prices = np.array([100.0])
        lr = compute_log_returns(prices)
        assert len(lr) == 0

    def test_zeros_handled(self) -> None:
        prices = np.array([0.0, 100.0, 101.0])
        lr = compute_log_returns(prices)
        assert len(lr) == 2


class TestEGARCHNLL:
    """Test negative log-likelihood computation."""

    def test_returns_finite(self) -> None:
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 200)
        params = np.array([-2.0, 0.08, 0.88, -0.04])
        nll = egarch_negative_log_likelihood(params, returns)
        assert math.isfinite(nll)
        assert nll > 0

    def test_bad_params_return_large(self) -> None:
        returns = np.random.RandomState(42).normal(0, 0.01, 200)
        bad_params = np.array([-2.0, 0.3, 0.9, -0.04])  # persistence ~ 1.2
        nll = egarch_negative_log_likelihood(bad_params, returns)
        assert nll > 1e5


class TestFitEGARCH:
    """Test EGARCH parameter fitting."""

    def test_fit_too_few_observations(self) -> None:
        prices = np.array([100.0, 101.0, 102.0])
        result = fit_egarch(prices, symbol="SHORT")
        assert result.convergence is False
        assert "Insufficient data" in result.message

    def test_fit_returns_valid_params(self) -> None:
        rng = np.random.RandomState(42)
        n = 500
        omega, alpha, beta, gamma = -2.0, 0.08, 0.88, -0.04
        log_var = omega / (1 - alpha - beta)
        returns = np.empty(n)
        for t in range(n):
            sigma = math.exp(log_var / 2)
            z = rng.normal()
            returns[t] = z * sigma
            shock = abs(z) - 0.7979
            log_var = omega + alpha * shock + gamma * z + beta * log_var
        prices = np.exp(np.cumsum(returns)) * 100

        result = fit_egarch(prices, symbol="TEST")

        # Should produce valid parameters even if not perfectly converged
        assert result.n_observations == n - 1
        assert 0.001 <= result.alpha <= 0.95
        assert 0.01 <= result.beta <= 0.999
        assert abs(result.gamma) <= 0.99
        assert result.persistence < 1.0
        assert result.long_run_vol > 0

    def test_fit_returns_diagnostics(self) -> None:
        rng = np.random.RandomState(123)
        prices = np.exp(np.cumsum(rng.normal(0, 0.01, 300))) * 100
        result = fit_egarch(prices, symbol="DIAG")

        assert hasattr(result, "ljung_box_p_value")
        assert hasattr(result, "arch_test_p_value")
        assert hasattr(result, "half_life")
        assert hasattr(result, "vol_ratio")
        assert 0.0 <= result.ljung_box_p_value <= 1.0
        assert 0.0 <= result.arch_test_p_value <= 1.0


class TestCalibrationResult:
    """Test CalibrationResult dataclass."""

    def test_to_dict(self) -> None:
        r = CalibrationResult(
            symbol="SYN100",
            omega=-2.0, alpha=0.08, beta=0.88, gamma=-0.04,
            n_observations=500,
            negative_log_likelihood=1234.5,
            convergence=True,
            message="OK",
        )
        d = r.to_dict()
        assert d["symbol"] == "SYN100"
        assert d["omega"] == -2.0
        assert d["alpha"] == 0.08
        assert d["beta"] == 0.88
        assert d["gamma"] == -0.04
        assert d["convergence"] is True

    def test_to_garch_state(self) -> None:
        r = CalibrationResult(
            symbol="SYN100",
            omega=-2.0, alpha=0.08, beta=0.88, gamma=-0.04,
            n_observations=500,
            negative_log_likelihood=1234.5,
            convergence=True,
            message="OK",
            persistence=0.96,
            half_life=17.0,
            long_run_vol=0.01,
            realized_vol=0.012,
        )
        state = r.to_garch_state()
        assert state.omega == -2.0
        assert state.alpha == 0.08
        assert state.beta == 0.88
        assert state.gamma == -0.04
        assert state.observations == 500
        assert state.long_run_variance > 0

    def test_to_garch_state_roundtrip_with_forecaster(self) -> None:
        """Verify CalibrationResult.to_garch_state() feeds correctly into EGARCHVarianceForecaster."""
        from synthetic_trader.models.garch import EGARCHVarianceForecaster

        # Fit to real-ish data
        rng = np.random.RandomState(42)
        prices = np.exp(np.cumsum(rng.normal(0, 0.01, 300))) * 100
        result = fit_egarch(prices, symbol="ROUNDTRIP")

        # Convert to GARCHState
        state = result.to_garch_state()
        assert state.omega == result.omega
        assert state.alpha == result.alpha
        assert state.beta == result.beta
        assert state.gamma == result.gamma
        assert state.observations == result.n_observations
        assert state.long_run_variance > 0

        # Feed into forecaster
        forecaster = EGARCHVarianceForecaster()
        forecaster.state = state

        # The forecaster should produce valid features immediately
        features = forecaster.get_forecast()
        assert "garch_sigma" in features
        assert "garch_vol_regime" in features
        assert "garch_mean_revert_signal" in features
        assert features["garch_sigma"] > 0
        assert features["garch_vol_regime"] in (0.0, 1.0, 2.0)
        assert 0.0 <= features["garch_mean_revert_signal"] <= 1.0

        # Forecaster should also work with streaming updates
        rng2 = np.random.RandomState(99)
        for _ in range(20):
            ret = rng2.normal(0, 0.01)
            feats = forecaster.update(ret)
            assert feats["garch_sigma"] > 0
            assert math.isfinite(feats["garch_forecast"])


class TestSaveLoad:
    """Test calibration result persistence."""

    def test_save_and_load(self) -> None:
        r = CalibrationResult(
            symbol="SYN100",
            omega=-1.5, alpha=0.07, beta=0.90, gamma=-0.03,
            n_observations=1000,
            negative_log_likelihood=5678.9,
            convergence=True,
            message="Fit completed",
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name

        save_calibration_result(r, path)
        loaded = load_calibration_result(path)

        assert isinstance(loaded, CalibrationResult)
        assert loaded.symbol == "SYN100"
        assert loaded.omega == -1.5
        assert loaded.alpha == 0.07
        assert loaded.convergence is True


class TestCalibrateFromCSV:
    """Test CSV-based calibration."""

    def test_calibrate_from_csv(self) -> None:
        rng = np.random.RandomState(42)
        n = 300
        omega, alpha, beta, gamma = -2.0, 0.08, 0.88, -0.04
        log_var = omega / (1 - alpha - beta)
        returns = np.empty(n)
        for t in range(n):
            sigma = math.exp(log_var / 2)
            z = rng.normal()
            returns[t] = z * sigma
            shock = abs(z) - 0.7979
            log_var = omega + alpha * shock + gamma * z + beta * log_var
        prices = np.exp(np.cumsum(returns)) * 100
        epochs = np.arange(n, dtype=float)

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("epoch,symbol,price\n")
            for i, p in enumerate(prices):
                f.write(f"{epochs[i]:.3f},SYN100,{p:.5f}\n")
            csv_path = f.name

        result = calibrate_from_ticks_csv(csv_path, symbol="SYN100")

        # Should produce valid parameters
        assert result.n_observations > 0
        assert result.symbol == "SYN100"
        assert 0.001 <= result.alpha <= 0.95
        assert 0.01 <= result.beta <= 0.999
        assert abs(result.gamma) <= 0.99

    def test_empty_csv(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("epoch,symbol,price\n")
            csv_path = f.name

        result = calibrate_from_ticks_csv(csv_path, symbol="EMPTY")
        assert result.n_observations == 0
        assert "No valid prices" in result.message
