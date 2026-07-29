"""Tests for FeatureImportanceMonitor — SHAP-based drift detection."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from synthetic_trader.models.feature_monitor import (
    FeatureImportanceMonitor,
    FeatureSnapshot,
    DriftAlert,
)


# ── Basic Monitor Tests ──────────────────────────────────────────


class TestMonitorBasics:
    def test_empty_monitor(self) -> None:
        mon = FeatureImportanceMonitor()
        assert mon.observations == 0
        assert mon.alerts == []
        assert mon.flagged_features == set()

    def test_observe_single(self) -> None:
        mon = FeatureImportanceMonitor(min_samples_before_alert=1)
        alerts = mon.observe(
            {"x": 1.0, "y": 2.0},
            {"x": 0.5, "y": -0.3},
        )
        assert mon.observations == 1
        # No alerts with healthy features
        assert len(alerts) == 0

    def test_observe_multiple_accumulates(self) -> None:
        mon = FeatureImportanceMonitor(min_samples_before_alert=10)
        for i in range(20):
            mon.observe({"x": float(i)}, {"x": 0.5})
        assert mon.observations == 20
        assert "x" in mon.get_rolling_importance()

    def test_rolling_importance(self) -> None:
        mon = FeatureImportanceMonitor(window_size=10, min_samples_before_alert=1)
        for _ in range(20):
            mon.observe({"x": 1.0}, {"x": 0.5})
        importance = mon.get_rolling_importance()
        assert "x" in importance
        assert importance["x"] > 0


# ── Threshold Drop Detection ─────────────────────────────────────


class TestThresholdDrop:
    def test_detects_threshold_drop(self) -> None:
        mon = FeatureImportanceMonitor(
            window_size=10,
            importance_floor=0.01,
            min_samples_before_alert=5,
        )
        # First 5 observations with strong feature (contribution = 0.5)
        for _ in range(5):
            mon.observe({"x": 1.0}, {"x": 0.5})
        assert len(mon.alerts) == 0

        # Next 15 observations with near-zero feature
        # After window fills with near-zero, rolling_avg drops below floor
        for _ in range(15):
            mon.observe({"x": 0.0001}, {"x": 0.0001})
        assert len(mon.alerts) > 0
        assert "x" in mon.flagged_features
        assert mon.alerts[0].drift_type == "threshold_drop"

    def test_recovers_when_importance_restores(self) -> None:
        mon = FeatureImportanceMonitor(
            window_size=10,
            importance_floor=0.01,
            min_samples_before_alert=5,
        )
        # Build up importance
        for _ in range(10):
            mon.observe({"x": 1.0}, {"x": 0.5})
        # Drop it
        for _ in range(15):
            mon.observe({"x": 0.0001}, {"x": 0.0001})
        assert "x" in mon.flagged_features

        # Restore it
        for _ in range(15):
            mon.observe({"x": 2.0}, {"x": 0.5})
        assert "x" not in mon.flagged_features


# ── Sign Flip Detection ──────────────────────────────────────────


class TestSignFlip:
    def test_detects_sign_flip(self) -> None:
        mon = FeatureImportanceMonitor(
            window_size=50,
            sign_flip_sensitivity=3,
            min_samples_before_alert=1,
        )
        # Build positive weight history
        for _ in range(10):
            mon.observe({"x": 1.0}, {"x": 0.5})

        # Flip to negative — need enough observations for sensitivity
        for _ in range(5):
            mon.observe({"x": 1.0}, {"x": -0.5})

        flip_alerts = [a for a in mon.alerts if a.drift_type == "sign_flip"]
        assert len(flip_alerts) > 0
        assert flip_alerts[0].feature == "x"

    def test_no_flip_with_same_sign(self) -> None:
        mon = FeatureImportanceMonitor(
            window_size=20,
            sign_flip_sensitivity=3,
            min_samples_before_alert=1,
        )
        for _ in range(20):
            mon.observe({"x": 1.0}, {"x": 0.5})

        flip_alerts = [a for a in mon.alerts if a.drift_type == "sign_flip"]
        assert len(flip_alerts) == 0


# ── Snapshots and Ranking ────────────────────────────────────────


class TestSnapshotsAndRanking:
    def test_get_snapshots(self) -> None:
        mon = FeatureImportanceMonitor(min_samples_before_alert=1)
        for _ in range(5):
            mon.observe({"x": 1.0, "y": 2.0}, {"x": 0.5, "y": 0.3})
        snapshots = mon.get_snapshots({"x": 0.5, "y": 0.3})
        assert len(snapshots) == 2
        names = {s.feature for s in snapshots}
        assert "x" in names
        assert "y" in names

    def test_get_ranked_features(self) -> None:
        mon = FeatureImportanceMonitor(min_samples_before_alert=1)
        for _ in range(10):
            mon.observe({"x": 0.5, "y": 2.0}, {"x": 0.1, "y": 0.9})
        ranked = mon.get_ranked_features({"x": 0.1, "y": 0.9})
        assert len(ranked) == 2
        # y should rank higher (higher weight × value)
        assert ranked[0][0] == "y"
        assert ranked[0][1] > ranked[1][1]

    def test_snapshot_sign_tracking(self) -> None:
        mon = FeatureImportanceMonitor(min_samples_before_alert=1)
        mon.observe({"x": 1.0}, {"x": 0.5})
        mon.observe({"x": 1.0}, {"x": -0.5})
        snapshots = mon.get_snapshots({"x": -0.5})
        pos_snap = [s for s in snapshots if s.feature == "x"]
        assert len(pos_snap) == 1
        assert pos_snap[0].sign == -1  # Latest weight is negative


# ── Persistence Tests ────────────────────────────────────────────


class TestMonitorPersistence:
    def test_save_and_load_roundtrip(self) -> None:
        mon = FeatureImportanceMonitor(
            window_size=50,
            importance_floor=0.02,
            sign_flip_sensitivity=5,
            min_samples_before_alert=10,
        )
        for i in range(30):
            mon.observe({"x": float(i % 10)}, {"x": 0.5 * (1 if i < 20 else -1)})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "monitor.json"
            mon.save(path)

            loaded = FeatureImportanceMonitor.load(path)
            assert loaded.window_size == 50
            assert loaded.importance_floor == 0.02
            assert loaded.observations == 30
            assert "x" in loaded._contribution_history

    def test_save_creates_valid_json(self) -> None:
        mon = FeatureImportanceMonitor()
        mon.observe({"x": 1.0}, {"x": 0.5})
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mon.json"
            mon.save(path)
            data = json.loads(path.read_text())
            assert "observations" in data
            assert "contribution_history" in data


# ── Edge Cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_unknown_features_ignored(self) -> None:
        """Features in model_weights but not in features dict get zero contribution."""
        mon = FeatureImportanceMonitor(min_samples_before_alert=1)
        alerts = mon.observe({}, {"x": 0.5})
        assert mon.observations == 1

    def test_empty_model_weights(self) -> None:
        mon = FeatureImportanceMonitor()
        mon.observe({"x": 1.0}, {})
        assert mon.observations == 1

    def test_multiple_features_independent_tracking(self) -> None:
        mon = FeatureImportanceMonitor(
            window_size=10,
            importance_floor=0.01,
            min_samples_before_alert=5,
        )
        # x stays strong, y drops
        for _ in range(10):
            mon.observe({"x": 1.0, "y": 1.0}, {"x": 0.5, "y": 0.5})
        for _ in range(15):
            mon.observe({"x": 1.0, "y": 0.0001}, {"x": 0.5, "y": 0.0001})
        assert "y" in mon.flagged_features
        assert "x" not in mon.flagged_features
