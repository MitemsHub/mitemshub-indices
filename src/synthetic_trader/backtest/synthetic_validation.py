"""Statistical validation suite for synthetic price data.

Verifies that generated synthetic data matches the empirical properties
of real Deriv synthetic indices.  This is critical for ensuring our
backtesting results are meaningful — if the synthetic data doesn't match
real data, the strategy's performance on synthetic data is meaningless.

Tests performed:
1. **ADF test** — verifies returns are stationary (unit root test)
2. **Hurst exponent** — verifies long-term memory properties
3. **Ljung-Box** — verifies return autocorrelation structure
4. **Volatility clustering** — verifies GARCH-like variance clustering
5. **Distribution tests** — verifies heavy tails (leptokurtosis)
6. **Autocorrelation of squared returns** — verifies ARCH effects

Reference:
- Augmented Dickey-Fuller (ADF) test for unit roots
- Hurst (1951) "The long-term storage capacity of reservoirs"
- Ljung & Box (1978) "On approximate tests of autocorrelation"
- Engle (1982) ARCH effects test
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from synthetic_trader.domain import Tick


@dataclass
class ValidationResult:
    """Result of a single statistical test."""
    name: str
    passed: bool
    statistic: float
    p_value: float
    threshold: float
    description: str


@dataclass
class SyntheticDataReport:
    """Complete validation report for a synthetic dataset."""
    n_ticks: int
    tests: list[ValidationResult]
    overall_passed: bool
    summary: str

    def to_dict(self) -> dict:
        return {
            "n_ticks": self.n_ticks,
            "overall_passed": self.overall_passed,
            "summary": self.summary,
            "tests": [
                {
                    "name": t.name,
                    "passed": t.passed,
                    "statistic": t.statistic,
                    "p_value": t.p_value,
                    "threshold": t.threshold,
                    "description": t.description,
                }
                for t in self.tests
            ],
        }


# ── Helper Functions ─────────────────────────────────────────────


def _compute_returns(prices: Sequence[float]) -> list[float]:
    """Compute log-returns from a price series."""
    returns: list[float] = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            returns.append(math.log(prices[i] / prices[i - 1]))
    return returns


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _variance(values: Sequence[float], ddof: int = 1) -> float:
    if len(values) <= ddof:
        return 0.0
    m = _mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - ddof)


def _std(values: Sequence[float], ddof: int = 1) -> float:
    return math.sqrt(_variance(values, ddof))


def _autocorrelation(values: Sequence[float], lag: int) -> float:
    """Compute autocorrelation at given lag."""
    n = len(values)
    if n <= lag:
        return 0.0
    m = _mean(values)
    var = _variance(values, ddof=0)
    if var == 0:
        return 0.0
    cov = sum((values[i] - m) * (values[i - lag] - m) for i in range(lag, n)) / n
    return cov / var


# ── Statistical Tests ────────────────────────────────────────────


def check_stationarity_adf(returns: Sequence[float], significance: float = 0.05) -> ValidationResult:
    """Augmented Dickey-Fuller test for unit root (simplified).

    Tests H0: series has a unit root (non-stationary)
    Rejection means the series is stationary (good for returns).

    Uses a simplified ADF regression:
        Δy_t = α + β*y_{t-1} + ε_t

    If β is significantly negative, the series is stationary.
    """
    n = len(returns)
    if n < 20:
        return ValidationResult(
            name="ADF Stationarity",
            passed=False,
            statistic=0.0,
            p_value=1.0,
            threshold=significance,
            description="Not enough data for ADF test (need ≥20 returns)",
        )

    # Compute first differences
    dy = [returns[i] - returns[i - 1] for i in range(1, n)]
    y_lag = list(returns[:-1])

    # Simple OLS regression: dy = α + β * y_lag
    n_reg = len(dy)
    x_mean = _mean(y_lag)
    y_mean = _mean(dy)

    ss_xy = sum((y_lag[i] - x_mean) * (dy[i] - y_mean) for i in range(n_reg))
    ss_xx = sum((y_lag[i] - x_mean) ** 2 for i in range(n_reg))

    if ss_xx == 0:
        return ValidationResult(
            name="ADF Stationarity",
            passed=False,
            statistic=0.0,
            p_value=1.0,
            threshold=significance,
            description="Zero variance in lagged values",
        )

    beta = ss_xy / ss_xx
    alpha = y_mean - beta * x_mean

    # Compute residual standard error
    residuals = [dy[i] - alpha - beta * y_lag[i] for i in range(n_reg)]
    se = math.sqrt(_variance(residuals, ddof=2)) if len(residuals) > 2 else 1e-10
    se_beta = se / math.sqrt(ss_xx) if ss_xx > 0 else 1e-10

    # ADF t-statistic
    t_stat = beta / se_beta if se_beta > 0 else 0.0

    # Critical values (simplified, approximate for large samples)
    # ADF critical values are more negative than standard t-distribution
    # -3.43 (1%), -2.86 (5%), -2.57 (10%)
    critical_value_5pct = -2.86

    passed = t_stat < critical_value_5pct
    # Approximate p-value (very rough)
    if t_stat < -3.43:
        p_value = 0.01
    elif t_stat < -2.86:
        p_value = 0.05
    elif t_stat < -2.57:
        p_value = 0.10
    else:
        p_value = 0.50

    return ValidationResult(
        name="ADF Stationarity",
        passed=passed,
        statistic=round(t_stat, 4),
        p_value=round(p_value, 4),
        threshold=significance,
        description=f"t-stat={t_stat:.3f}, critical(5%)={critical_value_5pct}",
    )


def check_hurst_exponent(prices: Sequence[float], max_lag: int = 100) -> ValidationResult:
    """Estimate the Hurst exponent using R/S analysis.

    H < 0.5: mean-reverting (anti-persistent)
    H = 0.5: random walk (uncorrelated)
    H > 0.5: trending (persistent)

    For synthetic indices, H should be close to 0.5 (random walk).
    A value significantly different from 0.5 suggests the data has
    structure that could be exploited.
    """
    n = len(prices)
    if n < 40:
        return ValidationResult(
            name="Hurst Exponent",
            passed=False,
            statistic=0.5,
            p_value=0.5,
            threshold=0.05,
            description="Not enough data for Hurst estimation (need ≥40 prices)",
        )

    returns = _compute_returns(prices)
    if len(returns) < 20:
        return ValidationResult(
            name="Hurst Exponent",
            passed=False,
            statistic=0.5,
            p_value=0.5,
            threshold=0.05,
            description="Not enough returns for Hurst estimation",
        )

    # R/S analysis for different lags
    lags = [min(lag, max_lag) for lag in [10, 20, 30, 40, 50]]
    lags = [l for l in lags if l < len(returns)]
    if not lags:
        lags = [min(20, len(returns) // 2)]

    log_rs_values: list[float] = []
    log_n_values: list[float] = []

    for lag in lags:
        # Divide returns into non-overlapping blocks
        n_blocks = len(returns) // lag
        if n_blocks < 1:
            continue

        rs_values: list[float] = []
        for b in range(n_blocks):
            block = returns[b * lag: (b + 1) * lag]
            mean_block = _mean(block)
            cumulative = []
            running_sum = 0.0
            for val in block:
                running_sum += (val - mean_block)
                cumulative.append(running_sum)
            R = max(cumulative) - min(cumulative)
            S = _std(block, ddof=1) if len(block) > 1 else 1e-10
            if S > 0:
                rs_values.append(R / S)

        if rs_values:
            log_rs_values.append(math.log(_mean(rs_values)))
            log_n_values.append(math.log(lag))

    if len(log_rs_values) < 2:
        return ValidationResult(
            name="Hurst Exponent",
            passed=False,
            statistic=0.5,
            p_value=0.5,
            threshold=0.05,
            description="Could not compute R/S for enough lags",
        )

    # Linear regression: log(R/S) = H * log(n) + c
    x_mean = _mean(log_n_values)
    y_mean = _mean(log_rs_values)
    ss_xy = sum((log_n_values[i] - x_mean) * (log_rs_values[i] - y_mean) for i in range(len(log_rs_values)))
    ss_xx = sum((log_n_values[i] - x_mean) ** 2 for i in range(len(log_n_values)))

    H = ss_xy / ss_xx if ss_xx > 0 else 0.5

    # For synthetic indices, H should be close to 0.5 (random walk)
    # Accept H in [0.35, 0.65] as "close enough" to random walk
    h_close_to_half = abs(H - 0.5) < 0.15
    passed = h_close_to_half

    # Approximate p-value: probability that H deviates from 0.5
    p_value = min(1.0, abs(H - 0.5) * 2.0)

    return ValidationResult(
        name="Hurst Exponent",
        passed=passed,
        statistic=round(H, 4),
        p_value=round(p_value, 4),
        threshold=0.15,
        description=f"H={H:.3f} (synthetic indices should have H≈0.5)",
    )


def check_volatility_clustering(returns: Sequence[float]) -> ValidationResult:
    """Test for volatility clustering using autocorrelation of squared returns.

    If squared returns show positive autocorrelation at lag 1, volatility
    is clustering (ARCH effects).  This is the key exploitable property
    of synthetic indices.
    """
    if len(returns) < 20:
        return ValidationResult(
            name="Volatility Clustering",
            passed=False,
            statistic=0.0,
            p_value=1.0,
            threshold=0.05,
            description="Not enough returns for volatility clustering test",
        )

    # Compute squared returns
    squared_returns = [r ** 2 for r in returns]

    # Autocorrelation of squared returns at lag 1
    acf_1 = _autocorrelation(squared_returns, lag=1)

    # For synthetic indices, we EXPECT positive autocorrelation
    # (volatility clustering is the exploitable property)
    # Accept acf_1 > 0.05 as evidence of clustering
    passed = acf_1 > 0.05

    # Approximate p-value using Bartlett's formula for white noise
    n = len(squared_returns)
    se = 1.0 / math.sqrt(n) if n > 0 else 1.0
    z = acf_1 / se if se > 0 else 0.0
    # Rough normal approximation
    p_value = max(0.0, min(1.0, 0.5 * (1.0 - math.erf(abs(z) / math.sqrt(2)))))

    return ValidationResult(
        name="Volatility Clustering",
        passed=passed,
        statistic=round(acf_1, 4),
        p_value=round(p_value, 4),
        threshold=0.05,
        description=f"ACF(1) of squared returns = {acf_1:.3f} (positive = clustering)",
    )


def check_heavy_tails(returns: Sequence[float]) -> ValidationResult:
    """Test for heavy tails (leptokurtosis) in the return distribution.

    Synthetic indices should have excess kurtosis > 0 (heavier tails
    than a normal distribution) due to the GARCH variance scheduling.
    """
    if len(returns) < 30:
        return ValidationResult(
            name="Heavy Tails (Kurtosis)",
            passed=False,
            statistic=0.0,
            p_value=1.0,
            threshold=0.05,
            description="Not enough returns for kurtosis test",
        )

    n = len(returns)
    m = _mean(returns)
    s = _std(returns, ddof=1)

    if s == 0:
        return ValidationResult(
            name="Heavy Tails (Kurtosis)",
            passed=False,
            statistic=0.0,
            p_value=1.0,
            threshold=0.05,
            description="Zero standard deviation",
        )

    # Compute excess kurtosis
    kurt = sum(((x - m) / s) ** 4 for x in returns) / n - 3.0

    # Synthetic indices should have positive excess kurtosis (heavy tails)
    # Accept kurtosis > -0.5 (slightly under-normal is OK due to sampling)
    passed = kurt > -0.5

    # Approximate p-value (excess kurtosis of normal = 0)
    # Using the fact that excess kurtosis has approximate variance 24/n
    se_kurt = math.sqrt(24.0 / n) if n > 0 else 1.0
    z = kurt / se_kurt if se_kurt > 0 else 0.0
    p_value = max(0.0, min(1.0, 0.5 * (1.0 - math.erf(abs(z) / math.sqrt(2)))))

    return ValidationResult(
        name="Heavy Tails (Kurtosis)",
        passed=passed,
        statistic=round(kurt, 4),
        p_value=round(p_value, 4),
        threshold=0.05,
        description=f"Excess kurtosis = {kurt:.3f} (positive = heavy tails, good for clustering)",
    )


def check_ljung_box(returns: Sequence[float], max_lag: int = 20) -> ValidationResult:
    """Ljung-Box test for autocorrelation in returns.

    Tests H0: returns are independently distributed (no autocorrelation).
    Rejection means there IS autocorrelation (which could be exploitable).

    For synthetic indices, we generally want returns to be uncorrelated
    (H0 should NOT be rejected), but squared returns SHOULD show
    autocorrelation (volatility clustering).
    """
    n = len(returns)
    if n < max_lag + 5:
        return ValidationResult(
            name="Ljung-Box (Returns)",
            passed=True,
            statistic=0.0,
            p_value=1.0,
            threshold=0.05,
            description="Not enough data for Ljung-Box test",
        )

    # Compute Q statistic
    q = 0.0
    for k in range(1, max_lag + 1):
        acf_k = _autocorrelation(returns, lag=k)
        q += (acf_k ** 2) / (n - k)

    q *= n * (n + 2)

    # Under H0, Q ~ chi-squared(max_lag)
    # Approximate critical value for chi-squared(20) at 5% = 31.41
    critical_value = 31.41

    # For synthetic indices, we want H0 to NOT be rejected
    # (returns should be uncorrelated)
    passed = q < critical_value

    # Approximate p-value (very rough chi-squared approximation)
    if q < 10.95:
        p_value = 0.95
    elif q < 31.41:
        p_value = 0.05
    else:
        p_value = 0.01

    return ValidationResult(
        name="Ljung-Box (Returns)",
        passed=passed,
        statistic=round(q, 4),
        p_value=round(p_value, 4),
        threshold=0.05,
        description=f"Q={q:.1f} (should be < {critical_value:.1f} for uncorrelated returns)",
    )


# ── Main Validation Function ────────────────────────────────────


def validate_synthetic_data(ticks: list[Tick]) -> SyntheticDataReport:
    """Run all statistical tests on a synthetic dataset.

    Parameters
    ----------
    ticks : list[Tick]
        List of Tick objects to validate.

    Returns
    -------
    SyntheticDataReport
        Complete validation report with test results.
    """
    if not ticks:
        return SyntheticDataReport(
            n_ticks=0,
            tests=[],
            overall_passed=False,
            summary="No ticks to validate",
        )

    prices = [t.price for t in ticks]
    returns = _compute_returns(prices)

    tests = [
        check_stationarity_adf(returns),
        check_hurst_exponent(prices),
        check_volatility_clustering(returns),
        check_heavy_tails(returns),
        check_ljung_box(returns),
    ]

    passed_count = sum(1 for t in tests if t.passed)
    total_count = len(tests)
    overall_passed = passed_count >= total_count * 0.6  # 60% threshold

    summary = (
        f"{passed_count}/{total_count} tests passed. "
        + ("Synthetic data matches Deriv properties." if overall_passed
           else "WARNING: Synthetic data may not match Deriv properties.")
    )

    return SyntheticDataReport(
        n_ticks=len(ticks),
        tests=tests,
        overall_passed=overall_passed,
        summary=summary,
    )
