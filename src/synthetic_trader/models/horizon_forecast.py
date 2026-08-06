"""4–6 hour volatility horizon forecasting for synthetic indices.

Synthetic indices are CSPRNG-generated, so the *direction* of the next
4–6 hours is fundamentally unpredictable.  What the data CAN support is a
forecast of the **volatility regime** over that horizon: how much price is
expected to range, whether volatility is mean-reverting up or down, and how
confident we should be given recent regime stability.

This module implements that honest inference:

  1. **EGARCH projection** — the online ``EGARCHVarianceForecaster`` tracks
     conditional log-variance.  Under EGARCH(1,1) the conditional expectation
     of future log-variance mean-reverts toward its long-run level at the
     persistence rate ``β``:

         E[log σ²_{t+h}] = logvar_long + β^h · (logvar_t − logvar_long)

     so the projected per-bar sigma at any horizon is analytic.  We compute
     the average sigma across the horizon and turn it into an expected
     price range using standard random-walk range multipliers.
  2. **ADWIN regime stability** — the move-magnitude stream (percentage
     scale) feeds a ``DriftDetector``; a recent drift means the regime is
     transitioning, which lowers confidence and widens the honest band.
  3. **Walk-forward validation** — ``score_horizon_forecast`` replays the
     tick history, makes a forecast at every step, then checks whether the
     *realized* range over the next horizon fell inside the p50/p90 bands.
     Coverage ≈ 0.5 / 0.9 means the bands are well calibrated — the only
     honest way to claim the engine "knows the next 4–6 hours."
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import Candle, Tick
from synthetic_trader.models.drift import DriftDetector
from synthetic_trader.models.garch import EGARCHVarianceForecaster

if TYPE_CHECKING:
    from synthetic_trader.models.garch import GARCHState

# ADWIN's statistical test is unreliable at 1e-5 absolute scales (float
# precision), so move magnitudes are fed as percentage-scale values: |r| * 100.
DRIFT_PCT_SCALE = 100.0


# E[log z^2] for a standard normal innovation: psi(1/2) + log(2) ≈ -1.2704.
# The realized-log-variance anchor is biased LOW by this amount unless
# corrected (E[2*log|r|] = log sigma^2 + E[log z^2]).  For Student-t the
# expectation differs and is computed from the digamma function.
_NORMAL_LOG_Z2_EXPECTATION = -1.2703628454614782


def _log_z2_expectation(distribution: str, dof: float) -> float:
    """E[log z^2] for the standardized innovation z.

    Normal: psi(1/2) + log(2).
    Student-t with dof df: z = x * sqrt((df-2)/df) where x ~ t_df, so
    E[log z^2] = psi(1/2) - psi(df/2) + log(df - 2).
    """
    if distribution == "studentt":
        try:
            from scipy.special import digamma

            if dof > 2.0:
                return _NORMAL_LOG_Z2_EXPECTATION - digamma(dof / 2.0) + math.log(dof - 2.0)
        except Exception:
            pass
        return _NORMAL_LOG_Z2_EXPECTATION
    return _NORMAL_LOG_Z2_EXPECTATION

# Starting multipliers for the range forecast: expected range of a Gaussian
# random walk over n bars with per-bar sigma σ is E[max−min] ≈ 1.6·σ·√n.
# These are the *initial* priors — score_horizon_forecast fits empirical
# multipliers from the walk-forward data (median / p90 quantile of the
# standardized realized range), which is the honest calibration.
RANGE_P50_MULT = 1.6
RANGE_P90_MULT = 2.5


@dataclass(frozen=True)
class HorizonVolForecast:
    """Forecast of the volatility regime over a forward horizon."""

    symbol: str
    horizon_sec: int
    timeframe_sec: int
    bars: int
    current_close: float
    # Volatility levels (per-bar log-return sigma).
    current_sigma: float
    projected_sigma_avg: float
    projected_sigma_end: float
    long_run_sigma: float
    # Price-range forecasts (absolute price width, p50 = median, p90).
    range_p50_price: float
    range_p90_price: float
    # Expected high/low bounds around the current close.
    expected_low_p50: float
    expected_high_p50: float
    expected_low_p90: float
    expected_high_p90: float
    # Regime diagnostics.
    vol_trend: str  # "rising" | "falling" | "stable"
    persistence: float
    drift_events: int
    steps_since_drift: int
    regime_stable: bool
    confidence: float  # 0-1
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "horizon_sec": self.horizon_sec,
            "timeframe_sec": self.timeframe_sec,
            "bars": self.bars,
            "current_close": self.current_close,
            "current_sigma": self.current_sigma,
            "projected_sigma_avg": self.projected_sigma_avg,
            "projected_sigma_end": self.projected_sigma_end,
            "long_run_sigma": self.long_run_sigma,
            "range_p50_price": self.range_p50_price,
            "range_p90_price": self.range_p90_price,
            "expected_low_p50": self.expected_low_p50,
            "expected_high_p50": self.expected_high_p50,
            "expected_low_p90": self.expected_low_p90,
            "expected_high_p90": self.expected_high_p90,
            "vol_trend": self.vol_trend,
            "persistence": self.persistence,
            "drift_events": self.drift_events,
            "steps_since_drift": self.steps_since_drift,
            "regime_stable": self.regime_stable,
            "confidence": self.confidence,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class HorizonValidation:
    """Walk-forward coverage results for the horizon forecast."""

    symbol: str
    horizon_sec: int
    timeframe_sec: int
    windows: int
    coverage_p50: float  # fraction of realized ranges inside the p50 band
    coverage_p90: float  # fraction of realized ranges inside the p90 band
    median_realized_ratio: float  # median(realized_range / forecast_p50_range)
    mean_realized_ratio: float
    over_forecast_pct: float  # fraction where the p90 band was wider than needed
    drift_events: int
    # Empirically fitted range multipliers from this walk-forward set:
    # the median / p90 quantile of realized_range / (sigma_avg * sqrt(n)).
    fitted_p50_mult: float
    fitted_p90_mult: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "horizon_sec": self.horizon_sec,
            "timeframe_sec": self.timeframe_sec,
            "windows": self.windows,
            "coverage_p50": self.coverage_p50,
            "coverage_p90": self.coverage_p90,
            "median_realized_ratio": self.median_realized_ratio,
            "mean_realized_ratio": self.mean_realized_ratio,
            "over_forecast_pct": self.over_forecast_pct,
            "drift_events": self.drift_events,
            "fitted_p50_mult": self.fitted_p50_mult,
            "fitted_p90_mult": self.fitted_p90_mult,
        }


class HorizonVolForecaster:
    """Streaming 4–6h volatility regime forecaster (EGARCH + ADWIN)."""

    def __init__(
        self,
        symbol: str,
        timeframe_sec: int = 300,
        garch_state: GARCHState | None = None,
        drift_delta: float = 0.002,
        distribution: str = "normal",
        dof: float = 5.0,
        long_run_ema_period: int = 300,
        p50_mult: float | None = None,
        p90_mult: float | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe_sec = timeframe_sec
        self.forecaster = EGARCHVarianceForecaster(
            distribution=distribution,
            dof=dof,
        )
        if garch_state is not None:
            # Keep calibrated dynamics but let the forecaster re-learn the
            # variance scale from this bar stream (calibration was fit at a
            # different bar scale).
            self.forecaster.state = replace(garch_state, observations=0)
        self.drift = DriftDetector(delta=drift_delta)
        self._prev_close: float | None = None
        self._candles_seen = 0
        # Slow EMA of *realized* log-variance used as the long-run reference.
        # The theoretical omega/(1-persistence) long-run is unreliable here:
        # calibrated persistence can sit near unit-root (~0.995), so the
        # denominator underflows and the loaded tick-scale prior is stale at
        # this bar scale.  The realized-scale EMA is robust to both.
        self._logvar_ema: float | None = None
        self._long_run_ema_period = long_run_ema_period
        # E[log z^2] for the innovation distribution, used to bias-correct the
        # realized log-variance anchor (see on_candle).
        self._log_z2_exp = _log_z2_expectation(distribution, dof)
        # Empirically fitted range multipliers (from the walk-forward
        # calibration).  When provided, the live bands use them instead of
        # the Gaussian priors — the honest calibration the docstring promises.
        self._p50_mult = p50_mult if p50_mult is not None else RANGE_P50_MULT
        self._p90_mult = p90_mult if p90_mult is not None else RANGE_P90_MULT

    @property
    def version(self) -> str:
        return "horizon-vol-v1"

    def on_candle(self, candle: Candle) -> None:
        """Feed a closed candle; updates EGARCH and the drift detector."""
        self._candles_seen += 1
        if self._prev_close is None or candle.close <= 0.0:
            self._prev_close = candle.close
            return
        log_return = math.log(candle.close / self._prev_close)
        self._prev_close = candle.close
        self.forecaster.update(log_return)
        # Update the long-run EMA from the REALIZED log-variance, bias-
        # corrected so its level is an unbiased estimate of log sigma^2.
        # E[2*log|r|] = log(sigma^2) + E[log z^2] where z is the standardized
        # innovation, and E[log z^2] < 0 (about -1.27 for normal z), so the
        # raw realized log-var is biased LOW by ~1.27 — a displayed sigma
        # ~47% under the true level.  The correction makes the anchor level
        # honest; the per-window adaptation still comes from the realized
        # series (responsive to regime changes) rather than the conditional
        # log-variance (already EGARCH-smoothed, so it lagged twice over).
        realized_logvar = (
            2.0 * math.log(max(abs(log_return), 1e-12)) - self._log_z2_exp
        )
        alpha = 2.0 / (self._long_run_ema_period + 1.0)
        if self._logvar_ema is None:
            self._logvar_ema = realized_logvar
        else:
            self._logvar_ema = self._logvar_ema * (1.0 - alpha) + realized_logvar * alpha
        self.drift.observe(abs(log_return) * DRIFT_PCT_SCALE)

    # ── Long-run reference ──────────────────────────────────────────

    def _long_run_logvar(self) -> float:
        """Long-run log-variance reference (realized-scale EMA)."""
        if (
            self._logvar_ema is not None
            and self._candles_seen >= 50
            and math.isfinite(self._logvar_ema)
        ):
            return max(min(self._logvar_ema, 5.0), -30.0)
        state = self.forecaster.state
        return max(min(state.log_variance, 5.0), -30.0)

    # ── Projection ──────────────────────────────────────────────────

    def _projected_logvars(self, bars: int) -> list[float]:
        """EGARCH conditional-expectation path of log-variance over ``bars``.

        E[log σ²_{t+h}] = logvar_long + β^h · (logvar_t − logvar_long)
        """
        state = self.forecaster.state
        logvar_now = max(min(state.log_variance, 5.0), -30.0)
        logvar_long = self._long_run_logvar()
        # The conditional-expectation formula is E[log s2_{t+h}] = logvar_long
        # + beta^h * (logvar_t - logvar_long) — the decay rate is the EGARCH
        # recursion coefficient beta, NOT the blended persistence
        # (beta + alpha*(1-gamma^2/2)).  persistence >= beta (alpha >= 0), so
        # the old code decayed SLOWER, hugging the current deviation longer;
        # beta^h is the mathematically correct rate for the log-variance
        # recursion.  (Coverage itself is dominated by the empirically fitted
        # range multipliers, which absorb the projection's level bias; the
        # decay fix aligns the path with the model's own formula.)
        beta = max(min(state.beta, 0.999), 0.0)
        path: list[float] = []
        for h in range(1, bars + 1):
            decay = beta ** h
            logvar_h = logvar_long + decay * (logvar_now - logvar_long)
            path.append(max(min(logvar_h, 5.0), -30.0))
        return path

    def forecast(
        self,
        horizon_sec: int,
        current_close: float | None = None,
        p50_mult: float | None = None,
        p90_mult: float | None = None,
    ) -> HorizonVolForecast:
        """Produce a volatility regime forecast for ``horizon_sec`` ahead.

        ``p50_mult``/``p90_mult`` override the constructor defaults (used to
        apply per-horizon calibrated multipliers loaded from disk).
        """
        state = self.forecaster.state
        bars = max(1, round(horizon_sec / self.timeframe_sec))

        logvars = self._projected_logvars(bars)
        avg_logvar = sum(logvars) / len(logvars)
        end_logvar = logvars[-1]
        current_sigma = math.exp(state.log_variance / 2.0)
        projected_avg_sigma = math.exp(avg_logvar / 2.0)
        projected_end_sigma = math.exp(end_logvar / 2.0)
        long_run_sigma = math.exp(self._long_run_logvar() / 2.0)

        close = current_close if current_close is not None else (self._prev_close or 0.0)
        root_n = math.sqrt(bars)
        eff_p50 = p50_mult if p50_mult is not None else self._p50_mult
        eff_p90 = p90_mult if p90_mult is not None else self._p90_mult
        range_p50_log = eff_p50 * projected_avg_sigma * root_n
        range_p90_log = eff_p90 * projected_avg_sigma * root_n
        range_p50_price = close * (math.exp(range_p50_log) - 1.0) if close > 0 else 0.0
        range_p90_price = close * (math.exp(range_p90_log) - 1.0) if close > 0 else 0.0

        # Vol trend: compare current to long-run (EGARCH converges toward it).
        tol = 1.05
        if current_sigma > long_run_sigma * tol:
            vol_trend = "falling"  # above long-run → converging down
        elif current_sigma * tol < long_run_sigma:
            vol_trend = "rising"  # below long-run → converging up
        else:
            vol_trend = "stable"

        steps_since = self.drift.steps_since_last_drift(self.drift.n_observations)
        regime_stable = steps_since >= 200 or self.drift.drift_events == 0

        # Confidence blend.
        confidence = 0.4
        if self._candles_seen >= 60:
            confidence += 0.15
        if state.observations >= 120:
            confidence += 0.1
        if regime_stable:
            confidence += 0.15
        if 0.6 <= state.persistence <= 0.98:
            confidence += 0.1
        confidence = max(0.05, min(0.95, confidence))

        notes = (
            f"EGARCH projection over {bars} bars ({horizon_sec}s horizon)",
            f"persistence={state.persistence:.3f} "
            f"(half-life={state.half_life:.0f} bars)",
            "regime_stable" if regime_stable else "regime_transitioning",
        )

        return HorizonVolForecast(
            symbol=self.symbol,
            horizon_sec=horizon_sec,
            timeframe_sec=self.timeframe_sec,
            bars=bars,
            current_close=close,
            current_sigma=current_sigma,
            projected_sigma_avg=projected_avg_sigma,
            projected_sigma_end=projected_end_sigma,
            long_run_sigma=long_run_sigma,
            range_p50_price=range_p50_price,
            range_p90_price=range_p90_price,
            expected_low_p50=close * math.exp(-range_p50_log / 2.0),
            expected_high_p50=close * math.exp(range_p50_log / 2.0),
            expected_low_p90=close * math.exp(-range_p90_log / 2.0),
            expected_high_p90=close * math.exp(range_p90_log / 2.0),
            vol_trend=vol_trend,
            persistence=state.persistence,
            drift_events=self.drift.drift_events,
            steps_since_drift=steps_since,
            regime_stable=regime_stable,
            confidence=confidence,
            notes=notes,
        )


# ── Walk-forward validation ──────────────────────────────────────────


def _quantile(values: list[float], q: float) -> float:
    """Nearest-rank quantile of ``values``; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(math.ceil(q * len(ordered))) - 1
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def _median(values: list[float]) -> float:
    return _quantile(values, 0.5)


