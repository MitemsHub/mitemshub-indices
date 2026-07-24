from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path


from synthetic_trader.config import ModelConfig
from synthetic_trader.features.indicators import clamp


@dataclass
class OnlineLogisticModel:
    config: ModelConfig = field(default_factory=ModelConfig)
    weights: dict[str, float] = field(default_factory=dict)
    bias: float = 0.0
    updates: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return f"{self.config.version}.{self.updates}"

    def predict_proba(self, features: dict[str, float]) -> float:
        score = self.bias
        for key, value in self._normalized(features).items():
            score += self.weights.get(key, 0.0) * value
        raw = 1.0 / (1.0 + math.exp(-clamp(score, -30.0, 30.0)))
        return clamp(raw, 0.08, 0.92)

    def update(self, features: dict[str, float], label: int, sample_weight: float = 1.0) -> float:
        if label not in (0, 1):
            raise ValueError("label must be 0 or 1")

        normalized = self._normalized(features)
        probability = self.predict_proba(features)
        error = float(label) - probability
        lr = self.config.learning_rate * sample_weight

        self.bias += lr * error
        for key, value in normalized.items():
            old_weight = self.weights.get(key, 0.0)
            regularized = old_weight * (1.0 - lr * self.config.l2)
            self.weights[key] = regularized + lr * error * value

        self.updates += 1
        return probability

    def save(self, path: str | Path, metadata: dict[str, str] | None = None) -> None:
        merged_metadata = {**self.metadata, **{str(key): str(value) for key, value in (metadata or {}).items()}}
        payload = {
            "config": asdict(self.config),
            "weights": self.weights,
            "bias": self.bias,
            "updates": self.updates,
            "metadata": merged_metadata,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.metadata = merged_metadata

    @classmethod
    def load(cls, path: str | Path) -> "OnlineLogisticModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            config=ModelConfig(**payload["config"]),
            weights={str(key): float(value) for key, value in payload["weights"].items()},
            bias=float(payload["bias"]),
            updates=int(payload["updates"]),
            metadata={str(key): str(value) for key, value in payload.get("metadata", {}).items()},
        )

    def clone(self) -> "OnlineLogisticModel":
        return type(self)(
            config=self.config,
            weights=dict(self.weights),
            bias=self.bias,
            updates=self.updates,
            metadata=dict(self.metadata),
        )

    def _normalized(self, features: dict[str, float]) -> dict[str, float]:
        clean: dict[str, float] = {}
        for key, value in features.items():
            if not isinstance(value, (int, float)):
                continue
            if math.isnan(value) or math.isinf(value):
                continue
            clean[key] = clamp(float(value), -self.config.feature_clip, self.config.feature_clip)
        return clean

