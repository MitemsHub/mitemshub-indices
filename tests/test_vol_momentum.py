"""Tests for the vol-targeting momentum (with-the-regime) backtest mode."""

from __future__ import annotations

import math

import pytest

from synthetic_trader.backtest.vol_momentum import (
    VolMomentumConfig,
    VolMomentumStrategy,
    run_vol_momentum_backtest,
)
from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle, Direction, Tick
from synthetic_trader.backtest.vol_reversion import dedupe_ticks


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


class TestVolMomentumStrategy:
    def test_no_signal_on_quiet_stream(self) -> None:
        """A calm, low-vol stream never triggers a momentum follow."""
        strat = VolMomentumStrategy(
            "R_75", 60, config=VolMomentumConfig(warmup_candles=5)
        )
        closes = [100.0 + 0.01 * math.sin(i) for i in range(120)]
        for candle in _candles(closes):
            assert strat.on_candle(candle) is None

    def test_follow_long_after_up_move(self) -> None:
        """After an extended up-move in an elevated-vol regime, follow LONG."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.8,
            vol_min_ratio=1.05,
            drift_cooldown_bars=0,  # isolate the momentum logic from drift gating
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        closes: list[float] = []
        # calm base
        for i in range(60):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))
        # sustained up-move in elevated vol: a burst the ex-ante sigma
        # forecast has not yet caught up with, then continued drift up
        base = closes[-1]
        closes.append(base * 1.04)   # +4% jump in one candle
        closes.append(closes[-1] * 1.03)
        for i in range(5):
            closes.append(closes[-1] * 1.01)

        signals = [strat.on_candle(c) for c in _candles(closes)]
        follows = [s for s in signals if s is not None]
        assert follows, "expected at least one momentum signal after the up-move"
        assert all(s.direction is Direction.LONG for s in follows)
        for s in follows:
            assert s.stop_loss < s.entry < s.take_profit  # LONG geometry
            assert s.horizon_sec == cfg.max_hold_bars * 60

    def test_follow_short_after_down_move(self) -> None:
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.8,
            vol_min_ratio=1.05,
            drift_cooldown_bars=0,
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        closes: list[float] = []
        for i in range(60):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))
        base = closes[-1]
        closes.append(base * 0.96)   # -4% drop in one candle
        closes.append(closes[-1] * 0.97)
        for i in range(5):
            closes.append(closes[-1] * 0.99)

        signals = [strat.on_candle(c) for c in _candles(closes)]
        follows = [s for s in signals if s is not None]
        assert follows
        assert all(s.direction is Direction.SHORT for s in follows)
        for s in follows:
            assert s.stop_loss > s.entry > s.take_profit  # SHORT geometry

    def test_drift_cooldown_suppresses_follows(self) -> None:
        """After ADWIN detects a move-magnitude shift, signals are suppressed."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.8,
            vol_min_ratio=1.05,
            drift_cooldown_bars=500,  # long cooldown
            drift_delta=0.002,
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        # Drive an abrupt regime shift in move magnitude directly on the
        # detector (percentage-scale: quiet 0.5% -> spike 35%), then feed a
        # momentum-worthy candle stream: cooldown must suppress every signal.
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
        assert all(s is None for s in signals), "cooldown should suppress all follows"

    def test_prev_sigma_stays_fresh_through_cooldown(self) -> None:
        """The ex-ante sigma reference must advance even when cooldown
        suppresses signals — a stale pre-drift sigma is the wrong reference
        after a regime change."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.8,
            vol_min_ratio=1.05,
            drift_cooldown_bars=500,
            drift_delta=0.002,
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
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


    def test_mirror_of_fade_is_opposite_direction(self) -> None:
        """The same extended-vol stream must make fade and momentum trade
        OPPOSITE directions — proving the pair is a true counterfactual."""
        from synthetic_trader.backtest.vol_reversion import (
            VolReversionConfig,
            VolReversionStrategy,
        )

        shared = dict(warmup_candles=5, z_entry=1.5, drift_cooldown_bars=0)
        fade = VolReversionStrategy(
            "R_75",
            60,
            config=VolReversionConfig(
                vol_extended_ratio=1.05, min_revert_signal=0.0, **shared
            ),
        )
        mom = VolMomentumStrategy(
            "R_75",
            60,
            config=VolMomentumConfig(vol_min_ratio=1.05, **shared),
        )

        closes: list[float] = []
        for i in range(60):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))
        base = closes[-1]
        closes.append(base * 1.04)   # up-spike in elevated vol
        closes.append(closes[-1] * 1.03)
        for i in range(5):
            closes.append(closes[-1] * 1.01)

        candles = _candles(closes)
        fade_sigs = [s for c in candles if (s := fade.on_candle(c)) is not None]
        mom_sigs = [s for c in candles if (s := mom.on_candle(c)) is not None]
        assert fade_sigs and mom_sigs, "both strategies should fire on the spike"
        assert all(s.direction is Direction.SHORT for s in fade_sigs)
        assert all(s.direction is Direction.LONG for s in mom_sigs)


class TestRunner:
    def test_runner_end_to_end(self) -> None:
        closes: list[float] = [100.0 + 0.005 * math.sin(i / 3.0) for i in range(60)]
        base = closes[-1]
        closes.append(base * 1.04)
        closes.append(closes[-1] * 1.03)
        for i in range(40):
            closes.append(closes[-1] * 1.005)

        result = run_vol_momentum_backtest(
            _ticks_from_closes(closes),
            symbol="R_75",
            timeframe_sec=60,
            strategy_config=VolMomentumConfig(
                warmup_candles=5,
                z_entry=0.8,
                vol_min_ratio=1.05,
                drift_cooldown_bars=0,
            ),
        )
        assert result.signals >= 0
        assert result.metrics.trades >= 0
        assert math.isfinite(result.final_equity)
        assert result.model_version.startswith("vol-momentum")

    def test_runner_uses_calibrated_garch_state(self) -> None:
        from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

        state = load_calibrated_garch_state("R_75")
        if state is None:
            pytest.skip("no calibration file for R_75")
        strat = VolMomentumStrategy("R_75", 60, garch_state=state)
        assert strat.forecaster.state.omega == state.omega
        assert strat.forecaster.state.alpha == state.alpha

    def test_dedupe_ticks_shared_with_fade(self) -> None:
        """The momentum runner uses the fade module's shared dedupe helper."""
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
            run_vol_momentum_backtest(
                [Tick(symbol="XXX", epoch=1.0, price=1.0)],
                symbol="XXX",
            )


