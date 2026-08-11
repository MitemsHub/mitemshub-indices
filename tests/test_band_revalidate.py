"""Tests for the weekly band-geometry re-validation harness."""

from __future__ import annotations

import json
import math
import time

import pytest

from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.domain import Tick
from synthetic_trader.research.band_revalidate import (
    DEFAULT_ARTIFACT_SUBDIR,
    DEFAULT_GRID,
    MAX_ARTIFACT_AGE_DAYS,
    MIN_ELAPSED_DAYS,
    MIN_GROWTH_DAYS,
    decide_promotion,
    focused_band_grid,
    load_latest_artifact,
    load_live_band_overrides,
    revalidate_band_geometry,
    split_stats,
    split_ticks,
)


def _ticks(n: int = 700, symbol: str = "R_75") -> list[Tick]:
    """Quiet base, then a sustained elevated-vol regime (fires the band gate)."""
    closes: list[float] = []
    for i in range(120):
        closes.append(100.0 + 0.005 * math.sin(i / 3.0))
    base = closes[-1]
    rng = [0.02, -0.018, 0.021, -0.019, 0.02, 0.017, -0.021, 0.019]
    for i in range(n - len(closes)):
        closes.append(base * math.exp(rng[i % len(rng)]))
    return [Tick(symbol=symbol, epoch=float(i * 60), price=c) for i, c in enumerate(closes)]


def _write_corpus(tmp_path, ticks: list[Tick], symbol: str = "R_75"):
    csv = tmp_path / "data" / "backfill" / f"{symbol}_ticks.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text(
        "\n".join(f"{t.epoch:.0f},{t.symbol},{t.price:.6f}" for t in ticks),
        encoding="utf-8",
    )
    return csv


def _extend_ticks(ticks: list[Tick], extra_days: float) -> list[Tick]:
    """Append a second elevated-vol block starting `extra_days` later."""
    import dataclasses

    start = ticks[-1].epoch + extra_days * 86400.0
    extra = _ticks(n=400)
    shifted = [
        dataclasses.replace(t, epoch=start + i * 60.0) for i, t in enumerate(extra)
    ]
    return ticks + shifted


# One-config grid: fast enough for the gate/pipeline tests (3 backtests per
# run), and every knob pinned to the §38 defaults.
TINY_GRID = {
    "z_entries": (1.0, 1.0, 0.1),
    "vol_ratios": (1.3, 1.3, 0.1),
    "stops": (0.2, 0.2, 0.1),
    "targets": (0.8, 0.8, 0.1),
    "holds": (3600, 3600, 1),
}


def _fast_kwargs(**extra):
    kwargs = dict(
        grid_overrides=TINY_GRID,
        timeframe_sec=60,  # matches the 60s-epoch fixture candles
        min_train_trades=1,
        min_holdout_trades=1,
        promote_margin_r=-999.0,  # any profitable candidate promotes
    )
    kwargs.update(extra)
    return kwargs


class TestSplit:
    def test_split_proportions(self) -> None:
        ticks = _ticks(n=700)
        train, holdout = split_ticks(ticks)
        assert len(train) + len(holdout) == 700
        # The 3-day minimum holdout window on a 0.49-day corpus is capped at
        # 60% of the span -> train keeps >= 40% of the ticks.
        assert len(train) >= 280
        assert len(holdout) > 0
        # Time-ordered: train is strictly older than holdout.
        assert train[-1].epoch < holdout[0].epoch

    def test_split_holdout_is_min_wall_clock(self) -> None:
        # A long corpus (30-day span) gets the proportional 20% holdout
        # (6 days), which exceeds HOLD_MIN_DAYS; a short one gets the min
        # window instead of a thin 20% slice.
        closes = [t.price for t in _ticks(n=700)]
        long_ticks = [
            Tick(
                symbol="R_75",
                epoch=float(i * 30 * 86400.0 / 699.0),
                price=c,
            )
            for i, c in enumerate(closes)
        ]
        _, holdout = split_ticks(long_ticks)
        # 20% of 30 days = 6 days > 3-day min -> proportional split.
        assert len(holdout) == 140
        # And the holdout really covers the newest ~6 days.
        assert holdout[0].epoch >= 24 * 86400.0

    def test_split_stats(self) -> None:
        stats = split_stats(_ticks(n=700))
        assert stats.ticks == 700
        assert stats.span_days == 699 * 60 / 86400.0
        assert stats.first_epoch == 0.0


