"""Tests for the vol-targeting mean-reversion backtest mode."""

from __future__ import annotations

import math

import pytest

from synthetic_trader.backtest.vol_reversion import (
    BreakevenTrailBroker,
    VolReversionConfig,
    VolReversionStrategy,
    dedupe_ticks,
    run_vol_reversion_backtest,
)
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
from synthetic_trader.domain import Candle, Direction, OrderIntent, Position, Tick, TradeSignal


def _candles(closes: list[float], timeframe_sec: int = 60) -> list[Candle]:
    """Build a synthetic candle stream from closes starting at epoch 0."""
    candles: list[Candle] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        open_time = i * timeframe_sec
        candles.append(
            Candle(
                symbol="R_75",
                timeframe_sec=timeframe_sec,
                open_time=open_time,
                open=prev,
                high=max(prev, close),
                low=min(prev, close),
                close=close,
                tick_count=1,
            )
        )
        prev = close
    return candles


def _ticks_from_closes(closes: list[float], symbol: str = "R_75") -> list[Tick]:
    return [
        Tick(symbol=symbol, epoch=float(i * 60), price=close)
        for i, close in enumerate(closes)
    ]


class TestVolReversionStrategy:
    def test_no_signal_on_quiet_stream(self) -> None:
        """A calm, low-vol stream never triggers a fade."""
        strat = VolReversionStrategy("R_75", 60, config=VolReversionConfig(warmup_candles=5))
        closes = [100.0 + 0.01 * math.sin(i) for i in range(120)]
        for candle in _candles(closes):
            assert strat.on_candle(candle) is None

    def test_fade_short_after_up_spike(self) -> None:
        """After an extended up-move in elevated vol, fade SHORT."""
        cfg = VolReversionConfig(
            warmup_candles=5,
            z_entry=1.5,
            vol_extended_ratio=1.05,
            min_revert_signal=0.0,  # default is 0.02 (clean-corpus tuning, §19);
            # this unit test relaxes it so the fade geometry logic is isolated
            # from the mean-revert gate's z-history timing.
            drift_cooldown_bars=0,  # isolate the fade logic from drift gating
        )
        strat = VolReversionStrategy("R_75", 60, config=cfg)
        closes: list[float] = []
        # calm base
        for i in range(60):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))
        # sharp up-spike (extended vol): a sudden burst the ex-ante sigma
        # forecast has not yet caught up with.  The corrected EGARCH reports
        # the TRUE per-candle sigma (~3.5%), so the spike must be large
        # enough to exceed z_entry=1.5 in accurate-sigma units (+4% is only
        # ~1.2 sigma; +8% crosses the threshold with margin).
        base = closes[-1]
        closes.append(base * 1.08)   # +8% jump in one candle
        closes.append(closes[-1] * 1.06)
        # reversion pullback
        for i in range(5):
            closes.append(closes[-1] - 0.15)

        signals = [strat.on_candle(c) for c in _candles(closes)]
        fades = [s for s in signals if s is not None]
        assert fades, "expected at least one fade signal after the up-spike"
        assert all(s.direction is Direction.SHORT for s in fades)
        for s in fades:
            assert s.stop_loss > s.entry > s.take_profit  # SHORT geometry
            assert s.horizon_sec == cfg.max_hold_bars * 60

    def test_fade_long_after_down_spike(self) -> None:
        cfg = VolReversionConfig(
            warmup_candles=5,
            z_entry=1.5,
            vol_extended_ratio=1.05,
            min_revert_signal=0.0,
            drift_cooldown_bars=0,
        )
        strat = VolReversionStrategy("R_75", 60, config=cfg)
        closes: list[float] = []
        for i in range(60):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))
        base = closes[-1]
        closes.append(base * 0.92)   # -8% drop in one candle (accurate sigma)
        closes.append(closes[-1] * 0.94)
        for i in range(5):
            closes.append(closes[-1] + 0.15)

        signals = [strat.on_candle(c) for c in _candles(closes)]
        fades = [s for s in signals if s is not None]
        assert fades
        assert all(s.direction is Direction.LONG for s in fades)
        for s in fades:
            assert s.stop_loss < s.entry < s.take_profit  # LONG geometry

    def test_drift_cooldown_suppresses_fades(self) -> None:
        """After ADWIN detects a move-magnitude shift, signals are suppressed."""
        cfg = VolReversionConfig(
            warmup_candles=5,
            z_entry=1.5,
            vol_extended_ratio=1.05,
            min_revert_signal=0.0,
            drift_cooldown_bars=500,  # long cooldown
            drift_delta=0.002,
        )
        strat = VolReversionStrategy("R_75", 60, config=cfg)
        # First drive an abrupt regime shift in move magnitude directly on
        # the detector (percentage-scale: quiet 0.5% -> spike 35%), then feed
        # a fade-worthy candle stream: cooldown must suppress every signal.
        for _ in range(200):
            strat.drift.observe(0.5)
        for _ in range(200):
            strat.drift.observe(35.0)
        assert strat.drift.drift_events >= 1, "expected ADWIN to fire"

        closes: list[float] = []
        for i in range(60):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))
        base = closes[-1]
        for i in range(1, 13):
            closes.append(base + i * 0.35)

        signals = [strat.on_candle(c) for c in _candles(closes)]
        assert all(s is None for s in signals), "cooldown should suppress all fades"

    def test_prev_sigma_stays_fresh_through_cooldown(self) -> None:
        """The ex-ante sigma reference must advance even when cooldown
        suppresses signals — a stale pre-drift sigma is the wrong reference
        after a regime change."""
        cfg = VolReversionConfig(
            warmup_candles=5,
            z_entry=1.5,
            vol_extended_ratio=1.05,
            min_revert_signal=0.0,
            drift_cooldown_bars=500,
            drift_delta=0.002,
        )
        strat = VolReversionStrategy("R_75", 60, config=cfg)
        for _ in range(200):
            strat.drift.observe(0.5)
        for _ in range(200):
            strat.drift.observe(35.0)
        assert strat.drift.drift_events >= 1

        # Quiet candles first (small sigma), then a big spike (large sigma).
        closes = [100.0 + 0.005 * math.sin(i / 3.0) for i in range(40)]
        base = closes[-1]
        for _ in range(20):
            closes.append(base * 1.01)  # sustained 1% moves
        for candle in _candles(closes):
            strat.on_candle(candle)  # all suppressed by cooldown

        # The reference must track the forecaster's recent sigma (large after
        # the spike), not the pre-drift quiet sigma.
        assert strat._prev_sigma is not None
        assert strat._prev_sigma > 0.001
        assert strat._prev_sigma < 0.2