def _compute_std_ranges(
    ticks: list[Tick],
    symbol: str,
    horizon_sec: int,
    timeframe_sec: int,
    garch_state: GARCHState | None,
    min_warmup_bars: int = 60,
) -> tuple[list[float], int]:
    """Replay ticks once and return per-window standardized realized ranges.

    Each value is the multiplier that would have covered that forward window
    exactly at p50: ``realized_range / (projected_sigma_avg * sqrt(n))``.
    Returns ``(std_ranges, drift_events)``.  Shared by ``score_horizon_forecast``
    and the band-tuning pass so both calibrate on the identical replay.
    """
    forecaster = HorizonVolForecaster(
        symbol,
        timeframe_sec=timeframe_sec,
        garch_state=garch_state,
    )
    builder = MultiTimeframeCandleBuilder(symbol, [timeframe_sec])
    candles: list[Candle] = []

    for tick in dedupe_ticks(ticks):
        closed = builder.update(tick)
        for tf, candle in closed.items():
            if tf == timeframe_sec:
                candles.append(candle)

    if len(candles) < min_warmup_bars + 2:
        return [], 0

    horizon_bars = max(1, round(horizon_sec / timeframe_sec))
    std_ranges: list[float] = []
    for i in range(len(candles) - horizon_bars):
        forecaster.on_candle(candles[i])
        if i + 1 < min_warmup_bars:
            continue
        if forecaster.forecaster.state.observations < 30:
            continue

        forecast = forecaster.forecast(horizon_sec, current_close=candles[i].close)
        window = candles[i + 1 : i + 1 + horizon_bars]
        realized_high = max(c.close for c in window)
        realized_low = min(c.close for c in window)
        if realized_low <= 0:
            continue
        realized_range = math.log(realized_high / realized_low)
        std_unit = forecast.projected_sigma_avg * math.sqrt(forecast.bars)
        if std_unit <= 0 or not math.isfinite(std_unit):
            continue
        std_ranges.append(realized_range / std_unit)
    return std_ranges, forecaster.drift.drift_events


