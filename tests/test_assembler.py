"""Regression tests for the feature assembler's online state warm-up.

The assembler holds module-level GARCH / session / fingerprint caches that
must warm up from a cold start on every run.  A guard bug froze the GARCH
forecaster at observation 0 (the first ``update()`` was never allowed), so
``garch_z_score`` stayed 0.0 in every snapshot — dead weight in the model's
feature vector.  These tests lock the warm-up behavior.
"""
from synthetic_trader.features import assembler
from synthetic_trader.features.assembler import build_snapshot, clear_assembler_caches
from tests.test_decision_engine import trending_candles


def test_build_snapshot_garch_forecaster_warms_up_from_cold() -> None:
    """Feeding bars from observation 1 must grow the GARCH observations and
    produce a live ``garch_z_score`` — not the frozen 0.0 of a forecaster
    that never updates."""
    clear_assembler_caches()
    candles = trending_candles(symbol="R_75", count=60)
    last = None
    for i in range(5, len(candles) + 1):
        last = build_snapshot(
            symbol="R_75",
            timeframe_sec=300,
            candles=candles[:i],
        )
    assert last is not None
    # The feature must be real after warm-up (the old guard returned 0.0
    # forever because update() was never called).
    assert abs(last.features.get("garch_z_score", 0.0)) > 1e-9
    # The forecaster's observation counter must actually have advanced —
    # this is the exact state the old guard never allowed to move.
    forecaster = assembler._garch_forecasters["R_75"]
    assert forecaster.state.observations >= 10


def test_build_snapshot_garch_state_resets_with_cache_clear() -> None:
    """A fresh run must start the forecaster cold again (per-run warm-up
    state, not process state)."""
    clear_assembler_caches()
    candles = trending_candles(symbol="R_75", count=30)
    for i in range(5, len(candles) + 1):
        build_snapshot(symbol="R_75", timeframe_sec=300, candles=candles[:i])
    warm = assembler._garch_forecasters["R_75"].state.observations
    assert warm > 0

    clear_assembler_caches()
    assert "R_75" not in assembler._garch_forecasters
    build_snapshot(symbol="R_75", timeframe_sec=300, candles=candles[:20])
    assert assembler._garch_forecasters["R_75"].state.observations < warm