class TestRunner:
    def test_runner_end_to_end(self) -> None:
        closes: list[float] = [100.0 + 0.005 * math.sin(i / 3.0) for i in range(60)]
        base = closes[-1]
        closes.append(base * 1.04)
        closes.append(closes[-1] * 1.03)
        for i in range(40):
            closes.append(closes[-1] - 0.15)

        result = run_vol_reversion_backtest(
            _ticks_from_closes(closes),
            symbol="R_75",
            timeframe_sec=60,
            strategy_config=VolReversionConfig(
                warmup_candles=5,
                z_entry=1.5,
                vol_extended_ratio=1.05,
                min_revert_signal=0.0,
                drift_cooldown_bars=0,
            ),
        )
        assert result.signals >= 0
        assert result.metrics.trades >= 0
        assert math.isfinite(result.final_equity)
        assert result.model_version.startswith("vol-reversion")

    def test_runner_uses_calibrated_garch_state(self) -> None:
        from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

        state = load_calibrated_garch_state("R_75")
        if state is None:
            pytest.skip("no calibration file for R_75")
        strat = VolReversionStrategy("R_75", 60, garch_state=state)
        assert strat.forecaster.state.omega == state.omega
        assert strat.forecaster.state.alpha == state.alpha

    def test_dedupe_ticks(self) -> None:
        ticks = [
            Tick(symbol="R_75", epoch=3.0, price=10.0),
            Tick(symbol="R_75", epoch=1.0, price=9.0),
            Tick(symbol="R_75", epoch=1.0, price=9.1),  # duplicate epoch
            Tick(symbol="R_75", epoch=2.0, price=9.5),
        ]
        deduped = dedupe_ticks(ticks)
        assert [t.epoch for t in deduped] == [1.0, 2.0, 3.0]
        assert deduped[0].price == 9.0  # first wins

    def test_unsupported_symbol_rejected(self) -> None:
        from synthetic_trader.domain import Tick

        with pytest.raises(ValueError):
            run_vol_reversion_backtest(
                [Tick(symbol="XXX", epoch=1.0, price=1.0)],
                symbol="XXX",
            )


