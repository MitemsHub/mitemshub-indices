"""Vol-targeting momentum backtest mode (the "follow" strategy).

The fade strategy (:mod:`synthetic_trader.backtest.vol_reversion`) assumes
mean-reversion: it sells over-extensions of price when forecast volatility
is high.  But during a genuine **drift / step-up regime** — when the move
magnitude has *changed* and is now sustained at a new, higher level —
fading is exactly wrong: the extension keeps going.

This module implements the with-the-regime counterpart:

  1. **EGARCH forecast** — the same ``EGARCHVarianceForecaster`` (optionally
     seeded with ``data/garch_calibration/{symbol}.json``) produces a
     one-step-ahead volatility forecast ``garch_sigma``.
  2. **High-vol regime gate** — *which* gate is configurable via
     ``mom_gate``:

     - ``"ratio"`` (default) — forecast sigma must be *elevated* relative
       to its own slow trailing baseline (``vol_min_ratio``).  Momentum only
       makes sense when the volatility regime is on: in a calm regime the
       move is noise, not a trend to follow.  This is the strictest gate —
       it only fires while sigma is *freshly* above its EMA, so it
       under-trades sustained regimes whose EMA has already caught up.
     - ``"absolute"`` — forecast sigma must clear a *fixed* multiple of the
       calibrated long-run vol (``abs_sigma_mult``).  Because the reference
       is the unconditional long-run level rather than a trailing EMA, the
       gate stays ON through an entire sustained high-vol regime instead of
       fading out once the EMA converges.
     - ``"trend"`` — the sigma EMA itself must be rising
       (``trend_eps`` minimum relative rise), i.e. the vol regime is still
       *building*.  Catches sustained regimes mid-climb without requiring a
       fixed absolute level.

  3. **ADWIN drift gate** — the same ``DriftDetector`` as the fade: a shift
     in move magnitude is a regime change, and standing down for
     ``drift_cooldown_bars`` after one keeps momentum from *entering at the
     top of a step-up* — the very regime that fading gets wrong.  (The
     intuition is that once the step-up has *stabilized* — no fresh drift
     for ``drift_cooldown_bars`` — the new high-vol level is the regime to
     follow, not fade.)
  4. **The follow** — when vol is high and the regime is stable, enter **in
     the direction of the move**: LONG after an up-move, SHORT after a
     down-move (price ``z_entry`` forecast-sigmas beyond its short EMA),
     with wider targets than stops (momentum profile, RR > 1 by default).

Run it side-by-side with the fade and the sniper reference::

    python -m synthetic_trader.cli backtest-vol --csv data/R_75_ticks.csv \\
        --symbol R_75 --timeframe 300 --compare
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from synthetic_trader.backtest.engine import BacktestResult
from synthetic_trader.backtest.vol_reversion import (
    DRIFT_PCT_SCALE,
    dedupe_ticks,
    run_vol_regime_backtest,
)
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
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

if TYPE_CHECKING:
    from synthetic_trader.models.garch import GARCHState

STRATEGY_VERSION = "vol-momentum-v1"


@dataclass(frozen=True)
class VolMomentumConfig:
    """Tunable parameters for the vol-targeting momentum follow overlay."""

    # Short EMA of close used as the momentum reference.
    ema_period: int = 20
    # Price must be this many *forecast* sigmas beyond the short EMA to follow.
    z_entry: float = 0.8
    # Forecast sigma must exceed this multiple of its slow trailing baseline
    # for the regime to count as "high volatility" (momentum regime on).
    # Only used when ``mom_gate == "ratio"``.
    vol_min_ratio: float = 1.15
    # High-vol regime gate selector:
    #   "ratio"     — sigma vs its slow trailing EMA (fresh elevation only)
    #   "absolute"  — sigma vs a fixed multiple of calibrated long-run vol
    #   "trend"     — the sigma EMA itself is rising (regime building)
    mom_gate: str = "ratio"
    # Only used when ``mom_gate == "absolute"``: forecast sigma must exceed
    # this multiple of the long-run sigma baseline to count as high-vol.
    abs_sigma_mult: float = 2.0
    # Only used when ``mom_gate == "absolute"``: period of the slow sigma
    # baseline.  The baseline starts from the seed long-run (calibrated
    # value when available) and is then updated from the actual candle stream
    # with this EMA period — a *long* period so it converges to the
    # instrument's unconditional vol without being dragged by one regime.
    # (The 60-bar ``sigma_ema_period`` reference catches up to a sustained
    # high-vol regime within it; a ~600-bar baseline barely moves, which is
    # exactly why the absolute gate keeps firing through the regime.)
    abs_ref_period: int = 600
    # Only used when ``mom_gate == "trend"``: the sigma EMA must rise by at
    # least this relative amount to count as a building vol regime.
    trend_eps: float = 1e-4

    def __post_init__(self) -> None:
        """Validate ``mom_gate`` — an unknown selector is a config bug, not
        something to silently paper over with the ratio gate."""
        if self.mom_gate not in ("ratio", "absolute", "trend"):
            raise ValueError(
                f"mom_gate must be one of 'ratio', 'absolute', 'trend'; got "
                f"{self.mom_gate!r}"
            )
    # Slow EMA period for the sigma baseline.
    sigma_ema_period: int = 60
    # Stop/target placement in forecast sigmas from entry.  Momentum profile:
    # tighter stop, wider target (RR = target/stop > 1 by default).
    stop_sigma_mult: float = 1.5
    target_sigma_mult: float = 3.0
    # Time stop in primary candles.
    max_hold_bars: int = 30
    # Stand down for this many candles after an ADWIN regime drift — keeps
    # momentum from entering at the top of a fresh step-up regime.
    drift_cooldown_bars: int = 30
    # ADWIN sensitivity (lower = more sensitive).
    drift_delta: float = 0.002
    # Skip signals before this many candles (let EGARCH warm up).
    warmup_candles: int = 60
    # Innovation distribution for the EGARCH forecaster.
    distribution: str = "normal"
    dof: float = 5.0
    # Breakeven trail (see VolReversionConfig.breakeven_trail_frac): move the
    # stop to entry once MFE reaches this fraction of the target distance.
    # 0.0 disables.  Shared by the fade/momentum runner.
    breakeven_trail_frac: float = 0.0


class VolMomentumStrategy:
    """Streaming momentum strategy driven by EGARCH forecast + ADWIN drift."""

    def __init__(
        self,
        symbol: str,
        timeframe_sec: int,
        config: VolMomentumConfig | None = None,
        garch_state: GARCHState | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe_sec = timeframe_sec
        self.config = config or VolMomentumConfig()
        self.forecaster = EGARCHVarianceForecaster(
            distribution=self.config.distribution,
            dof=self.config.dof,
        )
        if garch_state is not None:
            # Same seeding semantics as the fade: calibrated dynamics, but
            # observations=0 so the forecaster re-learns the variance scale
            # from the actual candle stream.
            self.forecaster.state = replace(garch_state, observations=0)
        # Absolute-gate reference: the long-run sigma baseline.  Seeded from
        # the *seed* state's long-run variance (calibrated value if one was
        # loaded, else the prior), then updated from the actual candle stream
        # with a slow EMA (``abs_ref_period``).  Deliberately NOT the
        # adaptive ``long_run_vol`` property — that tracks the current
        # conditional vol, which would collapse the absolute gate to
        # "always on" (sigma > k*sigma).  And deliberately *not* frozen at
        # the prior: the prior is tick-scale while per-candle sigma is
        # ~30x smaller, so a frozen prior would make the gate never fire on
        # real data.  The slow EMA self-calibrates to the true unconditional
        # vol while barely moving inside a single regime.
        self._abs_ref = math.sqrt(self.forecaster.state.long_run_variance)
        self._abs_alpha = 2.0 / (self.config.abs_ref_period + 1.0)
        self.drift = DriftDetector(delta=self.config.drift_delta)
        self._ema: float | None = None
        self._sigma_ema: float | None = None
        self._sigma_ema_prev: float | None = None
        self._prev_close: float | None = None
        self._prev_sigma: float | None = None
        self._candles_seen = 0
        # Data-gap detection: a multi-hour feed outage must not be misread
        # as one gigantic bar-scale return (see _gap_reanchor).
        self._last_bar_end: float | None = None
        self._max_gap_sec = max(3 * timeframe_sec, 600)

    def _gap_reanchor(self, candle: Candle) -> bool:
        """Return True (and re-anchor) when the candle follows a data gap.

        The candle stream is bucketed by wall-clock, so a multi-hour feed
        outage (collector downtime, terminal disconnect) produces a candle
        whose close sits far above the previous candle's close even though
        the market moved normally across the outage.  Feeding that span as
        one bar-scale return fabricates a spurious EGARCH shock (z ~ +50),
        clipping log-variance and poisoning the sigma EMA for the rest of
        the run.  On a gap we re-anchor the close/EMA baselines, skip the
        forecaster update, and stand aside for that candle."""
        if self._last_bar_end is not None and candle.open_time > self._last_bar_end + self._max_gap_sec:
            self._prev_close = candle.close
            self._ema = candle.close
            self._last_bar_end = candle.open_time + candle.timeframe_sec
            return True
        self._last_bar_end = candle.open_time + candle.timeframe_sec
        return False

    @property
    def version(self) -> str:
        return f"{STRATEGY_VERSION}:{self.config.distribution}"

    def on_candle(self, candle: Candle) -> TradeSignal | None:
        """Process one closed candle; returns a momentum signal or None."""
        self._candles_seen += 1
        if self._prev_close is None or candle.close <= 0.0:
            self._prev_close = candle.close
            self._ema = candle.close
            return None
        if self._gap_reanchor(candle):
            return None

        log_return = math.log(candle.close / self._prev_close)
        self._prev_close = candle.close
        features = self.forecaster.update(log_return)

        # Drift monitor: a shift in move magnitude is a volatility regime
        # change — stand down while it resolves instead of following into it.
        # Percentage-scale moves (|r| * 100) — ADWIN's test is unreliable at
        # 1e-5 absolute scales (float precision).
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
        self._sigma_ema_prev = self._sigma_ema
        self._sigma_ema = (
            sigma
            if self._sigma_ema is None
            else self._sigma_ema * (1.0 - sigma_alpha) + sigma * sigma_alpha
        )
        # Slow long-run baseline for the absolute gate: adapts to the actual
        # candle scale (the prior is tick-scale, ~30x too large) but with a
        # long period so a single sustained regime barely moves it.
        self._abs_ref = self._abs_ref * (1.0 - self._abs_alpha) + sigma * self._abs_alpha

        # Advance the ex-ante sigma reference unconditionally (same reason as
        # the fade: early returns must never leave a stale pre-drift sigma).
        prev_sigma = self._prev_sigma
        self._prev_sigma = sigma

        if self._candles_seen < self.config.warmup_candles:
            return None
        if self.forecaster.state.observations < 30:
            return None  # EGARCH not warmed up; features are defaults

        # ── Drift cooldown ──────────────────────────────────────
        steps_since = self.drift.steps_since_last_drift(self.drift.n_observations)
        if steps_since < self.config.drift_cooldown_bars:
            return None  # regime is transitioning — don't follow into it

        # ── High-volatility regime gate ─────────────────────────
        # Momentum only follows when the vol regime is ON.  Which definition
        # of "on" is used depends on ``mom_gate`` (see module docstring):
        # ratio = fresh elevation above the trailing EMA (strict),
        # absolute = above a fixed long-run multiple (stays on through
        # sustained regimes), trend = sigma EMA itself still rising.
        if prev_sigma is None or prev_sigma <= 1e-12:
            return None  # need one candle of sigma history
        gate = self.config.mom_gate
        if gate == "absolute":
            vol_high = prev_sigma > self.config.abs_sigma_mult * self._abs_ref
        elif gate == "trend":
            # The sigma EMA must be rising (regime building) AND the regime
            # must already be above the long-run baseline — without the floor,
            # a quiet regime slowly climbing from very low vol would qualify
            # as "momentum" even though vol isn't actually high yet (empirically
            # that chased noise: 0% WR at R_75@300s).
            rising = (
                self._sigma_ema_prev is not None
                and self._sigma_ema > self._sigma_ema_prev * (1.0 + self.config.trend_eps)
                and prev_sigma > self._abs_ref
            )
            vol_high = rising
        else:  # "ratio" (default)
            vol_high = prev_sigma > self.config.vol_min_ratio * self._sigma_ema
        if not vol_high:
            return None  # vol regime not elevated — no momentum to follow

        # ── Direction: follow the move ──────────────────────────
        # Price deviation measured in log space vs the ex-ante forecast
        # sigma (same geometry as the fade, opposite intent).
        z_dev = math.log(candle.close / self._ema) / prev_sigma
        if z_dev >= self.config.z_entry:
            direction = Direction.LONG  # up-move in a high-vol regime → follow up
        elif z_dev <= -self.config.z_entry:
            direction = Direction.SHORT  # down-move in a high-vol regime → follow down
        else:
            return None

        # Momentum profile: tighter stop, wider target (RR = 3.0/1.5 = 2.0 by
        # default — a momentum trade needs fewer winners but bigger ones).
        entry = candle.close
        stop = (
            entry * (1.0 - self.config.stop_sigma_mult * prev_sigma)
            if direction is Direction.LONG
            else entry * (1.0 + self.config.stop_sigma_mult * prev_sigma)
        )
        target = (
            entry * (1.0 + self.config.target_sigma_mult * prev_sigma)
            if direction is Direction.LONG
            else entry * (1.0 - self.config.target_sigma_mult * prev_sigma)
        )
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
                f"follow high-vol regime z_dev={z_dev:.2f} "
                f"gate={gate} sigma_baseline_ratio={sigma / self._sigma_ema:.2f}",
            ),
        )
        return TradeSignal(
            symbol=self.symbol,
            direction=direction,
            confidence=confidence,
            min_confidence=0.0,
            entry=entry,
            stop_loss=stop,
            take_profit=target,
            horizon_sec=self.config.max_hold_bars * self.timeframe_sec,
            snapshot=snapshot,
            rationale=(
                f"vol-targeting momentum: z_dev={z_dev:.2f} (|z|>={self.config.z_entry})",
                f"gate={gate} sigma_baseline_ratio={sigma / self._sigma_ema:.2f} "
                f"(>={self.config.vol_min_ratio})",
            ),
            model_version=self.version,
        )


def run_vol_momentum_backtest(
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int = 60,
    config: TraderConfig | None = None,
    strategy_config: VolMomentumConfig | None = None,
    garch_state: GARCHState | None = None,
    paper: PaperExecutionConfig | None = None,
    artifact_output_path: str | Path | None = None,
) -> BacktestResult:
    """Run the vol-targeting momentum backtest.

    Shares the same ``PaperBroker`` + ``RiskEngine`` pipeline as the fade
    and the sniper backtest so the three can be compared apples-to-apples.
    """
    config = config or TraderConfig.default()
    if symbol not in config.symbols:
        raise ValueError(f"unsupported symbol {symbol!r}")

    strategy = VolMomentumStrategy(
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
        artifact_strategy="vol-momentum",
        artifact_config=strategy_config,
    )
