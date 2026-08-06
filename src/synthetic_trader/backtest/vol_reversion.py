"""Vol-targeting mean-reversion backtest mode (the "fade" strategy).

Synthetic indices are CSPRNG-generated, so *direction* is unpredictable —
but volatility clusters and mean-reverts on a schedule.  The one genuinely
exploitable signal is therefore the **volatility regime**, not price
direction.

This module implements the vol-targeting overlay:

  1. **EGARCH forecast** — ``EGARCHVarianceForecaster`` (optionally seeded
     with calibrated parameters from ``data/garch_calibration/{symbol}.json``)
     produces a one-step-ahead volatility forecast ``garch_sigma``.  The
     strategy tracks the forecast sigma against its own trailing baseline
     (a slow EMA): when the forecast vol is *extended* well above baseline,
     that is the "extended volatility period" to fade.
  2. **ADWIN drift gate** — the absolute log-return magnitude is fed to
     ``DriftDetector``.  A shift in move magnitude is a *volatility regime
     change*; when one is detected the strategy stands down for
     ``drift_cooldown_bars`` instead of fading into a regime transition.
  3. **The fade** — when vol is extended *and* price is stretched by
     ``z_entry`` forecast-sigmas beyond its short EMA, enter **against** the
     extension (SHORT after an up-overshoot, LONG after a down-overshoot)
     with vol-scaled stop/targets and a time stop, expecting mean-reversion.

Run it side-by-side with the existing sniper strategy::

    python -m synthetic_trader.cli backtest-vol --csv data/R_75_ticks.csv \\
        --symbol R_75 --compare

Note on the EGARCH features: ``garch_vol_ratio`` is always ~1.0 by
construction (the forecaster's ``long_run_vol`` is the current conditional
vol), so this strategy computes its own extended-vol ratio — forecast sigma
vs a slow EMA of forecast sigma — which is the meaningful signal.
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
    TradeOutcome,
    TradeSignal,
)
from synthetic_trader.execution.paper import PaperBroker, Position
from synthetic_trader.journal.trade_journal import (
    metrics_from_outcomes,
    summarize_run_diagnostics,
)
from synthetic_trader.models.drift import DriftDetector
from synthetic_trader.models.garch import EGARCHVarianceForecaster
from synthetic_trader.risk.engine import RiskEngine

if TYPE_CHECKING:
    from synthetic_trader.models.garch import GARCHState

STRATEGY_VERSION = "vol-reversion-v1"

# ADWIN's statistical test is unreliable at 1e-5 absolute scales (float
# precision), so move magnitudes are fed as percentage-scale values: |r| * 100.
DRIFT_PCT_SCALE = 100.0


@dataclass(frozen=True)
class VolReversionConfig:
    """Tunable parameters for the vol-targeting fade overlay."""

    # Short EMA of close used as the "mean" to fade back toward.
    ema_period: int = 20
    # Price must be this many *forecast* sigmas beyond the short EMA to fade.
    # Tuned on the clean 7-day corpus (see PHASE5_SUMMARY §19): looser than the
    # original 2.0 — the fade's edge lives in sharp extensions, not 2.5-sigma
    # extremes that almost never print.
    z_entry: float = 1.5
    # Forecast sigma must exceed this multiple of its slow trailing baseline
    # for the period to count as "extended volatility".  Tuned upward from 1.3
    # to 1.5: requiring a genuinely extended vol regime beat the looser gates
    # at every z_entry on the clean corpus.
    vol_extended_ratio: float = 1.5
    # Slow EMA period for the sigma baseline.
    sigma_ema_period: int = 60
    # If > 0, additionally require the EGARCH mean-reversion signal
    # (probability of vol mean-reversion from the last return's z-score) to be
    # at least this value.  Tuned from 0.0 to 0.02: gating on the model's own
    # reversion probability selects SHARP-spike fades (|z| >= 2 last return)
    # over slow grinds, which was consistently the better trade on the clean
    # corpus (0.02 and 0.05 saturate identically — not knife-edged).
    # CAVEAT (§19): the z_entry/vol_extended_ratio pair only nets out vs the
    # old defaults WHILE this gate is active — with mr=0.0 the same z/vol is
    # −1.91R summed, worse than the old −1.62R.  Provisional pending more data.
    min_revert_signal: float = 0.02
    # Stop/target placement in forecast sigmas from entry.
    stop_sigma_mult: float = 2.5
    target_sigma_mult: float = 1.5
    # Time stop in primary candles.
    max_hold_bars: int = 30
    # Stand down for this many candles after an ADWIN regime drift.
    drift_cooldown_bars: int = 30
    # ADWIN sensitivity (lower = more sensitive).
    drift_delta: float = 0.002
    # Skip signals before this many candles (let EGARCH warm up).
    warmup_candles: int = 60
    # Innovation distribution for the EGARCH forecaster.
    distribution: str = "normal"
    dof: float = 5.0
    # Breakeven trail: move the stop to entry once the position's MFE (max
    # favorable excursion, in R units) reaches this fraction of the target
    # distance.  0.0 disables (hold the static stop).
    #
    # WHY (§31): the fade's planned RR is 0.6, but the *realized* RR is only
    # ~0.5 (slippage + same-candle stop/target collisions shave wins to
    # ~+0.5R while losses stay at ~-1R) — so the realized breakeven WR is
    # ~65-68%, above the 58-63% the fade actually prints.  Trailing to
    # breakeven at 0.3 x target converts many would-be -1R losses into ~0R
    # exits, lifting realized RR toward ~1.0 and expectancy positive (9/10
    # configs on the clean 7-day corpus).
    breakeven_trail_frac: float = 0.0


class BreakevenTrailBroker(PaperBroker):
    """PaperBroker with an optional breakeven trail.

    Mirrors the base ``_maybe_close`` stop-first / target / expiry semantics
    exactly, but once a position's tracked MFE (in R units) reaches
    ``breakeven_trail_frac`` of the *planned* target distance, the effective
    stop becomes the entry price.  Losses that first traveled that far in
    favor then exit at ~0R instead of -1R.
    """

    def __init__(
        self,
        config: PaperExecutionConfig,
        breakeven_trail_frac: float = 0.0,
    ) -> None:
        super().__init__(config)
        self.breakeven_trail_frac = breakeven_trail_frac
        self._mfe_r: dict[str, float] = {}

    def _maybe_close(self, position: Position, candle: Candle) -> TradeOutcome | None:
        signal = position.signal
        risk_distance = abs(signal.entry - signal.stop_loss)
        if risk_distance <= 0.0:
            risk_distance = signal.entry * 0.001
        if signal.direction is Direction.LONG:
            mfe = (candle.high - signal.entry) / risk_distance
        else:
            mfe = (signal.entry - candle.low) / risk_distance
        self._mfe_r[position.id] = max(self._mfe_r.get(position.id, 0.0), mfe)

        planned_rr = abs(signal.take_profit - signal.entry) / risk_distance
        trail_armed = (
            self.breakeven_trail_frac > 0.0
            and self._mfe_r[position.id] >= self.breakeven_trail_frac * planned_rr
        )
        effective_stop = signal.entry if trail_armed else signal.stop_loss

        expired = (
            candle.open_time + candle.timeframe_sec >= signal.snapshot.epoch + signal.horizon_sec
        )
        if signal.direction is Direction.LONG:
            stop_hit = candle.low <= effective_stop
            target_hit = candle.high >= signal.take_profit
        else:
            stop_hit = candle.high >= effective_stop
            target_hit = candle.low <= signal.take_profit

        if stop_hit and target_hit:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, effective_stop),
                candle.open_time + candle.timeframe_sec,
            )
        elif stop_hit:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, effective_stop),
                candle.open_time + candle.timeframe_sec,
            )
        elif target_hit:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.take_profit),
                candle.open_time + candle.timeframe_sec,
            )
        elif expired:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, candle.close),
                candle.open_time + candle.timeframe_sec,
            )
        else:
            return None
        # Free the per-position MFE state with the position (no unbounded
        # growth across a long sweep / live session).
        self._mfe_r.pop(position.id, None)
        return outcome


class VolReversionStrategy:
    """Streaming fade strategy driven by EGARCH forecast + ADWIN drift."""

    def __init__(
        self,
        symbol: str,
        timeframe_sec: int,
        config: VolReversionConfig | None = None,
        garch_state: GARCHState | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe_sec = timeframe_sec
        self.config = config or VolReversionConfig()
        self.forecaster = EGARCHVarianceForecaster(
            distribution=self.config.distribution,
            dof=self.config.dof,
        )
        if garch_state is not None:
            # Seed the online forecaster with market-calibrated dynamics
            # (omega/alpha/beta/gamma) but keep observations=0 so the
            # forecaster's own buffer re-initializes the variance scale
            # from the actual candle stream.  The calibration was fit at a
            # different bar scale, so its stored log_variance/observations
            # are not meaningful for this run.
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
        """Process one closed candle; returns a fade signal or None."""
        self._candles_seen += 1
        if self._prev_close is None or candle.close <= 0.0:
            self._prev_close = candle.close
            self._ema = candle.close
            return None

        log_return = math.log(candle.close / self._prev_close)
        self._prev_close = candle.close
        features = self.forecaster.update(log_return)

        # Drift monitor: a shift in move magnitude is a volatility regime
        # change — stand down while it resolves instead of fading into it.
        # ADWIN's statistical test is unreliable at 1e-5 absolute scales
        # (float precision), so feed percentage-scale moves: |r| * 100.
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

        # Advance the ex-ante sigma reference *unconditionally*, before any
        # gating: early returns (warmup, drift cooldown) must never leave a
        # stale pre-drift sigma behind — after a regime change that stale
        # value is exactly the wrong reference for vol-extension and z_dev.
        prev_sigma = self._prev_sigma
        self._prev_sigma = sigma

        if self._candles_seen < self.config.warmup_candles:
            return None
        if self.forecaster.state.observations < 30:
            return None  # EGARCH not warmed up; features are defaults

        # ── Drift cooldown ──────────────────────────────────────
        steps_since = self.drift.steps_since_last_drift(self.drift.n_observations)
        if steps_since < self.config.drift_cooldown_bars:
            return None  # regime is transitioning — don't fade into it

        # ── Extended-volatility gate ────────────────────────────
        # Judge extension against the *previous* forecast sigma (ex-ante):
        # by the time the current sigma has caught up to a move, the fade
        # has already lost its edge.
        if prev_sigma is None or prev_sigma <= 1e-12:
            return None  # need one candle of sigma history
        vol_extended = prev_sigma > self.config.vol_extended_ratio * self._sigma_ema
        if not vol_extended:
            return None  # vol not extended vs its baseline

        # ── Optional mean-reversion strictness ──────────────────
        if self.config.min_revert_signal > 0.0:
            revert = features.get("garch_mean_revert_signal", 0.0)
            if revert < self.config.min_revert_signal:
                return None

        # ── Price-extension fade ────────────────────────────────
        # garch_sigma is log-return vol (dimensionless); the price
        # deviation must be measured in log space too: ln(close/ema)/sigma.
        # Use the ex-ante forecast sigma so the extension is judged against
        # the vol level that was known before this bar's move.
        z_dev = math.log(candle.close / self._ema) / prev_sigma
        if z_dev >= self.config.z_entry:
            direction = Direction.SHORT  # up-overshoot → fade down
        elif z_dev <= -self.config.z_entry:
            direction = Direction.LONG  # down-overshoot → fade up
        else:
            return None

        # Convert the log-vol stop/target multipliers to price units by
        # scaling with the entry price: entry * (1 ± mult * sigma).
        # (Default RR = target/stop = 1.5/2.5 = 0.6 — a fade needs a
        # win rate above ~62.5% to break even, which is the usual profile
        # of mean-reversion entries.)
        entry = candle.close
        stop = (
            entry * (1.0 + self.config.stop_sigma_mult * prev_sigma)
            if direction is Direction.SHORT
            else entry * (1.0 - self.config.stop_sigma_mult * prev_sigma)
        )
        target = (
            entry * (1.0 - self.config.target_sigma_mult * prev_sigma)
            if direction is Direction.SHORT
            else entry * (1.0 + self.config.target_sigma_mult * prev_sigma)
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
                f"fade extended vol z_dev={z_dev:.2f} "
                f"sigma_baseline_ratio={sigma / self._sigma_ema:.2f}",
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
                f"vol-targeting fade: z_dev={z_dev:.2f} (|z|>={self.config.z_entry})",
                f"sigma_baseline_ratio={sigma / self._sigma_ema:.2f} "
                f"(>={self.config.vol_extended_ratio})",
            ),
            model_version=self.version,
        )


def dedupe_ticks(ticks: list[Tick]) -> list[Tick]:
    """Sort by epoch and drop exact-duplicate epochs (keep first)."""
    seen: set[float] = set()
    result: list[Tick] = []
    for tick in sorted(ticks, key=lambda item: item.epoch):
        if tick.epoch in seen:
            continue
        seen.add(tick.epoch)
        result.append(tick)
    return result


def run_vol_regime_backtest(
    strategy,
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int,
    config: TraderConfig,
    paper: PaperExecutionConfig | None = None,
    artifact_output_path: str | Path | None = None,
    artifact_strategy: str = "vol-reversion",
    artifact_config: object | None = None,
) -> BacktestResult:
    """Shared runner for the vol-regime backtest modes (fade / momentum).

    Mirrors ``BacktestEngine.run_ticks`` using the same ``PaperBroker`` +
    ``RiskEngine`` pipeline so fade, momentum, and the sniper comparison are
    apples-to-apples.  The RiskEngine is configured with regime-trade-
    appropriate gates (no confidence/R:R minimum, no extreme-vol block —
    extreme vol is the signal here).
    """
    builders = MultiTimeframeCandleBuilder(symbol, [timeframe_sec])
    risk_config = replace(
        config.risk,
        # Mechanical vol-scaled entries: no confidence/R:R gate (the
        # RiskEngine's range_z_50 cap is never hit — the strategy's
        # snapshot features don't include that key).
        min_confidence=0.0,
        min_reward_risk=0.0,
    )
    risk_engine = RiskEngine(risk_config)
    paper_config = paper or config.paper
    # Optional breakeven trail: read from the strategy's own config (the
    # runner already holds the strategy; artifact_config is purely for output
    # serialization and must never decide execution behavior).
    trail_frac = getattr(strategy.config, "breakeven_trail_frac", 0.0) or 0.0
    broker = (
        BreakevenTrailBroker(paper_config, breakeven_trail_frac=trail_frac)
        if trail_frac > 0.0
        else PaperBroker(paper_config)
    )
    outcomes: list[TradeOutcome] = []
    signals = 0
    rejected = 0

    for tick in sorted(ticks, key=lambda item: item.epoch):
        closed = builders.update(tick)
        for tf, candle in closed.items():
            if tf != timeframe_sec:
                continue
            for outcome in broker.on_candle(candle):
                outcomes.append(outcome)
                risk_engine.register_outcome(outcome)

            signal = strategy.on_candle(candle)
            if signal is None:
                continue
            signals += 1
            risk_decision = risk_engine.evaluate(signal)
            if not risk_decision.approved or risk_decision.intent is None:
                rejected += 1
                continue
            broker.submit(risk_decision.intent)
            risk_engine.register_open()

    flushed = builders.flush()
    final_primary = flushed.get(timeframe_sec)
    if final_primary is not None:
        for outcome in broker.on_candle(final_primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)
        for outcome in broker.close_all(final_primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)

    metrics = metrics_from_outcomes(outcomes)
    diagnostics = summarize_run_diagnostics(
        metrics=metrics,
        signals=signals,
        rejected_signals=rejected,
        shutdown_closed_trades=0,
        session_resets=0,
    )
    result = BacktestResult(
        metrics=metrics,
        final_equity=risk_engine.state.equity,
        signals=signals,
        rejected_signals=rejected,
        diagnostics=diagnostics,
        model_version=strategy.version,
    )
    if artifact_output_path is not None:
        from synthetic_trader.reporting.serializers import dump_json_file

        dump_json_file(
            artifact_output_path,
            {
                "strategy": artifact_strategy,
                "symbol": symbol,
                "timeframe_sec": timeframe_sec,
                "metrics": metrics.__dict__,
                "signals": signals,
                "rejected_signals": rejected,
                "final_equity": result.final_equity,
                "strategy_config": artifact_config.__dict__ if artifact_config else None,
            },
        )
    return result


def run_vol_reversion_backtest(
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int = 60,
    config: TraderConfig | None = None,
    strategy_config: VolReversionConfig | None = None,
    garch_state: GARCHState | None = None,
    paper: PaperExecutionConfig | None = None,
    artifact_output_path: str | Path | None = None,
) -> BacktestResult:
    """Run the vol-targeting fade backtest, mirroring BacktestEngine.run_ticks.

    Uses the same PaperBroker execution + metrics pipeline as the sniper
    backtest so the two can be compared apples-to-apples.
    """
    config = config or TraderConfig.default()
    if symbol not in config.symbols:
        raise ValueError(f"unsupported symbol {symbol!r}")

    strategy = VolReversionStrategy(
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
        artifact_strategy="vol-reversion",
        artifact_config=strategy_config,
    )