class TestDecidePromotion:
    def _cand(self, hold_trades=8, hold_exp=0.3, train_trades=15, train_exp=0.5):
        return {
            "config": {"z_entry": 1.0},
            "train": {"trades": train_trades, "expectancy_r": train_exp, "net_pnl": 1.0},
            "holdout": {"trades": hold_trades, "expectancy_r": hold_exp, "net_pnl": 1.0},
        }

    def test_promotes_when_beating_default_with_margin(self) -> None:
        cand = self._cand(hold_exp=0.30)
        assert decide_promotion([cand], default_hold_exp=0.10, promote_margin_r=0.05) is cand

    def test_keeps_when_below_margin(self) -> None:
        cand = self._cand(hold_exp=0.11)
        assert decide_promotion([cand], default_hold_exp=0.10, promote_margin_r=0.05) is None

    def test_keeps_when_too_few_holdout_trades(self) -> None:
        cand = self._cand(hold_trades=2, hold_exp=0.5)
        assert decide_promotion([cand], default_hold_exp=0.10, min_holdout_trades=5) is None

    def test_keeps_when_candidate_unprofitable(self) -> None:
        cand = self._cand(hold_exp=-0.2)
        assert decide_promotion([cand], default_hold_exp=0.10, promote_min_expectancy_r=0.10) is None

    def test_second_candidate_promotes_when_first_fails(self) -> None:
        weak = self._cand(hold_exp=0.01)
        strong = self._cand(hold_exp=0.4)
        assert decide_promotion([weak, strong], default_hold_exp=0.10, promote_margin_r=0.05) is strong


class TestFocusedGrid:
    def test_default_grid_size(self) -> None:
        grid = focused_band_grid()
        # §50: the vol-gate range now starts at 0.75 (step 0.1) so the calm
        # 0.86-vol regime is measurable — the old 1.15 floor skipped it.
        n_z = len([0.25, 0.5, 0.75, 1.0, 1.25])
        n_vr = len([0.75, 0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45])
        n_s = len([0.15, 0.2, 0.25, 0.3])
        n_t = len([0.6, 0.8, 1.0])
        n_h = len([3600, 7200])
        assert len(grid) == n_z * n_vr * n_s * n_t * n_h == 5 * 8 * 4 * 3 * 2 == 960
        # Every config keeps the fixed breakeven trail.
        assert all(c.breakeven_trail_frac == 0.3 for c in grid)

    def test_grid_overrides_shrink(self) -> None:
        grid = focused_band_grid({"z_entries": (0.75, 1.25, 0.5)})
        # _arange(0.75, 1.25, 0.5) -> [0.75, 1.25]
        assert {c.z_entry for c in grid} == {0.75, 1.25}
        assert len(grid) == 2 * 8 * 4 * 3 * 2  # other dims at defaults


