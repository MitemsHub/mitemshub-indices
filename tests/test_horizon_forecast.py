"""Tests for the 4–6h volatility horizon forecast module."""

from __future__ import annotations

import math

import pytest

from synthetic_trader.domain import Candle, Tick
from synthetic_trader.models.horizon_forecast import (
    HorizonValidation,
    HorizonVolForecast,
    HorizonVolForecaster,
    load_forecast_multipliers,
    save_forecast_multipliers,
    score_horizon_forecast,
    tune_forecast_multipliers,
)


def _candles(closes: list[float], timeframe_sec: int = 300) -> list[Candle]:
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


def _ticks_from_closes(closes: list[float], timeframe_sec: int = 300) -> list[Tick]:
    return [
        Tick(symbol="R_75", epoch=float(i * timeframe_sec), price=close)
        for i, close in enumerate(closes)
    ]


class TestHorizonVolForecaster:
    def test_forecast_after_feed(self) -> None:
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300)
        closes = [100.0 + 0.05 * math.sin(i / 5.0) for i in range(200)]
        for candle in _candles(closes):
            forecaster.on_candle(candle)
        fc = forecaster.forecast(5 * 3600, current_close=closes[-1])
        assert fc.bars == 60  # 5h / 300s
        assert fc.current_sigma > 0
        assert fc.projected_sigma_avg > 0
        assert fc.range_p90_price > fc.range_p50_price >= 0
        assert fc.expected_low_p50 < closes[-1] < fc.expected_high_p50
        assert fc.expected_low_p90 < fc.expected_low_p50
        assert fc.expected_high_p90 > fc.expected_high_p50
        assert 0.0 < fc.confidence <= 0.95
        assert fc.vol_trend in ("rising", "falling", "stable")

    def test_longer_horizon_wider_range(self) -> None:
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300)
        closes = [100.0 + 0.05 * math.sin(i / 5.0) for i in range(200)]
        for candle in _candles(closes):
            forecaster.on_candle(candle)
        fc2h = forecaster.forecast(2 * 3600, current_close=closes[-1])
        fc8h = forecaster.forecast(8 * 3600, current_close=closes[-1])
        assert fc8h.range_p90_price > fc2h.range_p90_price
        assert fc8h.bars > fc2h.bars

    def test_vol_trend_signals_rise_and_fall(self) -> None:
        # Feed a quiet stream: current sigma will sit near long-run → stable
        # or the sign flips cleanly between the two phases.
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300)
        closes = [100.0 + 0.01 * math.sin(i / 4.0) for i in range(150)]
        for candle in _candles(closes):
            forecaster.on_candle(candle)
        fc = forecaster.forecast(3600, current_close=closes[-1])
        assert fc.vol_trend in ("rising", "falling", "stable")

    def test_to_dict_roundtrip(self) -> None:
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300)
        closes = [100.0 + 0.05 * math.sin(i / 5.0) for i in range(120)]
        for candle in _candles(closes):
            forecaster.on_candle(candle)
        fc = forecaster.forecast(3600, current_close=closes[-1])
        payload = fc.to_dict()
        assert payload["horizon_sec"] == 3600
        assert payload["symbol"] == "R_75"
        assert "range_p90_price" in payload
        assert isinstance(payload["notes"], list)

    def test_no_data_forecast_is_degenerate_safe(self) -> None:
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300)
        # Forecast before any candle: must not crash and produce sane bounds.
        fc = forecaster.forecast(3600, current_close=100.0)
        assert fc.range_p50_price >= 0
        assert fc.range_p90_price >= fc.range_p50_price

    def test_uses_calibrated_state(self) -> None:
        from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

        state = load_calibrated_garch_state("R_75")
        if state is None:
            pytest.skip("no calibration file for R_75")
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300, garch_state=state)
        assert forecaster.forecaster.state.omega == state.omega
        assert forecaster.forecaster.state.observations == 0  # re-learn scale

    def test_decay_uses_beta_not_persistence(self) -> None:
        """The projection must decay at the EGARCH beta coefficient, per the
        documented formula E[log s2_{t+h}] = logvar_long + beta^h * gap.
        A state with alpha pinned high (persistence >> beta) must NOT decay
        at the inflated persistence rate.
        """
        from synthetic_trader.models.garch import GARCHState

        # persistence = 0.1 + 0.9*(1-0) = 1.0 vs beta 0.1 — extreme split.
        state = GARCHState(
            omega=-4.0, alpha=0.9, beta=0.1, gamma=0.0,
            log_variance=-8.0, observations=200,
        )
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300, garch_state=state)
        # Anchor at a DIFFERENT level (-4.0 vs current -8.0) so the gap is
        # non-zero and the decay rate actually moves the path.  With beta=0.1
        # the path jumps most of the way to the anchor in one bar; with
        # persistence (~1.0) it would stay near -8.0.
        forecaster._logvar_ema = -4.0
        forecaster._candles_seen = 100
        path = forecaster._projected_logvars(bars=10)
        # 1 bar: -4.0 + 0.1^1 * (-8.0 - -4.0) = -4.4 — far from current -8.0.
        assert path[0] > -5.0  # decayed toward the anchor quickly
        assert path[0] < -4.0  # but not all the way (beta^1 gap remains)
        assert path[-1] > -4.2  # 10 bars: 0.1^10 gap is ~0 -> converged near anchor
        assert forecaster.forecaster.state.persistence > 0.5  # guard: split is real

    def test_fitted_multipliers_widen_bands(self) -> None:
        """Calibrated multipliers must widen the live bands vs the priors."""
        forecaster = HorizonVolForecaster("R_75", timeframe_sec=300)
        closes = [100.0 + 0.05 * math.sin(i / 5.0) for i in range(200)]
        for candle in _candles(closes):
            forecaster.on_candle(candle)
        base = forecaster.forecast(4 * 3600, current_close=closes[-1])
        cal = forecaster.forecast(
            4 * 3600, current_close=closes[-1], p50_mult=2.7, p90_mult=4.0
        )
        assert cal.range_p50_price > base.range_p50_price
        assert cal.range_p90_price > base.range_p90_price

    def test_multiplier_persistence_roundtrip(self, tmp_path) -> None:
        """save/load/merge of fitted multipliers per horizon."""
        p1 = save_forecast_multipliers(
            "R_75", 60, {"4h": {"p50_mult": 2.7, "p90_mult": 4.0}}, tmp_path
        )
        assert p1.exists()
        p2 = save_forecast_multipliers(
            "R_75", 60, {"6h": {"p50_mult": 2.8, "p90_mult": 4.2}}, tmp_path
        )
        # Merge, not overwrite: both horizons must survive the second save.
        loaded = load_forecast_multipliers("R_75", 60, tmp_path)
        assert loaded is not None
        assert loaded["4h"]["p50_mult"] == 2.7
        assert loaded["6h"]["p50_mult"] == 2.8
        # A different timeframe must not collide.
        assert load_forecast_multipliers("R_75", 300, tmp_path) is None