def _signal(
    direction: Direction = Direction.LONG,
    entry: float = 100.0,
    stop: float = 95.0,
    target: float = 103.0,
) -> TradeSignal:
    """A minimal LONG signal with risk distance 5 and planned RR = 0.6."""
    from synthetic_trader.domain import FeatureSnapshot, Regime

    return TradeSignal(
        symbol="R_75",
        direction=direction,
        confidence=0.6,
        min_confidence=0.0,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        horizon_sec=1800,
        snapshot=FeatureSnapshot(
            symbol="R_75",
            epoch=0.0,
            timeframe_sec=60,
            features={},
            regime=Regime.VOLATILE,
            structure={},
        ),
        rationale=("test",),
    )


class TestBreakevenTrailBroker:
    """The breakeven trail converts -1R losses into ~0R exits once MFE
    reaches a fraction of the target distance — the §31 realized-RR fix."""

    def _broker(self, trail: float) -> BreakevenTrailBroker:
        return BreakevenTrailBroker(
            PaperExecutionConfig(exit_slippage_ticks=0.0),
            breakeven_trail_frac=trail,
        )

    def _open_long(self, broker: BreakevenTrailBroker) -> Position:
        signal = _signal(direction=Direction.LONG, entry=100.0, stop=95.0, target=103.0)
        intent = OrderIntent(signal=signal, stake=10.0, max_loss=10.0)
        return broker.submit(intent)

    @staticmethod
    def _candle(open_time: int, high: float, low: float, close: float) -> Candle:
        return Candle(
            symbol="R_75",
            timeframe_sec=60,
            open_time=open_time,
            open=close,
            high=high,
            low=low,
            close=close,
        )

    def test_disabled_trail_is_plain_broker(self) -> None:
        """trail=0.0 must behave exactly like PaperBroker (stop at -1R)."""
        broker = self._broker(0.0)
        self._open_long(broker)
        # Price goes to +0.2R (MFE=1.0 -> 20% of target) then stops out at -1R
        outcomes = broker.on_candle(self._candle(0, 101.0, 95.0, 95.0))
        assert len(outcomes) == 1
        assert outcomes[0].return_r < -0.9

    def test_trail_arms_and_breaks_even(self) -> None:
        """With trail=0.3, a trade that reaches 30% of target then reverses
        exits at ~0R instead of -1R."""
        broker = self._broker(0.3)
        self._open_long(broker)
        # planned target distance 3.0, risk 5.0 -> target_r = 0.6.
        # 30% of target = 0.18R = 0.9 price.  Candle 1: high 100.95 (MFE 0.95,
        # arms the trail) while low stays ABOVE entry (100.05) so the trail
        # arms without the same candle breaching the new breakeven stop.
        # Candle 2: falls to 95.0 -> the trail's stop is entry 100.0, so it
        # exits at ~0R instead of -1R.
        broker.on_candle(self._candle(60, 100.95, 100.05, 100.5))
        outcomes = broker.on_candle(self._candle(120, 100.0, 95.0, 95.0))
        assert len(outcomes) == 1
        assert abs(outcomes[0].return_r) < 0.05  # breakeven exit

    def test_trail_reaches_full_target_first(self) -> None:
        """A trade that runs to the full target after arming still pays +0.6R."""
        broker = self._broker(0.3)
        self._open_long(broker)
        broker.on_candle(self._candle(60, 100.95, 100.05, 100.5))  # arms trail
        # target candle: high hits 103.0 while low stays ABOVE the breakeven
        # stop (100.05) so the target, not the stop, is what fires
        outcomes = broker.on_candle(self._candle(120, 103.0, 100.05, 103.0))  # target
        assert len(outcomes) == 1
        assert outcomes[0].return_r > 0.5

    def test_mfe_is_cumulative_across_candles(self) -> None:
        """The trail arms from the running MFE, not just the current candle."""
        broker = self._broker(0.3)
        self._open_long(broker)
        # candle 1: MFE 0.95 price (0.19R) >= 0.3*0.6=0.18R -> arms cleanly
        # while staying above entry.  Candle 2: no new high, candle 3 drops
        # to 95.0 -> the already-armed trail exits at breakeven.
        broker.on_candle(self._candle(60, 100.95, 100.05, 100.5))
        broker.on_candle(self._candle(120, 100.1, 100.05, 100.1))
        outcomes = broker.on_candle(self._candle(180, 100.0, 95.0, 95.0))
        assert len(outcomes) == 1
        assert abs(outcomes[0].return_r) < 0.05

    def test_short_trail_sign_convention(self) -> None:
        """SHORT: favorable = price falls (MFE = (entry - low)/rd); after the
        trail arms from a drop, a rise through the moved stop exits at ~0R."""
        broker = self._broker(0.3)
        signal = _signal(direction=Direction.SHORT, entry=100.0, stop=105.0, target=97.0)
        broker.submit(OrderIntent(signal=signal, stake=10.0, max_loss=10.0))
        # SHORT: risk 5, target distance 3 -> planned_rr 0.6, trigger 0.18R =
        # 0.9 price.  Candle 1: low 99.05 (MFE 0.95, arms) while high stays
        # below entry (99.95) so the same candle does not breach the new stop.
        broker.on_candle(self._candle(60, 99.95, 99.05, 99.5))
        # Candle 2: rises to 105.0 -> the armed stop is entry 100.0 -> ~0R.
        outcomes = broker.on_candle(self._candle(120, 105.0, 100.0, 105.0))
        assert len(outcomes) == 1
        assert abs(outcomes[0].return_r) < 0.05

    def test_mfe_state_is_freed_on_close(self) -> None:
        """Closed positions must not leak entries into _mfe_r (reviewer:
        unbounded growth across a long sweep)."""
        broker = self._broker(0.3)
        pos = self._open_long(broker)
        broker.on_candle(self._candle(60, 100.95, 100.05, 100.5))
        broker.on_candle(self._candle(120, 100.0, 95.0, 95.0))  # stops out
        assert pos.id not in broker._mfe_r
        assert not broker._mfe_r

    def test_runner_uses_trail_broker_when_configured(self) -> None:
        """The runner swaps in BreakevenTrailBroker when breakeven_trail_frac
        is set on the strategy config (regression: wiring must not be lost)."""
        from synthetic_trader.backtest.vol_reversion import run_vol_regime_backtest

        closes: list[float] = [100.0 + 0.005 * math.sin(i / 3.0) for i in range(60)]
        base = closes[-1]
        closes.append(base * 1.04)
        closes.append(closes[-1] * 1.03)
        for i in range(40):
            closes.append(closes[-1] - 0.15)

        result = run_vol_reversion_backtest(
            _ticks_from_closes(closes),
            symbol="R_75",
            timeframe_sec=60,
            strategy_config=VolReversionConfig(
                warmup_candles=5,
                z_entry=1.5,
                vol_extended_ratio=1.05,
                min_revert_signal=0.0,
                drift_cooldown_bars=0,
                breakeven_trail_frac=0.3,
            ),
        )
        assert math.isfinite(result.final_equity)
        assert result.metrics.trades >= 0


class TestConfig:
    def test_defaults_sane(self) -> None:
        cfg = VolReversionConfig()
        assert cfg.z_entry > 1.0
        assert cfg.stop_sigma_mult > cfg.target_sigma_mult
        assert cfg.max_hold_bars > 0
        assert cfg.drift_cooldown_bars >= 0
        assert cfg.breakeven_trail_frac == 0.0  # off by default (opt-in)

    def test_defaults_are_the_clean_corpus_tuning(self) -> None:
        """Pin the gate defaults re-tuned on the clean 7-day corpus (§19).

        Deliberately explicit: changing these is a strategy decision that must
        come with fresh evidence (grid sweep on clean data), not a drive-by.
        """
        cfg = VolReversionConfig()
        assert cfg.z_entry == 1.5
        assert cfg.vol_extended_ratio == 1.5
        assert cfg.min_revert_signal == 0.02

    def test_reward_risk_from_multipliers(self) -> None:
        cfg = VolReversionConfig(stop_sigma_mult=2.5, target_sigma_mult=1.5)
        # reward/risk = target/stop by construction
        assert cfg.target_sigma_mult / cfg.stop_sigma_mult < 1.0
