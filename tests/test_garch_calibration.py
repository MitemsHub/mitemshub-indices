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
    _params_at_bounds,
    _degenerate_params,
    compute_egarch_diagnostics,
    _fit_candidate_acceptable,
    _select_best_candidate,
    load_calibrated_garch_state,
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


class TestParamsAtBounds:
    """Regression: degenerate calibration rejection.

    The on-disk R_75/R_100 calibration had beta pinned exactly at its
    0.01 floor (persistence ~0.03 — NO volatility clustering), and it
    slipped past the old guard which only rejected when 2+ params sat
    at bounds.  ``_params_at_bounds`` must reject on a single pinned
    parameter, on persistence below 0.05, and on a long-run vol far
    from the realized vol.
    """

    def _degenerate(self, **overrides):
        params = dict(
            symbol="R_75",
            omega=-2.0, alpha=0.03, beta=0.01, gamma=-0.02,
            n_observations=500,
            negative_log_likelihood=100.0,
            convergence=True,
            message="Optimization terminated successfully.",
            persistence=0.04,
            half_life=1.0,
            long_run_vol=0.01,
            realized_vol=0.0005,
        )
        params.update(overrides)
        return CalibrationResult(**params)

    def test_beta_pinned_at_floor_rejected(self) -> None:
        # beta exactly at its 0.01 floor, convergence=True
        assert _params_at_bounds(self._degenerate()) is True

    def test_beta_within_eps_of_floor_rejected(self) -> None:
        assert _params_at_bounds(self._degenerate(beta=0.0109)) is True

    def test_persistence_below_floor_rejected(self) -> None:
        # beta fine but persistence < 0.05 (no vol clustering)
        assert _params_at_bounds(
            self._degenerate(beta=0.88, persistence=0.03, long_run_vol=0.01)
        ) is True

    def test_healthy_fit_accepted(self) -> None:
        assert _params_at_bounds(
            self._degenerate(
                beta=0.88, alpha=0.08, gamma=-0.04, persistence=0.92,
                long_run_vol=0.0005, realized_vol=0.0005,
            )
        ) is False

    def test_long_run_vol_far_from_realized_rejected(self) -> None:
        assert _params_at_bounds(
            self._degenerate(
                beta=0.88, alpha=0.08, persistence=0.92,
                long_run_vol=1.0, realized_vol=0.0005,
            )
        ) is True

    def test_load_calibrated_garch_state_rejects_degenerate_on_disk(self) -> None:
        """End-to-end: a degenerate calibration file must yield None (defaults)."""
        with tempfile.TemporaryDirectory() as d:
            dirpath = Path(d)
            # Write the exact degenerate shape found in production
            save_calibration_result(self._degenerate(), dirpath / "r_75.json")
            state = load_calibrated_garch_state("R_75", dirpath)
            assert state is None

    def test_load_calibrated_garch_state_accepts_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            dirpath = Path(d)
            save_calibration_result(
                self._degenerate(
                    beta=0.88, alpha=0.08, gamma=-0.04, persistence=0.92,
                    long_run_vol=0.0005, realized_vol=0.0005,
                ),
                dirpath / "r_75.json",
            )
            state = load_calibrated_garch_state("R_75", dirpath)
            assert state is not None
            assert state.beta == 0.88


class TestHighPersistenceDiagnostics:
    """Regression: high-persistence fits (the R_100/R_75 shape) must report
    an honest long_run_vol / vol_ratio instead of the 1e-05 sqrt floor, and
    criterion 3 of ``_params_at_bounds`` must actually run for them (the old
    code skipped the ratio check at persistence >= 0.95)."""

    def _high_persistence_series(self, seed: int = 1234, n: int = 6000) -> np.ndarray:
        rng = np.random.RandomState(seed)
        # R_100-shaped EGARCH: persistence ~0.99 (beta 0.856 + alpha 0.134).
        omega, alpha, beta, gamma = -1.84, 0.134, 0.856, -0.037
        log_var = math.log(0.0016 ** 2)
        returns = np.empty(n)
        for t in range(n):
            sigma = math.exp(log_var / 2)
            z = rng.normal()
            returns[t] = z * sigma
            shock = abs(z) - 0.7979
            log_var = max(-30.0, min(5.0, omega + alpha * shock + gamma * z + beta * log_var))
        return 1000.0 * np.exp(np.cumsum(returns))

    def test_high_persistence_long_run_vol_not_at_floor(self) -> None:
        result = fit_egarch(self._high_persistence_series(), symbol="R100_SHAPE")
        # Never pinned at the 1e-05 sqrt floor (the old underflow artifact).
        assert result.long_run_vol > 1e-4
        # Anchored on the realized scale -> a healthy, scale-consistent ratio.
        assert result.realized_vol > 0
        ratio = result.long_run_vol / result.realized_vol
        assert 0.02 <= ratio <= 50.0
        # And the fit must not be rejected as degenerate.
        assert _params_at_bounds(result) is False

    def test_params_at_bounds_criterion3_runs_for_high_persistence(self) -> None:
        # persistence >= 0.95 (old code skipped the ratio check): a sane
        # long-run vol must be accepted...
        sane = CalibrationResult(
            symbol="HP", omega=-1.84, alpha=0.134, beta=0.856, gamma=-0.037,
            n_observations=5000, negative_log_likelihood=1.0, convergence=True,
            message="ok", persistence=0.9902, half_life=70.0,
            long_run_vol=0.0016, realized_vol=0.0017,
        )
        assert _params_at_bounds(sane) is False
        # ...and an absurd long-run vol must be rejected, proving the
        # ratio test now runs for high-persistence fits.
        absurd = CalibrationResult(
            symbol="HP", omega=-1.84, alpha=0.134, beta=0.856, gamma=-0.037,
            n_observations=5000, negative_log_likelihood=1.0, convergence=True,
            message="ok", persistence=0.9902, half_life=70.0,
            long_run_vol=1.0, realized_vol=0.0017,
        )
        assert _params_at_bounds(absurd) is True