class TestGateVariants:
    """The ``mom_gate`` selector must change *when* the strategy fires."""

    def _sustained_regime_closes(self, n_tail: int = 60) -> list[float]:
        """Quiet base, then a sustained elevated-vol regime that stays high.

        The key property for the gate comparison: after the regime has been
        high for a while, the sigma EMA *converges* to the elevated level, so
        a ratio gate (fresh elevation only) stops firing while the regime is
        still on — the exact under-trading the absolute/trend gates fix.
        """
        closes: list[float] = []
        for i in range(80):
            closes.append(100.0 + 0.005 * math.sin(i / 3.0))  # calm base
        base = closes[-1]
        rng = [0.02, -0.018, 0.021, -0.019, 0.02, 0.017, -0.021, 0.019]  # ~2% vol
        for i in range(n_tail):
            closes.append(base * math.exp(rng[i % len(rng)]))
        return closes

    def test_ratio_gate_under_trades_sustained_regime(self) -> None:
        """The strict ratio gate only fires on *fresh* elevation — on a
        sustained regime whose sigma EMA has converged it fires rarely."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.5,
            vol_min_ratio=1.15,
            mom_gate="ratio",
            drift_cooldown_bars=0,
            sigma_ema_period=20,  # fast EMA converges quickly
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        closes = self._sustained_regime_closes(n_tail=200)
        signals = [s for s in (strat.on_candle(c) for c in _candles(closes)) if s is not None]
        # The ratio gate is strict by design — it fires, but far less than
        # the absolute gate on the same stream (see the compare test below).
        assert signals

    def test_absolute_gate_fires_throughout_sustained_regime(self) -> None:
        """Absolute gate references the frozen long-run vol, not a trailing
        EMA, so it keeps qualifying for the entire sustained high-vol regime."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.5,
            mom_gate="absolute",
            abs_sigma_mult=1.2,
            drift_cooldown_bars=0,
            sigma_ema_period=20,
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        closes = self._sustained_regime_closes(n_tail=200)
        signals = [s for s in (strat.on_candle(c) for c in _candles(closes)) if s is not None]
        assert signals
        # The whole second half is still inside the elevated regime.
        late = [s for s in signals if s.snapshot.epoch >= 180 * 60]
        assert late, "absolute gate must keep firing deep into the regime"

    def test_ratio_vs_absolute_signal_counts_differ(self) -> None:
        """On the same stream the absolute gate fires dramatically more
        often — the whole point of the alternative gate."""
        closes = self._sustained_regime_closes(n_tail=200)
        candles = _candles(closes)

        def count(gate: str, **kw) -> int:
            cfg = VolMomentumConfig(
                warmup_candles=5,
                z_entry=0.5,
                mom_gate=gate,
                drift_cooldown_bars=0,
                sigma_ema_period=20,
                **kw,
            )
            strat = VolMomentumStrategy("R_75", 60, config=cfg)
            return sum(1 for c in candles if strat.on_candle(c) is not None)

        ratio_n = count("ratio")
        absolute_n = count("absolute", abs_sigma_mult=1.2)
        assert absolute_n > ratio_n, "absolute gate should fire more often on a sustained regime"

    def test_trend_gate_fires_while_ema_rising(self) -> None:
        """Trend gate qualifies while the sigma EMA is climbing (regime
        building) — it should fire during the regime's onset."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.5,
            mom_gate="trend",
            trend_eps=1e-6,
            drift_cooldown_bars=0,
            sigma_ema_period=20,
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        closes = self._sustained_regime_closes(n_tail=60)
        signals = [s for s in (strat.on_candle(c) for c in _candles(closes)) if s is not None]
        assert signals, "trend gate should fire while the regime is building"

    def test_trend_gate_silent_on_flat_sigma(self) -> None:
        """A flat (non-building) sigma stream never satisfies the trend gate."""
        cfg = VolMomentumConfig(
            warmup_candles=5,
            z_entry=0.5,
            mom_gate="trend",
            trend_eps=1e-3,
            drift_cooldown_bars=0,
        )
        strat = VolMomentumStrategy("R_75", 60, config=cfg)
        closes = [100.0 + 0.005 * math.sin(i / 3.0) for i in range(160)]
        signals = [s for s in (strat.on_candle(c) for c in _candles(closes)) if s is not None]
        assert not signals

    def test_invalid_gate_rejected(self) -> None:
        """An unknown gate value is a config error, not a silent fallback."""
        with pytest.raises(ValueError):
            VolMomentumConfig(mom_gate="bogus")


class TestConfig:
    def test_defaults_sane(self) -> None:
        cfg = VolMomentumConfig()
        # Momentum enters earlier than the fade (lower z) and targets wider
        # than it risks (RR > 1) — the opposite geometry of the fade.
        assert cfg.z_entry < 1.0
        assert cfg.target_sigma_mult > cfg.stop_sigma_mult
        assert cfg.max_hold_bars > 0
        assert cfg.drift_cooldown_bars >= 0
        assert cfg.mom_gate == "ratio"
        assert cfg.abs_sigma_mult > 0
        assert cfg.trend_eps > 0

    def test_reward_risk_from_multipliers(self) -> None:
        cfg = VolMomentumConfig(stop_sigma_mult=1.5, target_sigma_mult=3.0)
        # reward/risk = target/stop by construction — momentum wants RR > 1
        assert cfg.target_sigma_mult / cfg.stop_sigma_mult > 1.0
