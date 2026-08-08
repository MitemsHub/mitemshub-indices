"""Band-geometry vol-targeting backtest mode (the "band" strategy).

Identical *entry* logic to the vol-reversion fade — EGARCH forecast sigma,
ADWIN drift cooldown, extended-vol gate, and the price-extension ``z_entry``
fade — but the stop/target are placed by :func:`band_levels` (the shared
zero-drawdown band geometry): stop at ``stop_sigma_mult × σ_h`` and target
at ``target_sigma_mult × σ_h`` where ``σ_h`` is the horizon-scaled forecast
sigma over a 1–3h hold.

This is the geometry proposed for live calls (§36).  It is measured here so
the head-to-head verdict (``backtest-vol --compare``) is real data, and it
shares ``band_geometry.band_levels`` with the live path so the two can never
diverge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from synthetic_trader.backtest.engine import BacktestResult
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import (
    Candle,
    Direction,
    FeatureSnapshot,
    Regime,
    Tick,
    TradeSignal,
)
from synthetic_trader.models.drift import DriftDetector
from synthetic_trader.models.garch import EGARCHVarianceForecaster
from synthetic_trader.strategy.band_geometry import (
    BandGeometryConfig,
    band_levels,
)

if TYPE_CHECKING:
    from synthetic_trader.models.garch import GARCHState

STRATEGY_VERSION = "vol-band-v1"

# Same percentage-scale drift feed as the fade (ADWIN is unreliable at
# 1e-5 absolute scales).
DRIFT_PCT_SCALE = 100.0


@dataclass(frozen=True)
class VolBandConfig:
    """Tunable parameters for the band-geometry vol-targeting strategy."""

    # ── Entry gates (identical semantics to the tuned fade) ──────
    ema_period: int = 20
    # Tuned on the 9.5-day R_75 SYN75 corpus with calibrated EGARCH
    # dynamics (§36): z_entry 1.0 / vol gate 1.3 with the 0.3 breakeven
    # trail.  §38 swept the full geometry grid around this cell — the
    # winning cell keeps the same selective gate but tightens the stop to
    # 0.20σ_h and the target to 0.80σ_h with a 1h hold (23 trades,
    # +0.994R/trade vs the §36 default's 21 trades, +0.654R).  The gate is
    # the edge: opening vol_extended_ratio toward 1.0 buys more trades
    # (40-44) but dilutes expectancy to ~+0.44R, and 50+ trades are not
    # reachable on a 9.5-day corpus without destroying the edge.
    z_entry: float = 1.0
    vol_extended_ratio: float = 1.3
    sigma_ema_period: int = 60
    min_revert_signal: float = 0.02
    drift_cooldown_bars: int = 30
    drift_delta: float = 0.002
    warmup_candles: int = 60
    distribution: str = "normal"
    dof: float = 5.0

    # ── Band geometry (zero-drawdown levels, 1–3h hold) ──────────
    # §38 sweep winner: stop 0.20σ_h / target 0.80σ_h / 1h hold.  The
    # tighter stop keeps the zero-drawdown character (breakeven trail
    # converts early drift-outs to ~0R), and the shorter hold resolves
    # calls fast so the empirical gate learns 2× quicker than 2h.
    stop_sigma_mult: float = 0.20
    target_sigma_mult: float = 0.80
    max_hold_sec: int = 3600  # 1h default (§38 sweep winner)
    min_target_rr: float = 2.0
    max_stop_pct: float = 0.015  # 1.5% of price, as a fraction
    # Move the stop to breakeven once MFE reaches this fraction of the
    # planned target distance (converts would-be -1R losses into ~0R exits).
    breakeven_trail_frac: float = 0.3


class VolBandStrategy:
    """Streaming band-geometry strategy driven by EGARCH forecast + ADWIN."""

    def __init__(
        self,
        symbol: str,
        timeframe_sec: int,
        config: VolBandConfig | None = None,
        garch_state: GARCHState | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe_sec = timeframe_sec
        self.config = config or VolBandConfig()
        self.forecaster = EGARCHVarianceForecaster(
            distribution=self.config.distribution,
            dof=self.config.dof,
        )
        if garch_state is not None:
            self.forecaster.state = replace(garch_state, observations=0)
        self.drift = DriftDetector(delta=self.config.drift_delta)
        self._ema: float | None = None
        self._sigma_ema: float | None = None
        self._prev_close: float | None = None
        self._prev_sigma: float | None = None
        self._candles_seen = 0

    @property
    def version(self) -> str:
        return f"{STRATEGY_VERSION}:{self.config.distribution}"

    def on_candle(self, candle: Candle) -> TradeSignal | None:
        """Process one closed candle; returns a band signal or None."""
        self._candles_seen += 1
        if self._prev_close is None or candle.close <= 0.0:
            self._prev_close = candle.close
            self._ema = candle.close
            return None

        log_return = math.log(candle.close / self._prev_close)
        self._prev_close = candle.close
        features = self.forecaster.update(log_return)

        self.drift.observe(abs(log_return) * DRIFT_PCT_SCALE)

        alpha = 2.0 / (self.config.ema_period + 1.0)
        self._ema = (
            candle.close
            if self._ema is None
            else self._ema * (1.0 - alpha) + candle.close * alpha
        )

        sigma = features.get("garch_sigma", 0.0)
        if sigma <= 1e-12:
            return None
        sigma_alpha = 2.0 / (self.config.sigma_ema_period + 1.0)
        self._sigma_ema = (
            sigma
            if self._sigma_ema is None
            else self._sigma_ema * (1.0 - sigma_alpha) + sigma * sigma_alpha
        )

        prev_sigma = self._prev_sigma
        self._prev_sigma = sigma

        if self._candles_seen < self.config.warmup_candles:
            return None
        if self.forecaster.state.observations < 30:
            return None
        steps_since = self.drift.steps_since_last_drift(self.drift.n_observations)
        if steps_since < self.config.drift_cooldown_bars:
            return None
        if prev_sigma is None or prev_sigma <= 1e-12:
            return None
        vol_extended = prev_sigma > self.config.vol_extended_ratio * self._sigma_ema
        if not vol_extended:
            return None
        if self.config.min_revert_signal > 0.0:
            revert = features.get("garch_mean_revert_signal", 0.0)
            if revert < self.config.min_revert_signal:
                return None

        z_dev = math.log(candle.close / self._ema) / prev_sigma
        if z_dev >= self.config.z_entry:
            direction = Direction.SHORT
            direction_str = "sell"
        elif z_dev <= -self.config.z_entry:
            direction = Direction.LONG
            direction_str = "buy"
        else:
            return None

        entry = candle.close
        levels = band_levels(
            entry=entry,
            direction=direction_str,
            sigma_per_bar=prev_sigma,
            bar_sec=self.timeframe_sec,
            hold_horizon_sec=self.config.max_hold_sec,
            config=BandGeometryConfig(
                stop_sigma_mult=self.config.stop_sigma_mult,
                target_sigma_mult=self.config.target_sigma_mult,
                min_target_rr=self.config.min_target_rr,
                max_stop_pct=self.config.max_stop_pct,
                hold_horizon_sec=self.config.max_hold_sec,
            ),
        )
        if levels is None:
            return None

        confidence = min(
            0.95, 0.55 + min(0.35, abs(z_dev) / (self.config.z_entry * 3.0))
        )
        epoch = candle.open_time + candle.timeframe_sec
        snapshot = FeatureSnapshot(
            symbol=self.symbol,
            epoch=float(epoch),
            timeframe_sec=self.timeframe_sec,
            features={**features, "vol_z_dev": z_dev},
            regime=Regime.VOLATILE,
            structure={},
            notes=(
                f"band geometry z_dev={z_dev:.2f} sigma_baseline_ratio={sigma / self._sigma_ema:.2f}",
            ),
        )
        return TradeSignal(
            symbol=self.symbol,
            direction=direction,
            confidence=confidence,
            min_confidence=0.0,
            entry=entry,
            stop_loss=levels.stop_loss,
            take_profit=levels.take_profit,
            horizon_sec=levels.hold_horizon_sec,
            snapshot=snapshot,
            rationale=(
                f"band geometry (ZD): z_dev={z_dev:.2f} (|z|>={self.config.z_entry})",
                f"stop {self.config.stop_sigma_mult}σ_h target {self.config.target_sigma_mult}σ_h "
                f"hold {self.config.max_hold_sec}s RR={levels.reward_risk:.2f}",
            ),
            model_version=self.version,
        )


def run_vol_band_backtest(
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int = 60,
    config: TraderConfig | None = None,
    strategy_config: VolBandConfig | None = None,
    garch_state: GARCHState | None = None,
    paper: PaperExecutionConfig | None = None,
    artifact_output_path: str | Path | None = None,
    count_from_epoch: float | None = None,
    count_until_epoch: float | None = None,
) -> BacktestResult:
    """Run the band-geometry backtest through the shared vol-regime runner.

    Same PaperBroker + RiskEngine pipeline as fade/momentum/sniper so the
    head-to-head is apples-to-apples.  ``count_from_epoch`` /
    ``count_until_epoch`` (walk-forward window measurement) forward to
    :func:`run_vol_regime_backtest`.
    """
    from synthetic_trader.backtest.vol_reversion import run_vol_regime_backtest

    config = config or TraderConfig.default()
    if symbol not in config.symbols:
        raise ValueError(f"unsupported symbol {symbol!r}")

    strategy = VolBandStrategy(
        symbol,
        timeframe_sec,
        config=strategy_config,
        garch_state=garch_state,
    )
    return run_vol_regime_backtest(
        strategy,
        ticks,
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        config=config,
        paper=paper,
        artifact_output_path=artifact_output_path,
        artifact_strategy="vol-band",
        artifact_config=strategy_config,
        count_from_epoch=count_from_epoch,
        count_until_epoch=count_until_epoch,
    )
