from __future__ import annotations

import json
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
    ----------
    capacity : int
        Maximum number of entries to retain (default 10 000).
    mini_batch_size : int
        Number of samples to replay per update call (default 16).
    replay_ratio : float
        Fraction of each update that comes from replay vs. new data (0-1).
        A value of 0.2 means roughly 20% of gradient steps come from replay.
    """

    def __init__(
        self,
        capacity: int = 10_000,
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

    def save(self, path: str | Path) -> None:
        """Persist the buffer to a JSON file."""
        payload = {
            "capacity": self.capacity,
            "mini_batch_size": self.mini_batch_size,
            "replay_ratio": self.replay_ratio,
            "seen": self._seen,
            "entries": [
                {"features": e.features, "label": e.label, "sample_weight": e.sample_weight}
                for e in self._buffer
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ExperienceReplayBuffer":
        """Restore a buffer from a JSON file."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        buf = cls(
            capacity=payload["capacity"],
            mini_batch_size=payload["mini_batch_size"],
            replay_ratio=payload["replay_ratio"],
        )
        buf._seen = payload["seen"]
        buf._buffer = [
            ReplayEntry(
                features=e["features"],
                label=e["label"],
                sample_weight=e.get("sample_weight", 1.0),
            )
            for e in payload["entries"]
        ]
        return buf

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
