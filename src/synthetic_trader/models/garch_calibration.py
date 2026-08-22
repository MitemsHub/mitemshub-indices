"""EGARCH(1,1) maximum-likelihood parameter calibration from real tick data.

Fits omega, alpha, beta, gamma to observed returns using scipy.optimize.
This replaces estimated GARCH parameters with calibrated values from
actual Deriv synthetic index behavior.

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
from typing import Any

import numpy as np

from synthetic_trader.models.garch import GARCHState, ez_student_t


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
        """Convert fitted parameters to a GARCHState for the online forecaster.

        The online forecaster processes tick-level log-returns with very small
        variance (~1e-8).  We set the initial log_variance to a reasonable
        tick-level value (log(1e-6) ≈ -13.8) that the forecaster's own
        buffer initialization will override after 50 observations.

        The calibrated alpha/beta/gamma capture the *dynamics* of variance
        clustering (how vol responds to shocks) and are scale-independent.
        """
        # Use a reasonable tick-level initial variance.
        # The forecaster's buffer (50 observations) will override this
        # with the actual sample variance, so this only matters for
        # the first 50 ticks.  Starting at log(1e-6) ≈ -13.8 is a
        # conservative estimate for synthetic index tick-level returns.
        log_var = -13.8  # log(1e-6) — reasonable tick-level variance
        lr_var = math.exp(log_var)
        # Clamp to valid range
        lr_var = max(lr_var, 1e-10)
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
    result: np.ndarray = np.diff(np.log(np.maximum(prices, 1e-10)))
    return result


def compute_egarch_diagnostics(
    omega: float,
    alpha: float,
    beta: float,
    gamma: float,
    log_returns: np.ndarray,
    distribution: str = "normal",
    dof: float = 5.0,
) -> tuple[float, float, float, float, float]:
    """Compute EGARCH fit diagnostics from fitted parameters.

    Returns ``(persistence, half_life, long_run_vol, realized_vol, vol_ratio)``.

    ``realized_vol`` is the per-bar standard deviation of the returns — the
    same scale as ``long_run_vol`` — so ``vol_ratio`` is honest.  The old code
    annualized ``realized_vol`` with sqrt(252*24*4) (a 15-minute-bar factor
    that also disagreed with its "4H bars" comment), which put it ~155x above
    the per-bar long_run_vol and made every healthy fit look like
    vol_ratio ~0.0001.

    omega is a LOG-variance intercept: unconditional variance is
    exp(omega / (1 - persistence)).  The theoretical value is only meaningful
    at moderate persistence.  Near unit root (>= 0.95 — e.g. R_75 0.995,
    R_100 0.990) the denominator collapses and exp(omega/(1-persistence))
    underflows to ~0, pinning long_run_vol at the 1e-05 sqrt floor: the known
    unit-root issue the forecaster itself avoids by anchoring on a
    bias-corrected realized-scale estimate.  In that regime (or when the
    theoretical value is numerically degenerate) we anchor long_run_vol on
    the geometric-mean realized vol of the fitted series, so the diagnostic
    and its ratio stay honest.
    """
    persistence = alpha + beta
    half_life = math.log(0.5) / math.log(persistence) if 0.0 < persistence < 1.0 else float("inf")
    realized_vol = float(np.std(log_returns))

    theoretical_log_long_run_var = omega / max(1.0 - persistence, 1e-10)
    theoretical_long_run_var = math.exp(min(theoretical_log_long_run_var, 5.0))
    HIGH_PERSISTENCE = 0.95
    if (
        persistence >= HIGH_PERSISTENCE
        or not math.isfinite(theoretical_long_run_var)
        or theoretical_long_run_var < 1e-16
    ):
        # Bias-corrected mean realized log-variance: E[2*log|r|] =
        # log sigma^2 + E[log z^2] for the standardized innovation z,
        # so subtracting E[log z^2] removes the systematic low bias.
        # Same realized-scale anchor HorizonVolForecaster uses for its
        # long-run reference.  Lazy import mirrors the scipy pattern.
        from synthetic_trader.models.horizon_forecast import _log_z2_expectation

        realized_logvar = (
            float(np.mean(2.0 * np.log(np.maximum(np.abs(log_returns), 1e-12))))
            - _log_z2_expectation(distribution, dof)
        )
        long_run_var = math.exp(max(min(realized_logvar, 5.0), -30.0))
    else:
        long_run_var = theoretical_long_run_var
    long_run_vol = math.sqrt(max(long_run_var, 1e-10))
    vol_ratio = float(long_run_vol / max(realized_vol, 1e-10))
    return persistence, half_life, long_run_vol, realized_vol, vol_ratio


# A per-observation NLL above this is an optimizer blow-up, not a real fit:
# healthy EGARCH fits on these return series sit at roughly -3 to -8 per obs
# (per-bar sigma ~0.0005-0.01); the stability-penalty basin is ~1e10 per call
# and the measured R_100 full-corpus blow-up was ~+2500 per obs.
ABSURD_PER_OBS_NLL = 5.0


def _degenerate_params(
    omega: float,
    alpha: float,
    beta: float,
    gamma: float,
    persistence: float,
    long_run_vol: float,
    realized_vol: float,
) -> bool:
    """Raw-parameter degeneracy check shared by the multi-start winner
    selection and ``_params_at_bounds``.

    Returns True when a fit is degenerate and must NEVER be used:
      1. any single parameter pinned at an optimizer bound, OR
      2. persistence below 0.05 (no vol clustering to model), OR
      3. a long-run vol absurdly far from the realized vol.

    Bounds (matching fit_egarch):
        omega: [-30, 2], alpha: [0.001, 0.95], beta: [0.01, 0.999], gamma: [-0.99, 0.99]
    """
    BOUND_EPS = 0.001  # within 0.1% of bound edge
    at_bounds = 0
    if omega >= 2.0 - BOUND_EPS or omega <= -30.0 + BOUND_EPS:
        at_bounds += 1
    if alpha >= 0.95 - BOUND_EPS or alpha <= 0.001 + BOUND_EPS:
        at_bounds += 1
    if beta >= 0.999 - BOUND_EPS or beta <= 0.01 + BOUND_EPS:
        at_bounds += 1
    if abs(gamma) >= 0.99 - BOUND_EPS:
        at_bounds += 1
    if at_bounds >= 1:
        return True
    if persistence < 0.05:
        return True
    # Rule 3 (long-run vs realized vol sanity).  Both fields are per-bar
    # scale, and compute_egarch_diagnostics anchors long_run_vol on the
    # bias-corrected realized level for near-unit-root fits, so the ratio
    # is honest in every persistence regime.
    if realized_vol > 0:
        ratio = long_run_vol / realized_vol
        if ratio < 0.02 or ratio > 50.0:
            return True
    return False


def _fit_candidate_acceptable(
    x: np.ndarray,
    log_returns: np.ndarray,
    distribution: str,
    dof: float,
) -> bool:
    """True when a multi-start/DE candidate is a usable (non-degenerate) fit.

    The winner must NEVER be a fit that ``_params_at_bounds`` would reject:
    the degenerate R_100 refit on the repaired full-density corpus had the
    LOWEST raw NLL but alpha/beta pinned at their floors (persistence ~0.01,
    no vol clustering) — picking by NLL alone would seed the online
    forecaster with a broken fit that the loader then silently rejects.
    """
    omega, alpha, beta, gamma = x
    persistence, _, long_run_vol, realized_vol, _ = compute_egarch_diagnostics(
        omega, alpha, beta, gamma, log_returns,
        distribution=distribution, dof=dof,
    )
    return not _degenerate_params(
        omega, alpha, beta, gamma, persistence, long_run_vol, realized_vol
    )


def _select_best_candidate(
    candidates: list,
    log_returns: np.ndarray,
    distribution: str,
    dof: float,
) -> tuple:
    """Choose the multi-start winner: the best NLL among NON-degenerate
    basins, with the best degenerate candidate tracked only as a fallback.

    Returns ``(winner, fallback)``; either may be None.  ``winner`` is
    always a fit ``_params_at_bounds`` would accept (or None when every
    basin landed degenerate); ``fallback`` is the best-NLL degenerate fit
    for the caller to return with convergence=False rather than silently
    picking it as a valid calibration.
    """
    best_nll = float("inf")
    winner = None
    fb_nll = float("inf")
    fallback = None
    for cand in candidates:
        nll = float(cand.fun)
        per_obs = nll / max(len(log_returns), 1)
        if (
            not _fit_candidate_acceptable(cand.x, log_returns, distribution, dof)
            or (math.isfinite(nll) and per_obs > ABSURD_PER_OBS_NLL)
        ):
            # Bound-pinned / no-clustering / optimizer-blow-up basins are
            # never the winner — only the explicit all-degenerate fallback.
            if nll < fb_nll:
                fb_nll = nll
                fallback = cand
            continue
        if nll < best_nll:
            best_nll = nll
            winner = cand
    return winner, fallback


def _log_t_density(z: float, dof: float) -> float:
    """Log density of a standardized Student-t with ``dof`` degrees of freedom."""
    return (
        math.lgamma((dof + 1.0) / 2.0)
        - math.lgamma(dof / 2.0)
        - 0.5 * math.log(dof * math.pi)
        - ((dof + 1.0) / 2.0) * math.log1p(z * z / dof)
    )


def egarch_negative_log_likelihood(
    params: np.ndarray,
    log_returns: np.ndarray,
    distribution: str = "normal",
    dof: float = 5.0,
) -> float:
    """Compute negative log-likelihood for EGARCH(1,1).

    Parameters
    ----------
    params : array-like
        [omega, alpha, beta, gamma]
    log_returns : np.ndarray
        Log-return series
    distribution : str
        Innovation distribution: ``"normal"`` (default) or ``"studentt"``
        (fat-tailed Student-t with ``dof`` degrees of freedom).
    dof : float
        Degrees of freedom used when ``distribution="studentt"``.

    Returns
    -------
    float
        Negative log-likelihood (to be minimized)
    """
    omega, alpha, beta, gamma = params
    ez = ez_student_t(dof) if distribution == "studentt" else EZ_NORMAL
    n = len(log_returns)

    # Stability constraints — match the wider bounds used in fit_egarch()
    persistence = alpha + beta
    if persistence >= 0.995 or persistence <= 0.0:
        return 1e10  # near-unit-root is unstable
    if alpha < 0 or alpha > 0.95:
        return 1e10
    if beta < 0 or beta > 0.999:
        return 1e10
    if abs(gamma) > 0.99:
        return 1e10

    # Initialize variance from sample
    sample_var = max(np.var(log_returns), 1e-10)
    log_var = np.log(sample_var)
    # omega is a LOG-variance intercept, so the unconditional variance is
    # exp(omega / (1 - persistence)).
    long_run_var = math.exp(min(omega / max(1.0 - persistence, 1e-10), 5.0))

    # EGARCH recursion
    log_var_series = np.empty(n)
    nll = 0.0

    for t in range(n):
        if t > 0:
            z_prev = log_returns[t - 1] / max(math.exp(log_var_series[t - 1] / 2.0), 1e-10)
            shock_magnitude = abs(z_prev) - ez
            log_var_series[t] = omega + alpha * shock_magnitude + gamma * z_prev + beta * log_var_series[t - 1]
            # Clip for numerical stability
            log_var_series[t] = max(-30.0, min(5.0, log_var_series[t]))
        else:
            log_var_series[t] = log_var

        if distribution == "studentt":
            # Student-t innovations: -log f(r_t) = log(sigma_t) - log g(z_t)
            z_t = log_returns[t] / max(math.exp(log_var_series[t] / 2.0), 1e-10)
            nll += log_var_series[t] / 2.0 - _log_t_density(z_t, dof)
        else:
            var_t = math.exp(log_var_series[t])
            nll += 0.5 * (log_var_series[t] + log_returns[t] ** 2 / max(var_t, 1e-10))

    return nll


def fit_egarch(
    prices: np.ndarray | list[float],
    symbol: str = "unknown",
    initial_params: tuple[float, float, float, float] | None = None,
    max_iter: int = 500,
    distribution: str = "normal",
    dof: float = 5.0,
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

    # Initial parameter guess.  sample_var is computed unconditionally so
    # the multi-start list below works for the initial_params path too
    # (it previously crashed with UnboundLocalError when initial_params was
    # supplied but the guesses referenced sample_var).
    sample_var = float(np.var(log_returns))
    if initial_params is not None:
        x0 = np.array(initial_params)
    else:
        # Sensible defaults based on empirical properties of synthetic indices
        omega_init = math.log(max(sample_var * 0.5, 1e-10))
        x0 = np.array([omega_init, 0.08, 0.88, -0.04])

    # Bounds for parameters — widened for R_75 and other symbols
    # that need larger alpha/gamma values.  The to_garch_state() method
    # clamps the result to prevent underflow/overflow in the online forecaster.
    bounds = [
        (-30.0, 2.0),       # omega (log variance intercept) — wider for tick-level
        (0.001, 0.95),      # alpha (shock magnitude) — was 0.5, R_75 needs higher
        (0.01, 0.999),      # beta (persistence) — was 0.5 min, allow lower
        (-0.99, 0.99),      # gamma (asymmetry) — was ±0.5, allow full range
    ]

    # Lazy import: scipy.optimize hangs on Python 3.14 when imported at module level.
    from scipy.optimize import minimize, differential_evolution

    # ── Multi-start optimization ────────────────────────────────────
    # R_75 (and other symbols) can get stuck in local minima with a
    # single starting point.  Try multiple initial parameter sets and
    # keep the best fit (lowest NLL).
    # Initial guesses use realistic EGARCH(1,1) ranges: alpha 0.05-0.15,
    # beta 0.75-0.90, gamma -0.20 to 0.10.
    initial_guesses = [
        x0,  # default guess from data
        # Explicit high-persistence anchor.  Measured on R_100 (2026-08-16):
        # the five original guesses all converged to the LOW-persistence
        # basin (beta at its 0.01 floor, persistence ~0.05 — rejected by
        # _params_at_bounds as degenerate), while this anchor reaches the
        # genuinely better mode (NLL ~19 units lower, persistence ~0.99).
        # Including it makes the fit deterministic: the winner is chosen by
        # NLL among NON-degenerate basins, so corpus growth can no longer
        # flip the result to a WORSE local optimum or a bound-pinned one.
        np.array([-2.0, 0.10, 0.88, -0.04]),
        np.array([math.log(max(sample_var * 0.1, 1e-10)), 0.05, 0.90, -0.10]),  # low alpha, high beta
        np.array([math.log(max(sample_var * 0.3, 1e-10)), 0.12, 0.82, 0.05]),  # moderate alpha
        np.array([math.log(max(sample_var * 0.5, 1e-10)), 0.08, 0.85, -0.20]),  # strong asymmetry
        np.array([-5.0, 0.10, 0.80, 0.0]),  # neutral asymmetry
    ]

    candidates: list = []
    last_exception = None

    for guess in initial_guesses:
        try:
            candidates.append(
                minimize(
                    egarch_negative_log_likelihood,
                    guess,
                    args=(log_returns, distribution, dof),
                    method="L-BFGS-B",
                    bounds=bounds,
                    options={"maxiter": max_iter, "ftol": 1e-10},
                )
            )
        except Exception as exc:
            last_exception = exc
            continue

    best_result, best_degenerate_result = _select_best_candidate(
        candidates, log_returns, distribution, dof
    )

    # ── Differential evolution fallback ──────────────────────────────
    # If the best L-BFGS-B result didn't converge (or every start landed in
    # a degenerate basin), use differential evolution (global optimizer)
    # which doesn't need a good starting point.  DE needs more iterations
    # than L-BFGS-B (typically 2000+).  Its result goes through the same
    # degeneracy-gated selection.
    should_try_de = (
        best_result is None
        or not best_result.success
    )
    if should_try_de:
        try:
            candidates.append(
                differential_evolution(
                    egarch_negative_log_likelihood,
                    bounds=bounds,
                    args=(log_returns, distribution, dof),
                    maxiter=max(max_iter * 5, 2000),
                    seed=42,
                    tol=1e-8,
                    polish=True,  # L-BFGS-B polish after DE
                )
            )
            best_result, best_degenerate_result = _select_best_candidate(
                candidates, log_returns, distribution, dof
            )
        except Exception as exc:
            last_exception = exc

    if best_result is None and best_degenerate_result is not None:
        # Every basin landed degenerate (measured: the repaired full-density
        # R_100 corpus — alpha/beta pinned at floors, persistence ~0.01, no
        # vol clustering).  There is NO trustworthy calibration in this
        # data.  Return the best-NLL degenerate fit but force
        # convergence=False so load_calibrated_garch_state skips it (falls
        # back to default priors); _params_at_bounds would reject it as a
        # second layer of defense.
        result = best_degenerate_result
        omega_fit, alpha_fit, beta_fit, gamma_fit = result.x
        nll = float(result.fun)
        persistence, half_life, long_run_vol, realized_vol, vol_ratio = compute_egarch_diagnostics(
            omega_fit, alpha_fit, beta_fit, gamma_fit, log_returns,
            distribution=distribution, dof=dof,
        )
        msg = (
            f"All {len(initial_guesses)} multi-start basins degenerate "
            f"(bound-pinned or no vol clustering; best NLL {nll:.2f}) — "
            "fit rejected, forecaster falls back to default priors"
        )
        return CalibrationResult(
            symbol=symbol,
            omega=float(omega_fit),
            alpha=float(alpha_fit),
            beta=float(beta_fit),
            gamma=float(gamma_fit),
            n_observations=len(log_returns),
            negative_log_likelihood=nll,
            convergence=False,
            message=msg,
            persistence=persistence,
            half_life=half_life,
            long_run_vol=long_run_vol,
            realized_vol=realized_vol,
            vol_ratio=vol_ratio,
            ljung_box_p_value=0.5,
            arch_test_p_value=0.5,
        )

    if best_result is None:
        return CalibrationResult(
            symbol=symbol,
            omega=x0[0], alpha=x0[1], beta=x0[2], gamma=x0[3],
            n_observations=len(log_returns),
            negative_log_likelihood=float("inf"),
            convergence=False,
            message=f"All optimization attempts failed: {last_exception}",
        )

    result = best_result
    omega_fit, alpha_fit, beta_fit, gamma_fit = result.x
    nll = float(result.fun)
    converged = result.success

    # Compute diagnostics
    persistence, half_life, long_run_vol, realized_vol, vol_ratio = compute_egarch_diagnostics(
        omega_fit, alpha_fit, beta_fit, gamma_fit, log_returns,
        distribution=distribution, dof=dof,
    )

    # Goodness-of-fit diagnostics (skip if fit didn't converge)
    if converged:
        std_resid = _compute_standardized_residuals(
            log_returns, omega_fit, alpha_fit, beta_fit, gamma_fit,
            distribution=distribution, dof=dof,
        )
        ljung_box_p = _ljung_box_test_with_residuals(std_resid)
        arch_p = _arch_test_with_residuals(std_resid)
    else:
        ljung_box_p = 0.5  # neutral when unconverged
        arch_p = 0.5

    # Build convergence message
    n_starts = len(initial_guesses)
    if converged:
        msg = f"MLE fit completed (multi-start, {n_starts} starts)"
    else:
        msg = f"Partial convergence (multi-start, {n_starts} starts): {result.message}"

    return CalibrationResult(
        symbol=symbol,
        omega=float(omega_fit),
        alpha=float(alpha_fit),
        beta=float(beta_fit),
        gamma=float(gamma_fit),
        n_observations=len(log_returns),
        negative_log_likelihood=nll,
        convergence=converged,
        message=msg,
        persistence=float(persistence),
        half_life=float(half_life),
        long_run_vol=float(long_run_vol),
        realized_vol=realized_vol,
        vol_ratio=float(vol_ratio),
        ljung_box_p_value=float(ljung_box_p),
        arch_test_p_value=float(arch_p),
    )


def _compute_standardized_residuals(
    log_returns: np.ndarray,
    omega: float, alpha: float, beta: float, gamma: float,
    distribution: str = "normal",
    dof: float = 5.0,
) -> np.ndarray:
    """Compute standardized residuals from fitted EGARCH parameters."""
    ez = ez_student_t(dof) if distribution == "studentt" else EZ_NORMAL
    n = len(log_returns)
    log_var = math.log(max(float(np.var(log_returns)), 1e-10))
    std_resid = np.empty(n)
    for t in range(n):
        var_t = math.exp(log_var)
        std_resid[t] = log_returns[t] / max(math.sqrt(var_t), 1e-10)
        if t < n - 1:
            z_prev = std_resid[t]
            shock = abs(z_prev) - ez
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
    sq_resid: np.ndarray = std_resid ** 2
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

    sq: np.ndarray = std_resid ** 2
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
        ss_res: Any = np.sum((y - y_hat) ** 2)
        ss_tot: Any = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1.0 - ss_res / max(ss_tot, 1e-10)
        lm_stat = T * max(r_squared, 0.0)
        p_value = min(1.0, math.exp(-lm_stat / (2 * max_lag))) if lm_stat > 0 else 1.0
        return p_value
    except (np.linalg.LinAlgError, ValueError):
        return 0.5


def _resample_to_bars(
    epochs: list[float],
    prices: list[float],
    bar_seconds: int = 60,
) -> list[float]:
    """Resample tick-level data into OHLC bars and return close prices.

    Tick-level log-returns have std dev ~0.00003, which is too small
    for EGARCH calibration — the fitted omega underflows to near-zero.
    Resampling to 1-minute bars produces returns with std dev ~0.001,
    matching the scale the online forecaster expects.

    Parameters
    ----------
    epochs : list[float]
        Tick timestamps (epoch seconds).
    prices : list[float]
        Tick prices.
    bar_seconds : int
        Bar duration in seconds. Default 60 (1 minute).

    Returns
    -------
    list[float]
        Close prices for each bar.
    """
    if not prices:
        return []

    bars: list[float] = []
    bar_start = epochs[0]
    bar_close = prices[0]

    for i in range(1, len(prices)):
        if epochs[i] - bar_start >= bar_seconds:
            bars.append(bar_close)
            bar_start = epochs[i]
        bar_close = prices[i]

    # Append the last bar
    bars.append(bar_close)
    return bars


def calibrate_from_ticks_csv(
    csv_path: str | Path,
    symbol: str,
    price_column: str = "price",
    delimiter: str = ",",
    bar_seconds: int = 60,
) -> CalibrationResult:
    """Calibrate EGARCH parameters from a tick CSV file.

    The CSV should have at least 'epoch' and 'price' columns.
    Ticks are resampled into ``bar_seconds``-second bars before
    fitting so the return scale matches the online forecaster's
    expectation (tick-level returns are too small for stable MLE).
    """
    import csv as csv_mod

    epochs: list[float] = []
    prices: list[float] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        # Tolerate headerless CSVs (epoch,symbol,price,...) as written by
        # the collector, plus header'd files from the migrate tools.
        first_line = f.readline()
        f.seek(0)
        stripped = first_line.strip().lower()
        has_header = stripped.startswith(("epoch", "symbol", "price"))
        epoch_idx, price_idx = 0, 2  # enriched format: epoch,symbol,price,...
        reader = csv_mod.reader(f, delimiter=delimiter)
        if has_header:
            header = next(reader, None) or []
            if "epoch" in header:
                epoch_idx = header.index("epoch")
            if price_column in header:
                price_idx = header.index(price_column)
        for row in reader:
            if not row:
                continue
            if len(row) == 2:
                e_raw, p_raw = row[0], row[1]  # legacy epoch,price
            elif len(row) > max(epoch_idx, price_idx):
                e_raw, p_raw = row[epoch_idx], row[price_idx]
            else:
                continue
            try:
                e = float(e_raw)
                p = float(p_raw)
                if p > 0:
                    epochs.append(e)
                    prices.append(p)
            except (ValueError, IndexError):
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

    # Resample ticks to bars for stable calibration
    bar_prices = _resample_to_bars(epochs, prices, bar_seconds)
    if len(bar_prices) < 51:
        # Fall back to raw ticks if too few bars
        bar_prices = prices

    return fit_egarch(np.array(bar_prices), symbol=symbol)


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


def _params_at_bounds(result: CalibrationResult) -> bool:
    """Check if fitted parameters hit optimizer bounds (degenerate fit).

    An optimizer can report ``convergence=True`` while parameters are
    stuck at their bounds — this is a degenerate fit, not a good one.
    The on-disk R_75/R_100 calibration had beta pinned exactly at its
    0.01 floor (persistence ~0.03, i.e. NO volatility clustering at all),
    and it slipped past the old guard (which only rejected when 2+ params
    sat at bounds).  We now reject on:
      1. any single parameter at a bound, OR
      2. persistence below 0.05 (no vol clustering to model), OR
      3. a long-run vol absurdly far from the realized vol.

    Bounds (matching fit_egarch):
        omega: [-30, 2], alpha: [0.001, 0.95], beta: [0.01, 0.999], gamma: [-0.99, 0.99]
    """
    if _degenerate_params(
        result.omega, result.alpha, result.beta, result.gamma,
        result.persistence, result.long_run_vol, result.realized_vol,
    ):
        return True
    # An absurd per-observation NLL is also degenerate even when the
    # parameters alone look sane — an optimizer blow-up or the
    # stability-penalty basin (measured: the R_100 full-corpus refit
    # reported a predicate-clean fit at +2500 per obs).
    if result.n_observations > 0 and math.isfinite(result.negative_log_likelihood):
        per_obs = result.negative_log_likelihood / result.n_observations
        if per_obs > ABSURD_PER_OBS_NLL:
            return True
    return False


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
        if _params_at_bounds(result):
            # Optimizer hit bounds — degenerate fit, use defaults
            return None
        return result.to_garch_state()
    except (json.JSONDecodeError, KeyError, OSError):
        # Corrupted or unreadable file — use defaults
        return None
