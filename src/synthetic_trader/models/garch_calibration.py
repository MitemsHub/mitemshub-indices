"""EGARCH(1,1) maximum-likelihood parameter calibration from real tick data.

Fits omega, alpha, beta, gamma to observed returns using scipy.optimize.
This replaces estimated GARCH parameters with calibrated values from
actual Blueberry Markets synthetic index behavior.

The negative log-likelihood of the EGARCH(1,1) model is:

    L = 0.5 * sum( log(σ²_t) + r²_t / σ²_t )

where σ²_t follows the EGARCH recursion:

    log(σ²_t) = ω + α * (|z_{t-1}| - E|z|) + γ * z_{t-1} + β * log(σ²_{t-1})

Reference:
- Nelson (1991) "Conditional Heteroskedasticity in Asset Returns"
- Engle & Ng (1993) "News and the GARCH Model"
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from synthetic_trader.models.garch import GARCHState


# Standard normal E|z| for EGARCH standardization
EZ_NORMAL = 0.7979


@dataclass
class CalibrationResult:
    """Result of EGARCH parameter calibration."""

    symbol: str
    omega: float
    alpha: float
    beta: float
    gamma: float
    n_observations: int
    negative_log_likelihood: float
    convergence: bool
    message: str
    # Diagnostics
    persistence: float = 0.0
    half_life: float = 0.0
    long_run_vol: float = 0.0
    realized_vol: float = 0.0
    vol_ratio: float = 0.0
    # Goodness-of-fit
    ljung_box_p_value: float = 0.0
    arch_test_p_value: float = 0.0

    @property
    def conditional_volatility(self) -> float:
        """Unconditional volatility from fitted parameters."""
        return math.exp(self.omega / (2.0 * (1.0 - self.persistence))) if self.persistence < 1.0 else self.long_run_vol

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "omega": self.omega,
            "alpha": self.alpha,
            "beta": self.beta,
            "gamma": self.gamma,
            "n_observations": self.n_observations,
            "negative_log_likelihood": self.negative_log_likelihood,
            "convergence": self.convergence,
            "message": self.message,
            "persistence": self.persistence,
            "half_life": self.half_life,
            "long_run_vol": self.long_run_vol,
            "realized_vol": self.realized_vol,
            "vol_ratio": self.vol_ratio,
            "ljung_box_p_value": self.ljung_box_p_value,
            "arch_test_p_value": self.arch_test_p_value,
        }

    def to_garch_state(self) -> GARCHState:
        """Convert fitted parameters to a GARCHState for the online forecaster."""
        # Use omega / (1 - persistence) for long-run variance
        # Guard against persistence >= 1.0
        if self.persistence < 1.0 and self.persistence > 0.0:
            lr_var = math.exp(self.omega / (1.0 - self.persistence))
            log_var = self.omega / (1.0 - self.persistence)
        elif self.long_run_vol > 0:
            lr_var = self.long_run_vol ** 2
            log_var = math.log(lr_var)
        else:
            lr_var = 1e-4
            log_var = math.log(lr_var)
        return GARCHState(
            omega=self.omega,
            alpha=self.alpha,
            gamma=self.gamma,
            beta=self.beta,
            log_variance=log_var,
            observations=self.n_observations,
            long_run_variance=lr_var,
        )


def compute_log_returns(prices: np.ndarray) -> np.ndarray:
    """Compute log-returns from a price series."""
    return np.diff(np.log(np.maximum(prices, 1e-10)))


def egarch_negative_log_likelihood(
    params: np.ndarray,
    log_returns: np.ndarray,
) -> float:
    """Compute negative log-likelihood for EGARCH(1,1).

    Parameters
    ----------
    params : array-like
        [omega, alpha, beta, gamma]
    log_returns : np.ndarray
        Log-return series

    Returns
    -------
    float
        Negative log-likelihood (to be minimized)
    """
    omega, alpha, beta, gamma = params
    n = len(log_returns)

    # Stability constraints
    persistence = alpha + beta
    if persistence >= 0.999 or persistence <= 0.0:
        return 1e10
    if alpha < 0 or alpha > 0.5:
        return 1e10
    if beta < 0 or beta > 0.999:
        return 1e10
    if abs(gamma) > 0.5:
        return 1e10

    # Initialize variance from sample
    sample_var = max(np.var(log_returns), 1e-10)
    log_var = np.log(sample_var)
    long_run_var = omega / max(1.0 - persistence, 1e-10)

    # EGARCH recursion
    log_var_series = np.empty(n)
    nll = 0.0

    for t in range(n):
        if t > 0:
            z_prev = log_returns[t - 1] / max(math.exp(log_var_series[t - 1] / 2.0), 1e-10)
            shock_magnitude = abs(z_prev) - EZ_NORMAL
            log_var_series[t] = omega + alpha * shock_magnitude + gamma * z_prev + beta * log_var_series[t - 1]
            # Clip for numerical stability
            log_var_series[t] = max(-30.0, min(5.0, log_var_series[t]))
        else:
            log_var_series[t] = log_var

        var_t = math.exp(log_var_series[t])
        nll += 0.5 * (log_var_series[t] + log_returns[t] ** 2 / max(var_t, 1e-10))

    return nll


def fit_egarch(
    prices: np.ndarray | list[float],
    symbol: str = "unknown",
    initial_params: tuple[float, float, float, float] | None = None,
    max_iter: int = 500,
) -> CalibrationResult:
    """Fit EGARCH(1,1) parameters to observed price data using MLE.

    Parameters
    ----------
    prices : array-like
        Observed price series
    symbol : str
        Symbol name for the result
    initial_params : tuple, optional
        (omega, alpha, beta, gamma) initial guesses. If None, uses sensible defaults.
    max_iter : int
        Maximum optimizer iterations

    Returns
    -------
    CalibrationResult
        Fitted parameters and diagnostics
    """
    prices_arr = np.asarray(prices, dtype=np.float64)

    # Input validation: filter NaN/Inf and non-positive prices
    prices_arr = prices_arr[np.isfinite(prices_arr)]
    prices_arr = prices_arr[prices_arr > 0]
    if len(prices_arr) < 51:
        return CalibrationResult(
            symbol=symbol,
            omega=-2.0, alpha=0.08, beta=0.88, gamma=-0.04,
            n_observations=0,
            negative_log_likelihood=float("inf"),
            convergence=False,
            message="Insufficient data (< 50 observations)",
        )

    log_returns = compute_log_returns(prices_arr)

    # Realized volatility
    realized_vol = float(np.std(log_returns) * math.sqrt(252 * 24 * 4))  # annualized (4H bars)

    # Initial parameter guess
    if initial_params is not None:
        x0 = np.array(initial_params)
    else:
        # Sensible defaults based on empirical properties of synthetic indices
        sample_var = float(np.var(log_returns))
        omega_init = math.log(max(sample_var * 0.5, 1e-10))
        x0 = np.array([omega_init, 0.08, 0.88, -0.04])

    # Bounds for parameters
    bounds = [
        (-20.0, 0.0),       # omega (log variance intercept)
        (0.001, 0.5),       # alpha (shock magnitude)
        (0.5, 0.999),       # beta (persistence)
        (-0.5, 0.5),        # gamma (asymmetry)
    ]

    # Minimize negative log-likelihood
    try:
        result = minimize(
            egarch_negative_log_likelihood,
            x0,
            args=(log_returns,),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": max_iter, "ftol": 1e-10},
        )

        omega_fit, alpha_fit, beta_fit, gamma_fit = result.x
        nll = float(result.fun)
        converged = result.success

        # Compute diagnostics
        persistence = alpha_fit + beta_fit
        half_life = math.log(0.5) / math.log(persistence) if 0.0 < persistence < 1.0 else float("inf")
        long_run_var = omega_fit / max(1.0 - persistence, 1e-10)
        long_run_vol = math.sqrt(max(long_run_var, 1e-10))

        # Goodness-of-fit diagnostics (skip if fit didn't converge)
        if converged:
            std_resid = _compute_standardized_residuals(log_returns, omega_fit, alpha_fit, beta_fit, gamma_fit)
            ljung_box_p = _ljung_box_test_with_residuals(std_resid)
            arch_p = _arch_test_with_residuals(std_resid)
        else:
            ljung_box_p = 0.5  # neutral when unconverged
            arch_p = 0.5

        return CalibrationResult(
            symbol=symbol,
            omega=float(omega_fit),
            alpha=float(alpha_fit),
            beta=float(beta_fit),
            gamma=float(gamma_fit),
            n_observations=len(log_returns),
            negative_log_likelihood=nll,
            convergence=converged,
            message="MLE fit completed" if converged else f"Partial convergence: {result.message}",
            persistence=float(persistence),
            half_life=float(half_life),
            long_run_vol=float(long_run_vol),
            realized_vol=realized_vol,
            vol_ratio=float(long_run_vol / max(realized_vol, 1e-10)),
            ljung_box_p_value=float(ljung_box_p),
            arch_test_p_value=float(arch_p),
        )

    except Exception as exc:
        return CalibrationResult(
            symbol=symbol,
            omega=x0[0], alpha=x0[1], beta=x0[2], gamma=x0[3],
            n_observations=len(log_returns),
            negative_log_likelihood=float("inf"),
            convergence=False,
            message=f"Optimization failed: {exc}",
        )


def _compute_standardized_residuals(
    log_returns: np.ndarray,
    omega: float, alpha: float, beta: float, gamma: float,
) -> np.ndarray:
    """Compute standardized residuals from fitted EGARCH parameters."""
    n = len(log_returns)
    log_var = math.log(max(np.var(log_returns), 1e-10))
    std_resid = np.empty(n)
    for t in range(n):
        var_t = math.exp(log_var)
        std_resid[t] = log_returns[t] / max(math.sqrt(var_t), 1e-10)
        if t < n - 1:
            z_prev = std_resid[t]
            shock = abs(z_prev) - EZ_NORMAL
            log_var = omega + alpha * shock + gamma * z_prev + beta * log_var
            log_var = max(-30.0, min(5.0, log_var))
    return std_resid


def _ljung_box_test(
    log_returns: np.ndarray,
    omega: float, alpha: float, beta: float, gamma: float,
    max_lag: int = 10,
) -> float:
    """Ljung-Box test on standardized residuals (computes residuals internally)."""
    n = len(log_returns)
    if n < max_lag + 10:
        return 0.5
    std_resid = _compute_standardized_residuals(log_returns, omega, alpha, beta, gamma)
    return _ljung_box_test_with_residuals(std_resid, max_lag=max_lag)


def _ljung_box_test_with_residuals(
    std_resid: np.ndarray,
    max_lag: int = 10,
) -> float:
    """Ljung-Box test on pre-computed standardized residuals.

    Returns approximate p-value. Low p-value (< 0.05) indicates
    significant autocorrelation in residuals (model inadequacy).
    """
    n = len(std_resid)
    if n < max_lag + 10:
        return 0.5

    # Autocorrelation of squared standardized residuals
    sq_resid = std_resid ** 2
    mean_sq = np.mean(sq_resid)
    centered = sq_resid - mean_sq
    acf_full = np.correlate(centered, centered, mode="full")
    acf = acf_full[n - 1:n - 1 + max_lag + 1]
    if acf[0] > 0:
        acf = acf / acf[0]
    else:
        acf = np.zeros_like(acf)

    n_eff = n - max_lag
    if n_eff <= max_lag:
        return 0.5
    q_stat = n_eff * (n_eff + 2) * sum(acf[k] ** 2 / (n_eff - k) for k in range(1, max_lag + 1))
    p_value = min(1.0, math.exp(-q_stat / (2 * max_lag))) if q_stat > 0 else 1.0
    return p_value


def _arch_test(
    log_returns: np.ndarray,
    omega: float, alpha: float, beta: float, gamma: float,
    max_lag: int = 5,
) -> float:
    """ARCH LM test on standardized residuals (computes residuals internally)."""
    n = len(log_returns)
    if n < max_lag + 10:
        return 0.5
    std_resid = _compute_standardized_residuals(log_returns, omega, alpha, beta, gamma)
    return _arch_test_with_residuals(std_resid, max_lag=max_lag)


def _arch_test_with_residuals(
    std_resid: np.ndarray,
    max_lag: int = 5,
) -> float:
    """ARCH LM test on pre-computed standardized residuals.

    Returns approximate p-value. Low p-value indicates remaining
    ARCH effects (volatility clustering not captured by model).
    """
    n = len(std_resid)
    if n < max_lag + 10:
        return 0.5

    sq = std_resid ** 2
    T = n - max_lag
    if T < max_lag + 2:
        return 0.5

    # Build lagged matrix using consistent slicing
    # Each column k (0-indexed) contains sq[k+1 : k+1+T]
    # y contains sq[max_lag : max_lag+T]
    y = sq[max_lag:max_lag + T].copy()
    X_data = np.empty((T, max_lag))
    for k in range(max_lag):
        X_data[:, k] = sq[k:k + T]

    X_with_const = np.column_stack([np.ones(T), X_data])
    try:
        beta_hat = np.linalg.lstsq(X_with_const, y, rcond=None)[0]
        y_hat = X_with_const @ beta_hat
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1.0 - ss_res / max(ss_tot, 1e-10)
        lm_stat = T * max(r_squared, 0.0)
        p_value = min(1.0, math.exp(-lm_stat / (2 * max_lag))) if lm_stat > 0 else 1.0
        return p_value
    except (np.linalg.LinAlgError, ValueError):
        return 0.5


def calibrate_from_ticks_csv(
    csv_path: str | Path,
    symbol: str,
    price_column: str = "price",
    delimiter: str = ",",
) -> CalibrationResult:
    """Calibrate EGARCH parameters from a tick CSV file.

    The CSV should have at least 'epoch' and 'price' columns.
    """
    import csv as csv_mod

    prices: list[float] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv_mod.DictReader(f, delimiter=delimiter)
        for row in reader:
            try:
                p = float(row[price_column])
                if p > 0:
                    prices.append(p)
            except (ValueError, KeyError):
                continue

    if not prices:
        return CalibrationResult(
            symbol=symbol,
            omega=-2.0, alpha=0.08, beta=0.88, gamma=-0.04,
            n_observations=0,
            negative_log_likelihood=float("inf"),
            convergence=False,
            message=f"No valid prices found in {csv_path}",
        )

    return fit_egarch(np.array(prices), symbol=symbol)


def save_calibration_result(result: CalibrationResult, path: str | Path) -> None:
    """Save calibration result to JSON."""
    Path(path).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def load_calibration_result(path: str | Path) -> CalibrationResult:
    """Load calibration result from JSON as a CalibrationResult."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CalibrationResult(
        symbol=data["symbol"],
        omega=data["omega"],
        alpha=data["alpha"],
        beta=data["beta"],
        gamma=data["gamma"],
        n_observations=data["n_observations"],
        negative_log_likelihood=data["negative_log_likelihood"],
        convergence=data["convergence"],
        message=data["message"],
        persistence=data.get("persistence", 0.0),
        half_life=data.get("half_life", 0.0),
        long_run_vol=data.get("long_run_vol", 0.0),
        realized_vol=data.get("realized_vol", 0.0),
        vol_ratio=data.get("vol_ratio", 0.0),
        ljung_box_p_value=data.get("ljung_box_p_value", 0.0),
        arch_test_p_value=data.get("arch_test_p_value", 0.0),
    )