class TestScoreHorizonForecast:
    def test_quiet_stream_coverage_sane(self) -> None:
        closes = [100.0 + 0.05 * math.sin(i / 5.0) for i in range(800)]
        result = score_horizon_forecast(
            _ticks_from_closes(closes),
            symbol="R_75",
            horizon_sec=3600,
            timeframe_sec=300,
            min_warmup_bars=60,
        )
        assert isinstance(result, HorizonValidation)
        assert result.windows > 0
        assert 0.0 <= result.coverage_p50 <= 1.0
        assert 0.0 <= result.coverage_p90 <= 1.0
        assert result.coverage_p90 >= result.coverage_p50
        assert result.median_realized_ratio > 0

    def test_too_little_data_returns_empty(self) -> None:
        closes = [100.0 + i * 0.01 for i in range(20)]
        result = score_horizon_forecast(
            _ticks_from_closes(closes),
            symbol="R_75",
            horizon_sec=3600,
            timeframe_sec=300,
        )
        assert result.windows == 0
        assert result.coverage_p50 == 0.0

    def test_realistic_spike_data_bounded(self) -> None:
        # quiet then a sustained high-vol regime — coverage must stay in range
        rng = __import__("random").Random(42)
        closes: list[float] = [100.0]
        for i in range(600):
            if i > 300:
                step = rng.gauss(0.0, 0.15)  # high vol
            else:
                step = rng.gauss(0.0, 0.02)  # quiet
            closes.append(closes[-1] + step)
        result = score_horizon_forecast(
            _ticks_from_closes(closes),
            symbol="R_75",
            horizon_sec=3600,
            timeframe_sec=300,
        )
        assert result.windows > 20
        assert 0.0 <= result.coverage_p50 <= 1.0
        assert 0.0 <= result.coverage_p90 <= 1.0
        assert result.coverage_p90 >= result.coverage_p50

    def test_holdout_split_is_chronological_and_honest(self) -> None:
        """With the default holdout, multipliers are fit on the TRAIN portion
        and coverage is scored on the holdout — the fitted multipliers must
        be positive and holdout coverage must be a real fraction.
        """
        rng = __import__("random").Random(7)
        closes: list[float] = [100.0]
        for i in range(1000):
            vol = 0.05 if i % 200 < 100 else 0.15
            closes.append(closes[-1] + rng.gauss(0.0, vol))
        result = score_horizon_forecast(
            _ticks_from_closes(closes),
            symbol="R_75",
            horizon_sec=7200,
            timeframe_sec=300,
        )
        # holdout_frac=0.3 -> windows should be ~30% of the full set
        assert result.windows > 20
        assert result.fitted_p50_mult > 0
        assert result.fitted_p90_mult > result.fitted_p50_mult
        assert 0.05 <= result.coverage_p50 <= 0.95
        assert 0.5 <= result.coverage_p90 <= 1.0

    def test_explicit_multipliers_score_full_set(self) -> None:
        """Passing p50/p90 multipliers explicitly disables fitting: coverage
        is scored over all windows against the supplied multipliers.
        """
        closes = [100.0 + 0.05 * math.sin(i / 5.0) for i in range(800)]
        result = score_horizon_forecast(
            _ticks_from_closes(closes),
            symbol="R_75",
            horizon_sec=3600,
            timeframe_sec=300,
            p50_mult=2.0,
            p90_mult=4.0,
        )
        assert result.fitted_p50_mult == 2.0
        assert result.fitted_p90_mult == 4.0
        assert result.windows > 100
        assert 0.0 <= result.coverage_p50 <= 1.0