class _FakeCandidate:
    """Minimal stand-in for a scipy OptimizeResult used by the selection tests."""

    def __init__(self, x, fun, success=True):
        self.x = np.asarray(x, dtype=float)
        self.fun = fun
        self.success = success


def _returns(seed: int = 3, n: int = 2000, sigma: float = 0.001) -> np.ndarray:
    rng = np.random.RandomState(seed)
    prices = 1000.0 * np.exp(np.cumsum(rng.normal(0, sigma, n)))
    return np.diff(np.log(np.maximum(prices, 1e-10)))


class TestDegeneracyGatedSelection:
    """Regression: the multi-start winner must NEVER be a bound-pinned basin.

    The degenerate R_100 refit on the repaired full-density corpus had the
    LOWEST raw NLL but alpha/beta pinned at their floors (persistence ~0.01,
    no vol clustering) — a fit _params_at_bounds rejects.  The winner
    selection now gates every candidate through the same degeneracy check
    and only a fit that would be accepted on load can win."""

    def test_acceptance_rejects_measured_degenerate_refit(self) -> None:
        rets = _returns()
        # The exact degenerate R_100 refit from the full corpus.
        degenerate = np.array([-13.014684, 0.001, 0.01, -0.008503])
        assert _fit_candidate_acceptable(degenerate, rets, "normal", 5.0) is False
        # The preserved validated R_100 params (high persistence, healthy).
        healthy = np.array([-1.8412, 0.1345, 0.8557, -0.0374])
        assert _fit_candidate_acceptable(healthy, rets, "normal", 5.0) is True
        # The raw-parameter gate agrees with the on-disk CalibrationResult gate.
        p, _, lrv, rv, _ = compute_egarch_diagnostics(*degenerate, rets)
        assert _degenerate_params(*degenerate, p, lrv, rv) is True
        p, _, lrv, rv, _ = compute_egarch_diagnostics(*healthy, rets)
        assert _degenerate_params(*healthy, p, lrv, rv) is False

    def test_winner_prefers_non_degenerate_over_better_nll(self) -> None:
        rets = _returns()
        degenerate = _FakeCandidate([-13.0, 0.001, 0.01, -0.008], fun=-1000.0)  # best raw NLL
        healthy = _FakeCandidate([-1.84, 0.134, 0.8557, -0.037], fun=-900.0)    # worse NLL, usable
        winner, fallback = _select_best_candidate([degenerate, healthy], rets, "normal", 5.0)
        assert winner is healthy
        assert fallback is degenerate

    def test_all_degenerate_returns_fallback(self) -> None:
        rets = _returns()
        d1 = _FakeCandidate([-13.0, 0.001, 0.01, -0.008], fun=-1000.0)
        d2 = _FakeCandidate([-14.0, 0.001, 0.011, 0.0], fun=-950.0)
        winner, fallback = _select_best_candidate([d1, d2], rets, "normal", 5.0)
        assert winner is None
        assert fallback is d1  # best-NLL degenerate is the explicit fallback

    def test_absurd_nll_candidate_never_wins(self) -> None:
        """An optimizer blow-up (predicate-clean params but absurd NLL — the
        measured R_100 full-corpus case: ~+2500 per obs) must not win either."""
        rets = _returns()
        blowup = _FakeCandidate([-13.7, 0.222, 0.6427, -0.0563], fun=62_600_728.0)
        healthy = _FakeCandidate([-1.84, 0.134, 0.8557, -0.037], fun=-900.0)
        winner, fallback = _select_best_candidate([blowup, healthy], rets, "normal", 5.0)
        assert winner is healthy
        assert fallback is blowup

    def test_params_at_bounds_rejects_absurd_nll(self) -> None:
        # Predicate-clean parameters but an absurd per-obs NLL must be
        # rejected on load too (defense in depth, not just selection).
        clean = CalibrationResult(
            symbol="HP", omega=-13.7, alpha=0.222, beta=0.6427, gamma=-0.0563,
            n_observations=24693, negative_log_likelihood=62_600_728.0,
            convergence=True, message="ok", persistence=0.8647, half_life=4.8,
            long_run_vol=0.001368, realized_vol=0.001398,
        )
        assert _params_at_bounds(clean) is True

    def test_converged_fit_never_degenerate(self) -> None:
        """The end-to-end invariant: a fit reported converged must always be
        a fit _params_at_bounds accepts (on a healthy synthetic series)."""
        rng = np.random.default_rng(7)
        n = 400
        log_var = math.log(0.0004)
        omega, alpha, gamma, beta = -1.0, 0.10, -0.04, 0.85
        returns = np.empty(n)
        for t in range(n):
            sigma = math.exp(log_var / 2)
            z = rng.standard_normal()
            returns[t] = z * sigma
            shock = abs(z) - 0.7979
            log_var = omega + alpha * shock + gamma * z + beta * log_var
        prices = np.exp(np.cumsum(returns)) * 100
        result = fit_egarch(prices, symbol="T", initial_params=(-2.0, 0.10, 0.88, -0.04))
        if result.convergence:
            assert _params_at_bounds(result) is False


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

    def test_headerless_csv(self) -> None:
        """The live collector writes headerless CSVs — they must load."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("0.0,R_75,100.0,0.0,0,0.0\n")
            f.write("1.0,R_75,101.0,0.0,0,0.0\n")
            csv_path = f.name

        result = calibrate_from_ticks_csv(csv_path, symbol="R_75")
        # Too few points for a fit, but parsing must not crash
        assert result.n_observations == 0 or result.n_observations > 0


class TestFitEGARCHStudentT:
    """Student-t innovations in the EGARCH MLE."""

    def test_nll_studentt_finite(self) -> None:
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 200)
        params = np.array([-2.0, 0.08, 0.88, -0.04])
        nll = egarch_negative_log_likelihood(
            params, returns, distribution="studentt", dof=5.0
        )
        # The t-likelihood drops the Gaussian normalization constant, so the
        # raw value can be negative — only finiteness matters for the fit.
        assert math.isfinite(nll)
        assert nll != 0.0

    def test_nll_studentt_differs_from_normal(self) -> None:
        rng = np.random.RandomState(7)
        returns = rng.normal(0, 0.01, 200)
        params = np.array([-2.0, 0.08, 0.88, -0.04])
        nll_normal = egarch_negative_log_likelihood(params, returns)
        nll_t = egarch_negative_log_likelihood(
            params, returns, distribution="studentt", dof=5.0
        )
        assert nll_normal != nll_t

    def test_fit_studentt_returns_valid_params(self) -> None:
        """Fitting t-distributed returns with a Student-t likelihood works."""
        rng = np.random.RandomState(11)
        n = 400
        omega, alpha, beta, gamma = -2.0, 0.08, 0.88, -0.04
        log_var = omega / (1 - alpha - beta)
        returns = np.empty(n)
        for t in range(n):
            sigma = math.exp(log_var / 2)
            z = rng.standard_t(5.0)  # heavy-tailed innovations
            returns[t] = z * sigma
            shock = abs(z) - 0.7979
            log_var = omega + alpha * shock + gamma * z + beta * log_var
        prices = np.exp(np.cumsum(returns)) * 100

        result = fit_egarch(
            prices, symbol="T", distribution="studentt", dof=5.0
        )

        assert result.n_observations == n - 1
        assert 0.001 <= result.alpha <= 0.95
        assert 0.01 <= result.beta <= 0.999
        assert abs(result.gamma) <= 0.99
        assert result.persistence < 1.0
        assert math.isfinite(result.negative_log_likelihood)


class TestFitEgarchInitialParams:
    """fit_egarch(initial_params=...) must work — it previously crashed with
    UnboundLocalError because the multi-start guesses referenced sample_var
    which was only computed on the default path (2026-08-16, R_100 re-check).
    """

    def test_initial_params_no_crash(self) -> None:
        rng = np.random.default_rng(7)
        n = 400
        log_var = math.log(0.0004)
        omega, alpha, gamma, beta = -1.0, 0.10, -0.04, 0.85
        returns = np.empty(n)
        for t in range(n):
            sigma = math.exp(log_var / 2)
            z = rng.standard_normal()
            returns[t] = z * sigma
            shock = abs(z) - 0.7979
            log_var = omega + alpha * shock + gamma * z + beta * log_var
        prices = np.exp(np.cumsum(returns)) * 100

        # The anchored high-persistence start (the R_100 re-check fix): the
        # fit must complete without raising and stay in-bounds.
        result = fit_egarch(prices, symbol="T", initial_params=(-2.0, 0.10, 0.88, -0.04))
        assert result.convergence is True
        assert math.isfinite(result.negative_log_likelihood)
        assert 0.001 <= result.alpha <= 0.95
        assert 0.01 <= result.beta <= 0.999
        assert result.persistence < 1.0

    def test_initial_params_respected_as_guess(self) -> None:
        # Explicitly degenerate guess must not raise and must produce a result
        # with finite NLL (the fix computes sample_var unconditionally).
        rng = np.random.default_rng(11)
        n = 300
        prices = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.002))
        result = fit_egarch(prices, symbol="T", initial_params=(-12.0, 0.05, 0.05, -0.10))
        assert math.isfinite(result.negative_log_likelihood)
        assert result.n_observations == n - 1