# Default directory for calibrated EGARCH parameters.
# The CLI's calibrate-egarch command saves here automatically,
# and the assembler loads from here on startup.
DEFAULT_CALIBRATION_DIR = Path("data/garch_calibration")


def get_calibration_path(
    symbol: str,
    calibration_dir: str | Path | None = None,
) -> Path:
    """Return the canonical path for a symbol's calibration JSON.

    Parameters
    ----------
    symbol : str
        Symbol name, e.g. "R_75" or "R_100".
    calibration_dir : str | Path, optional
        Override the default directory.  When ``None``, uses
        ``data/garch_calibration/`` relative to the project root.
    """
    d = Path(calibration_dir) if calibration_dir else DEFAULT_CALIBRATION_DIR
    return d / f"{symbol.lower()}.json"


def save_calibrated_garch_state(
    result: CalibrationResult,
    symbol: str,
    calibration_dir: str | Path | None = None,
) -> Path:
    """Persist calibrated EGARCH parameters for the live pipeline.

    Saves to ``data/garch_calibration/{symbol}.json`` by default.
    The assembler's ``_get_garch_forecaster`` reads from this path
    so the online forecaster starts with market-calibrated priors
    instead of generic defaults.

    Returns
    -------
    Path
        The file path that was written.
    """
    path = get_calibration_path(symbol, calibration_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_calibration_result(result, path)
    return path


def load_calibrated_garch_state(
    symbol: str,
    calibration_dir: str | Path | None = None,
) -> GARCHState | None:
    """Load calibrated GARCHState for a symbol, or ``None`` if unavailable.

    The assembler calls this once per symbol on first access.  When a
    calibration file exists, the forecaster is initialized with the
    fitted parameters instead of generic defaults.  When no file exists
    (pre-calibration), the caller falls back to the default
    ``EGARCHVarianceForecaster()``.

    Parameters
    ----------
    symbol : str
        Symbol name, e.g. "R_75" or "R_100".
    calibration_dir : str | Path, optional
        Override the default calibration directory.

    Returns
    -------
    GARCHState | None
        Initialized GARCHState from calibrated parameters, or
        ``None`` if no calibration file is found.
    """
    path = get_calibration_path(symbol, calibration_dir)
    if not path.exists():
        return None
    try:
        result = load_calibration_result(path)
        if not result.convergence:
            # Calibration didn't converge — skip and use defaults
            return None
        return result.to_garch_state()
    except (json.JSONDecodeError, KeyError, OSError):
        # Corrupted or unreadable file — use defaults
        return None