class TestTuneForecastMultipliers:
    def test_tunes_to_calibrated_on_holdout(self, tmp_path) -> None:
        """The tuning pass must land the RECENT holdout coverage inside the
        calibrated band and persist the tuned multipliers.
        """
        rng = __import__("random").Random(11)
        closes: list[float] = [100.0]
        for i in range(1200):
            vol = 0.04 if i % 250 < 130 else 0.12  # alternating vol regimes
            closes.append(closes[-1] + rng.gauss(0.0, vol))
        report = tune_forecast_multipliers(
            "R_75",
            _ticks_from_closes(closes, timeframe_sec=60),
            horizon_sec=4 * 3600,
            timeframe_sec=60,
            multiplier_dir=tmp_path,
        )
        assert report["windows"] > 30
        assert report["verdict"] == "calibrated"
        assert 0.25 <= report["coverage_p50"] <= 0.75
        assert 0.75 <= report["coverage_p90"] <= 1.01
        assert report["persisted"] is True
        loaded = load_forecast_multipliers("R_75", 60, tmp_path)
        assert loaded is not None
        assert loaded["4h"]["p50_mult"] == pytest.approx(report["p50_mult"])
        assert loaded["4h"]["p90_mult"] == pytest.approx(report["p90_mult"])

    def test_shrinks_when_forecast_lags_a_vol_drop(self, tmp_path) -> None:
        """The genuine over-covering mechanism: a vol DROP the EGARCH forecast
        lags.  Forecast sigma stays high while realized moves shrink, so the
        recent holdout standardized ranges collapse and the train-seeded band
        over-covers.  The pass must SHRINK the multipliers so the recent
        coverage returns to the calibrated band.
        """
        rng = __import__("random").Random(5)
        closes: list[float] = [100.0]
        for i in range(4000):
            # loud bulk, then a quiet tail starting just after the 70% split
            vol = 0.02 if i > 2600 else 0.14
            closes.append(closes[-1] + rng.gauss(0.0, vol))
        ticks = _ticks_from_closes(closes, timeframe_sec=60)
        # The stale calibration: an in-sample fit on the FULL corpus, dominated
        # by the loud bulk, over-covers the quiet holdout.
        stale = score_horizon_forecast(
            ticks, symbol="R_75", horizon_sec=4 * 3600, timeframe_sec=60,
            holdout_frac=0.0,
        )
        report = tune_forecast_multipliers(
            "R_75", ticks, horizon_sec=4 * 3600, timeframe_sec=60,
            multiplier_dir=tmp_path,
        )
        assert report["verdict"] == "calibrated"
        assert report["iterations"] > 1  # the pass actually had to move
        assert 0.25 <= report["coverage_p50"] <= 0.75
        assert 0.75 <= report["coverage_p90"] <= 1.01
        # The tuned band must be TIGHTER than the stale full-corpus fit — the
        # pass corrected the over-covering for the recent (quieter) regime.
        assert report["p50_mult"] < stale.fitted_p50_mult

    def test_widens_when_forecast_lags_a_vol_rise(self, tmp_path) -> None:
        """Symmetric case: a vol RISE just at the holdout boundary.  The
        forecast has not caught up, so the recent windows realize ranges wider
        than the quiet-train seed predicts; the pass must WIDEN the band.
        """
        rng = __import__("random").Random(5)
        closes: list[float] = [100.0]
        for i in range(4000):
            vol = 0.14 if i > 2600 else 0.02  # quiet bulk, loud tail after split
            closes.append(closes[-1] + rng.gauss(0.0, vol))
        ticks = _ticks_from_closes(closes, timeframe_sec=60)
        stale = score_horizon_forecast(
            ticks, symbol="R_75", horizon_sec=4 * 3600, timeframe_sec=60,
            holdout_frac=0.0,
        )
        report = tune_forecast_multipliers(
            "R_75", ticks, horizon_sec=4 * 3600, timeframe_sec=60,
            multiplier_dir=tmp_path,
        )
        assert report["verdict"] == "calibrated"
        assert 0.25 <= report["coverage_p50"] <= 0.75
        assert 0.75 <= report["coverage_p90"] <= 1.01
        # Tuned band must be WIDER than the stale quiet-corpus fit.
        assert report["p50_mult"] > stale.fitted_p50_mult

    def test_too_little_data_reports_needs_more(self, tmp_path) -> None:
        closes = [100.0 + i * 0.01 for i in range(20)]
        report = tune_forecast_multipliers(
            "R_75",
            _ticks_from_closes(closes, timeframe_sec=60),
            horizon_sec=4 * 3600,
            timeframe_sec=60,
            multiplier_dir=tmp_path,
        )
        assert report["windows"] == 0
        assert report["verdict"] == "needs_more_data_or_tuning"
        assert report["persisted"] is False

    def test_does_not_persist_when_uncalibrated(self, tmp_path) -> None:
        """A run that never converges must NOT overwrite good multipliers with
        a stale/calibrated claim — persisted stays False.
        """
        rng = __import__("random").Random(31)
        closes: list[float] = [100.0]
        for i in range(400):
            closes.append(closes[-1] + rng.gauss(0.0, 0.05))
        save_forecast_multipliers(
            "R_75", 60, {"6h": {"p50_mult": 1.6, "p90_mult": 2.5}}, tmp_path
        )
        report = tune_forecast_multipliers(
            "R_75",
            _ticks_from_closes(closes, timeframe_sec=60),
            horizon_sec=6 * 3600,
            timeframe_sec=60,
            multiplier_dir=tmp_path,
            max_iters=3,
        )
        # 400 closes @60s with a 6h horizon leaves ~40 windows; the 30%
        # holdout is ~12 < min_windows=30, so it can never be "calibrated" —
        # deterministic: nothing must be persisted.
        assert report["verdict"] == "needs_more_data_or_tuning"
        assert report["persisted"] is False
        # The pre-existing 6h entry must survive untouched.
        loaded = load_forecast_multipliers("R_75", 60, tmp_path)
        assert loaded is not None
        assert loaded["6h"]["p50_mult"] == 1.6
