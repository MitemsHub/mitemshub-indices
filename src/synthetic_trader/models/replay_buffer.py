from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class ReplayEntry:
    """A single stored experience: features, label, and sample weight."""

    features: dict[str, float]
    label: int
    sample_weight: float = 1.0


class ExperienceReplayBuffer:
    """Fixed-size replay buffer using reservoir sampling.

    Stores up to ``capacity`` representative past experiences and yields
    mini-batches that can be replayed alongside new data during online model
    updates.  Reservoir sampling ensures every sample seen so far has an
    equal probability of being in the buffer, regardless of stream order.

    Parameters
    ----------        capacity : int
        Maximum number of entries to retain (default 500).
        Old entries are automatically pruned via reservoir sampling
        when this limit is reached, preventing unbounded growth
        during long-running sessions.
    mini_batch_size : int
        Number of samples to replay per update call (default 16).
    replay_ratio : float
        Fraction of each update that comes from replay vs. new data (0-1).
        A value of 0.2 means roughly 20% of gradient steps come from replay.
    """

    def __init__(
        self,
        capacity: int = 500,
        mini_batch_size: int = 16,
        replay_ratio: float = 0.2,
    ) -> None:
        self.capacity = capacity
        self.mini_batch_size = mini_batch_size
        self.replay_ratio = replay_ratio
        self._buffer: list[ReplayEntry] = []
        self._seen: int = 0
        self._rng: random.Random = random.Random()

    # ── Public API ────────────────────────────────────────────────

    def add(self, features: dict[str, float], label: int, sample_weight: float = 1.0) -> None:
        """Add a single experience to the buffer via reservoir sampling."""
        entry = ReplayEntry(features=dict(features), label=label, sample_weight=sample_weight)
        self._seen += 1

        if len(self._buffer) < self.capacity:
            self._buffer.append(entry)
        else:
            # Reservoir sampling: replace with probability capacity / seen
            idx = self._rng.randint(0, self._seen - 1)
            if idx < self.capacity:
                self._buffer[idx] = entry

    def sample_mini_batch(self) -> list[ReplayEntry]:
        """Return a random mini-batch from the buffer.

        Returns fewer entries if the buffer is smaller than ``mini_batch_size``.
        """
        k = min(self.mini_batch_size, len(self._buffer))
        if k == 0:
            return []
        return self._rng.sample(self._buffer, k)

    def replay_updates(self, model: object, n_steps: int | None = None) -> int:
        """Replay mini-batches through the model's ``update`` method.

        Parameters
        ----------
        model : OnlineLogisticModel
            The model to replay against.  Must have an ``update(features, label, sample_weight)`` method.
        n_steps : int | None
            Number of mini-batches to replay.  Each mini-batch contains up to
            ``mini_batch_size`` samples.  If *None*, computed as
            ``max(1, int(replay_ratio * mini_batch_size))``.

        Returns
        -------
        int
            Total number of individual sample updates performed (n_steps × actual_batch_sizes).
        """
        if not self._buffer:
            return 0

        if n_steps is None:
            n_steps = max(1, int(self.replay_ratio * self.mini_batch_size))

        steps_done = 0
        for _ in range(n_steps):
            batch = self.sample_mini_batch()
            for entry in batch:
                model.update(entry.features, entry.label, entry.sample_weight)
                steps_done += 1

        return steps_done

    # ── Persistence ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the buffer to a JSON-compatible dict."""
        return {
            "capacity": self.capacity,
            "mini_batch_size": self.mini_batch_size,
            "replay_ratio": self.replay_ratio,
            "seen": self.total_seen,
            "entries": [
                {"features": e.features, "label": e.label, "sample_weight": e.sample_weight}
                for e in self._buffer
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExperienceReplayBuffer":
        """Restore a buffer from a dict (e.g. parsed from JSON).

        Validates every field and entry before loading.  Corrupt entries
        are skipped with a warning rather than crashing the entire load, so
        a partially-corrupt state file still yields a usable buffer.
        """
        # ── Validate top-level fields ───────────────────────────
        capacity = cls._validate_positive_int(data.get("capacity"), "capacity", default=500)
        mini_batch_size = cls._validate_positive_int(data.get("mini_batch_size"), "mini_batch_size", default=16)
        replay_ratio = cls._validate_float_range(data.get("replay_ratio"), "replay_ratio", 0.0, 1.0, default=0.2)
        seen = cls._validate_non_negative_int(data.get("seen"), "seen", default=0)

        buf = cls(
            capacity=capacity,
            mini_batch_size=mini_batch_size,
            replay_ratio=replay_ratio,
        )
        buf._seen = seen

        # ── Validate and load entries ───────────────────────────
        raw_entries = data.get("entries", [])
        if not isinstance(raw_entries, list):
            logging.warning("[replay_buffer] 'entries' is not a list; skipping all entries")
            return buf

        skipped = 0
        loaded = 0
        MAX_ENTRY_WARNINGS = 3
        for i, e in enumerate(raw_entries):
            entry = ExperienceReplayBuffer._validate_entry(e, index=i)
            if entry is not None:
                buf._buffer.append(entry)
                loaded += 1
            else:
                skipped += 1
                if skipped <= MAX_ENTRY_WARNINGS:
                    logging.warning("[replay_buffer] skipped corrupt entry[%d] during load", i)

        if skipped > 0:
            extra = f" (+{skipped - MAX_ENTRY_WARNINGS} more)" if skipped > MAX_ENTRY_WARNINGS else ""
            logging.warning(
                "[replay_buffer] loaded %d entries, skipped %d corrupt entries%s",
                loaded, skipped, extra,
            )

        return buf

    # ── Validation helpers ──────────────────────────────────────

    @staticmethod
    def _validate_positive_int(value: object, name: str, *, default: int) -> int:
        """Validate that *value* is a positive integer, returning *default* if not."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            logging.warning("[replay_buffer] invalid %s=%r (expected positive int); using default %d", name, value, default)
            return default
        result = int(value)
        if result <= 0:
            logging.warning("[replay_buffer] %s=%d is not positive; using default %d", name, result, default)
            return default
        return result

    @staticmethod
    def _validate_non_negative_int(value: object, name: str, *, default: int) -> int:
        """Validate that *value* is a non-negative integer, returning *default* if not."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            logging.warning("[replay_buffer] invalid %s=%r (expected non-negative int); using default %d", name, value, default)
            return default
        result = int(value)
        if result < 0:
            logging.warning("[replay_buffer] %s=%d is negative; using default %d", name, result, default)
            return default
        return result

    @staticmethod
    def _validate_float_range(
        value: object, name: str, lo: float, hi: float, *, default: float
    ) -> float:
        """Validate that *value* is a float in [lo, hi], returning *default* if not."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            logging.warning("[replay_buffer] invalid %s=%r (expected float in [%.1f, %.1f]); using default %.1f", name, value, lo, hi, default)
            return default
        result = float(value)
        if not math.isfinite(result) or result < lo or result > hi:
            logging.warning("[replay_buffer] %s=%.4f out of range [%.1f, %.1f]; using default %.1f", name, result, lo, hi, default)
            return default
        return result

    @staticmethod
    def _validate_entry(e: object, *, index: int) -> ReplayEntry | None:
        """Validate a single replay entry dict.  Returns a ReplayEntry on success, None on failure."""
        if not isinstance(e, dict):
            logging.warning("[replay_buffer] entry[%d] is not a dict; skipping", index)
            return None

        # Validate features: must be dict[str, float]
        features = e.get("features")
        if not isinstance(features, dict):
            logging.warning("[replay_buffer] entry[%d] has no valid features dict; skipping", index)
            return None
        clean_features: dict[str, float] = {}
        for k, v in features.items():
            if isinstance(k, str) and isinstance(v, (int, float)) and math.isfinite(v):
                clean_features[k] = float(v)
            else:
                logging.warning("[replay_buffer] entry[%d] has non-numeric feature %r=%r; skipping entry", index, k, v)
                return None
        if not clean_features:
            logging.warning("[replay_buffer] entry[%d] has empty features; skipping", index)
            return None

        # Validate label: must be 0 or 1
        label = e.get("label")
        if label not in (0, 1):
            logging.warning("[replay_buffer] entry[%d] has invalid label=%r (must be 0 or 1); skipping", index, label)
            return None

        # Validate sample_weight: must be positive finite (default 1.0)
        sample_weight = e.get("sample_weight", 1.0)
        if not isinstance(sample_weight, (int, float)) or not math.isfinite(sample_weight) or sample_weight <= 0:
            logging.warning("[replay_buffer] entry[%d] has invalid sample_weight=%r; using 1.0", index, sample_weight)
            sample_weight = 1.0

        return ReplayEntry(features=clean_features, label=int(label), sample_weight=float(sample_weight))

    def save(self, path: str | Path) -> None:
        """Persist the buffer to a JSON file."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ExperienceReplayBuffer":
        """Restore a buffer from a JSON file."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ── Helpers ───────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._buffer)

    def __iter__(self) -> Iterator[ReplayEntry]:
        return iter(self._buffer)

    @property
    def total_seen(self) -> int:
        """Total number of samples ever added (before reservoir replacement)."""
        return self._seen

    @property
    def label_distribution(self) -> dict[int, int]:
        """Count of label=0 and label=1 entries currently in the buffer."""
        dist: dict[int, int] = {}
        for e in self._buffer:
            dist[e.label] = dist.get(e.label, 0) + 1
        return dist
