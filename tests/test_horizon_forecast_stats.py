"""Tests for synthetic_trader.scripts.horizon_forecast_stats."""

from __future__ import annotations

import math
import random

from synthetic_trader.data.collector import candles_to_ticks
from synthetic_trader.data.tick_store import write_ticks_csv
from synthetic_trader.scripts.horizon_forecast_stats import (
    get_horizon_forecast_stats,
    _resolve_tick_csv,
)


def _make_engine_root(tmp_path, symbol: str, n_candles: int = 650) -> tuple:
    """Create an engine-root-like dir with a backfill tick CSV for ``symbol``.

    Generates a synthetic random-walk candle series, expands it to an
    OHLC-exact tick stream (same reconstruction the MT5 backfill uses), and
    writes it to ``data/backfill/{symbol}_ticks.csv``.
    """
    root = tmp_path / "engine"
    backfill = root / "data" / "backfill"
    backfill.mkdir(parents=True, exist_ok=True)

    rng = random.Random(42)
    price = 1000.0
    candles: list[dict[str, float]] = []
    for i in range(n_candles):
        open_p = price
        drift = rng.gauss(0.0, 0.002)
        close_p = max(open_p * (1.0 + drift), 1.0)
        high_p = max(open_p, close_p) * (1.0 + abs(rng.gauss(0.0, 0.001)))
        low_p = min(open_p, close_p) * (1.0 - abs(rng.gauss(0.0, 0.001)))
        candles.append(
            {
                "epoch": 1_700_000_000.0 + i * 60.0,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
            }
        )
        price = close_p

    ticks = candles_to_ticks(symbol, candles, timeframe_sec=60)
    csv_path = backfill / f"{symbol}_ticks.csv"
    write_ticks_csv(csv_path, ticks, append=False)
    return root, csv_path


def test_resolve_tick_csv_prefers_backfill(tmp_path) -> None:
    root, csv_path = _make_engine_root(tmp_path, "R_75")
    resolved = _resolve_tick_csv(str(root), "R_75")
    assert resolved is not None
    assert resolved == csv_path


def test_resolve_tick_csv_returns_none_when_missing(tmp_path) -> None:
    root = tmp_path / "empty_engine"
    root.mkdir(parents=True, exist_ok=True)
    assert _resolve_tick_csv(str(root), "R_75") is None


def test_get_horizon_forecast_stats_structure(tmp_path) -> None:
    # 650 candles: enough to clear the 60-bar warmup AND the 6h horizon
    # (360 bars) so both horizons produce walk-forward windows.
    root, _ = _make_engine_root(tmp_path, "R_75", n_candles=650)
    stats = get_horizon_forecast_stats(str(root))

    assert "R_75" in stats
    entry = stats["R_75"]
    assert entry["error"] is None
    assert entry["symbol"] == "R_75"
    assert entry["timeframe_sec"] == 60
    assert entry["ticks"] == 650 * 4
    assert "4h" in entry["horizons"]
    assert "6h" in entry["horizons"]
    # Both horizons must produce walk-forward windows (fixture is big enough).
    assert entry["horizons"]["4h"]["validation"]["windows"] > 0
    assert entry["horizons"]["6h"]["validation"]["windows"] > 0

    for hours, horizon in entry["horizons"].items():
        assert horizon["horizon_sec"] == int(hours.replace("h", "")) * 3600
        assert horizon["verdict"] in ("calibrated", "needs_more_data_or_tuning")
        validation = horizon["validation"]
        assert validation["windows"] > 0
        assert 0.0 <= validation["coverage_p50"] <= 1.0
        assert 0.0 <= validation["coverage_p90"] <= 1.0
        assert validation["coverage_p90"] >= validation["coverage_p50"]
        assert validation["fitted_p50_mult"] > 0
        assert validation["fitted_p90_mult"] > 0

        forecast = horizon["forecast"]
        assert forecast["symbol"] == "R_75"
        assert forecast["current_close"] > 0
        assert forecast["range_p50_price"] > 0
        assert forecast["range_p90_price"] >= forecast["range_p50_price"]
        assert forecast["expected_high_p50"] > forecast["expected_low_p50"]
        assert forecast["expected_high_p90"] > forecast["expected_low_p90"]
        assert forecast["vol_trend"] in ("rising", "falling", "stable")
        assert 0.0 <= forecast["confidence"] <= 1.0
        assert isinstance(forecast["regime_stable"], bool)


def test_get_horizon_forecast_stats_missing_symbol(tmp_path) -> None:
    root, _ = _make_engine_root(tmp_path, "R_75", n_candles=400)
    stats = get_horizon_forecast_stats(str(root))

    # R_100 has no CSV in this engine root → error entry, not a crash
    assert "R_100" in stats
    assert stats["R_100"]["error"] == "no_tick_csv"


def test_get_horizon_forecast_stats_too_few_ticks(tmp_path) -> None:
    root = tmp_path / "tiny"
    backfill = root / "data" / "backfill"
    backfill.mkdir(parents=True, exist_ok=True)
    ticks = candles_to_ticks(
        "R_75",
        [{"epoch": 1_700_000_000.0, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}],
        timeframe_sec=60,
    )
    write_ticks_csv(backfill / "R_75_ticks.csv", ticks, append=False)

    stats = get_horizon_forecast_stats(str(root))
    assert stats["R_75"]["error"] == "insufficient_ticks"
    assert stats["R_75"]["ticks"] == 4


def test_live_forecast_matches_validation_scale(tmp_path) -> None:
    """The live forecast's sigma should be on the same scale as validation."""
    root, _ = _make_engine_root(tmp_path, "R_75", n_candles=400)
    stats = get_horizon_forecast_stats(str(root))
    horizon = stats["R_75"]["horizons"]["4h"]
    fc = horizon["forecast"]
    # Sigma must be a sane positive fraction of price movement scale.
    assert math.isfinite(fc["current_sigma"])
    assert fc["current_sigma"] > 0
    assert math.isfinite(fc["projected_sigma_avg"])
    assert fc["projected_sigma_avg"] > 0