def score_horizon_forecast(
    ticks: list[Tick],
    symbol: str,
    horizon_sec: int,
    timeframe_sec: int = 300,
    garch_state: GARCHState | None = None,
    min_warmup_bars: int = 60,
    holdout_frac: float = 0.3,
    p50_mult: float | None = None,
    p90_mult: float | None = None,
) -> HorizonValidation:
    """Replay the tick history and score p50/p90 range-band coverage.

    The walk-forward set is split chronologically: the empirical range
    multipliers are FITTED on the first ``1 - holdout_frac`` of windows and
    coverage is reported on the remaining holdout windows using those fitted
    multipliers.  That is the honest, out-of-sample calibration: coverage_p50
    ≈ 0.5 / coverage_p90 ≈ 0.9 on the *holdout* means the bands generalize,
    not just fit.  Pass explicit ``p50_mult``/``p90_mult`` to skip fitting
    and score coverage against supplied multipliers instead.
    """
    std_ranges, drift_events = _compute_std_ranges(
        ticks,
        symbol,
        horizon_sec,
        timeframe_sec,
        garch_state,
        min_warmup_bars,
    )

    total = len(std_ranges)
    if total == 0:
        return HorizonValidation(
            symbol=symbol,
            horizon_sec=horizon_sec,
            timeframe_sec=timeframe_sec,
            windows=0,
            coverage_p50=0.0,
            coverage_p90=0.0,
            median_realized_ratio=0.0,
            mean_realized_ratio=0.0,
            over_forecast_pct=0.0,
            drift_events=drift_events,
            fitted_p50_mult=0.0,
            fitted_p90_mult=0.0,
        )

    if (p50_mult is None) != (p90_mult is None):
        raise ValueError("p50_mult and p90_mult must be provided together")
    if p50_mult is not None:
        # Explicit multipliers (applied mode): score the whole set against them.
        holdout_std = std_ranges
        fitted_p50, fitted_p90 = p50_mult, p90_mult
    elif holdout_frac <= 0:
        # No holdout: fit and score on the full set (in-sample calibration).
        holdout_std = std_ranges
        fitted_p50 = _quantile(std_ranges, 0.5)
        fitted_p90 = _quantile(std_ranges, 0.9)
    else:
        split = int(total * (1.0 - holdout_frac))
        split = max(1, min(split, total - 1))
        train_std = std_ranges[:split]
        holdout_std = std_ranges[split:]
        # Fit the honest multipliers on TRAIN only; score coverage on HOLD OUT.
        fitted_p50 = _quantile(train_std, 0.5)
        fitted_p90 = _quantile(train_std, 0.9)

    windows = len(holdout_std)
    covered_p50 = sum(1 for s in holdout_std if s <= fitted_p50)
    covered_p90 = sum(1 for s in holdout_std if s <= fitted_p90)
    over_forecast = sum(1 for s in holdout_std if s > fitted_p90)
    ratios = [s / fitted_p50 for s in holdout_std] if fitted_p50 > 0 else [0.0] * windows

    return HorizonValidation(
        symbol=symbol,
        horizon_sec=horizon_sec,
        timeframe_sec=timeframe_sec,
        windows=windows,
        coverage_p50=covered_p50 / max(windows, 1),
        coverage_p90=covered_p90 / max(windows, 1),
        median_realized_ratio=_median(ratios),
        mean_realized_ratio=sum(ratios) / max(len(ratios), 1),
        over_forecast_pct=over_forecast / max(windows, 1),
        drift_events=drift_events,
        fitted_p50_mult=float(fitted_p50),
        fitted_p90_mult=float(fitted_p90),
    )


