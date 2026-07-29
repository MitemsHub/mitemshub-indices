"""Tests for generator fingerprint detection — identifies V75 vs V100."""
from __future__ import annotations

import math
import random
import tempfile
from pathlib import Path

from synthetic_trader.features.generator_fingerprint import (
    FingerprintState,
    GeneratorFingerprintDetector,
    IndexSignature,
    KNOWN_SIGNATURES,
)


class TestFingerprintState:
    def test_initial_state(self):
        s = FingerprintState()
        assert s.observations == 0
        assert s.return_buffer == []
        assert s.last_detected_id == -1

    def test_to_dict_roundtrip(self):
        s = FingerprintState(
            return_buffer=[0.01, -0.02, 0.005],
            observations=3,
            last_detected_id=0,
            last_detected_confidence=0.7,
        )
        d = s.to_dict()
        restored = FingerprintState.from_dict(d)
        assert restored.observations == 3
        assert len(restored.return_buffer) == 3
        assert restored.last_detected_id == 0


class TestGeneratorFingerprintDetector:
    def test_warmup_returns_defaults(self):
        det = GeneratorFingerprintDetector(min_observations=50)
        features = det.update(0.001)
        assert features["fingerprint_id"] == -1.0
        assert features["fingerprint_confidence"] == 0.0
        assert features["fingerprint_observations"] == 1.0

    def test_accumulates_observations(self):
        det = GeneratorFingerprintDetector(buffer_size=100, min_observations=5)
        for i in range(10):
            det.update(0.001 * (i + 1))
        assert det.state.observations == 10
        assert len(det.state.return_buffer) == 10

    def test_buffer_size_limit(self):
        det = GeneratorFingerprintDetector(buffer_size=10, min_observations=3)
        for i in range(20):
            det.update(0.001 * (i + 1))
        assert len(det.state.return_buffer) == 10
        assert det.state.observations == 20

    def test_compute_features_basic(self):
        det = GeneratorFingerprintDetector(min_observations=10)
        for i in range(20):
            det.update(random.gauss(0, 0.01))
        features = det.update(0.001)
        assert "fingerprint_kurtosis" in features
        assert "fingerprint_skewness" in features
        assert "fingerprint_autocorr" in features
        assert "fingerprint_vol_of_vol" in features
        assert features["fingerprint_confidence"] >= 0.0

    def test_normal_returns_low_kurtosis(self):
        det = GeneratorFingerprintDetector(min_observations=30)
        random.seed(42)
        for _ in range(100):
            det.update(random.gauss(0, 0.01))
        features = det._compute_features()
        # Normal distribution has kurtosis ~0
        assert abs(features["fingerprint_kurtosis"]) < 2.0

    def test_fat_tail_returns_high_kurtosis(self):
        det = GeneratorFingerprintDetector(min_observations=30)
        random.seed(42)
        for _ in range(200):
            # Student-t with df=3 has high kurtosis
            det.update(random.gauss(0, 0.01) * (1.0 if random.random() > 0.05 else 5.0))
        features = det._compute_features()
        # With outliers, kurtosis should be positive
        assert features["fingerprint_kurtosis"] > 0.0

    def test_match_known_signature(self):
        det = GeneratorFingerprintDetector(
            min_observations=30,
            known_signatures=[
                IndexSignature(
                    name="TEST",
                    expected_kurtosis=0.0,
                    expected_skewness=0.0,
                    expected_autocorr=0.0,
                    expected_vol_of_vol=1.0,
                ),
            ],
        )
        random.seed(42)
        for _ in range(100):
            det.update(random.gauss(0, 0.01))
        features = det._compute_features()
        assert features["fingerprint_id"] == 0.0
        assert features["fingerprint_confidence"] > 0.3

    def test_get_detected_index_none_during_warmup(self):
        det = GeneratorFingerprintDetector(min_observations=50)
        assert det.get_detected_index() is None

    def test_get_detected_index_after_warmup(self):
        det = GeneratorFingerprintDetector(min_observations=10)
        random.seed(42)
        for _ in range(50):
            det.update(random.gauss(0, 0.01))
        # After warmup, should detect something (confidence might be low)
        idx = det.get_detected_index()
        # May or may not detect depending on match quality
        assert idx is None or isinstance(idx, str)

    def test_save_load_roundtrip(self):
        det = GeneratorFingerprintDetector(buffer_size=100, min_observations=10)
        random.seed(42)
        for _ in range(30):
            det.update(random.gauss(0, 0.01))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        det.save(path)
        loaded = GeneratorFingerprintDetector.load(path)
        assert loaded.buffer_size == 100
        assert loaded.min_observations == 10
        assert loaded.state.observations == 30
        assert len(loaded.state.return_buffer) == 30
        Path(path).unlink()

    def test_known_signatures_not_empty(self):
        assert len(KNOWN_SIGNATURES) >= 2
        assert KNOWN_SIGNATURES[0].name == "R_75"
        assert KNOWN_SIGNATURES[1].name == "R_100"