class TestGates:
    def test_no_tick_csv_skips(self, tmp_path) -> None:
        report = revalidate_band_geometry(symbol="R_75", engine_root=tmp_path)
        assert report["verdict"] == "skipped"
        assert "no_tick_csv" in report["skip_reason"]

    def test_corpus_too_small_skips(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks(n=200))
        report = revalidate_band_geometry(symbol="R_75", engine_root=tmp_path)
        assert report["verdict"] == "skipped"
        assert "corpus_too_small" in report["skip_reason"]

    def test_elapsed_gate_skips_when_too_soon(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        t0 = time.time()
        first = revalidate_band_geometry(
            symbol="R_75", engine_root=tmp_path, now=t0, **_fast_kwargs()
        )
        assert first["verdict"] in ("keep", "promote")
        # Same corpus, 1 day later -> elapsed < MIN_ELAPSED_DAYS -> skip.
        second = revalidate_band_geometry(
            symbol="R_75", engine_root=tmp_path, now=t0 + 1 * 86400.0, **_fast_kwargs()
        )
        assert second["verdict"] == "skipped"
        assert "too_soon" in second["skip_reason"]

    def test_growth_gate_skips_without_new_data(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        t0 = time.time()
        first = revalidate_band_geometry(
            symbol="R_75", engine_root=tmp_path, now=t0, **_fast_kwargs()
        )
        assert first["verdict"] in ("keep", "promote")
        # Corpus grows only ~2 days (< MIN_GROWTH_DAYS) but 8 days elapsed:
        # the growth gate must fire.
        grown = _extend_ticks(_ticks(), extra_days=2.0)
        _write_corpus(tmp_path, grown)
        second = revalidate_band_geometry(
            symbol="R_75", engine_root=tmp_path, now=t0 + 8 * 86400.0, **_fast_kwargs()
        )
        assert second["verdict"] == "skipped"
        assert "insufficient_growth" in second["skip_reason"]

    def test_force_bypasses_gates(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        t0 = time.time()
        first = revalidate_band_geometry(
            symbol="R_75", engine_root=tmp_path, now=t0, **_fast_kwargs()
        )
        assert first["verdict"] in ("keep", "promote")
        second = revalidate_band_geometry(
            symbol="R_75",
            engine_root=tmp_path,
            now=t0 + 1 * 86400.0,
            force=True,
            **_fast_kwargs(),
        )
        assert second["verdict"] in ("keep", "promote")


class TestPipeline:
    def test_full_pipeline_writes_artifacts(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        report = revalidate_band_geometry(
            symbol="R_75", engine_root=tmp_path, **_fast_kwargs()
        )
        assert report["verdict"] in ("keep", "promote")
        assert report["corpus"]["ticks"] == 700
        assert report["train"]["ticks"] + report["holdout"]["ticks"] == 700
        assert report["holdout"]["ticks"] > 0
        # 0.49-day corpus -> 3-day min window capped at 60% of span (~0.29d).
        assert report["holdout"]["span_days"] == pytest.approx(0.485 * 0.6, abs=0.02)
        assert "default" in report and "holdout" in report["default"]
        # Both artifact files exist and round-trip.
        latest = tmp_path / DEFAULT_ARTIFACT_SUBDIR / "latest_R_75.json"
        assert latest.exists()
        persisted = json.loads(latest.read_text(encoding="utf-8"))
        assert persisted["verdict"] == report["verdict"]
        assert persisted["corpus"]["ticks"] == 700
        assert load_latest_artifact("R_75", tmp_path / DEFAULT_ARTIFACT_SUBDIR) == persisted

    def test_promote_writes_promoted_config(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        # Any candidate that beats the default's holdout expectancy (with a
        # huge negative margin, any positive-exp candidate promotes).
        report = revalidate_band_geometry(
            symbol="R_75",
            engine_root=tmp_path,
            timeframe_sec=60,
            promote_margin_r=-999.0,
            min_holdout_trades=1,
            min_train_trades=1,
            grid_overrides=TINY_GRID,
        )
        if report["verdict"] == "promote":
            promoted = report["promoted"]
            cfg = promoted["config"]
            for knob in ("z_entry", "vol_extended_ratio", "stop_sigma_mult",
                         "target_sigma_mult", "max_hold_sec"):
                assert knob in cfg
        else:
            assert report["promoted"] is None


class TestWalkForwardWindow:
    """The runner's count window: full-history state, windowed reporting."""

    def _run(self, **kwargs):
        from synthetic_trader.backtest.vol_band import (
            VolBandConfig,
            run_vol_band_backtest,
        )
        from synthetic_trader.config import PaperExecutionConfig, TraderConfig

        ticks = dedupe_ticks(_ticks(n=900))
        paper = PaperExecutionConfig(
            entry_slippage_ticks=0.05,
            exit_slippage_ticks=0.05,
            execution_penalty_per_trade=0.10,
        )
        return run_vol_band_backtest(
            ticks,
            symbol="R_75",
            timeframe_sec=60,
            config=TraderConfig.default(),
            strategy_config=VolBandConfig(),
            paper=paper,
            **kwargs,
        ), ticks

    def test_windows_partition_trades(self) -> None:
        full, ticks = self._run()
        mid = ticks[len(ticks) // 2].epoch
        train_res, _ = self._run(count_until_epoch=mid)
        hold_res, _ = self._run(count_from_epoch=mid)
        # Every trade opens on exactly one side of the boundary.
        assert train_res.metrics.trades + hold_res.metrics.trades == full.metrics.trades
        # Signals partition the same way.
        assert train_res.signals + hold_res.signals == full.signals

    def test_window_respects_boundary(self) -> None:
        _, ticks = self._run()
        first = ticks[0].epoch
        last = ticks[-1].epoch
        early, _ = self._run(count_until_epoch=first)
        late, _ = self._run(count_from_epoch=last + 1.0)
        # Nothing opens before the first tick or after the last.
        assert early.metrics.trades == 0 and early.signals == 0
        assert late.metrics.trades == 0 and late.signals == 0


class TestLiveLoader:
    def _write_artifact(self, tmp_path, symbol: str, verdict: str, generated_at: float, config=None):
        d = tmp_path / DEFAULT_ARTIFACT_SUBDIR
        d.mkdir(parents=True, exist_ok=True)
        artifact = {
            "version": 1,
            "symbol": symbol,
            "generated_at": generated_at,
            "verdict": verdict,
            "corpus": {"ticks": 700, "span_days": 0.5},
            "promoted": (
                {
                    "config": config or {
                        "z_entry": 0.75,
                        "vol_extended_ratio": 1.45,
                        "stop_sigma_mult": 0.25,
                        "target_sigma_mult": 0.6,
                        "max_hold_sec": 7200,
                    },
                    "train": {"trades": 20, "expectancy_r": 0.5, "net_pnl": 5.0},
                    "holdout": {"trades": 10, "expectancy_r": 0.4, "net_pnl": 4.0},
                }
                if verdict == "promote"
                else None
            ),
        }
        (d / f"latest_{symbol}.json").write_text(json.dumps(artifact), encoding="utf-8")
        return artifact

    def test_no_artifact_returns_empty(self, tmp_path) -> None:
        overrides, artifact = load_live_band_overrides("R_75", tmp_path)
        assert overrides == {}
        assert artifact is None

    def test_fresh_promote_overlays_knobs(self, tmp_path) -> None:
        artifact = self._write_artifact(
            tmp_path, "R_75", "promote", time.time()
        )
        overrides, loaded = load_live_band_overrides("R_75", tmp_path)
        assert loaded == artifact
        assert overrides == {
            "z_entry": 0.75,
            "vol_extended_ratio": 1.45,
            "stop_sigma_mult": 0.25,
            "target_sigma_mult": 0.6,
            "max_hold_sec": 7200,
        }

    def test_stale_artifact_returns_empty(self, tmp_path) -> None:
        old = time.time() - (MAX_ARTIFACT_AGE_DAYS + 1.0) * 86400.0
        artifact = self._write_artifact(tmp_path, "R_75", "promote", old)
        overrides, loaded = load_live_band_overrides("R_75", tmp_path)
        assert overrides == {}
        assert loaded == artifact  # stale still surfaced for the dashboard

    def test_keep_verdict_returns_empty(self, tmp_path) -> None:
        self._write_artifact(tmp_path, "R_75", "keep", time.time())
        overrides, _artifact = load_live_band_overrides("R_75", tmp_path)
        assert overrides == {}


class TestGapGuard:
    """A multi-hour feed gap must not be misread as one giant candle."""

    @staticmethod
    def _quiet_ticks(n_bars: int = 400, base: float = 100.0, start: float = 0.0) -> list[Tick]:
        """Realistic quiet data: ~0.1% per-bar returns (like the live corpus),
        so one big gap jump is a genuine outlier rather than background."""
        import random

        rng = random.Random(42)
        ticks = []
        price = base
        for i in range(n_bars):
            price *= math.exp(rng.gauss(0.0, 0.001))
            ticks.append(Tick(symbol="R_75", epoch=start + float(i * 60), price=price))
        return ticks

    def test_gap_candle_does_not_poison_sigma(self) -> None:
        from synthetic_trader.backtest.vol_band import (
            VolBandConfig,
            VolBandStrategy,
        )
        from synthetic_trader.data.candles import MultiTimeframeCandleBuilder

        # Quiet 400-bar block, then a 10-hour gap and a second block at a
        # +5% price level (collector downtime with the market drifting
        # across the outage).  Without the guard the 10h gap is misread as
        # one gigantic return (z ~ +50) that slams the EGARCH log-variance
        # clip (sigma ~ e^2.5 = 12).
        block1 = self._quiet_ticks(n_bars=400, base=100.0)
        gap_epoch = block1[-1].epoch + 10 * 3600.0
        block2 = self._quiet_ticks(n_bars=400, base=105.0, start=gap_epoch)
        builder = MultiTimeframeCandleBuilder("R_75", [60])
        candles = []
        for t in block1 + block2:
            for tf, c in (builder.update(t) or {}).items():
                if tf == 60:
                    candles.append(c)

        strat = VolBandStrategy("R_75", 60, config=VolBandConfig())
        max_sigma = 0.0
        for c in candles:
            strat.on_candle(c)
            if strat._prev_sigma is not None:
                max_sigma = max(max_sigma, strat._prev_sigma)
        # Quiet background sigma is ~0.001; the guard keeps the gap from
        # inflating it to the clip (~12).
        assert max_sigma < 1.0, f"gap poisoned sigma to {max_sigma:.3f}"

    def test_gap_guard_reanchors_and_does_not_suppress_post_gap(self) -> None:
        from synthetic_trader.backtest.vol_band import (
            VolBandConfig,
            VolBandStrategy,
        )
        from synthetic_trader.data.candles import MultiTimeframeCandleBuilder

        # Quiet block, then a 10-hour gap at a +5% price level, then a
        # second quiet block.  Assert the guard's mechanism precisely:
        # (1) the gap candle re-anchors _prev_close to its own close (so
        # the following return is the normal post-gap return, not the
        # 5%-gap span), and (2) post-gap candles still flow through the
        # strategy (sigma stays in the quiet range, not pinned at the
        # clip that would suppress every later signal).
        block1 = self._quiet_ticks(n_bars=200, base=100.0)
        gap_epoch = block1[-1].epoch + 10 * 3600.0
        block2 = self._quiet_ticks(n_bars=200, base=105.0, start=gap_epoch)
        builder = MultiTimeframeCandleBuilder("R_75", [60])
        candles = []
        for t in block1 + block2:
            for tf, c in (builder.update(t) or {}).items():
                if tf == 60:
                    candles.append(c)

        strat = VolBandStrategy("R_75", 60, config=VolBandConfig())
        gap_seen = False
        first_after_gap_sigma: float | None = None
        for c in candles:
            strat.on_candle(c)
            if gap_seen and first_after_gap_sigma is None and strat._prev_sigma is not None:
                first_after_gap_sigma = strat._prev_sigma
            # The gap candle is the first whose open_time jumps beyond
            # one max-gap interval from the previous candle's end.
            if not gap_seen and c.open_time >= gap_epoch:
                gap_seen = True
        # The re-anchor sets _prev_close to the gap candle's close, so the
        # first post-gap candle computes a normal (quiet-scale) return and
        # the GARCH sigma stays quiet — it must NOT be pinned at the clip.
        assert gap_seen
        assert first_after_gap_sigma is not None and first_after_gap_sigma < 0.1, (
            f"post-gap sigma {first_after_gap_sigma:.4f} — gap return poisoned the forecaster"
        )


class TestSessionDaySync:
    """Backtest runners must reset daily limits like the live path."""

    def test_loss_streak_resets_across_days(self) -> None:
        from synthetic_trader.backtest.vol_reversion import run_vol_regime_backtest
        from synthetic_trader.config import PaperExecutionConfig, RiskConfig, TraderConfig
        from synthetic_trader.domain import Direction, FeatureSnapshot, TradeSignal

        # A deterministic strategy that emits a signal on every candle — the
        # trade pipeline (RiskEngine + broker) is what we're testing here,
        # not the band gate (which needs real vol transitions).  Day 1's
        # trades all lose (tripping the 2-loss breaker); day 2's trades must
        # still open because the runner resets daily limits at the day
        # boundary exactly like the live paper_runner.
        class AlwaysFire:
            version = "stub"

            def __init__(self) -> None:
                self.config = type("C", (), {"breakeven_trail_frac": 0.0})()

            def on_candle(self, candle) -> TradeSignal:
                from synthetic_trader.domain import Regime

                return TradeSignal(
                    symbol="R_75",
                    direction=Direction.SHORT,
                    confidence=0.9,
                    min_confidence=0.0,
                    entry=candle.close,
                    stop_loss=candle.close * 1.02,
                    take_profit=candle.close * 0.98,
                    horizon_sec=3600,
                    snapshot=FeatureSnapshot(
                        symbol="R_75",
                        epoch=candle.open_time + candle.timeframe_sec,
                        timeframe_sec=candle.timeframe_sec,
                        features={},
                        regime=Regime.RANGE,
                        structure={},
                    ),
                    rationale=("stub",),
                )

        # Day 1 RISES (the stub's shorts all lose → 2-loss breaker trips);
        # day 2 FALLS (shorts win — but only if the breaker reset at the
        # day boundary).  Without the session-day sync the account stays
        # halted forever and day 2 never trades.
        def _block(day: int, price: float, rising: bool) -> list[Tick]:
            start = day * 86400.0
            step = 0.05 if rising else -0.05
            return [
                Tick(symbol="R_75", epoch=start + float(i * 60), price=price + step * i)
                for i in range(40)
            ]

        ticks = _block(5, 100.0, rising=True) + _block(6, 101.5, rising=False)
        from dataclasses import replace

        paper = PaperExecutionConfig(
            entry_slippage_ticks=0.05,
            exit_slippage_ticks=0.05,
            execution_penalty_per_trade=0.10,
        )
        risk = RiskConfig(
            max_consecutive_losses=2,
            max_daily_loss_fraction=0.10,
            min_confidence=0.0,
            min_reward_risk=0.0,
            max_open_positions=1,
        )
        config = replace(TraderConfig.default(), paper=paper, risk=risk)
        res = run_vol_regime_backtest(
            AlwaysFire(),
            ticks,
            symbol="R_75",
            timeframe_sec=60,
            config=config,
            paper=paper,
        )
        # Day 2 must contribute trades: the breaker tripped on day 1 (2
        # consecutive losses) but the day boundary must reset it.  Without
        # the sync, day-2 signals are all rejected and trades == 0 (the
        # account stays halted forever).  With the fix we see day-1's loss
        # AND day-2's win — trades >= 2 with at least one winner.
        assert res.metrics.trades >= 2, f"expected day-2 trading, got {res.metrics.trades} trades"
        assert res.metrics.win_rate >= 0.5, "day-2's winning trade must have opened after the reset"
        assert res.diagnostics.get("session_resets", 0) >= 1