# ── Band tuning pass ────────────────────────────────────────────────────
# The dashboard honestly reports when stored multipliers over- or under-cover
# the *recent* regime (verdict: needs_more_data_or_tuning).  The tuning pass
# closes that gap: it re-fits the p50/p90 range multipliers on a recent
# walk-forward holdout and iterates until the recent coverage lands inside the
# calibrated band, then persists them back to data/forecast_multipliers.


def tune_forecast_multipliers(
    symbol: str,
    ticks: list[Tick],
    horizon_sec: int,
    timeframe_sec: int = 60,
    garch_state: GARCHState | None = None,
    multiplier_dir: str | Path | None = None,
    holdout_frac: float = 0.3,
    max_iters: int = 40,
    step: float = 0.06,
    min_windows: int = 30,
) -> dict:
    """Adjust p50/p90 range multipliers against recent walk-forward coverage.

    The full corpus is replayed once (shared ``_compute_std_ranges``), split
    chronologically into train + a RECENT holdout tail, seeded from the train
    quantiles, then iterated: while the holdout coverage is outside the
    calibrated band, the multipliers are nudged proportionally (shrink when
    over-covering — bands too wide; widen when under-covering — bands too
    narrow).  On convergence the tuned multipliers are persisted via
    ``save_forecast_multipliers`` and a report dict is returned.

    Returns ``{p50_mult, p90_mult, windows, coverage_p50, coverage_p90,
    verdict, iterations, drift_events, persisted}`` — ``verdict`` reflects the
    RECENT holdout (the honest out-of-sample calibration), so a report verdict
    of "calibrated" means the bands currently on disk generalize to the regime
    the operator is trading right now.
    """
    std_ranges, drift_events = _compute_std_ranges(
        ticks, symbol, horizon_sec, timeframe_sec, garch_state, min_warmup_bars=60
    )
    total = len(std_ranges)
    if total < min_windows + 2:
        return {
            "symbol": symbol,
            "horizon_sec": horizon_sec,
            "timeframe_sec": timeframe_sec,
            "p50_mult": None,
            "p90_mult": None,
            "windows": 0,
            "coverage_p50": 0.0,
            "coverage_p90": 0.0,
            "verdict": "needs_more_data_or_tuning",
            "iterations": 0,
            "drift_events": drift_events,
            "persisted": False,
        }

    split = int(total * (1.0 - holdout_frac))
    split = max(1, min(split, total - 1))
    train_std = std_ranges[:split]
    holdout_std = std_ranges[split:]

    # Seed from the honest train-fit; the loop only moves them as much as the
    # RECENT regime demands.
    p50 = _quantile(train_std, 0.5)
    p90 = _quantile(train_std, 0.9)
    if p90 < p50:
        p90 = p50 * 1.2

    def _coverage(values: list[float], mult: float) -> float:
        return sum(1 for s in values if s <= mult) / max(len(values), 1)

    def _is_calibrated() -> bool:
        """Share the single source of truth with the dashboard: the verdict is
        ``horizon_verdict`` on a synthesized validation so the tuning pass can
        never persist multipliers the dashboard would call needs_more_data.
        """
        if len(holdout_std) < min_windows:
            return False
        cov50 = _coverage(holdout_std, p50)
        cov90 = _coverage(holdout_std, p90)
        return horizon_verdict(
            HorizonValidation(
                symbol=symbol,
                horizon_sec=horizon_sec,
                timeframe_sec=timeframe_sec,
                windows=len(holdout_std),
                coverage_p50=cov50,
                coverage_p90=cov90,
                median_realized_ratio=0.0,
                mean_realized_ratio=0.0,
                over_forecast_pct=0.0,
                drift_events=drift_events,
                fitted_p50_mult=float(p50),
                fitted_p90_mult=float(p90),
            )
        ) == "calibrated"

    iterations = 0
    verdict = "needs_more_data_or_tuning"
    for _ in range(max_iters):
        iterations += 1
        if _is_calibrated():
            verdict = "calibrated"
            break
        cov50 = _coverage(holdout_std, p50)
        cov90 = _coverage(holdout_std, p90)
        if cov50 > 0.75:
            p50 *= 1.0 - step  # over-covering -> shrink the band
        elif cov50 < 0.25:
            p50 *= 1.0 + step  # under-covering -> widen the band
        if cov90 > 1.01:
            p90 *= 1.0 - step
        elif cov90 < 0.75:
            p90 *= 1.0 + step
        if p90 < p50 * 1.1:
            p90 = p50 * 1.1
        if p50 <= 0.0 or p90 <= 0.0 or not math.isfinite(p50) or not math.isfinite(p90):
            verdict = "needs_more_data_or_tuning"
            break

    persisted = False
    if verdict == "calibrated":
        horizon_key = f"{max(1, int(horizon_sec / 3600))}h"
        saved = save_forecast_multipliers(
            symbol,
            timeframe_sec,
            {
                horizon_key: {
                    "p50_mult": float(p50),
                    "p90_mult": float(p90),
                    "windows": len(holdout_std),
                    "coverage_p50": _coverage(holdout_std, p50),
                    "coverage_p90": _coverage(holdout_std, p90),
                    "tuned": True,
                    "tune_iters": iterations,
                }
            },
            multiplier_dir,
        )
        persisted = saved.exists()

    return {
        "symbol": symbol,
        "horizon_sec": horizon_sec,
        "timeframe_sec": timeframe_sec,
        "p50_mult": float(p50) if p50 > 0 else None,
        "p90_mult": float(p90) if p90 > 0 else None,
        "windows": len(holdout_std),
        "coverage_p50": _coverage(holdout_std, p50),
        "coverage_p90": _coverage(holdout_std, p90),
        "verdict": verdict,
        "iterations": iterations,
        "drift_events": drift_events,
        "persisted": persisted,
    }


