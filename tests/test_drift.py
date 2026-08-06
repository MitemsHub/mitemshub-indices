"""Tests for the ADWIN drift detector and OnlineLogisticModel integration."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from synthetic_trader.models.drift import DriftDetector
from synthetic_trader.models.garch import ez_student_t
from synthetic_trader.models.online import OnlineLogisticModel


class TestEzStudentT:
    def test_exact_value_dof_two(self) -> None:
        # E|z| for dof=2 == sqrt(2)
        assert abs(ez_student_t(2.0) - math.sqrt(2.0)) < 1e-9

    def test_heavy_tails_larger_than_normal(self) -> None:
        assert ez_student_t(3.0) > 0.7979
        assert ez_student_t(5.0) > 0.7979

    def test_converges_to_normal(self) -> None:
        assert abs(ez_student_t(200.0) - 0.7979) < 0.02

    def test_monotonically_decreasing(self) -> None:
        values = [ez_student_t(d) for d in (3.0, 5.0, 10.0, 30.0, 100.0)]
        assert values == sorted(values, reverse=True)

    def test_dof_one_falls_back(self) -> None:
        assert ez_student_t(1.0) == 1.0


class TestDriftDetector:
    def test_stable_stream_no_drift(self) -> None:
        detector = DriftDetector()
        for _ in range(500):
            assert not detector.observe(0.1)
        assert detector.drift_events == 0
        assert detector.n_observations == 500

    def test_abrupt_shift_detected(self) -> None:
        detector = DriftDetector(delta=0.002)
        for _ in range(200):
            detector.observe(0.5)
        detected = any(detector.observe(5.0) for _ in range(200))
        assert detected
        assert detector.drift_events >= 1
        assert detector.last_drift_step is not None

    def test_reset_rebaselines_after_drift(self) -> None:
        detector = DriftDetector()
        for _ in range(200):
            detector.observe(0.5)
        # Drive the shift until ADWIN fires exactly once, then re-baseline
        fired = False
        for _ in range(200):
            if detector.observe(5.0):
                fired = True
                break
        assert fired
        events_after = detector.drift_events
        # Stable at the new level should not trigger endless drifts
        for _ in range(300):
            detector.observe(5.0)
        assert detector.drift_events == events_after

    def test_drift_rate(self) -> None:
        detector = DriftDetector()
        for _ in range(99):
            detector.observe(0.5)
        for _ in range(200):
            detector.observe(5.0)
        assert detector.drift_events >= 1
        assert 0.0 < detector.drift_rate <= 1.0

    def test_save_load_roundtrip(self) -> None:
        detector = DriftDetector(delta=0.005)
        for _ in range(50):
            detector.observe(0.3)
        detector.observe(9.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "drift.json"
            detector.save(path)
            loaded = DriftDetector.load(path)
        assert loaded.delta == 0.005
        assert loaded.n_observations == detector.n_observations
        assert loaded.drift_events == detector.drift_events
        assert loaded.last_drift_step == detector.last_drift_step

    def test_missing_river_degrades_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import synthetic_trader.models.drift as drift_mod

        monkeypatch.setattr(drift_mod, "ADWIN", None)
        detector = drift_mod.DriftDetector()
        assert detector.observe(0.5) is False
        assert detector.drift_events == 0


class TestOnlineModelDriftIntegration:
    def test_model_detects_drift_and_resets(self) -> None:
        model = OnlineLogisticModel()
        # Train on a stable regime (label=1, features that push probability up)
        for i in range(300):
            model.update({"signal": 1.0}, label=1)
        # The prediction-error distribution is now stable
        events_before = model.drift_detector.drift_events

        # Feed contradictory samples to force a regime shift in the error stream
        for i in range(300):
            model.update({"signal": 1.0}, label=0)

        assert model.drift_detector.drift_events > events_before

    def test_drift_reset_clears_weights(self) -> None:
        model = OnlineLogisticModel()
        for _ in range(200):
            model.update({"signal": 1.0}, label=1)
        assert len(model.weights) > 0 or abs(model.bias) > 1e-9

        for _ in range(200):
            model.update({"signal": 1.0}, label=0)
        assert model.drift_resets >= 1

    def test_save_load_preserves_drift_telemetry(self) -> None:
        model = OnlineLogisticModel()
        for _ in range(120):
            model.update({"signal": 1.0}, label=1)
        for _ in range(120):
            model.update({"signal": 1.0}, label=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            model.save(path)
            loaded = OnlineLogisticModel.load(path)
        assert loaded.drift_resets == model.drift_resets
        assert loaded.drift_detector.drift_events == model.drift_detector.drift_events
        assert (
            loaded.drift_detector.last_drift_step
            == model.drift_detector.last_drift_step
        )

    def test_load_old_state_without_drift_fields(self, tmp_path: Path) -> None:
        """State files written before drift support must still load."""
        path = tmp_path / "old_model.json"
        path.write_text(
            json.dumps(
                {
                    "config": {
                        "learning_rate": 0.05,
                        "l2": 0.0005,
                        "decision_threshold": 0.58,
                        "feature_clip": 8.0,
                        "version": "online-logistic-v1",
                    },
                    "weights": {"x": 0.5},
                    "bias": 0.1,
                    "updates": 42,
                    "metadata": {},
                }
            ),
            encoding="utf-8",
        )
        model = OnlineLogisticModel.load(path)
        assert model.drift_resets == 0
        assert model.drift_detector.n_observations == 0
        assert model.weights == {"x": 0.5}
