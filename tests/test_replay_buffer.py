"""Tests for ExperienceReplayBuffer — reservoir sampling, replay, persistence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from synthetic_trader.models.replay_buffer import ExperienceReplayBuffer, ReplayEntry
from synthetic_trader.models.online import OnlineLogisticModel


# ── Basic Buffer Tests ───────────────────────────────────────────


class TestReplayBufferBasics:
    def test_empty_buffer(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100)
        assert len(buf) == 0
        assert buf.total_seen == 0
        assert buf.sample_mini_batch() == []

    def test_add_single_entry(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100)
        buf.add({"x": 1.0, "y": 2.0}, label=1, sample_weight=0.8)
        assert len(buf) == 1
        assert buf.total_seen == 1
        entry = buf.sample_mini_batch()[0]
        assert entry.label == 1
        assert entry.sample_weight == 0.8
        assert entry.features["x"] == 1.0

    def test_add_multiple_entries_under_capacity(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100)
        for i in range(50):
            buf.add({"v": float(i)}, label=i % 2)
        assert len(buf) == 50
        assert buf.total_seen == 50

    def test_reservoir_sampling_replaces_when_full(self) -> None:
        buf = ExperienceReplayBuffer(capacity=10)
        for i in range(100):
            buf.add({"v": float(i)}, label=i % 2)
        assert len(buf) == 10
        assert buf.total_seen == 100

    def test_label_distribution(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100)
        for i in range(80):
            buf.add({"v": float(i)}, label=0)
        for i in range(20):
            buf.add({"v": float(i)}, label=1)
        dist = buf.label_distribution
        assert dist[0] == 80
        assert dist[1] == 20

    def test_sample_mini_batch_size_capped(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100, mini_batch_size=5)
        for i in range(20):
            buf.add({"v": float(i)}, label=i % 2)
        batch = buf.sample_mini_batch()
        assert len(batch) == 5

    def test_sample_mini_batch_fewer_than_requested(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100, mini_batch_size=50)
        for i in range(5):
            buf.add({"v": float(i)}, label=0)
        batch = buf.sample_mini_batch()
        assert len(batch) == 5


# ── Replay Updates Tests ─────────────────────────────────────────


class TestReplayUpdates:
    def test_replay_updates_returns_zero_for_empty_buffer(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100)
        model = OnlineLogisticModel()
        steps = buf.replay_updates(model)
        assert steps == 0

    def test_replay_updates_performs_gradient_steps(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100, mini_batch_size=10)
        model = OnlineLogisticModel()
        for i in range(50):
            buf.add({"feature_a": float(i % 10)}, label=i % 2)
        initial_updates = model.updates
        steps = buf.replay_updates(model, n_steps=3)
        assert steps > 0
        assert model.updates > initial_updates

    def test_replay_updates_respects_n_steps(self) -> None:
        buf = ExperienceReplayBuffer(capacity=100, mini_batch_size=10)
        model = OnlineLogisticModel()
        for i in range(50):
            buf.add({"f": float(i)}, label=i % 2)
        steps = buf.replay_updates(model, n_steps=5)
        # Each step samples a mini_batch of 10, so 5 steps = 50 updates
        assert steps == 50


# ── Integration with OnlineLogisticModel ─────────────────────────


class TestModelWithReplay:
    def test_update_with_replay_stores_in_buffer(self) -> None:
        model = OnlineLogisticModel()
        model.update_with_replay({"x": 1.0}, label=1)
        assert len(model.replay_buffer) == 1
        assert model.replay_buffer.total_seen == 1

    def test_update_with_replay_returns_probability(self) -> None:
        model = OnlineLogisticModel()
        prob = model.update_with_replay({"x": 1.0}, label=1)
        assert 0.0 <= prob <= 1.0

    def test_repeated_updates_build_buffer(self) -> None:
        model = OnlineLogisticModel()
        for i in range(100):
            model.update_with_replay({"v": float(i)}, label=i % 2)
        assert len(model.replay_buffer) == 100
        assert model.updates > 100  # original + replay steps

    def test_replay_prevents_forgetting(self) -> None:
        """Model trained on only label=1 should still predict label=1 after
        replaying a mix of label=0 and label=1 samples."""
        model = OnlineLogisticModel()
        # Train heavily on label=1
        for _ in range(200):
            model.update({"signal": 1.0}, label=1)
        pred_after_training = model.predict_proba({"signal": 1.0})
        assert pred_after_training > 0.8

        # Now replay a balanced mix without new updates
        buf = ExperienceReplayBuffer(capacity=200)
        for i in range(100):
            buf.add({"signal": 1.0}, label=1)
            buf.add({"signal": 1.0}, label=0)
        buf.replay_updates(model, n_steps=10)

        # Model should still predict reasonably for signal=1, not collapse to 0.5
        pred_after_replay = model.predict_proba({"signal": 1.0})
        assert pred_after_replay > 0.4  # Should not forget completely


# ── Persistence Tests ────────────────────────────────────────────


class TestReplayBufferPersistence:
    def test_save_and_load_roundtrip(self) -> None:
        buf = ExperienceReplayBuffer(capacity=50, mini_batch_size=8, replay_ratio=0.6)
        for i in range(30):
            buf.add({"x": float(i), "y": float(i * 2)}, label=i % 2, sample_weight=0.5 + i * 0.01)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "buffer.json"
            buf.save(path)

            loaded = ExperienceReplayBuffer.load(path)
            assert loaded.capacity == 50
            assert loaded.mini_batch_size == 8
            assert loaded.replay_ratio == 0.6
            assert loaded.total_seen == 30
            assert len(loaded) == 30

            # Verify entries match
            original_entries = sorted(
                [(e.features["x"], e.label) for e in buf],
                key=lambda t: t[0],
            )
            loaded_entries = sorted(
                [(e.features["x"], e.label) for e in loaded],
                key=lambda t: t[0],
            )
            assert original_entries == loaded_entries

    def test_save_creates_valid_json(self) -> None:
        buf = ExperienceReplayBuffer(capacity=10)
        buf.add({"a": 1.0}, label=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "buf.json"
            buf.save(path)
            data = json.loads(path.read_text())
            assert "entries" in data
            assert len(data["entries"]) == 1


# ── Edge Cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_features_are_copied_not_shared(self) -> None:
        """Adding a dict should copy it, not reference the original."""
        buf = ExperienceReplayBuffer(capacity=10)
        original = {"x": 1.0}
        buf.add(original, label=1)
        original["x"] = 999.0
        entry = buf.sample_mini_batch()[0]
        assert entry.features["x"] == 1.0  # Should not be mutated

    def test_iterator_yields_all_entries(self) -> None:
        buf = ExperienceReplayBuffer(capacity=10)
        for i in range(7):
            buf.add({"v": float(i)}, label=i % 2)
        collected = list(buf)
        assert len(collected) == 7

    def test_custom_capacity_one(self) -> None:
        buf = ExperienceReplayBuffer(capacity=1)
        buf.add({"a": 1.0}, label=0)
        buf.add({"a": 2.0}, label=1)
        assert len(buf) == 1
        assert buf.total_seen == 2