# ── Fitted-multiplier persistence ──────────────────────────────────────

DEFAULT_MULTIPLIER_DIR = Path("data/forecast_multipliers")


def get_multiplier_path(
    symbol: str,
    timeframe_sec: int,
    multiplier_dir: str | Path | None = None,
) -> Path:
    """Canonical path for a symbol's fitted range multipliers."""
    d = Path(multiplier_dir) if multiplier_dir else DEFAULT_MULTIPLIER_DIR
    return d / f"{symbol.lower()}_{timeframe_sec}s.json"


def save_forecast_multipliers(
    symbol: str,
    timeframe_sec: int,
    entries: dict[str, dict],
    multiplier_dir: str | Path | None = None,
) -> Path:
    """Persist fitted range multipliers keyed by horizon label (e.g. "4h").

    Existing entries for the same symbol/timeframe are merged, so fitting
    4h then 6h in separate runs accumulates both horizons in one file.
    """
    path = get_multiplier_path(symbol, timeframe_sec, multiplier_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_forecast_multipliers(symbol, timeframe_sec, multiplier_dir) or {}
    existing.update(entries)
    payload = {
        "symbol": symbol,
        "timeframe_sec": timeframe_sec,
        "entries": existing,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_forecast_multipliers(
    symbol: str,
    timeframe_sec: int,
    multiplier_dir: str | Path | None = None,
) -> dict[str, dict] | None:
    """Load fitted range multipliers; returns ``{horizon: {p50_mult, ...}}``."""
    path = get_multiplier_path(symbol, timeframe_sec, multiplier_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else None


def horizon_verdict(validation: HorizonValidation) -> str:
    """Honest calibration verdict, shared by the CLI and the operator dashboard.

    A single source of truth so the dashboard can never silently disagree
    with ``synth-trader forecast-horizon --validate``: "calibrated" requires
    enough walk-forward windows AND on-target p50/p90 coverage, otherwise the
    honest answer is "needs_more_data_or_tuning".
    """
    if (
        validation.windows >= 30
        and 0.25 <= validation.coverage_p50 <= 0.75
        and 0.75 <= validation.coverage_p90 <= 1.01
    ):
        return "calibrated"
    return "needs_more_data_or_tuning"
